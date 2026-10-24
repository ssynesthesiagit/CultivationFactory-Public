"""Version selection must not replace immutable Method source snapshots.

All projects and events here are deterministic scratch fixtures, not local-model
acceptance. Historical requests deliberately use the pre-mechanics input shape.
"""
from copy import deepcopy
from pathlib import Path
import json
import zipfile

import pytest

from app.core import FoundryError, Settings, canonical_json, sha256_bytes
from character_creation.response_materialization import CanonicalSelectionIntent
from contracts.canonical import ZERO_HASH, canonical_event_hash, canonical_project_hash, canonical_record_hash
from non_sphere_authority.service import NonSphereAuthorityService
from projector.method_mechanics import project_initial_method_mechanics
from projector.service import ProjectionService
from projector.v3_bridge import _validate_binding
from project_store.service import ProjectStore
from stage2.service import RulesCausalStage2Service, _state
from tests.test_cat3_p1r_persistence import _clone_catalog_database
from tests.test_creation_training_r4 import _real_creation_intent
from tests.test_rec1_p1cr5_owner_authority import _private_scope


def _method_snapshots(creator, project_id):
    with creator.db.connection() as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT record_id,pack_id,pack_version,record_hash,record_json "
            "FROM project_locked_records WHERE project_id=? AND record_id LIKE 'METHOD-%' ORDER BY record_id",
            (project_id,),
        )]


@pytest.fixture(scope="module")
def historical_method_project(catalog_environment):
    # Recreate the historical source-record/request format through the real
    # catalog and builder, without reading or rewriting retained owner data.
    original = NonSphereAuthorityService.project_locked_method_catalog_record

    def legacy_projection(self, method_id, *, snapshot_record=None, mechanical=False):
        return original(self, method_id, snapshot_record=snapshot_record, mechanical=False)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(NonSphereAuthorityService, "project_locked_method_catalog_record", legacy_projection)
        creator, project, run, intent, extra = _real_creation_intent(catalog_environment)
    request = deepcopy(run["request"])
    request["server_owned_authority"].pop("initial_method_mechanics_policy")
    request["request_sha256"] = creator.request_payload_sha256(request)
    request["server_owned_authority"]["output_profile"]["binding"]["request_sha256"] = request["request_sha256"]
    with creator.db.transaction() as conn:
        conn.execute("UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
                     (canonical_json(request), run["run_id"]))
    run = {**run, "request": request}
    return creator, project, run, intent, extra


def _revised_request(creator, project):
    return creator._complete_request(
        project["project_id"], revision_request={"reason": "Rebuild with explicitly versioned Method mechanics"},
        execution_mode="MANUAL_CHAT", idempotency_key="method-version-revision",
    )


def test_revised_request_preserves_packed_and_old_extra_method_bytes(historical_method_project):
    creator, project, run, _, _ = historical_method_project
    before = _method_snapshots(creator, project["project_id"])
    by_id = {row[0]: row for row in before}
    assert by_id["METHOD-001"][1] != "tianxia.non_sphere.authority"
    assert by_id["METHOD-083"][2] == "0.6"
    request = _revised_request(creator, project)
    assert request["server_owned_authority"]["initial_method_mechanics_policy"]
    assert request["request_sha256"] != run["request"]["request_sha256"]
    assert _method_snapshots(creator, project["project_id"]) == before
    with creator.db.connection() as conn:
        assert conn.execute("SELECT request_json FROM character_creation_runs WHERE run_id=?",
                            (run["run_id"],)).fetchone()[0] == canonical_json(run["request"])


def _initial_method_events(creator, project, run, intent, method_id, path_ids):
    document = intent.as_dict()
    document["selected_by_slot"]["method_choice"] = [method_id]
    document["selected_by_slot"]["path_choice"] = path_ids
    document["bounded_choices"]["path_progression_by_cl"] = {"1": path_ids[0]}
    rows = creator._derive_stage2_rows_from_frozen_authority(
        run, project, CanonicalSelectionIntent.from_document(document),
    )
    first_level = next(i for i, row in enumerate(rows) if row["kind"] == "level_advance")
    stage2 = RulesCausalStage2Service(creator.db)
    proposal = {
        "project_id": project["project_id"], "proposal_id": f"method-version-pipeline.{run['run_id']}.{method_id}",
        "expected_project_revision": project["revision"], "idempotency_key": "method-version-pipeline",
        "created_at": "2026-09-07T00:00:00+00:00",
    }
    state = _state(project["project_id"])
    events = []
    record_cache = {}
    with _private_scope(stage2, run["request"], run["run_id"], set(path_ids)), creator.db.connection() as conn:
        creator.projects.project_lock_proof(conn, project["project_id"])
        for index, choice in enumerate(rows[:first_level + 1]):
            event, state, blockers = stage2._choice_event(
                conn=conn, row=proposal, project=project, state=state, choice=choice,
                index=index, sequence=index + 1,
                previous_hash=events[-1]["event_hash"] if events else ZERO_HASH, generic_prefix=events,
                record_cache=record_cache,
            )
            assert not blockers, (choice["kind"], blockers)
            assert event is not None
            events.append(event)
    return stage2, events, state


def test_packed_method_uses_new_policy_in_real_stage2(catalog_environment):
    creator, project, run, intent, _ = _real_creation_intent(catalog_environment)
    before = _method_snapshots(creator, project["project_id"])
    _, events, state = _initial_method_events(
        creator, project, run, intent, "METHOD-001", ["tianxia.path.qi_cultivation"],
    )
    activation = next(event for event in events if event["advancement"]["kind"] == "method_activation")
    assert activation["content_binding"]["pack_version"] == "0.6.0-mechanics.1"
    assert state["method"]["state"] == "active"
    # METHOD-001 is explicitly Neutral, including after activation.
    assert state["resources"]["tianxia.resource.qi"]["method_delta"] == 0
    assert _method_snapshots(creator, project["project_id"]) == before


@pytest.mark.parametrize("method_id", ["METHOD-001", "METHOD-083"])
def test_historical_method_resolution_and_bytes_remain_legacy(historical_method_project, method_id):
    creator, project, run, _, _ = historical_method_project
    with creator.db.connection() as conn:
        creator.projects.project_lock_proof(conn, project["project_id"])
        record = creator.projects._resolve_locked_record_after_proof(conn, project["project_id"], method_id)
        expected = NonSphereAuthorityService(creator.db).project_locked_method_catalog_record(method_id)
        assert record == expected
        assert record["content_binding"]["pack_version"] == "0.6"
        creator.projects._assert_snapshot_record(conn, project["project_id"], record)
    assert "initial_method_mechanics_policy" not in run["request"]["server_owned_authority"]


@pytest.mark.parametrize("version", ["0.6.0-mechanics.1", "99.0.0"])
def test_rehashed_version_cannot_upgrade_ordinary_snapshot_authority(historical_method_project, version):
    creator, project, _, _, _ = historical_method_project
    record = NonSphereAuthorityService(creator.db).project_locked_method_catalog_record("METHOD-083")
    record["content_binding"]["pack_version"] = version
    record["record_hash"] = canonical_record_hash(record)
    with creator.db.connection() as conn:
        creator.projects.project_lock_proof(conn, project["project_id"])
        with pytest.raises(FoundryError, match="snapshot"):
            creator.projects._assert_snapshot_record(conn, project["project_id"], record)


def _persist_request(creator, original_run, request, suffix):
    run_id = original_run["run_id"] + suffix
    with creator.db.transaction() as conn:
        conn.execute(
            "INSERT INTO character_creation_runs(run_id,project_id,starting_revision,execution_mode,"
            "idempotency_key,request_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (run_id, request["project_id"], request["project_revision"], "MANUAL_CHAT", suffix,
             canonical_json(request), "WAITING_FOR_RESPONSE", "2026-09-07T00:00:00+00:00", "2026-09-07T00:00:00+00:00"),
        )
    return {**original_run, "run_id": run_id, "request": request}


def test_old_extra_method_activates_on_revised_request_with_private_proof(historical_method_project):
    creator, project, old_run, intent, _ = historical_method_project
    before = _method_snapshots(creator, project["project_id"])
    request = _revised_request(creator, project)
    run = _persist_request(creator, old_run, request, ".revised-method")
    paths = ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"]
    stage2, events, state = _initial_method_events(creator, project, run, intent, "METHOD-083", paths)
    assert state["resources"]["tianxia.resource.stamina"]["method_delta"] == -2
    assert state["resources"]["tianxia.resource.resonance"]["method_delta"] == 2
    method = NonSphereAuthorityService(creator.db).project_locked_method_catalog_record("METHOD-083", mechanical=True)
    with _private_scope(stage2, request, run["run_id"], set(paths)), creator.db.connection() as conn:
        stage2._assert_record_after_proof(conn, project["project_id"], method)
    # A correct-looking request/hash cannot manufacture the private durable run.
    with _private_scope(stage2, request, run["run_id"] + ".forged", set(paths)), creator.db.connection() as conn:
        with pytest.raises(FoundryError):
            stage2._assert_record_after_proof(conn, project["project_id"], method)
    assert _method_snapshots(creator, project["project_id"]) == before
    mixed_bindings = [event["content_binding"] for event in events if event["subject"]["record_id"] == "METHOD-083"]
    mixed_bindings[-1] = {**mixed_bindings[-1], "pack_version": "0.6"}
    with creator.db.connection() as conn, pytest.raises(FoundryError):
        creator.projects._resolve_event_bound_method_after_proof(conn, project["project_id"], "METHOD-083", mixed_bindings)


def _persist_events(creator, project, events):
    with creator.db.transaction() as conn:
        for event in events:
            conn.execute(
                "INSERT INTO events(project_id,sequence_no,event_id,event_hash,previous_event_hash,created_at,"
                "event_json,legacy_event_hash,canonical_schema_version,contract_status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (project["project_id"], event["sequence"], event["event_id"], event["event_hash"],
                 event["previous_event_hash"], event["created_at"], canonical_json(event), None, event["schema_version"], "valid"),
            )
        replay = creator.projects._replay_events(conn, project["project_id"])
        creator.projects._update_project_after_commit(conn, project["project_id"], replay)
    return replay


def _forged_event_version_package(original, target, method_id, version, record_hash=None):
    with zipfile.ZipFile(original) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    events = json.loads(files["events.json"])
    previous = ZERO_HASH
    for event in events:
        if event["subject"]["record_id"] == method_id:
            event["content_binding"]["pack_version"] = version
            if record_hash is not None:
                event["content_binding"]["record_hash"] = record_hash
        event["previous_event_hash"] = previous
        event["event_hash"] = canonical_event_hash(event)
        previous = event["event_hash"]
    project = json.loads(files["project.json"])
    project["event_stream"]["head_hash"] = previous
    replay = json.loads(files["replay.json"])
    replay["latest_event_hash"] = previous
    for name, value in [("project.json", project), ("events.json", events), ("replay.json", replay)]:
        files[name] = canonical_json(value).encode()
    manifest = json.loads(files["manifest.json"])
    manifest["canonical_project_hash"] = canonical_project_hash(project)
    manifest["latest_event_hash"] = previous
    manifest["files"] = {name: sha256_bytes(data) for name, data in files.items()
                         if name not in {"manifest.json", "SHA256SUMS.txt"}}
    files["manifest.json"] = canonical_json(manifest).encode()
    files["SHA256SUMS.txt"] = "".join(f"{digest}  {name}\n" for name, digest in sorted(manifest["files"].items())).encode()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)


@pytest.mark.parametrize("method_id,paths", [
    ("METHOD-001", ["tianxia.path.qi_cultivation"]),
    ("METHOD-083", ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"]),
])
def test_event_bound_projection_and_import_preserve_original_sources(catalog_environment, tmp_path, method_id, paths):
    destination = _clone_catalog_database(
        catalog_environment["db"], Settings.from_env(catalog_environment["db"].settings.root_dir, tmp_path / "destination"),
    )
    creator, project, run, intent, _ = _real_creation_intent(catalog_environment)
    source_bytes = _method_snapshots(creator, project["project_id"])
    stage2, events, _ = _initial_method_events(creator, project, run, intent, method_id, paths)
    replay = _persist_events(creator, project, events)
    with _private_scope(stage2, run["request"], run["run_id"], set(paths)):
        projected_project, projected_events, records, _ = ProjectionService(creator.db)._inputs(
            project["project_id"], private_record_resolver=stage2._resolve_record_after_proof,
        )
    method = NonSphereAuthorityService(creator.db).project_locked_method_catalog_record(method_id, mechanical=True)
    assert records[method_id] == method
    for event in projected_events:
        if event["subject"]["record_id"] == method_id:
            _validate_binding(event, method, projected_project, locked_records=records)
    exported = creator.projects.export_project(project["project_id"])
    store = ProjectStore(destination)
    legacy_hash = NonSphereAuthorityService(creator.db).project_locked_method_catalog_record(method_id)["record_hash"]
    for version in ["99.0.0", "0.6"]:
        forged = tmp_path / f"forged-{version}.zip"
        _forged_event_version_package(Path(exported["path"]), forged, method_id, version,
                                     record_hash=legacy_hash if version == "0.6" else None)
        with pytest.raises(FoundryError) as exc:
            store.import_project(forged)
        assert exc.value.code in {"NS1R_METHOD_MECHANICS_VERSION_INVALID", "PROJECT_METHOD_EVENT_VERSION_MISMATCH",
                                  "PROJECTION_METHOD_MECHANICS_INVALID"}
        with destination.connection() as conn:
            assert conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project["project_id"],)).fetchone() is None
    result = store.import_project(Path(exported["path"]))
    assert result["state_hash"] == replay["state_hash"]
    assert result["latest_event_hash"] == events[-1]["event_hash"]
    with destination.connection() as conn:
        store.project_lock_proof(conn, project["project_id"])
        bindings = [event["content_binding"] for event in events if event["subject"]["record_id"] == method_id]
        imported = store._resolve_event_bound_method_after_proof(conn, project["project_id"], method_id, bindings)
        snapshots = [tuple(row) for row in conn.execute(
            "SELECT record_id,pack_id,pack_version,record_hash,record_json FROM project_locked_records "
            "WHERE project_id=? AND record_id LIKE 'METHOD-%' ORDER BY record_id", (project["project_id"],),
        )]
    assert imported == method
    assert snapshots == source_bytes
    projection = project_initial_method_mechanics(destination.settings.root_dir, imported, events,
                                                 {event["event_id"]: "packet-" + event["event_id"] for event in events})
    assert projection["state"] == "active"


def test_historical_events_and_projection_hash_do_not_change_on_revision(historical_method_project):
    creator, project, run, intent, _ = historical_method_project
    paths = ["tianxia.path.qi_cultivation"]
    stage2, events, _ = _initial_method_events(creator, project, run, intent, "METHOD-001", paths)
    assert not any(event["advancement"]["kind"] == "method_activation" for event in events)
    replay = _persist_events(creator, project, events)
    with _private_scope(stage2, run["request"], run["run_id"], set(paths)):
        before = ProjectionService(creator.db)._inputs(project["project_id"], private_record_resolver=stage2._resolve_record_after_proof)
        _revised_request(creator, creator.projects.get_project(project["project_id"])["project"])
        after = ProjectionService(creator.db)._inputs(project["project_id"], private_record_resolver=stage2._resolve_record_after_proof)
    assert before == after
    assert after[2]["METHOD-001"]["content_binding"]["pack_version"] == "0.6"
    assert creator.projects.replay(project["project_id"])["state_hash"] == replay["state_hash"]
    assert creator.projects.timeline(project["project_id"]) == events
