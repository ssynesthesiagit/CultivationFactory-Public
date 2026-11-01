from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.core import Database, FoundryError, Settings, canonical_json, sha256_file, sha256_json
from factory_authoring.composite_controller import CompositeControllerAuthoring
from factory_authoring.final_character_workflow import (
    FINAL_CHARACTER_COMPONENT_POINTER_SCHEMA,
    FINAL_CHARACTER_REVIEW_STORE_NAME,
    FINAL_CHARACTER_REVIEW_PREVIEW_SCHEMA,
    FINAL_CHARACTER_WORKFLOW_ROOT_NAME,
    FinalCharacterWorkflowService,
)
import factory_authoring.final_character_materializer as materializer
import factory_authoring.final_character_workflow as workflow_module
from security.integrity import create_test_integrity_service
from security.local_identity import DeterministicTestPrincipalProvider


PROJECT_ID = "project.workflow.synthetic"
CANDIDATE = "a" * 64
PROJECTION = "projection.workflow.synthetic"
COMPOSITE_ID = "composite.workflow.synthetic"
COMPOSITE_ARTIFACT = "b" * 64
IMMORTAL_ART_ID = "tianxia.constructed.immortal_art.workflow"


def _write_json(path: Path, value: Any, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")
    os.chmod(path, mode)


def _service(tmp_path: Path) -> tuple[FinalCharacterWorkflowService, Path]:
    data = tmp_path / "data"
    settings = Settings.from_env(Path(__file__).resolve().parents[1], data)
    return FinalCharacterWorkflowService(Database(settings)), data


def _approval_service(tmp_path: Path) -> tuple[FinalCharacterWorkflowService, Path]:
    data = tmp_path / "data"
    settings = Settings.from_env(Path(__file__).resolve().parents[1], data)
    db = Database(settings)
    db.migrate()
    return FinalCharacterWorkflowService(
        db,
        principal_provider=DeterministicTestPrincipalProvider(),
        integrity=create_test_integrity_service(),
    ), data


def _action_tree(data: Path, *, project_id: str = PROJECT_ID) -> Path:
    root = data / "logs" / "command4" / "action.overlay.synthetic"
    request_sha = "1" * 64
    response_sha = "2" * 64
    source_sha = "3" * 64
    _write_json(
        root / "Command4_Provider_Overlay_Manifest.json",
        {
            "schema": "TianxiaFoundry.Command4ProviderOverlayManifest.v1",
            "overlay_id": "action.overlay.synthetic",
            "provider_id": "server_deterministic",
            "purpose": "factory_command4_action_authoring",
            "request_sha256": request_sha,
            "response_sha256": response_sha,
            "source_workspace_sha256": source_sha,
        },
    )
    _write_json(
        root / "Workspace_Manifest.json",
        {
            "schema_version": "TianxiaFoundry.FactoryCommand1To4Workspace.v1",
            "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
            "project_id": project_id,
            "projection_id": PROJECTION,
        },
    )
    _write_json(
        root / "Command_4" / "Complete_Action_Surface.json",
        {
            "schema_version": "TianxiaFoundry.Command4ProviderCompleteActionSurface.v1",
            "project_id": project_id,
            "status": "COMMAND4_ACTION_AUTHORITY_READY",
            "execution_authority": True,
            "source_workspace_sha256": source_sha,
            "actions": [{"action_id": "action.synthetic", "record_id": "record.synthetic", "economy": "action"}],
            "unresolved": [],
        },
    )
    _write_json(
        root / "Validation" / "Command4_Provider.validation.json",
        {
            "schema": "TianxiaFoundry.Command4ProviderAuthoringEvidence.v1",
            "valid": True,
            "execution_authority": True,
            "provider_id": "server_deterministic",
            "purpose": "factory_command4_action_authoring",
            "request_sha256": request_sha,
            "response_sha256": response_sha,
            "provider_calls": 0,
        },
    )
    _write_json(
        root / "Command_4" / "Provider_Action_Authoring_Audit.json",
        {
            "schema": "TianxiaFoundry.Command4ProviderAudit.v1",
            "execution_authority": True,
            "provider_id": "server_deterministic",
            "purpose": "factory_command4_action_authoring",
            "request_sha256": request_sha,
            "response_sha256": response_sha,
            "source_workspace_sha256": source_sha,
            "provider_calls": 0,
        },
    )
    files = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    }
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(files.items())),
        encoding="utf-8",
    )
    return root


def _composite_tree(data: Path) -> Path:
    root = data / "logs" / "composite" / COMPOSITE_ID
    _write_json(root / "Composite_Controller_Overlay_Manifest.json", {"overlay_id": COMPOSITE_ID})
    _write_json(
        root / "Command_4" / "Composite_Controller_Artifact.json",
        {"project_id": PROJECT_ID, "base_candidate_sha256": CANDIDATE, "projection_id": PROJECTION},
    )
    _write_json(root / "Validation" / "Composite_Controller.validation.json", {"valid": True})
    return root


@pytest.fixture
def validator_state(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    state = {
        "candidate": CANDIDATE,
        "projection": PROJECTION,
        "composite_source": "current",
        "composite_project": PROJECT_ID,
        "immortal_art_name": "Featherfall",
        "immortal_arts_valid": "yes",
    }

    def composite_validate(
        overlay: Path,
        *,
        project_id: str,
        candidate_sha256: str,
        projection_id: str,
        source_workspace: Path,
    ) -> dict[str, Any]:
        source_hash = materializer._workspace_sha256(source_workspace)
        bound_source = source_hash if state["composite_source"] == "current" else state["composite_source"]
        artifact = {
            "project_id": state["composite_project"],
            "base_candidate_sha256": state["candidate"],
            "projection_id": state["projection"],
            "source_workspace_sha256": bound_source,
        }
        return {
            "overlay_id": COMPOSITE_ID,
            "artifact_sha256": COMPOSITE_ARTIFACT,
            "artifact": artifact,
        }

    def immortal_arts(source_workspace: Path) -> dict[str, Any]:
        # The synthetic Action tree has no ledger; the real rules check is
        # covered by test_constructed_immortal_arts.py.
        if state["immortal_arts_valid"] != "yes":
            raise FoundryError("FINAL_CHARACTER_IMMORTAL_ART_INVALID", "synthetic invalid Immortal Art")
        arts = {
            "schema_version": "TianxiaFoundry.ConstructedImmortalArtBinding.v1",
            "arts": [{
                "immortal_art_id": IMMORTAL_ART_ID,
                "name": state["immortal_art_name"],
                "cl_created": 15,
                "action_id": "action.workflow.immortal",
                "art_sha256": "c" * 64,
                "action_sha256": "d" * 64,
            }],
        }
        return {**arts, "binding_sha256": materializer.sha256_json(arts)}

    monkeypatch.setattr(CompositeControllerAuthoring, "validate_overlay", staticmethod(composite_validate))
    monkeypatch.setattr(workflow_module, "constructed_immortal_art_binding", immortal_arts)
    return state


def _record_triplet(
    service: FinalCharacterWorkflowService,
    data: Path,
) -> tuple[Path, Path, list[dict[str, Any]]]:
    action = _action_tree(data)
    composite = _composite_tree(data)
    receipts = [
        service.record_action_workspace(PROJECT_ID, {"valid": True, "overlay_path": str(action)}),
        service.record_composite_controller(PROJECT_ID, {"valid": True, "overlay_path": str(composite)}),
    ]
    assert all(isinstance(receipt, dict) for receipt in receipts)
    return action, composite, receipts  # type: ignore[return-value]


def _workflow_snapshot(root: Path) -> dict[str, tuple[bytes, int, int]]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mode, path.stat().st_ino)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_absent_preview_is_not_ready_and_performs_no_write(tmp_path: Path) -> None:
    service, data = _service(tmp_path)
    workflow = data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME
    assert not workflow.exists()
    result = service.preview_current_triplet(PROJECT_ID)
    assert result == {
        "schema_version": FINAL_CHARACTER_REVIEW_PREVIEW_SCHEMA,
        "project_id": PROJECT_ID,
        "status": "NOT_READY",
        "available": False,
        "provider_calls": 0,
        "details": None,
    }
    assert not workflow.exists()


def test_failed_result_does_not_create_workflow_state(tmp_path: Path) -> None:
    service, data = _service(tmp_path)
    assert service.record_action_workspace(PROJECT_ID, {"valid": False, "overlay_path": "/ignored"}) is None
    assert service.record_composite_controller(PROJECT_ID, None) is None
    assert not hasattr(service, "record_immortal_art")
    assert not (data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME).exists()


def test_caller_asserted_valid_minimal_action_tree_is_rejected_without_workflow_write(tmp_path: Path) -> None:
    service, data = _service(tmp_path)
    root = data / "logs" / "minimal-command4"
    _write_json(root / "Command4_Provider_Overlay_Manifest.json", {"overlay_id": "minimal-command4"})
    _write_json(root / "Command_4/Complete_Action_Surface.json", {"execution_authority": True, "actions": [{"action_id": "invented"}]})
    _write_json(root / "Validation/Command4_Provider.validation.json", {"valid": True, "execution_authority": True})
    with pytest.raises(FoundryError) as error:
        service.record_action_workspace(PROJECT_ID, {"valid": True, "overlay_path": str(root)})
    assert error.value.code == "FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID"
    assert not (data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME).exists()


def test_happy_triplet_is_relative_private_exact_and_preview_is_read_only(
    tmp_path: Path,
    validator_state: dict[str, str],
) -> None:
    del validator_state
    service, data = _service(tmp_path)
    action, _composite, receipts = _record_triplet(service, data)
    for receipt in receipts:
        assert "overlay_path" not in receipt and "overlay_relative_path" not in receipt
    workflow = data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME
    project = workflow / PROJECT_ID
    assert stat_mode(workflow) == 0o700
    assert stat_mode(project) == 0o700
    pointer = json.loads((project / "current.json").read_text(encoding="utf-8"))
    assert pointer["schema_version"] == FINAL_CHARACTER_COMPONENT_POINTER_SCHEMA
    for component, receipt_id in pointer["components"].items():
        stored = project / "components" / f"{receipt_id}.json"
        assert stat_mode(stored) == 0o600
        payload = json.loads(stored.read_text(encoding="utf-8"))
        assert not Path(payload["overlay_relative_path"]).is_absolute()
        assert str(data) not in payload["overlay_relative_path"]
        assert payload["component"] == component
    before = _workflow_snapshot(workflow)
    preview = service.preview_current_triplet(PROJECT_ID)
    after = _workflow_snapshot(workflow)
    assert before == after
    assert preview["status"] == "READY_FOR_OWNER_APPROVAL"
    assert preview["available"] is True
    assert preview["provider_calls"] == 0
    assert preview["binding"]["source_workspace_sha256"] == materializer._workspace_sha256(action)
    assert preview["binding"]["candidate_sha256"] == CANDIDATE
    assert preview["binding"]["projection_id"] == PROJECTION
    assert all("path" not in canonical_json(component) for component in preview["components"])


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_captured_overlay_remains_regular_after_plain_path_cast(tmp_path: Path) -> None:
    service, data = _service(tmp_path)
    original = _composite_tree(data)
    with service._captured_server_tree(str(original), field="composite overlay") as (captured, _):
        plain = Path(captured)
        assert plain.is_dir() and not plain.is_symlink()
        assert (plain / "Command_4/Composite_Controller_Artifact.json").read_bytes() == (
            original / "Command_4/Composite_Controller_Artifact.json"
        ).read_bytes()
        digest = materializer._tree_hash(captured)
        _, relative = service._install_snapshot(PROJECT_ID, "composite_controller", captured, digest)
    assert materializer._tree_hash(data / relative) == digest


def test_identical_action_receipt_is_idempotent_and_not_replaced(tmp_path: Path) -> None:
    service, data = _service(tmp_path)
    action = _action_tree(data)
    result = {"valid": True, "overlay_path": str(action)}
    first = service.record_action_workspace(PROJECT_ID, result)
    assert first is not None
    path = data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / PROJECT_ID / "components" / f"{first['receipt_id']}.json"
    identity = (path.stat().st_ino, path.read_bytes())
    second = service.record_action_workspace(PROJECT_ID, result)
    assert second == first
    assert (path.stat().st_ino, path.read_bytes()) == identity


def test_root_rename_and_symlink_race_cannot_redirect_descriptor_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, data = _service(tmp_path)
    action = _action_tree(data)
    moved = action.with_name("action.overlay.original")
    outside = data / "outside-attacker-tree"
    _write_json(outside / "outside.json", {"escaped": True})
    original_copy = workflow_module._copy_descriptor_tree
    raced = False

    def race_once(source_fd: int, target: Path, budget: dict[str, int]) -> None:
        nonlocal raced
        if not raced:
            action.rename(moved)
            action.symlink_to(outside, target_is_directory=True)
            raced = True
        original_copy(source_fd, target, budget)

    monkeypatch.setattr(workflow_module, "_copy_descriptor_tree", race_once)
    receipt = service.record_action_workspace(PROJECT_ID, {"valid": True, "overlay_path": str(action)})
    assert receipt is not None and raced is True
    project = data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / PROJECT_ID
    stored = json.loads((project / "components" / f"{receipt['receipt_id']}.json").read_text(encoding="utf-8"))
    snapshot = data / stored["overlay_relative_path"]
    assert not (snapshot / "outside.json").exists()
    assert (snapshot / "Command_4/Complete_Action_Surface.json").is_file()


def test_data_root_intermediate_ancestor_swap_fails_closed_without_external_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_parent = tmp_path / "workflow-authority-parent"
    data = authority_parent / "data"
    settings = Settings.from_env(Path(__file__).resolve().parents[1], data)
    service = FinalCharacterWorkflowService(Database(settings))
    action = _action_tree(data)
    outside = tmp_path / "workflow-outside"
    outside.mkdir(mode=0o700)
    moved = tmp_path / "workflow-authority-parent-moved"
    original_copy = workflow_module._copy_descriptor_tree
    raced = False

    def race_once(source_fd: int, target: Path, budget: dict[str, int]) -> None:
        nonlocal raced
        if not raced:
            authority_parent.rename(moved)
            authority_parent.symlink_to(outside, target_is_directory=True)
            raced = True
        original_copy(source_fd, target, budget)

    monkeypatch.setattr(workflow_module, "_copy_descriptor_tree", race_once)
    with pytest.raises(FoundryError) as error:
        service.record_action_workspace(PROJECT_ID, {"valid": True, "overlay_path": str(action)})

    assert raced is True
    assert error.value.code == "FINAL_CHARACTER_DIRECTORY_AUTHORITY_CHANGED"
    assert not any(outside.iterdir())


@pytest.mark.parametrize("kind", ["escape", "root_symlink", "child_symlink", "cross_project"])
def test_record_rejects_untrusted_action_tree_without_workflow_write(tmp_path: Path, kind: str) -> None:
    service, data = _service(tmp_path)
    if kind == "escape":
        action = _action_tree(tmp_path / "outside")
    else:
        action = _action_tree(data, project_id="project.other" if kind == "cross_project" else PROJECT_ID)
        if kind == "root_symlink":
            target = action
            action = data / "logs" / "action-link"
            action.symlink_to(target, target_is_directory=True)
        elif kind == "child_symlink":
            (action / "leak").symlink_to(tmp_path / "outside-file")
    with pytest.raises(FoundryError) as error:
        service.record_action_workspace(PROJECT_ID, {"valid": True, "overlay_path": str(action)})
    assert error.value.code in {
        "FINAL_CHARACTER_WORKFLOW_PATH_ESCAPE",
        "FINAL_CHARACTER_WORKFLOW_SYMLINK_REJECTED",
        "FINAL_CHARACTER_COMPONENT_PROJECT_MISMATCH",
    }
    assert not (data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME).exists()


def test_stale_overlay_fails_before_preview_write(tmp_path: Path, validator_state: dict[str, str]) -> None:
    del validator_state
    service, data = _service(tmp_path)
    _action, _composite, _receipts = _record_triplet(service, data)
    workflow = data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME
    project = workflow / PROJECT_ID
    pointer = json.loads((project / "current.json").read_text(encoding="utf-8"))
    receipt = json.loads((project / "components" / f"{pointer['components']['composite_controller']}.json").read_text(encoding="utf-8"))
    snapshot = data / receipt["overlay_relative_path"]
    os.chmod(snapshot, 0o700)
    _write_json(snapshot / "new-file.json", {"changed": True})
    before = _workflow_snapshot(workflow)
    with pytest.raises(FoundryError) as error:
        service.preview_current_triplet(PROJECT_ID)
    assert error.value.code == "FINAL_CHARACTER_COMPONENT_STALE"
    assert _workflow_snapshot(workflow) == before


@pytest.mark.parametrize("target", ["pointer", "receipt"])
def test_tampered_workflow_object_fails_closed(tmp_path: Path, validator_state: dict[str, str], target: str) -> None:
    del validator_state
    service, data = _service(tmp_path)
    _record_triplet(service, data)
    project = data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / PROJECT_ID
    if target == "pointer":
        path = project / "current.json"
    else:
        pointer = json.loads((project / "current.json").read_text(encoding="utf-8"))
        path = project / "components" / f"{pointer['components']['composite_controller']}.json"
    _write_json(path, {"tampered": True}, mode=0o600)
    with pytest.raises(FoundryError) as error:
        service.preview_current_triplet(PROJECT_ID)
    assert error.value.code in {"FINAL_CHARACTER_CURRENT_POINTER_INVALID", "FINAL_CHARACTER_COMPONENT_RECEIPT_INVALID"}


@pytest.mark.parametrize("mismatch", ["candidate", "projection", "source", "project"])
def test_fresh_validation_binding_mismatch_fails_closed(
    tmp_path: Path,
    validator_state: dict[str, str],
    mismatch: str,
) -> None:
    service, data = _service(tmp_path)
    _record_triplet(service, data)
    if mismatch == "candidate":
        validator_state["candidate"] = "e" * 64
    elif mismatch == "projection":
        validator_state["projection"] = "projection.changed"
    elif mismatch == "source":
        validator_state["composite_source"] = "f" * 64
    else:
        validator_state["composite_project"] = "project.other"
    before = _workflow_snapshot(data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME)
    with pytest.raises(FoundryError) as error:
        service.preview_current_triplet(PROJECT_ID)
    assert error.value.code in {
        "FINAL_CHARACTER_COMPONENT_STALE",
        "FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH",
        "FINAL_CHARACTER_PROJECTION_BINDING_MISMATCH",
    }
    assert _workflow_snapshot(data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME) == before


def test_existing_0644_candidate_pointer_is_read_but_cannot_substitute_identity(
    tmp_path: Path,
    validator_state: dict[str, str],
) -> None:
    del validator_state
    service, data = _service(tmp_path)
    _record_triplet(service, data)
    pointer = data / "factory_candidates" / PROJECT_ID / "current.json"
    _write_json(
        pointer,
        {"project_id": PROJECT_ID, "candidate_sha256": "9" * 64, "projection_id": PROJECTION},
        mode=0o644,
    )
    with pytest.raises(FoundryError) as error:
        service.preview_current_triplet(PROJECT_ID)
    assert error.value.code == "FINAL_CHARACTER_CANDIDATE_BINDING_MISMATCH"


def test_content_address_collision_never_replaces_existing_bytes(tmp_path: Path) -> None:
    service, data = _service(tmp_path)
    action = _action_tree(data)
    result = {"valid": True, "overlay_path": str(action)}
    first = service.record_action_workspace(PROJECT_ID, result)
    assert first is not None
    path = data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / PROJECT_ID / "components" / f"{first['receipt_id']}.json"
    path.write_text("occupied\n", encoding="utf-8")
    os.chmod(path, 0o600)
    before = path.read_bytes()
    with pytest.raises(FoundryError) as error:
        service.record_action_workspace(PROJECT_ID, result)
    assert error.value.code == "FINAL_CHARACTER_COMPONENT_COLLISION"
    assert path.read_bytes() == before


@pytest.mark.parametrize("prefix", ["-", "_", "A"])
def test_review_challenge_approval_is_exact_once_and_redacted(
    tmp_path: Path,
    validator_state: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
) -> None:
    del validator_state
    monkeypatch.setattr("security.approval_challenges.secrets.token_urlsafe", lambda _size: prefix + "x" * 42)
    service, data = _approval_service(tmp_path)
    _record_triplet(service, data)

    issued = service.issue_review_challenge(PROJECT_ID, ttl_seconds=300)
    challenge = issued["challenge"]
    assert issued["status"] == "ISSUED"
    assert issued["provider_calls"] == 0
    assert challenge["nonce"]
    assert "binding" not in issued and "evidence_context" not in canonical_json(issued)
    assert str(data) not in canonical_json(issued)

    approved = service.approve_current_triplet(PROJECT_ID, challenge["challenge_id"], challenge["nonce"])
    assert approved["status"] == "APPROVED"
    assert approved["provider_calls"] == 0
    assert approved["review_record_id"].startswith("final-review.")
    assert "reviewer_id" not in canonical_json(approved)
    assert "binding" not in approved
    assert str(data) not in canonical_json(approved)
    assert list((data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / "reviews").glob("final-review.*.json"))

    with pytest.raises(FoundryError) as error:
        service.approve_current_triplet(PROJECT_ID, challenge["challenge_id"], challenge["nonce"])
    assert error.value.code == "APPROVAL_CHALLENGE_ALREADY_CONSUMED"


def test_review_root_intermediate_ancestor_swap_fails_closed_without_external_write(
    tmp_path: Path,
    validator_state: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del validator_state
    service, data = _approval_service(tmp_path)
    _record_triplet(service, data)
    binding = service._derive_triplet(PROJECT_ID)["binding"]
    review_parent = tmp_path / "review-authority-parent"
    review_root = review_parent / "records"
    review_root.mkdir(parents=True, mode=0o700)
    outside = tmp_path / "review-outside"
    outside.mkdir(mode=0o700)
    moved = tmp_path / "review-authority-parent-moved"
    original_open = materializer._open_fixed_directory
    open_calls = 0
    raced = False

    def open_raced(path: Path | str, *, create: bool, mode: int = 0o700):
        nonlocal open_calls, raced
        authority = original_open(path, create=create, mode=mode)
        if Path(path) == review_root and create:
            open_calls += 1
            if open_calls == 2:
                # The first create=True call is _ensure_review_root; the
                # second is _open_root, after its descriptor is held.
                review_parent.rename(moved)
                review_parent.symlink_to(outside, target_is_directory=True)
                raced = True
        return authority

    monkeypatch.setattr(materializer, "_open_fixed_directory", open_raced)
    with pytest.raises(FoundryError) as error:
        materializer._persist_review_record(
            review_root,
            service.integrity,
            binding,
            {"decision": "approved", "reviewer_id": "reviewer", "evidence_id": "evidence"},
        )

    assert raced is True
    assert error.value.code == "FINAL_CHARACTER_DIRECTORY_AUTHORITY_CHANGED"
    assert not any(outside.iterdir())


def test_output_root_intermediate_ancestor_swap_fails_closed_without_external_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_parent = tmp_path / "output-authority-parent"
    output_root = output_parent / "published"
    output_root.mkdir(parents=True, mode=0o700)
    outside = tmp_path / "output-outside"
    outside.mkdir(mode=0o700)
    moved = tmp_path / "output-authority-parent-moved"
    original_open = materializer._open_fixed_directory
    raced = False

    def open_raced(path: Path | str, *, create: bool, mode: int = 0o700):
        nonlocal raced
        authority = original_open(path, create=create, mode=mode)
        if Path(path) == output_root and not raced:
            output_parent.rename(moved)
            output_parent.symlink_to(outside, target_is_directory=True)
            raced = True
        return authority

    monkeypatch.setattr(materializer, "_open_fixed_directory", open_raced)
    with pytest.raises(FoundryError) as error:
        materializer._ensure_private_output_root(output_root)

    assert raced is True
    assert error.value.code == "FINAL_CHARACTER_OUTPUT_ROOT_CHANGED"
    assert not any(outside.iterdir())


def test_review_handoff_rejects_preopen_ancestor_swap_without_external_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _data = _service(tmp_path)
    review_binding = service._review_store_binding(create=True)
    review_root, expected_identity = review_binding
    assert expected_identity is not None
    review_parent = review_root.parent
    moved = tmp_path / "review-handoff-original"
    attacker_parent = tmp_path / "review-handoff-attacker"
    attacker_root = attacker_parent / FINAL_CHARACTER_REVIEW_STORE_NAME
    attacker_root.mkdir(parents=True, mode=0o700)
    marker = attacker_root / "marker"
    marker.write_bytes(b"attacker-before\n")
    before = marker.read_bytes()
    original_open = materializer._open_fixed_directory
    raced = False

    def open_before(path: Path | str, *, create: bool, mode: int = 0o700):
        nonlocal raced
        if Path(path) == review_root and not raced:
            review_parent.rename(moved)
            attacker_parent.rename(review_parent)
            raced = True
        return original_open(path, create=create, mode=mode)

    monkeypatch.setattr(materializer, "_open_fixed_directory", open_before)
    with pytest.raises(FoundryError) as error:
        materializer.FinalCharacterReviewAuthority(
            review_root,
            service.integrity,
            expected_identity=expected_identity,
            expected_present=True,
        )

    assert raced is True
    assert error.value.code == "FINAL_CHARACTER_REVIEW_STORE_CHANGED"
    assert (review_root / "marker").read_bytes() == before


def test_output_handoff_rejects_preopen_ancestor_swap_without_external_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _data = _service(tmp_path)
    workflow_root = service._workflow_root(create=True)
    project_root = service._private_child(workflow_root, PROJECT_ID, create=True)
    output_binding = service._private_child(
        project_root,
        "materializations",
        create=True,
        include_identity=True,
    )
    assert isinstance(output_binding, tuple)
    _held_output_root, expected_identity = output_binding
    assert expected_identity is not None
    output_root = service.data_root / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / PROJECT_ID / "materializations"
    output_parent = output_root.parent
    moved = tmp_path / "output-handoff-original"
    attacker_parent = tmp_path / "output-handoff-attacker"
    attacker_root = attacker_parent / "materializations"
    attacker_root.mkdir(parents=True, mode=0o700)
    marker = attacker_root / "marker"
    marker.write_bytes(b"attacker-before\n")
    before = marker.read_bytes()
    original_open = materializer._open_fixed_directory
    raced = False

    def open_before(path: Path | str, *, create: bool, mode: int = 0o700):
        nonlocal raced
        if Path(path) == output_root and not raced:
            output_parent.rename(moved)
            attacker_parent.rename(output_parent)
            raced = True
        return original_open(path, create=create, mode=mode)

    monkeypatch.setattr(materializer, "_open_fixed_directory", open_before)
    with pytest.raises(FoundryError) as error:
        materializer._ensure_private_output_root(
            output_root,
            expected_identity=expected_identity,
            expected_present=True,
        )

    assert raced is True
    assert error.value.code == "FINAL_CHARACTER_OUTPUT_ROOT_CHANGED"
    assert (output_root / "marker").read_bytes() == before


def test_review_workflow_handoff_rejects_preopen_ancestor_swap_without_external_write(
    tmp_path: Path,
    validator_state: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del validator_state
    service, data = _approval_service(tmp_path)
    _record_triplet(service, data)
    monkeypatch.setattr(workflow_module.secrets, "token_urlsafe", lambda _size: "n" * 43)
    issued = service.issue_review_challenge(PROJECT_ID)
    challenge = issued["challenge"]
    review_root = service.review_root
    review_parent = review_root.parent
    moved = tmp_path / "review-workflow-handoff-original"
    attacker_parent = tmp_path / "review-workflow-handoff-attacker"
    attacker_root = attacker_parent / FINAL_CHARACTER_REVIEW_STORE_NAME
    attacker_root.mkdir(parents=True, mode=0o700)
    marker = attacker_root / "marker"
    marker.write_bytes(b"attacker-before\n")
    before = marker.read_bytes()
    original_open = materializer._open_fixed_directory
    raced = False

    def open_before(path: Path | str, *, create: bool, mode: int = 0o700):
        nonlocal raced
        if Path(path) == review_root and not raced:
            review_parent.rename(moved)
            attacker_parent.rename(review_parent)
            raced = True
        return original_open(path, create=create, mode=mode)

    monkeypatch.setattr(materializer, "_open_fixed_directory", open_before)
    with pytest.raises(FoundryError) as error:
        service.approve_current_triplet(PROJECT_ID, challenge["challenge_id"], challenge["nonce"])

    assert raced is True
    assert error.value.code == "FINAL_CHARACTER_REVIEW_STORE_CHANGED"
    assert (review_root / "marker").read_bytes() == before


def test_materialization_output_workflow_handoff_rejects_preopen_ancestor_swap_without_external_write(
    tmp_path: Path,
    validator_state: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del validator_state
    service, data = _approval_service(tmp_path)
    _record_triplet(service, data)
    monkeypatch.setattr(workflow_module.secrets, "token_urlsafe", lambda _size: "n" * 43)
    issued = service.issue_review_challenge(PROJECT_ID)
    challenge = issued["challenge"]
    approved = service.approve_current_triplet(PROJECT_ID, challenge["challenge_id"], challenge["nonce"])
    output_root = data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / PROJECT_ID / "materializations"
    output_parent = output_root.parent
    moved = tmp_path / "output-workflow-handoff-original"
    attacker_parent = tmp_path / "output-workflow-handoff-attacker"
    attacker_root = attacker_parent / "materializations"
    attacker_root.mkdir(parents=True, mode=0o700)
    marker = attacker_root / "marker"
    marker.write_bytes(b"attacker-before\n")
    before = marker.read_bytes()
    original_open = materializer._open_fixed_directory
    raced = False

    def open_before(path: Path | str, *, create: bool, mode: int = 0o700):
        nonlocal raced
        if Path(path) == output_root and not raced:
            output_parent.rename(moved)
            attacker_parent.rename(output_parent)
            raced = True
        return original_open(path, create=create, mode=mode)

    monkeypatch.setattr(materializer, "_open_fixed_directory", open_before)
    with pytest.raises(FoundryError) as error:
        service.materialize_current_triplet(PROJECT_ID, approved["review_record_id"])

    assert raced is True
    assert error.value.code == "FINAL_CHARACTER_OUTPUT_ROOT_CHANGED"
    assert (output_root / "marker").read_bytes() == before


def test_changed_binding_rejects_existing_review_challenge(
    tmp_path: Path,
    validator_state: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del validator_state
    service, data = _approval_service(tmp_path)
    _record_triplet(service, data)
    issued = service.issue_review_challenge(PROJECT_ID)
    challenge = issued["challenge"]
    original = service._derive_triplet(PROJECT_ID)
    changed = json.loads(json.dumps(original))
    changed_binding = changed["binding"]
    changed_binding["candidate_sha256"] = "e" * 64
    changed_binding["binding_sha256"] = sha256_json(
        {key: changed_binding[key] for key in sorted(set(changed_binding) - {"binding_sha256"})}
    )
    monkeypatch.setattr(service, "_derive_triplet", lambda _project_id: changed)

    with pytest.raises(FoundryError) as error:
        service.approve_current_triplet(PROJECT_ID, challenge["challenge_id"], challenge["nonce"])
    assert error.value.code in {
        "APPROVAL_CHALLENGE_SUBJECT_MISMATCH",
        "APPROVAL_CHALLENGE_BYTES_CHANGED",
        "APPROVAL_CHALLENGE_BINDING_CHANGED",
    }
    assert not list((data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / "reviews").glob("final-review.*.json"))


def test_materialization_requires_current_approved_record_before_output(
    tmp_path: Path,
    validator_state: dict[str, str],
) -> None:
    del validator_state
    service, data = _approval_service(tmp_path)
    _record_triplet(service, data)
    missing_record = "final-review." + "f" * 64
    with pytest.raises(FoundryError) as error:
        service.materialize_current_triplet(PROJECT_ID, missing_record)
    assert error.value.code == "FINAL_CHARACTER_REVIEW_RECORD_NOT_FOUND"
    assert not (data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / PROJECT_ID / "materializations").exists()


def test_materialization_rejects_persisted_record_for_other_project_before_output(
    tmp_path: Path,
    validator_state: dict[str, str],
) -> None:
    del validator_state
    service, data = _approval_service(tmp_path)
    _record_triplet(service, data)
    current_binding = service._derive_triplet(PROJECT_ID)["binding"]
    other_binding = json.loads(json.dumps(current_binding))
    other_binding["project_id"] = "project.other"
    other_binding["binding_sha256"] = sha256_json(
        {key: other_binding[key] for key in sorted(set(other_binding) - {"binding_sha256"})}
    )
    other_record = materializer._persist_review_record(
        service.review_root,
        service.integrity,
        other_binding,
        {"decision": "approved", "reviewer_id": "other-reviewer", "evidence_id": "evidence.other"},
    )
    assert other_record["binding"]["project_id"] == "project.other"
    with pytest.raises(FoundryError) as error:
        service.materialize_current_triplet(PROJECT_ID, other_record["record_id"])
    assert error.value.code == "FINAL_CHARACTER_REVIEW_BINDING_MISMATCH"
    assert not (data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / PROJECT_ID / "materializations").exists()


def test_materialization_uses_held_server_snapshots_and_redacts_paths(
    tmp_path: Path,
    validator_state: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del validator_state
    service, data = _approval_service(tmp_path)
    _record_triplet(service, data)
    challenge = service.issue_review_challenge(PROJECT_ID)["challenge"]
    approved = service.approve_current_triplet(PROJECT_ID, challenge["challenge_id"], challenge["nonce"])
    captured: dict[str, Any] = {}
    materialize_calls = 0

    def fake_materialize(
        _self: Any,
        source_workspace: Path,
        composite_overlay: Path,
        output_root: Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        nonlocal materialize_calls
        materialize_calls += 1
        captured.update({
            "source": source_workspace,
            "composite": composite_overlay,
            "output": output_root,
            "kwargs": kwargs,
        })
        return {
            "materialization_id": "f" * 64,
            "idempotent": materialize_calls > 1,
            "output_path": "/must-not-leak/workspace",
            "receipt": {"output_tree_sha256": "e" * 64, "output_path": "/must-not-leak/workspace"},
        }

    monkeypatch.setattr(materializer.FinalCharacterMaterializer, "materialize", fake_materialize)
    result = service.materialize_current_triplet(PROJECT_ID, approved["review_record_id"])
    assert result["status"] == "MATERIALIZED"
    assert result["idempotent"] is False
    assert result["output_tree_sha256"] == "e" * 64
    assert "output_path" not in canonical_json(result)
    assert str(data) not in canonical_json(result)
    assert captured["kwargs"]["review_record_id"] == approved["review_record_id"]
    assert captured["output"] == data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / PROJECT_ID / "materializations"
    assert all(str(captured[name]).startswith("/proc/self/fd/") for name in ("source", "composite"))
    again = service.materialize_current_triplet(PROJECT_ID, approved["review_record_id"])
    assert again["status"] == "ALREADY_MATERIALIZED"
    assert again["idempotent"] is True
    assert again["materialization_id"] == result["materialization_id"]
    assert again["output_tree_sha256"] == "e" * 64


def test_factory_authoring_hooks_record_only_valid_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from factory_authoring import service as authoring_service_module
    from factory_authoring import command4_provider, composite_controller

    class FakeFinalWorkflow:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def _receipt(self, component: str) -> dict[str, str]:
            self.calls.append((component, PROJECT_ID))
            return {"receipt_id": f"component.{component}." + "a" * 64}

        def record_action_workspace(self, project_id: str, _result: Any) -> dict[str, str]:
            return self._receipt("command4")

        def record_composite_controller(self, project_id: str, _result: Any) -> dict[str, str]:
            return self._receipt("composite_controller")

    workflow = FakeFinalWorkflow()
    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / "data")
    authoring = authoring_service_module.FactoryAuthoringWorkspaceService(
        Database(settings),
        final_character_workflow=workflow,
    )

    class FakeCommand4:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def author(self, _project_id: str, _provider: Any, _output_root: Path) -> dict[str, Any]:
            return {"valid": True, "overlay_path": str(tmp_path / "command4")}

    class FakeComposite(FakeCommand4):
        pass

    monkeypatch.setattr(command4_provider, "Command4ProviderAuthoring", FakeCommand4)
    monkeypatch.setattr(composite_controller, "CompositeControllerAuthoring", FakeComposite)

    command4 = authoring.author_command4(PROJECT_ID, object())
    composite = authoring.author_composite_controller(PROJECT_ID, object())
    assert command4["final_character_component"]["receipt_id"].startswith("component.command4.")
    assert composite["final_character_component"]["receipt_id"].startswith("component.composite_controller.")
    assert not hasattr(authoring, "author_immortal_art")
    assert [name for name, _project in workflow.calls] == ["command4", "composite_controller"]

    class InvalidCommand4(FakeCommand4):
        def author(self, _project_id: str, _provider: Any, _output_root: Path) -> dict[str, Any]:
            return {"valid": False, "overlay_path": str(tmp_path / "invalid")}

    monkeypatch.setattr(command4_provider, "Command4ProviderAuthoring", InvalidCommand4)
    invalid = authoring.author_command4(PROJECT_ID, object())
    assert invalid["valid"] is False
    assert len(workflow.calls) == 2


def test_invalid_constructed_immortal_art_blocks_review_without_write(
    tmp_path: Path,
    validator_state: dict[str, str],
) -> None:
    service, data = _service(tmp_path)
    _record_triplet(service, data)
    validator_state["immortal_arts_valid"] = "no"
    before = _workflow_snapshot(data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME)
    with pytest.raises(FoundryError) as error:
        service.preview_current_triplet(PROJECT_ID)
    assert error.value.code == "FINAL_CHARACTER_IMMORTAL_ART_INVALID"
    assert _workflow_snapshot(data / FINAL_CHARACTER_WORKFLOW_ROOT_NAME) == before


def test_review_binding_carries_the_constructed_immortal_arts(
    tmp_path: Path,
    validator_state: dict[str, str],
) -> None:
    service, data = _approval_service(tmp_path)
    _record_triplet(service, data)
    preview = service.preview_current_triplet(PROJECT_ID)
    arts = preview["binding"]["constructed_immortal_arts"]["arts"]
    assert [(art["immortal_art_id"], art["cl_created"]) for art in arts] == [(IMMORTAL_ART_ID, 15)]
    assert [row["component"] for row in preview["components"]] == ["command4", "composite_controller"]
    challenge = service.issue_review_challenge(PROJECT_ID)["challenge"]
    approved = service.approve_current_triplet(PROJECT_ID, challenge["challenge_id"], challenge["nonce"])
    # A changed Immortal Art after approval invalidates the persisted review.
    validator_state["immortal_art_name"] = "Qi Armor"
    with pytest.raises(FoundryError) as error:
        service.materialize_current_triplet(PROJECT_ID, approved["review_record_id"])
    assert error.value.code == "FINAL_CHARACTER_REVIEW_BINDING_MISMATCH"
