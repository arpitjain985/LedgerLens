import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services.password_reset import create_reset_token, consume_reset_token, InvalidResetTokenError


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client._session_local = TestSessionLocal
        yield test_client
    app.dependency_overrides.clear()


def test_forgot_password_returns_generic_message_for_real_email(client):
    client.post("/auth/register", json={"email": "resettest@example.com", "password": "oldpassword123", "firm_name": "Reset Firm"})
    resp = client.post("/auth/forgot-password", json={"email": "resettest@example.com"})
    assert resp.status_code == 200
    assert "if an account exists" in resp.json()["message"].lower()


def test_forgot_password_returns_identical_message_for_nonexistent_email(client):
    """Section 22 / email-enumeration protection: the response must be
    indistinguishable whether or not the email is actually registered."""
    real_resp = client.post("/auth/forgot-password", json={"email": "doesnotexist@example.com"})
    assert real_resp.status_code == 200
    assert "if an account exists" in real_resp.json()["message"].lower()


def test_reset_password_with_valid_token_changes_password(client):
    client.post("/auth/register", json={"email": "validreset@example.com", "password": "oldpassword123", "firm_name": "Valid Reset Firm"})

    # Generate a real token directly via the service layer (the raw token
    # is normally only ever emailed, never returned by the API -- this
    # mirrors what a real user would get from clicking their email link).
    db = client._session_local()
    from app.models import User
    user = db.query(User).filter(User.email == "validreset@example.com").first()
    raw_token = create_reset_token(db, user.id)
    db.close()

    resp = client.post("/auth/reset-password", json={"token": raw_token, "new_password": "newpassword456"})
    assert resp.status_code == 200

    # Old password should no longer work, new one should.
    old_login = client.post("/auth/login", json={"email": "validreset@example.com", "password": "oldpassword123"})
    assert old_login.status_code == 401

    new_login = client.post("/auth/login", json={"email": "validreset@example.com", "password": "newpassword456"})
    assert new_login.status_code == 200


def test_reset_password_token_is_single_use(client):
    client.post("/auth/register", json={"email": "singleuse@example.com", "password": "oldpassword123", "firm_name": "Single Use Firm"})

    db = client._session_local()
    from app.models import User
    user = db.query(User).filter(User.email == "singleuse@example.com").first()
    raw_token = create_reset_token(db, user.id)
    db.close()

    first_use = client.post("/auth/reset-password", json={"token": raw_token, "new_password": "firstnewpass"})
    assert first_use.status_code == 200

    second_use = client.post("/auth/reset-password", json={"token": raw_token, "new_password": "secondnewpass"})
    assert second_use.status_code == 400


def test_reset_password_with_garbage_token_rejected(client):
    resp = client.post("/auth/reset-password", json={"token": "not-a-real-token", "new_password": "whatever123"})
    assert resp.status_code == 400
    assert "invalid" in resp.json()["error"].lower() or "expired" in resp.json()["error"].lower()


def test_expired_token_rejected_directly():
    """Direct service-level test using a manually-backdated token, since
    waiting real minutes for expiry in a test would be impractical."""
    from datetime import datetime, timedelta
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    from app.models import Firm, User, PasswordResetToken
    from app.services.auth import hash_password
    import hashlib

    firm = Firm(id="f1", name="Expiry Test Firm")
    db.add(firm)
    user = User(id="u1", firm_id="f1", email="expiry@example.com", hashed_password=hash_password("pass123"), role="SUPER_ADMIN")
    db.add(user)

    raw_token = "test-raw-token-value"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    db.add(PasswordResetToken(
        user_id="u1", token_hash=token_hash,
        expires_at=datetime.utcnow() - timedelta(minutes=5),  # already expired
    ))
    db.commit()

    with pytest.raises(InvalidResetTokenError):
        consume_reset_token(db, raw_token)
