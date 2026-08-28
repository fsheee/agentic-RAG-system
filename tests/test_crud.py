from datetime import date, time

import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.schema  # noqa: F401 — registers models on SQLModel.metadata
from app import crud
from app.schema import Appointment, Doctor, DoctorSchedule, Patient


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def doctor(session):
    doctor = Doctor(name="Dr. Sarah Ahmed", specialization="Cardiology")
    session.add(doctor)
    session.commit()
    session.refresh(doctor)
    return doctor


@pytest.fixture
def patient(session):
    patient = Patient(name="Ali Khan", phone="03001234567")
    session.add(patient)
    session.commit()
    session.refresh(patient)
    return patient


# --- doctors ---


def test_get_doctors_returns_all(session, doctor):
    session.add(Doctor(name="Dr. Bilal Raza", specialization="Dermatology"))
    session.commit()

    doctors = crud.get_doctors(session)

    assert len(doctors) == 2
    assert {d.name for d in doctors} == {"Dr. Sarah Ahmed", "Dr. Bilal Raza"}


def test_get_doctor_by_id(session, doctor):
    found = crud.get_doctor_by_id(session, doctor.id)

    assert found is not None
    assert found.name == "Dr. Sarah Ahmed"


def test_get_doctor_by_id_missing_returns_none(session):
    assert crud.get_doctor_by_id(session, 999) is None


# --- schedules ---


def test_get_doctor_schedule_filters_by_doctor(session, doctor):
    other = Doctor(name="Dr. Bilal Raza", specialization="Dermatology")
    session.add(other)
    session.commit()

    session.add(DoctorSchedule(doctor_id=doctor.id, day_of_week=0, start_time=time(9), end_time=time(17)))
    session.add(DoctorSchedule(doctor_id=doctor.id, day_of_week=2, start_time=time(9), end_time=time(13)))
    session.add(DoctorSchedule(doctor_id=other.id, day_of_week=0, start_time=time(10), end_time=time(16)))
    session.commit()

    schedule = crud.get_doctor_schedule(session, doctor.id)

    assert len(schedule) == 2
    assert all(s.doctor_id == doctor.id for s in schedule)


# --- appointments ---


def test_book_appointment_creates_booked_row(session, doctor, patient):
    appointment = crud.book_appointment(
        session,
        doctor_id=doctor.id,
        patient_id=patient.id,
        appointment_date=date(2026, 9, 1),
        start_time=time(10),
        end_time=time(10, 30),
    )

    assert appointment.id is not None
    assert appointment.status == "booked"
    assert appointment.doctor_id == doctor.id


def test_cancel_appointment_sets_status(session, doctor, patient):
    appointment = crud.book_appointment(
        session,
        doctor_id=doctor.id,
        patient_id=patient.id,
        appointment_date=date(2026, 9, 1),
        start_time=time(10),
        end_time=time(10, 30),
    )

    cancelled = crud.cancel_appointment(session, appointment.id)

    assert cancelled.status == "cancelled"


def test_cancel_appointment_missing_returns_none(session):
    assert crud.cancel_appointment(session, 999) is None


def test_reschedule_appointment_updates_slot(session, doctor, patient):
    appointment = crud.book_appointment(
        session,
        doctor_id=doctor.id,
        patient_id=patient.id,
        appointment_date=date(2026, 9, 1),
        start_time=time(10),
        end_time=time(10, 30),
    )

    rescheduled = crud.reschedule_appointment(
        session,
        appointment.id,
        appointment_date=date(2026, 9, 2),
        start_time=time(14),
        end_time=time(14, 30),
    )

    assert rescheduled.appointment_date == date(2026, 9, 2)
    assert rescheduled.start_time == time(14)


def test_reschedule_appointment_missing_returns_none(session):
    assert (
        crud.reschedule_appointment(
            session,
            999,
            appointment_date=date(2026, 9, 2),
            start_time=time(14),
            end_time=time(14, 30),
        )
        is None
    )


def test_get_patient_appointments_filters_by_patient(session, doctor, patient):
    other_patient = Patient(name="Ayesha Siddiqui", phone="03007654321")
    session.add(other_patient)
    session.commit()

    crud.book_appointment(
        session,
        doctor_id=doctor.id,
        patient_id=patient.id,
        appointment_date=date(2026, 9, 1),
        start_time=time(10),
        end_time=time(10, 30),
    )
    crud.book_appointment(
        session,
        doctor_id=doctor.id,
        patient_id=other_patient.id,
        appointment_date=date(2026, 9, 1),
        start_time=time(11),
        end_time=time(11, 30),
    )

    appointments = crud.get_patient_appointments(session, patient.id)

    assert len(appointments) == 1
    assert appointments[0].patient_id == patient.id


def test_find_conflicting_appointment(session, doctor, patient):
    crud.book_appointment(
        session,
        doctor_id=doctor.id,
        patient_id=patient.id,
        appointment_date=date(2026, 9, 1),
        start_time=time(10),
        end_time=time(10, 30),
    )

    conflict = crud.find_conflicting_appointment(
        session,
        doctor_id=doctor.id,
        appointment_date=date(2026, 9, 1),
        start_time=time(10, 15),
        end_time=time(10, 45),
    )

    assert conflict is not None
    assert conflict.start_time == time(10)


def test_find_conflicting_appointment_no_overlap(session, doctor, patient):
    crud.book_appointment(
        session,
        doctor_id=doctor.id,
        patient_id=patient.id,
        appointment_date=date(2026, 9, 1),
        start_time=time(10),
        end_time=time(10, 30),
    )

    conflict = crud.find_conflicting_appointment(
        session,
        doctor_id=doctor.id,
        appointment_date=date(2026, 9, 1),
        start_time=time(11),
        end_time=time(11, 30),
    )

    assert conflict is None
