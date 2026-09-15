from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Firm
from app.services.auth import get_current_user, require_role, CurrentUser
from app.services.invite import create_invite, list_firm_users, list_pending_invites
from app.services.email_sender import send_invite_email

router = APIRouter(prefix="/users", tags=["team"])


class InviteRequest(BaseModel):
    email: EmailStr
    role: str  # one of ROLE_HIERARCHY: VIEWER | REVIEWER | ACCOUNTANT | CA_AUDITOR | SUPER_ADMIN


@router.post("/invite")
def invite_user(
    body: InviteRequest,
    current_user: CurrentUser = Depends(require_role("CA_AUDITOR")),
    db: Session = Depends(get_db),
):
    """
    Section 19/20: invites someone by email to join the caller's firm with
    a specific role. Requires at least CA_AUDITOR -- inviting new team
    members with real permissions is exactly the kind of action that
    shouldn't be available to a VIEWER or REVIEWER. create_invite() also
    separately enforces that you can't grant a role more privileged than
    your own, even if you meet the CA_AUDITOR floor for this endpoint.
    """
    raw_token = create_invite(
        db, firm_id=current_user.firm_id, email=body.email, role=body.role,
        invited_by_user_id=current_user.user_id, inviter_role=current_user.role,
    )

    firm = db.get(Firm, current_user.firm_id)
    send_invite_email(to_email=body.email, raw_token=raw_token, firm_name=firm.name, role=body.role)

    return {"message": f"Invite sent to {body.email}."}


@router.get("")
def list_team(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Any authenticated member of a firm can see their own teammates --
    this isn't sensitive information within a firm the way cross-firm data
    isolation is."""
    return list_firm_users(db, current_user.firm_id)


@router.get("/invites/pending")
def list_pending(
    current_user: CurrentUser = Depends(require_role("CA_AUDITOR")),
    db: Session = Depends(get_db),
):
    """Who's been invited but hasn't accepted yet -- restricted to
    CA_AUDITOR+ since this is an administrative view, not general team info."""
    return list_pending_invites(db, current_user.firm_id)
