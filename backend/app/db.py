import os

from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine

import app.schema

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Pool tuning (overridable without a code change):
# - POOL_RECYCLE_SECONDS bounds connection age so no connection outlives the
#   server's own lifetime limits; the default is well under common idle
#   timeouts so recycled connections are cheap to replace.
# - POOL_SIZE / POOL_MAX_OVERFLOW cap how many connections one worker may
#   hold open against Neon's own pool limit.
# - POOL_TIMEOUT_SECONDS fails fast with a clear error instead of blocking a
#   request indefinitely when the pool is saturated.
POOL_RECYCLE_SECONDS = int(os.getenv("POOL_RECYCLE_SECONDS", "1800"))
POOL_SIZE = int(os.getenv("POOL_SIZE", "5"))
POOL_MAX_OVERFLOW = int(os.getenv("POOL_MAX_OVERFLOW", "10"))
POOL_TIMEOUT_SECONDS = int(os.getenv("POOL_TIMEOUT_SECONDS", "30"))

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL is missing from .env")
        # pool_pre_ping: Neon drops idle connections, and a stale one from
        # the pool fails the next query with "SSL connection closed" instead
        # of being replaced transparently.
        _engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=POOL_RECYCLE_SECONDS,
            pool_size=POOL_SIZE,
            max_overflow=POOL_MAX_OVERFLOW,
            pool_timeout=POOL_TIMEOUT_SECONDS,
        )
    return _engine


def create_tables():
    SQLModel.metadata.create_all(get_engine())


def get_session():
    with Session(get_engine()) as session:
        yield session
