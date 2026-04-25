from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from agentcare.analysis.burnout import BurnoutAnalysis, analyze_burnout_context
from agentcare.analysis.trend import TrendResult, detect_trend
from agentcare.extraction.burnout import BurnoutExtraction, extract_burnout_fields
from agentcare.policies.wellness import WellnessPolicyDecision, evaluate_wellness_policy
from agentcare.ports.wellness import WellnessHistoryStorePort
from agentcare.wellness import get_wellness_history_store


@dataclass
class WellnessDeps:
    store: WellnessHistoryStorePort
    extract_fields: Callable[[str], BurnoutExtraction]
    analyze_burnout_context: Callable[..., BurnoutAnalysis]
    detect_trend: Callable[[list[float]], TrendResult]
    evaluate_policy: Callable[..., WellnessPolicyDecision]


@dataclass
class WellnessExecutionResult:
    ok: bool
    execution_id: str | None
    employee_id: str | None
    extraction: dict[str, Any]
    analysis: dict[str, Any]
    trend: dict[str, Any]
    policy: dict[str, Any]
    persisted: bool
    notes: list[str] = field(default_factory=list)
    error: str | None = None


def build_wellness_deps() -> WellnessDeps:
    return WellnessDeps(
        store=get_wellness_history_store(),
        extract_fields=extract_burnout_fields,
        analyze_burnout_context=analyze_burnout_context,
        detect_trend=detect_trend,
        evaluate_policy=evaluate_wellness_policy,
    )


def _execution_key(execution: dict[str, Any]) -> str | None:
    return str(execution.get("id") or execution.get("execution_id") or "").strip() or None


def _employee_id(execution: dict[str, Any], extraction: BurnoutExtraction | None = None) -> str | None:
    candidates = [
        execution.get("employee_id"),
        execution.get("customer_id"),
        (execution.get("metadata") or {}).get("employee_id")
        if isinstance(execution.get("metadata"), dict)
        else None,
        (execution.get("context_details") or {}).get("employee_id")
        if isinstance(execution.get("context_details"), dict)
        else None,
        (execution.get("telephony_data") or {}).get("from_number")
        if isinstance(execution.get("telephony_data"), dict)
        else None,
        extraction.employee_name if extraction else None,
    ]
    for value in candidates:
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return None


def process_wellness_execution(
    execution: dict[str, Any],
    *,
    source: str = "manual",
    deps: WellnessDeps | None = None,
    history_loader: Callable[[str], list[float]] | None = None,
    history_appender: Callable[[str, dict[str, Any]], None] | None = None,
    extract_fn: Callable[[str], BurnoutExtraction] | None = None,
    analyze_fn: Callable[..., BurnoutAnalysis] | None = None,
    trend_fn: Callable[[list[float]], TrendResult] | None = None,
    policy_fn: Callable[..., WellnessPolicyDecision] | None = None,
) -> WellnessExecutionResult:
    wired = deps or build_wellness_deps()
    extract = extract_fn or wired.extract_fields
    analyze = analyze_fn or wired.analyze_burnout_context
    trend_detector = trend_fn or wired.detect_trend
    policy = policy_fn or wired.evaluate_policy

    notes: list[str] = []
    execution_id = _execution_key(execution)
    transcript = str(execution.get("transcript") or "").strip()
    reason = execution.get("reason")

    if not transcript:
        notes.append("empty_transcript")
        return WellnessExecutionResult(
            ok=False,
            execution_id=execution_id,
            employee_id=_employee_id(execution),
            extraction={},
            analysis={},
            trend={},
            policy={},
            persisted=False,
            notes=notes,
            error="empty_transcript",
        )

    extraction = extract(transcript)
    employee_id = _employee_id(execution, extraction)
    analysis = analyze(
        transcript=transcript,
        reason=reason,
        llm_ee=extraction.emotional_exhaustion_0_10,
        llm_dp=extraction.depersonalisation_0_10,
        llm_pa=extraction.reduced_accomplishment_0_10,
    )

    history: list[float] = []
    if employee_id:
        try:
            history = list(history_loader(employee_id) if history_loader else wired.store.load_scores(employee_id))
        except Exception as exc:
            notes.append(f"history_loader_error:{exc}")

    trend = trend_detector(history + [analysis.composite_score])
    decision = policy(
        risk_band=analysis.risk_band,
        high_acuity_flag=analysis.high_acuity_flag,
        trend_direction=trend.direction,
        triage_trigger=trend.triage_trigger,
    )

    persisted = False
    if employee_id:
        entry = {
            "execution_id": execution_id,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ee_score": analysis.ee_score,
            "dp_score": analysis.dp_score,
            "pa_score": analysis.pa_score,
            "composite_score": analysis.composite_score,
            "risk_band": analysis.risk_band,
            "high_acuity_flag": analysis.high_acuity_flag,
            "primary_stressor": extraction.primary_stressor,
            "engagement_level": extraction.engagement_level,
        }
        try:
            if history_appender:
                history_appender(employee_id, entry)
            else:
                wired.store.append_entry(employee_id, entry)
            persisted = True
        except Exception as exc:
            notes.append(f"history_appender_error:{exc}")
    else:
        notes.append("missing_employee_id")

    return WellnessExecutionResult(
        ok=True,
        execution_id=execution_id,
        employee_id=employee_id,
        extraction=extraction.model_dump(),
        analysis=asdict(analysis),
        trend=asdict(trend),
        policy=asdict(decision),
        persisted=persisted,
        notes=notes,
    )
