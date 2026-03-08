from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agentcare.settings import settings
from agentcare.templates import build_frontdesk_agent_spec


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    description: str
    category: str
    required_integrations: list[str]
    spec_builder: Callable[[], dict[str, Any]]


def workflow_frontdesk_booking() -> dict[str, Any]:
    return build_frontdesk_agent_spec(
        llm_base_url=settings.agentcare_llm_gateway_url,
        llm_model=settings.mistral_model,
        mock_ehr_base_url=settings.agentcare_mock_ehr_url,
        cal_api_key=settings.cal_api_key,
        cal_event_type_id=settings.cal_event_type_id,
        cal_timezone=settings.cal_timezone,
        calendar_tool_mode="auto",
    )


def workflow_care_navigation() -> dict[str, Any]:
    return build_frontdesk_agent_spec(
        agent_name="AgentCare Care Navigation",
        welcome_message="Hi, this is AgentCare care navigation. How can I support you today?",
        llm_base_url=settings.agentcare_llm_gateway_url,
        llm_model=settings.mistral_model,
        mock_ehr_base_url=settings.agentcare_mock_ehr_url,
        cal_api_key=settings.cal_api_key,
        cal_event_type_id=settings.cal_event_type_id,
        cal_timezone=settings.cal_timezone,
        calendar_tool_mode="custom",
    )


def workflow_followup_outreach() -> dict[str, Any]:
    return build_frontdesk_agent_spec(
        agent_name="AgentCare Follow-up Outreach",
        welcome_message="Hello from AgentCare. I am calling to help with your follow-up coordination.",
        llm_base_url=settings.agentcare_llm_gateway_url,
        llm_model=settings.mistral_model,
        mock_ehr_base_url=settings.agentcare_mock_ehr_url,
        cal_api_key=settings.cal_api_key,
        cal_event_type_id=settings.cal_event_type_id,
        cal_timezone=settings.cal_timezone,
        calendar_tool_mode="auto",
    )


WORKFLOW_REGISTRY: dict[str, WorkflowDefinition] = {
    "frontdesk_booking": WorkflowDefinition(
        name="frontdesk_booking",
        description="Schedule/reschedule appointments with optional calendar automation.",
        category="scheduling",
        required_integrations=["bolna", "llm_gateway", "appointment_connector", "email_optional"],
        spec_builder=workflow_frontdesk_booking,
    ),
    "care_navigation": WorkflowDefinition(
        name="care_navigation",
        description="General care coordination and intake routing, tool-friendly but booking-light.",
        category="care_coordination",
        required_integrations=["bolna", "llm_gateway", "customer_memory"],
        spec_builder=workflow_care_navigation,
    ),
    "followup_outreach": WorkflowDefinition(
        name="followup_outreach",
        description="Proactive follow-up calls for reminders and unresolved case closure.",
        category="outreach",
        required_integrations=["bolna", "llm_gateway", "analytics", "customer_memory"],
        spec_builder=workflow_followup_outreach,
    ),
}


def get_workflow_definition(workflow_name: str) -> WorkflowDefinition:
    if workflow_name not in WORKFLOW_REGISTRY:
        available = ", ".join(sorted(WORKFLOW_REGISTRY.keys()))
        raise ValueError(f"Unknown workflow: {workflow_name}. Available: {available}")
    return WORKFLOW_REGISTRY[workflow_name]


def list_workflows_metadata() -> list[dict[str, Any]]:
    return [
        {
            "name": wf.name,
            "description": wf.description,
            "category": wf.category,
            "required_integrations": wf.required_integrations,
        }
        for wf in sorted(WORKFLOW_REGISTRY.values(), key=lambda item: item.name)
    ]

