"""Burnout-aware LLM extraction layer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentcare.llm import MistralLLM
from agentcare.settings import settings


class BurnoutExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    employee_name: str | None = None
    role_or_team: str | None = None
    language_preference: Literal["english", "hindi"] | None = None
    emotional_exhaustion_0_10: int | None = Field(default=None, ge=0, le=10)
    depersonalisation_0_10: int | None = Field(default=None, ge=0, le=10)
    reduced_accomplishment_0_10: int | None = Field(default=None, ge=0, le=10)
    primary_stressor: Literal[
        "workload",
        "interpersonal",
        "role_clarity",
        "autonomy",
        "recognition",
        "values_misalignment",
        "personal_life",
        "unclear",
    ] | None = None
    engagement_level: Literal["high", "medium", "low"] | None = None
    sleep_disrupted: bool | None = None
    physical_symptoms_reported: bool | None = None
    crisis_signal: bool | None = None
    crisis_notes: str | None = None
    summary: str | None = None
    quote_evidence: list[str] = Field(default_factory=list)


BURNOUT_EXTRACTION_SYSTEM_PROMPT = """You are an analyst extracting burnout signals from a workplace wellness check-in transcript.

You are NOT a clinician. You do NOT diagnose. You produce a strict JSON object that scores observable conversational signals against the three Maslach Burnout Inventory (MBI) dimensions:

1. EMOTIONAL EXHAUSTION (0-10): explicit fatigue, depletion, "drained", "burnt out", inability to recover, sleep disruption from work, working extended hours, emotional depletion. Higher = more exhausted.
2. DEPERSONALISATION (0-10): cynicism, detachment, "going through the motions", "checked out", apathy, negative attitude toward work or colleagues, loss of engagement. Higher = more depersonalised.
3. REDUCED ACCOMPLISHMENT (0-10): feelings of ineffectiveness, "not making a difference", missed deadlines, performance decline, loss of confidence/motivation, impostor language. Higher = more reduced accomplishment.

Scoring rules:
- 0 = no signal at all in this conversation
- 1-3 = mild / fleeting mention
- 4-6 = moderate, recurring or substantive mention
- 7-10 = severe, multiple strong signals across the conversation
- Use null only if the conversation is too short or off-topic to score
- Do NOT invent signals. Anchor every non-zero score to the actual transcript.

Crisis signals (set crisis_signal=true and populate crisis_notes):
- Suicidal ideation, self-harm references, "want to die", "can't go on", explicit breakdown.

quote_evidence: include up to 4 SHORT verbatim quotes (under 20 words each) from the transcript that justify your scores. If no clear evidence, use an empty array.

Return ONLY valid JSON with this exact schema:
{
  "employee_name": "string|null",
  "role_or_team": "string|null",
  "language_preference": "english|hindi|null",
  "emotional_exhaustion_0_10": "integer 0-10 or null",
  "depersonalisation_0_10": "integer 0-10 or null",
  "reduced_accomplishment_0_10": "integer 0-10 or null",
  "primary_stressor": "workload|interpersonal|role_clarity|autonomy|recognition|values_misalignment|personal_life|unclear|null",
  "engagement_level": "high|medium|low|null",
  "sleep_disrupted": "boolean|null",
  "physical_symptoms_reported": "boolean|null",
  "crisis_signal": "boolean|null",
  "crisis_notes": "string|null",
  "summary": "string|null",
  "quote_evidence": ["string", "..."]
}

No markdown, no code fences, no commentary. JSON only.
"""


def extract_burnout_fields(transcript: str) -> BurnoutExtraction:
    if not transcript or not transcript.strip():
        return BurnoutExtraction()
    if not settings.mistral_api_key:
        return BurnoutExtraction()

    llm = MistralLLM(api_key=settings.mistral_api_key, model=settings.mistral_model)
    try:
        data = llm.chat_json(
            system=BURNOUT_EXTRACTION_SYSTEM_PROMPT,
            user=transcript,
            temperature=0.0,
            max_tokens=700,
        )
        return BurnoutExtraction.model_validate(data)
    except Exception:
        return BurnoutExtraction()
