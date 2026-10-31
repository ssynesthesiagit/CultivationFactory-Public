"""Focused integration checks for the sealed starting-proficiency contract."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from app.core import FoundryError
import character_creation.service as creation_service
import pytest
from character_creation.service import CharacterCreationExecutionService, _provider_response_template
from character_creation.starting_proficiency_authority import (
    CONTRACT_SCHEMA,
    build_starting_proficiency_choice_contract,
)


APP_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_ROOT = APP_ROOT / "non_sphere_authority" / "authority"
BACKGROUND_SOURCE_NAME = "Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md"


def _public_authority() -> tuple[dict, dict, str, dict]:
    paths_master = json.loads(
        (AUTHORITY_ROOT / "Tianxia_Path_Index_Master_P2A.json").read_text(encoding="utf-8")
    )
    path_profiles: dict[str, dict] = {}
    for row in paths_master["paths"]:
        index_path = AUTHORITY_ROOT / row["index_file"]
        profile = json.loads(index_path.read_text(encoding="utf-8"))
        path_profiles[profile["canonical_id"]] = profile
    background_rows = json.loads(
        (AUTHORITY_ROOT / "Background_Core_Authority_v1.json").read_text(encoding="utf-8")
    )["backgrounds"]
    backgrounds = {row["background_id"]: row for row in background_rows}
    source_path = AUTHORITY_ROOT / BACKGROUND_SOURCE_NAME
    source_text = source_path.read_text(encoding="utf-8")
    return (
        path_profiles,
        backgrounds,
        source_text,
        {
            "path": "09_RULES/Source_Text/" + BACKGROUND_SOURCE_NAME,
            "source_hash": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        },
    )


PATH_ID = "tianxia.path.qi_cultivation"
BACKGROUND_ID = "tianxia.background.abandoned_orphan"
ORIGIN_ID = "tianxia.origin_insight.born_under_suspicion"


def _choices() -> tuple[dict, dict]:
    return (
        {
            "path_choice": {PATH_ID: {"choice_id": PATH_ID, "name": "Qi Cultivation"}},
            "background_choice": {
                BACKGROUND_ID: {"choice_id": BACKGROUND_ID, "name": "Abandoned Orphan"}
            },
            "origin_insight_choice": {
                ORIGIN_ID: {
                    "choice_id": ORIGIN_ID,
                    "name": "Born Under Suspicion",
                    "summary": (
                        "You gain proficiency in Deception or Insight. "
                        "If you already have proficiency in the chosen skill, gain expertise in it."
                    ),
                    "source_evidence": [{
                        "source_path": "rules/origins/born-under-suspicion.md",
                        "source_hash": "a" * 64,
                        "source_anchor": "heading:born-under-suspicion",
                    }],
                }
            },
        },
        {
            "path_choice": [PATH_ID],
            "background_choice": [BACKGROUND_ID],
            "origin_insight_choice": [ORIGIN_ID],
        },
    )


def _contract() -> dict:
    paths, backgrounds, source_text, source = _public_authority()
    choices, allowed = _choices()
    return build_starting_proficiency_choice_contract(
        path_profiles=paths,
        backgrounds=backgrounds,
        choices_by_slot=choices,
        allowed_choice_ids_by_slot=allowed,
        campaign_language_source_text=source_text,
        campaign_language_source=source,
    )


def _starting_preflight_case() -> tuple[dict, dict, dict]:
    contract = _contract()
    selected = {
        "path_choice": [PATH_ID],
        "background_choice": [BACKGROUND_ID],
        "origin_insight_choice": [ORIGIN_ID],
    }
    bounded = {
        "path_skill_choices_by_path_id": {PATH_ID: ["Arcana", "Medicine"]},
        "background_language_choices_by_background_id": {BACKGROUND_ID: ["Classical"]},
        "origin_skill_choices_by_origin_id": {ORIGIN_ID: ["Deception"]},
    }
    return contract, selected, bounded


def _starting_preflight_run_plan(contract: dict, selected: dict, bounded: dict) -> tuple[dict, dict]:
    request = {
        "bounded_choice_contract": {
            "fields": {
                field: {
                    "type": "starting_proficiency_choice_map",
                    "contract_sha256": contract["contract_sha256"],
                    "selection_map": field,
                }
                for field in contract["fields"]
            },
            "starting_proficiency_choice_contract": deepcopy(contract),
        },
    }
    run = {
        "run_id": "cg1.test.starting-proficiency",
        "project_id": "project.starting-proficiency",
        "starting_revision": 7,
        "request": {
            **request,
            "content_lock_hash": "d" * 64,
            "request_sha256": "e" * 64,
        },
        "response": {"response_sha256": "f" * 64},
    }
    plan = {
        "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
        "selection_intent": {
            "by_slot": {
                **deepcopy(selected),
                "advancement_skeleton": [],
            },
        },
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
        },
        "bounded_choices": deepcopy(bounded),
    }
    return run, plan


def _stub_preflight_provider_payload(monkeypatch):
    calls: list[tuple[tuple, dict]] = []

    def fake_provider_payload(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "sphere_route_modules": [],
            "response_contract": {
                "expected_acquisition_counts": {
                    "sphere_free_talent_pairs": 0,
                    "ordinary_talent_ids": 0,
                },
                "presented_legal_first_cycle_pairs": [],
                "presented_legal_ordinary_talent_ids_by_cl": {},
            },
        }

    monkeypatch.setattr(creation_service, "_provider_payload", fake_provider_payload)
    monkeypatch.setattr(
        CharacterCreationExecutionService,
        "_validated_repaired_ordinary_context",
        lambda *args, **kwargs: None,
    )
    return calls


def test_contract_and_provider_schema_are_exact_and_fixed_grants_are_not_response_fields():
    contract = _contract()
    assert contract["schema"] == CONTRACT_SCHEMA
    assert contract["contract_sha256"] == _contract()["contract_sha256"]

    properties, required = creation_service._starting_proficiency_schema_properties(contract)
    assert required == [
        "path_skill_choices_by_path_id",
        "origin_skill_choices_by_origin_id",
        "background_language_choices_by_background_id",
    ]

    path_schema = properties["path_skill_choices_by_path_id"]
    path_value_schema = path_schema["properties"][PATH_ID]
    assert path_schema["additionalProperties"] is False
    assert path_value_schema["minItems"] == path_value_schema["maxItems"] == 2
    assert path_value_schema["items"]["enum"] == [
        "Arcana", "History", "Insight", "Investigation", "Medicine",
        "Nature", "Perception", "Persuasion", "Religion",
    ]

    origin_value_schema = properties["origin_skill_choices_by_origin_id"]["properties"][ORIGIN_ID]
    assert origin_value_schema["minItems"] == origin_value_schema["maxItems"] == 1
    assert origin_value_schema["items"]["enum"] == ["Deception", "Insight"]

    background_value_schema = properties["background_language_choices_by_background_id"]["properties"][BACKGROUND_ID]
    assert background_value_schema["minItems"] == background_value_schema["maxItems"] == 1
    assert background_value_schema["items"]["enum"] == [
        "Classical", "Trade Pidgin", "gang cant", "military signs",
        "ancestral liturgical language", "regional ritual language",
    ]
    assert all("fixed_skill_names" not in value for value in properties.values())

    template = _provider_response_template(
        request_sha256="b" * 64,
        descriptive_context={},
        presented_choices_by_slot={},
        ordinary_shortlist={},
        target_cl=1,
        bounded_choice_fields=required,
        owner_locks={},
    )
    assert set(template["bounded_choices"]) == set(required)
    assert all(template["bounded_choices"][field] == {} for field in required)


def test_request_integration_seals_contract_and_hash_binds_it_without_provider(monkeypatch):
    path_map, background_map, source_text, source = _public_authority()
    choices, allowed = _choices()

    class Authority:
        path_profiles = path_map
        backgrounds = background_map
        authority_root = AUTHORITY_ROOT
        root = APP_ROOT
        identity = {"files": {BACKGROUND_SOURCE_NAME: {
            "sha256": source["source_hash"],
        }}}

        @staticmethod
        def method_catalog(*, initial_creation=False):
            return {"records": {}}

        @staticmethod
        def foundation_catalog():
            return {"orthodox": {}}

    delegated = {
        "choices_by_slot": choices,
        "allowed_choice_ids_by_slot": allowed,
        "typed_choice_authority_by_slot": {"background_choice": {}},
        "advancement_choice_milestones": [],
        "path_progression_choices": [],
        "envelope_sha256": "c" * 64,
    }
    monkeypatch.setattr(creation_service, "NonSphereAuthorityService", lambda _db: Authority())
    monkeypatch.setattr(creation_service, "build_compiler_selection_authority", lambda *args, **kwargs: {})
    monkeypatch.setattr(creation_service, "build_delegated_choice_envelope", lambda *args, **kwargs: deepcopy(delegated))
    monkeypatch.setattr(creation_service, "_bind_path_feature_ability_change_rules", lambda *args, **kwargs: None)

    service = object.__new__(CharacterCreationExecutionService)
    service.db = SimpleNamespace(settings=SimpleNamespace(vendor_dir=APP_ROOT))
    service.stage1 = SimpleNamespace(generate_prompt=lambda _project_id: {"envelope": {"user_locks": []}})
    service.projects = SimpleNamespace()
    # A real project carries the owner's immutable target CL lock (885d87ea).
    service._project = lambda _project_id: {
        "project_id": "project.starting-choice",
        "content_lock": {},
        "user_locks": [{"field": "target_cl", "value": 1}],
    }
    service._revision = lambda _project_id: 4
    service._content_lock_hash = lambda _project_id: "d" * 64
    service._choice_snapshot = lambda _project_id: {"snapshot_sha256": "e" * 64}

    request = service._complete_request("project.starting-choice", idempotency_key="starting-choice")
    bounded = request["bounded_choice_contract"]
    sealed = bounded["starting_proficiency_choice_contract"]
    assert sealed["schema"] == CONTRACT_SCHEMA
    assert set(sealed["fields"]) == {
        "path_skill_choices_by_path_id",
        "origin_skill_choices_by_origin_id",
        "background_language_choices_by_background_id",
    }
    assert {
        field: bounded["fields"][field]["contract_sha256"]
        for field in sealed["fields"]
    } == {
        field: sealed["contract_sha256"]
        for field in sealed["fields"]
    }

    original_hash = request["request_sha256"]
    altered = deepcopy(request)
    altered["bounded_choice_contract"]["starting_proficiency_choice_contract"]["policy"][
        "language_registry_complete"
    ] = True
    assert CharacterCreationExecutionService.request_payload_sha256(altered) != original_hash

    provider_payload = creation_service._provider_payload(
        {"request": request},
        cue_limit=0,
        display_limit=0,
    )
    contract_ref = provider_payload["response_contract"][
        "starting_proficiency_choice_contract_ref"
    ]
    assert contract_ref == {
        "schema": CONTRACT_SCHEMA,
        "contract_sha256": sealed["contract_sha256"],
        "advertised_fields": sorted(sealed["fields"]),
    }
    assert any(
        "starting-proficiency map" in instruction
        for instruction in provider_payload["instructions"]
    )

    # The request-generation path never touches the provider object; the
    # service instance intentionally has no provider at all.
    assert not hasattr(service, "provider")


def test_complete_request_package_emits_closed_starting_maps():
    contract = _contract()
    fields = {
        field: {
            "type": "starting_proficiency_choice_map",
            "contract_sha256": contract["contract_sha256"],
            "selection_map": field,
        }
        for field in contract["fields"]
    }
    request = {
        "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
        "project_id": "project.starting-schema",
        "project_revision": 1,
        "request_sha256": "f" * 64,
        "content_lock_hash": "l" * 64,
        "typed_choice_snapshot": {"snapshot_sha256": "t" * 64},
        "required_components": sorted(creation_service.PREFERRED_RESPONSE_KEYS),
        "forbidden_planner_fields": [],
        "server_owned_authority": {
            "manual_collection": {
                "authority_version": "server_owned_pre_provider.v2",
                "policy_id": "cg1.manual.collection.v1",
                "nonce": "n" * 40,
                "seed": "cg1.manual.collection.secret",
                "roll": {"schema": "TianxiaFoundry.ManualCollectionRoll.v1", "cl": 1, "faces": [1], "total": 1},
            },
        },
        "bounded_choice_contract": {
            "schema": "TianxiaFoundry.BoundedChoiceContract.v1",
            "fields": fields,
            "starting_proficiency_choice_contract": contract,
        },
        "delegated_choice_envelope": {
            "frozen_owner_target_cl": {"value": 1},
            "allowed_choice_ids_by_slot": {},
            "choices_by_slot": {},
            "typed_choice_authority_by_slot": {},
            "advancement_choice_milestones": [],
            "path_progression_choices": [],
        },
        "stage1_prompt": {"envelope": {"user_locks": []}},
    }
    run = {
        "project_id": "project.starting-schema",
        "starting_revision": 1,
        "execution_mode": "MANUAL_CHAT",
        "request": request,
    }
    service = object.__new__(CharacterCreationExecutionService)
    service.owner_principal = "starting-schema-test"
    service.get = lambda _run_id: run
    service._locked_records_for_project_ids = lambda _project_id, _record_ids: {}
    package = service._complete_request_package("run.starting-schema")
    with zipfile.ZipFile(io.BytesIO(package["payload"])) as archive:
        complete_request_bytes = archive.read("COMPLETE_REQUEST.json")
        complete_request = json.loads(complete_request_bytes)
        binding = json.loads(archive.read("BINDING.json"))
        response_schema_bytes = archive.read("RESPONSE_SCHEMA.json")
        response_schema_document = json.loads(response_schema_bytes)
        schema = response_schema_document["preferred_response"]
    assert complete_request["request_sha256"] == request["request_sha256"]
    assert binding["request_sha256"] == request["request_sha256"]
    assert "manual_collection" not in (complete_request.get("server_owned_authority") or {})
    assert "manual_collection" not in (response_schema_document.get("server_owned") or {})
    assert b"n" * 40 not in complete_request_bytes
    assert b"cg1.manual.collection.secret" not in complete_request_bytes
    assert b"n" * 40 not in response_schema_bytes
    assert b"cg1.manual.collection.secret" not in response_schema_bytes
    bounded_schema = schema["properties"]["bounded_choices"]
    assert set(bounded_schema["required"]) == set(fields)
    assert bounded_schema["additionalProperties"] is False
    for field in fields:
        field_schema = bounded_schema["properties"][field]
        assert field_schema["additionalProperties"] is False


def test_preferred_preflight_validates_starting_maps_before_provider_work(monkeypatch):
    contract, selected, bounded = _starting_preflight_case()
    run, plan = _starting_preflight_run_plan(contract, selected, bounded)
    calls = _stub_preflight_provider_payload(monkeypatch)

    CharacterCreationExecutionService._validate_preferred_bounded_fields(run, plan)

    assert len(calls) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda selected, bounded: bounded["path_skill_choices_by_path_id"].pop(PATH_ID),
        lambda selected, bounded: bounded["path_skill_choices_by_path_id"].update(
            {"path.unselected": ["Arcana", "Medicine"]}
        ),
        lambda selected, bounded: bounded["path_skill_choices_by_path_id"].update(
            {PATH_ID: ["Arcana", "Arcana"]}
        ),
        lambda selected, bounded: bounded["path_skill_choices_by_path_id"].update(
            {PATH_ID: ["Arcana", "Stealth"]}
        ),
        lambda selected, bounded: selected.update({"path_choice": PATH_ID}),
        lambda selected, bounded: selected.update({"path_choice": ["path.unselected"]}),
    ],
)
def test_preferred_preflight_translates_invalid_starting_maps_to_bounded_error(
    monkeypatch,
    mutation,
):
    contract, selected, bounded = _starting_preflight_case()
    mutation(selected, bounded)
    run, plan = _starting_preflight_run_plan(contract, selected, bounded)
    calls = _stub_preflight_provider_payload(monkeypatch)

    with pytest.raises(FoundryError) as raised:
        CharacterCreationExecutionService._validate_preferred_bounded_fields(run, plan)

    error = raised.value
    assert error.code == "CG1_STARTING_PROFICIENCY_CHOICE_INVALID"
    assert error.status_code == 422
    assert set(error.details) == {
        "schema",
        "contract_sha256",
        "validation_sha256",
        "blockers",
    }
    assert error.details["blockers"]
    rendered = json.dumps(error.details, ensure_ascii=False)
    assert "Arcana" not in rendered
    assert "Medicine" not in rendered
    assert "Classical" not in rendered
    assert len(calls) == 0


def test_preferred_preflight_rejects_omitted_contract_maps_without_raw_values(monkeypatch):
    contract, selected, bounded = _starting_preflight_case()
    bounded.pop("origin_skill_choices_by_origin_id")
    run, plan = _starting_preflight_run_plan(contract, selected, bounded)
    _stub_preflight_provider_payload(monkeypatch)

    with pytest.raises(FoundryError) as raised:
        CharacterCreationExecutionService._validate_preferred_bounded_fields(run, plan)

    assert raised.value.code == "CG1_STARTING_PROFICIENCY_CHOICE_INVALID"
    assert any(
        blocker["code"] == "BOUNDED_CHOICE_MAP_KEY_MISSING"
        for blocker in raised.value.details["blockers"]
    )


class _StartingProficiencyLockStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def materialize_server_derived_user_lock(
        self,
        project_id,
        *,
        field,
        value,
        source,
        lock_id,
    ):
        self.calls.append({
            "project_id": project_id,
            "field": field,
            "value": deepcopy(value),
            "source": source,
            "lock_id": lock_id,
        })
        return {"project": {"project_id": project_id}}


def _starting_lock_service() -> CharacterCreationExecutionService:
    service = object.__new__(CharacterCreationExecutionService)
    store = _StartingProficiencyLockStore()
    service.projects = store
    service.db = store
    return service


def test_materialize_starting_proficiency_lock_is_exact_and_server_owned():
    contract, selected, bounded = _starting_preflight_case()
    run, plan = _starting_preflight_run_plan(contract, selected, bounded)
    service = _starting_lock_service()

    receipt = service._materialize_starting_proficiency_choices(
        run,
        plan,
        service.db,
    )

    assert receipt["schema"] == "TianxiaFoundry.ServerDerivedStartingProficiencies.v1"
    assert receipt["field"] == "character.choices.starting_proficiencies"
    assert receipt["lock_id"] == "lock.cg1.character-choices-starting-proficiencies"
    assert len(service.projects.calls) == 1
    call = service.projects.calls[0]
    assert call["project_id"] == run["project_id"]
    assert call["field"] == receipt["field"]
    assert call["lock_id"] == receipt["lock_id"]
    value = call["value"]
    assert set(value) == {
        "schema",
        "contract",
        "response_maps",
        "selected_by_slot",
        "validated",
        "binding",
    }
    assert value["schema"] == receipt["schema"]
    assert value["contract"] == contract
    assert value["response_maps"] == bounded
    assert value["selected_by_slot"] == selected
    assert value["validated"]["valid"] is True
    assert value["validated"]["contract_sha256"] == contract["contract_sha256"]
    assert value["validated"]["validation_sha256"] == receipt["validation_sha256"]
    assert value["binding"] == {
        "schema": receipt["schema"],
        "run_id": run["run_id"],
        "project_id": run["project_id"],
        "starting_revision": run["starting_revision"],
        "content_lock_hash": run["request"]["content_lock_hash"],
        "request_sha256": run["request"]["request_sha256"],
        "response_sha256": run["response"]["response_sha256"],
    }
    assert "phase" not in value
    assert "raw_response" not in value
    assert "response_text" not in value
    assert call["source"] == (
        f"cg1-starting-proficiencies:{receipt['lock_value_sha256']}:server-derived"
    )
    assert receipt["lock_value_sha256"] == creation_service.sha256_json(value)


def test_materialize_starting_proficiency_lock_is_byte_identical_across_phases():
    contract, selected, bounded = _starting_preflight_case()
    run, plan = _starting_preflight_run_plan(contract, selected, bounded)
    service = _starting_lock_service()

    # The phase is deliberately not part of the lock.  This mirrors the two
    # real call sites (scratch compilation and finalization) and ensures the
    # durable server-derived value cannot diverge by lifecycle boundary.
    first = service._materialize_starting_proficiency_choices(run, plan, service.db)
    second = service._materialize_starting_proficiency_choices(run, plan, service.db)

    assert first == second
    assert service.projects.calls[0]["value"] == service.projects.calls[1]["value"]
    assert service.projects.calls[0]["source"] == service.projects.calls[1]["source"]


def test_materialize_starting_proficiency_lock_rejects_forged_choices_before_store():
    contract, selected, bounded = _starting_preflight_case()
    bounded["path_skill_choices_by_path_id"][PATH_ID] = ["Arcana", "Stealth"]
    run, plan = _starting_preflight_run_plan(contract, selected, bounded)
    service = _starting_lock_service()

    with pytest.raises(FoundryError) as raised:
        service._materialize_starting_proficiency_choices(run, plan, service.db)

    assert raised.value.code == "CG1_STARTING_PROFICIENCY_CHOICE_INVALID"
    assert raised.value.status_code == 422
    assert len(service.projects.calls) == 0
    assert set(raised.value.details) == {
        "schema",
        "contract_sha256",
        "validation_sha256",
        "blockers",
    }
    assert "Stealth" not in json.dumps(raised.value.details)


def test_materialize_starting_proficiency_lock_is_legacy_noop_without_contract():
    service = _starting_lock_service()
    run = {
        "run_id": "cg1.test.legacy-starting-proficiency",
        "project_id": "project.legacy-starting-proficiency",
        "starting_revision": 1,
        "request": {},
        "response": {"response_sha256": "a" * 64},
    }
    plan = {"selection_intent": {"by_slot": {}}, "bounded_choices": {}}

    assert service._materialize_starting_proficiency_choices(run, plan, service.db) is None
    assert service.projects.calls == []


def test_descriptive_materialization_invokes_starting_lock_for_each_compile_phase():
    contract, selected, bounded = _starting_preflight_case()
    run, plan = _starting_preflight_run_plan(contract, selected, bounded)
    service = _starting_lock_service()

    service._materialize_descriptive_fields(run, plan, service.db, phase="scratch_compile")
    service._materialize_descriptive_fields(run, plan, service.db, phase="finalization")

    assert len(service.projects.calls) == 2
    assert service.projects.calls[0]["field"] == "character.choices.starting_proficiencies"
    assert service.projects.calls[0]["value"] == service.projects.calls[1]["value"]
