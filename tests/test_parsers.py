"""
Tests for bank detection routing and parser adapter interfaces.
Uses synthetic text samples -- no real financial data required (Section 32).
"""
from app.services.parsers.sbi import SBIParser
from app.services.parsers.hdfc import HDFCParser
from app.services.parsers.icici import ICICIParser
from app.services.parsers.generic import GenericParser


def test_sbi_parser_matches_sbi_letterhead():
    parser = SBIParser()
    assert parser.matches("STATE BANK OF INDIA\nAccount Statement\n...") is True


def test_sbi_parser_does_not_match_unrelated_text():
    parser = SBIParser()
    assert parser.matches("Some random document about cats and dogs") is False


def test_hdfc_parser_matches_hdfc_letterhead():
    parser = HDFCParser()
    assert parser.matches("HDFC BANK LIMITED\nStatement of Account") is True


def test_hdfc_parser_matches_ifsc_prefix():
    parser = HDFCParser()
    assert parser.matches("IFSC: HDFC0001234") is True


def test_icici_parser_matches_icici_letterhead():
    parser = ICICIParser()
    assert parser.matches("ICICI BANK LIMITED") is True


def test_generic_parser_always_matches():
    """The generic fallback must match anything -- it's the catch-all."""
    parser = GenericParser()
    assert parser.matches("literally anything") is True
    assert parser.matches("") is True


def test_generic_parser_row_to_transaction_extracts_date_and_amount():
    parser = GenericParser()
    txn = parser._row_to_transaction("01-07-2026  SALARY CREDIT NEFT  48,000.00 CR")
    assert txn is not None
    assert txn.date == "01-07-2026"
    assert txn.amount == 48000.00
    assert txn.transaction_type == "credit"


def test_generic_parser_row_with_no_date_returns_none():
    parser = GenericParser()
    txn = parser._row_to_transaction("This line has an amount 100.00 but no date")
    assert txn is None


def test_generic_parser_row_with_no_amount_returns_none():
    parser = GenericParser()
    txn = parser._row_to_transaction("01-07-2026 this line has a date but no amount")
    assert txn is None
