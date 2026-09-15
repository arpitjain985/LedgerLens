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

    import app.routers.upload as upload_router
    original_session_local = upload_router.SessionLocal
    upload_router.SessionLocal = TestSessionLocal

    with TestClient(app) as test_client:
        yield test_client

    upload_router.SessionLocal = original_session_local
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client):
    resp = client.post("/auth/register", json={
        "email": "sizetest@example.com", "password": "password123", "firm_name": "Size Test Firm",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_oversized_upload_is_rejected(client, auth_headers, monkeypatch):
    """
    Sets a tiny limit via monkeypatch rather than actually generating a
    25MB+ test file (which would be slow and wasteful to run on every test
    pass) -- this proves the enforcement logic itself works correctly at
    whatever the real limit is configured to.
    """
    import app.routers.upload as upload_router
    monkeypatch.setattr(upload_router, "MAX_UPLOAD_SIZE_BYTES", 100)  # 100 bytes

    oversized_content = b"%PDF-1.4\n" + (b"x" * 200)  # well over 100 bytes
    resp = client.post(
        "/statements/upload",
        files={"file": ("big.pdf", oversized_content, "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 413
    assert "too large" in resp.json()["error"].lower()


def test_undersized_upload_within_limit_is_accepted(client, auth_headers, monkeypatch):
    import app.routers.upload as upload_router
    monkeypatch.setattr(upload_router, "MAX_UPLOAD_SIZE_BYTES", 100_000)  # 100KB, generous for a tiny test PDF

    small_content = b"%PDF-1.4\n" + (b"x" * 50)
    resp = client.post(
        "/statements/upload",
        files={"file": ("small.pdf", small_content, "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 200


def test_partial_oversized_file_is_cleaned_up_from_disk(client, auth_headers, monkeypatch, tmp_path):
    """Confirms the partial file doesn't linger on disk after rejection --
    a real (if minor) resource-leak concern for repeated oversized upload
    attempts."""
    import app.routers.upload as upload_router
    monkeypatch.setattr(upload_router, "MAX_UPLOAD_SIZE_BYTES", 100)
    monkeypatch.setattr(upload_router, "UPLOAD_DIR", tmp_path)

    oversized_content = b"%PDF-1.4\n" + (b"x" * 500)
    client.post(
        "/statements/upload",
        files={"file": ("big.pdf", oversized_content, "application/pdf")},
        headers=auth_headers,
    )

    remaining_files = list(tmp_path.iterdir())
    assert remaining_files == [], f"Expected no leftover files, found: {remaining_files}"
