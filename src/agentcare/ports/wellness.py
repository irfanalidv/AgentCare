from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WellnessHistoryStorePort(Protocol):
    def load_scores(self, employee_id: str) -> list[float]: ...

    def append_entry(self, employee_id: str, entry: dict[str, Any]) -> None: ...
