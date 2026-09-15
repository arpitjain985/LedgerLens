import shutil
import uuid

from fastapi import APIRouter, UploadFile, File, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import Statement, Transaction, Job
from app.schemas import StatementUploadResponse
from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE_BYTES
from app.exceptions import UnsupportedFileTypeError, LedgerLensError, FileTooLargeError
from app.services.pdf_parser import parse_statement
from app.services import job_manager
from app.services.auth import get_current_user, CurrentUser

def _save_upload_with_size_limit(file: UploadFile, dest_path) -> None:
    """
    Streams the upload to disk in chunks, aborting (and cleaning up the
    partial file) as soon as the configured size limit is exceeded --
    rather than reading the whole thing into memory first, which would let
    an oversized upload consume memory before the limit check ever runs.
    Section 22 explicitly requires file size limits on uploads.
    """
    total_bytes = 0
    chunk_size = 1024 * 1024  # 1MB chunks
    with open(dest_path, "wb") as f:
        while chunk := file.file.read(chunk_size):
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_SIZE_BYTES:
                f.close()
                dest_path.unlink(missing_ok=True)
                raise FileTooLargeError(
                    detail=f"Upload exceeded {MAX_UPLOAD_SIZE_BYTES} bytes limit"
                )
            f.write(chunk)


router = APIRouter(prefix="/statements", tags=["upload"])


@router.post("/upload", response_model=StatementUploadResponse)
async def upload_statement(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns immediately with a job_id. Parsing/OCR runs in the background --
    poll GET /jobs/{job_id} for progress instead of waiting on this request.
    This is the Section 4 fix: uploads no longer block for several minutes.

    Migrated to auth (Section 20/22): firm_id now comes from the validated
    JWT, not a client-supplied query parameter -- a user can only ever
    upload into their own firm's data, never anyone else's.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise UnsupportedFileTypeError()

    firm_id = current_user.firm_id

    dest_path = UPLOAD_DIR / f"{uuid.uuid4()}_{file.filename}"
    _save_upload_with_size_limit(file, dest_path)

    job = job_manager.create_job(db, job_type="statement_upload")

    background_tasks.add_task(
        _process_statement_background,
        job_id=job.id,
        file_path=str(dest_path),
        filename=file.filename,
        firm_id=firm_id,
    )

    return StatementUploadResponse(
        statement_id="",       # not yet known -- populated once the job completes
        filename=file.filename,
        transactions_found=0,  # not yet known -- poll the job for the real count
        status="queued",
        job_id=job.id,
    )


def _process_statement_background(job_id: str, file_path: str, filename: str, firm_id: str) -> None:
    """
    Runs in the background after the HTTP response has already been sent.
    Uses its own DB session -- the request-scoped `db` dependency is closed
    by the time this executes.
    """
    db = SessionLocal()
    try:
        job_manager.update_progress(db, job_id, 20, "Parsing PDF...")
        bank_code, transactions, used_ocr = parse_statement(file_path)

        job_manager.update_progress(db, job_id, 60, f"Extracted {len(transactions)} transactions...")

        statement = Statement(
            firm_id=firm_id,
            filename=filename,
            bank_name=bank_code,
            used_ocr=used_ocr,
            status="parsed",
        )
        db.add(statement)
        db.flush()

        for txn in transactions:
            db.add(Transaction(
                statement_id=statement.id,
                txn_date=txn.date,
                description=txn.description,
                amount=txn.amount,
                txn_type=txn.transaction_type,
                debit=txn.debit,
                credit=txn.credit,
                balance=txn.balance,
                reference_number=txn.reference_number,
                payment_mode=txn.payment_mode,
                vendor=txn.vendor,
            ))
        db.commit()

        job_manager.update_progress(db, job_id, 90, "Finalizing...")
        job_manager.mark_completed(db, job_id, statement_id=statement.id)

    except LedgerLensError as e:
        job_manager.mark_failed(db, job_id, user_message=e.user_message, detail=e.detail)
    except Exception as e:
        job_manager.mark_failed(
            db, job_id,
            user_message="An unexpected error occurred while processing this statement.",
            detail=str(e),
        )
    finally:
        db.close()
