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
