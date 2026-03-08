from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.analytics.app import app


def test_analytics_call_detail_fallback_includes_summaries(tmp_path: Path, monkeypatch) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    event_path = artifacts / "call_events.json"
    event_path.write_text(
        json.dumps(
            [
                {
                    "execution_id": "exec_detail_001",
                    "status": "completed",
                    "extracted_data": {
                        "intent": "new_appointment",
                        "patient_facing_summary": "Patient requested a follow-up.",
                        "internal_ops_summary": "intent=new_appointment | note=Follow-up required.",
                    },
                }
            ]
        ),
        "utf-8",
    )
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)
    resp = client.get("/analytics/calls/exec_detail_001")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["row"]["patient_facing_summary"] == "Patient requested a follow-up."
    assert "internal_ops_summary" in payload["row"]
