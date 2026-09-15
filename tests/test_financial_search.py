import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Firm, Statement, Transaction
from app.services.financial_search import search_transactions, _extract_amount_threshold
from app.services.vendor_intelligence import update_vendor_profiles


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_amount_threshold_parses_lakh():
    assert _extract_amount_threshold("payments above rs 1 lakh") == 100_000


def test_amount_threshold_parses_crore():
    assert _extract_amount_threshold("more than 2 crore") == 20_000_000


def test_amount_threshold_parses_k_suffix():
    assert _extract_amount_threshold("over 500k") == 500_000


def test_amount_threshold_parses_plain_number():
    assert _extract_amount_threshold("transactions over 50000") == 50_000


def test_amount_threshold_returns_none_when_absent():
    assert _extract_amount_threshold("show everything") is None


def test_search_finds_high_value_new_vendor_payment_excludes_established_vendor(db_session):
    """The exact Section 14 example query: 'Show payments above Rs 1 lakh
    to new vendors' -- must find the new vendor's large payment and
    correctly exclude an established vendor's even larger payment."""
    db_session.add(Firm(id="f1", name="Test"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="t.pdf"))
    db_session.add(Transaction(id="t1", statement_id="s1", description="Big payment", amount=150000, txn_type="debit", vendor="Brand New Vendor"))
    db_session.add(Transaction(id="t2", statement_id="s1", description="Old vendor big payment", amount=200000, txn_type="debit", vendor="Established Co"))
    db_session.add(Transaction(id="t3", statement_id="s1", description="Established Co again", amount=50000, txn_type="debit", vendor="Established Co"))
    db_session.commit()
    update_vendor_profiles(db_session, "f1")

    result = search_transactions(db_session, "f1", "Show payments above Rs 1 lakh to new vendors")
    assert result["result_count"] == 1
    assert result["transactions"][0]["vendor"] == "Brand New Vendor"


def test_search_with_no_filters_returns_all_transactions(db_session):
    db_session.add(Firm(id="f1", name="Test"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="t.pdf"))
    db_session.add(Transaction(id="t1", statement_id="s1", description="A", amount=100, txn_type="debit"))
    db_session.add(Transaction(id="t2", statement_id="s1", description="B", amount=200, txn_type="credit"))
    db_session.commit()

    result = search_transactions(db_session, "f1", "show me everything")
    assert result["result_count"] == 2
    assert result["filters_applied"] == []


def test_search_filters_by_amount_only(db_session):
    db_session.add(Firm(id="f1", name="Test"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="t.pdf"))
    db_session.add(Transaction(id="t1", statement_id="s1", description="Small", amount=100, txn_type="debit"))
    db_session.add(Transaction(id="t2", statement_id="s1", description="Big", amount=60000, txn_type="debit"))
    db_session.commit()

    result = search_transactions(db_session, "f1", "transactions over 50000")
    assert result["result_count"] == 1
    assert result["transactions"][0]["amount"] == 60000
