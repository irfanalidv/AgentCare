"""Confirmation email rendering and Resend sending (Resend SDK faked)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentcare.email import resend_client
from agentcare.email.resend_client import _html_confirmation, send_confirmation_email
from agentcare.settings import settings

KW = {
    "to_email": "ava@x.com",
    "patient_name": "ava patel",
    "appointment_id": "bk_1",
    "slot_start": "2026-11-02T04:30:00Z",
    "reason": "knee pain",
    "summary": "Booked a knee consult.",
    "call_duration_sec": 95,
    "doctor_name": "Dr. Rahul Verma",
    "doctor_specialty": "Orthopedics",
}


def test_html_escapes_transcript_derived_fields():
    html = _html_confirmation(
        patient_name="<b>Eve</b>",
        appointment_id="bk_1",
        slot_start="not-a-date",
        reason='<a href="https://evil.test">click</a>',
        summary="<script>alert(1)</script>",
        call_duration_sec=None,
        doctor_name=None,
        doctor_specialty=None,
        clinic_name="AgentCare",
    )
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert '<a href="https://evil.test">' not in html
    assert "&lt;B&gt;Eve&lt;/B&gt;" in html  # name is title-cased, then escaped
    assert "not-a-date" in html


def test_slot_is_rendered_in_clinic_timezone(monkeypatch):
    monkeypatch.setattr(settings, "cal_timezone", "Asia/Kolkata")
    assert resend_client._format_slot_start("2026-11-02T04:30:00Z") == (
        "Monday, 02 Nov 2026 at 10:00 AM (IST)"
    )
    assert resend_client._format_slot_start("") == "Not available"


def test_send_requires_key(offline):
    with pytest.raises(ValueError, match="RESEND_API_KEY"):
        send_confirmation_email(**KW)


def test_send_and_unverified_domain_fallback(offline, monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "agentcare_email_from", "Clinic <care@clinic.test>")
    sent = []

    def send(params):
        sent.append(params)
        if params["from"] != resend_client.RESEND_DEV_FROM:
            raise RuntimeError("The clinic.test domain is not verified")
        return SimpleNamespace(id="em_1")

    fake = SimpleNamespace(api_key=None, Emails=SimpleNamespace(send=send, SendParams=dict))
    monkeypatch.setattr(resend_client, "resend", fake)
    out = send_confirmation_email(**KW)
    assert out["id"] == "em_1" and out["from_fallback_used"] is True
    assert [p["from"] for p in sent] == ["Clinic <care@clinic.test>", resend_client.RESEND_DEV_FROM]
    assert "Ava Patel" in sent[-1]["html"]
