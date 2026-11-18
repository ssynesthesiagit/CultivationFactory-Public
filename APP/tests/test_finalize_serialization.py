from __future__ import annotations

import json
import threading
from copy import deepcopy
from types import SimpleNamespace
from dataclasses import replace
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_json
from character_creation import CharacterCreationExecutionService, auto_token
from character_creation.delegated_choice_authority import final_plan_sha256


def test_finalize_rejects_overlap_and_releases_after_success_and_error(tmp_path) -> None:
    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / "data")
    settings = replace(settings, security_dir=settings.data_dir / "security", factory_zip=None, fixture_path=None)
    service = CharacterCreationExecutionService(
        Database(settings),
        stage1=None,
        provider=None,
        project_store=None,
    )
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def fake_finalize_locked(run_id: str, **_kwargs):
        calls.append(run_id)
        if len(calls) == 1:
            entered.set()
            release.wait(timeout=2)
            return {"run_id": run_id, "status": "READY_FOR_REVIEW"}
        if len(calls) == 2:
            raise RuntimeError("simulated finalization failure")
        return {"run_id": run_id, "status": "READY_FOR_REVIEW"}

    service._finalize_locked = fake_finalize_locked
    result: list[dict] = []
    worker = threading.Thread(target=lambda: result.append(service.finalize("first")))
    worker.start()
    assert entered.wait(timeout=2)

    with pytest.raises(FoundryError) as busy:
        service.finalize("overlap")
    assert busy.value.code == "CG1_FINALIZATION_IN_PROGRESS"
    assert busy.value.status_code == 409
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert result == [{"run_id": "first", "status": "READY_FOR_REVIEW"}]

    with pytest.raises(RuntimeError, match="simulated finalization failure"):
        service.finalize("fails")
    assert service.finalize("after-error")["run_id"] == "after-error"
    assert calls == ["first", "fails", "after-error"]


class _ProjectionArtifact:
    """Synthetic pipeline bytes, identical in scratch and live publication."""
    def __init__(self, db, surface):
        self.db = db
        self.surface = surface

    def build(self, project_id, **kwargs):
        payload = {"surface": self.surface, "project_id": project_id, "stage2_committed": True}
        if self.surface == "projection":
            payload["snapshot_sha256"] = kwargs["choice_snapshot"]["snapshot_sha256"]
        path = self.db.settings.exports_dir / f"{self.surface}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(payload), encoding="utf-8")
        return {**payload, "path": str(path), "sha256": sha256_json(payload)}

    export = verify = build_for_project = build


def _projection_pipeline(db):
    return {
        "stage1": SimpleNamespace(
            validate_response=lambda *a, **k: {"attempt_id": "s1", "validation": {"valid": True}},
            approve_and_commit=lambda *a: {"commit_id": "s1"},
        ),
        "stage2": SimpleNamespace(
            create_proposal=lambda proposal: {"proposal_id": "s2"},
            validate_proposal=lambda proposal_id: {"valid": True},
            commit_proposal=lambda proposal_id: {"commit_id": "s2"},
        ),
        "gm_consumer": SimpleNamespace(verify=lambda receipt: {"verified": True, "source_sha256": receipt["sha256"]}),
        **{service: _ProjectionArtifact(db, surface) for service, surface in (
            ("projections", "projection"), ("character_sheets", "character_sheet"),
            ("factory_authoring", "factory_authoring"), ("gm_exports", "gm_model"),
            ("portable_characters", "portable_character"),
        )},
    }


class _ProjectionFinalizer(CharacterCreationExecutionService):
    """Real compile/finalize/publication/readback; double only build dependencies.

    No vendor package, catalog, provider, GM guidance, or model server is needed
    to reproduce an output-set mismatch. Package admission is orthogonal here;
    its double checks the synthetic sheet bytes before publication.
    """
    def _project(self, project_id):
        with self.db.connection() as conn:
            row = conn.execute("SELECT project_json,revision FROM projects WHERE project_id=?", (project_id,)).fetchone()
        return {**json.loads(row["project_json"]), "revision": row["revision"]}

    def _require_frozen_choice_snapshot(self, run):
        return run["request"]["typed_choice_snapshot"]

    def _materialize_descriptive_fields(self, *args, **kwargs):
        pass

    def _materialize_delegated_final_grant_plan(self, *args, **kwargs):
        pass

    def _materialize_method_hard_lock(self, *args, **kwargs):
        pass

    def _materialize_constructed_arts(self, *args, **kwargs):
        pass

    def _issue_initial_catalog_provenance(self, *args, **kwargs):
        pass

    def _assert_completed_release_gate(self, outputs):
        receipt = outputs["character_sheet"]
        assert sha256_json(json.loads(Path(receipt["path"]).read_text())) == receipt["sha256"]


@pytest.fixture
def projection_finalizer(tmp_path, monkeypatch):
    data = tmp_path / "data"
    settings = Settings(
        root_dir=Path(__file__).resolve().parents[1], data_dir=data,
        db_path=data / "foundry.sqlite3", inbox_dir=data / "inbox",
        exports_dir=data / "exports", packs_dir=data / "content_packs",
        vendor_dir=data / "vendor", logs_dir=data / "logs",
        backups_dir=data / "backups", security_dir=data / "security",
        factory_zip=None, fixture_path=None,
    )
    db = Database(settings)
    db.migrate()
    service = _ProjectionFinalizer(
        db, provider=None, project_store=None, pipeline_factory=_projection_pipeline,
        owner_principal="owner", **_projection_pipeline(db),
    )
    service.candidate_gm_authoring = SimpleNamespace(
        candidate_compilation_authority=lambda *a, **k: None,
    )
    monkeypatch.setattr(auto_token, "start", lambda *a, **k: None)
    request = {
        "project_revision": 0, "content_lock_hash": "lock",
        "stage1_prompt": {"prompt_id": "prompt"},
        "typed_choice_snapshot": {"snapshot_sha256": "snapshot", "canonical_project_id": "p"},
    }
    request["request_sha256"] = service.request_payload_sha256(request)
    fields = {"identity": {"name": "Projection Test"}, "concept": "A cultivator"}
    plan = {
        "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
        "request_sha256": request["request_sha256"],
        "stage1_response": {"path": "PATH-QI"},
        "stage2_proposal": {"project_id": "p", "choices": [{"target_cl": 1, "kind": "qi"}]},
        "target_cl": 1, "owner_descriptive_fields": fields,
        "uncertainties": [], "fallbacks": [], "output_profile": {"combat_ready": False},
    }
    response_text = canonical_json(plan)
    response = {
        "exact_response_text": response_text, "parsed_plan": plan,
        "response_sha256": sha256_bytes(response_text.encode()),
    }
    final_plan = {
        "plan_sha256": sha256_json(plan), "response_sha256": response["response_sha256"],
        "request_sha256": request["request_sha256"], "immutable_after_validation": True,
    }
    final_plan["final_plan_sha256"] = final_plan_sha256(final_plan)
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,
            target_factory_version,target_candidate_schema_version,target_gm_screen_version,
            quality_target,project_json,compatibility_projection_status,compile_status,consumer_verification_status)
            VALUES ('p','Projection Test','draft',0,'now','now','x','x','x','x',?,'x','x','x')""",
            (canonical_json({"project_id": "p", "content_lock": {"lock_hash": "lock"}}),),
        )
        conn.execute(
            """INSERT INTO character_creation_runs(run_id,project_id,starting_revision,execution_mode,
            idempotency_key,request_json,response_json,validation_json,final_plan_json,quality_json,
            owner_descriptive_fields_json,accepted_descriptive_fields_json,status,created_at,updated_at)
            VALUES ('projection-run','p',0,'STANDARD_API','projection-test',?,?,?,?,?,?,?,
            'READY_FOR_REVIEW','2026-11-15T00:00:00Z','2026-11-15T00:00:00Z')""",
            tuple(map(canonical_json, (
                request, response, {"plan_sha256": sha256_json(plan)}, final_plan,
                {"status": "CLEAN"}, fields, fields,
            ))),
        )
    run = service.get("projection-run")
    candidate = service._compile_twice(run, plan, accepted_final_plan=final_plan)
    with db.transaction() as conn:
        conn.execute("UPDATE character_creation_runs SET dry_run_json=? WHERE run_id=?",
                     (canonical_json(candidate), run["run_id"]))
    return service, service.get(run["run_id"]), plan


def test_finalize_stage2_projection_publishes_and_reloads(projection_finalizer):
    service, run, _ = projection_finalizer
    finalized = service.finalize(run["run_id"])
    reloaded = service.get(run["run_id"])
    assert finalized["status"] == reloaded["status"] == "CLEAN_AND_FINALIZED"
    receipt = reloaded["outputs"]["projection"]
    assert json.loads(Path(receipt["path"]).read_text())["stage2_committed"] is True
    assert "ledger" not in reloaded["outputs"]
    assert "ledger" not in run["dry_run"]["identities"]
    assert "ledger" not in run["dry_run"]["preview"]["readiness"]
    assert reloaded["commit"]["approved_candidate_identity"] == run["dry_run"]["candidate_identity"]


def test_finalize_old_reviewed_surface_set_recompiles_without_review(projection_finalizer, monkeypatch):
    service, run, _ = projection_finalizer
    stored = deepcopy(run["dry_run"])
    stored["identities"]["ledger"] = stored["identities"]["projection"]
    stored["artifacts"]["ledger"] = deepcopy(stored["artifacts"]["projection"])
    stored["candidate_identity"] = "pre-fix-reviewed-candidate"
    with service.db.transaction() as conn:
        conn.execute("UPDATE character_creation_runs SET dry_run_json=? WHERE run_id=?",
                     (canonical_json(stored), run["run_id"]))
    compile_twice = service._compile_twice
    calls = []

    def record_compile(*args, **kwargs):
        calls.append(kwargs)
        return compile_twice(*args, **kwargs)

    monkeypatch.setattr(service, "_compile_twice", record_compile)
    finalized = service.finalize(run["run_id"])
    assert finalized["status"] == service.get(run["run_id"])["status"] == "CLEAN_AND_FINALIZED"
    assert len(calls) == 1
    assert calls[0]["accepted_final_plan"] == run["final_plan"]
    assert finalized["commit"]["approved_candidate_identity"] == run["dry_run"]["candidate_identity"]
    # Recompilation is request-local, not a rewrite or a new owner review.
    with service.db.connection() as conn:
        row = conn.execute("SELECT dry_run_json,response_json,final_plan_json FROM character_creation_runs WHERE run_id=?",
                           (run["run_id"],)).fetchone()
    assert json.loads(row["dry_run_json"]) == stored
    assert json.loads(row["response_json"]) == run["response"]
    assert json.loads(row["final_plan_json"]) == run["final_plan"]


def test_finalize_rejects_a_missing_live_projection(projection_finalizer, monkeypatch):
    service, run, _ = projection_finalizer
    execute_live = _ProjectionFinalizer._execute_live

    def omit_projection(self, *args, **kwargs):
        outputs = execute_live(self, *args, **kwargs)
        outputs.pop("projection")
        return outputs

    monkeypatch.setattr(_ProjectionFinalizer, "_execute_live", omit_projection)
    with pytest.raises(FoundryError) as error:
        service.finalize(run["run_id"])
    assert error.value.code == "CG1_FINALIZATION_ROLLED_BACK"
    assert error.value.details["cause_code"] == "CG1_LIVE_OUTPUT_DIVERGED"
    details = error.value.details["cause_details"]
    assert set(details["expected"]) - set(details["actual"]) == {"projection"}
    assert {k: v for k, v in details["expected"].items() if k != "projection"} == details["actual"]
    reloaded = service.get(run["run_id"])
    assert reloaded["status"] == "READY_FOR_REVIEW"
    assert reloaded["outputs"] == {}
    assert not (service.db.settings.exports_dir / "projection.json").exists()
