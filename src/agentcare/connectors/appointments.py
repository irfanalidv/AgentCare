from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

import httpx

from agentcare.calendar import create_cal_booking, fetch_cal_slots
from agentcare.settings import settings


@dataclass
class SlotCheckResult:
    ok: bool
    chosen_start_iso: str | None
    slots_preview: list[str]
    error: str | None = None
    skipped: bool = False


@dataclass
class BookingResult:
    ok: bool
    booking_id: str | None
    start_iso: str | None
    error: str | None = None
    skipped: bool = False


class AppointmentConnector(Protocol):
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


class CalAppointmentConnector:
    def check_slots(self, *, preferred_date_or_window: str | None, execution_id: str | None) -> SlotCheckResult:
        r = fetch_cal_slots(preferred_date_or_window=preferred_date_or_window, execution_id=execution_id)
        return SlotCheckResult(
            ok=r.ok,
            chosen_start_iso=r.chosen_start_iso,
            slots_preview=(r.slots or [])[:5],
            error=r.error,
            skipped=r.skipped,
        )

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
    ) -> BookingResult:
        r = create_cal_booking(
            patient_name=patient_name,
            patient_email=patient_email,
            patient_phone=patient_phone,
            reason=reason,
            doctor_name=doctor_name,
            doctor_specialty=doctor_specialty,
            visit_type=visit_type,
            summary=summary,
            preferred_date_or_window=preferred_date_or_window,
            slot_start_iso=slot_start_iso,
            execution_id=execution_id,
        )
        return BookingResult(
            ok=r.ok,
            booking_id=r.booking_id,
            start_iso=r.start_iso,
            error=r.error,
            skipped=r.skipped,
        )


class MockAppointmentConnector:
    def check_slots(self, *, preferred_date_or_window: str | None, execution_id: str | None) -> SlotCheckResult:
        return SlotCheckResult(ok=True, chosen_start_iso=None, slots_preview=[], skipped=True, error="mock_connector")

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
    ) -> BookingResult:
        return BookingResult(ok=False, booking_id=None, start_iso=slot_start_iso, skipped=True, error="mock_connector")


class FHIRAppointmentConnector:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        auth_token: str | None = None,
        timeout_sec: float | None = None,
        schedule_id: str | None = None,
        slot_search_count: int | None = None,
        organization_id: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.fhir_base_url or "").rstrip("/")
        self.auth_token = auth_token or settings.fhir_auth_token
        self.timeout_sec = timeout_sec or settings.fhir_timeout_sec
        self.schedule_id = schedule_id or settings.fhir_schedule_id
        self.slot_search_count = max(1, slot_search_count or settings.fhir_slot_search_count or 20)
        self.organization_id = organization_id or settings.fhir_organization_id

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/fhir+json, application/json",
            "Content-Type": "application/fhir+json",
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _slot_search_params(self, preferred_date_or_window: str | None) -> dict[str, str]:
        params: dict[str, str] = {
            "status": "free",
            "_count": str(self.slot_search_count),
            "_sort": "start",
        }
        if self.schedule_id:
            params["schedule"] = self.schedule_id
        preferred = (preferred_date_or_window or "").strip()
        if preferred:
            iso = _normalize_start_iso(preferred)
            if iso:
                params["start"] = f"ge{iso}"
            else:
                params["start"] = preferred
        return params

    def _find_best_slot(
        self,
        *,
        preferred_date_or_window: str | None,
        execution_id: str | None,
    ) -> tuple[str | None, list[str], str | None, str | None]:
        if not self.base_url:
            return None, [], None, "fhir_base_url_missing"
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                resp = client.get(
                    f"{self.base_url}/Slot",
                    params=self._slot_search_params(preferred_date_or_window),
                    headers=self._headers(),
                )
            if resp.status_code >= 400:
                return None, [], None, f"fhir_slot_search_failed:{resp.status_code}"
            bundle = resp.json() if resp.content else {}
            slots = _extract_free_slots(bundle)
            if not slots:
                return None, [], None, "no_free_slots"
            chosen = slots[0]
            preview = [s["start"] for s in slots[:5] if s.get("start")]
            return chosen.get("start"), preview, chosen.get("id"), None
        except Exception as e:
            return None, [], None, f"fhir_slot_error:{e}"

    def check_slots(self, *, preferred_date_or_window: str | None, execution_id: str | None) -> SlotCheckResult:
        chosen, preview, _slot_id, error = self._find_best_slot(
            preferred_date_or_window=preferred_date_or_window,
            execution_id=execution_id,
        )
        return SlotCheckResult(
            ok=bool(chosen),
            chosen_start_iso=chosen,
            slots_preview=preview,
            error=error,
            skipped=False,
        )

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
    ) -> BookingResult:
        if not self.base_url:
            return BookingResult(ok=False, booking_id=None, start_iso=slot_start_iso, skipped=True, error="fhir_base_url_missing")

        chosen_start = _normalize_start_iso(slot_start_iso or "")
        chosen_slot_id: str | None = None
        if not chosen_start:
            chosen_start, _preview, chosen_slot_id, slot_error = self._find_best_slot(
                preferred_date_or_window=preferred_date_or_window,
                execution_id=execution_id,
            )
            if not chosen_start:
                return BookingResult(
                    ok=False,
                    booking_id=None,
                    start_iso=None,
                    skipped=False,
                    error=slot_error or "slot_not_available",
                )

        # Ensure end time exists for Appointment resource.
        end_iso = _derive_end_iso(chosen_start)
        appointment_payload = {
            "resourceType": "Appointment",
            "status": "booked",
            "description": reason or "Scheduled by AgentCare",
            "start": chosen_start,
            "end": end_iso,
            "comment": f"execution_id={execution_id or 'unknown'}",
            "identifier": [
                {
                    "system": "urn:agentcare:execution",
                    "value": execution_id or f"exec-{uuid4().hex[:12]}",
                }
            ],
            "participant": [
                {
                    "status": "accepted",
                    "actor": {
                        "display": patient_name or "Patient",
                        "identifier": {"system": "urn:agentcare:phone", "value": patient_phone or ""},
                    },
                }
            ],
        }
        if patient_email:
            appointment_payload["participant"][0]["actor"]["telecom"] = [{"system": "email", "value": patient_email}]
        if chosen_slot_id:
            appointment_payload["slot"] = [{"reference": f"Slot/{chosen_slot_id}"}]
        if self.organization_id:
            appointment_payload["basedOn"] = [{"reference": f"Organization/{self.organization_id}"}]

        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                resp = client.post(
                    f"{self.base_url}/Appointment",
                    headers=self._headers(),
                    json=appointment_payload,
                )
            if resp.status_code >= 400:
                return BookingResult(
                    ok=False,
                    booking_id=None,
                    start_iso=chosen_start,
                    skipped=False,
                    error=f"fhir_appointment_create_failed:{resp.status_code}",
                )
            body = resp.json() if resp.content else {}
            booking_id = str(body.get("id") or "")
            if not booking_id:
                return BookingResult(
                    ok=False,
                    booking_id=None,
                    start_iso=chosen_start,
                    skipped=False,
                    error="fhir_appointment_missing_id",
                )
            return BookingResult(ok=True, booking_id=booking_id, start_iso=chosen_start, skipped=False, error=None)
        except Exception as e:
            return BookingResult(
                ok=False,
                booking_id=None,
                start_iso=chosen_start,
                skipped=False,
                error=f"fhir_appointment_error:{e}",
            )


def _normalize_start_iso(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return f"{raw}T09:00:00+00:00"
    normalized = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def _derive_end_iso(start_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except Exception:
        dt = datetime.now(timezone.utc)
    return (dt + timedelta(minutes=30)).isoformat()


def _extract_free_slots(bundle: dict) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    entries = bundle.get("entry") or []
    if not isinstance(entries, list):
        return out
    for item in entries:
        resource = (item or {}).get("resource") or {}
        if not isinstance(resource, dict):
            continue
        if str(resource.get("resourceType") or "") != "Slot":
            continue
        if str(resource.get("status") or "").lower() != "free":
            continue
        slot_id = str(resource.get("id") or "")
        slot_start = _normalize_start_iso(str(resource.get("start") or ""))
        if slot_id and slot_start:
            out.append({"id": slot_id, "start": slot_start})
    out.sort(key=lambda r: r["start"])
    return out


def get_appointment_connector() -> AppointmentConnector:
    backend = settings.appointment_connector_backend.strip().lower()
    if backend == "mock":
        return MockAppointmentConnector()
    if backend == "fhir":
        return FHIRAppointmentConnector()
    return CalAppointmentConnector()
