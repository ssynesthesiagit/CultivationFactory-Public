from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core import FoundryError, sha256_bytes, sha256_file
from portable_character.service import PortableCharacterPackageService
from .character_compilation import (
    ActionEconomy,
    CombatSheet,
    CombatantStats,
    ExecutableMechanicsLock,
    PrimitiveRegistry,
    StaticValidationReport,
    canonical_json,
    canonical_sha256,
)

SOURCE_PACKAGE_SHA256 = "c362665c32a06cd3323981c2ceb116d9e137a9e48bbdba4065363b65253d5fd8"
PROJECT_ID = "6a64af8e-7b8f-447b-bd81-fe4432b048c2"
PROJECT_REVISION = 27
EVENT_COUNT = 25
EVENT_HEAD = "9f9c987cac1d3dc15e5e9911f10bbebe0382034b278ff2c10d81d9563ba41354"
EVENT_STREAM_SHA256 = "4ed833b3a6f3382c4df4fb05909393916edaeb9ccec0016469d96dac8a295c7c"
REPLAY_STATE_HASH = "ae511d05a01fe0445e3f8aa04794efc815fbabcb4a45499e95ac4f4bb7044ded"
CONTENT_LOCK_HASH = "334a7fe393e99ea12ecf6db6c1d57e0fa9c220187d8e87f13d068173ed69b0bb"
OWNER_SHEET_SHA256 = "1258491740010cee4db25055bc24889c2ac26e14faf9d222bcef95426650800d"
COMPILER_ID = "TianxiaFoundry.CharacterCombatCompiler.C3A"
COMPILER_VERSION = "1.0.0"


@dataclass(frozen=True)
class CompilationResult:
    combat_sheet: CombatSheet
    static_validation: StaticValidationReport
    readiness: dict[str, Any]
    unsupported_coverage: dict[str, Any]
    execution_provenance: dict[str, Any]
    combat_build_manifest: dict[str, Any]
    output_package: Path | None
    output_package_sha256: str | None


def _canon_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.external_attr = 0o644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _sha_dict(files: dict[str, bytes]) -> dict[str, str]:
    return {name: sha256_bytes(data) for name, data in sorted(files.items())}


class CharacterCombatAdapter:
    """Typed C3A Character Package -> Combat Sheet adapter.

    The adapter consumes only sealed package JSON, the checksum-sealed mechanics
    lock, and the checksum-sealed primitive registry. It never parses display
    prose or creates encounter/runtime state.
    """

    def __init__(self, *, mechanics_lock: Path | None = None, primitive_registry: Path | None = None):
        authority_root = Path(__file__).resolve().parent / "character_authority"
        mechanics_lock = mechanics_lock or authority_root / "Tianxia_Fire_Qi_Executable_Mechanics_Lock_R1.json"
        primitive_registry = primitive_registry or authority_root / "Tianxia_Fire_Qi_Combat_Primitive_Registry_R1.json"
        self.lock_path = mechanics_lock.resolve()
        self.registry_path = primitive_registry.resolve()
        self.lock = ExecutableMechanicsLock.model_validate_json(self.lock_path.read_text(encoding="utf-8"))
        self.registry = PrimitiveRegistry.model_validate_json(self.registry_path.read_text(encoding="utf-8"))
        if self.lock.primitive_registry_sha256 != self.registry.registry_sha256:
            raise FoundryError("C3A_MECHANICS_REGISTRY_MISMATCH", "The mechanics lock does not match the primitive registry.")

    @staticmethod
    def _read_package(path: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
        audit = PortableCharacterPackageService.audit(path)
        with zipfile.ZipFile(path) as zf:
            files = {i.filename: zf.read(i.filename) for i in zf.infolist() if not i.is_dir()}
        return files, audit

    @staticmethod
    def _verify_source_identity(path: Path, files: dict[str, bytes], audit: dict[str, Any], *, require_exact_source_hash: bool) -> None:
        package_sha = sha256_file(path)
        if require_exact_source_hash and package_sha != SOURCE_PACKAGE_SHA256:
            raise FoundryError("SOURCE_IDENTITY_MISMATCH", "The portable Character package is stale or not the sealed C2C.1 source.", details={"expected": SOURCE_PACKAGE_SHA256, "actual": package_sha})
        manifest = audit["manifest"]
        expected = {
            "project_id": PROJECT_ID,
            "project_revision": PROJECT_REVISION,
            "event_count": EVENT_COUNT,
            "event_head_hash": EVENT_HEAD,
            "replay_state_hash": REPLAY_STATE_HASH,
            "content_lock_hash": CONTENT_LOCK_HASH,
        }
        mismatched = {k: {"expected": v, "actual": manifest.get(k)} for k, v in expected.items() if manifest.get(k) != v}
        if mismatched:
            raise FoundryError("SOURCE_IDENTITY_MISMATCH", "Canonical character identities do not match the C3A authority.", details=mismatched)
        if sha256_bytes(files["Tianxia_Owner_Character_Sheet_v1.json"]) != OWNER_SHEET_SHA256:
            raise FoundryError("SOURCE_IDENTITY_MISMATCH", "The canonical Owner Character Sheet changed.")
        with zipfile.ZipFile(io.BytesIO(files["source/Character_Project.tianxia-project.zip"])) as nested:
            events_sha = sha256_bytes(nested.read("events.json"))
        if events_sha != EVENT_STREAM_SHA256:
            raise FoundryError("SOURCE_IDENTITY_MISMATCH", "The canonical event stream changed.", details={"expected": EVENT_STREAM_SHA256, "actual": events_sha})

    def _validate_lock_coverage(self, files: dict[str, bytes]) -> None:
        selection = json.loads(files["Rules_Selection_Packets.json"])
        selected = {p.get("record_id") for p in selection.get("packets", []) if p.get("record_id")}
        classified_sources = {m.source.record_id for m in self.lock.mechanics} | {m.source.record_id for m in self.lock.classified_nonexecutables}
        required = {
            "tianxia.path.qi_cultivation",
            "tianxia.path.qi_cultivation.feature.qi_sensing",
            "tianxia.path.qi_cultivation.feature.meridian_regulation",
            "tianxia.path.qi_cultivation.feature.qi_cultivation_subpath",
            "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight",
            "tianxia.path.qi_cultivation.feature.qi_armor",
            "tianxia.subpath.qi.cinder_heart_cultivator.feature.cinder_touch",
            "FIRE_TAL_BURNING_WEAPON",
            "FIRE_TAL_FLAME_LASH",
            "FIRE_TAL_FIRE_WARD",
            "FIRE_TAL_COMBUSTIVE_STEP",
            "FIRE_TAL_HEAT_HAZE",
            "FIRE_TAL_FIREBALL_ART",
            "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE",
            "tianxia.origin_insight.street_hardened",
            "tianxia.sphere.fire",
            "tianxia.sphere.scoundrel",
        }
        missing_acquisition = sorted(required - selected - {"tianxia.subpath.qi.cinder_heart_cultivator.feature.cinder_touch"})
        missing_classification = sorted(required - classified_sources)
        if missing_acquisition or missing_classification:
            raise FoundryError("COMBAT_PROJECTION_INCOMPLETE", "Selected-record inventory is not fully classified.", details={"missing_acquisition": missing_acquisition, "missing_classification": missing_classification})

    @staticmethod
    def _stats(owner: dict[str, Any]) -> CombatantStats:
        ident = owner["identity"]
        stats = owner["ability_scores_and_statistics"]
        abilities = {row["ability"]: row["score"] for row in stats["abilities"]}
        skills = {row["skill"]: row["bonus"] for row in stats.get("skills", [])}
        # Qi Cultivation grants no saving-throw proficiencies. Values are base modifiers.
        saving_throws = {k: (v - 10) // 2 for k, v in abilities.items()}
        return CombatantStats(
            cultivation_level=ident["cultivation_level"], realm=ident["realm_display"], species=ident["species"],
            creature_type=ident["creature_type"], size=ident["size"], ability_scores=abilities,
            proficiency_bonus=ident["proficiency_bonus"], hit_points_maximum=stats["hit_points"]["maximum"],
            armor_class=stats["armor_class"]["value"], initiative_bonus=stats["initiative"]["bonus"],
            speed_ft=stats["speed"]["walking_ft"], technique_attack_bonus=stats["technique_attack_bonus"],
            technique_save_dc=stats["technique_save_dc"], saving_throws=saving_throws, skills=skills,
        )

    def _sheet(self, package_sha: str, files: dict[str, bytes], audit: dict[str, Any]) -> CombatSheet:
        owner = json.loads(files["Tianxia_Owner_Character_Sheet_v1.json"])
        manifest = audit["manifest"]
        groups = {kind: tuple(m.model_dump(mode="json") for m in self.lock.mechanics if m.mechanic_kind == kind) for kind in ("ACTION", "REACTION", "AUGMENT", "PASSIVE", "RESOURCE")}
        base = {
            "schema_version": "TianxiaFoundry.CombatSheet.v1",
            "combat_sheet_id": f"combat_sheet:{PROJECT_ID}", "combat_sheet_version": "1.0.0", "source_adapter": "CharacterCombatAdapter.v1",
            "character_id": PROJECT_ID, "display_name": owner["identity"]["display_name"],
            "source_portable_package_sha256": package_sha, "source_project_id": PROJECT_ID, "source_project_revision": PROJECT_REVISION,
            "source_event_head": EVENT_HEAD, "source_event_stream_sha256": EVENT_STREAM_SHA256, "source_replay_state_hash": REPLAY_STATE_HASH,
            "source_content_lock_hash": CONTENT_LOCK_HASH,
            "source_authority_identities": owner.get("authority_and_artifact_identity") or {},
            "source_projection_identity": {"owner_sheet_sha256": OWNER_SHEET_SHA256, "canonical_project_hash": manifest.get("canonical_project_hash")},
            "source_factory_build_identity": {"factory": "HF05ZVK-R1H", "core_pack": "tianxia.core.factory.hf05zvk.r1h.phase2i.hf2@2.9.3"},
            "mechanics_lock_identity": {"lock_id": self.lock.lock_id, "lock_sha256": self.lock.lock_sha256, "primitive_registry_sha256": self.registry.registry_sha256},
            "combat_compiler_identity": {"compiler_id": COMPILER_ID, "compiler_version": COMPILER_VERSION, "engine_api_version": self.registry.engine_api_version},
            "readiness_status": "COMBAT_READY", "readiness_diagnostics": (), "combatant_stats": self._stats(owner).model_dump(mode="json"), "action_economy": ActionEconomy(movement_ft_per_turn=30).model_dump(mode="json"),
            "actions": groups["ACTION"], "reactions": groups["REACTION"], "augments": groups["AUGMENT"], "passives": groups["PASSIVE"], "resources": groups["RESOURCE"],
            "movement": {"walking_speed_ft": 30, "grid_increment_ft": 5, "flight": False, "teleport": False},
            "conditions": tuple(self.registry.conditions), "concentration": {"supported": True, "maximum_simultaneous": 1},
            "zones_terrain_capabilities": ("fire_terrain", "conflagration_fire_terrain", "existing_conflagration_heat_haze_modifier"), "companions": (),
            "controller_policy_compatibility": {"compatible_with_existing_controller_contracts": True, "controller_created": False, "controller_registered": False},
            "execution_provenance": {"compiled_from_typed_lock_only": True, "display_prose_parsed": False, "encounter_created": False, "combat_executed": False},
            "unsupported_coverage": (), "combat_events_committed": 0, "dice_rolled": 0, "encounter_created": False, "controller_selected": False,
        }
        base["sheet_commitment_sha256"] = canonical_sha256(base)
        return CombatSheet.model_validate(base)

    def static_validate(self, sheet: CombatSheet) -> StaticValidationReport:
        known_primitives = {row.primitive_id for row in self.registry.primitives}
        known_conditions = set(self.registry.conditions)
        known_events = set(self.registry.event_types)
        known_targets = set(self.registry.target_domains)
        known_formulas = set(self.registry.formula_kinds)
        diagnostics: list[dict[str, Any]] = []
        primitive_count = formula_count = target_count = condition_count = event_count = 0
        mechanics = [m for group in (sheet.actions, sheet.reactions, sheet.augments, sheet.passives, sheet.resources) for m in group]
        for mechanic in mechanics:
            for primitive in mechanic.required_primitives:
                primitive_count += 1
                if primitive not in known_primitives:
                    diagnostics.append({"code": "UNKNOWN_PRIMITIVE", "mechanic": mechanic.stable_id, "value": primitive})
            for target in mechanic.targets.domains:
                target_count += 1
                if target not in known_targets:
                    diagnostics.append({"code": "UNKNOWN_TARGET_DOMAIN", "mechanic": mechanic.stable_id, "value": target})
            for condition in mechanic.conditions:
                condition_count += 1
                if condition not in known_conditions:
                    diagnostics.append({"code": "UNKNOWN_CONDITION", "mechanic": mechanic.stable_id, "value": condition})
            for event in mechanic.event_emission:
                event_count += 1
                if event not in known_events:
                    diagnostics.append({"code": "UNKNOWN_EVENT_TYPE", "mechanic": mechanic.stable_id, "value": event})
            if mechanic.formula:
                formula_count += 1
                if mechanic.formula.get("kind") not in known_formulas:
                    diagnostics.append({"code": "UNKNOWN_FORMULA_KIND", "mechanic": mechanic.stable_id, "value": mechanic.formula.get("kind")})
            if mechanic.resource_cost and int(mechanic.resource_cost.get("amount", 0)) < 0:
                diagnostics.append({"code": "RESOURCE_UNDERFLOW_CONTRACT", "mechanic": mechanic.stable_id})
            if mechanic.execution_provenance.get("runtime_prose_parsing") is not False:
                diagnostics.append({"code": "PROSE_INTERPRETATION_FORBIDDEN", "mechanic": mechanic.stable_id})
        report = {
            "schema_version": "TianxiaFoundry.C3AStaticExecutionValidation.v1", "status": "PASS" if not diagnostics else "FAIL",
            "combat_sheet_commitment_sha256": sheet.sheet_commitment_sha256, "mechanics_checked": len(mechanics),
            "primitive_references_checked": primitive_count, "formula_contracts_checked": formula_count, "target_contracts_checked": target_count,
            "condition_references_checked": condition_count, "event_type_references_checked": event_count,
            "unresolved_placeholders": (), "prose_interpretation_used": False, "combat_events_committed": 0, "dice_rolled": 0,
            "diagnostics": tuple(diagnostics),
        }
        validated = StaticValidationReport.model_validate(report)
        if validated.status != "PASS":
            raise FoundryError("UNSUPPORTED_MECHANICS", "The Combat Sheet failed static execution validation.", details=validated.model_dump(mode="json"))
        return validated

    @staticmethod
    def _artifact_payloads(sheet: CombatSheet, validation: StaticValidationReport, lock: ExecutableMechanicsLock, registry: PrimitiveRegistry) -> dict[str, bytes]:
        readiness = {
            "schema_version": "TianxiaFoundry.CombatReadiness.v1", "status": "COMBAT_READY", "advancement": "ADVANCEMENT_READY",
            "character_sheet": "CHARACTER_SHEET_READY", "gm_screen": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED", "combat": "COMBAT_READY",
            "encounter": "NOT_ATTEMPTED", "controller_selection": "NOT_ATTEMPTED", "native_or_interactive_acceptance": "NOT_RUN",
            "diagnostics": [], "combat_events_committed": 0, "dice_rolled": 0,
        }
        unsupported = {"schema_version": "TianxiaFoundry.UnsupportedCombatCoverage.v1", "status": "COMPLETE", "material_blockers": [], "display_only": ["Analyze Qi", "Hidden Tool Cache"], "encounter_time_requirements": ["Set current Qi without using package build-state current as encounter authority.", "Set Martial Focus current value from encounter authority."]}
        provenance = {"schema_version": "TianxiaFoundry.CombatExecutionProvenance.v1", "adapter": "CharacterCombatAdapter.v1", "compiler": f"{COMPILER_ID}@{COMPILER_VERSION}", "mechanics_lock_sha256": lock.lock_sha256, "primitive_registry_sha256": registry.registry_sha256, "source_package_sha256": sheet.source_portable_package_sha256, "typed_data_only": True, "runtime_prose_parsing": False, "encounter_created": False, "combat_executed": False, "combat_events_committed": 0, "dice_rolled": 0}
        payloads = {
            "combat/Combat_Sheet.json": _canon_bytes(sheet.model_dump(mode="json")),
            "combat/Combat_Readiness.json": _canon_bytes(readiness),
            "combat/Executable_Mechanics_Lock.json": _canon_bytes(lock.model_dump(mode="json")),
            "combat/Primitive_Registry.json": _canon_bytes(registry.model_dump(mode="json")),
            "combat/Execution_Provenance.json": _canon_bytes(provenance),
            "combat/Unsupported_Coverage.json": _canon_bytes(unsupported),
            "combat/Static_Execution_Validation.json": _canon_bytes(validation.model_dump(mode="json")),
        }
        build_manifest = {"schema_version": "TianxiaFoundry.CombatBuildManifest.v1", "compiler_id": COMPILER_ID, "compiler_version": COMPILER_VERSION, "source_package_sha256": sheet.source_portable_package_sha256, "combat_sheet_commitment_sha256": sheet.sheet_commitment_sha256, "readiness": "COMBAT_READY", "files": [{"path": name, "sha256": sha256_bytes(data), "bytes": len(data)} for name, data in sorted(payloads.items())], "encounter_created": False, "combat_executed": False}
        payloads["combat/Combat_Build_Manifest.json"] = _canon_bytes(build_manifest)
        return payloads

    @staticmethod
    def _build_package(source_files: dict[str, bytes], payloads: dict[str, bytes], output: Path) -> None:
        files = {k: v for k, v in source_files.items() if k != "SHA256SUMS.txt"}
        files.update(payloads)
        readiness = json.loads(files["READINESS.json"])
        readiness.update({"combat": "COMBAT_READY", "encounter": "NOT_ATTEMPTED", "controller_selection": "NOT_ATTEMPTED", "native_or_interactive_acceptance": "NOT_RUN", "cpk1_schemas_registered": False})
        files["READINESS.json"] = _canon_bytes(readiness)
        if "Release_Gate_Manifest.json" in files:
            gate = json.loads(files["Release_Gate_Manifest.json"])
            gate.update({"classification": "C3A_COMBAT_SHEET_READY", "evidence_boundary": "static_combat_compilation", "combat": "COMBAT_READY", "encounter": "NOT_ATTEMPTED", "controller_selection": "NOT_ATTEMPTED"})
            files["Release_Gate_Manifest.json"] = _canon_bytes(gate)
        package_manifest = json.loads(files["PACKAGE_MANIFEST.json"])
        package_manifest.update({"package_role": "portable_completed_character_combat_ready", "combat_execution": "STATIC_COMBAT_COMPILATION_ONLY", "combat_readiness": "COMBAT_READY", "combat_sheet_path": "combat/Combat_Sheet.json", "mechanics_lock_path": "combat/Executable_Mechanics_Lock.json", "encounter": "NOT_ATTEMPTED", "controller_selection": "NOT_ATTEMPTED", "cpk1_schemas_registered": False})
        package_manifest["files"] = []
        for name, data in sorted(files.items()):
            if name != "PACKAGE_MANIFEST.json":
                package_manifest["files"].append({"path": name, "sha256": sha256_bytes(data), "bytes": len(data)})
        files["PACKAGE_MANIFEST.json"] = _canon_bytes(package_manifest)
        files["SHA256SUMS.txt"] = "".join(f"{sha256_bytes(data)}  {name}\n" for name, data in sorted(files.items())).encode("utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for name, data in sorted(files.items()):
                zf.writestr(_zip_info(name), data)
        PortableCharacterPackageService.audit(output)

    def compile(self, package: Path, *, output_dir: Path | None = None, output_package: Path | None = None, require_exact_source_hash: bool = True) -> CompilationResult:
        package = package.resolve()
        files, audit = self._read_package(package)
        self._verify_source_identity(package, files, audit, require_exact_source_hash=require_exact_source_hash)
        self._validate_lock_coverage(files)
        package_sha = sha256_file(package)
        sheet = self._sheet(package_sha, files, audit)
        validation = self.static_validate(sheet)
        payloads = self._artifact_payloads(sheet, validation, self.lock, self.registry)
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            for name, data in payloads.items():
                target = output_dir / Path(name).name
                target.write_bytes(data)
        package_sha_out = None
        if output_package:
            self._build_package(files, payloads, output_package)
            package_sha_out = sha256_file(output_package)
        readiness = json.loads(payloads["combat/Combat_Readiness.json"])
        unsupported = json.loads(payloads["combat/Unsupported_Coverage.json"])
        provenance = json.loads(payloads["combat/Execution_Provenance.json"])
        build_manifest = json.loads(payloads["combat/Combat_Build_Manifest.json"])
        return CompilationResult(sheet, validation, readiness, unsupported, provenance, build_manifest, output_package, package_sha_out)
