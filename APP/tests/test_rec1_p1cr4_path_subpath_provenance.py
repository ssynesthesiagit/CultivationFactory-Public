from __future__ import annotations

import io
import json
import stat
import zipfile
from copy import deepcopy
from itertools import combinations
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_file, sha256_json
from character_builder import CharacterBuilderService
from character_creation.delegated_choice_authority import (
    _validate_path_subpath_bindings,
    build_delegated_choice_envelope,
)
from character_creation.service import CharacterCreationExecutionService
from contracts.canonical import canonical_record_hash
from non_sphere_authority import NonSphereAuthorityService
from path_method_authority import CANONICAL_PATH_IDS
from path_method_authority import method_granted_path_ids
from project_store.service import ProjectStore
from projector.v3_bridge import _dynamic_display_contract
from projector.v3_bridge import _explicit_subpath_owner
from projector.v3_bridge import _validate_generic_subpath_owners
from stage1.service import Stage1ClipboardService
from tests.test_cat3_p1r_persistence import _clone_catalog_database
from tests.test_cg1_character_creation_modes import make
from stage2.service import RulesCausalStage2Service, _state


_BODY_PATH = "tianxia.path.body_refining"
_QI_PATH = "tianxia.path.qi_cultivation"
_SPIRIT_PATH = "tianxia.path.spirit_awakening"
_BODY_SUBPATH = "tianxia.subpath.body.flesh_crucible"
_SPIRIT_SUBPATH = "tianxia.tradition.spirit.dreamweaver"
_FOUNDATION = "ancient_desolate_sacred_body_v0_2C"
_METHOD_ID = "METHOD-087"


def _restricted_subpaths_for_path(authority: NonSphereAuthorityService, path_id: str) -> list[str]:
    return [
        row["canonical_id"]
        for row in authority.subpaths.values()
        if row["owning_path_id"] == path_id
        and (row.get("access") or {}).get("access_source_record_required") is True
    ]


def _snapshot_project(catalog_environment) -> tuple[ProjectStore, str, str, str]:
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    created = builder.create_project(
        working_name="REC1 P1CR4 immutable non-sphere snapshot",
        concept="Exact Subpath and Foundation snapshot reconstruction.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={
            "path_choice": [_BODY_PATH, _SPIRIT_PATH],
            "subpath_choice": [_BODY_SUBPATH, _SPIRIT_SUBPATH],
            "foundation_choice": [_FOUNDATION],
        },
    )
    return ProjectStore(db), created["project_id"], _BODY_SUBPATH, _FOUNDATION


@pytest.mark.parametrize("record_kind", ["subpath", "foundation"])
def test_selected_non_sphere_records_reconstruct_from_exact_project_snapshot(catalog_environment, record_kind):
    store, project_id, subpath_id, foundation_id = _snapshot_project(catalog_environment)
    record_id = subpath_id if record_kind == "subpath" else foundation_id
    authority = NonSphereAuthorityService(store.db)
    with store.db.connection() as conn:
        store.project_lock_proof(conn, project_id)
        resolved = store._resolve_locked_record_after_proof(
            conn, project_id, record_id, authority_service=authority
        )

    assert resolved is not None
    assert resolved["record_id"] == record_id
    assert resolved.get("content_type") in {"subpath", "foundation"}
    if record_kind == "subpath":
        assert resolved["owning_path_id"] == _BODY_PATH
        assert resolved["parent_path_id"] == _BODY_PATH
        stage2 = resolved["compatibility"]["factory"]["stage2_authority"]
        assert resolved["owning_path_id"] == resolved["parent_path_id"] == stage2["owning_path_id"] == stage2["parent_path_id"]
        assert stage2["authority_complete"] is True
        assert stage2["allowed_kinds"] == ["subpath_acquisition"]
        assert stage2["allowed_channels"] == ["subpath-selection"]


def test_subpath_snapshot_reconstruction_does_not_reuse_mutated_live_registry(catalog_environment):
    store, project_id, subpath_id, _foundation_id = _snapshot_project(catalog_environment)
    authority = NonSphereAuthorityService(store.db)
    original = authority.subpaths[subpath_id]
    authority.subpaths[subpath_id] = {
        **original,
        "owning_path_id": _SPIRIT_PATH,
        "feature_progression": [],
    }
    try:
        with store.db.connection() as conn:
            store.project_lock_proof(conn, project_id)
            resolved = store._resolve_locked_record_after_proof(
                conn, project_id, subpath_id, authority_service=authority
            )
    finally:
        authority.subpaths[subpath_id] = original

    assert resolved is not None
    assert resolved["owning_path_id"] == _BODY_PATH
    assert resolved["parent_path_id"] == _BODY_PATH
    assert resolved["compatibility"]["factory"]["stage2_authority"]["feature_progression"]


@pytest.mark.parametrize("record_kind", ["subpath", "foundation"])
def test_absent_non_sphere_snapshot_record_fails_closed_without_live_catalog_fallback(catalog_environment, record_kind):
    store, project_id, subpath_id, foundation_id = _snapshot_project(catalog_environment)
    authority = NonSphereAuthorityService(store.db)
    if record_kind == "subpath":
        record_id = next(
            row["canonical_id"]
            for row in authority.subpath_catalog()["records"]
            if row["canonical_id"] not in {subpath_id, foundation_id}
        )
    else:
        record_id = next(
            row["foundation_id"]
            for row in authority.foundation_catalog()["orthodox"]
            if row["foundation_id"] != foundation_id
            and row["foundation_id"].startswith(("ancient_", "FOUNDATION_"))
        )
    # Use a valid live-catalog ID under a project namespace that has no
    # snapshot row.  The resolver must not turn that live match into authority.
    with store.db.connection() as conn:
        assert store._resolve_locked_record_after_proof(conn, "project-without-this-snapshot-row", record_id) is None


@pytest.mark.parametrize("record_kind", ["subpath", "foundation"])
def test_tampered_non_sphere_snapshot_record_is_rejected(catalog_environment, record_kind):
    store, project_id, subpath_id, foundation_id = _snapshot_project(catalog_environment)
    authority = NonSphereAuthorityService(store.db)
    if record_kind == "subpath":
        record_id = next(
            row["canonical_id"]
            for row in authority.subpath_catalog()["records"]
            if row["canonical_id"] not in {subpath_id, foundation_id}
        )
        snapshot = authority.project_locked_subpath_catalog_record(record_id)
    else:
        record_id = next(
            row["foundation_id"]
            for row in authority.foundation_catalog()["orthodox"]
            if row["foundation_id"] != foundation_id
            and row["foundation_id"].startswith(("ancient_", "FOUNDATION_"))
        )
        snapshot = authority.project_locked_foundation_catalog_record(record_id)
    record_id = f"{record_id}.tampered-test"
    snapshot["record_id"] = record_id
    snapshot["display_name"] = "Tampered immutable record"
    with store.db.transaction() as conn:
        conn.execute(
            "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
            (
                project_id,
                record_id,
                "test.non_sphere",
                "test",
                "0" * 64,
                canonical_json(snapshot),
            ),
        )
    with store.db.connection() as conn:
        with pytest.raises(FoundryError) as rejected:
            store._resolve_locked_record_after_proof(conn, project_id, record_id)
    assert rejected.value.code == "PROJECT_LOCK_SNAPSHOT_MISMATCH"


def test_conflicting_subpath_snapshot_ownership_fails_closed(catalog_environment):
    store, project_id, subpath_id, _foundation_id = _snapshot_project(catalog_environment)
    authority = NonSphereAuthorityService(store.db)
    with store.db.connection() as conn:
        row = conn.execute(
            "SELECT record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, subpath_id),
        ).fetchone()
        snapshot = json.loads(row[0])
    snapshot["parent_path_id"] = _SPIRIT_PATH
    with pytest.raises(FoundryError) as rejected:
        authority.project_locked_subpath_catalog_record(subpath_id, snapshot_record=snapshot)
    assert rejected.value.code == "PROJECT_LOCK_SUBPATH_OWNER_MISMATCH"


def test_outer_raw_projection_owner_mirror_fails_after_snapshot_integrity_rehash(catalog_environment):
    store, project_id, subpath_id, _foundation_id = _snapshot_project(catalog_environment)
    authority = NonSphereAuthorityService(store.db)
    with store.db.transaction() as conn:
        row = conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, subpath_id),
        ).fetchone()
        snapshot = json.loads(row["record_json"])
        snapshot["compatibility"]["factory"]["raw_projection"]["owning_path_id"] = _SPIRIT_PATH
        snapshot["record_hash"] = canonical_record_hash(snapshot)
        snapshot_json = canonical_json(snapshot)
        conn.execute("DROP TRIGGER trg_hf2_project_locked_record_no_update")
        conn.execute(
            "UPDATE project_locked_records SET record_hash=?,record_json=? WHERE project_id=? AND record_id=?",
            (snapshot["record_hash"], snapshot_json, project_id, subpath_id),
        )
        conn.execute(
            """
            CREATE TRIGGER trg_hf2_project_locked_record_no_update
            BEFORE UPDATE ON project_locked_records
            BEGIN SELECT RAISE(ABORT,'HF2_PROJECT_LOCKED_RECORD_IMMUTABLE'); END
            """
        )

    with store.db.connection() as conn:
        with pytest.raises(FoundryError) as rejected:
            store._resolve_locked_record_after_proof(
                conn,
                project_id,
                subpath_id,
                authority_service=authority,
            )
    assert rejected.value.code == "PROJECT_LOCK_SUBPATH_OWNER_MISMATCH"
    assert rejected.value.details["owner_sources"]["snapshot_raw_projection_owning_path_id"] == _SPIRIT_PATH


def _fixture_marker_project(root: str, *, source_suffix: str | None = None) -> dict:
    fixture_path = __import__("pathlib").Path(root) / "authority" / "Tianxia_C2AR1_Fixture_Selections_R1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    marker = f"owner-ratified:{fixture['fixture_id']}:{sha256_file(fixture_path)}"
    if source_suffix is not None:
        marker = source_suffix
    prefix = fixture["required_prefix"]
    return {
        "revision": int(prefix["revision"]) + 1,
        "user_locks": [
            {
                "lock_id": f"lock.c2ar1.{index}",
                "field": field,
                "value": value,
                "created_revision": int(prefix["revision"]) + 1,
                "source": marker,
            }
            for index, (field, value) in enumerate({
                "character.identity.display_name": fixture["selections"]["display_name"],
                "character.choices.qi_cultivation_skills": fixture["selections"]["qi_cultivation_skills"],
                "character.choices.street_hardened": fixture["selections"]["street_hardened"],
                "character.choices.language": fixture["selections"]["language"],
            }.items(), start=1)
        ],
    }


def _legacy_subpath_probe_events(event_head: str) -> list[dict]:
    events = [
        {
            "event_id": f"probe.{index}",
            "event_hash": "0" * 64,
            "advancement": {
                "kind": "typed_none",
                "target_cl": 1,
                "details": {"target": "forged_techniques"},
            },
        }
        for index in range(24)
    ]
    events.append({
        "event_id": "probe.subpath",
        "event_hash": event_head,
        "advancement": {
            "kind": "subpath_acquisition",
            "target_cl": 3,
            "details": {},
            "calculation": {"outputs": {}},
        },
        "subject": {"record_id": _BODY_SUBPATH},
    })
    return events


def _completion_probe_state() -> dict:
    state = _state("historical-probe")
    state.update({
        "current_cl": 3,
        "completed_levels": [1, 2, 3],
        "ability_scores": {"STR": 8},
        "background": "background",
        "background_sphere": "background-sphere",
        "background_talent": "background-talent",
        "origin_insight": "origin",
        "paths": [_BODY_PATH],
        "method": {"state": "acquired", "record_id": "method"},
        "foundation": {"state": "acquired", "record_id": "foundation"},
        "recorded_arts": [{"record_id": "manual"}],
        "equipment": ["equipment"],
        "level_talents": {str(cl): [{"record_id": f"talent-{cl}"}] for cl in range(1, 4)},
        "event_occurrences": {"starting_state": [{"event_id": "starting"}]},
        "typed_none_states": {"forged_techniques": {"state": "none", "source_backed": True}},
        "forged_techniques": {"state": "none"},
        "required_milestones": [{
            "milestone_id": "legacy-subpath-milestone",
            "cl": 3,
            "allowed_kinds": ["subpath_acquisition"],
            "count": 1,
            "path_id": _BODY_PATH,
            "feature_kind": "subpath_selection",
        }],
    })
    return state


def test_historical_subpath_milestone_fallback_requires_exact_owner_fixture_marker(catalog_environment):
    service = RulesCausalStage2Service(catalog_environment["db"])
    fixture_path = catalog_environment["settings"].root_dir / "authority" / "Tianxia_C2AR1_Fixture_Selections_R1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    events = _legacy_subpath_probe_events(fixture["required_prefix"]["event_head"])
    state = _completion_probe_state()

    accepted = service._completion_blockers(
        state,
        3,
        events,
        _fixture_marker_project(str(catalog_environment["settings"].root_dir)),
    )
    assert not any(row["code"] == "REQUIRED_PATH_MILESTONE_MISSING" for row in accepted)

    rejected_project = _fixture_marker_project(str(catalog_environment["settings"].root_dir), source_suffix="owner-ratified:wrong-fixture:wrong-hash")
    rejected = service._completion_blockers(state, 3, events, rejected_project)
    assert any(row["code"] == "REQUIRED_PATH_MILESTONE_MISSING" for row in rejected)


def test_historical_subpath_fallback_does_not_use_stage2_parent_mirror_as_owner(catalog_environment):
    service = RulesCausalStage2Service(catalog_environment["db"])
    fixture_path = catalog_environment["settings"].root_dir / "authority" / "Tianxia_C2AR1_Fixture_Selections_R1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    events = _legacy_subpath_probe_events(fixture["required_prefix"]["event_head"])
    state = _completion_probe_state()
    state["authority_snapshots"][_BODY_SUBPATH] = {
        "record": {
            "record_id": _BODY_SUBPATH,
            "compatibility": {"factory": {"stage2_authority": {"parent_path_id": _BODY_PATH}}},
        }
    }
    project = _fixture_marker_project(str(catalog_environment["settings"].root_dir))
    blocked = service._completion_blockers(state, 3, events, project)
    assert not any(row["code"] == "REQUIRED_PATH_MILESTONE_MISSING" for row in blocked)


def test_generic_dual_path_subpath_milestones_require_each_path_owner(catalog_environment):
    service = RulesCausalStage2Service(catalog_environment["db"])
    events = _legacy_subpath_probe_events("generic-subpath-event-head")
    events[-1]["advancement"]["calculation"]["outputs"]["parent_path_id"] = _BODY_PATH
    state = _completion_probe_state()
    state["paths"] = [_BODY_PATH, _SPIRIT_PATH]
    state["authority_snapshots"][_BODY_SUBPATH] = {
        "record": {
            "record_id": _BODY_SUBPATH,
            "owning_path_id": _BODY_PATH,
        }
    }
    state["required_milestones"] = [
        {
            "milestone_id": "body-subpath-milestone",
            "cl": 3,
            "allowed_kinds": ["subpath_acquisition"],
            "count": 1,
            "path_id": _BODY_PATH,
            "feature_kind": "subpath_selection",
        },
        {
            "milestone_id": "spirit-subpath-milestone",
            "cl": 3,
            "allowed_kinds": ["subpath_acquisition"],
            "count": 1,
            "path_id": _SPIRIT_PATH,
            "feature_kind": "subpath_selection",
        },
    ]
    blocked = service._completion_blockers(
        state,
        3,
        events,
        _fixture_marker_project(
            str(catalog_environment["settings"].root_dir),
            source_suffix="generic-project",
        ),
    )
    missing = [row for row in blocked if row["code"] == "REQUIRED_PATH_MILESTONE_MISSING"]
    assert any(row["details"]["milestone"]["path_id"] == _SPIRIT_PATH for row in missing)
    assert not any(row["details"]["milestone"]["path_id"] == _BODY_PATH for row in missing)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parent_path_id", _SPIRIT_PATH),
        ("stage2_owning_path_id", _SPIRIT_PATH),
        ("stage2_parent_path_id", _SPIRIT_PATH),
        ("output_parent_path_id", _SPIRIT_PATH),
    ],
)
def test_projector_subpath_ownership_mirrors_fail_closed(field, value):
    record = {
        "record_id": _BODY_SUBPATH,
        "owning_path_id": _BODY_PATH,
        "parent_path_id": _BODY_PATH,
        "compatibility": {"factory": {"stage2_authority": {
            "owning_path_id": _BODY_PATH,
            "parent_path_id": _BODY_PATH,
        }}},
    }
    event = {
        "event_id": "projector-owner-probe",
        "advancement": {"calculation": {"outputs": {"parent_path_id": _BODY_PATH}}},
    }
    if field == "parent_path_id":
        record["parent_path_id"] = value
    elif field.startswith("stage2_"):
        record["compatibility"]["factory"]["stage2_authority"][field.removeprefix("stage2_")] = value
    else:
        event["advancement"]["calculation"]["outputs"]["parent_path_id"] = value
    with pytest.raises(FoundryError) as rejected:
        _explicit_subpath_owner(event, record)
    assert rejected.value.code == "PROJECTION_SUBPATH_OWNER_MISMATCH"


def test_projector_subpath_owner_is_not_recovered_from_parent_mirror():
    with pytest.raises(FoundryError) as rejected:
        _explicit_subpath_owner(
            {"event_id": "missing-owner"},
            {
                "record_id": _BODY_SUBPATH,
                "compatibility": {"factory": {"stage2_authority": {"parent_path_id": _BODY_PATH}}},
            },
        )
    assert rejected.value.code == "PROJECTION_SUBPATH_OWNER_MISSING"


def _projector_owner_probe_event(event_id: str, owner: str = _BODY_PATH) -> dict:
    return {
        "event_id": event_id,
        "advancement": {"calculation": {"outputs": {"parent_path_id": owner}}},
    }


def _projector_owner_probe_record(record_id: str, owner: str = _BODY_PATH) -> dict:
    return {
        "record_id": record_id,
        "owning_path_id": owner,
        "parent_path_id": owner,
        "compatibility": {"factory": {"stage2_authority": {
            "owning_path_id": owner,
            "parent_path_id": owner,
        }}},
    }


def test_projector_generic_subpath_owner_must_be_selected():
    event = _projector_owner_probe_event("projector-unselected-owner", _SPIRIT_PATH)
    record = _projector_owner_probe_record(_BODY_SUBPATH, _SPIRIT_PATH)
    with pytest.raises(FoundryError) as rejected:
        _validate_generic_subpath_owners(
            [event],
            {event["event_id"]: record},
            [_BODY_PATH],
        )
    assert rejected.value.code == "PROJECTION_SUBPATH_OWNER_NOT_SELECTED"
    assert rejected.value.details["event_id"] == event["event_id"]


def test_projector_generic_subpath_owner_cannot_be_reused():
    first = _projector_owner_probe_event("projector-duplicate-owner-1")
    second = _projector_owner_probe_event("projector-duplicate-owner-2")
    records = {
        first["event_id"]: _projector_owner_probe_record(_BODY_SUBPATH),
        second["event_id"]: _projector_owner_probe_record(_SPIRIT_SUBPATH),
    }
    with pytest.raises(FoundryError) as rejected:
        _validate_generic_subpath_owners(
            [first, second],
            records,
            [_BODY_PATH, _SPIRIT_PATH],
        )
    assert rejected.value.code == "PROJECTION_SUBPATH_OWNER_DUPLICATE"
    assert rejected.value.details["duplicates"][_BODY_PATH] == [first["event_id"], second["event_id"]]


def _subpaths_by_path(authority: NonSphereAuthorityService) -> dict[str, list[str]]:
    result = {path_id: [] for path_id in CANONICAL_PATH_IDS}
    for row in authority.subpath_catalog()["records"]:
        result[row["owning_path_id"]].append(row["canonical_id"])
    return result


def test_method_compatibility_derives_every_canonical_subset_from_all_102_records(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    authority = NonSphereAuthorityService(db)
    canonical_records = authority.method_catalog(initial_creation=True)["records"]
    assert len(canonical_records) == 102

    expected_by_subset = {}
    for size in range(len(CANONICAL_PATH_IDS) + 1):
        for subset in combinations(CANONICAL_PATH_IDS, size):
            required = set(subset)
            expected = sorted(
                row["method_id"]
                for row in canonical_records
                if required.issubset(set(method_granted_path_ids(row)))
            )
            actual = builder.method_compatibility(list(subset))
            actual_ids = sorted(row["method_id"] for row in actual["compatible_methods"])
            expected_by_subset[subset] = expected
            assert actual_ids == expected
            assert all(
                {
                    "direct_access",
                    "access_required",
                    "access_tier",
                    "access_text",
                    "owner_route_options",
                    "exact_lock_configurable",
                }.issubset(row)
                for row in actual["compatible_methods"]
            )

    assert len(expected_by_subset[()]) == 102
    body_spirit = expected_by_subset[(CANONICAL_PATH_IDS[0], CANONICAL_PATH_IDS[2])]
    assert "METHOD-087" in body_spirit


def test_restricted_compatible_method_has_no_access_without_exact_route_or_evidence(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    result = builder.method_compatibility([CANONICAL_PATH_IDS[0], CANONICAL_PATH_IDS[2]])
    restricted = next(row for row in result["compatible_methods"] if row["method_id"] == "METHOD-087")
    assert restricted["access_required"] is True
    assert restricted["direct_access"] is False
    assert restricted["route_configurable"] is True
    assert restricted["access_authorized"] is False
    assert restricted["exact_access_record_present"] is False
    assert restricted["exact_lock_configurable"] is True
    assert restricted["owner_route_options"]

    categories = {row["slot_id"]: row for row in builder.options()["categories"]}
    option = next(row for row in categories["method_choice"]["choices"] if row["choice_id"] == "METHOD-087")
    assert option["method_access"]["access_required"] is True
    assert option["method_access"]["route_configurable"] is True
    assert option["method_access"]["access_authorized"] is False
    assert option["method_access"]["exact_access_record_present"] is False
    assert option["method_access"]["exact_lock_configurable"] is True
    assert option["method_access"]["owner_route_options"]

    created = builder.create_project(
        working_name="Restricted compatibility without access proof",
        concept="The compatible Method must remain fail-closed.",
        target_cl=1,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={"path_choice": [CANONICAL_PATH_IDS[0], CANONICAL_PATH_IDS[2]]},
    )
    prompt = Stage1ClipboardService(db).generate_prompt(created["project_id"])
    delegated = build_delegated_choice_envelope(
        ProjectStore(db).get_project(created["project_id"])["project"],
        prompt,
        execution_mode="MANUAL_CHAT",
        idempotency_key="rec1-p1cr4-access-proof",
    )
    assert "METHOD-087" not in delegated["allowed_choice_ids_by_slot"]["method_choice"]


def test_exact_method_planning_lock_is_frozen_separately_from_access_and_acquisition(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    created = builder.create_project(
        working_name="REC1 P1CR4 exact Method planning lock",
        concept="The exact Method planning lock must remain distinct from acquisition.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={
            "path_choice": [_BODY_PATH, _SPIRIT_PATH],
            "foundation_choice": [_FOUNDATION],
            "method_choice": ["METHOD-087"],
        },
        method_planning_mode="EXACT",
        method_route_choice="route-personal-teacher",
        method_learning_note="The owner selected the advertised personal-teacher route.",
    )
    prompt = Stage1ClipboardService(db).generate_prompt(created["project_id"])
    project = ProjectStore(db).get_project(created["project_id"])["project"]
    envelope = build_delegated_choice_envelope(
        project,
        prompt,
        execution_mode="MANUAL_CHAT",
        idempotency_key="rec1-p1cr4-method-planning-lock",
    )
    planning_lock = envelope["owner_locks"]["planning_by_slot"]["method_choice"]
    assert planning_lock["choice_ids"] == ["METHOD-087"]
    assert planning_lock["mode"] == "EXACT"
    assert planning_lock["planning_authority"] == "owner_locked_planning_selection"
    assert planning_lock["acquisition_authority"] == "server_materialized_after_validated_response"
    assert planning_lock["access_authority"]["present"] is True
    assert envelope["owner_locks"]["by_slot"].get("method_choice") == []


def test_method_087_planning_access_lock_survives_reopen_export_and_clean_import(
    catalog_environment,
    tmp_path: Path,
):
    db = catalog_environment["db"]
    target_settings = Settings.from_env(
        Path(__file__).resolve().parents[1],
        tmp_path / "method-087-clean-import",
    )
    target_db = _clone_catalog_database(db, target_settings)
    builder = CharacterBuilderService(db)
    created = builder.create_project(
        working_name="REC1 P1CR4 METHOD-087 persistence",
        concept="Planning and access metadata must survive the exact project boundary.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={
            "path_choice": [_BODY_PATH, _SPIRIT_PATH],
            "foundation_choice": [_FOUNDATION],
            "method_choice": [_METHOD_ID],
        },
        method_planning_mode="EXACT",
        method_route_choice="route-personal-teacher",
        method_learning_note="The owner selected the advertised personal-teacher route.",
    )
    project_id = created["project_id"]

    source_store = ProjectStore(Database(db.settings))
    reopened_source = source_store.get_project(project_id)
    source_locks = {
        row["field"]: row["value"]
        for row in reopened_source["project"]["user_locks"]
    }
    method_plan = source_locks["character_sheet.method_access_plan"]
    assert source_locks["character_sheet.method_planning_mode"] == "EXACT"
    assert source_locks["character_sheet.planning_preferences"]["method_exact_choice_id"] == _METHOD_ID
    assert method_plan["method_id"] == _METHOD_ID
    assert method_plan["route_type"] == "PERSONAL_TEACHER"
    assert method_plan["route_commitment_sha256"]
    assert method_plan["source_route_sha256"]
    assert method_plan["method_registry_commitment_sha256"]

    prompt = Stage1ClipboardService(Database(db.settings)).generate_prompt(project_id)
    envelope = build_delegated_choice_envelope(
        reopened_source["project"],
        prompt,
        execution_mode="MANUAL_CHAT",
        idempotency_key="rec1-p1cr4-method-087-reopen",
    )
    planning_lock = envelope["owner_locks"]["planning_by_slot"]["method_choice"]
    assert planning_lock["choice_ids"] == [_METHOD_ID]
    assert planning_lock["access_authority"] == {
        "field": "character_sheet.method_access_plan",
        "present": True,
        "method_id": _METHOD_ID,
        "route_type": method_plan["route_type"],
        "route_commitment_sha256": method_plan["route_commitment_sha256"],
    }
    assert planning_lock["acquisition_authority"] == "server_materialized_after_validated_response"
    assert envelope["owner_locks"]["by_slot"].get("method_choice") == []
    assert _METHOD_ID in envelope["offered_choice_ids_by_slot"]["method_choice"]
    assert _METHOD_ID in envelope["allowed_choice_ids_by_slot"]["method_choice"]
    method_access = envelope["path_method_authority"]["method_access_by_id"][_METHOD_ID]
    assert method_access["access_required"] is True
    assert method_access["route_configurable"] is True
    assert method_access["access_authorized"] is False

    state = NonSphereAuthorityService(Database(db.settings)).get_state(project_id)
    assert state["primary_method_id"] is None
    assert _METHOD_ID not in state["known_method_ids"]
    assert not any(
        row.get("authority_type") == "method_access"
        for row in state["access_source_records"]
    )

    export = source_store.export_project(project_id, "rec1-p1cr4-method-087.tianxia-project.zip")
    package = Path(export["path"])
    with zipfile.ZipFile(package) as archive:
        exported_project = json.loads(archive.read("project.json"))
    exported_locks = {
        row["field"]: row["value"]
        for row in exported_project["user_locks"]
    }
    for field in (
        "character_sheet.method_planning_mode",
        "character_sheet.planning_preferences",
        "character_sheet.method_access_plan",
    ):
        assert exported_locks[field] == source_locks[field]

    imported = ProjectStore(target_db).import_project(package)
    assert imported["project_id"] == project_id
    clean_reopened = ProjectStore(Database(target_settings)).get_project(project_id)
    clean_locks = {
        row["field"]: row["value"]
        for row in clean_reopened["project"]["user_locks"]
    }
    assert clean_locks["character_sheet.method_planning_mode"] == "EXACT"
    assert clean_locks["character_sheet.planning_preferences"]["method_exact_choice_id"] == _METHOD_ID
    assert clean_locks["character_sheet.method_access_plan"] == method_plan


def test_dynamic_display_provenance_binds_each_subpath_feature_to_its_own_event():
    def feature(record_id: str) -> dict:
        return {
            "record_id": record_id,
            "record_hash": f"hash-{record_id}",
            "display_name": record_id,
            "content_type": "path_feature",
            "display_projection": {
                "short_description": f"Short {record_id}",
                "full_description": f"Full {record_id}",
            },
            "source": {
                "path": "authority/path.json",
                "anchor": f"feature:{record_id}",
                "source_hash": "a" * 64,
            },
            "compatibility": {
                "factory": {
                    "stage2_authority": {
                        "rule_id": f"rule:{record_id}",
                        "authority_complete": True,
                    }
                }
            },
        }

    contract = _dynamic_display_contract(
        {"project_id": "p", "revision": 4},
        {
            "canonical_project_id": "p",
            "project_revision": 4,
            "snapshot_sha256": "b" * 64,
        },
        {"feature.body": feature("feature.body"), "feature.spirit": feature("feature.spirit")},
        [],
        ["feature.body", "feature.spirit"],
        "packet.primary-subpath",
        {
            "feature.body": [{"event_id": "event.body-subpath", "packet_id": "packet.body-subpath", "target_cl": 3}],
            "feature.spirit": [{"event_id": "event.spirit-subpath", "packet_id": "packet.spirit-subpath", "target_cl": 3}],
        },
    )
    by_id = {row["record_id"]: row for row in contract["rules"]}
    assert by_id["feature.body"]["acquisition_source"] == {
        "target_cl": 3,
        "advancement_kind": "subpath_acquisition",
        "packet_ids": ["packet.body-subpath"],
        "event_ids": ["event.body-subpath"],
    }
    assert by_id["feature.spirit"]["acquisition_source"] == {
        "target_cl": 3,
        "advancement_kind": "subpath_acquisition",
        "packet_ids": ["packet.spirit-subpath"],
        "event_ids": ["event.spirit-subpath"],
    }


def test_three_selected_paths_preserve_three_exact_subpath_bindings(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    authority = NonSphereAuthorityService(db)
    by_path = _subpaths_by_path(authority)
    subpaths = [by_path[path_id][0] for path_id in CANONICAL_PATH_IDS]

    normalized, _ = builder._validated_selections(
        {"path_choice": list(CANONICAL_PATH_IDS), "subpath_choice": subpaths},
        target_cl=3,
    )
    assert normalized["path_choice"] == list(CANONICAL_PATH_IDS)
    assert normalized["subpath_choice"] == subpaths

    with pytest.raises(FoundryError) as duplicate:
        builder._validated_selections(
            {
                "path_choice": list(CANONICAL_PATH_IDS),
                "subpath_choice": [by_path[CANONICAL_PATH_IDS[0]][0], by_path[CANONICAL_PATH_IDS[0]][1]],
            },
            target_cl=3,
        )
    assert duplicate.value.code == "NS1R_MULTIPLE_SUBPATHS_FOR_ONE_PATH"

    created = builder.create_project(
        working_name="REC1 P1CR4 multi-path bindings",
        concept="Three exact Path-owned Subpath bindings.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={"path_choice": list(CANONICAL_PATH_IDS), "subpath_choice": subpaths},
    )
    prompt = Stage1ClipboardService(db).generate_prompt(created["project_id"])
    envelope = prompt["envelope"]
    slots = {row["slot_id"]: row for row in envelope["decision_slots"]}
    assert slots["subpath_choice"]["required_choice_ids"] == subpaths
    assert len(slots["subpath_choice"]["choices"]) == 156
    assert all(
        next(row for row in slots["subpath_choice"]["choices"] if row["choice_id"] == subpath_id)["owning_path_id"] == path_id
        and next(row for row in slots["subpath_choice"]["choices"] if row["choice_id"] == subpath_id)["owning_path_choice_ids"] == [path_id]
        and
        path_id in {
            relation["record_id"]
            for relation in next(row for row in slots["subpath_choice"]["choices"] if row["choice_id"] == subpath_id)["parent_relationships"]
        }
        for path_id, subpath_id in zip(CANONICAL_PATH_IDS, subpaths)
    )
    assert len(envelope["path_method_authority"]["method_access_by_id"]) == 102

    diagnostics = Stage1ClipboardService._decision_diagnostics(
        {
            "decisions": [
                {"slot_id": "path_choice", "state": "selected", "choice_ids": list(CANONICAL_PATH_IDS)},
                {"slot_id": "subpath_choice", "state": "selected", "choice_ids": subpaths},
            ]
        },
        envelope,
    )
    assert not any(row["code"] in {"NS1R_PATH_SUBPATH_MISMATCH", "NS1R_MULTIPLE_SUBPATHS_FOR_ONE_PATH"} for row in diagnostics)

    project = ProjectStore(db).get_project(created["project_id"])["project"]
    delegated = build_delegated_choice_envelope(
        project,
        prompt,
        execution_mode="MANUAL_CHAT",
        idempotency_key="rec1-p1cr4-bindings",
    )
    _validate_path_subpath_bindings(
        delegated,
        {"path_choice": list(CANONICAL_PATH_IDS), "subpath_choice": subpaths},
    )
    with pytest.raises(FoundryError) as mismatch:
        _validate_path_subpath_bindings(
            delegated,
            {"path_choice": [CANONICAL_PATH_IDS[0]], "subpath_choice": [subpaths[1]]},
        )
    assert mismatch.value.code == "CG1_PATH_SUBPATH_MISMATCH"


def test_trusted_initial_restricted_subpath_identity_survives_save_reopen_export_and_import(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    authority = NonSphereAuthorityService(db)
    restricted = _restricted_subpaths_for_path(authority, _QI_PATH)
    assert len(restricted) >= 2
    first, replacement = restricted[:2]

    created = builder.create_project(
        working_name="Trusted restricted initial issuance",
        concept="The trusted Character Builder boundary must retain one exact restricted choice.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={
            "path_choice": [_QI_PATH],
            "subpath_choice": [first],
            "method_choice": ["METHOD-001"],
        },
    )
    project_id = created["project_id"]
    state = created["character_sheet"]["non_sphere_state"]
    assert state["initial_creation_subpath_ids"] == [first]
    assert state["access_source_records"] == []
    assert next(row for row in state["paths"] if row["path_id"] == _QI_PATH)["subpath_or_tradition_id"] == first
    assert state["readiness"]["status"] == "READY"

    saved = authority.save_state(project_id, deepcopy(state), operation="benign_initial_restricted_save")
    reopened = NonSphereAuthorityService(db).get_state(project_id)
    assert saved["initial_creation_subpath_ids"] == reopened["initial_creation_subpath_ids"] == [first]
    assert reopened["access_source_records"] == []
    assert next(row for row in reopened["paths"] if row["path_id"] == _QI_PATH)["subpath_or_tradition_id"] == first

    exported = authority.export_state(project_id)
    validated, _state_hash, _ledger = authority.validate_import_payload(project_id, exported)
    assert validated["initial_creation_subpath_ids"] == [first]
    assert next(row for row in validated["paths"] if row["path_id"] == _QI_PATH)["subpath_or_tradition_id"] == first

    destination = builder.create_project(
        working_name="Trusted restricted import destination",
        concept="The exact same restricted choice identity is locked for import validation.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={
            "path_choice": [_QI_PATH],
            "subpath_choice": [first],
            "method_choice": ["METHOD-001"],
        },
    )
    imported = authority.import_state(destination["project_id"], exported)
    assert imported["initial_creation_subpath_ids"] == [first]
    assert next(row for row in imported["paths"] if row["path_id"] == _QI_PATH)["subpath_or_tradition_id"] == first

    with pytest.raises(FoundryError) as replacement_error:
        authority.select_subpath(project_id, _QI_PATH, replacement)
    assert replacement_error.value.code == "NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED"


def test_raw_restricted_state_cannot_insert_arbitrary_initial_creation_subpath_bypass(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    authority = NonSphereAuthorityService(db)
    restricted = _restricted_subpaths_for_path(authority, _QI_PATH)
    assert restricted
    created = builder.create_project(
        working_name="Raw restricted provenance guard",
        concept="An arbitrary state field must not become trusted provenance.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={"path_choice": [_QI_PATH], "method_choice": ["METHOD-001"]},
    )
    state = authority.get_state(created["project_id"])
    path = next(row for row in state["paths"] if row["path_id"] == _QI_PATH)
    path["subpath_or_tradition_id"] = restricted[0]
    state["initial_creation_subpath_ids"] = [restricted[0]]
    with pytest.raises(FoundryError) as rejected:
        authority.save_state(created["project_id"], state, operation="raw_restricted_provenance_probe")
    assert rejected.value.code == "NS1R_INITIAL_CREATION_STATE_MUTATION_FORBIDDEN"


def test_trusted_initial_provenance_cannot_be_changed_after_persistence(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    authority = NonSphereAuthorityService(db)
    first = _restricted_subpaths_for_path(authority, _QI_PATH)[0]
    created = builder.create_project(
        working_name="Immutable trusted provenance",
        concept="Trusted initial provenance cannot be replaced by raw state mutation.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={
            "path_choice": [_QI_PATH],
            "subpath_choice": [first],
            "method_choice": ["METHOD-001"],
        },
    )
    state = authority.get_state(created["project_id"])
    state["initial_creation_subpath_ids"] = []
    with pytest.raises(FoundryError) as rejected:
        authority.save_state(created["project_id"], state, operation="raw_trusted_provenance_change")
    assert rejected.value.code == "NS1R_INITIAL_CREATION_STATE_MUTATION_FORBIDDEN"


def test_trusted_initial_import_requires_exact_destination_locked_selection(catalog_environment):
    db = catalog_environment["db"]
    builder = CharacterBuilderService(db)
    authority = NonSphereAuthorityService(db)
    first = _restricted_subpaths_for_path(authority, _QI_PATH)[0]
    source = builder.create_project(
        working_name="Trusted import source",
        concept="Source state for exact trusted provenance import.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={
            "path_choice": [_QI_PATH],
            "subpath_choice": [first],
            "method_choice": ["METHOD-001"],
        },
    )
    payload = authority.export_state(source["project_id"])
    destination = builder.create_project(
        working_name="Mismatched trusted import destination",
        concept="Destination does not lock the imported restricted choice.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={"path_choice": [_QI_PATH], "method_choice": ["METHOD-001"]},
    )
    with pytest.raises(FoundryError) as rejected:
        authority.import_state(destination["project_id"], payload)
    assert rejected.value.code == "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID"


def _zip_bytes(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload, mode in entries:
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.external_attr = ((mode if mode is not None else 0o100644) & 0xFFFF) << 16
            archive.writestr(info, payload)
    return output.getvalue()


def test_response_source_provenance_and_transport_failures_are_recoverable(tmp_path):
    service, _provider, _db = make(tmp_path / "provenance")
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="rec1-p1cr4-source")
    payload = _zip_bytes([("../response.json", b"{}", None)])

    with pytest.raises(FoundryError) as rejected:
        service.submit_manual_file(run["run_id"], filename="unsafe.zip", payload=payload)
    assert rejected.value.code == "CG1_MANUAL_RESPONSE_ZIP_PATH_INVALID"

    evidence = service.evidence(run["run_id"])
    provenance = evidence["source_provenance"]
    assert provenance["schema"] == "TianxiaFoundry.CharacterCreationResponseSourceProvenance.v1"
    assert provenance["filename"] == "unsafe.zip"
    assert provenance["archive_sha256"] == sha256_bytes(payload)
    assert evidence["last_submission_error"]["code"] == rejected.value.code
    assert evidence["last_submission_error"]["stage"] == "SOURCE_TRANSPORT"
    assert evidence["attempt_history"][-1]["error"]["stage"] == "SOURCE_TRANSPORT"

    text, receipt = CharacterCreationExecutionService._manual_response_text(
        "reply.json", b"\xef\xbb\xbf  {\"ok\": true} \n"
    )
    assert text == '{"ok": true}'
    assert receipt["source_provenance"]["normalization"]["bom_removed"] is True
    assert receipt["source_provenance"]["normalization"]["outer_whitespace_stripped"] is True
    assert receipt["source_provenance"]["normalization"]["normalized_text_sha256"] == sha256_bytes(text.encode("utf-8"))

    valid_zip = _zip_bytes([("reply.json", text.encode("utf-8"), None)])
    _, valid_receipt = CharacterCreationExecutionService._manual_response_text("reply.zip", valid_zip)
    valid_provenance = valid_receipt["source_provenance"]
    assert valid_provenance["archive_sha256"] == sha256_bytes(valid_zip)
    assert valid_provenance["member_filename"] == "reply.json"
    assert valid_provenance["archive_members"][0]["sha256"] == sha256_bytes(text.encode("utf-8"))

    with pytest.raises(FoundryError) as link:
        CharacterCreationExecutionService._manual_response_text(
            "link.zip", _zip_bytes([("reply.json", b"{}", stat.S_IFLNK | 0o777)])
        )
    assert link.value.code == "CG1_MANUAL_RESPONSE_ZIP_LINK_REJECTED"

    with pytest.raises(FoundryError) as collision:
        CharacterCreationExecutionService._manual_response_text(
            "collision.zip", _zip_bytes([("reply.json", b"{}", None), ("REPLY.JSON", b"{}", None)])
        )
    assert collision.value.code == "CG1_MANUAL_RESPONSE_ZIP_MEMBER_COLLISION"

    with pytest.raises(FoundryError) as ambiguous:
        CharacterCreationExecutionService._manual_response_text(
            "ambiguous.zip", _zip_bytes([("reply.json", b"{}", None), ("notes.md", b"{}", None)])
        )
    assert ambiguous.value.code == "CG1_MANUAL_RESPONSE_ZIP_CONTENT_INVALID"

    with pytest.raises(FoundryError) as encoding:
        CharacterCreationExecutionService._manual_response_text("bad.json", b"\xff\xfe")
    assert encoding.value.code == "CG1_MANUAL_RESPONSE_ENCODING_INVALID"

    with pytest.raises(FoundryError) as oversize:
        CharacterCreationExecutionService._manual_response_text("large.json", b"x" * 2_000_001)
    assert oversize.value.code == "CG1_MANUAL_RESPONSE_TOO_LARGE"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("CG1_MANUAL_RESPONSE_ZIP_PATH_INVALID", "SOURCE_TRANSPORT"),
        ("CG1_PLAN_JSON_INVALID", "JSON_SCHEMA"),
        ("CG1_COMPLETE_RESPONSE_REQUEST_HASH_MISMATCH", "REQUEST_BINDING"),
        ("CG1_AUTHORITY_SHAPE_UNRESOLVED", "SEMANTIC_AUTHORITY"),
        ("CG1_PATH_SUBPATH_MISMATCH", "LEGALITY"),
        ("CG1_STAGE2_INVALID", "COMPILATION"),
        ("SOME_NEW_UNKNOWN_DIAGNOSTIC", "VALIDATION"),
    ],
)
def test_diagnostic_stage_uses_exact_authoritative_code_table(code, expected):
    assert CharacterCreationExecutionService._diagnostic_stage(code) == expected


def test_diagnostic_stage_does_not_classify_unknown_substrings_as_authoritative():
    assert CharacterCreationExecutionService._diagnostic_stage("UNRELATED_PATH_REQUEST") == "VALIDATION"


def test_attempt_history_retains_project_when_temporary_discard_is_requested(tmp_path):
    service, _provider, db = make(tmp_path / "retention")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO character_builder_project_lifecycle(project_id,persistence_state,lifecycle_source,created_at,updated_at) VALUES(?,?,?,?,?)",
            ("p", "temporary", "test", "now", "now"),
        )
        conn.execute(
            "INSERT INTO character_creation_runs(run_id,project_id,starting_revision,execution_mode,idempotency_key,request_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("retained-run", "p", 0, "MANUAL_CHAT", "retained-run-key", "{}", "CANCELLED", "now", "now"),
        )
    service._append_attempt("retained-run", action_type="CANCEL_BUILD", status="CANCELLED")

    result = ProjectStore(db).discard_temporary_project("p", reason="test-retain-history")
    assert result["discarded"] is True
    assert result["retained"] is True
    assert result["retention"] == "attempt_history"
    with db.connection() as conn:
        assert conn.execute("SELECT 1 FROM projects WHERE project_id='p'").fetchone() is not None
        state = conn.execute(
            "SELECT persistence_state FROM character_builder_project_lifecycle WHERE project_id='p'"
        ).fetchone()
        assert state["persistence_state"] == "saved_draft"
        assert conn.execute(
            "SELECT 1 FROM character_creation_attempt_history WHERE project_id='p'"
        ).fetchone() is not None
