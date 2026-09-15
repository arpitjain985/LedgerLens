"""
Recurring transaction detection (Section 26): identifies vendor payments
that repeat at a roughly regular interval and similar amount — rent, EMI,
salary, subscriptions, insurance premiums, regular supplier payments.

Honest scope note: with a single month's statement, there usually isn't
enough history to detect a real recurrence pattern (you need at least 2
occurrences to compute an interval at all, and 3+ to trust it). This
function works across ALL of a firm's stored transactions (across every
statement uploaded so far), not just the current one — so it gets more
useful the more statements a firm uploads over time, which is the honest
tradeoff of this feature rather than something fixable in a single-file
MVP scope.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from sqlalchemy.orm import Session

from app.models import Transaction, Statement
from app.services.vendor_extraction import normalize_vendor_name

MIN_OCCURRENCES_TO_FLAG = 2
AMOUNT_SIMILARITY_TOLERANCE = 0.15  # amounts within 15% of each other count as "similar"
INTERVAL_TOLERANCE_DAYS = 5          # +/- 5 days around the average interval still counts as regular

DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y")


def detect_recurring_transactions(db: Session, firm_id: str) -> List[dict]:
    transactions = (
        db.query(Transaction)
        .join(Statement, Transaction.statement_id == Statement.id)
        .filter(Statement.firm_id == firm_id, Transaction.vendor.isnot(None))
        .all()
    )

    grouped: Dict[str, List[Transaction]] = defaultdict(list)
    for txn in transactions:
        grouped[normalize_vendor_name(txn.vendor)].append(txn)

    results = []
    for normalized_name, txns in grouped.items():
        if len(txns) < MIN_OCCURRENCES_TO_FLAG:
            continue

        parsed = sorted(
            [(t, _parse_date(t.txn_date)) for t in txns if _parse_date(t.txn_date)],
            key=lambda pair: pair[1],
        )
        if len(parsed) < MIN_OCCURRENCES_TO_FLAG:
            continue

        if not _amounts_are_similar([t.amount for t, _ in parsed]):
            continue

        intervals_days = [
            (parsed[i][1] - parsed[i - 1][1]).days
            for i in range(1, len(parsed))
        ]
        avg_interval = sum(intervals_days) / len(intervals_days)

        if not _intervals_are_regular(intervals_days, avg_interval):
            continue

        last_date = parsed[-1][1]
        next_expected = last_date + timedelta(days=round(avg_interval))

        results.append({
            "vendor_name": parsed[-1][0].vendor,
            "occurrences": len(parsed),
            "average_amount": round(sum(t.amount for t, _ in parsed) / len(parsed), 2),
            "average_interval_days": round(avg_interval),
            "frequency_label": _label_frequency(avg_interval),
            "last_payment_date": parsed[-1][0].txn_date,
            "next_expected_date": next_expected.strftime("%d-%m-%Y"),
        })

    return sorted(results, key=lambda r: r["occurrences"], reverse=True)


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _amounts_are_similar(amounts: List[float]) -> bool:
    if not amounts:
        return False
    avg = sum(amounts) / len(amounts)
    if avg == 0:
        return False
    return all(abs(a - avg) / avg <= AMOUNT_SIMILARITY_TOLERANCE for a in amounts)


def _intervals_are_regular(intervals_days: List[int], avg_interval: float) -> bool:
    return all(abs(d - avg_interval) <= INTERVAL_TOLERANCE_DAYS for d in intervals_days)


def _label_frequency(avg_interval_days: float) -> str:
    if avg_interval_days <= 9:
        return "Weekly"
    if avg_interval_days <= 16:
        return "Bi-weekly"
    if avg_interval_days <= 45:
        return "Monthly"
    if avg_interval_days <= 100:
        return "Quarterly"
    return "Annual"
