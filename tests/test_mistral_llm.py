"""MistralLLM + JSON coercion with the SDK mocked (no network)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import agentcare
from agentcare.llm import mistral as mistral_mod
from agentcare.llm.mistral import MistralLLM, _coerce_json_object

ROOT = Path(__file__).resolve().parents[1]


class _FakeClient:
    def __init__(self, content):
        self._content = content
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(complete=self._complete)

    def _complete(self, **kwargs):
        self.calls.append(kwargs)
        msg = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _llm(monkeypatch, content) -> tuple[MistralLLM, _FakeClient]:
    fake = _FakeClient(content)
    def factory(api_key, **kwargs):
        fake.init_kwargs = kwargs
        return fake

    monkeypatch.setattr(mistral_mod, "Mistral", factory)
    return MistralLLM(api_key="k", model="mistral-small-latest"), fake


def test_chat_passes_model_and_returns_text(monkeypatch):
    llm, fake = _llm(monkeypatch, "hello")
    assert llm.chat(messages=[{"role": "user", "content": "hi"}]) == "hello"
    assert fake.calls[0]["model"] == "mistral-small-latest"


def test_chat_joins_content_chunks(monkeypatch):
    chunks = [SimpleNamespace(text="foo "), SimpleNamespace(text="bar")]
    llm, _ = _llm(monkeypatch, chunks)
    assert llm.chat(messages=[]) == "foo bar"


def test_chat_json_parses_fenced_output(monkeypatch):
    llm, fake = _llm(monkeypatch, '```json\n{"intent": "book"}\n```')
    assert llm.chat_json(system="s", user="u") == {"intent": "book"}
    assert [m["role"] for m in fake.calls[0]["messages"]] == ["system", "user"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```\n{"json_field": "json"}\n```', {"json_field": "json"}),
        ('Sure! Here it is: {"a": {"b": 2}} Thanks.', {"a": {"b": 2}}),
    ],
)
def test_coerce_json_object(text, expected):
    assert _coerce_json_object(text) == expected


def test_coerce_json_object_rejects_non_object():
    with pytest.raises(ValueError):
        _coerce_json_object("[1, 2, 3]")


def test_cli_version_flag():
    proc = subprocess.run(
        [sys.executable, "-m", "agentcare", "--version"],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0
    assert agentcare.__version__ in proc.stdout


def test_client_gets_a_timeout(monkeypatch):
    llm, fake = _llm(monkeypatch, "x")
    assert fake.init_kwargs == {"timeout_ms": 30_000}


def test_unexpected_response_shape_falls_back_to_str(monkeypatch):
    fake = SimpleNamespace(chat=SimpleNamespace(complete=lambda **kw: SimpleNamespace(choices=[])))
    monkeypatch.setattr(mistral_mod, "Mistral", lambda api_key, **kw: fake)
    out = MistralLLM(api_key="k", model="m").chat(messages=[])
    assert "choices=[]" in out
