from app.services.vendor_extraction import extract_vendor, normalize_description, normalize_vendor_name


def test_extracts_vendor_after_payment_to():
    vendor = extract_vendor("03-07-2026 PAYMENT TO SUPPLIER RAJ ELECTRICALS INV-2201 6,750.00 DR")
    assert vendor is not None
    assert "Raj Electricals" in vendor


def test_extracts_vendor_after_upi_received():
    vendor = extract_vendor("10-07-2026 CUSTOMER PAYMENT RECEIVED UPI VIKRAM ENTERPRISES 1,25,000.00 CR")
    assert vendor == "Vikram Enterprises"


def test_atm_withdrawal_has_no_vendor():
    """An ATM withdrawal has no external counterparty -- must return None,
    not a false-positive guess."""
    vendor = extract_vendor("06-07-2026 ATM WITHDRAWAL SELF MG ROAD BRANCH 10,000.00 DR")
    assert vendor is None


def test_two_invoices_same_vendor_normalize_identically():
    """This is the exact property the correction flywheel depends on: two
    transactions to the same vendor with different invoice numbers/amounts/
    dates must normalize to the same string so a correction on one applies
    to the other."""
    desc1 = "03-07-2026 PAYMENT TO SUPPLIER RAJ ELECTRICALS INV-2201 6,750.00 DR"
    desc2 = "20-07-2026 PAYMENT TO SUPPLIER RAJ ELECTRICALS INV-2214 8,900.00 DR"
    assert normalize_description(desc1) == normalize_description(desc2)


def test_different_vendors_normalize_differently():
    desc1 = "PAYMENT TO SUPPLIER RAJ ELECTRICALS 6,750.00 DR"
    desc2 = "PAYMENT TO SUPPLIER ACME TRADERS 6,750.00 DR"
    assert normalize_description(desc1) != normalize_description(desc2)


def test_normalize_vendor_name_collapses_formatting_differences():
    assert normalize_vendor_name("Raj Electricals Ltd.") == normalize_vendor_name("RAJ ELECTRICALS LTD")
