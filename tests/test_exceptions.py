from app.exceptions import (
    LedgerLensError,
    UnsupportedFileTypeError,
    EncryptedPDFError,
    NoTransactionsFoundError,
    StatementNotFoundError,
)


def test_exception_has_status_code_and_user_message():
    exc = UnsupportedFileTypeError()
    assert exc.status_code == 400
    assert "PDF" in exc.user_message


def test_exception_custom_message_overrides_default():
    exc = LedgerLensError(user_message="Custom message")
    assert exc.user_message == "Custom message"


def test_encrypted_pdf_error_status_code():
    assert EncryptedPDFError().status_code == 400


def test_no_transactions_found_error_status_code():
    assert NoTransactionsFoundError().status_code == 422


def test_statement_not_found_status_code():
    assert StatementNotFoundError().status_code == 404
