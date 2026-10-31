"""Thin wrapper over the Mistral chat API with JSON-object coercion."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, cast

try:  # mistralai >= 2 moved the client under ``mistralai.client``
    from mistralai.client import Mistral
except ImportError:  # mistralai 1.x
    from mistralai import Mistral  # type: ignore[no-redef,attr-defined,unused-ignore]

logger = logging.getLogger(__name__)

#: Default per-request timeout. The SDK has no timeout unless one is given.
DEFAULT_TIMEOUT_S = 30.0


class MistralLLM:
    """Minimal chat client used by extraction, evaluation and summary polishing.

    Args:
        api_key: Mistral API key.
        model: Chat model name, e.g. ``"mistral-small-latest"``.
        timeout_s: Per-request timeout in seconds (the SDK default is unbounded).
    """

    def __init__(self, *, api_key: str, model: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._client = Mistral(api_key=api_key, timeout_ms=int(timeout_s * 1000))
        self._model = model

    def chat(
        self, *, messages: list[dict[str, Any]], temperature: float = 0.2, max_tokens: int = 800
    ) -> str:
        """Return the assistant text for ``messages`` (OpenAI-style role/content dicts)."""
        resp = self._client.chat.complete(
            model=self._model,
            messages=cast(Any, messages),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        # SDK response is a Pydantic model; keep extraction defensive.
        try:
            content = cast(Any, resp).choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            logger.warning("Unexpected Mistral response shape: %r", resp)
            return str(resp)
        if isinstance(content, list):  # content chunks (newer SDKs / some models)
            return "".join(getattr(c, "text", "") or "" for c in content)
        return content or ""

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 900,
    ) -> dict[str, Any]:
        """Chat with a system + user message and parse the reply as a JSON object.

        Raises:
            ValueError: the reply contains no JSON object.
        """
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
    cleaned = (text or "").strip()
    fence = re.match(r"^```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?```\s*$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    # Try direct parse
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Try to locate the first {...} block
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(cleaned[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    raise ValueError("Model did not return a JSON object")
