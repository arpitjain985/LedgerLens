import uuid
from typing import List

from fastapi import APIRouter, UploadFile, File, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Invoice
from app.schemas import InvoiceUploadResponse
from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE_BYTES
from app.exceptions import UnsupportedFileTypeError, EmptyOrCorruptFileError, FileTooLargeError
from app.services.invoice_extraction import extract_invoice
from app.services.audit_trail import log_action
from app.services.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _save_upload_with_size_limit(file: UploadFile, dest_path) -> None:
    """Same streaming size-limit pattern as routers/upload.py -- this file
    never had it, a real gap fixed while migrating to auth."""
    total_bytes = 0
    chunk_size = 1024 * 1024
    with open(dest_path, "wb") as f:
        while chunk := file.file.read(chunk_size):
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_SIZE_BYTES:
                f.close()
                dest_path.unlink(missing_ok=True)
                raise FileTooLargeError(detail=f"Upload exceeded {MAX_UPLOAD_SIZE_BYTES} bytes limit")
            f.write(chunk)


@router.post("/upload", response_model=InvoiceUploadResponse)
def upload_invoice(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Extracts structured fields from an invoice/receipt PDF (Section 6) and
    stores them. Runs synchronously (unlike statement upload) since regex
    extraction over a single document's text is fast -- the one honest
    caveat is a scanned invoice needing OCR could take a few seconds, which
    is an acceptable synchronous wait for a single-document upload but a
    documented gap if this needs true async handling later (see PROGRESS.md).

    Migrated to auth: firm_id comes from the JWT.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise UnsupportedFileTypeError()

    firm_id = current_user.firm_id

    dest_path = UPLOAD_DIR / f"{uuid.uuid4()}_{file.filename}"
    _save_upload_with_size_limit(file, dest_path)

    try:
        result = extract_invoice(str(dest_path))
    except Exception as e:
        raise EmptyOrCorruptFileError(detail=str(e))

    invoice = Invoice(
        firm_id=firm_id,
        filename=file.filename,
        used_ocr=result.used_ocr,
        vendor_name=result.vendor_name,
        customer_name=result.customer_name,
        invoice_number=result.invoice_number,
        invoice_date=result.invoice_date,
        due_date=result.due_date,
        gstin_vendor=result.gstin_vendor,
        gstin_customer=result.gstin_customer,
        taxable_amount=result.taxable_amount,
        cgst=result.cgst,
        sgst=result.sgst,
        igst=result.igst,
        total_amount=result.total_amount,
        extraction_confidence=result.confidence,
        raw_text=result.raw_text[:5000],
    )
    db.add(invoice)
    db.flush()

    log_action(
        db, firm_id=firm_id, entity_type="invoice", entity_id=invoice.id,
        action="created", reason=f"Extracted from uploaded document (confidence={result.confidence})",
        changed_by=current_user.user_id,
    )
    db.commit()
    db.refresh(invoice)

    return InvoiceUploadResponse(
        invoice_id=invoice.id,
        filename=invoice.filename,
        vendor_name=invoice.vendor_name,
        customer_name=invoice.customer_name,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        gstin_vendor=invoice.gstin_vendor,
        gstin_customer=invoice.gstin_customer,
        taxable_amount=invoice.taxable_amount,
        cgst=invoice.cgst,
        sgst=invoice.sgst,
        igst=invoice.igst,
        total_amount=invoice.total_amount,
        extraction_confidence=invoice.extraction_confidence,
        used_ocr=invoice.used_ocr,
    )


@router.get("", response_model=List[InvoiceUploadResponse])
def list_invoices(current_user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    invoices = (
        db.query(Invoice)
        .filter(Invoice.firm_id == current_user.firm_id)
        .order_by(Invoice.uploaded_at.desc())
        .all()
    )
    return [
        InvoiceUploadResponse(
            invoice_id=i.id, filename=i.filename, vendor_name=i.vendor_name,
            customer_name=i.customer_name, invoice_number=i.invoice_number,
            invoice_date=i.invoice_date, due_date=i.due_date,
            gstin_vendor=i.gstin_vendor, gstin_customer=i.gstin_customer,
            taxable_amount=i.taxable_amount, cgst=i.cgst, sgst=i.sgst, igst=i.igst,
            total_amount=i.total_amount, extraction_confidence=i.extraction_confidence or 0.0,
            used_ocr=i.used_ocr,
        )
        for i in invoices
    ]
