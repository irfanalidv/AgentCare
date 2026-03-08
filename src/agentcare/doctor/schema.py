from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DoctorProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    doctor_id: str
    name: str
    specialty: str
    languages: list[str] = ["english"]
    consult_modes: list[Literal["in_person", "tele"]] = ["in_person"]
    accepting_new_patients: bool = True


DEFAULT_DOCTORS: list[DoctorProfile] = [
    DoctorProfile(doctor_id="dr_001", name="Dr. Priya Menon", specialty="General Medicine", languages=["english", "hindi"]),
    DoctorProfile(doctor_id="dr_002", name="Dr. Arjun Shah", specialty="Cardiology", languages=["english", "hindi"]),
    DoctorProfile(doctor_id="dr_003", name="Dr. Meera Kulkarni", specialty="Dermatology", languages=["english", "hindi"]),
    DoctorProfile(doctor_id="dr_004", name="Dr. Rahul Verma", specialty="Orthopedics", languages=["english", "hindi"]),
    DoctorProfile(doctor_id="dr_005", name="Dr. Neha Iyer", specialty="ENT", languages=["english", "hindi"]),
    DoctorProfile(
        doctor_id="dr_006",
        name="Dr. Kavya Rao",
        specialty="Psychiatry",
        languages=["english", "hindi"],
        consult_modes=["tele", "in_person"],
    ),
]


def load_doctor_schema(path: Path = Path("artifacts/doctors.json")) -> list[DoctorProfile]:
    """
    Load doctor schema from JSON if present; otherwise use framework defaults.
    Expected shape: a JSON array of doctor objects.
    """
    if not path.exists():
        return DEFAULT_DOCTORS
    try:
        data = json.loads(path.read_text("utf-8"))
        if isinstance(data, list):
            doctors = [DoctorProfile.model_validate(x) for x in data if isinstance(x, dict)]
            if doctors:
                return doctors
    except Exception:
        pass
    return DEFAULT_DOCTORS
