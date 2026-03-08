from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


class AgentCreateStatus(_Base):
    agent_id: str
    status: Literal["created"]


class MakeCallStatus(_Base):
    message: str
    status: Literal["queued"]
    execution_id: str


class Voice(_Base):
    id: str
    voice_id: str | None = None
    provider: str | None = None
    name: str | None = None
    model: str | None = None
    accent: str | None = None


class KnowledgebaseStatus(_Base):
    rag_id: str
    file_name: str
    status: Literal["processing", "processed", "error"] | None = None
    source_type: Literal["pdf", "url"] | None = None


class Knowledgebase(_Base):
    rag_id: str
    file_name: str | None = None
    status: Literal["processing", "processed"] | None = None
    vector_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    humanized_created_at: str | None = None
    chunk_size: int | None = None
    similarity_top_k: int | None = None
    overlapping: int | None = None


class TelephonyData(_Base):
    duration: str | None = None
    to_number: str | None = None
    from_number: str | None = None
    recording_url: str | None = None
    hosted_telephony: bool | None = None
    provider_call_id: str | None = None
    call_type: Literal["outbound", "inbound"] | None = None
    provider: Literal["twilio", "plivo"] | None = None
    hangup_by: str | None = None
    hangup_reason: str | None = None
    hangup_provider_code: int | None = None
    ring_duration: int | None = None
    post_dial_delay: int | None = None
    to_number_carrier: str | None = None


class CostBreakdown(_Base):
    llm: float | None = None
    network: float | None = None
    platform: float | None = None
    synthesizer: float | None = None
    transcriber: float | None = None


class AgentExecution(_Base):
    id: str
    agent_id: str | None = None
    status: str | None = None
    transcript: str | None = None
    extracted_data: dict[str, Any] | None = None
    context_details: dict[str, Any] | None = None

    conversation_time: float | None = None
    total_cost: float | None = None
    cost_breakdown: CostBreakdown | None = None
    telephony_data: TelephonyData | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None
    error_message: str | None = None
    answered_by_voice_mail: bool | None = None


class VoiceExecution(_Base):
    """
    Normalized execution object used by sync pipelines.
    Bolna may return either `id` or `execution_id` depending on endpoint.
    """

    id: str | None = None
    execution_id: str | None = None
    agent_id: str | None = None
    status: str | None = None
    transcript: str | None = None
    conversation_time: float | None = None
    total_cost: float | None = None
    telephony_data: dict[str, Any] | None = None
    extracted_data: dict[str, Any] | None = None
    context_details: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AddCustomModelResponse(_Base):
    message: str
    status: Literal["added"]


class DeleteKnowledgebaseResponse(_Base):
    message: str = Field(default="success")
    state: str | None = None

