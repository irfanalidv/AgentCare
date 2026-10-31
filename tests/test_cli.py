"""CLI commands via Typer's CliRunner (offline)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from agentcare import __version__
from agentcare.cli import app

runner = CliRunner()


def _json(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and __version__ in result.output


def test_doctor_reports_configuration_without_secrets(offline):
    out = _json(runner.invoke(app, ["doctor"]))
    assert out["mistral_api_key_configured"] is False
    assert all("key" not in k or k.endswith("_configured") for k in out)


def test_list_workflows(offline):
    names = [
        w["name"] for w in _json(runner.invoke(app, ["framework", "list-workflows"]))["workflows"]
    ]
    assert "wellness_checkin" in names


def test_templates_frontdesk_writes_spec(offline, tmp_path):
    out = tmp_path / "spec.json"
    result = runner.invoke(
        app, ["templates", "frontdesk", "--out", str(out), "--agent-name", "Clinic"]
    )
    assert result.exit_code == 0
    assert json.loads(out.read_text())["agent_config"]["agent_name"] == "Clinic"


def test_customer_upsert_and_lookup(offline):
    created = _json(
        runner.invoke(
            app,
            [
                "customer",
                "upsert",
                "--name",
                "Ava",
                "--email",
                "ava@x.com",
                "--summary",
                "knee pain",
            ],
        )
    )
    assert created["customer_id"] == "cust_000001"
    found = _json(runner.invoke(app, ["customer", "lookup", "--query", "knee"]))
    assert found["found"] and found["customer"]["email"] == "ava@x.com"


def test_process_execution_wellness(offline, tmp_path):
    payload = tmp_path / "ex.json"
    payload.write_text(
        json.dumps(
            {
                "id": "w1",
                "employee_id": "emp_7",
                "transcript": "I feel drained and overwhelmed, working late every night.",
            }
        )
    )
    out = _json(
        runner.invoke(
            app,
            [
                "framework",
                "process-execution",
                "--execution-json",
                str(payload),
                "--workflow",
                "wellness_checkin",
            ],
        )
    )
    assert out["workflow"] == "wellness_checkin" and out["persisted"] is True
    assert out["analysis"]["ee_hits"] >= 2


def test_extract_transcript_without_key_returns_nulls(offline, tmp_path):
    path = tmp_path / "t.txt"
    path.write_text("Patient wants an appointment")
    out = _json(runner.invoke(app, ["extract", "transcript", str(path)]))
    assert out["intent"] is None


def test_init_artifacts(offline, tmp_path):
    result = runner.invoke(app, ["init-artifacts", "--dir", str(tmp_path / "a")])
    assert result.exit_code == 0 and (tmp_path / "a").is_dir()
