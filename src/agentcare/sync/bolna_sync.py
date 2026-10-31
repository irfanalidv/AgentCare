from __future__ import annotations

from pathlib import Path
from typing import Any

from agentcare._jsonio import read_json, write_json_atomic
from agentcare.bolna import BolnaClient
from agentcare.settings import settings
from agentcare.usecases import process_agentcare_execution, resolve_execution_workflow


def _execution_key(ex: dict[str, Any]) -> str | None:
    key = ex.get("id") or ex.get("execution_id")
    return str(key) if key else None


def sync_bolna_executions(
    *,
    agent_id: str,
    page_size: int = 50,
    max_pages: int = 10,
    out_path: Path = Path("artifacts/executions_sync.json"),
    force_automation: bool = False,
) -> dict[str, Any]:
    if not settings.bolna_api_key:
        raise ValueError("Missing BOLNA_API_KEY/bolna_API")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    processed = 0
    upserted_customers = 0
    automated = 0
    automation_processed_path = Path("artifacts/automation_processed.json")
    automation_processed: set[str] = (
        set()
        if force_automation
        else {str(x) for x in read_json(automation_processed_path, [], expected=list)}
    )

    with BolnaClient(api_key=settings.bolna_api_key, base_url=settings.bolna_base_url) as bolna:
        items = bolna.get_all_executions(
            agent_id=agent_id, page_size=page_size, max_pages=max_pages
        )
        rows = [x.model_dump() for x in items]

    for ex in rows:
        processed += 1
        ex_key = _execution_key(ex)
        should_automate = bool(ex_key and (force_automation or ex_key not in automation_processed))
        workflow = resolve_execution_workflow(ex)
        res = process_agentcare_execution(
            ex,
            source="sync_job",
            workflow=workflow,
            automate_actions=should_automate,
            enforce_idempotency=False,
        )
        if getattr(res, "customer_id", None):
            upserted_customers += 1
        # Booking automation only runs for completed calls. Marking an in-progress
        # execution as automated would skip it forever once it completes.
        completed = str(ex.get("status") or "").strip().lower() == "completed"
        if should_automate and ex_key and completed:
            automation_processed.add(ex_key)
            automated += 1

    payload = {
        "agent_id": agent_id,
        "processed_executions": processed,
        "customer_upserts": upserted_customers,
        "automated_executions": automated,
        "executions": rows,
    }
    write_json_atomic(automation_processed_path, sorted(automation_processed))
    write_json_atomic(out_path, payload)
    return {"ok": True, **payload, "out_path": str(out_path)}
