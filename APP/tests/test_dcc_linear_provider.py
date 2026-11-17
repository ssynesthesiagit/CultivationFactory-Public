"""Provider-free Slice S0 coverage for the DCC linear-step transport."""

from __future__ import annotations

import json

import httpx
import pytest

from ai_provider.secrets import InMemorySecretStore
from ai_provider.service import AIProviderService, DCC_LINEAR_STEP_PURPOSE
from app.core import FoundryError


_DCC_STEP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["option_id"],
    "properties": {
        "option_id": {
            "type": "string",
            "enum": ["dcc.opt.one"],
        },
    },
}


def _local_service(fresh_db, handler) -> AIProviderService:
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
    return service


def test_dcc_linear_step_uses_strict_schema_cache_and_timeout_override(fresh_db) -> None:
    observed: list[tuple[httpx.Request, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        observed.append((request, payload))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"option_id":"dcc.opt.one"}'},
                        "finish_reason": "stop",
                    },
                ],
                "timings": {"prompt_n": 17},
            },
        )

    service = _local_service(fresh_db, handler)
    result = service.complete_json(
        prompt_text="step prompt",
        system_message="step contract",
        purpose=DCC_LINEAR_STEP_PURPOSE,
        substantive=False,
        response_schema=_DCC_STEP_SCHEMA,
        response_schema_max_output_tokens=64,
        timeout_seconds=180,
    )

    assert result["value"] == {"option_id": "dcc.opt.one"}
    assert result["timings"]["provider_reported"]["prompt_n"] == 17
    assert len(observed) == 1
    request, payload = observed[0]
    assert payload["cache_prompt"] is True
    assert payload["max_tokens"] == 64
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "TianxiaFoundry_LocalMethodPathCorrection_v1",
            "strict": True,
            "schema": _DCC_STEP_SCHEMA,
        },
    }
    assert request.extensions["timeout"] == {
        "connect": 180,
        "read": 180,
        "write": 180,
        "pool": 180,
    }


@pytest.mark.parametrize("identity", [False, True])
def test_controller_step_budget_reaches_transport_for_response_shape(fresh_db, identity):
    from character_creation.service import CharacterCreationExecutionService
    from character_creation.creative_controller.linear_prompt import build_identity_response_schema

    value = ({"name": "Wei Lianhua", "title": "Keeper of the Furnace",
              "concept": "A patient laborer guards the village furnace and studies its changing heat."}
             if identity else {"option_id": "dcc.opt.one"})
    observed = []

    def handler(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{
            "message": {"content": json.dumps(value)}, "finish_reason": "stop",
        }]})

    controller = object.__new__(CharacterCreationExecutionService)
    controller.provider = _local_service(fresh_db, handler)
    schema = build_identity_response_schema() if identity else _DCC_STEP_SCHEMA
    result = controller._dcc_provider_step(prompt_text="bounded step", response_schema=schema)
    assert result["value"] == value
    assert len(observed) == 1
    assert observed[0]["max_tokens"] == (256 if identity else 64)
    assert observed[0]["response_format"]["json_schema"]["schema"] == schema


def test_identity_length_finish_reason_remains_rejected(fresh_db):
    from character_creation.service import CharacterCreationExecutionService
    from character_creation.creative_controller.linear_prompt import build_identity_response_schema

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{
            "message": {"content": '{"name":"Wei","title":"Guard","concept":"A guard"}'},
            "finish_reason": "length",
        }]})

    controller = object.__new__(CharacterCreationExecutionService)
    controller.provider = _local_service(fresh_db, handler)
    with pytest.raises(FoundryError) as failure:
        controller._dcc_provider_step(prompt_text="bounded step", response_schema=build_identity_response_schema())
    assert failure.value.code == "AI_PROVIDER_RESPONSE_CONTRACT_INVALID"
    assert len(calls) == 1


def test_dcc_linear_step_schema_ceiling_fails_closed_before_transport(fresh_db) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"option_id":"dcc.opt.one"}'},
                        "finish_reason": "stop",
                    },
                ],
            },
        )

    service = _local_service(fresh_db, handler)
    service.complete_json(
        prompt_text="step prompt",
        system_message="step contract",
        purpose=DCC_LINEAR_STEP_PURPOSE,
        substantive=False,
        response_schema=_DCC_STEP_SCHEMA,
        response_schema_max_output_tokens=256,
        timeout_seconds=180,
    )
    assert len(calls) == 1

    for invalid_limit in (0, -1, 257, True, 1.0):
        with pytest.raises(FoundryError) as failure:
            service.complete_json(
                prompt_text="step prompt",
                system_message="step contract",
                purpose=DCC_LINEAR_STEP_PURPOSE,
                substantive=False,
                response_schema=_DCC_STEP_SCHEMA,
                response_schema_max_output_tokens=invalid_limit,
                timeout_seconds=180,
            )
        assert failure.value.code == "AI_PROVIDER_RESPONSE_SCHEMA_INVALID"
    assert len(calls) == 1


def test_complete_json_timeout_override_rejects_invalid_values_without_transport(fresh_db) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("invalid timeout values must fail before transport")

    service = _local_service(fresh_db, handler)
    for invalid_timeout in (0, 9, 301, True, 1.0, "180", 10**400):
        with pytest.raises(FoundryError) as failure:
            service.complete_json(
                prompt_text="step prompt",
                system_message="step contract",
                purpose=DCC_LINEAR_STEP_PURPOSE,
                substantive=False,
                timeout_seconds=invalid_timeout,
            )
        assert failure.value.code == "AI_PROVIDER_TIMEOUT_INVALID"
    assert calls == []


def test_dcc_linear_step_response_is_validated_locally(fresh_db) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"option_id":"dcc.opt.other"}'},
                        "finish_reason": "stop",
                    },
                ],
            },
        )

    service = _local_service(fresh_db, handler)
    with pytest.raises(FoundryError) as failure:
        service.complete_json(
            prompt_text="step prompt",
            system_message="step contract",
            purpose=DCC_LINEAR_STEP_PURPOSE,
            substantive=False,
            response_schema=_DCC_STEP_SCHEMA,
            response_schema_max_output_tokens=64,
            timeout_seconds=180,
        )
    assert failure.value.code == "AI_PROVIDER_RESPONSE_CONTRACT_INVALID"
    assert failure.value.details["reason"] == "response_schema_validation_failed"
    assert len(calls) == 1
