from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from agentcare.settings import settings


def _connect():
    if not settings.database_url or "[YOUR-" in settings.database_url or "YOUR-PASSWORD" in settings.database_url:
        raise ValueError("DATABASE_URL/SUPABASE_DB_URL is not configured with a real value")
    return psycopg.connect(settings.database_url)


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _load_json_events() -> list[dict[str, Any]]:
    path = Path("artifacts/call_events.json")
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _filter_rows(rows: list[dict[str, Any]], *, from_ts: str | None, to_ts: str | None) -> list[dict[str, Any]]:
    f = _parse_ts(from_ts)
    t = _parse_ts(to_ts)
    out: list[dict[str, Any]] = []
    for r in rows:
        if _is_synthetic_event(r):
            continue
        created = _parse_ts(str((r.get("created_at") or r.get("updated_at") or "")))
        if created is None:
            created = datetime.now(timezone.utc)
        if f and created < f:
            continue
        if t and created > t:
            continue
        out.append(r)
    return out


def _is_synthetic_event(row: dict[str, Any]) -> bool:
    execution_id = str(row.get("execution_id") or "").strip()
    if not execution_id:
        return False
    # Hide local simulation/demo rows from KPI dashboards.
    if execution_id.startswith(("exec_demo_", "exec_ops_", "exec_test_", "exec_extract_", "exec_")):
        return True
    # UUID-like IDs are considered real provider executions.
    return re.fullmatch(r"[0-9a-fA-F-]{36}", execution_id) is None


def get_overview(*, from_ts: str | None = None, to_ts: str | None = None) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH f AS (
                  SELECT *
                  FROM call_executions
                  WHERE (%s::timestamptz IS NULL OR created_at >= %s::timestamptz)
                    AND (%s::timestamptz IS NULL OR created_at <= %s::timestamptz)
                )
                SELECT
                  COUNT(*) AS total_calls,
                  COUNT(*) FILTER (WHERE status = 'completed') AS completed_calls,
                  COUNT(*) FILTER (WHERE status IN ('no-answer','busy','failed','error','canceled')) AS failed_calls,
                  COALESCE(AVG(conversation_time),0) AS avg_conversation_time,
                  COALESCE(SUM(total_cost),0) AS total_cost
                FROM f
                """,
                (from_ts, from_ts, to_ts, to_ts),
            )
            row = cur.fetchone()
    total = int(row[0] or 0)
    completed = int(row[1] or 0)
    return {
        "total_calls": total,
        "completed_calls": completed,
        "failed_calls": int(row[2] or 0),
        "completion_rate": round(completed / total, 4) if total else 0.0,
        "avg_conversation_time": float(row[3] or 0.0),
        "total_cost": float(row[4] or 0.0),
    }


def get_calls_timeseries(
    *,
    from_ts: str | None = None,
    to_ts: str | None = None,
    interval: str = "day",
) -> list[dict[str, Any]]:
    interval = interval if interval in {"hour", "day", "week"} else "day"
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT date_trunc('{interval}', created_at) AS bucket,
                       COUNT(*) AS total_calls,
                       COUNT(*) FILTER (WHERE status = 'completed') AS completed_calls,
                       COALESCE(SUM(total_cost),0) AS total_cost
                FROM call_executions
                WHERE (%s::timestamptz IS NULL OR created_at >= %s::timestamptz)
                  AND (%s::timestamptz IS NULL OR created_at <= %s::timestamptz)
                GROUP BY 1
                ORDER BY 1 ASC
                """,
                (from_ts, from_ts, to_ts, to_ts),
            )
            rows = cur.fetchall()
    return [
        {
            "bucket": str(r[0]),
            "total_calls": int(r[1] or 0),
            "completed_calls": int(r[2] or 0),
            "total_cost": float(r[3] or 0.0),
        }
        for r in rows
    ]


def get_funnel(*, from_ts: str | None = None, to_ts: str | None = None) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH f AS (
                  SELECT *
                  FROM call_executions
                  WHERE (%s::timestamptz IS NULL OR created_at >= %s::timestamptz)
                    AND (%s::timestamptz IS NULL OR created_at <= %s::timestamptz)
                )
                SELECT
                  COUNT(*) AS calls_started,
                  COUNT(*) FILTER (WHERE intent = 'new_appointment') AS appointment_intents,
                  COUNT(*) FILTER (WHERE appointment_id IS NOT NULL) AS bookings_created,
                  COUNT(*) FILTER (WHERE follow_up_required IS TRUE) AS followups_required
                FROM f
                """,
                (from_ts, from_ts, to_ts, to_ts),
            )
            row = cur.fetchone()
    return {
        "calls_started": int(row[0] or 0),
        "appointment_intents": int(row[1] or 0),
        "bookings_created": int(row[2] or 0),
        "followups_required": int(row[3] or 0),
    }


def get_customer_cohorts(*, from_ts: str | None = None, to_ts: str | None = None) -> dict[str, Any]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH f AS (
                  SELECT *
                  FROM customer_profiles
                  WHERE (%s::timestamptz IS NULL OR created_at >= %s::timestamptz)
                    AND (%s::timestamptz IS NULL OR created_at <= %s::timestamptz)
                )
                SELECT
                  COUNT(*) FILTER (WHERE interaction_count = 1) AS new_customers,
                  COUNT(*) FILTER (WHERE interaction_count > 1) AS returning_customers,
                  COUNT(*) FILTER (WHERE interaction_count >= 3) AS repeat_customers
                FROM f
                """,
                (from_ts, from_ts, to_ts, to_ts),
            )
            row = cur.fetchone()
    return {
        "new_customers": int(row[0] or 0),
        "returning_customers": int(row[1] or 0),
        "repeat_customers": int(row[2] or 0),
    }


def get_call_detail(execution_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  execution_id, customer_id, status, transcript, conversation_time, total_cost,
                  source_phone, target_phone, appointment_id, slot_start, intent, follow_up_required,
                  patient_facing_summary, internal_ops_summary, extracted_data, context_details, telephony_data,
                  created_at, updated_at
                FROM call_executions
                WHERE execution_id = %s
                LIMIT 1
                """,
                (execution_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "execution_id": row[0],
        "customer_id": row[1],
        "status": row[2],
        "transcript": row[3],
        "conversation_time": float(row[4] or 0.0) if row[4] is not None else None,
        "total_cost": float(row[5] or 0.0) if row[5] is not None else None,
        "source_phone": row[6],
        "target_phone": row[7],
        "appointment_id": row[8],
        "slot_start": row[9],
        "intent": row[10],
        "follow_up_required": row[11],
        "patient_facing_summary": row[12],
        "internal_ops_summary": row[13],
        "extracted_data": row[14] or {},
        "context_details": row[15] or {},
        "telephony_data": row[16] or {},
        "created_at": str(row[17]) if row[17] else None,
        "updated_at": str(row[18]) if row[18] else None,
    }


def get_overview_fallback(*, from_ts: str | None = None, to_ts: str | None = None) -> dict[str, Any]:
    rows = _filter_rows(_load_json_events(), from_ts=from_ts, to_ts=to_ts)
    total = len(rows)
    completed = sum(1 for r in rows if r.get("status") == "completed")
    failed = sum(1 for r in rows if r.get("status") in {"no-answer", "busy", "failed", "error", "canceled"})
    durations = [float(r.get("conversation_time") or 0.0) for r in rows]
    costs = [float(r.get("total_cost") or 0.0) for r in rows]
    return {
        "total_calls": total,
        "completed_calls": completed,
        "failed_calls": failed,
        "completion_rate": round(completed / total, 4) if total else 0.0,
        "avg_conversation_time": (sum(durations) / len(durations)) if durations else 0.0,
        "total_cost": sum(costs),
        "source": "json_fallback",
    }


def get_calls_timeseries_fallback(
    *,
    from_ts: str | None = None,
    to_ts: str | None = None,
    interval: str = "day",
) -> list[dict[str, Any]]:
    interval = interval if interval in {"hour", "day", "week"} else "day"
    rows = _filter_rows(_load_json_events(), from_ts=from_ts, to_ts=to_ts)
    buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        dt = _parse_ts(str(r.get("created_at") or r.get("updated_at") or "")) or datetime.now(timezone.utc)
        if interval == "hour":
            key = dt.strftime("%Y-%m-%d %H:00")
        elif interval == "week":
            year, week, _ = dt.isocalendar()
            key = f"{year}-W{week:02d}"
        else:
            key = dt.strftime("%Y-%m-%d")
        b = buckets.setdefault(key, {"bucket": key, "total_calls": 0, "completed_calls": 0, "total_cost": 0.0})
        b["total_calls"] += 1
        if r.get("status") == "completed":
            b["completed_calls"] += 1
        b["total_cost"] += float(r.get("total_cost") or 0.0)
    return [buckets[k] for k in sorted(buckets.keys())]


def get_funnel_fallback(*, from_ts: str | None = None, to_ts: str | None = None) -> dict[str, Any]:
    rows = _filter_rows(_load_json_events(), from_ts=from_ts, to_ts=to_ts)
    calls_started = len(rows)
    appointment_intents = sum(1 for r in rows if (r.get("intent") == "new_appointment"))
    bookings_created = sum(1 for r in rows if r.get("appointment_id"))
    followups_required = sum(1 for r in rows if r.get("follow_up_required") is True)
    return {
        "calls_started": calls_started,
        "appointment_intents": appointment_intents,
        "bookings_created": bookings_created,
        "followups_required": followups_required,
        "source": "json_fallback",
    }


def get_customer_cohorts_fallback(*, from_ts: str | None = None, to_ts: str | None = None) -> dict[str, Any]:
    rows = _filter_rows(_load_json_events(), from_ts=from_ts, to_ts=to_ts)
    counts: dict[str, int] = {}
    for r in rows:
        cid = r.get("customer_id")
        if not cid:
            continue
        counts[cid] = counts.get(cid, 0) + 1
    new_customers = sum(1 for _, n in counts.items() if n == 1)
    returning_customers = sum(1 for _, n in counts.items() if n > 1)
    repeat_customers = sum(1 for _, n in counts.items() if n >= 3)
    return {
        "new_customers": new_customers,
        "returning_customers": returning_customers,
        "repeat_customers": repeat_customers,
        "source": "json_fallback",
    }


def get_call_detail_fallback(execution_id: str) -> dict[str, Any] | None:
    rows = _load_json_events()
    for row in reversed(rows):
        if str(row.get("execution_id") or "") != execution_id:
            continue
        ex = row.get("extracted_data") or {}
        return {
            "execution_id": row.get("execution_id"),
            "customer_id": row.get("customer_id"),
            "status": row.get("status"),
            "transcript": row.get("transcript"),
            "conversation_time": row.get("conversation_time"),
            "total_cost": row.get("total_cost"),
            "source_phone": row.get("source_phone"),
            "target_phone": row.get("target_phone"),
            "appointment_id": row.get("appointment_id"),
            "slot_start": row.get("slot_start"),
            "intent": row.get("intent"),
            "follow_up_required": row.get("follow_up_required"),
            "patient_facing_summary": ex.get("patient_facing_summary"),
            "internal_ops_summary": ex.get("internal_ops_summary"),
            "extracted_data": ex,
            "context_details": row.get("context_details") or {},
            "telephony_data": row.get("telephony_data") or {},
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "source": "json_fallback",
        }
    return None

