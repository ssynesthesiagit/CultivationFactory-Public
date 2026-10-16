"""Focused tests for the server-owned preferred combat target."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import FoundryError
from app.models import CharacterCreationStartRequest
import character_creation.service as creation_service
from character_creation.stage1_first_compile import compile_once_stage1_first
from character_creation.service import (
    CharacterCreationExecutionService,
    SERVER_OUTPUT_PROFILE_NAME,
    SERVER_OUTPUT_PROFILE_SCHEMA,
    _PRODUCTION_RELEASE_COMBAT_EVIDENCE_SCHEMA,
    _production_release_combat_receipt,
)
from character_creation.response_materialization import RESPONSE_SCHEMA


def _request_service(monkeypatch) -> CharacterCreationExecutionService:
    class Authority:
        path_profiles = {}
        backgrounds = {}
        authority_root = Path("/definitely-not-a-production-authority")
        root = authority_root
        identity = {"files": {}}

        @staticmethod
        def method_catalog(*, initial_creation=False):
            return {"records": {}}

        @staticmethod
        def foundation_catalog():
            return {"orthodox": {}}

    delegated = {
        "choices_by_slot": {},
        "allowed_choice_ids_by_slot": {},
        "typed_choice_authority_by_slot": {},
        "advancement_choice_milestones": [],
        "path_progression_choices": [],
        "envelope_sha256": "a" * 64,
    }
    monkeypatch.setattr(creation_service, "NonSphereAuthorityService", lambda _db: Authority())
    monkeypatch.setattr(creation_service, "build_compiler_selection_authority", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        creation_service,
        "build_delegated_choice_envelope",
        lambda *args, **kwargs: deepcopy(delegated),
    )
    monkeypatch.setattr(
        creation_service,
        "_bind_path_feature_ability_change_rules",
        lambda *args, **kwargs: None,
    )

    service = object.__new__(CharacterCreationExecutionService)
    service.db = SimpleNamespace(settings=SimpleNamespace(vendor_dir=Path(".")))
    service.stage1 = SimpleNamespace(
        generate_prompt=lambda _project_id: {"envelope": {"user_locks": []}}
    )
    service.projects = SimpleNamespace()
    service._project = lambda project_id: {
        "project_id": project_id,
        "revision": 4,
        "user_locks": [{"field": "target_cl", "value": 1}],
        "content_lock": {"lock_hash": "c" * 64},
    }
    service._revision = lambda _project_id: 4
    service._content_lock_hash = lambda _project_id: "c" * 64
    service._choice_snapshot = lambda _project_id: {"snapshot_sha256": "d" * 64}
    return service


def test_start_request_has_explicit_optional_combat_target():
    default = CharacterCreationStartRequest(
        execution_mode="MANUAL_CHAT",
        idempotency_key="combat-target-default",
    )
    enabled = CharacterCreationStartRequest(
        execution_mode="MANUAL_CHAT",
        idempotency_key="combat-target-enabled",
        combat_ready=True,
    )
    assert default.combat_ready is False
    assert enabled.combat_ready is True


def test_start_forwards_owner_target_to_request_completion():
    service = object.__new__(CharacterCreationExecutionService)
    captured = {}
    service.owner_principal = "test-owner"
    service.set_preference = lambda *_args, **_kwargs: None

    def complete(*args, **kwargs):
        captured.update(kwargs)
        return {
            "project_revision": 2,
            "content_lock_hash": "b" * 64,
            "request_sha256": "a" * 64,
        }

    service._complete_request = complete

    class _Result:
        def fetchone(self):
            return None

    class _Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return _Result()

    class _DB:
        def connection(self):
            return _Context()

        def transaction(self):
            return _Context()

    service.db = _DB()
    service._append_attempt = lambda *args, **kwargs: None
    service.get = lambda run_id: {"run_id": run_id}

    result = service.start(
        "project.start-forward",
        execution_mode="MANUAL_CHAT",
        idempotency_key="start-forward",
        combat_ready=True,
    )
    assert result["run_id"].startswith("cg1.run.")
    assert captured["combat_ready"] is True


def test_combat_collaborator_selection_is_driven_by_normalized_target():
    service = object.__new__(CharacterCreationExecutionService)
    service.production_release = None
    assert "combat_readiness" in service._required_collaborators(True)
    assert "combat_readiness" not in service._required_collaborators(False)


def _production_combat_receipt() -> dict:
    return {
        "schema_version": _PRODUCTION_RELEASE_COMBAT_EVIDENCE_SCHEMA,
        "raw_evidence_hashes": {"producer": "p" * 64},
        "semantic_projections": {"producer": {}},
        "layer_status": {"producer_command5": {"valid": True}},
        "schema_presence": {"producer_command5": True},
        "equalities": {"all_corresponding": True},
        "equality": True,
    }


def test_production_release_owns_combat_receipt_without_optional_collaborator():
    service = object.__new__(CharacterCreationExecutionService)
    service.production_release = object()
    service.combat_readiness = None

    assert "combat_readiness" not in service._required_collaborators(True)
    receipt = _production_combat_receipt()
    release = {
        "combat_readiness": receipt,
        "completion_proof": {"combat": deepcopy(receipt)},
    }
    returned = _production_release_combat_receipt(release)
    assert returned == receipt
    assert returned is not receipt


@pytest.mark.parametrize(
    "release",
    [
        {},
        {"combat_readiness": _production_combat_receipt()},
        {
            "combat_readiness": _production_combat_receipt(),
            "completion_proof": {"combat": {"equality": True}},
        },
        {
            "combat_readiness": {
                **_production_combat_receipt(),
                "equality": False,
            },
            "completion_proof": {"combat": _production_combat_receipt()},
        },
    ],
)
def test_production_release_combat_receipt_is_fail_closed(release):
    with pytest.raises(FoundryError) as raised:
        _production_release_combat_receipt(release)
    assert raised.value.code == "CG1_PRODUCTION_RELEASE_COMBAT_RECEIPT_INVALID"
    assert raised.value.status_code == 409


def test_execute_live_uses_release_combat_and_never_invokes_missing_collaborator(tmp_path):
    service = object.__new__(CharacterCreationExecutionService)
    receipt = _production_combat_receipt()
    release = {
        "factory_authoring": {"artifact": "factory"},
        "command5": {"artifact": "gm"},
        "consumer": {"artifact": "consumer"},
        "portable_audit": {"sha256": "portable"},
        "clean_import": {"verified": True},
        "registration": None,
        "gm_export": None,
        "production_artifact_identity": "release",
        "combat_readiness": receipt,
        "completion_proof": {"combat": deepcopy(receipt)},
    }
    events = []

    class Stage1:
        def validate_response(self, *_args, **_kwargs):
            return {"attempt_id": "stage1-attempt"}

        def approve_and_commit(self, *_args, **_kwargs):
            return {"commit_id": "stage1-commit"}

    class Release:
        def compile(self, *_args, **_kwargs):
            events.append("production_release")
            return deepcopy(release)

    production = Release()
    services = {
        "stage1": Stage1(),
        "stage2": object(),
        "character_sheets": object(),
        "production_release": production,
        "combat_readiness": None,
    }
    service.db = SimpleNamespace(
        settings=SimpleNamespace(
            data_dir=tmp_path / "data",
            logs_dir=tmp_path / "logs",
        ),
    )
    service.owner_principal = "owner"
    service._require_frozen_choice_snapshot = lambda _run: {"snapshot_sha256": "s" * 64}
    service._plan_with_accepted_final_target = lambda _run, value, _accepted: value
    service._execution_descriptive_fields = lambda _run, value: value
    service._materialize_descriptive_fields = lambda *_args, **_kwargs: None
    service._materialize_delegated_final_grant_plan = lambda *_args, **_kwargs: None
    service._stage1_prior_attempt_id = lambda *_args, **_kwargs: None
    service._materialize_method_hard_lock = lambda *_args, **_kwargs: {"method": "locked"}
    service._delegated_path_ids_from_canonical_intent = lambda _value: []
    service._issue_initial_catalog_provenance = lambda *_args, **_kwargs: {"issued": True}
    service._build_character_creation_projection = lambda *_args, **_kwargs: {"projection": True}
    service._stage2_commit = lambda *_args, **_kwargs: (
        {"validation": True},
        {"commit": True},
        {"projection": True},
    )
    service._invoke = lambda _obj, names, *_args, **_kwargs: (
        events.append(names[0]) or {"surface": names[0]}
    )
    service._live_pipeline = lambda: services
    run = {
        "run_id": "cg1.test.production-combat",
        "project_id": "project.production-combat",
        "request": {
            "stage1_prompt": {"prompt_id": "prompt"},
        },
        "final_plan": {},
        "transport": {},
    }
    plan = {
        "stage1_response": {"path": "PATH"},
        "stage2_proposal": {},
        "output_profile": {"combat_ready": True},
    }

    outputs = service._execute_live(run, plan)

    assert outputs["combat"] == receipt
    assert "production_release" in events
    assert "compile" not in events


def test_stage1_first_compile_uses_release_combat_and_never_invokes_missing_collaborator(
    monkeypatch,
    tmp_path,
):
    service = object.__new__(CharacterCreationExecutionService)
    # The stage1-first adapter captures the GM candidate through the same
    # collaborator as the central compiler; this test only pins release combat.
    service.candidate_gm = SimpleNamespace(capture=lambda **_kwargs: None)
    receipt = _production_combat_receipt()
    release = {
        "factory_authoring": {"artifact": "factory"},
        "command5": {"artifact": "gm"},
        "consumer": {"artifact": "consumer"},
        "portable_audit": {"sha256": "portable"},
        "clean_import": {"verified": True},
        "production_artifact_identity": "release",
        "combat_readiness": receipt,
        "completion_proof": {"combat": deepcopy(receipt)},
    }
    events = []

    class ScratchDatabase:
        def __init__(self, settings):
            self.settings = settings

        def migrate(self):
            events.append("scratch_migrate")

    class Stage1:
        def validate_response(self, *_args, **_kwargs):
            return {"attempt_id": "stage1-attempt", "validation": {"valid": True}}

        def approve_and_commit(self, *_args, **_kwargs):
            return {"commit_id": "stage1-commit"}

    class Release:
        def compile(self, *_args, **_kwargs):
            events.append("production_release")
            return deepcopy(release)

        def _stable(self, value):
            return value

    services = {
        "stage1": Stage1(),
        "stage2": object(),
        "character_sheets": object(),
        "production_release": Release(),
        "combat_readiness": None,
    }
    service.db = SimpleNamespace(
        settings=SimpleNamespace(
            root_dir=tmp_path,
            db_path=tmp_path / "foundry.sqlite3",
            factory_zip=None,
            fixture_path=None,
        ),
    )
    service.owner_principal = "owner"
    service._require_frozen_choice_snapshot = lambda _run: {"snapshot_sha256": "s" * 64}
    service._execution_descriptive_fields = lambda _run, value: value
    service._snapshot_data = lambda target, **_kwargs: target.mkdir(parents=True, exist_ok=True)
    service._snapshot_external_security = lambda _target: None
    service._prepare_scratch_compilation_run = lambda *_args, **_kwargs: events.append("scratch_prepare")
    service._scratch_services = lambda _scratch_db: services
    service._materialize_descriptive_fields = lambda *_args, **_kwargs: None
    service._materialize_method_hard_lock = lambda *_args, **_kwargs: {"method": "locked"}
    service._stage1_prior_attempt_id = lambda *_args, **_kwargs: None
    service._delegated_path_ids_from_canonical_intent = lambda _value: []
    service._stage2_commit = lambda *_args, **_kwargs: (
        {"validation": True},
        {"commit": True},
        {"projection": True},
    )
    service._invoke = lambda _obj, names, *_args, **_kwargs: (
        events.append(names[0]) or {"surface": names[0]}
    )
    service._identity_payload = lambda value, *, _surface: value
    monkeypatch.setattr(
        creation_service,
        "Settings",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        creation_service,
        "Database",
        ScratchDatabase,
    )
    run = {
        "run_id": "cg1.test.stage1-production-combat",
        "project_id": "project.stage1-production-combat",
        "request": {
            "stage1_prompt": {"prompt_id": "prompt"},
        },
    }
    plan = {
        "stage1_response": {"path": "PATH"},
        "stage2_proposal": {},
        "canonical_selection_intent": {},
        "output_profile": {"combat_ready": True},
    }

    result = compile_once_stage1_first(service, run, plan, 1)

    assert result["artifacts"]["combat"] == receipt
    assert "production_release" in events
    assert "compile" not in events


def test_complete_request_seals_target_and_hash_binds_true_vs_false(monkeypatch):
    service = _request_service(monkeypatch)
    disabled = service._complete_request(
        "project.combat-target",
        idempotency_key="combat-target-disabled",
        combat_ready=False,
    )
    enabled = service._complete_request(
        "project.combat-target",
        idempotency_key="combat-target-enabled",
        combat_ready=True,
    )

    for request, expected in ((disabled, False), (enabled, True)):
        target = request["server_owned_authority"]["output_profile"]
        assert target == {
            "schema": SERVER_OUTPUT_PROFILE_SCHEMA,
            "profile": SERVER_OUTPUT_PROFILE_NAME,
            "combat_ready": expected,
            "binding": {
                "project_id": "project.combat-target",
                "project_revision": 4,
                "content_lock_hash": "c" * 64,
                "request_sha256": request["request_sha256"],
            },
        }
        assert request["server_owned_authority"]["output_profile_target_required"] is True
        assert service.request_payload_sha256(request) == request["request_sha256"]
    assert disabled["request_sha256"] != enabled["request_sha256"]


def test_preferred_response_cannot_author_output_profile():
    plan = {
        "schema": RESPONSE_SCHEMA,
        "request_sha256": "a" * 64,
        "selection_intent": {"by_slot": {}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
        },
        "bounded_choices": {},
        "owner_descriptive_fields": {"identity": {"name": "Test"}, "concept": "Concept"},
        "output_profile": {"combat_ready": True, "profile": SERVER_OUTPUT_PROFILE_NAME},
    }
    with pytest.raises(FoundryError) as raised:
        CharacterCreationExecutionService._parse_plan(
            creation_service.canonical_json(plan),
            expected_request_sha256="a" * 64,
        )
    assert raised.value.code == "CG1_PREFERRED_RESPONSE_SHAPE_INVALID"


def test_normalization_uses_exact_server_target_and_rejects_tamper(monkeypatch):
    service = _request_service(monkeypatch)
    request = service._complete_request(
        "project.combat-normalize",
        idempotency_key="combat-normalize",
        combat_ready=True,
    )
    run = {
        "run_id": "cg1.test.combat-normalize",
        "project_id": "project.combat-normalize",
        "starting_revision": 4,
        "request": request,
    }
    project = {
        "project_id": run["project_id"],
        "revision": 4,
        "content_lock": {"lock_hash": "c" * 64},
        "user_locks": [{"field": "target_cl", "value": 1}],
    }
    service._project = lambda _project_id: deepcopy(project)
    intent = SimpleNamespace(intent_hash="e" * 64, as_dict=lambda: {"target_cl": 1})
    monkeypatch.setattr(creation_service, "normalize_selection_intent", lambda *args, **kwargs: intent)
    monkeypatch.setattr(
        creation_service,
        "inject_canonical_intent",
        lambda plan, _intent, *, target_cl: deepcopy(plan),
    )
    service._canonicalize_frozen_background_intent = lambda value, _envelope: value
    # This unit isolates output-profile authority using a synthetic intent;
    # manual materialization has its own real-intent boundary tests.
    service._server_manual_collection_intent = lambda _run, _project, value, **kwargs: value
    service._server_materialized_stage2_proposal = lambda *args, **kwargs: None

    normalized, _intent, _stage2 = service._normalize_and_materialize_response(
        run,
        {"schema": RESPONSE_SCHEMA, "stage1_response": {}},
    )
    assert normalized["output_profile"] == {
        "combat_ready": True,
        "profile": SERVER_OUTPUT_PROFILE_NAME,
    }
    assert normalized["output_profile"]["combat_ready"] is True

    tampered = deepcopy(run)
    tampered["request"]["server_owned_authority"]["output_profile"]["combat_ready"] = False
    with pytest.raises(FoundryError) as raised:
        service._normalize_and_materialize_response(
            tampered,
            {"schema": RESPONSE_SCHEMA, "stage1_response": {}},
        )
    assert raised.value.code == "CG1_OUTPUT_PROFILE_AUTHORITY_INVALID"


def test_missing_new_target_is_not_treated_as_legacy(monkeypatch):
    service = _request_service(monkeypatch)
    request = service._complete_request(
        "project.combat-required",
        idempotency_key="combat-required",
        combat_ready=True,
    )
    request["server_owned_authority"].pop("output_profile")
    run = {
        "run_id": "cg1.test.combat-required",
        "project_id": "project.combat-required",
        "starting_revision": 4,
        "request": request,
    }
    with pytest.raises(FoundryError) as raised:
        CharacterCreationExecutionService._validated_server_owned_output_profile_target(run)
    assert raised.value.code == "CG1_OUTPUT_PROFILE_AUTHORITY_INVALID"


@pytest.mark.parametrize("controller_route", [None, "LEGACY_FULL_PLAN", "DETERMINISTIC_CREATIVE_CONTROLLER"])
def test_create_new_request_from_edit_passes_parent_target(monkeypatch, controller_route):
    service = object.__new__(CharacterCreationExecutionService)
    source_request = {
        **({"controller_route": controller_route} if controller_route is not None else {}),
        "project_id": "project.edit-target",
        "project_revision": 3,
        "content_lock_hash": "c" * 64,
        "server_owned_authority": {
            "output_profile_target_required": True,
            "output_profile": {
                "schema": SERVER_OUTPUT_PROFILE_SCHEMA,
                "profile": SERVER_OUTPUT_PROFILE_NAME,
                "combat_ready": True,
                "binding": {
                    "project_id": "project.edit-target",
                    "project_revision": 3,
                    "content_lock_hash": "c" * 64,
                    "request_sha256": "a" * 64,
                },
            },
        },
    }
    source_request["request_sha256"] = CharacterCreationExecutionService.request_payload_sha256(source_request)
    source_request["server_owned_authority"]["output_profile"]["binding"]["request_sha256"] = source_request["request_sha256"]
    row = {
        "status": "PREPARED",
        "payload_json": "{\"owner_notes\":\"revise\"}",
        "payload_sha256": creation_service.sha256_json({"owner_notes": "revise"}),
        "source_run_id": "cg1.parent",
    }

    class _Result:
        def fetchone(self):
            return row

    class _Context:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _sql, _params=()):
            return _Result()

    class _DB:
        def connection(self):
            return _Context()

        def transaction(self):
            return _Context()

    service.db = _DB()
    source = {
        "run_id": "cg1.parent",
        "project_id": "project.edit-target",
        "starting_revision": 3,
        "status": "READY_FOR_REVIEW",
        "execution_mode": "MANUAL_CHAT",
        "idempotency_key": "parent-key",
        "request": source_request,
        "response": {},
        "blockers": [],
        "warnings": [],
    }
    child = {"run_id": "cg1.child"}
    returned = {"run_id": "cg1.child", "request": {}}
    service.get = lambda run_id: source if run_id == "cg1.parent" else returned
    service._revision = lambda _project_id: 4
    service._content_lock_hash = lambda _project_id: "d" * 64
    captured = {}

    def start(*args, **kwargs):
        captured.update(kwargs)
        return child

    service.start = start
    service._append_attempt = lambda *args, **kwargs: None
    service._latest_attempt_id = lambda _run_id: None

    result = service.create_new_request_from_edit("edit-target")
    assert result == returned
    assert captured["combat_ready"] is True
    assert captured["controller_route"] == (controller_route or "LEGACY_FULL_PLAN")
