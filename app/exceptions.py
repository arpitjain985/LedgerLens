"""
Custom exceptions with user-friendly messages, per Section 23 of the V2 spec.

Design: every exception carries a `user_message` (safe to show directly in
the UI) separate from the internal `detail` (safe to log, may contain more
technical context). This is caught centrally in main.py's exception handler
so routers don't need repetitive try/except blocks for the common cases.
"""


class LedgerLensError(Exception):
    """Base class for all LedgerLens application errors."""
    status_code = 500
    user_message = "Something went wrong while processing your request."

    def __init__(self, user_message: str = None, detail: str = None):
        self.user_message = user_message or self.user_message
        self.detail = detail or self.user_message
        super().__init__(self.detail)


class UnsupportedFileTypeError(LedgerLensError):
    status_code = 400
    user_message = "Only PDF files are supported. Please upload a PDF bank statement."


class EmptyOrCorruptFileError(LedgerLensError):
    status_code = 400
    user_message = (
        "This file couldn't be read — it may be corrupted, empty, or password-protected. "
        "Try re-exporting the statement from your bank's portal."
    )


class EncryptedPDFError(LedgerLensError):
    status_code = 400
    user_message = (
        "This PDF is password-protected. Please remove the password before uploading "
        "(most bank portals let you re-download an unprotected copy, or use a PDF tool "
        "to remove the password if you already know it)."
    )


class NoTransactionsFoundError(LedgerLensError):
    status_code = 422
    user_message = (
        "No transactions could be extracted from this statement. This usually means the "
        "PDF layout isn't recognized yet — if this is a scanned/photographed statement, "
        "OCR may have failed on it (try a clearer scan), or the bank's format isn't "
        "supported yet and fell through to the generic parser without matching anything."
    )


class OCRUnavailableError(LedgerLensError):
    status_code = 503
    user_message = (
        "OCR processing is unavailable right now. If you're running locally, confirm "
        "Tesseract and Poppler are installed and on your PATH (see README)."
    )


class ClassificationModelUnavailableError(LedgerLensError):
    status_code = 503
    user_message = (
        "The classification model couldn't be loaded. On first run this needs a one-time "
        "internet connection to download it (~80MB) — check your connection and try again."
    )


class StatementNotFoundError(LedgerLensError):
    status_code = 404
    user_message = "Statement not found. It may have been deleted, or the ID is incorrect."


class JobNotFoundError(LedgerLensError):
    status_code = 404
    user_message = "Job not found. It may have expired, or the ID is incorrect."


class NoTransactionsToClassifyError(LedgerLensError):
    status_code = 400
    user_message = "No transactions to classify — upload and parse a statement first."


class TransactionNotFoundError(LedgerLensError):
    status_code = 404
    user_message = "Transaction not found for this statement."


class FileTooLargeError(LedgerLensError):
    status_code = 413
    user_message = "This file is too large. Please upload a smaller file."
