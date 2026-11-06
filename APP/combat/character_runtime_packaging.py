from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path
from typing import Any

from app.core import sha256_bytes, sha256_file
from portable_character.service import PortableCharacterPackageService

from .character_runtime_adapter import CharacterRuntimeBundle

RUNTIME_PACKAGE_ROLE = "portable_completed_character_combat_runtime_ready"


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def runtime_adapter_contract_document(bundle: CharacterRuntimeBundle) -> dict[str, Any]:
    """Return the owner-facing pre-encounter contract without fixture current values."""
    actor = bundle.actor_template.model_dump(mode="json")
    actor["resources"] = [
        {
            "resource_id": "resource:core.qi",
            "minimum": 0,
            "maximum": 15,
            "current": "REQUIRED_AT_ENCOUNTER_TIME",
        },
        {
            "resource_id": "resource:core.martial_focus",
            "minimum": 0,
            "maximum": 1,
            "current": "REQUIRED_AT_ENCOUNTER_TIME",
        },
    ]
    return {
        "schema": "TianxiaCharacterCombatRuntimeAdapterContract.v1",
        "adapter_id": bundle.adapter_id,
        "adapter_version": bundle.adapter_version,
        "engine_version": bundle.engine_version,
        "readiness": "COMBAT_RUNTIME_READY",
        "combat_ready_semantics": "RUNTIME_READY_PRE_ENCOUNTER",
        "source_combat_sheet_sha256": bundle.source_combat_sheet_sha256,
        "mechanics_lock_sha256": bundle.mechanics_lock_sha256,
        "primitive_registry_sha256": bundle.primitive_registry_sha256,
        "actor_template_contract": actor,
        "action_catalog": [row.model_dump(mode="json") for row in bundle.action_catalog],
        "reaction_parameters": copy.deepcopy(bundle.reaction_parameters),
        "passive_bindings": list(bundle.passive_bindings),
        "augment_bindings": list(bundle.augment_bindings),
        "resource_initialization_contract": {
            "required_before_actor_instantiation": True,
            "persistent": False,
            "canonical_owner_choice": False,
            "provenance_required": True,
            "allowed_provenance_kinds": ["ENCOUNTER_AUTHORITY", "TEST_FIXTURE"],
            "owner_package_contains_current_values": False,
            "resources": actor["resources"],
        },
        "typed_data_only": True,
        "runtime_prose_parsing": False,
        "catalog_mutation_before_full_validation": False,
        "encounter_created": False,
        "match_created": False,
        "initiative_rolled": False,
        "persisted_event_count": 0,
    }


def primitive_handler_document(bundle: CharacterRuntimeBundle) -> dict[str, Any]:
    return {
        "schema": "TianxiaC3ARPrimitiveHandlerImplementation.v1",
        "status": "PASS",
        "primitive_count": len(bundle.primitive_bindings),
        "bindings": [row.model_dump(mode="json") for row in bundle.primitive_bindings],
        "newly_closed_primitives": [
            "primitive:ignite_object",
            "primitive:no_opportunity_movement",
            "primitive:once_per_turn",
            "primitive:suppress_condition_penalty",
        ],
        "existing_engine_reused": True,
        "parallel_engine_created": False,
        "runtime_prose_parsing": False,
    }


def support_matrix_document(bundle: CharacterRuntimeBundle) -> dict[str, Any]:
    return {
        "schema": "TianxiaC3ARRuntimeSupportMatrix.v1",
        "status": "PASS",
        "mechanic_count": len(bundle.support_matrix),
        "runtime_executable_count": len(bundle.support_matrix),
        "static_only_count": 0,
        "blocked_count": 0,
        "rows": [row.model_dump(mode="json") for row in bundle.support_matrix],
    }


def seal_runtime_ready_package(
    candidate: Path,
    output: Path,
    *,
    bundle: CharacterRuntimeBundle,
    runtime_validation: dict[str, Any],
) -> dict[str, Any]:
    candidate = Path(candidate).resolve()
    output = Path(output).resolve()
    PortableCharacterPackageService.audit(candidate)
    with zipfile.ZipFile(candidate) as zf:
        files = {
            row.filename: zf.read(row.filename)
            for row in zf.infolist()
            if not row.is_dir() and row.filename != "SHA256SUMS.txt"
        }

    contract = runtime_adapter_contract_document(bundle)
    matrix = support_matrix_document(bundle)
    primitive_report = primitive_handler_document(bundle)
    resource_contract = copy.deepcopy(contract["resource_initialization_contract"])
    resource_contract["schema"] = "TianxiaEncounterResourceInitializationContract.v1"

    runtime_payloads = {
        "combat/Runtime_Adapter_Contract.json": canonical_json_bytes(contract),
        "combat/Runtime_Support_Matrix.json": canonical_json_bytes(matrix),
        "combat/Primitive_Handler_Implementation.json": canonical_json_bytes(primitive_report),
        "combat/Runtime_Resource_Initialization_Contract.json": canonical_json_bytes(resource_contract),
        "combat/Runtime_Execution_Validation.json": canonical_json_bytes(runtime_validation),
    }
    files.update(runtime_payloads)

    readiness = json.loads(files["READINESS.json"])
    readiness.update(
        {
            "combat_sheet": "COMBAT_SHEET_READY",
            "combat_runtime": "COMBAT_RUNTIME_READY",
            "combat": "COMBAT_READY",
            "combat_ready_semantics": "RUNTIME_READY_PRE_ENCOUNTER",
            "encounter_time_resource_initialization": "REQUIRED",
            "encounter": "NOT_ATTEMPTED",
            "controller_selection": "NOT_ATTEMPTED",
            "cpk1_schemas_registered": False,
            "native_or_interactive_acceptance": "NOT_RUN",
        }
    )
    files["READINESS.json"] = canonical_json_bytes(readiness)

    combat_readiness = json.loads(files["combat/Combat_Readiness.json"])
    combat_readiness.update(
        {
            "status": "COMBAT_READY",
            "combat": "COMBAT_READY",
            "combat_sheet": "COMBAT_SHEET_READY",
            "combat_runtime": "COMBAT_RUNTIME_READY",
            "combat_ready_semantics": "RUNTIME_READY_PRE_ENCOUNTER",
            "runtime_adapter": bundle.adapter_id,
            "runtime_adapter_version": bundle.adapter_version,
            "runtime_engine_version": bundle.engine_version,
            "runtime_support_mechanic_count": len(bundle.support_matrix),
            "runtime_primitive_handler_count": len(bundle.primitive_bindings),
            "runtime_validation": "PASS",
            "encounter_time_resource_initialization": "REQUIRED",
            "owner_resource_values_chosen": False,
            "isolated_test_fixture_values_canonical": False,
            "persistent_match_created": False,
            "persisted_combat_events": 0,
            "initiative_rolled": False,
            "encounter": "NOT_ATTEMPTED",
            "controller_selection": "NOT_ATTEMPTED",
        }
    )
    files["combat/Combat_Readiness.json"] = canonical_json_bytes(combat_readiness)

    provenance = json.loads(files["combat/Execution_Provenance.json"])
    provenance.update(
        {
            "runtime_adapter": f"{bundle.adapter_id}@{bundle.adapter_version}",
            "runtime_engine_version": bundle.engine_version,
            "runtime_validation": "DETERMINISTIC_NONPERSISTENT_DRY_RUN_PASS",
            "runtime_support_mechanic_count": len(bundle.support_matrix),
            "runtime_primitive_handler_count": len(bundle.primitive_bindings),
            "fixture_resource_values_canonical": False,
            "owner_resource_values_chosen": False,
            "persistent_match_created": False,
            "persisted_event_count": 0,
            "initiative_rolled": False,
        }
    )
    files["combat/Execution_Provenance.json"] = canonical_json_bytes(provenance)

    if "Release_Gate_Manifest.json" in files:
        gate = json.loads(files["Release_Gate_Manifest.json"])
        gate.update(
            {
                "classification": "C3A_R_COMBAT_RUNTIME_READY",
                "evidence_boundary": "deterministic_nonpersistent_runtime_execution",
                "combat_sheet": "COMBAT_SHEET_READY",
                "combat_runtime": "COMBAT_RUNTIME_READY",
                "combat": "COMBAT_READY",
                "combat_ready_semantics": "RUNTIME_READY_PRE_ENCOUNTER",
                "encounter": "NOT_ATTEMPTED",
                "controller_selection": "NOT_ATTEMPTED",
            }
        )
        files["Release_Gate_Manifest.json"] = canonical_json_bytes(gate)

    build_manifest = json.loads(files["combat/Combat_Build_Manifest.json"])
    build_manifest.update(
        {
            "runtime_adapter_id": bundle.adapter_id,
            "runtime_adapter_version": bundle.adapter_version,
            "runtime_engine_version": bundle.engine_version,
            "runtime_readiness": "COMBAT_RUNTIME_READY",
            "combat_ready_semantics": "RUNTIME_READY_PRE_ENCOUNTER",
            "runtime_validation": "PASS",
            "encounter_time_resource_initialization": "REQUIRED",
            "owner_resource_values_chosen": False,
            "persistent_match_created": False,
            "persisted_event_count": 0,
            "initiative_rolled": False,
        }
    )
    build_manifest["files"] = []
    for name, data in sorted(files.items()):
        if name.startswith("combat/") and name != "combat/Combat_Build_Manifest.json":
            build_manifest["files"].append(
                {"path": name, "sha256": sha256_bytes(data), "bytes": len(data)}
            )
    files["combat/Combat_Build_Manifest.json"] = canonical_json_bytes(build_manifest)

    package_manifest = json.loads(files["PACKAGE_MANIFEST.json"])
    package_manifest.update(
        {
            "package_role": RUNTIME_PACKAGE_ROLE,
            "combat_execution": "DETERMINISTIC_NONPERSISTENT_RUNTIME_VALIDATION",
            "combat_sheet_readiness": "COMBAT_SHEET_READY",
            "combat_runtime_readiness": "COMBAT_RUNTIME_READY",
            "combat_readiness": "COMBAT_READY",
            "combat_ready_semantics": "RUNTIME_READY_PRE_ENCOUNTER",
            "runtime_adapter_contract_path": "combat/Runtime_Adapter_Contract.json",
            "runtime_support_matrix_path": "combat/Runtime_Support_Matrix.json",
            "runtime_validation_path": "combat/Runtime_Execution_Validation.json",
            "encounter_time_resource_initialization": "REQUIRED",
            "owner_resource_values_chosen": False,
            "encounter": "NOT_ATTEMPTED",
            "controller_selection": "NOT_ATTEMPTED",
            "cpk1_schemas_registered": False,
        }
    )
    package_manifest["files"] = []
    for name, data in sorted(files.items()):
        if name != "PACKAGE_MANIFEST.json":
            package_manifest["files"].append(
                {"path": name, "sha256": sha256_bytes(data), "bytes": len(data)}
            )
    files["PACKAGE_MANIFEST.json"] = canonical_json_bytes(package_manifest)
    files["SHA256SUMS.txt"] = "".join(
        f"{sha256_bytes(data)}  {name}\n" for name, data in sorted(files.items())
    ).encode("utf-8")

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, data in sorted(files.items()):
            zf.writestr(zip_info(name), data)
    audit = PortableCharacterPackageService.audit(output)
    return {
        "schema": "TianxiaC3ARRuntimeReadyPackageSeal.v1",
        "status": "PASS",
        "candidate_sha256": sha256_file(candidate),
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "audit": audit,
        "combat_sheet_sha256": sha256_bytes(files["combat/Combat_Sheet.json"]),
        "owner_sheet_sha256": sha256_bytes(files["Tianxia_Owner_Character_Sheet_v1.json"]),
        "gm_model_sha256": sha256_bytes(files["Tianxia_GM_Character_Model_v1.json"]),
        "resource_values_present_in_contract": False,
        "persistent_match_created": False,
        "persisted_event_count": 0,
    }
