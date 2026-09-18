"""Seed the database with sample doctors, schedules, a patient, and the
initial admin user (controlled setup).

Run: uv run python -m app.seed
"""

import os
from datetime import time

from sqlalchemy import text
from sqlmodel import Session, select

from app.auth import hash_password
from app.db import create_tables, get_engine
from app.schema import Doctor, DoctorSchedule, Patient, Role, User

DOCTORS = [
    ("Dr. Sarah Ahmed", "Cardiology", 3000),
    ("Dr. Bilal Raza", "Dermatology", 2500),
    ("Dr. Ayesha Siddiqui", "Pediatrics", 2000),
    ("Dr. Usman Tariq", "Orthopedics", 3500),
    ("Dr. Fatima Noor", "General Medicine", 1500),
]

# day_of_week: 0 = Monday ... 6 = Sunday
SCHEDULES = {
    "Dr. Sarah Ahmed": [(0, 9, 13), (2, 14, 18), (4, 9, 13)],
    "Dr. Bilal Raza": [(1, 10, 16), (3, 10, 16)],
    "Dr. Ayesha Siddiqui": [(0, 8, 14), (1, 8, 14), (2, 8, 14), (3, 8, 14), (4, 8, 12)],
    "Dr. Usman Tariq": [(2, 9, 17), (4, 9, 17), (5, 10, 14)],
    "Dr. Fatima Noor": [(0, 9, 17), (1, 9, 17), (2, 9, 17), (3, 9, 17), (4, 9, 17)],
}

PATIENTS = [
    ("Ali Khan", "03001234567"),
]


def _add_missing_columns():
    """create_tables() only creates missing tables; it does not alter
    existing ones, so new columns need an explicit migration."""
    with Session(get_engine()) as session:
        session.execute(
            text("ALTER TABLE doctor ADD COLUMN IF NOT EXISTS consultation_fee INTEGER")
        )
        session.execute(
            text("ALTER TABLE appointment ADD COLUMN IF NOT EXISTS created_at TIMESTAMP")
        )
        session.execute(
            text("ALTER TABLE patient ADD COLUMN IF NOT EXISTS user_id INTEGER")
        )
        session.commit()


def _seed_admin():
    """Create the initial admin from ADMIN_EMAIL/ADMIN_PASSWORD.

    Admins are never created via the API; this is the controlled setup.
    Idempotent: an existing admin with the same email is left untouched.
    """
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_email or not admin_password:
        print("ADMIN_EMAIL/ADMIN_PASSWORD not set; skipping admin seed.")
        return

    with Session(get_engine()) as session:
        existing = session.exec(
            select(User).where(User.email == admin_email)
        ).first()
        if existing:
            print(f"Admin already exists ({admin_email}); skipped.")
            return

        session.add(
            User(
                name="Admin",
                email=admin_email,
                password_hash=hash_password(admin_password),
                role=Role.admin,
                is_active=True,
            )
        )
        session.commit()
        print(f"Seeded admin user {admin_email}.")


def seed():
    create_tables()
    _add_missing_columns()
    _seed_admin()

    with Session(get_engine()) as session:
        # Idempotent: skip anything already present.
        existing_doctors = {
            doctor.name: doctor for doctor in session.exec(select(Doctor)).all()
        }
        existing_patients = {
            patient.name for patient in session.exec(select(Patient)).all()
        }

        seeded_doctors = 0
        seeded_schedules = 0

        for name, specialization, fee in DOCTORS:
            if name in existing_doctors:
                # Backfill the fee on doctors seeded before it existed.
                if existing_doctors[name].consultation_fee is None:
                    existing_doctors[name].consultation_fee = fee
                    session.add(existing_doctors[name])
                continue

            doctor = Doctor(
                name=name,
                specialization=specialization,
                consultation_fee=fee,
            )
            session.add(doctor)
            session.flush()  # assign doctor.id before building schedules

            for day_of_week, start_hour, end_hour in SCHEDULES[name]:
                session.add(
                    DoctorSchedule(
                        doctor_id=doctor.id,
                        day_of_week=day_of_week,
                        start_time=time(start_hour),
                        end_time=time(end_hour),
                    )
                )
                seeded_schedules += 1

            seeded_doctors += 1

        seeded_patients = 0
        for name, phone in PATIENTS:
            if name in existing_patients:
                continue

            session.add(Patient(name=name, phone=phone))
            seeded_patients += 1

        session.commit()
        print(
            f"Seeded {seeded_doctors} doctors, {seeded_schedules} schedules, "
            f"{seeded_patients} patient(s). Skipped existing records."
        )


if __name__ == "__main__":
    seed()
