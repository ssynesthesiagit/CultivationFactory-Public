"""Public-safe title authority regressions for delegated character creation."""

from __future__ import annotations

from copy import deepcopy
import io
import json
import zipfile

import pytest
from jsonschema import Draft202012Validator

import character_creation.delegated_choice_authority as delegated_authority
import character_creation.compiler_selection_authority as compiler_authority
import character_creation.response_materialization as response_materialization
from app.core import FoundryError, sha256_json
from character_creation.response_materialization import normalize_selection_intent
from character_creation.service import CharacterCreationExecutionService, _provider_response_template


def _production_project(*, title_lock: str | None = None) -> dict:
    locks = [{"field": "target_cl", "value": 1}]
    if title_lock is not None:
        locks.append({"field": "character.identity.title", "value": title_lock})
    return {
        "project_id": "project.title-authority",
        "revision": 3,
        "content_lock": {"lock_hash": "l" * 64, "catalog_build_id": "catalog-test"},
        "user_locks": locks,
        "working_name": "Li Wei",
        "concept": "A resourceful survivor.",
    }


def _production_prompt() -> dict:
    return {
        "prompt_id": "stage1.title-authority",
        "prompt_sha256": "p" * 64,
        "envelope": {
            "schema_version": "TianxiaFoundry.Stage1Prompt.v1",
            "decision_slots": [
                {
                    "slot_id": "path_choice",
                    "choices": [
                        {"choice_id": "path.qi", "name": "Qi Cultivation", "selectable": True},
                    ],
                },
            ],
        },
    }


def _compiler_snapshot() -> compiler_authority.CompilerSelectionAuthoritySnapshot:
    return compiler_authority.CompilerSelectionAuthoritySnapshot(
        {
            "authority_sha256": "a" * 64,
            "content": {"content_lock_hash": "l" * 64},
            "path_choice": {},
        },
        _token=compiler_authority._SERVER_SNAPSHOT_TOKEN,
    )


def test_new_compiler_gated_envelope_seals_delegated_title(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        delegated_authority,
        "verify_compiler_selection_authority",
        lambda authority, *, expected_content_lock: authority,
    )
    envelope = delegated_authority.build_delegated_choice_envelope(
        _production_project(),
        _production_prompt(),
        execution_mode="MANUAL_CHAT",
        idempotency_key="title-authority-1",
        compiler_selection_authority=_compiler_snapshot(),
    )
    assert envelope is not None
    assert envelope["delegated_fields"]["identity.title"] == {
        "state": "delegated",
        "owner_value": None,
        "response_field": "owner_descriptive_fields.identity.title",
        "required_in_response": True,
        "nonblank_required": True,
        "max_length": 120,
        "positive_delegation": True,
        "requirement_schema": "TianxiaFoundry.DelegatedTitleRequirement.v1",
        "semantic_requirement": "The response must propose one concise nonblank character title for owner review.",
    }
    assert envelope["delegated_title_contract"]["field"] == "owner_descriptive_fields.identity.title"
    assert envelope["delegated_title_contract"]["required"] is True


def test_existing_title_lock_is_exactly_sealed(monkeypatch: pytest.MonkeyPatch) -> None:
    # This uses the server-created marker directly only to keep the test
    # independent of a vendor fixture; the lock value still comes solely from
    # the synthetic project, never from response prose.
    monkeypatch.setattr(
        delegated_authority,
        "verify_compiler_selection_authority",
        lambda authority, *, expected_content_lock: authority,
    )
    envelope = delegated_authority.build_delegated_choice_envelope(
        _production_project(title_lock="Furnace-Bound Alchemist"),
        _production_prompt(),
        execution_mode="MANUAL_CHAT",
        idempotency_key="title-authority-locked",
        compiler_selection_authority=_compiler_snapshot(),
    )
    assert envelope["delegated_fields"]["identity.title"]["state"] == "owner_locked"
    assert envelope["delegated_title_contract"]["owner_locked_value"] == "Furnace-Bound Alchemist"


def test_overlong_owner_title_lock_is_rejected_before_schema_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        delegated_authority,
        "verify_compiler_selection_authority",
        lambda authority, *, expected_content_lock: authority,
    )
    with pytest.raises(FoundryError) as raised:
        delegated_authority.build_delegated_choice_envelope(
            _production_project(title_lock="T" * 121),
            _production_prompt(),
            execution_mode="MANUAL_CHAT",
            idempotency_key="title-authority-overlong",
            compiler_selection_authority=_compiler_snapshot(),
        )

    assert raised.value.code == "CG1_DELEGATED_TITLE_AUTHORITY_INVALID"


def test_canonical_intent_preserves_title_without_inventing_one() -> None:
    plan = {
        "selection_intent": {"by_slot": {}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
            "insight_occurrences": [],
        },
        "bounded_choices": {},
        "owner_descriptive_fields": {
            "identity": {"name": "Li Wei", "title": "Furnace-Bound Alchemist"},
            "concept": "A resourceful survivor.",
        },
    }
    intent = normalize_selection_intent(
        plan,
        request_sha256="b" * 64,
        delegated_envelope={},
        project={"project_id": "p", "revision": 1, "content_lock": {}},
        target_cl=1,
    )
    assert intent.as_dict()["owner_descriptive_fields"]["identity"] == {
        "name": "Li Wei",
        "title": "Furnace-Bound Alchemist",
    }
    legacy = deepcopy(plan)
    legacy["owner_descriptive_fields"]["identity"].pop("title")
    old_intent = normalize_selection_intent(
        legacy,
        request_sha256="c" * 64,
        delegated_envelope={},
        project={"project_id": "p", "revision": 1, "content_lock": {}},
        target_cl=1,
    )
    assert old_intent.as_dict()["owner_descriptive_fields"] == {
        "identity": {"name": "Li Wei"},
        "concept": "A resourceful survivor.",
    }


def test_provider_template_exposes_only_sealed_title_slot() -> None:
    template = _provider_response_template(
        request_sha256="d" * 64,
        descriptive_context={
            "identity.name": {"state": "owner_locked", "owner_locked_value": "Li Wei"},
            "identity.title": {"state": "delegated", "owner_locked_value": None},
            "concept": {"state": "owner_locked", "owner_locked_value": "A resourceful survivor."},
        },
        presented_choices_by_slot={},
        ordinary_shortlist={},
        target_cl=1,
    )
    assert template["owner_descriptive_fields"]["identity"] == {
        "name": "Li Wei",
        "title": None,
    }


def _sealed_title_validation_case(
    *,
    title_lock: str | None = None,
    compiler_gated: bool = False,
) -> tuple[dict, dict, dict]:
    project = _production_project(title_lock=title_lock)
    prompt = {
        "prompt_id": "stage1.title-validation",
        "prompt_sha256": "q" * 64,
        "envelope": {
            "decision_slots": [
                {
                    "slot_id": "path_choice",
                    "choices": [
                        {
                            "choice_id": "tianxia.path.qi_cultivation",
                            "name": "Qi Cultivation",
                            "selectable": True,
                        },
                    ],
                },
                {
                    "slot_id": "method_choice",
                    "choices": [
                        {
                            "choice_id": "method.title-test",
                            "name": "Title Test Method",
                            "related_choice_ids": ["tianxia.path.qi_cultivation"],
                            "initial_creation_selectable": True,
                        },
                    ],
                },
            ],
        },
    }
    compiler_snapshot = _compiler_snapshot() if compiler_gated else None
    if compiler_snapshot is not None:
        compiler_snapshot["method_choice"] = {
            "records": {
                "method.title-test": {
                    "choice_id": "method.title-test",
                    "canonical_name": "Title Test Method",
                    "selectable": True,
                },
            },
        }
    envelope = delegated_authority.build_delegated_choice_envelope(
        project,
        prompt,
        execution_mode="MANUAL_CHAT",
        idempotency_key="title-validation-run",
        compiler_selection_authority=compiler_snapshot,
    )
    assert envelope is not None
    owner_title = title_lock.strip() if isinstance(title_lock, str) and title_lock.strip() else None
    envelope["delegated_fields"]["identity.title"] = {
        "state": "owner_locked" if owner_title else "delegated",
        "owner_value": owner_title,
        "response_field": "owner_descriptive_fields.identity.title",
        "required_in_response": True,
        "nonblank_required": True,
        "max_length": 120,
        "positive_delegation": not bool(owner_title),
        "requirement_schema": "TianxiaFoundry.DelegatedTitleRequirement.v1",
        "semantic_requirement": "The response must propose one concise nonblank character title for owner review.",
    }
    envelope["delegated_title_contract"] = {
        "schema": "TianxiaFoundry.DelegatedTitleRequirement.v1",
        "field": "owner_descriptive_fields.identity.title",
        "state": "owner_locked" if owner_title else "delegated",
        "required": True,
        "nonblank": True,
        "max_length": 120,
        "positive_delegation": not bool(owner_title),
        "owner_locked_value": owner_title,
        "instruction": "The response must propose one concise nonblank character title for owner review.",
    }
    envelope["envelope_sha256"] = sha256_json({
        key: value for key, value in envelope.items() if key != "envelope_sha256"
    })
    run = {
        "project_id": project["project_id"],
        "starting_revision": project["revision"],
        "execution_mode": "MANUAL_CHAT",
        "idempotency_key": "title-validation-run",
        "request": {"delegated_choice_envelope": envelope},
    }
    if compiler_gated:
        run["request"].update({
            "request_sha256": "r" * 64,
            "project_id": project["project_id"],
            "project_revision": project["revision"],
            "content_lock_hash": project["content_lock"]["lock_hash"],
            "stage1_prompt": prompt,
        })
    plan = {
        "canonical_selection_intent": {},
        "owner_descriptive_fields": {
            "identity": {"name": "Li Wei"},
            "concept": "A resourceful survivor.",
        },
    }
    return project, run, plan


def _isolate_title_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        delegated_authority,
        "_validate_selected_slot_values",
        lambda *_args, **_kwargs: {
            "by_slot": {
                "path_choice": ["tianxia.path.qi_cultivation"],
                "method_choice": ["method.title-test"],
            },
            "sources_by_slot": {},
        },
    )
    monkeypatch.setattr(delegated_authority, "validate_delegated_target_cl", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(delegated_authority, "_validate_frozen_legality", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(delegated_authority, "_validate_path_subpath_bindings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(delegated_authority, "_validate_semantic_acquisition_intent", lambda *_args, **_kwargs: None)


@pytest.mark.parametrize("title", [None, "   "], ids=["missing", "blank"])
def test_delegated_plan_rejects_missing_or_blank_title(
    monkeypatch: pytest.MonkeyPatch,
    title: str | None,
) -> None:
    project, run, plan = _sealed_title_validation_case()
    if title is not None:
        plan["owner_descriptive_fields"]["identity"]["title"] = title
    _isolate_title_validator(monkeypatch)
    with pytest.raises(FoundryError) as raised:
        delegated_authority.validate_delegated_choice_plan(run, project, plan)
    assert raised.value.code == "CG1_DELEGATED_TITLE_REQUIRED"


def test_compiler_gated_plan_rejects_rehashed_envelope_with_both_title_halves_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        delegated_authority,
        "verify_compiler_selection_authority",
        lambda authority, *, expected_content_lock: authority,
    )
    project, run, plan = _sealed_title_validation_case(compiler_gated=True)
    envelope = run["request"]["delegated_choice_envelope"]
    envelope["delegated_fields"].pop("identity.title")
    envelope.pop("delegated_title_contract")
    envelope["envelope_sha256"] = sha256_json({
        key: value for key, value in envelope.items() if key != "envelope_sha256"
    })
    _isolate_title_validator(monkeypatch)

    with pytest.raises(FoundryError) as raised:
        delegated_authority.validate_delegated_choice_plan(run, project, plan)

    assert raised.value.code == "CG1_DELEGATED_TITLE_AUTHORITY_INVALID"


def test_delegated_plan_keeps_owner_locked_title_when_ai_changes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    # Owner rule 2026-10-10: owner-written wording wins (no blocker); the AI may only add to it.
    project, run, plan = _sealed_title_validation_case(title_lock="Owner Locked Title")
    plan["owner_descriptive_fields"]["identity"]["title"] = "Different Title"
    _isolate_title_validator(monkeypatch)
    final_plan = delegated_authority.validate_delegated_choice_plan(run, project, plan)
    resolved = repr(final_plan)
    assert "Owner Locked Title" in resolved and "Different Title" not in resolved


def test_server_materializes_evidence_bound_final_title_lock() -> None:
    calls: list[dict] = []

    class Store:
        def materialize_server_derived_user_lock(self, project_id, *, field, value, source, lock_id):
            calls.append({
                "project_id": project_id,
                "field": field,
                "value": value,
                "source": source,
                "lock_id": lock_id,
            })

    service = object.__new__(CharacterCreationExecutionService)
    service.projects = Store()
    # `_materialize_descriptive_fields` uses the service-owned store directly
    # only when the authority DB is the service DB.  A tiny in-memory test
    # double keeps this regression independent of the application database.
    service.db = service.projects
    run = {
        "run_id": "cg1.test.title-lock",
        "project_id": "project.title-authority",
        "request": {"request_sha256": "a" * 64},
        "response": {"response_sha256": "b" * 64},
    }
    plan = {
        "owner_descriptive_fields": {
            "identity": {"name": "Li Wei", "title": "Furnace-Bound Alchemist"},
            "concept": "A resourceful survivor.",
        },
    }
    service._materialize_descriptive_fields(run, plan, service.projects, phase="finalization")
    by_field = {call["field"]: call for call in calls}
    assert by_field["character.identity.final_title"]["value"] == {
        "value": "Furnace-Bound Alchemist",
        "binding": {
            "schema": "TianxiaFoundry.ServerDerivedDescriptiveFields.v1",
            "run_id": "cg1.test.title-lock",
            "project_id": "project.title-authority",
            "request_sha256": "a" * 64,
            "response_sha256": "b" * 64,
            "phase": "server-derived",
        },
    }


def test_active_preferred_response_schema_requires_delegated_title() -> None:
    title_contract = {
        "schema": "TianxiaFoundry.DelegatedTitleRequirement.v1",
        "field": "owner_descriptive_fields.identity.title",
        "state": "delegated",
        "required": True,
        "nonblank": True,
        "max_length": 120,
        "positive_delegation": True,
        "owner_locked_value": None,
    }
    envelope = {
        "allowed_choice_ids_by_slot": {},
        "choices_by_slot": {},
        "typed_choice_authority_by_slot": {},
        "frozen_owner_target_cl": {"value": 1},
        "delegated_name_contract": {
            "state": "owner_locked",
            "owner_locked_value": "Li Wei",
        },
        "delegated_title_contract": title_contract,
    }
    request = {
        "request_sha256": "e" * 64,
        "content_lock_hash": "l" * 64,
        "typed_choice_snapshot": {"snapshot_sha256": "t" * 64},
        "delegated_choice_envelope": envelope,
        "delegated_title_contract": title_contract,
        "required_components": [],
        "forbidden_planner_fields": [],
        "server_owned_authority": {},
        "bounded_choice_contract": {},
        "stage1_prompt": {
            "envelope": {
                "user_locks": [
                    {
                        "field": "character_sheet.ability_point_buy",
                        "value": {
                            "fixed_scores": {
                                "STR": 8,
                                "DEX": 8,
                                "CON": 8,
                                "INT": 8,
                                "WIS": 8,
                                "CHA": 8,
                            },
                            "auto_abilities": False,
                        },
                    },
                ],
            },
        },
    }
    run = {
        "project_id": "project.title-authority",
        "starting_revision": 3,
        "execution_mode": "STANDARD_API",
        "request": request,
    }
    service = object.__new__(CharacterCreationExecutionService)
    service.owner_principal = "title-test-owner"
    service.get = lambda _run_id: run
    service._locked_records_for_project_ids = lambda _project_id, _record_ids: {}
    package = service._complete_request_package("run.title-schema")
    with zipfile.ZipFile(io.BytesIO(package["payload"])) as archive:
        schema = json.loads(archive.read("RESPONSE_SCHEMA.json"))["preferred_response"]
    identity = schema["properties"]["owner_descriptive_fields"]["properties"]["identity"]
    assert "title" in identity["required"]
    assert identity["properties"]["title"]["minLength"] == 1
    assert identity["properties"]["title"]["maxLength"] == 120
    valid = {
        "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "request_sha256": "e" * 64,
        "selection_intent": {"by_slot": {}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
            "insight_occurrences": [],
        },
        "bounded_choices": {},
        "owner_descriptive_fields": {
            "identity": {"name": "Li Wei", "title": "Furnace-Bound Alchemist"},
        },
    }
    assert not list(Draft202012Validator(schema).iter_errors(valid))
    missing = deepcopy(valid)
    missing["owner_descriptive_fields"]["identity"].pop("title")
    assert list(Draft202012Validator(schema).iter_errors(missing))


def test_title_validation_rejects_blank_or_conflicting_values() -> None:
    # Exercise the strict descriptive projection helper used before any
    # persistence.  The active delegated validator performs the same checks
    # against the sealed title contract before mechanical materialization.
    assert not CharacterCreationExecutionService._has_canonical_descriptive_fields(
        {"identity": {"name": "Li Wei", "title": "   "}, "concept": "concept"}
    )
    with pytest.raises(FoundryError):
        response_materialization._descriptive_fields(
            {
                "owner_descriptive_fields": {"identity": {"name": "Li Wei", "title": "First"}},
                "descriptive_fields": {"identity": {"title": "Second"}},
            }
        )


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def execute(self, *args):
        self.calls.append(args)


class _RecordingDatabase:
    def __init__(self) -> None:
        self.connection = _RecordingConnection()

    def transaction(self):
        database = self

        class Transaction:
            def __enter__(self):
                return database.connection

            def __exit__(self, exc_type, exc, tb):
                return False

        return Transaction()


def _acceptance_service(
    *,
    proposed_title: object,
    title_lock: object | None = None,
    compiler_gated: bool = False,
):
    service = object.__new__(CharacterCreationExecutionService)
    database = _RecordingDatabase()
    owner_title = title_lock
    title_state = "owner_locked" if owner_title is not None else "delegated"
    title_authority = {
        "state": title_state,
        "owner_value": owner_title,
        "response_field": "owner_descriptive_fields.identity.title",
        "required_in_response": True,
        "nonblank_required": True,
        "max_length": 120,
        "requirement_schema": "TianxiaFoundry.DelegatedTitleRequirement.v1",
    }
    title_contract = {
        "schema": "TianxiaFoundry.DelegatedTitleRequirement.v1",
        "field": "owner_descriptive_fields.identity.title",
        "state": title_state,
        "required": True,
        "nonblank": True,
        "max_length": 120,
        "owner_locked_value": owner_title,
    }
    envelope = {
        "delegated_fields": {"identity.title": title_authority},
        "delegated_title_contract": title_contract,
    }
    if compiler_gated:
        envelope["compiler_selection_authority"] = {}
    run = {
        "run_id": "cg1.title-acceptance",
        "status": "READY_FOR_REVIEW",
        "owner_descriptive_fields": {
            "proposed": {
                "identity": {"name": "Li Wei", "title": proposed_title},
                "concept": "A resourceful survivor.",
            },
        },
        "request": {
            "delegated_choice_envelope": envelope,
        },
    }
    service.db = database
    service.get = lambda _run_id: run
    return service, database, run


def test_accept_descriptive_fields_preserves_valid_proposed_title_when_omitted() -> None:
    service, database, _run = _acceptance_service(proposed_title="  Furnace-Bound Alchemist  ")

    service.accept_descriptive_fields(
        "cg1.title-acceptance",
        name="Li Wei",
        concept="A resourceful survivor.",
    )

    persisted = json.loads(database.connection.calls[0][1][0])
    assert persisted["identity"]["title"] == "Furnace-Bound Alchemist"


def test_accept_descriptive_fields_refuses_while_the_run_is_being_finalized() -> None:
    # Owner 2026-09-27: a rename saved during auto-finalize was recorded on the run but never reached the character.
    service, database, _run = _acceptance_service(proposed_title="Furnace-Bound Alchemist")
    service._finalizing_run_id = "cg1.title-acceptance"

    with pytest.raises(FoundryError) as raised:
        service.accept_descriptive_fields("cg1.title-acceptance", name="Renamed", concept="A resourceful survivor.")

    assert raised.value.code == "CG1_DESCRIPTIVE_FIELDS_FINALIZING"
    assert database.connection.calls == []


def test_accept_descriptive_fields_rejects_compiler_gate_without_both_title_halves() -> None:
    service, database, run = _acceptance_service(
        proposed_title="Valid Title",
        compiler_gated=True,
    )
    envelope = run["request"]["delegated_choice_envelope"]
    envelope.pop("delegated_fields")
    envelope.pop("delegated_title_contract")

    with pytest.raises(FoundryError) as raised:
        service.accept_descriptive_fields(
            run["run_id"],
            name="Li Wei",
            concept="A resourceful survivor.",
        )

    assert raised.value.code == "CG1_DELEGATED_TITLE_AUTHORITY_INVALID"
    assert database.connection.calls == []


@pytest.mark.parametrize(
    "title,expected_code",
    [("   ", "CG1_DELEGATED_TITLE_REQUIRED"), ("T" * 121, "CG1_DELEGATED_TITLE_INVALID")],
    ids=["blank-owner-edit", "overlong-owner-edit"],
)
def test_accept_descriptive_fields_cannot_bypass_active_title_contract(
    title: str,
    expected_code: str,
) -> None:
    service, database, run = _acceptance_service(proposed_title="Valid Title")

    with pytest.raises(FoundryError) as raised:
        service.accept_descriptive_fields(
            run["run_id"],
            name="Li Wei",
            concept="A resourceful survivor.",
            title=title,
        )

    assert raised.value.code == expected_code
    assert database.connection.calls == []


def test_accept_descriptive_fields_preserves_owner_locked_title_exactly() -> None:
    service, database, run = _acceptance_service(
        proposed_title="Owner Title",
        title_lock="Owner Title",
    )

    # Owner rule 2026-10-10: a changed owner-locked title no longer blocks; the owner's exact title is saved.
    service.accept_descriptive_fields(
        run["run_id"],
        name="Li Wei",
        concept="A resourceful survivor.",
        title="Different Title",
    )

    written = repr(database.connection.calls)
    assert "Owner Title" in written and "Different Title" not in written
