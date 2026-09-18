import os

from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine

import app.schema

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL is missing from .env")
        _engine = create_engine(DATABASE_URL)
    return _engine


def create_tables():
    SQLModel.metadata.create_all(get_engine())


def get_session():
    with Session(get_engine()) as session:
        yield session
