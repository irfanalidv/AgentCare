from __future__ import annotations

from typing import Any

from agentcare.extraction.burnout import BurnoutExtraction
from agentcare.usecases.execution_router import process_agentcare_execution, resolve_execution_workflow
from agentcare.usecases.wellness import process_wellness_execution
from agentcare.workflows.registry import WORKFLOW_REGISTRY


def _stub_extract(_transcript: str) -> BurnoutExtraction:
    return BurnoutExtraction(
        employee_name="Sam",
        emotional_exhaustion_0_10=8,
        depersonalisation_0_10=7,
        reduced_accomplishment_0_10=6,
        primary_stressor="workload",
        engagement_level="low",
        sleep_disrupted=True,
        physical_symptoms_reported=False,
        crisis_signal=False,
        summary="High exhaustion, workload-driven.",
        quote_evidence=["I am completely exhausted"],
    )


def _stub_extract_low(_transcript: str) -> BurnoutExtraction:
    return BurnoutExtraction(
        employee_name="Sam",
        emotional_exhaustion_0_10=1,
        depersonalisation_0_10=1,
        reduced_accomplishment_0_10=1,
        engagement_level="high",
        crisis_signal=False,
        summary="Doing fine.",
    )


def test_wellness_pipeline_high_risk_routes_to_human() -> None:
    appended: list[tuple[str, dict[str, Any]]] = []
    history_store: dict[str, list[float]] = {"emp_001": [3.0, 4.5, 5.5, 6.5]}

    def loader(eid: str) -> list[float]:
        return list(history_store.get(eid, []))

    def appender(eid: str, entry: dict[str, Any]) -> None:
        appended.append((eid, entry))
        history_store.setdefault(eid, []).append(entry["composite_score"])

    result = process_wellness_execution(
        {
            "id": "exec_001",
            "employee_id": "emp_001",
            "transcript": "I am exhausted, I cannot sleep, I do not care anymore, I am missing deadlines.",
        },
        history_loader=loader,
        history_appender=appender,
        extract_fn=_stub_extract,
    )

    assert result.ok is True
    assert result.persisted is True
    assert result.policy["allow_auto_close"] is False
    assert result.policy["escalation_required"] is True
    assert result.analysis["risk_band"] in {"high", "medium"}
    assert len(appended) == 1


def test_wellness_pipeline_low_risk_auto_closes() -> None:
    result = process_wellness_execution(
        {
            "id": "exec_002",
            "employee_id": "emp_002",
            "transcript": "Workload is fine. Team is great. Slept well. Shipped two tickets.",
        },
        history_loader=lambda _eid: [1.0, 1.2, 0.9],
        history_appender=lambda _eid, _entry: None,
        extract_fn=_stub_extract_low,
    )

    assert result.ok is True
    assert result.policy["allow_auto_close"] is True
    assert result.policy["escalation_required"] is False


def test_wellness_pipeline_empty_transcript() -> None:
    result = process_wellness_execution({"id": "exec_003", "employee_id": "emp_003", "transcript": ""})
    assert result.ok is False
    assert "empty_transcript" in result.notes


def test_wellness_workflow_is_registered() -> None:
    assert "wellness_checkin" in WORKFLOW_REGISTRY


def test_execution_router_selects_wellness_workflow() -> None:
    payload = {"workflow": "wellness_checkin", "employee_id": "emp_004", "transcript": "I feel exhausted."}
    assert resolve_execution_workflow(payload) == "wellness_checkin"
    result = process_agentcare_execution(payload, source="test", workflow="wellness_checkin")
    assert result.ok is True
    assert getattr(result, "employee_id") == "emp_004"
