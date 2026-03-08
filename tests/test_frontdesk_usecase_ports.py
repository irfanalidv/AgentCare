from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcare.usecases.deps import FrontdeskDeps
from agentcare.usecases.frontdesk import process_frontdesk_execution


@dataclass
class _Customer:
    customer_id: str


class _Store:
    def semantic_lookup(self, query: str) -> dict[str, Any]:
        return {"found": False, "engine": "test"}

    def upsert_from_interaction(self, **kwargs: Any) -> _Customer:
        return _Customer(customer_id="cust_test_001")

    def is_execution_processed(self, execution_id: str) -> bool:
        return False

    def mark_execution_processed(self, execution_id: str) -> None:
        return None


class _Connector:
    def check_slots(self, **kwargs: Any):
        return type("SlotCheck", (), {"ok": True, "chosen_start_iso": None, "slots_preview": [], "error": None, "skipped": True})()

    def book_slot(self, **kwargs: Any):
        return type("Booking", (), {"ok": False, "booking_id": None, "start_iso": None, "error": None, "skipped": True})()


@dataclass
class _Policy:
    allow_auto_booking: bool = False
    escalation_required: bool = False
    triage_queue: str = "standard"
    follow_up_sla_hours: int = 24
    reason: str = "test_policy"


@dataclass
class _Health:
    care_category: str = "general"
    concern_tags: list[str] = None  # type: ignore[assignment]
    risk_level: str = "low"
    urgency_level: str = "routine"
    follow_up_recommendation: str = "none"
    needs_clinical_followup: bool = False

    def __post_init__(self) -> None:
        if self.concern_tags is None:
            self.concern_tags = []


@dataclass
class _Doctor:
    doctor_id: str = "doc_001"
    doctor_name: str = "Dr. Test"
    doctor_specialty: str = "General Medicine"
    assignment_reason: str = "default"


def _deps() -> FrontdeskDeps:
    class _Extraction:
        def model_dump(self) -> dict[str, Any]:
            return {}

    return FrontdeskDeps(
        store=_Store(),
        connector=_Connector(),
        extract_fields=lambda t: _Extraction(),
        send_confirmation_email=lambda **kwargs: {"ok": True},
        persist_call_event=lambda **kwargs: {"stored": "json_fallback"},
        persist_call_lifecycle_event=lambda **kwargs: {"stored": "json_fallback"},
        assign_doctor=lambda **kwargs: _Doctor(),
        analyze_healthcare_context=lambda **kwargs: _Health(),
        evaluate_frontdesk_policy=lambda **kwargs: _Policy(),
    )


def test_frontdesk_usecase_with_injected_ports() -> None:
    execution = {
        "id": "exec_ports_001",
        "status": "completed",
        "transcript": "Patient needs a follow-up and shared email test@example.com",
        "extracted_data": {"customer_email": "test@example.com", "intent": "new_appointment"},
        "telephony_data": {"to_number": "+15550000001"},
    }
    result = process_frontdesk_execution(
        execution,
        source="test",
        automate_actions=False,
        enforce_idempotency=True,
        deps=_deps(),
    )
    assert result.ok is True
    assert result.execution_id == "exec_ports_001"
    assert result.customer_id == "cust_test_001"
