"""
Top-level statement parsing entry point. Decides digital-text vs scanned/OCR
path, detects the bank, and raises specific errors (Section 23) instead of
generic failures.
"""
from typing import List, Tuple

import pdfplumber

from app.exceptions import (
    EmptyOrCorruptFileError,
    EncryptedPDFError,
    NoTransactionsFoundError,
    OCRUnavailableError,
)
from app.services.bank_detector import detect_and_parse
from app.services.parsers.base import NormalizedTransaction
from app.services.ocr import extract_transactions_from_scan


def parse_statement(file_path: str) -> Tuple[str, List[NormalizedTransaction], bool]:
    """
    Returns (bank_code, transactions, used_ocr).
    Raises EncryptedPDFError / EmptyOrCorruptFileError / NoTransactionsFoundError
    / OCRUnavailableError as appropriate -- callers should let these propagate
    up to the central exception handler in main.py rather than catching them.
    """
    _validate_pdf_readable(file_path)

    bank_code, transactions = detect_and_parse(file_path)
    used_ocr = False

    if not transactions:
        # Digital text layer produced nothing -- this is the standard signal
        # that the PDF is a scanned/image-based statement. Fall back to OCR.
        try:
            transactions = extract_transactions_from_scan(file_path)
            used_ocr = True
            bank_code = "GENERIC"  # OCR path only has generic line-level parsing for now
        except Exception as e:
            raise OCRUnavailableError(detail=str(e))

    if not transactions:
        raise NoTransactionsFoundError()

    return bank_code, transactions, used_ocr


def _validate_pdf_readable(file_path: str) -> None:
    try:
        with pdfplumber.open(file_path) as pdf:
            if len(pdf.pages) == 0:
                raise EmptyOrCorruptFileError(detail="PDF has zero pages")
    except EmptyOrCorruptFileError:
        raise
    except Exception as e:
        message = str(e).lower()
        if "password" in message or "encrypt" in message:
            raise EncryptedPDFError(detail=str(e))
        raise EmptyOrCorruptFileError(detail=str(e))
