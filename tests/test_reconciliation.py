from app.services.reconciliation import reconcile


def test_exact_amount_and_vendor_match():
    transactions = [
        {"id": "t1", "description": "PAYMENT TO ACME TRADERS INV001", "amount": 4500.0, "txn_type": "debit"},
    ]
    invoices = [{"ref": "INV001", "amount": 4500.0, "vendor": "Acme Traders"}]

    matches = reconcile(transactions, invoices)
    assert len(matches) == 1
    assert matches[0]["transaction_id"] == "t1"
    assert matches[0]["invoice_ref"] == "INV001"


def test_no_match_when_amount_differs_beyond_tolerance():
    transactions = [
        {"id": "t1", "description": "PAYMENT TO ACME TRADERS", "amount": 4500.0, "txn_type": "debit"},
    ]
    invoices = [{"ref": "INV001", "amount": 5000.0, "vendor": "Acme Traders"}]

    matches = reconcile(transactions, invoices)
    assert len(matches) == 0


def test_duplicate_transaction_only_matches_one_invoice():
    """Two identical transactions, one invoice -- only one should match,
    the other stays unreconciled (this is intentional, it's what surfaces
    the duplicate for human review rather than silently double-matching)."""
    transactions = [
        {"id": "t1", "description": "PAYMENT TO ACME TRADERS INV001", "amount": 4500.0, "txn_type": "debit"},
        {"id": "t2", "description": "PAYMENT TO ACME TRADERS INV001", "amount": 4500.0, "txn_type": "debit"},
    ]
    invoices = [{"ref": "INV001", "amount": 4500.0, "vendor": "Acme Traders"}]

    matches = reconcile(transactions, invoices)
    assert len(matches) == 1  # only one invoice available, only one match possible


def test_vendor_name_mismatch_prevents_match():
    transactions = [
        {"id": "t1", "description": "PAYMENT TO COMPLETELY UNRELATED PARTY", "amount": 4500.0, "txn_type": "debit"},
    ]
    invoices = [{"ref": "INV001", "amount": 4500.0, "vendor": "Acme Traders"}]

    matches = reconcile(transactions, invoices)
    assert len(matches) == 0
