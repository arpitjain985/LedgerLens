import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Firm, Statement, Transaction
from app.services.recurring_detection import (
    detect_recurring_transactions,
    _amounts_are_similar,
    _intervals_are_regular,
    _label_frequency,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_amounts_are_similar_within_tolerance():
    assert _amounts_are_similar([18000, 18000, 18000]) is True
    assert _amounts_are_similar([18000, 18500, 17800]) is True  # within 15%
    assert _amounts_are_similar([18000, 6750, 45000]) is False


def test_intervals_are_regular():
    assert _intervals_are_regular([30, 31, 29], 30) is True
    assert _intervals_are_regular([5, 45, 12], 20.7) is False


def test_frequency_labels():
    assert _label_frequency(7) == "Weekly"
    assert _label_frequency(30) == "Monthly"
    assert _label_frequency(90) == "Quarterly"
    assert _label_frequency(365) == "Annual"


def test_monthly_rent_pattern_detected(db_session):
    db_session.add(Firm(id="f1", name="Test Firm"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="test.pdf"))
    for i, date in enumerate(["02-05-2026", "02-06-2026", "03-07-2026"]):
        db_session.add(Transaction(
            id=f"rent{i}", statement_id="s1", description="RENT",
            amount=18000, vendor="Gupta Properties", txn_date=date,
        ))
    db_session.commit()

    results = detect_recurring_transactions(db_session, "f1")
    assert len(results) == 1
    assert results[0]["vendor_name"] == "Gupta Properties"
    assert results[0]["occurrences"] == 3
    assert results[0]["frequency_label"] == "Monthly"


def test_one_off_transaction_not_flagged_as_recurring(db_session):
    db_session.add(Firm(id="f1", name="Test Firm"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="test.pdf"))
    db_session.add(Transaction(
        id="t1", statement_id="s1", description="ONE TIME",
        amount=5000, vendor="Random Vendor", txn_date="15-07-2026",
    ))
    db_session.commit()

    results = detect_recurring_transactions(db_session, "f1")
    assert results == []


def test_irregular_amounts_not_flagged_as_recurring(db_session):
    """Same vendor, same-ish dates, but wildly different amounts -- not a
    recurring bill, just a vendor paid multiple times for different things."""
    db_session.add(Firm(id="f1", name="Test Firm"))
    db_session.add(Statement(id="s1", firm_id="f1", filename="test.pdf"))
    for i, (date, amount) in enumerate([("02-05-2026", 5000), ("02-06-2026", 45000), ("03-07-2026", 900)]):
        db_session.add(Transaction(
            id=f"t{i}", statement_id="s1", description="VARIABLE",
            amount=amount, vendor="Variable Vendor", txn_date=date,
        ))
    db_session.commit()

    results = detect_recurring_transactions(db_session, "f1")
    assert results == []
