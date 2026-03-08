from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentcare.extraction.conversation import ConversationExtraction


@runtime_checkable
class TranscriptExtractorPort(Protocol):
    def extract_conversation_fields(self, transcript: str) -> ConversationExtraction: ...
