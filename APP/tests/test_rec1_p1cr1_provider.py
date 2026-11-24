from __future__ import annotations

import json

import httpx
import pytest

from ai_provider.secrets import InMemorySecretStore
from ai_provider.service import AIProviderService
from app.core import FoundryError


def test_openai_profile_uses_openai_compatible_payload_without_deepseek_thinking(fresh_db) -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"connection":"ok"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    service = AIProviderService(
        fresh_db,
        transport=httpx.MockTransport(handler),
        secret_store=InMemorySecretStore("openai-test-secret-123"),
    )
    status = service.configure(
        enabled=True,
        provider_id="openai",
        model="gpt-4o-mini",
        thinking_mode="disabled",
        max_output_tokens=1024,
        timeout_seconds=30,
        data_sharing_acknowledged=True,
        acknowledged_by="P1CR1 provider regression",
    )
    assert status["provider_id"] == "openai"
    result = service.test_connection()
    assert result["status"] == "PASS"
    assert observed["url"] == "https://api.openai.com/v1/chat/completions"
    assert "thinking" not in observed["payload"]


def test_custom_provider_rejects_non_https_and_private_endpoints(fresh_db) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore("custom-test-secret-123"))
    base = {
        "enabled": False,
        "provider_id": "custom",
        "model": "compatible-model",
        "thinking_mode": "disabled",
        "max_output_tokens": 1024,
        "timeout_seconds": 30,
        "data_sharing_acknowledged": False,
        "acknowledged_by": None,
    }
    with pytest.raises(FoundryError) as http_error:
        service.configure(endpoint="http://example.com/chat", **base)
    assert http_error.value.code == "AI_PROVIDER_ENDPOINT_INVALID"
    with pytest.raises(FoundryError) as private_error:
        service.configure(endpoint="https://127.0.0.1/chat", **base)
    assert private_error.value.code == "AI_PROVIDER_ENDPOINT_BLOCKED"
