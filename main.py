from datetime import date, time

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app import crud
from app.db import engine


def get_session():
    with Session(engine) as session:
        yield session


class AppointmentCreate(BaseModel):
    doctor_id: int
    patient_id: int
    appointment_date: date
    start_time: time
    end_time: time


class AppointmentReschedule(BaseModel):
    appointment_date: date
    start_time: time
    end_time: time


app = FastAPI(title="Agent-RAG Hospital API")


@app.get("/doctors")
def api_get_doctors(session: Session = Depends(get_session)):
    return crud.get_doctors(session)


@app.get("/doctors/{doctor_id}")
def api_get_doctor(doctor_id: int, session: Session = Depends(get_session)):
    doctor = crud.get_doctor_by_id(session, doctor_id)
    if doctor is None:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doctor


@app.get("/doctors/{doctor_id}/schedule")
def api_get_doctor_schedule(doctor_id: int, session: Session = Depends(get_session)):
    doctor = crud.get_doctor_by_id(session, doctor_id)
    if doctor is None:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return crud.get_doctor_schedule(session, doctor_id)


@app.post("/appointments", status_code=201)
def api_book_appointment(body: AppointmentCreate, session: Session = Depends(get_session)):
    if crud.get_doctor_by_id(session, body.doctor_id) is None:
        raise HTTPException(status_code=404, detail="Doctor not found")

    conflict = crud.find_conflicting_appointment(
        session,
        doctor_id=body.doctor_id,
        appointment_date=body.appointment_date,
        start_time=body.start_time,
        end_time=body.end_time,
    )
    if conflict is not None:
        raise HTTPException(status_code=409, detail="Time slot already booked")

    return crud.book_appointment(
        session,
        doctor_id=body.doctor_id,
        patient_id=body.patient_id,
        appointment_date=body.appointment_date,
        start_time=body.start_time,
        end_time=body.end_time,
    )


@app.put("/appointments/{appointment_id}")
def api_reschedule_appointment(appointment_id: int, body: AppointmentReschedule, session: Session = Depends(get_session)):
    appointment = crud.reschedule_appointment(
        session,
        appointment_id,
        appointment_date=body.appointment_date,
        start_time=body.start_time,
        end_time=body.end_time,
    )
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment


@app.delete("/appointments/{appointment_id}")
def api_cancel_appointment(appointment_id: int, session: Session = Depends(get_session)):
    appointment = crud.cancel_appointment(session, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment


@app.get("/patients/{patient_id}/appointments")
def api_get_patient_appointments(patient_id: int, session: Session = Depends(get_session)):
    return crud.get_patient_appointments(session, patient_id)




