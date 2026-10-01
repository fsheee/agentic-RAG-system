from datetime import date, datetime, time
from enum import Enum

from sqlmodel import Field, SQLModel


class Role(str, Enum):
    admin = "admin"
    hr = "hr"
    employee = "employee"
    doctor = "doctor"
    patient = "patient"


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    role: Role = Field(default=Role.patient)
    is_active: bool = Field(default=True)


class Doctor(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    specialization: str
    consultation_fee: int | None = Field(default=None)  # PKR; null = not set
    # Links a Doctor record to its login, mirroring Patient.user_id.
    # Nullable: seeded doctors have no account until an admin creates one.
    user_id: int | None = Field(default=None, foreign_key="user.id", unique=True)


class DoctorSchedule(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    doctor_id: int = Field(foreign_key="doctor.id")

    day_of_week: int
    start_time: time
    end_time: time


class Patient(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    phone: str
    # Links a Patient record to its login (nullable: seeded/demo patients
    # and records created before auth may have none).
    user_id: int | None = Field(default=None, foreign_key="user.id", unique=True)


class Appointment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    doctor_id: int = Field(foreign_key="doctor.id")
    patient_id: int = Field(foreign_key="patient.id")

    appointment_date: date
    start_time: time
    end_time: time

    status: str = "booked"
    created_at: datetime | None = Field(default=None)  # when the booking was made


class Conversation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    # Ownership is mandatory, unlike Patient.user_id: conversations are only
    # ever created for an authenticated caller, so every read can filter on
    # both id and owner and a conversation is never orphaned.
    user_id: int = Field(foreign_key="user.id", index=True)

    title: str | None = Field(default=None)  # first question, truncated
    created_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)  # orders recent chats


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    conversation_id: int = Field(foreign_key="conversation.id", index=True)

    role: str  # "user" | "assistant"
    content: str
    created_at: datetime | None = Field(default=None)


class PendingBooking(SQLModel, table=True):
    """A booking awaiting the user's yes/no, one row per conversation.

    Existence of the row *is* the "awaiting confirmation" flag: the row is
    written when availability passes and deleted when the turn resolves
    (booked, declined, or unavailable), so counting rows can never drift
    from the state it represents.

    Keyed by conversation so a half-finished booking is scoped to the
    person who started it, survives a restart, and is visible to every
    worker — none of which a process-local dictionary could offer.
    """

    id: int | None = Field(default=None, primary_key=True)

    conversation_id: int = Field(
        foreign_key="conversation.id", unique=True, index=True
    )

    # Deliberately NOT a foreign key: this is transient working state, not
    # a relational record. A doctor removed mid-conversation must not block
    # the row from being written or cleaned up.
    doctor_id: int | None = Field(default=None)

    doctor_name: str = ""
    specialization: str = ""

    # Nullable so a partially-built request cannot fail to persist; the
    # booking workflow's own routing still guards against acting on one.
    day: date | None = Field(default=None)
    start: time | None = Field(default=None)

    # True only when the row is a finished request waiting on yes/no. A
    # half-built booking (doctor known, slot missing, or vice versa) is
    # stored with this False, so it can be resumed without the router
    # treating an unrelated next question as the answer to a confirmation.
    awaiting_confirmation: bool = Field(default=False)

    updated_at: datetime | None = Field(default=None)
