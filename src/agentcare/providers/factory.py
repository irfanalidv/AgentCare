from __future__ import annotations

from agentcare.bolna import BolnaClient
from agentcare.llm import MistralLLM
from agentcare.settings import settings


class ProviderFactory:
    @staticmethod
    def bolna() -> BolnaClient:
        if not settings.bolna_api_key:
            raise ValueError("BOLNA_API_KEY not configured")
        return BolnaClient(api_key=settings.bolna_api_key, base_url=settings.bolna_base_url)

    @staticmethod
    def mistral() -> MistralLLM:
        if not settings.mistral_api_key:
            raise ValueError("MISTRAL_API_KEY not configured")
        return MistralLLM(api_key=settings.mistral_api_key, model=settings.mistral_model)

