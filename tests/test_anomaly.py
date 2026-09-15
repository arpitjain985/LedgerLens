"""
Tests for anomaly detection -- covers all three rules (duplicate, z-score,
high-value) using synthetic data, including the exact real-world case that
was found and fixed during development (a large transaction hidden in a
small, wrongly-classified group).
"""
from app.services.anomaly import flag_anomalies


def _flagged_ids(transactions):
    results = flag_anomalies(transactions)
    return {r["transaction_id"] for r in results if r["is_anomaly"]}


def test_duplicate_payment_is_flagged():
    transactions = [
        {"id": "1", "description": "PAYMENT TO SUPPLIER X", "amount": 5000, "predicted_ledger_head": "VENDOR_PAYMENT"},
        {"id": "2", "description": "PAYMENT TO SUPPLIER X", "amount": 5000, "predicted_ledger_head": "VENDOR_PAYMENT"},
        {"id": "3", "description": "RENT PAID", "amount": 15000, "predicted_ledger_head": "RENT"},
    ]
    flagged = _flagged_ids(transactions)
    assert "1" in flagged and "2" in flagged
    assert "3" not in flagged


def test_high_value_transaction_flagged_even_in_small_group():
    """
    Regression test for the real bug found during manual testing: a
    Rs 3,45,000 transaction in a 4-item SALES_RECEIPT group had a z-score
    of only ~1.45 (below the old 2.5 threshold) and was missed. The
    high-value rule must catch it independently of group statistics.
    """
    transactions = [
        {"id": "1", "description": "Customer payment A", "amount": 125000, "predicted_ledger_head": "SALES_RECEIPT"},
        {"id": "2", "description": "Customer payment B", "amount": 34500, "predicted_ledger_head": "SALES_RECEIPT"},
        {"id": "3", "description": "Customer payment C", "amount": 210000, "predicted_ledger_head": "SALES_RECEIPT"},
        {"id": "4", "description": "Misc large wire transfer", "amount": 345000, "predicted_ledger_head": "SALES_RECEIPT"},
    ]
    flagged = _flagged_ids(transactions)
    assert "4" in flagged, "The Rs 3,45,000 outlier must be caught by the high-value rule"


def test_normal_transactions_not_flagged():
    transactions = [
        {"id": "1", "description": "Salary credit", "amount": 48000, "predicted_ledger_head": "SALARY"},
        {"id": "2", "description": "Rent paid", "amount": 18000, "predicted_ledger_head": "RENT"},
        {"id": "3", "description": "GST payment", "amount": 9340, "predicted_ledger_head": "GST_PAYMENT"},
    ]
    flagged = _flagged_ids(transactions)
    assert flagged == set()


def test_small_group_below_min_size_skips_zscore_but_high_value_still_applies():
    """A group with fewer than ANOMALY_MIN_GROUP_SIZE transactions skips the
    z-score check entirely, but the high-value rule is independent of group
    size and should still catch a large transaction."""
    transactions = [
        {"id": "1", "description": "Big one-off transfer", "amount": 500000, "predicted_ledger_head": "INTERNAL_TRANSFER"},
    ]
    flagged = _flagged_ids(transactions)
    assert "1" in flagged
