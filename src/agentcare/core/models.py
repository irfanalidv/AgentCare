from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FrameworkContext:
    workflow_name: str
    customer_id: str | None = None
    execution_id: str | None = None

