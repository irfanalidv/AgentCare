"""
Wellness dashboard endpoints.

Read-only JSON API surfacing the wellness check-in history for cohort-level
operations views. Reads directly from the JsonWellnessHistoryStore artefact
(artifacts/wellness_history.json) so the dashboard does not require any new
runtime dependencies.

Mount via:
    from agentcare.dashboard.wellness_routes import router as wellness_router
    app.include_router(wellness_router)
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from agentcare.wellness import get_wellness_history_store

router = APIRouter(prefix="/api/wellness", tags=["wellness"])


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _classify_band(composite: float) -> str:
    if composite >= 7.0:
        return "high"
    if composite >= 4.0:
        return "medium"
    return "low"


@router.get("/cohort")
def cohort_summary() -> dict[str, Any]:
    """
    Cohort-level summary across all employees.

    Returns counts by latest-session risk band, mean dimension scores,
    and the count of employees flagged for follow-up (latest band == high
    or high_acuity_flag set).
    """
    store = get_wellness_history_store()
    rows = store._read()  # noqa: SLF001 — the store is internal; this view is read-only

    if not isinstance(rows, dict) or not rows:
        return {
            "n_employees": 0,
            "n_sessions_total": 0,
            "by_band": {"low": 0, "medium": 0, "high": 0},
            "mean_scores": {"ee": 0.0, "dp": 0.0, "pa": 0.0, "composite": 0.0},
            "n_flagged_for_followup": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    n_employees = len(rows)
    n_sessions_total = 0
    band_counts: Counter[str] = Counter()
    flagged = 0
    ee_sum = dp_sum = pa_sum = comp_sum = 0.0
    score_n = 0

    for employee_id, entries in rows.items():
        if not isinstance(entries, list) or not entries:
            continue
        n_sessions_total += len(entries)
        latest = entries[-1]
        band = str(latest.get("risk_band") or _classify_band(_coerce_float(latest.get("composite_score"))))
        band_counts[band] += 1
        acuity = bool(latest.get("high_acuity_flag", False))
        if band == "high" or acuity:
            flagged += 1
        for entry in entries:
            ee_sum += _coerce_float(entry.get("ee_score"))
            dp_sum += _coerce_float(entry.get("dp_score"))
            pa_sum += _coerce_float(entry.get("pa_score"))
            comp_sum += _coerce_float(entry.get("composite_score"))
            score_n += 1

    mean_scores = {
        "ee": round(ee_sum / score_n, 2) if score_n else 0.0,
        "dp": round(dp_sum / score_n, 2) if score_n else 0.0,
        "pa": round(pa_sum / score_n, 2) if score_n else 0.0,
        "composite": round(comp_sum / score_n, 2) if score_n else 0.0,
    }

    return {
        "n_employees": n_employees,
        "n_sessions_total": n_sessions_total,
        "by_band": {
            "low": band_counts.get("low", 0),
            "medium": band_counts.get("medium", 0),
            "high": band_counts.get("high", 0),
        },
        "mean_scores": mean_scores,
        "n_flagged_for_followup": flagged,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/flagged")
def flagged_employees() -> dict[str, Any]:
    """
    List employees in the high band or with active acuity flags on their
    latest session, sorted by latest composite score descending.
    """
    store = get_wellness_history_store()
    rows = store._read()  # noqa: SLF001
    if not isinstance(rows, dict):
        rows = {}

    flagged: list[dict[str, Any]] = []
    for employee_id, entries in rows.items():
        if not isinstance(entries, list) or not entries:
            continue
        latest = entries[-1]
        composite = _coerce_float(latest.get("composite_score"))
        band = str(latest.get("risk_band") or _classify_band(composite))
        acuity = bool(latest.get("high_acuity_flag", False))
        if band != "high" and not acuity:
            continue
        flagged.append({
            "employee_id": employee_id,
            "latest_composite": round(composite, 2),
            "latest_band": band,
            "high_acuity_flag": acuity,
            "primary_stressor": latest.get("primary_stressor"),
            "engagement_level": latest.get("engagement_level"),
            "n_sessions": len(entries),
            "latest_timestamp": latest.get("timestamp"),
        })

    flagged.sort(key=lambda r: (not r["high_acuity_flag"], -r["latest_composite"]))
    return {"n": len(flagged), "employees": flagged}


@router.get("/employee/{employee_id}")
def employee_detail(employee_id: str) -> dict[str, Any]:
    """
    Full session history for one employee, plus a recomputed trend
    classification on the composite-score time series.
    """
    store = get_wellness_history_store()
    rows = store._read()  # noqa: SLF001
    if not isinstance(rows, dict) or employee_id not in rows:
        raise HTTPException(status_code=404, detail=f"unknown employee_id: {employee_id}")

    entries = rows[employee_id]
    if not isinstance(entries, list):
        entries = []

    composites = [_coerce_float(e.get("composite_score")) for e in entries]

    # Recompute trend on the fly so the dashboard reflects the latest data
    try:
        from agentcare.analysis.trend import detect_trend
        trend = detect_trend(composites)
        trend_dict = {
            "n": trend.n,
            "slope_per_session": trend.slope_per_session,
            "direction": trend.direction,
            "consecutive_deteriorating": trend.consecutive_deteriorating,
            "triage_trigger": trend.triage_trigger,
            "mk_p_value": trend.mk_p_value,
        }
    except Exception as exc:  # pragma: no cover
        trend_dict = {"error": str(exc)}

    return {
        "employee_id": employee_id,
        "n_sessions": len(entries),
        "sessions": entries,
        "composite_series": [round(c, 2) for c in composites],
        "trend": trend_dict,
    }


@router.get("/series")
def cohort_series(limit: int = 50) -> dict[str, Any]:
    """
    Lightweight payload for cohort trajectory plots: per-employee composite
    series, capped at `limit` employees (sorted by latest composite desc).
    """
    store = get_wellness_history_store()
    rows = store._read()  # noqa: SLF001
    if not isinstance(rows, dict):
        rows = {}

    employees: list[dict[str, Any]] = []
    for employee_id, entries in rows.items():
        if not isinstance(entries, list) or not entries:
            continue
        composites = [_coerce_float(e.get("composite_score")) for e in entries]
        employees.append({
            "employee_id": employee_id,
            "composite_series": [round(c, 2) for c in composites],
            "latest_composite": round(composites[-1], 2),
            "n_sessions": len(entries),
        })

    employees.sort(key=lambda r: -r["latest_composite"])
    return {"n_total": len(employees), "limit": limit, "employees": employees[:limit]}
