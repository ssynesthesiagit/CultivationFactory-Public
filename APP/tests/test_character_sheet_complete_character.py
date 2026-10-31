from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import character_sheet.service as sheet_module
from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_file
from character_sheet.service import CharacterSheetService
from portable_character.service import PortableCharacterPackageService


PROJECT_ID = "project.complete-character"
PROJECTION_ID = "projection.complete-character"


def test_resource_surface_preserves_wrapped_pools_without_private_fields() -> None:
    document = {"equipment_resources_states": {"resources": {"qi_maximum": {
        "name": "Resonance", "maximum": 36, "build_state_current": 2,
        "current_state_note": "Saved creation values.",
        "definitions": [
            {"resource_id": "tianxia.resource.resonance", "name": "Resonance", "current": 2, "max": 36},
            {"resource_id": "tianxia.resource.stamina", "name": "Stamina", "current": 0, "max": 36,
             "private_receipt": {"secret": "must-not-leak"}},
        ],
        "private_receipt": {"secret": "must-not-leak"},
    }}}}
    projected = CharacterSheetService._complete_character_project_member(
        "resources_states_suppression", sheet_module._COMPLETE_CHARACTER_MODEL_V1, document,
    )
    primary = projected["equipment_resources_states"]["resources"]["qi_maximum"]
    assert [(row["name"], row["current"], row["max"]) for row in primary["definitions"]] == [
        ("Resonance", 2, 36), ("Stamina", 0, 36),
    ]
    assert primary["current_state_note"] == "Saved creation values."
    assert "private_receipt" not in json.dumps(projected)
    assert "must-not-leak" not in json.dumps(projected)


def _archive_members() -> set[str]:
    return {
        member
        for members in sheet_module._COMPLETE_CHARACTER_SURFACE_MEMBERS.values()
        for member in members
    }


def _surface_document(member: str, *, display_name: str) -> dict:
    if member == sheet_module._COMPLETE_CHARACTER_VIEW:
        return {
            "schema": "Tianxia_GM_Character_View_Model_v2",
            "schema_version": "2.0.0",
            "identity": {
                "display_name": display_name,
                "metadata": {"request_sha256": "nested-receipt-must-not-leak"},
            },
            "core_stats": {"armor_class": {"value": 13}},
            "metadata": {"request_sha256": "receipt-must-not-leak"},
        }
    if member == sheet_module._COMPLETE_CHARACTER_MODEL_V2:
        return {
            "schema": "Tianxia_GM_Character_Model_v2",
            "schema_version": "2.0.0",
            "identity": {"display_name": display_name},
            "core_stats": {"armor_class": {"value": 13}},
        }
    if member == sheet_module._COMPLETE_CHARACTER_MODEL_V1:
        return {
            "schema": "Tianxia_GM_Character_Model_v1",
            "schema_version": "1.0.0",
            "identity": {"display_name": display_name},
            "stats": {"armor_class": 13},
            "paths_subpaths": {"path": "Fire Qi", "subpath": "Clean Fire"},
            "equipment_resources_states": {"resources": [{"resource_id": "stamina", "current": 1}]},
            "spirit_companions": {"entries": []},
        }
    if member == sheet_module._COMPLETE_CHARACTER_DISPLAY_ROWS:
        return {
            "rows": [
                {"tab_id": "paths-subpaths", "value": {"path": "Fire Qi"}},
                {"tab_id": "spheres-talents", "value": {"talents": ["Cinder Touch"]}},
                {"tab_id": "insights", "value": {"insights": ["Insight 1"]}},
                {"tab_id": "martial-manuals-recorded-arts", "value": {"manuals": []}},
            ]
        }
    if member == "Complete_Action_Surface.json":
        action = {
            "action_id": "action.test",
            "record_id": "record.test",
            "name": "Test Strike",
            "action_type": "action",
            "timing": "action",
            "cost": "1 CP",
            "range": "60 feet",
            "target": "one creature",
            "roll_save_check": "Cultivation Attack",
            "effect": {"text": "Deal Fire damage", "malicious_receipt": {"secret": "drop"}},
            "failure": "No effect",
            "duration": "Instantaneous",
            "limit": "Once per turn",
            "counterplay": "A successful save halves damage",
            "resource_costs": [{"resource_id": "RES_CP", "amount": 1, "condition": "legal", "timing": "declare"}],
            "resource_gains": [],
            "resource_requirements": [{"resource_id": "RES_CP", "minimum": 1, "condition": "available"}],
            "state_arrays": [{"state_id": "burning", "duration": "1 round"}],
            "unexpected_receipt": {"token": "drop"},
        }
        return {
            "schema_version": "test-action-surface",
            "status": "ACTION_SURFACE_READY",
            "execution_authority": True,
            "global_combat_readiness": True,
            "mechanical_authority": True,
            "signature_loadout_record_ids": ["record.test"],
            "actions": [action],
            "procedures": [],
            "provenance": {"secret": "drop"},
        }
    if member == "Composite_Playbook.json":
        return {
            "schema_version": "test-composite",
            "execution_authority": False,
            "classification": "display_playbook",
            "composites": [{
                "playbook_id": "playbook.test",
                "display_name": "Test Sequence",
                "classification": "display_playbook",
                "tactical_goal": "Create an opening",
                "sequence": [{
                    "action_id": "action.test",
                    "priority": 1,
                    "preconditions": ["target visible"],
                    "malicious_receipt": {"secret": "drop"},
                }],
                "resource_budget": {"resource_id": "RES_CP", "amount": 1},
                "branches": [{"condition": "miss", "action_ids": ["action.test"], "fallback": "defend"}],
                "fallback": "defend",
                "dao_i_ching_hooks": [{"hook": "read the wind", "dao": "patience", "i_ching": "change"}],
                "record_bindings": [{
                    "record_id": "record.test",
                    "display_name": "Test Strike",
                    "capabilities": {"gm_display": "SUPPORTED"},
                    "malicious_receipt": {"secret": "drop"},
                }],
                "linked_action_record_ids": ["record.test"],
                "linked_action_details": [{"action_id": "action.test", "name": "Test Strike", "effect": "Deal Fire damage"}],
                "unexpected_receipt": {"token": "drop"},
            }],
        }
    if member == "Projection_Diagnostics.json":
        return {"status": "PASS", "valid": True, "diagnostics": [{"code": "bounded"}]}
    if member == "Projection_Coverage_Report.json":
        return {"status": "PASS", "counts": {"available": 18}}
    return {"status": "PASS", "metadata": {"request_sha256": "receipt-must-not-leak"}}


def _write_archive(path: Path, *, display_name: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        member: canonical_json(_surface_document(member, display_name=display_name)).encode("utf-8")
        for member in sorted(_archive_members())
    }
    # Legacy archives may still carry this owner-authored file. It is ignored by
    # the current sheet surface, without changing the archive on disk.
    payload["Composite_Playbook.json"] = canonical_json({"composites": [{"display_name": "Old playbook"}]}).encode("utf-8")
    checksum = "".join(f"{sha256_bytes(data)}  {member}\n" for member, data in sorted(payload.items())).encode("utf-8")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for member, data in sorted({**payload, "SHA256SUMS.txt": checksum}.items()):
            info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return sha256_file(path)


def _write_candidate(data_root: Path, *, display_name: str = "Candidate", **pointer_overrides: object) -> tuple[Path, str]:
    candidate = data_root / "candidate.zip"
    candidate_sha256 = _write_archive(candidate, display_name=display_name)
    pointer = {
        "project_id": PROJECT_ID,
        "projection_id": PROJECTION_ID,
        "status": "GM_MODEL_CANDIDATE_READY",
        "candidate_zip": str(candidate),
        "candidate_sha256": candidate_sha256,
        **pointer_overrides,
    }
    pointer_path = data_root / "factory_candidates" / PROJECT_ID / "current.json"
    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    pointer_path.write_text(canonical_json(pointer), encoding="utf-8")
    return candidate, candidate_sha256


def _service(tmp_path: Path) -> CharacterSheetService:
    return CharacterSheetService(Database(Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / "data")))


def _sheet_stubs(service: CharacterSheetService) -> None:
    service.projects = SimpleNamespace(
        get_project=lambda _project_id: {
            "project": {
                "project_id": PROJECT_ID,
                "revision": 1,
                "name": "Complete Character Test",
                "updated_at": None,
                "user_locks": [],
            },
            "builder_lifecycle": {"persistence_state": "saved_draft"},
        }
    )
    service._blueprint = lambda _project_id: None
    service._compiled_artifacts = lambda _project_id: (
        None,
        {"status": "READY", "projection_id": PROJECTION_ID, "eligible_for_command5": False},
    )
    service._factory_workspace_status = lambda _project_id, **_kwargs: {
        "status": "NOT_ATTEMPTED",
        "command5": "NOT_RUN",
        "command6": "NOT_RUN",
        "gm_export_available": False,
    }


def test_sheet_emits_verified_candidate_envelope_with_all_canonical_surfaces(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _sheet_stubs(service)
    _candidate, candidate_sha256 = _write_candidate(service.db.settings.data_dir)

    result = service.sheet(PROJECT_ID)
    envelope = result["complete_character"]

    assert envelope["available"] is True
    assert envelope["source_kind"] == "candidate"
    assert envelope["finalized"] is False
    assert envelope["candidate_sha256"] == candidate_sha256
    assert envelope["package_sha256"] == candidate_sha256
    assert envelope["required_surface_ids"] == list(sheet_module._COMPLETE_CHARACTER_SURFACE_IDS)
    assert list(envelope["surfaces"]) == list(sheet_module._COMPLETE_CHARACTER_SURFACE_IDS)
    assert envelope["coverage"] == {
        "required_count": 17,
        "available_count": 17,
        "missing_ids": [],
        "complete": True,
    }
    assert envelope["surfaces"]["overview_core_stats"]["data"]["identity"]["display_name"] == "Candidate"
    action = envelope["surfaces"]["actions"]["data"]["actions"][0]
    assert action["effect"] == {"text": "Deal Fire damage"}
    assert action["resource_costs"] == [{"resource_id": "RES_CP", "amount": 1, "condition": "legal", "timing": "declare"}]
    assert "unexpected_receipt" not in action
    assert "composite_playbooks" not in envelope["surfaces"]
    assert "Composite_Playbook.json" in zipfile.ZipFile(_candidate).namelist()
    assert "malicious_receipt" not in json.dumps(envelope["surfaces"], sort_keys=True)


@pytest.mark.parametrize(
    ("pointer_overrides", "reason_code"),
    [
        ({"projection_id": "stale-projection"}, "COMPLETE_CHARACTER_CANDIDATE_PROJECTION_MISMATCH"),
        ({"candidate_sha256": "0" * 64}, "COMPLETE_CHARACTER_CANDIDATE_HASH_MISMATCH"),
    ],
)
def test_candidate_pointer_projection_and_hash_mismatch_fail_closed(
    tmp_path: Path,
    pointer_overrides: dict[str, object],
    reason_code: str,
) -> None:
    service = _service(tmp_path)
    _candidate, _candidate_sha256 = _write_candidate(service.db.settings.data_dir, **pointer_overrides)

    envelope = service._complete_character(PROJECT_ID, {"projection_id": PROJECTION_ID})

    assert envelope["available"] is False
    assert envelope["reason_code"] == reason_code
    assert list(envelope["surfaces"]) == list(sheet_module._COMPLETE_CHARACTER_SURFACE_IDS)
    assert envelope["coverage"]["complete"] is False


def test_archive_outer_hash_comes_from_open_handle_and_symlink_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    candidate, candidate_sha256 = _write_candidate(service.db.settings.data_dir)
    archive = service._complete_character_archive(candidate)
    assert archive["sha256"] == candidate_sha256

    def path_hash_must_not_be_used(_path: Path) -> str:
        raise AssertionError("archive verification reopened the path for hashing")

    monkeypatch.setattr(sheet_module, "sha256_file", path_hash_must_not_be_used)
    selected = CharacterSheetService._complete_character_candidate_pointer(
        service.db.settings.data_dir,
        PROJECT_ID,
        {"projection_id": PROJECTION_ID},
    )
    assert selected["candidate_sha256"] == candidate_sha256
    assert selected["archive"]["sha256"] == candidate_sha256

    symlink = service.db.settings.data_dir / "candidate-link.zip"
    os.symlink(candidate, symlink)
    with pytest.raises(FoundryError) as exc:
        service._complete_character_archive(symlink)
    assert exc.value.code == "COMPLETE_CHARACTER_ARCHIVE_INVALID"


def test_compact_sheet_does_not_touch_candidate_or_portable_mechanics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)
    _sheet_stubs(service)
    candidate = service.db.settings.data_dir / "candidate.zip"
    candidate.write_bytes(b"must-not-be-read")
    workspace_calls: list[dict[str, object]] = []

    service._factory_workspace_status = lambda _project_id, **kwargs: (
        workspace_calls.append(kwargs)
        or {
            "status": "NOT_ATTEMPTED",
            "command5": "NOT_RUN",
            "command6": "NOT_RUN",
            "gm_export_available": False,
        }
    )
    portable_calls: list[str] = []

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("compact sheet loaded the mechanics package")

    service._complete_character_with_portable = fail_if_called  # type: ignore[method-assign]
    monkeypatch.setattr(
        PortableCharacterPackageService,
        "verified_status",
        lambda _self, project_id: (portable_calls.append(project_id) or {"status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"}),
    )

    result = service.sheet(PROJECT_ID, compact=True)

    assert "complete_character" not in result
    assert candidate.read_bytes() == b"must-not-be-read"
    assert workspace_calls == [{"include_candidate": False}]
    assert portable_calls == [PROJECT_ID]


def test_invalid_candidate_does_not_downgrade_verified_base_sheet_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    _sheet_stubs(service)
    _candidate, _candidate_sha256 = _write_candidate(service.db.settings.data_dir, candidate_sha256="0" * 64)
    monkeypatch.setattr(
        PortableCharacterPackageService,
        "verified_status",
        lambda _self, _project_id: {"status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED"},
    )

    result = service.sheet(PROJECT_ID)

    assert result["complete_character"]["available"] is False
    assert result["complete_character"]["reason_code"] == "COMPLETE_CHARACTER_CANDIDATE_HASH_MISMATCH"
    assert result["gm_export"]["available"] is True
    assert result["gm_export"]["source_consumer_verified"] is True
    assert result["readiness"]["gm_screen"] == "GM_READY_SOURCE_VERIFIED"


def test_finalized_source_takes_precedence_only_when_linked_to_current_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    _candidate, candidate_sha256 = _write_candidate(service.db.settings.data_dir, display_name="Candidate")
    package = service.db.settings.data_dir / "portable_characters" / PROJECT_ID / "current.zip"
    package_sha256 = _write_archive(package, display_name="Finalized")
    verified = {
        "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
        "project_id": PROJECT_ID,
        "package_path": str(package),
        "package_sha256": package_sha256,
        "manifest_identity": {"source_command5_candidate_sha256": candidate_sha256},
        "audit": {
            "valid": True,
            "sha256": package_sha256,
            "manifest": {
                "project_id": PROJECT_ID,
                "projection_id": PROJECTION_ID,
                "source_command5_candidate_sha256": candidate_sha256,
            },
        },
    }
    monkeypatch.setattr(PortableCharacterPackageService, "verified_status", lambda _self, _project_id: verified)

    finalized = service._complete_character(PROJECT_ID, {"projection_id": PROJECTION_ID})
    assert finalized["available"] is True
    assert finalized["source_kind"] == "finalized"
    assert finalized["finalized"] is True
    assert finalized["package_sha256"] == package_sha256
    assert finalized["candidate_sha256"] == candidate_sha256
    assert finalized["surfaces"]["overview_core_stats"]["data"]["identity"]["display_name"] == "Finalized"

    mismatched_projection = json.loads(json.dumps(verified))
    mismatched_projection["projection_id"] = "stale-projection"
    monkeypatch.setattr(PortableCharacterPackageService, "verified_status", lambda _self, _project_id: mismatched_projection)
    candidate = service._complete_character(PROJECT_ID, {"projection_id": PROJECTION_ID})
    assert candidate["available"] is True
    assert candidate["source_kind"] == "candidate"
    assert candidate["finalized"] is False
    assert candidate["surfaces"]["overview_core_stats"]["data"]["identity"]["display_name"] == "Candidate"


def _rich_complete_character_members() -> dict[str, object]:
    """Build realistic public records with deliberately private noise."""

    occurrence = {
        "occurrence_id": "occ.path.iron-fist",
        "feature_id": "tianxia.path.body_refining.feature.iron_fist",
        "display_name": "Iron Fist",
        "parent_kind": "path",
        "owning_path_id": "tianxia.path.body_refining",
        "owning_path_level": 4,
        "acquisition_cl": 4,
        "acquired_at_character_cl": 4,
        "acquisition_event_id": "event.level.4",
        "acquisition_event_hash": "e" * 64,
        "event": {
            "event_id": "event.level.4",
            "event_hash": "e" * 64,
            "sequence": 4,
            "packet_id": "packet.level.4",
            "choice_kind": "ability_score_change",
            "deltas": {"CHA": 1, "CON": 1},
            "unknown_event_detail": "must be filtered",
        },
        "source_backed": True,
        "source_packet_ids": ["packet.level.4"],
        "source_text": "1d8 + Strength or Constitution modifier; choose B/P/S.",
        "full_description": "1d8 + Strength or Constitution modifier; choose B/P/S.",
        "selection": {
            "choice_kind": "ability_score_change",
            "deltas": {"CHA": 1, "CON": 1},
            "insight_occurrence": {
                "record_id": "insight.awakener-of-tools",
                "content_binding": {
                    "pack_id": "tianxia.insights",
                    "pack_version": "r1",
                    "pack_hash": "a" * 64,
                    "record_hash": "b" * 64,
                    "unknown_binding": "drop",
                },
                "source_evidence": [{
                    "source_id": "source.insight.awakener",
                    "source_path": "authority/insights.json",
                    "source_hash": "c" * 64,
                    "source_anchor": "insight:awakener-of-tools",
                    "unknown_evidence": "drop",
                }],
                "execution_authority": {
                    "execution_status": "display_only",
                    "manual_runtime_boundary": "No automatic runtime execution.",
                    "execution_profile": {"action_or_procedure": "display only", "unknown_profile": "drop"},
                    "unknown_authority": "drop",
                },
                "unknown_insight_binding": "drop",
            },
            "unknown_selection_detail": "must be filtered",
        },
        "unknown_occurrence_detail": {"sealed_request": {"seed": "must be filtered"}},
    }
    insight_occurrence = {
        "occurrence_id": "occ.insight.awakener",
        "insight_id": "insight.awakener-of-tools",
        "name": "Awakener of Tools",
        "gained_at_cl": 8,
        "ability": None,
        "amount": None,
        "ability_change_applied": False,
        "repeat_index": 1,
        "source_record_hash": "b" * 64,
        "source_packet_ids": ["packet.insight.8"],
        "source_evidence": [{
            "source_id": "source.insight.awakener",
            "source_path": "authority/insights.json",
            "source_hash": "c" * 64,
            "source_anchor": "insight:awakener-of-tools",
            "section_sha256": "d" * 64,
            "unknown_evidence": "drop",
        }],
        "unknown_occurrence_detail": "drop",
    }
    insight_occurrences = [
        insight_occurrence,
        {
            **insight_occurrence,
            "occurrence_id": "occ.insight.beast-core",
            "insight_id": "insight.beast-core-butcher",
            "name": "Beast-Core Butcher",
            "gained_at_cl": 12,
            "repeat_index": 2,
            "source_record_hash": "e" * 64,
            "source_packet_ids": ["packet.insight.12"],
            "source_evidence": [{
                **insight_occurrence["source_evidence"][0],
                "source_id": "source.insight.beast-core",
                "source_anchor": "insight:beast-core-butcher",
            }],
        },
        {
            **insight_occurrence,
            "occurrence_id": "occ.insight.bone-general",
            "insight_id": "insight.bone-general",
            "name": "Bone General",
            "gained_at_cl": 16,
            "repeat_index": 3,
            "source_record_hash": "f" * 64,
            "source_packet_ids": ["packet.insight.16"],
            "source_evidence": [{
                **insight_occurrence["source_evidence"][0],
                "source_id": "source.insight.bone-general",
                "source_anchor": "insight:bone-general",
            }],
        },
    ]
    return {
        "Leveling_Ledger.json": {
            "schema_version": "Leveling_Ledger.v2",
            "levels": [{
                "cl": 4,
                "event_id": "event.level.4",
                "trained_choices": [{"record_id": "talent.trained.4", "choice_type": "trained"}],
                "earned_feature_occurrences": [occurrence],
                "unknown_level_detail": {"request": {"seed": "drop"}},
            }],
        },
        "Insight_Execution_Coverage.json": {
            "schema_version": "Insight_Execution_Coverage.v1",
            "coverage": {"status": "complete", "unknown_coverage": "drop"},
            "cultivation_insight_occurrences": insight_occurrences,
            "cultivation_insight_record_ids": [
                "insight.awakener-of-tools", "insight.beast-core-butcher", "insight.bone-general",
            ],
            "unknown_document_detail": "drop",
        },
        "Forged_Techniques.json": {
            "schema_version": "Forged_Techniques.v1",
            "forged_techniques": [{
                "technique_id": "forged.test.athletics",
                "record_id": "forged.test.athletics",
                "record_text": "Forged record text with the complete public effect.",
                "display_name": "Athletics Projection",
                "action_type": "Action",
                "cp_cost": {"base_form": 3, "final": 5},
                "complexity": {"final": 7},
                "technique_forging_dc": 28,
                "effect": {
                    "summary": "Project an authenticated athletic effect.",
                    "primary_effect_text": "The source effect applies within its stated limits.",
                },
                "target_range_area": "30 feet",
                "limits": ["once per turn"],
                "drawbacks": [{"drawback_id": "drawback.test", "display_name": "Strain", "restriction": "one use", "cp_reduction": 1}],
                "construction": {"request": {"seed": "private request must not leak"}, "seed": "private seed must not leak"},
                "unknown_record_detail": {"secret": "drop"},
            }],
        },
        "Martial_Arts_and_Manuals.json": {
            "schema_version": "Martial_Arts_and_Manuals.v1",
            "manuals": [{
                "record_id": "manual.test.air-returning",
                "display_name": "Air Returning School",
                "record_text": "Recorded art text with the complete learning and execution contract.",
                "record_hash": "1" * 64,
                "learning_dc": {
                    "computed_dc": 17,
                    "difficulty": "Open",
                    "access_category": "Open",
                    "prior_recorded_arts_this_cl": 0,
                },
                "execution": {
                    "action_id": "manual.test.action",
                    "effect": "Redirect a committed strike.",
                    "range": "Self",
                    "target": "one attacker",
                    "timing": "Reaction",
                    "cost": "1 CP",
                    "counterplay": "The attacker may choose another target.",
                },
                "requirements": ["Study the sealed Manual"],
                "source": {
                    "path": "authority/manuals.json",
                    "anchor": "manual:air-returning",
                    "source_hash": "2" * 64,
                    "source_id": "source.manual.air-returning",
                },
                "unknown_record_detail": {"private": "drop"},
            }],
        },
        "Manual_Lineage_Record.json": {
            "schema_version": "Manual_Lineage_Record.v1",
            "training_sources": [{
                "source_id": "source.manual.air-returning",
                "name": "Air Returning School",
                "type": "manual",
                "contents": {
                    "false_routes": [],
                    "methods": ["Return force along the committed line."],
                    "recipes": [],
                    "recorded_arts": ["manual.test.air-returning"],
                    "theory": ["A response follows a witnessed source."],
                    "warnings": [],
                },
                "gained_at_cl": 1,
                "mechanics_granted": [],
                "restrictions": [],
                "risks": [],
                "record_hash": "3" * 64,
                "source_packet_ids": ["packet.manual.1"],
                "unknown_lineage_detail": {"request": {"seed": "drop"}},
            }],
        },
        "Immortal_Arts.json": {
            "schema_version": "Immortal_Arts.v1",
            "immortal_arts": [{
                "art_id": "immortal.test.creation",
                "record_id": "immortal.test.creation",
                "display_name": "Bone Guard Art",
                "record_text": "Immortal record text with the full source-backed construction result.",
                "canonical_id": "tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation",
                "corpus_path": "authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json",
                "cultivation_level": 14,
                "ownership": {"owning_path_id": "tianxia.path.body_refining", "at_owning_path_cl_14": 14},
                "realm": "Nascent Soul",
                "acquisition": {
                    "canonical_id": "tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation",
                    "at_owning_path_cl_14": 14,
                    "feature_record_hash": "5" * 64,
                    "granted_at_cl": 14,
                    "source": {
                        "path": "authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json",
                        "anchor": "feature:bone_guard_manifestation",
                        "sha256": "6" * 64,
                    },
                    "unknown_acquisition_detail": "drop",
                },
                "automatic_construction": {
                    "mode": "initial_factory_materialization",
                    "outcome": "accepted_after_full_rederivation",
                    "payment": "reported_requirement_only",
                    "roll": None,
                    "training_choice_cost": 0,
                    "unknown_construction_detail": "drop",
                },
                "activation_cp": 12,
                "activation_cp_breakdown": {"base_source_cp": 5, "factor_cp": 4, "final": 12},
                "mandate_complexity": 28,
                "mandate_complexity_breakdown": {"factor_cost": 4, "final": 28},
                "material_cost_gp": 100,
                "refinement_dc": 22,
                "factors": [{
                    "factor_id": "construct_puppet_body_creation",
                    "display_name": "Construct or Puppet Body Creation",
                    "mechanical_chassis": "Create a body frame with no unpaid action capacity.",
                    "cp_cost": 4,
                    "mandate_cost": 4,
                    "factor_count": 1,
                    "feature_record_hash": "5" * 64,
                    "granted_at_cl": 14,
                    "excerpt": "Create a body frame from an authenticated Bone Guard progression.",
                    "source": {
                        "path": "authority/chassis.json",
                        "anchor": "factor:creation",
                        "sha256": "4" * 64,
                        "corpus_path": "authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json",
                    },
                    "success_by_10": {
                        "threshold": 10,
                        "default": "The constructed frame remains stable.",
                        "stability_credit": {"amount": 2},
                    },
                    "cp_credit": {"amount": 4},
                    "unknown_factor_detail": "drop",
                }],
                "statistics": {
                    "size": "Large",
                    "reach": "5 feet",
                    "stability_credit": {"amount": 2},
                    "unknown_statistics_detail": "drop",
                },
                "action_surface": {
                    "action_type": "Action",
                    "effect": {"summary": "Create the authenticated Bone Guard body."},
                    "range": "Self",
                    "target": "one created frame",
                    "resource_cost": 12,
                    "limits": ["one active frame"],
                    "action_capacity": {"bone_strike": 1, "guard_the_sovereign": 1, "unknown_capacity": "drop"},
                    "default": {"action_type": "Action", "target": "one created frame"},
                    "bone_strike": {
                        "attack_roll": "d20 + PB + STR",
                        "effective_effect": "Bone Strike deals the authenticated source damage.",
                        "reach": "5 feet",
                        "saving_throws": None,
                        "unknown_bone_strike_detail": "drop",
                    },
                    "guard_the_sovereign": {
                        "effective_effect": "Guard the Sovereign protects the created frame within its stated limits.",
                        "saving_throws": "Dexterity save",
                        "threshold": 10,
                        "unknown_guard_detail": "drop",
                    },
                    "hp_restoration": {"formula": "PBd10", "at_owning_path_cl_14": "PBd10"},
                    "roll": None,
                    "source_mechanics": {"feature_id": "bone_guard", "published_section": "Bone Guard source"},
                },
                "steps": [{
                    "step": 12,
                    "name": "action_surface",
                    "payload": {
                        "result": "Resolve the created frame",
                        "cp_credit": {"amount": 4},
                        "stability_credit": {"amount": 2},
                        "success_by_10": {"threshold": 10},
                        "unknown": "drop",
                    },
                }],
                "gm_review_required": False,
                "construction": {"request": {"seed": "private request must not leak"}, "seed": "private seed must not leak"},
                "unknown_record_detail": "drop",
            }],
        },
    }


def test_complete_character_surfaces_preserve_typed_records_manual_lineage_and_insight_provenance() -> None:
    members = _rich_complete_character_members()
    surfaces, coverage = CharacterSheetService._complete_character_surfaces(
        {"members": members, "member_count": len(members), "checksum_count": len(members)},
        source_kind="candidate",
        finalized=False,
    )

    assert coverage["complete"] is False
    assert all(surfaces[surface_id]["available"] for surface_id in (
        "leveling", "insights", "forged_techniques", "manuals_recorded_arts", "immortal_arts",
    ))

    leveling = surfaces["leveling"]["data"]["levels"][0]
    assert leveling["earned_feature_occurrences"][0]["source_text"].startswith("1d8")
    assert leveling["earned_feature_occurrences"][0]["selection"]["deltas"] == {"CHA": 1, "CON": 1}
    milestone = leveling["earned_feature_occurrences"][0]
    assert milestone["source_backed"] is True
    assert milestone["event"] == {
        "event_id": "event.level.4",
        "event_hash": "e" * 64,
        "sequence": 4,
        "packet_id": "packet.level.4",
        "choice_kind": "ability_score_change",
        "deltas": {"CHA": 1, "CON": 1},
    }
    insight_binding = leveling["earned_feature_occurrences"][0]["selection"]["insight_occurrence"]
    assert insight_binding["content_binding"]["record_hash"] == "b" * 64
    assert insight_binding["source_evidence"][0]["source_id"] == "source.insight.awakener"
    assert insight_binding["execution_authority"]["manual_runtime_boundary"] == "No automatic runtime execution."
    assert insight_binding["execution_authority"]["execution_profile"]["action_or_procedure"] == "display only"
    assert "unknown_binding" not in insight_binding["content_binding"]
    assert "unknown_evidence" not in insight_binding["source_evidence"][0]
    assert "unknown_authority" not in insight_binding["execution_authority"]
    assert "unknown_profile" not in insight_binding["execution_authority"]["execution_profile"]
    assert "unknown_level_detail" not in leveling
    assert "unknown_occurrence_detail" not in leveling["earned_feature_occurrences"][0]

    insights = surfaces["insights"]["data"]["cultivation_insight_occurrences"]
    assert [(row["insight_id"], row["gained_at_cl"]) for row in insights] == [
        ("insight.awakener-of-tools", 8),
        ("insight.beast-core-butcher", 12),
        ("insight.bone-general", 16),
    ]
    assert [row["ability_change_applied"] for row in insights] == [False, False, False]
    assert [row["source_record_hash"] for row in insights] == ["b" * 64, "e" * 64, "f" * 64]
    assert insights[0]["source_packet_ids"] == ["packet.insight.8"]
    assert insights[0]["source_evidence"][0]["source_anchor"] == "insight:awakener-of-tools"
    assert "unknown_occurrence_detail" not in insights[0]

    forged = surfaces["forged_techniques"]["data"]["forged_techniques"][0]
    assert forged["record_text"].startswith("Forged record text")
    assert forged["effect"]["primary_effect_text"].startswith("The source effect")
    assert forged["drawbacks"][0]["restriction"] == "one use"
    assert "construction" not in forged
    assert "unknown_record_detail" not in forged

    manuals = surfaces["manuals_recorded_arts"]["data"]
    recorded = manuals["Martial_Arts_and_Manuals.json"]["manuals"][0]
    lineage = manuals["Manual_Lineage_Record.json"]["training_sources"][0]
    assert recorded["record_text"].startswith("Recorded art text")
    assert recorded["execution"]["counterplay"].startswith("The attacker")
    assert recorded["learning_dc"]["computed_dc"] == 17
    assert lineage["contents"]["recorded_arts"] == ["manual.test.air-returning"]
    assert lineage["source_packet_ids"] == ["packet.manual.1"]
    assert "unknown_record_detail" not in recorded
    assert "unknown_lineage_detail" not in lineage

    immortal = surfaces["immortal_arts"]["data"]["immortal_arts"][0]
    assert immortal["record_text"].startswith("Immortal record text")
    assert immortal["canonical_id"].endswith("bone_guard_manifestation")
    assert immortal["acquisition"]["at_owning_path_cl_14"] == 14
    assert immortal["acquisition"]["feature_record_hash"] == "5" * 64
    assert immortal["corpus_path"].endswith("Tianxia_Subpath_Tradition_Index_Master_P2B.json")
    assert immortal["acquisition"]["source"] == {
        "path": "authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json",
        "anchor": "feature:bone_guard_manifestation",
        "sha256": "6" * 64,
    }
    assert immortal["automatic_construction"] == {
        "mode": "initial_factory_materialization",
        "outcome": "accepted_after_full_rederivation",
        "payment": "reported_requirement_only",
        "roll": None,
        "training_choice_cost": 0,
    }
    assert immortal["statistics"]["size"] == "Large"
    assert immortal["statistics"]["reach"] == "5 feet"
    assert immortal["statistics"]["stability_credit"]["amount"] == 2
    assert immortal["factors"][0]["factor_id"] == "construct_puppet_body_creation"
    assert immortal["factors"][0]["mechanical_chassis"].startswith("Create a body")
    assert immortal["factors"][0]["factor_count"] == 1
    assert immortal["factors"][0]["source"]["corpus_path"].endswith("Tianxia_Subpath_Tradition_Index_Master_P2B.json")
    assert immortal["factors"][0]["success_by_10"] == {
        "threshold": 10,
        "default": "The constructed frame remains stable.",
        "stability_credit": {"amount": 2},
    }
    assert immortal["factors"][0]["cp_credit"]["amount"] == 4
    assert immortal["action_surface"]["effect"]["summary"].startswith("Create the authenticated")
    assert immortal["action_surface"]["action_capacity"] == {"bone_strike": 1, "guard_the_sovereign": 1}
    assert immortal["action_surface"]["bone_strike"]["attack_roll"] == "d20 + PB + STR"
    assert immortal["action_surface"]["bone_strike"]["effective_effect"].startswith("Bone Strike")
    assert immortal["action_surface"]["guard_the_sovereign"]["saving_throws"] == "Dexterity save"
    assert immortal["action_surface"]["hp_restoration"] == {"formula": "PBd10", "at_owning_path_cl_14": "PBd10"}
    assert immortal["steps"][0]["payload"]["result"] == "Resolve the created frame"
    assert immortal["steps"][0]["payload"]["cp_credit"]["amount"] == 4
    assert immortal["steps"][0]["payload"]["success_by_10"]["threshold"] == 10
    assert "construction" not in immortal
    assert "unknown_acquisition_detail" not in immortal["acquisition"]
    assert "unknown_factor_detail" not in immortal["factors"][0]
    assert "unknown_bone_strike_detail" not in immortal["action_surface"]["bone_strike"]
    assert "unknown_guard_detail" not in immortal["action_surface"]["guard_the_sovereign"]
    assert "unknown_record_detail" not in immortal


def test_complete_method_surface_preserves_activation_and_source_profiles() -> None:
    profile = {
        "path_id": "BODY_REFINING", "resource_id": "tianxia.resource.stamina", "resource_name": "Stamina",
        "delta_proficiency_bonus_units": -1, "exact_modifier": "-PB", "shape_key": "Narrow Channel",
        "applies_independently": True, "conversion_permitted": False, "conversion_rule": None,
        "source_text": "Narrow Channel applied independently to Stamina.",
    }
    method = {
        "record_id": "METHOD-083", "state": "active", "mechanical_projection": True,
        "activation_event_id": "event.activate", "source_packet_ids": ["packet.acquire", "packet.activate"],
        "mechanics": {
            "schema": "TianxiaFoundry.MethodMechanicalAuthority.v1", "method_id": "METHOD-083",
            "per_path_resource_profiles": [{**profile, "unknown_private_metadata": "excluded"}],
            "activation_min_cl": 1, "refill_current": False,
            "resource_modifiers": [{"formula": {"root": {"op": "multiply"}}}],
        },
        "unknown_private_metadata": "excluded",
    }
    projected = CharacterSheetService._complete_character_project_member(
        "method", "Cultivation_Method_Profile.json",
        {"schema_version": "TianxiaFoundry.CharacterGMMethod.v1", "method": method},
    )["method"]
    assert projected["activation_event_id"] == "event.activate"
    assert projected["source_packet_ids"] == ["packet.acquire", "packet.activate"]
    assert projected["mechanics"]["per_path_resource_profiles"] == [profile]
    assert projected["mechanics"]["refill_current"] is False
    assert "resource_modifiers" not in projected["mechanics"]
    assert "unknown_private_metadata" not in projected


def test_complete_foundation_surface_retains_source_conditions_and_initial_currency() -> None:
    from non_sphere_authority.foundation_mechanics import (
        installed_foundation_state, resolve_initial_foundation_mechanics, verified_foundation_records,
    )

    record = verified_foundation_records()["karma_knot_root_v0_2B"]
    mechanics = resolve_initial_foundation_mechanics(record, ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"])
    foundation = {
        **installed_foundation_state(mechanics, record["foundation_id"], "event.foundation"),
        "mechanical_projection": True, "mechanics": mechanics,
        "unknown_private_metadata": "excluded",
    }
    projected = CharacterSheetService._complete_character_project_member(
        "foundation", "Foundation_Detail_Ledger.json", {"foundation": foundation},
    )["foundation"]
    assert projected["stage"] == "Awakened"
    assert projected["active_expression_path_ids"] == ["tianxia.path.spirit_awakening"]
    assert projected["resource"]["current"] == 0
    assert projected["resource"]["maximum"] == 1
    assert projected["resource"]["rule_descriptions"] == foundation["resource"]["rule_descriptions"]
    assert projected["mechanics"]["source_passives"] == [
        {key: passive[key] for key in ("name", "source_fields", "source_feature_sha256", "execution_authority")}
        for passive in mechanics["source_passives"]
    ]
    assert "resource_modifiers" not in projected["mechanics"]
    assert "unknown_private_metadata" not in projected


def _selected_record_cards() -> dict[str, dict[str, object]]:
    return {
        "METHOD-002": {
            "record_id": "METHOD-002",
            "record_hash": "m" * 64,
            "display_name": "Ash-Breath Furnace Method",
            "full_description": "The complete sealed Method description.",
            "full_description_source": "locked_typed_catalog_record",
            "source": {"path": "methods.json", "anchor": "method:METHOD-002", "sha256": "a" * 64},
            "source_packet_ids": ["packet.method"],
        },
        "FOUNDATION-001": {
            "record_id": "FOUNDATION-001",
            "record_hash": "f" * 64,
            "display_name": "Dream Mirror Foundation",
            "full_description": "The complete sealed Foundation description.",
            "full_description_source": "locked_typed_catalog_record",
            "source": {"path": "foundations.json", "anchor": "foundation:FOUNDATION-001", "sha256": "b" * 64},
            "source_packet_ids": ["packet.foundation"],
        },
    }


def test_selected_method_and_foundation_rows_are_enriched_from_exact_sealed_cards() -> None:
    cards = _selected_record_cards()
    method = CharacterSheetService._enrich_selected_record_display(
        {
            "state": "acquired",
            "record_id": "METHOD-002",
            "record_hash": "m" * 64,
            "display_name": "Ash-Breath Furnace Method",
            "mechanical_projection": False,
        },
        cards,
        surface="Method",
    )
    foundation = CharacterSheetService._enrich_selected_record_display(
        {
            "state": "acquired",
            "record_id": "FOUNDATION-001",
            "record_hash": "f" * 64,
            "display_name": "Dream Mirror Foundation",
            "mechanical_projection": False,
        },
        cards,
        surface="Foundation",
    )

    assert method["full_description"] == "The complete sealed Method description."
    assert method["source"] == cards["METHOD-002"]["source"]
    assert method["source_packet_ids"] == ["packet.method"]
    assert method["mechanical_projection"] is False
    assert method["display_only_not_execution_authority"] is True
    assert foundation["full_description"] == "The complete sealed Foundation description."
    assert foundation["source_path"] == "foundations.json"
    assert foundation["source_anchor"] == "foundation:FOUNDATION-001"
    assert foundation["source_hash"] == "b" * 64
    assert foundation["mechanical_projection"] is False


@pytest.mark.parametrize("mutation", ["record_hash", "display_name", "source"])
def test_selected_method_display_rejects_hash_name_or_source_drift(mutation: str) -> None:
    cards = _selected_record_cards()
    selected = {
        "state": "acquired",
        "record_id": "METHOD-002",
        "record_hash": "m" * 64,
        "display_name": "Ash-Breath Furnace Method",
        "mechanical_projection": False,
    }
    if mutation == "record_hash":
        selected["record_hash"] = "0" * 64
    elif mutation == "display_name":
        selected["display_name"] = "Caller Relabelled Method"
    else:
        selected["source"] = {"path": "caller.md", "anchor": "method:METHOD-002", "sha256": "a" * 64}

    with pytest.raises(FoundryError) as rejected:
        CharacterSheetService._enrich_selected_record_display(selected, cards, surface="Method")
    assert rejected.value.code == "CHARACTER_SHEET_SELECTED_RECORD_DISPLAY_INVALID"


def test_leveling_joins_all_same_event_path_occurrences_without_backdating_subpaths() -> None:
    levels = [
        {
            "cl": 1,
            "event_id": "event.level.1",
            "trained_choices": [{"record_id": "talent.trained.1", "choice_type": "trained"}],
        },
        {
            "cl": 2,
            "event_id": "event.level.2",
            "trained_choices": [{"record_id": "talent.trained.2", "choice_type": "trained"}],
        },
    ]
    occurrences = [
        {
            "occurrence_id": "path.1a",
            "parent_kind": "path",
            "feature_id": "path.feature.one",
            "acquisition_event_id": "event.level.1",
            "acquisition_event": {"event_id": "event.level.1", "kind": "level_advance"},
        },
        {
            "occurrence_id": "path.1b",
            "parent_kind": "path",
            "feature_id": "path.feature.two",
            "acquisition_event_id": "event.level.1",
            "acquisition_event": {"event_id": "event.level.1", "kind": "level_advance"},
        },
        {
            "occurrence_id": "subpath.late",
            "parent_kind": "subpath",
            "feature_id": "subpath.feature.late",
            "acquisition_event_id": "event.level.1",
            "acquisition_event": {"event_id": "event.level.1", "kind": "level_advance"},
        },
        {
            "occurrence_id": "path.2",
            "parent_kind": "path",
            "feature_id": "path.feature.three",
            "acquisition_event_id": "event.level.2",
            "acquisition_event": {"event_id": "event.level.2", "kind": "level_advance"},
        },
    ]

    enriched = CharacterSheetService._levels_with_earned_feature_occurrences(levels, occurrences)

    assert [row["occurrence_id"] for row in enriched[0]["earned_feature_occurrences"]] == ["path.1a", "path.1b"]
    assert [row["occurrence_id"] for row in enriched[1]["earned_feature_occurrences"]] == ["path.2"]
    assert all(
        row["trained_choices"] == levels[index]["trained_choices"]
        for index, row in enumerate(enriched)
    )
    assert all(
        "subpath.late" not in {item["occurrence_id"] for item in row["earned_feature_occurrences"]}
        for row in enriched
    )

    surfaces, _coverage = CharacterSheetService._complete_character_surfaces(
        {
            "members": {"Leveling_Ledger.json": {"schema_version": "Leveling_Ledger.v2", "levels": enriched}},
            "member_count": 1,
            "checksum_count": 1,
        },
        source_kind="candidate",
        finalized=False,
    )
    filtered = surfaces["leveling"]["data"]["levels"][0]
    assert filtered["earned_feature_occurrences"][0]["occurrence_id"] == "path.1a"
