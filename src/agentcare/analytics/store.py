from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency path
    psycopg = None  # type: ignore[assignment]

from agentcare.settings import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_ready() -> bool:
    if not settings.database_url:
        return False
    if psycopg is None:
        return False
    bad = ("[YOUR-", "YOUR-PASSWORD")
    return not any(x in settings.database_url for x in bad)


def _append_json_fallback(event: dict[str, Any]) -> None:
    path = Path("artifacts/call_events.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]]
    if path.exists():
        try:
            rows = json.loads(path.read_text("utf-8"))
            if not isinstance(rows, list):
                rows = []
        except Exception:
            rows = []
    else:
        rows = []
    execution_id = event.get("execution_id")
    if execution_id:
        # Upsert by execution_id to avoid duplicate noisy rows in local fallback mode.
        replaced = False
        for i, row in enumerate(rows):
            if isinstance(row, dict) and row.get("execution_id") == execution_id:
                merged = dict(row)
                merged.update(event)
                rows[i] = merged
                replaced = True
                break
        if not replaced:
            rows.append(event)
    else:
        rows.append(event)
    path.write_text(json.dumps(rows, indent=2, default=str), "utf-8")


def _normalize_lifecycle_state(status: str | None) -> str:
    s = str(status or "").strip().lower()
    mapping = {
        "queued": "requested",
        "ringing": "ringing",
        "in_progress": "connected",
        "in-progress": "connected",
        "answered": "connected",
        "completed": "completed",
        "failed": "failed",
        "error": "failed",
        "busy": "failed",
        "no_answer": "failed",
        "no-answer": "failed",
        "rescheduled": "delayed",
        "canceled": "cancelled",
        "cancelled": "cancelled",
        "voicemail": "voicemail",
    }
    return mapping.get(s, s or "unknown")


def _append_lifecycle_json(event: dict[str, Any]) -> None:
    path = Path("artifacts/call_lifecycle_events.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]]
    if path.exists():
        try:
            rows = json.loads(path.read_text("utf-8"))
            if not isinstance(rows, list):
                rows = []
        except Exception:
            rows = []
    else:
        rows = []

    dedupe_key = (
        str(event.get("execution_id") or ""),
        str(event.get("state") or ""),
        str(event.get("source") or ""),
    )
    if dedupe_key[0]:
        for r in rows:
            if (
                isinstance(r, dict)
                and str(r.get("execution_id") or "") == dedupe_key[0]
                and str(r.get("state") or "") == dedupe_key[1]
                and str(r.get("source") or "") == dedupe_key[2]
            ):
                return
    rows.append(event)
    rows.sort(key=lambda x: str(x.get("ts") or ""))
    path.write_text(json.dumps(rows, indent=2, default=str), "utf-8")


def persist_call_lifecycle_event(
    *,
    execution_id: str | None,
    status: str | None,
    source: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not execution_id:
        return {"stored": "ignored", "reason": "missing_execution_id"}
    state = _normalize_lifecycle_state(status)
    event = {
        "execution_id": execution_id,
        "status": status,
        "state": state,
        "source": source,
        "details": details or {},
        "ts": _now_iso(),
    }

    if not _db_ready():
        _append_lifecycle_json(event)
        return {"stored": "json_fallback", "state": state}

    try:
        with psycopg.connect(settings.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS call_lifecycle_events (
                        event_id BIGSERIAL PRIMARY KEY,
                        execution_id TEXT NOT NULL,
                        status TEXT NULL,
                        state TEXT NOT NULL,
                        source TEXT NOT NULL,
                        details JSONB NOT NULL DEFAULT '{}'::jsonb,
                        ts TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                    CREATE INDEX IF NOT EXISTS idx_call_lifecycle_exec_ts
                    ON call_lifecycle_events (execution_id, ts DESC);
                    """
                )
                cur.execute(
                    """
                    INSERT INTO call_lifecycle_events (
                        execution_id, status, state, source, details, ts
                    ) VALUES (%s,%s,%s,%s,%s::jsonb,now())
                    """,
                    (execution_id, status, state, source, json.dumps(details or {})),
                )
                conn.commit()
        return {"stored": "postgres", "state": state}
    except Exception as e:
        _append_lifecycle_json(event)
        return {"stored": "json_fallback", "state": state, "db_error": str(e)}


def get_call_lifecycle(execution_id: str) -> dict[str, Any]:
    execution_id = str(execution_id or "").strip()
    if not execution_id:
        return {"execution_id": execution_id, "events": [], "current_state": "unknown"}

    if _db_ready():
        try:
            with psycopg.connect(settings.database_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT execution_id, status, state, source, details, ts
                        FROM call_lifecycle_events
                        WHERE execution_id = %s
                        ORDER BY ts ASC
                        """,
                        (execution_id,),
                    )
                    rows = cur.fetchall()
            events = [
                {
                    "execution_id": r[0],
                    "status": r[1],
                    "state": r[2],
                    "source": r[3],
                    "details": r[4] or {},
                    "ts": str(r[5]),
                }
                for r in rows
            ]
            current_state = events[-1]["state"] if events else "unknown"
            return {"execution_id": execution_id, "events": events, "current_state": current_state}
        except Exception:
            pass

    path = Path("artifacts/call_lifecycle_events.json")
    if not path.exists():
        return {"execution_id": execution_id, "events": [], "current_state": "unknown"}
    try:
        rows = json.loads(path.read_text("utf-8"))
        if not isinstance(rows, list):
            rows = []
    except Exception:
        rows = []
    events = [r for r in rows if isinstance(r, dict) and str(r.get("execution_id") or "") == execution_id]
    events.sort(key=lambda x: str(x.get("ts") or ""))
    current_state = str(events[-1].get("state") or "unknown") if events else "unknown"
    return {"execution_id": execution_id, "events": events, "current_state": current_state}


def persist_call_event(
    *,
    execution_id: str | None,
    customer_id: str | None,
    status: str | None,
    transcript: str | None,
    conversation_time: float | None,
    total_cost: float | None = None,
    source_phone: str | None = None,
    target_phone: str | None = None,
    appointment_id: str | None = None,
    slot_start: str | None = None,
    intent: str | None = None,
    follow_up_required: bool | None = None,
    patient_facing_summary: str | None = None,
    internal_ops_summary: str | None = None,
    extracted_data: dict[str, Any] | None = None,
    context_details: dict[str, Any] | None = None,
    telephony_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "execution_id": execution_id,
        "customer_id": customer_id,
        "status": status,
        "transcript": transcript,
        "conversation_time": conversation_time,
        "total_cost": total_cost,
        "source_phone": source_phone,
        "target_phone": target_phone,
        "appointment_id": appointment_id,
        "slot_start": slot_start,
        "intent": intent,
        "follow_up_required": follow_up_required,
        "patient_facing_summary": patient_facing_summary,
        "internal_ops_summary": internal_ops_summary,
        "extracted_data": extracted_data or {},
        "context_details": context_details or {},
        "telephony_data": telephony_data or {},
    }

    if not _db_ready():
        _append_json_fallback(event)
        return {"stored": "json_fallback"}

    try:
        with psycopg.connect(settings.database_url) as conn:
            with conn.cursor() as cur:
                # Migration-safe for existing deployments.
                cur.execute(
                    """
                    ALTER TABLE IF EXISTS call_executions
                    ADD COLUMN IF NOT EXISTS patient_facing_summary TEXT NULL;
                    ALTER TABLE IF EXISTS call_executions
                    ADD COLUMN IF NOT EXISTS internal_ops_summary TEXT NULL;
                    """
                )
                cur.execute(
                    """
                    INSERT INTO call_executions (
                        execution_id, customer_id, status, transcript, conversation_time, total_cost,
                        source_phone, target_phone, appointment_id, slot_start, intent, follow_up_required,
                        patient_facing_summary, internal_ops_summary,
                        extracted_data, context_details, telephony_data, created_at, updated_at
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,now(),now()
                    )
                    ON CONFLICT (execution_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        transcript = COALESCE(EXCLUDED.transcript, call_executions.transcript),
                        conversation_time = COALESCE(EXCLUDED.conversation_time, call_executions.conversation_time),
                        total_cost = COALESCE(EXCLUDED.total_cost, call_executions.total_cost),
                        source_phone = COALESCE(EXCLUDED.source_phone, call_executions.source_phone),
                        target_phone = COALESCE(EXCLUDED.target_phone, call_executions.target_phone),
                        appointment_id = COALESCE(EXCLUDED.appointment_id, call_executions.appointment_id),
                        slot_start = COALESCE(EXCLUDED.slot_start, call_executions.slot_start),
                        intent = COALESCE(EXCLUDED.intent, call_executions.intent),
                        follow_up_required = COALESCE(EXCLUDED.follow_up_required, call_executions.follow_up_required),
                        patient_facing_summary = COALESCE(
                            EXCLUDED.patient_facing_summary,
                            call_executions.patient_facing_summary
                        ),
                        internal_ops_summary = COALESCE(
                            EXCLUDED.internal_ops_summary,
                            call_executions.internal_ops_summary
                        ),
                        extracted_data = call_executions.extracted_data || EXCLUDED.extracted_data,
                        context_details = call_executions.context_details || EXCLUDED.context_details,
                        telephony_data = call_executions.telephony_data || EXCLUDED.telephony_data,
                        updated_at = now()
                    """,
                    (
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
                        follow_up_required,
                        patient_facing_summary,
                        internal_ops_summary,
                        json.dumps(extracted_data or {}),
                        json.dumps(context_details or {}),
                        json.dumps(telephony_data or {}),
                    ),
                )
                # Keep appointment timeline table in sync if appointment keys exist.
                if appointment_id:
                    cur.execute(
                        """
                        INSERT INTO appointments (
                            appointment_id, customer_id, slot_start, status, source_execution_id, created_at, updated_at
                        ) VALUES (%s,%s,%s,%s,%s,now(),now())
                        ON CONFLICT (appointment_id) DO UPDATE
                        SET customer_id = COALESCE(EXCLUDED.customer_id, appointments.customer_id),
                            slot_start = COALESCE(EXCLUDED.slot_start, appointments.slot_start),
                            status = COALESCE(EXCLUDED.status, appointments.status),
                            source_execution_id = COALESCE(EXCLUDED.source_execution_id, appointments.source_execution_id),
                            updated_at = now()
                        """,
                        (appointment_id, customer_id, slot_start, "booked", execution_id),
                    )
                conn.commit()
        return {"stored": "postgres"}
    except Exception as e:
        _append_json_fallback(event)
        return {"stored": "json_fallback", "db_error": str(e)}

