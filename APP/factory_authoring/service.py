from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core import Database, FoundryError, canonical_json, sha256_file, sha256_json
from character_sheet.service import CharacterSheetService
from projector.service import ProjectionService
from project_store.service import ProjectStore

_AUTHORING_PROFILE = "Tianxia_Fire_Qi_GM_Tactical_Authoring_Profile_R1.json"
_WORKSPACE_PROFILE = "Tianxia_C2B2_Factory_Command_1_4_Workspace_Profile_R1.json"
_STATUS = "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8", newline="\n")


class FactoryAuthoringWorkspaceService:
    """Build the bounded C2B.2 GM-authoring workspace through Command 1–4 inputs.

    This service reuses canonical project, projection, and Character Sheet read
    models. It does not run or replace the pinned Factory compiler, and it never
    claims the legacy executable Command 4, Command 5, or Command 6 seals.
    """

    def __init__(self, db: Database):
        self.db = db
        self.projects = ProjectStore(db)
        self.projections = ProjectionService(db)
        self.sheets = CharacterSheetService(db)

    @property
    def _contracts_dir(self) -> Path:
        return Path(__file__).resolve().parent / "contracts"

    @staticmethod
    def _verify_sealed_json(path: Path, *, expected_schema: str, error_prefix: str) -> tuple[dict[str, Any], str]:
        if not path.is_file():
            raise FoundryError(f"{error_prefix}_MISSING", f"Required sealed contract is missing: {path.name}")
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if not sidecar.is_file():
            raise FoundryError(f"{error_prefix}_SIDECAR_MISSING", f"Required detached checksum is missing: {sidecar.name}")
        try:
            digest, declared = sidecar.read_text(encoding="utf-8").strip().split(None, 1)
        except ValueError as exc:
            raise FoundryError(f"{error_prefix}_SIDECAR_INVALID", "The detached checksum sidecar is malformed.") from exc
        declared = declared.strip().lstrip("*")
        actual = sha256_file(path)
        if declared != path.name or digest.lower() != actual:
            raise FoundryError(
                f"{error_prefix}_STALE",
                "The sealed contract does not match its detached checksum.",
                details={"expected": digest.lower(), "actual": actual, "declared_name": declared},
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != expected_schema:
            raise FoundryError(
                f"{error_prefix}_SCHEMA_UNSUPPORTED",
                "The sealed contract schema is unsupported.",
                details={"expected": expected_schema, "actual": payload.get("schema_version")},
            )
        internal = payload.get("seal_sha256")
        unsigned = dict(payload); unsigned.pop("seal_sha256", None)
        calculated = sha256_json(unsigned)
        if internal != calculated:
            raise FoundryError(
                f"{error_prefix}_INTERNAL_SEAL_INVALID",
                "The sealed contract internal hash is invalid.",
                details={"expected": internal, "actual": calculated},
            )
        return payload, actual

    def _authoring_profile(self) -> tuple[dict[str, Any], str]:
        return self._verify_sealed_json(
            self._contracts_dir / _AUTHORING_PROFILE,
            expected_schema="TianxiaFoundry.GMTacticalAuthoringProfile.v1",
            error_prefix="GM_AUTHORING_PROFILE",
        )

    def _workspace_profile(self) -> tuple[dict[str, Any], str]:
        return self._verify_sealed_json(
            self._contracts_dir / _WORKSPACE_PROFILE,
            expected_schema="TianxiaFoundry.FactoryAuthoringWorkspaceProfile.v1",
            error_prefix="FACTORY_WORKSPACE_PROFILE",
        )

    @classmethod
    def _project_authoring_profile(
        cls,
        snapshot: dict[str, Any],
        sealed_profile: dict[str, Any],
        sealed_profile_sha: str,
        workspace_profile: dict[str, Any],
        workspace_profile_sha: str,
    ) -> tuple[dict[str, Any], str, dict[str, Any], str]:
        cards = cls._card_index(snapshot)
        selected_ids = set(cards)
        sealed_ids = set(workspace_profile.get("required_training_source_coverage") or [])
        if sealed_ids == selected_ids:
            return sealed_profile, sealed_profile_sha, workspace_profile, workspace_profile_sha

        grouped: dict[str, list[str]] = {}
        for record_id, card in cards.items():
            grouped.setdefault(str(card.get("section") or "selected_records"), []).append(record_id)
        training_sources = []
        for section in sorted(grouped):
            record_ids = sorted(grouped[section])
            training_sources.append({
                "source_id": f"gm.training.project.{sha256_json(record_ids)[:16]}",
                "name": f"{section.replace('_', ' ').title()} selected-record training",
                "source_category": "PROJECT_SELECTED_RECORD_TRAINING",
                "factory_source_type": "other",
                "classification": "GM_GUIDANCE_ONLY",
                "record_ids": record_ids,
                "summary": "Groups only records already selected in the revision-bound project snapshot; grants no mechanics or acquisitions.",
            })
        display_ids = sorted(
            record_id for record_id, card in cards.items()
            if (card.get("capabilities") or {}).get("combat_execution") != "NOT_APPLICABLE"
        ) or sorted(selected_ids)
        thematic_ids = sorted(
            record_id for record_id, card in cards.items()
            if str(card.get("section") or "") in {"path_subpath", "spheres", "talents", "path_features"}
        ) or sorted(selected_ids)
        unsigned = {
            "schema_version": "TianxiaFoundry.GMTacticalAuthoringProfile.v1",
            "profile_id": f"Tianxia_Project_Derived_GM_Tactical_Authoring_{sha256_json(sorted(selected_ids))[:16]}",
            "version": "1.0.0",
            "authority_classification": "OWNER_RATIFIED_GM_AUTHORING",
            "global_labels": ["GM_GUIDANCE_ONLY", "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY"],
            "scope": {
                "project_id_hardcoded": False,
                "event_id_hardcoded": False,
                "mechanical_authority": False,
                "execution_authority": False,
                "reusable_for_same_records": True,
                "supported_record_slice": "Exact records in the revision-bound typed project choice snapshot.",
            },
            "prohibitions": {
                "alter_advancement": True,
                "create_action_definitions": True,
                "create_method_manual_or_equipment": True,
                "invent_mechanics": True,
                "register_ai_policy": True,
            },
            "training_sources": training_sources,
            "composite_playbooks": [{
                "playbook_id": f"gm.playbook.project.display.{sha256_json(display_ids)[:16]}",
                "display_name": "Selected Display Options",
                "classification": "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
                "capability_status": "GM_GUIDANCE_ONLY",
                "record_ids": display_ids,
                "tactical_goal": "Help the GM locate the character's selected display records.",
                "grouping_note": "This is a display grouping only and defines no sequence, combination, or legality.",
                "resource_awareness_note": "Consult later typed execution authority before resolving costs or effects.",
                "fallback_note": "If typed legality is unavailable, do not invent mechanics.",
            }],
            "dao_i_ching": {
                "classification": "OWNER_RATIFIED_GM_AUTHORING",
                "dao": {
                    "authoring_id": f"gm.dao.project.{sha256_json(thematic_ids)[:16]}",
                    "display_name": "Project-Derived Cultivation Theme",
                    "core_theme": "Portray the character through the exact selected path, spheres, talents, and features.",
                    "principles": ["Respect selected authority", "Do not infer unselected mechanics"],
                    "strengths": [], "risks": [],
                    "roleplay_expression": "Use selected record descriptions as portrayal context only.",
                    "tactical_expression": "This guidance grants no bonus, action, or effect.",
                    "gm_usage_notes": "Interpretive display guidance only.",
                    "relevant_record_ids": thematic_ids,
                    "mechanical_effects": [],
                },
                "i_ching": {
                    "authoring_id": f"gm.iching.project.{sha256_json(thematic_ids)[:16]}",
                    "display_name": "Project-Derived Change Theme",
                    "core_theme": "Frame change through the character's exact selected record authority.",
                    "principles": ["Preserve canonical selections", "Keep interpretation non-mechanical"],
                    "strengths": [], "risks": [],
                    "roleplay_expression": "Use the selected record set as narrative context.",
                    "tactical_expression": "This guidance grants no bonus, action, or effect.",
                    "gm_usage_notes": "Interpretive display guidance only.",
                    "relevant_record_ids": thematic_ids,
                    "mechanical_effects": [],
                },
            },
            "ai_behavior": {
                "profile_id": f"gm.ai.project.display.{sha256_json(display_ids)[:16]}",
                "role": "Descriptive assistant for exact selected records",
                "classification": "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY",
                "record_ids": display_ids,
                "preferred_patterns": ["Reference exact selected records without inventing mechanics."],
                "capability_dependencies": ["typed combat execution definitions", "legal candidate generation"],
                "fallback_behavior": "When typed legality is unavailable, choose no invented mechanic.",
                "not_executable_controller_policy": True,
                "prohibited_invented_mechanic_behavior": ["Do not invent values, targets, effects, costs, or timing."],
            },
        }
        profile = {**unsigned, "seal_sha256": sha256_json(unsigned)}
        dynamic_workspace = deepcopy(workspace_profile)
        dynamic_workspace["profile_id"] = f"{workspace_profile['profile_id']}.project-derived"
        dynamic_workspace["required_training_source_coverage"] = sorted(selected_ids)
        workspace_unsigned = {key: value for key, value in dynamic_workspace.items() if key != "seal_sha256"}
        dynamic_workspace["seal_sha256"] = sha256_json(workspace_unsigned)
        return profile, sha256_json(profile), dynamic_workspace, sha256_json(dynamic_workspace)

    def _root(self, project_id: str) -> Path:
        return self.db.settings.data_dir / "factory_workspaces" / project_id

    def _pointer(self, project_id: str) -> Path:
        return self._root(project_id) / "current.json"

    @staticmethod
    def _card_index(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
        cards = [
            row for rows in (snapshot.get("selected_record_sections") or {}).values()
            for row in (rows or []) if isinstance(row, dict)
        ]
        return {str(row.get("record_id")): row for row in cards if row.get("record_id")}

    @staticmethod
    def _reject_executable_claims(value: Any, *, path: str = "$") -> None:
        forbidden_keys = {
            "action_definition", "action_intent", "attack_roll", "damage_dice", "save_dc",
            "target_scoring", "decision_weights", "legal_candidate", "controller_policy",
            "range_ft", "area_geometry", "condition_definition", "resource_cost",
        }
        if isinstance(value, dict):
            for key, item in value.items():
                if key in forbidden_keys:
                    raise FoundryError(
                        "GM_AUTHORING_EXECUTABLE_CLAIM_FORBIDDEN",
                        "GM authoring may not contain executable combat fields.",
                        details={"path": f"{path}/{key}"},
                    )
                FactoryAuthoringWorkspaceService._reject_executable_claims(item, path=f"{path}/{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                FactoryAuthoringWorkspaceService._reject_executable_claims(item, path=f"{path}/{index}")

    @classmethod
    def _validate_profile(
        cls,
        profile: dict[str, Any],
        workspace_profile: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> None:
        diagnostics: list[dict[str, Any]] = []
        if profile.get("authority_classification") != "OWNER_RATIFIED_GM_AUTHORING":
            diagnostics.append({"code": "GM_AUTHORING_AUTHORITY_CLASS_INVALID"})
        selected = cls._card_index(snapshot)
        selected_ids = set(selected)

        training = profile.get("training_sources") or []
        source_ids = [row.get("source_id") for row in training if isinstance(row, dict)]
        if len(source_ids) != len(set(source_ids)):
            diagnostics.append({"code": "GM_AUTHORING_TRAINING_SOURCE_DUPLICATE"})
        covered: list[str] = []
        for row in training:
            if not isinstance(row, dict):
                diagnostics.append({"code": "GM_AUTHORING_TRAINING_SOURCE_INVALID"}); continue
            if row.get("classification") != "GM_GUIDANCE_ONLY" or row.get("factory_source_type") != "other":
                diagnostics.append({"code": "GM_AUTHORING_TRAINING_SOURCE_CLASS_INVALID", "source_id": row.get("source_id")})
            records = [str(value) for value in row.get("record_ids") or []]
            if not records or not row.get("summary"):
                diagnostics.append({"code": "GM_AUTHORING_TRAINING_SOURCE_UNPROVEN", "source_id": row.get("source_id")})
            unknown = sorted(set(records) - selected_ids)
            if unknown:
                diagnostics.append({"code": "GM_AUTHORING_TRAINING_SOURCE_RECORD_UNKNOWN", "source_id": row.get("source_id"), "records": unknown})
            covered.extend(records)
        required_coverage = set(workspace_profile.get("required_training_source_coverage") or [])
        if set(covered) != required_coverage or len(covered) != len(set(covered)):
            diagnostics.append({
                "code": "GM_AUTHORING_TRAINING_SOURCE_COVERAGE_INVALID",
                "missing": sorted(required_coverage - set(covered)),
                "extra": sorted(set(covered) - required_coverage),
                "duplicates": sorted({value for value in covered if covered.count(value) > 1}),
            })

        playbooks = profile.get("composite_playbooks") or []
        playbook_ids = [row.get("playbook_id") for row in playbooks if isinstance(row, dict)]
        if not 1 <= len(playbooks) <= 3:
            diagnostics.append({"code": "GM_AUTHORING_COMPOSITE_COUNT_INVALID"})
        if len(playbook_ids) != len(set(playbook_ids)):
            diagnostics.append({"code": "GM_AUTHORING_COMPOSITE_ID_DUPLICATE"})
        for row in playbooks:
            if not isinstance(row, dict):
                diagnostics.append({"code": "GM_AUTHORING_COMPOSITE_INVALID"}); continue
            if row.get("classification") != "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY" or row.get("capability_status") != "GM_GUIDANCE_ONLY":
                diagnostics.append({"code": "GM_AUTHORING_COMPOSITE_EXECUTION_CLASS_INVALID", "playbook_id": row.get("playbook_id")})
            unknown = sorted(set(row.get("record_ids") or []) - selected_ids)
            if unknown:
                diagnostics.append({"code": "GM_AUTHORING_COMPOSITE_RECORD_UNKNOWN", "playbook_id": row.get("playbook_id"), "records": unknown})
            combined = " ".join(str(row.get(key) or "") for key in ("tactical_goal", "grouping_note", "resource_awareness_note", "fallback_note")).casefold()
            if any(token in combined for token in ("is a guaranteed sequence", "mechanically combines", "legal action script", "actionintent")):
                diagnostics.append({"code": "GM_AUTHORING_UNSUPPORTED_COMBO_CLAIM", "playbook_id": row.get("playbook_id")})

        dao = (profile.get("dao_i_ching") or {}).get("dao")
        iching = (profile.get("dao_i_ching") or {}).get("i_ching")
        legacy_profile = profile.get("profile_id") == "Tianxia_Fire_Qi_GM_Tactical_Authoring_Profile_R1"
        if not isinstance(dao, dict) or (legacy_profile and dao.get("authoring_id") != "gm.dao.refinement_through_controlled_flame") or not dao.get("authoring_id"):
            diagnostics.append({"code": "GM_AUTHORING_DAO_REQUIRED"})
        if not isinstance(iching, dict) or (legacy_profile and iching.get("authoring_id") != "gm.iching.hexagram_30_li") or not iching.get("authoring_id"):
            diagnostics.append({"code": "GM_AUTHORING_ICHING_REQUIRED"})
        for kind, row in (("dao", dao), ("i_ching", iching)):
            if isinstance(row, dict) and row.get("mechanical_effects") not in ([], None):
                diagnostics.append({"code": "GM_AUTHORING_THEME_MECHANICAL_EFFECT_FORBIDDEN", "kind": kind})
            if isinstance(row, dict):
                unknown = sorted(set(row.get("relevant_record_ids") or []) - selected_ids)
                if unknown:
                    diagnostics.append({"code": "GM_AUTHORING_THEME_RECORD_UNKNOWN", "kind": kind, "records": unknown})

        ai = profile.get("ai_behavior")
        if not isinstance(ai, dict) or ai.get("not_executable_controller_policy") is not True:
            diagnostics.append({"code": "GM_AUTHORING_AI_PROFILE_REQUIRED"})
        elif ai.get("classification") != "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY":
            diagnostics.append({"code": "GM_AUTHORING_AI_PROFILE_CLASS_INVALID"})
        elif sorted(set(ai.get("record_ids") or []) - selected_ids):
            diagnostics.append({"code": "GM_AUTHORING_AI_PROFILE_RECORD_UNKNOWN"})

        try:
            cls._reject_executable_claims(profile)
        except FoundryError as exc:
            diagnostics.append(exc.to_dict()["error"])
        serialized = canonical_json(profile).casefold()
        for forbidden in workspace_profile.get("forbidden_promotions") or []:
            if str(forbidden).casefold() in serialized:
                diagnostics.append({"code": "GM_AUTHORING_FALSE_READINESS_PROMOTION", "value": forbidden})
        if diagnostics:
            raise FoundryError(
                "GM_AUTHORING_PROFILE_BLOCKED",
                "The bounded GM tactical authoring profile failed validation.",
                details={"diagnostics": diagnostics},
            )

    @staticmethod
    def _portable_identity(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: FactoryAuthoringWorkspaceService._portable_identity(item) for key, item in value.items() if key not in {"path", "workspace_path"}}
        if isinstance(value, list):
            return [FactoryAuthoringWorkspaceService._portable_identity(item) for item in value]
        return deepcopy(value)

    @staticmethod
    def _bound_records(record_ids: list[str], cards: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for record_id in record_ids:
            card = cards[record_id]
            rows.append({
                "record_id": record_id,
                "display_name": card.get("display_name"),
                "record_hash": card.get("record_hash"),
                "source_packet_ids": sorted(card.get("source_packet_ids") or []),
                "source": deepcopy(card.get("source")),
                "capabilities": deepcopy(card.get("capabilities")),
                "display_only_not_execution_authority": bool(card.get("display_only_not_execution_authority")),
            })
        return rows

    @staticmethod
    def _validation(status: str, *, valid: bool, diagnostics: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
        return {"schema_version": "TianxiaFoundry.FactoryWorkspaceValidation.v1", "status": status, "valid": valid, "diagnostics": diagnostics or [], **extra}

    def _documents(
        self,
        *,
        project: dict[str, Any],
        sheet_response: dict[str, Any],
        profile: dict[str, Any],
        profile_sha: str,
        workspace_profile: dict[str, Any],
        workspace_profile_sha: str,
        projection_artifacts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        snapshot = sheet_response["owner_character_sheet"]
        cards = self._card_index(snapshot)
        identity = snapshot["identity"]
        ledger = deepcopy(projection_artifacts["Character_Master_Ledger.json"])
        packets = deepcopy(projection_artifacts["Rules_Selection_Packets.json"])
        projection_status = sheet_response["provenance"]["advancement_projection"]["projection"]

        training_sources = []
        for row in profile["training_sources"]:
            records = self._bound_records(row["record_ids"], cards)
            training_sources.append({
                **deepcopy(row),
                "allocation_id": f"allocation:{row['source_id']}",
                "type": row["factory_source_type"],
                "gained_at_cl": min((cards[r].get("acquisition_cl") or 0) for r in row["record_ids"]),
                "contents": {"record_ids": list(row["record_ids"]), "record_bindings": records, "recorded_arts": [], "methods": [], "warnings": ["GM guidance only; grants no additional mechanics."], "recipes": [], "theory": [], "false_routes": []},
                "restrictions": ["Does not create acquisitions or executable mechanics."],
                "risks": ["Do not infer teachers, sects, manuals, locations, or historical events."],
                "mechanics_granted": list(row["record_ids"]),
                "source_packet_ids": sorted({packet for record in records for packet in record["source_packet_ids"]}),
                "authority": {"profile_id": profile["profile_id"], "profile_sha256": profile_sha, "classification": row["classification"]},
            })

        playbooks = []
        for row in profile["composite_playbooks"]:
            playbooks.append({
                **deepcopy(row),
                "record_bindings": self._bound_records(row["record_ids"], cards),
                "provenance": {"profile_id": profile["profile_id"], "profile_sha256": profile_sha, "classification": row["classification"]},
                "not_a_combat_macro": True,
                "not_an_action_intent": True,
            })

        dao_i_ching = deepcopy(profile["dao_i_ching"])
        dao_i_ching["profile_identity"] = {"profile_id": profile["profile_id"], "profile_sha256": profile_sha}
        ai_behavior = deepcopy(profile["ai_behavior"])
        ai_behavior["profile_identity"] = {"profile_id": profile["profile_id"], "profile_sha256": profile_sha}

        capability_rows = deepcopy(snapshot["capability_status"]["records"])
        for row in capability_rows:
            row["gm_display"] = "SUPPORTED"
            row["combat_execution_preserved"] = row.get("combat_execution")
            row["ai_policy_preserved"] = row.get("ai_policy")
        selected_method = deepcopy(snapshot.get("method") or {})
        method_audit = (
            selected_method
            if selected_method.get("state") == "acquired" and selected_method.get("record_id")
            else deepcopy((snapshot.get("explicit_none_systems") or {}).get("method") or {"state": "none", "source_backed": True})
        )
        selected_foundation = deepcopy(snapshot.get("foundation") or {})
        foundation_audit = (
            selected_foundation
            if selected_foundation.get("state") == "acquired" and selected_foundation.get("record_id")
            else deepcopy((snapshot.get("explicit_none_systems") or {}).get("foundation") or {"state": "none", "source_backed": True})
        )

        command1 = {
            "Build_Request.json": {"schema_version": "TianxiaFoundry.C2B2BuildRequest.v1", "project_id": project["project_id"], "project_revision": project["revision"], "character_name": identity["display_name"], "target_cl": identity["cultivation_level"], "target_realm": identity["realm"], "requested_boundary": "GM tactical authoring and Command 1–4 workspace inputs only", "command5_authorized": False, "command6_authorized": False},
            "Inspiration_Source_Evidence.json": {"schema_version": "TianxiaFoundry.C2B2SourceEvidence.v1", "canonical_project": self._portable_identity(sheet_response["provenance"]["advancement_projection"]), "owner_sheet": self._portable_identity(sheet_response["sheet_artifact"]), "selected_record_bindings": self._bound_records(sorted(cards), cards), "gm_authoring_profile": {"profile_id": profile["profile_id"], "sha256": profile_sha}},
            "Character_Blueprint.json": {"schema_version": "TianxiaFoundry.C2B2CharacterBlueprint.v1", "identity": deepcopy(identity), "background_origin": deepcopy(snapshot["background_and_origin"]), "path_subpath": deepcopy(snapshot["path_and_subpath"]), "sphere_talent_ids": deepcopy(snapshot["spheres_and_talents"]), "authority":"canonical advancement and owner locks"},
            "Selection_Plan.json": {"schema_version": "TianxiaFoundry.C2B2SelectionPlan.v1", "owner_choice_locks": deepcopy(snapshot["advancement_history"]["owner_choice_locks"]), "selected_record_ids": sorted(cards), "gm_authoring_additions": ["training sources", "non-executable composite playbooks", "Dao/I Ching", "descriptive AI behavior"]},
            "Surface_Coverage_Plan.json": {"schema_version": "TianxiaFoundry.C2B2SurfaceCoveragePlan.v1", "capability_rows": capability_rows, "gm_display": "SUPPORTED", "combat_execution": "NOT_ATTEMPTED_OR_UNSUPPORTED", "pending_execution_surfaces": deepcopy(snapshot["capability_status"]["pending_execution_surfaces"])},
            "Open_Questions.json": {"schema_version": "TianxiaFoundry.C2B2OpenQuestions.v1", "resolved_for_c2b2": [], "deferred": workspace_profile["later_combat_execution_fields"], "blocking_for_c2b2": []},
            "Command_1_Audit.md": "# Command 1 Audit\n\nStatus: COMMAND_1_BLUEPRINT_LOCKED\n\nCanonical project, owner locks, selected records, and C2B.2 scope are locked. No mechanic or advancement history was changed.\n",
        }
        command2 = {
            "Rules_Selection_Packets.json": packets,
            "Canonical_Advancement_Ledger.json": deepcopy(ledger["advancement"]),
            "Canonical_Stats_Resource_Block.json": {"schema_version": "TianxiaFoundry.C2B2StatsResourceBlock.v1", "character": deepcopy(ledger["character"]), "core_stats": deepcopy(ledger["core_stats"]), "resources": deepcopy(ledger["resources"]), "typed_none": deepcopy(ledger["typed_none"])},
            "Advancement_Reconciliation.json": {"schema_version": "TianxiaFoundry.C2B2AdvancementReconciliation.v1", "status": "COMMAND_2_ADVANCEMENT_LEDGER_SEALED", "project_revision": project["revision"], "event_count": ledger["advancement"]["event_count"], "event_head_hash": ledger["advancement"]["event_head_hash"], "projection_id": projection_status.get("projection_id"), "canonical_preserved": True},
            "Command_2_Audit.md": "# Command 2 Audit\n\nStatus: COMMAND_2_ADVANCEMENT_LEDGER_SEALED\n\nThe accepted C2A-R.1 advancement projection is reused byte-for-byte.\n",
        }
        command3 = {
            "Subsystem_Completion_Ledger.json": {"schema_version": "TianxiaFoundry.C2B2SubsystemCompletion.v1", "status":"COMMAND_3_CHASSIS_COMPLETE", "advancement":"ADVANCEMENT_READY", "character_sheet":"CHARACTER_SHEET_READY", "gm_authoring":"COMPLETE_AS_WORKSPACE_INPUT", "combat_execution":"NOT_ATTEMPTED", "typed_none": deepcopy(snapshot["explicit_none_systems"])},
            "Feature_Execution_Coverage_Plan.json": {"schema_version":"TianxiaFoundry.C2B2FeatureCoveragePlan.v1", "records": capability_rows, "display_descriptions_are_not_execution_authority": True, "later_execution_surfaces": workspace_profile["later_combat_execution_fields"]},
            "Foundation_Lifecycle_Audit.json": {"schema_version":"TianxiaFoundry.C2B2TypedNoneAudit.v1", "system":"foundation", "result": foundation_audit},
            "Background_Origin_Method_Audit.json": {"schema_version":"TianxiaFoundry.C2B2BackgroundOriginMethodAudit.v1", "background_origin":deepcopy(snapshot["background_and_origin"]), "method":method_audit, "valid":True},
            "Recorded_Art_Roster_Plan.json": {"schema_version":"TianxiaFoundry.C2B2RecordedArtPlan.v1", "recorded_arts":deepcopy(snapshot["explicit_none_systems"]["manuals"]), "planned_records":[]},
            "Blueprint_Deviation_Reconciliation.json": {"schema_version":"TianxiaFoundry.C2B2BlueprintDeviation.v1", "deviations":[], "canonical_choice_changes":False},
            "Command_3_Audit.md": "# Command 3 Audit\n\nStatus: COMMAND_3_CHASSIS_COMPLETE\n\nCharacter chassis, typed-none systems, source-backed display coverage, and later execution dependencies are reconciled.\n",
        }
        command4 = {
            "Training_Sources.json": {"schema_version":"TianxiaFoundry.GMTrainingSources.v1", "classification":"OWNER_RATIFIED_GM_AUTHORING", "training_sources":training_sources},
            "Composite_Playbooks.json": {"schema_version":"TianxiaFoundry.GMCompositePlaybooks.v1", "classification":"DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY", "playbooks":playbooks},
            "Dao_I_Ching_GM_Authoring.json": {"schema_version":"TianxiaFoundry.GMDaoIChingAuthoring.v1", **dao_i_ching},
            "Descriptive_AI_Behavior.json": {"schema_version":"TianxiaFoundry.GMDescriptiveAIProfile.v1", **ai_behavior},
            "Executable_Action_Audit.json": {"schema_version":"TianxiaFoundry.C2B2DeferredExecutionAudit.v1", "status":"LATER_COMBAT_EXECUTION_NOT_ATTEMPTED", "executable_actions_created":0, "display_records_promoted":0, "legacy_pinned_command4_validation":"NOT_RUN", "blocking_for_c2b2":False},
            "Talent_Execution_Coverage_Audit.json": {"schema_version":"TianxiaFoundry.C2B2CapabilityAudit.v1", "records":capability_rows, "gm_display_complete":True, "combat_execution_complete":False, "legacy_pinned_command4_validation":"NOT_RUN"},
            "Composite_Feasibility_Audit.json": {"schema_version":"TianxiaFoundry.C2B2CompositeAudit.v1", "status":"NON_EXECUTABLE_GM_GUIDANCE_COMPLETE", "playbook_ids":[row["playbook_id"] for row in playbooks], "executable_sequences_created":0, "legacy_composite_schema_validation":"NOT_RUN"},
            "Recorded_Art_Audit.json": {"schema_version":"TianxiaFoundry.C2B2TypedNoneAudit.v1", "system":"recorded_arts", "result":deepcopy(snapshot["explicit_none_systems"]["manuals"])},
            "Forged_Technique_Audit.json": {"schema_version":"TianxiaFoundry.C2B2TypedNoneAudit.v1", "system":"forged_techniques", "result":deepcopy(snapshot["explicit_none_systems"]["forged_techniques"])},
            "Behavior_and_Dao_Audit.json": {"schema_version":"TianxiaFoundry.C2B2BehaviorDaoAudit.v1", "status":"GM_AUTHORING_COMPLETE", "dao_id":dao_i_ching["dao"]["authoring_id"], "i_ching_id":dao_i_ching["i_ching"]["authoring_id"], "ai_profile_id":ai_behavior["profile_id"], "mechanical_effect_count":0, "controller_policy_registered":False},
            "Command_4_Audit.md": "# Command 4 Workspace Input Audit\n\nStatus: GM_AUTHORING_INPUT_COMPLETE_EXECUTION_DEFERRED\n\nTraining sources, non-executable composite playbooks, Dao/I Ching, and descriptive AI behavior are complete. The pinned legacy executable Command 4 seal was not run and is not claimed.\n",
        }
        validations = {
            "Command_1.validation.json": self._validation("COMMAND_1_BLUEPRINT_LOCKED", valid=True),
            "Command_2.validation.json": self._validation("COMMAND_2_ADVANCEMENT_LEDGER_SEALED", valid=True),
            "Command_3.validation.json": self._validation("COMMAND_3_CHASSIS_COMPLETE", valid=True),
            "Command_4.validation.json": self._validation("GM_AUTHORING_INPUT_COMPLETE_EXECUTION_DEFERRED", valid=True, legacy_pinned_command4_pass=False, executable_combat_not_attempted=True),
            "C2B2_Workspace.validation.json": self._validation(_STATUS, valid=True, eligible_for_later_command5_checkpoint=True, legacy_command5_eligible=False, command5_invoked=False, command6_invoked=False, gm_export_available=False),
        }
        documents: dict[str, Any] = {}
        for prefix, rows in (("Command_1", command1),("Command_2",command2),("Command_3",command3),("Command_4",command4),("Validation",validations)):
            for name, value in rows.items(): documents[f"{prefix}/{name}"] = value
        documents["Workspace_Manifest.json"] = {
            "schema_version":"TianxiaFoundry.FactoryCommand1To4Workspace.v1",
            "workspace_status":_STATUS,
            "workspace_role":"deterministic existing-Factory authoring input workspace; not a legacy Command 4/5/6 seal",
            "project_id":project["project_id"], "project_revision":project["revision"],
            "event_count":ledger["advancement"]["event_count"], "event_head_hash":ledger["advancement"]["event_head_hash"],
            "replay_state_hash":ledger["advancement"].get("final_replay_state_hash"),
            "projection_id":projection_status.get("projection_id"),
            "character_sheet_sha256":sheet_response["sheet_artifact"]["sha256"],
            "gm_authoring_profile":{"id":profile["profile_id"],"sha256":profile_sha,"classification":profile["authority_classification"]},
            "workspace_profile":{"id":workspace_profile["profile_id"],"sha256":workspace_profile_sha},
            "required_training_source_coverage": sorted(workspace_profile.get("required_training_source_coverage") or []),
            "readiness":deepcopy(workspace_profile["semantics"]),
            "legacy_boundaries":deepcopy(workspace_profile["legacy_boundaries"]),
            "cpk1":{"status":"CANDIDATE_NON_AUTHORITATIVE","schemas_registered":False,"runtime_integrated":False},
        }
        return documents

    @staticmethod
    def _validate_documents(documents: dict[str, Any], workspace_profile: dict[str, Any]) -> None:
        diagnostics: list[dict[str, Any]] = []
        required = set(workspace_profile.get("required_artifacts") or []) - {"SHA256SUMS.txt"}
        if set(documents) != required:
            diagnostics.append({"code":"FACTORY_WORKSPACE_ARTIFACT_SET_MISMATCH","missing":sorted(required-set(documents)),"extra":sorted(set(documents)-required)})
        manifest = documents.get("Workspace_Manifest.json") or {}
        if manifest.get("workspace_status") != _STATUS:
            diagnostics.append({"code":"FACTORY_WORKSPACE_STATUS_INVALID"})
        if (manifest.get("legacy_boundaries") or {}).get("pinned_command4_executable_status") != "NOT_RUN":
            diagnostics.append({"code":"FACTORY_WORKSPACE_FALSE_COMMAND4_CLAIM"})
        validation = documents.get("Validation/C2B2_Workspace.validation.json") or {}
        if validation.get("valid") is not True or validation.get("command5_invoked") is not False or validation.get("command6_invoked") is not False:
            diagnostics.append({"code":"FACTORY_WORKSPACE_VALIDATION_INVALID"})
        training = documents.get("Command_4/Training_Sources.json", {}).get("training_sources") or []
        if not training:
            diagnostics.append({"code":"FACTORY_WORKSPACE_TRAINING_SOURCES_MISSING"})
        playbooks = documents.get("Command_4/Composite_Playbooks.json", {}).get("playbooks") or []
        ids=[row.get("playbook_id") for row in playbooks if isinstance(row,dict)]
        if len(ids) != len(set(ids)):
            diagnostics.append({"code":"FACTORY_WORKSPACE_COMPOSITE_ID_DUPLICATE"})
        if not documents.get("Command_4/Dao_I_Ching_GM_Authoring.json"):
            diagnostics.append({"code":"FACTORY_WORKSPACE_DAO_ICHING_MISSING"})
        ai=documents.get("Command_4/Descriptive_AI_Behavior.json") or {}
        if ai.get("not_executable_controller_policy") is not True:
            diagnostics.append({"code":"FACTORY_WORKSPACE_AI_PROFILE_MISSING"})
        serialized=canonical_json(documents).casefold()
        if "command_5_gm_screen_candidate_ready" in serialized or "simulated_consumer_pass_real_gmscreen_acceptance_required" in serialized:
            diagnostics.append({"code":"FACTORY_WORKSPACE_FALSE_LATER_SEAL"})
        if diagnostics:
            raise FoundryError("FACTORY_WORKSPACE_BUILD_BLOCKED","The Command 1–4 workspace failed cross-file validation.",details={"diagnostics":diagnostics})

    def build(self, project_id: str) -> dict[str, Any]:
        project = self.projects.get_project(project_id)["project"]
        sheet_response = self.sheets.sheet(project_id)
        if sheet_response.get("build_status") != "CHARACTER_SHEET_READY":
            raise FoundryError("FACTORY_WORKSPACE_CHARACTER_SHEET_NOT_READY","The owner-facing Character Sheet must be complete before C2B.2 authoring.")
        profile, profile_sha = self._authoring_profile()
        workspace_profile, workspace_profile_sha = self._workspace_profile()
        profile, profile_sha, workspace_profile, workspace_profile_sha = self._project_authoring_profile(
            sheet_response["owner_character_sheet"],
            profile,
            profile_sha,
            workspace_profile,
            workspace_profile_sha,
        )
        self._validate_profile(profile, workspace_profile, sheet_response["owner_character_sheet"])
        artifact_names=("Character_Master_Ledger.json","Rules_Selection_Packets.json","Projection_Provenance_Map.json","Projection_Coverage_Report.json","Projection_Diagnostics.json")
        projection_artifacts={name:json.loads(self.projections.artifact(project_id,name).read_text(encoding="utf-8")) for name in artifact_names}
        documents=self._documents(project=project,sheet_response=sheet_response,profile=profile,profile_sha=profile_sha,workspace_profile=workspace_profile,workspace_profile_sha=workspace_profile_sha,projection_artifacts=projection_artifacts)
        self._validate_documents(documents, workspace_profile)
        workspace_id=sha256_json({"project_id":project_id,"project_revision":project["revision"],"event_head_hash":documents["Workspace_Manifest.json"]["event_head_hash"],"character_sheet_sha256":sheet_response["sheet_artifact"]["sha256"],"profile_sha256":profile_sha,"workspace_profile_sha256":workspace_profile_sha})
        root=self._root(project_id); target=root/workspace_id; staging=root/(workspace_id+".staging")
        shutil.rmtree(staging,ignore_errors=True); staging.mkdir(parents=True,exist_ok=True)
        for rel,value in documents.items():
            path=staging/rel
            if rel.endswith(".md"):
                path.parent.mkdir(parents=True,exist_ok=True); path.write_text(str(value),encoding="utf-8",newline="\n")
            else: _write_json(path,value)
        checks=[]
        for path in sorted(staging.rglob("*")):
            if path.is_file(): checks.append(f"{sha256_file(path)}  {path.relative_to(staging).as_posix()}")
        (staging/"SHA256SUMS.txt").write_text("\n".join(checks)+"\n",encoding="utf-8",newline="\n")
        if target.exists(): shutil.rmtree(staging)
        else: staging.replace(target)
        file_hashes={path.relative_to(target).as_posix():sha256_file(path) for path in sorted(target.rglob("*")) if path.is_file()}
        workspace_sha=sha256_json(file_hashes)
        pointer={"schema_version":"TianxiaFoundry.FactoryWorkspacePointer.v1","project_id":project_id,"workspace_id":workspace_id,"workspace_status":_STATUS,"workspace_path":str(target),"workspace_sha256":workspace_sha,"manifest_sha256":file_hashes["Workspace_Manifest.json"],"gm_authoring_profile_sha256":profile_sha,"command5_invoked":False,"command6_invoked":False,"gm_export_available":False}
        root.mkdir(parents=True,exist_ok=True); pointer_tmp=root/"current.json.tmp"; _write_json(pointer_tmp,pointer); pointer_tmp.replace(self._pointer(project_id))
        return {**pointer,"artifact_hashes":file_hashes,"readiness":workspace_profile["semantics"],"legacy_boundaries":workspace_profile["legacy_boundaries"]}

    def status(self, project_id: str) -> dict[str, Any]:
        pointer=self._pointer(project_id)
        if not pointer.is_file():
            return {"project_id":project_id,"workspace_status":"NOT_ATTEMPTED","available":False,"command5_invoked":False,"command6_invoked":False,"gm_export_available":False}
        payload=json.loads(pointer.read_text(encoding="utf-8"))
        workspace=Path(payload.get("workspace_path") or "")
        if not workspace.is_dir():
            return {"project_id":project_id,"workspace_status":"STALE","available":False,"blockers":["The recorded Factory workspace directory is missing."],"command5_invoked":False,"command6_invoked":False,"gm_export_available":False}
        manifest=workspace/"Workspace_Manifest.json"
        if not manifest.is_file() or sha256_file(manifest)!=payload.get("manifest_sha256"):
            return {"project_id":project_id,"workspace_status":"STALE","available":False,"blockers":["The Factory workspace manifest is stale."],"command5_invoked":False,"command6_invoked":False,"gm_export_available":False}
        return {**payload,"available":True,"blockers":[]}
