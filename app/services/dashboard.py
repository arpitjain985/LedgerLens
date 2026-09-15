"""
Financial dashboard (Section 12): aggregates transaction data into the
summary figures and breakdowns a CA or business owner would want at a
glance. Pure aggregation over already-classified/risk-scored transactions —
no new extraction or ML here, just totals.
"""
import json
from collections import defaultdict
from typing import Dict

from sqlalchemy.orm import Session

from app.models import Transaction, Statement


def get_dashboard(db: Session, firm_id: str) -> dict:
    transactions = (
        db.query(Transaction)
        .join(Statement, Transaction.statement_id == Statement.id)
        .filter(Statement.firm_id == firm_id)
        .all()
    )

    total_credits = sum(t.amount for t in transactions if t.txn_type == "credit")
    total_debits = sum(t.amount for t in transactions if t.txn_type == "debit")
    reconciled_count = sum(1 for t in transactions if t.reconciled)
    unmatched_count = sum(1 for t in transactions if not t.reconciled)
    suspicious_count = sum(1 for t in transactions if (t.risk_level or "Low") in ("High", "Critical"))

    expense_by_category: Dict[str, float] = defaultdict(float)
    for t in transactions:
        if t.txn_type == "debit":
            head = t.corrected_ledger_head or t.predicted_ledger_head or "Unclassified"
            expense_by_category[head] += t.amount

    top_categories = sorted(expense_by_category.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return {
        "transaction_count": len(transactions),
        "total_credits": round(total_credits, 2),
        "total_debits": round(total_debits, 2),
        "net_cash_flow": round(total_credits - total_debits, 2),
        "reconciled_count": reconciled_count,
        "unmatched_count": unmatched_count,
        "suspicious_count": suspicious_count,
        "expense_by_category": [{"category": c, "amount": round(a, 2)} for c, a in top_categories],
    }
