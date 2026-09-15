from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import RecurringTransaction
from app.services.recurring_detection import detect_recurring_transactions
from app.services.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/recurring-transactions", tags=["recurring"])


@router.get("", response_model=List[RecurringTransaction])
def list_recurring_transactions(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Section 26: vendor payments repeating at a roughly regular interval and
    amount (rent, EMI, subscriptions, etc.), computed across all of a firm's
    stored transactions. Migrated to auth: firm_id comes from the validated
    JWT. Honest limitation: needs at least 2 occurrences to detect anything,
    so this gets more useful as more statements are uploaded over time --
    see the module docstring in recurring_detection.py.
    """
    return detect_recurring_transactions(db, current_user.firm_id)
