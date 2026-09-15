import pytest
from reportlab.pdfgen import canvas

from app.services.invoice_extraction import extract_invoice


def _make_pdf(path, lines):
    c = canvas.Canvas(path)
    c.setFont("Helvetica", 10)
    y = 750
    for line in lines:
        c.drawString(50, y, line)
        y -= 20
    c.save()


@pytest.fixture
def full_gst_invoice(tmp_path):
    path = str(tmp_path / "invoice.pdf")
    _make_pdf(path, [
        "TAX INVOICE",
        "From: Raj Electricals Pvt Ltd",
        "GSTIN: 27AAAPL1234C1ZV",
        "To: Sharma Traders & Co.",
        "GSTIN: 07BBBPL5678D1ZK",
        "Invoice No: INV-2201",
        "Invoice Date: 03-07-2026",
        "Due Date: 17-07-2026",
        "Taxable Value: 5,720.00",
        "CGST @ 9%: 514.80",
        "SGST @ 9%: 514.80",
        "IGST: 0.00",
        "Grand Total: 6,749.60",
    ])
    return path


@pytest.fixture
def sparse_receipt(tmp_path):
    path = str(tmp_path / "receipt.pdf")
    _make_pdf(path, ["RECEIPT", "Some purchase, no structured fields", "Thanks"])
    return path


def test_extracts_all_core_fields_from_full_invoice(full_gst_invoice):
    result = extract_invoice(full_gst_invoice)
    assert result.vendor_name is not None and "Raj Electricals" in result.vendor_name
    assert result.invoice_number == "INV-2201"
    assert result.invoice_date == "03-07-2026"
    assert result.due_date == "17-07-2026"
    assert result.total_amount == 6749.60


def test_extracts_gstin_for_both_parties(full_gst_invoice):
    result = extract_invoice(full_gst_invoice)
    assert result.gstin_vendor == "27AAAPL1234C1ZV"
    assert result.gstin_customer == "07BBBPL5678D1ZK"


def test_extracts_gst_breakdown(full_gst_invoice):
    result = extract_invoice(full_gst_invoice)
    assert result.taxable_amount == 5720.00
    assert result.cgst == 514.80
    assert result.sgst == 514.80
    assert result.igst == 0.00


def test_full_invoice_has_high_confidence(full_gst_invoice):
    result = extract_invoice(full_gst_invoice)
    assert result.confidence == 1.0


def test_sparse_document_returns_none_fields_not_false_positives(sparse_receipt):
    """A document with nothing structured to extract must honestly report
    that -- not guess or hallucinate a vendor/amount."""
    result = extract_invoice(sparse_receipt)
    assert result.vendor_name is None
    assert result.invoice_number is None
    assert result.total_amount is None
    assert result.confidence == 0.0


def test_gst_breakdown_sums_to_total_on_clean_invoice(full_gst_invoice):
    """Sanity check that the extracted GST breakdown is internally
    consistent -- not required by the extractor, but a useful signal that
    the right numbers were captured, not numbers from the wrong lines."""
    result = extract_invoice(full_gst_invoice)
    computed_total = result.taxable_amount + result.cgst + result.sgst + result.igst
    assert abs(computed_total - result.total_amount) < 0.01
