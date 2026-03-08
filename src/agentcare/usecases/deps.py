from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agentcare.analysis import analyze_healthcare_context
from agentcare.analytics import persist_call_event, persist_call_lifecycle_event
from agentcare.connectors import get_appointment_connector
from agentcare.customer import get_customer_store
from agentcare.doctor import assign_doctor
from agentcare.email import send_confirmation_email
from agentcare.extraction import extract_conversation_fields
from agentcare.policies import evaluate_frontdesk_policy
from agentcare.ports.appointments import AppointmentConnectorPort
from agentcare.ports.customer_store import CustomerStorePort


@dataclass
class FrontdeskDeps:
    store: CustomerStorePort
    connector: AppointmentConnectorPort
    extract_fields: Callable[[str], Any]
    send_confirmation_email: Callable[..., dict[str, Any]]
    persist_call_event: Callable[..., dict[str, Any]]
    persist_call_lifecycle_event: Callable[..., dict[str, Any]]
    assign_doctor: Callable[..., Any]
    analyze_healthcare_context: Callable[..., Any]
    evaluate_frontdesk_policy: Callable[..., Any]


def build_frontdesk_deps() -> FrontdeskDeps:
    return FrontdeskDeps(
        store=get_customer_store(),
        connector=get_appointment_connector(),
        extract_fields=extract_conversation_fields,
        send_confirmation_email=send_confirmation_email,
        persist_call_event=persist_call_event,
        persist_call_lifecycle_event=persist_call_lifecycle_event,
        assign_doctor=assign_doctor,
        analyze_healthcare_context=analyze_healthcare_context,
        evaluate_frontdesk_policy=evaluate_frontdesk_policy,
    )
