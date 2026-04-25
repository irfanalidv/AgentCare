from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agentcare.analytics import (
    build_appointment_summary,
    build_cases_queue,
    get_call_detail,
    get_call_detail_fallback,
    get_call_lifecycle,
    persist_call_lifecycle_event,
)
from agentcare.bolna import BolnaClient
from agentcare.bolna.errors import BolnaAuthError, BolnaRequestError
from agentcare.customer import get_customer_store
from agentcare.doctor import DoctorProfile, load_doctor_schema
from agentcare.extraction import extract_conversation_fields
from agentcare.settings import settings
from agentcare.usecases import process_agentcare_execution
from services.dashboard.wellness_routes import router as wellness_router


app = FastAPI(title="AgentCare Dashboard", version="0.2.0")
app.include_router(wellness_router)
_processing_execution_ids: set[str] = set()
_processing_lock = threading.Lock()
_dashboard_boot_ts = datetime.now(timezone.utc).isoformat()
_recent_exec_cache: dict[str, Any] = {"rows": [], "ts": 0.0}
_appointments_cache: dict[str, Any] = {"payload": None, "ts": 0.0}
_cases_cache: dict[str, Any] = {"payload": None, "ts": 0.0}
_async_call_requests: dict[str, dict[str, Any]] = {}
_async_call_lock = threading.Lock()
_async_call_state_path = Path("artifacts/async_call_requests.json")

_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/dashboard/version")
def dashboard_version() -> dict[str, Any]:
    return {"version": _dashboard_boot_ts}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    html = (_static_dir / "index.html").read_text("utf-8")
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


class CallNowRequest(BaseModel):
    phone_number: str
    customer_name: str | None = None
    agent_id: str | None = None
    from_phone_number: str | None = None
    scheduled_at: str | None = None
    bypass_call_guardrails: bool | None = None
    user_data: dict[str, Any] | None = None
    wait_for_outcome: bool | None = True
    fire_and_forget: bool | None = False


DOCTOR_DIRECTORY: list[DoctorProfile] = load_doctor_schema()


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


def _status_from_local_event(execution_id: str) -> dict[str, Any] | None:
    rows = _load_json_rows(Path("artifacts/call_events.json"))
    for row in reversed(rows):
        if str(row.get("execution_id") or "") != execution_id:
            continue
        status = str(row.get("status") or "unknown").lower()
        return {
            "execution_id": execution_id,
            "status": status,
            "terminal": _is_terminal_execution_status(status),
            "telephony_data": row.get("telephony_data") or {},
            "error_message": row.get("error_message"),
            "updated_at": row.get("updated_at") or row.get("created_at"),
            "processing_triggered": False,
            "source": "local_event_fallback",
        }
    return None


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
        # Keep purpose short and valuable in the UI.
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
    # Prefer caller metadata name from telephony context over noisy transcript extraction.
    context_name = (
        ((ev.get("context_details") or {}).get("recipient_data") or {}).get("customer_name")
        or ((ev.get("context_details") or {}).get("recipient_data") or {}).get("name")
    )
    return context_name or ex.get("customer_name") or (cust or {}).get("name")


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
    """
    Transcript-first enrichment: prefer LLM extracted datapoints from transcript.
    Keeps existing keys only when transcript extraction cannot provide them.
    """
    transcript = ev.get("transcript")
    if not transcript:
        return ex
    hangup_reason = str(((ev.get("telephony_data") or {}).get("hangup_reason")) or "").lower()
    if "voicemail" in hangup_reason:
        # Avoid low-signal extraction from voicemail transcripts.
        return ex
    structured = extract_conversation_fields(str(transcript)).model_dump()
    merged = dict(ex)
    llm_map = {
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
    for k, v in llm_map.items():
        if v not in (None, "", "null"):
            merged[k] = v
    if merged.get("preferred_date_or_window") and not merged.get("slot_start"):
        merged["slot_start"] = merged.get("preferred_date_or_window")
    return merged


def _event_dt(ev: dict[str, Any]) -> datetime:
    raw = str(ev.get("updated_at") or ev.get("created_at") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


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


def _require_bolna() -> tuple[str, str]:
    api_key = settings.bolna_api_key
    agent_id = settings.bolna_agent_id
    if not api_key:
        raise HTTPException(status_code=400, detail="BOLNA_API_KEY is not configured")
    if not agent_id:
        raise HTTPException(status_code=400, detail="BOLNA_AGENT_ID is not configured")
    return api_key, agent_id


def _is_valid_e164(phone_number: str) -> bool:
    # Strict E.164: + and 8-15 digits, first digit non-zero.
    return re.fullmatch(r"\+[1-9]\d{7,14}", phone_number) is not None


def _resolve_customer_name(phone_number: str, explicit_name: str | None) -> str | None:
    if explicit_name and explicit_name.strip():
        return explicit_name.strip()
    try:
        store = get_customer_store()
        existing = store.find_exact(phone_e164=phone_number)
        if existing and existing.name and existing.name.strip():
            return existing.name.strip()
    except Exception:
        # Keep call flow resilient even if memory backend is unavailable.
        pass
    return None


def _is_terminal_execution_status(status: str | None) -> bool:
    if not status:
        return False
    s = status.lower()
    return s in {
        "completed",
        "failed",
        "error",
        "no_answer",
        "busy",
        "canceled",
        "cancelled",
        "ended",
        "voicemail",
        "rescheduled",
    }


def _trigger_execution_processing_async(execution_payload: dict[str, Any]) -> bool:
    execution_id = str(execution_payload.get("id") or execution_payload.get("execution_id") or "").strip()
    if not execution_id:
        return False
    with _processing_lock:
        if execution_id in _processing_execution_ids:
            return False
        _processing_execution_ids.add(execution_id)

    def _runner() -> None:
        try:
            process_agentcare_execution(
                execution_payload,
                source="dashboard_status_terminal",
                automate_actions=True,
                enforce_idempotency=True,
            )
        finally:
            with _processing_lock:
                _processing_execution_ids.discard(execution_id)

    threading.Thread(target=_runner, daemon=True).start()
    return True


def _compose_call_detail_from_execution(payload: dict[str, Any]) -> dict[str, Any]:
    execution_id = str(payload.get("id") or payload.get("execution_id") or "")
    status = str(payload.get("status") or "").lower()
    transcript = str(payload.get("transcript") or "").strip()
    extracted = payload.get("extracted_data") or {}
    if not isinstance(extracted, dict):
        extracted = {}
    try:
        if transcript and not extracted:
            extracted = extract_conversation_fields(transcript).model_dump()
    except Exception:
        extracted = extracted or {}
    patient_summary = (
        str(payload.get("patient_facing_summary") or extracted.get("patient_facing_summary") or extracted.get("summary") or "").strip()
    )
    ops_summary = (
        str(payload.get("internal_ops_summary") or extracted.get("internal_ops_summary") or "").strip()
    )
    if not patient_summary and transcript:
        patient_summary = transcript[:280]
    if not ops_summary:
        reason = str(extracted.get("reason") or extracted.get("reason_for_visit") or "").strip()
        intent = str(extracted.get("intent") or payload.get("intent") or "").strip()
        appt = str(payload.get("appointment_id") or extracted.get("appointment_id") or "").strip()
        ops_parts = [
            f"status={status or 'unknown'}",
            f"intent={intent}" if intent else "",
            f"appointment={appt}" if appt else "",
            f"reason={reason}" if reason else "",
        ]
        ops_summary = " | ".join([p for p in ops_parts if p])
    return {
        "execution_id": execution_id,
        "status": status,
        "appointment_id": payload.get("appointment_id") or extracted.get("appointment_id"),
        "patient_facing_summary": patient_summary or "Detail pending from provider.",
        "internal_ops_summary": ops_summary or "Detail pending from provider.",
        "extracted_data": extracted,
    }


def _watch_execution_until_terminal(
    *,
    api_key: str,
    execution_id: str,
    request_id: str | None = None,
    timeout_s: int = 240,
) -> None:
    start = time.time()
    processing_kicked = False
    try:
        with BolnaClient(api_key=api_key, base_url=settings.bolna_base_url, timeout_s=10.0) as client:
            while (time.time() - start) < timeout_s:
                ex = client.get_execution(execution_id=execution_id).model_dump()
                status = str(ex.get("status") or "").lower()
                has_transcript = bool(str(ex.get("transcript") or "").strip())
                persist_call_lifecycle_event(
                    execution_id=execution_id,
                    status=status,
                    source="dashboard_async_watcher",
                    details={
                        "provider": ((ex.get("telephony_data") or {}).get("provider")),
                        "hangup_reason": ((ex.get("telephony_data") or {}).get("hangup_reason")),
                    },
                )
                if request_id:
                    _set_async_call_request(
                        request_id,
                        execution_id=execution_id,
                        status=status or "queued",
                        error=None,
                    )
                # If transcript is available, start downstream processing even when
                # provider status is slow to transition out of "queued".
                if has_transcript and not processing_kicked:
                    _trigger_execution_processing_async(ex)
                    processing_kicked = True
                    if request_id and status == "queued":
                        _set_async_call_request(request_id, status="processing")
                if _is_terminal_execution_status(status):
                    if status == "completed":
                        _trigger_execution_processing_async(ex)
                    elif request_id and not processing_kicked:
                        _set_async_call_request(request_id, status=status)
                    return
                time.sleep(2)
        if request_id and not processing_kicked:
            _set_async_call_request(request_id, status="provider_delay")
    except Exception as e:
        if request_id:
            _set_async_call_request(request_id, status="failed", error=str(e))


def _run_with_timeout(fn, timeout_s: float, **kwargs: Any) -> Any:
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, **kwargs)
    try:
        return fut.result(timeout=timeout_s)
    finally:
        # Do not wait for hung DB work; keep endpoint responsive.
        ex.shutdown(wait=False, cancel_futures=True)


def _set_async_call_request(request_id: str, **updates: Any) -> None:
    with _async_call_lock:
        _async_call_state_path.parent.mkdir(parents=True, exist_ok=True)
        persisted: dict[str, Any] = {}
        if _async_call_state_path.exists():
            try:
                payload = json.loads(_async_call_state_path.read_text("utf-8"))
                if isinstance(payload, dict):
                    persisted = payload
            except Exception:
                persisted = {}
        # Merge with in-memory view for current process continuity.
        current = dict(persisted.get(request_id) or _async_call_requests.get(request_id) or {})
        current.update(updates)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        _async_call_requests[request_id] = current
        persisted[request_id] = current
        tmp = _async_call_state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(persisted, indent=2, default=str), "utf-8")
        tmp.replace(_async_call_state_path)


def _get_async_call_request(request_id: str) -> dict[str, Any] | None:
    with _async_call_lock:
        # Check local memory first (fast path).
        if request_id in _async_call_requests:
            return dict(_async_call_requests[request_id])
        if not _async_call_state_path.exists():
            return None
        try:
            payload = json.loads(_async_call_state_path.read_text("utf-8"))
            if isinstance(payload, dict):
                state = payload.get(request_id)
                if isinstance(state, dict):
                    _async_call_requests[request_id] = state
                    return dict(state)
        except Exception:
            return None
        return None


def _build_appointments_json_fallback(limit: int) -> dict[str, Any]:
    prev_db_url = settings.database_url
    try:
        settings.database_url = None
        payload = build_appointment_summary(limit=limit)
        payload["source"] = "json_fallback"
        return payload
    finally:
        settings.database_url = prev_db_url


def _build_cases_json_fallback(limit: int) -> dict[str, Any]:
    prev_db_url = settings.database_url
    try:
        settings.database_url = None
        payload = build_cases_queue(limit=limit)
        payload["source"] = "json_fallback"
        return payload
    finally:
        settings.database_url = prev_db_url


@app.get("/api/workflow/status")
def workflow_status() -> dict[str, Any]:
    targets = {
        "llm_gateway": "http://localhost:8010/healthz",
        "mock_ehr": "http://localhost:8020/healthz",
        "webhooks": "http://localhost:8030/healthz",
        "analytics": "http://localhost:8040/healthz",
    }
    checks: dict[str, Any] = {}
    with httpx.Client(timeout=httpx.Timeout(4.0)) as client:
        for name, url in targets.items():
            try:
                res = client.get(url)
                checks[name] = {"ok": res.status_code == 200, "status_code": res.status_code}
            except Exception as e:
                checks[name] = {"ok": False, "error": str(e)}
    return {
        "ok": all(v.get("ok") for v in checks.values()),
        "checks": checks,
        "bolna_ready": bool(settings.bolna_api_key and settings.bolna_agent_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/call")
def call_now(req: CallNowRequest) -> dict[str, Any]:
    api_key, default_agent_id = _require_bolna()
    phone = req.phone_number.strip()
    if not _is_valid_e164(phone):
        raise HTTPException(
            status_code=400,
            detail="Invalid phone number. Use strict E.164 format like +14155552671.",
        )
    agent_id = req.agent_id or default_agent_id
    user_data = dict(req.user_data or {})
    # Dashboard "Call Now" should prioritize immediate dialing.
    bypass_guardrails = True if req.bypass_call_guardrails is None else req.bypass_call_guardrails
    if req.fire_and_forget:
        explicit_name = (req.customer_name or "").strip()
        if explicit_name and "customer_name" not in user_data:
            user_data["customer_name"] = explicit_name
        request_id = f"callreq_{int(time.time() * 1000)}"
        _set_async_call_request(
            request_id,
            status="queued",
            execution_id=None,
            error=None,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        def _runner() -> None:
            try:
                with BolnaClient(api_key=api_key, base_url=settings.bolna_base_url, timeout_s=30.0) as client:
                    result = client.make_call(
                        agent_id=agent_id,
                        recipient_phone_number=phone,
                        from_phone_number=req.from_phone_number,
                        scheduled_at=req.scheduled_at,
                        user_data=user_data or None,
                        bypass_call_guardrails=bypass_guardrails,
                    )
                    payload = result.model_dump()
                    _set_async_call_request(
                        request_id,
                        status=str(payload.get("status") or "queued").lower(),
                        execution_id=payload.get("execution_id"),
                        error=None,
                    )
                    execution_id = str(payload.get("execution_id") or "").strip()
                    persist_call_lifecycle_event(
                        execution_id=execution_id or payload.get("execution_id"),
                        status=payload.get("status"),
                        source="dashboard_api_async",
                        details={"phase": "call_created", "request_id": request_id},
                    )
                    if execution_id:
                        _watch_execution_until_terminal(
                            api_key=api_key,
                            execution_id=execution_id,
                            request_id=request_id,
                        )
            except Exception as e:
                # Keep API response fast; detailed failure is visible in provider logs/status polling.
                _set_async_call_request(request_id, status="failed", error=str(e))

        threading.Thread(target=_runner, daemon=True).start()
        return {
            "request_id": request_id,
            "execution_id": "-",
            "status": "queued",
            "effective_status": "queued",
            "outcome_hint": "queued_async",
            "next_action": "refresh_executions_and_poll_status",
        }
    resolved_name = _resolve_customer_name(req.phone_number, req.customer_name)
    if resolved_name and "customer_name" not in user_data:
        user_data["customer_name"] = resolved_name
    try:
        with BolnaClient(api_key=api_key, base_url=settings.bolna_base_url) as client:
            result = client.make_call(
                agent_id=agent_id,
                recipient_phone_number=phone,
                from_phone_number=req.from_phone_number,
                scheduled_at=req.scheduled_at,
                user_data=user_data or None,
                bypass_call_guardrails=bypass_guardrails,
            )
            payload = result.model_dump()
            execution_id = payload.get("execution_id")
            if not execution_id or req.wait_for_outcome is False:
                persist_call_lifecycle_event(
                    execution_id=execution_id,
                    status=payload.get("status"),
                    source="dashboard_api",
                    details={"phase": "call_created"},
                )
                payload["effective_status"] = payload.get("status")
                payload["outcome_hint"] = "queued"
                return payload

            # Poll briefly so UI gets practical status beyond initial "queued".
            persist_call_lifecycle_event(
                execution_id=execution_id,
                status=payload.get("status"),
                source="dashboard_api",
                details={"phase": "call_created"},
            )
            latest: dict[str, Any] | None = None
            for _ in range(8):  # ~16s max
                time.sleep(2)
                ex = client.get_execution(execution_id=execution_id).model_dump()
                latest = ex
                status = str(ex.get("status") or "").lower()
                persist_call_lifecycle_event(
                    execution_id=execution_id,
                    status=status,
                    source="dashboard_poll",
                    details={
                        "provider": ((ex.get("telephony_data") or {}).get("provider")),
                        "hangup_reason": ((ex.get("telephony_data") or {}).get("hangup_reason")),
                    },
                )
                if _is_terminal_execution_status(status):
                    break

            effective_status = (
                str((latest or {}).get("status") or payload.get("status") or "queued").lower()
            )
            payload["effective_status"] = effective_status
            payload["latest_execution"] = latest

            if effective_status == "rescheduled":
                payload["outcome_hint"] = "provider_or_guardrail_delay"
                payload["next_action"] = "retry_call_or_check_telephony_config"
            elif effective_status == "completed":
                payload["outcome_hint"] = "connected"
                payload["next_action"] = "refresh_appointments_and_cases"
            elif effective_status in {"no_answer", "busy", "failed", "error"}:
                payload["outcome_hint"] = "not_connected"
                payload["next_action"] = "retry_later_or_trigger_callback"
            else:
                payload["outcome_hint"] = "pending"
                payload["next_action"] = "continue_polling_execution_status"

            return payload
    except BolnaAuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except BolnaRequestError as e:
        detail = e.details if e.details is not None else str(e)
        raise HTTPException(status_code=e.status_code or 400, detail=detail) from e


@app.get("/api/call/request/{request_id}")
def call_request_status(request_id: str) -> dict[str, Any]:
    rid = str(request_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="request_id is required")
    payload = _get_async_call_request(rid) or {}
    if not payload:
        raise HTTPException(status_code=404, detail="request_id not found")
    return payload


@app.get("/api/executions/recent")
def recent_executions(limit: int = 20) -> dict[str, Any]:
    api_key, agent_id = _require_bolna()
    limit = max(1, min(limit, 100))
    now_ts = time.time()
    if _recent_exec_cache["rows"] and (now_ts - float(_recent_exec_cache["ts"])) < 8.0:
        return {"rows": _recent_exec_cache["rows"][:limit], "source": "cache"}
    try:
        with BolnaClient(api_key=api_key, base_url=settings.bolna_base_url, timeout_s=8.0) as client:
            items = client.get_all_executions(agent_id=agent_id, page_size=min(30, limit), max_pages=1)
    except BolnaAuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except BolnaRequestError as e:
        if _recent_exec_cache["rows"]:
            return {"rows": _recent_exec_cache["rows"][:limit], "source": "cache_stale"}
        detail = e.details if e.details is not None else str(e)
        raise HTTPException(status_code=e.status_code or 400, detail=detail) from e
    except Exception:
        if _recent_exec_cache["rows"]:
            return {"rows": _recent_exec_cache["rows"][:limit], "source": "cache_stale"}
        return {"rows": [], "source": "degraded"}
    rows = []
    for item in items[:limit]:
        telephony = item.telephony_data or {}
        rows.append(
            {
                "execution_id": item.id or item.execution_id,
                "status": item.status,
                "to_number": telephony.get("to_number"),
                "from_number": telephony.get("from_number"),
                "conversation_time": item.conversation_time,
                "total_cost": item.total_cost,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
        )
    _recent_exec_cache["rows"] = rows
    _recent_exec_cache["ts"] = now_ts
    return {"rows": rows, "source": "live"}


@app.get("/api/call/status/{execution_id}")
def call_status(execution_id: str) -> dict[str, Any]:
    api_key, _agent_id = _require_bolna()
    local_terminal = _status_from_local_event(execution_id)
    if local_terminal and bool(local_terminal.get("terminal")):
        return local_terminal
    try:
        def _fetch_provider_execution() -> dict[str, Any]:
            with BolnaClient(api_key=api_key, base_url=settings.bolna_base_url, timeout_s=6.0) as client:
                return client.get_execution(execution_id=execution_id).model_dump()

        payload = _run_with_timeout(_fetch_provider_execution, timeout_s=8.0)
        status = str(payload.get("status") or "").lower()
        persist_call_lifecycle_event(
            execution_id=execution_id,
            status=status,
            source="dashboard_status",
            details={
                "provider": ((payload.get("telephony_data") or {}).get("provider")),
                "hangup_reason": ((payload.get("telephony_data") or {}).get("hangup_reason")),
            },
        )
        terminal = _is_terminal_execution_status(status)
        processing_triggered = bool(terminal and status == "completed" and _trigger_execution_processing_async(payload))
        return {
            "execution_id": execution_id,
            "status": status,
            "terminal": terminal,
            "telephony_data": payload.get("telephony_data") or {},
            "error_message": payload.get("error_message"),
            "updated_at": payload.get("updated_at"),
            "processing_triggered": processing_triggered,
            "source": "provider_live",
        }
    except FuturesTimeoutError:
        fallback = _status_from_local_event(execution_id)
        if fallback:
            return fallback
        return {
            "execution_id": execution_id,
            "status": "queued",
            "terminal": False,
            "telephony_data": {},
            "error_message": "provider_timeout",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "processing_triggered": False,
            "source": "provider_timeout_fallback",
        }
    except BolnaAuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except BolnaRequestError as e:
        detail = e.details if e.details is not None else str(e)
        raise HTTPException(status_code=e.status_code or 400, detail=detail) from e
    except Exception:
        fallback = _status_from_local_event(execution_id)
        if fallback:
            return fallback
        return {
            "execution_id": execution_id,
            "status": "unknown",
            "terminal": False,
            "telephony_data": {},
            "error_message": "status_unavailable",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "processing_triggered": False,
            "source": "error_fallback",
        }


@app.get("/api/call/lifecycle/{execution_id}")
def call_lifecycle(execution_id: str) -> dict[str, Any]:
    return get_call_lifecycle(execution_id)


@app.get("/api/call/detail/{execution_id}")
def call_detail(execution_id: str) -> dict[str, Any]:
    eid = str(execution_id or "").strip()
    if not eid:
        return {"ok": False, "error": "execution_id is required"}
    try:
        local = get_call_detail(eid)
        if local.get("ok") and local.get("row"):
            return {"ok": True, "row": local["row"], "source": "local_processed"}
    except Exception:
        # Keep detail usable when the configured DB is temporarily unavailable.
        pass
    fallback = get_call_detail_fallback(eid)
    if fallback:
        return {"ok": True, "row": fallback, "source": "local_fallback"}
    api_key, _agent_id = _require_bolna()
    try:
        with BolnaClient(api_key=api_key, base_url=settings.bolna_base_url, timeout_s=6.0) as client:
            ex = client.get_execution(execution_id=eid)
            row = _compose_call_detail_from_execution(ex.model_dump())
            return {"ok": True, "row": row, "source": "provider_live"}
    except Exception as e:
        # graceful fallback shape for UI
        return {
            "ok": False,
            "error": "provider_timeout",
            "detail": str(e),
            "row": {
                "execution_id": eid,
                "status": "unknown",
                "appointment_id": None,
                "patient_facing_summary": "Call detail unavailable from provider.",
                "internal_ops_summary": "Call detail unavailable from provider.",
                "extracted_data": {},
            },
            "source": "provider_fallback",
        }


@app.get("/api/appointments/summary")
def appointment_summary(limit: int = 50) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    now_ts = time.time()
    if _appointments_cache["payload"] and (now_ts - float(_appointments_cache["ts"])) < 8.0:
        cached = dict(_appointments_cache["payload"])
        cached["rows"] = (cached.get("rows") or [])[:limit]
        cached["source"] = "cache"
        return cached
    try:
        payload = _run_with_timeout(build_appointment_summary, timeout_s=12.0, limit=limit)
        _appointments_cache["payload"] = payload
        _appointments_cache["ts"] = now_ts
        payload["source"] = "live"
        return payload
    except FuturesTimeoutError:
        try:
            payload = _build_appointments_json_fallback(limit)
            _appointments_cache["payload"] = payload
            _appointments_cache["ts"] = now_ts
            payload["source"] = payload.get("source") or "json_fallback_timeout"
            return payload
        except Exception:
            if _appointments_cache["payload"]:
                cached = dict(_appointments_cache["payload"])
                cached["rows"] = (cached.get("rows") or [])[:limit]
                cached["source"] = "cache_stale_timeout"
                return cached
            raise
    except Exception:
        try:
            payload = _build_appointments_json_fallback(limit)
            _appointments_cache["payload"] = payload
            _appointments_cache["ts"] = now_ts
            payload["source"] = payload.get("source") or "json_fallback_error"
            return payload
        except Exception:
            if _appointments_cache["payload"]:
                cached = dict(_appointments_cache["payload"])
                cached["rows"] = (cached.get("rows") or [])[:limit]
                cached["source"] = "cache_stale"
                return cached
            raise


@app.get("/api/doctors/schema")
def doctors_schema() -> dict[str, Any]:
    return {"rows": [d.model_dump() for d in DOCTOR_DIRECTORY]}


@app.get("/api/cases/queue")
def cases_queue(limit: int = 100) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    now_ts = time.time()
    if _cases_cache["payload"] and (now_ts - float(_cases_cache["ts"])) < 8.0:
        cached = dict(_cases_cache["payload"])
        cached["rows"] = (cached.get("rows") or [])[:limit]
        cached["source"] = "cache"
        return cached
    try:
        payload = _run_with_timeout(build_cases_queue, timeout_s=12.0, limit=limit)
        _cases_cache["payload"] = payload
        _cases_cache["ts"] = now_ts
        payload["source"] = "live"
        return payload
    except FuturesTimeoutError:
        try:
            payload = _build_cases_json_fallback(limit)
            _cases_cache["payload"] = payload
            _cases_cache["ts"] = now_ts
            payload["source"] = payload.get("source") or "json_fallback_timeout"
            return payload
        except Exception:
            if _cases_cache["payload"]:
                cached = dict(_cases_cache["payload"])
                cached["rows"] = (cached.get("rows") or [])[:limit]
                cached["source"] = "cache_stale_timeout"
                return cached
            raise
    except Exception:
        try:
            payload = _build_cases_json_fallback(limit)
            _cases_cache["payload"] = payload
            _cases_cache["ts"] = now_ts
            payload["source"] = payload.get("source") or "json_fallback_error"
            return payload
        except Exception:
            if _cases_cache["payload"]:
                cached = dict(_cases_cache["payload"])
                cached["rows"] = (cached.get("rows") or [])[:limit]
                cached["source"] = "cache_stale"
                return cached
            raise

