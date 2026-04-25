from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentcare.settings import settings


class JsonWellnessHistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self.path.write_text(json.dumps(rows, indent=2, default=str), "utf-8")

    def load_entries(self, employee_id: str) -> list[dict[str, Any]]:
        rows = self._read()
        entries = rows.get(employee_id, [])
        return entries if isinstance(entries, list) else []

    def load_scores(self, employee_id: str) -> list[float]:
        scores: list[float] = []
        for entry in self.load_entries(employee_id):
            try:
                scores.append(float(entry.get("composite_score", 0.0)))
            except (TypeError, ValueError):
                continue
        return scores

    def append_entry(self, employee_id: str, entry: dict[str, Any]) -> None:
        rows = self._read()
        entries = rows.setdefault(employee_id, [])
        entries.append(entry)
        self._write(rows)


def get_wellness_history_store() -> JsonWellnessHistoryStore:
    return JsonWellnessHistoryStore(Path(settings.wellness_history_store_path))
