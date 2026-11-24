"""Booking uniqueness: the database must prevent double-booking a slot
without preventing a cancelled slot from being rebooked.

Two layers are covered:

* **Unit tests** (in-memory SQLite, no external services) pin the *intended*
  index contract: a partial unique index on
  ``(doctor_id, appointment_date, start_time) WHERE status = 'booked'``.
  They run the real SQLModel schema plus that DDL, so they fail if the
  invariant is wrong.

* **Integration tests** (``-m integration``, live Neon) check the index that
  is actually deployed and prove the race end to end. These are the tests
  that catch the real-world mistake: a plain ``UNIQUE`` constraint also
  blocks cancelled rows, so a slot can never be rebooked.

Run the fast layer with the normal suite; the live layer with:

    uv run python -m pytest -q -m integration tests/test_booking_constraint.py
"""

import os
import threading
from datetime import date, time

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel import Session, SQLModel, select

from app.crud import (
    book_appointment,
    reschedule_appointment,
    SlotTakenError,
    update_appointment,
)
from app.schema import Appointment, Doctor, DoctorSchedule, Patient

# The one DDL that defines the invariant. A plain UNIQUE constraint is the
# bug: cancellation keeps the row (status='cancelled'), so the slot would
# stay occupied forever.
PARTIAL_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX unique_doctor_booking "
    "ON appointment (doctor_id, appointment_date, start_time) "
    "WHERE status = 'booked'"
)

SLOT_DAY = date(2031, 3, 3)  # far future: never collides with real data
SLOT_START = time(7, 0)
SLOT_END = time(7, 30)


# --------------------------------------------------------------------------
# Unit layer — in-memory SQLite
# --------------------------------------------------------------------------


@pytest.fixture()
def engine():
    """Real schema + the intended partial index, on in-memory SQLite.

    StaticPool keeps one connection so the schema and rows survive across
    the per-test sessions, matching the rest of the suite.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(PARTIAL_UNIQUE_INDEX))

    yield engine
    engine.dispose()


@pytest.fixture()
def seeded(engine):
    """One doctor with a schedule and one patient."""
    with Session(engine) as session:
        doctor = Doctor(
            name="Dr. Usman Tariq", specialization="Orthopedics", consultation_fee=3500
        )
        patient = Patient(name="Ali Khan", phone="03001234567")
        session.add(doctor)
        session.add(patient)
        session.flush()

        session.add(
            DoctorSchedule(
                doctor_id=doctor.id,
                day_of_week=SLOT_DAY.weekday(),
                start_time=time(9),
                end_time=time(17),
            )
        )
        session.commit()
        return {"doctor_id": doctor.id, "patient_id": patient.id}


def _book(engine, doctor_id, patient_id, status="booked", start=SLOT_START):
    with Session(engine) as session:
        appointment = Appointment(
            doctor_id=doctor_id,
            patient_id=patient_id,
            appointment_date=SLOT_DAY,
            start_time=start,
            end_time=SLOT_END,
            status=status,
        )
        session.add(appointment)
        session.commit()
        session.refresh(appointment)
        return appointment.id


def test_second_booked_row_for_the_same_slot_is_rejected(engine, seeded):
    """The invariant itself: two booked rows cannot share doctor/day/start."""
    _book(engine, seeded["doctor_id"], seeded["patient_id"])

    with pytest.raises(IntegrityError):
        _book(engine, seeded["doctor_id"], seeded["patient_id"])


def test_cancelled_row_does_not_block_the_slot(engine, seeded):
    """Cancellation keeps the row, so the index must ignore non-booked rows."""
    _book(engine, seeded["doctor_id"], seeded["patient_id"], status="cancelled")

    _book(engine, seeded["doctor_id"], seeded["patient_id"])

    with Session(engine) as session:
        rows = session.exec(select(Appointment)).all()

    assert len(rows) == 2
    assert {row.status for row in rows} == {"cancelled", "booked"}


def test_same_slot_for_a_different_doctor_is_allowed(engine, seeded):
    """The key includes the doctor: one doctor's booking is not another's."""
    with Session(engine) as session:
        other = Doctor(name="Dr. Fatima Noor", specialization="General Medicine")
        session.add(other)
        session.commit()
        other_id = other.id

    _book(engine, seeded["doctor_id"], seeded["patient_id"])
    _book(engine, other_id, seeded["patient_id"])

    with Session(engine) as session:
        assert len(session.exec(select(Appointment)).all()) == 2


def test_different_start_times_on_the_same_day_are_allowed(engine, seeded):
    """Slots are distinguished by start time, not by the day alone."""
    _book(engine, seeded["doctor_id"], seeded["patient_id"], start=time(7, 0))
    _book(engine, seeded["doctor_id"], seeded["patient_id"], start=time(7, 30))

    with Session(engine) as session:
        assert len(session.exec(select(Appointment)).all()) == 2


def test_book_appointment_raises_slot_taken_on_a_duplicate(engine, seeded):
    """The write-time check converts the duplicate into a domain error.

    The API maps SlotTakenError to 409; a raw IntegrityError would become a
    500, which is exactly the failure the guard exists to prevent.
    """
    with Session(engine) as session:
        book_appointment(
            session,
            doctor_id=seeded["doctor_id"],
            patient_id=seeded["patient_id"],
            appointment_date=SLOT_DAY,
            start_time=SLOT_START,
            end_time=SLOT_END,
        )

    with pytest.raises(SlotTakenError):
        with Session(engine) as session:
            book_appointment(
                session,
                doctor_id=seeded["doctor_id"],
                patient_id=seeded["patient_id"],
                appointment_date=SLOT_DAY,
                start_time=SLOT_START,
                end_time=SLOT_END,
            )


def test_book_appointment_rejects_an_overlapping_interval(engine, seeded):
    """The guard is overlap-based, not exact-start only.

    The partial unique index keys on start_time, so 07:15-07:45 would slip
    past the index; the locked conflict check must catch it.
    """
    _book(engine, seeded["doctor_id"], seeded["patient_id"])

    with pytest.raises(SlotTakenError):
        with Session(engine) as session:
            book_appointment(
                session,
                doctor_id=seeded["doctor_id"],
                patient_id=seeded["patient_id"],
                appointment_date=SLOT_DAY,
                start_time=time(7, 15),
                end_time=time(7, 45),
            )


def test_reschedule_into_a_taken_slot_raises_slot_taken(engine, seeded):
    """Moving an appointment onto a booked slot is rejected and rolled back."""
    _book(engine, seeded["doctor_id"], seeded["patient_id"], start=time(7, 0))
    second = _book(
        engine, seeded["doctor_id"], seeded["patient_id"], start=time(7, 30)
    )

    with pytest.raises(SlotTakenError):
        with Session(engine) as session:
            reschedule_appointment(
                session, second, SLOT_DAY, time(7, 0), SLOT_END
            )

    with Session(engine) as session:
        unchanged = session.get(Appointment, second)

    assert unchanged.start_time == time(7, 30)


def test_update_into_a_taken_slot_raises_slot_taken(engine, seeded):
    """An admin move takes the same guard as a patient booking."""
    _book(engine, seeded["doctor_id"], seeded["patient_id"], start=time(7, 0))
    second = _book(
        engine, seeded["doctor_id"], seeded["patient_id"], start=time(7, 30)
    )

    with pytest.raises(SlotTakenError):
        with Session(engine) as session:
            update_appointment(
                session,
                second,
                appointment_date=SLOT_DAY,
                start_time=time(7, 0),
                end_time=SLOT_END,
            )


def test_integrity_error_is_converted_when_the_precheck_misses(
    engine, seeded, monkeypatch
):
    """The database index is the last line of defence.

    If a writer bypasses the locked pre-check, the partial unique index still
    rejects the duplicate — and the CRUD helper turns that into the same
    SlotTakenError instead of a 500.
    """
    import app.crud as crud

    _book(engine, seeded["doctor_id"], seeded["patient_id"])

    monkeypatch.setattr(
        crud, "find_conflicting_appointment", lambda *args, **kwargs: None
    )

    with pytest.raises(SlotTakenError):
        with Session(engine) as session:
            book_appointment(
                session,
                doctor_id=seeded["doctor_id"],
                patient_id=seeded["patient_id"],
                appointment_date=SLOT_DAY,
                start_time=SLOT_START,
                end_time=SLOT_END,
            )


# --------------------------------------------------------------------------
# Integration layer — live Neon
# --------------------------------------------------------------------------

pytestmark_integration = pytest.mark.integration

# The live layer reads DATABASE_URL from the repo-root .env, exactly as the
# app does. Without this the skipif below is evaluated before any app module
# has loaded the file.
load_dotenv()

needs_database = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL is not configured"
)


def _live_connect():
    return create_engine(os.getenv("DATABASE_URL"), poolclass=NullPool).connect()


def _live_ids():
    with _live_connect() as connection:
        doctor_id = connection.execute(
            text("SELECT id FROM doctor ORDER BY id LIMIT 1")
        ).scalar()
        patient_id = connection.execute(
            text("SELECT id FROM patient ORDER BY id LIMIT 1")
        ).scalar()
    return doctor_id, patient_id


def _delete_rows(ids):
    if not ids:
        return
    with _live_connect() as connection:
        connection.execute(
            text("DELETE FROM appointment WHERE id = ANY(:ids)"),
            {"ids": list(ids)},
        )
        connection.commit()


def _live_insert(connection, doctor_id, patient_id, status, start=SLOT_START):
    return connection.execute(
        text(
            "INSERT INTO appointment "
            "(doctor_id, patient_id, appointment_date, start_time, end_time, status) "
            "VALUES (:doctor, :patient, :day, :start, :end, :status) RETURNING id"
        ),
        {
            "doctor": doctor_id,
            "patient": patient_id,
            "day": SLOT_DAY,
            "start": start,
            "end": SLOT_END,
            "status": status,
        },
    ).scalar()


@needs_database
@pytestmark_integration
def test_live_index_is_partial_and_not_a_plain_constraint():
    """The deployed index must be partial, or cancelled slots stay locked.

    A plain ``UNIQUE (doctor_id, appointment_date, start_time)`` closes the
    race but also counts cancelled rows, which is the failure this asserts
    against.
    """
    with _live_connect() as connection:
        definitions = [
            row[0]
            for row in connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'appointment' "
                    "AND indexdef ILIKE '%doctor_id%'"
                )
            )
        ]

        plain_constraints = connection.execute(
            text(
                """
                SELECT pg_get_constraintdef(c.oid)
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'appointment' AND c.contype = 'u'
                """
            )
        ).all()

    assert definitions, "no index covers (doctor_id, appointment_date, start_time)"
    assert any(
        "where" in definition.lower() and "booked" in definition.lower()
        for definition in definitions
    ), f"expected a partial index on status='booked', found: {definitions}"

    covering = [
        row[0]
        for row in plain_constraints
        if "doctor_id" in row[0] and "appointment_date" in row[0]
    ]
    assert not covering, (
        "a plain UNIQUE constraint still covers the slot columns: "
        f"{covering}. Cancelled slots can never be rebooked."
    )


@needs_database
@pytestmark_integration
def test_live_concurrent_duplicate_booking_creates_one_row():
    """Two transactions that both saw the slot free: only one may commit."""
    doctor_id, patient_id = _live_ids()
    created = []
    barrier = threading.Barrier(2)
    outcomes = []

    def worker(label):
        with _live_connect() as connection:
            transaction = connection.begin()
            seen = connection.execute(
                text(
                    "SELECT count(*) FROM appointment WHERE doctor_id = :doctor "
                    "AND appointment_date = :day AND start_time = :start "
                    "AND status = 'booked'"
                ),
                {"doctor": doctor_id, "day": SLOT_DAY, "start": SLOT_START},
            ).scalar()

            barrier.wait(timeout=10)  # both saw the same pre-insert state

            try:
                appointment_id = _live_insert(
                    connection, doctor_id, patient_id, "booked"
                )
                transaction.commit()
                outcomes.append((label, seen, "committed", appointment_id))
                created.append(appointment_id)
            except IntegrityError:
                transaction.rollback()
                outcomes.append((label, seen, "rejected", None))

    threads = [threading.Thread(target=worker, args=(f"T{i}",)) for i in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        with _live_connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT count(*) FROM appointment WHERE doctor_id = :doctor "
                    "AND appointment_date = :day AND start_time = :start"
                ),
                {"doctor": doctor_id, "day": SLOT_DAY, "start": SLOT_START},
            ).scalar()

        assert all(seen == 0 for _, seen, _, _ in outcomes), outcomes
        assert [outcome for _, _, outcome, _ in outcomes].count("committed") == 1
        assert rows == 1
    finally:
        _delete_rows(created)


@needs_database
@pytestmark_integration
def test_live_cancelled_slot_can_be_rebooked():
    """Cancel, then book the same slot: must succeed."""
    doctor_id, patient_id = _live_ids()
    created = []

    try:
        with _live_connect() as connection:
            created.append(_live_insert(connection, doctor_id, patient_id, "cancelled"))
            connection.commit()

        with _live_connect() as connection:
            created.append(_live_insert(connection, doctor_id, patient_id, "booked"))
            connection.commit()

        assert len(created) == 2
    finally:
        _delete_rows(created)


@needs_database
@pytestmark_integration
def test_live_app_level_concurrent_booking_creates_one_row():
    """The application guard, not just the index, serializes two writers.

    Both threads call ``book_appointment`` at the same moment. The doctor-row
    lock makes the second re-check see the first commit, so it must raise
    ``SlotTakenError`` — not IntegrityError, and certainly not a 500.
    """
    doctor_id, patient_id = _live_ids()
    created = []
    barrier = threading.Barrier(2)
    outcomes = []

    def worker(label):
        engine = create_engine(os.getenv("DATABASE_URL"), poolclass=NullPool)
        try:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                try:
                    appointment = book_appointment(
                        session,
                        doctor_id=doctor_id,
                        patient_id=patient_id,
                        appointment_date=SLOT_DAY,
                        start_time=SLOT_START,
                        end_time=SLOT_END,
                    )
                    outcomes.append((label, "booked", appointment.id))
                    created.append(appointment.id)
                except SlotTakenError:
                    outcomes.append((label, "slot_taken", None))
        finally:
            engine.dispose()

    threads = [
        threading.Thread(target=worker, args=(f"T{i}",)) for i in range(2)
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert [outcome for _, outcome, _ in outcomes].count("booked") == 1
        assert [outcome for _, outcome, _ in outcomes].count("slot_taken") == 1

        with _live_connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT count(*) FROM appointment WHERE doctor_id = :doctor "
                    "AND appointment_date = :day AND start_time = :start"
                ),
                {"doctor": doctor_id, "day": SLOT_DAY, "start": SLOT_START},
            ).scalar()

        assert rows == 1
    finally:
        _delete_rows(created)
