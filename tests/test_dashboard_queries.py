"""Dashboard projections over the local JSON stores."""

from __future__ import annotations

import uuid
from pathlib import Path

from agentcare.analytics import build_appointment_summary, build_cases_queue, persist_call_event
from agentcare.customer import CustomerMemoryStore
from agentcare.settings import settings


def _seed():
    store = CustomerMemoryStore(Path(settings.customer_store_path))
    cust = store.upsert_from_interaction(
        name="Ava Patel", email="ava@x.com", phone_e164="+15550001"
    )
    booked, failed = str(uuid.uuid4()), str(uuid.uuid4())
    common = {
        "customer_id": cust.customer_id,
        "transcript": "knee pain",
        "conversation_time": 60.0,
        "target_phone": "+15550001",
        "intent": "new_appointment",
    }
    persist_call_event(
        execution_id=booked,
        status="completed",
        appointment_id="bk_1",
        slot_start="2026-11-02T05:30:00+00:00",
        extracted_data={
            "reason": "knee pain",
            "cal_booking": {"ok": True, "booking_id": "bk_1"},
            "email_confirmation": {"id": "em_1", "sent_at": "2026-11-01T10:00:00Z"},
        },
        **common,
    )
    persist_call_event(
        execution_id=failed,
        status="completed",
        appointment_id=None,
        slot_start=None,
        extracted_data={
            "reason": "skin rash",
            "cal_booking": {"ok": False, "error": "calendar_down"},
        },
        **dict(common, target_phone="+15550002", customer_id=None),
    )
    persist_call_event(
        execution_id="exec_demo_9",
        status="completed",
        appointment_id=None,
        slot_start=None,
        **common,
    )  # synthetic: hidden
    return booked


def test_appointment_summary(offline):
    _seed()
    out = build_appointment_summary(limit=10)
    assert len(out["doctor_directory"]) == 6
    by_appt = {r.get("appointment_id"): r for r in out["rows"]}
    assert "bk_1" in by_appt
    assert len(out["rows"]) == 2


def test_cases_queue(offline):
    _seed()
    out = build_cases_queue(limit=10)
    by_phone = {r["patient_phone"]: r for r in out["rows"]}
    assert set(by_phone) == {"+15550001", "+15550002"}  # one case per phone number
    assert by_phone["+15550001"]["patient_email"] == "ava@x.com"
    assert by_phone["+15550002"]["recommended_action"] == "human_review_booking_failed"
