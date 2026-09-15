from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import VendorSummary
from app.services.vendor_intelligence import get_vendor_summary
from app.services.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("", response_model=List[VendorSummary])
def list_vendors(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Returns aggregated vendor profiles for a firm (Section 25) -- built from
    all transactions across every statement uploaded so far, not just one.
    Migrated to auth: firm_id comes from the validated JWT.
    """
    return get_vendor_summary(db, current_user.firm_id)
