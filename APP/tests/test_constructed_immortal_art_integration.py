"""Boundary regressions for the automatic Immortal Art Stage 2 lane.

The fixture uses a real project lock and the server materializer to produce a
Bone Guard record.  The compiler is then invoked through the actual Stage 2
record path inside the authenticated initial-creation scope.  It deliberately
does not create a project-lock row for the progression child: that child is a
parent-bound Subpath commitment, not an independent catalog record.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.core import FoundryError, canonical_json
from character_builder import CharacterBuilderService
from character_creation.constructed_arts.immortal_art import (
    construct_immortal_art,
    load_immortal_art_authority,
)
from character_creation.constructed_arts.records import (
    IMMORTAL_ART_RECORD_CHANNEL,
    build_immortal_art_record,
    immortal_art_record_text,
    validate_constructed_art_record,
)
from character_creation.constructed_arts.sources import installed_factory_root
from character_creation.service import CharacterCreationExecutionService
from contracts.canonical import ZERO_HASH
from project_store.service import ProjectStore
from stage1.service import Stage1ClipboardService
from stage2.service import RulesCausalStage2Service, _state
from projector.v3_bridge import _immortal_art_projection_rows
from tests.test_rec1_p1cr5_owner_authority import _private_scope


ROOT = Path(__file__).resolve().parents[1]
BODY_PATH = "tianxia.path.body_refining"
BONE_MONARCH = "tianxia.subpath.body.bone_monarch"


def _event(event_id: str, kind: str, record_id: str, record_hash: str, *, cl: int, outputs: dict | None = None) -> dict:
    """Build a complete canonical event envelope for real prefix replay."""
    return {
        "schema_version": "TianxiaFoundry.AdvancementEvent.v3",
        "event_id": event_id,
        "subject": {"record_id": record_id},
        "content_binding": {"record_hash": record_hash},
        "event_type": "acquire",
        "created_records": [record_id],
        "updated_records": [],
        "retired_records": [],
        "advancement": {
            "kind": kind,
            "target_cl": cl,
            "details": {},
            "calculation": {
                "formula": None,
                "inputs": {},
                "outputs": deepcopy(outputs or {}),
                "trace": {},
            },
            "authority_bindings": [],
            "training_transaction": None,
            "none_state": None,
        },
    }


@pytest.fixture(scope="module")
def immortal_environment(catalog_environment):
    return _immortal_environment(catalog_environment, BODY_PATH, BONE_MONARCH, "CON", legacy_request=True)


@pytest.fixture(scope="module")
def two_immortal_environment(catalog_environment):
    return _immortal_environment(
        catalog_environment,
        BODY_PATH,
        BONE_MONARCH,
        "CON",
        target_cl=20,
    )


@pytest.fixture(scope="module")
def dreamweaver_environment(catalog_environment):
    return _immortal_environment(
        catalog_environment,
        "tianxia.path.spirit_awakening",
        "tianxia.tradition.spirit.dreamweaver",
        "WIS",
    )


def _immortal_environment(catalog_environment, path_id, subpath_id, key_ability, *, target_cl=15, legacy_request=False, autogen_seed=None):
    """Build a project whose Immortal Art source is a real parent-bound Subpath feature.

    ``legacy_request`` stores the creation request with the pre-proof
    ``server_owned_pre_provider.v1`` marker.  Stage 2 then keeps the historical
    no-proof lane, which lets provenance/source tests use an Art whose
    Refinement DC the character can never reach (the auto-built CL15 Bone
    Monarch Art is Mandate Complexity 7 against a Nascent Soul threshold of 3,
    DC 28 versus a best check of 27).  Refinement enforcement itself is covered
    by the v2-request environments and test_immortal_art_refinement.py.
    """
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    created = builder.create_project(
        working_name="Item 5 Immortal Art boundary",
        concept="A real parent-bound Subpath source for Stage 2 boundary checks.",
        target_cl=target_cl,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={"path_choice": [path_id], "subpath_choice": [subpath_id]},
        generation_route="ai_bootstrap",
        autogen_seed=autogen_seed,
    )
    project_id = created["project_id"]
    store = ProjectStore(db)
    creator = CharacterCreationExecutionService(
        db,
        stage1=Stage1ClipboardService(db),
        provider=None,
        project_store=store,
    )
    request = creator._complete_request(
        project_id,
        execution_mode="MANUAL_CHAT",
        idempotency_key=f"item5-immortal-art-boundary:{project_id}",
    )
    run_id = f"cg1.test.item5-immortal-art-boundary.{project_id}"
    stored_request = deepcopy(request)
    if legacy_request:
        stored_request["server_owned_authority"]["manual_collection"]["authority_version"] = "server_owned_pre_provider.v1"
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO character_creation_runs(
                run_id,project_id,starting_revision,execution_mode,idempotency_key,
                request_json,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                project_id,
                request["project_revision"],
                "MANUAL_CHAT",
                f"item5-immortal-art-boundary:{project_id}",
                canonical_json(stored_request),
                "WAITING_FOR_RESPONSE",
                "2026-08-17T00:00:00+00:00",
                "2026-08-17T00:00:00+00:00",
            ),
        )

    project = store.get_project(project_id)["project"]
    records = creator._locked_records_for_project(project_id)
    assert path_id in records
    assert subpath_id in records
    path = records[path_id]
    parent = records[subpath_id]
    scores = {ability: 14 if ability == key_ability else 10 for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    path_authority = (path.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
    feature_ids_by_cl = {
        int(cl): list(progression.get("feature_record_ids") or [])
        for cl, progression in (path_authority.get("progression_by_cl") or {}).items()
        if str(cl).isdigit() and isinstance(progression, dict)
    }
    assert all(feature_ids_by_cl.get(cl) for cl in range(1, target_cl + 1))
    rows = [
        {
            "kind": "starting_state",
            "effective_cl": 1,
            "record_id": "tianxia.test.starting_state",
            "parameters": {"ability_scores": scores},
        },
        {"kind": "path_acquisition", "effective_cl": 1, "record_id": path_id},
        {"kind": "subpath_acquisition", "effective_cl": 3, "record_id": subpath_id},
    ]
    rows.extend(
        {
            "kind": "level_advance",
            "effective_cl": cl,
            "record_id": feature_ids_by_cl[cl][0],
        }
        for cl in range(1, target_cl + 1)
    )
    run = {"project_id": project_id, "request": stored_request}
    constructed = creator._immortal_art_constructions(
        run,
        project,
        {},
        rows,
        records,
        target_cl,
        intent_hash=request["request_sha256"],
    )
    assert len(constructed) == (2 if target_cl >= 20 else 1)
    art, record = constructed[0]
    with db.transaction() as conn:
        store.insert_constructed_art_records(
            conn,
            project_id,
            [record for _art, record in constructed],
        )
    with db.connection() as conn:
        child_row = conn.execute(
            "SELECT 1 FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, art["source_record_id"]),
        ).fetchone()
    assert child_row is None

    parent_features = (
        (parent.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
    ).get("feature_progression") or []
    prefix = [
        _event(
            "event.path.item5",
            "path_acquisition",
            path_id,
            path["record_hash"],
            cl=1,
        ),
        _event(
            "event.subpath.item5",
            "subpath_acquisition",
            subpath_id,
            parent["record_hash"],
            cl=3,
            outputs={"granted_feature_record_ids": [row["canonical_id"] for row in parent_features if isinstance(row, dict)]},
        ),
    ]
    prefix.extend(
        _event(
            f"event.level.item5.{cl}",
            "level_advance",
            feature_ids_by_cl[cl][0],
            ZERO_HASH,
            cl=cl,
            outputs={"path_progression_authority": {"path_id": path_id}},
        )
        for cl in range(1, target_cl + 1)
    )
    state = _state(project_id)
    state.update(
        {
            "current_cl": target_cl,
            "paths": [path_id],
            "subpaths": [subpath_id],
            "ability_scores": scores,
            "ability_modifiers": {ability: (score - 10) // 2 for ability, score in scores.items()},
            "record_event_ids": {path_id: "event.path.item5", subpath_id: "event.subpath.item5"},
        }
    )
    return {
        "db": db,
        "creator": creator,
        "stage2": RulesCausalStage2Service(db),
        "project": project,
        "run": {"project_id": project_id, "run_id": run_id, "request": stored_request},
        "legacy_request": legacy_request,
        "art": art,
        "record": record,
        "arts": constructed,
        "state": state,
        "prefix": prefix,
    }


def _refinement_parameters(env, art, record, *, index=0):
    """Server-derived Refinement Check history a creator Art must carry (opening rules 4-6)."""
    proof = env["creator"]._immortal_art_creation_parameters(
        env["run"], art, record, index=index, intent_hash=env["run"]["request"]["request_sha256"],
    )
    return {"immortal_refinement": proof} if proof is not None else None


def _compile_art(env, *, state=None, record=None, prefix=None, art=None):
    service = env["stage2"]
    request = env["run"]["request"]
    project_id = env["run"]["project_id"]
    target_record = record or env["record"]
    with _private_scope(service, request, env["run"]["run_id"], set(env["state"]["paths"])):
        with env["db"].connection() as conn:
            return service._immortal_art_compile(
                conn,
                project_id,
                target_record,
                deepcopy(state or env["state"]),
                "/choices/0",
                15,
                generic_prefix=deepcopy(prefix or env["prefix"]),
                parameters=_refinement_parameters(env, art or env["art"], target_record),
                event_id="event.art.item5",
            )


def _project_immortal_art(env, *, record, outputs, bindings):
    event_id = "event.immortal-art-projection-regression"
    event = {
        "event_id": event_id,
        "sequence": 1,
        "advancement": {
            "authority_bindings": deepcopy(bindings),
            "calculation": {"outputs": deepcopy(outputs)},
        },
    }
    locked_records = env["creator"]._locked_records_for_project(env["run"]["project_id"])
    locked_records[record["record_id"]] = deepcopy(record)
    factory_root = installed_factory_root(env["creator"].db.settings.vendor_dir)
    return _immortal_art_projection_rows(
        [event],
        event_records={event_id: deepcopy(record)},
        locked_records=locked_records,
        packet_by_event={event_id: "packet.immortal-art-projection-regression"},
        factory_root=factory_root,
    )


def _coherently_rederived_art(env, mutation):
    request = deepcopy(env["art"]["construction"]["request"])
    source_id = env["art"]["source_record_id"]
    source = next(row for row in request["known_sources"] if row["record_id"] == source_id)
    mutation(source)
    authority = load_immortal_art_authority(ROOT)
    art = construct_immortal_art(authority, request)
    return art, build_immortal_art_record(art)


def test_dreamweaver_stage2_rederives_complete_action_and_dependencies(dreamweaver_environment):
    env = dreamweaver_environment
    assert env["art"]["source_record_id"] == "tianxia.tradition.spirit.dreamweaver.feature.unreality_bites_back"
    source = env["art"]["source"]
    assert [row["purpose"] for row in source["source_dependencies"]] == [
        "dream_thread_definition", "dreamweaver_cultivation_boundary",
    ]
    assert "once per rest" in source["action_surface"]["cleanup"]
    blockers, outputs, bindings, _inputs = _compile_art(env)
    assert blockers == []
    assert outputs
    rows, indexes = _project_immortal_art(env, record=env["record"], outputs=outputs, bindings=bindings)
    assert indexes
    assert [row["record_id"] for row in rows] == [env["art"]["art_id"]]


@pytest.mark.parametrize("mutation", ("dependency_removed", "dependency_purpose", "action_limit"))
def test_dreamweaver_stage2_rejects_coherently_rederived_dependency_drift(dreamweaver_environment, mutation):
    def mutate(source):
        if mutation == "dependency_removed":
            source["source_dependencies"].pop()
        elif mutation == "dependency_purpose":
            source["source_dependencies"][0]["purpose"] = "untrusted_replacement"
        else:
            source["action_surface"]["limits"].pop()

    env = dreamweaver_environment
    art, record = _coherently_rederived_art(env, mutate)
    blockers, _outputs, _bindings, _inputs = _compile_art(env, record=record)
    expected = "IMMORTAL_ART_ACTION_SOURCE_MISMATCH" if mutation == "action_limit" else "IMMORTAL_ART_SOURCE_DEPENDENCY_MISMATCH"
    assert expected in {row["code"] for row in blockers}
    valid_blockers, outputs, bindings, _inputs = _compile_art(env)
    assert valid_blockers == []
    outputs["immortal_art"] = art
    outputs["immortal_art_record_text"] = immortal_art_record_text(art)
    with pytest.raises(FoundryError) as error:
        _project_immortal_art(env, record=record, outputs=outputs, bindings=bindings)
    projection_code = "PROJECTION_IMMORTAL_ART_ACTION_SOURCE_INVALID" if mutation == "action_limit" else "PROJECTION_IMMORTAL_ART_SOURCE_DEPENDENCY_INVALID"
    assert error.value.code == projection_code


def test_immortal_record_and_projection_accept_exact_terminal_source_newline(immortal_environment):
    env = immortal_environment
    factory_root = installed_factory_root(env["creator"].db.settings.vendor_dir)
    assert env["art"]["source"]["published_text"].endswith("\n")
    validated = validate_constructed_art_record(
        env["record"],
        root_dir=ROOT,
        factory_root=factory_root,
    )
    assert validated["art_id"] == env["art"]["art_id"]

    blockers, outputs, bindings, _inputs = _compile_art(env)
    assert blockers == []
    rows, indexes = _project_immortal_art(
        env,
        record=env["record"],
        outputs=outputs,
        bindings=bindings,
    )
    assert indexes
    assert [row["record_id"] for row in rows] == [env["art"]["art_id"]]
    parent = env["creator"]._locked_records_for_project(env["run"]["project_id"])[BONE_MONARCH]
    feature = next(
        row for row in parent["compatibility"]["factory"]["stage2_authority"]["feature_progression"]
        if row["canonical_id"] == env["art"]["source_record_id"]
    )
    # The canonical parent snapshot intentionally carries only the source
    # file/bounds commitment; the adapter supplies the normalized source ID.
    assert "source_id" not in feature["source"]


def test_persisted_immortal_art_snapshot_rederives_after_json_round_trip(immortal_environment):
    """The immutable DB row must survive canonical JSON reload unchanged."""
    env = immortal_environment
    with env["db"].connection() as conn:
        row = conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (env["run"]["project_id"], env["record"]["record_id"]),
        ).fetchone()
    assert row is not None
    stored = json.loads(row["record_json"])
    assert canonical_json(stored) == row["record_json"]
    assert row["record_hash"] == stored["record_hash"]
    factory_root = installed_factory_root(env["creator"].db.settings.vendor_dir)
    validated = validate_constructed_art_record(stored, root_dir=ROOT, factory_root=factory_root)
    assert validated["art_id"] == env["art"]["art_id"]
    locked = env["creator"]._locked_records_for_project(env["run"]["project_id"])
    assert canonical_json(locked[env["record"]["record_id"]]) == row["record_json"]


@pytest.mark.parametrize("environment_name", ["immortal_environment", "dreamweaver_environment"])
def test_command4_uses_rederived_immortal_cost_and_factor_result(request, environment_name, tmp_path):
    from types import SimpleNamespace
    from factory_authoring.immortal_art_mechanics import load_immortal_action_binding, validate_immortal_action_candidate
    from factory_authoring.command4_actions import _parse_explicit_fields
    from factory_authoring.command4_provider import Command4ProviderAuthoring

    env = request.getfixturevalue(environment_name)
    project_id = env["run"]["project_id"]
    binding = load_immortal_action_binding(env["db"], project_id, env["record"]["record_id"])
    action = env["art"]["action_surface"]
    fields = _parse_explicit_fields(binding["full_description"])
    assert fields["cost"] == f"{action['resource_cost']} {action['resource_name']}"
    assert "Published source block" not in binding["full_description"]
    assert canonical_json(action["factor_application"]["effective_effect"]) in binding["full_description"]
    if "destruction_factor" in action["factor_application"]:
        assert action["factor_application"]["destruction_factor"]["effective_damage_expression"] in binding["full_description"]

    candidate = {key: binding[key] for key in ("record_id", "record_hash", "source", "name", "full_description")}
    candidate.update(constructed_immortal_source_binding=binding, source_packet_ids=["creation"], missing_fields=["unambiguous_locked_mechanics_source"])
    assert validate_immortal_action_candidate(env["db"], project_id, candidate) == binding
    (tmp_path / "Command_1").mkdir()
    (tmp_path / "Command_1/Build_Request.json").write_text(json.dumps({"project_id": project_id}))
    source = binding["source"]
    packet = {"record_id": binding["record_id"], "record_hash": binding["record_hash"], "advancement_kind": "immortal_art_creation", "source_evidence": [{"source_path": source["path"], "source_hash": source["sha256"], "source_anchor": source["anchor"]}]}
    author = Command4ProviderAuthoring(workspace_service=SimpleNamespace(db=env["db"]))
    proof = author._resolve_locked_source_proof(tmp_path, candidate, {"creation": packet}, ())
    assert proof["constructed_immortal_source_binding"] == binding
    assert proof["source_packet_ids"] == ["creation"]

    changed = deepcopy(candidate)
    changed["full_description"] = changed["full_description"].replace(f"Cost: {action['resource_cost']}", "Cost: 0")
    changed["constructed_immortal_source_binding"]["full_description"] = changed["full_description"]
    with pytest.raises(FoundryError) as altered:
        validate_immortal_action_candidate(env["db"], project_id, changed)
    assert altered.value.code == "COMMAND4_IMMORTAL_SOURCE_INVALID"
    altered_packet = deepcopy(packet)
    altered_packet["source_evidence"][0]["source_hash"] = "0" * 64
    with pytest.raises(FoundryError) as stale_packet:
        author._resolve_locked_source_proof(tmp_path, candidate, {"creation": altered_packet}, ())
    assert stale_packet.value.code == "COMMAND4_IMMORTAL_ACQUISITION_MISMATCH"


def _command4_immortal_fixture(env, *, packet_id="creation", record=None):
    from factory_authoring.immortal_art_mechanics import load_immortal_action_binding

    project_id = env["run"]["project_id"]
    selected_record = record or env["record"]
    binding = load_immortal_action_binding(env["db"], project_id, selected_record["record_id"])
    source = binding["source"]
    card = {
        "record_id": binding["record_id"],
        "record_hash": binding["record_hash"],
        "display_name": binding["name"],
        "full_description": binding["full_description"],
        "one_line_description": binding["name"],
        "source_packet_ids": [packet_id],
        "source": deepcopy(source),
        "acquisition_cl": 15,
        "acquisition_route": "immortal_art_creation",
        "constructed_immortal_source_binding": deepcopy(binding),
    }
    candidate = {
        "record_id": binding["record_id"],
        "record_hash": binding["record_hash"],
        "source": deepcopy(source),
        "name": binding["name"],
        "full_description": binding["full_description"],
        "source_packet_ids": [packet_id],
        "missing_fields": ["unambiguous_locked_mechanics_source"],
        "constructed_immortal_source_binding": deepcopy(binding),
    }
    packet = {
        "packet_id": packet_id,
        "record_id": binding["record_id"],
        "record_hash": binding["record_hash"],
        "advancement_kind": "immortal_art_creation",
        "source_evidence": [{
            "source_path": source["path"],
            "source_hash": source["sha256"],
            "source_anchor": source["anchor"],
        }],
    }
    return card, candidate, packet, binding


def test_command4_producer_promotes_two_immortal_rows_only_with_server_proof(
    two_immortal_environment,
):
    from factory_authoring.command4_actions import Command4ActionProducer, _issue_authenticated_constructed_immortal_source
    from factory_authoring.command4_provider import _resolve_constructed_immortal_source_proof

    cards = []
    authorities = {}
    env = two_immortal_environment
    for index, (_art, record) in enumerate(env["arts"]):
        card, candidate, packet, _binding = _command4_immortal_fixture(
            env,
            packet_id=f"creation.{index}",
            record=record,
        )
        proof = _resolve_constructed_immortal_source_proof(
            env["db"],
            env["run"]["project_id"],
            candidate,
            [packet],
        )
        authorities[card["record_id"]] = _issue_authenticated_constructed_immortal_source(proof)
        cards.append(card)
    # Retain one incomplete unrelated action so this checkpoint cannot claim
    # whole-surface readiness merely because the two source rows are valid.
    cards.append({
        "record_id": "tianxia.talent.unresolved",
        "display_name": "Unresolved Action",
        "full_description": "Action Type: Action\nCost: None",
        "source_packet_ids": [],
        "source": None,
    })

    documents = Command4ActionProducer.produce(
        cards,
        project_id=env["run"]["project_id"],
        _authenticated_constructed_immortal_sources=authorities,
    )
    surface = documents["Complete_Action_Surface.json"]
    assert surface["status"] == "ACTION_SURFACE_PARTIAL"
    assert surface["execution_authority"] is False
    assert {row["record_id"] for row in surface["actions"]} == {
        record["record_id"] for _art, record in env["arts"]
    }
    candidates = {
        row["record_id"]: row
        for row in documents["Action_Authoring_Candidates.json"]["candidates"]
    }
    for record_id in authorities:
        assert candidates[record_id]["constructed_immortal_source_binding"]["record_id"] == record_id
        assert candidates[record_id]["missing_fields"] == []
    assert "tianxia.talent.unresolved" in {
        row["record_id"] for row in documents["Action_Authoring_Candidates.json"]["candidates"]
    }

    wrong_project = Command4ActionProducer.produce(
        cards,
        project_id="project.not.the.owner",
        _authenticated_constructed_immortal_sources=authorities,
    )
    assert wrong_project["Complete_Action_Surface.json"]["actions"] == []
    assert all(
        "unambiguous_locked_mechanics_source" in row["missing_fields"]
        for row in wrong_project["Action_Authoring_Candidates.json"]["candidates"]
        if row["record_id"] in authorities
    )

    missing_project = Command4ActionProducer.produce(
        cards,
        _authenticated_constructed_immortal_sources=authorities,
    )
    assert missing_project["Complete_Action_Surface.json"]["actions"] == []
    assert all(
        "unambiguous_locked_mechanics_source" in row["missing_fields"]
        for row in missing_project["Action_Authoring_Candidates.json"]["candidates"]
        if row["record_id"] in authorities
    )


def test_factory_documents_rederive_two_immortal_rows_from_real_project_packets(
    two_immortal_environment,
):
    from factory_authoring.service import FactoryAuthoringWorkspaceService

    env = two_immortal_environment
    cards = []
    packets = []
    for index, (_art, record) in enumerate(env["arts"]):
        card, _candidate, packet, _binding = _command4_immortal_fixture(
            env,
            packet_id=f"service.creation.{index}",
            record=record,
        )
        card["section"] = "immortal_arts"
        cards.append(card)
        packets.append(packet)

    snapshot = {
        "identity": {
            "display_name": "Service Immortal Art Fixture",
            "cultivation_level": 20,
            "realm": "Immortal",
        },
        "selected_record_sections": {"immortal_arts": cards},
        "capability_status": {"records": [], "pending_execution_surfaces": []},
        "advancement_history": {"owner_choice_locks": []},
        "explicit_none_systems": {
            "method": {"state": "none", "source_backed": True},
            "foundation": {"state": "none", "source_backed": True},
        },
        "recorded_arts": [],
        "immortal_arts": deepcopy(cards),
        "forged_techniques": [],
        "training_sources": [],
        "background_and_origin": {},
        "path_and_subpath": {},
        "spheres_and_talents": {},
        "method": {},
        "foundation": {},
    }
    service = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
    service.db = env["db"]
    sealed_profile, sealed_profile_sha = service._authoring_profile()
    sealed_workspace, sealed_workspace_sha = service._workspace_profile()
    profile, profile_sha, workspace_profile, workspace_profile_sha = service._project_authoring_profile(
        snapshot,
        sealed_profile,
        sealed_profile_sha,
        sealed_workspace,
        sealed_workspace_sha,
    )
    documents = service._documents(
        project=env["project"],
        sheet_response={
            "owner_character_sheet": snapshot,
            "provenance": {"advancement_projection": {"projection": {"projection_id": "real"}}},
            "sheet_artifact": {"sha256": "sheet-real"},
        },
        profile=profile,
        profile_sha=profile_sha,
        workspace_profile=workspace_profile,
        workspace_profile_sha=workspace_profile_sha,
        projection_artifacts={
            "Character_Master_Ledger.json": {
                "advancement": {"event_count": 0, "event_head_hash": "0" * 64},
                "character": {},
                "core_stats": {},
                "resources": {},
                "typed_none": {},
            },
            "Rules_Selection_Packets.json": {"packets": packets},
            "Projection_Provenance_Map.json": {"projection_id": "real"},
        },
    )
    surface = documents["Command_4/Complete_Action_Surface.json"]
    assert surface["status"] == "ACTION_SURFACE_READY"
    assert surface["execution_authority"] is True
    assert {row["record_id"] for row in surface["actions"]} == {
        record["record_id"] for _art, record in env["arts"]
    }
    assert all(
        row["constructed_immortal_source_binding"]["project_id"] == env["project"]["project_id"]
        for row in surface["actions"]
    )


def test_command4_supplied_immortal_binding_without_authoritative_context_stays_unresolved(
    immortal_environment,
):
    from factory_authoring.command4_actions import Command4ActionProducer

    card, _candidate, _packet, _binding = _command4_immortal_fixture(immortal_environment)
    documents = Command4ActionProducer.produce([card])
    assert documents["Complete_Action_Surface.json"]["actions"] == []
    [candidate] = documents["Action_Authoring_Candidates.json"]["candidates"]
    assert "unambiguous_locked_mechanics_source" in candidate["missing_fields"]
    assert "constructed_immortal_source_binding" not in candidate


@pytest.mark.parametrize("mutation", ("wrong_project", "wrong_record", "wrong_source", "wrong_action_surface", "missing_packet", "stale_packet", "duplicate_packet"))
def test_command4_immortal_proof_rejects_identity_and_acquisition_drift(immortal_environment, mutation):
    from factory_authoring.command4_provider import _resolve_constructed_immortal_source_proof

    _card, candidate, packet, binding = _command4_immortal_fixture(immortal_environment)
    project_id = immortal_environment["run"]["project_id"]
    packets = [packet]
    if mutation == "wrong_project":
        project_id = "project.not.the.owner"
    elif mutation == "wrong_record":
        candidate["record_id"] = "tianxia.constructed.immortal_art.missing"
    elif mutation == "wrong_source":
        candidate["source"]["sha256"] = "0" * 64
    elif mutation == "wrong_action_surface":
        candidate["full_description"] += "\nEffect: forged source text"
    elif mutation == "missing_packet":
        packets = []
    elif mutation == "stale_packet":
        packets[0] = deepcopy(packet)
        packets[0]["source_evidence"][0]["source_hash"] = "0" * 64
    elif mutation == "duplicate_packet":
        candidate["source_packet_ids"] = [packet["packet_id"], packet["packet_id"]]

    with pytest.raises(FoundryError) as excinfo:
        _resolve_constructed_immortal_source_proof(
            immortal_environment["db"],
            project_id,
            candidate,
            packets,
        )
    assert excinfo.value.code in {
        "COMMAND4_IMMORTAL_SOURCE_MISSING",
        "COMMAND4_IMMORTAL_OWNER_MISMATCH",
        "COMMAND4_IMMORTAL_SOURCE_INVALID",
        "COMMAND4_IMMORTAL_ACQUISITION_MISMATCH",
    }


@pytest.mark.parametrize("mutation_name", ("trimmed_published_text", "section_hash_drift", "file_hash_drift"))
def test_runtime_rejects_coherent_exact_source_drift(immortal_environment, mutation_name):
    """A rehashed payload cannot replace the installed bounded source section."""
    mutations = {
        "trimmed_published_text": lambda row: row.update(published_text=row["published_text"].strip()),
        "section_hash_drift": lambda row: row["progression"]["source"].update(section_sha256="0" * 64),
        "file_hash_drift": lambda row: row["progression"]["source"].update(source_file_sha256="0" * 64),
    }
    env = immortal_environment
    art, record = _coherently_rederived_art(env, mutations[mutation_name])
    assert art["art_id"] != env["art"]["art_id"]
    factory_root = installed_factory_root(env["creator"].db.settings.vendor_dir)
    with pytest.raises(FoundryError) as excinfo:
        validate_constructed_art_record(record, root_dir=ROOT, factory_root=factory_root)
    assert excinfo.value.code == "CONSTRUCTED_ART_RECORD_INVALID"
    assert "exact hash-verified installed published section" in excinfo.value.message


def test_projection_rejects_coherently_rederived_tampered_source_id(immortal_environment):
    env = immortal_environment
    art, record = _coherently_rederived_art(
        env,
        lambda row: row["source"].update(source_id="source.tampered.adapter"),
    )
    blockers, outputs, bindings, _inputs = _compile_art(env)
    assert blockers == []
    outputs["immortal_art"] = art
    outputs["immortal_art_record_text"] = immortal_art_record_text(art)
    with pytest.raises(FoundryError) as excinfo:
        _project_immortal_art(env, record=record, outputs=outputs, bindings=bindings)
    assert excinfo.value.code == "PROJECTION_IMMORTAL_ART_SOURCE_BINDING_INVALID"


def test_parent_bound_feature_compiles_without_independent_child_lock(immortal_environment):
    env = immortal_environment
    blockers, outputs, bindings, inputs = _compile_art(env)
    assert blockers == [], [
        {
            "code": row.get("code"),
            "message": row.get("message"),
            "details": row.get("details"),
        }
        for row in blockers
    ]
    assert outputs["immortal_art"]["source_record_id"] == env["art"]["source_record_id"]
    assert outputs.get("training_transaction") is None
    assert inputs["parent_subpath_acquisition_event_id"] == "event.subpath.item5"
    assert {binding["role"] for binding in bindings} == {
        "immortal_art_parent_subpath",
        "immortal_art_path_authority",
    }
    assert env["art"]["cl_created"] == 15
    assert env["art"]["pb_at_creation"] == 5


def test_wrong_parent_snapshot_hash_is_rejected(immortal_environment, monkeypatch):
    env = immortal_environment
    original = env["stage2"]._record

    def read(*args, **kwargs):
        record, issues = original(*args, **kwargs)
        if isinstance(record, dict) and record.get("record_id") == BONE_MONARCH:
            record = deepcopy(record)
            record["record_hash"] = "0" * 64
        return record, issues

    monkeypatch.setattr(env["stage2"], "_record", read)
    blockers, _outputs, _bindings, _inputs = _compile_art(env)
    assert "IMMORTAL_ART_PARENT_SOURCE_HASH_MISMATCH" in {row["code"] for row in blockers}


def test_missing_parent_and_insufficient_path_attainment_are_rejected(immortal_environment):
    env = immortal_environment
    missing_parent = deepcopy(env["state"])
    missing_parent["subpaths"] = []
    blockers, _outputs, _bindings, _inputs = _compile_art(env, state=missing_parent)
    assert "IMMORTAL_ART_PARENT_SUBPATH_REQUIRED" in {row["code"] for row in blockers}

    short_prefix = env["prefix"][: 2 + 10]
    blockers, _outputs, _bindings, _inputs = _compile_art(env, prefix=short_prefix)
    assert "IMMORTAL_ART_PATH_ATTAINMENT_INSUFFICIENT" in {row["code"] for row in blockers}


def test_same_id_changed_external_art_snapshot_is_rejected(immortal_environment):
    env = immortal_environment
    drifted = deepcopy(env["record"])
    nested = drifted["compatibility"]["factory"]["constructed_art"]["art"]
    nested["source"]["published_text"] = nested["source"]["published_text"] + "\nchanged"
    blockers, _outputs, _bindings, _inputs = _compile_art(env, record=drifted)
    assert blockers
    assert any(code in {row["code"] for row in blockers} for code in {
        "IMMORTAL_ART_FACTORY_CONTRACT_INVALID",
        "IMMORTAL_ART_SOURCE_TEXT_MISMATCH",
        "IMMORTAL_ART_REDERIVATION_MISMATCH",
    })


def test_cl20_selects_remaining_body_source_at_each_creation_point(catalog_environment):
    """A second Art uses the next attained Body source at CL20.

    The first source is priced and identified at CL15/PB5.  After that source
    is excluded, the CL20 construction selects Marrow Regeneration at
    CL20/PB6 rather than indexing the remaining candidate list by ordinal.
    """
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    created = builder.create_project(
        working_name="Item 5 CL20 Body source boundary",
        concept="Two distinct parent-bound Body sources for CL15 and CL20 Arts.",
        target_cl=20,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={"path_choice": [BODY_PATH], "subpath_choice": [BONE_MONARCH]},
        generation_route="ai_bootstrap",
    )
    project_id = created["project_id"]
    creator = CharacterCreationExecutionService(
        db,
        stage1=Stage1ClipboardService(db),
        provider=None,
        project_store=ProjectStore(db),
    )
    request = creator._complete_request(
        project_id,
        execution_mode="MANUAL_CHAT",
        idempotency_key=f"item5-immortal-art-cl20-boundary:{project_id}",
    )
    project = ProjectStore(db).get_project(project_id)["project"]
    records = creator._locked_records_for_project(project_id)
    path = records[BODY_PATH]
    path_authority = (path.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
    feature_ids_by_cl = {
        int(cl): list(progression.get("feature_record_ids") or [])
        for cl, progression in (path_authority.get("progression_by_cl") or {}).items()
        if str(cl).isdigit() and isinstance(progression, dict)
    }
    assert all(feature_ids_by_cl.get(cl) for cl in range(1, 21))
    rows = [
        {
            "kind": "starting_state",
            "effective_cl": 1,
            "record_id": "tianxia.test.starting_state.cl20",
            "parameters": {"ability_scores": {"STR": 10, "DEX": 10, "CON": 14, "INT": 10, "WIS": 10, "CHA": 10}},
        },
        {"kind": "path_acquisition", "effective_cl": 1, "record_id": BODY_PATH},
        {"kind": "subpath_acquisition", "effective_cl": 3, "record_id": BONE_MONARCH},
    ]
    rows.extend(
        {
            "kind": "level_advance",
            "effective_cl": cl,
            "record_id": feature_ids_by_cl[cl][0],
        }
        for cl in range(1, 21)
    )
    constructed = creator._immortal_art_constructions(
        {"project_id": project_id, "request": request},
        project,
        {},
        rows,
        records,
        20,
        intent_hash=request["request_sha256"],
    )
    assert len(constructed) == 2
    first, second = (art for art, _record in constructed)
    assert first["source_record_id"].endswith("bone_guard_manifestation")
    assert first["cl_created"] == 15
    assert first["pb_at_creation"] == 5
    assert first["realm"] == "Nascent Soul"
    assert first["construction"]["request"]["owning_path_cl"] == 15
    assert second["source_record_id"].endswith("marrow_regeneration")
    assert second["source_record_id"] != first["source_record_id"]
    # Marrow carries both Body and healing tags; only the authenticated
    # Restoration Factor is supported, so default Aspect selection must not
    # let the overlapping Body tag route it to Creation.
    assert second["dao_aspect"]["display_name"] == "Restoration"
    assert second["factors"][0]["factor_id"] == "hp_restoration"
    assert second["cl_created"] == 20
    assert second["pb_at_creation"] == 6
    assert second["realm"] == "Immortal"
    assert second["construction"]["request"]["owning_path_cl"] == 20
    assert second["mandate_complexity"] == 4
    assert second["refinement_dc"] == 17
    assert second["activation_cp"] == 6
    assert second["source"]["action_surface"]["effect"]["healing"]["base_dice"] == "2d10"
    effective = second["action_surface"]["factor_application"]["effective_effect"]
    assert effective["healing_formula"] == "PBd10"
    assert "replaces" in effective["restoration_factor"]["package"]["replacement"]


    # Replay the same constructed records through the actual Stage 2 event
    # boundary.  The production helper must keep the CL15 event before the
    # later level advances; a CL20 event is rejected until those advances have
    # established CL20.
    with db.transaction() as conn:
        ProjectStore(db).insert_constructed_art_records(
            conn,
            project_id,
            [record for _art, record in constructed],
        )
    run_id = f"cg1.test.item5-chronology.{project_id}"
    # Source selection per creation point is the subject here; the CL15 Bone
    # Monarch Art (DC 28) can never be refined, so keep the pre-proof lane.
    stored_request = deepcopy(request)
    stored_request["server_owned_authority"]["manual_collection"]["authority_version"] = "server_owned_pre_provider.v1"
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO character_creation_runs(
                run_id,project_id,starting_revision,execution_mode,idempotency_key,
                request_json,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                project_id,
                request["project_revision"],
                "MANUAL_CHAT",
                f"item5-chronology:{project_id}",
                canonical_json(stored_request),
                "WAITING_FOR_RESPONSE",
                "2026-08-17T00:00:00+00:00",
                "2026-08-17T00:00:00+00:00",
            ),
        )
    rows_with_arts = deepcopy(rows)
    for art, record in constructed:
        creator._insert_stage2_row_at_effective_cl(
            rows_with_arts,
            {
                "kind": "immortal_art_creation",
                "effective_cl": art["cl_created"],
                "record_id": record["record_id"],
                "acquisition_channel": IMMORTAL_ART_RECORD_CHANNEL,
                "parameters": {},
            },
        )
    baseline = [
        (entry["kind"], entry["effective_cl"], entry["record_id"])
        for entry in rows
    ]
    without_arts = [
        (entry["kind"], entry["effective_cl"], entry["record_id"])
        for entry in rows_with_arts
        if entry["kind"] != "immortal_art_creation"
    ]
    assert without_arts == baseline
    art_positions = [
        index
        for index, entry in enumerate(rows_with_arts)
        if entry["kind"] == "immortal_art_creation"
    ]
    assert [rows_with_arts[index]["effective_cl"] for index in art_positions] == [15, 20]
    assert art_positions[0] > max(
        index
        for index, entry in enumerate(rows_with_arts)
        if entry["effective_cl"] == 15 and entry["kind"] != "immortal_art_creation"
    )
    assert art_positions[0] < min(
        index
        for index, entry in enumerate(rows_with_arts)
        if type(entry.get("effective_cl")) is int and entry["effective_cl"] > 15
    )
    assert art_positions[1] > max(
        index
        for index, entry in enumerate(rows_with_arts)
        if entry["effective_cl"] == 20 and entry["kind"] != "immortal_art_creation"
    )

    stage2 = RulesCausalStage2Service(db)
    proposal_row = {
        "proposal_id": f"item5-chronology-{project_id}",
        "project_id": project_id,
        "expected_project_revision": request["project_revision"],
        "idempotency_key": f"item5-chronology:{project_id}",
        "created_at": "2026-08-17T00:00:00+00:00",
    }
    state15 = _state(project_id)
    state15.update({
        "current_cl": 15,
        "completed_levels": list(range(1, 16)),
        "pb": 5,
        "ability_scores": {"STR": 10, "DEX": 10, "CON": 14, "INT": 10, "WIS": 10, "CHA": 10},
        "ability_modifiers": {"STR": 0, "DEX": 0, "CON": 2, "INT": 0, "WIS": 0, "CHA": 0},
        "paths": [BODY_PATH],
        "subpaths": [BONE_MONARCH],
        "record_event_ids": {
            BODY_PATH: "event.path.item5.cl20",
            BONE_MONARCH: "event.subpath.item5.cl20",
        },
    })
    prefix15 = [
        _event("event.path.item5.cl20", "path_acquisition", BODY_PATH, path["record_hash"], cl=1),
        _event(
            "event.subpath.item5.cl20",
            "subpath_acquisition",
            BONE_MONARCH,
            records[BONE_MONARCH]["record_hash"],
            cl=3,
            outputs={
                "granted_feature_record_ids": [
                    row["canonical_id"]
                    for row in (records[BONE_MONARCH]["compatibility"]["factory"]["stage2_authority"].get("feature_progression") or [])
                ],
            },
        ),
    ]
    prefix15.extend(
        _event(
            f"event.level.item5.cl20.{cl}",
            "level_advance",
            feature_ids_by_cl[cl][0],
            ZERO_HASH,
            cl=cl,
            outputs={"path_progression_authority": {"path_id": BODY_PATH}},
        )
        for cl in range(1, 16)
    )

    records_by_art = {art["art_id"]: record for art, record in constructed}
    creation_run = {"project_id": project_id, "request": stored_request}

    def art_choice(art, cl):
        # A v2 creator request would carry the server-derived Refinement Check
        # (opening rules 4-6); the legacy request above keeps the sealed no-proof row.
        proof = creator._immortal_art_creation_parameters(
            creation_run, art, records_by_art[art["art_id"]],
            index=0 if cl == 15 else 1, intent_hash=request["request_sha256"],
        )
        return {
            "kind": "immortal_art_creation",
            "effective_cl": cl,
            "record_id": art["art_id"],
            "acquisition_channel": IMMORTAL_ART_RECORD_CHANNEL,
            "parameters": {"immortal_refinement": proof} if proof is not None else {},
        }

    def replay(state, choice, prefix, index):
        with _private_scope(stage2, request, run_id, {BODY_PATH}):
            with db.connection() as conn:
                return stage2._choice_event(
                    conn=conn,
                    row=proposal_row,
                    project=project,
                    state=deepcopy(state),
                    choice=choice,
                    index=index,
                    sequence=index + 1,
                    previous_hash=ZERO_HASH,
                    generic_prefix=deepcopy(prefix),
                )

    first_event, after_first, first_blockers = replay(
        state15,
        art_choice(first, 15),
        prefix15,
        0,
    )
    assert first_blockers == []
    assert first_event is not None

    inactive_event, unchanged, inactive_blockers = replay(
        after_first,
        art_choice(second, 20),
        [*prefix15, first_event],
        1,
    )
    assert inactive_event is None
    assert unchanged == after_first
    assert "ACQUISITION_BEFORE_LEVEL_ADVANCE" in {row["code"] for row in inactive_blockers}

    state20 = deepcopy(after_first)
    state20.update({"current_cl": 20, "completed_levels": list(range(1, 21)), "pb": 6})
    prefix20 = [
        *prefix15,
        first_event,
        *(_event(
            f"event.level.item5.cl20.{cl}",
            "level_advance",
            feature_ids_by_cl[cl][0],
            ZERO_HASH,
            cl=cl,
            outputs={"path_progression_authority": {"path_id": BODY_PATH}},
        ) for cl in range(16, 21)),
    ]
    second_event, _after_second, second_blockers = replay(
        state20,
        art_choice(second, 20),
        prefix20,
        2,
    )
    assert second_blockers == []
    assert second_event is not None
