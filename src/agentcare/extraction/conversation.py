from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agentcare.llm import MistralLLM
from agentcare.settings import settings


class ConversationExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    patient_name: str | None = None
    patient_phone: str | None = None
    patient_email: str | None = None
    language_preference: Literal["english", "hindi"] | None = None
    intent: (
        Literal[
            "new_appointment",
            "reschedule",
            "cancel",
            "appointment_status",
            "care_coordination",
            "other",
        ]
        | None
    ) = None
    preferred_date_or_window: str | None = None
    visit_type: Literal["new", "follow_up"] | None = None
    reason_for_visit: str | None = None
    appointment_id: str | None = None
    follow_up_required: bool | None = None
    summary: str | None = None


EXTRACTION_SYSTEM_PROMPT = """Extract a strict JSON object from the conversation.
Use null for unknown values. Do not invent facts.

Return ONLY valid JSON with this exact schema:
{
  "patient_name": "string|null",
  "patient_phone": "string|null",
  "patient_email": "string|null",
  "language_preference": "english|hindi|null",
  "intent": "new_appointment|reschedule|cancel|appointment_status|care_coordination|other|null",
  "preferred_date_or_window": "string|null",
  "visit_type": "new|follow_up|null",
  "reason_for_visit": "string|null",
  "appointment_id": "string|null",
  "follow_up_required": "boolean|null",
  "summary": "string|null"
}
"""


def extract_conversation_fields(transcript: str) -> ConversationExtraction:
    """
    Built-in transcript extraction mechanism.
    Returns schema-constrained output, defaults to null fields if model unavailable.
    """
    if not transcript.strip():
        return ConversationExtraction()
    if not settings.mistral_api_key:
        return ConversationExtraction()

    llm = MistralLLM(api_key=settings.mistral_api_key, model=settings.mistral_model)
    try:
        data = llm.chat_json(
            system=EXTRACTION_SYSTEM_PROMPT,
            user=transcript,
            temperature=0.0,
            max_tokens=500,
        )
        return ConversationExtraction.model_validate(data)
    except Exception:
        return ConversationExtraction()

