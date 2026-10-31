"""Local JSON analytics backend: persistence, lifecycle dedupe and KPI fallbacks."""

from __future__ import annotations

import uuid

from agentcare.analytics import (
    get_call_detail_fallback,
    get_call_lifecycle,
    get_calls_timeseries_fallback,
    get_customer_cohorts_fallback,
    get_funnel_fallback,
    get_overview_fallback,
    persist_call_event,
    persist_call_lifecycle_event,
)


def _event(execution_id, **kw):
    base = {
        "execution_id": execution_id,
        "customer_id": "cust_1",
        "status": "completed",
        "transcript": "hello",
        "conversation_time": 60.0,
        "total_cost": 0.5,
        "intent": "new_appointment",
        "appointment_id": "bk_1",
        "follow_up_required": True,
        "extracted_data": {"patient_facing_summary": "Booked."},
    }
    base.update(kw)
    return persist_call_event(**base)


def test_events_upsert_and_kpis(offline):
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    assert _event(a)["stored"] == "json_fallback"
    _event(a, total_cost=1.5)  # same execution: merged, not duplicated
    _event(b, status="no-answer", appointment_id=None, customer_id="cust_1", intent=None)
    _event("exec_demo_001")  # synthetic ids are hidden from KPIs

    overview = get_overview_fallback()
    assert overview["total_calls"] == 2
    assert overview["completed_calls"] == 1 and overview["failed_calls"] == 1
    assert overview["total_cost"] == 2.0
    funnel = get_funnel_fallback()
    assert funnel == {
        "calls_started": 2,
        "appointment_intents": 1,
        "bookings_created": 1,
        "followups_required": 2,
        "source": "json_fallback",
    }
    assert get_customer_cohorts_fallback()["returning_customers"] == 1
    series = get_calls_timeseries_fallback(interval="week")
    assert sum(b["total_calls"] for b in series) == 2
    detail = get_call_detail_fallback(a)
    assert detail["total_cost"] == 1.5
    assert detail["patient_facing_summary"] == "Booked."
    assert get_call_detail_fallback("missing") is None


def test_lifecycle_is_normalised_and_deduplicated(offline):
    persist_call_lifecycle_event(execution_id="e1", status="queued", source="webhook")
    persist_call_lifecycle_event(execution_id="e1", status="in-progress", source="webhook")
    persist_call_lifecycle_event(execution_id="e1", status="in-progress", source="webhook")
    persist_call_lifecycle_event(execution_id="e1", status="completed", source="webhook")
    out = get_call_lifecycle("e1")
    assert [e["state"] for e in out["events"]] == ["requested", "connected", "completed"]
    assert out["current_state"] == "completed"
    assert get_call_lifecycle("nope")["events"] == []
