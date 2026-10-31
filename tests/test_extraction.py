"""LLM extraction layers with MistralLLM faked (no network)."""

from __future__ import annotations

import pytest

from agentcare.eval.transcript import evaluate_transcript
from agentcare.extraction import (
    burnout,
    conversation,
    extract_burnout_fields,
    extract_conversation_fields,
)
from agentcare.settings import settings


class FakeLLM:
    def __init__(self, payload=None, error=None, **kwargs):
        self.payload, self.error = payload, error

    def chat_json(self, **kwargs):
        if self.error:
            raise self.error
        return self.payload


def use_llm(monkeypatch, module, **kw):
    monkeypatch.setattr(settings, "mistral_api_key", "test-key")
    monkeypatch.setattr(module, "MistralLLM", lambda **_: FakeLLM(**kw))


def test_no_key_or_empty_transcript_returns_empty(offline):
    assert extract_conversation_fields("hello").intent is None
    assert extract_conversation_fields("   ").intent is None
    assert extract_burnout_fields("I am tired").emotional_exhaustion_0_10 is None


def test_conversation_fields_validated(offline, monkeypatch):
    use_llm(
        monkeypatch,
        conversation,
        payload={"intent": "new_appointment", "patient_name": "Ava", "extra": 1},
    )
    out = extract_conversation_fields("I need an appointment")
    assert out.intent == "new_appointment" and out.patient_name == "Ava"


def test_invalid_llm_output_is_logged_not_raised(offline, monkeypatch, caplog):
    use_llm(monkeypatch, conversation, payload={"intent": "teleport"})
    with caplog.at_level("WARNING"):
        assert extract_conversation_fields("x").intent is None
    assert "Conversation extraction failed" in caplog.text


def test_burnout_fields(offline, monkeypatch, caplog):
    use_llm(
        monkeypatch,
        burnout,
        payload={"emotional_exhaustion_0_10": 8, "primary_stressor": "workload"},
    )
    out = extract_burnout_fields("drained every day")
    assert out.emotional_exhaustion_0_10 == 8 and out.primary_stressor == "workload"
    use_llm(monkeypatch, burnout, error=TimeoutError("slow"))
    with caplog.at_level("WARNING"):
        assert extract_burnout_fields("drained").emotional_exhaustion_0_10 is None
    assert "TimeoutError" in caplog.text


def test_evaluate_transcript():
    llm = FakeLLM(
        payload={
            "overall_score_0_to_10": 8,
            "summary": "Polite and correct.",
            "empathy_score_0_to_10": 9,
            "correctness_score_0_to_10": 8,
            "brevity_score_0_to_10": 7,
            "next_best_action_score_0_to_10": 8,
            "safety_flags": ["phi_leak"],
        }
    )
    out = evaluate_transcript(llm=llm, transcript="...", context={"clinic": "x"})
    assert out.overall_score_0_to_10 == 8 and out.safety_flags == ["phi_leak"]
    with pytest.raises(ValueError):
        evaluate_transcript(llm=FakeLLM(payload={"summary": "missing scores"}), transcript="x")
