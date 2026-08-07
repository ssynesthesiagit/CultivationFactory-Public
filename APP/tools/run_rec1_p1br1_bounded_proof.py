from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import Database, Settings, canonical_json, sha256_file, sha256_json
from catalog.service import CatalogService
from character_creation.choice_snapshot import materialize_choice_snapshot
from character_creation.current_fixture import complete_plan, create_fresh_project
from character_sheet.service import CharacterSheetService
from factory_authoring.command5_profile import CHARACTER_GM_PROFILE, CharacterGMCommand5Profile
from gm2_contract.adapter import _migrate_fire, migrate_package, normalize_view
from portable_character.service import PortableCharacterPackageService
from project_store.service import ProjectStore
from projector.reducer import ReducedProjectionState
from projector.service import ProjectionService
from projector.v3_bridge import reduce_v3
from security.local_identity import BoundPrincipalProvider, ProcessPrincipalProvider
from stage2 import Stage2AdvancementService
from tests.r4v_harness import provision_external_test_key
from vendor_adapter.service import FactoryAdapter


FACTORY_ZIP = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"


def _insight_choice(record_id: str, ability: str, cl: int = 4) -> dict:
    return {
        "kind": "cultivation_insight_acquisition",
        "effective_cl": cl,
        "record_id": record_id,
        "acquisition_channel": "cultivation-insight-selection",
        "parameters": {"ability": ability, "amount": 1, "repeat_index": 1},
    }


def _portable_project_export_without_inherited_non_sphere(source: Path, target: Path) -> dict:
    """Make a checksum-valid portable fixture without the out-of-scope NS1R sidecar."""
    with zipfile.ZipFile(source) as archive:
        files = {
            info.filename: archive.read(info.filename)
            for info in archive.infolist()
            if not info.is_dir()
        }
    omitted = "non-sphere-authority.json" in files
    files.pop("non-sphere-authority.json", None)
    manifest = json.loads(files["manifest.json"])
    payload = {
        name: data
        for name, data in files.items()
        if name not in {"manifest.json", "SHA256SUMS.txt"}
    }
    manifest["files"] = {
        name: hashlib.sha256(data).hexdigest()
        for name, data in sorted(payload.items())
    }
    files["manifest.json"] = canonical_json(manifest).encode("utf-8")
    files["SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(payload.items())
    ).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return {
        "source_path": str(source),
        "source_sha256": sha256_file(source),
        "path": str(target),
        "sha256": sha256_file(target),
        "omitted_members": ["non-sphere-authority.json"] if omitted else [],
        "project_identity_preserved": True,
        "scope_note": "P1BR1 does not modify CAT2/NS1R; the inherited optional Non-Sphere sidecar is omitted only from this bounded portable consumer fixture.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt: dict = {
        "schema": "Tianxia.REC1P1BR1.BoundedStage2Probe.v1",
        "status": "NOT_RUN",
        "scope": "REAL_STAGE2_CATALOG_LOCK_AND_PROPOSAL_COMPILER",
        "factory_zip_sha256": sha256_file(FACTORY_ZIP),
    }
    try:
        with tempfile.TemporaryDirectory(prefix="rec1-p1br1-stage2-") as td:
            data = Path(td) / "data"
            settings = Settings.from_env(ROOT, data)
            provision_external_test_key(data)
            db = Database(settings)
            db.migrate()
            factory = FactoryAdapter(db)
            configured = factory.configure(FACTORY_ZIP)
            catalog_report = CatalogService(db).rebuild_core(Path(configured["factory_root"]))
            created = create_fresh_project(db)
            project_id = created["project_id"]
            project = ProjectStore(db).get_project(project_id)["project"]
            plan = complete_plan(db, project_id)
            choices = plan["stage2_proposal"]["choices"]
            # The exact Qi Path milestone is ASI-or-Insight, so the bounded
            # character uses the restored Insight as its CL4 selection.
            choices[:] = [row for row in choices if row["kind"] != "ability_score_change"]
            ai_sphere_index = next(
                i for i, row in enumerate(choices)
                if row["kind"] == "ai_bootstrap_sphere_acquisition"
            )
            ai_talent_index = next(
                i for i, row in enumerate(choices)
                if row["kind"] == "ai_bootstrap_talent_acquisition"
            )
            air_sphere = dict(choices[ai_sphere_index])
            air_sphere["record_id"] = "tianxia.sphere.air"
            air_talent = dict(choices[ai_talent_index])
            air_talent["record_id"] = "TAL_AIR_FLOWING_STEP"
            fire_sphere = dict(choices[ai_sphere_index])
            fire_talent = dict(choices[ai_talent_index])
            choices[ai_sphere_index:ai_talent_index + 1] = [
                air_sphere,
                air_talent,
                fire_sphere,
                fire_talent,
            ]
            anchor = next(
                i for i, row in enumerate(choices)
                if row["kind"] == "level_advance" and row["effective_cl"] == 4
            )
            choices[anchor + 1:anchor + 1] = [
                _insight_choice("insight.legacy-qi-efficiency", "INT"),
            ]
            late_anchor = next(
                i for i, row in enumerate(choices)
                if row["kind"] == "level_advance" and row["effective_cl"] == 5
            )
            choices[late_anchor + 1:late_anchor + 1] = [
                _insight_choice("insight.expanded-dantian", "CHA", 5),
            ]
            body = plan["stage2_proposal"]
            # The bounded probe invokes the Stage 2 compiler directly, before
            # CharacterCreationExecutionService commits the Stage 1 blueprint
            # revision that the full production route normally consumes.
            body["expected_project_revision"] = project["revision"]
            stage2 = Stage2AdvancementService(
                db,
                principal_provider=BoundPrincipalProvider(ProcessPrincipalProvider().current_principal()),
            )
            proposal = stage2.create_proposal(body)
            validation = stage2.validate_proposal(proposal["proposal_id"])
            compiled_events = validation.get("compiled_events") or []
            if not validation.get("valid"):
                raise RuntimeError(f"bounded Stage 2 proposal is blocked: {validation.get('blocker_report')}")
            approval_challenge = stage2.issue_approval_challenge(proposal["proposal_id"])
            approval_challenge = approval_challenge.get("challenge") or approval_challenge
            approval = stage2.approve_proposal(
                proposal["proposal_id"],
                challenge_id=approval_challenge["challenge_id"],
                nonce=approval_challenge["nonce"],
            )
            commit_receipt = stage2.commit_proposal(proposal["proposal_id"])
            projects = ProjectStore(db)
            project = projects.get_project(project_id)["project"]
            compiled_events = projects.timeline(project_id)
            replay = projects.replay(project_id)
            required_record_ids = {
                event["subject"]["record_id"] for event in compiled_events
            }
            for event in compiled_events:
                required_record_ids.update(
                    (event.get("advancement") or {})
                    .get("calculation", {})
                    .get("outputs", {})
                    .get("granted_feature_record_ids")
                    or []
                )
            with db.connection() as conn:
                locked_records = {
                    record_id: projects._resolve_locked_record_after_proof(conn, project_id, record_id)
                    for record_id in sorted(required_record_ids)
                }
            missing_locked = sorted(key for key, value in locked_records.items() if value is None)
            if missing_locked:
                raise RuntimeError(f"missing locked records: {missing_locked}")
            snapshot = materialize_choice_snapshot(project)
            reduced = reduce_v3(
                root_dir=ROOT,
                registry=stage2.hf1.registry,
                project=project,
                events=compiled_events,
                locked_records=locked_records,
                choice_snapshot=snapshot,
                state_type=ReducedProjectionState,
            )
            projection_service = ProjectionService(db, factory_root=Path(configured["factory_root"]))
            projection_build = projection_service.build(project_id, choice_snapshot=snapshot)
            projection_status = projection_service.status(project_id)
            sheet_response = CharacterSheetService(db).sheet(project_id)
            command5 = CharacterGMCommand5Profile(db, factory_root=Path(configured["factory_root"]))
            command5_profile, command5_profile_sha = command5.select_profile(CHARACTER_GM_PROFILE)
            workspace_root = data / "bounded-command5-workspace"
            (workspace_root / "Command_4").mkdir(parents=True, exist_ok=True)
            workspace_files = {
                "Command_4/Training_Sources.json": {"training_sources": []},
                "Command_4/Composite_Playbooks.json": {"playbooks": []},
                "Command_4/Dao_I_Ching_GM_Authoring.json": {
                    "classification": "OWNER_RATIFIED_GM_AUTHORING",
                    "dao": {"mechanical_effects": []},
                    "i_ching": {"mechanical_effects": []},
                },
                "Command_4/Descriptive_AI_Behavior.json": {
                    "not_executable_controller_policy": True,
                    "controller_policy_registered": False,
                },
            }
            for relative, value in workspace_files.items():
                path = workspace_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(canonical_json(value), encoding="utf-8", newline="\n")
            workspace_manifest = {
                "workspace_id": "REC1-P1BR1-bounded-command5",
                "project_id": project_id,
                "project_revision": project["revision"],
                "files": sorted(workspace_files),
            }
            workspace_manifest_path = workspace_root / "Workspace_Manifest.json"
            workspace_manifest_path.write_text(canonical_json(workspace_manifest), encoding="utf-8", newline="\n")
            workspace_status = {
                "workspace_id": workspace_manifest["workspace_id"],
                "workspace_sha256": sha256_json(workspace_manifest),
                "manifest_sha256": sha256_file(workspace_manifest_path),
            }
            command4 = {
                "schema_version": "TianxiaFoundry.CharacterGMCommand4ProfileValidation.v1",
                "status": "CHARACTER_GM_COMMAND_4_PROFILE_PASS",
                "valid": True,
                "project_id": project_id,
                "project_revision": project["revision"],
            }
            gm_model, gm_view, gm_tabs = command5._models(
                project=project,
                sheet_response=sheet_response,
                workspace_root=workspace_root,
                workspace_status=workspace_status,
                profile=command5_profile,
                profile_contract_sha=command5_profile_sha,
                command4=command4,
            )
            command5_audit = command5._validate_models(gm_model, gm_view, gm_tabs)
            gm2_selected = {
                "model": gm_model,
                "path": "Tianxia_GM_Character_Model_v1.json",
                "manifest": {},
                "profile": "fire_qi_c2c1_v1",
                "model_sha256": sha256_json(gm_model),
                "runtime_package": False,
            }
            gm2_model, gm2_mappings, gm2_omissions = _migrate_fire(gm2_selected, sha256_json(gm_model))
            gm2_view = normalize_view(gm2_model)
            candidate_zip = data / "command5-candidate.zip"
            candidate_members = {
                "Tianxia_GM_Character_Model_v1.json": canonical_json(gm_model).encode("utf-8"),
                "Tianxia_GM_Character_View_Model_v2.json": canonical_json(gm_view).encode("utf-8"),
                "PACKAGE_MANIFEST.json": canonical_json({
                    "schema_version": "TianxiaFoundry.CharacterGMCandidate.v1",
                    "project_id": project_id,
                    "canonical_models": ["Tianxia_GM_Character_Model_v1.json"],
                    "derived_display_models": ["Tianxia_GM_Character_View_Model_v2.json"],
                }).encode("utf-8"),
            }
            candidate_members["SHA256SUMS.txt"] = "".join(
                f"{hashlib.sha256(member_data).hexdigest()}  {name}\n"
                for name, member_data in sorted(candidate_members.items())
            ).encode("utf-8")
            with zipfile.ZipFile(candidate_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for name, member_data in sorted(candidate_members.items()):
                    info = zipfile.ZipInfo(name)
                    info.date_time = (1980, 1, 1, 0, 0, 0)
                    info.external_attr = 0o644 << 16
                    archive.writestr(info, member_data)
            export_receipt = projects.export_project(project_id)
            portable_project_export = _portable_project_export_without_inherited_non_sphere(
                Path(export_receipt["path"]),
                data / "portable-project-export-p1br1.tianxia-project.zip",
            )
            portable_zip = data / "portable-character.zip"
            projection_artifacts = {
                name: projection_service.artifact(project_id, name)
                for name in (
                    "Character_Master_Ledger.json",
                    "Rules_Selection_Packets.json",
                    "Projection_Provenance_Map.json",
                    "Projection_Coverage_Report.json",
                    "Projection_Diagnostics.json",
                )
            }
            portable_audit = PortableCharacterPackageService.build(
                candidate_zip=candidate_zip,
                project_export=Path(portable_project_export["path"]),
                output_zip=portable_zip,
                consumer_identity={"consumer": "REC1-P1BR1-bounded", "version": "1.0"},
                projection_artifacts=projection_artifacts,
                owner_sheet_path=Path(sheet_response["sheet_artifact"]["path"]),
            )
            gm2_result = migrate_package(portable_zip)
            receipt.update({
                "status": "PASS" if validation.get("valid") else "BLOCKED",
                "project_id": project_id,
                "project_revision": project["revision"],
                "catalog_build_id": catalog_report.get("catalog_build_id"),
                "proposal_id": proposal["proposal_id"],
                "proposal_hash": proposal.get("proposal_hash"),
                "validation_hash": validation.get("validation_hash"),
                "approval": {
                    "status": approval.get("status"),
                    "principal_id": approval.get("approved_principal_id"),
                    "approval_evidence_id": approval.get("approval_evidence_id"),
                },
                "commit": {
                    "status": commit_receipt.get("status") or "COMMITTED",
                    "commit_id": commit_receipt.get("commit_id"),
                    "event_count": len(compiled_events),
                    "state_hash": (commit_receipt.get("replay") or {}).get("state_hash"),
                },
                "compiled_event_count": len(compiled_events),
                "compiled_event_kinds": [
                    event["advancement"]["kind"] for event in validation.get("compiled_events") or []
                ],
                "insight_occurrences": [
                    event["advancement"]["calculation"]["outputs"].get("insight_occurrence")
                    for event in validation.get("compiled_events") or []
                    if event["advancement"]["kind"] == "cultivation_insight_acquisition"
                ],
                "sphere_events": [
                    event["subject"]["record_id"]
                    for event in validation.get("compiled_events") or []
                    if "sphere" in event["advancement"]["kind"]
                ],
                "blockers": validation.get("blocker_report", {}).get("blockers", []),
                "event_head_hash": (validation.get("compiled_events") or [{}])[-1].get("event_hash"),
                "persisted_event_head_hash": (compiled_events or [{}])[-1].get("event_hash"),
                "replay": {
                    "event_count": replay.get("event_count"),
                    "state_hash": replay.get("state_hash"),
                    "latest_event_hash": replay.get("latest_event_hash"),
                },
                "source_lock_hash": project["content_lock"]["lock_hash"],
                "projection_service": {
                    "status": projection_status.get("status"),
                    "projection_id": projection_status.get("projection_id"),
                    "eligible_for_command5": projection_status.get("eligible_for_command5"),
                    "build_status": projection_build.get("status"),
                    "artifact_count": len(projection_status.get("artifacts") or []),
                },
                "character_sheet_service": {
                    "build_status": sheet_response.get("build_status"),
                    "advancement": (sheet_response.get("readiness") or {}).get("advancement"),
                    "character_sheet": (sheet_response.get("readiness") or {}).get("character_sheet"),
                    "sheet_sha256": (sheet_response.get("sheet_artifact") or {}).get("sha256"),
                    "sphere_component_count": len(((sheet_response.get("owner_character_sheet") or {}).get("spheres_and_talents") or {}).get("automatic_sphere_components") or []),
                    "insight_occurrence_count": len(((sheet_response.get("owner_character_sheet") or {}).get("spheres_and_talents") or {}).get("cultivation_insight_occurrences") or []),
                },
                "command5": {
                    "audit_status": command5_audit.get("status"),
                    "model_schema_valid": command5_audit.get("valid"),
                    "gm_component_count": len(((gm_model.get("spheres_talents") or {}).get("automatic_sphere_components") or [])),
                    "gm_insight_occurrence_count": len(((gm_model.get("paths_subpaths_insights") or {}).get("cultivation_insight_occurrences") or [])),
                    "sphere_component_ids_equal_sheet": sorted(
                        component.get("component_id")
                        for component in ((gm_model.get("spheres_talents") or {}).get("automatic_sphere_components") or [])
                    ) == sorted(
                        component.get("component_id")
                        for component in (((sheet_response.get("owner_character_sheet") or {}).get("spheres_and_talents") or {}).get("automatic_sphere_components") or [])
                    ),
                    "insight_occurrences_equal_sheet": ((gm_model.get("paths_subpaths_insights") or {}).get("cultivation_insight_occurrences") or []) == (((sheet_response.get("owner_character_sheet") or {}).get("spheres_and_talents") or {}).get("cultivation_insight_occurrences") or []),
                },
                "gm2": {
                    "direct_component_count": len(gm2_model.get("automatic_sphere_components") or []),
                    "direct_insight_count": len(gm2_model.get("insights") or []),
                    "direct_insight_occurrence_count": len(gm2_model.get("cultivation_insight_occurrences") or []),
                    "normalized_view_component_count": len((gm2_view.get("sections") or {}).get("automatic_sphere_components") or []),
                    "normalized_view_insight_count": len((gm2_view.get("sections") or {}).get("insights") or []),
                    "omission_count": len(gm2_omissions),
                },
                "portable": {
                    "project_export_fixture": portable_project_export,
                    "audit_valid": portable_audit.get("valid"),
                    "entry_count": portable_audit.get("entry_count"),
                    "checksum_count": portable_audit.get("checksum_count"),
                    "migration_status": gm2_result.get("status"),
                    "migration_component_count": len((gm2_result.get("model") or {}).get("automatic_sphere_components") or []),
                    "migration_insight_occurrence_count": len((gm2_result.get("model") or {}).get("cultivation_insight_occurrences") or []),
                    "normalized_view_component_count": len(((gm2_result.get("normalized_view") or {}).get("sections") or {}).get("automatic_sphere_components") or []),
                    "normalized_view_insight_count": len(((gm2_result.get("normalized_view") or {}).get("sections") or {}).get("insights") or []),
                },
                "projection_ledger_sha256": sha256_json(reduced.ledger),
                "projection_packets_sha256": sha256_json(reduced.rules_selection_packets),
                "projection_readiness": reduced.ledger.get("readiness"),
                "projection_sphere_ids": [
                    row["sphere_id"] for row in reduced.ledger.get("spheres") or []
                ],
                "projection_insight_ids": [
                    row["insight_id"] for row in reduced.ledger.get("insights") or []
                ],
                "projection_component_count": len(reduced.ledger.get("automatic_sphere_components") or []),
                "projection_component_receipt_count": len(reduced.ledger.get("automatic_sphere_component_receipts") or []),
                "projection_component_receipt_component_counts": [
                    {
                        "parent_sphere_id": row.get("parent_sphere_id"),
                        "component_count": len(row.get("components") or []),
                        "component_ids": [component.get("component_id") for component in row.get("components") or []],
                    }
                    for row in reduced.ledger.get("automatic_sphere_component_receipts") or []
                ],
                "stage2_sphere_packet_diagnostics": [
                    {
                        "sphere_id": event["subject"]["record_id"],
                        "component_count": len(
                            (((event.get("advancement") or {}).get("calculation") or {}).get("outputs") or {})
                            .get("automatic_component_authority", {})
                            .get("components", [])
                        ),
                        "component_ids": [
                            component.get("component_id")
                            for component in (
                                (((event.get("advancement") or {}).get("calculation") or {}).get("outputs") or {})
                                .get("automatic_component_authority", {})
                                .get("components", [])
                            )
                        ],
                    }
                    for event in compiled_events
                    if "sphere" in event["advancement"]["kind"]
                ],
            })
            args.output.write_text(canonical_json(receipt), encoding="utf-8", newline="\n")
    except Exception as exc:
        receipt.update({"status": "ERROR", "error_type": type(exc).__name__, "error": str(exc)})
        args.output.write_text(canonical_json(receipt), encoding="utf-8", newline="\n")
        raise
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
