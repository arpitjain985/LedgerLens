"""
Tests for the invite-teammate flow (Section 19/20). Proves the two things
that actually matter here: (1) a real second user can be created and log
in through this flow, not just a database row, and (2) you genuinely
cannot invite someone to a role more privileged than your own, even if you
meet the endpoint's floor requirement.
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
        test_client._session_local = TestSessionLocal
        yield test_client
    app.dependency_overrides.clear()


def test_super_admin_can_invite_and_invitee_can_accept_and_login(client):
    owner_data = client.post("/auth/register", json={
        "email": "owner@teamtest.com", "password": "password123", "firm_name": "Team Test Firm",
    }).json()
    owner_token = owner_data["access_token"]

    # Capture the raw token the way a real invitee would -- by intercepting
    # what send_invite_email would have emailed, via monkeypatching in this
    # test rather than reading the (deliberately unrecoverable) hash from the DB.
    captured = {}
    import app.routers.users as users_router
    original_send = users_router.send_invite_email

    def fake_send(to_email, raw_token, firm_name, role):
        captured["token"] = raw_token

    users_router.send_invite_email = fake_send
    try:
        invite_resp = client.post(
            "/users/invite", json={"email": "teammate@teamtest.com", "role": "ACCOUNTANT"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    finally:
        users_router.send_invite_email = original_send

    assert invite_resp.status_code == 200
    assert "token" in captured

    accept_resp = client.post("/auth/accept-invite", json={
        "token": captured["token"], "password": "teammatepass123", "full_name": "Teammate Name",
    })
    assert accept_resp.status_code == 200
    accept_data = accept_resp.json()
    assert accept_data["role"] == "ACCOUNTANT"
    assert accept_data["firm_id"] == owner_data["firm_id"]  # same firm as the inviter

    # The new teammate can now log in independently with their own password.
    login_resp = client.post("/auth/login", json={"email": "teammate@teamtest.com", "password": "teammatepass123"})
    assert login_resp.status_code == 200


def test_accountant_cannot_invite_anyone_role_too_low_for_endpoint(client):
    """ACCOUNTANT sits below the CA_AUDITOR floor required just to call
    /users/invite at all."""
    owner_token = client.post("/auth/register", json={
        "email": "owner2@teamtest.com", "password": "password123", "firm_name": "Firm Two",
    }).json()["access_token"]

    # Directly insert an ACCOUNTANT-role user for this firm (same pattern
    # as tests/test_rbac.py, since there's no lower-privilege invite flow
    # to bootstrap one through yet).
    import app.routers.upload as upload_router
    from app.models import User
    from app.services.auth import hash_password, create_access_token
    db = upload_router.SessionLocal()
    owner_data = client.post("/auth/login", json={"email": "owner2@teamtest.com", "password": "password123"}).json()
    firm_id = owner_data["firm_id"]
    accountant = User(firm_id=firm_id, email="accountant@teamtest.com", hashed_password=hash_password("pass123"), role="ACCOUNTANT")
    db.add(accountant)
    db.commit()
    accountant_token = create_access_token(user_id=accountant.id, firm_id=firm_id, role="ACCOUNTANT")
    db.close()

    resp = client.post(
        "/users/invite", json={"email": "newperson@teamtest.com", "role": "VIEWER"},
        headers={"Authorization": f"Bearer {accountant_token}"},
    )
    assert resp.status_code == 403


def test_cannot_invite_someone_to_a_role_higher_than_your_own(client):
    """
    A CA_AUDITOR meets the endpoint's floor requirement, but must NOT be
    able to grant SUPER_ADMIN -- a role more privileged than their own.
    This is the real test of create_invite()'s own internal check, separate
    from the endpoint's coarser require_role("CA_AUDITOR") floor.
    """
    owner_data = client.post("/auth/register", json={
        "email": "owner3@teamtest.com", "password": "password123", "firm_name": "Firm Three",
    }).json()

    import app.routers.upload as upload_router
    from app.models import User
    from app.services.auth import hash_password, create_access_token
    db = upload_router.SessionLocal()
    auditor = User(firm_id=owner_data["firm_id"], email="auditor@teamtest.com", hashed_password=hash_password("pass123"), role="CA_AUDITOR")
    db.add(auditor)
    db.commit()
    auditor_token = create_access_token(user_id=auditor.id, firm_id=owner_data["firm_id"], role="CA_AUDITOR")
    db.close()

    resp = client.post(
        "/users/invite", json={"email": "wannabe-admin@teamtest.com", "role": "SUPER_ADMIN"},
        headers={"Authorization": f"Bearer {auditor_token}"},
    )
    assert resp.status_code == 403


def test_cannot_invite_email_that_already_has_an_account(client):
    client.post("/auth/register", json={"email": "existing@teamtest.com", "password": "password123", "firm_name": "Firm A"})
    owner_token = client.post("/auth/register", json={"email": "owner4@teamtest.com", "password": "password123", "firm_name": "Firm B"}).json()["access_token"]

    resp = client.post(
        "/users/invite", json={"email": "existing@teamtest.com", "role": "VIEWER"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 400


def test_expired_invite_token_rejected_directly():
    """Direct service-level test using a manually-backdated invite, same
    pattern as the password reset expiry test."""
    from datetime import datetime, timedelta
    import hashlib
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    from app.models import Firm, User, Invite
    from app.services.auth import hash_password
    from app.services.invite import accept_invite, InvalidInviteTokenError

    firm = Firm(id="f1", name="Expiry Firm")
    db.add(firm)
    owner = User(id="u1", firm_id="f1", email="owner@expiry.com", hashed_password=hash_password("pass123"), role="SUPER_ADMIN")
    db.add(owner)

    raw_token = "test-invite-raw-token"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    db.add(Invite(
        firm_id="f1", email="invitee@expiry.com", role="VIEWER", invited_by_user_id="u1",
        token_hash=token_hash, expires_at=datetime.utcnow() - timedelta(hours=1),
    ))
    db.commit()

    with pytest.raises(InvalidInviteTokenError):
        accept_invite(db, raw_token, password="newpass123")


def test_invite_is_single_use(client):
    owner_data = client.post("/auth/register", json={"email": "owner5@teamtest.com", "password": "password123", "firm_name": "Firm Five"}).json()

    from app.services.invite import create_invite
    db = client._session_local()
    raw_token = create_invite(db, firm_id=owner_data["firm_id"], email="onetime@teamtest.com", role="VIEWER",
                               invited_by_user_id="doesnt-matter-for-this-test", inviter_role="SUPER_ADMIN")
    db.close()

    first = client.post("/auth/accept-invite", json={"token": raw_token, "password": "pass123456"})
    assert first.status_code == 200

    second = client.post("/auth/accept-invite", json={"token": raw_token, "password": "differentpass123"})
    assert second.status_code == 400


def test_list_team_shows_all_firm_members(client):
    owner_token = client.post("/auth/register", json={"email": "owner6@teamtest.com", "password": "password123", "firm_name": "Firm Six"}).json()["access_token"]

    resp = client.get("/users", headers={"Authorization": f"Bearer {owner_token}"})
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) == 1
    assert users[0]["email"] == "owner6@teamtest.com"
    assert users[0]["role"] == "SUPER_ADMIN"
