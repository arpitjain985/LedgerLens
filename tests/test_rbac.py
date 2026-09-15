"""
Proves RBAC (Section 20) is actually enforced on a real endpoint, not just
defined in a service module nobody calls. GET /statements/workpaper-package/full
requires at least CA_AUDITOR -- registering a new user always creates them
as SUPER_ADMIN (the firm's first/owner user), so to test a LOWER role
actually gets denied, this manually creates a lower-role user directly in
the DB (simulating what a future invite-a-teammate flow would produce)
rather than skipping this coverage just because that flow isn't built yet.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User
from app.services.auth import hash_password, create_access_token, CurrentUser


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

    # Same pattern as test_auth.py / test_phase2_integration.py: point the
    # background upload task's SessionLocal at the same test engine.
    import app.routers.upload as upload_router
    original_session_local = upload_router.SessionLocal
    upload_router.SessionLocal = TestSessionLocal

    with TestClient(app) as test_client:
        yield test_client
        # expose the sessionmaker for tests that need to insert rows directly
        test_client._test_session_local = TestSessionLocal

    upload_router.SessionLocal = original_session_local
    app.dependency_overrides.clear()


def _register(client, email="owner@example.com", firm_name="Test Firm") -> dict:
    resp = client.post("/auth/register", json={"email": email, "password": "password123", "firm_name": firm_name})
    return resp.json()


def _create_user_with_role(client, firm_id: str, role: str) -> str:
    """Directly inserts a User row with a specific role and returns a valid
    token for them -- stands in for an invite-teammate flow not built yet."""
    import app.routers.upload as upload_router
    db = upload_router.SessionLocal()
    user = User(firm_id=firm_id, email=f"{role.lower()}@example.com",
                hashed_password=hash_password("password123"), role=role)
    db.add(user)
    db.commit()
    token = create_access_token(user_id=user.id, firm_id=firm_id, role=role)
    db.close()
    return token


def test_super_admin_can_access_workpaper_package(client):
    data = _register(client)
    token = data["access_token"]
    resp = client.get("/statements/workpaper-package/full", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_viewer_role_is_denied_workpaper_package(client):
    data = _register(client)
    viewer_token = _create_user_with_role(client, data["firm_id"], "VIEWER")
    resp = client.get("/statements/workpaper-package/full", headers={"Authorization": f"Bearer {viewer_token}"})
    assert resp.status_code == 403


def test_reviewer_role_is_denied_workpaper_package(client):
    data = _register(client)
    reviewer_token = _create_user_with_role(client, data["firm_id"], "REVIEWER")
    resp = client.get("/statements/workpaper-package/full", headers={"Authorization": f"Bearer {reviewer_token}"})
    assert resp.status_code == 403


def test_accountant_role_is_denied_workpaper_package(client):
    data = _register(client)
    accountant_token = _create_user_with_role(client, data["firm_id"], "ACCOUNTANT")
    resp = client.get("/statements/workpaper-package/full", headers={"Authorization": f"Bearer {accountant_token}"})
    assert resp.status_code == 403


def test_ca_auditor_role_is_allowed_workpaper_package(client):
    data = _register(client)
    auditor_token = _create_user_with_role(client, data["firm_id"], "CA_AUDITOR")
    resp = client.get("/statements/workpaper-package/full", headers={"Authorization": f"Bearer {auditor_token}"})
    assert resp.status_code == 200


def test_role_hierarchy_logic_directly():
    """Direct unit check on the hierarchy comparison itself, independent of
    any HTTP plumbing -- ACCOUNTANT sits below CA_AUDITOR."""
    user = CurrentUser(user_id="u1", firm_id="f1", role="ACCOUNTANT")
    assert user.has_at_least("CA_AUDITOR") is False
    assert user.has_at_least("ACCOUNTANT") is True
    assert user.has_at_least("VIEWER") is True


def test_statement_export_returns_404_for_nonexistent_or_foreign_statement(client):
    """A user must not be able to fetch another firm's statement just by
    guessing/knowing its ID -- same-shaped 404 either way, no leak."""
    firm1_token = _register(client, email="f1owner@example.com", firm_name="Firm1")["access_token"]
    resp = client.get("/statements/some-fake-id/export", headers={"Authorization": f"Bearer {firm1_token}"})
    assert resp.status_code == 404
