"""Shared fixtures: an isolated working directory and offline settings."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import httpx
import pytest

from agentcare.settings import settings

_REAL_CLIENT = httpx.Client


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[None]:
    """Run in a temp CWD (artifacts/ lands there) with every external key unset."""
    monkeypatch.chdir(tmp_path)
    for name in (
        "mistral_api_key",
        "bolna_api_key",
        "cal_api_key",
        "cal_event_type_id",
        "resend_api_key",
        "database_url",
        "frontdesk_policy_path",
        "fhir_base_url",
    ):
        monkeypatch.setattr(settings, name, None)
    monkeypatch.setattr(settings, "customer_store_backend", "json")
    monkeypatch.setattr(settings, "appointment_connector_backend", "mock")
    yield


@pytest.fixture
def mock_http(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable], list[httpx.Request]]:
    """Route every ``httpx.Client`` / ``httpx.get`` / ``httpx.post`` through ``handler``.

    Returns the list of captured requests.
    """

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        transport = httpx.MockTransport(wrapped)

        def client_factory(*args, **kwargs):
            kwargs.pop("transport", None)
            return _REAL_CLIENT(*args, transport=transport, **kwargs)

        def one_shot(method: str):
            def call(url, **kwargs):
                timeout = kwargs.pop("timeout", None)
                with client_factory(timeout=timeout) as c:
                    return c.request(method, url, **kwargs)

            return call

        monkeypatch.setattr(httpx, "Client", client_factory)
        monkeypatch.setattr(httpx, "get", one_shot("GET"))
        monkeypatch.setattr(httpx, "post", one_shot("POST"))
        return seen

    return install
