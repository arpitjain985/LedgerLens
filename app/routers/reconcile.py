from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Statement, Transaction
from app.schemas import ReconcileRequest
from app.exceptions import StatementNotFoundError
from app.services.reconciliation import reconcile
from app.services.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/statements", tags=["reconcile"])


@router.post("/{statement_id}/reconcile")
def reconcile_statement(
    statement_id: str,
    request: ReconcileRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = db.get(Statement, statement_id)
    if not statement or statement.firm_id != current_user.firm_id:
        raise StatementNotFoundError()

    transactions = db.query(Transaction).filter(Transaction.statement_id == statement_id).all()
    txn_dicts = [
        {"id": t.id, "description": t.description, "amount": t.amount, "txn_type": t.txn_type}
        for t in transactions
    ]

    matches = reconcile(txn_dicts, request.invoice_lines)
    match_by_txn_id = {m["transaction_id"]: m for m in matches}

    for txn in transactions:
        match = match_by_txn_id.get(txn.id)
        if match:
            txn.reconciled = True
            txn.matched_invoice_ref = match["invoice_ref"]

    statement.status = "reconciled"
    db.commit()

    return {
        "statement_id": statement_id,
        "matched_count": len(matches),
        "unmatched_invoice_count": len(request.invoice_lines) - len(matches),
        "matches": matches,
    }
