from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import zipfile
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from app.core import Database, FoundryError, canonical_json, sha256_file, sha256_json
from app.runtime import helper_python_executable
from character_sheet.service import CharacterSheetService
from factory_authoring.service import FactoryAuthoringWorkspaceService
from projector.service import ProjectionService
from project_store.service import ProjectStore

BUILD_PROFILE_CONTRACT = "Tianxia_C2B3_Factory_Build_Profiles_R1.json"
GM_MODEL_PROFILE_SCHEMA = "Tianxia_C2B3_GM_Character_Model_Profile_R1.schema.json"
LEGACY_PROFILE = "LEGACY_FULL_EXECUTION"
CHARACTER_GM_PROFILE = "CHARACTER_GM_MODEL"
CHARACTER_GM_COMMAND4_PASS = "CHARACTER_GM_COMMAND_4_PROFILE_PASS"
GM_CANDIDATE_READY = "GM_MODEL_CANDIDATE_READY"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8", newline="\n")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FoundryError("PINNED_FACTORY_MODULE_UNAVAILABLE", f"Unable to load pinned Factory module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CharacterGMCommand5Profile:
    @staticmethod
    def _canonicalize_candidate_zip(candidate: Path) -> None:
        """Remove host filesystem timestamps from the pinned sealer's ZIP."""
        canonical = candidate.with_suffix(".canonical.zip")
        with zipfile.ZipFile(candidate, "r") as source, zipfile.ZipFile(
            canonical, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as destination:
            for original in sorted(source.infolist(), key=lambda item: item.filename):
                info = zipfile.ZipInfo(original.filename, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = original.external_attr
                info.flag_bits = original.flag_bits & 0x800
                destination.writestr(info, source.read(original.filename))
        canonical.replace(candidate)

    """Character/GM branch of the existing Command 5 lifecycle.

    Legacy omission remains routed by ProjectionVerifier through the historical
    pinned Command 5 path. This class only assembles and audits the explicit
    CHARACTER_GM_MODEL profile; it never performs Command 6 or GM export.
    """

    def __init__(self, db: Database, *, factory_root: Path):
        self.db = db
        self.factory_root = factory_root.resolve()
        self.projects = ProjectStore(db)
        self.projections = ProjectionService(db, factory_root=self.factory_root)
        self.sheets = CharacterSheetService(db)
        self.workspaces = FactoryAuthoringWorkspaceService(db)

    @property
    def _contracts_dir(self) -> Path:
        return Path(__file__).resolve().parent / "contracts"

    def build_profiles(self) -> tuple[dict[str, Any], str]:
        return self.workspaces._verify_sealed_json(
            self._contracts_dir / BUILD_PROFILE_CONTRACT,
            expected_schema="TianxiaFoundry.FactoryBuildProfiles.v1",
            error_prefix="FACTORY_BUILD_PROFILE",
        )

    def select_profile(self, profile_id: str | None) -> tuple[dict[str, Any], str]:
        contract, contract_sha = self.build_profiles()
        selected = profile_id or contract.get("default_profile_id")
        profile = (contract.get("profiles") or {}).get(selected)
        if not isinstance(profile, dict):
            raise FoundryError(
                "FACTORY_BUILD_PROFILE_UNKNOWN",
                "The requested Factory build profile is not supported.",
                details={"requested": selected, "supported": sorted((contract.get("profiles") or {}).keys())},
            )
        return deepcopy(profile), contract_sha

    def _model_schema(self) -> tuple[dict[str, Any], str]:
        path = self._contracts_dir / GM_MODEL_PROFILE_SCHEMA
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if not path.is_file() or not sidecar.is_file():
            raise FoundryError("GM_MODEL_PROFILE_SCHEMA_MISSING", "The Character/GM model profile schema is missing.")
        digest, declared = sidecar.read_text(encoding="utf-8").strip().split(None, 1)
        actual = sha256_file(path)
        if digest.lower() != actual or declared.strip().lstrip("*") != path.name:
            raise FoundryError("GM_MODEL_PROFILE_SCHEMA_STALE", "The Character/GM model profile schema checksum is stale.")
        return json.loads(path.read_text(encoding="utf-8")), actual

    def _workspace_identity(self, project_id: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
        status = self.workspaces.status(project_id)
        if status.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE" or not status.get("available"):
            raise FoundryError("CHARACTER_GM_WORKSPACE_NOT_READY", "The deterministic C2B.2 Command 1-4 workspace is required.", details=status)
        root = Path(str(status.get("workspace_path") or ""))
        manifest = json.loads((root / "Workspace_Manifest.json").read_text(encoding="utf-8"))
        if manifest.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE":
            raise FoundryError("CHARACTER_GM_WORKSPACE_STATUS_INVALID", "The Factory workspace status is not complete.")
        return status, root, manifest

    @staticmethod
    def _all_cards(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        cards = [row for rows in (snapshot.get("selected_record_sections") or {}).values() for row in (rows or []) if isinstance(row, dict)]
        cards.sort(key=lambda row: (int(row.get("acquisition_cl") or 0), str(row.get("section") or ""), str(row.get("record_id") or "")))
        return cards

    @staticmethod
    def _display_actions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        by_id = {str(row.get("record_id")): row for row in CharacterGMCommand5Profile._all_cards(snapshot)}
        rows = []
        for index in snapshot.get("owner_facing_action_feature_index") or []:
            card = by_id.get(str(index.get("record_id")))
            if not card:
                continue
            execution = (card.get("capabilities") or {}).get("combat_execution") or "UNSUPPORTED"
            rows.append({
                "record_id": card.get("record_id"),
                "display_name": card.get("display_name"),
                "category": card.get("timing_or_category") or index.get("timing_or_category") or "Feature",
                "acquisition_cl": card.get("acquisition_cl"),
                "acquisition_route": card.get("acquisition_route"),
                "one_line_description": card.get("one_line_description"),
                "full_description": card.get("full_description"),
                "source": deepcopy(card.get("source")),
                "source_packet_ids": deepcopy(card.get("source_packet_ids") or []),
                "capabilities": deepcopy(card.get("capabilities") or {}),
                "combat_execution_status": execution,
                "display_only_not_execution_authority": True,
                "stable_id": card.get("record_id"),
            })
        return rows

    def validate_command4(self, project_id: str, *, profile_id: str = CHARACTER_GM_PROFILE) -> dict[str, Any]:
        profile, profile_contract_sha = self.select_profile(profile_id)
        if profile.get("profile_id") != CHARACTER_GM_PROFILE:
            raise FoundryError("CHARACTER_GM_PROFILE_REQUIRED", "Character/GM Command 4 validation requires the explicit CHARACTER_GM_MODEL profile.")
        project = self.projects.get_project(project_id)["project"]
        sheet_response = self.sheets.sheet(project_id)
        snapshot = sheet_response.get("owner_character_sheet") or {}
        workspace_status, workspace_root, manifest = self._workspace_identity(project_id)
        diagnostics: list[dict[str, Any]] = []
        readiness = sheet_response.get("readiness") or {}
        if readiness.get("advancement") != "ADVANCEMENT_READY": diagnostics.append({"code":"CHARACTER_GM_ADVANCEMENT_NOT_READY"})
        if readiness.get("character_sheet") != "CHARACTER_SHEET_READY": diagnostics.append({"code":"CHARACTER_GM_SHEET_NOT_READY"})
        if readiness.get("gm_screen") != "NOT_ATTEMPTED": diagnostics.append({"code":"CHARACTER_GM_FALSE_CONSUMER_READINESS"})
        if sheet_response.get("gm_export", {}).get("available") is not False: diagnostics.append({"code":"CHARACTER_GM_EXPORT_MUST_REMAIN_BLOCKED"})
        if manifest.get("project_id") != project_id or manifest.get("project_revision") != project.get("revision"):
            diagnostics.append({"code":"CHARACTER_GM_WORKSPACE_PROJECT_IDENTITY_MISMATCH"})
        if manifest.get("character_sheet_sha256") != sheet_response.get("sheet_artifact", {}).get("sha256"):
            diagnostics.append({"code":"CHARACTER_GM_WORKSPACE_SHEET_STALE"})
        required = [
            "Command_4/Training_Sources.json", "Command_4/Composite_Playbooks.json",
            "Command_4/Dao_I_Ching_GM_Authoring.json", "Command_4/Descriptive_AI_Behavior.json",
            "Validation/C2B2_Workspace.validation.json",
        ]
        for rel in required:
            if not (workspace_root / rel).is_file(): diagnostics.append({"code":"CHARACTER_GM_AUTHORING_ARTIFACT_MISSING","path":rel})
        training = json.loads((workspace_root / "Command_4/Training_Sources.json").read_text(encoding="utf-8")) if (workspace_root / "Command_4/Training_Sources.json").is_file() else {}
        playbooks = json.loads((workspace_root / "Command_4/Composite_Playbooks.json").read_text(encoding="utf-8")) if (workspace_root / "Command_4/Composite_Playbooks.json").is_file() else {}
        dao = json.loads((workspace_root / "Command_4/Dao_I_Ching_GM_Authoring.json").read_text(encoding="utf-8")) if (workspace_root / "Command_4/Dao_I_Ching_GM_Authoring.json").is_file() else {}
        ai = json.loads((workspace_root / "Command_4/Descriptive_AI_Behavior.json").read_text(encoding="utf-8")) if (workspace_root / "Command_4/Descriptive_AI_Behavior.json").is_file() else {}
        selected_ids = {str(row.get("record_id")) for row in self._all_cards(snapshot)}
        required_training_ids = set(manifest.get("required_training_source_coverage") or [])
        if not required_training_ids:
            workspace_profile, _workspace_profile_sha = self.workspaces._workspace_profile()
            required_training_ids = set(workspace_profile.get("required_training_source_coverage") or [])
        covered = [str(record) for row in training.get("training_sources") or [] for record in row.get("record_ids") or []]
        if set(covered) != required_training_ids or len(covered) != len(set(covered)):
            diagnostics.append({"code":"CHARACTER_GM_TRAINING_COVERAGE_INVALID","missing":sorted(required_training_ids-set(covered)),"extra":sorted(set(covered)-required_training_ids)})
        for row in playbooks.get("playbooks") or []:
            if row.get("classification") != "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY": diagnostics.append({"code":"CHARACTER_GM_PLAYBOOK_EXECUTABLE_CLAIM","playbook_id":row.get("playbook_id")})
        if dao.get("classification") != "OWNER_RATIFIED_GM_AUTHORING" or (dao.get("dao") or {}).get("mechanical_effects") != [] or (dao.get("i_ching") or {}).get("mechanical_effects") != []:
            diagnostics.append({"code":"CHARACTER_GM_DAO_ICHING_CLASSIFICATION_INVALID"})
        if ai.get("not_executable_controller_policy") is not True or ai.get("controller_policy_registered") is True:
            diagnostics.append({"code":"CHARACTER_GM_AI_POLICY_EXECUTABLE_CLAIM"})
        if any((row.get("capabilities") or {}).get("combat_execution") not in {"SUPPORTED","NOT_APPLICABLE"} and not row.get("display_only_not_execution_authority") for row in self._all_cards(snapshot)):
            diagnostics.append({"code":"CHARACTER_GM_DISPLAY_PROMOTED_TO_EXECUTION"})
        result = {
            "schema_version":"TianxiaFoundry.CharacterGMCommand4ProfileValidation.v1",
            "project_id":project_id,"project_revision":project.get("revision"),"build_profile":profile,
            "build_profile_contract_sha256":profile_contract_sha,
            "character_gm_command4_status":CHARACTER_GM_COMMAND4_PASS if not diagnostics else "CHARACTER_GM_COMMAND_4_PROFILE_FAIL",
            "legacy_full_command4_status":"BLOCKED_NOT_RUN_COMBAT_EXECUTION_INCOMPLETE",
            "workspace_id":workspace_status.get("workspace_id"),"workspace_sha256":workspace_status.get("workspace_sha256"),
            "character_sheet_sha256":sheet_response.get("sheet_artifact",{}).get("sha256"),
            "selected_record_count":len(selected_ids),"training_coverage_count":len(set(covered)),
            "command5_invoked":False,"command6_invoked":False,"gm_export_available":False,
            "diagnostics":diagnostics,"valid":not diagnostics,
        }
        if diagnostics:
            raise FoundryError("CHARACTER_GM_COMMAND4_BLOCKED", "The Character/GM Command 4 profile failed validation.", details=result)
        return result

    @staticmethod
    def _typed_none(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
        selected_method = snapshot.get("method") or {}
        if name == "method" and selected_method.get("state") == "acquired" and selected_method.get("record_id"):
            return deepcopy(selected_method)
        return deepcopy((snapshot.get("explicit_none_systems") or {}).get(name) or {"state":"none","source_backed":True})

    def _models(self, *, project: dict[str, Any], sheet_response: dict[str, Any], workspace_root: Path, workspace_status: dict[str, Any], profile: dict[str, Any], profile_contract_sha: str, command4: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        snapshot = deepcopy(sheet_response["owner_character_sheet"])
        actions = self._display_actions(snapshot)
        training = json.loads((workspace_root / "Command_4/Training_Sources.json").read_text(encoding="utf-8"))
        playbooks = json.loads((workspace_root / "Command_4/Composite_Playbooks.json").read_text(encoding="utf-8"))
        dao = json.loads((workspace_root / "Command_4/Dao_I_Ching_GM_Authoring.json").read_text(encoding="utf-8"))
        ai = json.loads((workspace_root / "Command_4/Descriptive_AI_Behavior.json").read_text(encoding="utf-8"))
        auth = snapshot.get("authority_and_artifact_identity") or {}
        metadata = {
            "build_profile":CHARACTER_GM_PROFILE,"build_profile_version":profile.get("profile_version"),"build_profile_contract_sha256":profile_contract_sha,
            "candidate_status":GM_CANDIDATE_READY,"project_id":project["project_id"],"project_revision":project["revision"],
            "event_count":auth.get("event_count"),"event_head_hash":auth.get("event_head_hash"),"content_lock_hash":auth.get("content_lock_hash"),
            "typed_choice_snapshot_sha256":auth.get("typed_choice_snapshot_sha256"),
            "projection_id":auth.get("projection_id"),"character_sheet_sha256":sheet_response["sheet_artifact"]["sha256"],
            "workspace_id":workspace_status.get("workspace_id"),"workspace_sha256":workspace_status.get("workspace_sha256"),
            "consumer_verification":"NOT_ATTEMPTED","gm_export_available":False,"command6_status":"NOT_RUN",
            "combat_execution":"NOT_ATTEMPTED_OR_UNSUPPORTED","cpk1_schemas_registered":False,
        }
        gm_model = {
            "schema_version":"Tianxia_GM_Character_Model_v1","metadata":metadata,
            "identity":deepcopy(snapshot.get("identity")),"stats":deepcopy(snapshot.get("ability_scores_and_statistics")),
            "leveling_ledger":deepcopy((snapshot.get("advancement_history") or {}).get("levels") or []),
            "background_origin":deepcopy(snapshot.get("background_and_origin")),
            "paths_subpaths_insights":deepcopy(snapshot.get("path_and_subpath")),
            "spheres_talents":deepcopy(snapshot.get("spheres_and_talents")),
            "actions":actions,"composites":deepcopy(playbooks.get("playbooks") or []),
            "recorded_arts":self._typed_none(snapshot,"manuals"),"foundation":self._typed_none(snapshot,"foundation"),"method":self._typed_none(snapshot,"method"),
            "dao_i_ching":{"dao":deepcopy(dao.get("dao")),"i_ching":deepcopy(dao.get("i_ching"))},
            "equipment_resources_states":{"equipment":self._typed_none(snapshot,"equipment"),"resources":{"qi_maximum":(snapshot.get("ability_scores_and_statistics") or {}).get("primary_resource")},"states":{"status":"PENDING_COMBAT_EXECUTION","typed_definitions":[]}},
            "spirit_companions":{"state":"none","source_backed":True,"entries":[]},
            "forged_techniques":self._typed_none(snapshot,"forged_techniques"),
            "training_sources":deepcopy(training.get("training_sources") or []),"ai_behavior":deepcopy(ai),
            "diagnostics":{"valid":True,"gm_screen_consumer_verification":"NOT_ATTEMPTED","combat_execution_pending":True,"display_only_record_count":sum(1 for row in actions if row["display_only_not_execution_authority"]),"no_false_combat_claim":True},
            "capability_readiness":{"advancement":"ADVANCEMENT_READY","character_sheet":"CHARACTER_SHEET_READY","gm_tactical_authoring":"COMPLETE","character_gm_command4":CHARACTER_GM_COMMAND4_PASS,"gm_model_candidate":GM_CANDIDATE_READY,"gm_screen_consumer":"NOT_ATTEMPTED","combat":"NOT_ATTEMPTED"},
            "provenance":{"character_sheet":deepcopy(snapshot.get("section_provenance")),"command4_profile_validation_sha256":sha256_json(command4),"workspace_manifest_sha256":workspace_status.get("manifest_sha256"),"selected_record_identity_index":deepcopy(snapshot.get("selected_record_identity_index"))},
        }
        view = {
            "schema_version":"Tianxia_GM_Character_View_Model_v2","identity":deepcopy(gm_model["identity"]),"core_stats":deepcopy(gm_model["stats"]),
            "leveling_ledger":deepcopy(gm_model["leveling_ledger"]),"background_origin":deepcopy(gm_model["background_origin"]),"spheres_talents":deepcopy(gm_model["spheres_talents"]),
            "actions":deepcopy(actions),"composites":deepcopy(gm_model["composites"]),"forged_techniques":[],"preserved_forged_expressions":[],"emergency_technique_seeds":[],"martial_manuals":[],
            "foundation":deepcopy(gm_model["foundation"]),"method":deepcopy(gm_model["method"]),"dao_i_ching":deepcopy(gm_model["dao_i_ching"]),"equipment_resources_states":deepcopy(gm_model["equipment_resources_states"]),
            "diagnostics":[{"code":"GM_SCREEN_CONSUMER_VERIFICATION_PENDING","severity":"notice"},{"code":"COMBAT_EXECUTION_PENDING","severity":"notice","display_only_records":sum(1 for row in actions if row["display_only_not_execution_authority"])}],
            "validation":{"status":GM_CANDIDATE_READY,"build_profile":CHARACTER_GM_PROFILE,"schema_valid":True,"consumer_verification":"NOT_ATTEMPTED","gm_export_available":False},
            "metadata":deepcopy(metadata),"paths_subpaths_insights":deepcopy(gm_model["paths_subpaths_insights"]),"training_sources":deepcopy(gm_model["training_sources"]),"ai_behavior":deepcopy(ai),"capability_readiness":deepcopy(gm_model["capability_readiness"]),"provenance":deepcopy(gm_model["provenance"]),
        }
        display_rows = []
        for section, value in (("Overview/Core", {"identity":gm_model["identity"],"stats":gm_model["stats"]}),("Leveling Ledger",gm_model["leveling_ledger"]),("Background and Origin",gm_model["background_origin"]),("Paths/Subpaths/Insights",gm_model["paths_subpaths_insights"]),("Spheres and Talents",gm_model["spheres_talents"]),("Actions and Reactions",gm_model["actions"]),("Composite Playbooks",gm_model["composites"]),("Recorded Arts",gm_model["recorded_arts"]),("Foundation",gm_model["foundation"]),("Method",gm_model["method"]),("Dao and I Ching",gm_model["dao_i_ching"]),("Equipment, Resources, and States",gm_model["equipment_resources_states"]),("Spirit Companions",gm_model["spirit_companions"]),("Forged Techniques",gm_model["forged_techniques"]),("Diagnostics",gm_model["diagnostics"])):
            display_rows.append({"tab":section,"value":deepcopy(value),"structured":True,"source_model":"Tianxia_GM_Character_Model_v1"})
        tabs = {"schema_version":"TianxiaFoundry.CharacterGMTabCoverage.v1","status":"COMPLETE_CHARACTER_GM_PROFILE","rows":display_rows,"required_tabs":[row["tab"] for row in display_rows]}
        return gm_model, view, tabs

    def _validate_models(self, gm_model: dict[str, Any], view: dict[str, Any], tabs: dict[str, Any]) -> dict[str, Any]:
        model_schema, model_schema_sha = self._model_schema()
        model_errors = sorted(error.message for error in Draft202012Validator(model_schema).iter_errors(gm_model))
        pinned_schema_path = self.factory_root / "04_SCHEMAS" / "gm_character_view_model.schema.json"
        pinned_schema = json.loads(pinned_schema_path.read_text(encoding="utf-8"))
        view_errors = sorted(error.message for error in Draft202012Validator(pinned_schema).iter_errors(view))
        diagnostics: list[dict[str, Any]] = []
        for message in model_errors: diagnostics.append({"code":"GM_MODEL_PROFILE_SCHEMA_ERROR","message":message})
        for message in view_errors: diagnostics.append({"code":"GM_VIEW_MODEL_PINNED_SCHEMA_ERROR","message":message})
        serialized = canonical_json({"gm_model":gm_model,"view":view,"tabs":tabs})
        for token in ("[object Object]","TBD","TODO","placeholder"):
            if token.casefold() in serialized.casefold(): diagnostics.append({"code":"GM_CANDIDATE_FORBIDDEN_PLACEHOLDER","token":token})
        action_ids = [row.get("record_id") for row in gm_model.get("actions") or []]
        if len(action_ids) != len(set(action_ids)): diagnostics.append({"code":"GM_CANDIDATE_ACTION_ARRAY_DUPLICATE"})
        if any(row.get("display_only_not_execution_authority") is not True and row.get("combat_execution_status") not in {"SUPPORTED","NOT_APPLICABLE"} for row in gm_model.get("actions") or []):
            diagnostics.append({"code":"GM_CANDIDATE_FALSE_EXECUTION_CLAIM"})
        if any(row.get("classification") != "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY" for row in gm_model.get("composites") or []): diagnostics.append({"code":"GM_CANDIDATE_EXECUTABLE_COMPOSITE"})
        if len(tabs.get("rows") or []) != len(tabs.get("required_tabs") or []): diagnostics.append({"code":"GM_CANDIDATE_TAB_COVERAGE_INCOMPLETE"})
        if diagnostics:
            raise FoundryError("CHARACTER_GM_COMMAND5_AUDIT_FAILED", "The Character/GM model candidate failed schema or deep-audit validation.", details={"diagnostics":diagnostics})
        return {"schema_version":"TianxiaFoundry.CharacterGMCommand5DeepAudit.v1","valid":True,"status":"PASS_CHARACTER_GM_COMMAND_5_AUDIT","gm_model_profile_schema_sha256":model_schema_sha,"pinned_view_model_schema_sha256":sha256_file(pinned_schema_path),"tab_count":len(tabs.get("rows") or []),"action_display_count":len(action_ids),"composite_count":len(gm_model.get("composites") or []),"array_preservation":True,"placeholder_leakage":False,"false_combat_claim":False,"consumer_verification":"NOT_ATTEMPTED"}

    def _surfaces(self, *, project: dict[str, Any], sheet_response: dict[str, Any], workspace_root: Path, workspace_status: dict[str, Any], profile: dict[str, Any], profile_contract_sha: str, command4: dict[str, Any]) -> dict[str, Any]:
        gm_model, view, tabs = self._models(project=project,sheet_response=sheet_response,workspace_root=workspace_root,workspace_status=workspace_status,profile=profile,profile_contract_sha=profile_contract_sha,command4=command4)
        audit = self._validate_models(gm_model, view, tabs)
        snapshot = sheet_response["owner_character_sheet"]
        projections = {name:json.loads(self.projections.artifact(project["project_id"],name).read_text(encoding="utf-8")) for name in ("Character_Master_Ledger.json","Rules_Selection_Packets.json","Projection_Provenance_Map.json","Projection_Coverage_Report.json","Projection_Diagnostics.json")}
        surfaces: dict[str, Any] = {
            "C2B3_Build_Profile.json":{"schema_version":"TianxiaFoundry.FactoryBuildProfileSelection.v1","profile":profile,"profile_contract_sha256":profile_contract_sha,"default_legacy_behavior_preserved":True},
            "C2B3_Character_GM_Command_4_Validation.json":command4,
            "Tianxia_GM_Character_Model_v1.json":gm_model,
            "Tianxia_GM_Character_View_Model_v2.json":view,
            "GM_Screen_Tab_Expectation_Manifest.json":tabs,
            "GM_Screen_Display_Rows.json":{"schema_version":"TianxiaFoundry.CharacterGMDisplayRows.v1","rows":deepcopy(tabs["rows"])},
            "GM_Screen_Projection_Rows.json":{"schema_version":"TianxiaFoundry.CharacterGMProjectionRows.v1","rows":deepcopy(tabs["rows"]),"source":"C2B3 CHARACTER_GM_MODEL deterministic profile"},
            "Character_Master_Ledger.json":projections["Character_Master_Ledger.json"],
            "Rules_Selection_Packets.json":projections["Rules_Selection_Packets.json"],
            "Projection_Provenance_Map.json":projections["Projection_Provenance_Map.json"],
            "Projection_Coverage_Report.json":projections["Projection_Coverage_Report.json"],
            "Projection_Diagnostics.json":projections["Projection_Diagnostics.json"],
            "Tianxia_Owner_Character_Sheet_v1.json":snapshot,
            "Leveling_Ledger.json":{"schema_version":"TianxiaFoundry.CharacterGMLevelingLedger.v1","levels":deepcopy(gm_model["leveling_ledger"])},
            "Background_Origin_Ledger.json":{"schema_version":"TianxiaFoundry.CharacterGMBackgroundOrigin.v1","background_origin":deepcopy(gm_model["background_origin"])},
            "Selected_Spheres.json":{"schema_version":"TianxiaFoundry.CharacterGMSelectedSpheres.v1","spheres":deepcopy((snapshot.get("selected_record_sections") or {}).get("spheres") or [])},
            "Talent_Source_Ledger.json":{"schema_version":"TianxiaFoundry.CharacterGMTalentSources.v1","background_talents":deepcopy((snapshot.get("selected_record_sections") or {}).get("background_talent") or []),"learned_talents":deepcopy((snapshot.get("selected_record_sections") or {}).get("talents") or [])},
            "Complete_Action_Surface.json":{"schema_version":"TianxiaFoundry.CharacterGMDisplayActionSurface.v1","actions":deepcopy(gm_model["actions"]),"execution_authority":False},
            "Composite_Playbook.json":{"schema_version":"TianxiaFoundry.CharacterGMCompositePlaybooks.v1","composites":deepcopy(gm_model["composites"]),"execution_authority":False},
            "Manual_Lineage_Record.json":{"schema_version":"TianxiaFoundry.CharacterGMTrainingSources.v1","training_sources":deepcopy(gm_model["training_sources"])},
            "Martial_Arts_and_Manuals.json":{"schema_version":"TianxiaFoundry.CharacterGMManuals.v1","none_state":deepcopy(gm_model["recorded_arts"]),"manuals":[]},
            "Foundation_Detail_Ledger.json":{"schema_version":"TianxiaFoundry.CharacterGMFoundation.v1","foundation":deepcopy(gm_model["foundation"])},
            "Cultivation_Method_Profile.json":{"schema_version":"TianxiaFoundry.CharacterGMMethod.v1","method":deepcopy(gm_model["method"])},
            "Dao_IChing_Combat_Profile.json":{"schema_version":"TianxiaFoundry.CharacterGMDaoIChing.v1","dao_i_ching":deepcopy(gm_model["dao_i_ching"]),"classification":"GM_GUIDANCE_ONLY","execution_authority":False},
            "Equipment_Ledger.json":{"schema_version":"TianxiaFoundry.CharacterGMEquipment.v1","equipment":deepcopy(gm_model["equipment_resources_states"]["equipment"])},
            "Resources_and_States.json":{"schema_version":"TianxiaFoundry.CharacterGMResourcesStates.v1","equipment_resources_states":deepcopy(gm_model["equipment_resources_states"])},
            "Forged_Techniques.json":{"schema_version":"TianxiaFoundry.CharacterGMForgedTechniques.v1","none_state":deepcopy(gm_model["forged_techniques"]),"forged_techniques":[]},
            "AI_Combat_Behavior_Profile.json":{"schema_version":"TianxiaFoundry.CharacterGMDescriptiveAI.v1","profile":deepcopy(gm_model["ai_behavior"]),"not_executable_controller_policy":True},
            "Semantic_Validation_Report.json":{"schema_version":"TianxiaFoundry.CharacterGMSemanticValidation.v1","verdict":"PASS_CHARACTER_GM_PROFILE","release_ready":False,"character_gm_candidate_ready":True,"combat_execution_ready":False,"diagnostics":deepcopy(gm_model["diagnostics"])},
            "C2B3_Character_GM_Live_Render_Seal.json":{"schema_version":"TianxiaFoundry.CharacterGMLiveRenderSeal.v1","status":"PASS_STATIC_CHARACTER_GM_RENDER_SEAL","evidence_boundary":"static_character_gm_candidate","consumer_verification":"NOT_ATTEMPTED","tab_manifest_sha256":sha256_json(tabs),"gm_model_sha256":sha256_json(gm_model),"view_model_sha256":sha256_json(view),"array_preservation":True,"readable_structured_values":True},
            "C2B3_Character_GM_Deep_Audit.json":audit,
            "Build_Reconciliation.json":{"schema_version":"TianxiaFoundry.CharacterGMBuildReconciliation.v1","status":GM_CANDIDATE_READY,"build_profile":CHARACTER_GM_PROFILE,"all_derived_from_canonical_or_sealed_authoring":True,"manual_derived_file_edits_allowed":False,"legacy_full_execution_status":"BLOCKED_NOT_RUN_COMBAT_EXECUTION_INCOMPLETE","command6_status":"NOT_RUN","gm_export_available":False},
        }
        return surfaces

    def command5(self, project_id: str, *, output_root: Path) -> dict[str, Any]:
        profile, profile_contract_sha = self.select_profile(CHARACTER_GM_PROFILE)
        command4 = self.validate_command4(project_id, profile_id=CHARACTER_GM_PROFILE)
        project = self.projects.get_project(project_id)["project"]
        sheet_response = self.sheets.sheet(project_id)
        workspace_status, source_workspace, _manifest = self._workspace_identity(project_id)
        if output_root.exists(): shutil.rmtree(output_root)
        workspace = output_root / "workspace"
        shutil.copytree(source_workspace, workspace)
        build = workspace / "Build"
        surfaces = self._surfaces(project=project,sheet_response=sheet_response,workspace_root=source_workspace,workspace_status=workspace_status,profile=profile,profile_contract_sha=profile_contract_sha,command4=command4)
        compiler = _load_module(self.factory_root / "05_COMPILER" / "compile_character.py", "tianxia_pinned_compile_character_c2b3")
        compiler.write_build(build, surfaces)
        candidate = output_root / "candidate.zip"
        seal_tool = self.factory_root / "07_TOOLS" / "seal_character_zip.py"
        # The copied Factory root can exceed the legacy Windows MAX_PATH limit.
        # The sealer receives absolute inputs and does not require that long path
        # as its process working directory, so launch it from the stable source
        # root while retaining the exact pinned tool and build identities.
        completed = subprocess.run([str(helper_python_executable()),str(seal_tool),"--build",str(build),"--output",str(candidate),"--classification","COMMAND_5_GM_SCREEN_CANDIDATE_READY"],cwd=self.db.settings.root_dir,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=300)
        if completed.returncode != 0 or not candidate.is_file():
            raise FoundryError("CHARACTER_GM_COMMAND5_SEAL_FAILED", "The pinned deterministic candidate sealer failed.", details={"exit_code":completed.returncode,"stdout":completed.stdout,"stderr":completed.stderr})
        self._canonicalize_candidate_zip(candidate)
        model_path = build / "Tianxia_GM_Character_Model_v1.json"
        view_path = build / "Tianxia_GM_Character_View_Model_v2.json"
        audit_path = build / "C2B3_Character_GM_Deep_Audit.json"
        manifest_path = build / "PACKAGE_MANIFEST.json"
        report = {
            "schema_version":"TianxiaFoundry.CharacterGMCommand5Verification.v1","project_id":project_id,"projection_id":self.projections.status(project_id).get("projection_id"),
            "status":GM_CANDIDATE_READY,"build_profile":profile,"build_profile_contract_sha256":profile_contract_sha,
            "character_gm_command4":command4,"legacy_full_command4_status":"BLOCKED_NOT_RUN_COMBAT_EXECUTION_INCOMPLETE",
            "workspace":str(workspace),"build":str(build),"candidate_zip":str(candidate),"candidate_sha256":sha256_file(candidate),
            "gm_model_path":str(model_path),"gm_model_sha256":sha256_file(model_path),"gm_view_model_sha256":sha256_file(view_path),
            "deep_audit_sha256":sha256_file(audit_path),"build_manifest_sha256":sha256_file(manifest_path),
            "command6_status":"NOT_RUN","gm_screen_consumer_verification":"NOT_ATTEMPTED","gm_export_available":False,"combat_execution":"NOT_ATTEMPTED",
            "seal_run":{"exit_code":completed.returncode,"stdout":completed.stdout,"stderr":completed.stderr},
        }
        candidate_root = self.db.settings.data_dir / "factory_candidates" / project_id
        candidate_root.mkdir(parents=True, exist_ok=True)
        durable = candidate_root / report["candidate_sha256"]
        if durable.exists(): shutil.rmtree(durable)
        shutil.copytree(output_root, durable)
        durable_build = durable / "workspace" / "Build"
        pointer = {
            **report,
            "workspace":str(durable/"workspace"),
            "build":str(durable_build),
            "candidate_zip":str(durable/"candidate.zip"),
            "gm_model_path":str(durable_build/"Tianxia_GM_Character_Model_v1.json"),
            "gm_view_model_path":str(durable_build/"Tianxia_GM_Character_View_Model_v2.json"),
            "deep_audit_path":str(durable_build/"C2B3_Character_GM_Deep_Audit.json"),
            "build_manifest_path":str(durable_build/"PACKAGE_MANIFEST.json"),
        }
        _write_json(candidate_root / "current.json", pointer)
        with self.db.transaction() as conn:
            projection_id = report["projection_id"]
            conn.execute("UPDATE projection_runs SET command5_status=?,candidate_sha256=?,diagnostics_json=? WHERE projection_id=?",(GM_CANDIDATE_READY,report["candidate_sha256"],canonical_json([]),projection_id))
            conn.execute("UPDATE projects SET compile_status=? WHERE project_id=?",(GM_CANDIDATE_READY,project_id))
        return pointer

    def status(self, project_id: str) -> dict[str, Any]:
        path = self.db.settings.data_dir / "factory_candidates" / project_id / "current.json"
        if not path.is_file():
            return {"project_id":project_id,"status":"NOT_ATTEMPTED","build_profile":None,"gm_export_available":False,"command6_status":"NOT_RUN"}
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidate = Path(str(payload.get("candidate_zip") or ""))
        model = Path(str(payload.get("gm_model_path") or ""))
        stale = not candidate.is_file() or sha256_file(candidate) != payload.get("candidate_sha256") or not model.is_file() or sha256_file(model) != payload.get("gm_model_sha256")
        if stale:
            return {**payload,"status":"STALE","gm_export_available":False,"blockers":["The Character/GM candidate or model hash is stale."]}
        return {**payload,"blockers":[],"gm_export_available":False}
