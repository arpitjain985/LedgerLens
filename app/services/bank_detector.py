"""
Detects which bank a statement is from and routes to the matching parser
adapter. Falls back to the generic parser (V1's proven logic) if nothing
matches — a statement should never fail to parse just because its bank
isn't recognized yet.
"""
from typing import List

import pdfplumber

from app.services.parsers.base import NormalizedTransaction
from app.services.parsers.sbi import SBIParser
from app.services.parsers.hdfc import HDFCParser
from app.services.parsers.icici import ICICIParser
from app.services.parsers.generic import GenericParser

# Order matters: more specific parsers are tried before the generic fallback,
# which always matches and must stay last.
PARSERS = [
    SBIParser(),
    HDFCParser(),
    ICICIParser(),
    GenericParser(),
]


def detect_and_parse(file_path: str) -> tuple[str, List[NormalizedTransaction]]:
    """
    Returns (bank_code, transactions). Tries each parser's detection against
    a text sample from the first page, then parses with the first match.
    """
    text_sample = _get_text_sample(file_path)

    for parser in PARSERS:
        if parser.matches(text_sample):
            transactions = parser.parse(file_path)
            return parser.bank_code, transactions

    # Should never reach here since GenericParser.matches() always returns True,
    # but keep an explicit fallback in case PARSERS is ever reordered incorrectly.
    generic = GenericParser()
    return generic.bank_code, generic.parse(file_path)


def _get_text_sample(file_path: str) -> str:
    """Pulls text from the first 1-2 pages for bank-detection purposes only."""
    try:
        with pdfplumber.open(file_path) as pdf:
            sample_pages = pdf.pages[:2]
            return "\n".join((p.extract_text() or "") for p in sample_pages)
    except Exception:
        # If even opening the PDF for a text sample fails, return empty —
        # this routes to the generic parser, and the real error (corrupt/
        # encrypted file) will surface properly when parse() is attempted.
        return ""
