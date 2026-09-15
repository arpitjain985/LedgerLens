from app.services.risk_engine import compute_risk, _score_to_level


def test_score_to_level_bands():
    """Exact bands from Section 10: 0-30 Low, 31-60 Medium, 61-80 High, 81-100 Critical."""
    assert _score_to_level(0) == "Low"
    assert _score_to_level(30) == "Low"
    assert _score_to_level(31) == "Medium"
    assert _score_to_level(60) == "Medium"
    assert _score_to_level(61) == "High"
    assert _score_to_level(80) == "High"
    assert _score_to_level(81) == "Critical"
    assert _score_to_level(100) == "Critical"


def test_normal_small_transaction_scores_low():
    transactions = [
        {"id": "1", "description": "Small odd payment", "amount": 1234.56,
         "predicted_ledger_head": "OFFICE_SUPPLIES", "txn_date": "01-07-2026", "vendor": None},
    ]
    result = compute_risk(transactions)[0]
    assert result["risk_level"] == "Low"
    assert result["risk_score"] < 20


def test_duplicate_scores_at_least_medium():
    transactions = [
        {"id": "1", "description": "PAYMENT TO X", "amount": 5000, "predicted_ledger_head": "VENDOR_PAYMENT", "txn_date": "01-07-2026", "vendor": None},
        {"id": "2", "description": "PAYMENT TO X", "amount": 5000, "predicted_ledger_head": "VENDOR_PAYMENT", "txn_date": "01-07-2026", "vendor": None},
    ]
    results = compute_risk(transactions)
    for r in results:
        assert r["risk_level"] in ("Medium", "High", "Critical")
        assert r["risk_score"] >= 31


def test_high_value_transaction_scores_at_least_medium():
    """
    Regression test tied to a real tuning decision: the Rs 3,45,000
    transaction found during manual testing initially scored only 30/Low
    under the first weighting, which undersold a transaction significant
    enough to have needed a dedicated detection rule in the first place.
    Weights were adjusted so a high-value flag alone reliably lands at
    least Medium.
    """
    transactions = [
        {"id": "1", "description": "Misc large wire transfer", "amount": 345000,
         "predicted_ledger_head": "SALES_RECEIPT", "txn_date": "28-07-2026", "vendor": None},
    ]
    result = compute_risk(transactions)[0]
    assert result["risk_score"] >= 31
    assert result["risk_level"] in ("Medium", "High", "Critical")


def test_new_vendor_flag_adds_risk_when_supplied():
    transactions = [
        {"id": "1", "description": "PAYMENT TO NEW CO", "amount": 5000,
         "predicted_ledger_head": "VENDOR_PAYMENT", "txn_date": "01-07-2026", "vendor": "New Co"},
    ]
    without_vendor_data = compute_risk(transactions)[0]
    with_new_vendor_flag = compute_risk(transactions, vendor_first_seen={"new co": True})[0]
    assert with_new_vendor_flag["risk_score"] > without_vendor_data["risk_score"]


def test_weekend_transaction_flagged():
    # 04-07-2026 is a Saturday
    transactions = [
        {"id": "1", "description": "Odd weekend payment", "amount": 3333,
         "predicted_ledger_head": "VENDOR_PAYMENT", "txn_date": "04-07-2026", "vendor": None},
    ]
    result = compute_risk(transactions)[0]
    assert any("weekend" in r.lower() for r in result["risk_reasons"])


def test_score_never_exceeds_100():
    """A transaction hitting every rule at once must still cap at 100."""
    transactions = [
        {"id": "1", "description": "DUP", "amount": 500000, "predicted_ledger_head": "SALES_RECEIPT", "txn_date": "04-07-2026", "vendor": "Brand New Vendor"},
        {"id": "2", "description": "DUP", "amount": 500000, "predicted_ledger_head": "SALES_RECEIPT", "txn_date": "04-07-2026", "vendor": "Brand New Vendor"},
        {"id": "3", "description": "tiny one", "amount": 10, "predicted_ledger_head": "SALES_RECEIPT", "txn_date": "05-07-2026", "vendor": None},
        {"id": "4", "description": "tiny two", "amount": 12, "predicted_ledger_head": "SALES_RECEIPT", "txn_date": "05-07-2026", "vendor": None},
    ]
    results = compute_risk(transactions, vendor_first_seen={"brand new vendor": True})
    for r in results:
        assert r["risk_score"] <= 100
