"""Authorization rules for the REST appointment/doctor endpoints.

These run against a real (in-memory SQLite) database, so the actual CRUD,
ownership and availability helpers are exercised — not stubs. Identity
comes from a real signed JWT, so require_roles() is tested end to end.

The rule under test throughout: a caller's role and user id come from the
token, never from the request body, and a patient or doctor only ever
reaches their own records.
"""

from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import api
from app.auth import create_access_token
from app.crud import book_appointment
from app.db import get_session
from app.schema import Doctor, DoctorSchedule, Patient, Role, User

# 2026-09-28 is a Monday (weekday 0), which is when both doctors work.
MONDAY = date(2026, 9, 28)


def _seed(session: Session) -> dict:
    """Two doctors (one with a login, one without) and six accounts."""
    doctor_a = Doctor(
        name="Dr. Sarah Ahmed", specialization="Cardiology", consultation_fee=3000
    )
    doctor_b = Doctor(
        name="Dr. Bilal Raza", specialization="Dermatology", consultation_fee=2500
    )
    session.add(doctor_a)
    session.add(doctor_b)
    session.flush()

    for doctor in (doctor_a, doctor_b):
        session.add(
            DoctorSchedule(
                doctor_id=doctor.id,
                day_of_week=0,  # Monday
                start_time=time(9),
                end_time=time(13),
            )
        )

    users = {
        "patient": User(
            name="Ali Khan",
            email="ali@example.com",
            password_hash="x",
            role=Role.patient,
        ),
        "other_patient": User(
            name="Sara Malik",
            email="sara@example.com",
            password_hash="x",
            role=Role.patient,
        ),
        # A patient account with no linked Patient row.
        "orphan_patient": User(
            name="No Record",
            email="orphan@example.com",
            password_hash="x",
            role=Role.patient,
        ),
        "admin": User(
            name="Admin",
            email="admin@example.com",
            password_hash="x",
            role=Role.admin,
        ),
        "doctor": User(
            name="Dr. Sarah Ahmed",
            email="sarah@example.com",
            password_hash="x",
            role=Role.doctor,
        ),
        # A doctor account with no linked Doctor row.
        "unlinked_doctor": User(
            name="Dr. Nobody",
            email="nobody@example.com",
            password_hash="x",
            role=Role.doctor,
        ),
    }
    for user in users.values():
        session.add(user)
    session.flush()

    patient_a = Patient(name="Ali Khan", phone="1", user_id=users["patient"].id)
    patient_b = Patient(name="Sara Malik", phone="2", user_id=users["other_patient"].id)
    session.add(patient_a)
    session.add(patient_b)

    # Only doctor_a has a login; Dr. Bilal Raza has no account.
    doctor_a.user_id = users["doctor"].id
    session.add(doctor_a)
    session.commit()

    return {
        "users": users,
        "doctor_a": doctor_a,
        "doctor_b": doctor_b,
        "patient_a": patient_a,
        "patient_b": patient_b,
    }


@pytest.fixture()
def client():
    # In-memory SQLite so these tests need no live Neon. StaticPool keeps a
    # single shared connection so the schema and data persist across the
    # per-request sessions.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def test_session():
        with Session(engine) as session:
            yield session

    # expire_on_commit=False keeps the seeded rows usable after the commit
    # closes this session — the tests read ids and roles off them to build
    # tokens.
    with Session(engine, expire_on_commit=False) as session:
        data = _seed(session)

    api.app.dependency_overrides[get_session] = test_session
    yield TestClient(api.app), data, engine
    api.app.dependency_overrides.clear()


def _auth(user: User) -> dict:
    """Bearer header for a real signed token (role comes from the token)."""
    token = create_access_token(user.id, user.role.value)
    return {"Authorization": f"Bearer {token}"}


def _make_appointment(engine, doctor_id: int, patient_id: int, start_hour: int = 10):
    """Insert an appointment directly, for tests that need existing data."""
    with Session(engine) as session:
        return book_appointment(
            session,
            doctor_id=doctor_id,
            patient_id=patient_id,
            appointment_date=MONDAY,
            start_time=time(start_hour),
            end_time=time(start_hour, 30),
        )


# --------------------------------------------------------------------------
# GET /doctors — public
# --------------------------------------------------------------------------


def test_doctor_list_is_public(client):
    """Doctor lists are public hospital information (matches the agent)."""
    http, _data, _engine = client

    response = http.get("/doctors")

    assert response.status_code == 200
    assert {d["name"] for d in response.json()} == {
        "Dr. Sarah Ahmed",
        "Dr. Bilal Raza",
    }


# --------------------------------------------------------------------------
# Patient
# --------------------------------------------------------------------------


def test_patient_books_an_appointment(client):
    http, data, _engine = client

    response = http.post(
        "/appointments",
        json={
            "doctor_id": data["doctor_a"].id,
            "appointment_date": str(MONDAY),
            "start_time": "10:00",
        },
        headers=_auth(data["users"]["patient"]),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["doctor_name"] == "Dr. Sarah Ahmed"
    assert body["patient_name"] == "Ali Khan"
    assert body["patient_id"] == data["patient_a"].id
    assert body["status"] == "booked"


def test_patient_cannot_book_for_someone_else(client):
    """A patient_id in the body must be ignored: identity comes from the JWT."""
    http, data, _engine = client

    response = http.post(
        "/appointments",
        json={
            "doctor_id": data["doctor_a"].id,
            "appointment_date": str(MONDAY),
            "start_time": "10:00",
            "patient_id": data["patient_b"].id,
        },
        headers=_auth(data["users"]["patient"]),
    )

    assert response.status_code == 201
    assert response.json()["patient_id"] == data["patient_a"].id


def test_patient_does_not_see_another_patients_appointments(client):
    http, data, engine = client
    _make_appointment(engine, data["doctor_a"].id, data["patient_b"].id, start_hour=11)

    response = http.get("/appointments", headers=_auth(data["users"]["patient"]))

    assert response.status_code == 200
    assert response.json() == []  # patient A has none; B's is not visible


def test_patient_sees_their_own_appointment(client):
    http, data, engine = client
    _make_appointment(engine, data["doctor_a"].id, data["patient_a"].id)

    response = http.get("/appointments", headers=_auth(data["users"]["patient"]))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["patient_id"] == data["patient_a"].id


def test_patient_without_a_linked_record_gets_404(client):
    http, data, _engine = client

    response = http.get("/appointments", headers=_auth(data["users"]["orphan_patient"]))

    assert response.status_code == 404


def test_patient_cannot_update_an_appointment(client):
    http, data, engine = client
    appointment = _make_appointment(engine, data["doctor_a"].id, data["patient_a"].id)

    response = http.patch(
        f"/admin/appointments/{appointment.id}",
        json={"status": "cancelled"},
        headers=_auth(data["users"]["patient"]),
    )

    assert response.status_code == 403


def test_patient_cannot_delete_an_appointment(client):
    http, data, engine = client
    appointment = _make_appointment(engine, data["doctor_a"].id, data["patient_a"].id)

    response = http.delete(
        f"/admin/appointments/{appointment.id}",
        headers=_auth(data["users"]["patient"]),
    )

    assert response.status_code == 403


def test_patient_cannot_list_all_appointments(client):
    http, data, _engine = client

    response = http.get(
        "/admin/appointments", headers=_auth(data["users"]["patient"])
    )

    assert response.status_code == 403


def test_anonymous_caller_is_rejected(client):
    """No token: 401 for a missing credential. Appointment and doctor
    detail routes always need an identity — unlike /doctors and /ask."""
    http, _data, _engine = client

    assert http.get("/appointments").status_code == 401
    assert http.get("/doctors/me/schedule").status_code == 401
    assert http.get("/admin/appointments").status_code == 401


def test_booking_outside_the_schedule_conflicts(client):
    http, data, _engine = client

    response = http.post(
        "/appointments",
        json={
            "doctor_id": data["doctor_a"].id,
            "appointment_date": str(MONDAY),
            "start_time": "20:00",  # doctor works 09:00-13:00
        },
        headers=_auth(data["users"]["patient"]),
    )

    assert response.status_code == 409


def test_double_booking_the_same_slot_conflicts(client):
    http, data, _engine = client
    slot = {
        "doctor_id": data["doctor_a"].id,
        "appointment_date": str(MONDAY),
        "start_time": "10:00",
    }
    headers = _auth(data["users"]["patient"])

    assert http.post("/appointments", json=slot, headers=headers).status_code == 201
    assert http.post("/appointments", json=slot, headers=headers).status_code == 409


def test_booking_an_unknown_doctor_is_404(client):
    http, _data, _engine = client

    response = http.post(
        "/appointments",
        json={
            "doctor_id": 9999,
            "appointment_date": str(MONDAY),
            "start_time": "10:00",
        },
        headers=_auth(_data["users"]["patient"]),
    )

    assert response.status_code == 404


# --------------------------------------------------------------------------
# Doctor
# --------------------------------------------------------------------------


def test_doctor_sees_only_their_own_schedule(client):
    http, data, _engine = client

    response = http.get(
        "/doctors/me/schedule", headers=_auth(data["users"]["doctor"])
    )

    assert response.status_code == 200
    assert response.json() == [
        {"day_of_week": 0, "start_time": "09:00:00", "end_time": "13:00:00"}
    ]


def test_doctor_sees_only_their_own_appointments(client):
    http, data, engine = client
    # One with Dr. Sarah (the caller) and one with Dr. Bilal.
    _make_appointment(engine, data["doctor_a"].id, data["patient_a"].id)
    _make_appointment(engine, data["doctor_b"].id, data["patient_a"].id)

    response = http.get(
        "/doctors/me/appointments", headers=_auth(data["users"]["doctor"])
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["doctor_id"] == data["doctor_a"].id


def test_doctor_without_a_linked_record_gets_404(client):
    http, data, _engine = client

    for path in ("/doctors/me/schedule", "/doctors/me/appointments"):
        response = http.get(path, headers=_auth(data["users"]["unlinked_doctor"]))
        assert response.status_code == 404, path


def test_doctor_cannot_update_or_delete_appointments(client):
    http, data, engine = client
    appointment = _make_appointment(engine, data["doctor_a"].id, data["patient_a"].id)
    headers = _auth(data["users"]["doctor"])

    updated = http.patch(
        f"/admin/appointments/{appointment.id}",
        json={"status": "cancelled"},
        headers=headers,
    )
    deleted = http.delete(f"/admin/appointments/{appointment.id}", headers=headers)

    assert updated.status_code == 403
    assert deleted.status_code == 403


def test_doctor_cannot_list_all_appointments(client):
    http, data, _engine = client

    response = http.get("/admin/appointments", headers=_auth(data["users"]["doctor"]))

    assert response.status_code == 403


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------


def test_admin_sees_all_appointments(client):
    http, data, engine = client
    _make_appointment(engine, data["doctor_a"].id, data["patient_a"].id)
    _make_appointment(engine, data["doctor_b"].id, data["patient_b"].id, start_hour=11)

    headers = _auth(data["users"]["admin"])
    listing = http.get("/admin/appointments", headers=headers)

    assert listing.status_code == 200
    assert len(listing.json()) == 2
    # GET /appointments gives an admin the same view.
    assert len(http.get("/appointments", headers=headers).json()) == 2


def test_admin_updates_an_appointment(client):
    http, data, engine = client
    appointment = _make_appointment(engine, data["doctor_a"].id, data["patient_a"].id)

    response = http.patch(
        f"/admin/appointments/{appointment.id}",
        json={"status": "cancelled"},
        headers=_auth(data["users"]["admin"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_admin_update_rejects_an_unknown_status(client):
    http, data, engine = client
    appointment = _make_appointment(engine, data["doctor_a"].id, data["patient_a"].id)

    response = http.patch(
        f"/admin/appointments/{appointment.id}",
        json={"status": "banana"},
        headers=_auth(data["users"]["admin"]),
    )

    assert response.status_code == 422


def test_admin_update_still_validates_the_slot(client):
    http, data, engine = client
    appointment = _make_appointment(engine, data["doctor_a"].id, data["patient_a"].id)

    response = http.patch(
        f"/admin/appointments/{appointment.id}",
        json={"start_time": "20:00"},  # outside the doctor's hours
        headers=_auth(data["users"]["admin"]),
    )

    assert response.status_code == 409


def test_admin_deletes_an_appointment(client):
    http, data, engine = client
    appointment = _make_appointment(engine, data["doctor_a"].id, data["patient_a"].id)

    headers = _auth(data["users"]["admin"])
    response = http.delete(f"/admin/appointments/{appointment.id}", headers=headers)

    assert response.status_code == 204
    assert http.get("/admin/appointments", headers=headers).json() == []


def test_admin_delete_of_a_missing_appointment_is_404(client):
    http, data, _engine = client

    response = http.delete(
        "/admin/appointments/9999", headers=_auth(data["users"]["admin"])
    )

    assert response.status_code == 404


# --------------------------------------------------------------------------
# Admin — doctor schedules (the runtime replacement for the seeded dict)
# --------------------------------------------------------------------------


def test_admin_reads_any_doctors_schedule(client):
    http, data, _engine = client

    response = http.get(
        f"/admin/doctors/{data['doctor_a'].id}/schedule",
        headers=_auth(data["users"]["admin"]),
    )

    assert response.status_code == 200
    assert response.json() == [
        {"day_of_week": 0, "start_time": "09:00:00", "end_time": "13:00:00"}
    ]


def test_admin_replaces_a_doctors_schedule(client):
    http, data, _engine = client

    response = http.put(
        f"/admin/doctors/{data['doctor_a'].id}/schedule",
        json={
            "slots": [
                {"day_of_week": 1, "start_time": "10:00", "end_time": "14:00"},
                {"day_of_week": 3, "start_time": "10:00", "end_time": "14:00"},
            ]
        },
        headers=_auth(data["users"]["admin"]),
    )

    assert response.status_code == 200
    assert response.json() == [
        {"day_of_week": 1, "start_time": "10:00:00", "end_time": "14:00:00"},
        {"day_of_week": 3, "start_time": "10:00:00", "end_time": "14:00:00"},
    ]
    # Replacing, not merging: the original Monday slot is gone.
    assert all(slot["day_of_week"] != 0 for slot in response.json())


def test_admin_schedule_change_takes_effect_on_booking(client):
    """The whole point: an admin edits hours, and booking follows."""
    http, data, _engine = client
    headers = _auth(data["users"]["admin"])
    slot = {
        "doctor_id": data["doctor_a"].id,
        "appointment_date": str(MONDAY),
        "start_time": "10:00",
    }
    patient = _auth(data["users"]["patient"])

    assert http.post("/appointments", json=slot, headers=patient).status_code == 201

    # Move the doctor off Mondays entirely.
    http.put(
        f"/admin/doctors/{data['doctor_a'].id}/schedule",
        json={"slots": [{"day_of_week": 2, "start_time": "09:00", "end_time": "13:00"}]},
        headers=headers,
    )

    later = dict(slot, start_time="11:00")
    assert http.post("/appointments", json=later, headers=patient).status_code == 409


def test_admin_can_clear_a_schedule(client):
    http, data, _engine = client
    headers = _auth(data["users"]["admin"])

    response = http.put(
        f"/admin/doctors/{data['doctor_a'].id}/schedule",
        json={"slots": []},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == []


def test_admin_schedule_rejects_a_backwards_slot(client):
    http, data, _engine = client

    response = http.put(
        f"/admin/doctors/{data['doctor_a'].id}/schedule",
        json={"slots": [{"day_of_week": 0, "start_time": "14:00", "end_time": "09:00"}]},
        headers=_auth(data["users"]["admin"]),
    )

    assert response.status_code == 422


def test_admin_schedule_rejects_overlapping_slots(client):
    http, data, _engine = client

    response = http.put(
        f"/admin/doctors/{data['doctor_a'].id}/schedule",
        json={
            "slots": [
                {"day_of_week": 0, "start_time": "09:00", "end_time": "12:00"},
                {"day_of_week": 0, "start_time": "11:00", "end_time": "13:00"},
            ]
        },
        headers=_auth(data["users"]["admin"]),
    )

    assert response.status_code == 422


def test_admin_schedule_rejects_an_out_of_range_day(client):
    http, data, _engine = client

    response = http.put(
        f"/admin/doctors/{data['doctor_a'].id}/schedule",
        json={"slots": [{"day_of_week": 9, "start_time": "09:00", "end_time": "12:00"}]},
        headers=_auth(data["users"]["admin"]),
    )

    assert response.status_code == 422


def test_admin_schedule_for_an_unknown_doctor_is_404(client):
    http, data, _engine = client
    headers = _auth(data["users"]["admin"])

    assert http.get("/admin/doctors/9999/schedule", headers=headers).status_code == 404
    assert (
        http.put(
            "/admin/doctors/9999/schedule", json={"slots": []}, headers=headers
        ).status_code
        == 404
    )


def test_non_admins_cannot_change_a_schedule(client):
    """Doctors and patients must not be able to edit working hours."""
    http, data, _engine = client
    body = {"slots": [{"day_of_week": 0, "start_time": "09:00", "end_time": "12:00"}]}
    path = f"/admin/doctors/{data['doctor_a'].id}/schedule"

    for who in ("doctor", "patient"):
        headers = _auth(data["users"][who])
        assert http.put(path, json=body, headers=headers).status_code == 403, who
        assert http.get(path, headers=headers).status_code == 403, who
