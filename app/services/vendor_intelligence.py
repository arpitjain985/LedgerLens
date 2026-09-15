"""
Vendor intelligence (Section 25): builds/updates aggregated vendor profiles
from transaction data. Called after classification, once vendor names have
been extracted onto each transaction.

Design: profiles are rebuilt from scratch per statement processed, using
UPSERT-by-normalized-name semantics — this keeps the logic simple (no
incremental-update bugs) at the cost of re-scanning all of a firm's
transactions each time. Fine for MVP data volumes; the documented upgrade
path if this becomes a bottleneck is incremental aggregation instead of
full rebuild.
"""
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models import Transaction, Statement, Vendor
from app.services.vendor_extraction import normalize_vendor_name

NEW_VENDOR_MAX_TRANSACTIONS = 1  # a vendor with only 1 transaction ever seen is "new"


def update_vendor_profiles(db: Session, firm_id: str) -> Dict[str, bool]:
    """
    Rebuilds vendor profiles for a firm from all of its transactions with a
    non-null vendor field. Returns {normalized_vendor_name: is_new_vendor}
    for use by risk_engine.py's new-vendor risk factor.
    """
    transactions = (
        db.query(Transaction)
        .join(Statement, Transaction.statement_id == Statement.id)
        .filter(Statement.firm_id == firm_id, Transaction.vendor.isnot(None))
        .all()
    )

    grouped: Dict[str, List[Transaction]] = {}
    for txn in transactions:
        key = normalize_vendor_name(txn.vendor)
        grouped.setdefault(key, []).append(txn)

    vendor_first_seen: Dict[str, bool] = {}

    for normalized_name, txns in grouped.items():
        amounts = [t.amount for t in txns]
        dates = sorted(t.txn_date for t in txns if t.txn_date)

        vendor = (
            db.query(Vendor)
            .filter(Vendor.firm_id == firm_id, Vendor.normalized_name == normalized_name)
            .first()
        )
        if not vendor:
            vendor = Vendor(firm_id=firm_id, normalized_name=normalized_name, display_name=txns[0].vendor)
            db.add(vendor)

        vendor.display_name = txns[0].vendor  # keep most recent formatting
        vendor.total_payments = sum(amounts)
        vendor.transaction_count = len(txns)
        vendor.average_payment = sum(amounts) / len(amounts)
        vendor.highest_payment = max(amounts)
        vendor.lowest_payment = min(amounts)
        vendor.first_payment_date = dates[0] if dates else None
        vendor.last_payment_date = dates[-1] if dates else None
        vendor.is_new_vendor = len(txns) <= NEW_VENDOR_MAX_TRANSACTIONS

        vendor_score, vendor_reasons = _compute_vendor_risk(vendor, amounts)
        vendor.risk_score = vendor_score
        import json
        vendor.risk_reasons = json.dumps(vendor_reasons)

        vendor_first_seen[normalized_name] = vendor.is_new_vendor

    db.commit()
    return vendor_first_seen


def _compute_vendor_risk(vendor: Vendor, amounts: List[float]) -> tuple:
    """Lightweight vendor-level risk signal, separate from per-transaction risk_engine.py."""
    score = 0
    reasons = []

    if vendor.is_new_vendor:
        score += 20
        reasons.append("New vendor with limited transaction history")

    if len(amounts) >= 2:
        recent, previous = amounts[-1], amounts[-2]
        if previous > 0 and recent > previous * 3:
            score += 25
            reasons.append("Most recent payment is more than 3x the previous payment to this vendor")

    return min(score, 100), reasons


def get_vendor_summary(db: Session, firm_id: str) -> List[dict]:
    vendors = db.query(Vendor).filter(Vendor.firm_id == firm_id).order_by(Vendor.total_payments.desc()).all()
    return [
        {
            "vendor_name": v.display_name,
            "total_payments": v.total_payments,
            "transaction_count": v.transaction_count,
            "average_payment": round(v.average_payment, 2),
            "highest_payment": v.highest_payment,
            "lowest_payment": v.lowest_payment,
            "first_payment_date": v.first_payment_date,
            "last_payment_date": v.last_payment_date,
            "is_new_vendor": v.is_new_vendor,
            "risk_score": v.risk_score,
        }
        for v in vendors
    ]
