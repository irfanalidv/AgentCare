from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from agentcare.bolna.errors import BolnaAuthError, BolnaRequestError
from agentcare.bolna.models import (
    AddCustomModelResponse,
    AgentCreateStatus,
    AgentExecution,
    DeleteKnowledgebaseResponse,
    Knowledgebase,
    KnowledgebaseStatus,
    MakeCallStatus,
    VoiceExecution,
    Voice,
)


class BolnaClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.bolna.ai",
        timeout_s: float = 30.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_s),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BolnaClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _handle(self, resp: httpx.Response) -> Any:
        if resp.status_code == 401:
            raise BolnaAuthError("Bolna API auth failed (401). Check BOLNA_API_KEY.")
        if 200 <= resp.status_code < 300:
            if not resp.content:
                return None
            ctype = resp.headers.get("content-type", "")
            if "application/json" in ctype:
                return resp.json()
            return resp.text

        details: object | None = None
        try:
            details = resp.json()
        except Exception:
            details = resp.text
        raise BolnaRequestError(
            f"Bolna API request failed ({resp.status_code})",
            status_code=resp.status_code,
            details=details,
        )

    # --- Agents / Calls / Executions ---

    def create_agent_v2(self, *, agent_config: dict[str, Any], agent_prompts: dict[str, Any]) -> AgentCreateStatus:
        payload = {"agent_config": agent_config, "agent_prompts": agent_prompts}
        resp = self._client.post("/v2/agent", json=payload)
        data = self._handle(resp)
        return AgentCreateStatus.model_validate(data)

    def make_call(
        self,
        *,
        agent_id: str,
        recipient_phone_number: str,
        from_phone_number: str | None = None,
        scheduled_at: str | None = None,
        user_data: dict[str, Any] | None = None,
        agent_data: dict[str, Any] | None = None,
        retry_config: dict[str, Any] | None = None,
        bypass_call_guardrails: bool | None = None,
    ) -> MakeCallStatus:
        payload: dict[str, Any] = {
            "agent_id": agent_id,
            "recipient_phone_number": recipient_phone_number,
        }
        if from_phone_number:
            payload["from_phone_number"] = from_phone_number
        if scheduled_at:
            payload["scheduled_at"] = scheduled_at
        if user_data:
            payload["user_data"] = user_data
        if agent_data:
            payload["agent_data"] = agent_data
        if retry_config:
            payload["retry_config"] = retry_config
        if bypass_call_guardrails is not None:
            payload["bypass_call_guardrails"] = bypass_call_guardrails

        resp = self._client.post("/call", json=payload)
        data = self._handle(resp)
        return MakeCallStatus.model_validate(data)

    def get_execution(self, *, execution_id: str) -> AgentExecution:
        resp = self._client.get(f"/executions/{execution_id}")
        data = self._handle(resp)
        return AgentExecution.model_validate(data)

    def get_executions_page(
        self,
        *,
        agent_id: str,
        page_number: int = 1,
        page_size: int = 50,
    ) -> list[VoiceExecution]:
        """
        Fetch one executions page for an agent.
        Bolna response shapes vary; normalize to list[VoiceExecution].
        """
        candidate_requests = [
            ("/executions", {"agent_id": agent_id, "page_number": page_number, "page_size": page_size}),
            (f"/agent/{agent_id}/executions", {"page_number": page_number, "page_size": page_size}),
            (f"/v2/agent/{agent_id}/executions", {"page_number": page_number, "page_size": page_size}),
        ]

        data = None
        last_error: BolnaRequestError | None = None
        for path, params in candidate_requests:
            resp = self._client.get(path, params=params)
            if resp.status_code == 404:
                continue
            try:
                data = self._handle(resp)
                break
            except BolnaRequestError as e:
                last_error = e
                continue

        if data is None:
            if last_error:
                raise last_error
            raise BolnaRequestError("No supported executions endpoint found for this Bolna account")
        if isinstance(data, dict):
            items = data.get("data") or data.get("items") or data.get("executions") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        if not isinstance(items, list):
            raise BolnaRequestError("Unexpected /executions response shape", details=data)
        return [VoiceExecution.model_validate(x) for x in items]

    def get_all_executions(
        self,
        *,
        agent_id: str,
        page_size: int = 50,
        max_pages: int = 10,
    ) -> list[VoiceExecution]:
        out: list[VoiceExecution] = []
        for page in range(1, max_pages + 1):
            items = self.get_executions_page(agent_id=agent_id, page_number=page, page_size=page_size)
            if not items:
                break
            out.extend(items)
            if len(items) < page_size:
                break
        return out

    # --- Voices ---

    def list_voices(self) -> list[Voice]:
        resp = self._client.get("/me/voices")
        data = self._handle(resp)
        items = data.get("data") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise BolnaRequestError("Unexpected /me/voices response shape", details=data)
        return [Voice.model_validate(v) for v in items]

    # --- Knowledgebases ---

    def create_knowledgebase_from_url(
        self,
        *,
        url: str,
        chunk_size: int | None = None,
        similarity_top_k: int | None = None,
        overlapping: int | None = None,
    ) -> KnowledgebaseStatus:
        files = None
        data: dict[str, Any] = {"url": url}
        if chunk_size is not None:
            data["chunk_size"] = str(chunk_size)
        if similarity_top_k is not None:
            data["similarity_top_k"] = str(similarity_top_k)
        if overlapping is not None:
            data["overlapping"] = str(overlapping)
        resp = self._client.post("/knowledgebase", data=data, files=files)
        out = self._handle(resp)
        return KnowledgebaseStatus.model_validate(out)

    def create_knowledgebase_from_pdf(
        self,
        *,
        pdf_path: Path,
        chunk_size: int | None = None,
        similarity_top_k: int | None = None,
        overlapping: int | None = None,
    ) -> KnowledgebaseStatus:
        with pdf_path.open("rb") as f:
            files = {"file": (pdf_path.name, f, "application/pdf")}
            data: dict[str, Any] = {}
            if chunk_size is not None:
                data["chunk_size"] = str(chunk_size)
            if similarity_top_k is not None:
                data["similarity_top_k"] = str(similarity_top_k)
            if overlapping is not None:
                data["overlapping"] = str(overlapping)
            resp = self._client.post("/knowledgebase", data=data, files=files)
            out = self._handle(resp)
            return KnowledgebaseStatus.model_validate(out)

    def get_knowledgebase(self, *, rag_id: str) -> Knowledgebase:
        resp = self._client.get(f"/knowledgebase/{rag_id}")
        out = self._handle(resp)
        return Knowledgebase.model_validate(out)

    def list_knowledgebases(self) -> list[Knowledgebase]:
        resp = self._client.get("/knowledgebase/all")
        out = self._handle(resp)
        return [Knowledgebase.model_validate(k) for k in out]

    def delete_knowledgebase(self, *, rag_id: str) -> DeleteKnowledgebaseResponse:
        resp = self._client.delete(f"/knowledgebase/{rag_id}")
        out = self._handle(resp)
        if isinstance(out, dict):
            return DeleteKnowledgebaseResponse.model_validate(out)
        try:
            parsed = json.loads(out)
            return DeleteKnowledgebaseResponse.model_validate(parsed)
        except Exception:
            return DeleteKnowledgebaseResponse(message="success", state=None)

    # --- Custom models ---

    def add_custom_llm_model(self, *, custom_model_name: str, custom_model_url: str) -> AddCustomModelResponse:
        resp = self._client.post(
            "/user/model/custom",
            json={"custom_model_name": custom_model_name, "custom_model_url": custom_model_url},
        )
        out = self._handle(resp)
        return AddCustomModelResponse.model_validate(out)

