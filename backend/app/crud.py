from datetime import date, datetime, time

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.schema import (
    Appointment,
    Conversation,
    Doctor,
    DoctorSchedule,
    Message,
    Patient,
    PendingBooking,
)


class SlotTakenError(Exception):
    """The requested slot is no longer free.

    Raised when the write-time conflict check — or the database's partial
    unique index, as a last resort — rejects a booking that another
    transaction won. Carries the conflicting appointment's id and start time
    (both ``None`` when only the index caught it) so callers can explain
    what happened without re-querying.
    """

    def __init__(self, conflict: Appointment | None = None) -> None:
        self.conflict_id = conflict.id if conflict is not None else None
        self.conflict_start = (
            conflict.start_time if conflict is not None else None
        )
        super().__init__("That slot was just booked by someone else.")


def _lock_doctor(session: Session, doctor_id: int) -> None:
    """Serialize appointment writes for one doctor.

    The availability check and the insert must be one atomic step: without
    this, two requests can both see a free slot, both pass the check, and
    both try to take it. A row lock on the doctor is the simplest portable
    guard — every writer for that doctor queues here, then re-checks
    conflicts while holding the lock.

    SQLite ignores ``FOR UPDATE`` (and serializes writers itself), so the
    unit suite still runs unchanged; Postgres takes a real row lock.
    """
    session.exec(
        select(Doctor.id).where(Doctor.id == doctor_id).with_for_update()
    ).first()


def get_doctors(session: Session) -> list[Doctor]:
    return list(session.exec(select(Doctor)).all())


def get_patients(session: Session) -> list[Patient]:
    return list(session.exec(select(Patient)).all())


def get_doctor_by_id(session: Session, doctor_id: int) -> Doctor | None:
    return session.get(Doctor, doctor_id)


def get_doctor_by_user_id(session: Session, user_id: int) -> Doctor | None:
    """The Doctor record linked to a login, if any.

    Mirrors get_patient_by_user_id: a doctor reaches only their own row,
    and a doctor account with no linked Doctor row reaches nothing.
    """
    return session.exec(
        select(Doctor).where(Doctor.user_id == user_id)
    ).first()


def get_patient_by_user_id(session: Session, user_id: int) -> Patient | None:
    """The Patient record linked to a login, if any.

    This is the ownership rule for appointment data: a patient is only
    ever their own Patient row, never another user's.
    """
    return session.exec(
        select(Patient).where(Patient.user_id == user_id)
    ).first()


def get_appointment_by_id(
    session: Session, appointment_id: int
) -> Appointment | None:
    return session.get(Appointment, appointment_id)


def get_doctor_schedule(session: Session, doctor_id: int) -> list[DoctorSchedule]:
    return list(
        session.exec(
            select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id)
        ).all()
    )


def replace_doctor_schedule(
    session: Session,
    doctor_id: int,
    slots: list[tuple[int, time, time]],
) -> None:
    """Replace a doctor's weekly schedule wholesale.

    Replace rather than merge: the caller sends the complete week, so a
    slot absent from the payload is a slot the doctor no longer works.
    Validation of the slots themselves is the caller's job.
    """
    existing = session.exec(
        select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id)
    ).all()

    for slot in existing:
        session.delete(slot)

    for day_of_week, start_time, end_time in slots:
        session.add(
            DoctorSchedule(
                doctor_id=doctor_id,
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
            )
        )

    session.commit()


def book_appointment(
    session: Session,
    doctor_id: int,
    patient_id: int,
    appointment_date: date,
    start_time: time,
    end_time: time,
) -> Appointment:
    """Create a booking atomically.

    The conflict check runs *inside* the doctor lock, so two callers cannot
    both pass it. Raises ``SlotTakenError`` — never a raw IntegrityError —
    when the slot was taken between the caller's earlier check and this
    write, so the API can answer 409 and the agent can suggest alternatives.

    Rolling back on the conflict is deliberate: it releases the lock before
    the caller builds its response. Callers must not hold other pending
    writes on this session when they book.
    """
    _lock_doctor(session, doctor_id)

    conflict = find_conflicting_appointment(
        session, doctor_id, appointment_date, start_time, end_time
    )
    if conflict is not None:
        session.rollback()
        raise SlotTakenError(conflict)

    appointment = Appointment(
        doctor_id=doctor_id,
        patient_id=patient_id,
        appointment_date=appointment_date,
        start_time=start_time,
        end_time=end_time,
        status="booked",
        created_at=datetime.now(),
    )
    session.add(appointment)

    try:
        session.commit()
    except IntegrityError as exc:
        # Safety net for a writer that bypassed the lock (or a conflict the
        # overlap check could not see): the partial unique index still
        # refuses the duplicate.
        session.rollback()
        raise SlotTakenError() from exc

    session.refresh(appointment)
    return appointment


def cancel_appointment(session: Session, appointment_id: int) -> Appointment | None:
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        return None

    appointment.status = "cancelled"
    session.add(appointment)
    session.commit()
    session.refresh(appointment)
    return appointment


def reschedule_appointment(
    session: Session,
    appointment_id: int,
    appointment_date: date,
    start_time: time,
    end_time: time,
) -> Appointment | None:
    """Move an appointment, re-checking the slot under the doctor lock.

    Excludes the appointment itself from the conflict check, so moving it to
    a slot it already occupies is not a conflict. Raises ``SlotTakenError``
    when another booking won the target slot.
    """
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        return None

    _lock_doctor(session, appointment.doctor_id)

    conflict = find_conflicting_appointment(
        session,
        appointment.doctor_id,
        appointment_date,
        start_time,
        end_time,
        exclude_appointment_id=appointment_id,
    )
    if conflict is not None:
        session.rollback()
        raise SlotTakenError(conflict)

    appointment.appointment_date = appointment_date
    appointment.start_time = start_time
    appointment.end_time = end_time
    session.add(appointment)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SlotTakenError() from exc

    session.refresh(appointment)
    return appointment


def get_patient_appointments(session: Session, patient_id: int) -> list[Appointment]:
    return list(
        session.exec(
            select(Appointment).where(Appointment.patient_id == patient_id)
        ).all()
    )


def get_doctor_appointments(session: Session, doctor_id: int) -> list[Appointment]:
    """Appointments booked with one doctor (the doctor's own view)."""
    return list(
        session.exec(
            select(Appointment).where(Appointment.doctor_id == doctor_id)
        ).all()
    )


def get_all_appointments(session: Session) -> list[Appointment]:
    """Every appointment. Admin-only callers; never exposed to patients."""
    return list(session.exec(select(Appointment)).all())


def update_appointment(
    session: Session, appointment_id: int, **changes
) -> Appointment | None:
    """Apply field changes to an appointment. Callers must have already
    checked that the caller is allowed to change it.

    Moving a booked appointment (or re-activating a cancelled one) takes the
    same doctor lock and conflict check as booking, so an admin edit cannot
    race a patient into the same slot. Raises ``SlotTakenError`` on conflict.
    """
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        return None

    result_status = changes.get("status", appointment.status)
    scheduling_changed = any(
        field in changes
        for field in ("appointment_date", "start_time", "end_time")
    )

    if result_status == "booked" and (
        scheduling_changed or changes.get("status") == "booked"
    ):
        _lock_doctor(session, appointment.doctor_id)
        conflict = find_conflicting_appointment(
            session,
            appointment.doctor_id,
            changes.get("appointment_date", appointment.appointment_date),
            changes.get("start_time", appointment.start_time),
            changes.get("end_time", appointment.end_time),
            exclude_appointment_id=appointment_id,
        )
        if conflict is not None:
            session.rollback()
            raise SlotTakenError(conflict)

    for field, value in changes.items():
        setattr(appointment, field, value)

    session.add(appointment)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SlotTakenError() from exc

    session.refresh(appointment)
    return appointment


def delete_appointment(session: Session, appointment_id: int) -> bool:
    """Remove an appointment row. False when it does not exist."""
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        return False

    session.delete(appointment)
    session.commit()
    return True


def find_conflicting_appointment(
    session: Session,
    doctor_id: int,
    appointment_date: date,
    start_time: time,
    end_time: time,
    exclude_appointment_id: int | None = None,
) -> Appointment | None:
    """The first booked appointment that overlaps ``[start_time, end_time)``.

    Overlap, not just equality: the REST API accepts arbitrary start/end
    pairs, so 10:00-10:30 and 10:15-10:45 are the same slot in practice.
    ``exclude_appointment_id`` lets a reschedule ignore the row it is moving.
    """
    appointments = session.exec(
        select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.status == "booked",
        )
    ).all()

    for appointment in appointments:
        if appointment.id == exclude_appointment_id:
            continue
        if start_time < appointment.end_time and appointment.start_time < end_time:
            return appointment

    return None


# --------------------------------------------------------------------------
# Conversations and messages
# --------------------------------------------------------------------------

# A single stored turn is capped so a pathological answer cannot bloat Neon
# or the prompt. Very long doctor/appointment listings will be cut.
MAX_MESSAGE_CHARS = 8000
TITLE_MAX_CHARS = 200
HISTORY_LIMIT = 10  # messages, i.e. 5 turns


def create_conversation(
    session: Session, user_id: int, title: str | None = None
) -> Conversation:
    """Open a conversation owned by `user_id`."""
    now = datetime.now()
    conversation = Conversation(
        user_id=user_id,
        title=title[:TITLE_MAX_CHARS] if title else None,
        created_at=now,
        updated_at=now,
    )
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def get_conversation_for_user(
    session: Session, conversation_id: int, user_id: int
) -> Conversation | None:
    """Ownership-checked lookup: filters on id AND owner together.

    This is what makes "a user reads only their own conversations" true —
    another user's id resolves to None rather than to their data. Never
    replace this with a bare session.get(Conversation, id) on a request path.
    """
    return session.exec(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    ).first()


def append_message(
    session: Session, conversation_id: int, role: str, content: str
) -> Message:
    """Append a turn. `role` is "user" or "assistant".

    Callers must have already established that the conversation belongs to
    the requesting user.
    """
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content[:MAX_MESSAGE_CHARS],
        created_at=datetime.now(),
    )
    session.add(message)

    # Keep "recent chats" ordering honest: the conversation moves to the top
    # when it gains a turn.
    conversation = session.get(Conversation, conversation_id)
    if conversation is not None:
        conversation.updated_at = datetime.now()
        session.add(conversation)

    session.commit()
    session.refresh(message)
    return message


def get_recent_messages(
    session: Session, conversation_id: int, limit: int = HISTORY_LIMIT
) -> list[Message]:
    """The most recent messages, oldest first.

    Ordered by id rather than created_at: ids are monotonic within a
    conversation, while two turns can share a timestamp.
    """
    recent = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()

    return list(reversed(recent))


# --------------------------------------------------------------------------
# Pending booking state
# --------------------------------------------------------------------------


def get_pending_booking(
    session: Session, conversation_id: int
) -> PendingBooking | None:
    """The pending booking for a conversation, if one is awaiting a reply."""
    return session.exec(
        select(PendingBooking).where(
            PendingBooking.conversation_id == conversation_id
        )
    ).first()


def save_pending_booking(
    session: Session,
    conversation_id: int,
    doctor_id: int | None,
    doctor_name: str,
    specialization: str,
    day: date | None,
    start: time | None,
    awaiting_confirmation: bool = False,
) -> PendingBooking:
    """Upsert the conversation's pending booking.

    One row per conversation (unique conversation_id), so this updates in
    place rather than accumulating rows across turns.
    """
    pending = get_pending_booking(session, conversation_id)

    if pending is None:
        pending = PendingBooking(conversation_id=conversation_id)
        session.add(pending)

    pending.doctor_id = doctor_id
    pending.doctor_name = doctor_name
    pending.specialization = specialization
    pending.day = day
    pending.start = start
    pending.awaiting_confirmation = awaiting_confirmation
    pending.updated_at = datetime.now()

    session.add(pending)
    session.commit()
    session.refresh(pending)
    return pending


def clear_pending_booking(session: Session, conversation_id: int) -> None:
    """Forget the conversation's pending booking. Safe when none exists."""
    pending = get_pending_booking(session, conversation_id)
    if pending is not None:
        session.delete(pending)
        session.commit()
