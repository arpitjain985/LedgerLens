"""
Base interface all bank-specific parsers implement, and the normalized
transaction schema every parser must produce regardless of source bank.

This is the contract from Section 5 of the V2 spec: whatever bank a
statement comes from, it must end up in this same shape before it ever
reaches the database or the classifier.
"""
from dataclasses import dataclass, asdict
from typing import Optional, List, Protocol
import re


@dataclass
class NormalizedTransaction:
    date: Optional[str]
    description: str
    debit: Optional[float]      # None if this row is a credit
    credit: Optional[float]     # None if this row is a debit
    amount: float                # always positive, magnitude of the transaction
    transaction_type: str        # "debit" | "credit" | "unknown"
    balance: Optional[float] = None
    reference_number: Optional[str] = None
    payment_mode: Optional[str] = None   # "UPI" | "NEFT" | "IMPS" | "CHEQUE" | "ATM" | "CASH" | "CARD" | None
    vendor: Optional[str] = None         # best-effort extraction, refined later by classifier

    def to_dict(self) -> dict:
        return asdict(self)


class BankParser(Protocol):
    """Every per-bank parser adapter implements this interface."""
    bank_code: str
    bank_display_name: str

    def matches(self, text_sample: str) -> bool:
        """Returns True if this parser recognizes the statement's format."""
        ...

    def parse(self, file_path: str) -> List[NormalizedTransaction]:
        """Extracts and normalizes transactions from the statement."""
        ...


# --- Shared helpers used by multiple bank adapters ---

DATE_PATTERN = re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b")
AMOUNT_PATTERN = re.compile(r"[\d,]+\.\d{2}")
REFERENCE_PATTERN = re.compile(r"\b([A-Z]{2,6}\d{6,20})\b")

PAYMENT_MODE_KEYWORDS = {
    "UPI": ["upi"],
    "NEFT": ["neft"],
    "IMPS": ["imps"],
    "RTGS": ["rtgs"],
    "CHEQUE": ["cheque", "chq"],
    "ATM": ["atm"],
    "CASH": ["cash deposit", "cash withdrawal", "cash "],
    "CARD": ["pos ", "card txn", "debit card", "credit card"],
}


def detect_payment_mode(text: str) -> Optional[str]:
    text_lower = text.lower()
    for mode, keywords in PAYMENT_MODE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return mode
    return None


def guess_txn_type(text: str) -> str:
    text_lower = text.lower()
    if any(k in text_lower for k in ["dr", "debit", "withdrawal"]):
        return "debit"
    if any(k in text_lower for k in ["cr", "credit", "deposit"]):
        return "credit"
    return "unknown"


def extract_reference(text: str) -> Optional[str]:
    match = REFERENCE_PATTERN.search(text)
    return match.group(1) if match else None
