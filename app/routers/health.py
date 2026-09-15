"""
GET /health — reports the status of each subsystem individually, per
Section 37. LLM is explicitly reported as "optional" since the app must
function fully without it (Section 3, zero-cost/local-first principle).
"""
from fastapi import APIRouter
from sqlalchemy import text

from app.database import SessionLocal
from app.config import LLM_PROVIDER, GROQ_API_KEY, OPENAI_API_KEY, OCR_ENGINE

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    checks = {
        "backend": _check_backend(),
        "database": _check_database(),
        "ocr": _check_ocr(),
        "embedding_model": _check_embedding_model(),
        "llm": _check_llm(),
    }
    overall_ok = all(c["status"] == "ok" or c["status"] == "optional" for c in checks.values())
    return {
        "overall_status": "ok" if overall_ok else "degraded",
        "checks": checks,
    }


def _check_backend() -> dict:
    return {"status": "ok", "detail": "API is responding"}


def _check_database() -> dict:
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "ok", "detail": "Database connection successful"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def _check_ocr() -> dict:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return {"status": "ok", "detail": f"Tesseract available (engine={OCR_ENGINE})"}
    except Exception as e:
        return {"status": "error", "detail": f"Tesseract not available: {e}"}


def _check_embedding_model() -> dict:
    # Uses find_spec instead of a real import -- importing sentence_transformers
    # pulls in torch, which has a genuinely slow cold-import cost (several
    # seconds first time, confirmed during testing). A health check should
    # never have unpredictable multi-second latency, so this only confirms
    # the package is installed without paying that cost. The model itself
    # still loads lazily on first actual classification (Section 34).
    import importlib.util
    if importlib.util.find_spec("sentence_transformers") is not None:
        return {"status": "ok", "detail": "sentence-transformers installed (model loads lazily on first use)"}
    return {"status": "error", "detail": "sentence-transformers not installed"}


def _check_llm() -> dict:
    if LLM_PROVIDER == "none":
        return {"status": "optional", "detail": "LLM fallback disabled (LLM_PROVIDER=none) -- app works fully without it"}
    if LLM_PROVIDER == "groq" and not GROQ_API_KEY:
        return {"status": "optional", "detail": "GROQ_API_KEY not set -- LLM fallback will be skipped, embeddings-only classification still works"}
    if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
        return {"status": "optional", "detail": "OPENAI_API_KEY not set -- LLM fallback will be skipped, embeddings-only classification still works"}
    return {"status": "optional", "detail": f"LLM fallback configured (provider={LLM_PROVIDER})"}
