import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Firm, Statement, Transaction
from app.services.dashboard import get_dashboard


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_dashboard_totals_and_net_cash_flow(db_session):
    db_session.add(Firm(id="f1", name="Test"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="t.pdf"))
    db_session.add(Transaction(id="t1", statement_id="s1", description="Salary", amount=48000, txn_type="credit", predicted_ledger_head="SALARY"))
    db_session.add(Transaction(id="t2", statement_id="s1", description="Rent", amount=18000, txn_type="debit", predicted_ledger_head="RENT"))
    db_session.commit()

    result = get_dashboard(db_session, "f1")
    assert result["total_credits"] == 48000.0
    assert result["total_debits"] == 18000.0
    assert result["net_cash_flow"] == 30000.0
    assert result["transaction_count"] == 2


def test_dashboard_reconciliation_counts(db_session):
    db_session.add(Firm(id="f1", name="Test"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="t.pdf"))
    db_session.add(Transaction(id="t1", statement_id="s1", description="A", amount=100, txn_type="debit", reconciled=True))
    db_session.add(Transaction(id="t2", statement_id="s1", description="B", amount=200, txn_type="debit", reconciled=False))
    db_session.commit()

    result = get_dashboard(db_session, "f1")
    assert result["reconciled_count"] == 1
    assert result["unmatched_count"] == 1


def test_dashboard_suspicious_count_uses_high_and_critical_only(db_session):
    db_session.add(Firm(id="f1", name="Test"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="t.pdf"))
    db_session.add(Transaction(id="t1", statement_id="s1", description="A", amount=100, txn_type="debit", risk_level="Low"))
    db_session.add(Transaction(id="t2", statement_id="s1", description="B", amount=200, txn_type="debit", risk_level="Medium"))
    db_session.add(Transaction(id="t3", statement_id="s1", description="C", amount=300, txn_type="debit", risk_level="High"))
    db_session.add(Transaction(id="t4", statement_id="s1", description="D", amount=400, txn_type="debit", risk_level="Critical"))
    db_session.commit()

    result = get_dashboard(db_session, "f1")
    assert result["suspicious_count"] == 2  # only High + Critical


def test_dashboard_expense_by_category_uses_corrected_head_when_present(db_session):
    """A human-corrected ledger head should take priority over the AI
    prediction when computing expense breakdowns."""
    db_session.add(Firm(id="f1", name="Test"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="t.pdf"))
    db_session.add(Transaction(
        id="t1", statement_id="s1", description="A", amount=5000, txn_type="debit",
        predicted_ledger_head="VENDOR_PAYMENT", corrected_ledger_head="OFFICE_SUPPLIES",
    ))
    db_session.commit()

    result = get_dashboard(db_session, "f1")
    categories = {c["category"]: c["amount"] for c in result["expense_by_category"]}
    assert categories.get("OFFICE_SUPPLIES") == 5000.0
    assert "VENDOR_PAYMENT" not in categories


def test_dashboard_empty_firm_returns_zeros(db_session):
    db_session.add(Firm(id="f1", name="Empty Firm"))
    db_session.commit()

    result = get_dashboard(db_session, "f1")
    assert result["transaction_count"] == 0
    assert result["total_credits"] == 0
    assert result["net_cash_flow"] == 0
    assert result["expense_by_category"] == []
