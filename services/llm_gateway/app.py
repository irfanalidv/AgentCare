from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agentcare.llm import MistralLLM
from agentcare.settings import settings


app = FastAPI(title="AgentCare LLM Gateway", version="0.1.0")


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatCompletionsRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float = 0.2
    max_tokens: int = Field(default=800, ge=1, le=4096)
    stream: bool = False


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "mistral_api_key_configured": bool(settings.mistral_api_key),
        "default_model": settings.mistral_model,
    }


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    default = settings.mistral_model
    return {
        "object": "list",
        "data": [{"id": default, "object": "model", "owned_by": "agentcare"}],
    }


@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionsRequest) -> dict[str, Any]:
    if req.stream:
        raise HTTPException(status_code=400, detail="stream=true not supported by this gateway yet")
    if not settings.mistral_api_key:
        raise HTTPException(status_code=500, detail="MISTRAL_API_KEY not configured")

    model = req.model or settings.mistral_model
    llm = MistralLLM(api_key=settings.mistral_api_key, model=model)
    content = llm.chat(
        messages=[m.model_dump() for m in req.messages],
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )

    created = int(time.time())
    return {
        "id": f"chatcmpl_{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

