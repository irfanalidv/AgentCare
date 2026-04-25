from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency path
    psycopg = None  # type: ignore[assignment]

from agentcare.doctor import DoctorProfile, load_doctor_schema
from agentcare.settings import settings

DOCTOR_DIRECTORY: list[DoctorProfile] = load_doctor_schema()


def _db_ready() -> bool:
    if not settings.database_url:
        return False
    if psycopg is None:
        return False
    bad = ("[YOUR-", "YOUR-PASSWORD")
    return not any(x in settings.database_url for x in bad)


def _db_connect():
    # Keep dashboard responsive under transient DB slowness.
    return psycopg.connect(
        settings.database_url,
        connect_timeout=3,
        options="-c statement_timeout=5000",
    )


def _load_call_events() -> list[dict[str, Any]]:
    """
    DB-first source of truth for dashboard projections.
    Falls back to artifact JSON when DB is unavailable/slow.
    """
    if _db_ready():
        try:
            with _db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            execution_id,
                            customer_id,
                            status,
                            transcript,
                            conversation_time,
                            total_cost,
                            source_phone,
                            target_phone,
                            appointment_id,
                            slot_start,
                            intent,
                            extracted_data,
                            context_details,
                            telephony_data,
                            created_at,
                            updated_at
                        FROM call_executions
                        ORDER BY updated_at DESC
                        LIMIT 2000
                        """
                    )
                    rows = cur.fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                out.append(
                    {
                        "execution_id": r[0],
                        "customer_id": r[1],
                        "status": r[2],
                        "transcript": r[3],
                        "conversation_time": float(r[4] or 0.0) if r[4] is not None else None,
                        "total_cost": float(r[5] or 0.0) if r[5] is not None else None,
                        "source_phone": r[6],
                        "target_phone": r[7],
                        "appointment_id": r[8],
                        "slot_start": r[9],
                        "intent": r[10],
                        "extracted_data": r[11] or {},
                        "context_details": r[12] or {},
                        "telephony_data": r[13] or {},
                        "created_at": str(r[14]) if r[14] else None,
                        "updated_at": str(r[15]) if r[15] else None,
                    }
                )
            if out:
                return out
        except Exception:
            pass
    return _load_json_rows(Path("artifacts/call_events.json"))


def _load_customers() -> list[dict[str, Any]]:
    if _db_ready():
        try:
            with _db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT customer_id, phone_e164, name, email, interaction_count
                        FROM customer_profiles
                        ORDER BY updated_at DESC
                        LIMIT 5000
                        """
                    )
                    rows = cur.fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                out.append(
                    {
                        "customer_id": r[0],
                        "phone_e164": r[1],
                        "name": r[2],
                        "email": r[3],
                        "interaction_count": int(r[4] or 0),
                    }
                )
            if out:
                return out
        except Exception:
            pass
    return _load_json_rows(Path(settings.customer_store_path))


def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _is_synthetic_event(row: dict[str, Any]) -> bool:
    execution_id = str(row.get("execution_id") or "").strip()
    if not execution_id:
        return False
    if execution_id.startswith(("exec_demo_", "exec_ops_", "exec_test_", "exec_extract_", "exec_")):
        return True
    return re.fullmatch(r"[0-9a-fA-F-]{36}", execution_id) is None


def _doctor_for_reason(reason: str | None) -> DoctorProfile:
    if not reason:
        return DOCTOR_DIRECTORY[0]
    r = reason.lower()
    if any(k in r for k in ("anxiety", "depression", "panic", "sleep", "therapy", "stress")):
        return DOCTOR_DIRECTORY[5]
    if any(k in r for k in ("chest", "bp", "heart", "cardio", "palpitation")):
        return DOCTOR_DIRECTORY[1]
    if any(k in r for k in ("skin", "rash", "acne", "eczema", "allergy")):
        return DOCTOR_DIRECTORY[2]
    if any(k in r for k in ("knee", "back", "joint", "fracture", "pain")):
        return DOCTOR_DIRECTORY[3]
    if any(k in r for k in ("ear", "nose", "throat", "sinus", "hearing")):
        return DOCTOR_DIRECTORY[4]
    return DOCTOR_DIRECTORY[0]


def _compact_purpose(reason: str | None, intent: str | None) -> str | None:
    if reason and reason.strip():
        compact = " ".join(reason.split())
        if len(compact) > 90:
            compact = compact[:87].rstrip() + "..."
        return compact
    if intent and intent.strip():
        label_map = {
            "new_appointment": "New appointment request",
            "reschedule": "Reschedule appointment",
            "cancel": "Cancel appointment",
            "appointment_status": "Appointment status query",
            "care_coordination": "Care coordination support",
        }
        return label_map.get(intent, intent.replace("_", " ").strip().capitalize())
    return None


def _preferred_patient_name(ev: dict[str, Any], ex: dict[str, Any], cust: dict[str, Any] | None) -> str | None:
    context_name = (
        ((ev.get("context_details") or {}).get("recipient_data") or {}).get("customer_name")
        or ((ev.get("context_details") or {}).get("recipient_data") or {}).get("name")
    )
    extracted_name = str(ex.get("customer_name") or "").strip()
    if extracted_name:
        return extracted_name
    return context_name or (cust or {}).get("name")


def _is_generic_purpose(purpose: str | None) -> bool:
    if not purpose:
        return True
    p = purpose.strip().lower()
    return p in {"other"}


def _unscheduled_score(row: dict[str, Any]) -> int:
    score = 0
    if row.get("slot_start"):
        score += 40
    if row.get("reason_for_visit"):
        score += 20
    if row.get("intent") == "new_appointment":
        score += 15
    if not _is_generic_purpose(row.get("purpose")):
        score += 20
    if row.get("patient_email"):
        score += 5
    return score


def _enrich_from_transcript(ev: dict[str, Any], ex: dict[str, Any]) -> dict[str, Any]:
    transcript = ev.get("transcript")
    if not transcript:
        return ex
    hangup_reason = str(((ev.get("telephony_data") or {}).get("hangup_reason")) or "").lower()
    if "voicemail" in hangup_reason:
        return ex
    t = str(transcript)
    email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", t)
    phone_match = re.search(r"\+[1-9]\d{7,14}\b", t)
    lower_t = t.lower()
    inferred_intent = None
    if "reschedule" in lower_t:
        inferred_intent = "reschedule"
    elif "cancel" in lower_t:
        inferred_intent = "cancel"
    elif "appointment status" in lower_t or "status of appointment" in lower_t:
        inferred_intent = "appointment_status"
    elif "book" in lower_t or "new appointment" in lower_t:
        inferred_intent = "new_appointment"
    merged = dict(ex)
    if email_match and not merged.get("customer_email"):
        merged["customer_email"] = email_match.group(0)
    if phone_match and not merged.get("customer_phone"):
        merged["customer_phone"] = phone_match.group(0)
    if inferred_intent and not merged.get("intent"):
        merged["intent"] = inferred_intent
    if merged.get("preferred_date_or_window") and not merged.get("slot_start"):
        merged["slot_start"] = merged.get("preferred_date_or_window")
    return merged


def _event_dt(ev: dict[str, Any]) -> datetime:
    raw = str(ev.get("updated_at") or ev.get("created_at") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def _extract_first_value(payload: Any, candidate_keys: tuple[str, ...]) -> Any:
    if isinstance(payload, dict):
        for key in candidate_keys:
            value = payload.get(key)
            if value not in (None, ""):
                return value
        for value in payload.values():
            found = _extract_first_value(value, candidate_keys)
            if found not in (None, ""):
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_first_value(item, candidate_keys)
            if found not in (None, ""):
                return found
    return None


def _extract_first_str(payload: Any, candidate_keys: tuple[str, ...]) -> str | None:
    value = _extract_first_value(payload, candidate_keys)
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _extract_first_bool(payload: Any, candidate_keys: tuple[str, ...]) -> bool | None:
    value = _extract_first_value(payload, candidate_keys)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "ok", "sent", "success", "booked"}:
            return True
        if normalized in {"false", "no", "0", "failed", "error"}:
            return False
    return None


def _extract_calendar_booking_url(extracted_data: dict[str, Any]) -> str | None:
    cal_booking = extracted_data.get("cal_booking")
    url_keys = ("calendar_booking_url", "booking_url", "url", "link")
    return (
        _extract_first_str(cal_booking, url_keys)
        or _extract_first_str(extracted_data.get("details"), url_keys)
        or _extract_first_str(extracted_data, url_keys)
    )


def _extract_email_delivery_status(email_confirmation: Any) -> str:
    if email_confirmation in (None, "", {}):
        return "unknown"
    ok_flag = _extract_first_bool(email_confirmation, ("ok",))
    if ok_flag is True:
        return "sent"
    if ok_flag is False:
        return "failed"
    if _extract_first_str(email_confirmation, ("id", "message_id", "delivery_id", "email_delivery_id")):
        return "sent"
    status = (_extract_first_str(email_confirmation, ("status", "delivery_status")) or "").lower()
    if status in {"sent", "delivered", "success", "ok"}:
        return "sent"
    if status in {"failed", "error", "bounced", "rejected"}:
        return "failed"
    return "unknown"


def _calendar_booking_status(cal_booking: Any) -> str | None:
    ok_flag = _extract_first_bool(cal_booking, ("ok",))
    if ok_flag is True:
        return "booked"
    if ok_flag is False:
        return "failed"
    if cal_booking in (None, "", {}):
        return None
    return "unknown"


def _trusted_appointment_id(ev: dict[str, Any], ex: dict[str, Any]) -> str | None:
    cal_booking = ex.get("cal_booking")
    calendar_ok = _extract_first_bool(cal_booking, ("ok",))
    event_appointment_id = str(ev.get("appointment_id") or "").strip() or None
    if calendar_ok is True:
        return (
            _extract_first_str(cal_booking, ("calendar_booking_id", "booking_id", "id", "appointment_id"))
            or event_appointment_id
            or _extract_first_str(ex, ("appointment_id",))
        )
    return event_appointment_id


def _email_delivery_status(email_confirmation: Any, calendar_status: str | None) -> str:
    if email_confirmation in (None, "", {}) and calendar_status == "failed":
        return "not_sent"
    return _extract_email_delivery_status(email_confirmation)


def _email_delivery_error(email_confirmation: Any, calendar_status: str | None) -> str | None:
    error = _extract_first_str(email_confirmation, ("error", "error_message", "message", "reason"))
    if error:
        return error
    if email_confirmation in (None, "", {}) and calendar_status == "failed":
        return "booking_failed"
    return None


def _is_voicemail_event(ev: dict[str, Any]) -> bool:
    transcript = str(ev.get("transcript") or "").lower()
    hangup_reason = str(((ev.get("telephony_data") or {}).get("hangup_reason")) or "").lower()
    return "voicemail" in hangup_reason or "forwarded to voice mail" in transcript


def _case_event_score(ev: dict[str, Any], ex: dict[str, Any]) -> int:
    score = 0
    if ex.get("appointment_id"):
        score += 40
    if ev.get("slot_start") or ex.get("slot_start") or ex.get("preferred_date_or_window"):
        score += 25
    if ex.get("reason"):
        score += 20
    if ex.get("intent") == "new_appointment":
        score += 12
    if ex.get("customer_email"):
        score += 8
    if _is_voicemail_event(ev):
        score -= 20
    return score


def _customer_segment(cust: dict[str, Any] | None) -> str:
    if not cust:
        return "unknown"
    n = int(cust.get("interaction_count") or 0)
    if n <= 1:
        return "new"
    if n == 2:
        return "returning"
    return "repeat"


def build_appointment_summary(*, limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    events = _load_call_events()
    customers = _load_customers()
    by_phone = {str(c.get("phone_e164")): c for c in customers if c.get("phone_e164")}
    by_customer_id = {str(c.get("customer_id")): c for c in customers if c.get("customer_id")}

    latest_by_execution: dict[str, dict[str, Any]] = {}
    for ev in events:
        if _is_synthetic_event(ev):
            continue
        exec_id = str(ev.get("execution_id") or "")
        if exec_id:
            latest_by_execution[exec_id] = ev
        else:
            latest_by_execution[f"no_exec_{id(ev)}"] = ev

    rows: list[dict[str, Any]] = []
    for _exec_id, ev in latest_by_execution.items():
        ex = _enrich_from_transcript(ev, ev.get("extracted_data") or {})
        cal_booking = ex.get("cal_booking")
        email_confirmation = ex.get("email_confirmation")
        calendar_status = _calendar_booking_status(cal_booking)
        event_email_sent_at = str(ev.get("updated_at") or ev.get("created_at") or "") or None
        payload_email_sent_at = _extract_first_str(
            email_confirmation,
            ("sent_at", "sentAt", "created_at", "createdAt", "timestamp"),
        )
        appt_id = _trusted_appointment_id(ev, ex)
        transcript_appt_id = _extract_first_str(ex, ("preexisting_appointment_id", "appointment_id"))
        cid = str(ev.get("customer_id") or "")
        phone = ev.get("target_phone") or (ev.get("telephony_data") or {}).get("to_number") or ex.get("customer_phone")
        cust = by_customer_id.get(cid) or by_phone.get(str(phone))
        reason = ex.get("reason") or ex.get("reason_for_visit")
        doctor = _doctor_for_reason(reason)
        purpose = _compact_purpose(reason, ev.get("intent") or ex.get("intent"))
        base_row = {
            "appointment_id": appt_id,
            "transcript_appointment_id": transcript_appt_id if transcript_appt_id != appt_id else None,
            "status": "booking_failed"
            if calendar_status == "failed"
            else ((ev.get("status") or "booked") if appt_id else "needs_scheduling"),
            "slot_start": ev.get("slot_start") or ex.get("slot_start") or ex.get("preferred_date_or_window"),
            "patient_name": _preferred_patient_name(ev, ex, cust),
            "patient_phone": phone,
            "patient_email": ex.get("customer_email") or (cust or {}).get("email"),
            "calendar_booking_url": _extract_calendar_booking_url(ex),
            "calendar_booking_id": (
                _extract_first_str(cal_booking, ("calendar_booking_id", "booking_id", "id", "appointment_id"))
                or _extract_first_str(ex.get("details"), ("calendar_booking_id", "booking_id", "id", "appointment_id"))
                or _extract_first_str(ex, ("calendar_booking_id", "booking_id"))
            ),
            "calendar_booking_status": calendar_status,
            "email_delivery_status": _email_delivery_status(email_confirmation, calendar_status),
            "email_delivery_error": _email_delivery_error(email_confirmation, calendar_status),
            "email_delivery_id": _extract_first_str(
                email_confirmation,
                ("email_delivery_id", "delivery_id", "message_id", "id"),
            ),
            "email_to": _extract_first_str(email_confirmation, ("to", "email", "recipient", "to_email")),
            "email_subject": _extract_first_str(email_confirmation, ("subject", "email_subject")),
            "email_sent_at": payload_email_sent_at or event_email_sent_at,
            "intent": ev.get("intent") or ex.get("intent"),
            "visit_type": ex.get("visit_type"),
            "customer_segment": _customer_segment(cust),
            "reason_for_visit": reason,
            "purpose": purpose,
            "summary": ex.get("summary"),
            "assigned_doctor_name": doctor.name,
            "assigned_doctor_specialty": doctor.specialty,
            "assigned_doctor_id": doctor.doctor_id,
            "source_execution_id": ev.get("execution_id"),
            "_created_at": str(ev.get("updated_at") or ev.get("created_at") or ""),
        }
        rows.append(base_row)

    latest_unscheduled_by_exec: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("status") == "needs_scheduling":
            exec_id = str(r.get("source_execution_id") or "")
            latest_unscheduled_by_exec[exec_id or f"no_exec_{id(r)}"] = r

    unscheduled = list(latest_unscheduled_by_exec.values())
    scheduled = [r for r in rows if r.get("status") != "needs_scheduling"]
    best_unscheduled_by_phone: dict[str, dict[str, Any]] = {}
    for r in unscheduled:
        key = str(r.get("patient_phone") or r.get("source_execution_id") or "")
        if key not in best_unscheduled_by_phone:
            best_unscheduled_by_phone[key] = r
            continue
        cur = best_unscheduled_by_phone[key]
        cur_score = (_unscheduled_score(cur), str(cur.get("_created_at") or ""))
        new_score = (_unscheduled_score(r), str(r.get("_created_at") or ""))
        if new_score > cur_score:
            best_unscheduled_by_phone[key] = r

    rows = scheduled + list(best_unscheduled_by_phone.values())
    for r in rows:
        r.pop("_created_at", None)
    rows = list(reversed(rows))[:limit]
    return {"rows": rows, "doctor_directory": [d.model_dump() for d in DOCTOR_DIRECTORY]}


def build_cases_queue(*, limit: int = 100) -> dict[str, Any]:
    events = [ev for ev in _load_call_events() if not _is_synthetic_event(ev)]
    customers = _load_customers()
    by_phone = {str(c.get("phone_e164")): c for c in customers if c.get("phone_e164")}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        ex = _enrich_from_transcript(ev, ev.get("extracted_data") or {})
        phone = ev.get("target_phone") or (ev.get("telephony_data") or {}).get("to_number") or ex.get("customer_phone")
        if not phone:
            continue
        grouped.setdefault(str(phone), []).append({"event": ev, "ex": ex})

    rows: list[dict[str, Any]] = []
    for phone, items in grouped.items():
        items.sort(key=lambda x: _event_dt(x["event"]))
        latest = items[-1]
        best = max(items, key=lambda x: (_case_event_score(x["event"], x["ex"]), _event_dt(x["event"])))
        cust = by_phone.get(phone)
        best_ex = best["ex"]
        latest_ev = latest["event"]
        appointment_ids = sorted(
            {
                appt_id
                for x in items
                if (appt_id := _trusted_appointment_id(x["event"], x["ex"]))
            }
        )
        booking_failed = any(_calendar_booking_status(x["ex"].get("cal_booking")) == "failed" for x in items)
        slots = sorted(
            {
                str(x["event"].get("slot_start") or x["ex"].get("slot_start") or x["ex"].get("preferred_date_or_window"))
                for x in items
                if (x["event"].get("slot_start") or x["ex"].get("slot_start") or x["ex"].get("preferred_date_or_window"))
            }
        )
        purposes = sorted({str(x["ex"].get("reason")) for x in items if x["ex"].get("reason")})
        intent = latest["ex"].get("intent") or latest_ev.get("intent")
        reason = best_ex.get("reason")
        doctor = _doctor_for_reason(reason)
        risk_level = best_ex.get("risk_level") or "low"
        slot_conflict = len(slots) > 1
        purpose_conflict = len(purposes) > 1
        appt_conflict = len(appointment_ids) > 1
        has_conflict = slot_conflict or purpose_conflict or appt_conflict
        if booking_failed:
            action = "human_review_booking_failed"
        elif has_conflict:
            action = "human_review_conflict"
        elif risk_level == "high":
            action = "urgent_clinical_triage"
        elif appointment_ids:
            action = "appointment_confirmed"
        elif _is_voicemail_event(latest_ev):
            action = "retry_or_callback"
        elif not (best_ex.get("customer_email") or (cust or {}).get("email")):
            action = "collect_email"
        elif slots and reason:
            action = "book_appointment"
        else:
            action = "capture_missing_details"

        rows.append(
            {
                "patient_name": _preferred_patient_name(best["event"], best_ex, cust),
                "patient_phone": phone,
                "patient_email": best_ex.get("customer_email") or (cust or {}).get("email"),
                "customer_segment": _customer_segment(cust),
                "latest_status": latest_ev.get("status"),
                "intent": intent,
                "purpose": _compact_purpose(reason, intent),
                "care_category": best_ex.get("care_category"),
                "risk_level": risk_level,
                "urgency_level": best_ex.get("urgency_level") or "routine",
                "slot_start": best["event"].get("slot_start") or best_ex.get("slot_start") or best_ex.get("preferred_date_or_window"),
                "appointment_id": appointment_ids[0] if len(appointment_ids) == 1 else None,
                "assigned_doctor_id": doctor.doctor_id,
                "assigned_doctor_name": doctor.name,
                "assigned_doctor_specialty": doctor.specialty,
                "conflicts": {
                    "has_conflict": has_conflict,
                    "slot_conflict": slot_conflict,
                    "purpose_conflict": purpose_conflict,
                    "appointment_conflict": appt_conflict,
                    "booking_failed": booking_failed,
                },
                "recommended_action": action,
                "last_execution_id": latest_ev.get("execution_id"),
                "last_updated_at": str(latest_ev.get("updated_at") or latest_ev.get("created_at") or ""),
            }
        )

    rows.sort(key=lambda r: r.get("last_updated_at") or "", reverse=True)
    rows = rows[: max(1, min(limit, 500))]
    summary = {
        "total_cases": len(rows),
        "needs_human_review": sum(
            1
            for r in rows
            if r["recommended_action"] in {"human_review_conflict", "human_review_booking_failed"}
        ),
        "booking_failed": sum(1 for r in rows if r["recommended_action"] == "human_review_booking_failed"),
        "urgent_triage": sum(1 for r in rows if r["recommended_action"] == "urgent_clinical_triage"),
        "needs_email": sum(1 for r in rows if r["recommended_action"] == "collect_email"),
        "ready_to_book": sum(1 for r in rows if r["recommended_action"] == "book_appointment"),
        "confirmed": sum(1 for r in rows if r["recommended_action"] == "appointment_confirmed"),
    }
    return {"rows": rows, "summary": summary}
