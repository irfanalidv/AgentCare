from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentcare.bolna import BolnaClient
from agentcare.settings import settings
from agentcare.usecases import process_frontdesk_execution


def _execution_key(ex: dict[str, Any]) -> str | None:
    return ex.get("id") or ex.get("execution_id")


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
    if automation_processed_path.exists() and not force_automation:
        try:
            automation_processed = set(json.loads(automation_processed_path.read_text("utf-8")))
        except Exception:
            automation_processed = set()
    else:
        automation_processed = set()

    with BolnaClient(api_key=settings.bolna_api_key, base_url=settings.bolna_base_url) as bolna:
        items = bolna.get_all_executions(agent_id=agent_id, page_size=page_size, max_pages=max_pages)
        rows = [x.model_dump() for x in items]

    for ex in rows:
        processed += 1
        ex_key = _execution_key(ex)
        should_automate = bool(ex_key and (force_automation or ex_key not in automation_processed))
        res = process_frontdesk_execution(
            ex,
            source="sync_job",
            automate_actions=should_automate,
            enforce_idempotency=False,
        )
        if res.customer_id:
            upserted_customers += 1
        if should_automate and ex_key:
            automation_processed.add(ex_key)
            automated += 1

    payload = {
        "agent_id": agent_id,
        "processed_executions": processed,
        "customer_upserts": upserted_customers,
        "automated_executions": automated,
        "executions": rows,
    }
    automation_processed_path.parent.mkdir(parents=True, exist_ok=True)
    automation_processed_path.write_text(json.dumps(sorted(list(automation_processed)), indent=2), "utf-8")
    out_path.write_text(json.dumps(payload, indent=2, default=str), "utf-8")
    return {"ok": True, **payload, "out_path": str(out_path)}

