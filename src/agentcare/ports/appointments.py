from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentcare.connectors.appointments import BookingResult, SlotCheckResult


@runtime_checkable
class AppointmentConnectorPort(Protocol):
    def check_slots(self, *, preferred_date_or_window: str | None, execution_id: str | None) -> SlotCheckResult: ...

    def book_slot(
        self,
        *,
        patient_name: str | None,
        patient_email: str | None,
        patient_phone: str | None,
        reason: str | None,
        doctor_name: str | None,
        doctor_specialty: str | None,
        visit_type: str | None,
        summary: str | None,
        preferred_date_or_window: str | None,
        slot_start_iso: str | None,
        execution_id: str | None,
    ) -> BookingResult: ...
