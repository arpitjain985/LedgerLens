from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Firm
from app.services.auth import (
    hash_password, verify_password, create_access_token,
    AuthenticationError, EmailAlreadyRegisteredError, ROLE_HIERARCHY,
)
from app.services.rate_limit import limiter
from app.config import LOGIN_RATE_LIMIT, REGISTER_RATE_LIMIT
from app.services.password_reset import (
    create_reset_token, consume_reset_token, InvalidResetTokenError,
)
from app.services.email_sender import send_password_reset_email
from app.services.invite import accept_invite

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str = None
    firm_name: str  # creates a new firm for the first user who registers under it


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    firm_id: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class AcceptInviteRequest(BaseModel):
    token: str
    password: str
    full_name: str = None


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/register", response_model=TokenResponse)
@limiter.limit(REGISTER_RATE_LIMIT)
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    """Section 22: rate-limited (default 10/hour per IP) to slow down
    automated mass account creation."""
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise EmailAlreadyRegisteredError()

    # First user to register under a firm name becomes SUPER_ADMIN for it.
    # A real multi-user-per-firm invite flow is a Phase 5 follow-up (see
    # PROGRESS.md) -- this covers the single-owner-signs-up case correctly.
    firm = Firm(name=body.firm_name)
    db.add(firm)
    db.flush()

    user = User(
        firm_id=firm.id,
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role="SUPER_ADMIN",
    )
    db.add(user)
    db.commit()

    token = create_access_token(user_id=user.id, firm_id=firm.id, role=user.role)
    return TokenResponse(access_token=token, role=user.role, firm_id=firm.id)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(LOGIN_RATE_LIMIT)
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    """Section 22: rate-limited (default 5/minute per IP) to slow down
    password brute-forcing / credential stuffing against this endpoint."""
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise AuthenticationError()
    if not user.is_active:
        raise AuthenticationError(user_message="This account has been deactivated.")

    user.last_login_at = datetime.utcnow()
    db.commit()

    token = create_access_token(user_id=user.id, firm_id=user.firm_id, role=user.role)
    return TokenResponse(access_token=token, role=user.role, firm_id=user.firm_id)


@router.post("/forgot-password")
@limiter.limit(LOGIN_RATE_LIMIT)
def forgot_password(request: Request, body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Always returns the same generic success message whether or not the
    email is registered -- same email-enumeration protection principle as
    /auth/login's identical error for wrong-password vs. nonexistent-email.
    Rate-limited for the same reason login is: this endpoint can be used to
    probe which emails exist even with the generic response, if unlimited
    attempts were allowed to correlate timing/side channels.
    """
    user = db.query(User).filter(User.email == body.email).first()
    if user:
        raw_token = create_reset_token(db, user.id)
        send_password_reset_email(to_email=user.email, raw_token=raw_token)

    return {"message": "If an account exists for that email, a password reset link has been sent."}


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = consume_reset_token(db, body.token)  # raises InvalidResetTokenError if bad/expired/used

    user.hashed_password = hash_password(body.new_password)
    db.commit()

    return {"message": "Password has been reset. You can now log in with your new password."}


@router.post("/accept-invite", response_model=TokenResponse)
def accept_invite_endpoint(body: AcceptInviteRequest, db: Session = Depends(get_db)):
    """
    Public endpoint (no auth) -- the invitee doesn't have an account until
    this call creates it. Returns a token immediately (auto-login) so the
    new teammate lands in the app straight away, consistent with
    /auth/register's behavior.
    """
    user = accept_invite(db, raw_token=body.token, password=body.password, full_name=body.full_name)
    token = create_access_token(user_id=user.id, firm_id=user.firm_id, role=user.role)
    return TokenResponse(access_token=token, role=user.role, firm_id=user.firm_id)
