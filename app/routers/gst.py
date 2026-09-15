from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import GSTSummary
from app.services.gst_summary import get_gst_summary
from app.services.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/gst-summary", tags=["gst"])


@router.get("", response_model=GSTSummary)
def gst_summary(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_gst_summary(db, current_user.firm_id)
