from __future__ import annotations
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from agentcare.usecases import process_agentcare_execution, resolve_execution_workflow


app = FastAPI(title="AgentCare Webhooks", version="0.1.0")


class BolnaExecutionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    status: str | None = None
    transcript: str | None = None
    conversation_time: float | None = None
    total_cost: float | None = None
    extracted_data: dict[str, Any] | None = None
    context_details: dict[str, Any] | None = None
    telephony_data: dict[str, Any] | None = None


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True}


@app.post("/bolna/execution")
def on_bolna_execution(payload: BolnaExecutionPayload) -> dict[str, Any]:
    """
    Receives Bolna execution payload, updates customer memory,
    and sends confirmation email when customer email + appointment details exist.
    """
    event = payload.model_dump()
    workflow = resolve_execution_workflow(event)
    res = process_agentcare_execution(
        event,
        source="webhook",
        workflow=workflow,
        automate_actions=True,
        enforce_idempotency=True,
    )

    return {
        "ok": res.ok,
        "workflow": workflow,
        "deduplicated": getattr(res, "deduplicated", False),
        "execution_id": res.execution_id,
        "customer_id": getattr(res, "customer_id", None),
        "employee_id": getattr(res, "employee_id", None),
        "email_sent": bool(getattr(res, "email_confirmation", None)),
        "email_result": getattr(res, "email_confirmation", None),
        "analytics_store": getattr(res, "analytics_store", None),
        "enriched_fields": getattr(res, "extracted_data", getattr(res, "extraction", {})),
        "wellness": {
            "analysis": getattr(res, "analysis", None),
            "trend": getattr(res, "trend", None),
            "policy": getattr(res, "policy", None),
            "persisted": getattr(res, "persisted", None),
        }
        if workflow == "wellness_checkin"
        else None,
    }

