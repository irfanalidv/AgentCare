"""sync_bolna_executions with the Bolna client and pipeline stubbed out."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcare.bolna.models import VoiceExecution
from agentcare.settings import settings
from agentcare.sync import bolna_sync


class FakeBolna:
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def get_all_executions(self, **kwargs):
        return [
            VoiceExecution(id="done", status="completed", transcript="hi"),
            VoiceExecution(id="live", status="in-progress"),
        ]


def test_sync_only_marks_completed_calls_as_automated(offline, monkeypatch):
    monkeypatch.setattr(settings, "bolna_api_key", "bn_test")
    monkeypatch.setattr(bolna_sync, "BolnaClient", FakeBolna)
    calls = []

    def fake_process(ex, **kwargs):
        calls.append((ex["id"], kwargs["automate_actions"]))
        return SimpleNamespace(customer_id="cust_1")

    monkeypatch.setattr(bolna_sync, "process_agentcare_execution", fake_process)

    out = bolna_sync.sync_bolna_executions(agent_id="ag", out_path=Path("artifacts/s.json"))
    assert out["processed_executions"] == 2
    assert out["automated_executions"] == 1
    marked = json.loads(Path("artifacts/automation_processed.json").read_text())
    # Regression: the in-progress call must stay eligible for automation later.
    assert marked == ["done"]

    calls.clear()
    bolna_sync.sync_bolna_executions(agent_id="ag", out_path=Path("artifacts/s.json"))
    assert dict(calls) == {"done": False, "live": True}


def test_sync_requires_api_key(offline):
    with pytest.raises(ValueError, match="BOLNA_API_KEY"):
        bolna_sync.sync_bolna_executions(agent_id="ag")
