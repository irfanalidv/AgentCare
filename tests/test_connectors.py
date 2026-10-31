"""Appointment connectors (FHIR over a mock transport, mock backend, factory)."""

from __future__ import annotations

import json

import httpx

from agentcare.connectors import appointments as appt
from agentcare.connectors.appointments import (
    CalAppointmentConnector,
    FHIRAppointmentConnector,
    MockAppointmentConnector,
    get_appointment_connector,
)
from agentcare.settings import settings

BOOK_KW = {
    "patient_name": "Ava",
    "patient_email": "ava@x.com",
    "patient_phone": "+1555",
    "reason": "knee pain",
    "doctor_name": None,
    "doctor_specialty": None,
    "visit_type": "new",
    "summary": None,
    "preferred_date_or_window": "2026-11-02",
    "execution_id": "ex_1",
}

SLOT_BUNDLE = {
    "resourceType": "Bundle",
    "entry": [
        {
            "resource": {
                "resourceType": "Slot",
                "id": "s2",
                "status": "free",
                "start": "2026-11-02T11:00:00Z",
            }
        },
        {
            "resource": {
                "resourceType": "Slot",
                "id": "s1",
                "status": "free",
                "start": "2026-11-02T10:00:00Z",
            }
        },
        {
            "resource": {
                "resourceType": "Slot",
                "id": "busy",
                "status": "busy",
                "start": "2026-11-02T09:00:00Z",
            }
        },
        {"resource": {"resourceType": "Patient", "id": "p"}},
    ],
}


def fhir(handler_map):
    def handler(req: httpx.Request) -> httpx.Response:
        return handler_map[(req.method, req.url.path)](req)

    return handler


def test_fhir_check_slots_picks_earliest_free(mock_http):
    seen = mock_http(fhir({("GET", "/fhir/Slot"): lambda r: httpx.Response(200, json=SLOT_BUNDLE)}))
    conn = FHIRAppointmentConnector(
        base_url="https://ehr.test/fhir/", schedule_id="sch1", auth_token="t"
    )
    res = conn.check_slots(preferred_date_or_window="2026-11-02", execution_id="ex")
    assert res.ok and res.chosen_start_iso == "2026-11-02T10:00:00+00:00"
    assert res.slots_preview == ["2026-11-02T10:00:00+00:00", "2026-11-02T11:00:00+00:00"]
    params = seen[0].url.params
    assert params["schedule"] == "sch1" and params["start"] == "ge2026-11-02T09:00:00+00:00"
    assert seen[0].headers["Authorization"] == "Bearer t"


def test_fhir_book_slot_posts_appointment(mock_http):
    def create(req):
        body = json.loads(req.content)
        assert body["slot"] == [{"reference": "Slot/s1"}]
        assert body["participant"][0]["actor"]["telecom"][0]["value"] == "ava@x.com"
        assert body["end"] == "2026-11-02T10:30:00+00:00"
        return httpx.Response(201, json={"id": "appt_9"})

    mock_http(
        fhir(
            {
                ("GET", "/fhir/Slot"): lambda r: httpx.Response(200, json=SLOT_BUNDLE),
                ("POST", "/fhir/Appointment"): create,
            }
        )
    )
    res = FHIRAppointmentConnector(base_url="https://ehr.test/fhir").book_slot(
        slot_start_iso=None, **BOOK_KW
    )
    assert res.ok and res.booking_id == "appt_9"


def test_fhir_errors_are_reported(mock_http):
    mock_http(lambda r: httpx.Response(503))
    conn = FHIRAppointmentConnector(base_url="https://ehr.test/fhir")
    assert conn.check_slots(preferred_date_or_window=None, execution_id=None).error == (
        "fhir_slot_search_failed:503"
    )
    res = conn.book_slot(slot_start_iso="2026-11-02T10:00:00Z", **BOOK_KW)
    assert res.error == "fhir_appointment_create_failed:503"

    mock_http(lambda r: httpx.Response(200, json={}))
    assert (
        conn.check_slots(preferred_date_or_window=None, execution_id=None).error == "no_free_slots"
    )
    res = conn.book_slot(slot_start_iso="2026-11-02T10:00:00Z", **BOOK_KW)
    assert res.error == "fhir_appointment_missing_id"


def test_fhir_without_base_url_is_skipped(offline):
    conn = FHIRAppointmentConnector()
    assert conn.check_slots(preferred_date_or_window=None, execution_id=None).error == (
        "fhir_base_url_missing"
    )
    assert conn.book_slot(slot_start_iso=None, **BOOK_KW).skipped


def test_iso_helpers():
    assert appt._normalize_start_iso("2026-11-02") == "2026-11-02T09:00:00+00:00"
    assert appt._normalize_start_iso("2026-11-02T10:00:00") == "2026-11-02T10:00:00+00:00"
    assert appt._normalize_start_iso("next week") is None
    assert appt._normalize_start_iso("  ") is None
    assert appt._derive_end_iso("2026-11-02T10:00:00+00:00") == "2026-11-02T10:30:00+00:00"


def test_mock_connector_and_factory(offline, monkeypatch):
    mock = MockAppointmentConnector()
    assert mock.check_slots(preferred_date_or_window=None, execution_id=None).skipped
    assert mock.book_slot(slot_start_iso=None, **BOOK_KW).error == "mock_connector"
    assert isinstance(get_appointment_connector(), MockAppointmentConnector)
    monkeypatch.setattr(settings, "appointment_connector_backend", "fhir")
    assert isinstance(get_appointment_connector(), FHIRAppointmentConnector)
    monkeypatch.setattr(settings, "appointment_connector_backend", "cal")
    conn = get_appointment_connector()
    assert isinstance(conn, CalAppointmentConnector)
    # Without CAL_API_KEY the Cal connector skips instead of calling out.
    assert conn.check_slots(preferred_date_or_window="tomorrow 3pm", execution_id=None).skipped
    assert conn.book_slot(slot_start_iso=None, **BOOK_KW).skipped
