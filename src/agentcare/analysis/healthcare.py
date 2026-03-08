from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class HealthcareAnalysis:
    care_category: str
    concern_tags: list[str]
    risk_level: str
    urgency_level: str
    follow_up_recommendation: str
    needs_clinical_followup: bool


_CATEGORY_PATTERNS: dict[str, list[str]] = {
    "mental_health": [
        r"\banxiety\b",
        r"\bstress\b",
        r"\bpanic\b",
        r"\bdepression\b",
        r"\btherapy\b",
        r"\bsleep (issue|problem|difficult|difficulty)\b",
        r"\binsomnia\b",
    ],
    "musculoskeletal": [
        r"\bback pain\b",
        r"\bneck pain\b",
        r"\bjoint pain\b",
        r"\bknee pain\b",
        r"\bshoulder pain\b",
        r"\bmuscle\b",
        r"\bortho\b",
    ],
    "cardio_metabolic": [
        r"\bchest pain\b",
        r"\bpalpitation\b",
        r"\bbp\b",
        r"\bhypertension\b",
        r"\bdiabetes\b",
        r"\bblood sugar\b",
    ],
    "respiratory_ent": [
        r"\bcough\b",
        r"\bbreath\b",
        r"\bbreathing\b",
        r"\bsinus\b",
        r"\bthroat\b",
        r"\bent\b",
    ],
    "dermatology": [
        r"\brash\b",
        r"\bskin\b",
        r"\bacne\b",
        r"\beczema\b",
        r"\ballergy\b",
    ],
    "general_consult": [
        r"\bfever\b",
        r"\bcheckup\b",
        r"\bfollow[\s-]?up\b",
        r"\bconsultation\b",
    ],
}

_HIGH_RISK_PATTERNS = [
    r"\bsuicid(al|e)\b",
    r"\bself[- ]harm\b",
    r"\bchest pain\b",
    r"\bsevere breath(ing)?\b",
    r"\bfainted\b",
    r"\bunconscious\b",
]

_MEDIUM_RISK_PATTERNS = [
    r"\bsevere\b",
    r"\bnot able to sleep\b",
    r"\bpanic\b",
    r"\bhigh stress\b",
    r"\bcontinuous pain\b",
]


def _match_patterns(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, flags=re.I) for p in patterns)


def _tags_for_text(text: str) -> list[str]:
    tags: list[str] = []
    for category, patterns in _CATEGORY_PATTERNS.items():
        if _match_patterns(text, patterns):
            tags.append(category)
    # keep stable and short
    return sorted(list(dict.fromkeys(tags)))[:4]


def analyze_healthcare_context(*, transcript: str | None, reason: str | None, intent: str | None) -> HealthcareAnalysis:
    text = " ".join([reason or "", transcript or ""]).strip().lower()
    if not text:
        return HealthcareAnalysis(
            care_category="general_consult",
            concern_tags=[],
            risk_level="low",
            urgency_level="routine",
            follow_up_recommendation="capture_more_details",
            needs_clinical_followup=False,
        )

    tags = _tags_for_text(text)
    care_category = tags[0] if tags else "general_consult"

    if _match_patterns(text, _HIGH_RISK_PATTERNS):
        risk_level = "high"
        urgency_level = "urgent"
        follow_up = "human_nurse_triage_immediately"
        needs_clinical_followup = True
    elif _match_patterns(text, _MEDIUM_RISK_PATTERNS):
        risk_level = "medium"
        urgency_level = "priority"
        follow_up = "doctor_followup_within_24h"
        needs_clinical_followup = True
    else:
        risk_level = "low"
        urgency_level = "routine"
        follow_up = "standard_booking_flow"
        needs_clinical_followup = False

    if intent in {"reschedule", "appointment_status"} and risk_level == "low":
        follow_up = "appointment_ops_support"

    return HealthcareAnalysis(
        care_category=care_category,
        concern_tags=tags,
        risk_level=risk_level,
        urgency_level=urgency_level,
        follow_up_recommendation=follow_up,
        needs_clinical_followup=needs_clinical_followup,
    )
