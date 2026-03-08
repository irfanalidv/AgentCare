from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class UpsertCustomerResult(Protocol):
    customer_id: str


@runtime_checkable
class CustomerStorePort(Protocol):
    def semantic_lookup(self, query: str) -> dict[str, Any]: ...

    def upsert_from_interaction(
        self,
        *,
        name: str | None = None,
        email: str | None = None,
        phone_e164: str | None = None,
        summary: str | None = None,
        status: str | None = None,
        appointment_id: str | None = None,
        slot_start: str | None = None,
        note: str | None = None,
    ) -> UpsertCustomerResult: ...

    def is_execution_processed(self, execution_id: str) -> bool: ...

    def mark_execution_processed(self, execution_id: str) -> None: ...
