"""Focused Stage B/C route-substrate tests using temporary databases only."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import _character_creation_api_view, create_app
from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_json
from character_creation.creative_controller import (
    ACTIVE_ROUTE_BINDING_SCHEMA,
    ACTIVATION_POLICY_ACTIVE,
    CONTROLLER_STATE_AUTHORITY_FROZEN,
    DETERMINISTIC_CREATIVE_CONTROLLER,
    LEGACY_FULL_PLAN,
    ControllerRoutePersistence,
    build_active_controller_route_binding,
    build_controller_event,
    build_route_binding,
    initial_route_state_sha256,
    validate_route_binding,
)
import character_creation.creative_controller.route_persistence as route_persistence


ROOT = Path(__file__).resolve().parents[1]


def _db(tmp_path: Path) -> Database:
    db = Database(Settings.from_env(ROOT, tmp_path / "data"))
    db.migrate()
    now = "2026-09-02T00:00:00Z"
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(
               project_id,working_name,status,revision,created_at,updated_at,
               target_factory_version,target_candidate_schema_version,target_gm_screen_version,
               catalog_build_hash,quality_target,project_json,
               compatibility_projection_status,compile_status,consumer_verification_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "p",
                "P",
                "draft",
                0,
                now,
                now,
                "x",
                "x",
                "x",
                None,
                "x",
                canonical_json({"project_id": "p", "revision": 0}),
                "x",
                "x",
                "x",
            ),
        )
    return db


def _run(db: Database, run_id: str, *, request: dict | None = None) -> None:
    now = "2026-09-02T00:00:00Z"
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO character_creation_runs(
               run_id,project_id,starting_revision,execution_mode,idempotency_key,
               request_json,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                "p",
                0,
                "MANUAL_CHAT",
                f"key-{run_id}",
                canonical_json(request or {}),
                "WAITING_FOR_RESPONSE",
                now,
                now,
            ),
        )


class _Projects:
    def __init__(self, db: Database):
        self.db = db

    def get_project(self, project_id: str) -> dict:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT revision,project_json FROM projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
        project = json.loads(row["project_json"])
        project["revision"] = row["revision"]
        project.setdefault("content_lock", {"lock_hash": "a" * 64})
        return {"project": project}


class _Provider:
    def __init__(self) -> None:
        self.status_calls = 0

    def status(self) -> dict:
        self.status_calls += 1
        raise AssertionError("the inactive DCC route must not inspect provider readiness")


class _ActiveProvider(_Provider):
    """Static selected-AI seam; every transport-shaped method is forbidden."""

    def __init__(self, identity_sha256: str = "c" * 64, *, available: bool = True) -> None:
        super().__init__()
        self.identity_sha256 = identity_sha256
        self.available = available
        self.identity_calls = 0
        self.complete_calls = 0

    def selected_ai_identity(self) -> dict[str, str | None]:
        self.identity_calls += 1
        if not self.available:
            return {
                "selected_ai_identity_sha256": None,
                "selected_ai_identity_state": "UNAVAILABLE_WITHOUT_PROVIDER_INVOCATION",
            }
        return {
            "selected_ai_identity_sha256": self.identity_sha256,
            "selected_ai_identity_state": "AVAILABLE_STATIC",
        }

    def complete_json(self, *_args: object, **_kwargs: object) -> None:
        self.complete_calls += 1
        raise AssertionError("active DCC start must not invoke provider transport")


_ACTIVE_PUBLICATION_RECEIPT = {
    "receipt_sha256": "1" * 64,
    "content_snapshot_sha256": "2" * 64,
    "semantic_authority_bundle_sha256": "3" * 64,
    "source_rights_authority_sha256": "4" * 64,
}


def _active_publication(profile_name: str = "v2") -> dict[str, object]:
    return {
        "profile": SimpleNamespace(name=profile_name),
        "publication_receipt": dict(_ACTIVE_PUBLICATION_RECEIPT),
    }


def _active_stub_service(db: Database, monkeypatch: pytest.MonkeyPatch) -> tuple[object, _ActiveProvider]:
    from character_creation.service import CharacterCreationExecutionService

    provider = _ActiveProvider()
    monkeypatch.setattr(
        route_persistence,
        "load_active_dcc_semantic_publication",
        _active_publication,
    )
    monkeypatch.setattr(
        route_persistence,
        "reopen_dcc_semantic_publication",
        lambda _receipt_sha256: _active_publication(),
    )
    service = CharacterCreationExecutionService(
        db,
        stage1=None,
        provider=provider,
        project_store=_Projects(db),
        owner_principal="route-test-owner",
    )

    def complete(_project_id: str, *_args: object, controller_route: str, **_kwargs: object) -> dict:
        binding = (
            build_active_controller_route_binding(provider=provider)
            if controller_route == DETERMINISTIC_CREATIVE_CONTROLLER
            else build_route_binding(controller_route, provider=provider)
        )
        request = {
            "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
            "project_id": "p",
            "project_revision": 0,
            "content_lock_hash": "a" * 64,
            "controller_route": controller_route,
            "controller_route_binding": binding,
        }
        request["request_sha256"] = service.request_payload_sha256(request)
        return request

    service._complete_request = complete
    return service, provider


def _stub_service(db: Database) -> tuple[object, _Provider]:
    from character_creation.service import CharacterCreationExecutionService

    provider = _Provider()
    service = CharacterCreationExecutionService(
        db,
        stage1=None,
        provider=provider,
        project_store=_Projects(db),
        owner_principal="route-test-owner",
    )

    def complete(_project_id: str, *_args: object, controller_route: str, **_kwargs: object) -> dict:
        request = {
            "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
            "project_id": "p",
            "project_revision": 0,
            "content_lock_hash": "a" * 64,
            "controller_route": controller_route,
            "controller_route_binding": build_route_binding(controller_route),
        }
        request["request_sha256"] = service.request_payload_sha256(request)
        return request

    service._complete_request = complete
    return service, provider


def _seed_dcc_run(db: Database, run_id: str) -> dict:
    from character_creation.service import CharacterCreationExecutionService

    binding = build_route_binding(DETERMINISTIC_CREATIVE_CONTROLLER)
    request = {
        "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
        "project_id": "p",
        "project_revision": 0,
        "content_lock_hash": "a" * 64,
        "controller_route": DETERMINISTIC_CREATIVE_CONTROLLER,
        "controller_route_binding": binding,
    }
    request["request_sha256"] = CharacterCreationExecutionService.request_payload_sha256(request)
    _run(db, run_id, request=request)
    with db.transaction() as conn:
        ControllerRoutePersistence(db).bind_run(
            conn,
            run_id=run_id,
            project_id="p",
            request_sha256=request["request_sha256"],
            binding=binding,
            created_at="2026-09-02T00:00:00Z",
        )
    return request


def _shape_dcc_needs_review(db: Database, run_id: str) -> None:
    """Make a frozen DCC row look eligible for local correction."""

    response_text = "{}"
    response = {
        "exact_response_text": response_text,
        "response_sha256": sha256_bytes(response_text.encode("utf-8")),
    }
    validation = {
        "last_submission_error": {
            "code": "CG1_PLAN_SCHEMA_INVALID",
            "message": "test-only correction-eligible diagnostic",
            "details": {},
        }
    }
    transport = {"provider_id": "local", "automatic_retries": 0}
    with db.transaction() as conn:
        conn.execute(
            """UPDATE character_creation_runs
               SET execution_mode='STANDARD_API', status='NEEDS_REVIEW',
                   response_json=?, validation_json=?, transport_json=?
               WHERE run_id=?""",
            (canonical_json(response), canonical_json(validation), canonical_json(transport), run_id),
        )


def test_service_start_pins_dcc_route_before_request_hash_and_does_not_call_provider(tmp_path: Path) -> None:
    db = _db(tmp_path)
    service, provider = _stub_service(db)
    run = service.start(
        "p",
        execution_mode="STANDARD_API",
        idempotency_key="dcc-start-1234",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )
    request = run["request"]
    assert run["status"] == "PREPARING_REQUEST"
    assert provider.status_calls == 0
    assert request["controller_route"] == DETERMINISTIC_CREATIVE_CONTROLLER
    assert request["request_sha256"] == service.request_payload_sha256(request)
    assert request["controller_route_binding"]["binding_sha256"]
    assert run["controller_route_status"]["event_count"] == 1
    assert service.list("p")[0]["controller_route_status"] == run["controller_route_status"]
    assert service.recovery("p")["active_run"]["controller_route_status"] == run["controller_route_status"]


def test_active_dcc_start_pins_v2_authority_ai_and_frozen_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    service, provider = _active_stub_service(db, monkeypatch)
    run = service.start(
        "p",
        execution_mode="STANDARD_API",
        idempotency_key="active-dcc-1234",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )

    binding = run["request"]["controller_route_binding"]
    assert binding["schema"] == ACTIVE_ROUTE_BINDING_SCHEMA
    assert binding["activation_policy"] == ACTIVATION_POLICY_ACTIVE
    assert binding["selected_ai_identity_sha256"] == provider.identity_sha256
    assert binding["selected_ai_identity_state"] == "AVAILABLE_STATIC"
    for field, expected in _ACTIVE_PUBLICATION_RECEIPT.items():
        binding_field = "publication_receipt_sha256" if field == "receipt_sha256" else field
        assert binding[binding_field] == expected
    assert run["controller_route_status"]["state"] == CONTROLLER_STATE_AUTHORITY_FROZEN
    assert run["controller_route_status"]["activation_policy"] == ACTIVATION_POLICY_ACTIVE
    projection = service.controller_route_projection(run["run_id"])
    assert projection is not None
    assert projection["state"] == CONTROLLER_STATE_AUTHORITY_FROZEN
    assert projection["events"][0]["payload"]["state"] == CONTROLLER_STATE_AUTHORITY_FROZEN
    # Migration 029 retains its append-only storage sentinel; the projection
    # is the authoritative derived state for the V2 activation slice.
    with db.connection() as conn:
        assert conn.execute(
            "SELECT state FROM dcc_controller_run_bindings WHERE run_id=?",
            (run["run_id"],),
        ).fetchone()[0] == "INACTIVE"
    assert provider.identity_calls == 1
    assert provider.status_calls == 0
    assert provider.complete_calls == 0

    public = _character_creation_api_view(run)
    public_status = public["controller_route_status"]
    assert public_status["state"] == CONTROLLER_STATE_AUTHORITY_FROZEN
    assert public_status["publication_receipt_sha256"] == _ACTIVE_PUBLICATION_RECEIPT["receipt_sha256"]
    assert public_status["selected_ai_identity_sha256"] == provider.identity_sha256
    assert "controller_route_binding" not in public["request"]
    assert "events" not in public_status


@pytest.mark.parametrize("profile_name", ("v2", "v3"))
def test_active_and_historical_route_bindings_accept_validated_v2_or_v3(
    profile_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    provider = _ActiveProvider()
    publication = lambda: _active_publication(profile_name)
    monkeypatch.setattr(route_persistence, "load_active_dcc_semantic_publication", publication)
    monkeypatch.setattr(route_persistence, "reopen_dcc_semantic_publication", lambda _receipt: publication())

    binding = build_active_controller_route_binding(provider=provider)
    persistence = ControllerRoutePersistence(db)
    persistence._validate_active_publication_binding(binding)
    assert binding["publication_receipt_sha256"] == _ACTIVE_PUBLICATION_RECEIPT["receipt_sha256"]


def test_seeded_active_route_binding_persists_without_reading_ai_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    provider = _ActiveProvider(available=False)
    publication = lambda: _active_publication("v2")
    monkeypatch.setattr(route_persistence, "load_active_dcc_semantic_publication", publication)
    monkeypatch.setattr(route_persistence, "reopen_dcc_semantic_publication", lambda _receipt: publication())

    binding = build_active_controller_route_binding(provider=provider, seeded=True)
    assert binding["selected_ai_identity_sha256"] is None
    assert binding["selected_ai_identity_state"] == route_persistence.SELECTED_AI_SEEDED
    assert provider.identity_calls == 0
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO character_creation_runs(run_id,project_id,starting_revision,execution_mode,idempotency_key,request_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("seeded-run", "p", 0, "STANDARD_API", "seeded-key", "{}", "PREPARING_REQUEST", "2026-09-02T00:00:00Z", "2026-09-02T00:00:00Z"),
        )
        projection = ControllerRoutePersistence(db).bind_new_run(
            conn, run_id="seeded-run", project_id="p", request_sha256="a" * 64, binding=binding,
        )
    assert projection is not None
    assert ControllerRoutePersistence(db).projection("seeded-run")["binding"]["selected_ai_identity_sha256"] is None


def test_active_route_rejects_non_v2_v3_publication_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _ActiveProvider()
    monkeypatch.setattr(
        route_persistence,
        "load_active_dcc_semantic_publication",
        lambda: _active_publication("v1"),
    )
    with pytest.raises(FoundryError) as failure:
        build_active_controller_route_binding(provider=provider)
    assert failure.value.code == "DCC_ROUTE_PUBLICATION_INVALID"


def test_active_v2_binding_rejects_rehashed_unavailable_ai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    service, provider = _active_stub_service(db, monkeypatch)
    binding = build_active_controller_route_binding(provider=provider)
    binding["selected_ai_identity_sha256"] = None
    binding["selected_ai_identity_state"] = "UNAVAILABLE_WITHOUT_PROVIDER_INVOCATION"
    binding["binding_sha256"] = sha256_json(
        {key: binding[key] for key in sorted(binding) if key != "binding_sha256"}
    )
    with pytest.raises(FoundryError) as failure:
        validate_route_binding(binding)
    assert failure.value.code == "DCC_ROUTE_BINDING_INVALID"


def test_active_dcc_authority_or_ai_failure_happens_before_run_or_preference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    service, provider = _active_stub_service(db, monkeypatch)
    monkeypatch.setattr(
        route_persistence,
        "load_active_dcc_semantic_publication",
        lambda: (_ for _ in ()).throw(FoundryError("DCC_PUBLICATION_POINTER_UNAVAILABLE", "unavailable")),
    )
    with pytest.raises(FoundryError) as publication_failure:
        service.start(
            "p",
            execution_mode="STANDARD_API",
            idempotency_key="active-pub-fail-1",
            controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
        )
    assert publication_failure.value.code == "DCC_ROUTE_PUBLICATION_UNAVAILABLE"
    provider.available = False
    monkeypatch.setattr(route_persistence, "load_active_dcc_semantic_publication", _active_publication)
    with pytest.raises(FoundryError) as ai_failure:
        service.start(
            "p",
            execution_mode="STANDARD_API",
            idempotency_key="active-ai-fail-1",
            controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
        )
    assert ai_failure.value.code == "DCC_SELECTED_AI_UNAVAILABLE"
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM character_creation_runs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM dcc_controller_run_bindings").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM dcc_controller_events").fetchone()[0] == 0
    assert service.preference("p")["explicit"] is False


def test_saved_provider_selection_identity_is_read_only_and_provider_free(tmp_path: Path) -> None:
    from ai_provider.secrets import InMemorySecretStore
    from ai_provider.identity import build_hosted_identity
    from ai_provider.service import AIProviderService

    db = _db(tmp_path)
    provider = AIProviderService(db, secret_store=InMemorySecretStore())
    provider.configure(
        enabled=True,
        provider_id="deepseek",
        endpoint="https://api.deepseek.com/chat/completions",
        model="deepseek-v4-flash",
        thinking_mode="enabled",
        max_output_tokens=1024,
        timeout_seconds=30,
        data_sharing_acknowledged=True,
        acknowledged_by="dcc-route-test",
    )
    identity = provider.selected_ai_identity()
    assert identity["selected_ai_identity_state"] == "AVAILABLE_STATIC"
    assert identity["selected_ai_identity_sha256"] == build_hosted_identity("deepseek", "deepseek-v4-flash")["identity_sha256"]
    assert identity["identity_assurance"] == "SERVICE_LABELED"


def test_active_dcc_binding_failure_rolls_back_run_and_event_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    service, _provider = _active_stub_service(db, monkeypatch)
    original = service.controller_routes.bind_new_run

    def fail(*_args: object, **_kwargs: object) -> None:
        raise FoundryError("DCC_ROUTE_BINDING_PERSISTENCE_FAILED", "test failure")

    service.controller_routes.bind_new_run = fail
    with pytest.raises(FoundryError) as failure:
        service.start(
            "p",
            execution_mode="STANDARD_API",
            idempotency_key="active-bind-fail-1",
            controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
        )
    service.controller_routes.bind_new_run = original
    assert failure.value.code == "DCC_ROUTE_BINDING_PERSISTENCE_FAILED"
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM character_creation_runs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM dcc_controller_run_bindings").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM dcc_controller_events").fetchone()[0] == 0


def test_active_reload_reopens_pinned_receipt_not_mutable_active_pointer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    service, provider = _active_stub_service(db, monkeypatch)
    run = service.start(
        "p",
        execution_mode="MANUAL_CHAT",
        idempotency_key="active-historical-1",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )
    pinned = run["request"]["controller_route_binding"]["publication_receipt_sha256"]
    reopen_calls: list[str] = []

    def reopen(receipt_sha256: str) -> dict[str, object]:
        reopen_calls.append(receipt_sha256)
        return _active_publication()

    monkeypatch.setattr(route_persistence, "reopen_dcc_semantic_publication", reopen)
    # A changed/unavailable mutable pointer must not affect a run that already
    # carries a validated historical publication identity.
    monkeypatch.setattr(
        route_persistence,
        "load_active_dcc_semantic_publication",
        lambda: (_ for _ in ()).throw(FoundryError("DCC_PUBLICATION_POINTER_UNAVAILABLE", "pointer changed")),
    )
    fresh = type(service)(
        db,
        stage1=None,
        provider=provider,
        project_store=_Projects(db),
        owner_principal="route-test-owner",
    )
    assert fresh.get(run["run_id"])["controller_route_status"]["publication_receipt_sha256"] == pinned
    assert reopen_calls == [pinned]


def test_active_reload_validates_once_per_content_and_rejects_missing_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    service, provider = _active_stub_service(db, monkeypatch)
    reopen_calls: list[str] = []

    def reopen(receipt_sha256: str) -> dict[str, object]:
        reopen_calls.append(receipt_sha256)
        return _active_publication()

    monkeypatch.setattr(route_persistence, "reopen_dcc_semantic_publication", reopen)
    run = service.start(
        "p",
        execution_mode="MANUAL_CHAT",
        idempotency_key="active-cache-1",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )
    first = service.get(run["run_id"])["controller_route_status"]
    second = service.get(run["run_id"])["controller_route_status"]
    assert first == second
    assert len(reopen_calls) == 1

    fresh = type(service)(
        db,
        stage1=None,
        provider=provider,
        project_store=_Projects(db),
        owner_principal="route-test-owner",
    )
    assert fresh.get(run["run_id"])["controller_route_status"] == first
    # FINALSPEED2: repositories share the same verified publication identity;
    # constructing a new service is not a change to its authority content.
    assert len(reopen_calls) == 1

    storage_key = route_persistence.dcc_publication_storage_key()
    monkeypatch.setattr(route_persistence, "dcc_publication_storage_key", lambda: ("changed-storage", storage_key))
    monkeypatch.setattr(
        route_persistence,
        "reopen_dcc_semantic_publication",
        lambda _receipt_sha256: (_ for _ in ()).throw(
            FoundryError("DCC_PUBLICATION_RECEIPT_UNAVAILABLE", "receipt missing")
        ),
    )
    with pytest.raises(FoundryError) as warm_failure:
        fresh.get(run["run_id"])
    assert warm_failure.value.code == "DCC_ROUTE_PUBLICATION_TAMPERED"
    missing_receipt_store = type(service)(
        db,
        stage1=None,
        provider=provider,
        project_store=_Projects(db),
        owner_principal="route-test-owner",
    )
    with pytest.raises(FoundryError) as missing_failure:
        missing_receipt_store.get(run["run_id"])
    assert missing_failure.value.code == "DCC_ROUTE_PUBLICATION_TAMPERED"


def test_active_reload_rejects_coherently_rehashed_binding_with_receipt_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    service, provider = _active_stub_service(db, monkeypatch)
    run = service.start(
        "p",
        execution_mode="MANUAL_CHAT",
        idempotency_key="active-rehash-1",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )
    run_id = run["run_id"]
    mutated_binding = dict(run["request"]["controller_route_binding"])
    mutated_binding["content_snapshot_sha256"] = "f" * 64
    mutated_binding["binding_sha256"] = sha256_json(
        {key: mutated_binding[key] for key in sorted(mutated_binding) if key != "binding_sha256"}
    )
    mutated_request = dict(run["request"])
    mutated_request["controller_route_binding"] = mutated_binding
    mutated_request["request_sha256"] = service.request_payload_sha256(mutated_request)

    with db.transaction() as conn:
        conn.execute("DROP TRIGGER trg_dcc_controller_run_bindings_no_update")
        conn.execute("DROP TRIGGER trg_dcc_controller_events_no_update")
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(mutated_request), run_id),
        )
        conn.execute(
            "UPDATE dcc_controller_run_bindings SET binding_json=?,binding_sha256=?,request_sha256=? WHERE run_id=?",
            (
                canonical_json(mutated_binding),
                mutated_binding["binding_sha256"],
                mutated_request["request_sha256"],
                run_id,
            ),
        )
        old_event = json.loads(conn.execute(
            "SELECT event_json FROM dcc_controller_events WHERE run_id=?", (run_id,)
        ).fetchone()[0])
        state_hash = initial_route_state_sha256(
            run_id=run_id,
            project_id="p",
            binding=mutated_binding,
        )
        event = build_controller_event(
            run_id=run_id,
            project_id="p",
            route_binding_sha256=mutated_binding["binding_sha256"],
            ordinal=1,
            event_type="ROUTE_BOUND",
            previous_event_sha256=None,
            subject_sha256=mutated_binding["binding_sha256"],
            state_sha256_before=state_hash,
            state_sha256_after=state_hash,
            payload={
                "route_mode": DETERMINISTIC_CREATIVE_CONTROLLER,
                "state": CONTROLLER_STATE_AUTHORITY_FROZEN,
            },
            created_at=old_event["created_at"],
        )
        conn.execute(
            """UPDATE dcc_controller_events SET event_id=?,route_binding_sha256=?,ordinal=?,
               event_type=?,previous_event_sha256=?,subject_sha256=?,state_sha256_before=?,
               state_sha256_after=?,event_json=?,event_sha256=?,created_at=? WHERE run_id=?""",
            (
                event["event_id"], event["route_binding_sha256"], event["ordinal"],
                event["event_type"], event["previous_event_sha256"], event["subject_sha256"],
                event["state_sha256_before"], event["state_sha256_after"], canonical_json(event),
                event["event_sha256"], event["created_at"], run_id,
            ),
        )

    # The request, binding, row columns, and event are all coherently
    # rehashed; only the detached historical receipt proves the mismatch.
    fresh = type(service)(
        db,
        stage1=None,
        provider=provider,
        project_store=_Projects(db),
        owner_principal="route-test-owner",
    )
    with pytest.raises(FoundryError) as mismatch_failure:
        fresh.get(run_id)
    assert mismatch_failure.value.code == "DCC_ROUTE_PUBLICATION_TAMPERED"


def test_active_dcc_reload_rejects_request_binding_and_event_tamper_and_status_is_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db(tmp_path)
    service, _provider = _active_stub_service(db, monkeypatch)
    run = service.start(
        "p",
        execution_mode="MANUAL_CHAT",
        idempotency_key="active-tamper-1",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )
    run_id = run["run_id"]
    status = run["controller_route_status"]
    assert service.get(run_id)["controller_route_status"] == status
    assert service.recovery("p")["active_run"]["controller_route_status"] == status

    with db.transaction() as conn:
        request = json.loads(conn.execute(
            "SELECT request_json FROM character_creation_runs WHERE run_id=?", (run_id,)
        ).fetchone()[0])
        request["controller_route"] = LEGACY_FULL_PLAN
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(request), run_id),
        )
    with pytest.raises(FoundryError) as request_failure:
        service.get(run_id)
    assert request_failure.value.code == "DCC_ROUTE_BINDING_TAMPERED"

    with db.transaction() as conn:
        missing_binding_request = dict(run["request"])
        missing_binding_request.pop("controller_route_binding")
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(missing_binding_request), run_id),
        )
    with pytest.raises(FoundryError) as missing_binding_failure:
        service.get(run_id)
    assert missing_binding_failure.value.code == "DCC_ROUTE_BINDING_NOT_FOUND"

    # Restore the request row, then tamper the append-only binding JSON.  The
    # binding trigger is deliberately removed only in this temporary database
    # so reload exercises the sealed self-hash boundary.
    with db.transaction() as conn:
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(run["request"]), run_id),
        )
        conn.execute("DROP TRIGGER trg_dcc_controller_run_bindings_no_update")
        binding = json.loads(conn.execute(
            "SELECT binding_json FROM dcc_controller_run_bindings WHERE run_id=?", (run_id,)
        ).fetchone()[0])
        binding["selected_ai_identity_sha256"] = "d" * 64
        conn.execute(
            "UPDATE dcc_controller_run_bindings SET binding_json=? WHERE run_id=?",
            (canonical_json(binding), run_id),
        )
    with pytest.raises(FoundryError) as binding_failure:
        service.get(run_id)
    assert binding_failure.value.code == "DCC_ROUTE_BINDING_HASH_INVALID"


def test_active_dcc_event_column_tamper_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    service, _provider = _active_stub_service(db, monkeypatch)
    run = service.start(
        "p",
        execution_mode="MANUAL_CHAT",
        idempotency_key="active-event-tamper-1",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )
    with db.transaction() as conn:
        conn.execute("DROP TRIGGER trg_dcc_controller_events_no_update")
        conn.execute(
            "UPDATE dcc_controller_events SET state_sha256_after=? WHERE run_id=?",
            ("e" * 64, run["run_id"]),
        )
    with pytest.raises(FoundryError) as failure:
        service.get(run["run_id"])
    assert failure.value.code == "DCC_CONTROLLER_EVENT_TAMPERED"


def test_service_omitted_route_is_legacy_and_binding_failure_rolls_back_run(tmp_path: Path) -> None:
    db = _db(tmp_path)
    service, _provider = _stub_service(db)
    legacy = service.start(
        "p",
        execution_mode="MANUAL_CHAT",
        idempotency_key="legacy-start-1234",
    )
    assert legacy["request"]["controller_route"] == LEGACY_FULL_PLAN
    assert "controller_route_status" not in legacy
    assert service.controller_route_projection(legacy["run_id"]) is None
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM dcc_controller_run_bindings").fetchone()[0] == 0

    original = service.controller_routes.bind_new_run

    def fail(*_args: object, **_kwargs: object) -> None:
        raise FoundryError("DCC_ROUTE_BINDING_PERSISTENCE_FAILED", "test failure")

    service.controller_routes.bind_new_run = fail
    with pytest.raises(FoundryError) as failure:
        service.start(
            "p",
            execution_mode="MANUAL_CHAT",
            idempotency_key="dcc-rollback-1234",
            controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
        )
    assert failure.value.code == "DCC_ROUTE_BINDING_PERSISTENCE_FAILED"
    service.controller_routes.bind_new_run = original
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM character_creation_runs WHERE idempotency_key='dcc-rollback-1234'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM dcc_controller_run_bindings").fetchone()[0] == 0


def test_service_reload_rejects_request_or_binding_tamper(tmp_path: Path) -> None:
    db = _db(tmp_path)
    service, _provider = _stub_service(db)
    run = service.start(
        "p",
        execution_mode="MANUAL_CHAT",
        idempotency_key="dcc-tamper-1234",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )
    with db.transaction() as conn:
        request = json.loads(conn.execute("SELECT request_json FROM character_creation_runs WHERE run_id=?", (run["run_id"],)).fetchone()[0])
        request["controller_route"] = LEGACY_FULL_PLAN
        # The run table is not protected by the DCC binding triggers in this
        # slice, so this simulates an out-of-band tamper and verifies reload
        # remains fail-closed at the service boundary.
        conn.execute("UPDATE character_creation_runs SET request_json=? WHERE run_id=?", (canonical_json(request), run["run_id"]))
    with pytest.raises(FoundryError) as failure:
        service.get(run["run_id"])
    assert failure.value.code in {"DCC_ROUTE_BINDING_TAMPERED", "DCC_ROUTE_REQUEST_HASH_INVALID"}

    with db.transaction() as conn:
        request = json.loads(
            conn.execute(
                "SELECT request_json FROM character_creation_runs WHERE run_id=?",
                (run["run_id"],),
            ).fetchone()[0]
        )
        request["controller_route"] = DETERMINISTIC_CREATIVE_CONTROLLER
        request["content_lock_hash"] = "b" * 64
        # Restore the route selector but alter an unrelated request field;
        # reload must still recompute and reject the immutable request hash.
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(request), run["run_id"]),
        )
    with pytest.raises(FoundryError) as request_failure:
        service.get(run["run_id"])
    assert request_failure.value.code == "DCC_ROUTE_REQUEST_HASH_INVALID"

    second = service.start(
        "p",
        execution_mode="MANUAL_CHAT",
        idempotency_key="dcc-binding-tamper",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )
    with db.transaction() as conn:
        request = json.loads(
            conn.execute(
                "SELECT request_json FROM character_creation_runs WHERE run_id=?",
                (second["run_id"],),
            ).fetchone()[0]
        )
        request["controller_route_binding"]["route_mode"] = LEGACY_FULL_PLAN
        # A request-table mutation cannot pass the self-hash validation of the
        # sealed binding, so reload must reject it before exposing the run.
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(request), second["run_id"]),
        )
    with pytest.raises(FoundryError) as binding_failure:
        service.get(second["run_id"])
    assert binding_failure.value.code in {
        "DCC_ROUTE_BINDING_INVALID",
        "DCC_ROUTE_BINDING_HASH_INVALID",
    }


def test_omitted_route_is_legacy_and_preexisting_rows_are_not_retrofitted(tmp_path: Path) -> None:
    db = _db(tmp_path)
    binding = build_route_binding(None)
    assert binding["route_mode"] == LEGACY_FULL_PLAN
    _run(db, "legacy")
    store = ControllerRoutePersistence(db)
    with db.transaction() as conn:
        assert store.bind_run(
            conn,
            run_id="legacy",
            project_id="p",
            request_sha256="a" * 64,
            binding=binding,
        ) is None
    assert store.projection("legacy") is None
    with db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM dcc_controller_run_bindings").fetchone()[0] == 0


def test_dcc_binding_is_hashed_persisted_atomically_and_reloadable(tmp_path: Path) -> None:
    db = _db(tmp_path)
    binding = build_route_binding(DETERMINISTIC_CREATIVE_CONTROLLER)
    _run(db, "dcc")
    store = ControllerRoutePersistence(db)
    with db.transaction() as conn:
        receipt = store.bind_run(
            conn,
            run_id="dcc",
            project_id="p",
            request_sha256="b" * 64,
            binding=binding,
            created_at="2026-09-02T00:00:00Z",
        )
    assert receipt and receipt["event_count"] == 1
    assert validate_route_binding(binding) == binding
    first = store.projection("dcc")
    second = ControllerRoutePersistence(db).projection("dcc")
    assert first == second
    assert first["binding"]["binding_sha256"] == binding["binding_sha256"]
    assert first["events"][0]["previous_event_sha256"] is None
    assert first["events"][0]["event_sha256"] == first["event_head_sha256"]


def test_append_only_and_strict_cas_reject_stale_or_mutating_writes(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _run(db, "dcc")
    store = ControllerRoutePersistence(db)
    with db.transaction() as conn:
        store.bind_run(
            conn,
            run_id="dcc",
            project_id="p",
            request_sha256="c" * 64,
            binding=build_route_binding(DETERMINISTIC_CREATIVE_CONTROLLER),
        )
    current = store.projection("dcc")
    state = current["state_sha256"]
    event = store.append_event(
        "dcc",
        event_type="FUTURE_SEAM_PROBE",
        subject_sha256="d" * 64,
        state_sha256_before=state,
        state_sha256_after="e" * 64,
        expected_ordinal=2,
        expected_event_head_sha256=current["event_head_sha256"],
        payload={"state": "INACTIVE"},
    )
    assert event["ordinal"] == 2
    with pytest.raises(FoundryError) as stale:
        store.append_event(
            "dcc",
            event_type="FUTURE_SEAM_PROBE",
            subject_sha256="d" * 64,
            state_sha256_before=state,
            state_sha256_after="e" * 64,
            expected_ordinal=2,
            expected_event_head_sha256=current["event_head_sha256"],
            payload={"state": "INACTIVE"},
        )
    assert stale.value.code == "DCC_CONTROLLER_EVENT_STALE"
    with db.connection() as conn:
        with pytest.raises(Exception):
            conn.execute("UPDATE dcc_controller_run_bindings SET state='INACTIVE' WHERE run_id='dcc'")
        with pytest.raises(Exception):
            conn.execute("DELETE FROM dcc_controller_events WHERE run_id='dcc'")


def test_persisted_event_column_and_json_tamper_fail_closed(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed_dcc_run(db, "event-column-tamper")
    _seed_dcc_run(db, "event-json-tamper")
    store = ControllerRoutePersistence(db)

    with db.transaction() as conn:
        conn.execute("DROP TRIGGER trg_dcc_controller_events_no_update")
        conn.execute(
            "UPDATE dcc_controller_events SET event_type=? WHERE run_id=?",
            ("TAMPERED", "event-column-tamper"),
        )
    with pytest.raises(FoundryError) as column_failure:
        store.projection("event-column-tamper")
    assert column_failure.value.code == "DCC_CONTROLLER_EVENT_TAMPERED"

    with db.transaction() as conn:
        event = json.loads(
            conn.execute(
                "SELECT event_json FROM dcc_controller_events WHERE run_id=?",
                ("event-json-tamper",),
            ).fetchone()[0]
        )
        event["payload"]["tampered"] = True
        conn.execute(
            "UPDATE dcc_controller_events SET event_json=? WHERE run_id=?",
            (canonical_json(event), "event-json-tamper"),
        )
    with pytest.raises(FoundryError) as json_failure:
        store.projection("event-json-tamper")
    assert json_failure.value.code == "DCC_CONTROLLER_EVENT_HASH_INVALID"


def test_http_run_list_redacts_dcc_binding_and_events(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _seed_dcc_run(db, "http-dcc")
    app = create_app(db.settings)
    with TestClient(app) as client:
        response = client.get("/api/projects/p/character-creation/runs")

    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["project_id"] == "p"
    assert len(envelope["runs"]) == 1
    public = envelope["runs"][0]
    assert public["run_id"] == "http-dcc"
    assert public["controller_route_status"]["mode"] == DETERMINISTIC_CREATIVE_CONTROLLER
    assert public["controller_route_status"]["event_count"] == 1
    assert "controller_route_binding" not in public["request"]
    serialized = json.dumps(public, sort_keys=True)
    assert "controller_version_sha256" not in serialized
    assert "operator_contract_sha256" not in serialized
    assert "selected_ai_identity_state" not in serialized
    assert "ROUTE_BOUND" not in serialized
    assert "event_json" not in serialized
    assert "events" not in public


def test_public_route_projection_redacts_binding_and_event_details(tmp_path: Path) -> None:
    # The API helper receives only the safe service projection here; private
    # event/binding details are intentionally not part of its public contract.
    run = {
        "run_id": "dcc",
        "project_id": "p",
        "request": {
            "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
            "project_id": "p",
            "project_revision": 0,
            "request_sha256": "f" * 64,
            "content_lock_hash": "a" * 64,
            "controller_route": DETERMINISTIC_CREATIVE_CONTROLLER,
        },
        "controller_route_status": {
            "schema": "TianxiaFoundry.ControllerRouteStatus.v1",
            "run_id": "dcc",
            "project_id": "p",
            "mode": DETERMINISTIC_CREATIVE_CONTROLLER,
            "state": "INACTIVE",
            "request_sha256": "f" * 64,
            "binding_sha256": "e" * 64,
            "event_count": 1,
            "event_head_sha256": "d" * 64,
            "private_evidence": {"secret": "hidden"},
        },
    }
    public = _character_creation_api_view(run)
    assert public["controller_route_status"]["mode"] == DETERMINISTIC_CREATIVE_CONTROLLER
    assert "private_evidence" not in public["controller_route_status"]
    assert "controller_route_binding" not in public["request"]


def test_dcc_needs_review_hides_and_rejects_local_ai_correction_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from character_creation.service import (
        DCC_PROVIDER_EXECUTION_NOT_ACTIVATED,
        DCC_PROVIDER_EXECUTION_NOT_ACTIVATED_MESSAGE,
    )

    db = _db(tmp_path)
    service, provider = _active_stub_service(db, monkeypatch)
    run = service.start(
        "p",
        execution_mode="STANDARD_API",
        idempotency_key="dcc-correction-fence-1",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )
    _shape_dcc_needs_review(db, run["run_id"])

    loaded = service.get(run["run_id"])
    availability = loaded["action_availability"]["retry_local_ai_correction"]
    assert availability["available"] is False
    assert availability["reason"] == DCC_PROVIDER_EXECUTION_NOT_ACTIVATED_MESSAGE
    assert service._explicit_provider_correction_context(loaded) is None
    assert provider.status_calls == 0
    assert provider.complete_calls == 0

    with pytest.raises(FoundryError) as failure:
        service.retry_local_ai_correction(run["run_id"])
    assert failure.value.code == DCC_PROVIDER_EXECUTION_NOT_ACTIVATED
    assert failure.value.message == DCC_PROVIDER_EXECUTION_NOT_ACTIVATED_MESSAGE
    assert failure.value.status_code == 409
    assert provider.status_calls == 0
    assert provider.complete_calls == 0


def test_private_run_provider_rejects_frozen_dcc_before_provider_audit_or_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from character_creation.service import DCC_PROVIDER_EXECUTION_NOT_ACTIVATED

    db = _db(tmp_path)
    service, provider = _active_stub_service(db, monkeypatch)
    run = service.start(
        "p",
        execution_mode="STANDARD_API",
        idempotency_key="dcc-provider-fence-1",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
    )

    with pytest.raises(FoundryError) as failure:
        service._run_provider(run["run_id"])
    assert failure.value.code == DCC_PROVIDER_EXECUTION_NOT_ACTIVATED
    assert failure.value.status_code == 409
    assert provider.status_calls == 0
    assert provider.complete_calls == 0
