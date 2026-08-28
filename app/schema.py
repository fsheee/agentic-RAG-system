from datetime import date, time

from sqlmodel import Field, SQLModel


class Doctor(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    specialization: str


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


class Appointment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)

    doctor_id: int = Field(foreign_key="doctor.id")
    patient_id: int = Field(foreign_key="patient.id")

    appointment_date: date
    start_time: time
    end_time: time

    status: str = "booked"
