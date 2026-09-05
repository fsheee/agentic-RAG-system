"""Appointment booking tool.

Booking is a multi-step LangGraph workflow with explicit state instead of
one immediate call:

    parse -> check availability -> ask confirmation -> book

An appointment is only created after the user explicitly confirms.

Single-user demo: bookings are made for the seeded patient (Ali Khan) and
the pending booking state is kept in memory between turns.
"""

import re
from datetime import date, datetime, time, timedelta
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlmodel import Session, select

from app.crud import (
    book_appointment,
    cancel_appointment,
    find_conflicting_appointment,
    get_doctor_schedule,
    get_doctors,
    get_patient_appointments,
    reschedule_appointment,
)
from app.db import engine
from app.schema import Appointment, Patient

DEFAULT_PATIENT_NAME = "Ali Khan"
APPOINTMENT_MINUTES = 30

CONFIRM_WORDS = ("yes", "confirm", "sure", "ok", "book it")
DENY_WORDS = ("no", "cancel", "don't", "do not", "stop")


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def is_awaiting_confirmation() -> bool:
    """True while a booking is waiting for the user's yes/no reply."""
    return bool(_pending.get("awaiting_confirmation"))


def reset_pending():
    """Forget any pending booking (used by tests)."""
    global _pending
    _pending = {}


_pending: dict = {}


def _find_patient(session: Session) -> Patient | None:
    return session.exec(
        select(Patient).where(Patient.name == DEFAULT_PATIENT_NAME)
    ).first()


def _find_doctor(question: str, doctors):
    """Match a doctor by name in the question ('dr. ayesha', full name...)."""
    text = question.lower().replace("dr.", " ").replace("dr", " ")

    for doctor in doctors:
        name = doctor.name.lower()
        if name in text:
            return doctor

        # Match on any single distinctive name token ("dr. ayesha",
        # "siddiqui") when the full name is not spelled out.
        tokens = [
            token
            for token in name.replace("dr.", "").split()
            if len(token) > 3
        ]
        if tokens and any(token in text for token in tokens):
            return doctor

    return None


_ISO_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DMY_DATE = re.compile(r"\b(\d{1,2})[/](\d{1,2})[/](\d{4})\b")

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _parse_date(text: str) -> date | None:
    lowered = text.lower()

    if "tomorrow" in lowered:
        return date.today() + timedelta(days=1)
    if "today" in lowered:
        return date.today()

    match = _ISO_DATE.search(text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None

    match = _DMY_DATE.search(text)
    if match:
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            return None

    # Weekday names: the next occurrence ("friday" -> coming Friday).
    for index, name in enumerate(_WEEKDAYS):
        if name in lowered:
            days_ahead = (index - date.today().weekday()) % 7 or 7
            return date.today() + timedelta(days=days_ahead)

    return None


_TIME_PATTERN = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b")


def _parse_time(text: str) -> time | None:
    lowered = text.lower()

    def _to_time(match) -> time | None:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3)

        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0

        if not (0 <= hour < 24 and 0 <= minute < 60):
            return None

        return time(hour, minute)

    # Explicit times first ("10am", "10:00") — bare numbers are usually
    # appointment ids or date parts, not times.
    for match in _TIME_PATTERN.finditer(lowered):
        if match.group(2) or match.group(3):
            parsed = _to_time(match)
            if parsed:
                return parsed

    # A bare hour is only a time when introduced by "at" ("at 10").
    for match in _TIME_PATTERN.finditer(lowered):
        prefix = lowered[max(0, match.start() - 3) : match.start()]
        if prefix.strip().endswith("at"):
            parsed = _to_time(match)
            if parsed:
                return parsed

    return None


def _end_time(start: time) -> time:
    combined = datetime.combine(date.today(), start) + timedelta(
        minutes=APPOINTMENT_MINUTES
    )
    return combined.time()


# --------------------------------------------------------------------------
# Booking workflow state and nodes
# --------------------------------------------------------------------------

class BookingState(TypedDict):
    question: str
    doctor_id: int | None
    doctor_name: str
    specialization: str
    day: date | None
    start: time | None
    available: bool | None
    availability_message: str
    awaiting_confirmation: bool
    confirmation: str | None  # "yes" | "no" once the user replied
    answer: str


def parse_node(state: BookingState) -> dict:
    """Extract doctor / date / time from the question, or a yes/no reply
    to a pending confirmation. Values from earlier turns carry over."""
    question = state["question"]
    lowered = question.lower()

    if state["awaiting_confirmation"]:
        if any(word in lowered for word in CONFIRM_WORDS):
            return {"confirmation": "yes"}
        if any(word in lowered for word in DENY_WORDS):
            return {"confirmation": "no"}
        # Not a yes/no: treat as a new/updated request below.

    updates: dict = {"confirmation": None}

    with Session(engine) as session:
        doctors = get_doctors(session)
        doctor = _find_doctor(question, doctors)

    if doctor is not None:
        updates.update(
            doctor_id=doctor.id,
            doctor_name=doctor.name,
            specialization=doctor.specialization,
        )

    day = _parse_date(question)
    if day is not None:
        updates["day"] = day

    start = _parse_time(question)
    if start is not None:
        updates["start"] = start

    return updates


def check_availability_node(state: BookingState) -> dict:
    """Validate the requested slot against the doctor's schedule and
    existing appointments. Nothing is written to the database here."""
    day = state["day"]
    start = state["start"]
    end = _end_time(start)

    with Session(engine) as session:
        schedule = get_doctor_schedule(session, state["doctor_id"])
        on_day = [
            slot
            for slot in schedule
            if slot.day_of_week == day.weekday()
            and slot.start_time <= start
            and end <= slot.end_time
        ]

        if not on_day:
            days = ", ".join(
                ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][slot.day_of_week]
                for slot in schedule
            )
            return {
                "available": False,
                "availability_message": (
                    f"{state['doctor_name']} is not available on that day/time. "
                    f"Scheduled days: {days}."
                ),
                "awaiting_confirmation": False,
            }

        conflict = find_conflicting_appointment(
            session, state["doctor_id"], day, start, end
        )
        if conflict:
            return {
                "available": False,
                "availability_message": (
                    f"Sorry, {state['doctor_name']} already has an appointment at "
                    f"{conflict.start_time} on {day}."
                ),
                "awaiting_confirmation": False,
            }

    return {
        "available": True,
        "availability_message": "",
        "awaiting_confirmation": True,
    }


def ask_confirmation_node(state: BookingState) -> dict:
    """Availability passed: ask the user to confirm before booking."""
    end = _end_time(state["start"])
    return {
        "answer": (
            f"Please confirm: appointment with {state['doctor_name']} "
            f"({state['specialization']}) on {state['day']} at "
            f"{state['start']}-{end} for {DEFAULT_PATIENT_NAME}. "
            "Reply 'yes' to confirm or 'no' to cancel."
        )
    }


def book_node(state: BookingState) -> dict:
    """User confirmed: create the appointment now."""
    end = _end_time(state["start"])

    with Session(engine) as session:
        patient = _find_patient(session)
        if patient is None:
            return {
                "answer": (
                    f"No patient record found for {DEFAULT_PATIENT_NAME}. "
                    "Please run the seed script first."
                ),
                "awaiting_confirmation": False,
            }

        appointment = book_appointment(
            session,
            doctor_id=state["doctor_id"],
            patient_id=patient.id,
            appointment_date=state["day"],
            start_time=state["start"],
            end_time=end,
        )

    return {
        "answer": (
            f"Appointment booked with {state['doctor_name']} "
            f"({state['specialization']}) on {appointment.appointment_date} at "
            f"{appointment.start_time}-{appointment.end_time} "
            f"for {DEFAULT_PATIENT_NAME}."
        ),
        "awaiting_confirmation": False,
    }


def decline_node(state: BookingState) -> dict:
    """User declined the pending booking."""
    return {
        "answer": "Okay, the booking was cancelled.",
        "awaiting_confirmation": False,
        "confirmation": None,
    }


def unavailable_node(state: BookingState) -> dict:
    return {"answer": state["availability_message"]}


def ask_doctor_node(state: BookingState) -> dict:
    with Session(engine) as session:
        doctors = get_doctors(session)

    if not doctors:
        return {"answer": "No doctors are currently registered."}

    names = ", ".join(doctor.name for doctor in doctors)
    return {"answer": f"Which doctor would you like to book with? Available: {names}."}


def ask_slot_node(state: BookingState) -> dict:
    return {
        "answer": (
            f"You'd like to book with {state['doctor_name']} "
            f"({state['specialization']}). On which date and time? "
            "For example: '2026-09-10 at 10:00' or 'tomorrow at 2pm'."
        )
    }


def _route_after_parse(state: BookingState) -> str:
    if state.get("confirmation") == "yes":
        return "book"
    if state.get("confirmation") == "no":
        return "decline"

    if state.get("doctor_id") is None:
        return "ask_doctor"
    if state.get("day") is None or state.get("start") is None:
        return "ask_slot"

    return "check_availability"


def build_booking_graph():
    graph = StateGraph(BookingState)

    graph.add_node("parse", parse_node)
    graph.add_node("check_availability", check_availability_node)
    graph.add_node("ask_confirmation", ask_confirmation_node)
    graph.add_node("book", book_node)
    graph.add_node("decline", decline_node)
    graph.add_node("unavailable", unavailable_node)
    graph.add_node("ask_doctor", ask_doctor_node)
    graph.add_node("ask_slot", ask_slot_node)

    graph.add_edge(START, "parse")
    graph.add_conditional_edges(
        "parse",
        _route_after_parse,
        {
            "book": "book",
            "decline": "decline",
            "ask_doctor": "ask_doctor",
            "ask_slot": "ask_slot",
            "check_availability": "check_availability",
        },
    )
    graph.add_conditional_edges(
        "check_availability",
        lambda state: "ask_confirmation" if state["available"] else "unavailable",
        {"ask_confirmation": "ask_confirmation", "unavailable": "unavailable"},
    )
    for node in ("book", "decline", "unavailable", "ask_doctor", "ask_slot", "ask_confirmation"):
        graph.add_edge(node, END)

    return graph.compile()


def run_booking(question: str) -> str:
    """Run one turn of the booking workflow, carrying pending state over
    from the previous turn. Returns the answer text."""
    global _pending

    graph = build_booking_graph()

    initial: BookingState = {
        "question": question,
        "doctor_id": _pending.get("doctor_id"),
        "doctor_name": _pending.get("doctor_name", ""),
        "specialization": _pending.get("specialization", ""),
        "day": _pending.get("day"),
        "start": _pending.get("start"),
        "available": None,
        "availability_message": "",
        "awaiting_confirmation": _pending.get("awaiting_confirmation", False),
        "confirmation": None,
        "answer": "",
    }

    result = graph.invoke(initial)

    still_pending = result["awaiting_confirmation"]
    _pending = {
        "doctor_id": result["doctor_id"],
        "doctor_name": result["doctor_name"],
        "specialization": result["specialization"],
        "day": result["day"],
        "start": result["start"],
        "awaiting_confirmation": still_pending,
    } if still_pending else {}

    return result["answer"]


# --------------------------------------------------------------------------
# Appointment listing and cancel/reschedule
# --------------------------------------------------------------------------

def list_appointments() -> str:
    """Answer text listing the default patient's appointments."""
    with Session(engine) as session:
        lines = _appointment_lines(session)

    if lines is None:
        return (
            f"No patient record found for {DEFAULT_PATIENT_NAME}. "
            "Please run the seed script first."
        )

    if not lines:
        return f"{DEFAULT_PATIENT_NAME} has no appointments."

    return f"{DEFAULT_PATIENT_NAME}'s appointments:\n" + "\n".join(lines)


def _appointment_lines(session: Session) -> list[str] | None:
    """Formatted appointment list for the default patient (None if no patient)."""
    patient = _find_patient(session)
    if patient is None:
        return None

    appointments = get_patient_appointments(session, patient.id)
    if not appointments:
        return []

    doctors = {doctor.id: doctor.name for doctor in get_doctors(session)}

    return [
        f"- #{a.id}: {doctors.get(a.doctor_id, 'Unknown doctor')} on "
        f"{a.appointment_date} at {a.start_time}-{a.end_time} ({a.status})"
        for a in appointments
    ]


CANCEL_WORDS = ("cancel",)
RESCHEDULE_WORDS = ("reschedule", "postpone", "move")
_APPOINTMENT_ID = re.compile(r"#?(\d+)\b")


def handle_appointment_action(question: str) -> str | None:
    """Handle a cancel/reschedule request. Returns None when the question
    is not about canceling or rescheduling."""
    lowered = question.lower()

    wants_cancel = any(word in lowered for word in CANCEL_WORDS)
    wants_reschedule = any(word in lowered for word in RESCHEDULE_WORDS)

    if not (wants_cancel or wants_reschedule):
        return None

    with Session(engine) as session:
        patient = _find_patient(session)

        if patient is None:
            return (
                f"No patient record found for {DEFAULT_PATIENT_NAME}. "
                "Please run the seed script first."
            )

        appointments = get_patient_appointments(session, patient.id)

        if not appointments:
            return f"{DEFAULT_PATIENT_NAME} has no appointments to change."

        doctors = {doctor.id: doctor for doctor in get_doctors(session)}

        def _listing() -> str:
            return "\n".join(
                f"- #{a.id}: {doctors[a.doctor_id].name if a.doctor_id in doctors else 'Unknown doctor'} "
                f"on {a.appointment_date} at {a.start_time}-{a.end_time} ({a.status})"
                for a in appointments
            )

        match = _APPOINTMENT_ID.search(question)
        if match is None:
            return (
                "Which appointment? Please include its number, e.g. "
                "'cancel appointment 3'.\n" + _listing()
            )

        appointment_id = int(match.group(1))
        appointment = session.get(Appointment, appointment_id)

        if appointment is None or appointment.patient_id != patient.id:
            return (
                f"No appointment #{appointment_id} found for "
                f"{DEFAULT_PATIENT_NAME}.\n" + _listing()
            )

        doctor = doctors.get(appointment.doctor_id)

        if wants_cancel:
            cancelled = cancel_appointment(session, appointment_id)
            if cancelled is None:
                return f"Could not cancel appointment #{appointment_id}."

            return (
                f"Appointment #{cancelled.id} on {cancelled.appointment_date} "
                f"at {cancelled.start_time} has been cancelled."
            )

        # Reschedule: a new date/time must be in the same message.
        day = _parse_date(question)
        start = _parse_time(question)

        if day is None or start is None:
            return (
                "Please include the new date and time, e.g. "
                "'reschedule appointment 3 to 2026-09-12 at 10am'."
            )

        end = _end_time(start)

        if doctor is not None:
            schedule = get_doctor_schedule(session, doctor.id)
            on_day = [
                slot
                for slot in schedule
                if slot.day_of_week == day.weekday()
                and slot.start_time <= start
                and end <= slot.end_time
            ]

            if not on_day:
                days = ", ".join(
                    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][slot.day_of_week]
                    for slot in schedule
                )
                return (
                    f"{doctor.name} is not available on that day/time. "
                    f"Scheduled days: {days}."
                )

            conflict = find_conflicting_appointment(
                session, doctor.id, day, start, end
            )
            if conflict is not None and conflict.id != appointment_id:
                return (
                    f"Sorry, {doctor.name} already has an appointment at "
                    f"{conflict.start_time} on {day}."
                )

        moved = reschedule_appointment(session, appointment_id, day, start, end)
        if moved is None:
            return f"Could not reschedule appointment #{appointment_id}."

        doctor_name = doctor.name if doctor else "the doctor"
        return (
            f"Appointment #{moved.id} rescheduled with {doctor_name} to "
            f"{moved.appointment_date} at {moved.start_time}-{moved.end_time}."
        )
