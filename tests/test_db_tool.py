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


DOCTORS = [
    {"id": 1, "name": "Dr. Sarah Ahmed", "specialization": "Cardiology"},
    {"id": 2, "name": "Dr. Fatima Noor", "specialization": "General Medicine"},
]


def test_specialty_alias_matches():
    # "general physician" is how a patient asks; "General Medicine" is how
    # it is stored. Without the alias the whole directory came back.
    result = db_tool.find_by_specialization(
        "any general physician available", DOCTORS
    )

    assert result is not None
    matched, specializations = result
    assert [doctor["name"] for doctor in matched] == ["Dr. Fatima Noor"]
    assert specializations == ["General Medicine"]


def test_stored_specialty_matches():
    result = db_tool.find_by_specialization("show me the cardiologist", DOCTORS)

    assert result is not None
    matched, specializations = result
    assert [doctor["name"] for doctor in matched] == ["Dr. Sarah Ahmed"]
    assert specializations == ["Cardiology"]


def test_no_specialty_named_returns_none():
    # The generic listing must keep working for a plain "which doctors
    # are available?" question.
    assert db_tool.find_by_specialization("which doctors are available?", DOCTORS) is None
    assert db_tool.find_by_specialization("list all doctors", DOCTORS) is None


def test_alias_does_not_match_inside_another_token():
    assert db_tool.find_by_specialization("what is your gps coverage?", DOCTORS) is None


def test_referenced_doctor_resolves_single_mention(sqlite_engine):
    # "what her fee" names nobody; the referent is whoever the previous
    # answer listed.
    history = [
        {"role": "user", "content": "any cardiologist available"},
        {"role": "assistant", "content": "Cardiology doctors:\n- Dr. Sarah Ahmed (Cardiology)"},
    ]

    referenced = db_tool.referenced_doctor(history)

    assert referenced is not None
    assert referenced["name"] == "Dr. Sarah Ahmed"


def test_referenced_doctor_is_none_for_a_directory_listing(sqlite_engine):
    history = [
        {
            "role": "assistant",
            "content": "Registered doctors:\n- Dr. Sarah Ahmed (Cardiology)\n- Dr. Bilal Raza (Dermatology)",
        }
    ]

    assert db_tool.referenced_doctor(history) is None


def test_referenced_doctor_is_none_without_a_mention(sqlite_engine):
    assert db_tool.referenced_doctor(None) is None
    assert db_tool.referenced_doctor([{"role": "user", "content": "hello"}]) is None
