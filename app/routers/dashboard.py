from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import DashboardSummary
from app.services.dashboard import get_dashboard
from app.services.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSummary)
def dashboard(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Migrated to auth (Section 20/22): firm_id now comes from the validated
    JWT, not a client-supplied query parameter -- this is the actual
    security property multi-tenancy requires (a user literally cannot pass
    a different firm_id to see another firm's dashboard, because the value
    isn't attacker-controlled input anymore). See PROGRESS.md for which
    other routers are/aren't migrated yet.
    """
    return get_dashboard(db, current_user.firm_id)
