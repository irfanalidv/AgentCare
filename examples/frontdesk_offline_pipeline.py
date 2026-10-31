"""
Front-desk call -> triage -> booking -> confirmation, fully offline
==================================================================
Shows    : ``process_frontdesk_execution`` on two post-call payloads (the shape Bolna
           sends to a webhook). The real regex extraction, healthcare risk analysis,
           booking policy and doctor routing run; the calendar and email sender are
           in-memory stand-ins, and customers go to a JSON store in a temp folder.
           A routine knee-pain call is booked and confirmed; a chest-pain call is
           escalated to clinical triage and never auto-booked.
Needs    : ``pip install agentcare``. No API keys, no network.
Run      : python examples/frontdesk_offline_pipeline.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from agentcare.analysis import analyze_healthcare_context
from agentcare.connectors.appointments import BookingResult, SlotCheckResult
from agentcare.customer import CustomerMemoryStore
from agentcare.doctor import assign_doctor
from agentcare.extraction import ConversationExtraction
from agentcare.policies import evaluate_frontdesk_policy
from agentcare.usecases import FrontdeskDeps, process_frontdesk_execution


class InMemoryCalendar:
    """Implements AppointmentConnectorPort with one free slot."""

    def check_slots(self, *, preferred_date_or_window, execution_id) -> SlotCheckResult:
        slot = "2026-11-03T05:30:00+00:00"
        return SlotCheckResult(ok=True, chosen_start_iso=slot, slots_preview=[slot])

    def book_slot(self, **kw: Any) -> BookingResult:
        return BookingResult(ok=True, booking_id="bk_1001", start_iso=kw["slot_start_iso"])


def extractor(transcript: str) -> ConversationExtraction:
    """Stand-in for the Mistral extractor: every call here is a booking request."""
    return ConversationExtraction(intent="new_appointment", visit_type="new")


outbox: list[dict[str, Any]] = []
deps = FrontdeskDeps(
    store=CustomerMemoryStore(Path(tempfile.mkdtemp()) / "customers.json"),
    connector=InMemoryCalendar(),
    extract_fields=extractor,
    send_confirmation_email=lambda **kw: outbox.append(kw) or {"ok": True},
    persist_call_event=lambda **kw: {"stored": "skipped_in_example"},
    persist_call_lifecycle_event=lambda **kw: {"stored": "skipped_in_example"},
    assign_doctor=assign_doctor,
    analyze_healthcare_context=analyze_healthcare_context,
    evaluate_frontdesk_policy=evaluate_frontdesk_policy,
)

calls = [
    {
        "id": "call-001",
        "status": "completed",
        "transcript": "Hi, I'm Ava Patel, ava@example.com. My knee pain is back, can I see someone?",
        "extracted_data": {"customer_name": "ava patel", "reason": "knee pain"},
        "telephony_data": {"from_number": "+15550001001"},
    },
    {
        "id": "call-002",
        "status": "completed",
        "transcript": "This is Ravi, ravi@example.com. I have chest pain since this morning.",
        "extracted_data": {"customer_name": "ravi", "reason": "chest pain"},
        "telephony_data": {"from_number": "+15550001002"},
    },
]

for call in calls:
    res = process_frontdesk_execution(call, source="example", deps=deps)
    ex = res.extracted_data
    print(f"\n{call['id']}: {ex['customer_name']} <{ex['customer_email']}>")
    print(
        f"  risk={ex['risk_level']} urgency={ex['urgency_level']} queue={ex['policy_triage_queue']}"
    )
    print(f"  doctor={ex['assigned_doctor_name']} ({ex['assigned_doctor_specialty']})")
    if res.cal_booking:
        print(f"  booked {res.cal_booking['booking_id']} at {res.cal_booking['start_iso']}")
    else:
        print(f"  not auto-booked: {ex.get('automation_blocked_reason')}")

print(f"\nConfirmation emails queued: {[m['appointment_id'] for m in outbox]}")
