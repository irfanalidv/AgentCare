"""Policies, doctor routing, workflow registry, templates and the orchestrator."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agentcare.analysis import analyze_healthcare_context
from agentcare.doctor import assign_doctor, load_doctor_schema
from agentcare.orchestrator import runtime
from agentcare.policies import evaluate_frontdesk_policy, evaluate_wellness_policy
from agentcare.providers import ProviderFactory
from agentcare.settings import settings
from agentcare.templates import build_frontdesk_agent_spec
from agentcare.workflows import get_workflow_definition, list_workflows_metadata


def test_frontdesk_policy_defaults(offline):
    d = evaluate_frontdesk_policy(intent="new_appointment", risk_level="low")
    assert d.allow_auto_booking and not d.escalation_required and d.follow_up_sla_hours == 24
    d = evaluate_frontdesk_policy(intent="new_appointment", risk_level="high")
    assert not d.allow_auto_booking and d.escalation_required
    assert d.triage_queue == "clinical_triage" and d.reason == "risk_blocked_auto_booking:high"
    d = evaluate_frontdesk_policy(intent=None, risk_level=None)
    assert d.reason == "intent_blocked_auto_booking:other"


def test_frontdesk_policy_file(offline, monkeypatch, tmp_path, caplog):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps({"intent_rules": {"other": {"allow_auto_booking": True, "sla_hours": 4}}})
    )
    monkeypatch.setattr(settings, "frontdesk_policy_path", str(path))
    d = evaluate_frontdesk_policy(intent="anything", risk_level="low")
    assert d.allow_auto_booking and d.follow_up_sla_hours == 4

    path.write_text("{oops")
    with caplog.at_level("WARNING"):
        assert evaluate_frontdesk_policy(intent="other", risk_level="low").follow_up_sla_hours == 24
    assert "unreadable policy file" in caplog.text


@pytest.mark.parametrize(
    "kwargs, target, sla",
    [
        ({"risk_band": "low", "high_acuity_flag": True}, "confidential_human_followup", 1),
        ({"risk_band": "high", "high_acuity_flag": False}, "confidential_human_followup", 24),
        (
            {"risk_band": "low", "high_acuity_flag": False, "triage_trigger": True},
            "confidential_human_followup",
            24,
        ),
        ({"risk_band": "medium", "high_acuity_flag": False}, "manager_check_in", 72),
        (
            {"risk_band": "low", "high_acuity_flag": False, "trend_direction": "deteriorating"},
            "manager_check_in",
            72,
        ),
        ({"risk_band": "low", "high_acuity_flag": False}, "none", 168),
    ],
)
def test_wellness_policy(kwargs, target, sla):
    d = evaluate_wellness_policy(**kwargs)
    assert (d.escalation_target, d.follow_up_sla_hours) == (target, sla)


def test_healthcare_analysis_risk_levels():
    high = analyze_healthcare_context(transcript="sudden chest pain", reason=None, intent=None)
    assert (high.risk_level, high.urgency_level, high.care_category) == (
        "high",
        "urgent",
        "cardio_metabolic",
    )
    medium = analyze_healthcare_context(transcript="severe back pain", reason=None, intent=None)
    assert medium.risk_level == "medium" and medium.needs_clinical_followup
    ops = analyze_healthcare_context(transcript="move my slot", reason=None, intent="reschedule")
    assert ops.follow_up_recommendation == "appointment_ops_support"
    empty = analyze_healthcare_context(transcript=None, reason=None, intent=None)
    assert empty.follow_up_recommendation == "capture_more_details"


def test_doctor_routing(offline, tmp_path, caplog):
    assert assign_doctor(reason="itchy skin rash").doctor_specialty == "Dermatology"
    assert assign_doctor(reason="general checkup").assignment_reason == "default_general_medicine"
    assert assign_doctor(reason="x", doctors=[]).doctor_id == "unassigned"
    bad = tmp_path / "doctors.json"
    bad.write_text("[{}]")
    with caplog.at_level("WARNING"):
        assert load_doctor_schema(bad)[0].doctor_id == "dr_001"
    assert "invalid doctor schema" in caplog.text


def test_workflow_registry_and_templates(offline):
    names = [w["name"] for w in list_workflows_metadata()]
    assert names == [
        "care_navigation",
        "followup_outreach",
        "frontdesk_booking",
        "wellness_checkin",
    ]
    spec = get_workflow_definition("wellness_checkin").spec_builder()
    assert set(spec) >= {"agent_config", "agent_prompts"}
    with pytest.raises(ValueError, match="Unknown workflow"):
        get_workflow_definition("nope")
    custom = build_frontdesk_agent_spec(
        agent_name="Clinic Bot",
        llm_base_url="http://gw/v1",
        llm_model="mistral-small-latest",
        mock_ehr_base_url="http://ehr",
    )
    assert custom["agent_config"]["agent_name"] == "Clinic Bot"


def test_orchestrator_creates_agent(offline, monkeypatch):
    class FakeBolna:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def create_agent_v2(self, **kwargs):
            assert "agent_config" in kwargs
            return SimpleNamespace(agent_id="ag_1", status="created")

    monkeypatch.setattr(runtime.ProviderFactory, "bolna", staticmethod(lambda: FakeBolna()))
    out = runtime.Orchestrator().create_agent_from_workflow("frontdesk_booking")
    assert out == {
        "workflow": "frontdesk_booking",
        "category": "scheduling",
        "agent_id": "ag_1",
        "status": "created",
    }


def test_provider_factory_requires_keys(offline):
    with pytest.raises(ValueError, match="BOLNA_API_KEY"):
        ProviderFactory.bolna()
    with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
        ProviderFactory.mistral()
