from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.copilot import answer_question
from app.services.financial_search import search_transactions
from app.services.auth import get_current_user, CurrentUser

router = APIRouter(tags=["ai-platform"])


class AskRequest(BaseModel):
    question: str


class SearchRequest(BaseModel):
    query: str


@router.post("/ai/ask")
def ask_ledgerlens(
    request: AskRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Section 13: natural-language Q&A over the firm's actual stored data.
    Every number in the answer comes from a real database aggregation, not
    from the LLM -- see app/services/copilot.py's module docstring for the
    full grounding design. Unrecognized questions get an honest "I don't
    know how to answer that yet" instead of a guess. Migrated to auth.
    """
    return answer_question(db, current_user.firm_id, request.question)


@router.post("/ai/search")
def financial_search(
    request: SearchRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Section 14: natural-language transaction search via structured
    filter extraction (amount thresholds, new-vendor, debit/credit) -- no
    LLM involved, pure SQL filtering grounded in the parsed query."""
    return search_transactions(db, current_user.firm_id, request.query)
