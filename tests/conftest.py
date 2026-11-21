"""Shared test configuration.

The API's in-process rate limiter is disabled for every test by default.
TestClient requests all share one client address ("testclient"), so a
suite of dozens of requests would trip the real window and cascade 429s
into unrelated tests. Tests that exercise the limiter install their own
instance via monkeypatch.

The app's default database engine is also replaced for every test, so the
suite behaves identically on a laptop (which has a .env) and in CI (which
does not, and has no database).
"""

import pytest


@pytest.fixture(autouse=True)
def _unlimited_rate_limiter():
    from app import api

    original = api.rate_limiter
    api.rate_limiter = api.SlidingWindowRateLimiter(max_requests=10**9)
    yield
    api.rate_limiter = original


@pytest.fixture(autouse=True)
def _isolated_app_database(monkeypatch):
    """Give the app's default engine a throwaway in-memory database.

    Some graph nodes resolve doctor details before their tool calls are
    stubbed, so without this a "unit" test opens a session against whatever
    DATABASE_URL is configured — or fails with "DATABASE_URL is missing"
    when there is no .env, which is exactly the CI environment. Pinning the
    engine keeps the suite identical on a laptop and in CI.

    Every module binds ``get_engine`` at import time, so each reference has
    to be patched. Tests that need rows still create their own engine and
    override the same attributes afterwards.
    """
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, create_engine

    import app.db
    import app.schema  # noqa: F401  (registers the tables on the metadata)
    from app.agent import graph
    from app.agent.tools import booking_tool, db_tool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    for module in (app.db, graph, booking_tool, db_tool):
        monkeypatch.setattr(module, "get_engine", lambda: engine)

    yield engine

    engine.dispose()
