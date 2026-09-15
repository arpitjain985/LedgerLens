"""
Financial search (Section 14): natural-language filtering over transactions,
e.g. "Show payments above Rs 1 lakh to new vendors". Same grounding
principle as copilot.py -- extracts concrete filter criteria from the query
text via regex, then runs a real SQL-backed filter. No LLM involved at all
for this one, since it's pure structured filtering, not conversational.
"""
import re
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import Transaction, Statement, Vendor
from app.services.vendor_extraction import normalize_vendor_name

AMOUNT_PATTERN = re.compile(
    r"(?:above|over|more than|greater than|at least)\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|crore|k)?",
    re.IGNORECASE,
)
MULTIPLIERS = {"k": 1_000, "lakh": 100_000, "crore": 10_000_000}


def search_transactions(db: Session, firm_id: str, query: str) -> dict:
    """
    Parses supported filter criteria out of a natural-language query and
    returns matching transactions. Unrecognized filters are simply ignored
    (not treated as errors) -- e.g. "show payments" with no amount/vendor
    filter returns everything, which is honest: it didn't find a specific
    filter to narrow by, so it isn't inventing one.
    """
    q = query.lower()
    filters_applied = []

    query_obj = (
        db.query(Transaction)
        .join(Statement, Transaction.statement_id == Statement.id)
        .filter(Statement.firm_id == firm_id)
    )

    min_amount = _extract_amount_threshold(q)
    if min_amount is not None:
        query_obj = query_obj.filter(Transaction.amount >= min_amount)
        filters_applied.append(f"amount >= {min_amount:,.0f}")

    if "new vendor" in q or "new supplier" in q:
        new_vendor_names = {
            v.normalized_name for v in db.query(Vendor).filter(Vendor.firm_id == firm_id, Vendor.is_new_vendor == True).all()
        }
        transactions = query_obj.all()
        transactions = [t for t in transactions if t.vendor and normalize_vendor_name(t.vendor) in new_vendor_names]
        filters_applied.append("vendor is new")
    else:
        transactions = query_obj.all()

    if "debit" in q or "expense" in q or "payment" in q:
        transactions = [t for t in transactions if t.txn_type == "debit"]
        filters_applied.append("type = debit")
    elif "credit" in q or "receipt" in q:
        transactions = [t for t in transactions if t.txn_type == "credit"]
        filters_applied.append("type = credit")

    return {
        "query": query,
        "filters_applied": filters_applied,
        "result_count": len(transactions),
        "transactions": [_txn_summary(t) for t in transactions],
    }


def _extract_amount_threshold(q: str) -> Optional[float]:
    match = AMOUNT_PATTERN.search(q)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").lower()
    return value * MULTIPLIERS.get(unit, 1)


def _txn_summary(t: Transaction) -> dict:
    return {
        "id": t.id, "date": t.txn_date, "description": t.description,
        "amount": t.amount, "txn_type": t.txn_type, "vendor": t.vendor,
        "predicted_ledger_head": t.predicted_ledger_head,
    }
