import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services.auth import (
    hash_password, verify_password, create_access_token, decode_access_token,
    CurrentUser, TokenError,
)


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

    # Same fix as test_phase2_integration.py / test_phase3_integration.py:
    # the background upload-processing task uses its own SessionLocal
    # reference (by design, see routers/upload.py), which bypasses the
    # get_db override above. Patch it directly so background writes land
    # in the same in-memory test DB as the request.
    import app.routers.upload as upload_router
    original_session_local = upload_router.SessionLocal
    upload_router.SessionLocal = TestSessionLocal

    with TestClient(app) as test_client:
        yield test_client

    upload_router.SessionLocal = original_session_local
    app.dependency_overrides.clear()


# --- Unit tests: password hashing ---

def test_password_hash_is_not_plaintext():
    hashed = hash_password("mySecret123")
    assert hashed != "mySecret123"
    assert hashed.startswith("$2b$")  # bcrypt hash prefix


def test_correct_password_verifies():
    hashed = hash_password("mySecret123")
    assert verify_password("mySecret123", hashed) is True


def test_wrong_password_does_not_verify():
    hashed = hash_password("mySecret123")
    assert verify_password("wrongPassword", hashed) is False


# --- Unit tests: JWT ---

def test_token_round_trip():
    token = create_access_token(user_id="u1", firm_id="f1", role="ACCOUNTANT")
    payload = decode_access_token(token)
    assert payload["sub"] == "u1"
    assert payload["firm_id"] == "f1"
    assert payload["role"] == "ACCOUNTANT"


def test_tampered_token_rejected():
    import jwt as pyjwt
    from datetime import datetime, timedelta
    fake_token = pyjwt.encode(
        {"sub": "u1", "firm_id": "f1", "role": "SUPER_ADMIN", "exp": datetime.utcnow() + timedelta(minutes=5)},
        "wrong-secret", algorithm="HS256",
    )
    with pytest.raises(TokenError):
        decode_access_token(fake_token)


def test_expired_token_rejected():
    import jwt as pyjwt
    from datetime import datetime, timedelta
    from app.config import JWT_SECRET_KEY, JWT_ALGORITHM
    expired_token = pyjwt.encode(
        {"sub": "u1", "firm_id": "f1", "role": "VIEWER", "exp": datetime.utcnow() - timedelta(minutes=5)},
        JWT_SECRET_KEY, algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(TokenError):
        decode_access_token(expired_token)


# --- Unit tests: RBAC role hierarchy ---

def test_higher_role_has_lower_role_permissions():
    admin = CurrentUser(user_id="u1", firm_id="f1", role="SUPER_ADMIN")
    assert admin.has_at_least("VIEWER") is True
    assert admin.has_at_least("CA_AUDITOR") is True


def test_lower_role_lacks_higher_role_permissions():
    viewer = CurrentUser(user_id="u1", firm_id="f1", role="VIEWER")
    assert viewer.has_at_least("ACCOUNTANT") is False
    assert viewer.has_at_least("SUPER_ADMIN") is False


def test_unknown_role_never_satisfies_any_requirement():
    """An unrecognized role must be treated as insufficient, never as
    elevated access -- fail closed, not open."""
    broken = CurrentUser(user_id="u1", firm_id="f1", role="NOT_A_REAL_ROLE")
    assert broken.has_at_least("VIEWER") is False


# --- Integration tests: real HTTP register/login flow ---

def test_register_returns_valid_token(client):
    resp = client.post("/auth/register", json={
        "email": "new@example.com", "password": "password123", "firm_name": "New Firm",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "SUPER_ADMIN"
    assert "access_token" in data


def test_duplicate_email_registration_rejected(client):
    client.post("/auth/register", json={"email": "dup@example.com", "password": "password123", "firm_name": "Firm A"})
    resp = client.post("/auth/register", json={"email": "dup@example.com", "password": "otherpassword", "firm_name": "Firm B"})
    assert resp.status_code == 400


def test_login_with_correct_credentials_succeeds(client):
    client.post("/auth/register", json={"email": "login@example.com", "password": "password123", "firm_name": "Firm"})
    resp = client.post("/auth/login", json={"email": "login@example.com", "password": "password123"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_with_wrong_password_rejected(client):
    client.post("/auth/register", json={"email": "login2@example.com", "password": "password123", "firm_name": "Firm"})
    resp = client.post("/auth/login", json={"email": "login2@example.com", "password": "wrongpassword"})
    assert resp.status_code == 401


def test_login_nonexistent_email_and_wrong_password_give_identical_error(client):
    """Security property: don't leak whether an email is registered."""
    client.post("/auth/register", json={"email": "exists@example.com", "password": "password123", "firm_name": "Firm"})

    wrong_password_resp = client.post("/auth/login", json={"email": "exists@example.com", "password": "wrong"})
    nonexistent_resp = client.post("/auth/login", json={"email": "doesnotexist@example.com", "password": "wrong"})

    assert wrong_password_resp.status_code == nonexistent_resp.status_code == 401
    assert wrong_password_resp.json()["error"] == nonexistent_resp.json()["error"]


def test_protected_endpoint_rejects_missing_token(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 401


def test_protected_endpoint_rejects_garbage_token(client):
    resp = client.get("/dashboard", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


def test_protected_endpoint_accepts_valid_token(client):
    register_resp = client.post("/auth/register", json={
        "email": "valid@example.com", "password": "password123", "firm_name": "Valid Firm",
    })
    token = register_resp.json()["access_token"]
    resp = client.get("/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_two_firms_cannot_see_each_others_data(client):
    """The actual point of multi-tenancy: register two separate firms,
    upload real data to one, and confirm the other's dashboard stays empty
    -- not just two empty dashboards that happen to look isolated."""
    firm1_token = client.post("/auth/register", json={
        "email": "owner1@firm1.com", "password": "password123", "firm_name": "Firm One",
    }).json()["access_token"]
    firm2_token = client.post("/auth/register", json={
        "email": "owner2@firm2.com", "password": "password123", "firm_name": "Firm Two",
    }).json()["access_token"]

    import io
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica", 10)
    c.drawString(50, 750, "01-07-2026 SALARY CREDIT NEFT FROM ACME 48,000.00 CR")
    c.save()

    upload_resp = client.post(
        "/statements/upload",
        files={"file": ("test.pdf", buf.getvalue(), "application/pdf")},
        headers={"Authorization": f"Bearer {firm1_token}"},
    )
    job_id = upload_resp.json()["job_id"]
    for _ in range(20):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] == "completed":
            break

    firm1_dashboard = client.get("/dashboard", headers={"Authorization": f"Bearer {firm1_token}"}).json()
    firm2_dashboard = client.get("/dashboard", headers={"Authorization": f"Bearer {firm2_token}"}).json()

    assert firm1_dashboard["transaction_count"] == 1
    assert firm1_dashboard["total_credits"] == 48000.0
    assert firm2_dashboard["transaction_count"] == 0  # firm2 must NOT see firm1's transaction
