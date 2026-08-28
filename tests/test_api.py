from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.schema  # noqa: F401 — registers models on SQLModel.metadata
from main import app, get_session
from app.schema import Doctor, DoctorSchedule, Patient


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(engine):
    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def doctor(engine):
    with Session(engine) as session:
        doctor = Doctor(name="Dr. Sarah Ahmed", specialization="Cardiology")
        session.add(doctor)
        session.flush()
        session.add(DoctorSchedule(doctor_id=doctor.id, day_of_week=0, start_time=time(9), end_time=time(17)))
        session.add(Patient(name="Ali Khan", phone="03001234567"))
        session.commit()
        session.refresh(doctor)
        return doctor


def test_get_doctors(client, doctor):
    response = client.get("/doctors")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Dr. Sarah Ahmed"


def test_get_doctor_not_found(client):
    assert client.get("/doctors/999").status_code == 404


def test_get_doctor_schedule(client, doctor):
    response = client.get(f"/doctors/{doctor.id}/schedule")

    assert response.status_code == 200
    assert response.json()[0]["day_of_week"] == 0


def test_book_appointment(client, doctor):
    response = client.post(
        "/appointments",
        json={
            "doctor_id": doctor.id,
            "patient_id": 1,
            "appointment_date": "2026-09-01",
            "start_time": "10:00:00",
            "end_time": "10:30:00",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "booked"


def test_book_appointment_conflict_returns_409(client, doctor):
    payload = {
        "doctor_id": doctor.id,
        "patient_id": 1,
        "appointment_date": "2026-09-01",
        "start_time": "10:00:00",
        "end_time": "10:30:00",
    }
    client.post("/appointments", json=payload)

    response = client.post("/appointments", json=payload)

    assert response.status_code == 409


def test_book_appointment_missing_doctor_returns_404(client):
    response = client.post(
        "/appointments",
        json={
            "doctor_id": 999,
            "patient_id": 1,
            "appointment_date": "2026-09-01",
            "start_time": "10:00:00",
            "end_time": "10:30:00",
        },
    )

    assert response.status_code == 404


def test_reschedule_appointment(client, doctor):
    appointment_id = client.post(
        "/appointments",
        json={
            "doctor_id": doctor.id,
            "patient_id": 1,
            "appointment_date": "2026-09-01",
            "start_time": "10:00:00",
            "end_time": "10:30:00",
        },
    ).json()["id"]

    response = client.put(
        f"/appointments/{appointment_id}",
        json={
            "appointment_date": "2026-09-02",
            "start_time": "14:00:00",
            "end_time": "14:30:00",
        },
    )

    assert response.status_code == 200
    assert response.json()["appointment_date"] == "2026-09-02"


def test_cancel_appointment(client, doctor):
    appointment_id = client.post(
        "/appointments",
        json={
            "doctor_id": doctor.id,
            "patient_id": 1,
            "appointment_date": "2026-09-01",
            "start_time": "10:00:00",
            "end_time": "10:30:00",
        },
    ).json()["id"]

    response = client.delete(f"/appointments/{appointment_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_appointment_not_found(client):
    assert client.delete("/appointments/999").status_code == 404


def test_get_patient_appointments(client, doctor):
    client.post(
        "/appointments",
        json={
            "doctor_id": doctor.id,
            "patient_id": 1,
            "appointment_date": "2026-09-01",
            "start_time": "10:00:00",
            "end_time": "10:30:00",
        },
    )

    response = client.get("/patients/1/appointments")

    assert response.status_code == 200
    assert len(response.json()) == 1
