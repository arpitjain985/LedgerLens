"""
End-to-end test of the full classify pipeline: upload -> classify -> vendor
intelligence -> risk scoring -> correction flywheel -- all through real HTTP
routes, with ONLY the embedding model call mocked (via monkeypatch), since
that's the one piece that needs real internet access to download a model
this test environment can't reach. Everything else -- vendor extraction,
DB writes, risk scoring, the /vendors and /recurring-transactions endpoints,
and the correction flywheel actually persisting and being reused -- runs
for real.
"""
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from reportlab.pdfgen import canvas

from app.database import Base, get_db
from app.main import app
import app.routers.classify as classify_router
from app.services.classifier import ClassificationResult


@pytest.fixture
def client():
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

    # The background upload-processing task (see routers/upload.py) can't
    # participate in FastAPI's request-scoped dependency injection -- it
    # runs after the response is sent, using its own SessionLocal reference
    # by design. Patch that module-level reference directly so the
    # background task writes to the same in-memory test DB as the request,
    # instead of the real default database.
    import app.routers.upload as upload_router
    original_session_local = upload_router.SessionLocal
    upload_router.SessionLocal = TestSessionLocal

    with TestClient(app) as test_client:
        yield test_client

    upload_router.SessionLocal = original_session_local
    app.dependency_overrides.clear()


@pytest.fixture
def mock_classify(monkeypatch):
    """
    Replaces the real embedding-based classify_transaction with a simple
    rule so tests don't need internet access to download a model. Still
    respects correction memory for real, since that's implemented as a DB
    lookup this mock delegates to -- this is the actual piece we want to
    prove works, not something worth faking.
    """
    from app.services.classifier import _check_correction_memory

    def fake_classify(description, db=None, firm_id=None):
        if db is not None and firm_id is not None:
            from app.services.vendor_extraction import normalize_description
            remembered = _check_correction_memory(db, firm_id, normalize_description(description))
            if remembered:
                return ClassificationResult(remembered, 1.0, "correction_memory", "Matches a previous correction.")

        if "RENT" in description.upper():
            return ClassificationResult("RENT", 0.9, "embedding", "Test mock: contains RENT")
        if "SALARY" in description.upper():
            return ClassificationResult("SALARY", 0.9, "embedding", "Test mock: contains SALARY")
        return ClassificationResult("VENDOR_PAYMENT", 0.7, "embedding", "Test mock: default guess")

    monkeypatch.setattr(classify_router, "classify_transaction", fake_classify)


def _make_test_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica", 10)
    lines = [
        "01-07-2026 SALARY CREDIT NEFT FROM SHARMA TRADERS PAYROLL 48,000.00 CR",
        "02-07-2026 OFFICE RENT PAID TO LANDLORD GUPTA PROPERTIES 18,000.00 DR",
        "03-07-2026 PAYMENT TO SUPPLIER RAJ ELECTRICALS INV-2201 6,750.00 DR",
        "03-07-2026 PAYMENT TO SUPPLIER RAJ ELECTRICALS INV-2201 6,750.00 DR",
    ]
    y = 750
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def _get_auth_headers(client) -> dict:
    """
    Registers a test user once per TestClient instance and caches the token
    on the client object itself -- several tests call
    _upload_and_wait_for_completion more than once against the SAME client
    (e.g. to prove the correction flywheel across two separate uploads), so
    this must not try to register the same email twice.
    """
    if not hasattr(client, "_test_auth_headers"):
        resp = client.post("/auth/register", json={
            "email": "phase2test@example.com", "password": "testpassword123", "firm_name": "Phase2 Test Firm",
        })
        token = resp.json()["access_token"]
        client._test_auth_headers = {"Authorization": f"Bearer {token}"}
    return client._test_auth_headers


def _upload_and_wait_for_completion(client, pdf_bytes) -> str:
    headers = _get_auth_headers(client)
    resp = client.post("/statements/upload", files={"file": ("test.pdf", pdf_bytes, "application/pdf")}, headers=headers)
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # TestClient runs background tasks synchronously before returning the
    # response in recent FastAPI/Starlette versions, but poll defensively
    # in case that behavior changes.
    for _ in range(20):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] == "completed":
            return job["statement_id"]
        if job["status"] == "failed":
            pytest.fail(f"Upload job failed: {job.get('error_message')}")
    pytest.fail("Job did not complete in time")


def test_full_pipeline_vendor_extraction_and_risk_scoring(client, mock_classify):
    statement_id = _upload_and_wait_for_completion(client, _make_test_pdf())

    resp = client.post(f"/statements/{statement_id}/classify", headers=_get_auth_headers(client))
    assert resp.status_code == 200
    data = resp.json()

    assert data["classified_count"] == 4
    transactions = data["transactions"]

    # Vendor extraction ran
    rent_txn = next(t for t in transactions if t["predicted_ledger_head"] == "RENT")
    assert rent_txn["vendor"] is not None
    assert "Gupta" in rent_txn["vendor"]

    # Classification reason is populated (Section 7 explainability)
    assert rent_txn["classification_reason"] is not None

    # Risk scoring ran and produced valid bands
    for t in transactions:
        assert t["risk_score"] is not None
        assert 0 <= t["risk_score"] <= 100
        assert t["risk_level"] in ("Low", "Medium", "High", "Critical")

    # The duplicate Raj Electricals payments should score at least Medium
    duplicate_txns = [t for t in transactions if "RAJ ELECTRICALS" in t["description"]]
    assert len(duplicate_txns) == 2
    for t in duplicate_txns:
        assert t["risk_score"] >= 31


def test_vendor_endpoint_reflects_classified_data(client, mock_classify):
    statement_id = _upload_and_wait_for_completion(client, _make_test_pdf())
    client.post(f"/statements/{statement_id}/classify", headers=_get_auth_headers(client))

    resp = client.get("/vendors", headers=_get_auth_headers(client))
    assert resp.status_code == 200
    vendors = resp.json()
    assert len(vendors) > 0

    raj_vendor = next((v for v in vendors if "Raj Electricals" in v["vendor_name"]), None)
    assert raj_vendor is not None
    assert raj_vendor["transaction_count"] == 2
    assert raj_vendor["total_payments"] == 13500.0  # 6750 * 2


def test_correction_flywheel_applies_to_future_matching_transaction(client, mock_classify):
    """
    This is the real test of Section 8: correct one transaction, then upload
    a NEW statement with a similarly-worded transaction for the same vendor
    (different invoice number/amount/date) and confirm it gets classified
    from correction memory automatically -- not re-guessed.
    """
    statement_id = _upload_and_wait_for_completion(client, _make_test_pdf())
    classify_resp = client.post(f"/statements/{statement_id}/classify", headers=_get_auth_headers(client)).json()

    raj_txn = next(t for t in classify_resp["transactions"] if "RAJ ELECTRICALS" in t["description"])
    assert raj_txn["predicted_ledger_head"] == "VENDOR_PAYMENT"  # mock's default guess

    # Human corrects it to a more specific head
    correct_resp = client.post(
        f"/statements/{statement_id}/correct",
        json={"transaction_id": raj_txn["id"], "corrected_ledger_head": "OFFICE_SUPPLIES"},
        headers=_get_auth_headers(client),
    )
    assert correct_resp.status_code == 200

    # Upload a second statement with a similarly-worded transaction, same vendor
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica", 10)
    c.drawString(50, 750, "15-08-2026 PAYMENT TO SUPPLIER RAJ ELECTRICALS INV-9999 3,200.00 DR")
    c.save()

    statement_id_2 = _upload_and_wait_for_completion(client, buf.getvalue())
    classify_resp_2 = client.post(f"/statements/{statement_id_2}/classify", headers=_get_auth_headers(client)).json()

    assert classify_resp_2["correction_memory_count"] == 1
    new_txn = classify_resp_2["transactions"][0]
    assert new_txn["classification_method"] == "correction_memory"
    assert new_txn["predicted_ledger_head"] == "OFFICE_SUPPLIES"


def test_recurring_transactions_endpoint(client, mock_classify):
    """Uploads 3 statements each with a rent payment ~30 days apart and
    confirms the recurring-transactions endpoint picks up the pattern."""
    for date in ["02-05-2026", "02-06-2026", "03-07-2026"]:
        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.setFont("Helvetica", 10)
        c.drawString(50, 750, f"{date} OFFICE RENT PAID TO LANDLORD GUPTA PROPERTIES 18,000.00 DR")
        c.save()
        sid = _upload_and_wait_for_completion(client, buf.getvalue())
        client.post(f"/statements/{sid}/classify", headers=_get_auth_headers(client))

    resp = client.get("/recurring-transactions", headers=_get_auth_headers(client))
    assert resp.status_code == 200
    recurring = resp.json()
    assert len(recurring) == 1
    assert recurring[0]["occurrences"] == 3
    assert recurring[0]["frequency_label"] == "Monthly"
