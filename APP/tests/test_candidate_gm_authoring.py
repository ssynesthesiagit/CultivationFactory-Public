from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace

import pytest

from app.core import FoundryError, canonical_json, sha256_bytes
from character_creation.candidate_gm import CandidateGMCapsuleStore
from character_creation.candidate_gm_authoring import CandidateGMAuthoringService, _CandidateScopedGMIO
from factory_authoring.service import FactoryAuthoringWorkspaceService
from security.integrity import create_test_integrity_service
from test_candidate_gm_context import (
    PROJECT_ID, RUN_ID, _TestDB, _capture, _capture_with_factory,
    _synthetic_composite_provider_result, _synthetic_factory_workspace, candidate_context,
)


def _response(record_id: str) -> dict:
    theme = {
        "display_name": "Bound theme",
        "core_theme": "Source-bound discipline",
        "principles": ["Respect the source", "Preserve the boundary"],
        "strengths": ["Attention", "Restraint"],
        "risks": ["Overreach", "Assumption"],
        "roleplay_expression": "Describe the selected record faithfully.",
        "tactical_expression": "Use display guidance only.",
        "gm_usage_notes": "No executable effect is defined.",
        "relevant_record_ids": [record_id],
        "mechanical_effects": [],
    }
    return {
        "dao": deepcopy(theme),
        "i_ching": deepcopy(theme),
    }


class _Provider:
    def __init__(self, value: dict):
        self.value = value
        self.calls: list[dict] = []

    def _settings(self) -> dict:
        return {
            "provider_id": "local",
            "model": "fixture-local-model",
            "max_output_tokens": 16384,
            "thinking_mode": "disabled",
        }

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return _synthetic_composite_provider_result(kwargs, settings=self._settings())


def _authoring(fixture, provider, store):
    return CandidateGMAuthoringService(
        fixture.root,
        provider=provider,
        capsule_store=store,
        integrity=create_test_integrity_service(b"candidate-gm-authoring-fixture"),
    )


def _install_candidate_approval_schema(db):
    """Install the narrow R5 approval tables used by the isolated fixture."""
    with db.connection() as conn:
        conn.executescript(
            """
            CREATE TABLE exact_approval_challenges(
                challenge_id TEXT PRIMARY KEY,
                challenge_hash TEXT NOT NULL UNIQUE,
                principal_id TEXT NOT NULL,
                principal_hash TEXT NOT NULL,
                operation TEXT NOT NULL,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                exact_bytes_hash TEXT NOT NULL,
                binding_hash TEXT NOT NULL,
                project_lock_hash TEXT NOT NULL,
                nonce_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT,
                challenge_json TEXT NOT NULL,
                expired_observed_at TEXT,
                process_epoch_id TEXT,
                issued_monotonic_ns INTEGER,
                deadline_monotonic_ns INTEGER,
                consumed_monotonic_ns INTEGER,
                invalidated_observed_at TEXT,
                invalidation_reason TEXT
            );
            CREATE TABLE exact_approval_evidence(
                evidence_id TEXT PRIMARY KEY,
                challenge_id TEXT NOT NULL UNIQUE,
                challenge_hash TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                principal_hash TEXT NOT NULL,
                operation TEXT NOT NULL,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                exact_bytes_hash TEXT NOT NULL,
                binding_hash TEXT NOT NULL,
                project_lock_hash TEXT NOT NULL,
                evidence_hash TEXT NOT NULL UNIQUE,
                evidence_json TEXT NOT NULL,
                consumed_at TEXT NOT NULL,
                approval_projection_json TEXT,
                approval_projection_hash TEXT,
                integrity_version TEXT,
                integrity_key_id TEXT,
                integrity_domain TEXT,
                integrity_mac TEXT,
                process_epoch_id TEXT,
                consumed_monotonic_ns INTEGER
            );
            CREATE TABLE approval_clock_authority_state(
                singleton_id INTEGER PRIMARY KEY,
                wall_high_water_at TEXT NOT NULL,
                last_process_epoch_id TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE approval_process_epochs(
                process_epoch_id TEXT PRIMARY KEY,
                process_id INTEGER NOT NULL,
                first_seen_wall_at TEXT NOT NULL,
                first_seen_monotonic_ns INTEGER NOT NULL,
                monotonic_high_water_ns INTEGER NOT NULL,
                last_seen_wall_at TEXT NOT NULL,
                last_seen_monotonic_ns INTEGER NOT NULL,
                registered_at TEXT NOT NULL
            );
            """
        )


def test_candidate_authoring_missing_workspace_fails_closed_before_legacy_cache_or_provider(candidate_context):
    store, _summary = _capture(candidate_context)
    provider = _Provider(_response("PATH-1"))
    service = _authoring(candidate_context, provider, store)

    with pytest.raises(FoundryError) as caught:
        service.author(RUN_ID)

    assert caught.value.code == "CG1_GM_CANDIDATE_WORKSPACE_MISSING"
    assert provider.calls == []


def test_server_guidance_preserves_typed_states_and_drops_model_preconditions():
    token = "ccopt_" + "a" * 24
    action = {
        "action_id": "action.typed",
        "record_id": "PATH-1",
        "name": "Typed action",
        "economy": "action",
        "timing": "Current turn",
        "required_states": ["ready"],
        "resource_costs": [],
        "execution_authority": True,
    }
    prepared = {
        "token_to_action": {token: action},
        "resource": {"resource_id": "tianxia.resource.stamina", "name": "Stamina", "current": 5, "maximum": 5},
    }
    validated = {
        "composite_controller": {
            "resource_budget": {"resource_id": "RES_CP", "max_spend": 0},
            "sequence": [{"step": 1, "action_token": token, "round_offset": 0, "requires_states": ["ready"], "external_preconditions": ["moonlight is present"]}],
            "fallback": {"action_token": token, "reason": "safe fallback"},
            "conditional_options": [{"action_token": token, "when": "untrusted model condition", "priority": 1}],
            "dao_hook": "untrusted dao prose",
            "i_ching_hook": "untrusted i ching prose",
        },
    }

    guidance = CandidateGMAuthoringService._server_controller_guidance(
        prepared, validated, selected_record_ids=["PATH-1"],
    )
    sequence = guidance["sequence"][0]
    assert sequence["conditions"]["requires_states"] == ["ready"]
    assert "advisory_external_preconditions" not in sequence
    assert "advisory_when" not in guidance["conditional_options"][0]
    assert "moonlight is present" not in json.dumps(guidance)
    assert "untrusted model condition" not in json.dumps(guidance)
    assert "untrusted dao prose" not in json.dumps(guidance)
    assert "untrusted i ching prose" not in json.dumps(guidance)


def test_gm_tactical_prompt_compacts_oversized_nested_records_without_changing_source():
    records = []
    for index in range(155):
        records.append(
            {
                "section": "talents" if index % 2 else "path_features",
                "record": {
                    "record_id": f"synthetic.record.{index:03d}",
                    "display_name": f"Synthetic Record {index}",
                    "one_line_description": f"Descriptive source fact {index} remains available to the GM.",
                    "subsection": "Technique",
                    "acquisition_route": "training",
                    "parent_sphere_id": "tianxia.sphere.fire",
                    "acquisition_cl": 5,
                    "full_description": f"Full source prose for {index}. " + "source-detail " * 700,
                    "execution": {"procedure": ["resolve", "defer"] * 20, "padding": "x" * 1600},
                    "provenance": {"source_path": "public-synthetic-fixture", "padding": "y" * 1200},
                },
            }
        )
    original = deepcopy(records)
    system_message = (
        "You are the local Tianxia GM authoring adapter. Return exactly one object matching the supplied schema. "
        "Use only the selected record content in the request. Produce descriptive Dao and I Ching text. "
        "Do not add mechanics, costs, bonuses, actions, effects, targets, or execution policy."
    )
    legacy_prompt = canonical_json(
        {
            "task": "Author descriptive GM guidance for this exact selected-record snapshot.",
            "source": {
                "project_id": "project.gm-prompt-projection",
                "project_revision": 1,
                "records": deepcopy(records),
                "record_content_sha256": "a" * 64,
            },
            "constraints": [
                "mechanical_effects must be []",
                "all relevant record IDs must be selected IDs",
                "do not invent source facts",
            ],
        }
    )
    assert len((legacy_prompt + system_message).encode("utf-8")) > 65_536

    system, prompt = FactoryAuthoringWorkspaceService.gm_tactical_prompt(
        project_id="project.gm-prompt-projection",
        project_revision=1,
        records=records,
        record_content_sha256="a" * 64,
    )
    assert len((prompt + system).encode("utf-8")) <= 48 * 1024
    assert len((prompt + system).encode("utf-8")) <= 65_536
    projected = json.loads(prompt)["source"]["records"]
    assert len(projected) == len(records)
    for index, row in enumerate(projected):
        assert row == {
            "acquisition_cl": 5,
            "acquisition_route": "training",
            "display_name": f"Synthetic Record {index}",
            "one_line_description": f"Descriptive source fact {index} remains available to the GM.",
            "parent_sphere_id": "tianxia.sphere.fire",
            "record_id": f"synthetic.record.{index:03d}",
            "section": "talents" if index % 2 else "path_features",
            "subsection": "Technique",
        }
    assert records == original


class _ProcessProvider(_Provider):
    def __init__(self, value: dict, counter, entered, release):
        super().__init__(value)
        self.counter = counter
        self.entered = entered
        self.release = release

    def complete_json(self, **kwargs):
        with self.counter.get_lock():
            self.counter.value += 1
            first = self.counter.value == 1
        if first:
            self.entered.set()
            if not self.release.wait(5):
                raise TimeoutError("process fixture release was not signalled")
        return super().complete_json(**kwargs)


def _process_author_worker(root_dir, counter, entered, release, result_queue):
    from character_creation.candidate_gm import CandidateGMCapsuleStore
    from character_creation.candidate_gm_authoring import CandidateGMAuthoringService
    from security.integrity import create_test_integrity_service
    from test_candidate_gm_context import _TestDB

    root = _TestDB(Path(root_dir))
    provider = _ProcessProvider(_response("PATH-1"), counter, entered, release)
    service = CandidateGMAuthoringService(
        root,
        provider=provider,
        capsule_store=CandidateGMCapsuleStore(root),
        integrity=create_test_integrity_service(b"candidate-gm-authoring-fixture"),
    )
    try:
        authored = service.author(RUN_ID)
        result_queue.put(("ok", authored["receipt_sha256"], authored["capsule_id"], authored["provider_calls"]))
    except BaseException as exc:  # pragma: no cover - parent reports child failures
        result_queue.put(("error", type(exc).__name__, str(getattr(exc, "code", exc))))


def test_candidate_authoring_is_one_provider_call_and_provider_free_afterward(candidate_context):
    store, _summary = _capture_with_factory(candidate_context)
    provider = _Provider(_response("PATH-1"))
    service = _authoring(candidate_context, provider, store)

    authored = service.author(RUN_ID)
    assert authored["status"] == "CANDIDATE_GM_AUTHORING_READY_FOR_REVIEW"
    assert authored["gm_authoring"] == "ACTUAL_GM_AUTHORING_PENDING_OWNER_RATIFICATION"
    assert authored["owner_ratified"] is False
    assert authored["eligible_for_later_command5_checkpoint"] is False
    assert authored["provider_calls"] == 1
    assert provider.calls and provider.calls[0]["max_request_bytes"] == 64 * 1024
    candidate_root = service._root(RUN_ID)
    capsule_id = store.summary(RUN_ID)["capsule_id"]
    gm_root = candidate_root / "contexts" / capsule_id / "gm"
    assert (gm_root / "receipts").is_dir()
    assert not (candidate_context.root.settings.data_dir / "factory_gm_authoring").exists()

    status = service.status(RUN_ID)
    loaded = service.load(RUN_ID)
    rebuilt = service.build(RUN_ID)
    repeated = service.author(RUN_ID)
    assert status["receipt_sha256"] == authored["receipt_sha256"]
    assert loaded["profile_sha256"] == authored["profile_sha256"]
    assert rebuilt["workspace_status"] == "CANDIDATE_GM_AUTHORING_REVIEW_READY"
    assert repeated["provider_calls"] == 0
    assert len(provider.calls) == 1


def test_approved_candidate_rebinds_exact_authority_across_independent_scratch_admissions(
    candidate_context, tmp_path,
):
    """Approval proof remains frozen while two fresh scratch copies are admitted."""
    _install_candidate_approval_schema(candidate_context.root)
    store, _summary = _capture_with_factory(candidate_context)
    service = _authoring(candidate_context, _Provider(_response("PATH-1")), store)

    service.author(RUN_ID)
    challenge = service.issue_candidate_approval_challenge(RUN_ID)
    approved = service.approve_candidate_gm(
        RUN_ID,
        challenge["challenge"]["challenge_id"],
        challenge["challenge"]["nonce"],
    )
    assert approved["owner_ratified"] is True
    authority = service.candidate_compilation_authority(
        candidate_context.run,
        final_plan=candidate_context.final_plan,
    )
    assert authority is not None
    assert authority["candidate_project"]["project_revision"] == 8

    factory_authoring = SimpleNamespace(
        integrity=create_test_integrity_service(b"candidate-gm-authoring-fixture"),
    )

    def fresh_scratch(name: str):
        destination = tmp_path / name
        shutil.copytree(candidate_context.scratch.settings.data_dir.parent, destination)
        return _TestDB(destination, authority_root=Path(__file__).resolve().parents[1])

    results = []
    for name in ("scratch-one", "scratch-two"):
        scratch = fresh_scratch(name)
        results.append(
            service.materialize_approved_factory_authoring(
                candidate_context.run,
                scratch,
                final_plan=candidate_context.final_plan,
                factory_authoring=factory_authoring,
                authority=authority,
            )
        )

    assert results[0]["approval_id"] == results[1]["approval_id"] == authority["approval_id"]
    assert results[0]["binding_sha256"] == results[1]["binding_sha256"] == authority["binding_sha256"]
    for name in ("scratch-one", "scratch-two"):
        pointer = json.loads(
            (tmp_path / name / "data" / "factory_gm_authoring" / PROJECT_ID / "current.json")
            .read_text(encoding="utf-8")
        )
        assert pointer["owner_decision_id"].startswith("gm-decision.")

    tampered_authority = {**authority, "binding_sha256": "0" * 64}
    with pytest.raises(FoundryError) as caught:
        service.materialize_approved_factory_authoring(
            candidate_context.run,
            fresh_scratch("scratch-tampered"),
            final_plan=candidate_context.final_plan,
            factory_authoring=factory_authoring,
            authority=tampered_authority,
        )
    assert caught.value.code == "CG1_GM_CANDIDATE_APPROVAL_BINDING_INVALID"


def test_approved_candidate_uses_immutable_capsule_after_live_root_advances(
    candidate_context, tmp_path,
):
    """Live admission keeps the capsule proof while ordinary loads keep the root guard."""
    _install_candidate_approval_schema(candidate_context.root)
    store, _summary = _capture_with_factory(candidate_context)
    service = _authoring(candidate_context, _Provider(_response("PATH-1")), store)
    service.author(RUN_ID)
    challenge = service.issue_candidate_approval_challenge(RUN_ID)
    service.approve_candidate_gm(
        RUN_ID,
        challenge["challenge"]["challenge_id"],
        challenge["challenge"]["nonce"],
    )
    authority = service.candidate_compilation_authority(
        candidate_context.run,
        final_plan=candidate_context.final_plan,
    )
    assert authority is not None

    with candidate_context.scratch.connection() as conn:
        candidate_row = conn.execute(
            "SELECT revision,project_json,canonical_project_hash FROM projects WHERE project_id=?",
            (PROJECT_ID,),
        ).fetchone()
    with candidate_context.root.connection() as conn:
        conn.execute(
            "UPDATE projects SET revision=?,project_json=?,canonical_project_hash=? WHERE project_id=?",
            (
                candidate_row["revision"],
                candidate_row["project_json"],
                candidate_row["canonical_project_hash"],
                PROJECT_ID,
            ),
        )

    with pytest.raises(FoundryError) as stale:
        store.load(RUN_ID)
    assert stale.value.code == "CG1_GM_CANDIDATE_ROOT_ANCHOR_STALE"

    destination = tmp_path / "advanced-live-scratch"
    shutil.copytree(candidate_context.scratch.settings.data_dir.parent, destination)
    scratch = _TestDB(destination, authority_root=Path(__file__).resolve().parents[1])
    factory_authoring = SimpleNamespace(
        integrity=create_test_integrity_service(b"candidate-gm-authoring-fixture"),
    )
    materialized = service.materialize_approved_factory_authoring(
        candidate_context.run,
        scratch,
        final_plan=candidate_context.final_plan,
        factory_authoring=factory_authoring,
        authority=authority,
    )
    assert materialized["capsule_id"] == authority["capsule_id"]
    assert (
        destination / "data" / "factory_gm_authoring" / PROJECT_ID / "current.json"
    ).is_file()

    tampered_context = {**authority, "context_sha256": "0" * 64}
    tampered_destination = tmp_path / "advanced-live-tampered"
    shutil.copytree(candidate_context.scratch.settings.data_dir.parent, tampered_destination)
    tampered_scratch = _TestDB(
        tampered_destination,
        authority_root=Path(__file__).resolve().parents[1],
    )
    with pytest.raises(FoundryError) as tampered:
        service.materialize_approved_factory_authoring(
            candidate_context.run,
            tampered_scratch,
            final_plan=candidate_context.final_plan,
            factory_authoring=factory_authoring,
            authority=tampered_context,
        )
    assert tampered.value.code == "CG1_GM_CANDIDATE_APPROVAL_BINDING_INVALID"
    assert not (
        tampered_destination / "data" / "factory_gm_authoring" / PROJECT_ID
    ).exists()

def _factory_fixture_for_transition(fixture, base_name: str, *, empty_actions: bool = False):
    base = fixture.scratch.settings.data_dir.parent / base_name
    base.mkdir(parents=True, exist_ok=False)
    workspace, factory = _synthetic_factory_workspace(
        base,
        project_id=fixture.run["project_id"],
        project_revision=fixture.projection["project_revision"],
        projection_id=fixture.projection["projection_id"],
        event_head_hash=fixture.projection["event_head_hash"],
    )
    if empty_actions:
        surface_path = workspace / "Command_4" / "Complete_Action_Surface.json"
        surface = json.loads(surface_path.read_text(encoding="utf-8"))
        surface["status"] = "ACTION_SURFACE_PARTIAL"
        surface["actions"] = []
        surface_path.write_text(canonical_json(surface), encoding="utf-8")
        hashes = {
            path.relative_to(workspace).as_posix(): sha256_bytes(path.read_bytes())
            for path in sorted(workspace.rglob("*"))
            if path.is_file() and path.name != "SHA256SUMS.txt"
        }
        sums = "".join(f"{hashes[name]}  {name}\n" for name in sorted(hashes))
        sums_path = workspace / "SHA256SUMS.txt"
        sums_path.write_text(sums, encoding="utf-8")
        hashes["SHA256SUMS.txt"] = sha256_bytes(sums_path.read_bytes())
        factory = {
            **factory,
            "workspace_sha256": sha256_bytes(canonical_json(hashes).encode("utf-8")),
            "artifact_hashes": hashes,
        }
    return workspace, factory


def test_authoring_allows_authenticated_current_capsule_transition_before_prepare(candidate_context, monkeypatch):
    _first_workspace, first_factory = _factory_fixture_for_transition(candidate_context, "factory-first")
    store, first_summary = _capture(candidate_context, factory_authoring=first_factory)
    provider = _Provider(_response("PATH-1"))
    service = _authoring(candidate_context, provider, store)
    first_authored = service.author(RUN_ID)
    pointer_path = service._root(RUN_ID) / "current.json"
    old_pointer = pointer_path.read_bytes()
    old_envelope_path = service._root(RUN_ID) / "envelopes" / f"envelope.{json.loads(old_pointer)['envelope_sha256']}.json"
    old_envelope = old_envelope_path.read_bytes()

    second_workspace, second_factory = _factory_fixture_for_transition(
        candidate_context, "factory-second", empty_actions=True,
    )
    _store, second_summary = _capture(candidate_context, factory_authoring=second_factory)
    assert second_summary["capsule_id"] != first_summary["capsule_id"]
    assert second_workspace.is_dir()

    with pytest.raises(FoundryError) as caught_status:
        service.status(RUN_ID)
    assert caught_status.value.code == "CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE"

    prepared_projects: list[str] = []
    from factory_authoring.composite_controller import CompositeControllerAuthoring
    real_prepare = CompositeControllerAuthoring.prepare

    def observe_prepare(controller, project_id):
        prepared_projects.append(project_id)
        return real_prepare(controller, project_id)

    monkeypatch.setattr(CompositeControllerAuthoring, "prepare", observe_prepare)
    with pytest.raises(FoundryError) as caught_author:
        service.author(RUN_ID)
    assert caught_author.value.code != "CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE"
    assert prepared_projects == [PROJECT_ID]
    assert len(provider.calls) == 1
    assert pointer_path.read_bytes() == old_pointer
    assert old_envelope_path.read_bytes() == old_envelope
    assert first_authored["capsule_id"] == first_summary["capsule_id"]


def _persist_legacy_candidate_base(service, capsule_store, run_id: str, capsule_id: str):
    capsule = capsule_store.load(run_id)
    parts = service._context_parts(capsule)
    base_service = service._factory_store(run_id, capsule_id)
    response = _response("PATH-1")
    raw_response = canonical_json(response)
    provider_result = {
        "provider_id": "local",
        "purpose": "factory_gm_tactical_authoring",
        "model": "fixture-legacy-model",
        "request_sha256": "1" * 64,
        "response_sha256": "2" * 64,
        "completion_sha256": sha256_bytes(raw_response.encode("utf-8")),
        "response_text": raw_response,
        "finish_reason": "stop",
        "value": response,
    }
    try:
        FactoryAuthoringWorkspaceService._persist_gm_authoring(
            base_service,
            parts["project_id"],
            int(parts["project_revision"]),
            parts["snapshot"],
            prompt_text="legacy fixture prompt",
            system_message="legacy fixture system",
            provider_result=provider_result,
            response=response,
        )
        loaded = FactoryAuthoringWorkspaceService._load_gm_authoring(
            base_service,
            parts["project_id"],
            project_revision=int(parts["project_revision"]),
            snapshot=parts["snapshot"],
        )
    finally:
        base_service.close()
    assert loaded is not None
    assert "authoring_contract" not in loaded["binding"]
    service._publish(parts, loaded)
    return parts, loaded


def test_authoring_transitions_from_authenticated_legacy_draft_and_rejects_corruption(candidate_context, monkeypatch):
    _first_workspace, first_factory = _factory_fixture_for_transition(candidate_context, "legacy-factory-first")
    store, first_summary = _capture(candidate_context, factory_authoring=first_factory)
    service = _authoring(candidate_context, _Provider(_response("PATH-1")), store)
    old_parts, legacy = _persist_legacy_candidate_base(
        service, store, RUN_ID, first_summary["capsule_id"],
    )
    pointer_path = service._root(RUN_ID) / "current.json"
    old_pointer = pointer_path.read_bytes()
    old_gm_root = service._root(RUN_ID) / "contexts" / first_summary["capsule_id"] / "gm"
    old_gm_bytes = {
        path.relative_to(old_gm_root).as_posix(): path.read_bytes()
        for path in old_gm_root.rglob("*") if path.is_file()
    }
    receipt_path = old_gm_root / "receipts" / f"{legacy['binding']['receipt_id']}.json"
    old_receipt = receipt_path.read_bytes()

    second_workspace, second_factory = _factory_fixture_for_transition(
        candidate_context, "legacy-factory-second", empty_actions=True,
    )
    _store, second_summary = _capture(candidate_context, factory_authoring=second_factory)
    assert second_summary["capsule_id"] != old_parts["capsule_id"]
    assert second_workspace.is_dir()

    with pytest.raises(FoundryError) as caught_status:
        service.status(RUN_ID)
    assert caught_status.value.code == "CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE"

    prepared_projects: list[str] = []
    from factory_authoring.composite_controller import CompositeControllerAuthoring
    real_prepare = CompositeControllerAuthoring.prepare

    def observe_prepare(controller, project_id):
        prepared_projects.append(project_id)
        return real_prepare(controller, project_id)

    monkeypatch.setattr(CompositeControllerAuthoring, "prepare", observe_prepare)
    with pytest.raises(FoundryError) as caught_author:
        service.author(RUN_ID)
    assert caught_author.value.code != "CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE"
    assert prepared_projects == [PROJECT_ID]
    assert service.provider.calls == []
    assert pointer_path.read_bytes() == old_pointer
    assert {
        path.relative_to(old_gm_root).as_posix(): path.read_bytes()
        for path in old_gm_root.rglob("*") if path.is_file()
    } == old_gm_bytes

    receipt_path.write_bytes(old_receipt + b" ")
    try:
        with pytest.raises(FoundryError) as caught_corrupt:
            service.author(RUN_ID)
        assert caught_corrupt.value.code == "CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE"
        assert prepared_projects == [PROJECT_ID]
        assert service.provider.calls == []
    finally:
        receipt_path.write_bytes(old_receipt)


def test_candidate_authoring_rejects_cross_run_context_before_provider_call(candidate_context):
    store, _summary = _capture_with_factory(candidate_context)
    provider = _Provider(_response("PATH-1"))

    class _CrossRunStore:
        def load(self, run_id):
            value = store.load(run_id)
            value["context"]["run_id"] = "cg1.other-run"
            return value

    service = _authoring(candidate_context, provider, _CrossRunStore())
    with pytest.raises(FoundryError) as caught:
        service.author(RUN_ID)
    assert caught.value.code == "CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID"
    assert provider.calls == []


def test_candidate_authoring_rejects_tampered_envelope_and_ancestor_symlink(candidate_context, tmp_path):
    store, _summary = _capture_with_factory(candidate_context)
    provider = _Provider(_response("PATH-1"))
    service = _authoring(candidate_context, provider, store)
    authored = service.author(RUN_ID)
    current = service._root(RUN_ID) / "current.json"
    pointer = json.loads(current.read_text(encoding="utf-8"))
    envelope = service._root(RUN_ID) / "envelopes" / f"envelope.{pointer['envelope_sha256']}.json"
    original = envelope.read_bytes()
    envelope.write_bytes(original + b" ")
    with pytest.raises(FoundryError):
        service.status(RUN_ID)
    envelope.write_bytes(original)

    root = service._root(RUN_ID)
    moved = tmp_path / "candidate-run-backup"
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)
    try:
        with pytest.raises(FoundryError) as caught:
            service.status(RUN_ID)
        assert caught.value.code == "CG1_GM_CANDIDATE_PATH_INVALID"
    finally:
        root.unlink()
        moved.rename(root)
    assert authored["provider_calls"] == 1


@pytest.mark.parametrize(
    "child",
    ["sources", "requests", "responses", "artifacts", "profiles", "receipts", "attempts", "envelopes"],
)
def test_candidate_factory_adapter_rejects_inner_symlink_before_any_write(candidate_context, tmp_path, child):
    store, _summary = _capture_with_factory(candidate_context)
    provider = _Provider(_response("PATH-1"))
    service = _authoring(candidate_context, provider, store)
    capsule_id = store.summary(RUN_ID)["capsule_id"]
    root = service._root(RUN_ID) / "contexts" / capsule_id / "gm"
    service._factory_store(RUN_ID, capsule_id).close()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / child).rename(tmp_path / f"safe-{child}")
    (root / child).symlink_to(outside, target_is_directory=True)

    with pytest.raises(FoundryError) as caught:
        service.author(RUN_ID)
    assert caught.value.code == "CG1_GM_CANDIDATE_PATH_INVALID"
    assert list(outside.iterdir()) == []
    assert len(provider.calls) == 1


def test_candidate_factory_adapter_keeps_held_scope_when_ancestor_changes_during_authoring(candidate_context, tmp_path, monkeypatch):
    store, _summary = _capture_with_factory(candidate_context)
    provider = _Provider(_response("PATH-1"))
    service = _authoring(candidate_context, provider, store)
    capsule_id = store.summary(RUN_ID)["capsule_id"]
    gm_root = service._root(RUN_ID) / "contexts" / capsule_id / "gm"
    service._factory_store(RUN_ID, capsule_id).close()

    outside = tmp_path / "outside"
    outside_context = outside / "context"
    (outside_context / "gm").mkdir(parents=True)
    context_root = gm_root.parent
    moved_context = tmp_path / "safe-context"
    original_open_relative_dir = CandidateGMCapsuleStore._open_relative_dir
    original_open_child_dir = CandidateGMCapsuleStore._open_child_dir
    swapped = False

    def replace_ancestor_after_check(store_instance, parent_fd, parts, *, create, label):
        nonlocal swapped
        if tuple(parts) == ("contexts", capsule_id, "gm") and not swapped:
            # Validate and open the first two components, then replace the
            # lexical ancestor before the final openat descent.  The final
            # component must still resolve through the already-held capsule
            # descriptor.
            contexts_fd = original_open_child_dir(
                store_instance, parent_fd, "contexts", create=create, label=label,
            )
            capsule_fd = original_open_child_dir(
                store_instance, contexts_fd, capsule_id, create=create, label=label,
            )
            context_root.rename(moved_context)
            context_root.symlink_to(outside_context, target_is_directory=True)
            swapped = True
            try:
                return original_open_child_dir(
                    store_instance, capsule_fd, "gm", create=create, label=label,
                )
            finally:
                os.close(capsule_fd)
                os.close(contexts_fd)
        return original_open_relative_dir(
            store_instance, parent_fd, parts, create=create, label=label,
        )

    monkeypatch.setattr(CandidateGMCapsuleStore, "_open_relative_dir", replace_ancestor_after_check)
    try:
        service.author(RUN_ID)
    finally:
        if context_root.is_symlink():
            context_root.unlink()
        if moved_context.exists():
            moved_context.rename(context_root)

    assert swapped
    assert not [path for path in outside.rglob("*") if path.is_file()]


@pytest.mark.parametrize("failure", ["envelope", "pointer"])
def test_candidate_authoring_recovers_existing_base_without_second_provider_call(candidate_context, monkeypatch, failure):
    store, _summary = _capture_with_factory(candidate_context)
    provider = _Provider(_response("PATH-1"))
    service = _authoring(candidate_context, provider, store)
    real_write_immutable = service._write_immutable
    real_write_pointer = service._write_pointer

    def fail_envelope(root, name, value):
        if failure == "envelope" and root.name == "envelopes":
            raise FoundryError("CG1_TEST_ENVELOPE_WRITE_FAILED", "fixture envelope publication failure")
        return real_write_immutable(root, name, value)

    def fail_pointer(path, value):
        if failure == "pointer" and path.name == "current.json":
            raise FoundryError("CG1_TEST_POINTER_WRITE_FAILED", "fixture pointer publication failure")
        return real_write_pointer(path, value)

    monkeypatch.setattr(service, "_write_immutable", fail_envelope)
    monkeypatch.setattr(service, "_write_pointer", fail_pointer)
    with pytest.raises(FoundryError):
        service.author(RUN_ID)
    assert len(provider.calls) == 1
    capsule_id = store.summary(RUN_ID)["capsule_id"]
    gm_root = service._root(RUN_ID) / "contexts" / capsule_id / "gm"
    base_bytes = {
        path.relative_to(gm_root).as_posix(): path.read_bytes()
        for path in gm_root.rglob("*")
        if path.is_file()
    }

    class _NoProvider:
        @staticmethod
        def _settings():
            return {"provider_id": "local", "model": "must-not-be-used"}

        @staticmethod
        def complete_json(**_kwargs):
            raise AssertionError("recovery must not call the provider")

    monkeypatch.setattr(service, "_write_immutable", real_write_immutable)
    monkeypatch.setattr(service, "_write_pointer", real_write_pointer)
    service.provider = _NoProvider()
    recovered = service.author(RUN_ID)
    assert recovered["provider_calls"] == 0
    assert recovered["receipt_id"]
    assert {
        path.relative_to(gm_root).as_posix(): path.read_bytes()
        for path in gm_root.rglob("*")
        if path.is_file()
    } == base_bytes


def test_candidate_authoring_records_unexpected_provider_failure_without_success(candidate_context):
    store, _summary = _capture_with_factory(candidate_context)

    class _ExplodingProvider:
        calls = 0

        @staticmethod
        def _settings():
            return {"provider_id": "local", "model": "fixture-local-model"}

        def complete_json(self, **_kwargs):
            self.calls += 1
            raise TimeoutError("provider transport secret must not be persisted")

    provider = _ExplodingProvider()
    service = _authoring(candidate_context, provider, store)
    with pytest.raises(FoundryError) as caught:
        service.author(RUN_ID)
    assert caught.value.code == "GM_AUTHORING_UNEXPECTED_FAILURE"
    assert caught.value.details == {"phase": "provider_or_publication", "cause_type": "TimeoutError"}
    assert provider.calls == 1
    assert not (service._root(RUN_ID) / "current.json").exists()
    attempts = list((service._root(RUN_ID) / "attempts").glob("attempt.*.json"))
    assert len(attempts) == 1
    attempt = json.loads(attempts[0].read_text(encoding="utf-8"))
    assert attempt["error"]["code"] == "GM_AUTHORING_UNEXPECTED_FAILURE"
    assert attempt["error"]["details"] == {"phase": "provider_or_publication", "cause_type": "TimeoutError"}


def test_candidate_authoring_serializes_concurrent_requests_to_one_provider_call(candidate_context):
    store, _summary = _capture_with_factory(candidate_context)
    provider = _Provider(_response("PATH-1"))
    entered = threading.Event()
    release = threading.Event()
    original_complete = provider.complete_json

    def blocked_complete(**kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original_complete(**kwargs)

    provider.complete_json = blocked_complete
    service = _authoring(candidate_context, provider, store)
    results: list[dict] = []
    errors: list[BaseException] = []

    def invoke():
        try:
            results.append(service.author(RUN_ID))
        except BaseException as exc:  # pragma: no cover - assertion below reports any race error
            errors.append(exc)

    first = threading.Thread(target=invoke)
    second = threading.Thread(target=invoke)
    first.start()
    assert entered.wait(5)
    second.start()
    release.set()
    first.join(10)
    second.join(10)

    assert not errors
    assert len(results) == 2
    assert len(provider.calls) == 1
    assert results[0]["receipt_sha256"] == results[1]["receipt_sha256"]
    assert results[0]["capsule_id"] == results[1]["capsule_id"]


def test_candidate_authoring_serializes_cross_process_requests_with_flock(candidate_context):
    store, _summary = _capture_with_factory(candidate_context)
    ctx = multiprocessing.get_context("fork")
    counter = ctx.Value("i", 0)
    entered = ctx.Event()
    release = ctx.Event()
    result_queue = ctx.Queue()
    # The child reconstructs the test database from its root.  Passing the
    # application root pointed the worker at the shared APP data directory,
    # where this fixture's capsule does not exist.  Use the fixture root so
    # both workers resolve the same isolated data/security namespaces.
    root_dir = str(candidate_context.root.settings.data_dir.parent)
    processes = [
        ctx.Process(target=_process_author_worker, args=(root_dir, counter, entered, release, result_queue))
        for _ in range(2)
    ]
    processes[0].start()
    assert entered.wait(5)
    processes[1].start()
    release.set()
    for process in processes:
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()
    results = [result_queue.get(timeout=2) for _ in processes]

    assert all(process.exitcode == 0 for process in processes)
    assert all(result[0] == "ok" for result in results), results
    assert counter.value == 1
    assert len({result[1] for result in results}) == 1
    assert len({result[2] for result in results}) == 1
    assert sorted(result[3] for result in results) == [0, 1]
