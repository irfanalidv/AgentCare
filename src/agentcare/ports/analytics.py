from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AnalyticsStorePort(Protocol):
    def persist_call_event(self, **kwargs: Any) -> dict[str, Any]: ...

    def persist_call_lifecycle_event(self, **kwargs: Any) -> dict[str, Any]: ...
