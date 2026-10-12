"""Cancel/reschedule intent detection.

The booking flow resolves doctors and dates fuzzily, so a typo'd cancel has
to be caught too — otherwise "cancle" falls through to the booking workflow
and books an appointment instead of cancelling one.
"""

from datetime import time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.agent import graph, run_agent
from app.agent.tools.booking_tool import (
    CANCEL_WORDS,
    DENY_WORDS,
    RESCHEDULE_WORDS,
    _APPOINTMENT_ID,
    _parse_date,
    matches_action_word,
)
from app.schema import Appointment, Doctor, Patient, Role, User


@pytest.fixture
def sqlite_engine(monkeypatch):
    """In-memory DB shared by the cancel gate and the booking workflow."""
    from app.agent.tools import booking_tool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(graph, "get_engine", lambda: engine)
    monkeypatch.setattr(booking_tool, "get_engine", lambda: engine)
    yield engine
    engine.dispose()


def _user(user_id=1):
    return User(
        id=user_id,
        name="Test User",
        email="user@example.com",
        password_hash="x",
        role=Role.patient,
        is_active=True,
    )


def _seed_appointment(engine, appointment_date=None):
    """The reported case: one booked appointment with Dr. Sarah on the 19th."""
    with Session(engine) as session:
        doctor = Doctor(name="Dr. Sarah Ahmed", specialization="Cardiology")
        patient = Patient(name="Ali Khan", phone="0300-1234567", user_id=1)
        session.add(doctor)
        session.add(patient)
        session.flush()
        appointment = Appointment(
            doctor_id=doctor.id,
            patient_id=patient.id,
            appointment_date=appointment_date or _parse_date("19th oct"),
            start_time=time(10),
            end_time=time(10, 30),
        )
        session.add(appointment)
        session.commit()
        session.refresh(appointment)
        return appointment.id


# --- Typo-tolerant intent matching ----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "cancel my appointment",
        "cancle my appointment with dr.sara on 19th oct",
        "CANCEL appointment 3",
        "please cancel appointment 3",
        "I want 2 cancel my appointment",
    ],
)
def test_cancel_requests_are_detected(text):
    assert matches_action_word(text, CANCEL_WORDS) is True


def test_cancel_typo_without_appointment_context_is_not_a_cancel():
    """A word that merely looks like a typo of "cancel" must not act."""
    assert matches_action_word("what causes cancer", CANCEL_WORDS) is False
    assert matches_action_word("recommend a good recipe", CANCEL_WORDS) is False


def test_unrelated_questions_do_not_match_action_words():
    assert matches_action_word("what are the visiting hours", CANCEL_WORDS) is False
    assert matches_action_word("book me a slot on friday", CANCEL_WORDS) is False
    assert matches_action_word("book an appointment", RESCHEDULE_WORDS) is False


def test_reschedule_typo_is_detected():
    assert matches_action_word("reshedule my appointment", RESCHEDULE_WORDS) is True
    assert matches_action_word("postpond my appointment", RESCHEDULE_WORDS) is True


def test_deny_typo_matches_bare_reply():
    """A confirmation reply has no appointment words around it, so the typo
    match must not require context there."""
    assert matches_action_word("cancle", DENY_WORDS, contextual=False) is True
    assert matches_action_word("cancle", DENY_WORDS) is False


def test_exact_substrings_still_need_no_context():
    assert matches_action_word("cancel", CANCEL_WORDS) is True
    assert matches_action_word("I want to cancel", CANCEL_WORDS) is True


# --- Appointment ids -------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("cancel appointment 3", "3"),
        ("cancel appointment #3", "3"),
        ("cancel #3", "3"),
        ("cancel 3", "3"),
        ("cancle my appointment with dr.sara on 19th oct", None),
        ("cancel my appointment on 19th oct", None),
        ("cancel appointment on the 3rd", None),
    ],
)
def test_appointment_ids_never_swallow_dates(text, expected):
    """The id used to be any bare number, so "19th oct" looked like
    appointment #19 and the cancel failed with 'No appointment #19'."""
    match = _APPOINTMENT_ID.search(text)
    found = None
    if match is not None:
        found = match.group(1) or match.group(2) or match.group(3)
    assert found == expected


# --- End to end ------------------------------------------------------------


def test_typo_cancel_cancels_the_named_appointment(sqlite_engine):
    from app.agent.tools import booking_tool

    appointment_id = _seed_appointment(sqlite_engine)

    answer = booking_tool.handle_appointment_action(
        "cancle my appointment with dr.sara on 19th oct", user=None
    )

    assert answer is not None
    assert "cancelled" in answer
    with Session(sqlite_engine) as session:
        assert session.get(Appointment, appointment_id).status == "cancelled"


def test_typo_cancel_never_reaches_the_booking_flow(monkeypatch, sqlite_engine):
    """The reported bug: 'cancle' fell through to the booking workflow and
    answered 'You'd like to book ... On which date and time?'"""
    _seed_appointment(sqlite_engine)
    monkeypatch.setattr(graph, "route_question", lambda question: "booking")

    state = run_agent(
        "cancle my appointment with dr.sara on 19th oct", user=_user()
    )

    assert "date and time" not in state["answer"]
    assert "cancelled" in state["answer"]


def test_database_route_still_catches_a_typo_cancel(monkeypatch, sqlite_engine):
    """Even when the LLM router sends the cancel to the database route."""
    appointment_id = _seed_appointment(sqlite_engine)
    monkeypatch.setattr(graph, "route_question", lambda question: "database")
    monkeypatch.setattr(graph.db_tool, "list_doctors", lambda: [])

    state = run_agent(
        "cancle my appointment with dr.sara on 19th oct", user=_user()
    )

    assert "cancelled" in state["answer"]
    with Session(sqlite_engine) as session:
        assert session.get(Appointment, appointment_id).status == "cancelled"


def test_ambiguous_cancel_still_asks_which_appointment(sqlite_engine):
    """Doctor and date must narrow to one appointment before acting."""
    from app.agent.tools import booking_tool

    _seed_appointment(sqlite_engine)

    answer = booking_tool.handle_appointment_action(
        "cancle my appointment with dr.sara on 20th oct", user=None
    )

    assert answer is not None
    assert answer.startswith("Which appointment?")
    with Session(sqlite_engine) as session:
        appointment = session.exec(select(Appointment)).one()
        assert appointment.status == "booked"


def test_repeating_a_cancel_reports_it_as_already_cancelled(sqlite_engine):
    """The reported appointment is already cancelled: repeating the request
    must say so instead of asking which appointment was meant."""
    from app.agent.tools import booking_tool

    _seed_appointment(sqlite_engine)
    question = "cancle my appointment with dr.sara on 19th oct"

    first = booking_tool.handle_appointment_action(question, user=None)
    second = booking_tool.handle_appointment_action(question, user=None)

    assert first is not None and "has been cancelled" in first
    assert second is not None and "already cancelled" in second
