"""
Tests for rate limiting (Section 22). Uses monkeypatch to set a small,
fast-to-hit limit rather than the real default (5/minute would make this
test slow and awkward) -- this proves the enforcement mechanism itself
works correctly at whatever the real limit is configured to, the same
pattern already used in tests/test_upload_size_limit.py.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


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
        yield test_client
    app.dependency_overrides.clear()


def test_login_rate_limit_blocks_after_threshold(client, monkeypatch):
    """
    Sets LOGIN_RATE_LIMIT to 3/minute via the actual decorator's limit
    string re-application isn't trivial to monkeypatch after the fact
    (slowapi bakes the limit string in at decoration time), so instead
    this test hits the REAL configured default (5/minute) and confirms
    request #6 is blocked -- slower to write, but tests the actual
    production configuration rather than a substitute.
    """
    client.post("/auth/register", json={"email": "ratelimit@example.com", "password": "password123", "firm_name": "Rate Firm"})

    responses = []
    for _ in range(6):
        resp = client.post("/auth/login", json={"email": "ratelimit@example.com", "password": "wrongpassword"})
        responses.append(resp.status_code)

    # First 5 attempts should be normal auth failures (401), the 6th should
    # be rate-limited (429) -- confirms the limit is actually enforced, not
    # just configured and ignored.
    assert responses[:5] == [401, 401, 401, 401, 401]
    assert responses[5] == 429


def test_rate_limit_response_has_clean_error_shape(client):
    client.post("/auth/register", json={"email": "ratelimit2@example.com", "password": "password123", "firm_name": "Rate Firm 2"})

    for _ in range(5):
        client.post("/auth/login", json={"email": "ratelimit2@example.com", "password": "wrong"})

    resp = client.post("/auth/login", json={"email": "ratelimit2@example.com", "password": "wrong"})
    assert resp.status_code == 429
    assert "error" in resp.json()
    assert "too many" in resp.json()["error"].lower()


def test_register_rate_limit_blocks_after_threshold(client):
    """REGISTER_RATE_LIMIT defaults to 10/hour -- confirm request #11 in
    the same test run is blocked."""
    responses = []
    for i in range(11):
        resp = client.post("/auth/register", json={
            "email": f"bulk{i}@example.com", "password": "password123", "firm_name": f"Bulk Firm {i}",
        })
        responses.append(resp.status_code)

    assert responses[:10] == [200] * 10
    assert responses[10] == 429
