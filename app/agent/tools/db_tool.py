from sqlmodel import Session

from app.crud import get_doctor_schedule, get_doctors, get_patient_appointments
from app.db import engine


def _serialize(doctor) -> dict:
    return {"id": doctor.id, "name": doctor.name, "specialization": doctor.specialization}


def _serialize_slot(slot) -> dict:
    return {
        "doctor_id": slot.doctor_id,
        "day_of_week": slot.day_of_week,
        "start_time": str(slot.start_time),
        "end_time": str(slot.end_time),
    }


def _serialize_appointment(appointment) -> dict:
    return {
        "id": appointment.id,
        "doctor_id": appointment.doctor_id,
        "appointment_date": str(appointment.appointment_date),
        "start_time": str(appointment.start_time),
        "end_time": str(appointment.end_time),
        "status": appointment.status,
    }


def list_doctors() -> list[dict]:
    """All registered doctors (name + specialization)."""
    with Session(engine) as session:
        return [_serialize(doctor) for doctor in get_doctors(session)]


def get_schedule(doctor_id: int) -> list[dict]:
    """Weekly schedule slots for one doctor."""
    with Session(engine) as session:
        return [_serialize_slot(slot) for slot in get_doctor_schedule(session, doctor_id)]


def get_appointments(patient_id: int) -> list[dict]:
    """All appointments for one patient."""
    with Session(engine) as session:
        return [
            _serialize_appointment(appointment)
            for appointment in get_patient_appointments(session, patient_id)
        ]
