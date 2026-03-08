"""Send post-call confirmation emails via Resend."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

try:
    import resend
except Exception:  # pragma: no cover - optional dependency path
    resend = None  # type: ignore[assignment]

from agentcare.settings import settings

RESEND_DEV_FROM = "AgentCare <onboarding@resend.dev>"


def _html_confirmation(
    *,
    patient_name: str,
    appointment_id: str,
    slot_start: str,
    reason: str | None,
    summary: str | None,
    call_duration_sec: float | None,
    doctor_name: str | None,
    doctor_specialty: str | None,
    clinic_name: str,
) -> str:
    summary_block = (
        f"""
        <tr>
          <td style="padding: 8px 0; color: #4b5563; vertical-align: top; width: 180px;">Call summary</td>
          <td style="padding: 8px 0; color: #111827;">{summary}</td>
        </tr>
        """.strip()
        if summary
        else ""
    )
    duration_block = (
        f"""
        <tr>
          <td style="padding: 8px 0; color: #4b5563; vertical-align: top;">Call duration</td>
          <td style="padding: 8px 0; color: #111827;">{int(call_duration_sec or 0)} seconds</td>
        </tr>
        """.strip()
        if call_duration_sec
        else ""
    )
    reason_block = (
        f"""
        <tr>
          <td style="padding: 8px 0; color: #4b5563; vertical-align: top;">Reason for visit</td>
          <td style="padding: 8px 0; color: #111827;">{reason}</td>
        </tr>
        """.strip()
        if reason
        else ""
    )
    doctor_block = (
        f"""
        <tr>
          <td style="padding: 8px 0; color: #4b5563; vertical-align: top;">Assigned doctor</td>
          <td style="padding: 8px 0; color: #111827;">{doctor_name}{f" ({doctor_specialty})" if doctor_specialty else ""}</td>
        </tr>
        """.strip()
        if doctor_name
        else ""
    )
    patient_display = " ".join((patient_name or "there").split()).title()
    formatted_slot = _format_slot_start(slot_start)
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Appointment Confirmation</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #f3f4f6; margin: 0; padding: 24px;">
  <table role="presentation" style="max-width: 640px; margin: 0 auto; width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden;">
    <tr>
      <td style="padding: 20px 24px; background: #0f172a; color: #f9fafb;">
        <div style="font-size: 20px; font-weight: 700;">Appointment Confirmed</div>
        <div style="font-size: 13px; margin-top: 4px; color: #cbd5e1;">{clinic_name}</div>
      </td>
    </tr>
    <tr>
      <td style="padding: 24px;">
        <p style="margin: 0 0 14px 0; color: #111827;">Hi {patient_display},</p>
        <p style="margin: 0 0 18px 0; color: #111827;">Your appointment is scheduled. Please keep this confirmation for your records.</p>
        <table role="presentation" style="width: 100%; border-collapse: collapse;">
          <tr>
            <td style="padding: 8px 0; color: #4b5563; vertical-align: top; width: 180px;">Confirmation ID</td>
            <td style="padding: 8px 0; color: #111827; font-weight: 600;">{appointment_id}</td>
          </tr>
          <tr>
            <td style="padding: 8px 0; color: #4b5563; vertical-align: top;">Date & time</td>
            <td style="padding: 8px 0; color: #111827;">{formatted_slot}</td>
          </tr>
          {doctor_block}
          {reason_block}
          {summary_block}
          {duration_block}
        </table>
        <p style="margin: 18px 0 6px 0; color: #111827;">If you need to reschedule or update details, reply to this email or contact the clinic support line.</p>
        <p style="margin: 0; color: #6b7280;">— AgentCare</p>
      </td>
    </tr>
  </table>
</body>
</html>
""".strip()


def _format_slot_start(slot_start: str) -> str:
    raw = (slot_start or "").strip()
    if not raw:
        return "Not available"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        tz = ZoneInfo(settings.cal_timezone)
        local = dt.astimezone(tz)
        return local.strftime("%A, %d %b %Y at %I:%M %p (%Z)")
    except Exception:
        return raw


def send_confirmation_email(
    *,
    to_email: str,
    patient_name: str = "there",
    appointment_id: str,
    slot_start: str,
    reason: str | None = None,
    summary: str | None = None,
    call_duration_sec: float | None = None,
    doctor_name: str | None = None,
    doctor_specialty: str | None = None,
    clinic_name: str = "AgentCare",
    subject: str | None = None,
) -> dict[str, Any]:
    """
    Send email confirmation via Resend.

    Requires RESEND_API_KEY in env. Resend uses onboarding@resend.dev for testing
    by default; for production, verify your domain and set AGENTCARE_EMAIL_FROM.
    """
    if not settings.resend_api_key:
        raise ValueError("RESEND_API_KEY (or resent_API) not configured")
    if resend is None:
        raise ValueError("Email extras not installed. Install with: pip install 'agentcare[email]'")

    resend.api_key = settings.resend_api_key

    html = _html_confirmation(
        patient_name=patient_name,
        appointment_id=appointment_id,
        slot_start=slot_start,
        reason=reason,
        summary=summary,
        call_duration_sec=call_duration_sec,
        doctor_name=doctor_name,
        doctor_specialty=doctor_specialty,
        clinic_name=clinic_name,
    )

    subj = subject or f"Appointment confirmed – {appointment_id}"

    preferred_from = settings.agentcare_email_from or RESEND_DEV_FROM

    def _utc_iso8601_now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _send(from_value: str) -> dict[str, Any]:
        params: resend.Emails.SendParams = {
            "from": from_value,
            "to": [to_email],
            "subject": subj,
            "html": html,
        }
        email = resend.Emails.send(params)
        return {
            "id": getattr(email, "id", None),
            "to": to_email,
            "subject": subj,
            "from": from_value,
            "sent_at": _utc_iso8601_now(),
        }

    try:
        return _send(preferred_from)
    except Exception as e:
        # In dev/test, users often keep a non-verified sender (e.g., gmail).
        # Auto-retry using Resend's onboarding sender so webhook flows remain smooth.
        msg = str(e).lower()
        needs_fallback = ("domain is not verified" in msg) or ("verify your domain" in msg)
        if needs_fallback and preferred_from != RESEND_DEV_FROM:
            fallback_result = _send(RESEND_DEV_FROM)
            fallback_result["from_fallback_used"] = True
            return fallback_result
        raise
