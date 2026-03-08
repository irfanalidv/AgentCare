from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="AgentCare Mock EHR", version="0.1.0")


class Patient(BaseModel):
    patient_id: str
    name: str
    phone_e164: str
    dob: str | None = None


class Appointment(BaseModel):
    appointment_id: str
    patient_id: str
    slot_start: datetime
    reason: str | None = None
    status: Literal["booked", "cancelled"] = "booked"


PATIENTS: dict[str, Patient] = {
    "p_001": Patient(patient_id="p_001", name="Ava Patel", phone_e164="+15550000001", dob="1992-10-12"),
    "p_002": Patient(patient_id="p_002", name="Noah Kim", phone_e164="+15550000002", dob="1985-03-28"),
}

APPOINTMENTS: dict[str, Appointment] = {}


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _generate_slots(day: date, *, start_hour: int = 9, end_hour: int = 17, step_minutes: int = 30) -> list[datetime]:
    slots: list[datetime] = []
    start = datetime.combine(day, time(hour=start_hour), tzinfo=timezone.utc)
    end = datetime.combine(day, time(hour=end_hour), tzinfo=timezone.utc)
    cur = start
    while cur < end:
        slots.append(cur)
        cur += timedelta(minutes=step_minutes)
    return slots


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "patients": len(PATIENTS), "appointments": len(APPOINTMENTS)}


@app.get("/patients/{patient_id}")
def get_patient(patient_id: str) -> Patient:
    p = PATIENTS.get(patient_id)
    if not p:
        raise HTTPException(status_code=404, detail="patient not found")
    return p


@app.get("/patients/by_phone")
def get_patient_by_phone(phone_e164: str) -> Patient:
    for p in PATIENTS.values():
        if p.phone_e164 == phone_e164:
            return p
    raise HTTPException(status_code=404, detail="patient not found")


class AvailableSlotsQuery(BaseModel):
    day: date = Field(..., description="Date (YYYY-MM-DD) in UTC for demo")
    patient_phone_e164: str | None = None


@app.get("/tools/get_available_slots")
def tool_get_available_slots(day: date) -> dict[str, Any]:
    slots = _generate_slots(day)
    booked = {a.slot_start for a in APPOINTMENTS.values() if a.status == "booked"}
    available = [s for s in slots if s not in booked]
    return {"day": str(day), "timezone": "UTC", "available_slots": [s.isoformat() for s in available]}


@app.post("/tools/get_available_slots")
def tool_get_available_slots_post(q: AvailableSlotsQuery) -> dict[str, Any]:
    return tool_get_available_slots(day=q.day)


class BookAppointmentRequest(BaseModel):
    patient_phone_e164: str
    slot_start_iso: str = Field(..., description="ISO datetime for slot start (UTC preferred)")
    reason: str | None = None


@app.post("/tools/book_appointment")
def tool_book_appointment(req: BookAppointmentRequest) -> dict[str, Any]:
    try:
        slot_start = _utc(datetime.fromisoformat(req.slot_start_iso.replace("Z", "+00:00")))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid slot_start_iso: {e}") from e

    # Verify slot is allowed (within next 30 days for demo).
    if slot_start < datetime.now(timezone.utc) - timedelta(minutes=1):
        raise HTTPException(status_code=400, detail="slot_start must be in the future")
    if slot_start > datetime.now(timezone.utc) + timedelta(days=30):
        raise HTTPException(status_code=400, detail="slot_start too far in the future for demo")

    # Ensure patient exists (create if unknown for demo).
    patient = None
    for p in PATIENTS.values():
        if p.phone_e164 == req.patient_phone_e164:
            patient = p
            break
    if patient is None:
        new_id = f"p_{len(PATIENTS) + 1:03d}"
        patient = Patient(patient_id=new_id, name="Unknown", phone_e164=req.patient_phone_e164)
        PATIENTS[new_id] = patient

    # Ensure not already booked.
    for a in APPOINTMENTS.values():
        if a.status == "booked" and a.slot_start == slot_start:
            raise HTTPException(status_code=409, detail="slot already booked")

    appt_id = f"appt_{len(APPOINTMENTS) + 1:05d}"
    appt = Appointment(appointment_id=appt_id, patient_id=patient.patient_id, slot_start=slot_start, reason=req.reason)
    APPOINTMENTS[appt_id] = appt

    return {
        "status": "booked",
        "appointment_id": appt_id,
        "patient_id": patient.patient_id,
        "slot_start": slot_start.isoformat(),
        "reason": req.reason,
    }

