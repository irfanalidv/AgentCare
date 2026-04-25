from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentcare.calendar import parse_preferred_slot
from agentcare.llm import MistralLLM
from agentcare.settings import settings
from agentcare.usecases.deps import FrontdeskDeps, build_frontdesk_deps


def _execution_key(execution: dict[str, Any]) -> str | None:
    return str(execution.get("id") or execution.get("execution_id") or "").strip() or None


def _regex_extract(transcript: str) -> dict[str, str]:
    out: dict[str, str] = {}
    email = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", transcript)
    if email:
        out["customer_email"] = email.group(0)
    phone = re.search(r"\+\d{10,15}", transcript)
    if phone:
        out["customer_phone"] = phone.group(0)
    appt = re.search(r"\b(?:appt|appointment)[-_ ]?id[: ]+([A-Za-z0-9_-]+)\b", transcript, flags=re.I)
    if appt:
        out["appointment_id"] = appt.group(1)
    slot = re.search(
        r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?\b",
        transcript,
    )
    if slot:
        out["slot_start"] = slot.group(0)
    return out


def _clean_person_name(name: str | None) -> str | None:
    if not name:
        return None
    compact = " ".join(str(name).split()).strip()
    if not compact:
        return None
    return compact.title()


def _compose_patient_facing_summary(
    *,
    extracted: dict[str, Any],
    transcript: str,
) -> str | None:
    fallback_parts: list[str] = []
    intent = str(extracted.get("intent") or "").replace("_", " ").strip()
    reason = str(extracted.get("reason") or "").strip()
    slot = str(extracted.get("slot_start") or extracted.get("preferred_date_or_window") or "").strip()
    doctor = str(extracted.get("assigned_doctor_name") or "").strip()
    if intent:
        fallback_parts.append(f"Request type: {intent}.")
    if reason:
        fallback_parts.append(f"Reason: {reason}.")
    if slot:
        fallback_parts.append(f"Preferred/confirmed time: {slot}.")
    if doctor:
        fallback_parts.append(f"Assigned doctor: {doctor}.")
    fallback_summary = " ".join(fallback_parts).strip() or None

    # Optional LLM polish to keep patient-facing communications concise and professional.
    if not settings.mistral_api_key:
        return fallback_summary
    source_text = str(extracted.get("summary") or transcript[:500] or "").strip()
    if not source_text:
        return fallback_summary
    try:
        llm = MistralLLM(api_key=settings.mistral_api_key, model=settings.mistral_model)
        prompt = (
            "Rewrite the following call note as a professional patient-facing summary in 1-2 sentences. "
            "Use plain English, no diagnosis, no assumptions, and keep under 280 characters."
        )
        rewritten = llm.chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": source_text},
            ],
            temperature=0.1,
            max_tokens=120,
        )
        polished = " ".join(str(rewritten).split()).strip()
        polished = polished.strip("\"' ")
        polished = re.sub(r"\s*\(\d+\s*characters?\)\s*$", "", polished, flags=re.I).strip()
        if polished:
            return polished[:280]
    except Exception:
        pass
    return fallback_summary


def _compose_internal_ops_summary(
    *,
    extracted: dict[str, Any],
    transcript: str,
    source: str,
) -> str | None:
    parts: list[str] = []
    if extracted.get("intent"):
        parts.append(f"intent={extracted.get('intent')}")
    if extracted.get("visit_type"):
        parts.append(f"visit_type={extracted.get('visit_type')}")
    if extracted.get("reason"):
        parts.append(f"reason={extracted.get('reason')}")
    if extracted.get("slot_start") or extracted.get("preferred_date_or_window"):
        parts.append(f"slot={extracted.get('slot_start') or extracted.get('preferred_date_or_window')}")
    if extracted.get("assigned_doctor_name"):
        parts.append(
            f"doctor={extracted.get('assigned_doctor_name')} ({extracted.get('assigned_doctor_specialty') or 'general'})"
        )
    if extracted.get("risk_level"):
        parts.append(f"risk={extracted.get('risk_level')}")
    if extracted.get("urgency_level"):
        parts.append(f"urgency={extracted.get('urgency_level')}")
    if extracted.get("policy_reason"):
        parts.append(f"policy={extracted.get('policy_reason')}")
    rag = extracted.get("rag_backfill")
    if isinstance(rag, dict):
        parts.append(f"rag_used={bool(rag.get('used'))}")
    ops_summary = " | ".join([str(p) for p in parts if p]).strip()
    raw_summary = str(extracted.get("summary") or "").strip()
    looks_internal = ("| note=" in raw_summary) or raw_summary.startswith("intent=")
    fallback = raw_summary if (raw_summary and not looks_internal) else str(transcript[:350] or "").strip()
    if ops_summary and fallback:
        return f"{ops_summary} | note={fallback}"[:1200]
    if ops_summary:
        return ops_summary[:1200]
    if fallback:
        return f"source={source} | note={fallback}"[:1200]
    return None


def _is_missing(value: Any) -> bool:
    return value in (None, "", "null")


def _extract_calendar_booking_url(details: Any) -> str | None:
    key_candidates = {"bookingurl", "booking_url", "url", "link"}
    stack: list[Any] = [details]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if str(key).strip().lower() not in key_candidates:
                    continue
                if isinstance(value, str):
                    cleaned = value.strip()
                    if cleaned:
                        return cleaned
            for value in current.values():
                if isinstance(value, (dict, list, tuple)):
                    stack.append(value)
        elif isinstance(current, (list, tuple)):
            for value in current:
                if isinstance(value, (dict, list, tuple)):
                    stack.append(value)
    return None


def _rag_backfill_fields(
    *,
    store: Any,
    execution: dict[str, Any],
    transcript: str,
    extracted: dict[str, Any],
) -> dict[str, Any]:
    if not hasattr(store, "semantic_lookup"):
        return {"used": False, "reason": "semantic_lookup_unavailable"}

    query_parts = [
        transcript[:400] if transcript else "",
        str(extracted.get("customer_name") or ""),
        str(extracted.get("customer_email") or ""),
        str(extracted.get("customer_phone") or ""),
        str(extracted.get("reason") or ""),
        str((execution.get("telephony_data") or {}).get("to_number") or ""),
        str((execution.get("telephony_data") or {}).get("from_number") or ""),
    ]
    query = " ".join([part for part in query_parts if part]).strip()
    if not query:
        return {"used": False, "reason": "empty_query"}

    lookup = store.semantic_lookup(query)
    if not lookup.get("found"):
        return {
            "used": False,
            "reason": lookup.get("reason") or "not_found",
            "engine": lookup.get("engine"),
        }

    customer = lookup.get("customer") or {}
    if not isinstance(customer, dict):
        return {"used": False, "reason": "invalid_customer_shape", "engine": lookup.get("engine")}

    filled: dict[str, Any] = {}
    mapping: dict[str, tuple[str, ...]] = {
        "customer_name": ("name",),
        "customer_email": ("email",),
        "customer_phone": ("phone_e164",),
        "appointment_id": ("last_appointment_id",),
        "slot_start": ("last_slot_start",),
        "summary": ("last_summary",),
        "reason": ("last_summary",),
    }
    for target, source_keys in mapping.items():
        if not _is_missing(extracted.get(target)):
            continue
        value = None
        for source in source_keys:
            source_value = customer.get(source)
            if not _is_missing(source_value):
                value = source_value
                break
        if not _is_missing(value):
            filled[target] = value

    return {
        "used": bool(filled),
        "engine": lookup.get("engine"),
        "customer_id": customer.get("customer_id"),
        "filled_fields": sorted(filled.keys()),
        "filled_values": filled,
    }


def _read_processed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text("utf-8"))
        if isinstance(data, list):
            return {str(x) for x in data}
    except Exception:
        pass
    return set()


def _write_processed(path: Path, values: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(values), indent=2), "utf-8")


@dataclass
class FrontdeskProcessingResult:
    ok: bool
    execution_id: str | None
    deduplicated: bool
    customer_id: str | None
    extracted_data: dict[str, Any]
    cal_slot_check: dict[str, Any] | None
    cal_booking: dict[str, Any] | None
    email_confirmation: dict[str, Any] | None
    analytics_store: dict[str, Any] | None
    error: str | None = None


def process_frontdesk_execution(
    execution: dict[str, Any],
    *,
    source: str,
    automate_actions: bool = True,
    enforce_idempotency: bool = False,
    deps: FrontdeskDeps | None = None,
) -> FrontdeskProcessingResult:
    wired = deps or build_frontdesk_deps()
    store = wired.store
    connector = wired.connector
    ex_key = _execution_key(execution)
    status = str(execution.get("status") or "").strip().lower() or None
    transcript = str(execution.get("transcript") or "")
    extracted = dict(execution.get("extracted_data") or {})

    if enforce_idempotency and ex_key:
        if hasattr(store, "is_execution_processed") and store.is_execution_processed(ex_key):
            return FrontdeskProcessingResult(
                ok=True,
                execution_id=ex_key,
                deduplicated=True,
                customer_id=None,
                extracted_data=extracted,
                cal_slot_check=None,
                cal_booking=None,
                email_confirmation=None,
                analytics_store=None,
            )
        processed_path = Path(settings.processed_executions_path)
        processed = _read_processed(processed_path)
        if ex_key in processed:
            return FrontdeskProcessingResult(
                ok=True,
                execution_id=ex_key,
                deduplicated=True,
                customer_id=None,
                extracted_data=extracted,
                cal_slot_check=None,
                cal_booking=None,
                email_confirmation=None,
                analytics_store=None,
            )

    wired.persist_call_lifecycle_event(
        execution_id=ex_key,
        status=status,
        source=source,
        details={
            "provider": (execution.get("telephony_data") or {}).get("provider"),
            "hangup_reason": (execution.get("telephony_data") or {}).get("hangup_reason"),
            "has_transcript": bool(transcript),
        },
    )

    if transcript:
        extracted.update(_regex_extract(transcript))
        structured = wired.extract_fields(transcript).model_dump()
        mapped = {
            "customer_name": structured.get("patient_name"),
            "customer_phone": structured.get("patient_phone"),
            "customer_email": structured.get("patient_email"),
            "appointment_id": structured.get("appointment_id"),
            "reason": structured.get("reason_for_visit"),
            "summary": structured.get("summary"),
            "intent": structured.get("intent"),
            "visit_type": structured.get("visit_type"),
            "preferred_date_or_window": structured.get("preferred_date_or_window"),
            "follow_up_required": structured.get("follow_up_required"),
        }
        for key, value in mapped.items():
            if value in (None, "", "null"):
                continue
            if not _is_missing(extracted.get(key)):
                continue
            extracted[key] = value
    rag_backfill = _rag_backfill_fields(store=store, execution=execution, transcript=transcript, extracted=extracted)
    if rag_backfill.get("used"):
        extracted.update(rag_backfill.get("filled_values") or {})
    extracted["rag_backfill"] = {k: v for k, v in rag_backfill.items() if k != "filled_values"}

    # Domain-specific post-call analysis (inspired by production wellness/workflow systems).
    health = wired.analyze_healthcare_context(
        transcript=transcript,
        reason=extracted.get("reason"),
        intent=extracted.get("intent"),
    )
    extracted.update(
        {
            "care_category": health.care_category,
            "concern_tags": health.concern_tags,
            "risk_level": health.risk_level,
            "urgency_level": health.urgency_level,
            "follow_up_recommendation": health.follow_up_recommendation,
            "needs_clinical_followup": health.needs_clinical_followup,
        }
    )
    policy = wired.evaluate_frontdesk_policy(intent=extracted.get("intent"), risk_level=extracted.get("risk_level"))
    extracted.update(
        {
            "policy_allow_auto_booking": policy.allow_auto_booking,
            "policy_escalation_required": policy.escalation_required,
            "policy_triage_queue": policy.triage_queue,
            "policy_follow_up_sla_hours": policy.follow_up_sla_hours,
            "policy_reason": policy.reason,
        }
    )
    doctor_assignment = wired.assign_doctor(reason=extracted.get("reason"), intent=extracted.get("intent"))
    extracted.update(
        {
            "assigned_doctor_id": doctor_assignment.doctor_id,
            "assigned_doctor_name": doctor_assignment.doctor_name,
            "assigned_doctor_specialty": doctor_assignment.doctor_specialty,
            "doctor_assignment_reason": doctor_assignment.assignment_reason,
        }
    )
    if extracted.get("customer_name"):
        extracted["customer_name"] = _clean_person_name(str(extracted.get("customer_name")))
    internal_ops_summary = _compose_internal_ops_summary(extracted=extracted, transcript=transcript, source=source)
    if internal_ops_summary:
        extracted["internal_ops_summary"] = internal_ops_summary
    patient_facing_summary = _compose_patient_facing_summary(extracted=extracted, transcript=transcript)
    if patient_facing_summary:
        extracted["patient_facing_summary"] = patient_facing_summary

    phone = (
        extracted.get("customer_phone")
        or (execution.get("telephony_data") or {}).get("to_number")
        or (execution.get("telephony_data") or {}).get("from_number")
    )
    appointment_id = extracted.get("appointment_id")
    slot_start = extracted.get("slot_start") or extracted.get("preferred_date_or_window")
    if slot_start:
        parsed = parse_preferred_slot(str(slot_start), timezone_name=settings.cal_timezone)
        if parsed:
            slot_start = parsed

    slot_check_result: dict[str, Any] | None = None
    cal_result: dict[str, Any] | None = None
    email_result: dict[str, Any] | None = None
    slot_candidate: str | None = None
    should_automate = bool(automate_actions and status == "completed")

    # Guardrail: transcript-extracted appointment IDs are often stale/echoed values.
    # For booking flows, trust existing appointment_id only when it comes from a
    # previously successful connector booking payload.
    if should_automate and extracted.get("intent") in {"new_appointment", "reschedule"} and appointment_id:
        cal_booking = extracted.get("cal_booking") or {}
        trusted_existing_id = bool(
            isinstance(cal_booking, dict)
            and cal_booking.get("ok") is True
            and str(cal_booking.get("booking_id") or "") == str(appointment_id)
        )
        if not trusted_existing_id:
            extracted["preexisting_appointment_id"] = appointment_id
            appointment_id = None

    if should_automate and extracted.get("intent") in {"new_appointment", "reschedule"}:
        slot_check = connector.check_slots(
            preferred_date_or_window=str(extracted.get("preferred_date_or_window") or slot_start or ""),
            execution_id=ex_key,
        )
        slot_check_result = {
            "ok": slot_check.ok,
            "chosen_start_iso": slot_check.chosen_start_iso,
            "slots_count": len(slot_check.slots_preview or []),
            "slots_preview": slot_check.slots_preview or [],
            "error": slot_check.error,
            "skipped": slot_check.skipped,
        }
        slot_candidate = slot_check.chosen_start_iso
        if slot_candidate:
            slot_start = slot_candidate

    auto_booking_allowed = bool(policy.allow_auto_booking)
    if (
        should_automate
        and auto_booking_allowed
        and not appointment_id
        and extracted.get("intent") in {"new_appointment", "reschedule"}
    ):
        if slot_check_result is not None and not slot_candidate:
            cal_result = {
                "ok": False,
                "booking_id": None,
                "start_iso": slot_start,
                "error": slot_check_result.get("error") or "no_available_slots",
                "skipped": True,
            }
        else:
            cal_attempt = connector.book_slot(
                patient_name=extracted.get("customer_name"),
                patient_email=extracted.get("customer_email"),
                patient_phone=phone,
                reason=extracted.get("reason"),
                doctor_name=extracted.get("assigned_doctor_name"),
                doctor_specialty=extracted.get("assigned_doctor_specialty"),
                visit_type=extracted.get("visit_type"),
                summary=extracted.get("internal_ops_summary") or extracted.get("summary"),
                preferred_date_or_window=str(extracted.get("preferred_date_or_window") or slot_start or ""),
                slot_start_iso=slot_candidate or slot_start,
                execution_id=ex_key,
            )
            cal_result = {
                "ok": cal_attempt.ok,
                "booking_id": cal_attempt.booking_id,
                "start_iso": cal_attempt.start_iso,
                "error": cal_attempt.error,
                "skipped": cal_attempt.skipped,
            }
            booking_url = _extract_calendar_booking_url(getattr(cal_attempt, "details", None))
            if booking_url:
                cal_result["calendar_booking_url"] = booking_url
            if cal_attempt.ok and cal_attempt.booking_id:
                appointment_id = cal_attempt.booking_id
            if cal_attempt.start_iso:
                slot_start = cal_attempt.start_iso

    if should_automate and extracted.get("customer_email") and appointment_id and slot_start:
        try:
            email_result = wired.send_confirmation_email(
                to_email=str(extracted.get("customer_email")),
                patient_name=str(extracted.get("customer_name") or "there"),
                appointment_id=str(appointment_id),
                slot_start=str(slot_start),
                reason=str(extracted.get("reason") or ""),
                summary=str(extracted.get("patient_facing_summary") or extracted.get("summary") or transcript[:300]),
                call_duration_sec=execution.get("conversation_time"),
                doctor_name=str(extracted.get("assigned_doctor_name") or ""),
                doctor_specialty=str(extracted.get("assigned_doctor_specialty") or ""),
                clinic_name="AgentCare",
            )
        except Exception as e:
            email_result = {"ok": False, "error": str(e)}
    elif should_automate and extracted.get("customer_email") and slot_start and cal_result is not None:
        if cal_result.get("ok") is False:
            email_result = {
                "ok": False,
                "skipped": True,
                "reason": "booking_failed",
                "error": cal_result.get("error") or "appointment booking did not complete",
                "to_email": extracted.get("customer_email"),
            }

    if appointment_id:
        extracted["appointment_id"] = appointment_id
    if slot_start:
        extracted["slot_start"] = slot_start
    if slot_check_result is not None:
        extracted["cal_slot_check"] = slot_check_result
    if cal_result is not None:
        extracted["cal_booking"] = cal_result
    if not auto_booking_allowed and should_automate:
        extracted["automation_blocked_reason"] = policy.reason
    if email_result is not None:
        extracted["email_confirmation"] = email_result

    customer = store.upsert_from_interaction(
        name=extracted.get("customer_name"),
        email=extracted.get("customer_email"),
        phone_e164=phone,
        summary=extracted.get("internal_ops_summary")
        or extracted.get("summary")
        or (transcript[:300] if transcript else None),
        status=status,
        appointment_id=appointment_id,
        slot_start=slot_start,
        note=f"{source}_execution={ex_key}",
    )
    analytics_result = wired.persist_call_event(
        execution_id=ex_key,
        customer_id=customer.customer_id,
        status=status,
        transcript=transcript or None,
        conversation_time=execution.get("conversation_time"),
        total_cost=execution.get("total_cost"),
        source_phone=(execution.get("telephony_data") or {}).get("from_number"),
        target_phone=(execution.get("telephony_data") or {}).get("to_number"),
        appointment_id=str(appointment_id) if appointment_id else None,
        slot_start=str(slot_start) if slot_start else None,
        intent=extracted.get("intent"),
        follow_up_required=extracted.get("follow_up_required"),
        patient_facing_summary=extracted.get("patient_facing_summary"),
        internal_ops_summary=extracted.get("internal_ops_summary"),
        extracted_data=extracted,
        context_details=execution.get("context_details"),
        telephony_data=execution.get("telephony_data"),
    )

    if enforce_idempotency and ex_key:
        if hasattr(store, "mark_execution_processed"):
            store.mark_execution_processed(ex_key)
        else:
            processed_path = Path(settings.processed_executions_path)
            processed = _read_processed(processed_path)
            processed.add(ex_key)
            _write_processed(processed_path, processed)

    return FrontdeskProcessingResult(
        ok=True,
        execution_id=ex_key,
        deduplicated=False,
        customer_id=customer.customer_id,
        extracted_data=extracted,
        cal_slot_check=slot_check_result,
        cal_booking=cal_result,
        email_confirmation=email_result,
        analytics_store=analytics_result,
    )
