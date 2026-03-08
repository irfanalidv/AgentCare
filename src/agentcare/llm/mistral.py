from __future__ import annotations

import json
from typing import Any

from mistralai import Mistral


class MistralLLM:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = Mistral(api_key=api_key)
        self._model = model

    def chat(self, *, messages: list[dict[str, Any]], temperature: float = 0.2, max_tokens: int = 800) -> str:
        resp = self._client.chat.complete(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # SDK response is a Pydantic model; keep extraction defensive.
        try:
            return resp.choices[0].message.content  # type: ignore[attr-defined]
        except Exception:
            return str(resp)

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 900,
    ) -> dict[str, Any]:
        content = self.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return _coerce_json_object(content)


def _coerce_json_object(text: str) -> dict[str, Any]:
    """
    Best-effort JSON object parsing.
    Mistral often returns clean JSON; this trims common code fences.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()
    # Try direct parse
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Try to locate the first {...} block
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(cleaned[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    raise ValueError("Model did not return a JSON object")

