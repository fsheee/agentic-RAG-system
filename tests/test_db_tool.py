"""doctor_details name matching — the database route's doctor lookup.

A question that shortens or slightly misspells a name ("sara" for
"Sarah") must still resolve to that doctor; otherwise the database node
falls back to the generic doctor list and never answers the question.
"""

from datetime import time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from app.agent.tools import db_tool
from app.schema import Doctor, DoctorSchedule


@pytest.fixture
def sqlite_engine(monkeypatch):
    """In-memory DB with two doctors, so doctor_details never hits Neon."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        sarah = Doctor(
            name="Dr. Sarah Ahmed",
            specialization="Cardiology",
            consultation_fee=3000,
        )
        bilal = Doctor(
            name="Dr. Bilal Raza",
            specialization="Dermatology",
            consultation_fee=2500,
        )
        session.add(sarah)
        session.add(bilal)
        session.flush()
        session.add(
            DoctorSchedule(
                doctor_id=sarah.id,
                day_of_week=0,
                start_time=time(9, 0),
                end_time=time(13, 0),
            )
        )
        session.commit()

    monkeypatch.setattr(db_tool, "get_engine", lambda: engine)
    yield engine
    engine.dispose()


def test_shortened_name_matches(sqlite_engine):
    # The original bug: "sara" did not match token "sarah", so the agent
    # answered with the generic doctor list instead of the schedule.
    result = db_tool.doctor_details("dr.sara available on saturday at 4pm")

    assert result is not None
    assert "Dr. Sarah Ahmed" in result
    assert "Weekly schedule" in result


def test_full_name_still_matches(sqlite_engine):
    result = db_tool.doctor_details("What is Dr. Bilal Raza's fee?")

    assert result is not None
    assert "Dr. Bilal Raza" in result


def test_no_doctor_mentioned_returns_none(sqlite_engine):
    # Falls through to the generic doctor list in the database node.
    assert db_tool.doctor_details("list all doctors") is None
    assert db_tool.doctor_details("What are the visiting hours?") is None
