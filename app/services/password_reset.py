"""
Password reset token lifecycle: create (on /forgot-password), consume (on
/reset-password). Tokens are single-use, expire after
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES, and are stored only as a hash --
never the raw value -- same principle as password storage.

Uses SHA-256 rather than bcrypt for the token hash: these are random
32-byte tokens (secrets.token_urlsafe), not human-chosen passwords, so
there's no dictionary/brute-force risk that bcrypt's deliberate slowness
defends against -- a fast hash is the right tool here, and it's also what
lets lookup happen via a DB index (bcrypt hashes are salted differently
every time, so they can't be looked up by equality; SHA-256 of the same
input is always identical, which is what makes indexed lookup possible).
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import PasswordResetToken, User
from app.config import PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
from app.exceptions import LedgerLensError


class InvalidResetTokenError(LedgerLensError):
    status_code = 400
    user_message = "This password reset link is invalid or has expired. Please request a new one."


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_reset_token(db: Session, user_id: str) -> str:
    """Returns the RAW token (to be emailed) -- only the hash is stored."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)

    db.add(PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=datetime.utcnow() + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
    ))
    db.commit()

    return raw_token


def consume_reset_token(db: Session, raw_token: str) -> User:
    """
    Validates and marks a token used, returning the associated User.
    Raises InvalidResetTokenError for any invalid/expired/already-used
    token -- deliberately the same error for all three cases, so a caller
    can't distinguish "expired" from "never existed" from "already used"
    (that distinction isn't useful to a legitimate user and IS useful to
    an attacker probing for valid-looking tokens).
    """
    token_hash = _hash_token(raw_token)
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()

    if not reset_token:
        raise InvalidResetTokenError()
    if reset_token.used:
        raise InvalidResetTokenError()
    if reset_token.expires_at < datetime.utcnow():
        raise InvalidResetTokenError()

    reset_token.used = True
    db.commit()

    user = db.get(User, reset_token.user_id)
    if not user:
        raise InvalidResetTokenError()  # user was deleted after token issuance -- treat as invalid

    return user
