from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AuditLogEntry
from app.services.audit_trail import get_audit_log
from app.services.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("", response_model=List[AuditLogEntry])
def audit_log(
    entity_id: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_audit_log(db, current_user.firm_id, entity_id)
