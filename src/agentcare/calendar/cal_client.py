from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re
from typing import Any

import httpx

from agentcare.settings import settings


@dataclass
class CalBookingAttempt:
    ok: bool
    booking_id: str | None = None
    start_iso: str | None = None
    details: dict[str, Any] | None = None
    error: str | None = None
    skipped: bool = False


@dataclass
class CalSlotCheckAttempt:
    ok: bool
    slots: list[str]
    chosen_start_iso: str | None = None
    details: dict[str, Any] | None = None
    error: str | None = None
    skipped: bool = False


def parse_preferred_slot(preferred: str | None, *, timezone_name: str) -> str | None:
    if not preferred:
        return None
    text = preferred.strip()
    if not text:
        return None

    # ISO pass-through.
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(timezone_name))
        return dt.isoformat()
    except Exception:
        pass

    # Heuristic parser for phrases like: "tomorrow at three pm ist"
    t = text.lower()
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz=tz)
    day = now.date()
    m_date = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m_date:
        day = datetime(int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))).date()
    if "tomorrow" in t:
        day = day + timedelta(days=1)

    word_to_hour = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
    }
    hour: int | None = None
    minute = 0

    m_num = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if m_num:
        hour = int(m_num.group(1))
        if m_num.group(2):
            minute = int(m_num.group(2))
        ampm = m_num.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
    else:
        m_24h = re.search(r"\b(?:at\s*)?([01]?\d|2[0-3]):([0-5]\d)\b", t)
        if m_24h:
            hour = int(m_24h.group(1))
            minute = int(m_24h.group(2))
        else:
            m_word = re.search(r"\b(" + "|".join(word_to_hour.keys()) + r")\s*(am|pm)\b", t)
            if m_word:
                hour = word_to_hour[m_word.group(1)]
                ampm = m_word.group(2)
                if ampm == "pm" and hour < 12:
                    hour += 12
                if ampm == "am" and hour == 12:
                    hour = 0

    if hour is None:
        return None

    dt = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
    return dt.isoformat()


def _day_window_from_preferred(preferred_date_or_window: str | None, timezone_name: str) -> tuple[str, str] | None:
    parsed = parse_preferred_slot(preferred_date_or_window, timezone_name=timezone_name)
    if not parsed:
        return None
    dt = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
    day_start = datetime(dt.year, dt.month, dt.day, 0, 0, 0, tzinfo=dt.tzinfo)
    day_end = day_start + timedelta(days=1)
    return day_start.isoformat(), day_end.isoformat()


def _extract_slots(data: Any) -> list[str]:
    """
    Normalize Cal slot responses into a flat ISO list.
    Handles both list and nested map response shapes.
    """
    out: list[str] = []
    if isinstance(data, dict):
        data = data.get("data", data)
    if isinstance(data, dict):
        # Common Cal shape: {"slots": {"2026-...": [{"start":"..."}]}}
        slots_node = data.get("slots", data)
        if isinstance(slots_node, dict):
            for _, day_slots in slots_node.items():
                if isinstance(day_slots, list):
                    for s in day_slots:
                        if isinstance(s, dict):
                            val = s.get("start") or s.get("time") or s.get("dateTime")
                            if isinstance(val, str) and val.strip():
                                out.append(val.strip())
                        elif isinstance(s, str):
                            out.append(s.strip())
        elif isinstance(slots_node, list):
            for s in slots_node:
                if isinstance(s, dict):
                    val = s.get("start") or s.get("time") or s.get("dateTime")
                    if isinstance(val, str) and val.strip():
                        out.append(val.strip())
                elif isinstance(s, str):
                    out.append(s.strip())
    elif isinstance(data, list):
        for s in data:
            if isinstance(s, dict):
                val = s.get("start") or s.get("time") or s.get("dateTime")
                if isinstance(val, str) and val.strip():
                    out.append(val.strip())
            elif isinstance(s, str):
                out.append(s.strip())
    return sorted(list(dict.fromkeys(out)))


def _safe_error_text(value: str, *, limit: int = 300) -> str:
    redacted = re.sub(r"cal_(live|test)_[A-Za-z0-9]+", "cal_***", value or "")
    redacted = re.sub(r"(apiKey=)[^&\\s]+", r"\1***", redacted)
    return redacted[:limit].replace("\n", " ")


def _to_utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_cal_headers(*, api_version: str | None = None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if settings.cal_api_key:
        headers["Authorization"] = f"Bearer {settings.cal_api_key}"
    if api_version:
        headers["cal-api-version"] = api_version
    return headers


def _verify_event_type_id(event_type_id: int) -> bool:
    try:
        res = httpx.get(
            f"https://api.cal.com/v2/event-types/{event_type_id}",
            headers=_build_cal_headers(api_version="2024-06-14"),
            timeout=httpx.Timeout(10.0),
        )
        return res.status_code == 200
    except Exception:
        return False


def _discover_event_type_id() -> int | None:
    try:
        res = httpx.get(
            "https://api.cal.com/v2/event-types",
            params={"limit": 1, "sortCreatedAt": "desc"},
            headers=_build_cal_headers(api_version="2024-06-14"),
            timeout=httpx.Timeout(10.0),
        )
        if res.status_code >= 400:
            return None
        payload = res.json() if res.content else {}
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            return None
        first = rows[0]
        if not isinstance(first, dict):
            return None
        found = first.get("id")
        if found is None:
            return None
        return int(found)
    except Exception:
        return None


def _resolve_event_type_id() -> tuple[int | None, str]:
    configured_raw = getattr(settings, "cal_event_type_id", None)
    if configured_raw not in (None, ""):
        try:
            configured = int(configured_raw)
            if _verify_event_type_id(configured):
                return configured, "configured"
        except Exception:
            pass
    discovered = _discover_event_type_id()
    if discovered is not None:
        return discovered, "discovered"
    return None, "missing_or_invalid"


def _choose_slot(preferred_date_or_window: str | None, slots: list[str], timezone_name: str) -> str | None:
    if not slots:
        return None
    preferred_iso = parse_preferred_slot(preferred_date_or_window, timezone_name=timezone_name)
    if not preferred_iso:
        return slots[0]
    try:
        pref_dt = datetime.fromisoformat(preferred_iso.replace("Z", "+00:00"))
    except Exception:
        return slots[0]

    parsed_slots: list[tuple[datetime, str]] = []
    for s in slots:
        try:
            parsed_slots.append((datetime.fromisoformat(s.replace("Z", "+00:00")), s))
        except Exception:
            continue
    if not parsed_slots:
        return slots[0]
    parsed_slots.sort(key=lambda x: x[0])
    future = [x for x in parsed_slots if x[0] >= pref_dt]
    return (future[0][1] if future else parsed_slots[0][1])


def fetch_cal_slots(
    *,
    preferred_date_or_window: str | None,
    execution_id: str | None = None,
) -> CalSlotCheckAttempt:
    """
    Check available Cal.com slots (best effort) before booking.
    """
    if not settings.cal_api_key:
        return CalSlotCheckAttempt(ok=False, slots=[], skipped=True, error="CAL_API_KEY not configured")
    event_type_id, event_id_source = _resolve_event_type_id()
    if not event_type_id:
        return CalSlotCheckAttempt(ok=False, slots=[], skipped=True, error="CAL_EVENT_TYPE_ID missing/invalid and discovery failed")

    timezone_name = getattr(settings, "cal_timezone", "Asia/Kolkata")
    window = _day_window_from_preferred(preferred_date_or_window, timezone_name)
    if not window:
        return CalSlotCheckAttempt(ok=False, slots=[], skipped=True, error="could not parse preferred day/window")
    start_iso, end_iso = window
    start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    start_utc = _to_utc_z(start_dt)
    end_utc = _to_utc_z(end_dt)

    candidate_requests = [
        (
            "GET",
            "https://api.cal.com/v2/slots",
            {"eventTypeId": event_type_id, "start": start_utc, "end": end_utc, "timeZone": timezone_name},
            _build_cal_headers(api_version="2024-09-04"),
        ),
        (
            "GET",
            "https://api.cal.com/v2/slots",
            {
                "apiKey": settings.cal_api_key,
                "eventTypeId": event_type_id,
                "start": start_utc,
                "end": end_utc,
                "timeZone": timezone_name,
            },
            {"Accept": "application/json", "cal-api-version": "2024-09-04"},
        ),
        (
            "GET",
            "https://api.cal.com/v1/slots",
            {
                "apiKey": settings.cal_api_key,
                "eventTypeId": event_type_id,
                "startTime": start_iso,
                "endTime": end_iso,
                "timeZone": timezone_name,
            },
            {"Accept": "application/json"},
        ),
    ]
    errors: list[str] = []
    with httpx.Client(timeout=httpx.Timeout(20.0)) as client:
        for method, url, params, headers in candidate_requests:
            try:
                res = client.request(method, url, params=params, headers=headers)
                if res.status_code >= 400:
                    snippet = _safe_error_text(res.text or "", limit=200)
                    errors.append(f"{url} => {res.status_code} {snippet}")
                    continue
                payload = res.json()
                slots = _extract_slots(payload)
                chosen = _choose_slot(preferred_date_or_window, slots, timezone_name)
                if not chosen:
                    errors.append(f"{url} => no available slots")
                    continue
                return CalSlotCheckAttempt(
                    ok=True,
                    slots=slots,
                    chosen_start_iso=chosen,
                    details={
                        "window_start": start_iso,
                        "window_end": end_iso,
                        "execution_id": execution_id,
                        "api": url,
                        "event_type_id": event_type_id,
                        "event_type_id_source": event_id_source,
                    },
                )
            except Exception as e:
                errors.append(f"{url} => {e}")

    return CalSlotCheckAttempt(
        ok=False,
        slots=[],
        error="; ".join(errors)[:1000] if errors else "cal slot fetch failed",
    )


def create_cal_booking(
    *,
    patient_name: str | None,
    patient_email: str | None,
    patient_phone: str | None,
    reason: str | None,
    doctor_name: str | None,
    doctor_specialty: str | None,
    visit_type: str | None,
    summary: str | None,
    preferred_date_or_window: str | None,
    slot_start_iso: str | None = None,
    execution_id: str | None = None,
) -> CalBookingAttempt:
    """
    Best-effort Cal.com booking creation.
    Requires CAL_API_KEY and CAL_EVENT_TYPE_ID.
    Uses Cal v1 API for broad compatibility.
    """
    if not settings.cal_api_key:
        return CalBookingAttempt(ok=False, skipped=True, error="CAL_API_KEY not configured")

    event_type_id, event_id_source = _resolve_event_type_id()
    if not event_type_id:
        return CalBookingAttempt(ok=False, skipped=True, error="CAL_EVENT_TYPE_ID missing/invalid and discovery failed")

    if not patient_email:
        return CalBookingAttempt(ok=False, skipped=True, error="patient_email missing")

    timezone_name = getattr(settings, "cal_timezone", "Asia/Kolkata")
    start_iso = slot_start_iso or parse_preferred_slot(preferred_date_or_window, timezone_name=timezone_name)
    if not start_iso:
        return CalBookingAttempt(ok=False, skipped=True, error="could not parse preferred slot")

    start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    start_utc = _to_utc_z(start_dt)
    booking_notes = _compose_booking_notes(
        reason=reason,
        doctor_name=doctor_name,
        doctor_specialty=doctor_specialty,
        visit_type=visit_type,
        summary=summary,
    )
    payload_v2 = {
        "eventTypeId": event_type_id,
        "start": start_utc,
        "attendee": {
            "name": patient_name or "Patient",
            "email": patient_email,
            "timeZone": timezone_name,
            "language": "en",
            "phoneNumber": patient_phone or None,
        },
        "bookingFieldsResponses": {
            "reason": reason or "",
            "notes": booking_notes,
        },
        "metadata": {
            "source": "agentcare",
            "execution_id": execution_id,
            "reason_for_visit": reason or "",
            "doctor_name": doctor_name or "",
            "doctor_specialty": doctor_specialty or "",
            "visit_type": visit_type or "",
            "patient_summary": (summary or "")[:500],
        },
    }
    payload_v1 = {
        "eventTypeId": event_type_id,
        "start": start_iso,
        "timeZone": timezone_name,
        "language": "en",
        "responses": {
            "name": patient_name or "Patient",
            "email": patient_email,
            "location": {"optionValue": "phone", "value": patient_phone or ""},
            "notes": booking_notes,
        },
        "metadata": {
            "source": "agentcare",
            "execution_id": execution_id,
            "reason_for_visit": reason or "",
            "doctor_name": doctor_name or "",
            "doctor_specialty": doctor_specialty or "",
            "visit_type": visit_type or "",
            "patient_summary": (summary or "")[:500],
        },
    }
    candidate_requests = [
        (
            "https://api.cal.com/v2/bookings",
            payload_v2,
            _build_cal_headers(api_version="2024-08-13"),
            None,
        ),
        (
            "https://api.cal.com/v1/bookings",
            payload_v1,
            {"Accept": "application/json"},
            {"apiKey": settings.cal_api_key},
        ),
    ]
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0)) as client:
            errors: list[str] = []
            for url, payload, headers, params in candidate_requests:
                res = client.post(url, params=params, json=payload, headers=headers)
                if res.status_code >= 400:
                    snippet = _safe_error_text(res.text or "", limit=300)
                    errors.append(f"{url} => {res.status_code} {snippet}")
                    continue
                data = res.json()
                booking = data.get("data") if isinstance(data, dict) else {}
                booking_id = None
                if isinstance(booking, dict):
                    booking_id = str(booking.get("uid") or booking.get("id") or "")
                if not booking_id:
                    booking_id = f"cal_pending_{execution_id or 'unknown'}"
                details = data if isinstance(data, dict) else {"raw": data}
                details["event_type_id"] = event_type_id
                details["event_type_id_source"] = event_id_source
                return CalBookingAttempt(ok=True, booking_id=booking_id, start_iso=start_iso, details=details)
        return CalBookingAttempt(
            ok=False,
            start_iso=start_iso,
            error="cal booking failed",
            details={"errors": errors, "event_type_id": event_type_id, "event_type_id_source": event_id_source},
        )
    except Exception as e:
        return CalBookingAttempt(ok=False, start_iso=start_iso, error=str(e))


def _compose_booking_notes(
    *,
    reason: str | None,
    doctor_name: str | None,
    doctor_specialty: str | None,
    visit_type: str | None,
    summary: str | None,
) -> str:
    lines: list[str] = []
    if reason:
        lines.append(f"Reason: {reason}")
    if visit_type:
        lines.append(f"Visit type: {visit_type}")
    if doctor_name:
        if doctor_specialty:
            lines.append(f"Assigned doctor: {doctor_name} ({doctor_specialty})")
        else:
            lines.append(f"Assigned doctor: {doctor_name}")
    if summary:
        lines.append(f"Call summary: {summary}")
    return " | ".join(lines)[:900]
