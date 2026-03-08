from __future__ import annotations

from dataclasses import dataclass

from agentcare.doctor.schema import DoctorProfile, load_doctor_schema


@dataclass
class DoctorAssignment:
    doctor_id: str
    doctor_name: str
    doctor_specialty: str
    assignment_reason: str


def assign_doctor(
    *,
    reason: str | None,
    intent: str | None = None,
    doctors: list[DoctorProfile] | None = None,
) -> DoctorAssignment:
    """
    Route a patient to the best-fit doctor using lightweight specialty heuristics.
    """
    directory = doctors or load_doctor_schema()
    if not directory:
        return DoctorAssignment(
            doctor_id="unassigned",
            doctor_name="Unassigned",
            doctor_specialty="General Medicine",
            assignment_reason="doctor_directory_empty",
        )

    text = f"{reason or ''} {intent or ''}".lower()
    specialty_keywords: list[tuple[str, tuple[str, ...]]] = [
        ("Psychiatry", ("anxiety", "depression", "panic", "sleep", "therapy", "stress")),
        ("Cardiology", ("chest", "bp", "heart", "cardio", "palpitation")),
        ("Dermatology", ("skin", "rash", "acne", "eczema", "allergy")),
        ("Orthopedics", ("knee", "back", "joint", "fracture", "pain")),
        ("ENT", ("ear", "nose", "throat", "sinus", "hearing")),
    ]

    chosen = directory[0]
    route_reason = "default_general_medicine"
    for specialty, keywords in specialty_keywords:
        if any(k in text for k in keywords):
            match = next((d for d in directory if d.specialty.lower() == specialty.lower()), None)
            if match is not None:
                chosen = match
                route_reason = f"keyword_match:{specialty.lower()}"
                break

    return DoctorAssignment(
        doctor_id=chosen.doctor_id,
        doctor_name=chosen.name,
        doctor_specialty=chosen.specialty,
        assignment_reason=route_reason,
    )
