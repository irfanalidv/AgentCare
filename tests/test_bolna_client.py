"""BolnaClient against an in-memory HTTP transport (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agentcare.bolna import BolnaClient
from agentcare.bolna.errors import BolnaAuthError, BolnaRequestError


def make_client(handler) -> tuple[BolnaClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = BolnaClient(api_key="bn_test", base_url="https://bolna.test/")
    client._client = httpx.Client(
        base_url="https://bolna.test",
        transport=httpx.MockTransport(wrapped),
        headers={"Authorization": "Bearer bn_test"},
    )
    return client, seen


def test_create_agent_and_call():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/agent":
            return httpx.Response(200, json={"agent_id": "ag_1", "status": "created"})
        body = json.loads(req.content)
        assert body == {
            "agent_id": "ag_1",
            "recipient_phone_number": "+15550001",
            "from_phone_number": "+15559999",
            "user_data": {"name": "Ava"},
        }
        return httpx.Response(
            200, json={"message": "ok", "status": "queued", "execution_id": "ex_1"}
        )

    with make_client(handler)[0] as bolna:
        assert bolna.create_agent_v2(agent_config={}, agent_prompts={}).agent_id == "ag_1"
        call = bolna.make_call(
            agent_id="ag_1",
            recipient_phone_number="+15550001",
            from_phone_number="+15559999",
            user_data={"name": "Ava"},
        )
    assert call.execution_id == "ex_1"


def test_auth_error_and_request_error():
    bolna, _ = make_client(lambda r: httpx.Response(401))
    with pytest.raises(BolnaAuthError):
        bolna.get_execution(execution_id="x")

    bolna, _ = make_client(lambda r: httpx.Response(500, json={"detail": "boom"}))
    with pytest.raises(BolnaRequestError) as exc:
        bolna.get_execution(execution_id="x")
    assert exc.value.status_code == 500
    assert exc.value.details == {"detail": "boom"}


def test_executions_endpoint_fallback_and_pagination():
    pages = {1: [{"id": "e1"}, {"id": "e2"}], 2: [{"execution_id": "e3"}]}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/executions":
            return httpx.Response(404)
        page = int(req.url.params["page_number"])
        return httpx.Response(200, json={"data": pages.get(page, [])})

    bolna, seen = make_client(handler)
    items = bolna.get_all_executions(agent_id="ag_1", page_size=2, max_pages=5)
    assert [i.id or i.execution_id for i in items] == ["e1", "e2", "e3"]
    assert {r.url.path for r in seen} == {"/executions", "/agent/ag_1/executions"}


def test_executions_no_endpoint():
    bolna, _ = make_client(lambda r: httpx.Response(404))
    with pytest.raises(BolnaRequestError, match="No supported executions endpoint"):
        bolna.get_executions_page(agent_id="ag")


def test_voices_and_knowledgebases(tmp_path: Path):
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/me/voices":
            return httpx.Response(200, json={"data": [{"id": "v1", "name": "Asha"}]})
        if path == "/knowledgebase" and req.method == "POST":
            return httpx.Response(200, json={"rag_id": "r1", "file_name": "faq.pdf"})
        if path == "/knowledgebase/all":
            return httpx.Response(200, json=[{"rag_id": "r1"}])
        if path == "/knowledgebase/r1" and req.method == "GET":
            return httpx.Response(200, json={"rag_id": "r1", "status": "processed"})
        if path == "/knowledgebase/r1" and req.method == "DELETE":
            return httpx.Response(200, text="deleted", headers={"content-type": "text/plain"})
        if path == "/user/model/custom":
            return httpx.Response(200, json={"message": "ok", "status": "added"})
        return httpx.Response(418)

    bolna, _ = make_client(handler)
    assert bolna.list_voices()[0].name == "Asha"
    pdf = tmp_path / "faq.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert bolna.create_knowledgebase_from_pdf(pdf_path=pdf, chunk_size=256).rag_id == "r1"
    assert bolna.create_knowledgebase_from_url(url="https://x", similarity_top_k=3).rag_id == "r1"
    assert [k.rag_id for k in bolna.list_knowledgebases()] == ["r1"]
    assert bolna.get_knowledgebase(rag_id="r1").status == "processed"
    assert bolna.delete_knowledgebase(rag_id="r1").message == "success"
    added = bolna.add_custom_llm_model(custom_model_name="m", custom_model_url="http://gw")
    assert added.status == "added"
