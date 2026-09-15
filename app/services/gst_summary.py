"""
GST summary generation (Section 11). Aggregates GST figures across all
invoices stored for a firm, and classifies each invoice's likely tax
treatment. Per the spec's explicit instruction, this NEVER presents itself
as legally authoritative -- every summary is labeled as requiring
professional verification.
"""
from typing import List

from sqlalchemy.orm import Session

from app.models import Invoice


def get_gst_summary(db: Session, firm_id: str) -> dict:
    invoices = (
        db.query(Invoice)
        .filter(Invoice.firm_id == firm_id, Invoice.total_amount.isnot(None))
        .all()
    )

    total_taxable_value = sum(i.taxable_amount or 0 for i in invoices)
    total_cgst = sum(i.cgst or 0 for i in invoices)
    total_sgst = sum(i.sgst or 0 for i in invoices)
    total_igst = sum(i.igst or 0 for i in invoices)
    total_gst = total_cgst + total_sgst + total_igst
    total_invoice_value = sum(i.total_amount or 0 for i in invoices)

    low_confidence_count = sum(1 for i in invoices if (i.extraction_confidence or 0) < 0.5)

    return {
        "invoice_count": len(invoices),
        "total_taxable_value": round(total_taxable_value, 2),
        "total_cgst": round(total_cgst, 2),
        "total_sgst": round(total_sgst, 2),
        "total_igst": round(total_igst, 2),
        "total_gst": round(total_gst, 2),
        "total_invoice_value": round(total_invoice_value, 2),
        "potential_input_tax_credit": round(total_gst, 2),  # see disclaimer below
        "low_confidence_invoice_count": low_confidence_count,
        "disclaimer": (
            "These figures are computed from automated document extraction and are "
            "provided for review purposes only. They are not a substitute for "
            "professional GST filing advice and must be verified by a qualified "
            "professional before use in any tax filing."
        ),
    }


def classify_expense_type(invoice: Invoice) -> str:
    """
    Best-effort classification for whether an invoice looks like a business
    expense, per Section 11. Deliberately conservative -- returns
    "Unclassified" rather than guessing when there isn't enough signal,
    since a wrong business/personal classification has real tax
    consequences (see the module docstring's disclaimer principle).
    """
    if invoice.gstin_vendor and invoice.taxable_amount:
        return "Likely business expense (has GSTIN and taxable value — verify before filing)"
    if invoice.total_amount and not invoice.gstin_vendor:
        return "Unclassified — no GSTIN detected, verify manually"
    return "Unclassified — insufficient data extracted"
