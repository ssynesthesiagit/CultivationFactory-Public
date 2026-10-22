from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_file, sha256_json
from character_sheet.service import CharacterSheetService
from factory_authoring.service import FactoryAuthoringWorkspaceService
from gm_export.service import GMCharacterExportService
from security.approval_challenges import ApprovalChallengeService
from security.integrity import create_test_integrity_service
from security.local_identity import BoundPrincipalProvider, LocalPrincipal
from test_candidate_gm_context import _synthetic_composite_provider_result, _synthetic_factory_workspace

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "6a64af8e-7b8f-447b-bd81-fe4432b048c2"
EXPECTED_SHEET_SHA256 = "1258491740010cee4db25055bc24889c2ac26e14faf9d222bcef95426650800d"
EXPECTED_WORKSPACE_ID = "8c50a7f0f82f03f3f6b10974c31443a78d2adf7309effccd7222d1d4c2caabc6"
EXPECTED_WORKSPACE_SHA256 = "aec44b9b1b9ebd5bae7e8a737bc811e7bf3b0951e4d79dce788089335db9f1e4"
EXPECTED_ADVANCEMENT_HASHES = {
    "Character_Master_Ledger.json": "a0abf32f57cdc5780e86a281e8f1a3c533c7019294c9426a069e4f91fe6fda97",
    "Rules_Selection_Packets.json": "7257a45dad5c24a667bd6984f4ece14b53f12db4eeb18e40ebc46a828196d071",
    "Projection_Provenance_Map.json": "2f306c14a4143ca967cc0cf5e516d74e9b52459c0db716749284d87c574a40b4",
    "Projection_Coverage_Report.json": "879b04f36ba8e6d9b95101341ed292b93f52c96b637856bdcb9aef79db5ccf91",
    "Projection_Diagnostics.json": "1e8401c7396c99df95098d4eb533ee90da49c9f0083508cf711b8364bf1451f3",
}


def _roots() -> list[Path]:
    values = [value for value in os.getenv("TIANXIA_C2B2_DATA_ROOTS", "").split(os.pathsep) if value]
    if len(values) < 2:
        pytest.skip("Two C2B.2 clean data roots are not configured")
    return [Path(value) for value in values[:2]]


def _artifact_dir() -> Path:
    value = os.getenv("TIANXIA_C2B2_ADVANCEMENT_ARTIFACT_DIR")
    if not value:
        pytest.skip("C2A-R.1 advancement artifact directory is not configured")
    return Path(value)


def _service(data_root: Path) -> FactoryAuthoringWorkspaceService:
    return FactoryAuthoringWorkspaceService(Database(Settings.from_env(ROOT, data_root)))


def _sheet_snapshot(data_root: Path) -> dict:
    return CharacterSheetService(Database(Settings.from_env(ROOT, data_root))).sheet(PROJECT_ID)["owner_character_sheet"]


def _configure_synthetic_gm_route(service, tmp_path: Path, project_id: str) -> dict:
    workspace, factory = _synthetic_factory_workspace(
        tmp_path,
        project_id=project_id,
        project_revision=4,
        projection_id=f"projection.{project_id}",
        candidate_sha256=sha256_json({"project_id": project_id, "project_revision": 4}),
    )
    settings = SimpleNamespace(
        root_dir=ROOT,
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        security_dir=tmp_path / "security",
    )
    settings.data_dir.mkdir()
    settings.logs_dir.mkdir()
    settings.security_dir.mkdir()
    service.db = SimpleNamespace(settings=settings)
    service.status = lambda value: {
        "available": True,
        "workspace_path": str(workspace),
        "workspace_sha256": factory["workspace_sha256"],
        "workspace_status": factory["workspace_status"],
    } if value == project_id else {"available": False}
    return factory


def _project_derived_gm_fixture() -> tuple[FactoryAuthoringWorkspaceService, dict, dict, dict]:
    service = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
    service.db = SimpleNamespace(settings=SimpleNamespace(root_dir=ROOT))
    sealed_profile, sealed_profile_sha = service._authoring_profile()
    workspace_profile, workspace_profile_sha = service._workspace_profile()
    card = {
        "record_id": "selected.record.one",
        "display_name": "Selected Record",
        "record_hash": "record-hash",
        "source_packet_ids": ["packet.selected"],
        "source": {"path": "LocalSources/selected.txt", "anchor": "selected"},
        "acquisition_cl": 1,
        "capabilities": {"combat_execution": "NOT_APPLICABLE", "gm_display": "SUPPORTED", "ai_policy": "BLOCKED_BY_DEPENDENCY"},
        "display_only_not_execution_authority": True,
        "section": "selected_records",
    }
    snapshot = {
        "identity": {"display_name": "Derived Fixture", "cultivation_level": 1, "realm": "Mortal"},
        "selected_record_sections": {"selected_records": [card]},
        "capability_status": {"records": [], "pending_execution_surfaces": []},
        "advancement_history": {"owner_choice_locks": []},
        "explicit_none_systems": {"method": {"state": "none", "source_backed": True}, "foundation": {"state": "none", "source_backed": True}},
        "recorded_arts": [],
        "forged_techniques": [],
        "immortal_arts": [],
        "training_sources": [],
        "background_and_origin": {},
        "path_and_subpath": {},
        "spheres_and_talents": {},
        "method": {},
        "foundation": {},
    }
    workspace_profile["required_training_source_coverage"] = ["sealed.record"]
    return service, snapshot, {
        "profile": sealed_profile,
        "profile_sha": sealed_profile_sha,
        "workspace": workspace_profile,
        "workspace_sha": workspace_profile_sha,
    }, card


def test_c2b2_project_derived_gm_guidance_is_provisional_and_not_complete():
    service, snapshot, sealed, _card = _project_derived_gm_fixture()
    profile, _profile_sha, workspace, _workspace_sha = service._project_authoring_profile(
        snapshot,
        sealed["profile"],
        sealed["profile_sha"],
        sealed["workspace"],
        sealed["workspace_sha"],
    )

    assert profile["authority_classification"] == "PROVISIONAL_GM_GUIDANCE"
    assert profile["authorship"]["status"] == "PROVISIONAL"
    assert profile["authorship"]["artifact_bound"] is False
    assert profile["authorship"]["owner_ratified"] is False
    assert profile["dao_i_ching"]["classification"] == "PROVISIONAL_GM_GUIDANCE"
    assert "OWNER_RATIFIED_GM_AUTHORING" not in canonical_json(profile)
    assert workspace["semantics"]["gm_authoring"] == "PROVISIONAL_GM_GUIDANCE_ONLY"
    assert workspace["legacy_boundaries"]["eligible_for_later_command5_checkpoint"] is False

    service._validate_profile(profile, workspace, snapshot)
    documents = service._documents(
        project={"project_id": "project.derived", "revision": 1},
        sheet_response={"owner_character_sheet": snapshot, "provenance": {"advancement_projection": {"projection": {}}}, "sheet_artifact": {"sha256": "sheet-hash"}},
        profile=profile,
        profile_sha=_profile_sha,
        workspace_profile=workspace,
        workspace_profile_sha=_workspace_sha,
        projection_artifacts={
            "Character_Master_Ledger.json": {"advancement": {"event_count": 0, "event_head_hash": "0" * 64}, "character": {}, "core_stats": {}, "resources": {}, "typed_none": {}},
            "Rules_Selection_Packets.json": {"packets": []},
            "Projection_Provenance_Map.json": {},
        },
    )
    assert documents["Command_3/Subsystem_Completion_Ledger.json"]["gm_authoring"] == "PROVISIONAL_GM_GUIDANCE_ONLY"
    assert documents["Command_4/Training_Sources.json"]["classification"] == "PROVISIONAL_GM_GUIDANCE"
    assert documents["Command_4/Behavior_and_Dao_Audit.json"]["status"] == "PROVISIONAL_GM_GUIDANCE_ONLY"
    assert "GM_AUTHORING_COMPLETE" not in canonical_json(documents)
    assert "COMPLETE_AS_WORKSPACE_INPUT" not in canonical_json(documents)
    service._validate_documents(documents, workspace, profile)

    tampered = copy.deepcopy(documents)
    tampered["Command_4/Training_Sources.json"]["classification"] = "OWNER_RATIFIED_GM_AUTHORING"
    with pytest.raises(FoundryError) as exc:
        service._validate_documents(tampered, workspace, profile)
    assert exc.value.code == "FACTORY_WORKSPACE_BUILD_BLOCKED"


def test_c2b2_caller_metadata_cannot_create_actual_gm_artifact_binding():
    service, snapshot, sealed, _card = _project_derived_gm_fixture()
    provisional, _provisional_sha, workspace, _workspace_sha = service._project_authoring_profile(
        snapshot,
        sealed["profile"],
        sealed["profile_sha"],
        sealed["workspace"],
        sealed["workspace_sha"],
    )
    actual = copy.deepcopy(provisional)
    actual["profile_id"] = "Tianxia_Actual_GM_Tactical_Authoring_fixture"
    actual["authority_classification"] = "ACTUAL_GM_AUTHORING"
    actual["authorship"] = {
        "schema_version": "TianxiaFoundry.GMAuthorshipBinding.v1",
        "status": "ACTUAL",
        "origin": "provider_model_artifact",
        "provider_id": "lemonade",
        "artifact_bound": True,
        "artifact_sha256": "a" * 64,
        "owner_ratified": False,
        "source_record_ids": ["selected.record.one"],
    }
    actual["dao_i_ching"]["classification"] = "ACTUAL_GM_AUTHORING"
    with pytest.raises(FoundryError) as exc:
        service._validate_profile(actual, workspace, snapshot)
    assert exc.value.code == "GM_AUTHORING_PROFILE_BLOCKED"
    assert any(
        diagnostic.get("code") == "GM_AUTHORING_ACTUAL_ARTIFACT_UNVERIFIED"
        for diagnostic in (exc.value.details or {}).get("diagnostics", [])
    )


def test_c2b2_actual_gm_fabricated_artifact_hash_is_rejected_without_server_receipt():
    service, snapshot, sealed, _card = _project_derived_gm_fixture()
    provisional, _provisional_sha, workspace, _workspace_sha = service._project_authoring_profile(
        snapshot,
        sealed["profile"],
        sealed["profile_sha"],
        sealed["workspace"],
        sealed["workspace_sha"],
    )
    actual = copy.deepcopy(provisional)
    actual["profile_id"] = "Tianxia_Actual_GM_Tactical_Authoring_spoof"
    actual["authority_classification"] = "ACTUAL_GM_AUTHORING"
    actual["authorship"] = {
        "schema_version": "TianxiaFoundry.GMAuthorshipBinding.v1",
        "status": "ACTUAL",
        "origin": "provider_model_artifact",
        "provider_id": "lemonade",
        "artifact_bound": True,
        "artifact_sha256": "a" * 64,
        "owner_ratified": False,
        "source_record_ids": ["selected.record.one"],
    }
    actual["dao_i_ching"]["classification"] = "ACTUAL_GM_AUTHORING"

    with pytest.raises(FoundryError) as exc:
        service._validate_profile(actual, workspace, snapshot)

    assert exc.value.code == "GM_AUTHORING_PROFILE_BLOCKED"
    assert any(
        diagnostic.get("code") == "GM_AUTHORING_ACTUAL_ARTIFACT_UNVERIFIED"
        for diagnostic in (exc.value.details or {}).get("diagnostics", [])
    )


def _actual_gm_response(record_id: str) -> dict:
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
        "dao": copy.deepcopy(theme),
        "i_ching": copy.deepcopy(theme),
    }


def _persisted_actual_gm_fixture(tmp_path: Path):
    service, snapshot, _sealed, card = _project_derived_gm_fixture()
    service.db = SimpleNamespace(settings=SimpleNamespace(root_dir=ROOT, data_dir=tmp_path, logs_dir=tmp_path / "logs", security_dir=tmp_path / "security"))
    service.integrity = create_test_integrity_service()
    response = _actual_gm_response(card["record_id"])
    raw_response = canonical_json(response)
    provider_result = {
        "provider_id": "lemonade",
        "purpose": "factory_gm_tactical_authoring",
        "model": "fixture-local-model",
        "request_sha256": "a" * 64,
        "response_sha256": "b" * 64,
        "completion_sha256": hashlib.sha256(raw_response.encode()).hexdigest(),
        "response_text": raw_response,
        "finish_reason": "stop",
        "value": response,
    }
    persisted = service._persist_gm_authoring(
        "project.actual.fixture",
        1,
        snapshot,
        prompt_text="fixture prompt",
        system_message="fixture system",
        provider_result=provider_result,
        response=response,
    )
    return service, snapshot, persisted


def test_c2b2_actual_gm_binding_reloads_from_server_owned_fixture_and_rejects_tamper(tmp_path: Path):
    service, snapshot, persisted = _persisted_actual_gm_fixture(tmp_path)
    loaded = service._load_gm_authoring("project.actual.fixture", project_revision=1, snapshot=snapshot)
    assert loaded is not None
    assert loaded["binding"]["verified"] is True
    assert loaded["binding"]["owner_ratified"] is False
    assert loaded["profile"]["authority_classification"] == "ACTUAL_GM_AUTHORING"

    artifact_path = Path(persisted["paths"]["artifact"])
    artifact_path.write_text(artifact_path.read_text(encoding="utf-8").replace("Bound theme", "Spoofed theme"), encoding="utf-8")
    with pytest.raises(FoundryError) as exc:
        service._load_gm_authoring("project.actual.fixture", project_revision=1, snapshot=snapshot)
    assert exc.value.code in {"GM_AUTHORING_ARTIFACT_STALE", "GM_AUTHORING_ARTIFACT_INVALID"}


def test_c2b2_actual_gm_binding_rejects_current_selected_record_content_change(tmp_path: Path):
    service, snapshot, _persisted = _persisted_actual_gm_fixture(tmp_path)
    changed = copy.deepcopy(snapshot)
    changed["selected_record_sections"]["selected_records"][0]["source_packet_ids"] = ["packet.tampered"]
    with pytest.raises(FoundryError) as exc:
        service._load_gm_authoring("project.actual.fixture", project_revision=1, snapshot=changed)
    assert exc.value.code == "GM_AUTHORING_ARTIFACT_STALE"


def test_c2b2_composite_contract_is_derived_from_signed_receipt_not_pointer(tmp_path: Path):
    service, snapshot, _persisted = _persisted_actual_gm_fixture(tmp_path)
    persisted = service._persist_gm_authoring(
        "project.actual.fixture",
        1,
        snapshot,
        prompt_text="fixture prompt",
        system_message="fixture system",
        provider_result={
            "provider_id": "lemonade",
            "purpose": "factory_gm_tactical_authoring",
            "model": "fixture-local-model",
            "request_sha256": "c" * 64,
            "response_sha256": "d" * 64,
            "completion_sha256": hashlib.sha256(canonical_json(_actual_gm_response("selected.record.one")).encode()).hexdigest(),
            "response_text": canonical_json(_actual_gm_response("selected.record.one")),
            "value": _actual_gm_response("selected.record.one"),
        },
        response=_actual_gm_response("selected.record.one"),
        authoring_contract="TianxiaFoundry.CandidateGMCompositeController.v1",
    )
    pointer_path = service._gm_root("project.actual.fixture") / "current.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["authoring_contract"] = "legacy-free-prose"
    pointer["pointer_sha256"] = sha256_json({key: value for key, value in pointer.items() if key != "pointer_sha256"})
    pointer_path.write_text(canonical_json(pointer), encoding="utf-8")
    with pytest.raises(FoundryError) as exc:
        service._load_gm_authoring("project.actual.fixture", project_revision=1, snapshot=snapshot)
    assert exc.value.code == "GM_AUTHORING_RECEIPT_POINTER_MISMATCH"
    assert persisted["binding"].get("authoring_contract") == "TianxiaFoundry.CandidateGMCompositeController.v1"


def test_c2b2_legacy_gm_receipt_cannot_enter_ratification(tmp_path: Path):
    service, snapshot, _persisted = _persisted_actual_gm_fixture(tmp_path)
    service.projects = SimpleNamespace(get_project=lambda _value: {"project": {"revision": 1}})
    service.sheets = SimpleNamespace(sheet=lambda _value: {"owner_character_sheet": snapshot})
    with pytest.raises(FoundryError) as exc:
        service.issue_gm_authoring_ratification_challenge("project.actual.fixture")
    assert exc.value.code == "GM_AUTHORING_RECEIPT_NOT_FOUND"


def test_c2b2_public_gm_authoring_uses_composite_prepare_and_validation(monkeypatch):
    service = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
    project_id = "project-composite-route"
    snapshot = {"selected_record_sections": {}}
    service.projects = SimpleNamespace(get_project=lambda value: {"project": {"revision": 4}})
    service.sheets = SimpleNamespace(sheet=lambda value: {"build_status": "CHARACTER_SHEET_READY", "owner_character_sheet": snapshot})
    service._selected_record_snapshot = lambda *_args: {"records": [], "record_ids": [], "selected_record_content_sha256": "e" * 64}
    service._persist_gm_authoring = lambda *_args, **kwargs: {"binding": {"provider_id": "local", "model": "fixture", "receipt_id": "gm-receipt.route", "artifact_sha256": "a" * 64, "profile_sha256": "b" * 64, "source_snapshot_sha256": "c" * 64, "selected_record_content_sha256": "e" * 64, "owner_ratified": False}, **kwargs}
    service.build = lambda _value: {"workspace_id": "workspace.route", "workspace_sha256": "f" * 64, "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"}
    calls = {"prepare": 0, "validate": 0, "persist": None}

    class _Composite:
        purpose = "factory_composite_controller"

        def __init__(self, **_kwargs):
            pass

        def prepare(self, value, *, theme_records=None):
            assert value == project_id
            assert theme_records == []
            calls["prepare"] += 1
            return {"prompt_text": "{}", "system_message": "system", "response_schema": {}, "response_schema_name": "schema", "max_request_bytes": 49152}

        @staticmethod
        def _validate_response(prepared, value):
            assert prepared["prompt_text"] == "{}"
            assert value["composite_controller"] == {}
            calls["validate"] += 1
            return {"composite_controller": {}}

    monkeypatch.setattr("factory_authoring.composite_controller.CompositeControllerAuthoring", _Composite)
    monkeypatch.setattr(
        "character_creation.candidate_gm_authoring.CandidateGMAuthoringService._server_response",
        staticmethod(lambda *_args, **_kwargs: ({"dao": {}, "i_ching": {}}, {"authoring_contract": "server"})),
    )

    class _Provider:
        @staticmethod
        def _settings():
            return {"provider_id": "local", "model": "fixture"}

        @staticmethod
        def complete_json(**kwargs):
            raw = canonical_json({"composite_controller": {}})
            return {"provider_id": "local", "model": "fixture", "purpose": "factory_composite_controller", "request_sha256": kwargs["expected_request_sha256"], "response_sha256": sha256_bytes(raw.encode()), "completion_sha256": sha256_bytes(raw.encode()), "response_text": raw, "value": {"composite_controller": {}}}

    result = service.author_gm_tactical(project_id, _Provider())
    assert calls == {"prepare": 1, "validate": 1, "persist": None}
    assert result["workspace_id"] == "workspace.route"


def test_c2b2_authoring_returns_provider_free_pending_workspace_after_persist(monkeypatch, tmp_path: Path):
    service = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
    project_id = "project-author-pending"
    factory = _configure_synthetic_gm_route(service, tmp_path, project_id)
    snapshot = {"selected_record_sections": {}}
    service.projects = SimpleNamespace(
        get_project=lambda value: {"project": {"revision": 4}} if value == project_id else None,
    )
    service.sheets = SimpleNamespace(
        sheet=lambda value: {"build_status": "CHARACTER_SHEET_READY", "owner_character_sheet": snapshot},
    )
    service._selected_record_snapshot = lambda *_args: {
        "records": [{"record_id": "selected.record.one", "display_name": "Selected Record"}],
        "record_ids": ["selected.record.one"],
        "selected_record_content_sha256": "c" * 64,
    }
    service._gm_provider_wire_hash = lambda *_args: "d" * 64
    service._persist_gm_authoring = lambda *_args, **_kwargs: {
        "binding": {
            "provider_id": "local",
            "model": "fixture-model",
            "receipt_id": "gm-receipt.fixture",
            "artifact_sha256": "a" * 64,
            "profile_sha256": "b" * 64,
            "source_snapshot_sha256": "c" * 64,
            "selected_record_content_sha256": "c" * 64,
            "owner_ratified": False,
            "authoring_contract": "TianxiaFoundry.CandidateGMCompositeController.v1",
        },
    }
    service.build = lambda value: {"workspace_id": "workspace.pending", "workspace_sha256": "e" * 64} if value == project_id else None
    # This public GM route requests a 1024-token response; match its provider cap.
    settings = {"provider_id": "local", "model": "fixture-model", "max_output_tokens": 1024}
    provider = SimpleNamespace(
        _settings=lambda: settings,
        complete_json=lambda **kwargs: _synthetic_composite_provider_result(kwargs, settings=settings),
    )

    result = service.author_gm_tactical(project_id, provider)

    assert result["workspace_id"] == "workspace.pending"
    assert result["workspace_sha256"] == "e" * 64
    assert result["owner_ratified"] is False


def test_c2b2_authoring_reports_persisted_receipt_when_workspace_rebuild_fails(monkeypatch, tmp_path: Path):
    service = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
    project_id = "project-author-rebuild-pending"
    factory = _configure_synthetic_gm_route(service, tmp_path, project_id)
    snapshot = {"selected_record_sections": {}}
    service.projects = SimpleNamespace(
        get_project=lambda value: {"project": {"revision": 4}} if value == project_id else None,
    )
    service.sheets = SimpleNamespace(
        sheet=lambda value: {"build_status": "CHARACTER_SHEET_READY", "owner_character_sheet": snapshot},
    )
    service._selected_record_snapshot = lambda *_args: {
        "records": [{"record_id": "selected.record.one", "display_name": "Selected Record"}],
        "record_ids": ["selected.record.one"],
        "selected_record_content_sha256": "c" * 64,
    }
    service._gm_provider_wire_hash = lambda *_args: "d" * 64
    binding = {
        "project_id": project_id,
        "project_revision": 4,
        "provider_id": "local",
        "model": "fixture-model",
        "receipt_id": "gm-receipt.rebuild-pending",
        "receipt_sha256": "1" * 64,
        "artifact_sha256": "a" * 64,
        "profile_sha256": "b" * 64,
        "source_snapshot_sha256": "c" * 64,
        "selected_record_content_sha256": "c" * 64,
        "owner_ratified": False,
        "authoring_contract": "TianxiaFoundry.CandidateGMCompositeController.v1",
    }
    service._persist_gm_authoring = lambda *_args, **_kwargs: {"binding": binding}
    service._load_gm_authoring = lambda *_args, **_kwargs: {"binding": binding}
    build_calls = {"count": 0}

    def build(value):
        assert value == project_id
        build_calls["count"] += 1
        if build_calls["count"] == 1:
            raise FoundryError("FACTORY_WORKSPACE_BUILD_BLOCKED", "fixture rebuild failure")
        return {
            "workspace_id": "workspace.recovered",
            "workspace_sha256": "e" * 64,
            "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        }

    service.build = build
    provider_calls = {"count": 0}

    settings = {"provider_id": "local", "model": "fixture-model", "max_output_tokens": 1024}

    def complete_json(**kwargs):
        provider_calls["count"] += 1
        return _synthetic_composite_provider_result(kwargs, settings=settings)

    provider = SimpleNamespace(
        _settings=lambda: settings,
        complete_json=complete_json,
    )

    pending = service.author_gm_tactical(project_id, provider)

    assert pending["status"] == "GM_AUTHORING_PERSISTED_REBUILD_PENDING"
    assert pending["receipt_id"] == binding["receipt_id"]
    assert pending["provider_calls"] == 1
    assert pending["provider_free_rebuild_available"] is True
    assert pending["workspace_rebuild_status"] == "FAILED"
    assert pending["owner_ratified"] is False
    assert "workspace_id" not in pending
    assert provider_calls["count"] == 1

    recovered = service.build(project_id)
    assert recovered["workspace_status"] == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
    assert build_calls["count"] == 2
    assert provider_calls["count"] == 1


@pytest.mark.parametrize("failure_phase", ["decision", "pointer", "build"])
def test_c2b2_ratification_recovers_after_post_consume_failure_without_reconsuming(fresh_db, monkeypatch, failure_phase: str):
    project_id = "project-ratification-recovery"
    receipt_id = "gm-receipt." + "a" * 64
    lock_hash = "l" * 64
    binding = {
        "project_id": project_id,
        "project_revision": 1,
        "receipt_id": receipt_id,
        "receipt_sha256": "b" * 64,
        "artifact_sha256": "c" * 64,
        "profile_sha256": "d" * 64,
        "request_sha256": "1" * 64,
        "response_sha256": "2" * 64,
        "source_snapshot_sha256": "e" * 64,
        "selected_record_content_sha256": "f" * 64,
        "owner_ratified": False,
        "owner_decision_id": None,
        "authoring_contract": "TianxiaFoundry.CandidateGMCompositeController.v1",
    }
    profile = {"schema_version": "fixture.profile.v1", "guidance": "exact"}
    principal = BoundPrincipalProvider(LocalPrincipal("owner.recovery", "Owner", "test", "test-owner"))
    integrity = create_test_integrity_service()
    service = FactoryAuthoringWorkspaceService(fresh_db, principal_provider=principal, integrity=integrity)
    service.projects = SimpleNamespace(get_project=lambda _value: {"project": {"revision": 1}})
    service.sheets = SimpleNamespace(sheet=lambda _value: {"owner_character_sheet": {}})
    service._gm_project_lock_hash = lambda _value: lock_hash

    root = service._gm_root(project_id)
    pointer_unsigned = {
        "schema_version": "TianxiaFoundry.GMAuthoringPointer.v1",
        "project_id": project_id,
        "project_revision": 1,
        "receipt_id": receipt_id,
        "receipt_sha256": binding["receipt_sha256"],
        "artifact_sha256": binding["artifact_sha256"],
        "profile_sha256": binding["profile_sha256"],
        "request_sha256": "1" * 64,
        "response_sha256": "2" * 64,
        "source_snapshot_sha256": binding["source_snapshot_sha256"],
        "selected_record_content_sha256": binding["selected_record_content_sha256"],
        "owner_decision_id": None,
    }
    service._gm_write_pointer(root / "current.json", {**pointer_unsigned, "pointer_sha256": sha256_json(pointer_unsigned)})

    def loaded(_project_id, **_kwargs):
        pointer = service._gm_read_json(root / "current.json")
        current = copy.deepcopy(binding)
        current["owner_decision_id"] = pointer.get("owner_decision_id")
        current["owner_ratified"] = pointer.get("owner_decision_id") is not None
        return {"profile": profile, "binding": current}

    service._load_gm_authoring = loaded
    workspace = fresh_db.settings.data_dir / "factory_workspaces" / project_id / "workspace-1"
    workspace.mkdir(parents=True)
    manifest = {
        "project_revision": 1,
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "gm_authoring_profile": {"classification": "ACTUAL_GM_AUTHORING"},
        "gm_artifact_binding": {
            field: binding.get(field)
            for field in (
                "receipt_id", "receipt_sha256", "artifact_sha256", "profile_sha256",
                "source_snapshot_sha256", "selected_record_content_sha256", "owner_decision_id", "owner_ratified",
            )
        },
    }
    manifest_path = workspace / "Workspace_Manifest.json"
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
    workspace_pointer_unsigned = {
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "workspace_id": "workspace-1",
        "workspace_path": str(workspace),
        "workspace_sha256": "9" * 64,
        "manifest_sha256": sha256_file(manifest_path),
        "gm_authoring_status": "ACTUAL_GM_AUTHORING",
        "gm_authorship_status": "ACTUAL",
        "gm_authoring_actual": True,
        "gm_receipt_id": receipt_id,
        "gm_receipt_sha256": binding["receipt_sha256"],
        "gm_artifact_sha256": binding["artifact_sha256"],
        "gm_profile_sha256": binding["profile_sha256"],
        "gm_request_sha256": binding["request_sha256"],
        "gm_response_sha256": binding["response_sha256"],
        "gm_source_snapshot_sha256": binding["source_snapshot_sha256"],
        "gm_selected_record_content_sha256": binding["selected_record_content_sha256"],
        "gm_owner_decision_id": None,
    }
    service._pointer(project_id).parent.mkdir(parents=True, exist_ok=True)
    service._pointer(project_id).write_text(canonical_json(workspace_pointer_unsigned), encoding="utf-8")
    builds: list[str] = []
    build_failure = {"value": failure_phase == "build"}

    def build(value):
        builds.append(value)
        if build_failure["value"]:
            build_failure["value"] = False
            raise FoundryError("GM_AUTHORING_TEST_INJECTED", "injected workspace rebuild failure")
        return {"workspace_id": "workspace.recovered", "workspace_sha256": "9" * 64}

    service.build = build
    approval = ApprovalChallengeService(fresh_db, principal_provider=principal, integrity=integrity)
    issued = approval.issue(
        operation="gm_authoring_owner_ratify",
        subject_type="gm_authoring_receipt",
        subject_id=receipt_id,
        exact_bytes=service._gm_json_bytes(profile),
        binding=service._gm_approval_binding(binding),
        project_lock_hash=lock_hash,
    )["challenge"]
    original_write = service._gm_write_immutable_json
    failed = {"value": True}
    original_pointer = service._gm_write_pointer

    def fail_decision(root_path, name, value):
        if failure_phase == "decision" and root_path.name == "decisions" and failed["value"]:
            failed["value"] = False
            raise FoundryError("GM_AUTHORING_TEST_INJECTED", "injected decision persistence failure")
        return original_write(root_path, name, value)

    def fail_pointer(path, value):
        if failure_phase == "pointer" and failed["value"]:
            failed["value"] = False
            raise FoundryError("GM_AUTHORING_TEST_INJECTED", "injected pointer persistence failure")
        return original_pointer(path, value)

    monkeypatch.setattr(service, "_gm_write_immutable_json", fail_decision)
    monkeypatch.setattr(service, "_gm_write_pointer", fail_pointer)
    with pytest.raises(FoundryError) as first:
        service.ratify_gm_authoring(project_id, receipt_id, issued["challenge_id"], issued["nonce"])
    assert first.value.code == "GM_AUTHORING_TEST_INJECTED"
    with fresh_db.connection() as conn:
        assert conn.execute("SELECT status FROM exact_approval_challenges WHERE challenge_id=?", (issued["challenge_id"],)).fetchone()[0] == "consumed"
        assert conn.execute("SELECT COUNT(*) FROM exact_approval_evidence WHERE challenge_id=?", (issued["challenge_id"],)).fetchone()[0] == 1

    if failure_phase == "decision":
        def tampered_loaded(_project_id, **_kwargs):
            current = loaded(_project_id, **_kwargs)
            current["binding"]["artifact_sha256"] = "0" * 64
            return current

        service._load_gm_authoring = tampered_loaded
        with pytest.raises(FoundryError) as mismatch:
            service.ratify_gm_authoring(project_id, receipt_id, issued["challenge_id"], issued["nonce"])
        assert mismatch.value.code == "APPROVAL_EVIDENCE_BINDING_MISMATCH"
        service._load_gm_authoring = loaded

    monkeypatch.setattr(service, "_gm_write_immutable_json", original_write)
    monkeypatch.setattr(service, "_gm_write_pointer", original_pointer)
    recovered = service.ratify_gm_authoring(project_id, receipt_id, issued["challenge_id"], issued["nonce"])

    assert recovered["status"] == "GM_AUTHORING_OWNER_RATIFIED"
    assert recovered["workspace_id"] == "workspace.recovered"
    assert builds == [project_id] * (2 if failure_phase == "build" else 1)
    with fresh_db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM exact_approval_evidence WHERE challenge_id=?", (issued["challenge_id"],)).fetchone()[0] == 1


def test_c2b2_sheet_status_reads_provisional_state_from_manifest_when_pointer_field_is_missing(tmp_path: Path):
    service = CharacterSheetService.__new__(CharacterSheetService)
    service.db = SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path))
    project_id = "project-provisional-status"
    workspace = tmp_path / "factory_workspaces" / project_id / "workspace-1"
    authorship = {
        "schema_version": "TianxiaFoundry.GMAuthorshipBinding.v1",
        "status": "PROVISIONAL",
        "origin": "project_selected_record_template",
        "provider_id": None,
        "artifact_bound": False,
        "artifact_sha256": None,
        "owner_ratified": False,
        "source_record_ids": ["selected.record.one"],
    }
    manifest = {
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "gm_authoring_profile": {
            "classification": "PROVISIONAL_GM_GUIDANCE",
            "authorship": authorship,
        },
    }
    workspace.mkdir(parents=True)
    manifest_path = workspace / "Workspace_Manifest.json"
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
    pointer = {
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "workspace_id": "workspace-1",
        "workspace_path": str(workspace),
        "manifest_sha256": sha256_file(manifest_path),
    }
    pointer_path = tmp_path / "factory_workspaces" / project_id / "current.json"
    pointer_path.write_text(canonical_json(pointer), encoding="utf-8")

    status = service._factory_workspace_status(project_id)

    assert status["gm_authoring"] == "PROVISIONAL_GM_GUIDANCE_ONLY"
    assert status["gm_authorship_status"] == "PROVISIONAL"
    assert status["gm_authoring_actual"] is False
    assert status["eligible_for_later_command5_checkpoint"] is False


def test_c2b2_status_surfaces_verified_receipt_for_provider_free_workspace_rebuild(tmp_path: Path, monkeypatch):
    factory_service, snapshot, persisted = _persisted_actual_gm_fixture(tmp_path)
    project_id = "project.actual.fixture"
    factory_service.projects = SimpleNamespace(get_project=lambda _value: {"project": {"revision": 1}})
    factory_service.sheets = SimpleNamespace(sheet=lambda _value: {"owner_character_sheet": snapshot})

    workspace_status = factory_service.status(project_id)

    assert workspace_status["workspace_status"] == "REBUILD_PENDING"
    assert workspace_status["available"] is False
    assert workspace_status["provider_free_rebuild_available"] is True
    assert workspace_status["gm_authoring_status"] == "ACTUAL_GM_AUTHORING"
    assert workspace_status["gm_receipt_id"] == persisted["binding"]["receipt_id"]

    workspace = tmp_path / "factory_workspaces" / project_id / "workspace-1"
    workspace.mkdir(parents=True)
    manifest_path = workspace / "Workspace_Manifest.json"
    manifest_path.write_text(canonical_json({
        "project_revision": 1,
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "gm_authoring_profile": {
            "classification": "PROVISIONAL_GM_GUIDANCE",
            "authorship": {"status": "PROVISIONAL", "owner_ratified": False},
        },
    }), encoding="utf-8")
    pointer_path = tmp_path / "factory_workspaces" / project_id / "current.json"
    pointer_path.write_text(canonical_json({
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "workspace_id": "workspace-1",
        "workspace_path": str(workspace),
        "manifest_sha256": sha256_file(manifest_path),
    }), encoding="utf-8")

    sheet_service = CharacterSheetService.__new__(CharacterSheetService)
    sheet_service.db = factory_service.db
    sheet_service.projects = factory_service.projects
    monkeypatch.setattr("security.integrity.IntegrityService.for_database", lambda _db: factory_service.integrity)
    sheet_status = sheet_service._factory_workspace_status(project_id)

    assert sheet_status["status"] == "REBUILD_PENDING"
    assert sheet_status["workspace_id"] is None
    assert sheet_status["provider_free_rebuild_available"] is True
    assert sheet_status["gm_authoring"] == "ACTUAL_GM_AUTHORING"
    assert sheet_status["gm_authoring_actual"] is True
    assert sheet_status["gm_receipt_id"] == persisted["binding"]["receipt_id"]
    assert sheet_status["eligible_for_later_command5_checkpoint"] is False


def _unready_gm_ratification_fixture(fresh_db, workspace_state: str):
    project_id = "project-ratification-readiness"
    receipt_id = "gm-receipt." + "a" * 64
    lock_hash = "l" * 64
    binding = {
        "project_id": project_id,
        "project_revision": 1,
        "receipt_id": receipt_id,
        "receipt_sha256": "b" * 64,
        "artifact_sha256": "c" * 64,
        "profile_sha256": "d" * 64,
        "request_sha256": "e" * 64,
        "response_sha256": "f" * 64,
        "source_snapshot_sha256": "1" * 64,
        "selected_record_content_sha256": "2" * 64,
        "owner_ratified": False,
        "owner_decision_id": None,
        "authoring_contract": "TianxiaFoundry.CandidateGMCompositeController.v1",
    }
    profile = {"profile_id": "profile.ratification-readiness"}
    principal = BoundPrincipalProvider(LocalPrincipal("owner.readiness", "Owner", "test", "readiness"))
    integrity = create_test_integrity_service()
    service = FactoryAuthoringWorkspaceService(fresh_db, principal_provider=principal, integrity=integrity)
    service.projects = SimpleNamespace(get_project=lambda _value: {"project": {"revision": 1}})
    service.sheets = SimpleNamespace(sheet=lambda _value: {"owner_character_sheet": {}})
    service._load_gm_authoring = lambda *_args, **_kwargs: {"profile": profile, "binding": binding}
    service._gm_project_lock_hash = lambda _value: lock_hash

    root = service._gm_root(project_id)
    pointer_unsigned = {
        "schema_version": "TianxiaFoundry.GMAuthoringPointer.v1",
        "project_id": project_id,
        "project_revision": 1,
        "receipt_id": receipt_id,
        "receipt_sha256": binding["receipt_sha256"],
        "artifact_sha256": binding["artifact_sha256"],
        "profile_sha256": binding["profile_sha256"],
        "request_sha256": binding["request_sha256"],
        "response_sha256": binding["response_sha256"],
        "source_snapshot_sha256": binding["source_snapshot_sha256"],
        "selected_record_content_sha256": binding["selected_record_content_sha256"],
        "owner_decision_id": None,
    }
    service._gm_write_pointer(root / "current.json", {**pointer_unsigned, "pointer_sha256": sha256_json(pointer_unsigned)})
    if workspace_state == "stale":
        workspace_pointer = service._pointer(project_id)
        workspace_pointer.parent.mkdir(parents=True, exist_ok=True)
        workspace_pointer.write_text(canonical_json({
            "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
            "workspace_id": "workspace.stale",
            "workspace_path": str(workspace_pointer.parent / "missing-workspace"),
            "manifest_sha256": "0" * 64,
        }), encoding="utf-8")
    return service, binding, profile, principal, integrity, lock_hash


@pytest.mark.parametrize("workspace_state", ["missing", "stale"])
def test_c2b2_ratification_challenge_issue_fails_closed_without_ready_workspace(fresh_db, workspace_state: str):
    service, _binding, _profile, _principal, _integrity, _lock_hash = _unready_gm_ratification_fixture(fresh_db, workspace_state)

    with pytest.raises(FoundryError) as exc:
        service.issue_gm_authoring_ratification_challenge("project-ratification-readiness")

    assert exc.value.code == "GM_AUTHORING_WORKSPACE_NOT_READY"
    with fresh_db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM exact_approval_challenges").fetchone()[0] == 0


@pytest.mark.parametrize("workspace_state", ["missing", "stale"])
def test_c2b2_ratification_first_consume_fails_closed_without_ready_workspace(fresh_db, workspace_state: str):
    service, binding, profile, principal, integrity, lock_hash = _unready_gm_ratification_fixture(fresh_db, workspace_state)
    approval = ApprovalChallengeService(fresh_db, principal_provider=principal, integrity=integrity)
    issued = approval.issue(
        operation="gm_authoring_owner_ratify",
        subject_type="gm_authoring_receipt",
        subject_id=binding["receipt_id"],
        exact_bytes=service._gm_json_bytes(profile),
        binding=service._gm_approval_binding(binding),
        project_lock_hash=lock_hash,
    )["challenge"]

    def build_should_not_run(_project_id):
        raise FoundryError("GM_AUTHORING_BUILD_SHOULD_NOT_RUN", "The provider-free build must not run before workspace readiness.")

    service.build = build_should_not_run
    with pytest.raises(FoundryError) as exc:
        service.ratify_gm_authoring(
            "project-ratification-readiness",
            binding["receipt_id"],
            issued["challenge_id"],
            issued["nonce"],
        )

    assert exc.value.code == "GM_AUTHORING_WORKSPACE_NOT_READY"
    with fresh_db.connection() as conn:
        challenge = conn.execute(
            "SELECT status FROM exact_approval_challenges WHERE challenge_id=?",
            (issued["challenge_id"],),
        ).fetchone()
        assert challenge["status"] == "issued"
        assert conn.execute(
            "SELECT COUNT(*) FROM exact_approval_evidence WHERE challenge_id=?",
            (issued["challenge_id"],),
        ).fetchone()[0] == 0
    decisions = service._gm_root("project-ratification-readiness") / "decisions"
    assert not decisions.exists() or not any(decisions.iterdir())


def test_c2b2_sealed_profiles_and_scope(tmp_path: Path):
    service = _service(tmp_path)
    profile, profile_sha = service._authoring_profile()
    workspace, workspace_sha = service._workspace_profile()
    assert profile_sha == "8178fdb6e089e11c833389d9beaeeceb40c5bb22e173cb8386895929e93ef8a5"
    assert workspace_sha == "94ca0548f9a944c83e76c5d3e03fd3d4eb1896f4f6b012be98158ab453e8bf61"
    assert profile["authority_classification"] == "OWNER_RATIFIED_GM_AUTHORING"
    assert profile["scope"]["mechanical_authority"] is False
    assert profile["scope"]["execution_authority"] is False
    assert workspace["legacy_boundaries"]["pinned_command4_executable_status"] == "NOT_RUN"
    assert workspace["legacy_boundaries"]["legacy_command5_eligible"] is False


def test_c2b2_training_source_coverage_and_no_invented_lore():
    data = _roots()[0]
    service = _service(data)
    profile, _ = service._authoring_profile(); workspace, _ = service._workspace_profile()
    service._validate_profile(profile, workspace, _sheet_snapshot(data))
    covered = [rid for row in profile["training_sources"] for rid in row["record_ids"]]
    assert set(covered) == set(workspace["required_training_source_coverage"])
    assert len(covered) == len(set(covered))
    assert all(row["factory_source_type"] == "other" for row in profile["training_sources"])
    assert "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE" in next(row["record_ids"] for row in profile["training_sources"] if row["source_id"] == "gm.training.background.scoundrel")
    assert all(key not in row for row in profile["training_sources"] for key in ("teacher", "sect", "manual", "location", "historical_event"))


def test_c2b2_dao_and_i_ching_are_owner_authoring_without_bonuses():
    profile, _ = _service(_roots()[0])._authoring_profile()
    dao = profile["dao_i_ching"]["dao"]; iching = profile["dao_i_ching"]["i_ching"]
    assert dao["authoring_id"] == "gm.dao.refinement_through_controlled_flame"
    assert iching["authoring_id"] == "gm.iching.hexagram_30_li"
    assert dao["mechanical_effects"] == [] and iching["mechanical_effects"] == []
    assert all(key not in dao and key not in iching for key in ("bonus", "penalty", "reroll", "resource_change"))


def test_c2b2_ai_profile_is_descriptive_and_not_registered_controller():
    profile, _ = _service(_roots()[0])._authoring_profile(); ai = profile["ai_behavior"]
    assert ai["not_executable_controller_policy"] is True
    assert ai["classification"] == "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY"
    assert "decision_weights" not in ai and "target_scoring" not in ai and "legal_candidate" not in ai
    source = (ROOT / "factory_authoring/service.py").read_text(encoding="utf-8")
    assert "from combat" not in source and "controller_policy" not in source.split("_reject_executable_claims", 1)[0]


def test_c2b2_two_builds_and_two_clean_roots_are_byte_identical():
    results = []
    for data in _roots():
        service = _service(data)
        first = service.build(PROJECT_ID); second = service.build(PROJECT_ID)
        assert first["workspace_id"] == second["workspace_id"] == EXPECTED_WORKSPACE_ID
        assert first["workspace_sha256"] == second["workspace_sha256"] == EXPECTED_WORKSPACE_SHA256
        assert first["workspace_status"] == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
        assert first["legacy_boundaries"]["pinned_command4_executable_status"] == "NOT_RUN"
        assert first["legacy_boundaries"]["legacy_command5_eligible"] is False
        assert first["readiness"]["gm_screen"] == "NOT_ATTEMPTED"
        assert first["readiness"]["combat"] == "NOT_ATTEMPTED"
        results.append((first["workspace_id"], first["workspace_sha256"], first["artifact_hashes"]))
    assert results[0] == results[1]


def test_c2b2_workspace_required_files_and_cross_file_statuses():
    result = _service(_roots()[0]).build(PROJECT_ID)
    root = Path(result["workspace_path"])
    profile, _ = _service(_roots()[0])._workspace_profile()
    assert set(result["artifact_hashes"]) == set(profile["required_artifacts"])
    assert {
        "Command_4/Action_Authoring_Candidates.json",
        "Command_4/Complete_Action_Surface.json",
    }.issubset(result["artifact_hashes"])
    manifest = json.loads((root / "Workspace_Manifest.json").read_text())
    assert manifest["workspace_status"] == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
    assert manifest["legacy_boundaries"]["pinned_command4_executable_status"] == "NOT_RUN"
    command4 = json.loads((root / "Validation/Command_4.validation.json").read_text())
    assert command4["valid"] is True
    assert command4["legacy_pinned_command4_pass"] is False
    assert command4["executable_combat_not_attempted"] is True
    c2b2 = json.loads((root / "Validation/C2B2_Workspace.validation.json").read_text())
    assert c2b2["command5_invoked"] is False and c2b2["command6_invoked"] is False


def test_c2b2_documents_preserve_acquired_manual_and_canonical_training_source():
    service = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
    service.db = SimpleNamespace(settings=SimpleNamespace(root_dir=ROOT))
    manual = {
        "record_id": "manual.constructed",
        "display_name": "Constructed Manual",
        "record_hash": "manual-hash",
        "source_packet_ids": ["packet.manual"],
        "source": {"path": "LocalSources/manual.txt", "anchor": "manual"},
        "acquisition_cl": 1,
        "capabilities": {},
        "display_only_not_execution_authority": True,
        "section": "manuals",
    }
    canonical_source = {
        "source_id": "manual.constructed",
        "allocation_id": "training_source_access:event.manual",
        "name": "Constructed Manual",
        "type": "other",
        "gained_at_cl": 1,
        "contents": {
            "recorded_arts": ["art.constructed"],
            "methods": [],
            "warnings": [],
            "recipes": [],
            "theory": [],
            "false_routes": [],
        },
        "restrictions": [],
        "risks": [],
        "mechanics_granted": [],
        "source_packet_ids": ["packet.manual"],
        "record_hash": "manual-hash",
    }
    snapshot = {
        "identity": {"display_name": "Test Character", "cultivation_level": 1, "realm": "Mortal"},
        "selected_record_sections": {"manuals": [manual]},
        "capability_status": {"records": [], "pending_execution_surfaces": []},
        "advancement_history": {"owner_choice_locks": []},
        "explicit_none_systems": {"method": {"state": "none"}, "foundation": {"state": "none"}},
        "recorded_arts": [{"record_id": "art.constructed"}],
        "training_sources": [canonical_source],
        "background_and_origin": {},
        "path_and_subpath": {},
        "spheres_and_talents": {},
        "method": {},
        "foundation": {},
    }
    profile = {
        "profile_id": "profile.test",
        "authority_classification": "OWNER_RATIFIED_GM_AUTHORING",
        "training_sources": [{
            "source_id": "gm.guidance.manual",
            "name": "Manual guidance",
            "factory_source_type": "other",
            "classification": "GM_GUIDANCE_ONLY",
            "record_ids": ["manual.constructed"],
        }],
        "dao_i_ching": {
            "dao": {"authoring_id": "dao.test"},
            "i_ching": {"authoring_id": "iching.test"},
        },
        "ai_behavior": {"profile_id": "ai.test"},
    }
    documents = service._documents(
        project={"project_id": "project.test", "revision": 1},
        sheet_response={
            "owner_character_sheet": snapshot,
            "provenance": {"advancement_projection": {"projection": {}}},
            "sheet_artifact": {"sha256": "sheet-hash"},
        },
        profile=profile,
        profile_sha="profile-hash",
        workspace_profile={
            "profile_id": "workspace-profile.test",
            "later_combat_execution_fields": [],
            "required_training_source_coverage": ["manual.constructed"],
            "semantics": {"gm_screen": "NOT_ATTEMPTED", "combat": "NOT_ATTEMPTED"},
            "legacy_boundaries": {"pinned_command4_executable_status": "NOT_RUN"},
        },
        workspace_profile_sha="workspace-profile-hash",
        projection_artifacts={
            "Character_Master_Ledger.json": {
                "advancement": {"event_count": 0, "event_head_hash": "0" * 64},
                "character": {}, "core_stats": {}, "resources": {}, "typed_none": {},
            },
            "Rules_Selection_Packets.json": {"packets": []},
            "Projection_Provenance_Map.json": {},
        },
    )

    roster = documents["Command_3/Recorded_Art_Roster_Plan.json"]
    assert roster["recorded_arts"] == snapshot["recorded_arts"]
    training_document = documents["Command_4/Training_Sources.json"]
    assert training_document["canonical_training_sources"] == snapshot["training_sources"]
    guidance = training_document["guidance_training_sources"][0]
    assert guidance["source_id"] == "gm.guidance.manual"
    assert guidance["classification"] == "GM_GUIDANCE_ONLY"
    assert guidance["gained_at_cl"] == 1
    assert guidance["contents"]["record_ids"] == ["manual.constructed"]
    assert guidance["contents"]["record_bindings"] == [{
        "record_id": "manual.constructed",
        "display_name": "Constructed Manual",
        "record_hash": "manual-hash",
        "source_packet_ids": ["packet.manual"],
        "source": manual["source"],
        "capabilities": {},
        "display_only_not_execution_authority": True,
    }]
    assert training_document["training_sources"] == [*snapshot["training_sources"], guidance]
    assert training_document["source_provenance"]["canonical_training_sources"]["classification"] == "CANONICAL_ADVANCEMENT_PROJECTION"
    assert training_document["source_provenance"]["guidance_training_sources"]["classification"] == "GM_GUIDANCE_ONLY"


def test_c2b2_read_only_view_verifies_workspace_hash_and_projects_only_guidance(tmp_path: Path):
    project_id = "project-gm-view"
    service = _service(tmp_path)
    workspace = service._root(project_id) / "workspace-1"
    documents = {
        "Workspace_Manifest.json": {"workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"},
        "Command_4/Training_Sources.json": {"training_sources": [{"source_id": "source.1", "display_name": "Source One"}]},
        "Command_4/Composite_Playbooks.json": {"playbooks": [{"playbook_id": "playbook.1", "not_a_combat_macro": True}]},
        "Command_4/Dao_I_Ching_GM_Authoring.json": {"classification": "OWNER_RATIFIED_GM_AUTHORING", "dao": {"display_name": "Dao", "mechanical_effects": []}, "i_ching": {"display_name": "I Ching", "mechanical_effects": []}},
        "Command_4/Recorded_Art_Audit.json": {"result": {"state": "none", "source_backed": True}},
        "Command_4/Forged_Technique_Audit.json": {"result": {"state": "none", "source_backed": True}},
    }
    for relative_path, value in documents.items():
        path = workspace / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(value), encoding="utf-8")
    file_hashes = {
        path.relative_to(workspace).as_posix(): sha256_file(path)
        for path in sorted(workspace.rglob("*")) if path.is_file()
    }
    pointer = {
        "project_id": project_id,
        "workspace_id": "workspace-1",
        "workspace_status": "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE",
        "workspace_path": str(workspace),
        "workspace_sha256": sha256_json(file_hashes),
        "manifest_sha256": file_hashes["Workspace_Manifest.json"],
        "command5_invoked": False,
        "command6_invoked": False,
        "gm_export_available": False,
    }
    service._pointer(project_id).parent.mkdir(parents=True, exist_ok=True)
    service._pointer(project_id).write_text(canonical_json(pointer), encoding="utf-8")

    view = service.view(project_id)

    assert view["available"] is True
    assert "workspace_path" not in view and "artifact_hashes" not in view
    assert view["authority"]["mechanical_authority"] is False
    assert "composite_playbooks" not in view
    assert view["dao_i_ching"]["dao"]["mechanical_effects"] == []
    assert view["advanced_systems"]["forged_techniques"]["state"] == "none"
    assert view["advanced_systems"]["immortal_arts"]["state"] == "not_projected"

    (workspace / "Command_4/Composite_Playbooks.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FoundryError) as exc_info:
        service.view(project_id)
    assert exc_info.value.code == "FACTORY_WORKSPACE_VIEW_STALE"


def test_c2b2_read_only_gm_authoring_view_is_bounded_and_non_executable():
    service = _service(_roots()[0])
    service.build(PROJECT_ID)

    view = service.view(PROJECT_ID)

    assert view["schema_version"] == "TianxiaFoundry.GMAuthoringSheetView.v1"
    assert view["available"] is True
    assert "workspace_path" not in view and "artifact_hashes" not in view
    assert view["authority"] == {
        "classification": "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
        "capability_status": "GM_GUIDANCE_ONLY",
        "mechanical_authority": False,
        "execution_authority": False,
        "not_a_combat_macro": True,
    }
    assert "composite_playbooks" not in view
    assert view["dao_i_ching"]["dao"]["mechanical_effects"] == []
    assert view["dao_i_ching"]["i_ching"]["mechanical_effects"] == []
    assert view["advanced_systems"]["forged_techniques"]["state"] == "none"
    assert view["advanced_systems"]["immortal_arts"]["state"] == "not_projected"


def test_c2b2_negative_missing_training_and_unproven_statement():
    data = _roots()[0]; service = _service(data); snapshot = _sheet_snapshot(data)
    profile, _ = service._authoring_profile(); workspace, _ = service._workspace_profile()
    missing = copy.deepcopy(profile); missing["training_sources"] = missing["training_sources"][:-1]
    with pytest.raises(FoundryError): service._validate_profile(missing, workspace, snapshot)
    unproven = copy.deepcopy(profile); unproven["training_sources"][0]["summary"] = ""
    with pytest.raises(FoundryError): service._validate_profile(unproven, workspace, snapshot)


def test_c2b2_negative_dao_ai_and_executable_claims():
    data = _roots()[0]; service = _service(data); snapshot = _sheet_snapshot(data)
    profile, _ = service._authoring_profile(); workspace, _ = service._workspace_profile()
    no_dao = copy.deepcopy(profile); no_dao["dao_i_ching"].pop("dao")
    with pytest.raises(FoundryError): service._validate_profile(no_dao, workspace, snapshot)
    no_ai = copy.deepcopy(profile); no_ai.pop("ai_behavior")
    with pytest.raises(FoundryError): service._validate_profile(no_ai, workspace, snapshot)
    executable = copy.deepcopy(profile); executable["ai_behavior"]["decision_weights"] = {"attack": 100}
    with pytest.raises(FoundryError): service._validate_profile(executable, workspace, snapshot)


def test_c2b2_gm_export_remains_blocked_and_sheet_identity_is_preserved():
    data = _roots()[0]; db = Database(Settings.from_env(ROOT, data))
    _service(data).build(PROJECT_ID)
    sheet = CharacterSheetService(db).sheet(PROJECT_ID)
    assert sheet["build_status"] == "CHARACTER_SHEET_READY"
    assert sheet["sheet_artifact"]["sha256"] == EXPECTED_SHEET_SHA256
    assert sheet["readiness"] == {"advancement":"ADVANCEMENT_READY","character_sheet":"CHARACTER_SHEET_READY","gm_screen":"NOT_ATTEMPTED","combat":"NOT_ATTEMPTED"}
    assert sheet["factory_workspace"]["status"] == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
    status = GMCharacterExportService(db).status(PROJECT_ID)
    assert status["available"] is False
    if sheet["factory_workspace"].get("command5") == "GM_MODEL_CANDIDATE_READY":
        assert any("consumer verification has not been attempted" in blocker.lower() for blocker in status["blockers"])
    else:
        assert any("Command 5 and Command 6 have not been run" in blocker for blocker in status["blockers"])


def test_c2b2_advancement_artifacts_and_canonical_sheet_remain_byte_identical():
    root = _artifact_dir()
    assert {name: sha256_file(root / name) for name in EXPECTED_ADVANCEMENT_HASHES} == EXPECTED_ADVANCEMENT_HASHES
    assert sha256_file(Path('/mnt/data/c2b1_work/Tianxia_Owner_Character_Sheet_v1.json')) == EXPECTED_SHEET_SHA256


def test_c2b2_ui_is_readable_and_exposes_no_false_export_readiness():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "Prepare Command 1–4 Workspace" in html
    assert "GM tactical authoring is complete" in js
    assert "GM Screen not verified" in js
    assert "Combat not typed" in js
    assert "Command 5 and Command 6 have not been run. GM export remains unavailable." in js
    assert "JSON.stringify(value, null, 2)" in js  # advanced fallback remains available, not normal presentation


def test_c2b2_cpk1_remains_isolated_candidate_and_unregistered():
    service_source = (ROOT / "factory_authoring/service.py").read_text(encoding="utf-8")
    api_source = (ROOT / "app/api.py").read_text(encoding="utf-8")
    assert "content_pack_validator" not in service_source
    assert "candidate_schemas" not in service_source
    assert "SchemaRegistry" in api_source  # existing production registry remains separate
    for path in (ROOT / "schemas/content_pack_candidate").glob("*.json"):
        assert "CANDIDATE_NON_AUTHORITATIVE" in path.read_text(encoding="utf-8")


def test_c2b2_cpk1_retained_verification_report_marks_candidate_non_authoritative():
    report = ROOT / "docs/content_pack_validator/CPK1_INPUT_VERIFICATION_AND_PRESERVATION.json"
    if not report.is_file():
        pytest.skip("The retained CPK1 verification report is not included in this checkout")
    isolation = json.loads(report.read_text(encoding="utf-8"))
    assert isolation.get("candidate_status") == "CANDIDATE_NON_AUTHORITATIVE" or "CANDIDATE_NON_AUTHORITATIVE" in json.dumps(isolation)


def test_c2b2_no_command5_or_command6_invocation_in_new_service():
    source = (ROOT / "factory_authoring/service.py").read_text(encoding="utf-8")
    assert ".command5(" not in source
    assert ".command6(" not in source
    assert "GMCharacterExportService" not in source
