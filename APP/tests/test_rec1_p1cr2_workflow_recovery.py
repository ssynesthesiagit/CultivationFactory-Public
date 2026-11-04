from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ai_provider.secrets import APIProviderSecretStore, InMemorySecretStore
from ai_provider.service import AIProviderService
from app.core import FoundryError
from character_creation.delegated_choice_authority import validate_delegated_target_cl
from character_creation.service import CharacterCreationExecutionService
from tests.test_cg1_character_creation_modes import bound_plan, make
import tests.test_cg1_character_creation_modes as _cg1_modes
from tests.test_rec1_p1ar2_target_cl_authority import _authority, _plan_for_target


@pytest.fixture(autouse=True)
def _pinned_cg1_vendor(factory_environment, monkeypatch):
    # make() builds its settings from the cg1 modes module's pinned vendor
    # directory, which that module's own autouse fixture sets only for its
    # own tests; without it start() cannot find the pinned compiler authority.
    monkeypatch.setattr(_cg1_modes, "_PINNED_VENDOR_DIR", Path(factory_environment["settings"].vendor_dir))


def test_waiting_and_blocked_runs_keep_owner_recovery_and_evidence(tmp_path) -> None:
    service, _provider, _db = make(tmp_path / "recovery")
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="recovery-run-1")
    recovery = service.recovery("p")
    assert recovery["active"] is True
    assert recovery["active_run"]["run_id"] == run["run_id"]
    assert recovery["active_run"]["status"] == "WAITING_FOR_RESPONSE"
    assert recovery["next_legal_action"] == "Load one response file or paste the complete response."

    proposed = bound_plan(run)
    with pytest.raises(FoundryError) as exc:
        service.submit_manual(
            run["run_id"],
            response_text=json.dumps(proposed, separators=(",", ":")),
            request_sha256="0" * 64,
        )
    assert exc.value.code == "CG1_COMPLETE_RESPONSE_REQUEST_HASH_MISMATCH"
    failed = service.recovery("p")
    assert failed["active_run"]["status"] == "WAITING_FOR_RESPONSE"
    assert failed["active_run"]["submission_error"]["code"] == "CG1_COMPLETE_RESPONSE_REQUEST_HASH_MISMATCH"
    assert failed["active_run"]["owner_descriptive_fields"]["proposed"]["identity"]["name"] == "Test"

    evidence = service.evidence(run["run_id"])
    assert evidence["status"] == "WAITING_FOR_RESPONSE"
    assert evidence["response_binding"]["submitted_request_sha256"] == "0" * 64
    assert evidence["last_submission_error"]["code"] == "CG1_COMPLETE_RESPONSE_REQUEST_HASH_MISMATCH"
    assert evidence["response_view"]["exact_response_present"] is True


def test_global_recoverable_uses_compact_chooser_rows(tmp_path, monkeypatch) -> None:
    service, _provider, db = make(tmp_path / "compact-global-recovery")
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="compact-global-1")
    service.projects.list_projects = lambda: [{"project_id": "p"}]

    with db.connection() as conn:
        plan = conn.execute(
            """EXPLAIN QUERY PLAN
               SELECT run_id, project_id, starting_revision, execution_mode,
                      status, updated_at, created_at
               FROM character_creation_runs
               ORDER BY project_id, created_at DESC"""
        ).fetchall()
    details = " ".join(str(row[3]) for row in plan)
    assert "USING COVERING INDEX idx_cg1_recovery_chooser" in details
    assert not any(str(row[3]).strip() == "SCAN character_creation_runs" for row in plan)

    def unexpected_full_run_load(_run_id: str):
        raise AssertionError("global recovery must not load the full run for every project")

    monkeypatch.setattr(service, "get", unexpected_full_run_load)
    recoveries = service.recoverable()

    assert len(recoveries) == 1
    recovery = recoveries[0]
    assert recovery["active"] is True
    assert recovery["active_run"]["run_id"] == run["run_id"]
    assert recovery["active_run"]["status"] == "WAITING_FOR_RESPONSE"
    assert recovery["next_legal_action"] == "Load one response file or paste the complete response."
    assert recovery["active_run"]["owner_descriptive_fields"] == {}


def test_stale_revision_run_is_not_active_and_latest_finalized_run_surfaces(tmp_path) -> None:
    service, _provider, db = make(tmp_path / "stale-revision-recovery")
    stale = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="stale-revision-1")
    with db.transaction() as conn:
        conn.execute("UPDATE projects SET revision=1 WHERE project_id=?", ("p",))
    latest = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="current-revision-1")
    with db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET status='CLEAN_AND_FINALIZED', created_at='a', updated_at='a' WHERE run_id=?",
            (latest["run_id"],),
        )
        conn.execute(
            "UPDATE character_creation_runs SET created_at='z', updated_at='z' WHERE run_id=?",
            (stale["run_id"],),
        )

    recovery = service.recovery("p", audit_provider=False)
    assert recovery["active"] is False
    assert recovery["active_run"] is None
    assert recovery["latest_run"]["run_id"] == latest["run_id"]
    assert recovery["latest_run"]["status"] == "CLEAN_AND_FINALIZED"

    chooser = service.recoverable()[0]
    assert chooser["active"] is False
    assert chooser["active_run"] is None
    assert chooser["latest_run"]["run_id"] == latest["run_id"]
    assert chooser["latest_run"]["status"] == "CLEAN_AND_FINALIZED"
    assert stale["run_id"] != latest["run_id"]


def test_global_recoverable_omits_project_with_only_stale_active_run(tmp_path) -> None:
    service, _provider, db = make(tmp_path / "stale-only-recovery")
    stale = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="stale-only-1")
    with db.transaction() as conn:
        conn.execute("UPDATE projects SET revision=1 WHERE project_id=?", ("p",))

    recovery = service.recovery("p", audit_provider=False)
    assert recovery["active"] is False
    assert recovery["active_run"] is None
    assert recovery["latest_run"] is None
    assert service.recoverable() == []
    assert stale["starting_revision"] == 0
    assert any(row["run_id"] == stale["run_id"] for row in service.list("p"))


def test_global_recoverable_skips_large_payload_and_full_project_json(tmp_path, monkeypatch) -> None:
    service, _provider, db = make(tmp_path / "large-global-recovery")
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="large-global-1")
    sentinel = json.dumps({"retained_request_sentinel": "x" * 2_000_000})
    with db.transaction() as conn:
        conn.execute(
            """UPDATE character_creation_runs
               SET request_json=?, response_json=?, validation_json=?, final_plan_json=?,
                   owner_descriptive_fields_json=?, accepted_descriptive_fields_json=?
               WHERE run_id=?""",
            (sentinel, sentinel, sentinel, sentinel, sentinel, sentinel, run["run_id"]),
        )

    def unexpected_full_load(_run_id: str):
        raise AssertionError("global recovery must not load the full run")

    def unexpected_project_load(_project_id: str):
        raise AssertionError("global recovery must not load full project JSON")

    monkeypatch.setattr(service, "get", unexpected_full_load)
    monkeypatch.setattr(service.projects, "get_project", unexpected_project_load)
    original_loads = service._loads

    def unexpected_descriptive_parse(row, key, default):
        if key in {"owner_descriptive_fields_json", "accepted_descriptive_fields_json"}:
            raise AssertionError("global recovery must not parse descriptive JSON")
        return original_loads(row, key, default)

    monkeypatch.setattr(service, "_loads", unexpected_descriptive_parse)
    service.projects.list_projects = lambda: [{"project_id": "p"}]
    recoveries = service.recoverable()

    assert recoveries[0]["project_id"] == "p"
    assert recoveries[0]["project_name"] == "P"
    assert recoveries[0]["active_run"]["run_id"] == run["run_id"]
    assert recoveries[0]["active_run"]["status"] == "WAITING_FOR_RESPONSE"
    source = Path(__file__).resolve().parents[1].joinpath("character_creation", "service.py").read_text(encoding="utf-8")
    chooser_source = source.split("def _chooser_recoverable", 1)[1].split("def recoverable", 1)[0]
    assert "owner_descriptive_fields_json" not in chooser_source
    assert "accepted_descriptive_fields_json" not in chooser_source


def test_recovery_actions_preserve_attempt_history_for_replace_and_retry(tmp_path) -> None:
    service, _provider, _db = make(tmp_path / "recovery-actions")
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="recovery-actions-1")
    assert run["action_availability"]["replace_response"]["available"] is True
    assert run["action_availability"]["retry_local_build"]["available"] is False
    assert run["action_availability"]["edit_brief_create_new_request"]["available"] is True
    assert run["action_availability"]["cancel_build"]["available"] is True

    incomplete = {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "request_sha256": run["request"]["request_sha256"],
    }
    blocked = service.submit_manual(
        run["run_id"],
        response_text=json.dumps(incomplete, separators=(",", ":")),
        request_sha256=run["request"]["request_sha256"],
    )
    assert blocked["status"] == "NEEDS_REVIEW"
    assert blocked["action_availability"]["retry_local_build"]["available"] is True
    assert blocked["attempt_history"]

    retried = service.retry_local_build(run["run_id"])
    assert retried["status"] == "NEEDS_REVIEW"
    assert retried["attempt_history"][-1]["action_type"] == "RETRY_LOCAL_BUILD"

    replaced = service.replace_response_file(
        run["run_id"],
        filename="corrected-response.json",
        payload=json.dumps(incomplete, separators=(",", ":")).encode("utf-8"),
    )
    assert replaced["status"] == "NEEDS_REVIEW"
    assert replaced["attempt_history"][-1]["action_type"] == "REPLACE_RESPONSE"
    assert len(replaced["attempt_history"]) == len(retried["attempt_history"]) + 1


def test_unresolved_owner_projection_does_not_erase_response_descriptive_fields() -> None:
    plan = {"owner_descriptive_fields": {"identity": {"name": "AI Name"}, "concept": "AI concept"}}
    run = {"owner_descriptive_fields": {"resolved": {"identity": {"name": None}, "concept": None}}}
    assert CharacterCreationExecutionService._execution_descriptive_fields(run, plan) == plan


def test_owner_descriptive_fields_persist_and_are_separate_from_mechanics(tmp_path) -> None:
    service, _provider, db = make(tmp_path / "descriptive")
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="descriptive-run-1")
    response = service.submit_manual(
        run["run_id"],
        response_text=json.dumps(bound_plan(run), separators=(",", ":")),
        request_sha256=run["request"]["request_sha256"],
    )
    assert response["status"] == "READY_FOR_REVIEW"
    assert response["owner_descriptive_fields"]["state"] == "AI_PROPOSED"
    assert response["owner_descriptive_fields"]["resolved"]["identity"]["name"] == "Test"
    saved = service.accept_descriptive_fields(run["run_id"], name="Owner-approved Test", concept="Owner-approved concept")
    assert saved["owner_descriptive_fields"]["state"] == "OWNER_ACCEPTED"
    assert saved["owner_descriptive_fields"]["resolved"]["identity"]["name"] == "Owner-approved Test"
    assert saved["owner_descriptive_fields"]["resolved"]["concept"] == "Owner-approved concept"
    assert saved["request"]["typed_choice_snapshot"]["snapshot_sha256"] == run["request"]["typed_choice_snapshot"]["snapshot_sha256"]
    with db.connection() as conn:
        row = conn.execute(
            "SELECT accepted_descriptive_fields_json FROM character_creation_runs WHERE run_id=?",
            (run["run_id"],),
        ).fetchone()
    assert json.loads(row["accepted_descriptive_fields_json"])["identity"]["name"] == "Owner-approved Test"


def test_provider_credentials_are_keyed_by_selected_profile() -> None:
    store = InMemorySecretStore()
    store.set("openai-secret-123", "openai")
    store.set("deepseek-secret-123", "deepseek")
    store.set("custom-secret-123", "custom")
    assert store.get("openai") == "openai-secret-123"
    assert store.get("deepseek") == "deepseek-secret-123"
    assert store.get("custom") == "custom-secret-123"
    assert store.delete("deepseek") is True
    assert store.get("deepseek") is None
    assert store.get("openai") == "openai-secret-123"
    assert store.get("custom") == "custom-secret-123"


def test_provider_environment_fallback_is_selected_profile_only(monkeypatch, tmp_path) -> None:
    store = APIProviderSecretStore(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-env-123")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-env-123")
    monkeypatch.setenv("API_PROVIDER_API_KEY", "generic-legacy-123")
    assert store.get("openai") == "openai-env-123"
    assert store.get("deepseek") == "deepseek-env-123"
    assert store.get("custom") is None
    assert store.status("custom")["present"] is False


def test_custom_endpoint_is_resolved_and_revalidated_before_request(fresh_db) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"connection":"ok"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    resolver = lambda hostname, port: ["8.8.8.8"]
    service = AIProviderService(
        fresh_db,
        transport=httpx.MockTransport(handler),
        secret_store=InMemorySecretStore(),
        resolver=resolver,
    )
    service.configure(
        enabled=True,
        provider_id="custom",
        endpoint="https://example.test/chat",
        model="compatible-model",
        thinking_mode="disabled",
        max_output_tokens=1024,
        timeout_seconds=30,
        data_sharing_acknowledged=True,
        acknowledged_by="P1CR2 test",
    )
    service.set_api_key("custom-secret-123")
    assert service.test_connection()["status"] == "PASS"
    assert calls == ["https://example.test/chat"]

    blocked_calls: list[str] = []
    blocked_service = AIProviderService(
        fresh_db,
        transport=httpx.MockTransport(lambda request: blocked_calls.append(str(request.url)) or httpx.Response(200)),
        secret_store=InMemorySecretStore(),
        resolver=lambda hostname, port: ["8.8.8.8", "127.0.0.1"],
    )
    blocked_service.configure(
        enabled=True,
        provider_id="custom",
        endpoint="https://example.test/chat",
        model="compatible-model",
        thinking_mode="disabled",
        max_output_tokens=1024,
        timeout_seconds=30,
        data_sharing_acknowledged=True,
        acknowledged_by="P1CR2 test",
    )
    blocked_service.set_api_key("custom-secret-123")
    with pytest.raises(FoundryError) as exc:
        blocked_service.test_connection()
    assert exc.value.code == "AI_PROVIDER_ENDPOINT_BLOCKED"
    assert blocked_calls == []


def test_selection_intent_only_stage2_keeps_top_level_target_authority() -> None:
    project, _envelope, run = _authority(5)
    plan = _plan_for_target(5)
    plan["stage2_proposal"] = {"selection_intent_by_slot": {"sphere_priorities": []}}
    assert validate_delegated_target_cl(run, project, plan) == 5
