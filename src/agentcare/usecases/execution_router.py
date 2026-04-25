from __future__ import annotations

from typing import Any, Literal

from agentcare.usecases.frontdesk import FrontdeskProcessingResult, process_frontdesk_execution
from agentcare.usecases.wellness import WellnessExecutionResult, process_wellness_execution

ExecutionWorkflow = Literal["frontdesk_booking", "care_navigation", "followup_outreach", "wellness_checkin"]
ExecutionProcessingResult = FrontdeskProcessingResult | WellnessExecutionResult


def resolve_execution_workflow(execution: dict[str, Any], *, default: str = "frontdesk_booking") -> str:
    metadata = execution.get("metadata") if isinstance(execution.get("metadata"), dict) else {}
    context = execution.get("context_details") if isinstance(execution.get("context_details"), dict) else {}
    candidates = [
        execution.get("workflow"),
        execution.get("workflow_name"),
        execution.get("agentcare_workflow"),
        metadata.get("workflow"),
        metadata.get("agentcare_workflow"),
        context.get("workflow"),
        context.get("agentcare_workflow"),
    ]
    for candidate in candidates:
        workflow = str(candidate or "").strip()
        if workflow:
            return workflow

    agent_name = str(execution.get("agent_name") or context.get("agent_name") or "").lower()
    if "wellness" in agent_name or "burnout" in agent_name:
        return "wellness_checkin"

    return default


def process_agentcare_execution(
    execution: dict[str, Any],
    *,
    source: str,
    workflow: str | None = None,
    automate_actions: bool = True,
    enforce_idempotency: bool = False,
) -> ExecutionProcessingResult:
    selected = workflow or resolve_execution_workflow(execution)
    if selected == "wellness_checkin":
        return process_wellness_execution(execution, source=source)

    return process_frontdesk_execution(
        execution,
        source=source,
        automate_actions=automate_actions,
        enforce_idempotency=enforce_idempotency,
    )
