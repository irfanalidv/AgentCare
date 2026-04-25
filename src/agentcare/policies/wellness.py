"""Policy decisions for wellness check-in outcomes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WellnessPolicyDecision:
    allow_auto_close: bool
    escalation_required: bool
    escalation_target: str
    follow_up_sla_hours: int
    reason: str


def evaluate_wellness_policy(
    *,
    risk_band: str | None,
    high_acuity_flag: bool,
    trend_direction: str | None = None,
    triage_trigger: bool = False,
) -> WellnessPolicyDecision:
    band = (risk_band or "low").strip().lower()
    direction = (trend_direction or "stable").strip().lower()

    if high_acuity_flag:
        return WellnessPolicyDecision(
            allow_auto_close=False,
            escalation_required=True,
            escalation_target="confidential_human_followup",
            follow_up_sla_hours=1,
            reason="high_acuity_crisis_signal",
        )

    if band == "high" or triage_trigger:
        return WellnessPolicyDecision(
            allow_auto_close=False,
            escalation_required=True,
            escalation_target="confidential_human_followup",
            follow_up_sla_hours=24,
            reason=f"high_risk_band:{band}|triage:{triage_trigger}",
        )

    if band == "medium" or direction == "deteriorating":
        return WellnessPolicyDecision(
            allow_auto_close=False,
            escalation_required=True,
            escalation_target="manager_check_in",
            follow_up_sla_hours=72,
            reason=f"medium_risk_or_deteriorating:{band}|{direction}",
        )

    return WellnessPolicyDecision(
        allow_auto_close=True,
        escalation_required=False,
        escalation_target="none",
        follow_up_sla_hours=168,
        reason="low_risk_stable",
    )
