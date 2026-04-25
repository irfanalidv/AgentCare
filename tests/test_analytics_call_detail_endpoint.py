from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.analytics.app import app
import agentcare.analytics.dashboard_queries as dashboard_queries


def test_analytics_call_detail_fallback_includes_summaries(tmp_path: Path, monkeypatch) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    event_path = artifacts / "call_events.json"
    event_path.write_text(
        json.dumps(
            [
                {
                    "execution_id": "exec_detail_001",
                    "status": "completed",
                    "extracted_data": {
                        "intent": "new_appointment",
                        "patient_facing_summary": "Patient requested a follow-up.",
                        "internal_ops_summary": "intent=new_appointment | note=Follow-up required.",
                    },
                }
            ]
        ),
        "utf-8",
    )
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    resp = client.get("/analytics/calls/exec_detail_001")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["row"]["patient_facing_summary"] == "Patient requested a follow-up."
    assert "internal_ops_summary" in payload["row"]


def test_booking_failed_projection_does_not_confirm_transcript_id(tmp_path: Path, monkeypatch) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "customers.json").write_text(
        json.dumps(
            [
                {
                    "customer_id": "cust_001",
                    "name": "Elifanli",
                    "email": "irfanali29@hotmail.com",
                    "phone_e164": "+919971627567",
                    "interaction_count": 1,
                }
            ]
        ),
        "utf-8",
    )
    (artifacts / "call_events.json").write_text(
        json.dumps(
            [
                {
                    "execution_id": "11111111-1111-4111-8111-111111111111",
                    "customer_id": "cust_001",
                    "status": "completed",
                    "target_phone": "+919971627567",
                    "slot_start": "2026-04-26T19:00:00+05:30",
                    "intent": "new_appointment",
                    "extracted_data": {
                        "customer_name": "Elifanli",
                        "customer_email": "irfanali29@hotmail.com",
                        "customer_phone": "+919971627567",
                        "appointment_id": "APT123456",
                        "preexisting_appointment_id": "APT123456",
                        "reason": "therapy session",
                        "cal_booking": {
                            "ok": False,
                            "booking_id": None,
                            "start_iso": "2026-04-26T19:00:00+05:30",
                            "error": "cal booking failed",
                        },
                    },
                }
            ]
        ),
        "utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dashboard_queries, "_db_ready", lambda: False)

    appointments = dashboard_queries.build_appointment_summary()["rows"]
    row = appointments[0]
    assert row["appointment_id"] is None
    assert row["transcript_appointment_id"] == "APT123456"
    assert row["status"] == "booking_failed"
    assert row["calendar_booking_status"] == "failed"
    assert row["email_delivery_status"] == "not_sent"
    assert row["email_delivery_error"] == "booking_failed"

    cases = dashboard_queries.build_cases_queue()["rows"]
    assert cases[0]["appointment_id"] is None
    assert cases[0]["recommended_action"] == "human_review_booking_failed"
