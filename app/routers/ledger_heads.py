from fastapi import APIRouter

from app.services.classifier import _load_ledger_heads

router = APIRouter(tags=["ledger-heads"])


@router.get("/ledger-heads")
def list_ledger_heads():
    """
    Returns the static classification taxonomy (code + display label) --
    used by the frontend to populate a correction dropdown. No auth needed:
    this is a fixed reference list, not firm-specific data.
    """
    heads = _load_ledger_heads()
    return [{"code": h["code"], "label": h["label"]} for h in heads]
