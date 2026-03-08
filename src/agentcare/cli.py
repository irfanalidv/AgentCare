from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import typer
from rich import print

from agentcare.bolna import BolnaClient
from agentcare.customer import get_customer_store, init_postgres_schema
from agentcare.eval import evaluate_transcript
from agentcare.extraction import extract_conversation_fields
from agentcare.llm import MistralLLM
from agentcare.orchestrator import Orchestrator
from agentcare.settings import settings
from agentcare.sync import sync_bolna_executions
from agentcare.templates import build_frontdesk_agent_spec
from agentcare.usecases import process_frontdesk_execution
from agentcare.workflows import WORKFLOW_REGISTRY, list_workflows_metadata

app = typer.Typer(add_completion=False, help="AgentCare CLI (Bolna + Mistral + eval).")
bolna_app = typer.Typer(add_completion=False, help="Bolna API helpers.")
app.add_typer(bolna_app, name="bolna")
eval_app = typer.Typer(add_completion=False, help="Evaluation helpers (Mistral).")
app.add_typer(eval_app, name="eval")
tpl_app = typer.Typer(add_completion=False, help="Generate agent specs/templates.")
app.add_typer(tpl_app, name="templates")
customer_app = typer.Typer(add_completion=False, help="Customer memory lookup/upsert.")
app.add_typer(customer_app, name="customer")
webhook_app = typer.Typer(add_completion=False, help="Webhook tools and local simulation.")
app.add_typer(webhook_app, name="webhook")
framework_app = typer.Typer(add_completion=False, help="Framework setup commands.")
app.add_typer(framework_app, name="framework")
extract_app = typer.Typer(add_completion=False, help="Built-in transcript extraction.")
app.add_typer(extract_app, name="extract")


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def _is_non_placeholder(value: str | None) -> bool:
    if not value:
        return False
    tokens = ("[YOUR-", "YOUR-PASSWORD", "example", "replace_me")
    return not any(t in value for t in tokens)


def _required_runtime_env_summary() -> dict[str, bool]:
    return {
        "MISTRAL_API_KEY": _is_non_placeholder(settings.mistral_api_key),
        "BOLNA_API_KEY": _is_non_placeholder(settings.bolna_api_key),
        "RESEND_API_KEY": _is_non_placeholder(settings.resend_api_key),
        "DATABASE_URL": _is_non_placeholder(settings.database_url),
    }


def _service_specs() -> list[dict[str, str]]:
    return [
        {
            "name": "llm_gateway",
            "script": "scripts/run_llm_gateway.sh",
            "health": "http://127.0.0.1:8010/healthz",
        },
        {
            "name": "mock_ehr",
            "script": "scripts/run_mock_ehr.sh",
            "health": "http://127.0.0.1:8020/healthz",
        },
        {
            "name": "webhooks",
            "script": "scripts/run_webhooks.sh",
            "health": "http://127.0.0.1:8030/healthz",
        },
        {
            "name": "analytics",
            "script": "scripts/run_analytics.sh",
            "health": "http://127.0.0.1:8040/healthz",
        },
        {
            "name": "dashboard",
            "script": "scripts/run_dashboard.sh",
            "health": "http://127.0.0.1:8050/healthz",
        },
    ]


@app.command()
def doctor() -> None:
    """Print effective environment variables and defaults (no secrets)."""
    safe = {
        "bolna_base_url": settings.bolna_base_url,
        "bolna_api_key_configured": bool(settings.bolna_api_key),
        "bolna_agent_id_configured": bool(settings.bolna_agent_id),
        "mistral_model": settings.mistral_model,
        "mistral_api_key_configured": bool(settings.mistral_api_key),
        "resend_api_key_configured": bool(settings.resend_api_key),
        "cal_api_key_configured": bool(settings.cal_api_key),
        "cal_event_type_id_configured": bool(settings.cal_event_type_id),
        "cal_timezone": settings.cal_timezone,
        "customer_store_backend": settings.customer_store_backend,
        "database_url_configured": _is_non_placeholder(settings.database_url),
        "supabase_url_configured": _is_non_placeholder(settings.supabase_url),
        "supabase_publishable_key_configured": _is_non_placeholder(settings.supabase_publishable_key),
        "agentcare_llm_gateway_url": settings.agentcare_llm_gateway_url,
        "agentcare_mock_ehr_url": settings.agentcare_mock_ehr_url,
    }
    _print_json(safe)


@app.command()
def init_artifacts(dir: Path = typer.Option(Path("artifacts"), "--dir", help="Artifacts folder")) -> None:
    """Create local artifacts folder."""
    dir.mkdir(parents=True, exist_ok=True)
    print(f"[green]ok[/green] created `{dir}`")


def _bolna() -> BolnaClient:
    if not settings.bolna_api_key:
        raise typer.BadParameter("Missing BOLNA_API_KEY in environment/.env")
    return BolnaClient(api_key=settings.bolna_api_key, base_url=settings.bolna_base_url)

def _mistral() -> MistralLLM:
    if not settings.mistral_api_key:
        raise typer.BadParameter("Missing MISTRAL_API_KEY in environment/.env")
    return MistralLLM(api_key=settings.mistral_api_key, model=settings.mistral_model)


@bolna_app.command("voices")
def bolna_voices() -> None:
    """List voices available for your Bolna account."""
    with _bolna() as c:
        voices = c.list_voices()
    _print_json([v.model_dump() for v in voices])


@bolna_app.command("execution")
def bolna_execution(execution_id: str = typer.Argument(..., help="Bolna execution_id (UUID)")) -> None:
    """Fetch a single call execution by id."""
    with _bolna() as c:
        ex = c.get_execution(execution_id=execution_id)
    _print_json(ex.model_dump())


@bolna_app.command("call")
def bolna_call(
    agent_id: str | None = typer.Option(None, "--agent-id", help="Bolna agent_id (UUID); defaults to BOLNA_AGENT_ID"),
    to: str = typer.Option(..., "--to", help="Recipient phone number in E.164 format"),
    from_phone: str | None = typer.Option(
        None,
        "--from",
        help="Sender phone number in E.164 format; defaults to BOLNA_FROM_PHONE_NUMBER if configured",
    ),
    scheduled_at: str | None = typer.Option(None, "--scheduled-at", help="ISO8601 datetime with timezone"),
    user_data_json: str | None = typer.Option(None, "--user-data-json", help="JSON object for dynamic variables"),
) -> None:
    """Initiate an outbound call."""
    resolved_agent_id = agent_id or settings.bolna_agent_id
    if not resolved_agent_id:
        raise typer.BadParameter("Missing --agent-id and BOLNA_AGENT_ID/bolna_agent_id is not configured")
    user_data = json.loads(user_data_json) if user_data_json else None
    resolved_from_phone = from_phone or settings.bolna_from_phone_number
    with _bolna() as c:
        status = c.make_call(
            agent_id=resolved_agent_id,
            recipient_phone_number=to,
            from_phone_number=resolved_from_phone,
            scheduled_at=scheduled_at,
            user_data=user_data,
        )
    _print_json(status.model_dump())


@bolna_app.command("create-agent")
def bolna_create_agent(
    spec_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="JSON spec with agent_config + agent_prompts"),
) -> None:
    """Create an agent from a JSON spec file."""
    spec = json.loads(spec_path.read_text("utf-8"))
    if "agent_config" not in spec or "agent_prompts" not in spec:
        raise typer.BadParameter("Spec JSON must contain keys: agent_config, agent_prompts")
    with _bolna() as c:
        status = c.create_agent_v2(agent_config=spec["agent_config"], agent_prompts=spec["agent_prompts"])
    _print_json(status.model_dump())


@bolna_app.command("add-custom-model")
def bolna_add_custom_model(
    name: str = typer.Option("AgentCare Mistral Gateway", "--name", help="Human-readable model name"),
    url: str = typer.Option(None, "--url", help="OpenAI-compatible base URL (ending in /v1)"),
) -> None:
    """Register a custom LLM endpoint in Bolna (OpenAI-compatible)."""
    target_url = url or settings.agentcare_llm_gateway_url
    with _bolna() as c:
        out = c.add_custom_llm_model(custom_model_name=name, custom_model_url=target_url)
    _print_json(out.model_dump())


@bolna_app.command("sync-executions")
def bolna_sync_executions(
    agent_id: str | None = typer.Option(
        None, "--agent-id", help="Bolna agent_id (UUID); defaults to BOLNA_AGENT_ID"
    ),
    page_size: int = typer.Option(50, "--page-size"),
    max_pages: int = typer.Option(10, "--max-pages"),
    out_path: Path = typer.Option(Path("artifacts/executions_sync.json"), "--out"),
    force_automation: bool = typer.Option(
        False,
        "--force-automation",
        help="Re-run extraction/Cal/email automation for completed executions even if previously processed",
    ),
) -> None:
    """Fetch paginated executions and process customer memory updates."""
    resolved_agent_id = agent_id or settings.bolna_agent_id
    if not resolved_agent_id:
        raise typer.BadParameter("Missing --agent-id and BOLNA_AGENT_ID/bolna_agent_id is not configured")
    result = sync_bolna_executions(
        agent_id=resolved_agent_id,
        page_size=page_size,
        max_pages=max_pages,
        out_path=out_path,
        force_automation=force_automation,
    )
    _print_json(result)


kb_app = typer.Typer(add_completion=False, help="Knowledgebase APIs.")
bolna_app.add_typer(kb_app, name="kb")


@kb_app.command("create-url")
def bolna_kb_create_url(url: str = typer.Argument(..., help="URL to ingest")) -> None:
    with _bolna() as c:
        out = c.create_knowledgebase_from_url(url=url)
    _print_json(out.model_dump())


@kb_app.command("create-pdf")
def bolna_kb_create_pdf(pdf_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="PDF file path")) -> None:
    with _bolna() as c:
        out = c.create_knowledgebase_from_pdf(pdf_path=pdf_path)
    _print_json(out.model_dump())


@kb_app.command("list")
def bolna_kb_list() -> None:
    with _bolna() as c:
        out = c.list_knowledgebases()
    _print_json([k.model_dump() for k in out])


@kb_app.command("get")
def bolna_kb_get(rag_id: str = typer.Argument(..., help="Knowledgebase rag_id")) -> None:
    with _bolna() as c:
        out = c.get_knowledgebase(rag_id=rag_id)
    _print_json(out.model_dump())


@kb_app.command("delete")
def bolna_kb_delete(rag_id: str = typer.Argument(..., help="Knowledgebase rag_id")) -> None:
    with _bolna() as c:
        out = c.delete_knowledgebase(rag_id=rag_id)
    _print_json(out.model_dump())


@eval_app.command("transcript")
def eval_transcript(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Text file containing transcript"),
) -> None:
    """Evaluate a transcript file with Mistral."""
    transcript = path.read_text("utf-8")
    llm = _mistral()
    result = evaluate_transcript(llm=llm, transcript=transcript)
    _print_json(result.model_dump())


@eval_app.command("execution")
def eval_execution(
    execution_id: str = typer.Argument(..., help="Bolna execution_id (UUID)"),
) -> None:
    """Fetch a Bolna execution and evaluate its transcript with Mistral."""
    with _bolna() as c:
        ex = c.get_execution(execution_id=execution_id)
    if not ex.transcript:
        raise typer.BadParameter("Execution has no transcript yet (or call not completed).")
    llm = _mistral()
    result = evaluate_transcript(llm=llm, transcript=ex.transcript, context={"execution_id": execution_id})
    _print_json({"execution": ex.model_dump(), "eval": result.model_dump()})


@tpl_app.command("frontdesk")
def templates_frontdesk(
    out: Path = typer.Option(Path("frontdesk_agent.json"), "--out", help="Where to write the JSON spec"),
    agent_name: str = typer.Option("AgentCare Front Desk", "--agent-name"),
    welcome: str = typer.Option(
        "Hi! Thanks for calling AgentCare. How can I help you today?",
        "--welcome",
        help="Agent welcome message",
    ),
    webhook_url: str | None = typer.Option(None, "--webhook-url", help="Bolna webhook URL (optional)"),
    calendar_tool_mode: str = typer.Option(
        "auto",
        "--calendar-tool-mode",
        help="Calendar tool config mode: auto | native | custom",
    ),
) -> None:
    """Generate a Bolna agent spec JSON for a healthcare front desk workflow."""
    spec = build_frontdesk_agent_spec(
        agent_name=agent_name,
        welcome_message=welcome,
        webhook_url=webhook_url,
        llm_base_url=settings.agentcare_llm_gateway_url,
        llm_model=settings.mistral_model,
        mock_ehr_base_url=settings.agentcare_mock_ehr_url,
        cal_api_key=settings.cal_api_key,
        cal_event_type_id=settings.cal_event_type_id,
        cal_timezone=settings.cal_timezone,
        calendar_tool_mode=calendar_tool_mode,  # type: ignore[arg-type]
    )
    out.write_text(json.dumps(spec, indent=2), "utf-8")
    print(f"[green]ok[/green] wrote `{out}`")


def _customer_store():
    return get_customer_store()


@customer_app.command("lookup")
def customer_lookup(
    query: str = typer.Option(..., "--query", help="Free-text customer search query"),
) -> None:
    """Lookup customer details from memory (ragfallback-aware, with lexical fallback)."""
    store = _customer_store()
    out = store.semantic_lookup(query)
    _print_json(out)


@customer_app.command("upsert")
def customer_upsert(
    name: str | None = typer.Option(None, "--name"),
    email: str | None = typer.Option(None, "--email"),
    phone: str | None = typer.Option(None, "--phone"),
    summary: str | None = typer.Option(None, "--summary"),
    status: str | None = typer.Option(None, "--status"),
    appointment_id: str | None = typer.Option(None, "--appointment-id"),
    slot_start: str | None = typer.Option(None, "--slot-start"),
) -> None:
    """Create/update a customer profile from interaction data."""
    store = _customer_store()
    out = store.upsert_from_interaction(
        name=name,
        email=email,
        phone_e164=phone,
        summary=summary,
        status=status,
        appointment_id=appointment_id,
        slot_start=slot_start,
    )
    _print_json(out.__dict__)


@webhook_app.command("simulate")
def webhook_simulate(
    url: str = typer.Option("http://localhost:8030/bolna/execution", "--url", help="Webhook endpoint URL"),
    execution_id: str = typer.Option("exec_demo_001", "--execution-id"),
    customer_name: str = typer.Option("Ava Patel", "--customer-name"),
    customer_email: str = typer.Option("ava@example.com", "--customer-email"),
    customer_phone: str = typer.Option("+15550000001", "--customer-phone"),
    appointment_id: str = typer.Option("appt_00001", "--appointment-id"),
    slot_start: str = typer.Option("2026-03-10T10:30:00+00:00", "--slot-start"),
) -> None:
    """Send a synthetic Bolna execution payload to webhook endpoint."""
    payload = {
        "id": execution_id,
        "status": "completed",
        "conversation_time": 95.0,
        "transcript": (
            f"Patient {customer_name} confirmed booking. "
            f"Email is {customer_email}. "
            f"Phone is {customer_phone}. "
            f"Appointment ID: {appointment_id}. "
            f"Slot: {slot_start}."
        ),
        "extracted_data": {
            "customer_name": customer_name,
            "customer_email": customer_email,
            "customer_phone": customer_phone,
            "appointment_id": appointment_id,
            "slot_start": slot_start,
            "reason": "Follow-up consultation",
            "summary": "Booked follow-up successfully.",
        },
        "telephony_data": {"to_number": customer_phone},
    }
    resp = httpx.post(url, json=payload, timeout=20.0)
    _print_json({"status_code": resp.status_code, "response": resp.json()})


@framework_app.command("init-db")
def framework_init_db() -> None:
    """Initialize postgres schema for customer memory + idempotency."""
    if not settings.database_url:
        raise typer.BadParameter("Set DATABASE_URL/SUPABASE_DB_URL (direct postgres connection string)")
    init_postgres_schema(settings.database_url)
    print("[green]ok[/green] initialized postgres schema")


@framework_app.command("provider-test")
def framework_provider_test() -> None:
    """Quickly validate provider key wiring and local services."""
    results = {
        "bolna_api_key": bool(settings.bolna_api_key),
        "mistral_api_key": bool(settings.mistral_api_key),
        "resend_api_key": bool(settings.resend_api_key),
        "cal_api_key": bool(settings.cal_api_key),
        "cal_event_type_id": bool(settings.cal_event_type_id),
        "cal_timezone": settings.cal_timezone,
        "appointment_connector_backend": settings.appointment_connector_backend,
        "frontdesk_policy_path": settings.frontdesk_policy_path,
        "database_url": bool(settings.database_url),
    }
    _print_json(results)


@framework_app.command("list-workflows")
def framework_list_workflows() -> None:
    """List available reusable workflow templates."""
    _print_json({"workflows": list_workflows_metadata()})


@framework_app.command("create-agent")
def framework_create_agent(
    workflow: str = typer.Option("frontdesk_booking", "--workflow", help="Workflow template name"),
) -> None:
    """Create Bolna agent directly from workflow registry."""
    if workflow not in WORKFLOW_REGISTRY:
        available = ", ".join(sorted(WORKFLOW_REGISTRY.keys()))
        raise typer.BadParameter(f"Unknown --workflow '{workflow}'. Available: {available}")
    orchestrator = Orchestrator()
    out = orchestrator.create_agent_from_workflow(workflow)
    _print_json(out)


@framework_app.command("process-execution")
def framework_process_execution(
    execution_json: Path = typer.Option(..., "--execution-json", exists=True, dir_okay=False),
    source: str = typer.Option("manual", "--source"),
    automate_actions: bool = typer.Option(True, "--automate-actions/--no-automate-actions"),
    enforce_idempotency: bool = typer.Option(False, "--enforce-idempotency/--no-enforce-idempotency"),
) -> None:
    """
    Process one execution payload through the reusable frontdesk pipeline.
    Useful for framework-level integration testing and custom ingestion sources.
    """
    payload = json.loads(execution_json.read_text("utf-8"))
    if not isinstance(payload, dict):
        raise typer.BadParameter("--execution-json must contain a JSON object")
    res = process_frontdesk_execution(
        payload,
        source=source,
        automate_actions=automate_actions,
        enforce_idempotency=enforce_idempotency,
    )
    _print_json(res.__dict__)


@app.command("up")
def up(
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate env + print startup plan only"),
    health_timeout_sec: int = typer.Option(20, "--health-timeout-sec", min=3, max=120),
) -> None:
    """Start the full local AgentCare stack and verify health."""
    env_status = _required_runtime_env_summary()
    specs = _service_specs()
    logs_dir = Path("artifacts/runtime-logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "services": specs,
        "env_configured": env_status,
        "logs_dir": str(logs_dir),
    }
    if dry_run:
        _print_json({"ok": True, "dry_run": True, **plan})
        return

    started: list[dict[str, Any]] = []
    for spec in specs:
        script_path = Path(spec["script"])
        log_path = logs_dir / f"{spec['name']}.log"
        if not script_path.exists():
            started.append({"name": spec["name"], "ok": False, "error": "script_missing"})
            continue
        with log_path.open("ab") as fh:
            proc = subprocess.Popen(  # noqa: S603
                ["/bin/bash", str(script_path)],
                stdout=fh,
                stderr=fh,
                env=os.environ.copy(),
            )
        started.append(
            {
                "name": spec["name"],
                "pid": proc.pid,
                "log": str(log_path),
                "health": spec["health"],
            }
        )

    deadline = time.time() + health_timeout_sec
    health: list[dict[str, Any]] = []
    for item in started:
        url = item.get("health")
        ok = False
        last_error: str | None = None
        while time.time() < deadline:
            try:
                r = httpx.get(str(url), timeout=2.5)
                if r.status_code < 500:
                    ok = True
                    break
                last_error = f"http_{r.status_code}"
            except Exception as e:
                last_error = str(e)
            time.sleep(0.6)
        health.append(
            {
                "name": item["name"],
                "pid": item.get("pid"),
                "ok": ok,
                "health": url,
                "log": item.get("log"),
                "error": None if ok else last_error,
            }
        )

    _print_json(
        {
            "ok": all(h["ok"] for h in health),
            "env_configured": env_status,
            "services": health,
            "urls": {
                "llm_gateway": "http://127.0.0.1:8010",
                "mock_ehr": "http://127.0.0.1:8020",
                "webhooks": "http://127.0.0.1:8030",
                "analytics": "http://127.0.0.1:8040",
                "dashboard": "http://127.0.0.1:8050",
            },
        }
    )


@extract_app.command("transcript")
def extract_transcript(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Transcript text file"),
) -> None:
    """Extract strict healthcare fields from transcript text."""
    transcript = path.read_text("utf-8")
    out = extract_conversation_fields(transcript).model_dump()
    _print_json(out)


def main() -> None:
    app()

