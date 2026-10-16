"""Shared test configuration.

The API's in-process rate limiter is disabled for every test by default.
TestClient requests all share one client address ("testclient"), so a
suite of dozens of requests would trip the real window and cascade 429s
into unrelated tests. Tests that exercise the limiter install their own
instance via monkeypatch.
"""

import pytest


@pytest.fixture(autouse=True)
def _unlimited_rate_limiter():
    from app import api

    original = api.rate_limiter
    api.rate_limiter = api.SlidingWindowRateLimiter(max_requests=10**9)
    yield
    api.rate_limiter = original
