import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Firm, Statement, Transaction, Invoice
from app.services.copilot import answer_question
from app.services.vendor_intelligence import update_vendor_profiles


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def populated_firm(db_session):
    db_session.add(Firm(id="f1", name="Test Firm"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="t.pdf"))
    db_session.add(Transaction(id="t1", statement_id="s1", description="Salary", amount=48000, txn_type="credit", predicted_ledger_head="SALARY"))
    db_session.add(Transaction(id="t2", statement_id="s1", description="Big risky", amount=345000, txn_type="debit", predicted_ledger_head="SALES_RECEIPT", risk_level="High", vendor="Random Corp"))
    db_session.add(Transaction(id="t3", statement_id="s1", description="Rent", amount=18000, txn_type="debit", predicted_ledger_head="RENT", vendor="Gupta Properties"))
    db_session.add(Invoice(id="i1", firm_id="f1", filename="inv.pdf", vendor_name="Raj Electricals", invoice_number="INV-001", taxable_amount=5000, cgst=450, sgst=450, igst=0, total_amount=5900))
    db_session.commit()
    update_vendor_profiles(db_session, "f1")
    return db_session


def test_suspicious_transactions_question(populated_firm):
    result = answer_question(populated_firm, "f1", "Show suspicious transactions.")
    assert result["intent"] == "suspicious_transactions"
    assert result["data"]["count"] == 1
    assert "1" in result["answer"]


def test_top_vendor_question_matches_actual_top_payer(populated_firm):
    result = answer_question(populated_firm, "f1", "Which vendor received the most money?")
    assert result["intent"] == "top_vendor"
    assert result["data"]["top_vendor"]["vendor_name"] == "Random Corp"
    assert result["data"]["top_vendor"]["total_payments"] == 345000.0


def test_vendor_spend_question_sums_correctly(populated_firm):
    result = answer_question(populated_firm, "f1", "How much did we spend on suppliers?")
    assert result["intent"] == "vendor_spend"
    assert result["data"]["total_spend"] == 363000.0  # 345000 + 18000


def test_gst_question_matches_gst_summary_exactly(populated_firm):
    result = answer_question(populated_firm, "f1", "How much GST did we pay?")
    assert result["intent"] == "gst_paid"
    assert result["data"]["total_gst"] == 900.0
    assert "verified by a qualified professional" in result["answer"]


def test_unmatched_invoices_question(populated_firm):
    result = answer_question(populated_firm, "f1", "Show all unmatched invoices.")
    assert result["intent"] == "unmatched"
    assert result["data"]["unmatched_count"] == 3  # none of the 3 transactions are reconciled


def test_expense_category_question(populated_firm):
    result = answer_question(populated_firm, "f1", "What were our expenses by category?")
    assert result["intent"] == "expenses_by_category"
    assert result["data"]["categories"][0]["category"] == "SALES_RECEIPT"


def test_cash_flow_question_matches_dashboard_exactly(populated_firm):
    result = answer_question(populated_firm, "f1", "Show me the cash flow.")
    assert result["intent"] == "cash_flow"
    assert result["data"]["net_cash_flow"] == 48000.0 - 363000.0


def test_unrecognized_question_returns_unknown_not_a_guess(populated_firm):
    """Section 13's explicit requirement: never hallucinate, say when data
    is unavailable/unrecognized rather than guessing at an intent."""
    result = answer_question(populated_firm, "f1", "What is the airspeed velocity of an unladen swallow?")
    assert result["intent"] == "unknown"
    assert result["data"] is None
    assert "couldn't match" in result["answer"].lower()


def test_generic_spending_question_without_vendor_context_is_unknown(populated_firm):
    """Regression test for a real precedence bug found during development:
    'and'/'or' without parentheses meant ANY question containing 'spent'
    incorrectly matched the vendor_spend intent even with no vendor/supplier
    context at all."""
    result = answer_question(populated_firm, "f1", "How much have I spent this year overall?")
    assert result["intent"] != "vendor_spend"


def test_empty_firm_gives_honest_zero_answers_not_errors(db_session):
    db_session.add(Firm(id="f2", name="Empty Firm"))
    db_session.commit()

    result = answer_question(db_session, "f2", "Which vendor received the most money?")
    assert result["intent"] == "top_vendor"
    assert result["data"]["top_vendor"] is None
    assert "no vendor data" in result["answer"].lower()
