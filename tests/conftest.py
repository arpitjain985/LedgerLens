"""
Shared pytest configuration.

The rate limiter (app/services/rate_limit.py) uses process-wide in-memory
storage by design -- correct for the real app (one process, real clients),
but wrong for a test suite: with 100+ tests each hitting /auth/register or
/auth/login to set up test data, later tests would exceed the configured
limit and get real 429s, unrelated to whatever that test is actually
checking. This autouse fixture resets the limiter's counters before every
test so each test starts with a clean slate, matching how a real client
would experience the app (their own fresh rate-limit window), not how a
shared test process accumulates one.
"""
import pytest

from app.services.rate_limit import limiter


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
