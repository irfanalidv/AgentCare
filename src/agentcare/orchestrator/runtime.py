from __future__ import annotations

from typing import Any

from agentcare.providers import ProviderFactory
from agentcare.workflows import get_workflow_definition


class Orchestrator:
    """
    Framework runtime:
    - selects workflow template
    - creates Bolna agent
    - can be extended for events, retries, and analytics pipelines
    """

    def create_agent_from_workflow(self, workflow_name: str) -> dict[str, Any]:
        workflow = get_workflow_definition(workflow_name)
        spec = workflow.spec_builder()
        with ProviderFactory.bolna() as bolna:
            status = bolna.create_agent_v2(
                agent_config=spec["agent_config"],
                agent_prompts=spec["agent_prompts"],
            )
        return {
            "workflow": workflow_name,
            "category": workflow.category,
            "agent_id": status.agent_id,
            "status": status.status,
        }

