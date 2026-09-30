"""Appointment booking tool.

Booking is a multi-step LangGraph workflow with explicit state instead of
one immediate call:

    parse -> check availability -> ask confirmation -> book

An appointment is only created after the user explicitly confirms.

Pending booking state lives in Neon, keyed by the conversation it belongs
to (see crud.get_pending_booking), so a half-finished booking is scoped to
one conversation, survives a restart, and is shared across workers.
"""

import re
from datetime import date, datetime, time, timedelta
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlmodel import Session, select

from app.crud import (
    book_appointment,
    cancel_appointment,
    clear_pending_booking,
    find_conflicting_appointment,
    get_doctor_schedule,
    get_doctors,
    get_patient_appointments,
    get_patient_by_user_id,
    get_pending_booking,
    reschedule_appointment,
    save_pending_booking,
)
from app.db import get_engine
from app.schema import Appointment, Patient, User

DEFAULT_PATIENT_NAME = "Ali Khan"
APPOINTMENT_MINUTES = 30

CONFIRM_WORDS = ("yes", "confirm", "sure", "ok", "book it")
DENY_WORDS = ("no", "cancel", "don't", "do not", "stop")


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def is_awaiting_confirmation(conversation_id: int | None = None) -> bool:
    """True while this conversation has a booking waiting on a yes/no reply.

    A half-built booking (doctor known, slot still missing) is stored too,
    but is NOT awaiting confirmation — the next question may be unrelated,
    and only a completed request should bypass the router.

    Pending state lives in Neon keyed by conversation (see
    crud.get_pending_booking), so it survives a restart and is shared by
    every worker.

    Without a conversation there is nothing to key on, so this is False —
    deliberately, rather than falling back to a shared default slot.
    """
    if conversation_id is None:
        return False

    with Session(get_engine()) as session:
        pending = get_pending_booking(session, conversation_id)
        return pending is not None and pending.awaiting_confirmation


def _find_patient(session: Session, user: User | None = None) -> Patient | None:
    """The patient record for the requesting user.

    With a user: only their own linked Patient row (never another user's).
    Without (legacy/direct use): the seeded demo patient.
    """
    if user is not None:
        return get_patient_by_user_id(session, user.id)
    return session.exec(
        select(Patient).where(Patient.name == DEFAULT_PATIENT_NAME)
    ).first()


def _find_doctor(question: str, doctors):
    """Match a doctor by name in the question ('dr. ayesha', full name...),
    including shortened or slightly misspelled names ('sara' -> 'sarah')."""
    text = question.lower().replace("dr.", " ").replace("dr", " ")
    # Words long enough to be a real name fragment; short ones ("4pm")
    # would prefix-match too eagerly.
    words = [word for word in text.split() if len(word) >= 4]

    for doctor in doctors:
        name = doctor.name.lower()
        if name in text:
            return doctor

        # Match on any single distinctive name token ("dr. ayesha",
        # "siddiqui") when the full name is not spelled out — or on a
        # typed word sharing a prefix with a token ("sara" -> "sarah").
        tokens = [
            token
            for token in name.replace("dr.", "").split()
            if len(token) > 3
        ]
        if tokens and any(
            token in text
            or any(word.startswith(token) or token.startswith(word) for word in words)
            for token in tokens
        ):
            return doctor

    return None


_ISO_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_DMY_DATE = re.compile(r"\b(\d{1,2})[/](\d{1,2})[/](\d{4})\b")

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# Month names, including the common 3-4 letter abbreviations, so a natural
# "28th Sept 2026" parses as readily as "2026-09-28".
_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Longest first so "sept" is not swallowed by "sep".
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

# "28th Sept 2026" / "28 September 2026" / "28 sept"
_DAY_MONTH_YEAR = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})\.?\s*,?\s*(\d{{4}})?\b",
    re.IGNORECASE,
)

# "Sept 28 2026" / "September 28, 2026" / "sept 28"
_MONTH_DAY_YEAR = re.compile(
    rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(\d{{4}})?\b",
    re.IGNORECASE,
)


def _month_name_date(text: str) -> date | None:
    """A date written with a month name, in either order.

    The year is optional and defaults to the current one.
    """
    for pattern, day_group, month_group, year_group in (
        (_DAY_MONTH_YEAR, 1, 2, 3),
        (_MONTH_DAY_YEAR, 2, 1, 3),
    ):
        match = pattern.search(text)
        if match is None:
            continue

        try:
            return date(
                int(match.group(year_group) or date.today().year),
                _MONTHS[match.group(month_group).lower().rstrip(".")],
                int(match.group(day_group)),
            )
        except ValueError:
            # e.g. "31 February" — a real-looking but impossible date.
            return None

    return None


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

    # Month names: "28th Sept 2026", "September 28, 2026".
    month_date = _month_name_date(text)
    if month_date is not None:
        return month_date

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


def end_time_for(start: time) -> time:
    """End of an appointment slot starting at `start`."""
    combined = datetime.combine(date.today(), start) + timedelta(
        minutes=APPOINTMENT_MINUTES
    )
    return combined.time()


_DAY_NAMES_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def check_slot(
    session: Session,
    doctor_id: int,
    doctor_name: str,
    day: date,
    start: time,
    end: time,
    exclude_appointment_id: int | None = None,
) -> tuple[bool, str]:
    """Validate a slot against the doctor's weekly schedule and existing
    appointments. Returns (available, message); nothing is written.

    `exclude_appointment_id` lets a reschedule ignore the appointment
    being moved, which would otherwise conflict with itself.

    The single implementation of this rule: the booking workflow, the
    reschedule path, and the REST booking endpoint all call it, so they
    cannot drift apart.
    """
    schedule = get_doctor_schedule(session, doctor_id)
    on_day = [
        slot
        for slot in schedule
        if slot.day_of_week == day.weekday()
        and slot.start_time <= start
        and end <= slot.end_time
    ]

    if not on_day:
        days = ", ".join(_DAY_NAMES_SHORT[slot.day_of_week] for slot in schedule)
        return False, (
            f"{doctor_name} is not available on that day/time. "
            f"Scheduled days: {days}."
        )

    conflict = find_conflicting_appointment(session, doctor_id, day, start, end)
    if conflict is not None and conflict.id != exclude_appointment_id:
        return False, (
            f"Sorry, {doctor_name} already has an appointment at "
            f"{conflict.start_time} on {day}."
        )

    return True, ""


# --------------------------------------------------------------------------
# Booking workflow state and nodes
# --------------------------------------------------------------------------

class BookingState(TypedDict):
    question: str
    user: User | None
    # Prior turns as [{"role", "content"}] dicts, used only when the
    # current message names no doctor — see parse_node. None/empty for
    # stateless callers (CLI, tests without history).
    history: list[dict] | None
    doctor_id: int | None
    doctor_name: str
    specialization: str
    day: date | None
    start: time | None
    available: bool | None
    availability_message: str
    awaiting_confirmation: bool
    confirmation: str | None  # "yes" | "no" once the user replied
    # True once the turn reached a terminal outcome (booked, declined or
    # unavailable). False means the workflow is still collecting details,
    # so whatever was parsed must be carried to the next turn.
    resolved: bool
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

    with Session(get_engine()) as session:
        doctors = get_doctors(session)
        doctor = _find_doctor(question, doctors)

        # No doctor in this message and none pending: fall back to the
        # most recent user message that named one, so "confirm my
        # appointment friday 11am" continues the doctor discussed in the
        # previous turn instead of asking again. Only user messages are
        # scanned — assistant replies list every doctor and would match
        # arbitrarily.
        if doctor is None and state.get("doctor_id") is None:
            for message in reversed(state.get("history") or []):
                if message.get("role") != "user":
                    continue
                doctor = _find_doctor(str(message.get("content") or ""), doctors)
                if doctor is not None:
                    break

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
    end = end_time_for(start)

    with Session(get_engine()) as session:
        available, message = check_slot(
            session,
            state["doctor_id"],
            state["doctor_name"],
            day,
            start,
            end,
        )

    if not available:
        return {
            "available": False,
            "availability_message": message,
            "awaiting_confirmation": False,
        }

    return {
        "available": True,
        "availability_message": "",
        "awaiting_confirmation": True,
    }


def ask_confirmation_node(state: BookingState) -> dict:
    """Availability passed: ask the user to confirm before booking."""
    end = end_time_for(state["start"])
    who = _patient_display_name(state["user"])
    return {
        "answer": (
            f"Please confirm: appointment with {state['doctor_name']} "
            f"({state['specialization']}) on {state['day']} at "
            f"{state['start']}-{end} for {who}. "
            "Reply 'yes' to confirm or 'no' to cancel."
        )
    }


def _patient_display_name(user: User | None) -> str:
    if user is None:
        return DEFAULT_PATIENT_NAME
    with Session(get_engine()) as session:
        patient = _find_patient(session, user)
    if patient is not None:
        return patient.name
    return user.name


def book_node(state: BookingState) -> dict:
    """User confirmed: create the appointment now."""
    end = end_time_for(state["start"])

    with Session(get_engine()) as session:
        patient = _find_patient(session, state["user"])
        if patient is None:
            who = state["user"].name if state["user"] else DEFAULT_PATIENT_NAME
            return {
                "answer": (
                    f"No patient record is linked to your account, {who}. "
                    "Please register as a patient first."
                ),
                "awaiting_confirmation": False,
            }

        # Re-check at booking time: the availability check ran an earlier
        # turn ago, and the same slot may have been taken (or booked twice)
        # since then.
        conflict = find_conflicting_appointment(
            session, state["doctor_id"], state["day"], state["start"], end
        )
        if conflict is not None:
            return {
                "answer": (
                    f"Sorry, {state['doctor_name']} already has an appointment "
                    f"at {conflict.start_time} on {state['day']}. "
                    "Please pick another time."
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
        message = (
            f"Appointment booked with {state['doctor_name']} "
            f"({state['specialization']}) on {appointment.appointment_date} at "
            f"{appointment.start_time}-{appointment.end_time} "
            f"for {patient.name}."
        )

    return {
        "answer": message,
        "awaiting_confirmation": False,
        "resolved": True,
    }


def decline_node(state: BookingState) -> dict:
    """User declined the pending booking."""
    return {
        "answer": "Okay, the booking was cancelled.",
        "awaiting_confirmation": False,
        "confirmation": None,
        "resolved": True,
    }


def unavailable_node(state: BookingState) -> dict:
    """The requested slot is not bookable; nothing is left in progress."""
    return {"answer": state["availability_message"], "resolved": True}


def ask_doctor_node(state: BookingState) -> dict:
    with Session(get_engine()) as session:
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
        # Only book when the slot is complete; a stale/partial pending
        # state must not crash the booking.
        if (
            state.get("doctor_id") is not None
            and state.get("day") is not None
            and state.get("start") is not None
        ):
            return "book"
        return "ask_slot"
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


def _load_pending(conversation_id: int | None) -> dict:
    """Pending booking state for this conversation, or {} when there is none."""
    if conversation_id is None:
        return {}

    with Session(get_engine()) as session:
        pending = get_pending_booking(session, conversation_id)
        if pending is None:
            return {}

        return {
            "doctor_id": pending.doctor_id,
            "doctor_name": pending.doctor_name,
            "specialization": pending.specialization,
            "day": pending.day,
            "start": pending.start,
            "awaiting_confirmation": pending.awaiting_confirmation,
        }


def _save_pending(conversation_id: int | None, result: BookingState) -> None:
    """Persist whatever the turn established.

    Anything learned is kept — a doctor chosen in one turn and a time given
    in the next both survive — because dropping partial progress forces the
    user to repeat themselves. Only a terminal outcome (booked, declined,
    unavailable) clears the row.
    """
    if conversation_id is None:
        return

    learned_nothing = (
        result["doctor_id"] is None
        and result["day"] is None
        and result["start"] is None
    )

    with Session(get_engine()) as session:
        if result["resolved"] or learned_nothing:
            clear_pending_booking(session, conversation_id)
            return

        save_pending_booking(
            session,
            conversation_id,
            doctor_id=result["doctor_id"],
            doctor_name=result["doctor_name"],
            specialization=result["specialization"],
            day=result["day"],
            start=result["start"],
            awaiting_confirmation=result["awaiting_confirmation"],
        )


def run_booking(
    question: str,
    user: User | None = None,
    conversation_id: int | None = None,
    history: list[dict] | None = None,
) -> str:
    """Run one turn of the booking workflow. Returns the answer.

    `conversation_id` keys the pending state, which is loaded from and
    saved to Neon so a half-finished booking survives a restart and is
    shared across workers.

    `history` is prior turns (same shape the API loads for `/ask`). It is
    consulted only when the current message names no doctor and none is
    pending, so the booking can continue the doctor discussed earlier in
    the conversation.

    With no conversation_id there is nowhere to keep multi-turn state, so
    the turn runs stateless: it will not carry a confirmation over to the
    next call. The API always supplies one for an authenticated caller.
    """
    pending = _load_pending(conversation_id)

    graph = build_booking_graph()

    initial: BookingState = {
        "question": question,
        "user": user,
        "history": history,
        "doctor_id": pending.get("doctor_id"),
        "doctor_name": pending.get("doctor_name", ""),
        "specialization": pending.get("specialization", ""),
        "day": pending.get("day"),
        "start": pending.get("start"),
        "available": None,
        "availability_message": "",
        "awaiting_confirmation": pending.get("awaiting_confirmation", False),
        "confirmation": None,
        "resolved": False,
        "answer": "",
    }

    result = graph.invoke(initial)

    _save_pending(conversation_id, result)

    return result["answer"]


# --------------------------------------------------------------------------
# Appointment listing and cancel/reschedule
# --------------------------------------------------------------------------

def list_appointments(user: User | None = None) -> str:
    """Answer text listing the requesting user's appointments."""
    with Session(get_engine()) as session:
        lines = _appointment_lines(session, user)

    if lines is None:
        if user is not None:
            return "No patient record is linked to your account."
        return (
            f"No patient record found for {DEFAULT_PATIENT_NAME}. "
            "Please run the seed script first."
        )

    who = _patient_display_name(user) if user else DEFAULT_PATIENT_NAME

    if not lines:
        return f"{who} has no appointments."

    return f"{who}'s appointments:\n" + "\n".join(lines)


def _appointment_lines(session: Session, user: User | None = None) -> list[str] | None:
    """Formatted appointment list for the requesting user (None if no patient)."""
    patient = _find_patient(session, user)
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


def handle_appointment_action(question: str, user: User | None = None) -> str | None:
    """Handle a cancel/reschedule request. Returns None when the question
    is not about canceling or rescheduling."""
    lowered = question.lower()

    wants_cancel = any(word in lowered for word in CANCEL_WORDS)
    wants_reschedule = any(word in lowered for word in RESCHEDULE_WORDS)

    if not (wants_cancel or wants_reschedule):
        return None

    with Session(get_engine()) as session:
        patient = _find_patient(session, user)

        if patient is None:
            if user is not None:
                return "No patient record is linked to your account."
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

        end = end_time_for(start)

        if doctor is not None:
            # Same rule as booking; exclude this appointment so it does
            # not conflict with itself.
            available, message = check_slot(
                session,
                doctor.id,
                doctor.name,
                day,
                start,
                end,
                exclude_appointment_id=appointment_id,
            )
            if not available:
                return message

        moved = reschedule_appointment(session, appointment_id, day, start, end)
        if moved is None:
            return f"Could not reschedule appointment #{appointment_id}."

        doctor_name = doctor.name if doctor else "the doctor"
        return (
            f"Appointment #{moved.id} rescheduled with {doctor_name} to "
            f"{moved.appointment_date} at {moved.start_time}-{moved.end_time}."
        )
