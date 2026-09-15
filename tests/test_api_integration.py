"""
Integration tests using FastAPI's TestClient -- these hit real routes
through the actual app, unlike the unit tests in the other test files.

Uses FastAPI's standard dependency_overrides mechanism to point the app at
a throwaway in-memory SQLite DB for the duration of each test, so this
never touches your real ledgerlens.db.
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
    # Fresh in-memory DB per test -- fast, isolated, no leftover state.
    # StaticPool is required here: without it, SQLite's :memory: gives each
    # new connection its own empty database, so the tables created by
    # Base.metadata.create_all() below wouldn't be visible to the requests
    # TestClient makes (which open their own connections via get_db).
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


@pytest.fixture
def auth_headers(client):
    """Registers a real test user/firm and returns a valid Authorization
    header -- used by any test that needs to call an auth-protected route."""
    resp = client.post("/auth/register", json={
        "email": "testuser@example.com", "password": "testpassword123", "firm_name": "Test Firm",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health_endpoint_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "overall_status" in body
    assert set(body["checks"].keys()) == {"backend", "database", "ocr", "embedding_model", "llm"}


def test_root_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["service"] == "LedgerLens API"


def test_upload_requires_authentication(client):
    """Section 20/22: uploading without a valid token must be rejected."""
    resp = client.post(
        "/statements/upload",
        files={"file": ("statement.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 401


def test_upload_rejects_non_pdf(client, auth_headers):
    resp = client.post(
        "/statements/upload",
        files={"file": ("statement.txt", b"not a pdf", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["error"]


def test_classify_nonexistent_statement_returns_404(client, auth_headers):
    resp = client.post("/statements/does-not-exist/classify", headers=auth_headers)
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"].lower()


def test_job_status_for_nonexistent_job_returns_404(client):
    resp = client.get("/jobs/does-not-exist")
    assert resp.status_code == 404


def test_export_nonexistent_statement_returns_404(client, auth_headers):
    resp = client.get("/statements/does-not-exist/export", headers=auth_headers)
    assert resp.status_code == 404
