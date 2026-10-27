from __future__ import annotations

import ctypes
import json
from ctypes import wintypes
from pathlib import Path

import httpx
import pytest

from ai_provider import local_runtime
from ai_provider.local_runtime import DEFAULT_LOCAL_MODEL, ManagedLemonadeRuntime, detect_local_models, validate_local_endpoint
from ai_provider.secrets import InMemorySecretStore
from ai_provider.service import (
    AIProviderService,
    COMMAND4_ACTION_AUTHORING_PURPOSE,
    LOCAL_COMMAND4_MAX_OUTPUT_TOKENS,
    LOCAL_PROBE_MAX_OUTPUT_TOKENS,
    MAX_LOCAL_MODEL_LIST_RESPONSE_BYTES,
    LOCAL_SUBSTANTIVE_MAX_OUTPUT_TOKENS,
)
from app.core import FoundryError, canonical_json, sha256_bytes
from factory_authoring.command4_provider import canonical_command4_wire_bytes
from factory_authoring.service import FactoryAuthoringWorkspaceService, _GM_RESPONSE_SCHEMA


def _live_request_hash(service: AIProviderService, prompt_text: str, system_message: str, *, temperature: int | float | None = None) -> str:
    settings = service._settings()
    payload = service._request_payload(prompt_text, settings, substantive=True)
    payload["messages"] = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": prompt_text},
    ]
    if settings["provider_id"] in {"local", "lemonade"}:
        payload["cache_prompt"] = True
    if temperature is not None:
        payload["temperature"] = temperature
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def test_local_loopback_validation_and_remote_custom_block(fresh_db) -> None:
    assert validate_local_endpoint("http://127.0.0.1:11435/v1/chat/completions").startswith("http://127.0.0.1")
    with pytest.raises(FoundryError) as remote_local:
        validate_local_endpoint("https://example.com/v1/chat/completions")
    assert remote_local.value.code == "LOCAL_AI_ENDPOINT_INVALID"

    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    with pytest.raises(FoundryError) as remote_custom:
        service.configure(
            enabled=False,
            provider_id="custom",
            endpoint="http://127.0.0.1:11435/v1/chat/completions",
            model="compatible-model",
            thinking_mode="disabled",
            max_output_tokens=1024,
            timeout_seconds=30,
            data_sharing_acknowledged=False,
            acknowledged_by=None,
        )
    assert remote_custom.value.code == "AI_PROVIDER_ENDPOINT_INVALID"


def test_local_provider_call_needs_no_key_or_ack_and_omits_authorization(fresh_db, monkeypatch) -> None:
    from ai_provider import service as service_module

    # 9e77b527: selecting "local" first proves a loopback listener owned by
    # this user (/proc/net socket table).  This test serves the model through
    # a mock transport, so it stands in for that proof and checks the call.
    proofs: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        service_module,
        "derive_provider_identity",
        lambda *args, **kwargs: proofs.append((*args, kwargs)) or {"provider_id": args[0]},
    )
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers.get("authorization")
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"connection":"ok"}'}, "finish_reason": "stop"}],
        })

    service = AIProviderService(
        fresh_db,
        transport=httpx.MockTransport(handler),
        secret_store=InMemorySecretStore(),
    )
    status = service.select_local_ai(
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
    )
    assert status["provider_id"] == "local"
    assert status["ready"] is True
    assert status["settings"]["data_sharing_acknowledged"] is False
    assert status["secret"]["source"] == "loopback_no_key"
    assert status["selection_test"]["status"] == "PASS"
    assert status["readiness_state"] == "READY"
    assert "acknowledgement" not in status["readiness_reason"].lower()
    assert "protected key" not in status["readiness_reason"].lower()
    assert observed["authorization"] is None
    assert observed["payload"]["model"] == "qwen3.5-9b-pretrained"
    assert observed["payload"]["max_tokens"] == 128
    assert observed["payload"]["response_format"] == {"type": "json_object"}
    assert observed["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert proofs == [("local", "qwen3.5-9b-pretrained", {"endpoint": "http://127.0.0.1:11435/v1/chat/completions"})]


def _save_local_selection(
    db,
    *,
    provider_id: str = "local",
    endpoint: str = "http://127.0.0.1:11435/v1/chat/completions",
    model: str = "qwen3.5-9b-pretrained",
) -> None:
    service = AIProviderService(db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id=provider_id,
        endpoint=endpoint,
        model=model,
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )


def test_saved_local_selection_restores_readiness_from_model_list_after_restart(fresh_db) -> None:
    _save_local_selection(fresh_db)
    calls: list[tuple[str, str]] = []
    body = json.dumps({"data": [{"id": "qwen3.5-9b-pretrained"}]}).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.method == "GET"
        assert request.url.path == "/v1/models"
        assert request.headers.get("authorization") is None
        return httpx.Response(200, content=body)

    restarted = AIProviderService(
        fresh_db,
        transport=httpx.MockTransport(handler),
        secret_store=InMemorySecretStore(),
    )
    first = restarted.status()
    second = restarted.status()

    assert calls == [("GET", "/v1/models")]
    assert first["ready"] is True
    assert first["readiness_state"] == "READY"
    assert "model-list readiness probe passed" in first["readiness_reason"]
    assert first["connection_test"] == second["connection_test"]
    evidence = first["connection_test"]
    assert evidence["status"] == "PASS"
    assert evidence["probe_kind"] == "non_generative_model_list"
    assert evidence["endpoint"] == "http://127.0.0.1:11435/v1/chat/completions"
    assert evidence["models_endpoint"] == "http://127.0.0.1:11435/v1/models"
    assert evidence["model"] == "qwen3.5-9b-pretrained"
    assert evidence["response_sha256"] == sha256_bytes(body)
    assert evidence["response_bytes"] == len(body)
    assert type(evidence["duration_ms"]) is int
    assert not {"response_text", "response_body", "request_bytes", "authorization", "error"}.intersection(evidence)
    assert first["usage_totals"] == {
        "runs": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    with fresh_db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ai_provider_runs").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("case", "response"),
    [
        ("malformed", httpx.Response(200, content=b"not-json")),
        ("redirect", httpx.Response(307, headers={"Location": "http://127.0.0.1:11436/v1/models"}, content=b"redirect")),
        ("wrong-model", httpx.Response(200, json={"data": [{"id": "other-model"}]})),
        ("invalid-shape", httpx.Response(200, json={"status": "ok"})),
        ("oversize", httpx.Response(200, content=b"x" * (MAX_LOCAL_MODEL_LIST_RESPONSE_BYTES + 1))),
    ],
)
def test_saved_local_restart_probe_fails_closed_without_completion(
    fresh_db,
    case: str,
    response: httpx.Response,
) -> None:
    _save_local_selection(fresh_db)
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.method == "GET"
        assert request.url.path == "/v1/models"
        return response

    restarted = AIProviderService(
        fresh_db,
        transport=httpx.MockTransport(handler),
        secret_store=InMemorySecretStore(),
    )
    status = restarted.status()

    assert calls == [("GET", "/v1/models")]
    assert status["ready"] is False
    assert status["readiness_state"] == "CONNECTION_FAILED"
    assert status["connection_test"]["status"] == "FAILED"
    assert status["connection_test"]["probe_kind"] == "non_generative_model_list"
    assert status["connection_test"]["reason_code"] in {
        "response_invalid",
        "redirect_rejected",
        "model_not_found",
        "response_too_large",
    }
    assert status["usage_totals"]["runs"] == 0


def test_saved_local_restart_probe_rejects_non_loopback_without_network(fresh_db) -> None:
    _save_local_selection(fresh_db)
    with fresh_db.transaction() as conn:
        conn.execute(
            "UPDATE ai_provider_settings SET endpoint=? WHERE provider_id='local'",
            ("http://192.0.2.44:11435/v1/chat/completions",),
        )
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        raise AssertionError("non-loopback endpoint must not be contacted")

    restarted = AIProviderService(
        fresh_db,
        transport=httpx.MockTransport(handler),
        secret_store=InMemorySecretStore(),
    )
    status = restarted.status()

    assert calls == []
    assert status["ready"] is False
    assert status["readiness_state"] == "CONNECTION_FAILED"
    assert status["connection_test"]["reason_code"] == "endpoint_invalid"
    assert status["connection_test"]["endpoint"] is None
    assert status["connection_test"]["models_endpoint"] is None


def test_saved_remote_selection_stays_not_tested_after_restart(fresh_db) -> None:
    secret_store = InMemorySecretStore("owner-supplied-test-key")
    service = AIProviderService(fresh_db, secret_store=secret_store)
    service.configure(
        enabled=True,
        provider_id="openai",
        model="gpt-4o-mini",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=30,
        data_sharing_acknowledged=True,
        acknowledged_by="owner",
    )
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        raise AssertionError("remote providers require the explicit owner connection test")

    restarted = AIProviderService(
        fresh_db,
        transport=httpx.MockTransport(handler),
        secret_store=secret_store,
    )
    status = restarted.status()

    assert calls == []
    assert status["ready"] is False
    assert status["readiness_state"] == "CONNECTION_NOT_TESTED"
    assert status["connection_test"]["status"] == "NOT_TESTED"
    assert "probe_kind" not in status["connection_test"]


def test_managed_lemonade_restart_probe_requires_runtime_ownership(fresh_db) -> None:
    _save_local_selection(
        fresh_db,
        provider_id="lemonade",
        endpoint="http://127.0.0.1:13305/api/v1/chat/completions",
        model=DEFAULT_LOCAL_MODEL,
    )
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        raise AssertionError("unowned managed runtime must not be contacted")

    restarted = AIProviderService(
        fresh_db,
        transport=httpx.MockTransport(handler),
        secret_store=InMemorySecretStore(),
    )
    status = restarted.status()

    assert calls == []
    assert status["ready"] is False
    assert status["readiness_state"] == "LOCAL_AI_NOT_READY"
    assert status["connection_test"]["status"] == "NOT_TESTED"


def test_local_target_correction_schema_is_strict_bounded_and_internal_only(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    observed: list[dict] = []

    def provider_call(**kwargs):
        observed.append(json.loads(kwargs["request_bytes"]))
        return 200, b'{"choices":[{"message":{"content":"{\\"option_id\\":\\"mp-test\\"}"},"finish_reason":"stop"}]}'

    monkeypatch.setattr(service, "_provider_call", provider_call)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["option_id"],
        "properties": {"option_id": {"type": "string", "enum": ["mp-test"]}},
    }
    service.complete_json(
        prompt_text="{}",
        system_message="{}",
        purpose="character_creation_local_correction",
        response_schema=schema,
    )

    assert len(observed) == 1
    assert observed[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "TianxiaFoundry_LocalMethodPathCorrection_v1",
            "strict": True,
            "schema": schema,
        },
    }
    assert observed[0]["max_tokens"] == 128
    assert observed[0]["cache_prompt"] is True
    schema["properties"]["option_id"]["enum"].append("mutated-after-call")
    assert observed[0]["response_format"]["json_schema"]["schema"]["properties"]["option_id"]["enum"] == ["mp-test"]

    with pytest.raises(FoundryError) as malformed:
        service.complete_json(
            prompt_text="{}",
            system_message="{}",
            purpose="character_creation_local_correction",
            response_schema={"type": "not-a-json-schema-type"},
        )
    assert malformed.value.code == "AI_PROVIDER_RESPONSE_SCHEMA_INVALID"
    assert len(observed) == 1


def test_command4_schema_output_cap_is_purpose_scoped(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="gemma4-26b-a4b",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    observed: list[dict] = []

    def provider_call(**kwargs):
        observed.append(json.loads(kwargs["request_bytes"]))
        return 200, b'{"choices":[{"message":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}'

    monkeypatch.setattr(service, "_provider_call", provider_call)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }
    service.complete_json(
        prompt_text="{}",
        system_message="{}",
        purpose=COMMAND4_ACTION_AUTHORING_PURPOSE,
        response_schema=schema,
        response_schema_max_output_tokens=LOCAL_COMMAND4_MAX_OUTPUT_TOKENS,
    )
    assert observed[-1]["max_tokens"] == LOCAL_COMMAND4_MAX_OUTPUT_TOKENS
    assert observed[-1]["response_format"]["json_schema"]["strict"] is True

    with pytest.raises(FoundryError) as near_spelling:
        service.complete_json(
            prompt_text="{}",
            system_message="{}",
            purpose="factory_command4_action_authoring_typo",
            response_schema=schema,
            response_schema_max_output_tokens=LOCAL_COMMAND4_MAX_OUTPUT_TOKENS,
        )
    assert near_spelling.value.code == "AI_PROVIDER_RESPONSE_SCHEMA_INVALID"
    assert near_spelling.value.details == {"max_tokens": 1024}
    assert len(observed) == 1


def test_gm_authoring_schema_budget_is_wire_bound_at_16384(fresh_db) -> None:
    observed: dict[str, object] = {}
    theme = {
        "display_name": "Fixture theme",
        "core_theme": "Exact source",
        "principles": ["Respect source", "Keep boundaries"],
        "strengths": ["Care", "Restraint"],
        "risks": ["Overreach", "Assumption"],
        "roleplay_expression": "Read selected records.",
        "tactical_expression": "Display guidance only.",
        "gm_usage_notes": "No executable effect.",
        "relevant_record_ids": ["record.fixture"],
        "mechanical_effects": [],
    }
    response = {
        "dao": dict(theme),
        "i_ching": dict(theme),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        observed["payload"] = json.loads(request.content)
        observed["request_sha256"] = sha256_bytes(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(response, separators=(",", ":"))}, "finish_reason": "stop"}],
        })

    service = AIProviderService(
        fresh_db,
        transport=httpx.MockTransport(handler),
        secret_store=InMemorySecretStore(),
    )
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    result = service.complete_json(
        prompt_text='{"gm":true}',
        system_message="GM authoring wire contract",
        purpose="factory_gm_tactical_authoring",
        response_schema=_GM_RESPONSE_SCHEMA,
        response_schema_name="tianxia_gm_tactical_authoring",
        response_schema_max_output_tokens=16384,
        temperature=0,
    )

    assert observed["payload"]["max_tokens"] == 16384
    assert observed["payload"]["response_format"]["json_schema"]["strict"] is True
    assert result["request_sha256"] == observed["request_sha256"]
    assert result["request_sha256"] == FactoryAuthoringWorkspaceService._gm_provider_wire_hash(
        '{"gm":true}',
        "GM authoring wire contract",
        service._settings(),
    )


def test_exact_request_byte_cap_includes_schema_wrapper_and_rejects_before_network(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    observed: list[bytes] = []

    def provider_call(**kwargs):
        observed.append(kwargs["request_bytes"])
        return 200, b'{"choices":[{"message":{"content":"{\\"option_id\\":\\"opaque-1\\"}"},"finish_reason":"stop"}]}'

    monkeypatch.setattr(service, "_provider_call", provider_call)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["option_id"],
        "properties": {"option_id": {"type": "string", "enum": ["opaque-1"]}},
    }
    service.complete_json(
        prompt_text="compact prompt " + "x" * 512,
        system_message="system contract",
        purpose="character_creation_complete_plan",
        response_schema=schema,
        max_request_bytes=100_000,
    )
    assert len(observed) == 1
    wire_payload = json.loads(observed[0])
    assert set(wire_payload) == {
        "model", "messages", "response_format", "max_tokens", "stream", "chat_template_kwargs", "cache_prompt",
    }
    assert wire_payload["cache_prompt"] is True
    assert wire_payload["messages"] == [
        {"role": "system", "content": "system contract"},
        {"role": "user", "content": "compact prompt " + "x" * 512},
    ]
    assert wire_payload["response_format"]["json_schema"]["schema"] == schema
    assert canonical_json(wire_payload).encode("utf-8") == observed[0]
    exact_wire_size = len(observed[0])

    with pytest.raises(FoundryError) as too_large:
        service.complete_json(
            prompt_text="compact prompt " + "x" * 512,
            system_message="system contract",
            purpose="character_creation_complete_plan",
            response_schema=schema,
            max_request_bytes=exact_wire_size - 1,
        )
    assert too_large.value.code == "AI_PROVIDER_REQUEST_TOO_LARGE"
    assert too_large.value.details == {
        "request_bytes": exact_wire_size,
        "max_request_bytes": exact_wire_size - 1,
        "provider_called": False,
    }
    assert len(observed) == 1

    with pytest.raises(FoundryError) as invalid_limit:
        service.complete_json(
            prompt_text="{}",
            system_message="{}",
            purpose="character_creation_complete_plan",
            max_request_bytes=0,
        )
    assert invalid_limit.value.code == "AI_PROVIDER_REQUEST_SIZE_INVALID"
    assert len(observed) == 1


def test_local_contract_failure_retains_bounded_content_diagnostics_without_payload(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    content = '{"secret":"must-not-leak"'
    envelope = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 321, "completion_tokens": 17, "total_tokens": 338},
        "timings": {
            "prompt_eval_count": 321,
            "prompt_eval_duration": 1250,
            "predicted_n": 17,
            "secret": "omit",
        },
    }
    response_bytes = canonical_json(envelope).encode("utf-8")
    monkeypatch.setattr(service, "_provider_call", lambda **kwargs: (200, response_bytes))

    with pytest.raises(FoundryError) as failure:
        service.complete_json(prompt_text="{}", system_message="{}", purpose="command4_test")

    assert failure.value.code == "AI_PROVIDER_RESPONSE_CONTRACT_INVALID"
    details = failure.value.details
    assert details["reason"] == "invalid_json"
    assert details["response_sha256"] == sha256_bytes(response_bytes)
    assert details["completion_sha256"] == sha256_bytes(content.encode("utf-8"))
    assert details["completion_bytes"] == len(content.encode("utf-8"))
    assert details["usage"] == {"prompt_tokens": 321, "completion_tokens": 17, "total_tokens": 338}
    assert details["performance"]["duration_ms"] >= 1
    assert details["timings"]["provider_reported"] == {
        "predicted_n": 17,
        "prompt_eval_count": 321,
        "prompt_eval_duration": 1250,
    }
    serialized = canonical_json(details)
    assert content not in serialized
    assert "must-not-leak" not in serialized
    assert "response_text" not in details


def test_local_non_stop_contract_failure_retains_finish_reason_and_safe_metrics(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    content = '{"ok":true}'
    response_bytes = canonical_json({
        "choices": [{"message": {"content": content}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 42, "completion_tokens": 9, "total_tokens": 51},
        "timings": {"eval_count": 9, "eval_duration": 900},
    }).encode("utf-8")
    monkeypatch.setattr(service, "_provider_call", lambda **kwargs: (200, response_bytes))

    with pytest.raises(FoundryError) as failure:
        service.complete_json(prompt_text="{}", system_message="{}", purpose="command4_test")

    assert failure.value.code == "AI_PROVIDER_RESPONSE_CONTRACT_INVALID"
    details = failure.value.details
    assert details["reason"] == "finish_reason_not_stop"
    assert details["finish_reason"] == "length"
    assert details["completion_sha256"] == sha256_bytes(content.encode("utf-8"))
    assert details["completion_bytes"] == len(content.encode("utf-8"))
    assert details["usage"] == {"prompt_tokens": 42, "completion_tokens": 9, "total_tokens": 51}
    assert details["timings"]["provider_reported"] == {"eval_count": 9, "eval_duration": 900}
    assert details["performance"]["duration_ms"] >= 1


def test_local_contract_failure_does_not_reflect_malicious_finish_reason(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    sentinel = "credential-sentinel-finish"
    response_bytes = canonical_json({
        "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": sentinel}],
    }).encode("utf-8")
    monkeypatch.setattr(service, "_provider_call", lambda **kwargs: (200, response_bytes))

    with pytest.raises(FoundryError) as failure:
        service.complete_json(prompt_text="{}", system_message="{}", purpose="command4_test")

    details = failure.value.details
    assert details["reason"] == "finish_reason_not_stop"
    assert details["finish_reason"] == "other"
    assert sentinel not in canonical_json(details)


def test_optional_temperature_is_canonical_and_default_call_shape_is_unchanged(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    observed: list[bytes] = []

    def provider_call(**kwargs):
        observed.append(kwargs["request_bytes"])
        return 200, b'{"choices":[{"message":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}'

    monkeypatch.setattr(service, "_provider_call", provider_call)
    service.complete_json(prompt_text="prompt", system_message="system", purpose="command4_test", temperature=0)
    service.complete_json(prompt_text="prompt", system_message="system", purpose="other_test")
    first, second = (json.loads(item) for item in observed)
    assert first["temperature"] == 0
    assert canonical_json(first).encode("utf-8") == observed[0]
    assert "temperature" not in second
    assert canonical_json(second).encode("utf-8") == observed[1]

    for invalid in (True, -0.01, 2.01, 10**400, float("nan"), float("inf"), "0"):
        with pytest.raises(FoundryError) as failure:
            service.complete_json(prompt_text="{}", system_message="{}", purpose="command4_test", temperature=invalid)
        assert failure.value.code == "AI_PROVIDER_TEMPERATURE_INVALID"
    assert len(observed) == 2


def test_command4_local_output_ceiling_is_exact_purpose_scoped_and_wire_exact(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="gemma4-26b-a4b",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    observed: list[bytes] = []

    def provider_call(**kwargs):
        observed.append(kwargs["request_bytes"])
        return 200, b'{"choices":[{"message":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}'

    monkeypatch.setattr(service, "_provider_call", provider_call)
    prompt_text = '{"compact":true}'
    system_message = "Command 4 exact-cap contract"
    service.complete_json(
        prompt_text=prompt_text,
        system_message=system_message,
        purpose=COMMAND4_ACTION_AUTHORING_PURPOSE,
        temperature=0,
    )
    service.complete_json(
        prompt_text=prompt_text,
        system_message=system_message,
        purpose="character_creation_complete_plan",
    )
    service.complete_json(
        prompt_text=prompt_text,
        system_message=system_message,
        purpose="factory_command4_action_authoring_typo",
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
    }
    service.complete_json(
        prompt_text=prompt_text,
        system_message=system_message,
        purpose=COMMAND4_ACTION_AUTHORING_PURPOSE,
        response_schema=schema,
        response_schema_max_output_tokens=1024,
    )
    service.complete_json(
        prompt_text=prompt_text,
        system_message=system_message,
        purpose=COMMAND4_ACTION_AUTHORING_PURPOSE,
        substantive=False,
    )

    payloads = [json.loads(request) for request in observed]
    assert [payload["max_tokens"] for payload in payloads] == [
        LOCAL_COMMAND4_MAX_OUTPUT_TOKENS,
        LOCAL_SUBSTANTIVE_MAX_OUTPUT_TOKENS,
        LOCAL_SUBSTANTIVE_MAX_OUTPUT_TOKENS,
        1024,
        LOCAL_PROBE_MAX_OUTPUT_TOKENS,
    ]
    expected_wire = canonical_command4_wire_bytes(
        prompt_text,
        system_message=system_message,
        settings=service._settings(),
        temperature=0,
    )
    expected_wire_payload = json.loads(expected_wire)
    expected_wire_payload["cache_prompt"] = True
    expected_wire = canonical_json(expected_wire_payload).encode("utf-8")
    assert observed[0] == expected_wire
    assert sha256_bytes(observed[0]) == sha256_bytes(expected_wire)
    assert AIProviderService._max_output_tokens(
        {"provider_id": "openai", "max_output_tokens": 16384},
        substantive=True,
        purpose=COMMAND4_ACTION_AUTHORING_PURPOSE,
    ) == 8192

    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="gemma4-26b-a4b",
        thinking_mode="disabled",
        max_output_tokens=4096,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    service.complete_json(
        prompt_text=prompt_text,
        system_message=system_message,
        purpose=COMMAND4_ACTION_AUTHORING_PURPOSE,
    )
    assert json.loads(observed[-1])["max_tokens"] == 4096
    assert len(observed) == 6


def test_expected_request_hash_rejects_invalid_values_before_transport(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    calls: list[dict] = []
    monkeypatch.setattr(service, "_provider_call", lambda **kwargs: calls.append(kwargs))

    for invalid in ("A" * 64, "g" * 64, "a" * 63, "a" * 65, True, 1, 10**400):
        with pytest.raises(FoundryError) as failure:
            service.complete_json(
                prompt_text="{}",
                system_message="{}",
                purpose="request_hash_test",
                expected_request_sha256=invalid,
            )
        assert failure.value.code == "AI_PROVIDER_REQUEST_HASH_INVALID"
    assert calls == []


def test_expected_request_hash_fails_closed_when_settings_change_before_transport(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    prompt_text = "{}"
    system_message = "request hash contract"
    expected_hash = _live_request_hash(service, prompt_text, system_message, temperature=0)
    changed_settings = service._settings()
    changed_settings["model"] = "qwen3.5-9b-pretrained-flipped"
    monkeypatch.setattr(service, "_settings", lambda: changed_settings)
    transport_calls: list[dict] = []
    monkeypatch.setattr(service, "_provider_call", lambda **kwargs: transport_calls.append(kwargs))

    with pytest.raises(FoundryError) as failure:
        service.complete_json(
            prompt_text=prompt_text,
            system_message=system_message,
            purpose="request_hash_test",
            temperature=0,
            expected_request_sha256=expected_hash,
        )

    assert failure.value.code == "AI_PROVIDER_REQUEST_CHANGED"
    assert failure.value.status_code == 409
    assert failure.value.details["expected_request_sha256"] == expected_hash
    actual_hash = failure.value.details["actual_request_sha256"]
    assert isinstance(actual_hash, str) and len(actual_hash) == 64
    assert actual_hash != expected_hash
    assert failure.value.details["provider_called"] is False
    assert transport_calls == []


def test_expected_request_hash_accepts_exact_live_request_and_returns_same_hash(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    prompt_text = "{\"request\":\"parity\"}"
    system_message = "request hash parity contract"
    expected_hash = _live_request_hash(service, prompt_text, system_message, temperature=0)
    observed: list[bytes] = []

    def provider_call(**kwargs):
        observed.append(kwargs["request_bytes"])
        return 200, b'{"choices":[{"message":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}'

    monkeypatch.setattr(service, "_provider_call", provider_call)
    result = service.complete_json(
        prompt_text=prompt_text,
        system_message=system_message,
        purpose="request_hash_test",
        temperature=0,
        expected_request_sha256=expected_hash,
    )

    assert len(observed) == 1
    assert sha256_bytes(observed[0]) == expected_hash
    assert result["request_sha256"] == expected_hash


def test_local_schema_validation_rejects_endpoint_that_ignores_schema(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    observed: list[dict] = []

    def provider_call(**kwargs):
        observed.append(json.loads(kwargs["request_bytes"]))
        # This simulates a compatible server that accepts but ignores the
        # requested response_format schema.
        return 200, b'{"choices":[{"message":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}'

    monkeypatch.setattr(service, "_provider_call", provider_call)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["option_id"],
        "properties": {"option_id": {"type": "string", "enum": ["mp-test"]}},
    }
    with pytest.raises(FoundryError) as contract_error:
        service.complete_json(
            prompt_text="{}",
            system_message="{}",
            purpose="character_creation_local_correction",
            response_schema=schema,
        )

    assert contract_error.value.code == "AI_PROVIDER_RESPONSE_CONTRACT_INVALID"
    assert contract_error.value.details["reason"] == "response_schema_validation_failed"
    assert contract_error.value.details["response_sha256"]
    assert "response_text" not in contract_error.value.details
    assert observed[0]["max_tokens"] == 128


def test_cloud_target_schema_is_rejected_and_default_format_stays_json_object(fresh_db, monkeypatch) -> None:
    service = AIProviderService(
        fresh_db,
        secret_store=InMemorySecretStore("openai-test-secret-123"),
    )
    service.configure(
        enabled=True,
        provider_id="openai",
        model="gpt-4o-mini",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=37,
        data_sharing_acknowledged=True,
        acknowledged_by="schema test",
    )
    calls = []

    def provider_call(**kwargs):
        calls.append(kwargs)
        return 200, b'{"choices":[{"message":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}'

    monkeypatch.setattr(service, "_provider_call", provider_call)
    with pytest.raises(FoundryError) as unsupported:
        service.complete_json(
            prompt_text="{}",
            system_message="{}",
            purpose="character_creation_local_correction",
            response_schema={"type": "object"},
        )
    assert unsupported.value.code == "AI_PROVIDER_RESPONSE_SCHEMA_UNSUPPORTED"
    assert calls == []

    service.complete_json(prompt_text="{}", system_message="{}", purpose="character_creation")
    payload = json.loads(calls[0]["request_bytes"])
    assert payload["response_format"] == {"type": "json_object"}


def test_local_first_response_grace_covers_connection_test_and_substantive_completion(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    observed: list[tuple[int, int]] = []

    def provider_call(**kwargs):
        payload = json.loads(kwargs["request_bytes"])
        observed.append((kwargs["timeout_seconds"], payload["max_tokens"]))
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        return 200, b'{"choices":[{"message":{"content":"{\\"connection\\":\\"ok\\"}"},"finish_reason":"stop"}]}'

    monkeypatch.setattr(service, "_provider_call", provider_call)
    service.complete_json(prompt_text="{}", system_message="{}", purpose="character_creation")
    assert observed[-1] == (2400, 6144)

    service.test_connection()
    assert observed[-1] == (2400, 128)
    assert len(observed) == 2  # one upstream call per owner action; no retries


def test_local_completion_records_usage_duration_and_output_rate(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )

    monkeypatch.setattr(
        service,
        "_provider_call",
        lambda **kwargs: (
            200,
            b'{"choices":[{"message":{"content":"{\\"connection\\":\\"ok\\"}"},"finish_reason":"stop"}],'
            b'"usage":{"prompt_tokens":100,"completion_tokens":25,"total_tokens":125},'
            b'"timings":{"prompt_n":100,"prompt_ms":12.5,"predicted_n":25,"predicted_ms":2500,"secret":"omit","negative_ms":-1}}',
        ),
    )
    clock = iter((10.0, 10.25, 12.75, 12.9))
    monkeypatch.setattr("ai_provider.service.time.perf_counter", lambda: next(clock))

    receipt = service.complete_json(prompt_text="{}", system_message="{}", purpose="character_creation")

    assert receipt["usage"] == {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125}
    assert receipt["performance"] == {
        "duration_ms": 2500,
        "duration_seconds": 2.5,
        "completion_tokens_per_second": 10.0,
    }
    assert receipt["timings"] == {
        "schema": "TianxiaFoundry.AIProviderTimingReceipt.v1",
        "phases_ms": {
            "request_preparation": 250,
            "provider_transport": 2500,
            "response_body_parse": 150,
        },
        "provider_reported": {
            "predicted_ms": 2500,
            "predicted_n": 25,
            "prompt_ms": 12.5,
            "prompt_n": 100,
        },
    }


def test_connection_returns_safe_usage_performance_and_timings_without_payload(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="gemma-3-12b-it",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    calls: list[dict[str, object]] = []
    provider_result = {
        "model": "gemma-3-12b-it",
        "request_sha256": "r" * 64,
        "response_sha256": "s" * 64,
        "response_text": '{"connection":"ok"}',
        "value": {"connection": "ok"},
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 18,
            "total_tokens": 138,
            "api_key": "must-not-leak",
        },
        "performance": {
            "duration_ms": 2750,
            "duration_seconds": 2.75,
            "completion_tokens_per_second": 6.55,
            "endpoint": "https://provider.invalid",
        },
        "timings": {
            "schema": "untrusted-schema",
            "phases_ms": {
                "request_preparation": 1,
                "provider_transport": 2750,
                "response_body_parse": 2.5,
                "response_text": "must-not-leak",
            },
            "provider_reported": {
                "predicted_n": 18,
                "prompt_ms": 9.5,
                "headers": {"authorization": "must-not-leak"},
            },
        },
    }

    def fake_complete_json(**kwargs):
        calls.append(kwargs)
        return provider_result

    monkeypatch.setattr(service, "complete_json", fake_complete_json)
    result = service.test_connection()

    assert len(calls) == 1
    assert result["status"] == "PASS"
    assert result["model"] == "gemma-3-12b-it"
    assert result["usage"] == {
        "prompt_tokens": 120,
        "completion_tokens": 18,
        "total_tokens": 138,
    }
    assert result["performance"] == {
        "duration_ms": 2750,
        "duration_seconds": 2.75,
        "completion_tokens_per_second": 6.55,
    }
    assert result["timings"] == {
        "schema": "TianxiaFoundry.AIProviderTimingReceipt.v1",
        "phases_ms": {
            "request_preparation": 1,
            "provider_transport": 2750,
            "response_body_parse": 2.5,
        },
        "provider_reported": {
            "predicted_n": 18,
            "prompt_ms": 9.5,
        },
    }
    protected = {"response_text", "value", "prompt", "request_bytes", "endpoint", "headers", "key", "secret", "credentials"}

    def assert_no_protected(value):
        if isinstance(value, dict):
            assert not protected.intersection(value)
            for nested in value.values():
                assert_no_protected(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_no_protected(nested)

    assert_no_protected(result)
    result["timings"]["provider_reported"]["predicted_n"] = 999
    assert provider_result["timings"]["provider_reported"]["predicted_n"] == 18


def test_local_completion_omits_oversized_provider_timing_integer(fresh_db, monkeypatch) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    service.configure(
        enabled=True,
        provider_id="local",
        endpoint="http://127.0.0.1:11435/v1/chat/completions",
        model="qwen3.5-9b-pretrained",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=False,
        acknowledged_by=None,
    )
    provider_body = {
        "choices": [{"message": {"content": '{"connection":"ok"}'}, "finish_reason": "stop"}],
        "timings": {"predicted_n": 10**400},
    }
    monkeypatch.setattr(
        service,
        "_provider_call",
        lambda **kwargs: (200, json.dumps(provider_body).encode("utf-8")),
    )
    clock = iter((20.0, 20.25, 21.25, 21.5))
    monkeypatch.setattr("ai_provider.service.time.perf_counter", lambda: next(clock))

    receipt = service.complete_json(prompt_text="{}", system_message="{}", purpose="character_creation")

    assert receipt["value"] == {"connection": "ok"}
    assert "predicted_n" not in receipt["timings"]["provider_reported"]


def test_cloud_substantive_completion_uses_saved_timeout(fresh_db, monkeypatch) -> None:
    service = AIProviderService(
        fresh_db,
        secret_store=InMemorySecretStore("openai-test-secret-123"),
    )
    service.configure(
        enabled=True,
        provider_id="openai",
        model="gpt-4o-mini",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=37,
        data_sharing_acknowledged=True,
        acknowledged_by="timeout test",
    )
    observed: list[int] = []

    def provider_call(**kwargs):
        observed.append(kwargs["timeout_seconds"])
        payload = json.loads(kwargs["request_bytes"])
        assert payload["max_tokens"] == 8192
        assert "chat_template_kwargs" not in payload
        return 200, b'{"choices":[{"message":{"content":"{\\"connection\\":\\"ok\\"}"},"finish_reason":"stop"}]}'

    monkeypatch.setattr(service, "_provider_call", provider_call)
    service.complete_json(prompt_text="{}", system_message="{}", purpose="character_creation")
    assert observed == [37]


def test_bounded_detection_parses_openai_and_lemonade_model_shapes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        port = request.url.port
        path = request.url.path
        if path in {"/health", "/v1/health", "/api/v1/health"}:
            return httpx.Response(200, json={"status": "ok", "backend": "llama.cpp"})
        if path == "/v1/models" and port == 11435:
            return httpx.Response(200, json={"data": [{"id": "qwen3.5-9b-pretrained"}]})
        if path == "/api/v1/models" and port == 11437:
            return httpx.Response(200, json={"models": [{"name": "gemma4-26b-a4b"}]})
        return httpx.Response(404, json={"error": "not found"})

    candidates = detect_local_models(
        transport=httpx.MockTransport(handler),
        ports=[11435, 11437, 9999, 11435],
        timeout_seconds=0.1,
    )
    models = {(row["port"], row["model"]) for row in candidates if row["model"]}
    assert (11435, "qwen3.5-9b-pretrained") in models
    assert (11437, "gemma4-26b-a4b") in models
    external_lemonade = next(row for row in candidates if row["port"] == 11437 and row["model"] == "gemma4-26b-a4b")
    assert external_lemonade["provider_id"] == "local"
    assert external_lemonade["endpoint"] == "http://127.0.0.1:11437/v1/chat/completions"
    assert all(row["port"] in {11435, 11437} for row in candidates)
    assert all(row["ready"] is True for row in candidates if row["model"])


def test_windows_job_limit_configuration_is_structural_only() -> None:
    class FakeKernel32:
        def __init__(self) -> None:
            self.flags = 0
            self.info_size = 0

        def SetInformationJobObject(self, _job, _info_class, info_pointer, info_size):
            info = ctypes.cast(
                info_pointer,
                ctypes.POINTER(local_runtime._JOBOBJECT_EXTENDED_LIMIT_INFORMATION),
            ).contents
            self.flags = info.BasicLimitInformation.LimitFlags
            self.info_size = info_size
            return True

    kernel32 = FakeKernel32()
    assert local_runtime._set_job_object_kill_on_close(kernel32, object()) is True
    assert kernel32.flags & local_runtime._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    assert kernel32.info_size == ctypes.sizeof(local_runtime._JOBOBJECT_EXTENDED_LIMIT_INFORMATION)


def test_windows_job_requests_assignable_process_handle(monkeypatch) -> None:
    class FakeFunction:
        def __init__(self, result):
            self.result = result
            self.calls = []
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            self.calls.append(args)
            return self.result

    class FakeKernel32:
        def __init__(self):
            self.CreateJobObjectW = FakeFunction(0x100000001)
            self.OpenProcess = FakeFunction(0x200000002)
            self.CloseHandle = FakeFunction(True)
            self.SetInformationJobObject = FakeFunction(True)
            self.AssignProcessToJobObject = FakeFunction(True)

    class FakeProcess:
        pid = 321

    kernel32 = FakeKernel32()
    monkeypatch.setattr(local_runtime.os, "name", "nt")
    monkeypatch.setattr(local_runtime.ctypes, "WinDLL", lambda *args, **kwargs: kernel32, raising=False)

    job = local_runtime._WindowsJob(FakeProcess())
    try:
        assert job.handle == 0x100000001
        assert kernel32.OpenProcess.calls[0] == (
            local_runtime._PROCESS_SET_QUOTA | local_runtime._PROCESS_TERMINATE,
            False,
            321,
        )
        assert kernel32.OpenProcess.argtypes == [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        assert kernel32.OpenProcess.restype is wintypes.HANDLE
        assert kernel32.AssignProcessToJobObject.argtypes == [wintypes.HANDLE, wintypes.HANDLE]
        assert kernel32.CloseHandle.argtypes == [wintypes.HANDLE]
        assert kernel32.CloseHandle.restype is wintypes.BOOL
    finally:
        job.close()


def test_managed_setup_config_and_pull_request_are_bounded(tmp_path, monkeypatch) -> None:
    class FakeProcess:
        pid = 12345

        def poll(self):
            return None

        def terminate(self):
            return None

        def kill(self):
            return None

        def wait(self, timeout=None):
            return None

    process = FakeProcess()
    runtime = ManagedLemonadeRuntime(tmp_path)
    runtime._executable = lambda: tmp_path / "lemond.exe"
    runtime._free_port = lambda: 43210
    runtime._install_backend = lambda: "rocm"
    monkeypatch.setattr(local_runtime.subprocess, "Popen", lambda *args, **kwargs: process)
    requests = []

    def request(method, path, *, timeout, json_body=None):
        requests.append((method, path, timeout, json_body))
        if method == "GET" and path == "/api/v1/health":
            return 200, {"status": "ok"}
        if method == "POST" and path == "/api/v1/pull":
            return 200, {"status": "pulled"}
        raise AssertionError(f"unexpected managed request: {method} {path}")

    runtime._request = request
    runtime._prepare_once()

    pull = next(row for row in requests if row[0] == "POST")
    assert pull[1] == "/api/v1/pull"
    assert pull[2] >= 1800
    assert pull[3] == {"model_name": "Qwen3-4B-GGUF", "stream": False}
    assert runtime.endpoint == "http://127.0.0.1:43210/api/v1/chat/completions"
    assert local_runtime.SETUP_DOWNLOAD_TIMEOUT_SECONDS >= 1800

    config = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert config["config_version"] == 2
    assert config["broadcast"] is False
    assert config["host"] == "127.0.0.1"
    assert config["global_timeout"] >= 600
    assert config["max_loaded_models"] == 2
    assert config["ctx_size"] == 8192
    assert config["log_level"] == "warning"
    assert config["telemetry"]["enabled"] is False
    assert config["llamacpp"]["backend"] == "auto"
    assert config["llamacpp"]["prefer_system"] is False
    runtime.stop()


def test_managed_prepare_is_idempotent_for_live_ready_process(tmp_path) -> None:
    class FakeProcess:
        pid = 54321

        def poll(self):
            return None

    process = FakeProcess()
    runtime = ManagedLemonadeRuntime(tmp_path)
    runtime._process = process
    runtime._state = "READY"
    runtime._endpoint = "http://127.0.0.1:43210/api/v1/chat/completions"
    before_model = runtime.model

    status = runtime.prepare("different-model")

    assert status["ready"] is True
    assert runtime._process is process
    assert runtime.model == before_model


def test_local_first_ui_and_manual_emergency_disclosure_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (root / "static" / "app.js").read_text(encoding="utf-8")
    styles = (root / "static" / "styles.css").read_text(encoding="utf-8")
    local = html.index('data-guided-route="LOCAL_AI"')
    provider = html.index('data-guided-route="STANDARD_API"')
    manual = html.index('id="guidedManualFallbackDetails"')
    assert local < provider < manual
    assert "Emergency fallback / Manual Chat" in html
    assert 'id="guidedDetectLocalAI"' in html
    assert 'id="guidedManagedPrepare"' in html
    assert 'candidate.provider_id === "local" && candidate.ready' in javascript
    assert 'managedPrepare.disabled = !!managed.loading' in javascript
    assert 'let guidedSelectedRoute = "LOCAL_AI"' in javascript
    assert 'setGuidedRoute("LOCAL_AI")' in javascript
    assert 'const restoredResolved = restoredRun?.owner_descriptive_fields?.resolved' in javascript
    assert 'const resolved = restoredResolved && typeof restoredResolved === "object"' in javascript
    assert 'id="guidedRetryLocalAICorrection"' in html
    assert "Fix with Local AI" in html
    assert 'retry-local-ai-correction' in javascript
    assert 'Retry Local Build (no provider)' in html
    assert 'guidedRetryLocalAICorrection: availability.retry_local_ai_correction' in javascript
    assert 'name="guidedLocalBuildMode" value="LOCAL_AUTO" checked' in html
    assert 'name="guidedLocalBuildMode" value="LOCAL_PREVIEW"' in html
    assert 'id="guidedLocalAutoFinalizeConsent"' in html
    assert 'guidedLocalBuildMode() === "LOCAL_AUTO" ? "AUTO_FINALIZE_WHEN_CLEAN" : "STANDARD_API"' in javascript
    assert 'Build &amp; save automatically (Recommended)' in html
    assert 'Build a preview for review' in html
    assert 'applyGuidedExecutionPreference(guidedRun.execution_mode, guidedRun)' in javascript
    assert 'guidedFinalizeInFlight' in javascript
    assert 'if (!guidedRun?.run_id || guidedFinalizeInFlight) return;' in javascript
    assert 'run.attempt_history.slice().reverse()' in javascript
    assert 'attempt?.binding?.transport?.provider_id' in javascript
    assert 'attempt?.binding?.transport?.local_correction?.provider_id' in javascript
    assert 'const providerId = directProviderId || attemptProviderId' in javascript
    assert 'class="sheet-section-heading local-ai-heading"' in html
    assert '.local-ai-setup .local-ai-heading { display: block; }' in styles
    assert '.auto-finalize-consent > span { display: grid;' in styles
    assert 'if (manualDetails) manualDetails.open = route === "MANUAL_CHAT";' in javascript
    legacy_panel = html.index('id="characterCreationModesPanel"')
    assert 'class="stage-panel legacy-retired"' in html[legacy_panel - 80:legacy_panel + 80]
    assert 'hidden aria-hidden="true"' in html[legacy_panel - 80:legacy_panel + 80]
    assert 'let cgFinalizeInFlight = false;' in javascript
    assert 'if (!cgRun?.run_id || cgFinalizeInFlight) return;' in javascript
    assert 'cgFinalizeInFlight = true;' in javascript
    assert 'cgFinalizeInFlight = false;' in javascript
    assert 'function cgIsClean(run)' in javascript
    assert 'button.disabled = !cgIsClean(cgRun);' in javascript


def test_auto_brief_continue_preserves_selected_creation_mode() -> None:
    javascript = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    brief_handler = javascript[
        javascript.index('document.getElementById("guidedBriefContinue")'):
        javascript.index('document.getElementById("ownerPathsBack")')
    ]
    assert 'setCreationMode("detailed")' not in brief_handler
    assert 'setGuidedStep(2)' in brief_handler
    assert 'A cold first reply can take up to 40 minutes; keep this page open and do not retry.' in javascript
    assert 'Number(row.character_creation_run_count || 0) === 0' in javascript
    assert 'Continue this exact character without creating another project.' in javascript
    assert 'candidate.builder_persistence_state === "temporary" && Number(candidate.character_creation_run_count || 0) === 0' in javascript
    assert 'setGuidedRoute("LOCAL_AI")' in javascript
