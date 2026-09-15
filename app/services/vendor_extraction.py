"""
Extracts a best-effort vendor/counterparty name from a raw transaction
description, and normalizes it for matching/grouping.

This is deliberately a heuristic, not an ML model — bank transaction
descriptions are short, inconsistent, and full of bank-specific noise
(reference numbers, payment mode codes, branch codes), so a handful of
targeted regex rules gets most of the real signal without needing training
data we don't have.
"""
import re
from typing import Optional

# Common prefixes that precede the actual party name in Indian bank
# transaction descriptions.
VENDOR_PREFIX_PATTERN = re.compile(
    r"\b(?:TO|FROM|PAYMENT TO|PAID TO|BY|VIA|UPI|RECEIVED (?:FROM|UPI))\s+([A-Z][A-Z&.\s]{2,40}?)(?:\s+(?:INV|REF|TXN|UPI|NEFT|IMPS|RTGS|-|\d)|\s*$)",
    re.IGNORECASE,
)

# Noise tokens to strip out even when found inside an otherwise-good match.
NOISE_TOKENS = {
    "SELF", "ACCOUNT", "A/C", "BRANCH", "LTD", "LIMITED", "PVT",
    "TRANSACTION", "PAYMENT", "TRANSFER",
}


def extract_vendor(description: str) -> Optional[str]:
    """
    Returns a cleaned-up vendor name, or None if nothing confident could be
    extracted (e.g. "ATM WITHDRAWAL SELF" has no external vendor).
    """
    match = VENDOR_PREFIX_PATTERN.search(description)
    if not match:
        return None

    candidate = match.group(1).strip()
    candidate = re.sub(r"\s+", " ", candidate)

    words = [w for w in candidate.split() if w.upper() not in NOISE_TOKENS]
    if not words:
        return None

    cleaned = " ".join(words).strip(" .-")
    if len(cleaned) < 3:
        return None

    return cleaned.title()


def normalize_vendor_name(vendor_name: str) -> str:
    """
    Normalizes a vendor name for grouping/matching purposes — lowercase,
    collapsed whitespace, punctuation stripped. Two descriptions that refer
    to the same real-world vendor with slightly different formatting should
    normalize to the same key.
    """
    normalized = vendor_name.lower().strip()
    normalized = re.sub(r"[.,&\-]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def normalize_description(description: str) -> str:
    """
    Normalizes a full transaction description for correction-matching
    (Section 8's flywheel). Strips dates, amounts, and reference numbers so
    that "03-07-2026 PAYMENT TO RAJ ELECTRICALS INV-2201 6,750.00 DR" and
    "05-07-2026 PAYMENT TO RAJ ELECTRICALS INV-2214 8,900.00 DR" — same
    vendor, different invoice/amount/date — normalize close enough to match
    on the vendor phrase, which is what should actually drive the ledger
    head, not the specific invoice number or amount.
    """
    text = description.upper()
    text = re.sub(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", "", text)   # dates
    text = re.sub(r"[\d,]+\.\d{2}", "", text)                    # amounts
    text = re.sub(r"\b[A-Z]{2,6}\d{6,20}\b", "", text)           # reference numbers
    text = re.sub(r"\b(?:INV|REF|TXN)[-#]?\d+\b", "", text)      # invoice/ref codes
    text = re.sub(r"\s+", " ", text)
    return text.strip()
