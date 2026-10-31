"""End-to-end front-desk pipeline with the real analysis/policy/doctor layers and
fake connector, store and notifier (offline)."""

from __future__ import annotations

from typing import Any

from agentcare.analysis import analyze_healthcare_context
from agentcare.connectors.appointments import BookingResult, SlotCheckResult
from agentcare.customer import CustomerMemoryStore
from agentcare.doctor import assign_doctor
from agentcare.extraction import ConversationExtraction
from agentcare.policies import evaluate_frontdesk_policy
from agentcare.usecases import (
    FrontdeskDeps,
    process_agentcare_execution,
    resolve_execution_workflow,
)
from agentcare.usecases.frontdesk import process_frontdesk_execution


class RecordingConnector:
    def __init__(self, slot: str | None = "2026-11-02T05:30:00+00:00", book_ok: bool = True):
        self.slot, self.book_ok, self.booked = slot, book_ok, []

    def check_slots(self, *, preferred_date_or_window, execution_id) -> SlotCheckResult:
        return SlotCheckResult(
            ok=bool(self.slot),
            chosen_start_iso=self.slot,
            slots_preview=[self.slot] if self.slot else [],
            error=None if self.slot else "no_free_slots",
        )

    def book_slot(self, **kwargs: Any) -> BookingResult:
        self.booked.append(kwargs)
        if not self.book_ok:
            return BookingResult(ok=False, booking_id=None, start_iso=None, error="calendar_down")
        return BookingResult(ok=True, booking_id="bk_42", start_iso=kwargs["slot_start_iso"])


def make_deps(tmp_path, connector, emails, extraction=None) -> FrontdeskDeps:
    return FrontdeskDeps(
        store=CustomerMemoryStore(tmp_path / "customers.json"),
        connector=connector,
        extract_fields=lambda t: extraction or ConversationExtraction(),
        send_confirmation_email=lambda **kw: emails.append(kw) or {"ok": True, "id": "em_1"},
        persist_call_event=lambda **kw: {"stored": "test"},
        persist_call_lifecycle_event=lambda **kw: {"stored": "test"},
        assign_doctor=assign_doctor,
        analyze_healthcare_context=analyze_healthcare_context,
        evaluate_frontdesk_policy=evaluate_frontdesk_policy,
    )


BOOKING_CALL = {
    "id": "ex_1",
    "status": "completed",
    "conversation_time": 80,
    "transcript": "Hi, this is ava patel, ava@example.com. I have knee pain and want a visit tomorrow 11am.",
    "telephony_data": {"from_number": "+15550001"},
}


def test_completed_booking_call_books_and_emails(offline, tmp_path):
    connector, emails = RecordingConnector(), []
    extraction = ConversationExtraction(
        intent="new_appointment",
        patient_name="ava patel",
        reason_for_visit="knee pain",
        visit_type="new",
    )
    res = process_frontdesk_execution(
        BOOKING_CALL, source="test", deps=make_deps(tmp_path, connector, emails, extraction)
    )
    ex = res.extracted_data
    assert res.cal_booking["ok"] and res.cal_booking["booking_id"] == "bk_42"
    assert ex["customer_name"] == "Ava Patel" and ex["customer_email"] == "ava@example.com"
    assert ex["assigned_doctor_specialty"] == "Orthopedics"
    assert connector.booked[0]["doctor_name"] == "Dr. Rahul Verma"
    assert emails[0]["appointment_id"] == "bk_42"
    assert res.customer_id == "cust_000001"


def test_high_risk_call_is_escalated_not_booked(offline, tmp_path):
    connector, emails = RecordingConnector(), []
    call = dict(BOOKING_CALL, transcript="I have chest pain, book me in. ava@example.com")
    extraction = ConversationExtraction(intent="new_appointment")
    res = process_frontdesk_execution(
        call, source="test", deps=make_deps(tmp_path, connector, emails, extraction)
    )
    ex = res.extracted_data
    assert ex["risk_level"] == "high" and ex["policy_escalation_required"]
    assert ex["automation_blocked_reason"] == "risk_blocked_auto_booking:high"
    assert connector.booked == [] and emails == []


def test_failed_booking_reports_instead_of_emailing(offline, tmp_path):
    connector, emails = RecordingConnector(book_ok=False), []
    extraction = ConversationExtraction(intent="new_appointment")
    res = process_frontdesk_execution(
        BOOKING_CALL, source="test", deps=make_deps(tmp_path, connector, emails, extraction)
    )
    assert res.cal_booking["error"] == "calendar_down"
    assert res.email_confirmation["reason"] == "booking_failed" and emails == []


def test_no_slots_skips_booking(offline, tmp_path):
    connector, emails = RecordingConnector(slot=None), []
    extraction = ConversationExtraction(intent="new_appointment")
    res = process_frontdesk_execution(
        BOOKING_CALL, source="test", deps=make_deps(tmp_path, connector, emails, extraction)
    )
    assert res.cal_booking["skipped"] and res.cal_booking["error"] == "no_free_slots"
    assert connector.booked == []


def test_idempotency_with_json_processed_file(offline, tmp_path):
    class StoreWithoutTracking(CustomerMemoryStore):
        pass

    deps = make_deps(tmp_path, RecordingConnector(), [])
    first = process_frontdesk_execution(
        BOOKING_CALL, source="t", automate_actions=False, enforce_idempotency=True, deps=deps
    )
    second = process_frontdesk_execution(
        BOOKING_CALL, source="t", automate_actions=False, enforce_idempotency=True, deps=deps
    )
    assert not first.deduplicated and second.deduplicated


def test_resolve_and_route_workflow(offline, monkeypatch):
    assert (
        resolve_execution_workflow({"metadata": {"workflow": "care_navigation"}})
        == "care_navigation"
    )
    assert resolve_execution_workflow({"agent_name": "Weekly Wellness"}) == "wellness_checkin"
    assert resolve_execution_workflow({"metadata": "not-a-dict"}) == "frontdesk_booking"
    res = process_agentcare_execution(
        {"id": "w1", "transcript": ""}, source="t", workflow="wellness_checkin"
    )
    assert res.error == "empty_transcript"
