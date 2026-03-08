from __future__ import annotations
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from agentcare.usecases import process_frontdesk_execution


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
    res = process_frontdesk_execution(
        event,
        source="webhook",
        automate_actions=True,
        enforce_idempotency=True,
    )

    return {
        "ok": res.ok,
        "deduplicated": res.deduplicated,
        "execution_id": res.execution_id,
        "customer_id": res.customer_id,
        "email_sent": bool(res.email_confirmation),
        "email_result": res.email_confirmation,
        "analytics_store": res.analytics_store,
        "enriched_fields": res.extracted_data,
    }

