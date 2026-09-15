"""
Team invite lifecycle (Section 19/20): an existing user with sufficient
privilege invites someone by email to join their firm with a specific
role. The invitee doesn't have an account until they accept -- there's no
User row for them yet, unlike password reset which always targets an
existing user.

Same token-hash-for-lookup principle as password_reset.py: only a SHA-256
hash of the token is stored, the raw value is only ever held in memory
long enough to email it.
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Invite, User, Firm
from app.config import INVITE_TOKEN_EXPIRE_HOURS
from app.exceptions import LedgerLensError
from app.services.auth import ROLE_HIERARCHY, hash_password


class InvalidInviteTokenError(LedgerLensError):
    status_code = 400
    user_message = "This invite link is invalid, expired, or has already been used. Please ask for a new one."


class CannotInviteHigherRoleError(LedgerLensError):
    status_code = 403
    user_message = "You can't invite someone to a role higher than your own."


class UserAlreadyExistsError(LedgerLensError):
    status_code = 400
    user_message = "An account with this email already exists."


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_invite(db: Session, firm_id: str, email: str, role: str, invited_by_user_id: str, inviter_role: str) -> str:
    """Returns the RAW token (to be emailed) -- only the hash is stored."""
    if role not in ROLE_HIERARCHY:
        raise InvalidInviteTokenError(user_message=f"'{role}' is not a valid role.")

    # Can't grant a role more privileged than your own -- a REVIEWER can't
    # invite someone as SUPER_ADMIN, even if the invite endpoint itself is
    # otherwise permitted for their role (see the endpoint's own minimum
    # role requirement, which is a separate, coarser check).
    if ROLE_HIERARCHY.index(role) > ROLE_HIERARCHY.index(inviter_role):
        raise CannotInviteHigherRoleError()

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise UserAlreadyExistsError()

    raw_token = secrets.token_urlsafe(32)
    db.add(Invite(
        firm_id=firm_id,
        email=email,
        role=role,
        invited_by_user_id=invited_by_user_id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(hours=INVITE_TOKEN_EXPIRE_HOURS),
    ))
    db.commit()

    return raw_token


def accept_invite(db: Session, raw_token: str, password: str, full_name: str = None) -> User:
    """
    Validates the invite and creates the actual User row -- this is the
    point at which the invitee's account first comes into existence.
    """
    token_hash = _hash_token(raw_token)
    invite = db.query(Invite).filter(Invite.token_hash == token_hash).first()

    if not invite:
        raise InvalidInviteTokenError()
    if invite.accepted:
        raise InvalidInviteTokenError()
    if invite.expires_at < datetime.utcnow():
        raise InvalidInviteTokenError()

    # An account could have been created with this email through a
    # different path (e.g. a separate registration) between invite creation
    # and acceptance -- check again right before creating the row.
    existing_user = db.query(User).filter(User.email == invite.email).first()
    if existing_user:
        raise UserAlreadyExistsError()

    user = User(
        firm_id=invite.firm_id,
        email=invite.email,
        hashed_password=hash_password(password),
        full_name=full_name,
        role=invite.role,
    )
    db.add(user)

    invite.accepted = True
    invite.accepted_at = datetime.utcnow()

    db.commit()
    db.refresh(user)

    return user


def list_firm_users(db: Session, firm_id: str) -> list:
    users = db.query(User).filter(User.firm_id == firm_id).order_by(User.created_at).all()
    return [
        {
            "id": u.id, "email": u.email, "full_name": u.full_name,
            "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        }
        for u in users
    ]


def list_pending_invites(db: Session, firm_id: str) -> list:
    invites = (
        db.query(Invite)
        .filter(Invite.firm_id == firm_id, Invite.accepted == False)  # noqa: E712
        .order_by(Invite.created_at.desc())
        .all()
    )
    now = datetime.utcnow()
    return [
        {
            "id": i.id, "email": i.email, "role": i.role,
            "created_at": i.created_at.isoformat() if i.created_at else None,
            "expires_at": i.expires_at.isoformat() if i.expires_at else None,
            "expired": i.expires_at < now,
        }
        for i in invites
    ]
