from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_json
from catalog.service import CatalogService
from character_builder import CharacterBuilderService
from character_creation.choice_snapshot import materialize_choice_snapshot
from character_creation.compiler_selection_authority import build_compiler_selection_authority
from character_creation.delegated_choice_authority import build_delegated_choice_envelope
from character_creation.owner_decision_authority import enrich_milestone_details
from character_creation.response_materialization import CanonicalSelectionIntent
from character_creation.service import CharacterCreationExecutionService
import character_creation.service as creation_service
from character_creation.stage1_first_compile import compile_once_stage1_first
from contracts.canonical import canonical_project_hash, canonical_record_hash
from non_sphere_authority import NonSphereAuthorityService
from portable_character import PortableCharacterPackageService
from portable_character.service import PROJECT_MEMBER
from project_store.service import ProjectStore
from projector.service import ProjectionService
from security.integrity import IntegrityService, create_test_integrity_service
from stage1.service import Stage1ClipboardService
from stage2.service import (
    RulesCausalStage2Service,
    _CharacterCreationPathAuthorityHandoff,
    _INITIAL_CREATION_HANDOFF_ISSUER,
    _TRUSTED_CHARACTER_CREATION_EXECUTION,
)
from tests.test_cat3_p1r_persistence import _clone_catalog_database
from vendor_adapter.service import FactoryAdapter


_BODY_PATH = "tianxia.path.body_refining"
_QI_PATH = "tianxia.path.qi_cultivation"


@pytest.fixture(scope="module")
def _rec1_p1cr5_test_integrity():
    service = create_test_integrity_service(b"REC1-P1CR5-owner-authority")
    descriptor = IntegrityService.__dict__["for_database"]
    IntegrityService.for_database = classmethod(lambda _cls, _db: service)
    try:
        yield service
    finally:
        IntegrityService.for_database = descriptor


@pytest.fixture(scope="module")
def catalog_environment(factory_zip, tmp_path_factory, _rec1_p1cr5_test_integrity):
    root = Path(__file__).resolve().parents[1]
    reusable_data = os.environ.get("REC1_P1CR5_TEST_DATA_DIR")
    data = Path(reusable_data).resolve() if reusable_data else tmp_path_factory.mktemp("rec1_p1cr5_catalog")
    settings = Settings.from_env(root, data)
    db = Database(settings)
    if not reusable_data:
        db.migrate()
    adapter = FactoryAdapter(db)
    if reusable_data:
        return {
            "settings": settings,
            "db": db,
            "adapter": adapter,
            "root": None,
            "report": None,
        }
    configured = adapter.configure(factory_zip)
    catalog = CatalogService(db, integrity=_rec1_p1cr5_test_integrity)
    report = catalog.rebuild_core(Path(configured["factory_root"]))
    return {
        "settings": settings,
        "db": db,
        "adapter": adapter,
        "root": Path(configured["factory_root"]),
        "report": report,
    }


def _path_authority_fixture(catalog_environment, *, selections=None):
    db = catalog_environment["db"]
    created = CharacterBuilderService(db).create_project(
        working_name="REC1 P1CR5 delegated Path authority",
        concept="Frozen delegated Path authority regression.",
        target_cl=1,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={} if selections is None else selections,
        generation_route="ai_bootstrap",
    )
    project_id = created["project_id"]
    prompt = Stage1ClipboardService(db).generate_prompt(project_id)
    store = ProjectStore(db)
    project = store.get_project(project_id)["project"]
    # A real Stage 1 prompt must carry the server-built compiler-selection
    # authority; build it from server settings and the exact project lock the
    # same way CharacterCreationExecutionService does.
    compiler_authority_service = NonSphereAuthorityService(db)
    compiler_selection_authority = build_compiler_selection_authority(
        db.settings.vendor_dir,
        content_lock=project.get("content_lock") or {},
        method_records=compiler_authority_service.method_catalog(initial_creation=True)["records"],
        foundation_records=compiler_authority_service.foundation_catalog()["orthodox"],
    )
    envelope = build_delegated_choice_envelope(
        project,
        prompt,
        execution_mode="MANUAL_CHAT",
        idempotency_key="rec1-p1cr5-path-authority",
        compiler_selection_authority=compiler_selection_authority,
    )
    assert envelope is not None
    return db, store, project_id, project, envelope


def _stage2_authority(record):
    return (record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}


def _private_creation_run(catalog_environment, *, status: str = "WAITING_FOR_RESPONSE"):
    db, store, project_id, _project, envelope = _path_authority_fixture(catalog_environment)
    creator = CharacterCreationExecutionService(
        db,
        stage1=Stage1ClipboardService(db),
        provider=None,
        project_store=store,
    )
    request = creator._complete_request(
        project_id,
        execution_mode="MANUAL_CHAT",
        idempotency_key=f"rec1-p1cr5-private-scope:{project_id}",
    )
    assert request["delegated_choice_envelope"]["schema"] == envelope["schema"]
    assert request["delegated_choice_envelope"]["binding"]["project_id"] == project_id
    run_id = f"cg1.test.rec1-p1cr5-private-scope.{project_id}"
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
                f"rec1-p1cr5-private-scope:{project_id}",
                canonical_json(request),
                status,
                "2026-08-17T00:00:00+00:00",
                "2026-08-17T00:00:00+00:00",
            ),
        )
    return db, store, project_id, request, run_id


def _private_scope(stage2, request, run_id, path_ids):
    return stage2._trusted_character_creation_scope(
        run_id=run_id,
        project_id=request["project_id"],
        starting_revision=request["project_revision"],
        content_lock_hash=request["content_lock_hash"],
        typed_choice_snapshot_sha256=request["typed_choice_snapshot"]["snapshot_sha256"],
        request_sha256=request["request_sha256"],
        authorized_delegated_path_ids=path_ids,
        phase="scratch_compile",
        candidate_identity=None,
        _server_authority=_TRUSTED_CHARACTER_CREATION_EXECUTION,
    )


def _finalization_scope(stage2, request, run_id, path_ids, candidate_identity):
    return stage2._trusted_character_creation_scope(
        run_id=run_id,
        project_id=request["project_id"],
        starting_revision=request["project_revision"],
        content_lock_hash=request["content_lock_hash"],
        typed_choice_snapshot_sha256=request["typed_choice_snapshot"]["snapshot_sha256"],
        request_sha256=request["request_sha256"],
        authorized_delegated_path_ids=path_ids,
        phase="finalization",
        candidate_identity=candidate_identity,
        _server_authority=_TRUSTED_CHARACTER_CREATION_EXECUTION,
    )


def _finalized_creation_run(catalog_environment):
    db, store, project_id, request, run_id = _private_creation_run(
        catalog_environment,
        status="CLEAN_AND_FINALIZED",
    )
    project = store.get_project(project_id)["project"]
    candidate_identity = f"candidate-finalized-{project_id}"
    package_sha256 = "a" * 64
    output = {
        "portable_character": {
            "package_sha256": package_sha256,
            "audit": {"sha256": package_sha256, "valid": True},
            "registration": {
                "package_sha256": package_sha256,
                "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
            },
            "clean_import": {
                "first": {
                    "package_sha256": package_sha256,
                    "status": "IMPORTED",
                    "imported": True,
                    "project_id": project_id,
                },
                "second": {
                    "package_sha256": package_sha256,
                    "status": "ALREADY_INSTALLED_IDENTICAL",
                    "imported": False,
                    "project_id": project_id,
                },
            },
        }
    }
    commit = {
        "schema": "TianxiaFoundry.CharacterCreationCanonicalCommit.v2",
        "approved_candidate_identity": candidate_identity,
        "typed_choice_snapshot_sha256": request["typed_choice_snapshot"]["snapshot_sha256"],
        "outputs": {"portable_character": sha256_json(output["portable_character"])},
    }
    quality = {"status": "CLEAN", "candidate_identity": candidate_identity}
    with db.transaction() as conn:
        conn.execute(
            """UPDATE character_creation_runs
               SET dry_run_json=?, quality_json=?, commit_json=?, final_revision=?, output_json=?
               WHERE run_id=?""",
            (
                canonical_json({"candidate_identity": candidate_identity}),
                canonical_json(quality),
                canonical_json(commit),
                project["revision"],
                canonical_json(output),
                run_id,
            ),
        )
    return {
        "db": db,
        "store": store,
        "project_id": project_id,
        "project": project,
        "request": request,
        "run_id": run_id,
        "candidate_identity": candidate_identity,
        "quality": quality,
        "commit": commit,
        "output": output,
    }


def _validated_finalized_path_ids(fixture):
    stage2 = RulesCausalStage2Service(fixture["db"])
    with _finalization_scope(
        stage2,
        fixture["request"],
        fixture["run_id"],
        {_BODY_PATH},
        fixture["candidate_identity"],
    ):
        with fixture["db"].connection() as conn:
            return stage2._validated_initial_creation_delegated_path_ids(
                conn,
                fixture["project_id"],
                _BODY_PATH,
            )


def test_private_stage2_scope_accepts_exact_clean_finalized_history(catalog_environment) -> None:
    fixture = _finalized_creation_run(catalog_environment)

    assert _validated_finalized_path_ids(fixture) == frozenset({_BODY_PATH})


def test_private_stage2_scope_rejects_tampered_clean_finalized_history(catalog_environment) -> None:
    fixture = _finalized_creation_run(catalog_environment)
    variants = (
        "final_revision_mismatch",
        "project_revision_mismatch",
        "candidate_mismatch",
        "quality_candidate_mismatch",
        "commit_snapshot_mismatch",
        "commit_schema_mismatch",
        "package_hash_mismatch",
        "coherent_output_replacement",
        "audit_invalid",
        "first_import_mismatch",
        "second_import_mismatch",
        "registration_mismatch",
    )

    for variant in variants:
        with fixture["db"].transaction() as conn:
            if variant == "final_revision_mismatch":
                conn.execute(
                    "UPDATE character_creation_runs SET final_revision=? WHERE run_id=?",
                    (fixture["project"]["revision"] + 1, fixture["run_id"]),
                )
            elif variant == "project_revision_mismatch":
                conn.execute(
                    "UPDATE projects SET revision=? WHERE project_id=?",
                    (fixture["project"]["revision"] + 1, fixture["project_id"]),
                )
            elif variant == "candidate_mismatch":
                conn.execute(
                    "UPDATE character_creation_runs SET dry_run_json=? WHERE run_id=?",
                    (canonical_json({"candidate_identity": "different-candidate"}), fixture["run_id"]),
                )
            elif variant == "quality_candidate_mismatch":
                conn.execute(
                    "UPDATE character_creation_runs SET quality_json=? WHERE run_id=?",
                    (canonical_json({"status": "CLEAN", "candidate_identity": "different-candidate"}), fixture["run_id"]),
                )
            elif variant == "commit_snapshot_mismatch":
                tampered_commit = deepcopy(fixture["commit"])
                tampered_commit["typed_choice_snapshot_sha256"] = "b" * 64
                conn.execute(
                    "UPDATE character_creation_runs SET commit_json=? WHERE run_id=?",
                    (canonical_json(tampered_commit), fixture["run_id"]),
                )
            elif variant == "commit_schema_mismatch":
                tampered_commit = deepcopy(fixture["commit"])
                tampered_commit["schema"] = "TianxiaFoundry.CharacterCreationCanonicalCommit.invalid"
                conn.execute(
                    "UPDATE character_creation_runs SET commit_json=? WHERE run_id=?",
                    (canonical_json(tampered_commit), fixture["run_id"]),
                )
            else:
                tampered_output = deepcopy(fixture["output"])
                portable = tampered_output["portable_character"]
                if variant == "package_hash_mismatch":
                    portable["registration"]["package_sha256"] = "b" * 64
                elif variant == "audit_invalid":
                    portable["audit"]["valid"] = False
                elif variant == "first_import_mismatch":
                    portable["clean_import"]["first"]["status"] = "ALREADY_INSTALLED_IDENTICAL"
                elif variant == "second_import_mismatch":
                    portable["clean_import"]["second"]["imported"] = True
                elif variant == "coherent_output_replacement":
                    replacement_sha256 = "b" * 64
                    portable["package_sha256"] = replacement_sha256
                    portable["audit"]["sha256"] = replacement_sha256
                    portable["registration"]["package_sha256"] = replacement_sha256
                    portable["clean_import"]["first"]["package_sha256"] = replacement_sha256
                    portable["clean_import"]["second"]["package_sha256"] = replacement_sha256
                else:
                    portable["registration"]["status"] = "NOT_VERIFIED"
                conn.execute(
                    "UPDATE character_creation_runs SET output_json=? WHERE run_id=?",
                    (canonical_json(tampered_output), fixture["run_id"]),
                )
        assert _validated_finalized_path_ids(fixture) is None, variant

        with fixture["db"].transaction() as conn:
            conn.execute(
                "UPDATE projects SET revision=? WHERE project_id=?",
                (fixture["project"]["revision"], fixture["project_id"]),
            )
            conn.execute(
                """UPDATE character_creation_runs
                   SET dry_run_json=?, quality_json=?, commit_json=?, final_revision=?, output_json=?
                   WHERE run_id=?""",
                (
                    canonical_json({"candidate_identity": fixture["candidate_identity"]}),
                    canonical_json(fixture["quality"]),
                    canonical_json(fixture["commit"]),
                    fixture["project"]["revision"],
                    canonical_json(fixture["output"]),
                    fixture["run_id"],
                ),
            )


@pytest.fixture
def _workspace_tmp_path():
    with tempfile.TemporaryDirectory(
        prefix=".rec1-p1cr5-handoff-",
        dir=Path(__file__).resolve().parents[2],
    ) as directory:
        yield Path(directory)


def test_clean_import_path_handoff_reproduces_loss_then_proves_first_and_identical_reimport(_workspace_tmp_path, monkeypatch) -> None:
    """Exercise the reopened-DB importer seam, including its public failure mode."""
    root = Path(__file__).resolve().parents[1]
    project_id = "project-clean-import-path-handoff"
    path_id = _BODY_PATH
    project = {
        "project_id": project_id,
        "revision": 7,
        "name": "Clean import handoff regression",
        "content_lock": {"lock_hash": "lock-clean-import", "catalog_build_id": "catalog-clean-import"},
        "event_stream": {"count": 0, "head_hash": "event-head-clean-import"},
        "user_locks": [],
    }
    project_json = canonical_json(project)
    project_hash = canonical_project_hash(project)
    snapshot_record = {
        "record_id": path_id,
        "record_hash": "snapshot-path-clean-import",
        "content_type": "path",
    }
    snapshot_record["record_hash"] = canonical_record_hash(snapshot_record)
    snapshot_json = canonical_json(snapshot_record)
    projected_record = {
        **snapshot_record,
        "record_hash": "projected-path-clean-import",
        "compatibility": {"factory": {"stage2_authority": {"authority_complete": True}}},
    }
    choice_snapshot = materialize_choice_snapshot({**project, "revision": 1})
    manifest = {
        "project_id": project_id,
        "project_revision": project["revision"],
        "event_head_hash": project["event_stream"]["head_hash"],
        "content_lock_hash": project["content_lock"]["lock_hash"],
        "canonical_project_hash": project_hash,
        "typed_choice_snapshot_sha256": choice_snapshot["snapshot_sha256"],
        "advancement_projection_references": {},
    }
    with zipfile.ZipFile(_workspace_tmp_path / "portable.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PROJECT_MEMBER, b"project-export-placeholder")
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", b"owner-sheet")
        archive.writestr(
            "source/advancement_projection/Projection_Provenance_Map.json",
            canonical_json({"typed_choice_snapshot": choice_snapshot}),
        )
    package = _workspace_tmp_path / "portable.zip"
    package_sha256 = sha256_bytes(package.read_bytes())
    audit = {
        "manifest": manifest,
        "sha256": package_sha256,
        "readiness": {},
    }
    projected_sha256 = sha256_bytes(canonical_json(projected_record).encode("utf-8"))
    handoff = _CharacterCreationPathAuthorityHandoff(
        _issuer=_INITIAL_CREATION_HANDOFF_ISSUER,
        run_id="run-clean-import-path-handoff",
        project_id=project_id,
        choice_snapshot_project_revision=choice_snapshot["project_revision"],
        project_revision=project["revision"],
        project_canonical_hash=project_hash,
        event_head_hash=project["event_stream"]["head_hash"],
        content_lock_hash=project["content_lock"]["lock_hash"],
        catalog_build_id=project["content_lock"]["catalog_build_id"],
        typed_choice_snapshot_sha256=choice_snapshot["snapshot_sha256"],
        request_sha256="request-clean-import",
        delegated_choice_envelope_sha256="envelope-clean-import",
        authorized_delegated_path_ids=(path_id,),
        path_bindings=(
            (
                path_id,
                snapshot_record["record_hash"],
                sha256_bytes(snapshot_json.encode("utf-8")),
                projected_record["record_hash"],
                projected_sha256,
            ),
        ),
        path_feature_bindings=(),
        phase="scratch_compile",
        candidate_identity=None,
    )

    integrity = create_test_integrity_service(b"REC1-P1CR5-clean-import-handoff")
    monkeypatch.setattr(
        IntegrityService,
        "for_database",
        classmethod(lambda _cls, _db: integrity),
    )

    class ImportProjects:
        def __init__(self, db):
            self.db = db

        def import_project(self, _nested):
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO projects(
                       project_id,working_name,status,revision,project_json,canonical_project_hash
                    ) VALUES(?,?,?,?,?,?)""",
                    (
                        project_id,
                        project["name"],
                        "draft",
                        project["revision"],
                        project_json,
                        project_hash,
                    ),
                )
                conn.execute(
                    "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
                    (project_id, path_id, "clean-import-pack", "1", snapshot_record["record_hash"], snapshot_json),
                )
            return {"project_id": project_id, "revision": project["revision"]}

    def make_db(data_dir: Path) -> Database:
        settings = Settings.from_env(root, data_dir)
        db = Database(settings)
        with db.transaction() as conn:
            conn.execute(
                """CREATE TABLE projects(
                   project_id TEXT PRIMARY KEY, working_name TEXT NOT NULL, status TEXT NOT NULL,
                   revision INTEGER NOT NULL, project_json TEXT NOT NULL, canonical_project_hash TEXT
                )""",
            )
            conn.execute(
                """CREATE TABLE project_locked_records(
                   project_id TEXT NOT NULL, record_id TEXT NOT NULL, pack_id TEXT NOT NULL,
                   pack_version TEXT NOT NULL, record_hash TEXT NOT NULL, record_json TEXT NOT NULL,
                   PRIMARY KEY(project_id, record_id)
                )""",
            )
        return db

    class ReadyProduct:
        def __init__(self, _db):
            pass

        def report(self):
            return {"portable_import": {"ready": True}}

    class ReadyFactory:
        def __init__(self, _db):
            pass

        def status(self):
            return {"configured": True, "health": "READY", "factory_root": str(_workspace_tmp_path)}

    class FakeProjection:
        def __init__(self, db, *, factory_root):
            self.db = db
            self.factory_root = factory_root

        def build(self, *_args, **_kwargs):
            raise FoundryError(
                "PROJECTION_LOCKED_RECORD_MISSING",
                "The public clean-import projector cannot resolve the delegated Path.",
            )

        def _build(self, requested_project_id, *, force, choice_snapshot, private_record_resolver):
            assert requested_project_id == project_id
            assert force is True
            assert choice_snapshot == choice_snapshot_expected
            with self.db.connection() as conn:
                resolved = private_record_resolver(conn, requested_project_id, path_id)
            assert resolved == projected_record
            return {"projection_id": "projection-clean-import", "artifacts": []}

    class FakeSheet:
        def __init__(self, _db):
            pass

        def sheet(self, requested_project_id):
            assert requested_project_id == project_id
            return {"build_status": "VERIFIED", "sheet_artifact": {"sha256": sheet_sha256}}

    import character_sheet.service as sheet_module
    import portable_character.service as portable_module
    import projector.service as projector_module
    import vendor_adapter.service as vendor_module

    choice_snapshot_expected = choice_snapshot
    sheet_sha256 = sha256_bytes(b"owner-sheet")
    monkeypatch.setattr(portable_module, "ProductReadinessService", ReadyProduct)
    monkeypatch.setattr(portable_module.PortableCharacterPackageService, "audit", lambda _self, _path: deepcopy(audit))
    monkeypatch.setattr(projector_module, "ProjectionService", FakeProjection)
    monkeypatch.setattr(sheet_module, "CharacterSheetService", FakeSheet)
    monkeypatch.setattr(vendor_module, "FactoryAdapter", ReadyFactory)
    monkeypatch.setattr(ProjectStore, "_resolve_locked_record_after_proof", lambda _self, _conn, _project_id, _record_id, **_kwargs: deepcopy(projected_record))

    # This is the loss point from the persisted run: without the private
    # capability, import_into_factory uses the ordinary public projector.
    public_db = make_db(_workspace_tmp_path / "public-loss")
    public_service = PortableCharacterPackageService(public_db)
    public_service.projects = ImportProjects(public_db)
    with pytest.raises(FoundryError) as raised:
        public_service.import_into_factory(package)
    assert raised.value.code == "PROJECTION_LOCKED_RECORD_MISSING"

    clean_db = make_db(_workspace_tmp_path / "clean-first")
    clean_service = PortableCharacterPackageService(clean_db)
    clean_service.projects = ImportProjects(clean_db)
    first = clean_service._import_into_factory(
        package,
        _character_creation_path_authority=handoff,
    )
    assert first["status"] == "IMPORTED"
    assert handoff.choice_snapshot_project_revision == choice_snapshot["project_revision"] == 1
    assert handoff.project_revision == project["revision"] == 7
    assert handoff._validate_reopened_project(clean_db, project_id, choice_snapshot=choice_snapshot)

    wrong_final_revision = replace(handoff, project_revision=project["revision"] - 1)
    assert not wrong_final_revision._validate_reopened_project(
        clean_db,
        project_id,
        choice_snapshot=choice_snapshot,
    )

    wrong_snapshot_revision = deepcopy(choice_snapshot)
    wrong_snapshot_revision["project_revision"] = project["revision"]
    wrong_snapshot_revision["snapshot_sha256"] = sha256_json(
        {key: value for key, value in wrong_snapshot_revision.items() if key != "snapshot_sha256"}
    )
    assert not handoff._validate_reopened_project(
        clean_db,
        project_id,
        choice_snapshot=wrong_snapshot_revision,
    )

    wrong_snapshot_hash = deepcopy(choice_snapshot)
    wrong_snapshot_hash["snapshot_sha256"] = "tampered-snapshot-hash"
    assert not handoff._validate_reopened_project(
        clean_db,
        project_id,
        choice_snapshot=wrong_snapshot_hash,
    )

    wrong_snapshot_lock = deepcopy(choice_snapshot)
    wrong_snapshot_lock["content_lock_hash"] = "tampered-content-lock"
    wrong_snapshot_lock["snapshot_sha256"] = sha256_json(
        {key: value for key, value in wrong_snapshot_lock.items() if key != "snapshot_sha256"}
    )
    assert not handoff._validate_reopened_project(
        clean_db,
        project_id,
        choice_snapshot=wrong_snapshot_lock,
    )

    wrong_snapshot_project = deepcopy(choice_snapshot)
    wrong_snapshot_project["canonical_project_id"] = "different-project"
    wrong_snapshot_project["snapshot_sha256"] = sha256_json(
        {key: value for key, value in wrong_snapshot_project.items() if key != "snapshot_sha256"}
    )
    assert not handoff._validate_reopened_project(
        clean_db,
        project_id,
        choice_snapshot=wrong_snapshot_project,
    )

    reopened_service = PortableCharacterPackageService(clean_db)
    second = reopened_service._import_into_factory(
        package,
        _character_creation_path_authority=handoff,
    )
    assert second["status"] == "ALREADY_INSTALLED_IDENTICAL"


def test_finalization_guard_blocks_only_live_owner_authority() -> None:
    service = object.__new__(CharacterCreationExecutionService)
    unresolved = {
        "blockers": [],
        "final_plan": {
            "unresolved": [
                {
                    "slot_id": "advancement_choice",
                    "milestone_id": "milestone.body.8",
                    "status": "unresolved",
                    "provenance": "needs_owner",
                }
            ],
            "resolution": {"provenance": []},
        },
        "validation": {},
    }
    with pytest.raises(FoundryError) as raised:
        service._require_owner_decisions_resolved(unresolved)
    assert raised.value.code == "CG1_OWNER_DECISIONS_REQUIRED"
    assert raised.value.details["unresolved_count"] == 1

    resolved_history = {
        "blockers": [{"code": "OLD_BLOCKER", "resolved": True}],
        "final_plan": {
            "unresolved": [],
            "resolution": {
                "provenance": [
                    {
                        "slot_id": "advancement_choice",
                        "milestone_id": "milestone.body.8",
                        "status": "accepted",
                        "provenance": "owner_selected",
                    }
                ]
            },
        },
        "validation": {"unresolved_owner_decisions": []},
    }
    service._require_owner_decisions_resolved(resolved_history)


def test_nonrequired_planning_owner_rows_preserve_immutable_final_plan() -> None:
    service = object.__new__(CharacterCreationExecutionService)
    service._provider_nonrequired_planning_slot_ids = lambda run: {"insight_priorities"}
    owner_row = {
        "slot_id": "insight_priorities",
        "choice_id": None,
        "status": "unresolved",
        "provenance": "needs_owner",
    }
    run = {
        "blockers": [],
        "final_plan": {
            "final_plan_sha256": "persisted-hash",
            "plan_sha256": "same-plan",
            "unresolved": [deepcopy(owner_row)],
            "resolution": {"provenance": [deepcopy(owner_row)], "mechanics": {"hp": 9}},
        },
        "validation": {},
    }
    service._require_owner_decisions_resolved(run)

    candidate = deepcopy(run["final_plan"])
    candidate["final_plan_sha256"] = "regenerated-hash"
    candidate["unresolved"] = []
    candidate["resolution"]["provenance"] = []
    assert service._final_plan_nonrequired_planning_compatible(
        run, run["final_plan"], candidate
    )

    mechanically_changed = deepcopy(candidate)
    mechanically_changed["resolution"]["mechanics"]["hp"] = 10
    assert not service._final_plan_nonrequired_planning_compatible(
        run, run["final_plan"], mechanically_changed
    )

    service._provider_nonrequired_planning_slot_ids = lambda run: set()
    with pytest.raises(FoundryError) as raised:
        service._require_owner_decisions_resolved(run)
    assert raised.value.code == "CG1_OWNER_DECISIONS_REQUIRED"


def _insight_envelope() -> dict:
    authorities = {
        "legal": {
            "allowed_cls": [8],
            "repeatability": {"mode": "nonrepeatable", "maximum": 1},
            "ability_change": {"allowed_abilities": ["DEX"], "amount": 1, "cap": 20},
        },
        "repeat": {
            "allowed_cls": [4, 8],
            "repeatability": {"mode": "nonrepeatable", "maximum": 1},
            "ability_change": {"allowed_abilities": ["DEX"], "amount": 1, "cap": 20},
        },
        "unmet": {
            "allowed_cls": [8],
            "repeatability": {"mode": "nonrepeatable", "maximum": 1},
            "ability_change": {"allowed_abilities": ["DEX"], "amount": 1, "cap": 20},
        },
        "capped": {
            "allowed_cls": [8],
            "repeatability": {"mode": "nonrepeatable", "maximum": 1},
            "ability_change": {"allowed_abilities": ["STR"], "amount": 2, "cap": 20},
        },
        "incompatible": {
            "allowed_cls": [8],
            "repeatability": {"mode": "nonrepeatable", "maximum": 1},
            "ability_change": {"allowed_abilities": ["DEX"], "amount": 1, "cap": 20},
        },
        "wrong-cl": {
            "allowed_cls": [12],
            "repeatability": {"mode": "nonrepeatable", "maximum": 1},
            "ability_change": {"allowed_abilities": ["DEX"], "amount": 1, "cap": 20},
        },
    }
    choices = {
        "legal": {
            "name": "Legal Insight",
            "description": "A legal owner-visible choice.",
            "prerequisites": [
                {"kind": "path", "operator": "requires", "target_id": "path.body"},
                {"kind": "sphere", "operator": "requires", "target_id": "sphere.poison"},
            ],
            "incompatibilities": [],
        },
        "repeat": {"prerequisites": [], "incompatibilities": []},
        "unmet": {
            "prerequisites": [
                {"kind": "sphere", "operator": "requires", "target_id": "sphere.metal"}
            ],
            "incompatibilities": [],
        },
        "capped": {"prerequisites": [], "incompatibilities": []},
        "incompatible": {
            "prerequisites": [],
            "incompatibilities": [
                {"kind": "insight", "operator": "excludes", "target_id": "repeat"}
            ],
        },
        "wrong-cl": {"prerequisites": [], "incompatibilities": []},
    }
    return {
        "advancement_choice_milestones": [
            {"milestone_id": "milestone.body.4", "cl": 4, "path_id": "path.body"},
            {
                "milestone_id": "milestone.body.8",
                "cl": 8,
                "path_id": "path.body",
                "allowed_kinds": ["ability_score_change", "cultivation_insight_acquisition"],
            },
        ],
        "owner_locks": {"by_slot": {"path_choice": ["path.body"]}},
        "allowed_choice_ids_by_slot": {"insight_priorities": list(authorities)},
        "unavailable_or_rejected_choice_ids_by_slot": {"insight_priorities": []},
        "choices_by_slot": {"insight_priorities": choices},
        "typed_choice_authority_by_slot": {
            "insight_priorities": {"stage2_authority_by_choice": authorities}
        },
        "prerequisites_and_availability": {
            "insight_priorities": {
                insight_id: {
                    "prerequisites": choice["prerequisites"],
                    "incompatibilities": choice["incompatibilities"],
                    "availability": {},
                }
                for insight_id, choice in choices.items()
            }
        },
    }


def test_milestone_choices_are_legal_and_show_score_cap_context() -> None:
    details = enrich_milestone_details(
        {
            "milestone_id": "milestone.body.8",
            "allowed_kinds": ["ability_score_change", "cultivation_insight_acquisition"],
        },
        envelope=_insight_envelope(),
        proposal_bounded={
            "ability_scores": {"STR": 18, "DEX": 18, "CON": 14, "INT": 10, "WIS": 10, "CHA": 8},
            "ability_score_changes_by_milestone_id": {"milestone.body.4": {"STR": 1}},
            "path_progression_by_cl": {"8": "path.body"},
        },
        proposal_acquisition={
            "acquired_sphere_ids": ["sphere.poison"],
            "insight_occurrences": [
                {"milestone_id": "milestone.body.4", "insight_id": "repeat", "parameters": {"ability": "DEX"}},
                {"milestone_id": "milestone.body.8", "insight_id": "legal", "parameters": {"ability": "DEX"}},
            ],
        },
        proposal_selected_by_slot={"path_choice": ["path.body"]},
        authority_by_milestone={
            "milestone.body.8": {
                "ability_change": {
                    "allowed_abilities": ["STR", "DEX"],
                    "allowed_deltas": [1, 2],
                    "budget": 2,
                    "cap": 20,
                }
            }
        },
    )

    insights = [
        choice for choice in details["legal_choices"]
        if choice["value"]["kind"] == "cultivation_insight_acquisition"
    ]
    assert [choice["value"]["insight_id"] for choice in insights] == ["legal"]
    assert {
        key: insights[0][key]
        for key in ("current_score", "resulting_score", "cap", "ability", "amount")
    } == {
        "current_score": 19,
        "resulting_score": 20,
        "cap": 20,
        "ability": "DEX",
        "amount": 1,
    }

    asi_choices = [
        choice for choice in details["legal_choices"]
        if choice["value"]["kind"] == "ability_score_change"
    ]
    assert asi_choices
    current = {"STR": 19, "DEX": 19}
    assert all(
        current[ability] + delta <= 20
        for choice in asi_choices
        for ability, delta in choice["value"]["deltas"].items()
    )

    wrong_path = enrich_milestone_details(
        {"milestone_id": "milestone.body.8", "allowed_kinds": ["cultivation_insight_acquisition"]},
        envelope=_insight_envelope(),
        proposal_bounded={"ability_scores": {"STR": 18, "DEX": 18}},
        proposal_acquisition={},
        proposal_selected_by_slot={"path_choice": ["path.spirit"]},
    )
    assert wrong_path["legal_choices"] == []


def test_frozen_materializer_rejects_path_outside_delegated_envelope() -> None:
    service = object.__new__(CharacterCreationExecutionService)
    service._locked_records_for_project = lambda _project_id: {}
    run = {
        "project_id": "project-under-test",
        "request": {
            "delegated_choice_envelope": {
                "allowed_choice_ids_by_slot": {"path_choice": [_BODY_PATH]},
                "choices_by_slot": {"path_choice": {_BODY_PATH: {"choice_id": _BODY_PATH}}},
            }
        },
    }
    intent = CanonicalSelectionIntent.from_document(
        {"selected_by_slot": {"path_choice": [_QI_PATH]}}
    )

    with pytest.raises(FoundryError) as raised:
        service._derive_stage2_rows_from_frozen_authority(run, {}, intent)

    assert raised.value.code == "CG1_DELEGATED_CHOICE_OUT_OF_ENVELOPE"
    assert raised.value.details["choice_ids"] == [_QI_PATH]


def test_delegated_path_projection_is_complete_without_owner_lock_and_is_read_only(catalog_environment) -> None:
    db, store, project_id, project, envelope = _path_authority_fixture(catalog_environment)
    locks = {
        row["field"]: row["value"]
        for row in project.get("user_locks") or []
        if isinstance(row, dict)
    }
    assert not (locks["character_sheet.locked_choices"] or {}).get("path_choice")
    assert _BODY_PATH in envelope["allowed_choice_ids_by_slot"]["path_choice"]
    assert _BODY_PATH in envelope["choices_by_slot"]["path_choice"]
    before = store.get_project(project_id)["project"]
    authority = NonSphereAuthorityService(db)

    with db.connection() as conn:
        store.project_lock_proof(conn, project_id)
        resolved = store._resolve_locked_record_after_proof(
            conn,
            project_id,
            _BODY_PATH,
            authority_service=authority,
            authorized_delegated_path_ids={_BODY_PATH},
        )

    assert resolved is not None
    stage2 = _stage2_authority(resolved)
    assert stage2["authority_complete"] is True
    assert stage2["allowed_kinds"] == ["path_acquisition"]
    assert stage2["allowed_channels"] == ["path-selection"]
    kind, channel, _ = CharacterCreationExecutionService._resolve_event_authority(
        resolved,
        before,
        requested_kind="path_acquisition",
        requested_channel="path-selection",
        field="path_choice",
    )
    assert (kind, channel) == ("path_acquisition", "path-selection")

    after = store.get_project(project_id)["project"]
    assert after["revision"] == before["revision"]
    assert after["content_lock"] == before["content_lock"]


def test_delegated_path_authority_fails_closed_for_unselected_or_missing_snapshot(catalog_environment) -> None:
    db, store, project_id, _project, envelope = _path_authority_fixture(catalog_environment)
    authority = NonSphereAuthorityService(db)
    assert _QI_PATH in envelope["allowed_choice_ids_by_slot"]["path_choice"]

    with db.connection() as conn:
        store.project_lock_proof(conn, project_id)
        unselected = store._resolve_locked_record_after_proof(
            conn,
            project_id,
            _QI_PATH,
            authority_service=authority,
            authorized_delegated_path_ids={_BODY_PATH},
        )
        missing_snapshot = store._resolve_locked_record_after_proof(
            conn,
            "project-without-this-snapshot-row",
            _QI_PATH,
            authority_service=authority,
            authorized_delegated_path_ids={_QI_PATH},
        )

    assert unselected is None
    assert missing_snapshot is None


def test_owner_locked_path_projection_remains_typed(catalog_environment) -> None:
    db, store, project_id, project, _envelope = _path_authority_fixture(
        catalog_environment,
        selections={"path_choice": [_BODY_PATH]},
    )
    locks = {
        row["field"]: row["value"]
        for row in project.get("user_locks") or []
        if isinstance(row, dict)
    }
    assert (locks["character_sheet.locked_choices"] or {}).get("path_choice") == [_BODY_PATH]
    authority = NonSphereAuthorityService(db)

    with db.connection() as conn:
        store.project_lock_proof(conn, project_id)
        resolved = store._resolve_locked_record_after_proof(
            conn,
            project_id,
            _BODY_PATH,
            authority_service=authority,
        )

    assert resolved is not None
    assert _stage2_authority(resolved)["authority_complete"] is True


def test_private_stage2_scope_resolves_delegated_path_and_features_without_mutation(catalog_environment) -> None:
    db, store, project_id, request, run_id = _private_creation_run(catalog_environment)
    stage2 = RulesCausalStage2Service(db)
    authority = NonSphereAuthorityService(db)
    feature_id = next(
        feature["canonical_id"]
        for feature in authority.path_profiles[_BODY_PATH]["features"]
        if isinstance(feature, dict) and isinstance(feature.get("canonical_id"), str)
    )
    before = store.get_project(project_id)["project"]

    with _private_scope(stage2, request, run_id, {_BODY_PATH}):
        with db.connection() as conn:
            store.project_lock_proof(conn, project_id)
            handoff = stage2._issue_character_creation_path_authority_handoff()
            cache: dict[str, dict | None] = {}
            path, path_issues = stage2._record(
                conn,
                project_id,
                _BODY_PATH,
                "/choices/0/record_id",
                record_cache=cache,
            )
            feature, feature_issues = stage2._record(
                conn,
                project_id,
                feature_id,
                "/choices/1/record_id",
                record_cache=cache,
            )
            unselected = stage2._resolve_record_after_proof(
                conn,
                project_id,
                _QI_PATH,
                authority_service=authority,
            )

    assert path is not None
    assert feature is not None
    assert path_issues == []
    assert feature_issues == []
    assert feature["dependencies"] == [_BODY_PATH]
    assert unselected is None
    assert handoff.project_id == project_id
    assert handoff.choice_snapshot_project_revision == request["project_revision"]
    assert handoff.authorized_delegated_path_ids == (_BODY_PATH,)
    assert handoff.path_bindings[0][0] == _BODY_PATH
    assert handoff.path_feature_bindings == ()

    after = store.get_project(project_id)["project"]
    assert after["revision"] == before["revision"]
    assert after["content_lock"] == before["content_lock"]
    assert after["user_locks"] == before["user_locks"]


def test_private_stage2_handoff_binds_exact_event_path_features_and_rejects_unbound_ids(
    catalog_environment,
    monkeypatch,
) -> None:
    db, store, project_id, request, run_id = _private_creation_run(catalog_environment)
    stage2 = RulesCausalStage2Service(db)
    authority = NonSphereAuthorityService(db)
    body_features = authority.path_profiles[_BODY_PATH]["features"]
    feature_id = next(
        feature["canonical_id"]
        for feature in body_features
        if isinstance(feature, dict)
        and isinstance(feature.get("canonical_id"), str)
        and feature["canonical_id"].endswith(".tempered_response")
    )
    unreferenced_feature_id = next(
        feature["canonical_id"]
        for feature in body_features
        if isinstance(feature, dict) and feature.get("canonical_id") != feature_id
    )
    spirit_parent = "tianxia.path.spirit_awakening"
    unauthorized_feature_id = next(
        feature["canonical_id"]
        for feature in authority.path_profiles[spirit_parent]["features"]
        if isinstance(feature, dict) and isinstance(feature.get("canonical_id"), str)
    )
    calculation_only_id = f"{_BODY_PATH}.feature.cl1.1"
    monkeypatch.setattr(
        stage2.projects,
        "timeline",
        lambda requested_project_id: [
            {"subject": {"record_id": _BODY_PATH}},
            {
                "subject": {"record_id": "tianxia.subpath.body.tempering"},
                "advancement": {
                    "kind": "subpath_acquisition",
                    "calculation": {
                        "outputs": {"granted_feature_record_ids": [feature_id]},
                        "evidence": {"calculation_only_path_id": calculation_only_id},
                    },
                },
            },
        ],
    )

    with _private_scope(stage2, request, run_id, {_BODY_PATH}):
        with db.connection() as conn:
            store.project_lock_proof(conn, project_id)
            handoff = stage2._issue_character_creation_path_authority_handoff()

    assert handoff.authorized_delegated_path_ids == (_BODY_PATH,)
    assert len(handoff.path_feature_bindings) == 1
    feature_binding = handoff.path_feature_bindings[0]
    assert feature_binding[0] == feature_id
    assert feature_binding[1] == _BODY_PATH
    assert feature_binding[2]
    assert feature_binding[3]
    assert feature_id not in handoff.authorized_delegated_path_ids
    assert handoff._path_feature_binding(calculation_only_id) is None

    def resolve(candidate, record_id, *, authority_service=authority):
        with db.connection() as conn:
            return candidate._resolve_record_after_proof(
                db,
                conn,
                project_id,
                record_id,
                authority_service=authority_service,
            )

    assert resolve(handoff, _BODY_PATH)["record_id"] == _BODY_PATH
    assert resolve(handoff, feature_id)["record_id"] == feature_id
    assert resolve(handoff, unreferenced_feature_id) is None
    assert resolve(handoff, unauthorized_feature_id) is None
    assert resolve(handoff, f"{_BODY_PATH}.feature.unknown_feature") is None
    assert resolve(handoff, calculation_only_id) is None

    no_authority_lookup = Mock()
    assert resolve(handoff, unreferenced_feature_id, authority_service=no_authority_lookup) is None
    assert resolve(handoff, unauthorized_feature_id, authority_service=no_authority_lookup) is None
    assert resolve(handoff, f"{_BODY_PATH}.feature.unknown_feature", authority_service=no_authority_lookup) is None
    assert resolve(handoff, calculation_only_id, authority_service=no_authority_lookup) is None
    assert no_authority_lookup.method_calls == []

    binding = feature_binding
    tampered_id = replace(
        handoff,
        path_feature_bindings=((f"{_BODY_PATH}.feature.other", binding[1], binding[2], binding[3]),),
    )
    assert resolve(tampered_id, feature_id) is None

    tampered_parent = replace(
        handoff,
        path_feature_bindings=((feature_id, _QI_PATH, binding[2], binding[3]),),
    )
    assert resolve(tampered_parent, feature_id) is None

    tampered_record_hash = replace(
        handoff,
        path_feature_bindings=((feature_id, binding[1], "tampered-record-hash", binding[3]),),
    )
    with pytest.raises(FoundryError) as raised:
        resolve(tampered_record_hash, feature_id)
    assert raised.value.code == "PROJECT_LOCK_SNAPSHOT_MISMATCH"

    tampered_canonical_sha = replace(
        handoff,
        path_feature_bindings=((feature_id, binding[1], binding[2], "tampered-canonical-sha"),),
    )
    with pytest.raises(FoundryError) as raised:
        resolve(tampered_canonical_sha, feature_id)
    assert raised.value.code == "PROJECT_LOCK_SNAPSHOT_MISMATCH"


@pytest.mark.parametrize("status", ["NEEDS_REVIEW", "READY_FOR_REVIEW"])
def test_private_stage2_scope_allows_review_scratch_retry_but_public_scope_does_not(catalog_environment, status: str) -> None:
    db, store, project_id, request, run_id = _private_creation_run(
        catalog_environment,
        status=status,
    )
    stage2 = RulesCausalStage2Service(db)
    authority = NonSphereAuthorityService(db)
    authorized_paths = {_BODY_PATH, _QI_PATH}
    unauthorized_path = "tianxia.path.spirit_awakening"

    with _private_scope(stage2, request, run_id, authorized_paths):
        with db.connection() as conn:
            store.project_lock_proof(conn, project_id)
            scratch_records = {
                path_id: stage2._resolve_record_after_proof(
                    conn,
                    project_id,
                    path_id,
                    authority_service=authority,
                )
                for path_id in authorized_paths
            }
            unauthorized_record = stage2._resolve_record_after_proof(
                conn,
                project_id,
                unauthorized_path,
                authority_service=authority,
            )
    assert {record["record_id"] for record in scratch_records.values() if record is not None} == authorized_paths
    assert unauthorized_record is None

    with db.connection() as conn:
        store.project_lock_proof(conn, project_id)
        public_record = stage2._resolve_record_after_proof(
            conn,
            project_id,
            _BODY_PATH,
            authority_service=authority,
        )
    assert public_record is None


def test_private_stage2_scope_binding_mismatch_fails_closed(catalog_environment) -> None:
    db, store, project_id, request, run_id = _private_creation_run(catalog_environment)
    stage2 = RulesCausalStage2Service(db)
    authority = NonSphereAuthorityService(db)

    with db.transaction() as conn:
        tampered_request = json.loads(
            conn.execute(
                "SELECT request_json FROM character_creation_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
        )
        tampered_request["content_lock_hash"] = "tampered-content-lock"
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(tampered_request), run_id),
        )

    with _private_scope(stage2, request, run_id, {_BODY_PATH}):
        with db.connection() as conn:
            store.project_lock_proof(conn, project_id)
            resolved = stage2._resolve_record_after_proof(
                conn,
                project_id,
                _BODY_PATH,
                authority_service=authority,
            )
    assert resolved is None


def _method_lock_import_fixture(catalog_environment, tmp_path: Path, *, mechanical: bool = False):
    db = catalog_environment["db"]
    target_settings = Settings.from_env(
        Path(__file__).resolve().parents[1],
        tmp_path / "method-lock-clean-target",
    )
    target_db = _clone_catalog_database(db, target_settings)
    created = CharacterBuilderService(db).create_project(
        working_name="REC1 P1CR5 Method lock import",
        concept="An authenticated offered Method remains in the immutable project snapshot.",
        target_cl=1,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={},
        generation_route="ai_bootstrap",
    )
    project_id = created["project_id"]
    store = ProjectStore(db)
    authority = NonSphereAuthorityService(db)
    method_record = authority.project_locked_method_catalog_record("METHOD-081", mechanical=mechanical)
    store.add_server_locked_records(project_id, [method_record])
    with db.connection() as conn:
        source_proof = store.project_lock_proof(conn, project_id)
    export = store.export_project(project_id, "method-lock-clean-import.tianxia-project.zip")
    package = Path(export["path"])
    with zipfile.ZipFile(package) as archive:
        records = json.loads(archive.read("locked-records.json"))
    return {
        "db": db,
        "target_db": target_db,
        "target_settings": target_settings,
        "project_id": project_id,
        "method_record": method_record,
        "records": records,
        "package": package,
        "source_proof": source_proof,
    }


def _rewrite_locked_records_archive(package: Path, target: Path, records: list[dict]) -> Path:
    with zipfile.ZipFile(package) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["locked-records.json"] = canonical_json(records).encode("utf-8")
    payload_names = sorted(set(files) - {"manifest.json", "SHA256SUMS.txt"})
    checksums = {name: sha256_bytes(files[name]) for name in payload_names}
    manifest = json.loads(files["manifest.json"])
    manifest["files"] = checksums
    files["manifest.json"] = canonical_json(manifest).encode("utf-8")
    files["SHA256SUMS.txt"] = "".join(
        f"{digest}  {name}\n" for name, digest in sorted(checksums.items())
    ).encode("utf-8")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return target


@pytest.mark.parametrize("mechanical", [False, True])
def test_authenticated_method_extra_survives_clean_import_and_reproduces_lock_proof(
    catalog_environment,
    tmp_path: Path,
    mechanical: bool,
) -> None:
    fixture = _method_lock_import_fixture(catalog_environment, tmp_path, mechanical=mechanical)
    imported_store = ProjectStore(fixture["target_db"])

    imported = imported_store.import_project(fixture["package"])

    assert imported["project_id"] == fixture["project_id"]
    with fixture["target_db"].connection() as conn:
        row = conn.execute(
            "SELECT pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (fixture["project_id"], "METHOD-081"),
        ).fetchone()
        imported_proof = imported_store.project_lock_proof(conn, fixture["project_id"])
        resolved = imported_store._resolve_project_locked_method_after_proof(
            conn, fixture["project_id"], "METHOD-081",
        )
    assert row is not None
    assert row["pack_id"] == fixture["method_record"]["content_binding"]["pack_id"]
    assert row["pack_version"] == fixture["method_record"]["content_binding"]["pack_version"]
    assert row["record_hash"] == fixture["method_record"]["record_hash"]
    assert row["record_json"] == canonical_json(fixture["method_record"])
    assert imported_proof == fixture["source_proof"]
    assert resolved == fixture["method_record"]


@pytest.mark.parametrize("variant", ["unknown", "wrong_binding", "tampered", "duplicate", "missing_pack"])
def test_clean_import_rejects_unauthorized_or_incomplete_locked_record_sets(
    catalog_environment,
    tmp_path: Path,
    variant: str,
) -> None:
    fixture = _method_lock_import_fixture(catalog_environment, tmp_path / variant)
    records = deepcopy(fixture["records"])
    expected_code = "PROJECT_LOCK_SNAPSHOT_INCOMPLETE"
    if variant == "unknown":
        unknown = deepcopy(fixture["method_record"])
        unknown["record_id"] = "METHOD-UNKNOWN-IMPORT"
        unknown["record_hash"] = canonical_record_hash(unknown)
        records.append(unknown)
    elif variant == "wrong_binding":
        wrong_binding = deepcopy(fixture["method_record"])
        wrong_binding["content_binding"] = {
            **wrong_binding["content_binding"],
            "pack_id": "tianxia.core.factory",
        }
        wrong_binding["record_hash"] = canonical_record_hash(wrong_binding)
        records[records.index(fixture["method_record"])] = wrong_binding
    elif variant == "tampered":
        tampered = deepcopy(fixture["method_record"])
        tampered["summary"] = f"{tampered['summary']} (tampered)"
        tampered["record_hash"] = canonical_record_hash(tampered)
        records[records.index(fixture["method_record"])] = tampered
    elif variant == "duplicate":
        records.append(deepcopy(records[0]))
        expected_code = "PROJECT_LOCK_SNAPSHOT_INVALID"
    else:
        pack_record = next(record for record in records if record["record_id"] != "METHOD-081")
        records.remove(pack_record)

    package = _rewrite_locked_records_archive(
        fixture["package"],
        tmp_path / f"{variant}-tampered.tianxia-project.zip",
        records,
    )
    with pytest.raises(FoundryError) as raised:
        ProjectStore(fixture["target_db"]).import_project(package)
    assert raised.value.code == expected_code


def test_private_commit_snapshot_assertion_accepts_exact_regenerated_feature_bytes() -> None:
    record = {
        "record_id": f"{_BODY_PATH}.feature.cl1.1",
        "record_hash": "feature-record-hash",
        "content_binding": {"pack_id": "tianxia.non_sphere.authority"},
    }
    ordinary_assertion = Mock()
    stage2 = object.__new__(RulesCausalStage2Service)
    stage2.projects = Mock()
    stage2.projects._assert_snapshot_record = ordinary_assertion
    stage2._validated_initial_creation_delegated_path_ids = Mock(return_value=frozenset({_BODY_PATH}))
    stage2._resolve_record_after_proof = Mock(return_value={**record})
    conn = object()

    stage2._assert_record_after_proof(conn, "project-under-test", record)

    stage2._validated_initial_creation_delegated_path_ids.assert_called_once_with(
        conn,
        "project-under-test",
        record["record_id"],
    )
    stage2._resolve_record_after_proof.assert_called_once_with(
        conn,
        "project-under-test",
        record["record_id"],
    )
    ordinary_assertion.assert_not_called()


def test_private_commit_snapshot_assertion_rejects_regenerated_byte_mismatch() -> None:
    record = {
        "record_id": _BODY_PATH,
        "record_hash": "committed-record-hash",
        "content_binding": {"pack_id": "tianxia.non_sphere.authority"},
    }
    ordinary_assertion = Mock()
    stage2 = object.__new__(RulesCausalStage2Service)
    stage2.projects = Mock()
    stage2.projects._assert_snapshot_record = ordinary_assertion
    stage2._validated_initial_creation_delegated_path_ids = Mock(return_value=frozenset({_BODY_PATH}))
    stage2._resolve_record_after_proof = Mock(
        return_value={**record, "record_hash": "different-record-hash"}
    )

    with pytest.raises(FoundryError) as raised:
        stage2._assert_record_after_proof(object(), "project-under-test", record)

    assert raised.value.code == "PROJECT_LOCK_SNAPSHOT_MISMATCH"
    ordinary_assertion.assert_not_called()


def test_commit_snapshot_assertion_delegates_without_valid_private_scope() -> None:
    record = {
        "record_id": _BODY_PATH,
        "record_hash": "committed-record-hash",
        "content_binding": {"pack_id": "tianxia.non_sphere.authority"},
    }
    ordinary_assertion = Mock()
    stage2 = object.__new__(RulesCausalStage2Service)
    stage2.projects = Mock()
    stage2.projects._assert_snapshot_record = ordinary_assertion
    stage2._validated_initial_creation_delegated_path_ids = Mock(return_value=None)
    stage2._resolve_record_after_proof = Mock()
    conn = object()

    stage2._assert_record_after_proof(conn, "project-under-test", record)

    ordinary_assertion.assert_called_once_with(conn, "project-under-test", record)
    stage2._resolve_record_after_proof.assert_not_called()


def _catalog_free_projection_fixture():
    project_id = "project-private-projection"
    path_id = _BODY_PATH
    raw_record = {
        "record_id": path_id,
        "record_hash": "raw-path-record-hash",
        "content_type": "path",
        "publication": {"status": "published"},
    }
    resolved_record = {
        **raw_record,
        "record_hash": "resolved-path-record-hash",
        "compatibility": {"factory": {"stage2_authority": {"authority_complete": True}}},
    }
    project = {
        "project_id": project_id,
        "revision": 4,
        "content_lock": {"lock_hash": "content-lock-hash"},
        "user_locks": [],
    }
    events = [{
        "event_id": "event-private-path",
        "event_hash": "event-private-path-hash",
        "advancement": {"kind": "path_acquisition"},
        "subject": {"record_id": path_id},
    }]

    locked_row = {
        "record_id": path_id,
        "pack_id": "pack.private-projection",
        "pack_version": "1.0.0",
        "record_hash": raw_record["record_hash"],
        "record_json": canonical_json(raw_record),
    }

    class Connection:
        def execute(self, sql, _params=()):
            if "record_id IN" in sql:
                return [dict(locked_row)]
            if "ORDER BY record_id" in sql:
                return [dict(locked_row)]
            raise AssertionError(f"unexpected projection SQL: {sql}")

    class DatabaseStub:
        def connection(self):
            return nullcontext(Connection())

    class ProjectsStub:
        def get_project(self, requested_project_id):
            assert requested_project_id == project_id
            return {
                "project": project,
                "project_id": project_id,
                "revision": project["revision"],
                "working_name": "private projection test",
            }

        def timeline(self, requested_project_id):
            assert requested_project_id == project_id
            return events

        def project_lock_proof(self, _conn, requested_project_id):
            assert requested_project_id == project_id

        def _resolve_locked_record_after_proof(self, _conn, requested_project_id, record_id):
            assert requested_project_id == project_id
            assert record_id == path_id
            return None

        def _resolve_locked_record(self, _conn, requested_project_id, record_id):
            assert requested_project_id == project_id
            assert record_id == path_id
            return None

    projector = object.__new__(ProjectionService)
    projector.db = DatabaseStub()
    projector.projects = ProjectsStub()
    return projector, project_id, path_id, project, events, raw_record, resolved_record


def _projection_input_hash(project, events, locked_record_json):
    digest = hashlib.sha256()
    digest.update(b'{"events":')
    digest.update(canonical_json(events).encode("utf-8"))
    digest.update(b',"locked_records":{')
    for index, record_id in enumerate(sorted(locked_record_json)):
        if index:
            digest.update(b",")
        digest.update(canonical_json(record_id).encode("utf-8"))
        digest.update(b":")
        digest.update(locked_record_json[record_id].encode("utf-8"))
    digest.update(b'},"project":')
    digest.update(canonical_json(project).encode("utf-8"))
    digest.update(b"}")
    return digest.hexdigest()


def test_private_character_creation_projection_uses_stage2_path_resolver_and_canonical_input_hash() -> None:
    projector, project_id, path_id, _project, _events, raw_record, resolved_record = _catalog_free_projection_fixture()
    resolver_calls = []

    def resolve_record(_conn, requested_project_id, record_id):
        resolver_calls.append((requested_project_id, record_id))
        return resolved_record if record_id == path_id else None

    captured = {}

    def capture_build(requested_project_id, *, force=False, choice_snapshot=None, private_record_resolver=None):
        captured["resolver"] = private_record_resolver
        captured["force"] = force
        captured["choice_snapshot"] = choice_snapshot
        return projector._inputs(
            requested_project_id,
            private_record_resolver=private_record_resolver,
        )

    projector._build = capture_build
    stage2 = SimpleNamespace(_resolve_record_after_proof=resolve_record)
    project, events, records, input_hash = projector._build_for_character_creation(
        project_id,
        stage2_service=stage2,
        choice_snapshot={"snapshot": "private"},
    )

    assert captured["resolver"] is resolve_record
    assert captured["choice_snapshot"] == {"snapshot": "private"}
    assert resolver_calls == [(project_id, path_id)]
    assert records[path_id] == resolved_record
    assert input_hash == _projection_input_hash(
        project,
        events,
        {path_id: canonical_json(resolved_record)},
    )
    assert input_hash != _projection_input_hash(
        project,
        events,
        {path_id: canonical_json(raw_record)},
    )


def test_private_character_creation_projection_fails_closed_without_valid_stage2_scope() -> None:
    projector, project_id, path_id, _project, _events, _raw_record, _resolved_record = _catalog_free_projection_fixture()
    stage2 = object.__new__(RulesCausalStage2Service)
    stage2.projects = projector.projects
    stage2._validated_initial_creation_delegated_path_ids = lambda _conn, _project_id, _record_id: None

    captured = {}

    def capture_build(requested_project_id, *, force=False, choice_snapshot=None, private_record_resolver=None):
        captured["resolver"] = private_record_resolver
        return projector._inputs(
            requested_project_id,
            private_record_resolver=private_record_resolver,
        )

    projector._build = capture_build
    _project, _events, records, private_hash = projector._build_for_character_creation(
        project_id,
        stage2_service=stage2,
        choice_snapshot={"snapshot": "invalid-scope"},
    )
    _ordinary_project, _ordinary_events, ordinary_records, ordinary_hash = projector._inputs(project_id)

    assert callable(captured["resolver"])
    assert path_id not in records
    assert path_id not in ordinary_records
    assert private_hash == ordinary_hash


def test_character_creation_projection_falls_back_to_ordinary_build_for_fake_collaborator() -> None:
    seen = {}

    class OrdinaryProjection:
        def build(self, project_id, *, choice_snapshot):
            seen["project_id"] = project_id
            seen["choice_snapshot"] = choice_snapshot
            return {"status": "ordinary"}

    snapshot = {"choices": ["path"]}
    result = CharacterCreationExecutionService._build_character_creation_projection(
        OrdinaryProjection(),
        object(),
        "project-fake-collaborator",
        snapshot,
    )

    assert result == {"status": "ordinary"}
    assert seen == {"project_id": "project-fake-collaborator", "choice_snapshot": snapshot}


def test_bound_stage1_first_adapter_keeps_private_projection_in_stage2_scope_and_forwards_handoff(
    monkeypatch,
    tmp_path,
) -> None:
    assert CharacterCreationExecutionService._compile_once is compile_once_stage1_first

    service = object.__new__(CharacterCreationExecutionService)
    # Candidate capture is a separate collaborator; this test pins the private
    # projection scope and handoff only.
    service.candidate_gm = SimpleNamespace(capture=lambda **_kwargs: None)
    project_id = "project-stage1-first-private-path"
    path_ids = (_BODY_PATH,)
    choice_snapshot = {
        "canonical_project_id": project_id,
        "snapshot_sha256": "s" * 64,
    }
    handoff = object()
    events = []
    active = {"value": False}
    private_calls = []
    ordinary_calls = []
    release_calls = []

    class ScratchDatabase:
        def __init__(self, settings):
            self.settings = settings

        def migrate(self):
            events.append("scratch.migrate")

    class Scope:
        def __enter__(self):
            active["value"] = True
            events.append("scope.enter")
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            events.append("scope.exit")
            active["value"] = False

    class ScratchStage1:
        def validate_response(self, prompt_id, response_text, prior_attempt_id=None):
            events.append("stage1.validate")
            return {
                "attempt_id": "stage1-attempt",
                "validation": {"valid": True},
            }

        def approve_and_commit(self, attempt_id, approved_by):
            events.append("stage1.approve")
            return {"commit_id": "stage1-commit"}

    class ScratchStage2:
        def _trusted_character_creation_scope(self, **kwargs):
            events.append("scope.request")
            return Scope()

        def create_proposal(self, proposal):
            assert active["value"]
            events.append("stage2.create")
            return {"proposal_id": "stage2-proposal"}

        def validate_proposal(self, proposal_id):
            assert active["value"]
            events.append("stage2.validate")
            return {"valid": True, "proposal_id": proposal_id}

        def commit_proposal(self, proposal_id):
            assert active["value"]
            events.append("stage2.commit")
            return {"commit_id": "stage2-commit"}

        def _issue_character_creation_path_authority_handoff(self):
            assert active["value"]
            events.append("handoff")
            return handoff

    class ScratchProjection:
        def _build_for_character_creation(self, requested_project_id, *, stage2_service, choice_snapshot):
            assert active["value"]
            events.append("private.projection")
            private_calls.append(
                (requested_project_id, stage2_service, choice_snapshot),
            )
            return {"projection": "private", "project_id": requested_project_id}

        def build(self, *args, **kwargs):
            ordinary_calls.append((args, kwargs))
            raise AssertionError("ordinary projection escaped the Stage 2 scope")

    class ScratchSheet:
        def build(self, requested_project_id):
            events.append("sheet")
            return {"sheet": requested_project_id}

    release = {
        "factory_authoring": {"artifact": "factory"},
        "command5": {"artifact": "gm"},
        "consumer": {"artifact": "consumer"},
        "portable_audit": {"sha256": "portable"},
        "clean_import": {"verified": True},
        "production_artifact_identity": {"identity": "release"},
    }

    class ScratchRelease:
        def compile(self, requested_project_id, **kwargs):
            assert not active["value"]
            events.append("release")
            release_calls.append((requested_project_id, kwargs))
            return release

        def _stable(self, value):
            return value

    stage2 = ScratchStage2()
    services = {
        "stage1": ScratchStage1(),
        "stage2": stage2,
        "projections": ScratchProjection(),
        "character_sheets": ScratchSheet(),
        "production_release": ScratchRelease(),
        "combat_readiness": None,
    }
    source_settings = SimpleNamespace(
        root_dir=tmp_path,
        db_path=tmp_path / "foundry.sqlite3",
        factory_zip=None,
        fixture_path=None,
    )
    service.db = SimpleNamespace(settings=source_settings)
    service.owner_principal = "owner"
    service._require_frozen_choice_snapshot = lambda _run: deepcopy(choice_snapshot)
    service._execution_descriptive_fields = lambda _run, value: value
    service._snapshot_data = lambda target, **_kwargs: target.mkdir(parents=True, exist_ok=True)
    service._snapshot_external_security = lambda _target: None
    service._prepare_scratch_compilation_run = lambda *_args, **_kwargs: events.append("scratch.prepare")
    service._scratch_services = lambda _scratch_db: services
    service._materialize_descriptive_fields = lambda *_args, **_kwargs: events.append(
        "materialize.descriptive"
    )
    service._materialize_method_hard_lock = lambda *_args, **_kwargs: (
        events.append("method.lock") or {"method": "locked"}
    )
    service._stage1_prior_attempt_id = lambda _db, _prompt_id, attempt_id: attempt_id
    delegated_path_ids = Mock(return_value=path_ids)
    service._delegated_path_ids_from_canonical_intent = delegated_path_ids

    def provenance(run_arg, **kwargs):
        assert run_arg["project_id"] == project_id
        assert active["value"]
        events.append("provenance")

    service._issue_initial_catalog_provenance = provenance

    stage2_call = {}
    actual_stage2_commit = CharacterCreationExecutionService._stage2_commit.__get__(
        service,
        CharacterCreationExecutionService,
    )

    def stage2_commit(svc, proposal, owner, **kwargs):
        stage2_call.update({"svc": svc, "proposal": proposal, "owner": owner, **kwargs})
        assert kwargs["delegated_path_ids"] == path_ids
        assert callable(kwargs["after_commit"])
        events.append("adapter.stage2_commit")
        return actual_stage2_commit(svc, proposal, owner, **kwargs)

    service._stage2_commit = stage2_commit
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
        "run_id": "run-stage1-first-private-path",
        "project_id": project_id,
        "starting_revision": 4,
        "request": {
            "stage1_prompt": {"prompt_id": "prompt-stage1-first"},
            "typed_choice_snapshot": choice_snapshot,
            "content_lock_hash": "content-lock",
            "request_sha256": "request-sha",
        },
    }
    plan = {
        "stage1_response": {"path": "PATH-BODY"},
        "stage2_proposal": {"choices": [{"kind": "path", "record_id": _BODY_PATH}]},
        "canonical_selection_intent": {
            "selected_by_slot": {"path_choice": [_BODY_PATH]},
        },
        "target_cl": 1,
        "owner_descriptive_fields": {},
        "uncertainties": [],
        "fallbacks": [],
        "output_profile": {"combat_ready": False},
    }

    result = service._compile_once(run, plan, 1)

    assert result["artifacts"]["projection"] == {
        "projection": "private",
        "project_id": project_id,
    }
    assert delegated_path_ids.call_args.args == (plan["canonical_selection_intent"],)
    assert stage2_call["creation_run"] is run
    assert stage2_call["phase"] == "scratch_compile"
    assert private_calls == [(project_id, stage2, choice_snapshot)]
    assert ordinary_calls == []
    assert release_calls[0][0] == project_id
    assert release_calls[0][1]["_character_creation_path_authority"] is handoff
    assert events.index("scratch.migrate") < events.index("scratch.prepare")
    assert events.index("scratch.prepare") < events.index("stage1.validate")
    assert events.index("stage2.commit") < events.index("provenance")
    assert events.index("provenance") < events.index("private.projection")
    assert events.index("private.projection") < events.index("handoff")
    assert events.index("handoff") < events.index("scope.exit")
    assert events.index("scope.exit") < events.index("release")
