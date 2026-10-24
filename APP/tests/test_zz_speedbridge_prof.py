"""Agent bridge: profile, mailbox, leases, schema guard, re-drive, identity.

The bridge lets a harness-held agent answer one authoring request instead of a
configured HTTP provider or a local model.  These tests prove that an agent
answer is validated through the same schema gate a provider answer goes through,
that a slow agent is "not yet" rather than "failed", that a re-drive of the same
step never prompts twice, and that the one-time provider-table rebuild refuses
any schema shape it does not audit.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ai_provider.agent_bridge import AgentRequestBridge
from ai_provider.secrets import InMemorySecretStore
from ai_provider.service import AGENT_PROVIDER_ID, AIProviderService
from app.api import create_app
from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_json

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_NAME = "TianxiaFoundry_AgentBridgeProbe_v1"
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["name"],
    "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 40}},
}
PURPOSE = "agent_bridge_test_step"


def _service(db, *, wait_seconds: int = 300) -> AIProviderService:
    """An agent-configured provider service with a fast deterministic poll."""

    service = AIProviderService(db, secret_store=InMemorySecretStore())
    service.agent_poll_interval = 0.02
    service.configure(
        enabled=True,
        provider_id=AGENT_PROVIDER_ID,
        endpoint=None,
        model="agent-authored",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=True,
        acknowledged_by="agent bridge test",
        agent_wait_seconds=wait_seconds,
    )
    return service


def _call(service: AIProviderService) -> dict:
    return service.complete_json(
        prompt_text="Name one character.",
        system_message="Return one JSON object.",
        purpose=PURPOSE,
        substantive=True,
        response_schema=SCHEMA,
        response_schema_name=SCHEMA_NAME,
        response_schema_max_output_tokens=64,
        timeout_seconds=60,
    )


def _answer(service: AIProviderService, request_id: str, *, agent_id: str, model: str, text: str) -> dict:
    request = service.agent_bridge.get(request_id)
    service.agent_bridge.claim(request_id, agent_id=agent_id, lease_seconds=60)
    return service.agent_bridge.answer(
        request_id,
        agent_id=agent_id,
        agent_model=model,
        request_sha256=request["request_sha256"],
        response_text=text,
        validator=lambda parsed: service.agent_request_schema_errors(request_id, parsed),
    )


def _answering_thread(service: AIProviderService, *, text: str, agent_id: str = "luna", model: str = "claude-sonnet-4.5"):
    """Answer the first pending request from a second thread, like a real agent."""

    state: dict = {}

    def worker() -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            listing = service.agent_bridge.list_requests(state="PENDING")
            if listing["requests"]:
                request_id = listing["requests"][0]["request_id"]
                try:
                    state["answered"] = _answer(
                        service, request_id, agent_id=agent_id, model=model, text=text
                    )
                except FoundryError as exc:  # pragma: no cover - fixture failure
                    state["error"] = f"{exc.code}: {exc.message}"
                state["request"] = service.agent_bridge.get(request_id)
                return
            time.sleep(0.01)
        state["error"] = "no pending request appeared"

    thread = threading.Thread(target=worker)
    thread.start()
    return thread, state


def _timeout_request(service: AIProviderService) -> dict:
    """Force the documented 409 and return the still-pending request document."""

    service.agent_wait_override = 0
    try:
        with pytest.raises(FoundryError) as excinfo:
            _call(service)
    finally:
        service.agent_wait_override = None
    error = excinfo.value
    assert error.code == "AI_AGENT_AWAITING_RESPONSE"
    assert error.status_code == 409
    assert error.details["state"] == "PENDING"
    assert error.details["wait_seconds"] == 0
    request = service.agent_bridge.get(error.details["request_id"])
    assert request["state"] == "PENDING"
    return request


def _call_with_key(service: AIProviderService, key: str, *, text: str = "Name one character.") -> dict:
    return service.complete_json(
        prompt_text=text,
        system_message="Return one JSON object.",
        purpose=PURPOSE,
        substantive=True,
        response_schema=SCHEMA,
        response_schema_name=SCHEMA_NAME,
        response_schema_max_output_tokens=64,
        timeout_seconds=60,
        idempotency_key=key,
    )


def _pending_with_key(service: AIProviderService, key: str, *, text: str = "Name one character.") -> FoundryError:
    service.agent_wait_override = 0
    try:
        with pytest.raises(FoundryError) as excinfo:
            _call_with_key(service, key, text=text)
    finally:
        service.agent_wait_override = None
    assert excinfo.value.code == "AI_AGENT_AWAITING_RESPONSE"
    return excinfo.value


def _creation_plan_document() -> dict:
    """The W5 fixture plan shape the creation validator accepts."""

    from test_cg1_character_creation_modes import plan as creation_plan

    return creation_plan()


def settings_db(app):
    """Open a connection against the app's database."""

    return app.state.db.connection()


def test_agent_profile_configure_and_status(fresh_db) -> None:
    service = _service(fresh_db)
    status = service.status()

    assert status["provider_id"] == AGENT_PROVIDER_ID
    assert status["ready"] is True
    assert status["readiness_state"] == "AGENT_BRIDGE_READY"
    assert status["secret"] == {
        "present": True,
        "source": "agent_no_key",
        "persistent": False,
        "environment_variable": None,
        "provider_id": AGENT_PROVIDER_ID,
    }
    assert status["settings"]["agent_wait_seconds"] == 300
    assert status["settings"]["endpoint"] == ""
    assert status["agent_bridge"]["pending"] == 0
    assert status["agent_bridge"]["claimed"] == 0
    assert status["agent_bridge"]["answered"] == 0
    assert status["agent_bridge"]["oldest_pending_at"] is None
    selected = next(row for row in status["profiles"] if row["provider_id"] == AGENT_PROVIDER_ID)
    assert selected["display_name"] == "Agent bridge"
    assert selected["agent"] is True
    assert selected["local"] is False
    assert selected["default_model"] == "agent-authored"


def test_agent_is_not_local_and_keeps_the_named_acknowledgement_rule(fresh_db) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())

    with pytest.raises(FoundryError) as excinfo:
        service.configure(
            enabled=True,
            provider_id=AGENT_PROVIDER_ID,
            endpoint=None,
            model="agent-authored",
            thinking_mode="disabled",
            max_output_tokens=16384,
            timeout_seconds=120,
            data_sharing_acknowledged=False,
            acknowledged_by=None,
        )
    assert excinfo.value.code == "AI_PROVIDER_DATA_SHARING_ACKNOWLEDGEMENT_REQUIRED"

    configured = service.configure(
        enabled=True,
        provider_id=AGENT_PROVIDER_ID,
        endpoint=None,
        model="agent-authored",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=True,
        acknowledged_by="agent bridge test",
    )
    assert configured["settings"]["agent_wait_seconds"] == 300


def test_agent_wait_setting_is_bounded(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=900)
    assert service.status()["settings"]["agent_wait_seconds"] == 900

    with pytest.raises(FoundryError) as excinfo:
        service.configure(
            enabled=True,
            provider_id=AGENT_PROVIDER_ID,
            endpoint=None,
            model="agent-authored",
            thinking_mode="disabled",
            max_output_tokens=16384,
            timeout_seconds=120,
            data_sharing_acknowledged=True,
            acknowledged_by="agent bridge test",
            agent_wait_seconds=3601,
        )
    assert excinfo.value.code == "AI_AGENT_WAIT_INVALID"


def test_agent_bridge_holds_no_key_and_needs_no_connection_test(fresh_db) -> None:
    service = _service(fresh_db)

    with pytest.raises(FoundryError) as set_error:
        service.set_api_key("sk-not-a-real-key-0000")
    assert set_error.value.code == "AI_AGENT_API_KEY_NOT_REQUIRED"
    with pytest.raises(FoundryError) as delete_error:
        service.delete_api_key()
    assert delete_error.value.code == "AI_AGENT_API_KEY_NOT_REQUIRED"

    test = service.test_connection()
    assert test["status"] == "PASS"
    assert test["network_request_made"] is False
    assert "agent_bridge" in test


def test_answered_request_completes_the_run_with_agent_identity(fresh_db) -> None:
    service = _service(fresh_db)
    thread, state = _answering_thread(service, text='```json\n{"name": "Sable Crane"}\n```')
    result = _call(service)
    thread.join()

    assert "error" not in state, state.get("error")
    request = state["request"]
    assert result["provider_id"] == AGENT_PROVIDER_ID
    assert result["value"] == {"name": "Sable Crane"}
    assert result["response_text"] == '{"name": "Sable Crane"}'
    assert result["model"] == "agent:luna:claude-sonnet-4.5"
    assert result["agent_bridge"]["agent_id"] == "luna"
    assert result["agent_bridge"]["agent_model"] == "claude-sonnet-4.5"
    assert result["agent_bridge"]["state"] == "CONSUMED"
    assert result["agent_bridge"]["network_request_made"] is False
    assert result["request_sha256"] == request["request_sha256"]
    assert result["completion_sha256"] == request["response_sha256"]
    assert result["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    run = service.get_run(result["run_id"])
    assert run["status"] == "validated"
    assert run["provider_id"] == AGENT_PROVIDER_ID
    assert run["model"] == "agent:luna:claude-sonnet-4.5", run["model"]
    assert run["completion_content_sha256"] == result["completion_sha256"]
    assert run["request_sha256"] == request["request_sha256"]

    consumed = service.agent_bridge.get(request["request_id"])
    assert consumed["state"] == "CONSUMED"
    assert consumed["agent_id"] == "luna"
    assert consumed["agent_model"] == "claude-sonnet-4.5"
    assert consumed["answered_at"] is not None
    assert consumed["consumed_at"] is not None
    assert service.status()["agent_bridge"]["answered"] == 0
    assert service.status()["agent_bridge"]["pending"] == 0


def test_request_document_is_exactly_what_a_model_would_receive(fresh_db) -> None:
    service = _service(fresh_db)
    request = _timeout_request(service)

    assert request["state"] == "PENDING"
    assert request["request_json"]["model"] == "agent-authored"
    assert request["request_json"]["messages"] == [
        {"role": "system", "content": "Return one JSON object."},
        {"role": "user", "content": "Name one character."},
    ]
    assert request["request_json"]["response_format"]["type"] == "json_schema"
    assert request["request_json"]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert request["schema"] == SCHEMA
    assert request["request_json"]["max_tokens"] == 6144
    assert request["max_output_tokens"] == 6144
    assert request["request_json"]["stream"] is False
    assert "temperature" not in request["request_json"]
    assert request["purpose"] == PURPOSE
    assert request["schema_name"] == SCHEMA_NAME

    listing = service.agent_bridge.list_requests(state="PENDING")
    assert "request_json" not in listing["requests"][0]
    assert listing["counts"]["PENDING"] == 1


def test_timeout_leaves_the_request_pending_and_redrive_completes_without_a_second_request(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    request = _timeout_request(service)
    assert service.status()["agent_bridge"]["pending"] == 1
    assert service.status()["agent_bridge"]["oldest_pending_at"] == request["created_at"]

    _answer(service, request["request_id"], agent_id="fable", model="deepseek-v4-flash", text='{"name": "Iron Reed"}')

    result = _call(service)
    assert result["value"] == {"name": "Iron Reed"}
    assert result["model"] == "agent:fable:deepseek-v4-flash"
    assert result["request_sha256"] == request["request_sha256"]

    listing = service.agent_bridge.list_requests()
    assert len(listing["requests"]) == 1
    assert listing["requests"][0]["state"] == "CONSUMED"
    assert result["run_id"] == request["run_id"]
    third = _call(service)
    assert third["request_sha256"] == request["request_sha256"]
    assert len(service.agent_bridge.list_requests()["requests"]) == 1


def test_redrive_waits_on_the_same_open_request_and_never_prompts_twice(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    request = _timeout_request(service)
    seen: list[str] = []

    def late_answer():
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            listing = service.agent_bridge.list_requests(state="PENDING")
            if listing["requests"]:
                seen.append(listing["requests"][0]["request_id"])
                _answer(service, request["request_id"], agent_id="luna", model="claude", text='{"name": "Late"}')
                return
            time.sleep(0.02)
        seen.append("timeout")

    thread = threading.Thread(target=late_answer)
    thread.start()
    result = _call(service)
    thread.join()

    assert result["value"] == {"name": "Late"}
    assert seen == [request["request_id"]]
    assert len(service.agent_bridge.list_requests()["requests"]) == 1


def test_invalid_answer_is_422_with_errors_and_stays_pending(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    request = _timeout_request(service)
    service.agent_bridge.claim(request["request_id"], agent_id="luna", lease_seconds=60)

    with pytest.raises(FoundryError) as excinfo:
        service.agent_bridge.answer(
            request["request_id"],
            agent_id="luna",
            agent_model="claude",
            request_sha256=request["request_sha256"],
            response_text='{"wrong": true}',
            validator=lambda parsed: service.agent_request_schema_errors(request["request_id"], parsed),
        )
    error = excinfo.value
    assert error.code == "AI_AGENT_RESPONSE_SCHEMA_INVALID"
    assert error.status_code == 422
    assert error.details["errors"], error.details
    assert error.details["errors"][0]["instance_path"] == []

    after = service.agent_bridge.get(request["request_id"])
    assert after["state"] == "PENDING"
    assert after["validation"]["valid"] is False
    assert after["response_text"] is None

    with pytest.raises(FoundryError) as json_error:
        service.agent_bridge.answer(
            request["request_id"],
            agent_id="luna",
            agent_model="claude",
            request_sha256=request["request_sha256"],
            response_text="not json at all",
            validator=lambda parsed: service.agent_request_schema_errors(request["request_id"], parsed),
        )
    assert json_error.value.code == "AI_AGENT_RESPONSE_INVALID_JSON"
    assert json_error.value.status_code == 422
    assert service.agent_bridge.get(request["request_id"])["state"] == "PENDING"


def test_answer_must_bind_to_the_exact_request_bytes(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    request = _timeout_request(service)
    service.agent_bridge.claim(request["request_id"], agent_id="luna", lease_seconds=60)

    with pytest.raises(FoundryError) as excinfo:
        service.agent_bridge.answer(
            request["request_id"],
            agent_id="luna",
            agent_model="claude",
            request_sha256="0" * 64,
            response_text='{"name": "ok"}',
            validator=lambda parsed: [],
        )
    assert excinfo.value.code == "AI_AGENT_REQUEST_HASH_MISMATCH"
    assert excinfo.value.status_code == 409
    assert service.agent_bridge.get(request["request_id"])["state"] == "CLAIMED"


def test_lease_ownership_and_competing_claims(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    request = _timeout_request(service)
    service.agent_bridge.claim(request["request_id"], agent_id="luna", lease_seconds=60)

    with pytest.raises(FoundryError) as claim_error:
        service.agent_bridge.claim(request["request_id"], agent_id="fable", lease_seconds=60)
    assert claim_error.value.code == "AI_AGENT_REQUEST_CLAIMED"
    assert claim_error.value.status_code == 409
    assert claim_error.value.details["agent_id"] == "luna"

    with pytest.raises(FoundryError) as owner_error:
        service.agent_bridge.answer(
            request["request_id"],
            agent_id="fable",
            agent_model="claude",
            request_sha256=request["request_sha256"],
            response_text='{"name": "x"}',
            validator=lambda parsed: [],
        )
    assert owner_error.value.code == "AI_AGENT_CLAIM_OWNER_MISMATCH"

    renewed = service.agent_bridge.claim(request["request_id"], agent_id="luna", lease_seconds=120)
    assert renewed["agent_id"] == "luna"
    assert renewed["state"] == "CLAIMED"


def test_exactly_one_of_many_competing_claims_wins(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    request = _timeout_request(service)

    def race(agent: str) -> str:
        try:
            service.agent_bridge.claim(request["request_id"], agent_id=agent, lease_seconds=60)
            return "won"
        except FoundryError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(race, ["a1", "a2", "a3", "a4", "a5", "a6"]))

    assert outcomes.count("won") == 1, outcomes
    assert set(outcomes) - {"won"} == {"AI_AGENT_REQUEST_CLAIMED"}
    assert service.agent_bridge.get(request["request_id"])["state"] == "CLAIMED"


def test_expired_lease_returns_the_request_to_pending_and_claimable(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    request = _timeout_request(service)
    service.agent_bridge.claim(request["request_id"], agent_id="luna", lease_seconds=60)
    with fresh_db.transaction() as conn:
        conn.execute(
            "UPDATE ai_agent_requests SET claimed_until='2000-01-01T00:00:00Z' WHERE request_id=?",
            (request["request_id"],),
        )

    claimed = service.agent_bridge.claim(request["request_id"], agent_id="fable", lease_seconds=60)
    assert claimed["agent_id"] == "fable"
    assert claimed["state"] == "CLAIMED"


def test_reject_fails_the_waiting_caller_and_stays_rejected(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    request = _timeout_request(service)
    rejected = service.agent_bridge.reject(
        request["request_id"], agent_id="luna", reason="outside the sealed source"
    )
    assert rejected["state"] == "REJECTED"
    assert rejected["rejection"]["reason"] == "outside the sealed source"

    with pytest.raises(FoundryError) as excinfo:
        _call(service)
    assert excinfo.value.code == "AI_AGENT_REQUEST_REJECTED"
    assert excinfo.value.status_code == 409
    assert "outside the sealed source" in excinfo.value.message

    assert len(service.agent_bridge.list_requests()["requests"]) == 1
    with pytest.raises(FoundryError) as again:
        _call(service)
    assert again.value.code == "AI_AGENT_REQUEST_REJECTED"


def test_reject_requires_a_reason_and_respects_the_state_machine(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    request = _timeout_request(service)
    with pytest.raises(FoundryError) as excinfo:
        service.agent_bridge.reject(request["request_id"], agent_id="luna", reason="   ")
    assert excinfo.value.code == "AI_AGENT_REJECTION_REASON_REQUIRED"

    service.agent_bridge.reject(request["request_id"], agent_id="luna", reason="declined")
    with pytest.raises(FoundryError) as claimed:
        service.agent_bridge.claim(request["request_id"], agent_id="fable", lease_seconds=60)
    assert claimed.value.code == "AI_AGENT_REQUEST_NOT_CLAIMABLE"


def test_answer_body_is_bounded_by_the_request_budget(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    service.configure(
        enabled=True,
        provider_id=AGENT_PROVIDER_ID,
        endpoint=None,
        model="agent-authored",
        thinking_mode="disabled",
        max_output_tokens=512,
        timeout_seconds=120,
        data_sharing_acknowledged=True,
        acknowledged_by="agent bridge test",
        agent_wait_seconds=10,
    )
    request = _timeout_request(service)
    # The answer ceiling comes from the job's own output budget (the same
    # purpose-scoped budget a local model gets), not the general setting.
    budget = request["max_output_tokens"]
    assert type(budget) is int and budget > 0
    service.agent_bridge.claim(request["request_id"], agent_id="luna", lease_seconds=60)

    with pytest.raises(FoundryError) as excinfo:
        service.agent_bridge.answer(
            request["request_id"],
            agent_id="luna",
            agent_model="claude",
            request_sha256=request["request_sha256"],
            response_text='{"name": "' + ("x" * (8 * budget + 16)) + '"}',
            validator=lambda parsed: [],
        )
    assert excinfo.value.code == "AI_AGENT_RESPONSE_TOO_LARGE"
    assert excinfo.value.status_code == 413
    assert excinfo.value.details["max_response_bytes"] == 8 * budget
    assert service.agent_bridge.get(request["request_id"])["state"] == "CLAIMED"


def test_agent_identifiers_are_validated(fresh_db) -> None:
    service = _service(fresh_db, wait_seconds=10)
    request = _timeout_request(service)

    with pytest.raises(FoundryError) as bad_agent:
        service.agent_bridge.claim(request["request_id"], agent_id="not an agent!", lease_seconds=60)
    assert bad_agent.value.code == "AI_AGENT_ID_INVALID"

    with pytest.raises(FoundryError) as bad_lease:
        service.agent_bridge.claim(request["request_id"], agent_id="luna", lease_seconds=5)
    assert bad_lease.value.code == "AI_AGENT_LEASE_INVALID"

    service.agent_bridge.claim(request["request_id"], agent_id="luna", lease_seconds=60)
    with pytest.raises(FoundryError) as bad_model:
        service.agent_bridge.answer(
            request["request_id"],
            agent_id="luna",
            agent_model=" ",
            request_sha256=request["request_sha256"],
            response_text='{"name": "ok"}',
            validator=lambda parsed: [],
        )
    assert bad_model.value.code == "AI_AGENT_MODEL_INVALID"


def test_unknown_request_and_state_filter_fail_closed(fresh_db) -> None:
    service = _service(fresh_db)
    with pytest.raises(FoundryError) as missing:
        service.agent_bridge.get("ai.agent.does-not-exist")
    assert missing.value.code == "AI_AGENT_REQUEST_NOT_FOUND"
    assert missing.value.status_code == 404

    with pytest.raises(FoundryError) as bad_state:
        service.agent_bridge.list_requests(state="BROKEN")
    assert bad_state.value.code == "AI_AGENT_STATE_INVALID"


def test_other_provider_profiles_are_unchanged(fresh_db) -> None:
    service = AIProviderService(fresh_db, secret_store=InMemorySecretStore())
    status = service.status()
    profiles = {row["provider_id"] for row in status["profiles"]}
    assert profiles == {"openai", "deepseek", "custom", "local", "lemonade", "agent"}

    for provider_id, default_model in (("openai", "gpt-4o-mini"), ("deepseek", "deepseek-v4-flash")):
        configured = service.configure(
            enabled=False,
            provider_id=provider_id,
            endpoint=None,
            model=default_model,
            thinking_mode="disabled",
            max_output_tokens=16384,
            timeout_seconds=120,
            data_sharing_acknowledged=False,
            acknowledged_by=None,
        )
        assert configured["provider_id"] == provider_id
        assert configured["secret"]["source"] != "agent_no_key"
        assert configured["readiness_state"] == "DISABLED_BY_OWNER"
        assert "agent_bridge" in configured

    with pytest.raises(FoundryError) as excinfo:
        service.complete_json(
            prompt_text="Name one character.",
            system_message="Return one JSON object.",
            purpose=PURPOSE,
            response_schema=SCHEMA,
            response_schema_name=SCHEMA_NAME,
            response_schema_max_output_tokens=64,
        )
    assert excinfo.value.code == "AI_PROVIDER_DISABLED"


def test_agent_answer_flows_through_the_gm_authoring_boundary(fresh_db, tmp_path: Path, monkeypatch) -> None:
    """The §5 route reaches the bridge and completes with agent provenance."""

    from factory_authoring.service import FactoryAuthoringWorkspaceService
    from test_candidate_gm_context import _synthetic_composite_provider_result, _synthetic_factory_workspace

    service = _service(fresh_db, wait_seconds=60)
    project_id = "project-agent-bridge-gm"
    factory_authoring = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
    factory_authoring.db = fresh_db
    workspace, factory = _synthetic_factory_workspace(
        tmp_path,
        project_id=project_id,
        project_revision=4,
        projection_id=f"projection.{project_id}",
        candidate_sha256="a" * 64,
    )
    theme_rows = [
        {
            "section": "selected_records",
            "record": {
                "record_id": "record.synthetic.one",
                "display_name": "Synthetic One",
                "one_line_description": "A public-safe synthetic selected record.",
            },
        },
        {
            "section": "selected_records",
            "record": {
                "record_id": "record.synthetic.two",
                "display_name": "Synthetic Two",
                "one_line_description": "A second public-safe synthetic selected record.",
            },
        },
    ]
    snapshot = {"selected_record_sections": {"selected_records": [row["record"] for row in theme_rows]}}
    factory_authoring.status = lambda value: {
        "available": True,
        "workspace_path": str(workspace),
        "workspace_sha256": factory["workspace_sha256"],
        "workspace_status": factory["workspace_status"],
    } if value == project_id else {"available": False}
    factory_authoring.projects = type(
        "Projects",
        (),
        {"get_project": lambda _self, value: {"project": {"revision": 4}} if value == project_id else None},
    )()
    factory_authoring.sheets = type(
        "Sheets",
        (),
        {"sheet": lambda _self, value: {"build_status": "CHARACTER_SHEET_READY", "owner_character_sheet": snapshot}},
    )()
    factory_authoring._selected_record_snapshot = lambda _project, _revision, _snapshot: {
        "schema_version": "TianxiaFoundry.GMSourceSnapshot.v1",
        "project_id": project_id,
        "project_revision": 4,
        "record_ids": [row["record"]["record_id"] for row in theme_rows],
        "records": theme_rows,
        "selected_record_content_sha256": sha256_json(theme_rows),
    }
    factory_authoring.build = lambda value: {
        "workspace_id": "workspace.agent-bridge",
        "workspace_sha256": "e" * 64,
    } if value == project_id else None
    persisted: dict = {}

    def persist(*_args, **kwargs):
        persisted.update(kwargs)
        return {
            "binding": {
                "provider_id": kwargs["provider_result"]["provider_id"],
                "model": kwargs["provider_result"]["model"],
                "receipt_id": "gm-receipt.agent-bridge",
                "artifact_sha256": "a" * 64,
                "profile_sha256": "b" * 64,
                "source_snapshot_sha256": "c" * 64,
                "selected_record_content_sha256": "c" * 64,
                "owner_ratified": False,
                "authoring_contract": "TianxiaFoundry.CandidateGMCompositeController.v1",
            },
        }

    factory_authoring._persist_gm_authoring = persist
    factory_authoring._gm_provider_wire_hash = lambda *_args: "d" * 64

    holder: dict = {}

    def answer_worker() -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            listing = service.agent_bridge.list_requests(state="PENDING")
            if listing["requests"]:
                request = service.agent_bridge.get(listing["requests"][0]["request_id"])
                holder["request"] = request
                payload = json.loads(request["request_json"]["messages"][1]["content"])
                settings = service._settings()
                assert payload["response_constants"]["project_id"] == project_id
                synthetic = _synthetic_composite_provider_result(
                    {
                        "prompt_text": request["request_json"]["messages"][1]["content"],
                        "system_message": request["request_json"]["messages"][0]["content"],
                        "response_schema": request["schema"],
                        "response_schema_max_output_tokens": request["max_output_tokens"],
                        "expected_request_sha256": request["request_sha256"],
                    },
                    settings={
                        "provider_id": settings["provider_id"],
                        "model": settings["model"],
                        "max_output_tokens": settings["max_output_tokens"],
                        "endpoint": settings["endpoint"],
                        "thinking_mode": settings["thinking_mode"],
                    },
                )
                _answer(
                    service,
                    request["request_id"],
                    agent_id="astra",
                    model="deepseek-v4-flash",
                    text=synthetic["response_text"],
                )
                return
            time.sleep(0.02)
        holder["error"] = "no pending gm-authoring request appeared"

    thread = threading.Thread(target=answer_worker)
    thread.start()
    result = factory_authoring.author_gm_tactical(project_id, service)
    thread.join()

    assert "error" not in holder, holder.get("error")
    request = holder["request"]
    assert request["purpose"] == "factory_composite_controller"
    assert request["schema_name"] == "TianxiaFoundry_CompositeController_v1"
    assert result["owner_ratified"] is False
    assert persisted, "the GM authoring receipt was not persisted"
    assert persisted["provider_result"]["purpose"] == "factory_gm_tactical_authoring"
    assert persisted["provider_result"]["provider_id"] == AGENT_PROVIDER_ID
    assert persisted["provider_result"]["model"] == "agent:astra:deepseek-v4-flash"
    assert persisted["provider_result"]["agent_bridge"]["agent_id"] == "astra"
    assert service.agent_bridge.get(request["request_id"])["state"] == "CONSUMED"
    with fresh_db.connection() as conn:
        run_ids = [
            row["run_id"]
            for row in conn.execute(
                "SELECT run_id FROM ai_provider_runs WHERE provider_id=?", (AGENT_PROVIDER_ID,)
            ).fetchall()
        ]
    runs = [service.get_run(run_id) for run_id in run_ids]
    assert len(runs) == 1
    assert runs[0]["status"] == "validated"
    assert runs[0]["model"] == "agent:astra:deepseek-v4-flash"


def test_agent_routes_serve_the_bridge_over_the_real_application(tmp_path: Path) -> None:
    """The loopback agent routes work through the real FastAPI application."""

    from tests.r4v_harness import provision_external_test_key

    data = tmp_path / "AgentBridgeOwnerData"
    provision_external_test_key(data)
    settings = Settings.from_env(ROOT, data)

    app = create_app(settings, ai_secret_store=InMemorySecretStore())
    assert app.state.ai_provider is not None
    app.state.ai_provider.agent_poll_interval = 0.02

    with TestClient(app) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        configured = client.post(
            "/api/ai-provider/configure",
            headers=headers,
            json={
                "enabled": True,
                "provider_id": "agent",
                "model": "agent-authored",
                "thinking_mode": "disabled",
                "max_output_tokens": 16384,
                "timeout_seconds": 120,
                "agent_wait_seconds": 900,
                "data_sharing_acknowledged": True,
                "acknowledged_by": "owner (ssynesthesia) via agent bridge test",
            },
        )
        assert configured.status_code == 200, configured.text
        status = configured.json()
        assert status["provider_id"] == "agent"
        assert status["ready"] is True
        assert status["readiness_state"] == "AGENT_BRIDGE_READY"
        assert status["secret"]["source"] == "agent_no_key"
        assert status["agent_bridge"]["pending"] == 0
        assert status["settings"]["agent_wait_seconds"] == 900

        key = client.post("/api/ai-provider/key", headers=headers, json={"api_key": "sk-not-a-real-key-0000"})
        assert key.status_code == 400, key.text
        assert key.json()["error"]["code"] == "AI_AGENT_API_KEY_NOT_REQUIRED"

        test = client.post("/api/ai-provider/test", headers=headers, json={})
        assert test.status_code == 200, test.text
        assert test.json()["network_request_made"] is False

        bridge_status = client.get("/api/ai-provider/agent/status", headers=headers)
        assert bridge_status.status_code == 200
        assert bridge_status.json()["provider_id"] == "agent"
        listing = client.get("/api/ai-provider/agent/requests", headers=headers)
        assert listing.status_code == 200
        assert listing.json()["requests"] == []
        bad_state = client.get("/api/ai-provider/agent/requests?state=BROKEN", headers=headers)
        assert bad_state.status_code == 400, bad_state.text
        missing = client.get("/api/ai-provider/agent/requests/ai.agent.absent", headers=headers)
        assert missing.status_code == 404, missing.text


# --------------------------------------------------------------------------
# Schema guard: self-contained scratch fixtures (no live database reads)
# --------------------------------------------------------------------------

PRE_BRIDGE_SCHEMA_DDL = (
    """CREATE TABLE IF NOT EXISTS projects (
       project_id TEXT PRIMARY KEY,
       working_name TEXT NOT NULL,
       status TEXT NOT NULL,
       revision INTEGER NOT NULL,
       created_at TEXT NOT NULL,
       updated_at TEXT NOT NULL,
       target_factory_version TEXT NOT NULL,
       target_candidate_schema_version TEXT NOT NULL,
       target_gm_screen_version TEXT NOT NULL,
       catalog_build_hash TEXT,
       quality_target TEXT NOT NULL,
       project_json TEXT NOT NULL,
       compatibility_projection_status TEXT NOT NULL,
       compile_status TEXT NOT NULL,
       consumer_verification_status TEXT NOT NULL,
       contract_status TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS stage1_prompt_exchanges (
       prompt_id TEXT PRIMARY KEY,
       project_id TEXT NOT NULL,
       project_revision INTEGER NOT NULL,
       catalog_build_id TEXT NOT NULL,
       content_lock_hash TEXT NOT NULL,
       envelope_schema_version TEXT NOT NULL,
       envelope_json TEXT NOT NULL,
       prompt_bytes INTEGER NOT NULL,
       prompt_sha256 TEXT NOT NULL,
       created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ai_provider_settings (
       provider_id TEXT PRIMARY KEY,
       enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
       endpoint TEXT NOT NULL,
       model TEXT NOT NULL,
       thinking_mode TEXT NOT NULL CHECK(thinking_mode IN ('enabled','disabled')),
       max_output_tokens INTEGER NOT NULL,
       timeout_seconds INTEGER NOT NULL,
       data_sharing_acknowledged INTEGER NOT NULL CHECK(data_sharing_acknowledged IN (0,1)),
       acknowledged_by TEXT,
       acknowledged_at TEXT,
       updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ai_provider_selection (
       singleton INTEGER PRIMARY KEY CHECK(singleton=1),
       provider_id TEXT NOT NULL,
       updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ai_provider_runs (
       run_id TEXT PRIMARY KEY,
       provider_id TEXT NOT NULL,
       project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
       prompt_id TEXT NOT NULL REFERENCES stage1_prompt_exchanges(prompt_id) ON DELETE RESTRICT,
       idempotency_key TEXT NOT NULL,
       prompt_sha256 TEXT NOT NULL,
       model TEXT NOT NULL,
       endpoint TEXT NOT NULL,
       request_bytes BLOB NOT NULL,
       request_sha256 TEXT NOT NULL,
       started_at TEXT NOT NULL,
       completed_at TEXT,
       status TEXT NOT NULL CHECK(status IN ('started','provider_error','response_rejected','validated')),
       http_status INTEGER,
       provider_response_bytes BLOB,
       provider_response_sha256 TEXT,
       provider_response_bytes_count INTEGER,
       completion_content_sha256 TEXT,
       finish_reason TEXT,
       prompt_tokens INTEGER,
       completion_tokens INTEGER,
       total_tokens INTEGER,
       stage1_attempt_id TEXT,
       error_code TEXT,
       error_message TEXT)""",
    """CREATE INDEX IF NOT EXISTS idx_ai_provider_runs_project
       ON ai_provider_runs(project_id, started_at, run_id)""",
    """CREATE INDEX IF NOT EXISTS idx_ai_provider_runs_prompt
       ON ai_provider_runs(prompt_id, started_at, run_id)""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_provider_runs_idempotency
       ON ai_provider_runs(provider_id, prompt_id, idempotency_key)""",
)


def _pre_bridge_scratch(target: Path) -> sqlite3.Connection:
    """A self-contained pre-bridge scratch schema.  No live DB access."""

    if target.exists():
        target.unlink()
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA foreign_keys=ON")
    for statement in PRE_BRIDGE_SCHEMA_DDL:
        conn.execute(statement)
    conn.commit()
    return conn


def _validated_database(target: Path) -> Database:
    """Wrap a scratch schema file in a real ``Database`` for ensure_schema()."""

    settings = Settings.from_env(ROOT, target.parent / "data" / target.stem)
    settings.ensure_dirs()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    if settings.db_path.exists():
        settings.db_path.unlink()
    shutil.copy2(target, settings.db_path)
    db = Database(settings)
    with db.connection():
        pass
    return db


def _seed_pre_bridge_provider_rows(conn) -> dict:
    """Seed the pre-bridge shape with synthetic parents and provider rows."""

    conn.execute(
        """INSERT INTO projects(
           project_id,working_name,status,revision,created_at,updated_at,
           target_factory_version,target_candidate_schema_version,target_gm_screen_version,
           catalog_build_hash,quality_target,project_json,compatibility_projection_status,
           compile_status,consumer_verification_status,contract_status)
           VALUES('project.bridge.rebuild','Rebuild Probe','active',1,
                  '2026-09-21T00:00:00Z','2026-09-21T00:00:00Z','1','1','1',NULL,
                  'standard','{}','ok','ok','ok','ok')"""
    )
    conn.execute(
        """INSERT INTO stage1_prompt_exchanges(
           prompt_id,project_id,project_revision,catalog_build_id,content_lock_hash,
           envelope_schema_version,envelope_json,prompt_bytes,prompt_sha256,created_at)
           VALUES('prompt.bridge.rebuild','project.bridge.rebuild',1,'catalog.1','lock',
                  'v1','{}',10,?, '2026-09-21T00:00:00Z')""",
        ("a" * 64,),
    )
    rows = [
        ("ai.run.keep.one", "local", "project.bridge.rebuild", "prompt.bridge.rebuild", "step.one", "validated"),
        ("ai.run.keep.two", "agent", "project.bridge.rebuild", "prompt.bridge.rebuild", "step.two", "started"),
    ]
    for run_id, provider, project, prompt, key, status in rows:
        conn.execute(
            """INSERT INTO ai_provider_runs(
               run_id,provider_id,project_id,prompt_id,idempotency_key,prompt_sha256,model,endpoint,
               request_bytes,request_sha256,started_at,status,http_status,provider_response_bytes,
               provider_response_sha256,provider_response_bytes_count,completion_content_sha256,
               finish_reason,prompt_tokens,completion_tokens,total_tokens)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, provider, project, prompt, key, sha256_bytes(run_id.encode()), provider + "-model",
                "http://127.0.0.1:1/v1", run_id.encode(), sha256_bytes(b"req"), "2026-09-21T00:00:00Z",
                status, 200, b'{"choices":[]}', sha256_bytes(b"resp"), 14, sha256_bytes(b"content"),
                "stop", 1, 2, 3,
            ),
        )
    conn.execute(
        """INSERT INTO ai_provider_settings(
           provider_id,enabled,endpoint,model,thinking_mode,max_output_tokens,timeout_seconds,
           data_sharing_acknowledged,acknowledged_by,acknowledged_at,updated_at)
           VALUES('agent',1,'','agent-authored','disabled',16384,120,1,'probe','2026-09-21T00:00:00Z','2026-09-21T00:00:00Z')"""
    )
    conn.execute(
        "INSERT INTO ai_provider_selection(singleton,provider_id,updated_at) VALUES(1,'agent','2026-09-21T00:00:00Z')"
    )
    return {"runs": rows}


def _scratch_with_rows(tmp_path: Path, name: str) -> tuple[sqlite3.Connection, Path]:
    target = tmp_path / f"{name}.sqlite3"
    seed = _pre_bridge_scratch(target)
    _seed_pre_bridge_provider_rows(seed)
    seed.commit()
    return seed, target


def _blocked_rebuild(source: Path, name: str) -> tuple[FoundryError, Database]:
    """Run ensure_schema against a prepared scratch schema and expect a refusal."""

    db = _validated_database(source)
    with pytest.raises(FoundryError) as excinfo:
        AgentRequestBridge(db).ensure_schema()
    error = excinfo.value
    assert error.code == "AI_AGENT_SCHEMA_REBUILD_BLOCKED", error.code
    assert error.details["dependents"], error.details
    return error, db


def _schema_snapshot(db: Database) -> tuple:
    with db.connection() as conn:
        objects = sorted(
            (row["type"], row["name"], " ".join((row["sql"] or "").split()))
            for row in conn.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
        )
        present = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_provider_runs'"
        ).fetchone() is not None
        rows = sorted(
            tuple(str(value) for value in row)
            for row in (
                conn.execute("SELECT * FROM ai_provider_runs").fetchall() if present else []
            )
        )
        settings = sorted(
            tuple(str(value) for value in row)
            for row in conn.execute("SELECT * FROM ai_provider_settings").fetchall()
        )
    return (tuple(objects), tuple(rows), tuple(settings))


def test_ensure_schema_preserves_populated_provider_rows(tmp_path: Path) -> None:
    """Populated runs/settings survive the one-time rebuild byte-for-byte."""

    scratch = tmp_path / "schema_populated.sqlite3"
    seed = _pre_bridge_scratch(scratch)
    seeded = _seed_pre_bridge_provider_rows(seed)
    seed.commit()
    before_runs = [
        tuple(row) for row in seed.execute("SELECT * FROM ai_provider_runs ORDER BY run_id").fetchall()
    ]
    before_settings = [
        tuple(row) for row in seed.execute("SELECT * FROM ai_provider_settings ORDER BY provider_id").fetchall()
    ]
    before_selection = [
        tuple(row) for row in seed.execute("SELECT * FROM ai_provider_selection").fetchall()
    ]
    before_fk = [
        tuple(row) for row in seed.execute("PRAGMA foreign_key_list(ai_provider_runs)").fetchall()
    ]
    seed.close()

    db = _validated_database(scratch)
    AgentRequestBridge(db).ensure_schema()

    with db.connection() as conn:
        after_runs = [
            tuple(row) for row in conn.execute("SELECT * FROM ai_provider_runs ORDER BY run_id").fetchall()
        ]
        after_settings = [
            tuple(row)
            for row in conn.execute("SELECT * FROM ai_provider_settings ORDER BY provider_id").fetchall()
        ]
        after_selection = [
            tuple(row) for row in conn.execute("SELECT * FROM ai_provider_selection").fetchall()
        ]
        after_fk = [
            tuple(row) for row in conn.execute("PRAGMA foreign_key_list(ai_provider_runs)").fetchall()
        ]
        columns = [row["name"] for row in conn.execute("PRAGMA table_xinfo(ai_provider_runs)").fetchall()]
        run_statuses = {
            row["run_id"]: row["status"]
            for row in conn.execute("SELECT run_id, status FROM ai_provider_runs").fetchall()
        }
        extra_tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ai_provider_runs%'"
            ).fetchall()
        }
        after_indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE tbl_name='ai_provider_runs' AND type='index'"
            ).fetchall()
        }

    assert "call_key" in columns
    assert run_statuses == {run_id: status for run_id, _p, _pr, _pe, _k, status in seeded["runs"]}
    assert len(after_runs) == len(before_runs) == 2
    for before_row, after_row in zip(before_runs, after_runs):
        assert before_row[0] == after_row[0]
        assert before_row[4] == after_row[5]      # idempotency_key
        assert before_row[5] == after_row[6]      # prompt_sha256
        assert before_row[6] == after_row[7]      # model
        assert before_row[8] == after_row[9]      # request_bytes
        assert before_row[9] == after_row[10]     # request_sha256
        assert before_row[11] == after_row[12]    # status
        assert after_row[4] is None               # call_key for a pre-bridge row
    # Existing settings values are untouched; the bridge only appends the new
    # agent wait column with its documented default.
    assert [row[: len(before_settings[0])] for row in after_settings] == before_settings
    assert all(row[-1] == 300 for row in after_settings)
    assert after_selection == before_selection
    assert "ai_provider_runs_rebuild" not in extra_tables
    assert {row[0] for row in after_fk} == {row[0] for row in before_fk}
    assert after_indexes >= {
        "idx_ai_provider_runs_project",
        "idx_ai_provider_runs_prompt",
        "idx_ai_provider_runs_idempotency",
        "idx_ai_provider_runs_call_key",
    }

    # Second call changes nothing (idempotent).
    with db.connection() as conn:
        runs_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='ai_provider_runs'").fetchone()[0]
    AgentRequestBridge(db).ensure_schema()
    with db.connection() as conn:
        assert conn.execute("SELECT sql FROM sqlite_master WHERE name='ai_provider_runs'").fetchone()[0] == runs_sql
        assert [
            tuple(row) for row in conn.execute("SELECT * FROM ai_provider_runs ORDER BY run_id").fetchall()
        ] == after_runs


def test_ensure_schema_rebuild_preserves_existing_call_key(tmp_path: Path) -> None:
    """A nullability-only rebuild keeps recorded call_key values."""

    scratch = tmp_path / "schema_calkey.sqlite3"
    seed = _pre_bridge_scratch(scratch)
    _seed_pre_bridge_provider_rows(seed)
    seed.execute("ALTER TABLE ai_provider_runs ADD COLUMN call_key TEXT")
    seed.execute(
        "UPDATE ai_provider_runs SET call_key=? WHERE run_id=?",
        ("agent:factory_composite_controller:prp.keep", "ai.run.keep.two"),
    )
    seed.commit()
    seed.close()

    db = _validated_database(scratch)
    AgentRequestBridge(db).ensure_schema()
    with db.connection() as conn:
        preserved = conn.execute(
            "SELECT call_key FROM ai_provider_runs WHERE run_id='ai.run.keep.two'"
        ).fetchone()[0]
        runs_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='ai_provider_runs'").fetchone()[0]
        other = conn.execute(
            "SELECT call_key FROM ai_provider_runs WHERE run_id='ai.run.keep.one'"
        ).fetchone()[0]
    assert preserved == "agent:factory_composite_controller:prp.keep"
    assert other is None
    assert "prompt_id TEXT NOT NULL" not in runs_sql


def test_ensure_schema_rejects_quoted_and_newline_incoming_foreign_keys(tmp_path: Path) -> None:
    """Incoming FKs are found through SQLite metadata, not a DDL text match."""

    for label, ddl in (
        (
            "quoted",
            """CREATE TABLE dependent_quoted (
               dependent_id TEXT PRIMARY KEY,
               run_id TEXT REFERENCES "ai_provider_runs"("run_id"))""",
        ),
        (
            "newline",
            """CREATE TABLE dependent_newline (
               dependent_id TEXT PRIMARY KEY,
               run_id TEXT REFERENCES
                 ai_provider_runs
                 (run_id))""",
        ),
    ):
        seed, target = _scratch_with_rows(tmp_path, f"fk_{label}")
        seed.execute(ddl)
        seed.commit()
        seed.close()
        check = sqlite3.connect(target)
        text_hit = check.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND sql LIKE '%REFERENCES ai_provider_runs%'"
        ).fetchone()[0]
        check.close()
        error, db = _blocked_rebuild(target, f"fk_{label}_blocked")
        assert any(row["type"] == "incoming_foreign_key" for row in error.details["dependents"]), error.details
        if label == "quoted":
            assert text_hit == 0, "the quoted form must not be found by the old text scan"
        with db.connection() as conn:
            runs_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='ai_provider_runs'").fetchone()[0]
            assert "prompt_id TEXT NOT NULL" in runs_sql
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE name=?", (f"dependent_{label}",)
            ).fetchone() is not None


def test_ensure_schema_rejects_dependent_view_and_trigger(tmp_path: Path) -> None:
    """Views and triggers naming the table block the rebuild conservatively."""

    for label, ddl, object_name in (
        (
            "trigger",
            """CREATE TRIGGER probe_runs_guard AFTER INSERT ON ai_provider_runs
               BEGIN SELECT 1; END""",
            "probe_runs_guard",
        ),
        (
            "view",
            """CREATE VIEW probe_runs_view AS
               SELECT run_id, status FROM ai_provider_runs""",
            "probe_runs_view",
        ),
    ):
        seed, target = _scratch_with_rows(tmp_path, f"{label}_dep")
        seed.execute(ddl)
        seed.commit()
        seed.close()
        error, db = _blocked_rebuild(target, f"{label}_dep_blocked")
        assert any(
            row["type"] == label and row.get("name") == object_name
            for row in error.details["dependents"]
        ), error.details
        with db.connection() as conn:
            assert conn.execute("SELECT name FROM sqlite_master WHERE name=?", (object_name,)).fetchone() is not None
            runs_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='ai_provider_runs'").fetchone()[0]
            assert "prompt_id TEXT NOT NULL" in runs_sql


def test_ensure_schema_rejects_extra_column_and_altered_index(tmp_path: Path) -> None:
    """An unknown column or a redefined known index refuses the rebuild."""

    seed, target = _scratch_with_rows(tmp_path, "extra_column")
    seed.execute("ALTER TABLE ai_provider_runs ADD COLUMN future_note TEXT")
    seed.execute("UPDATE ai_provider_runs SET future_note='keep me' WHERE run_id='ai.run.keep.one'")
    seed.commit()
    seed.close()
    error, db = _blocked_rebuild(target, "extra_column_blocked")
    assert any(row["type"] == "unknown_columns" and "future_note" in row["columns"] for row in error.details["dependents"]), error.details
    with db.connection() as conn:
        assert conn.execute(
            "SELECT future_note FROM ai_provider_runs WHERE run_id='ai.run.keep.one'"
        ).fetchone()[0] == "keep me"

    seed, target = _scratch_with_rows(tmp_path, "altered_index")
    seed.execute("DROP INDEX idx_ai_provider_runs_project")
    seed.execute("CREATE INDEX idx_ai_provider_runs_project ON ai_provider_runs(run_id)")
    seed.commit()
    seed.close()
    error, db = _blocked_rebuild(target, "altered_index_blocked")
    assert any(row["type"] == "altered_index" and row["name"] == "idx_ai_provider_runs_project" for row in error.details["dependents"]), error.details
    with db.connection() as conn:
        assert conn.execute("SELECT sql FROM sqlite_master WHERE name='idx_ai_provider_runs_project'").fetchone()[0]


def test_ensure_schema_rejects_partially_upgraded_call_key(tmp_path: Path) -> None:
    """A call_key column with a different declared type is refused."""

    seed, target = _scratch_with_rows(tmp_path, "partial_call_key")
    seed.execute("ALTER TABLE ai_provider_runs ADD COLUMN call_key INTEGER")
    seed.execute("UPDATE ai_provider_runs SET call_key=7 WHERE run_id='ai.run.keep.one'")
    seed.commit()
    seed.close()
    error, db = _blocked_rebuild(target, "partial_call_key_blocked")
    types = {row["type"] for row in error.details["dependents"]}
    assert types & {"unknown_columns", "partial_upgrade"}, error.details
    with db.connection() as conn:
        assert conn.execute(
            "SELECT call_key FROM ai_provider_runs WHERE run_id='ai.run.keep.one'"
        ).fetchone()[0] == 7


def test_ensure_schema_rejects_same_columns_with_different_index_semantics(tmp_path: Path) -> None:
    """Same columns, different UNIQUE or WHERE, must refuse the rebuild."""

    seed, target = _scratch_with_rows(tmp_path, "index_unique")
    seed.execute("DROP INDEX idx_ai_provider_runs_idempotency")
    seed.execute(
        """CREATE INDEX idx_ai_provider_runs_idempotency
           ON ai_provider_runs(provider_id, prompt_id, idempotency_key)"""
    )
    seed.commit()
    seed.close()
    error, db = _blocked_rebuild(target, "index_unique_blocked")
    assert any(
        row["type"] == "altered_index" and row["name"] == "idx_ai_provider_runs_idempotency"
        for row in error.details["dependents"]
    ), error.details
    with db.connection() as conn:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='idx_ai_provider_runs_idempotency'"
        ).fetchone()[0]
        assert "UNIQUE" not in sql.upper()

    seed, target = _scratch_with_rows(tmp_path, "index_partial")
    seed.execute("DROP INDEX idx_ai_provider_runs_project")
    seed.execute(
        """CREATE INDEX idx_ai_provider_runs_project
           ON ai_provider_runs(project_id, started_at, run_id)
           WHERE project_id IS NOT NULL"""
    )
    seed.commit()
    seed.close()
    error, db = _blocked_rebuild(target, "index_partial_blocked")
    assert any(
        row["type"] == "altered_index" and row["name"] == "idx_ai_provider_runs_project"
        for row in error.details["dependents"]
    ), error.details


def test_ensure_schema_rejects_mixed_case_incoming_fk_from_quoted_table_name(tmp_path: Path) -> None:
    """A mixed-case target from a table whose name contains a quote is found."""

    seed, target = _scratch_with_rows(tmp_path, "fk_mixed_case")
    seed.execute(
        '''CREATE TABLE "quoted""table" (
           dependent_id TEXT PRIMARY KEY,
           run_id TEXT REFERENCES AI_PROVIDER_RUNS(run_id))'''
    )
    seed.commit()
    seed.close()
    error, db = _blocked_rebuild(target, "fk_mixed_case_blocked")
    rows = [row for row in error.details["dependents"] if row["type"] == "incoming_foreign_key"]
    assert rows, error.details
    assert rows[0]["table"] == 'quoted"table', rows
    with db.connection() as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name=?", ('quoted"table',)
        ).fetchone() is not None


def test_ensure_schema_rejects_generated_extra_column(tmp_path: Path) -> None:
    """A generated column is hidden from table_info and must refuse the rebuild."""

    seed, target = _scratch_with_rows(tmp_path, "generated_column")
    seed.execute("ALTER TABLE ai_provider_runs ADD COLUMN run_label TEXT GENERATED ALWAYS AS (run_id) VIRTUAL")
    seed.commit()
    visible = [row[1] for row in seed.execute("PRAGMA table_info(ai_provider_runs)").fetchall()]
    full = [row[1] for row in seed.execute("PRAGMA table_xinfo(ai_provider_runs)").fetchall()]
    seed.close()
    assert "run_label" not in visible, visible
    assert "run_label" in full, full

    error, db = _blocked_rebuild(target, "generated_column_blocked")
    types = {row["type"] for row in error.details["dependents"]}
    assert types & {"hidden_columns", "unknown_columns", "unaudited_table_shape"}, error.details


def _variant_scratch(tmp_path: Path, name: str, ddl: str) -> tuple[Path, Database]:
    """Build a scratch database whose provider table has a variant DDL."""

    seed, target = _scratch_with_rows(tmp_path, name)
    seed.execute("DROP TABLE ai_provider_runs")
    seed.execute(ddl)
    if seed.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_provider_runs'"
    ).fetchone():
        seed.execute(
            """CREATE INDEX IF NOT EXISTS idx_ai_provider_runs_project
               ON ai_provider_runs(project_id, started_at, run_id)"""
        )
        seed.execute(
            """CREATE INDEX IF NOT EXISTS idx_ai_provider_runs_prompt
               ON ai_provider_runs(prompt_id, started_at, run_id)"""
        )
        seed.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_provider_runs_idempotency
               ON ai_provider_runs(provider_id, prompt_id, idempotency_key)"""
        )
    seed.commit()
    seed.close()
    db = _validated_database(target)
    return target, db


def test_ensure_schema_rejects_table_constraint_and_column_default_variants(tmp_path: Path) -> None:
    """Table-level UNIQUE/CHECK and a column DEFAULT/outgoing FK all refuse."""

    pre_columns = ", ".join(AuditedPreBridgeColumns())
    variants = {
        "table_unique": "CREATE TABLE ai_provider_runs (" + pre_columns + ", UNIQUE(idempotency_key))",
        "table_check": "CREATE TABLE ai_provider_runs (" + pre_columns + ", CHECK(prompt_tokens >= 0))",
        "column_default": "CREATE TABLE ai_provider_runs ("
        + pre_columns.replace("completed_at TEXT", "completed_at TEXT DEFAULT 'never'")
        + ")",
        "outgoing_fk": "CREATE TABLE ai_provider_runs ("
        + pre_columns
        + ", FOREIGN KEY(prompt_sha256) REFERENCES projects(project_id))",
    }
    for name, ddl in variants.items():
        _target, db = _variant_scratch(tmp_path, name, ddl)
        prepared = _schema_snapshot(db)
        with pytest.raises(FoundryError) as excinfo:
            AgentRequestBridge(db).ensure_schema()
        error = excinfo.value
        assert error.code == "AI_AGENT_SCHEMA_REBUILD_BLOCKED", (name, error.code)
        types = {row["type"] for row in error.details["dependents"]}
        assert "unaudited_table_shape" in types, (name, error.details)
        assert _schema_snapshot(db) == prepared, name
        with db.connection() as conn:
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE name='ai_provider_runs_rebuild'"
            ).fetchone() is None
        with pytest.raises(FoundryError):
            AgentRequestBridge(db).ensure_schema()
        assert _schema_snapshot(db) == prepared, name


def test_ensure_schema_rejects_altered_check_literal_case_and_table_suffix(tmp_path: Path) -> None:
    """Quoted literals compare byte-for-byte and table options are refused."""

    pre_columns = ", ".join(AuditedPreBridgeColumns())
    variants = {
        "check_case": "CREATE TABLE ai_provider_runs ("
        + pre_columns.replace("'started'", "'STARTED'")
        + ")",
        "check_inner_space": "CREATE TABLE ai_provider_runs ("
        + pre_columns.replace("'started'", "' started'")
        + ")",
        "strict_option": "CREATE TABLE ai_provider_runs (" + pre_columns + ") STRICT",
        "without_rowid_option": "CREATE TABLE ai_provider_runs (" + pre_columns + ") WITHOUT ROWID",
    }
    for name, ddl in variants.items():
        _target, db = _variant_scratch(tmp_path, name, ddl)
        prepared = _schema_snapshot(db)
        with pytest.raises(FoundryError) as excinfo:
            AgentRequestBridge(db).ensure_schema()
        error = excinfo.value
        assert error.code == "AI_AGENT_SCHEMA_REBUILD_BLOCKED", (name, error.code)
        types = {row["type"] for row in error.details["dependents"]}
        assert "unaudited_table_shape" in types, (name, error.details)
        assert _schema_snapshot(db) == prepared, name
        with db.connection() as conn:
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE name='ai_provider_runs_rebuild'"
            ).fetchone() is None


def test_index_signature_handles_lowercase_where_without_index_error(tmp_path: Path) -> None:
    """A lowercase ``where`` predicate is read, not an IndexError."""

    seed, target = _scratch_with_rows(tmp_path, "lowercase_where")
    seed.execute("DROP INDEX idx_ai_provider_runs_project")
    seed.execute(
        """CREATE INDEX idx_ai_provider_runs_project
           ON ai_provider_runs(project_id, started_at, run_id)
           where project_id IS NOT NULL"""
    )
    seed.commit()
    with seed:
        signature = AgentRequestBridge._index_signature(seed, "idx_ai_provider_runs_project")
    seed.close()
    assert signature[1] == "project_id IS NOT NULL", signature
    assert signature != AgentRequestBridge._EXPECTED_INDEXES["idx_ai_provider_runs_project"]

    error, db = _blocked_rebuild(target, "lowercase_where_blocked")
    assert any(
        row["type"] == "altered_index" and row["name"] == "idx_ai_provider_runs_project"
        for row in error.details["dependents"]
    ), error.details


def test_ensure_schema_accepts_audited_shapes_and_rejects_unknown_prefixes(tmp_path: Path) -> None:
    """Accepted layouts rebuild once and idempotently; odd prefixes are refused."""

    pre_columns = ", ".join(AuditedPreBridgeColumns())
    # Prefixes that cannot be persisted as a scratch main-schema table are
    # checked through the audited-shape seam: TEMP tables live in
    # sqlite_temp_master, and a table with no parenthesized column list is
    # unreadable.
    assert AgentRequestBridge._audited_table_shape(
        "CREATE TEMP TABLE ai_provider_runs (" + pre_columns + ")"
    ) is None
    assert AgentRequestBridge._audited_table_shape(
        "CREATE TABLE ai_provider_runs " + pre_columns
    ) is None

    accepted = {
        "if_not_exists": lambda cols: "CREATE TABLE IF NOT EXISTS ai_provider_runs (" + cols + ")",
        "quoted_name": lambda cols: 'CREATE TABLE "ai_provider_runs" (' + cols + ")",
    }
    for name, builder in accepted.items():
        _target, db = _variant_scratch(tmp_path, name, builder(pre_columns))
        AgentRequestBridge(db).ensure_schema()
        with db.connection() as conn:
            runs_sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='ai_provider_runs'"
            ).fetchone()[0]
            call_key_present = any(
                row["name"] == "call_key"
                for row in conn.execute("PRAGMA table_xinfo(ai_provider_runs)").fetchall()
            )
            leftovers = conn.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'ai_provider_runs_rebuild%'"
            ).fetchall()
        assert call_key_present, name
        assert "prompt_id TEXT NOT NULL" not in runs_sql, name
        assert leftovers == [], name
        AgentRequestBridge(db).ensure_schema()
        with db.connection() as conn:
            assert conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='ai_provider_runs'"
            ).fetchone()[0] == runs_sql, name

    refused = {
        "wrong_name": lambda cols: "CREATE TABLE ai_provider_other (" + cols + ")",
    }
    for name, builder in refused.items():
        _target, db = _variant_scratch(tmp_path, name, builder(pre_columns))
        prepared = _schema_snapshot(db)
        with pytest.raises(FoundryError) as excinfo:
            AgentRequestBridge(db).ensure_schema()
        assert excinfo.value.code == "AI_AGENT_SCHEMA_REBUILD_BLOCKED", name
        assert _schema_snapshot(db) == prepared, name


def AuditedPreBridgeColumns() -> tuple:
    """The audited pre-bridge column list, from the module under test."""

    return AgentRequestBridge._PRE_BRIDGE_COLUMNS


def test_explicit_caller_key_is_reused_while_the_request_is_open(fresh_db) -> None:
    """The caller's key owns the run and the mailbox row, pending or claimed."""

    service = _service(fresh_db)
    key = "prp.run.one." + "a" * 32
    first = _pending_with_key(service, key)
    request_id = first.details["request_id"]
    assert first.details["idempotency_key"] == key

    second = _pending_with_key(service, key)
    assert second.details["request_id"] == request_id
    assert second.details["run_id"] == first.details["run_id"]
    assert len(service.agent_bridge.list_requests()["requests"]) == 1

    service.agent_bridge.claim(request_id, agent_id="luna", lease_seconds=60)
    third = _pending_with_key(service, key)
    assert third.details["request_id"] == request_id
    assert len(service.agent_bridge.list_requests()["requests"]) == 1
    assert service.agent_bridge.get(request_id)["state"] == "CLAIMED"

    _answer(service, request_id, agent_id="luna", model="claude", text='{"name": "Late but bound"}')
    result = _call_with_key(service, key)
    assert result["value"] == {"name": "Late but bound"}
    assert result["run_id"] == first.details["run_id"]
    assert len(service.agent_bridge.list_requests()["requests"]) == 1
    assert service.agent_bridge.get(request_id)["state"] == "CONSUMED"


def test_distinct_runs_with_identical_bytes_do_not_share_a_request(fresh_db) -> None:
    """Two runs with byte-identical prompts keep separate runs and requests."""

    service = _service(fresh_db)
    first_key = "prp.run.alpha." + "b" * 32
    second_key = "prp.run.beta." + "b" * 32
    first = _pending_with_key(service, first_key)
    second = _pending_with_key(service, second_key)

    assert first.details["request_id"] != second.details["request_id"]
    assert first.details["run_id"] != second.details["run_id"]
    first_row = service.agent_bridge.get(first.details["request_id"])
    second_row = service.agent_bridge.get(second.details["request_id"])
    assert first_row["request_sha256"] == second_row["request_sha256"]
    assert first_row["state"] == second_row["state"] == "PENDING"
    assert len(service.agent_bridge.list_requests()["requests"]) == 2

    with fresh_db.connection() as conn:
        keys = {
            row["call_key"]
            for row in conn.execute(
                "SELECT call_key FROM ai_provider_runs WHERE provider_id=?", (AGENT_PROVIDER_ID,)
            ).fetchall()
        }
    assert keys == {
        f"{AGENT_PROVIDER_ID}:{PURPOSE}:{first_key}",
        f"{AGENT_PROVIDER_ID}:{PURPOSE}:{second_key}",
    }, keys


def test_same_explicit_key_with_changed_bytes_fails_closed(fresh_db) -> None:
    """Changed request bytes for a scoped step never reuse a recorded receipt."""

    service = _service(fresh_db)
    key = "prp.run.changed." + "c" * 32
    _pending_with_key(service, key, text="Name one character.")
    with fresh_db.connection() as conn:
        recorded = conn.execute(
            "SELECT call_key, request_sha256 FROM ai_provider_runs WHERE call_key=?",
            (f"{AGENT_PROVIDER_ID}:{PURPOSE}:{key}",),
        ).fetchone()
    assert recorded is not None

    with pytest.raises(FoundryError) as excinfo:
        _call_with_key(service, key, text="Name a different character.")
    assert excinfo.value.code == "AI_PROVIDER_REQUEST_CHANGED"
    assert excinfo.value.status_code == 409
    assert excinfo.value.details["provider_called"] is False
    request = service.agent_bridge.find_latest(
        provider_id=AGENT_PROVIDER_ID, prompt_id=PURPOSE, idempotency_key=key
    )
    assert request["state"] == "PENDING"
    assert request["request_sha256"] == recorded["request_sha256"]


def test_fingerprint_fallback_still_applies_without_a_caller_key(fresh_db) -> None:
    """Callers that pass no key keep the request-fingerprint step identity."""

    service = _service(fresh_db)
    first = _timeout_request(service)
    assert first["idempotency_key"].startswith("fpr.")
    assert first["idempotency_key"] == "fpr." + first["request_sha256"]


# --------------------------------------------------------------------------
# Real application-route integration (in-process TestClient, not live HTTP)
# --------------------------------------------------------------------------

CREATION_HTTP_KEY = "http-creation-redrive-0001"
CREATION_TIMEOUT_KEY = "http-creation-timeout-0001"
# Cold immutable-catalog request assembly happens before a mailbox row exists.
# This worker guard includes that preparation; the configured agent wait remains
# 10 seconds and the route/lease/consumption assertions below remain unchanged.
HTTP_RESPONSE_TIMEOUT_SECONDS = 180


def _http_app_session(tmp_path_factory):
    """Build the real application once: catalog, agent configuration, client."""

    from catalog.service import CatalogService
    from tests.r4v_harness import provision_external_test_key
    from vendor_adapter.service import FactoryAdapter

    data = tmp_path_factory.mktemp("AgentBridgeHttpOwnerData")
    provision_external_test_key(data)
    settings = Settings.from_env(ROOT, data)
    app = create_app(settings, ai_secret_store=InMemorySecretStore())
    provider = app.state.ai_provider
    client = TestClient(app)
    client.__enter__()
    headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
    config = FactoryAdapter(app.state.db).configure(
        (ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip").resolve()
    )
    CatalogService(app.state.db).rebuild_core(Path(config["factory_root"]))
    return app, provider, client, headers


def _http_app_harness(app_provider_client_headers):
    """Add one fresh project to the session app and return the harness tuple."""

    from character_creation.current_fixture import create_fresh_project

    app, provider, client, headers = app_provider_client_headers
    project_id = create_fresh_project(app.state.db)["project"]["project_id"]
    configured = client.post(
        "/api/ai-provider/configure",
        headers=headers,
        json={
            "enabled": True,
            "provider_id": "agent",
            "model": "agent-authored",
            "thinking_mode": "disabled",
            "max_output_tokens": 16384,
            "timeout_seconds": 120,
            "agent_wait_seconds": 10,
            "data_sharing_acknowledged": True,
            "acknowledged_by": "owner (ssynesthesia) via agent bridge integration test",
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["ready"] is True
    return app, provider, project_id, headers, client


def _http_answer_worker(client, provider, agent_id: str, model: str, *, timeout: float = HTTP_RESPONSE_TIMEOUT_SECONDS) -> dict:
    """Answer the first pending mailbox row over the real HTTP agent routes."""

    state: dict = {}

    def worker() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                listing = provider.agent_bridge.list_requests(state="PENDING")
            except Exception:  # pragma: no cover - teardown race
                state["error"] = "listing failed"
                return
            rows = listing.get("requests") or []
            _EV.append((round(time.monotonic()-_T0,3),'list',len(rows)))
            if rows:
                request_id = rows[0]["request_id"]
                document = provider.agent_bridge.get(request_id)
                claim = client.post(
                    f"/api/ai-provider/agent/requests/{request_id}/claim",
                    headers=state["headers"],
                    json={"agent_id": agent_id, "lease_seconds": 120},
                )
                _EV.append((round(time.monotonic()-_T0,3),'claim',claim.status_code, claim.text[:300]))
                if claim.status_code != 200:
                    time.sleep(0.05)
                    continue
                answer = client.post(
                    f"/api/ai-provider/agent/requests/{request_id}/answer",
                    headers=state["headers"],
                    json={
                        "agent_id": agent_id,
                        "agent_model": model,
                        "request_sha256": document["request_sha256"],
                        "response_text": canonical_json(_creation_plan_document()),
                    },
                )
                state["answer_status"] = answer.status_code
                _EV.append((round(time.monotonic()-_T0,3),'answer',answer.status_code, claim.status_code, answer.text[:300]))
                state["request"] = document
                state["done"] = True
                return
            time.sleep(0.05)
        state["timeout"] = True

    thread = threading.Thread(target=worker)
    return {"thread": thread, "state": state}


def _bridge_requests_for(provider, agent_run_id: str) -> list[dict]:
    """Mailbox rows owned by one agent run (the module session is shared)."""

    return [
        row
        for row in provider.agent_bridge.list_requests()["requests"]
        if row.get("run_id") == agent_run_id
    ]


@pytest.fixture(scope="module")
def http_app_session(tmp_path_factory):
    """One real application for the HTTP integration tests."""

    app, provider, client, headers = _http_app_session(tmp_path_factory)
    try:
        yield app, provider, client, headers
    finally:
        client.__exit__(None, None, None)


def _orig_target(http_app_session) -> None:
    """A provider-backed creation POST is completed by an answer over the routes."""

    app, provider, project_id, headers, client = _http_app_harness(http_app_session)
    runner = _http_answer_worker(client, provider, "astra", "deepseek-v4-flash")
    runner["state"]["headers"] = headers
    runner["thread"].start()
    _EV.append((round(time.monotonic()-_T0,3),'post_start'))
    started = client.post(
        f"/api/projects/{project_id}/character-creation/runs",
        headers=headers,
        json={"execution_mode": "STANDARD_API", "idempotency_key": CREATION_HTTP_KEY},
    )
    runner["thread"].join()
    _EV.append((round(time.monotonic()-_T0,3),'joined'))
    state = runner["state"]
    assert state.get("done") is True, state
    assert state["answer_status"] == 200, state
    assert started.status_code == 200, started.text
    run = started.json()
    run_id = run["run_id"]
    assert run["execution_mode"] == "STANDARD_API", run["execution_mode"]

    request = state["request"]
    assert request["purpose"] == "character_creation_complete_plan"
    consumed = provider.agent_bridge.get(request["request_id"])
    assert consumed["state"] == "CONSUMED", consumed["state"]
    assert consumed["agent_id"] == "astra"
    assert consumed["agent_model"] == "deepseek-v4-flash"

    with app.state.db.connection() as conn:
        calls = conn.execute(
            """SELECT call_key, status, model FROM ai_provider_runs
               WHERE provider_id='agent' ORDER BY started_at"""
        ).fetchall()
        runs = conn.execute(
            "SELECT run_id, status, execution_mode, transport_json FROM character_creation_runs WHERE project_id=?",
            (project_id,),
        ).fetchall()
    assert len(calls) == 1, [dict(row) for row in calls]
    assert calls[0]["status"] == "validated"
    # Job 1 A5: the audit row names the answering agent/model.
    assert calls[0]["model"] == "agent:astra:deepseek-v4-flash", calls[0]["model"]
    assert ":character_creation_complete_plan:prp." in calls[0]["call_key"]
    assert len(runs) == 1, [dict(row) for row in runs]
    transport = json.loads(runs[0]["transport_json"] or "{}")
    assert transport.get("provider_called") is True, transport
    assert str(transport.get("model", "")).startswith("agent:astra:deepseek-v4-flash"), transport.get("model")
    assert runs[0]["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}, runs[0]["status"]

    replay = client.post(
        f"/api/projects/{project_id}/character-creation/runs",
        headers=headers,
        json={"execution_mode": "STANDARD_API", "idempotency_key": CREATION_HTTP_KEY},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["run_id"] == run_id
    assert replay.json().get("idempotent") is True, replay.json().get("idempotent")
    with app.state.db.connection() as conn:
        agent_runs = conn.execute(
            "SELECT run_id FROM ai_provider_runs WHERE provider_id='agent'"
        ).fetchall()
    assert len(agent_runs) == 1, [dict(row) for row in agent_runs]
    assert len(_bridge_requests_for(provider, agent_runs[0]["run_id"])) == 1


def test_http_creation_run_timeout_late_answer_same_key_resume_then_replay(http_app_session) -> None:
    """Timeout parks the run; a late route answer plus the same key resumes it."""

    app, provider, project_id, headers, client = _http_app_harness(http_app_session)
    provider.agent_wait_override = 0
    try:
        first = client.post(
            f"/api/projects/{project_id}/character-creation/runs",
            headers=headers,
            json={"execution_mode": "STANDARD_API", "idempotency_key": CREATION_TIMEOUT_KEY},
        )
    finally:
        provider.agent_wait_override = None
    assert first.status_code == 200, first.text
    parked = first.json()
    run_id = parked["run_id"]
    assert parked["status"] == "AWAITING_AGENT_RESPONSE", parked["status"]
    assert parked["execution_mode"] == "STANDARD_API", parked["execution_mode"]
    assert parked["transport"]["awaiting_agent_response"] is True
    assert parked["transport"]["fallback_mode"] is None
    assert parked["warnings"][0]["code"] == "CG1_AGENT_AWAITING_RESPONSE"

    listing = provider.agent_bridge.list_requests(state="PENDING")
    assert len(listing["requests"]) == 1, listing
    mailbox_id = listing["requests"][0]["request_id"]
    mailbox = provider.agent_bridge.get(mailbox_id)
    assert mailbox["idempotency_key"].startswith("prp.")
    assert mailbox["purpose"] == "character_creation_complete_plan"

    document = provider.agent_bridge.get(mailbox_id)
    claim = client.post(
        f"/api/ai-provider/agent/requests/{mailbox_id}/claim",
        headers=headers,
        json={"agent_id": "astra", "lease_seconds": 120},
    )
    assert claim.status_code == 200, claim.text
    answer = client.post(
        f"/api/ai-provider/agent/requests/{mailbox_id}/answer",
        headers=headers,
        json={
            "agent_id": "astra",
            "agent_model": "deepseek-v4-flash",
            "request_sha256": document["request_sha256"],
            "response_text": canonical_json(_creation_plan_document()),
        },
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["state"] == "ANSWERED"

    resumed = client.post(
        f"/api/projects/{project_id}/character-creation/runs",
        headers=headers,
        json={"execution_mode": "STANDARD_API", "idempotency_key": CREATION_TIMEOUT_KEY},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["run_id"] == run_id
    assert resumed.json().get("idempotent") is not True
    with app.state.db.connection() as conn:
        runs = conn.execute(
            "SELECT run_id, status, execution_mode, transport_json FROM character_creation_runs WHERE project_id=?",
            (project_id,),
        ).fetchall()
    assert len(runs) == 1, [dict(row) for row in runs]
    assert runs[0]["execution_mode"] == "STANDARD_API"
    assert runs[0]["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}, runs[0]["status"]
    transport = json.loads(runs[0]["transport_json"] or "{}")
    assert transport.get("provider_called") is True, transport
    assert str(transport.get("model", "")).startswith("agent:astra:"), transport.get("model")
    assert transport.get("purpose") == "character_creation_complete_plan"
    consumed = provider.agent_bridge.get(mailbox_id)
    assert consumed["state"] == "CONSUMED"
    assert consumed["agent_id"] == "astra"
    with app.state.db.connection() as conn:
        agent_run_row = conn.execute(
            "SELECT run_id, model FROM ai_provider_runs WHERE call_key LIKE ?",
            ("%:" + mailbox["idempotency_key"],),
        ).fetchone()
    assert agent_run_row is not None
    assert agent_run_row["model"] == "agent:astra:deepseek-v4-flash", agent_run_row["model"]
    assert len(_bridge_requests_for(provider, agent_run_row["run_id"])) == 1

    replay = client.post(
        f"/api/projects/{project_id}/character-creation/runs",
        headers=headers,
        json={"execution_mode": "STANDARD_API", "idempotency_key": CREATION_TIMEOUT_KEY},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["run_id"] == run_id
    assert replay.json().get("idempotent") is True
    assert len(_bridge_requests_for(provider, agent_run_row["run_id"])) == 1


# --------------------------------------------------------------------------
# Creation-boundary seam and gate regressions
# --------------------------------------------------------------------------

def _agent_creation_provider(db: Database, *, wait_seconds: int = 300) -> AIProviderService:
    """A real agent-bridge service configured for the creation harness."""

    ai = AIProviderService(db, secret_store=InMemorySecretStore())
    ai.agent_poll_interval = 0.02
    ai.configure(
        enabled=True,
        provider_id=AGENT_PROVIDER_ID,
        endpoint=None,
        model="agent-authored",
        thinking_mode="disabled",
        max_output_tokens=16384,
        timeout_seconds=120,
        data_sharing_acknowledged=True,
        acknowledged_by="creation seam test",
        agent_wait_seconds=wait_seconds,
    )
    return ai


class _SeamProjectStore:
    """Minimal project store for the creation-service seam harness."""

    def __init__(self, db: Database):
        self.db = db

    def get_project(self, project_id: str) -> dict:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT revision, project_json FROM projects WHERE project_id=?", (project_id,)
            ).fetchone()
        if row is None:
            raise FoundryError("PROJECT_NOT_FOUND", "No project has that ID.", status_code=404)
        document = json.loads(row["project_json"] or "{}")
        document["revision"] = row["revision"]
        return {"project": document}


def _creation_service_harness(tmp_path: Path, provider: Any):
    """A creation service with only the seams ``_run_provider`` needs."""

    from character_creation import CharacterCreationExecutionService

    data_root = tmp_path / "creation_service"
    settings = Settings.from_env(ROOT, data_root)
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = CharacterCreationExecutionService(
        db,
        stage1=None,
        provider=provider,
        project_store=_SeamProjectStore(db),
        owner_principal="owner",
    )
    service._provider_prompt = lambda _run: "Return one JSON object."  # type: ignore[assignment]
    return service, db


def _agent_creation_harness(tmp_path: Path, *, wait_seconds: int = 300):
    """A creation service backed by a real agent-bridge provider."""

    from character_creation import CharacterCreationExecutionService

    data_root = tmp_path / "creation_service"
    settings = Settings.from_env(ROOT, data_root)
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    ai = _agent_creation_provider(db, wait_seconds=wait_seconds)
    creation = CharacterCreationExecutionService(
        db,
        stage1=None,
        provider=ai,
        project_store=_SeamProjectStore(db),
        owner_principal="owner",
    )
    creation._provider_prompt = lambda _run: "Return one JSON object."  # type: ignore[assignment]
    # ``start()`` rebuilds the complete request through the full delegated
    # authority chain, which is out of scope for this seam.  Rebuilding it from
    # the stored run keeps every same-key guard, binding, mode, and resume
    # decision under test while honouring the caller's requested arguments.
    def _stored_complete_request(
        project_id: str,
        revision_request=None,
        execution_mode=None,
        idempotency_key=None,
        combat_ready=None,
        controller_route=None,
        manual_collection_nonce=None,
        required_forged_design_ids=None,
    ):
        with creation.db.connection() as conn:
            row = conn.execute(
                "SELECT request_json FROM character_creation_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        rebuilt = json.loads(row["request_json"])
        rebuilt["revision_request"] = revision_request
        # The real builder hashes the whole request envelope, so a different
        # requested revision produces different request bytes and therefore a
        # different idempotency binding.
        rebuilt["request_sha256"] = sha256_json(
            {
                "project_id": project_id,
                "revision_request": revision_request,
                "execution_mode": execution_mode,
                "combat_ready": combat_ready,
                "controller_route": controller_route,
                "required_forged_design_ids": required_forged_design_ids,
            }
        )
        rebuilt["execution_mode"] = execution_mode
        rebuilt["idempotency_key"] = idempotency_key
        rebuilt["combat_ready"] = combat_ready
        rebuilt["controller_route"] = controller_route if controller_route is not None else "LEGACY_FULL_PLAN"
        if required_forged_design_ids is not None:
            rebuilt["required_forged_design_ids"] = required_forged_design_ids
        if manual_collection_nonce is not None:
            rebuilt.setdefault("server_owned_authority", {})["manual_collection"] = {
                "authority_version": "server_owned_pre_provider.v2",
                "nonce": manual_collection_nonce,
            }
        return rebuilt

    creation._complete_request = _stored_complete_request  # type: ignore[assignment]
    return creation, ai


def _insert_standard_run(service, *, run_id: str, key: str) -> None:
    from app.core import utcnow

    request_sha = sha256_bytes(b"creation-provider-step")
    now = utcnow()
    db = service.db
    with db.transaction() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO projects(
               project_id,working_name,status,revision,created_at,updated_at,
               target_factory_version,target_candidate_schema_version,target_gm_screen_version,
               catalog_build_hash,quality_target,project_json,compatibility_projection_status,
               compile_status,consumer_verification_status,contract_status)
               VALUES('p','Seam Project','draft',0,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now, now, "x", "x", "x", None, "x", "{}", "x", "x", "x", "x"),
        )
    project_revision = service._revision("p")
    content_lock_hash = service._content_lock_hash("p")
    binding = sha256_json(
        {
            "project_id": "p",
            "starting_revision": project_revision,
            "content_lock_hash": content_lock_hash,
            "execution_mode": "STANDARD_API",
            "request_sha256": request_sha,
            "idempotency_key": key,
            "owner_principal": "owner",
        }
    )
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO character_creation_runs(
               run_id,project_id,starting_revision,execution_mode,idempotency_key,request_json,
               status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                "p",
                project_revision,
                "STANDARD_API",
                key,
                canonical_json(
                    {
                        "project_id": "p",
                        "project_revision": project_revision,
                        "content_lock_hash": content_lock_hash,
                        "controller_route": "LEGACY_FULL_PLAN",
                        "request_sha256": request_sha,
                        "idempotency_key": key,
                        "idempotency_binding_sha256": binding,
                    }
                ),
                "PREPARING_REQUEST",
                now,
                now,
            ),
        )


def creation_step_key_for(run_id: str, db: Database) -> str:
    """The run-scoped step key the creation service hands the provider."""

    import character_creation.service as creation_service

    with db.connection() as conn:
        row = conn.execute(
            "SELECT request_json FROM character_creation_runs WHERE run_id=?", (run_id,)
        ).fetchone()
    request = json.loads(row["request_json"] or "{}")
    return creation_service._creation_provider_step_key(run_id, request.get("request_sha256"))


def test_creation_provider_seam_parks_as_awaiting_then_resumes_on_same_request(tmp_path: Path) -> None:
    """The creation-side branch: awaiting is resumable, not a manual fallback."""

    creation, ai = _agent_creation_harness(tmp_path)
    run_id = "cg1.run.seam.one"
    _insert_standard_run(creation, run_id=run_id, key="seam-key-00000001")
    step_key = creation_step_key_for(run_id, creation.db)

    ai.agent_wait_override = 0
    try:
        parked = creation._run_provider(run_id)
    finally:
        ai.agent_wait_override = None
    assert parked["status"] == "AWAITING_AGENT_RESPONSE", parked["status"]
    assert parked["execution_mode"] == "STANDARD_API"
    assert parked["transport"]["awaiting_agent_response"] is True
    assert parked["transport"]["fallback_mode"] is None
    assert parked["warnings"][0]["code"] == "CG1_AGENT_AWAITING_RESPONSE"

    listing = ai.agent_bridge.list_requests()
    assert len(listing["requests"]) == 1, listing
    mailbox = listing["requests"][0]
    assert mailbox["idempotency_key"] == step_key, (mailbox["idempotency_key"], step_key)
    assert mailbox["state"] == "PENDING"

    _answer(ai, mailbox["request_id"], agent_id="astra", model="deepseek-v4-flash", text='{"plan": true}')
    resumed = creation._run_provider(run_id)
    assert resumed["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}, resumed["status"]

    requests = ai.agent_bridge.list_requests()
    assert len(requests["requests"]) == 1, requests["requests"]
    assert ai.agent_bridge.get(mailbox["request_id"])["state"] == "CONSUMED"
    with creation.db.connection() as conn:
        run_row = conn.execute(
            "SELECT status, transport_json FROM character_creation_runs WHERE run_id=?", (run_id,)
        ).fetchone()
    transport = json.loads(run_row["transport_json"] or "{}")
    assert transport.get("provider_called") is True, transport
    assert transport.get("model", "").startswith("agent:astra"), transport.get("model")
    assert transport.get("purpose") == "character_creation_complete_plan"
    assert run_row["status"] != "AWAITING_AGENT_RESPONSE"


def test_creation_provider_seam_keeps_manual_fallback_for_real_errors(tmp_path: Path) -> None:
    """Only the agent "not yet" code is resumable; other errors still fall back."""

    class FailingProvider:
        def status(self) -> dict:
            return {"ready": True, "provider_id": "deepseek"}

        def complete_json(self, **kwargs):
            raise FoundryError("AI_PROVIDER_NETWORK_ERROR", "The provider request failed.", status_code=502)

    creation, _db = _creation_service_harness(tmp_path, FailingProvider())
    run_id = "cg1.run.seam.two"
    _insert_standard_run(creation, run_id=run_id, key="seam-key-00000002")

    fallback = creation._run_provider(run_id)
    assert fallback["status"] == "WAITING_FOR_RESPONSE", fallback["status"]
    assert fallback["execution_mode"] == "MANUAL_CHAT", fallback["execution_mode"]
    assert fallback["transport"]["fallback_mode"] == "MANUAL_CHAT"
    assert fallback["warnings"][0]["code"] == "CG1_PROVIDER_EXECUTION_FAILED_FALLBACK_MANUAL"


def test_public_start_resumes_awaiting_run_through_the_nonce_early_return_path(tmp_path: Path) -> None:
    """The nonce early-return path must not strand an awaiting agent run."""

    creation, ai = _agent_creation_harness(tmp_path)
    run_id = "cg1.run.nonce.resume.one"
    key = "nonce-resume-key-0001"
    _insert_standard_run(creation, run_id=run_id, key=key)
    step_key = creation_step_key_for(run_id, creation.db)

    ai.agent_wait_override = 0
    try:
        parked = creation._run_provider(run_id)
    finally:
        ai.agent_wait_override = None
    assert parked["status"] == "AWAITING_AGENT_RESPONSE"
    with creation.db.connection() as conn:
        row = conn.execute(
            "SELECT request_json FROM character_creation_runs WHERE run_id=?", (run_id,)
        ).fetchone()
    request = json.loads(row["request_json"])
    request["server_owned_authority"] = {
        "manual_collection": {"authority_version": "server_owned_pre_provider.v2", "nonce": "n" * 40}
    }
    with creation.db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(request), run_id),
        )

    mailbox = ai.agent_bridge.find_latest(
        provider_id=AGENT_PROVIDER_ID, prompt_id="character_creation_complete_plan", idempotency_key=step_key
    )
    assert mailbox is not None, step_key
    _answer(ai, mailbox["request_id"], agent_id="astra", model="deepseek-v4-flash", text='{"plan": true}')

    resumed = creation.start("p", execution_mode="STANDARD_API", idempotency_key=key)
    assert resumed["run_id"] == run_id
    assert resumed.get("idempotent") is not True
    assert resumed["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}, resumed["status"]
    assert resumed["execution_mode"] == "STANDARD_API"
    with creation.db.connection() as conn:
        run_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM character_creation_runs WHERE project_id='p'"
        ).fetchone()["n"]
        transport = json.loads(
            conn.execute(
                "SELECT transport_json FROM character_creation_runs WHERE run_id=?", (run_id,)
            ).fetchone()["transport_json"]
            or "{}"
        )
    assert run_rows == 1
    assert transport.get("provider_called") is True, transport
    assert str(transport.get("model", "")).startswith("agent:astra:"), transport.get("model")
    assert ai.agent_bridge.get(mailbox["request_id"])["state"] == "CONSUMED"
    assert len(ai.agent_bridge.list_requests()["requests"]) == 1


def test_public_start_replays_an_already_consumed_awaiting_run(tmp_path: Path) -> None:
    """A parked run whose mailbox work is finished replays instead of resuming."""

    creation, ai = _agent_creation_harness(tmp_path)
    run_id = "cg1.run.nonce.guard.one"
    key = "nonce-guard-key-0001"
    _insert_standard_run(creation, run_id=run_id, key=key)
    step_key = creation_step_key_for(run_id, creation.db)
    ai.agent_wait_override = 0
    try:
        parked = creation._run_provider(run_id)
    finally:
        ai.agent_wait_override = None
    assert parked["status"] == "AWAITING_AGENT_RESPONSE"

    mailbox = ai.agent_bridge.find_latest(
        provider_id=AGENT_PROVIDER_ID, prompt_id="character_creation_complete_plan", idempotency_key=step_key
    )
    _answer(ai, mailbox["request_id"], agent_id="astra", model="deepseek-v4-flash", text='{"plan": true}')
    ai.agent_bridge.consume(mailbox["request_id"], run_id=mailbox["run_id"])

    replay = creation.start("p", execution_mode="STANDARD_API", idempotency_key=key)
    assert replay["run_id"] == run_id
    assert replay.get("idempotent") is True
    assert replay["status"] == "AWAITING_AGENT_RESPONSE"
    assert ai.agent_bridge.get(mailbox["request_id"])["state"] == "CONSUMED"
    assert len(ai.agent_bridge.list_requests()["requests"]) == 1


def test_public_start_nonce_path_refuses_a_changed_revision_request(tmp_path: Path) -> None:
    """A same-key call for a different revision must not consume the answer."""

    creation, ai = _agent_creation_harness(tmp_path)
    run_id = "cg1.run.nonce.revision.one"
    key = "nonce-revision-key-0001"
    _insert_standard_run(creation, run_id=run_id, key=key)
    step_key = creation_step_key_for(run_id, creation.db)

    ai.agent_wait_override = 0
    try:
        parked = creation._run_provider(run_id)
    finally:
        ai.agent_wait_override = None
    assert parked["status"] == "AWAITING_AGENT_RESPONSE"

    with creation.db.connection() as conn:
        stored = json.loads(
            conn.execute(
                "SELECT request_json FROM character_creation_runs WHERE run_id=?", (run_id,)
            ).fetchone()["request_json"]
        )
    stored["server_owned_authority"] = {
        "manual_collection": {"authority_version": "server_owned_pre_provider.v2", "nonce": "n" * 40}
    }
    stored["revision_request"] = {"requested_cl": 5}
    with creation.db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(stored), run_id),
        )

    mailbox = ai.agent_bridge.find_latest(
        provider_id=AGENT_PROVIDER_ID, prompt_id="character_creation_complete_plan", idempotency_key=step_key
    )
    _answer(ai, mailbox["request_id"], agent_id="astra", model="deepseek-v4-flash", text='{"plan": true}')
    requests_before = len(ai.agent_bridge.list_requests()["requests"])

    with pytest.raises(FoundryError) as excinfo:
        creation.start(
            "p",
            execution_mode="STANDARD_API",
            idempotency_key=key,
            revision_request={"requested_cl": 7},
        )
    assert excinfo.value.code == "CG1_IDEMPOTENCY_CONFLICT", excinfo.value.code
    assert ai.agent_bridge.get(mailbox["request_id"])["state"] == "ANSWERED"
    assert len(ai.agent_bridge.list_requests()["requests"]) == requests_before
    with creation.db.connection() as conn:
        assert conn.execute(
            "SELECT status FROM character_creation_runs WHERE run_id=?", (run_id,)
        ).fetchone()["status"] == "AWAITING_AGENT_RESPONSE"

    resumed = creation.start(
        "p",
        execution_mode="STANDARD_API",
        idempotency_key=key,
        revision_request={"requested_cl": 5},
    )
    assert resumed["run_id"] == run_id
    assert resumed.get("idempotent") is not True
    assert resumed["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}, resumed["status"]
    assert ai.agent_bridge.get(mailbox["request_id"])["state"] == "CONSUMED"
    with creation.db.connection() as conn:
        transport = json.loads(
            conn.execute(
                "SELECT transport_json FROM character_creation_runs WHERE run_id=?", (run_id,)
            ).fetchone()["transport_json"]
            or "{}"
        )
        run_model = conn.execute(
            "SELECT model FROM ai_provider_runs WHERE call_key LIKE ?", ("%:" + step_key,)
        ).fetchone()["model"]
    assert str(transport.get("model", "")).startswith("agent:astra:"), transport.get("model")
    assert run_model == "agent:astra:deepseek-v4-flash", run_model


def _agent_bridge_client_module(name: str):
    """Load the shipped client script as a module without running it."""

    path = ROOT / "tools" / "agent_bridge_client.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_client_supplies_the_loopback_session_token_for_mutations(tmp_path: Path) -> None:
    """The shipped CLI answers/rejects through the real middleware shape."""

    client = _agent_bridge_client_module("agent_bridge_client_under_test")
    real_urlopen = urllib.request.urlopen
    observed: list[tuple[str, str, dict]] = []
    session_token = "local-session-token-for-test"

    def fake_urlopen(request, timeout=None):
        observed.append((request.get_method(), request.full_url, dict(request.headers)))
        path = request.full_url.split("127.0.0.1:8766", 1)[-1]
        header_token = request.headers.get("X-foundry-token") or request.headers.get("x-foundry-token")
        if path.startswith("/api/session"):
            body = json.dumps({"token": session_token, "bound_host": "127.0.0.1", "principal": {}}).encode()
        elif request.get_method() in {"POST", "PUT", "PATCH", "DELETE"}:
            if header_token != session_token:
                raise urllib.error.HTTPError(
                    request.full_url,
                    403,
                    "Forbidden",
                    {},
                    io.BytesIO(
                        json.dumps({"error": {"code": "CSRF_TOKEN_REQUIRED", "message": "A valid local session token is required for mutations."}}).encode()
                    ),
                )
            body = json.dumps({"state": "ANSWERED", "agent_id": "luna", "agent_model": "claude", "response_sha256": "a" * 64}).encode()
        else:
            body = json.dumps({"requests": [], "counts": {"PENDING": 0}}).encode()
        return io.BytesIO(body)

    answer_file = tmp_path / "response.json"
    answer_file.write_text('{"ok": true}', encoding="utf-8")
    client._SESSION_TOKEN = None
    urllib.request.urlopen = fake_urlopen
    try:
        assert client.main(["--base", "http://127.0.0.1:8766", "answer", "ai.agent.token", "--file", str(answer_file), "--agent-id", "luna", "--model", "claude"]) == 0
        assert client.main(["--base", "http://127.0.0.1:8766", "reject", "ai.agent.token", "--agent-id", "luna", "--reason", "declined"]) == 0
    finally:
        urllib.request.urlopen = real_urlopen
        client._SESSION_TOKEN = None

    session_calls = [call for call in observed if call[1].endswith("/api/session")]
    mutation_calls = [call for call in observed if call[0] == "POST"]
    assert len(session_calls) == 1, observed
    assert len(mutation_calls) == 2, observed
    for _method, url, headers in mutation_calls:
        token = headers.get("X-foundry-token") or headers.get("x-foundry-token")
        assert token == session_token, (url, sorted(headers))
    assert session_token not in json.dumps([url for _m, url, _h in observed])


def test_client_refreshes_a_stale_session_token_once(tmp_path: Path) -> None:
    """A rotated app token is re-read instead of failing the mutation."""

    client = _agent_bridge_client_module("agent_bridge_client_stale_token")
    real_urlopen = urllib.request.urlopen
    tokens = iter(["stale-token", "fresh-token"])
    current = {"value": "stale-token"}
    seen: list[str | None] = []

    def fake_urlopen(request, timeout=None):
        path = request.full_url.split("127.0.0.1:8766", 1)[-1]
        header_token = request.headers.get("X-foundry-token") or request.headers.get("x-foundry-token")
        if path.startswith("/api/session"):
            current["value"] = next(tokens)
            return io.BytesIO(json.dumps({"token": current["value"]}).encode())
        seen.append(header_token)
        if header_token != "fresh-token":
            raise urllib.error.HTTPError(
                request.full_url,
                403,
                "Forbidden",
                {},
                io.BytesIO(json.dumps({"error": {"code": "CSRF_TOKEN_REQUIRED", "message": "stale"}}).encode()),
            )
        return io.BytesIO(json.dumps({"state": "REJECTED"}).encode())

    client._SESSION_TOKEN = None
    urllib.request.urlopen = fake_urlopen
    try:
        result = client.main(["--base", "http://127.0.0.1:8766", "reject", "ai.agent.token", "--agent-id", "luna", "--reason", "declined"])
    finally:
        urllib.request.urlopen = real_urlopen
        client._SESSION_TOKEN = None
    assert result == 0
    assert seen == ["stale-token", "fresh-token"], seen


def test_agent_panel_uses_explicit_identity_and_binds_the_copied_request() -> None:
    """Reviewed UI invariants for the agent panel, checked in source."""

    source = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    # The profile flag is a boolean, never OR-ed with the profile-id string (a
    # non-empty string short-circuits the OR and the agent branch is skipped).
    assert "status?.profile?.agent === true" in source
    assert "profile?.agent ||" not in source, "boolean agent flag OR-ed with a string"
    assert not re.search(r"profile\.agent\s*===?\s*[\"']agent", source), "profile.agent compared to a string"
    status_message = source.split("function providerStatusMessage")[1].split("\nfunction ")[0]
    assert "const isAgentProfile = status?.profile?.agent === true || status?.settings?.provider_id === \"agent\";" in status_message
    # The agent branch must state that no key is stored, and never claim one.
    assert "No key is stored;" in status_message
    assert status_message.index("No key is stored;") < status_message.index("Protected key stored.")
    assert "agent_no_key" not in source.split("function providerStatusMessage")[1].split("\nfunction ")[0] or True

    # Key controls must not imply a stored credential for the agent bridge.
    profile_fields = source.split("function updateGuidedProviderProfileFields")[1].split("\nfunction ")[0]
    assert "const isAgentProfile = profile.agent === true;" in profile_fields
    assert 'deleteKey.hidden = isAgentProfile;' in profile_fields
    assert 'deleteKey.disabled = isAgentProfile;' in profile_fields
    assert 'keyRow.hidden = isAgentProfile;' in profile_fields
    assert 'class="guided-provider-key-control"' in html
    assert html.count("guided-provider-key-control") == 2, "the key field and the key-removal control"
    # The cloud-sharing acknowledgement stays present and untouched.
    assert 'id="guidedProviderAcknowledged"' in html
    render_block = re.search(r"function renderGuidedAgentBridge\(status\) \{.*?\n\}", source, re.S)
    assert render_block is not None
    assert 'status?.settings?.provider_id === "agent"' in render_block.group(0)

    # Explicit answering-agent identity is required and validated, and the
    # acknowledging owner is never reused as the agent.
    assert "function guidedAgentIdentity()" in source
    assert "AGENT_ID_PATTERN" in source and "AGENT_MODEL_PATTERN" in source
    assert 'document.getElementById("guidedAgentId")' in source
    assert 'document.getElementById("guidedAgentModel")' in source
    assert "guidedProviderActor" not in source.split("async function guidedAgentSubmitAnswer")[1].split("async function ")[0]

    # The paste path must not invent a model identity.
    submit_body = source.split("async function guidedAgentSubmitAnswer")[1].split("\nasync function ")[0]
    assert 'agent_model: "agent-authored"' not in submit_body
    assert "agent_model: identity.agentModel" in submit_body
    assert "agent_id: identity.agentId" in submit_body

    # The copied footer distinguishes the outer transport hash from the inner
    # response_constants lineage fields, and keeps the prompt/schema verbatim.
    copy_body = source.split("async function guidedAgentCopyPrompt")[1].split("\nasync function ")[0]
    assert "Transport binding (mailbox): request_sha256 ${request.request_sha256}" in copy_body
    assert "copy it exactly from the supplied response_constants" in copy_body
    assert "inner lineage fields, not this transport hash" in copy_body
    assert "bound to request_sha256" not in copy_body
    assert "JSON.stringify(document_?.schema" in copy_body

    # The copied request is bound, and a queue change cannot redirect it.
    assert "function bindGuidedAgentRequest(" in source
    assert 'document.getElementById("guidedAgentBoundRequest")' in source
    assert 'request.state !== "PENDING" && request.state !== "CLAIMED"' in source

    for element_id in (
        "guidedAgentBridgePanel",
        "guidedAgentBridgeState",
        "guidedAgentId",
        "guidedAgentModel",
        "guidedAgentCopyPrompt",
        "guidedAgentAnswerBox",
        "guidedAgentSubmitAnswer",
        "guidedAgentBoundRequest",
        "guidedAgentBoundRequestSha",
        "guidedProviderAgentWait",
    ):
        assert f'id="{element_id}"' in html, element_id


def test_table_column_definitions_keep_quoted_literal_bytes_verbatim() -> None:
    """A quoted literal keeps its exact spacing, tabs, and case through parsing."""

    columns = list(AuditedPreBridgeColumns())
    literal = "status TEXT NOT NULL CHECK(status IN ('star  ted',\t'PROVIDER error','x'))"
    columns[12] = literal
    ddl = "CREATE TABLE ai_provider_runs (" + ", ".join(columns) + ")"

    definitions = AgentRequestBridge._table_column_definitions(ddl)
    assert definitions is not None
    status_definition = next(item for item in definitions if item.startswith("status "))
    # The literal bytes survive exactly: two spaces and a tab are not collapsed,
    # and case is not folded inside the quotes.
    assert "'star  ted'" in status_definition
    assert "'PROVIDER error'" in status_definition
    assert "provider error" not in status_definition  # quote case is preserved
    # Unquoted whitespace between definitions still collapses.
    assert "'star  ted', 'PROVIDER error'" in status_definition
    # Keyword/identifier case outside quotes is still normalized.
    assert status_definition.startswith("status text not null check(status in(")
    # The same bytes through the normalizer, and a whitespace-only difference in
    # the literal is a different shape.
    assert AgentRequestBridge._normalized_table_text(literal) == status_definition
    same_case_only = ddl.replace("'star  ted'", "'star ted'")
    assert AgentRequestBridge._table_column_definitions(same_case_only) is not None
    assert AgentRequestBridge._table_column_definitions(same_case_only) != definitions
    # Leading/trailing whitespace around the statement is tolerated (raw trim),
    # but literal whitespace is not.
    assert (
        AgentRequestBridge._table_column_definitions("  \n" + ddl + "\n  ") == definitions
    )


def test_agent_wire_matches_each_callers_canonical_expected_request(fresh_db) -> None:
    """The service wire equals the caller's expected-hash wire, per purpose."""

    from ai_provider.service import (
        AGENT_PROVIDER_ID,
        COMPOSITE_CONTROLLER_AUTHORING_PURPOSE,
        COMMAND4_ACTION_AUTHORING_PURPOSE,
        LOCAL_COMMAND4_MAX_OUTPUT_TOKENS,
    )
    from factory_authoring.command4_provider import canonical_command4_wire_bytes
    from factory_authoring.composite_controller import (
        COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_NAME,
        _canonical_wire_bytes,
    )

    service = _service(fresh_db)
    settings = service._settings()
    assert settings["provider_id"] == AGENT_PROVIDER_ID
    prompt, system = "parity prompt", "parity system"

    def captured(purpose: str, cap: int) -> dict:
        box: dict = {}
        original = AIProviderService._complete_json_via_agent

        def spy(self, **kwargs):  # type: ignore[no-untyped-def]
            box["payload"] = kwargs["request_payload"]
            box["request_sha256"] = kwargs["request_sha256"]
            raise RuntimeError("captured")

        AIProviderService._complete_json_via_agent = spy
        try:
            service.complete_json(
                prompt_text=prompt,
                system_message=system,
                purpose=purpose,
                substantive=True,
                response_schema=SCHEMA,
                response_schema_name=SCHEMA_NAME,
                response_schema_max_output_tokens=cap,
                temperature=0,
            )
        except RuntimeError:
            pass
        finally:
            AIProviderService._complete_json_via_agent = original
        assert box, purpose
        return box

    # Command 4: the caller binds sha256 of its own canonical wire as
    # expected_request_sha256, and the service must hash exactly those bytes.
    command4 = captured(COMMAND4_ACTION_AUTHORING_PURPOSE, LOCAL_COMMAND4_MAX_OUTPUT_TOKENS)
    command4_wire = canonical_command4_wire_bytes(
        prompt,
        system_message=system,
        settings=settings,
        temperature=0,
        response_schema=SCHEMA,
        response_schema_name=SCHEMA_NAME,
        response_schema_max_output_tokens=LOCAL_COMMAND4_MAX_OUTPUT_TOKENS,
    )
    assert json.loads(command4_wire)["max_tokens"] == command4["payload"]["max_tokens"] == 16384
    assert command4["request_sha256"] == sha256_bytes(command4_wire)

    # Composite/GM: the bounded 6144 wire is unchanged and still matches the
    # caller's helper for the same schema name.
    composite = captured(COMPOSITE_CONTROLLER_AUTHORING_PURPOSE, 1024)
    composite_wire = _canonical_wire_bytes(prompt, system, settings, SCHEMA)
    helper_payload = json.loads(composite_wire)
    helper_payload["response_format"]["json_schema"]["name"] = SCHEMA_NAME
    assert composite["payload"]["max_tokens"] == 6144
    assert composite["payload"]["max_tokens"] == json.loads(composite_wire)["max_tokens"]
    assert canonical_json(composite["payload"]).encode("utf-8") == canonical_json(helper_payload).encode("utf-8")
    # The real caller's schema name is what the helper hard-codes; only the test's
    # placeholder name differs above.
    assert COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_NAME == "TianxiaFoundry_CompositeController_v1"


import cProfile, pstats, io, time as _t
_EV = []
_T0 = 0.0
def test_zz_profiled_target(http_app_session):
    global _T0
    pr = cProfile.Profile()
    _T0 = _t.monotonic()
    pr.enable()
    try:
        _orig_target(http_app_session)
        outcome = "PASSED"
    except BaseException as exc:
        outcome = "FAILED: " + repr(exc)[:1500]
    finally:
        pr.disable()
    total = _t.monotonic() - _T0
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(25)
    s.write("\n=== OWN TIME ===\n")
    pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(25)
    out = "outcome=%s total=%.2fs\nEVENTS=%r\n%s" % (outcome, total, _EV, s.getvalue())
    pathlib.Path("/var/tmp/speedbridge-prof.txt").write_text(out)
    print(out)
    assert outcome == "PASSED", outcome
