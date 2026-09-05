from sqlmodel import Session

from app.crud import get_doctor_schedule, get_doctors, get_patient_appointments
from app.db import engine


def _serialize(doctor) -> dict:
    return {
        "id": doctor.id,
        "name": doctor.name,
        "specialization": doctor.specialization,
        "consultation_fee": doctor.consultation_fee,
    }


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
    """All registered doctors (name + specialization + fee)."""
    with Session(engine) as session:
        return [_serialize(doctor) for doctor in get_doctors(session)]


def get_consultation_fees(doctor_id: int | None = None) -> list[dict]:
    """Consultation fees (PKR). One doctor by id, or all when omitted."""
    with Session(engine) as session:
        doctors = get_doctors(session)
        if doctor_id is not None:
            doctors = [doctor for doctor in doctors if doctor.id == doctor_id]
        return [
            {
                "name": doctor.name,
                "specialization": doctor.specialization,
                "consultation_fee": doctor.consultation_fee,
            }
            for doctor in doctors
        ]


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


_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def doctor_details(question: str) -> str | None:
    """Details (specialization, fee, weekly schedule) for one doctor
    mentioned by name in the question. None when no doctor is mentioned."""
    with Session(engine) as session:
        doctors = get_doctors(session)

    text = question.lower().replace("dr.", " ").replace("dr", " ")

    matched = None
    for doctor in doctors:
        name = doctor.name.lower()
        if name in text:
            matched = doctor
            break

        tokens = [token for token in name.split() if len(token) > 3]
        if tokens and any(token in text for token in tokens):
            matched = doctor
            break

    if matched is None:
        return None

    fee = (
        f"PKR {matched.consultation_fee}"
        if matched.consultation_fee is not None
        else "fee not set"
    )

    slots = get_schedule(matched.id)
    if slots:
        schedule = "\n".join(
            f"- {_DAY_NAMES[slot['day_of_week']]}: "
            f"{slot['start_time']}-{slot['end_time']}"
            for slot in slots
        )
    else:
        schedule = "- no weekly schedule set"

    return (
        f"{matched.name} ({matched.specialization})\n"
        f"Consultation fee: {fee}\n"
        f"Weekly schedule:\n{schedule}"
    )
