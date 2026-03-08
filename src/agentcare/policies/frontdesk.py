from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agentcare.settings import settings


@dataclass
class FrontdeskPolicyDecision:
    allow_auto_booking: bool
    escalation_required: bool
    triage_queue: str
    follow_up_sla_hours: int
    reason: str


def _default_policy() -> dict:
    return {
        "risk_thresholds": {
            "block_auto_booking": ["high"],
            "escalation_required": ["high"],
        },
        "intent_rules": {
            "new_appointment": {"allow_auto_booking": True, "sla_hours": 24},
            "reschedule": {"allow_auto_booking": True, "sla_hours": 24},
            "appointment_status": {"allow_auto_booking": False, "sla_hours": 12},
            "care_coordination": {"allow_auto_booking": False, "sla_hours": 8},
            "other": {"allow_auto_booking": False, "sla_hours": 24},
        },
        "queues": {
            "default": "ops_frontdesk",
            "escalation": "clinical_triage",
        },
    }


def _load_policy() -> dict:
    path = settings.frontdesk_policy_path
    if path:
        p = Path(path)
        if p.exists():
            try:
                data = json.loads(p.read_text("utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return _default_policy()


def evaluate_frontdesk_policy(*, intent: str | None, risk_level: str | None) -> FrontdeskPolicyDecision:
    policy = _load_policy()
    risk = str(risk_level or "low").strip().lower()
    intent_key = str(intent or "other").strip().lower()

    risk_rules = policy.get("risk_thresholds") or {}
    block_auto_booking = set(risk_rules.get("block_auto_booking") or [])
    escalation_required_levels = set(risk_rules.get("escalation_required") or [])

    intent_rules = policy.get("intent_rules") or {}
    intent_rule = intent_rules.get(intent_key) or intent_rules.get("other") or {}

    allow_auto_booking = bool(intent_rule.get("allow_auto_booking", False))
    if risk in block_auto_booking:
        allow_auto_booking = False

    escalation_required = risk in escalation_required_levels
    queues = policy.get("queues") or {}
    triage_queue = queues.get("escalation") if escalation_required else queues.get("default", "ops_frontdesk")
    sla_hours = int(intent_rule.get("sla_hours", 24))

    reason = "policy_default"
    if risk in block_auto_booking:
        reason = f"risk_blocked_auto_booking:{risk}"
    elif not allow_auto_booking:
        reason = f"intent_blocked_auto_booking:{intent_key}"

    return FrontdeskPolicyDecision(
        allow_auto_booking=allow_auto_booking,
        escalation_required=escalation_required,
        triage_queue=str(triage_queue),
        follow_up_sla_hours=sla_hours,
        reason=reason,
    )
