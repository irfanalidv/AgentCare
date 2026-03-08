from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class NotificationSenderPort(Protocol):
    def send_confirmation_email(self, **kwargs: Any) -> dict[str, Any]: ...
