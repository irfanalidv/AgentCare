"""Cal.com helpers: slot parsing, slot choice, and API calls over a mock transport."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from agentcare.calendar import cal_client
from agentcare.calendar.cal_client import create_cal_booking, fetch_cal_slots, parse_preferred_slot
from agentcare.settings import settings

TZ = "Asia/Kolkata"


@pytest.mark.parametrize(
    "text, hour, minute",
    [
        ("3pm", 15, 0),
        ("at 10:30", 10, 30),
        ("three pm", 15, 0),
        ("12 am", 0, 0),
        ("9:15 am", 9, 15),
    ],
)
def test_parse_times_today(text, hour, minute):
    parsed = datetime.fromisoformat(parse_preferred_slot(text, timezone_name=TZ))
    assert (parsed.hour, parsed.minute) == (hour, minute)
    assert parsed.date() == datetime.now(ZoneInfo(TZ)).date()


def test_parse_tomorrow_and_dates():
    tomorrow = datetime.fromisoformat(parse_preferred_slot("tomorrow at 4 pm", timezone_name=TZ))
    assert tomorrow.date() == datetime.now(ZoneInfo(TZ)).date() + timedelta(days=1)
    assert parse_preferred_slot("2026-11-02 at 11am", timezone_name=TZ).startswith(
        "2026-11-02T11:00:00"
    )
    assert parse_preferred_slot("2026-11-02T10:00:00", timezone_name=TZ) == (
        "2026-11-02T10:00:00+05:30"
    )
    assert parse_preferred_slot("sometime next week", timezone_name=TZ) is None
    assert parse_preferred_slot("", timezone_name=TZ) is None
    assert parse_preferred_slot(None, timezone_name=TZ) is None


def test_extract_and_choose_slots():
    nested = {
        "data": {
            "slots": {
                "2026-11-02": [{"time": "2026-11-02T04:30:00Z"}, {"start": "2026-11-02T06:30:00Z"}]
            }
        }
    }
    slots = cal_client._extract_slots(nested)
    assert slots == ["2026-11-02T04:30:00Z", "2026-11-02T06:30:00Z"]
    assert cal_client._choose_slot("2026-11-02 at 11am", slots, TZ) == "2026-11-02T06:30:00Z"
    assert cal_client._choose_slot(None, slots, TZ) == slots[0]
    assert cal_client._choose_slot("x", [], TZ) is None


def test_error_text_redacts_keys():
    text = cal_client._safe_error_text("bad key cal_live_abc123 apiKey=secret&x=1")
    assert "abc123" not in text and "secret" not in text


@pytest.fixture
def cal_ready(offline, monkeypatch):
    monkeypatch.setattr(settings, "cal_api_key", "cal_test_key")
    monkeypatch.setattr(settings, "cal_event_type_id", "42")
    monkeypatch.setattr(settings, "cal_timezone", TZ)


def test_fetch_slots_uses_first_working_endpoint(cal_ready, mock_http):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/event-types/42":
            return httpx.Response(200, json={"data": {"id": 42}})
        if req.url.path == "/v2/slots" and "apiKey" not in req.url.params:
            return httpx.Response(500, text="upstream error")
        return httpx.Response(
            200, json={"data": {"2026-11-02": [{"start": "2026-11-02T05:30:00Z"}]}}
        )

    seen = mock_http(handler)
    res = fetch_cal_slots(preferred_date_or_window="2026-11-02 at 10am")
    assert res.ok and res.chosen_start_iso == "2026-11-02T05:30:00Z"
    assert res.details["event_type_id_source"] == "configured"
    assert len(seen) == 3  # verify + failing v2 + v2 with apiKey


def test_create_booking_v2(cal_ready, mock_http):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, json={"data": {"id": 42}})
        body = json.loads(req.content)
        assert body["attendee"]["email"] == "ava@x.com"
        assert "Reason: knee pain" in body["bookingFieldsResponses"]["notes"]
        return httpx.Response(201, json={"data": {"uid": "bk_1"}})

    mock_http(handler)
    res = create_cal_booking(
        patient_name="Ava",
        patient_email="ava@x.com",
        patient_phone=None,
        reason="knee pain",
        doctor_name="Dr. Rahul Verma",
        doctor_specialty="Orthopedics",
        visit_type="new",
        summary="s",
        preferred_date_or_window="2026-11-02 at 10am",
    )
    assert res.ok and res.booking_id == "bk_1"


def test_create_booking_guards(cal_ready, mock_http):
    mock_http(lambda r: httpx.Response(200, json={"data": {"id": 42}}))
    kw = {
        "patient_name": None,
        "patient_phone": None,
        "reason": None,
        "doctor_name": None,
        "doctor_specialty": None,
        "visit_type": None,
        "summary": None,
    }
    assert create_cal_booking(patient_email=None, preferred_date_or_window="3pm", **kw).error == (
        "patient_email missing"
    )
    assert create_cal_booking(
        patient_email="a@b.c", preferred_date_or_window="soon", **kw
    ).error == ("could not parse preferred slot")


def test_event_type_discovery_failure_skips(offline, monkeypatch, mock_http):
    monkeypatch.setattr(settings, "cal_api_key", "cal_test_key")
    mock_http(lambda r: httpx.Response(404))
    res = fetch_cal_slots(preferred_date_or_window="3pm")
    assert res.skipped and "discovery failed" in res.error
