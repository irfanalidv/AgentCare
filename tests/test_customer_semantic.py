"""Semantic customer lookup with ragfallback mocked (no models, no network)."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from agentcare.customer.memory import _rag_vector_lookup

ROWS = [
    {"customer_id": "c1", "name": "Asha", "last_summary": "knee pain", "notes": []},
    {"customer_id": "c2", "name": "Bob", "last_summary": "dental", "notes": ["am"]},
]


@pytest.fixture
def fake_ragfallback(monkeypatch):
    pytest.importorskip("langchain_core")
    seen: dict = {}

    class _Store:
        def __init__(self, docs):
            self.docs = docs

        def similarity_search(self, query, k):
            hits = [d for d in self.docs if "knee" in d.page_content and "knee" in query]
            return [SimpleNamespace(metadata=d.metadata) for d in hits][:k]

    def create_faiss_vector_store(docs, embeddings):
        seen["docs"] = docs
        return _Store(docs)

    utils = types.ModuleType("ragfallback.utils")
    utils.create_open_source_embeddings = lambda: object()
    utils.create_faiss_vector_store = create_faiss_vector_store
    pkg = types.ModuleType("ragfallback")
    pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "ragfallback", pkg)
    monkeypatch.setitem(sys.modules, "ragfallback.utils", utils)
    return seen


def test_vector_lookup_finds_customer(fake_ragfallback):
    out = _rag_vector_lookup(ROWS, "patient with knee pain")
    assert out["found"] is True, out
    assert out["customer"]["customer_id"] == "c1"
    assert len(fake_ragfallback["docs"]) == 2


def test_vector_lookup_no_match(fake_ragfallback):
    out = _rag_vector_lookup(ROWS, "billing question")
    assert out == {"found": False, "engine": "ragfallback_vector", "reason": "no_match"}


def test_vector_lookup_without_ragfallback_reports_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "ragfallback", None)
    monkeypatch.setitem(sys.modules, "ragfallback.utils", None)
    out = _rag_vector_lookup(ROWS, "knee")
    assert out["found"] is False and out["reason"] == "error"
