import re

from sqlmodel import Session

from app.crud import get_doctor_schedule, get_doctors, get_patient_appointments
from app.db import get_engine


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
    with Session(get_engine()) as session:
        return [_serialize(doctor) for doctor in get_doctors(session)]


# A question usually names a specialty the way a patient would say it, not
# the way it is stored ("general physician" vs "General Medicine"), so each
# stored value carries the phrasings that should retrieve it.
SPECIALTY_ALIASES: dict[str, tuple[str, ...]] = {
    "cardiology": ("cardiologist",),
    "dermatology": ("dermatologist",),
    "pediatrics": ("pediatrician", "paediatrician"),
    "orthopedics": ("orthopedic", "orthopaedic"),
    "general medicine": (
        "general physician",
        "general practitioner",
        "family physician",
        "gp",
    ),
}


def find_by_specialization(
    question: str, doctors: list[dict]
) -> tuple[list[dict], list[str]] | None:
    """
    The doctors whose specialization the question asks for.

    Returns (matched, specializations) when the question names at least one
    specialty, or None when it names none — the caller then lists every
    doctor, which is the right answer to "which doctors are available?".

    `matched` is never empty: a specialty only counts as named when some
    doctor holds it, so "any general physician available?" narrows the list
    instead of replying that no such specialty exists.
    """
    text = question.lower()
    matched: list[dict] = []
    specializations: list[str] = []

    for doctor in doctors:
        spec = doctor["specialization"]
        terms = (spec.lower(), *SPECIALTY_ALIASES.get(spec.lower(), ()))

        # Word-boundary match so "gp" does not fire inside an unrelated
        # token, and the plural form does not match its own adjective.
        if not any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms):
            continue

        matched.append(doctor)
        if spec not in specializations:
            specializations.append(spec)

    if not matched:
        return None

    return matched, specializations


def get_consultation_fees(doctor_id: int | None = None) -> list[dict]:
    """Consultation fees (PKR). One doctor by id, or all when omitted."""
    with Session(get_engine()) as session:
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
    with Session(get_engine()) as session:
        return [_serialize_slot(slot) for slot in get_doctor_schedule(session, doctor_id)]


def get_appointments(patient_id: int) -> list[dict]:
    """All appointments for one patient."""
    with Session(get_engine()) as session:
        return [
            _serialize_appointment(appointment)
            for appointment in get_patient_appointments(session, patient_id)
        ]


_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _matching_doctors(text: str) -> list[dict]:
    """
    Every doctor whose name appears in `text`, in registration order.

    Tolerant matching: the full name, a single name fragment, or a
    shortened / slightly misspelled first name ("sara" for "Sarah") all
    count, so a question that abbreviates a name still resolves instead of
    falling through to the generic doctor list.
    """
    with Session(get_engine()) as session:
        doctors = get_doctors(session)

    text = text.lower().replace("dr.", " ").replace("dr", " ")
    # Words long enough to be a real name fragment; short ones ("4pm")
    # would prefix-match too eagerly.
    words = [word for word in text.split() if len(word) >= 4]

    matches = []
    for doctor in doctors:
        name = doctor.name.lower()

        if name in text:
            matches.append(_serialize(doctor))
            continue

        tokens = [token for token in name.split() if len(token) > 3]
        # Match a full name token, or a typed word that shares a prefix
        # with one ("sara" -> "sarah"), so shortening and common typos
        # still resolve to the doctor.
        if tokens and any(
            token in text
            or any(word.startswith(token) or token.startswith(word) for word in words)
            for token in tokens
        ):
            matches.append(_serialize(doctor))

    return matches


def named_doctor(text: str) -> dict | None:
    """The doctor named in `text`. None when it names none."""
    matches = _matching_doctors(text)
    return matches[0] if matches else None


def referenced_doctor(history: list[dict] | None) -> dict | None:
    """
    The single doctor the conversation is already talking about.

    "what her fee" names nobody — the referent is whoever the previous
    answer mentioned, so the most recent turn that names exactly one doctor
    decides. A turn that names several is a directory rather than a
    referent ("Registered doctors: ... five of them"), and returning None
    keeps the caller's full listing as the answer instead of picking one
    arbitrarily.

    Scans backwards and stops at the first turn that names any doctor, so
    an older mention cannot override the current subject.
    """
    for message in reversed(history or []):
        content = str(message.get("content", ""))
        if not content:
            continue

        matches = _matching_doctors(content)

        if len(matches) == 1:
            return matches[0]
        if matches:
            return None

    return None


def format_doctor_details(doctor: dict) -> str:
    """Name, specialization, consultation fee and weekly schedule."""
    fee = (
        f"PKR {doctor['consultation_fee']}"
        if doctor["consultation_fee"] is not None
        else "fee not set"
    )

    slots = get_schedule(doctor["id"])
    if slots:
        schedule = "\n".join(
            f"- {_DAY_NAMES[slot['day_of_week']]}: "
            f"{slot['start_time']}-{slot['end_time']}"
            for slot in slots
        )
    else:
        schedule = "- no weekly schedule set"

    return (
        f"{doctor['name']} ({doctor['specialization']})\n"
        f"Consultation fee: {fee}\n"
        f"Weekly schedule:\n{schedule}"
    )


def doctor_details(question: str) -> str | None:
    """Details (specialization, fee, weekly schedule) for one doctor
    mentioned by name in the question. None when no doctor is mentioned."""
    doctor = named_doctor(question)
    return None if doctor is None else format_doctor_details(doctor)
