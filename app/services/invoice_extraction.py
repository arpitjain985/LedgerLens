"""
Extracts structured fields from an invoice/receipt PDF (Section 6), including
GST-specific fields (Section 11): GSTIN, CGST/SGST/IGST, taxable value.

Like the bank statement parsers, this is a heuristic regex-based extractor,
not an ML model — Indian GST invoices follow a fairly consistent set of
labels ("GSTIN", "Invoice No", "Taxable Value", "CGST @ 9%", etc.) even
when overall layout varies, so targeted patterns get real signal without
needing training data.

Honest scope: this handles text-based (digital) PDF invoices via pdfplumber.
Scanned invoices fall back to the same Tesseract OCR path used for bank
statements. Extraction confidence is reported per-document based on how
many of the expected fields were actually found, so a human reviewer knows
at a glance whether to double check a given invoice.
"""
import re
from dataclasses import dataclass, field
from typing import Optional, List

import pdfplumber

from app.services.ocr import _extract_text_tesseract

GSTIN_PATTERN = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d])\b")
INVOICE_NUMBER_PATTERN = re.compile(
    r"(?:invoice\s*(?:no|number|#)|inv\s*(?:no|#))\s*[:.\-]?\s*([A-Z0-9\-/]{3,25})",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b")
AMOUNT_PATTERN = re.compile(r"[\d,]+\.\d{2}")

# Labeled amount fields -- captures the number following each label.
LABELED_AMOUNT_PATTERNS = {
    "taxable_amount": re.compile(r"taxable\s*(?:value|amount)\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
    "cgst": re.compile(r"cgst\s*(?:@\s*[\d.]+%)?\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
    "sgst": re.compile(r"sgst\s*(?:@\s*[\d.]+%)?\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
    "igst": re.compile(r"igst\s*(?:@\s*[\d.]+%)?\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
    "total_amount": re.compile(r"(?:grand\s*total|total\s*amount|invoice\s*total)\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+\.?\d*)", re.IGNORECASE),
}

VENDOR_LABEL_PATTERN = re.compile(r"(?:from|seller|vendor|supplier|billed\s*by)\s*[:\-]?\s*([A-Za-z][A-Za-z0-9&.,\s]{2,50})", re.IGNORECASE)
CUSTOMER_LABEL_PATTERN = re.compile(r"(?:to|buyer|customer|billed\s*to|bill\s*to)\s*[:\-]?\s*([A-Za-z][A-Za-z0-9&.,\s]{2,50})", re.IGNORECASE)


@dataclass
class InvoiceExtractionResult:
    vendor_name: Optional[str] = None
    customer_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    gstin_vendor: Optional[str] = None
    gstin_customer: Optional[str] = None
    taxable_amount: Optional[float] = None
    cgst: Optional[float] = None
    sgst: Optional[float] = None
    igst: Optional[float] = None
    total_amount: Optional[float] = None
    raw_text: str = ""
    used_ocr: bool = False
    fields_found: List[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        """
        Fraction of the expected core fields that were actually found.
        Deliberately simple and transparent -- a human reviewer can see
        exactly which fields are missing rather than trusting a black-box
        score (same explainability principle as Section 7's classification
        reasons).
        """
        core_fields = ["vendor_name", "invoice_number", "invoice_date", "total_amount"]
        found = sum(1 for f in core_fields if f in self.fields_found)
        return round(found / len(core_fields), 2)


def extract_invoice(file_path: str) -> InvoiceExtractionResult:
    text, used_ocr = _get_text(file_path)
    result = InvoiceExtractionResult(raw_text=text, used_ocr=used_ocr)

    _extract_gstins(text, result)
    _extract_invoice_number(text, result)
    _extract_dates(text, result)
    _extract_parties(text, result)
    _extract_amounts(text, result)

    return result


def _get_text(file_path: str) -> tuple:
    """Returns (text, used_ocr). Tries the digital text layer first, falls
    back to OCR if the PDF has no extractable text (scanned document)."""
    with pdfplumber.open(file_path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)

    if text.strip():
        return text, False

    return _extract_text_tesseract(file_path), True


def _extract_gstins(text: str, result: InvoiceExtractionResult) -> None:
    gstins = GSTIN_PATTERN.findall(text)
    if len(gstins) >= 1:
        result.gstin_vendor = gstins[0]
        result.fields_found.append("gstin_vendor")
    if len(gstins) >= 2:
        result.gstin_customer = gstins[1]
        result.fields_found.append("gstin_customer")


def _extract_invoice_number(text: str, result: InvoiceExtractionResult) -> None:
    match = INVOICE_NUMBER_PATTERN.search(text)
    if match:
        result.invoice_number = match.group(1).strip()
        result.fields_found.append("invoice_number")


def _extract_dates(text: str, result: InvoiceExtractionResult) -> None:
    dates = DATE_PATTERN.findall(text)
    if len(dates) >= 1:
        result.invoice_date = dates[0]
        result.fields_found.append("invoice_date")
    if len(dates) >= 2:
        # Second date on an invoice is very commonly the due date.
        result.due_date = dates[1]
        result.fields_found.append("due_date")


def _extract_parties(text: str, result: InvoiceExtractionResult) -> None:
    vendor_match = VENDOR_LABEL_PATTERN.search(text)
    if vendor_match:
        result.vendor_name = _clean_party_name(vendor_match.group(1))
        result.fields_found.append("vendor_name")

    customer_match = CUSTOMER_LABEL_PATTERN.search(text)
    if customer_match:
        result.customer_name = _clean_party_name(customer_match.group(1))
        result.fields_found.append("customer_name")


def _clean_party_name(raw: str) -> str:
    # Stop at the first newline-equivalent boundary -- these patterns can
    # over-match into the next line's label since we search plain text.
    cleaned = re.split(r"\s{2,}|\n", raw)[0].strip(" ,.")
    return cleaned


def _extract_amounts(text: str, result: InvoiceExtractionResult) -> None:
    for field_name, pattern in LABELED_AMOUNT_PATTERNS.items():
        match = pattern.search(text)
        if match:
            try:
                value = float(match.group(1).replace(",", ""))
                setattr(result, field_name, value)
                result.fields_found.append(field_name)
            except ValueError:
                continue
