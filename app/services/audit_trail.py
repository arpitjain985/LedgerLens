"""
Audit trail (Section 18): records financial-data changes with full
before/after context, so nothing important happens invisibly. This is
called from routers/classify.py on both classification and correction --
not just on manual edits, per the spec's explicit instruction that no
important change should happen without traceability.
"""
from sqlalchemy.orm import Session

from app.models import AuditLog


def log_action(
    db: Session,
    firm_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    field_changed: str = None,
    previous_value: str = None,
    new_value: str = None,
    reason: str = None,
    changed_by: str = "system",
) -> None:
    db.add(AuditLog(
        firm_id=firm_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        field_changed=field_changed,
        previous_value=previous_value,
        new_value=new_value,
        reason=reason,
        changed_by=changed_by,
    ))
    # Deliberately no db.commit() here -- the caller controls the
    # transaction boundary so an audit entry is written atomically with the
    # change it describes, not as a separate commit that could succeed even
    # if the actual change fails (or vice versa).


def get_audit_log(db: Session, firm_id: str, entity_id: str = None, limit: int = 200) -> list:
    query = db.query(AuditLog).filter(AuditLog.firm_id == firm_id)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    entries = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "action": e.action,
            "field_changed": e.field_changed,
            "previous_value": e.previous_value,
            "new_value": e.new_value,
            "reason": e.reason,
            "changed_by": e.changed_by,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]
