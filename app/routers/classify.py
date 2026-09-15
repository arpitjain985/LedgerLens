import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Statement, Transaction, Correction
from app.schemas import ClassifyResponse, TransactionCorrection
from app.exceptions import (
    StatementNotFoundError,
    NoTransactionsToClassifyError,
    TransactionNotFoundError,
    ClassificationModelUnavailableError,
)
from app.services.classifier import classify_transaction
from app.services.anomaly import flag_anomalies
from app.services.risk_engine import compute_risk
from app.services.vendor_extraction import extract_vendor, normalize_description
from app.services.vendor_intelligence import update_vendor_profiles
from app.services.audit_trail import log_action
from app.services.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/statements", tags=["classify"])


@router.post("/{statement_id}/classify", response_model=ClassifyResponse)
def classify_statement(
    statement_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Migrated to auth: firm_id comes from the JWT, and ownership of the
    statement is checked -- same 404 whether it doesn't exist or belongs to
    another firm, so a valid-but-foreign ID can't be distinguished by an
    attacker (same principle already used in routers/export.py)."""
    statement = db.get(Statement, statement_id)
    if not statement or statement.firm_id != current_user.firm_id:
        raise StatementNotFoundError()

    transactions = db.query(Transaction).filter(Transaction.statement_id == statement_id).all()
    if not transactions:
        raise NoTransactionsToClassifyError()

    llm_fallback_count = 0
    correction_memory_count = 0

    for txn in transactions:
        if txn.vendor is None:
            txn.vendor = extract_vendor(txn.description)

        try:
            result = classify_transaction(txn.description, db=db, firm_id=statement.firm_id)
        except Exception as e:
            raise ClassificationModelUnavailableError(detail=str(e))

        txn.predicted_ledger_head = result.ledger_head
        txn.confidence = result.confidence
        txn.classification_method = result.method
        txn.classification_reason = result.reason

        if result.method == "llm_fallback":
            llm_fallback_count += 1
        elif result.method == "correction_memory":
            correction_memory_count += 1

    db.commit()

    vendor_first_seen = update_vendor_profiles(db, statement.firm_id)

    anomaly_input = [
        {"id": t.id, "description": t.description, "amount": t.amount,
         "predicted_ledger_head": t.predicted_ledger_head}
        for t in transactions
    ]
    anomaly_results = {r["transaction_id"]: r for r in flag_anomalies(anomaly_input)}

    risk_input = [
        {"id": t.id, "description": t.description, "amount": t.amount,
         "predicted_ledger_head": t.predicted_ledger_head, "txn_date": t.txn_date,
         "vendor": t.vendor}
        for t in transactions
    ]
    risk_results = {r["transaction_id"]: r for r in compute_risk(risk_input, vendor_first_seen)}

    for txn in transactions:
        anomaly_result = anomaly_results.get(txn.id)
        if anomaly_result:
            txn.is_anomaly = anomaly_result["is_anomaly"]
            txn.anomaly_reason = anomaly_result["reason"]

        risk_result = risk_results.get(txn.id)
        if risk_result:
            txn.risk_score = risk_result["risk_score"]
            txn.risk_level = risk_result["risk_level"]
            txn.risk_reasons = json.dumps(risk_result["risk_reasons"])

    statement.status = "classified"
    db.commit()
    db.refresh(statement)

    return ClassifyResponse(
        statement_id=statement_id,
        classified_count=len(transactions),
        llm_fallback_count=llm_fallback_count,
        correction_memory_count=correction_memory_count,
        transactions=transactions,
    )


@router.post("/{statement_id}/correct")
def correct_transaction(
    statement_id: str,
    correction: TransactionCorrection,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Records a CA's manual correction to a predicted ledger head -- the data
    flywheel (Section 8). Migrated to auth: verifies the statement belongs
    to the caller's firm before allowing a correction against it.
    """
    statement = db.get(Statement, statement_id)
    if not statement or statement.firm_id != current_user.firm_id:
        raise StatementNotFoundError()

    txn = db.get(Transaction, correction.transaction_id)
    if not txn or txn.statement_id != statement_id:
        raise TransactionNotFoundError()

    previous_head = txn.predicted_ledger_head
    txn.corrected_ledger_head = correction.corrected_ledger_head
    db.add(Correction(
        firm_id=statement.firm_id,
        normalized_description=normalize_description(txn.description),
        corrected_ledger_head=correction.corrected_ledger_head,
        original_description=txn.description,
    ))

    log_action(
        db, firm_id=statement.firm_id, entity_type="transaction", entity_id=txn.id,
        action="corrected", field_changed="ledger_head",
        previous_value=previous_head, new_value=correction.corrected_ledger_head,
        reason="Human correction via /correct endpoint", changed_by=current_user.user_id,
    )

    db.commit()

    return {"status": "ok", "transaction_id": txn.id, "corrected_ledger_head": txn.corrected_ledger_head}
