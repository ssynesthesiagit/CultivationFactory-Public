from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core import FoundryError, sha256_file, sha256_json
from contracts.canonical import canonical_event_hash
from sphere_component_authority import normalize_sphere_automatic_components
from stage2.formulas import FormulaError, evaluate_formula

ZERO_HASH = "0" * 64
V3 = "TianxiaFoundry.AdvancementEvent.v3"


def _read_sealed(path: Path, *, schema_version: str, mismatch_code: str) -> dict[str, Any]:
    if not path.is_file():
        raise FoundryError(mismatch_code, "A required sealed C2A-R.1 authority file is missing.", details={"path": str(path)})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FoundryError(mismatch_code, "A required sealed C2A-R.1 authority file is unreadable.", details={"path": str(path), "error": str(exc)}) from exc
    if value.get("schema_version") != schema_version:
        raise FoundryError(mismatch_code, "A required C2A-R.1 authority file declares an unsupported schema.", details={"path": str(path), "schema_version": value.get("schema_version")})
    seal = value.get("seal_sha256")
    unsigned = {key: item for key, item in value.items() if key != "seal_sha256"}
    if seal != sha256_json(unsigned):
        raise FoundryError(mismatch_code, "A required C2A-R.1 authority file failed its canonical seal.", details={"path": str(path)})
    return value


def _locks(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for lock in project.get("user_locks") or []:
        field = lock.get("field")
        if isinstance(field, str):
            result[field] = lock
    return result


def _display(record: dict[str, Any]) -> tuple[str, str]:
    projection = record.get("display_projection") or {}
    short = projection.get("short_description")
    full = projection.get("full_description")
    name = record.get("display_name") or record.get("name") or record.get("record_id")
    if not isinstance(short, str) or not short.strip():
        short = str(name)
    if not isinstance(full, str) or not full.strip():
        full = short
    return short.strip(), full.strip()


def _packet_id(event: dict[str, Any]) -> str:
    return f"packet.stage2.{int(event['sequence']):03d}.{event['event_hash'][:16]}"


def _event_provenance(event: dict[str, Any], record: dict[str, Any], contract: dict[str, Any], destinations: list[str], transformation: str) -> dict[str, Any]:
    binding = event["content_binding"]
    sources = deepcopy(event.get("source_evidence") or [])
    stage2 = (record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
    return {
        "provenance_unit": "canonical_advancement_event",
        "event_id": event["event_id"],
        "event_hash": event["event_hash"],
        "event_sequence": event["sequence"],
        "record_id": record["record_id"],
        "record_hash": record["record_hash"],
        "pack_id": binding["pack_id"],
        "pack_version": binding["pack_version"],
        "pack_hash": binding["pack_hash"],
        "canonical_sources": sources,
        "stage2_rule_id": event["advancement"]["calculation"]["rule_id"],
        "projection_contract_id": contract["contract_id"],
        "projection_contract_hash": sha256_json({k: v for k, v in contract.items() if k != "seal_sha256"}),
        "stage2_normalization_authority": deepcopy(contract["stage2_authority_pack"]),
        "exact_source_map": deepcopy(contract["exact_source_map"]),
        "destination_pointers": sorted(destinations),
        "transformation_kind": transformation,
        "authority_complete": stage2.get("authority_complete") is True,
    }


def _lock_provenance(lock: dict[str, Any], fixture_path: Path, destinations: list[str], transformation: str) -> dict[str, Any]:
    return {
        "provenance_unit": "owner_project_lock",
        "lock_id": lock["lock_id"],
        "lock_field": lock["field"],
        "created_revision": lock["created_revision"],
        "source": lock.get("source", "local-user"),
        "fixture_contract_sha256": sha256_file(fixture_path),
        "destination_pointers": sorted(destinations),
        "transformation_kind": transformation,
    }


def _baseline_provenance(rule: dict[str, Any], pack: dict[str, Any], pack_path: Path, destinations: list[str], trace: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "provenance_unit": "core_character_baseline_rule",
        "rule_id": rule["rule_id"],
        "authority_classification": rule["authority_classification"],
        "source": deepcopy(rule["source"]),
        "baseline_pack_id": pack["pack_id"],
        "baseline_pack_version": pack["version"],
        "baseline_pack_sha256": sha256_file(pack_path),
        "destination_pointers": sorted(destinations),
        "transformation_kind": "DIRECT_TYPED_VALUE" if "typed_value" in rule else "SAFE_FORMULA_EVALUATION",
    }
    if trace is not None:
        result["formula_trace"] = trace
    return result


def _capability_entry(record: dict[str, Any], selected_at_cl: int, event: dict[str, Any]) -> dict[str, Any]:
    record_id = record["record_id"]
    content_type = record.get("content_type", "unknown")
    _, full = _display(record)
    is_executable_surface = content_type in {"talent", "path_feature", "subpath_feature", "origin_insight"}
    combat = "UNSUPPORTED" if is_executable_surface else "NOT_APPLICABLE"
    ai = "BLOCKED_BY_DEPENDENCY" if is_executable_surface else "NOT_APPLICABLE"
    surfaces: list[str] = []
    lowered = full.lower()
    for label, terms in {
        "BURN": ("burn", "burning"),
        "FIRE_TERRAIN": ("fire terrain", "terrain"),
        "REACTION": ("reaction",),
        "CONCENTRATION": ("concentration",),
        "MOVEMENT": ("move", "push", "pull", "speed"),
        "DAMAGE_PREVENTION": ("reduce damage", "prevent damage"),
        "RESOURCE": (" qi", "cost:"),
        "MODIFIER": ("advantage", "+3 ac", "bonus"),
        "PROCEDURE": ("trigger:", "save", "attack roll"),
    }.items():
        if any(term in lowered for term in terms):
            surfaces.append(label)
    return {
        "record_id": record_id,
        "record_hash": record["record_hash"],
        "record_type": content_type,
        "selected_at_cl": selected_at_cl,
        "event_id": event["event_id"],
        "coverage": {
            "advancement": "SUPPORTED",
            "character_sheet": "PARTIAL" if is_executable_surface else "SUPPORTED",
            "gm_display": "PARTIAL" if is_executable_surface else "SUPPORTED",
            "combat_execution": combat,
            "ai_policy": ai,
        },
        "demonstrated_surfaces": sorted(set(surfaces)),
        "display_only_not_execution_authority": is_executable_surface,
    }


def _dynamic_display_section(record: dict[str, Any], packets: list[dict[str, Any]]) -> tuple[str, str]:
    content_type = str(record.get("content_type") or "")
    record_id = str(record.get("record_id") or "")
    kinds = {str(packet.get("advancement_kind") or "") for packet in packets}
    if record_id.startswith("tianxia.c1a.none."):
        return "explicit_none", "Explicit None"
    if content_type == "source_document":
        return "source_authority", "Authority Source"
    if content_type in {"background", "origin_insight"}:
        return "background_origin", "Background" if content_type == "background" else "Origin Insight"
    if content_type in {"path", "subpath"}:
        return "path_subpath", content_type.replace("_", " ").title()
    if content_type == "sphere":
        return "spheres", "Sphere"
    if content_type == "cultivation_insight":
        return "insights", "Insight"
    if content_type == "talent":
        if "background_talent_acquisition" in kinds:
            return "background_talent", "Background Talent"
        return "talents", "Talent"
    if content_type == "path_feature" and "ability_score_change" in kinds:
        return "advancement_features", "Path Feature"
    if content_type in {"path_feature", "subpath_feature"}:
        return "path_features", content_type.replace("_", " ").title()
    return "other", content_type.replace("_", " ").title() or "Selected Record"


def _component_display_source(component: dict[str, Any], parent_source: dict[str, Any], parent_record_id: str) -> dict[str, str]:
    """Map the CAT3 source-matrix identity to the sheet display-source shape."""
    source = component.get("source") if isinstance(component.get("source"), dict) else {}
    path = source.get("path") or source.get("source_path") or parent_source.get("path")
    anchor = source.get("anchor") or source.get("source_anchor") or f"{parent_source.get('anchor', parent_record_id)}:{component.get('component_id')}"
    source_hash = (
        source.get("source_hash")
        or source.get("source_file_sha256")
        or source.get("compendium_sha256")
        or parent_source.get("source_hash")
    )
    if not all(isinstance(value, str) and value for value in (path, anchor, source_hash)):
        raise FoundryError(
            "CHARACTER_SHEET_DESCRIPTION_UNPROVEN",
            "A Sphere automatic component lacks exact source identity.",
            details={"parent_sphere_id": parent_record_id, "component_id": component.get("component_id"), "source": source},
        )
    return {"path": path, "anchor": anchor, "source_hash": source_hash}


def _sphere_record_with_event_authority(record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Bind the immutable compiled Sphere packet to the locked display record.

    Some project-lock adapters retain the CAT3 packet only in the event's
    calculation output, while others retain it in the raw catalog record.
    The event packet is already normalized and content-bound by Stage 2, so
    using it here keeps projector output independent of that storage detail.
    """
    packet = (
        (event.get("advancement") or {})
        .get("calculation", {})
        .get("outputs", {})
        .get("automatic_component_authority")
    )
    if not isinstance(packet, dict):
        return record
    result = deepcopy(record)
    result["automatic_component_authority"] = deepcopy(packet)
    return result


def _dynamic_display_contract(
    project: dict[str, Any],
    choice_snapshot: dict[str, Any],
    locked_records: dict[str, dict[str, Any]],
    packets: list[dict[str, Any]],
    granted_ids: list[str],
    subpath_packet_id: str,
) -> dict[str, Any]:
    packets_by_record: dict[str, list[dict[str, Any]]] = {}
    for packet in packets:
        packets_by_record.setdefault(str(packet["record_id"]), []).append(packet)
    required_ids = set(packets_by_record) | set(granted_ids)
    rules: list[dict[str, Any]] = []
    automatic_component_ids: set[str] = set()
    for record_id in sorted(required_ids):
        record = locked_records.get(record_id)
        if not record:
            raise FoundryError(
                "CHARACTER_SHEET_DISPLAY_AUTHORITY_MISSING",
                "A selected record lacks its locked typed catalog snapshot.",
                details={"record_id": record_id},
            )
        record_packets = sorted(packets_by_record.get(record_id) or [], key=lambda row: int(row.get("sequence") or 0))
        binding_packet = next(
            (packet for packet in record_packets if packet.get("advancement_kind") == "level_advance"),
            record_packets[0] if record_packets else None,
        )
        if binding_packet is None:
            binding_packet = {
                "packet_id": subpath_packet_id,
                "target_cl": 3,
                "advancement_kind": "source_granted_subpath_feature",
            }
        short, full = _display(record)
        source = deepcopy(record.get("source") or {})
        if not all(isinstance(source.get(key), str) and source.get(key) for key in ("path", "anchor", "source_hash")):
            raise FoundryError(
                "CHARACTER_SHEET_DESCRIPTION_UNPROVEN",
                "A selected typed catalog record lacks exact source identity.",
                details={"record_id": record_id},
            )
        section, subsection = _dynamic_display_section(record, record_packets)
        content_type = str(record.get("content_type") or "")
        executable = content_type in {"talent", "path_feature", "subpath_feature", "origin_insight"}
        stage2 = ((record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {})
        rule = {
            "record_id": record_id,
            "record_hash": record["record_hash"],
            "display_name": record.get("display_name") or record_id,
            "section": section,
            "subsection": subsection,
            "one_line_description": short,
            "full_description": full,
            "full_description_source": "locked_typed_catalog_record",
            "source": source,
            "acquisition_source": {
                "target_cl": binding_packet.get("target_cl"),
                "advancement_kind": binding_packet.get("advancement_kind"),
                "packet_ids": [binding_packet["packet_id"]],
            },
            "stage2_rule_id": stage2.get("rule_id"),
            "display_timing_or_category": None,
            "capabilities": {
                "character_sheet": "SUPPORTED",
                "gm_display": "NOT_ATTEMPTED",
                "combat_execution": "UNSUPPORTED" if executable else "NOT_APPLICABLE",
                "ai_policy": "BLOCKED_BY_DEPENDENCY" if executable else "NOT_APPLICABLE",
            },
            "display_only_not_execution_authority": executable,
        }
        if content_type == "sphere":
            sphere_packet = normalize_sphere_automatic_components(record)
            rule["automatic_component_authority"] = sphere_packet
            for component in sphere_packet["components"]:
                component_id = component["component_id"]
                if component_id in automatic_component_ids:
                    raise FoundryError(
                        "CHARACTER_SHEET_DUPLICATE_DISPLAY_MAPPING",
                        "A Sphere automatic component ID is attached to more than one display mapping.",
                        details={"component_id": component_id},
                    )
                automatic_component_ids.add(component_id)
                component_source = _component_display_source(component, source, record_id)
                component_text = str(component["player_rules_text"]).strip()
                component_rule = {
                    "record_id": component_id,
                    "record_hash": component["component_hash"],
                    "display_name": component.get("display_name") or component_id,
                    "section": "sphere_automatic_components",
                    "subsection": f"{record.get('display_name') or record_id} Automatic Components",
                    "one_line_description": component_text.splitlines()[0].strip(),
                    "full_description": component_text,
                    "full_description_source": "locked_sphere_automatic_component_authority",
                    "source": component_source,
                    "acquisition_source": {
                        "target_cl": binding_packet.get("target_cl"),
                        "advancement_kind": binding_packet.get("advancement_kind"),
                        "packet_ids": [binding_packet["packet_id"]],
                    },
                    "stage2_rule_id": stage2.get("rule_id"),
                    "display_timing_or_category": "Automatic Sphere Component",
                    "capabilities": {
                        "character_sheet": "SUPPORTED",
                        "gm_display": "NOT_ATTEMPTED",
                        "combat_execution": "NOT_APPLICABLE",
                        "ai_policy": "NOT_APPLICABLE",
                    },
                    "display_only_not_execution_authority": False,
                    "parent_sphere_id": record_id,
                    "component_hash": component["component_hash"],
                    "automatic_component_flags": {
                        key: component[key]
                        for key in (
                            "automatic_grant",
                            "owner_removable",
                            "counts_as_talent_choice",
                            "counts_as_advancement_talent",
                            "counts_as_training_talent",
                        )
                    },
                    "owner_ruling": deepcopy(component.get("owner_ruling") or {}),
                    "automatic_component_authority": {
                        "schema_version": sphere_packet["schema_version"],
                        "parent_sphere_id": record_id,
                        "package_hash": sphere_packet["package_hash"],
                        "component_ids": [component_id],
                    },
                }
                rules.append(component_rule)
            required_ids.update(automatic_component_ids)
        rules.append(rule)
    unsigned = {
        "schema_version": "TianxiaFoundry.CharacterSheetDisplayContract.v1",
        "contract_id": f"tianxia.character_sheet.display.project.{project['project_id']}",
        "canonical_project_id": project["project_id"],
        "project_revision": project["revision"],
        "typed_choice_snapshot_sha256": choice_snapshot["snapshot_sha256"],
        "readiness_stage": "CHARACTER_SHEET_READY",
        "policies": {
            "combat_execution_promotion": False,
            "duplicate_record_presentation": "FAIL_CLOSED",
            "missing_mapping": "FAIL_CLOSED",
            "runtime_prose_parsing": False,
            "source_backed_display_only": True,
            "unproven_description": "FAIL_CLOSED",
        },
        "rules": rules,
    }
    return {**unsigned, "seal_sha256": sha256_json(unsigned)}


def _validate_binding(event: dict[str, Any], record: dict[str, Any], project: dict[str, Any]) -> None:
    binding = event.get("content_binding") or {}
    rb = record.get("content_binding") or {}
    if binding.get("record_hash") != record.get("record_hash") or any(binding.get(k) != rb.get(k) for k in ("pack_id", "pack_version", "pack_hash")):
        raise FoundryError("PROJECTION_CONTENT_BINDING_MISMATCH", "A v3 event does not match its locked record snapshot.", details={"event_id": event.get("event_id"), "record_id": record.get("record_id")})
    allowed = {(x.get("pack_id"), x.get("version"), x.get("content_hash")) for x in (project.get("content_lock") or {}).get("packs", [])}
    factory = record.get("compatibility", {}).get("factory", {})
    raw_projection = factory.get("raw_projection") or {}
    non_sphere_authority = (
        binding.get("pack_id") == "tianxia.non_sphere.authority"
        and (record.get("selected_authority") is True or raw_projection.get("selected_authority") is True)
        and record.get("publication", {}).get("status") == "published"
        and record.get("record_id", "").startswith(("METHOD-", "tianxia.path."))
        and str(record.get("source", {}).get("path", "")).startswith("non_sphere_authority/authority/")
        and (factory.get("stage2_authority", {}).get("authority_complete") is True)
    )
    if (binding.get("pack_id"), binding.get("pack_version"), binding.get("pack_hash")) not in allowed and not non_sphere_authority:
        raise FoundryError("PROJECTION_UNLOCKED_CONTENT", "A v3 event references content outside the project lock.", details={"event_id": event.get("event_id")})


def _validate_non_sphere_method_access_event(
    event: dict[str, Any],
    record: dict[str, Any],
    project: dict[str, Any],
) -> None:
    """Validate a server method-access event without projecting mechanics.

    Non-Sphere authority events deliberately bind a complete immutable target
    set rather than one catalog record.  They remain part of the canonical
    event chain and packet audit, but cannot supply Stage 2 ledger mechanics.
    """
    details = (event.get("advancement") or {}).get("details") or {}
    subject = event.get("subject") or {}
    calculation = (event.get("advancement") or {}).get("calculation") or {}
    bindings = (event.get("advancement") or {}).get("authority_bindings") or []
    target_bindings = [row for row in bindings if row.get("role") != "project_lock_proof"]
    proof_bindings = [row for row in bindings if row.get("role") == "project_lock_proof"]
    invalid = (
        event.get("legal_channel") != "authenticated_project_authority_service"
        or subject.get("content_type") != "non_sphere_authority"
        or subject.get("record_id") != details.get("method_id")
        or details.get("authority_type") != "method_access"
        or details.get("creation_authority") != "AUTHENTICATED_PROJECT_AUTHORITY_SERVICE"
        or details.get("amount_awarded") is not None
        or record.get("record_id") != details.get("method_id")
        or record.get("content_type") != "cultivation_method"
        or record.get("publication", {}).get("status") != "published"
        or len(target_bindings) != 1
        or len(proof_bindings) != 1
        or calculation.get("rule_id") != "non_sphere_authority_commit"
        or (calculation.get("trace") or {}).get("authenticated") is not True
    )
    if invalid:
        raise FoundryError(
            "PROJECTION_NON_SPHERE_AUTHORITY_INVALID",
            "A non-Sphere Method access event failed its server-authority boundary.",
            details={"event_id": event.get("event_id"), "kind": event.get("advancement", {}).get("kind")},
        )

    record_binding = record.get("content_binding") or {}
    target = target_bindings[0]
    target_matches_record = all(
        target.get(key) == expected
        for key, expected in {
            "role": "method",
            "record_id": record.get("record_id"),
            "record_hash": record.get("record_hash"),
            "relationship_id": f"method:{record.get('record_id')}",
            "pack_id": record_binding.get("pack_id"),
            "pack_version": record_binding.get("pack_version"),
            "pack_hash": record_binding.get("pack_hash"),
            "source_id": record.get("record_id"),
            "source_hash": record.get("record_hash"),
        }.items()
    )
    proof = proof_bindings[0]
    proof_matches_shape = all(
        proof.get(key) == expected
        for key, expected in {
            "relationship_id": "project_lock_proof",
            "relationship_hash": proof.get("record_hash"),
            "record_id": "project_lock_proof",
            "record_hash": proof.get("record_hash"),
            "pack_id": "project.lock",
            "pack_version": "HF2",
            "pack_hash": proof.get("record_hash"),
            "source_id": "project_lock_proof",
            "source_hash": proof.get("record_hash"),
        }.items()
    )
    binding = event.get("content_binding") or {}
    canonical_targets = [{
        key: target[key]
        for key in (
            "role", "record_id", "record_hash", "relationship_id", "relationship_hash",
            "pack_id", "pack_version", "pack_hash",
        )
    }]
    expected_target_hash = sha256_json({
        "schema": "Tianxia.CompleteLockedTargetBinding.v1",
        "targets": canonical_targets,
    })
    target_details = {
        key: value
        for key, value in details.items()
        if key not in {"authority_type", "amount_awarded", "creation_authority", "operation_hash"}
    }
    expected_operation_hash = sha256_json({
        "project_id": project["project_id"],
        "kind": "non_sphere_method_access",
        "details": target_details,
        "amount_awarded": None,
        "idempotency_key": event.get("idempotency_key"),
    })
    binding_valid = (
        binding.get("pack_id") == "project.locked.target-set"
        and binding.get("pack_version") == "1"
        and binding.get("pack_hash") == proof.get("record_hash")
        and binding.get("record_hash") == expected_target_hash
        and binding.get("catalog_build_id") == (
            project.get("catalog_build_hash")
            or (project.get("content_lock") or {}).get("catalog_build_id")
            or "catalog.unbuilt"
        )
    )
    if (
        not target_matches_record
        or not proof_matches_shape
        or not binding_valid
        or details.get("operation_hash") != expected_operation_hash
    ):
        raise FoundryError(
            "PROJECTION_NON_SPHERE_AUTHORITY_INVALID",
            "A non-Sphere Method access event has an invalid immutable target or operation binding.",
            details={"event_id": event.get("event_id"), "method_id": details.get("method_id")},
        )


def _validate_non_sphere_method_acquisition_event(
    event: dict[str, Any],
    record: dict[str, Any],
) -> None:
    """Validate the initial Method acquisition as an audited non-mechanical event."""
    advancement = event.get("advancement") or {}
    details = advancement.get("details") or {}
    subject = event.get("subject") or {}
    stage2 = (record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
    raw_projection = ((record.get("compatibility") or {}).get("factory") or {}).get("raw_projection") or {}
    invalid = (
        event.get("legal_channel") != "method-acquisition"
        or subject.get("content_type") != "cultivation_method"
        or subject.get("record_id") != record.get("record_id")
        or not str(record.get("record_id") or "").startswith("METHOD-")
        or record.get("content_type") != "cultivation_method"
        or record.get("publication", {}).get("status") != "published"
        or not (record.get("selected_authority") is True or raw_projection.get("selected_authority") is True)
        or stage2.get("authority_complete") is not True
        or "method_acquisition" not in (stage2.get("allowed_kinds") or [])
        or "method-acquisition" not in (stage2.get("allowed_channels") or [])
        or (details.get("method_id") is not None and details.get("method_id") != record.get("record_id"))
    )
    if invalid:
        raise FoundryError(
            "PROJECTION_NON_SPHERE_AUTHORITY_INVALID",
            "An initial non-Sphere Method acquisition event failed its authenticated authority boundary.",
            details={"event_id": event.get("event_id"), "method_id": record.get("record_id")},
        )


def _non_sphere_event_provenance(
    event: dict[str, Any],
    record: dict[str, Any],
    contract: dict[str, Any],
    destination: str | list[str],
) -> dict[str, Any]:
    destinations = [destination] if isinstance(destination, str) else list(destination)
    return {
        "provenance_unit": "canonical_non_sphere_authority_event",
        "event_id": event["event_id"],
        "event_hash": event["event_hash"],
        "event_sequence": event["sequence"],
        "record_id": record["record_id"],
        "record_hash": record["record_hash"],
        "pack_id": event["content_binding"]["pack_id"],
        "pack_version": event["content_binding"]["pack_version"],
        "pack_hash": event["content_binding"]["pack_hash"],
        "canonical_sources": deepcopy(event.get("source_evidence") or []),
        "stage2_rule_id": None,
        "projection_contract_id": contract["contract_id"],
        "projection_contract_hash": sha256_json({k: v for k, v in contract.items() if k != "seal_sha256"}),
        "stage2_normalization_authority": deepcopy(contract["stage2_authority_pack"]),
        "exact_source_map": deepcopy(contract["exact_source_map"]),
        "destination_pointers": sorted(destinations),
        "transformation_kind": "NON_SPHERE_AUTHORITY_AUDIT_ONLY",
        "authority_complete": True,
        "mechanical_projection": False,
    }


def reduce_v3(*, root_dir: Path, registry: Any, project: dict[str, Any], events: list[dict[str, Any]], locked_records: dict[str, dict[str, Any]], choice_snapshot: dict[str, Any] | None, state_type: Any) -> Any:
    contract_path = root_dir / "projector" / "contracts" / "C2AR1_Stage2_v3_Projection_Contract.json"
    profile_path = root_dir / "projector" / "contracts" / "C2AR1_Stage_Aware_Validation_Profile.json"
    fixture_path = root_dir / "authority" / "Tianxia_C2AR1_Fixture_Selections_R1.json"
    baseline_path = root_dir / "authority" / "Tianxia_Core_Character_Baseline_Authority_Pack_R1.json"
    language_path = root_dir / "authority" / "Tianxia_Campaign_Language_Binding_Fire_Qi_Proof_R1.json"
    amendment_path = root_dir / "authority" / "Tianxia_Core_Character_Baseline_Owner_Amendment_R1.json"
    stage2_pack_path = root_dir / "catalog" / "typed_authority" / "C1A_Canonical_Typed_Authority_Pack_v1.json"
    source_map_path = root_dir / "catalog" / "typed_authority" / "C1A_Exact_Source_Map_v1.json"
    contract = _read_sealed(contract_path, schema_version="TianxiaFoundry.Stage2V3FactoryProjectionContract.v1", mismatch_code="PROJECTION_V3_CONTRACT_INVALID")
    profile = _read_sealed(profile_path, schema_version="TianxiaFoundry.StageAwareProjectionValidationProfile.v1", mismatch_code="PROJECTION_VALIDATION_PROFILE_INVALID")
    fixture = _read_sealed(fixture_path, schema_version="TianxiaFoundry.OwnerFixtureSelections.v1", mismatch_code="PROJECTION_FIXTURE_SELECTIONS_INVALID")
    baseline = _read_sealed(baseline_path, schema_version="TianxiaFoundry.CoreCharacterBaselineAuthorityPack.v1", mismatch_code="PROJECTION_BASELINE_PACK_INVALID")
    language = _read_sealed(language_path, schema_version="TianxiaFoundry.CampaignLanguageBinding.v1", mismatch_code="PROJECTION_LANGUAGE_BINDING_INVALID")
    amendment = _read_sealed(amendment_path, schema_version="TianxiaFoundry.OwnerRatifiedRuleAmendment.v1", mismatch_code="PROJECTION_OWNER_AMENDMENT_INVALID")
    expected_files = {
        "baseline_pack": (baseline_path, contract["baseline_pack"]["sha256"]),
        "fixture_selection_contract": (fixture_path, contract["fixture_selection_contract"]["sha256"]),
        "validation_profile": (profile_path, contract["validation_profile"]["sha256"]),
        "stage2_authority_pack": (stage2_pack_path, contract["stage2_authority_pack"]["sha256"]),
        "exact_source_map": (source_map_path, contract["exact_source_map"]["sha256"]),
    }
    for label, (path, expected) in expected_files.items():
        if sha256_file(path) != expected:
            raise FoundryError("PROJECTION_AUTHORITY_IDENTITY_MISMATCH", "A projection authority identity does not match the sealed bridge contract.", details={"authority": label, "path": str(path)})
    if sha256_file(amendment_path) != next(rule["source"]["amendment_sha256"] for rule in baseline["rules"] if rule["rule_id"] == "tianxia.core.unarmored_ac.owner_r1"):
        raise FoundryError("PROJECTION_OWNER_AMENDMENT_IDENTITY_MISMATCH", "The owner amendment does not match the baseline pack binding.")
    if sha256_file(language_path) != fixture["authority"]["language"]["binding_sha256"]:
        raise FoundryError("PROJECTION_LANGUAGE_BINDING_IDENTITY_MISMATCH", "The campaign language binding does not match the fixture-selection contract.")

    supported_kinds = set(contract["supported_event_kinds"])
    non_projecting_kinds = set(contract.get("non_projecting_event_kinds") or [])
    # The sealed C2A-R.1 contract predates the normal-wizard initial Method
    # acquisition.  It is accepted here only as a strictly validated audit
    # event; it contributes no projected mechanics.
    non_projecting_kinds.add("method_acquisition")
    supported_records = set(contract["supported_record_ids"])
    previous = ZERO_HASH
    by_kind: dict[str, list[dict[str, Any]]] = {}
    event_records: dict[str, dict[str, Any]] = {}
    for expected, event in enumerate(events, start=1):
        report = registry.report(event, V3)
        if not report["valid"]:
            raise FoundryError("PROJECTION_EVENT_SCHEMA_INVALID", "A v3 event failed canonical validation before projection.", details={"event_id": event.get("event_id"), "diagnostics": report["diagnostics"]})
        if event["sequence"] != expected or event["previous_event_hash"] != previous:
            raise FoundryError("PROJECTION_EVENT_CHAIN_BROKEN", "The v3 event stream is not a gap-free canonical chain.", details={"expected": expected, "actual": event.get("sequence")})
        if canonical_event_hash(event) != event["event_hash"]:
            raise FoundryError("PROJECTION_EVENT_HASH_MISMATCH", "A v3 event does not match its canonical event hash.", details={"sequence": expected})
        kind = event["advancement"]["kind"]
        record_id = event["subject"]["record_id"]
        record = locked_records.get(record_id)
        if record is None:
            raise FoundryError("PROJECTION_LOCKED_RECORD_MISSING", "The v3 event record is absent from the canonical locked-record snapshot.", details={"record_id": record_id})
        rr = registry.report(record, "TianxiaFoundry.RulesCatalogRecord.v1")
        if not rr["valid"]:
            raise FoundryError("PROJECTION_RECORD_SCHEMA_INVALID", "A v3 locked record failed canonical validation.", details={"record_id": record_id, "diagnostics": rr["diagnostics"]})
        if kind not in supported_kinds and kind not in non_projecting_kinds:
            raise FoundryError("PROJECTION_V3_KIND_UNSUPPORTED", "The v3 projection contract does not support this advancement kind.", details={"kind": kind, "event_id": event["event_id"]})
        if kind in non_projecting_kinds:
            if kind == "method_acquisition":
                _validate_non_sphere_method_acquisition_event(event, record)
            elif kind != "non_sphere_method_access":
                raise FoundryError("PROJECTION_V3_KIND_UNSUPPORTED", "The v3 projection contract declares an unsupported non-projecting event kind.", details={"kind": kind, "event_id": event["event_id"]})
            else:
                _validate_non_sphere_method_access_event(event, record, project)
        else:
            stage2 = (record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
            if record_id not in supported_records and stage2.get("authority_complete") is not True:
                raise FoundryError("PROJECTION_V3_RECORD_AUTHORITY_MISSING", "The selected record is neither sealed by the legacy projection contract nor complete in the project's locked typed catalog authority.", details={"record_id": record_id, "event_id": event["event_id"]})
            if stage2.get("authority_complete") is not True or kind not in (stage2.get("allowed_kinds") or []):
                raise FoundryError("PROJECTION_V3_RECORD_AUTHORITY_MISSING", "The selected record lacks complete Stage 2 authority for this event kind.", details={"record_id": record_id, "kind": kind})
            _validate_binding(event, record, project)
            by_kind.setdefault(kind, []).append(event)
        event_records[event["event_id"]] = record
        previous = event["event_hash"]

    locks = _locks(project)
    current_fixture = (
        project.get("project_id") == "40ea751e-7913-557f-b403-a3ec3cd7c004"
        and locks.get("source_reference", {}).get("value")
        == "Accepted C1A owner intent; current catalog authority only"
        and locks.get("character.identity.display_name", {}).get("value")
        == "W5 Current Fire-Qi Owner-Test Fixture"
    )
    required_prefix = fixture["required_prefix"]
    historical_fixture = (
        len(events) == int(required_prefix["event_count"])
        and previous == required_prefix["event_head"]
    )
    generic_project = not current_fixture and not historical_fixture
    if current_fixture and len(events) != 25:
        raise FoundryError("CG1_CURRENT_PROJECTION_EVENT_COUNT_INVALID", "The bounded current fixture requires the exact 25-event Fire/Qi route.", details={"event_count": len(events)})
    final_display_lock = locks.get("character.identity.final_display_name", {}).get("value")
    final_concept_lock = locks.get("character.identity.final_concept", {}).get("value")
    if isinstance(final_display_lock, dict):
        final_display_lock = final_display_lock.get("value")
    if isinstance(final_concept_lock, dict):
        final_concept_lock = final_concept_lock.get("value")
    required_lock_values = {
        "character.identity.display_name": (
            final_display_lock
            or locks.get("character.identity.display_name", {}).get("value")
            or choice_snapshot.get("display_name_content")
            if generic_project
            else "W5 Current Fire-Qi Owner-Test Fixture"
            if current_fixture
            else fixture["selections"]["display_name"]
        ),
        "character.choices.qi_cultivation_skills": (
            locks.get("character.choices.qi_cultivation_skills", {}).get("value", [])
            if generic_project
            else fixture["selections"]["qi_cultivation_skills"]
        ),
        "character.choices.street_hardened": (
            locks.get("character.choices.street_hardened", {}).get("value")
            if generic_project
            else fixture["selections"]["street_hardened"]
        ),
        "character.choices.language": (
            locks.get("character.choices.language", {}).get("value")
            if generic_project
            else fixture["selections"]["language"]
        ),
    }
    concept_value = final_concept_lock or next(
        lock["value"] for lock in project["user_locks"] if lock["field"] == "concept"
    )
    for field, expected in required_lock_values.items() if not generic_project else ():
        lock = locks.get(field)
        if lock is None or lock.get("value") != expected:
            raise FoundryError("PROJECTION_REQUIRED_OWNER_CHOICE_MISSING", "A required owner-ratified fixture choice is absent or differs from the sealed selection.", details={"field": field})
    if not generic_project and "character.identity.title" in locks:
        raise FoundryError("PROJECTION_OPTIONAL_TITLE_FABRICATED", "The owner-approved proof fixture intentionally omitted its optional title.")
    language_ids = {entry["language_id"] for entry in language["languages"] if entry.get("selected") is True}
    if not generic_project and required_lock_values["character.choices.language"] not in language_ids:
        raise FoundryError("PROJECTION_LANGUAGE_BINDING_MISSING", "The selected language is not present in the sealed campaign binding.")

    def only(kind: str) -> dict[str, Any]:
        values = by_kind.get(kind) or []
        if len(values) != 1:
            raise FoundryError("PROJECTION_REQUIRED_EVENT_COUNT_INVALID", "A required advancement event kind has the wrong cardinality.", details={"kind": kind, "count": len(values)})
        return values[0]

    start = only("starting_state")
    background = only("background_acquisition")
    origin = only("origin_insight_acquisition")
    path_events = sorted(
        by_kind.get("path_acquisition") or [],
        key=lambda event: (int(event["sequence"]), event["subject"]["record_id"]),
    )
    path_ids = [event["subject"]["record_id"] for event in path_events]
    canonical_all_path_ids = {
        "tianxia.path.body_refining",
        "tianxia.path.qi_cultivation",
        "tianxia.path.spirit_awakening",
    }
    if len(path_events) == 1:
        pass
    elif len(path_events) == len(canonical_all_path_ids) and set(path_ids) == canonical_all_path_ids:
        # The normal wizard may commit the authenticated Method's complete
        # three-Path grant.  Keep the historical single-Path projection
        # shape as the primary view, while retaining every Path below.
        pass
    else:
        raise FoundryError(
            "PROJECTION_REQUIRED_EVENT_COUNT_INVALID",
            "The projection requires either one Path or the authenticated canonical three-Path grant.",
            details={"kind": "path_acquisition", "count": len(path_events), "record_ids": path_ids},
        )
    path_event = next(
        (event for event in path_events if event["subject"]["record_id"] == "tianxia.path.qi_cultivation"),
        path_events[0] if path_events else None,
    )
    subpath = only("subpath_acquisition")
    score_changes = by_kind.get("ability_score_change") or []
    if len(score_changes) > 1:
        raise FoundryError(
            "PROJECTION_REQUIRED_EVENT_COUNT_INVALID",
            "The projection permits at most one CL-specific ability-score change event.",
            details={"kind": "ability_score_change", "count": len(score_changes)},
        )
    insight_events = by_kind.get("cultivation_insight_acquisition") or []
    if not score_changes and not insight_events:
        raise FoundryError(
            "PROJECTION_REQUIRED_EVENT_COUNT_INVALID",
            "The projection requires an ability-score change or an ordinary Cultivation Insight event to represent the CL4 selection authority.",
            details={"ability_score_change_count": 0, "cultivation_insight_count": 0},
        )
    score_change = score_changes[0] if score_changes else None
    level_events = sorted(by_kind.get("level_advance") or [], key=lambda e: e["advancement"]["target_cl"])
    target_cl = max((e["advancement"]["target_cl"] for e in level_events), default=0)
    if [e["advancement"]["target_cl"] for e in level_events] != list(range(1, target_cl + 1)):
        raise FoundryError("PROJECTION_LEVEL_ADVANCEMENT_INCOMPLETE", "The projection requires a gap-free committed level chain.", details={"target_cl": target_cl})
    ability_history_events = [
        event
        for event in [background, *(score_changes or []), *insight_events]
        if ((event.get("advancement") or {}).get("calculation") or {}).get("outputs", {}).get("ability_scores")
    ]
    ability_history_events.sort(key=lambda event: int(event["sequence"]))
    latest_ability_event = ability_history_events[-1]
    final_scores = deepcopy(latest_ability_event["advancement"]["calculation"]["outputs"]["ability_scores"])
    final_mods = deepcopy(latest_ability_event["advancement"]["calculation"]["outputs"]["ability_modifiers"])
    final_pb = level_events[-1]["advancement"]["calculation"]["outputs"]["pb"]
    formula_context = {"ability_scores": final_scores, "ability_modifiers": final_mods, "cl": target_cl, "pb": final_pb}
    rules_by_id = {rule["rule_id"]: rule for rule in baseline["rules"]}
    try:
        ac_result = evaluate_formula(rules_by_id["tianxia.core.unarmored_ac.owner_r1"]["formula"]["root"], formula_context)
        init_result = evaluate_formula(rules_by_id["tianxia.core.initiative.owner_r1"]["formula"]["root"], formula_context)
    except FormulaError as exc:
        raise FoundryError("PROJECTION_BASELINE_FORMULA_INVALID", "A sealed core baseline formula could not be evaluated.", details={"error": str(exc)}) from exc

    packet_by_event: dict[str, str] = {event["event_id"]: _packet_id(event) for event in events}
    packets_list: list[dict[str, Any]] = []
    capability: list[dict[str, Any]] = []
    for event in events:
        record = event_records[event["event_id"]]
        short, full = _display(record)
        packets_list.append({
            "packet_id": packet_by_event[event["event_id"]],
            "event_id": event["event_id"],
            "event_hash": event["event_hash"],
            "sequence": event["sequence"],
            "target_cl": event["advancement"]["target_cl"],
            "advancement_kind": event["advancement"]["kind"],
            "record_id": record["record_id"],
            "record_hash": record["record_hash"],
            "display_name": event["subject"]["display_name"],
            "short_description": short,
            "full_description": full,
            "stage2_rule_id": event["advancement"]["calculation"]["rule_id"],
            "source_evidence": deepcopy(event.get("source_evidence") or []),
            "content_binding": deepcopy(event["content_binding"]),
        })
        if event["advancement"]["kind"] not in non_projecting_kinds:
            capability.append(_capability_entry(record, event["advancement"]["target_cl"], event))
    # Include source-granted Subpath features without inventing independent events.
    granted_ids = subpath["advancement"]["calculation"]["outputs"].get("granted_feature_record_ids") or []
    for granted_id in granted_ids:
        record = locked_records.get(granted_id)
        granted_authority = ((record or {}).get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
        if record is None or (granted_id not in supported_records and granted_authority.get("authority_complete") is not True):
            raise FoundryError("PROJECTION_V3_RECORD_AUTHORITY_MISSING", "A source-granted feature lacks complete locked typed authority.", details={"record_id": granted_id})
        capability.append(_capability_entry(record, 3, subpath))

    spheres = []
    sphere_packets: dict[str, dict[str, Any]] = {}
    for kind, acquisition_type in (
        ("background_sphere_acquisition", "background_sphere"),
        ("ai_bootstrap_sphere_acquisition", "level_1_sphere"),
        ("sphere_training_attempt", "sphere_training"),
    ):
        for event in by_kind.get(kind) or []:
            if kind == "sphere_training_attempt" and ((event.get("advancement") or {}).get("training_transaction") or {}).get("result") != "success":
                continue
            record = _sphere_record_with_event_authority(event_records[event["event_id"]], event)
            sphere_packet = normalize_sphere_automatic_components(record, acquisition_event=event)
            sphere_id = event["subject"]["record_id"]
            sphere_packets[sphere_id] = sphere_packet
            spheres.append({
                "sphere_id": sphere_id,
                "name": event["subject"]["display_name"],
                "gained_at_cl": event["advancement"]["target_cl"],
                "acquisition_type": acquisition_type,
                "source_packet_ids": [packet_by_event[event["event_id"]]],
                "allocation_id": f"allocation.{event['event_id']}",
                "automatic_component_authority": deepcopy(sphere_packet),
                "automatic_component_ids": deepcopy(sphere_packet["component_ids"]),
                "automatic_base_abilities": deepcopy(sphere_packet["components"]),
            })
    spheres.sort(key=lambda x: (x["gained_at_cl"], x["sphere_id"]))
    automatic_sphere_component_receipts = [
        {
            "schema_version": packet["schema_version"],
            "parent_sphere_id": packet["parent_sphere_id"],
            "parent_record_hash": packet.get("parent_record_hash"),
            "package_hash": packet["package_hash"],
            "component_ids": deepcopy(packet["component_ids"]),
            "components": deepcopy(packet["components"]),
            "acquisition": deepcopy(packet.get("acquisition") or {}),
        }
        for packet in sorted(sphere_packets.values(), key=lambda row: row["parent_sphere_id"])
    ]
    automatic_sphere_components = []
    component_by_id: dict[str, dict[str, Any]] = {}
    for receipt in automatic_sphere_component_receipts:
        for component in receipt["components"]:
            prior = component_by_id.get(component["component_id"])
            if prior is not None and prior["component_hash"] != component["component_hash"]:
                raise FoundryError(
                    "SPHERE_AUTOMATIC_COMPONENT_CONFLICT",
                    "The projection encountered conflicting bytes for one automatic Sphere component ID.",
                    details={"component_id": component["component_id"]},
                )
            if prior is None:
                component_by_id[component["component_id"]] = deepcopy(component)
    automatic_sphere_components = [component_by_id[key] for key in sorted(component_by_id)]
    sphere_names = {
        event["subject"]["record_id"]: event["subject"]["display_name"]
        for kind in ("background_sphere_acquisition", "ai_bootstrap_sphere_acquisition")
        for event in by_kind.get(kind) or []
    }
    talents = []
    for kind, acquisition_type in (("background_talent_acquisition", "background_talent"), ("ai_bootstrap_talent_acquisition", "new_sphere_bonus"), ("level_talent_acquisition", "free_level")):
        for event in by_kind.get(kind) or []:
            rid = event["subject"]["record_id"]
            record = event_records[event["event_id"]]
            stage2 = record["compatibility"]["factory"]["stage2_authority"]
            sphere_id = stage2.get("sphere_id")
            sphere_name = sphere_names.get(sphere_id, str(sphere_id or "Unbound"))
            talents.append({
                "talent_id": rid,
                "name": event["subject"]["display_name"].title() if event["subject"]["display_name"].isupper() else event["subject"]["display_name"],
                "sphere": sphere_name,
                "gained_at_cl": event["advancement"]["target_cl"],
                "acquisition_type": acquisition_type,
                "mechanical_summary": _display(record)[0],
                "source_packet_ids": [packet_by_event[event["event_id"]]],
                "allocation_id": f"allocation.{event['event_id']}",
            })
    talents.sort(key=lambda x: (x["gained_at_cl"], x["talent_id"]))

    insights = []
    for event in sorted(by_kind.get("cultivation_insight_acquisition") or [], key=lambda row: int(row["sequence"])):
        record = event_records[event["event_id"]]
        outputs = (event.get("advancement") or {}).get("calculation", {}).get("outputs") or {}
        occurrence = deepcopy(outputs.get("insight_occurrence") or {})
        insights.append({
            "insight_id": event["subject"]["record_id"],
            "name": event["subject"]["display_name"],
            "gained_at_cl": event["advancement"]["target_cl"],
            "repeat_index": occurrence.get("repeat_index", (event.get("advancement") or {}).get("details", {}).get("repeat_index", 1)),
            "ability": occurrence.get("ability"),
            "amount": occurrence.get("amount"),
            "ability_change_applied": bool(outputs.get("ability_change_applied")),
            "source_packet_ids": [packet_by_event[event["event_id"]]],
            "source_record_hash": record["record_hash"],
            "source_evidence": deepcopy(event.get("source_evidence") or []),
        })

    features = []
    for event in level_events:
        record = event_records[event["event_id"]]
        features.append({
            "feature_id": event["subject"]["record_id"],
            "allocation_id": f"allocation.{event['event_id']}",
            "name": event["subject"]["display_name"],
            "gained_at_cl": event["advancement"]["target_cl"],
            "mechanical_summary": _display(record)[0],
            "source_packet_ids": [packet_by_event[event["event_id"]]],
            "category": "path_feature",
        })
    for granted_id in granted_ids:
        record = locked_records[granted_id]
        features.append({
            "feature_id": granted_id,
            "allocation_id": f"allocation.{subpath['event_id']}.{granted_id}",
            "name": record.get("display_name") or granted_id,
            "gained_at_cl": 3,
            "mechanical_summary": _display(record)[0],
            "source_packet_ids": [packet_by_event[subpath["event_id"]]],
            "category": "subpath_feature",
            "grant_source_record_id": subpath["subject"]["record_id"],
        })
    features.sort(key=lambda x: (x["gained_at_cl"], x["feature_id"]))

    def primary_resource_id(resources: dict[str, Any]) -> str:
        if "tianxia.resource.qi" in resources:
            return "tianxia.resource.qi"
        if not resources:
            raise FoundryError(
                "PROJECTION_RESOURCE_AUTHORITY_MISSING",
                "The final level calculation contains no authenticated primary resource.",
            )
        return sorted(resources)[0]

    def resource_display_name(resource_id: str) -> str:
        return {
            "tianxia.resource.qi": "Qi",
            "tianxia.resource.stamina": "Stamina",
            "tianxia.resource.resonance": "Resonance",
        }.get(resource_id, resource_id.rsplit(".", 1)[-1].replace("_", " ").title())

    levels = []
    cumulative_talents: list[str] = []
    talent_by_cl: dict[int, list[str]] = {}
    for t in talents:
        talent_by_cl.setdefault(t["gained_at_cl"], []).append(t["talent_id"])

    def ability_scores_after(sequence: int) -> dict[str, int]:
        for history_event in reversed(ability_history_events):
            if int(history_event["sequence"]) <= sequence:
                return deepcopy(history_event["advancement"]["calculation"]["outputs"]["ability_scores"])
        return deepcopy(background["advancement"]["calculation"]["outputs"]["ability_scores"])

    for event in level_events:
        cl = event["advancement"]["target_cl"]
        out = event["advancement"]["calculation"]["outputs"]
        for rid in sorted(talent_by_cl.get(cl, [])):
            cumulative_talents.append(rid)
        hp_total = out["hp_after"]["total"]
        resource = out["resources_after"][primary_resource_id(out.get("resources_after") or {})]
        levels.append({
            "cl": cl,
            "realm": "Mortal",
            "pb": out["pb"],
            "hp": {"gain": out["hp_after"]["last_gain"], "max_after_level": hp_total, "formula_id": out["hp_after"]["last_formula_id"]},
            "resource": {"resource_id": resource["resource_id"], "maximum": resource["maximum"], "current_after_event": resource["current"], "formula_id": resource["formula_id"]},
            "ability_scores_after": ability_scores_after(int(event["sequence"])),
            "feature_record_id": event["subject"]["record_id"],
            "talent_record_ids_gained": sorted(talent_by_cl.get(cl, [])),
            "talent_record_ids_known": sorted(cumulative_talents),
            "state_after_hash": event["state_after_hash"],
            "event_id": event["event_id"],
        })
    # CL1 must show the starting and background/bootstrap talents as known.
    cl1_initial = sorted([t["talent_id"] for t in talents if t["gained_at_cl"] == 1])
    levels[0]["talent_record_ids_known"] = cl1_initial
    for idx in range(1, len(levels)):
        prior = set(levels[idx - 1]["talent_record_ids_known"])
        levels[idx]["talent_record_ids_known"] = sorted(prior | set(levels[idx]["talent_record_ids_gained"]))

    typed_none: dict[str, Any] = {}
    for event in by_kind.get("typed_none") or []:
        target = event["advancement"]["details"].get("target")
        if target not in {"method", "foundation", "manuals", "equipment", "forged_techniques"}:
            raise FoundryError("PROJECTION_TYPED_NONE_TARGET_UNSUPPORTED", "The v3 projection contract does not support this typed-none target.", details={"target": target})
        typed_none[target] = deepcopy(event["advancement"]["none_state"])
    method_acquisition_events = [
        event for event in events
        if event["advancement"]["kind"] == "method_acquisition"
    ]
    if len(method_acquisition_events) > 1:
        raise FoundryError(
            "PROJECTION_REQUIRED_EVENT_COUNT_INVALID",
            "The initial proof stream may contain at most one authenticated Method acquisition.",
            details={"kind": "method_acquisition", "count": len(method_acquisition_events)},
        )
    required_typed_none_targets = {"foundation", "manuals", "equipment", "forged_techniques"}
    missing_typed_none_targets = sorted(required_typed_none_targets - set(typed_none))
    if missing_typed_none_targets or (not method_acquisition_events and "method" not in typed_none):
        raise FoundryError("PROJECTION_REQUIRED_FIELD_AUTHORITY_MISSING", "The proof stream does not contain all required exact typed-none sections.", details={"present": sorted(typed_none)})
    if method_acquisition_events and "method" in typed_none:
        raise FoundryError(
            "PROJECTION_METHOD_AUTHORITY_CONFLICT",
            "An authenticated Method acquisition and a typed-none Method cannot both be present.",
            details={"method_event_id": method_acquisition_events[0]["event_id"]},
        )
    method_projection = deepcopy(typed_none.get("method"))
    if method_acquisition_events:
        method_event = method_acquisition_events[0]
        method_record = event_records[method_event["event_id"]]
        method_projection = {
            "state": "acquired",
            "status": "acquired",
            "record_id": method_record["record_id"],
            "display_name": method_event["subject"]["display_name"],
            "event_id": method_event["event_id"],
            "record_hash": method_record["record_hash"],
            "source_packet_ids": [packet_by_event[method_event["event_id"]]],
            "mechanical_projection": False,
        }

    background_record = event_records[background["event_id"]]
    origin_record = event_records[origin["event_id"]]
    last_level_out = level_events[-1]["advancement"]["calculation"]["outputs"]
    primary_resource = last_level_out["resources_after"][primary_resource_id(last_level_out.get("resources_after") or {})]
    key_ability = ((event_records[path_event["event_id"]].get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}).get("key_ability", "INT")
    attack_bonus = final_mods[key_ability] + final_pb
    save_dc = 8 + final_mods[key_ability] + final_pb
    selected_skills = [x.rsplit(".", 1)[-1].title() for x in required_lock_values["character.choices.qi_cultivation_skills"]]
    background_skills = background["advancement"]["calculation"]["outputs"].get("skill_proficiencies", [])
    proficient_skills = sorted(set(background_skills + selected_skills))
    multipliers = {skill: 1 for skill in proficient_skills}
    expertise_skill = required_lock_values["character.choices.street_hardened"]
    if isinstance(expertise_skill, str) and expertise_skill:
        multipliers[expertise_skill.rsplit(".", 1)[-1].title()] = 2
    skill_ability_map = {
        skill: ("INT" if skill in {"Arcana", "History"} else "CHA" if skill == "Deception" else "DEX")
        for skill in proficient_skills
    }
    skills = {skill: final_mods[skill_ability_map[skill]] + final_pb * multipliers[skill] for skill in sorted(skill_ability_map)}
    path_selection_rows = []
    path_event_indexes = {}
    for index, event in enumerate(path_events):
        path_event_indexes[event["event_id"]] = index
        record_stage2 = ((event_records[event["event_id"]].get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {})
        path_selection_rows.append({
            "path_id": event["subject"]["record_id"],
            "display_name": event["subject"]["display_name"],
            "effective_cl": target_cl,
            "key_ability": record_stage2.get("key_ability") or (key_ability if event["event_id"] == path_event["event_id"] else None),
            "selected_skills": deepcopy(selected_skills) if event["event_id"] == path_event["event_id"] else [],
            "source_packet_ids": [packet_by_event[event["event_id"]]],
        })

    readiness = {
        "active_profile": "ADVANCEMENT_READY",
        "advancement": "ADVANCEMENT_READY",
        "character_sheet": "NOT_ATTEMPTED",
        "gm_screen": "NOT_ATTEMPTED",
        "combat": "NOT_ATTEMPTED",
        "profile_id": profile["profile_id"],
        "profile_sha256": sha256_file(profile_path),
    }
    later = {
        "character_sheet": {"status": "NOT_ATTEMPTED", "pending": profile["later_stage_nodes"]["character_sheet"]},
        "gm_screen": {"status": "NOT_ATTEMPTED", "pending": profile["later_stage_nodes"]["gm_screen"]},
        "combat": {"status": "NOT_ATTEMPTED", "pending": profile["later_stage_nodes"]["combat"]},
    }
    display_packets = [
        packet for packet in packets_list
        if packet["advancement_kind"] not in non_projecting_kinds
        or packet["advancement_kind"] == "method_acquisition"
    ]
    display_locked_records = deepcopy(locked_records)
    for event in events:
        if "sphere" not in str((event.get("advancement") or {}).get("kind") or ""):
            continue
        record_id = (event.get("subject") or {}).get("record_id")
        if record_id in display_locked_records:
            display_locked_records[record_id] = _sphere_record_with_event_authority(
                display_locked_records[record_id], event
            )
    dynamic_display_contract = (
        _dynamic_display_contract(
            project,
            choice_snapshot,
            display_locked_records,
            display_packets,
            granted_ids,
            packet_by_event[subpath["event_id"]],
        )
        if generic_project
        else None
    )
    ledger = {
        "schema_version": "HF05ZVK-R1F",
        "projection_profile": "TianxiaFoundry.AdvancementReadyProjection.v1",
        "build_mode": "production",
        "status": "COMMAND_2_ADVANCEMENT_LEDGER_SEALED",
        "typed_choice_snapshot": {
            "schema": "TianxiaFoundry.TypedProjectChoiceSnapshotBinding.v1",
            "canonical_project_id": choice_snapshot["canonical_project_id"],
            "project_revision": choice_snapshot["project_revision"],
            "content_lock_hash": choice_snapshot["content_lock_hash"],
            "event_stream": deepcopy(choice_snapshot["event_stream"]),
            "snapshot_sha256": choice_snapshot["snapshot_sha256"],
            "typed_lock_count": len(choice_snapshot.get("typed_locks") or []),
        },
        "readiness": readiness,
        "character": {
            "character_id": project["project_id"],
            "name": required_lock_values["character.identity.display_name"],
            "concept": concept_value,
            "species": rules_by_id["tianxia.core.human.species.v1"]["typed_value"],
            "creature_type": rules_by_id["tianxia.core.human.creature_type.v1"]["typed_value"],
            "size": rules_by_id["tianxia.core.human.size.v1"]["typed_value"],
            "cl": target_cl,
            "realm": "Mortal",
            "path": path_event["subject"]["display_name"],
            "path_id": path_event["subject"]["record_id"],
            "key_ability": key_ability,
            "pb": final_pb,
            "title": None,
            "title_status": "OPTIONAL_OMITTED_BY_OWNER",
        },
        "core_stats": {
            "ability_scores": final_scores,
            "ability_modifiers": final_mods,
            "ability_generation": deepcopy(start["advancement"]["calculation"]),
            "ac_base": ac_result.value,
            "ac_active": ac_result.value,
            "ac_generation": {"calculation": "unarmored_base", "formula_id": rules_by_id["tianxia.core.unarmored_ac.owner_r1"]["formula"]["formula_id"], "trace": ac_result.trace, "conditional_bonuses_pending_execution": ["tianxia.path.qi_cultivation.feature.qi_armor"]},
            "initiative_bonus": init_result.value,
            "initiative_generation": {"ability": "DEX", "check": "1d20", "formula_id": rules_by_id["tianxia.core.initiative.owner_r1"]["formula"]["formula_id"], "trace": init_result.trace, "situational_advantage_sources": ["tianxia.origin_insight.street_hardened"]},
            "speed_ft": rules_by_id["tianxia.core.human.walking_speed.v1"]["typed_value"],
            "speed_generation": {"rule_id": "tianxia.core.human.walking_speed.v1", "mode": "walking"},
            "hp_current": last_level_out["hp_after"]["total"],
            "hp_max": last_level_out["hp_after"]["total"],
            "hp_generation": {"levels": [{"cl": level["cl"], "gain": level["hp"]["gain"], "maximum": level["hp"]["max_after_level"], "formula_id": level["hp"]["formula_id"]} for level in levels]},
            "primary_resource_name": resource_display_name(primary_resource["resource_id"]),
            "primary_resource_current": primary_resource["current"],
            "primary_resource_max": primary_resource["maximum"],
            "technique_attack_bonus": attack_bonus,
            "save_dc": save_dc,
            "proficient_skills": proficient_skills,
            "skills": skills,
            "skill_ability_map": skill_ability_map,
            "skill_proficiency_multipliers": multipliers,
            "skill_sources": {
                skill: [path_event["subject"]["record_id"]] if skill in selected_skills else [background["subject"]["record_id"]]
                for skill in proficient_skills
            },
        },
        "background_origin": {
            "background": {
                "background_id": background["subject"]["record_id"],
                "name": background["subject"]["display_name"],
                "ability_score_change": {"DEX": 2},
                "skill_proficiencies": background_skills,
                "tool_proficiencies": background["advancement"]["calculation"]["outputs"].get("tool_proficiencies", []),
                "languages": (
                    []
                    if generic_project or not required_lock_values["character.choices.language"]
                    else [{"language_id": language["languages"][0]["language_id"], "display_name": language["languages"][0]["display_name"]}]
                ),
                "background_sphere": next((event["subject"]["display_name"] for event in by_kind.get("background_sphere_acquisition") or []), None),
                "background_talent": next((event["subject"]["display_name"] for event in by_kind.get("background_talent_acquisition") or []), None),
                "summary": _display(background_record)[0],
                "source_packet_ids": [packet_by_event[background["event_id"]]],
            },
            "origin_insight": {
                "origin_insight_id": origin["subject"]["record_id"],
                "name": origin["subject"]["display_name"],
                "selected_skill": expertise_skill.rsplit(".", 1)[-1].title() if isinstance(expertise_skill, str) and expertise_skill else None,
                "result": "expertise" if expertise_skill else "catalog_effect",
                "initiative_effect": "situational_advantage",
                "summary": _display(origin_record)[0],
                "source_packet_ids": [packet_by_event[origin["event_id"]]],
            },
        },
        "advancement": {"levels": levels, "event_count": len(events), "event_head_hash": previous, "historical_prefix_preserved": historical_fixture},
        "path_selections": path_selection_rows,
        "subpaths": [{"subpath_id": subpath["subject"]["record_id"], "name": subpath["subject"]["display_name"], "owning_path_id": path_event["subject"]["record_id"], "selected_at_cl": 3, "feature_ids_expected": granted_ids, "source_packet_ids": [packet_by_event[subpath["event_id"]]]}],
        "spheres": spheres,
        "automatic_sphere_component_receipts": automatic_sphere_component_receipts,
        "automatic_sphere_components": automatic_sphere_components,
        "talents": talents,
        "insights": insights,
        "cultivation_insight_occurrences": deepcopy(insights),
        "features": features,
        "resources": [{"resource_id": primary_resource["resource_id"], "name": resource_display_name(primary_resource["resource_id"]), "current": primary_resource["current"], "max": primary_resource["maximum"], "formula_id": primary_resource["formula_id"], "authority_components": primary_resource["authority_components"]}],
        "method": method_projection,
        "foundation": deepcopy(typed_none["foundation"]),
        "recorded_arts": deepcopy(typed_none["manuals"]),
        "equipment": deepcopy(typed_none["equipment"]),
        "forged_techniques": deepcopy(typed_none["forged_techniques"]),
        "typed_none": typed_none,
        "record_capability_coverage": sorted(capability, key=lambda x: x["record_id"]),
        "later_stage_readiness": later,
        "authority_identities": {
            "stage2_authority_pack": deepcopy(contract.get("stage2_authority_pack")),
            "core_baseline_pack": {"pack_id": baseline["pack_id"], "version": baseline["version"], "sha256": sha256_file(baseline_path)},
            "owner_amendment": {"amendment_id": amendment["amendment_id"], "sha256": sha256_file(amendment_path)},
            "campaign_language_binding": {"binding_id": language["binding_id"], "sha256": sha256_file(language_path)},
            "projection_contract": {"contract_id": contract["contract_id"], "version": contract["version"], "sha256": sha256_file(contract_path)},
        },
    }
    packets = {
        "schema_version": "TianxiaFoundry.RulesSelectionPackets.v2",
        "project_id": project["project_id"],
        "project_revision": project["revision"],
        "readiness_profile": "ADVANCEMENT_READY",
        "packets": sorted(packets_list, key=lambda x: x["sequence"]),
        "owner_selections": {
            "display_name": required_lock_values["character.identity.display_name"],
            "language": required_lock_values["character.choices.language"],
            "qi_cultivation_skills": deepcopy(required_lock_values["character.choices.qi_cultivation_skills"]),
            "street_hardened": required_lock_values["character.choices.street_hardened"],
            "title": None,
            "typed_choice_snapshot_sha256": choice_snapshot["snapshot_sha256"],
        },
        "baseline_rule_ids": sorted(rules_by_id),
    }

    state = state_type()
    state.ledger = ledger
    state.rules_selection_packets = packets
    state.operations_applied = len(events)
    state.event_ids = [event["event_id"] for event in events]
    state.selected_record_ids = sorted({
        event["subject"]["record_id"]
        for event in events
        if event["advancement"]["kind"] not in non_projecting_kinds
    } | set(granted_ids))
    state.event_schema_version = V3
    state.readiness = readiness
    state.capability_coverage = sorted(capability, key=lambda x: x["record_id"])
    state.validation_profile = deepcopy(profile)
    state.project_display_contract = deepcopy(dynamic_display_contract)
    state.typed_choice_snapshot = deepcopy(choice_snapshot)

    # Semantic provenance: one entry per meaningful node or bounded subtree.
    semantic: dict[str, dict[str, Any]] = {}
    semantic["typed_choice_snapshot"] = {
        "provenance_unit": "revision_bound_typed_project_choice_snapshot",
        "canonical_project_id": choice_snapshot["canonical_project_id"],
        "project_revision": choice_snapshot["project_revision"],
        "content_lock_hash": choice_snapshot["content_lock_hash"],
        "event_stream": deepcopy(choice_snapshot["event_stream"]),
        "snapshot_sha256": choice_snapshot["snapshot_sha256"],
        "destination_pointers": [
            "/ledger/typed_choice_snapshot",
            "/ledger/character/character_id",
            "/ledger/character/name",
            "/rules_selection_packets/owner_selections",
        ],
        "transformation_kind": "SERVER_MATERIALIZED_TYPED_CHOICE_BINDING",
    }
    for event in events:
        record = event_records[event["event_id"]]
        kind = event["advancement"]["kind"]
        if kind in non_projecting_kinds:
            destinations = [f"/rules_selection_packets/packets/{event['sequence'] - 1}"]
            if kind == "method_acquisition":
                destinations.append("/ledger/method")
            semantic[f"event:{event['sequence']:03d}:{event['event_id']}"] = _non_sphere_event_provenance(event, record, contract, destinations)
            continue
        destinations = [f"/ledger/advancement/events/{event['sequence']}", f"/rules_selection_packets/packets/{event['sequence'] - 1}"]
        if kind == "starting_state": destinations += ["/ledger/core_stats/ability_generation"]
        elif kind == "background_acquisition": destinations += ["/ledger/background_origin/background", "/ledger/core_stats/ability_scores", "/ledger/core_stats/ability_modifiers"]
        elif kind == "origin_insight_acquisition": destinations += ["/ledger/background_origin/origin_insight"]
        elif kind == "path_acquisition": destinations += [f"/ledger/path_selections/{path_event_indexes.get(event['event_id'], 0)}"]
        elif kind in {"background_sphere_acquisition", "ai_bootstrap_sphere_acquisition"}: destinations += ["/ledger/spheres"]
        elif kind == "sphere_training_attempt": destinations += ["/ledger/spheres"]
        elif kind in {"background_talent_acquisition", "ai_bootstrap_talent_acquisition", "level_talent_acquisition"}: destinations += ["/ledger/talents"]
        elif kind == "cultivation_insight_acquisition": destinations += ["/ledger/insights", "/ledger/cultivation_insight_occurrences"]
        elif kind == "level_advance": destinations += ["/ledger/advancement/levels", "/ledger/core_stats/hp_generation", "/ledger/resources"]
        elif kind == "subpath_acquisition": destinations += ["/ledger/subpaths", "/ledger/features"]
        elif kind == "ability_score_change": destinations += ["/ledger/core_stats/ability_scores", "/ledger/core_stats/ability_modifiers"]
        elif kind == "typed_none": destinations += [f"/ledger/typed_none/{event['advancement']['details']['target']}"]
        semantic[f"event:{event['sequence']:03d}:{event['event_id']}"] = _event_provenance(event, record, contract, destinations, "CANONICAL_V3_EVENT_PROJECTION")
    for field, destinations in {
        "character.identity.display_name": ["/ledger/character/name"],
        "character.choices.qi_cultivation_skills": ["/ledger/path_selections/0/selected_skills", "/ledger/core_stats/proficient_skills"],
        "character.choices.street_hardened": ["/ledger/background_origin/origin_insight/selected_skill", "/ledger/core_stats/skill_proficiency_multipliers/Deception"],
        "character.choices.language": ["/ledger/background_origin/background/languages/0"],
    }.items():
        if field in locks:
            semantic[f"lock:{field}"] = _lock_provenance(locks[field], fixture_path, destinations, "OWNER_SELECTION_BINDING")
    baseline_destinations = {
        "tianxia.core.human.species.v1": ["/ledger/character/species"],
        "tianxia.core.human.creature_type.v1": ["/ledger/character/creature_type"],
        "tianxia.core.human.size.v1": ["/ledger/character/size"],
        "tianxia.core.human.walking_speed.v1": ["/ledger/core_stats/speed_ft", "/ledger/core_stats/speed_generation"],
        "tianxia.core.unarmored_ac.owner_r1": ["/ledger/core_stats/ac_base", "/ledger/core_stats/ac_active", "/ledger/core_stats/ac_generation"],
        "tianxia.core.initiative.owner_r1": ["/ledger/core_stats/initiative_bonus", "/ledger/core_stats/initiative_generation"],
    }
    for rule_id, destinations in baseline_destinations.items():
        trace = ac_result.trace if rule_id == "tianxia.core.unarmored_ac.owner_r1" else init_result.trace if rule_id == "tianxia.core.initiative.owner_r1" else None
        semantic[f"baseline:{rule_id}"] = _baseline_provenance(rules_by_id[rule_id], baseline, baseline_path, destinations, trace)
    state.provenance = semantic
    return state
