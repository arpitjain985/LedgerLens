from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Statement, Transaction
from app.exceptions import StatementNotFoundError, NoTransactionsToClassifyError
from app.services.exporter import build_workpaper
from app.services.workpaper_package import build_workpaper_package
from app.services.auth import get_current_user, require_role, CurrentUser

router = APIRouter(prefix="/statements", tags=["export"])


@router.get("/{statement_id}/export")
def export_workpaper(
    statement_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = db.get(Statement, statement_id)
    if not statement or statement.firm_id != current_user.firm_id:
        # Deliberately the same 404 whether the statement doesn't exist at
        # all or belongs to a different firm -- a 403 here would leak that
        # the ID is valid but just not yours, which is its own information
        # disclosure. Same principle as login's identical error for a wrong
        # password vs. a nonexistent email.
        raise StatementNotFoundError()

    transactions = db.query(Transaction).filter(Transaction.statement_id == statement_id).all()
    if not transactions:
        raise NoTransactionsToClassifyError()

    txn_dicts = [
        {
            "txn_date": t.txn_date,
            "description": t.description,
            "amount": t.amount,
            "txn_type": t.txn_type,
            "predicted_ledger_head": t.corrected_ledger_head or t.predicted_ledger_head,
            "confidence": t.confidence,
            "classification_method": t.classification_method,
            "reconciled": t.reconciled,
            "is_anomaly": t.is_anomaly,
            "anomaly_reason": t.anomaly_reason,
        }
        for t in transactions
    ]

    buffer = build_workpaper(txn_dicts)
    filename = f"LedgerLens_Workpaper_{statement.filename.rsplit('.', 1)[0]}.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/workpaper-package/full")
def export_workpaper_package(
    current_user: CurrentUser = Depends(require_role("CA_AUDITOR")),
    db: Session = Depends(get_db),
):
    """
    Section 17: the full CA workpaper package across ALL of a firm's
    statements/invoices, as a ZIP of multiple Excel reports.

    RBAC demonstration (Section 20): this endpoint requires at least the
    CA_AUDITOR role, not just any authenticated user -- a firm-wide data
    export is exactly the kind of sensitive, bulk operation that shouldn't
    be available to a VIEWER or REVIEWER role. See tests/test_rbac.py for
    proof this is actually enforced, not just decorative.
    """
    buffer = build_workpaper_package(db, current_user.firm_id)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="LedgerLens_Workpaper_Package.zip"'},
    )
