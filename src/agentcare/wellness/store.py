from __future__ import annotations

from pathlib import Path
from typing import Any

from agentcare._jsonio import read_json, write_json_atomic
from agentcare.settings import settings


class JsonWellnessHistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        data: dict[str, list[dict[str, Any]]] = read_json(self.path, {}, expected=dict)
        return data

    def _write(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        write_json_atomic(self.path, rows)

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
