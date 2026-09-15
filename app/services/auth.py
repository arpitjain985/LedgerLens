"""
Authentication and RBAC (Section 20).

Passwords: bcrypt hashing only, never stored or logged in plaintext.
Tokens: JWT (HS256), carrying user_id, firm_id, and role -- so every
downstream request can authorize without a DB round-trip just to know
"which firm does this user belong to."

Roles (highest to lowest privilege): SUPER_ADMIN, CA_AUDITOR, ACCOUNTANT,
REVIEWER, VIEWER. Permission checks are role-hierarchy-based: a role can do
everything the roles below it can, per the ROLE_HIERARCHY ordering.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_ACCESS_TOKEN_EXPIRE_MINUTES
from app.database import get_db
from app.exceptions import LedgerLensError

logger = logging.getLogger(__name__)

if JWT_SECRET_KEY == "INSECURE-DEV-ONLY-CHANGE-ME-IN-PRODUCTION":
    logger.warning(
        "JWT_SECRET_KEY is using the insecure default. Set a real secret via "
        "the JWT_SECRET_KEY environment variable before any real deployment "
        "-- see .env.example."
    )

ROLE_HIERARCHY = ["VIEWER", "REVIEWER", "ACCOUNTANT", "CA_AUDITOR", "SUPER_ADMIN"]


class AuthenticationError(LedgerLensError):
    status_code = 401
    user_message = "Invalid email or password."


class TokenError(LedgerLensError):
    status_code = 401
    user_message = "Your session has expired or is invalid. Please log in again."


class PermissionDeniedError(LedgerLensError):
    status_code = 403
    user_message = "You don't have permission to perform this action."


class EmailAlreadyRegisteredError(LedgerLensError):
    status_code = 400
    user_message = "An account with this email already exists."


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id: str, firm_id: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "firm_id": firm_id, "role": role, "exp": expire}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise TokenError(detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise TokenError(detail=str(e))


class CurrentUser:
    """Lightweight object carrying the authenticated request's identity --
    avoids a DB round-trip on every request just to know who's calling."""

    def __init__(self, user_id: str, firm_id: str, role: str):
        self.user_id = user_id
        self.firm_id = firm_id
        self.role = role

    def has_at_least(self, required_role: str) -> bool:
        try:
            return ROLE_HIERARCHY.index(self.role) >= ROLE_HIERARCHY.index(required_role)
        except ValueError:
            return False


def get_current_user(authorization: Optional[str] = Header(None)) -> CurrentUser:
    """
    FastAPI dependency: extracts and validates the bearer token, returning
    the authenticated user's identity. Use this instead of a hardcoded
    firm_id query parameter in any router being migrated to auth (see
    PROGRESS.md for which routers currently use this vs. the old pattern).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise TokenError(detail="Missing or malformed Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    return CurrentUser(user_id=payload["sub"], firm_id=payload["firm_id"], role=payload["role"])


def require_role(minimum_role: str):
    """
    FastAPI dependency factory: use as
    `Depends(require_role("CA_AUDITOR"))` to require at least that role.
    Raises PermissionDeniedError (403) rather than silently allowing or
    failing open -- an unrecognized/misconfigured role is treated as
    insufficient, never as elevated access.
    """
    def _check(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not current_user.has_at_least(minimum_role):
            raise PermissionDeniedError(
                detail=f"Role {current_user.role} does not meet minimum required role {minimum_role}"
            )
        return current_user

    return _check
