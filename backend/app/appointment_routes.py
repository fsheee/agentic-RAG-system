"""REST endpoints for doctors and appointments.

These are plain CRUD routes. POST /ask remains the single AI/NLP endpoint;
nothing here calls the LLM, and no RAG or booking logic lives here.

Authorization is enforced in Python via require_roles(), and identity
always comes from the JWT — never from the request body or a query
parameter. Ownership uses the same rules as the agent's booking tool
(Patient.user_id / Doctor.user_id), so the REST API and /ask can never
disagree about who may see or change an appointment.
"""

from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.agent.tools.booking_tool import check_slot, end_time_for
from app.auth_routes import require_roles
from app.crud import (
    book_appointment,
    delete_appointment,
    get_all_appointments,
    get_appointment_by_id,
    get_doctor_appointments,
    get_doctor_by_id,
    get_doctor_by_user_id,
    get_doctor_schedule,
    get_doctors,
    get_patient_appointments,
    get_patient_by_user_id,
    get_patients,
    replace_doctor_schedule,
    update_appointment,
)
from app.db import get_session
from app.schema import Appointment, Doctor, Patient, Role, User

router = APIRouter(tags=["appointments"])

# Module-level dependencies so tests can override them by reference.
_patient_only = require_roles(Role.patient)
_doctor_only = require_roles(Role.doctor)
_admin_only = require_roles(Role.admin)
_patient_or_admin = require_roles(Role.patient, Role.admin)

# Statuses an admin may set. Cancelling is a status change, not a delete.
ALLOWED_STATUSES = {"booked", "cancelled"}


# --------------------------------------------------------------------------
# Response / request schemas
# --------------------------------------------------------------------------

class DoctorResponse(BaseModel):
    id: int
    name: str
    specialization: str
    consultation_fee: int | None = None


class ScheduleSlotResponse(BaseModel):
    day_of_week: int
    start_time: time
    end_time: time


class ScheduleSlotInput(BaseModel):
    day_of_week: int = Field(ge=0, le=6)  # 0 = Monday ... 6 = Sunday
    start_time: time
    end_time: time


class ScheduleUpdate(BaseModel):
    """The complete week. Slots omitted here are removed, so this replaces
    the schedule rather than adding to it."""

    slots: list[ScheduleSlotInput] = Field(default_factory=list)


class AppointmentResponse(BaseModel):
    id: int
    doctor_id: int
    doctor_name: str
    patient_id: int
    patient_name: str
    appointment_date: date
    start_time: time
    end_time: time
    status: str


class AppointmentCreate(BaseModel):
    doctor_id: int
    appointment_date: date
    start_time: time


class AppointmentUpdate(BaseModel):
    appointment_date: date | None = None
    start_time: time | None = None
    status: str | None = None


# --------------------------------------------------------------------------
# Serialization helpers
# --------------------------------------------------------------------------

def _serialize_appointment(
    appointment: Appointment,
    doctors: dict[int, Doctor],
    patients: dict[int, Patient],
) -> AppointmentResponse:
    doctor = doctors.get(appointment.doctor_id)
    patient = patients.get(appointment.patient_id)

    return AppointmentResponse(
        id=appointment.id,
        doctor_id=appointment.doctor_id,
        doctor_name=doctor.name if doctor else "Unknown doctor",
        patient_id=appointment.patient_id,
        patient_name=patient.name if patient else "Unknown patient",
        appointment_date=appointment.appointment_date,
        start_time=appointment.start_time,
        end_time=appointment.end_time,
        status=appointment.status,
    )


def _appointments_response(
    session: Session, appointments: list[Appointment]
) -> list[AppointmentResponse]:
    doctors = {doctor.id: doctor for doctor in get_doctors(session)}
    patients = {patient.id: patient for patient in get_patients(session)}

    return [
        _serialize_appointment(appointment, doctors, patients)
        for appointment in appointments
    ]


def _require_doctor(session: Session, doctor_id: int) -> Doctor:
    doctor = get_doctor_by_id(session, doctor_id)
    if doctor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")
    return doctor


def _slot_response(slot) -> ScheduleSlotResponse:
    return ScheduleSlotResponse(
        day_of_week=slot.day_of_week,
        start_time=slot.start_time,
        end_time=slot.end_time,
    )


def _validate_slots(slots: list[ScheduleSlotInput]) -> None:
    """Reject slots that could never book: a backwards window or two
    overlapping slots on the same day, which would make availability
    ambiguous."""
    by_day: dict[int, list[ScheduleSlotInput]] = {}

    for slot in slots:
        if slot.start_time >= slot.end_time:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Slot on day {slot.day_of_week} must start before it ends.",
            )
        by_day.setdefault(slot.day_of_week, []).append(slot)

    for day, day_slots in by_day.items():
        ordered = sorted(day_slots, key=lambda slot: slot.start_time)
        for earlier, later in zip(ordered, ordered[1:]):
            if later.start_time < earlier.end_time:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Overlapping slots on day {day}.",
                )


def _require_linked_doctor(session: Session, user: User) -> Doctor:
    """The Doctor row for the signed-in doctor.

    An account with no linked Doctor row must not fall back to any other
    doctor's data, so this fails closed.
    """
    doctor = get_doctor_by_user_id(session, user.id)
    if doctor is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No doctor record is linked to your account.",
        )
    return doctor


def _require_linked_patient(session: Session, user: User) -> Patient:
    """The Patient row for the signed-in patient, or 404.

    Never falls back to the seeded demo patient: an unlinked account must
    not be able to read or change someone else's appointments.
    """
    patient = get_patient_by_user_id(session, user.id)
    if patient is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No patient record is linked to your account.",
        )
    return patient


def _require_appointment(session: Session, appointment_id: int) -> Appointment:
    appointment = get_appointment_by_id(session, appointment_id)
    if appointment is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No appointment #{appointment_id} found.",
        )
    return appointment


# --------------------------------------------------------------------------
# Doctors
# --------------------------------------------------------------------------

@router.get("/doctors", response_model=list[DoctorResponse], tags=["doctors"])
def list_doctors(session: Session = Depends(get_session)):
    """Doctor list: public hospital information, so no token is required.

    Matches the agent's behavior, where an anonymous caller may ask about
    doctors and their fees.
    """
    return [
        DoctorResponse(
            id=doctor.id,
            name=doctor.name,
            specialization=doctor.specialization,
            consultation_fee=doctor.consultation_fee,
        )
        for doctor in get_doctors(session)
    ]


@router.get(
    "/doctors/me/schedule",
    response_model=list[ScheduleSlotResponse],
    tags=["doctors"],
)
def my_schedule(
    user: User = Depends(_doctor_only),
    session: Session = Depends(get_session),
):
    """The signed-in doctor's own weekly schedule."""
    doctor = _require_linked_doctor(session, user)

    return [
        _slot_response(slot) for slot in get_doctor_schedule(session, doctor.id)
    ]


@router.get(
    "/doctors/me/appointments",
    response_model=list[AppointmentResponse],
    tags=["doctors"],
)
def my_doctor_appointments(
    user: User = Depends(_doctor_only),
    session: Session = Depends(get_session),
):
    """Appointments booked with the signed-in doctor — only their own."""
    doctor = _require_linked_doctor(session, user)

    return _appointments_response(
        session, get_doctor_appointments(session, doctor.id)
    )


# --------------------------------------------------------------------------
# Appointments — patient
# --------------------------------------------------------------------------

@router.post(
    "/appointments",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["appointments"],
)
def create_appointment(
    request: AppointmentCreate,
    user: User = Depends(_patient_only),
    session: Session = Depends(get_session),
):
    """Book an appointment for the signed-in patient.

    The patient is the caller's own linked Patient row — never an id taken
    from the request body — so a patient cannot book on someone else's
    behalf. Slot validation reuses the same check the agent's booking
    workflow uses.
    """
    patient = _require_linked_patient(session, user)
    doctor = _require_doctor(session, request.doctor_id)

    end = end_time_for(request.start_time)
    available, message = check_slot(
        session,
        doctor.id,
        doctor.name,
        request.appointment_date,
        request.start_time,
        end,
    )
    if not available:
        raise HTTPException(status.HTTP_409_CONFLICT, message)

    appointment = book_appointment(
        session,
        doctor_id=doctor.id,
        patient_id=patient.id,
        appointment_date=request.appointment_date,
        start_time=request.start_time,
        end_time=end,
    )

    return _serialize_appointment(
        appointment, {doctor.id: doctor}, {patient.id: patient}
    )


@router.get(
    "/appointments",
    response_model=list[AppointmentResponse],
    tags=["appointments"],
)
def list_appointments(
    user: User = Depends(_patient_or_admin),
    session: Session = Depends(get_session),
):
    """A patient sees only their own appointments; an admin sees all."""
    if user.role is Role.admin:
        return _appointments_response(session, get_all_appointments(session))

    patient = _require_linked_patient(session, user)
    return _appointments_response(
        session, get_patient_appointments(session, patient.id)
    )


# --------------------------------------------------------------------------
# Appointments — admin
# --------------------------------------------------------------------------

@router.get(
    "/admin/doctors/{doctor_id}/schedule",
    response_model=list[ScheduleSlotResponse],
    tags=["admin"],
)
def admin_get_doctor_schedule(
    doctor_id: int,
    user: User = Depends(_admin_only),
    session: Session = Depends(get_session),
):
    """Any doctor's weekly schedule. Admin only."""
    doctor = _require_doctor(session, doctor_id)

    return [
        _slot_response(slot) for slot in get_doctor_schedule(session, doctor.id)
    ]


@router.put(
    "/admin/doctors/{doctor_id}/schedule",
    response_model=list[ScheduleSlotResponse],
    tags=["admin"],
)
def admin_replace_doctor_schedule(
    doctor_id: int,
    request: ScheduleUpdate,
    user: User = Depends(_admin_only),
    session: Session = Depends(get_session),
):
    """Set a doctor's weekly schedule, replacing the previous one.

    This is the runtime replacement for the seeded hardcoded schedule:
    changing a doctor's hours no longer needs a code change and a
    re-seed. Every slot is validated the same way bookings are, and the
    result is what `check_slot` will use for the next booking.

    An empty `slots` list clears the schedule, which also makes the
    doctor unbookable until slots are set again.
    """
    doctor = _require_doctor(session, doctor_id)
    _validate_slots(request.slots)

    replace_doctor_schedule(
        session,
        doctor.id,
        [
            (slot.day_of_week, slot.start_time, slot.end_time)
            for slot in request.slots
        ],
    )

    return [
        _slot_response(slot) for slot in get_doctor_schedule(session, doctor.id)
    ]


@router.get(
    "/admin/appointments",
    response_model=list[AppointmentResponse],
    tags=["admin"],
)
def admin_list_appointments(
    user: User = Depends(_admin_only),
    session: Session = Depends(get_session),
):
    """Every appointment. Admin only — never reachable by a patient."""
    return _appointments_response(session, get_all_appointments(session))


@router.patch(
    "/admin/appointments/{appointment_id}",
    response_model=AppointmentResponse,
    tags=["admin"],
)
def admin_update_appointment(
    appointment_id: int,
    request: AppointmentUpdate,
    user: User = Depends(_admin_only),
    session: Session = Depends(get_session),
):
    """Update an appointment. Only an admin may change an appointment."""
    appointment = _require_appointment(session, appointment_id)

    changes: dict = {}

    if request.status is not None:
        if request.status not in ALLOWED_STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"status must be one of: {', '.join(sorted(ALLOWED_STATUSES))}",
            )
        changes["status"] = request.status

    # Changing the date or time moves the slot, so it must still be valid.
    new_day = request.appointment_date or appointment.appointment_date
    new_start = request.start_time or appointment.start_time

    if request.appointment_date is not None or request.start_time is not None:
        new_end = end_time_for(new_start)
        doctor = get_doctor_by_id(session, appointment.doctor_id)

        available, message = check_slot(
            session,
            appointment.doctor_id,
            doctor.name if doctor else "The doctor",
            new_day,
            new_start,
            new_end,
            exclude_appointment_id=appointment_id,
        )
        if not available:
            raise HTTPException(status.HTTP_409_CONFLICT, message)

        changes["appointment_date"] = new_day
        changes["start_time"] = new_start
        changes["end_time"] = new_end

    if not changes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No updatable fields were provided.",
        )

    updated = update_appointment(session, appointment_id, **changes)

    return _appointments_response(session, [updated])[0]


@router.delete(
    "/admin/appointments/{appointment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["admin"],
)
def admin_delete_appointment(
    appointment_id: int,
    user: User = Depends(_admin_only),
    session: Session = Depends(get_session),
):
    """Delete an appointment. Only an admin may delete an appointment."""
    if not delete_appointment(session, appointment_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No appointment #{appointment_id} found.",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
