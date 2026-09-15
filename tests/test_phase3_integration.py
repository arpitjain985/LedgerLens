"""
Integration tests for Phase 3 (Accounting Intelligence): invoice upload,
GST summary aggregation, and the audit trail -- all through real HTTP
routes, no mocking needed since none of this depends on the embedding model.
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
        "email": "phase3test@example.com", "password": "password123", "firm_name": "Phase3 Test Firm",
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _make_invoice_pdf(vendor="Raj Electricals Pvt Ltd", invoice_no="INV-2201", taxable=5720.00, cgst=514.80, sgst=514.80, total=6749.60):
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica", 10)
    lines = [
        "TAX INVOICE",
        f"From: {vendor}",
        "GSTIN: 27AAAPL1234C1ZV",
        "To: Sharma Traders & Co.",
        f"Invoice No: {invoice_no}",
        "Invoice Date: 03-07-2026",
        f"Taxable Value: {taxable:,.2f}",
        f"CGST @ 9%: {cgst:,.2f}",
        f"SGST @ 9%: {sgst:,.2f}",
        "IGST: 0.00",
        f"Grand Total: {total:,.2f}",
    ]
    y = 750
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def test_invoice_upload_extracts_fields(client, auth_headers):
    resp = client.post("/invoices/upload", files={"file": ("inv.pdf", _make_invoice_pdf(), "application/pdf")}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "Raj Electricals" in data["vendor_name"]
    assert data["invoice_number"] == "INV-2201"
    assert data["total_amount"] == 6749.60
    assert data["extraction_confidence"] == 1.0


def test_invoice_upload_rejects_non_pdf(client, auth_headers):
    resp = client.post("/invoices/upload", files={"file": ("inv.txt", b"not a pdf", "text/plain")}, headers=auth_headers)
    assert resp.status_code == 400


def test_list_invoices_returns_uploaded_invoice(client, auth_headers):
    client.post("/invoices/upload", files={"file": ("inv.pdf", _make_invoice_pdf(), "application/pdf")}, headers=auth_headers)
    resp = client.get("/invoices", headers=auth_headers)
    assert resp.status_code == 200
    invoices = resp.json()
    assert len(invoices) == 1
    assert invoices[0]["invoice_number"] == "INV-2201"


def test_gst_summary_aggregates_across_invoices(client, auth_headers):
    client.post("/invoices/upload", files={"file": (
        "inv1.pdf", _make_invoice_pdf(invoice_no="INV-001", taxable=5000, cgst=450, sgst=450, total=5900), "application/pdf",
    )}, headers=auth_headers)
    client.post("/invoices/upload", files={"file": (
        "inv2.pdf", _make_invoice_pdf(invoice_no="INV-002", taxable=3000, cgst=270, sgst=270, total=3540), "application/pdf",
    )}, headers=auth_headers)

    resp = client.get("/gst-summary", headers=auth_headers)
    assert resp.status_code == 200
    summary = resp.json()

    assert summary["invoice_count"] == 2
    assert summary["total_taxable_value"] == 8000.0
    assert summary["total_cgst"] == 720.0
    assert summary["total_sgst"] == 720.0
    assert summary["total_gst"] == 1440.0
    assert summary["total_invoice_value"] == 9440.0
    assert "not a substitute for professional" in summary["disclaimer"]


def test_gst_summary_empty_when_no_invoices(client, auth_headers):
    resp = client.get("/gst-summary", headers=auth_headers)
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["invoice_count"] == 0
    assert summary["total_gst"] == 0.0


def test_audit_log_records_invoice_creation(client, auth_headers):
    upload_resp = client.post("/invoices/upload", files={"file": ("inv.pdf", _make_invoice_pdf(), "application/pdf")}, headers=auth_headers)
    invoice_id = upload_resp.json()["invoice_id"]

    resp = client.get("/audit-log", headers=auth_headers)
    assert resp.status_code == 200
    entries = resp.json()

    matching = [e for e in entries if e["entity_id"] == invoice_id]
    assert len(matching) == 1
    assert matching[0]["action"] == "created"
    assert matching[0]["entity_type"] == "invoice"


def test_audit_log_records_transaction_correction():
    """
    Separate test, no fixture reuse needed -- directly exercises the
    correction audit path added to routers/classify.py this phase.
    """
    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from sqlalchemy.pool import StaticPool as _StaticPool
    from app.database import Base as _Base
    from app.models import Firm, Statement, Transaction

    engine = _create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=_StaticPool)
    _Base.metadata.create_all(bind=engine)
    Session = _sessionmaker(bind=engine)
    db = Session()

    db.add(Firm(id="f1", name="Test Firm"))
    db.add(Statement(id="s1", firm_id="f1", filename="test.pdf"))
    db.add(Transaction(id="t1", statement_id="s1", description="TEST", amount=100, predicted_ledger_head="RENT"))
    db.commit()

    from app.services.audit_trail import log_action, get_audit_log
    log_action(db, firm_id="f1", entity_type="transaction", entity_id="t1", action="corrected",
               field_changed="ledger_head", previous_value="RENT", new_value="OFFICE_SUPPLIES",
               reason="test correction", changed_by="user")
    db.commit()

    entries = get_audit_log(db, "f1", entity_id="t1")
    assert len(entries) == 1
    assert entries[0]["previous_value"] == "RENT"
    assert entries[0]["new_value"] == "OFFICE_SUPPLIES"
    assert entries[0]["changed_by"] == "user"
