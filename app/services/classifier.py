"""
Classifies a transaction description into a ledger head.

V2 architecture — three tiers, checked in order (Sections 7 + 8):
  1. Correction memory: has a human corrected a transaction with this same
     normalized description before? If so, use that instantly — no model
     call needed, and it's exactly right by construction (Section 8's data
     flywheel).
  2. Embedding similarity against app/data/ledger_heads.json (free, fast,
     local). V2 change: now compares against EVERY example phrase per head
     (not just an averaged embedding) and reports which specific example
     phrase drove the match — this is what makes the result explainable
     (Section 7) instead of just a bare confidence number.
  3. If still ambiguous, escalate to an LLM call (Groq by default) for a
     structured classification WITH a stated reason.

This keeps LLM API costs low: most transactions are either previously
corrected or obvious on embeddings alone.

V2 change (Section 34, model management): sentence-transformers is imported
lazily, inside _get_embedder(), instead of at module load time — the app
starts instantly even before the ML dependency is installed/downloaded.
"""
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from sqlalchemy.orm import Session

from app.config import (
    EMBEDDING_MODEL_NAME,
    CLASSIFICATION_CONFIDENCE_THRESHOLD,
    LEDGER_HEADS_PATH,
    LLM_PROVIDER,
)
from app.services.vendor_extraction import normalize_description


@dataclass
class ClassificationResult:
    ledger_head: str
    confidence: float
    method: str      # "correction_memory" | "embedding" | "llm_fallback"
    reason: str       # human-readable explanation (Section 7)


@lru_cache(maxsize=1)
def _load_ledger_heads():
    with open(LEDGER_HEADS_PATH) as f:
        data = json.load(f)["ledger_heads"]
    return data


@lru_cache(maxsize=1)
def _get_embedder():
    # V2 fix: bound the network timeout for the model download/lookup.
    # Without this, huggingface_hub has no hard timeout on its own and will
    # hang for minutes on a slow/unreachable connection instead of failing
    # fast — confirmed during testing (a call with no internet access hung
    # 40+ seconds with no error). This makes a real failure surface in
    # ~10 seconds as a clean ClassificationModelUnavailableError (Section 23)
    # instead of an indefinite hang, without affecting normal cached/local use.
    import os
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "10")

    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


@lru_cache(maxsize=1)
def _get_example_embeddings():
    """
    Returns a flat list of (head_code, example_text, embedding) — one entry
    PER EXAMPLE PHRASE, not averaged per head. Comparing against individual
    examples (rather than one blended head embedding) is both more accurate
    and gives us a specific phrase to cite as the reason for a match.
    """
    embedder = _get_embedder()
    heads = _load_ledger_heads()
    entries = []
    for head in heads:
        embeddings = embedder.encode(head["examples"], convert_to_tensor=True)
        for example_text, embedding in zip(head["examples"], embeddings):
            entries.append((head["code"], example_text, embedding))
    return entries


def classify_transaction(
    description: str,
    db: Optional[Session] = None,
    firm_id: Optional[str] = None,
) -> ClassificationResult:
    normalized = normalize_description(description)

    # --- Tier 1: correction memory (Section 8 data flywheel) ---
    if db is not None and firm_id is not None:
        remembered = _check_correction_memory(db, firm_id, normalized)
        if remembered:
            return ClassificationResult(
                ledger_head=remembered,
                confidence=1.0,
                method="correction_memory",
                reason="Matches a transaction you previously corrected to this ledger head.",
            )

    # --- Tier 2: embedding similarity against individual example phrases ---
    from sentence_transformers import util  # lazy import, see module docstring

    embedder = _get_embedder()
    examples = _get_example_embeddings()
    txn_embedding = embedder.encode(description, convert_to_tensor=True)

    best_code, best_score, best_example = None, -1.0, None
    for code, example_text, example_emb in examples:
        score = float(util.cos_sim(txn_embedding, example_emb))
        if score > best_score:
            best_code, best_score, best_example = code, score, example_text

    if best_score >= CLASSIFICATION_CONFIDENCE_THRESHOLD:
        return ClassificationResult(
            ledger_head=best_code,
            confidence=round(best_score, 3),
            method="embedding",
            reason=f'Description closely matches the pattern "{best_example}" for this category.',
        )

    # --- Tier 3: LLM fallback for ambiguous cases ---
    llm_result = _classify_with_llm(description)
    if llm_result:
        ledger_head, confidence, llm_reason = llm_result
        return ClassificationResult(
            ledger_head=ledger_head,
            confidence=confidence,
            method="llm_fallback",
            reason=llm_reason,
        )

    # No LLM configured / call failed — return the best embedding guess
    # anyway, clearly flagged as low-confidence for human review.
    return ClassificationResult(
        ledger_head=best_code,
        confidence=round(best_score, 3),
        method="embedding",
        reason=f'Best available match (low confidence) — closest pattern was "{best_example}".',
    )


def _check_correction_memory(db: Session, firm_id: str, normalized_description: str) -> Optional[str]:
    from app.models import Correction
    correction = (
        db.query(Correction)
        .filter(Correction.firm_id == firm_id, Correction.normalized_description == normalized_description)
        .order_by(Correction.created_at.desc())
        .first()
    )
    return correction.corrected_ledger_head if correction else None


def _classify_with_llm(description: str) -> Optional[tuple]:
    if LLM_PROVIDER == "none":
        return None

    heads = _load_ledger_heads()
    head_codes = [h["code"] for h in heads]

    prompt = (
        "You are classifying a bank transaction description into exactly one "
        f"ledger head code from this list: {head_codes}.\n\n"
        f'Transaction description: "{description}"\n\n'
        "Respond ONLY with valid JSON in this exact format, nothing else:\n"
        '{"ledger_head": "<one code from the list>", "confidence": <float 0-1>, '
        '"reason": "<one short sentence explaining why>"}'
    )

    try:
        if LLM_PROVIDER == "groq":
            return _call_groq(prompt)
        elif LLM_PROVIDER == "openai":
            return _call_openai(prompt)
    except Exception as e:
        print(f"[classifier] LLM fallback failed: {e}")
        return None

    return None


def _call_groq(prompt: str) -> Optional[tuple]:
    from groq import Groq
    from app.config import GROQ_API_KEY, GROQ_MODEL

    if not GROQ_API_KEY:
        return None

    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    result = json.loads(response.choices[0].message.content)
    return result["ledger_head"], float(result.get("confidence", 0.6)), result.get("reason", "Classified by LLM fallback.")


def _call_openai(prompt: str) -> Optional[tuple]:
    from openai import OpenAI
    from app.config import OPENAI_API_KEY, OPENAI_MODEL

    if not OPENAI_API_KEY:
        return None

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    result = json.loads(response.choices[0].message.content)
    return result["ledger_head"], float(result.get("confidence", 0.6)), result.get("reason", "Classified by LLM fallback.")
