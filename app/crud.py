from datetime import date, datetime, time

from sqlmodel import Session, select

from app.schema import Appointment, Doctor, DoctorSchedule


def get_doctors(session: Session) -> list[Doctor]:
    return list(session.exec(select(Doctor)).all())


def get_doctor_by_id(session: Session, doctor_id: int) -> Doctor | None:
    return session.get(Doctor, doctor_id)


def get_doctor_schedule(session: Session, doctor_id: int) -> list[DoctorSchedule]:
    return list(
        session.exec(
            select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id)
        ).all()
    )


def book_appointment(
    session: Session,
    doctor_id: int,
    patient_id: int,
    appointment_date: date,
    start_time: time,
    end_time: time,
) -> Appointment:
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
    session.commit()
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
    appointment = session.get(Appointment, appointment_id)
    if appointment is None:
        return None

    appointment.appointment_date = appointment_date
    appointment.start_time = start_time
    appointment.end_time = end_time
    session.add(appointment)
    session.commit()
    session.refresh(appointment)
    return appointment


def get_patient_appointments(session: Session, patient_id: int) -> list[Appointment]:
    return list(
        session.exec(
            select(Appointment).where(Appointment.patient_id == patient_id)
        ).all()
    )


def find_conflicting_appointment(
    session: Session,
    doctor_id: int,
    appointment_date: date,
    start_time: time,
    end_time: time,
) -> Appointment | None:
    appointments = session.exec(
        select(Appointment).where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
            Appointment.status == "booked",
        )
    ).all()

    for appointment in appointments:
        if start_time < appointment.end_time and appointment.start_time < end_time:
            return appointment

    return None
