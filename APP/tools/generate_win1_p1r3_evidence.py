from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
OUTPUT = REPO / "win1_p1r3"


def write_json(name: str, value: Any) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / name).write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sphere_inventory() -> dict[str, Any]:
    catalog_path = ROOT / "catalog_authority" / "cat3" / "generated" / "catalog_authority.v1.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    rows_by_sphere: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in catalog["automatic_base_abilities"]:
        rows_by_sphere[row["mapped_canonical_sphere_id"]].append(row)

    field_names = (
        "action_type", "factory_combat_bucket", "factory_routing", "range", "cost",
        "target", "trigger", "effect", "use_limit", "scaling", "tags", "full_description",
    )
    spheres: list[dict[str, Any]] = []
    for sphere in catalog["spheres"]:
        source_rows = rows_by_sphere[sphere["canonical_sphere_id"]]
        unique: dict[str, dict[str, Any]] = {}
        for row in source_rows:
            unique.setdefault(row["runtime_component_id"], row)
        abilities = []
        for row in unique.values():
            detail = {name: row.get(name) for name in field_names}
            missing = [name for name, value in detail.items() if value in (None, "", [])]
            abilities.append({
                "runtime_component_id": row["runtime_component_id"],
                "display_name": row["display_name"],
                "automatic_grant": True,
                "owner_removable": False,
                "counts_as_talent_choice": False,
                "detail": detail,
                "source_provenance": row["source_provenance"],
                "record_commitment_sha256": row["record_commitment_sha256"],
                "fields_not_separately_stated_by_source": missing,
            })
        spheres.append({
            "canonical_sphere_id": sphere["canonical_sphere_id"],
            "display_name": sphere["display_name"],
            "source_row_count": len(source_rows),
            "automatic_component_count": len(abilities),
            "automatic_base_abilities": abilities,
            "explicit_no_automatic_base_ability_statement": (
                None if abilities else "No automatic base ability is projected from the authenticated current source for this Sphere."
            ),
            "source_section": sphere["source_provenance"],
        })
    karma = next(row for row in spheres if row["display_name"] == "Karma")
    assert [row["display_name"] for row in karma["automatic_base_abilities"]] == [
        "Invoke the Ledger", "Ledger Eye", "Record the Deed", "Settle Minor Account",
    ]
    assert all(row["detail"]["full_description"] for row in karma["automatic_base_abilities"])
    return {
        "schema": "TianxiaFoundry.WIN1P1R3SphereBaseAbilityInventory.v1",
        "scope": "Every canonical Sphere in the pinned CAT3 registry; automatic grants are free, non-removable, and do not consume a Talent choice.",
        "source_catalog": catalog_path.relative_to(REPO).as_posix(),
        "source_catalog_commitment_sha256": catalog["registry_commitment_sha256"],
        "summary": {
            "canonical_sphere_count": len(spheres),
            "sphere_source_row_count": sum(row["source_row_count"] for row in spheres),
            "unique_automatic_component_count": sum(row["automatic_component_count"] for row in spheres),
            "spheres_with_automatic_components": sum(bool(row["automatic_component_count"]) for row in spheres),
            "spheres_with_explicit_none_statement": sum(not row["automatic_component_count"] for row in spheres),
            "karma_automatic_component_count": karma["automatic_component_count"],
        },
        "spheres": spheres,
    }


def insight_inventories() -> tuple[dict[str, Any], dict[str, Any]]:
    central_path = REPO / "win1_p1r2" / "INSIGHT_SOURCE_AUTHORITY_MATRIX.json"
    background_path = ROOT / "non_sphere_authority" / "authority" / "Background_Core_Authority_v1.json"
    central = json.loads(central_path.read_text(encoding="utf-8"))
    backgrounds = json.loads(background_path.read_text(encoding="utf-8"))
    origin_occurrences: list[dict[str, str]] = []
    for background in backgrounds["backgrounds"]:
        for name in background["origin_insight"].get("suggested_options") or []:
            origin_occurrences.append({"background_id": background["background_id"], "display_name": name})
    origin_names = sorted({row["display_name"] for row in origin_occurrences})
    central_counts = Counter(row["insight_authority"]["authority_type"] for row in central["records"])
    unresolved = [
        {
            "record_id": row["record_id"],
            "display_name": row["display_name"],
            "authority": row["insight_authority"],
            "owner_decision_required": True,
        }
        for row in central["records"]
        if row["insight_authority"]["authority_type"] == "Unresolved"
    ]
    counts = {name: central_counts.get(name, 0) for name in (
        "General", "Sphere", "Path", "Method", "Foundation", "Background-Origin",
        "Item-Equipment", "Special", "Unresolved",
    )}
    counts["Background-Origin"] = len(origin_names)
    selectable_counts = {
        "General": 0,
        "Sphere": sum(1 for row in central["records"] if row["insight_authority"]["authority_type"] == "Sphere" and row.get("selectable", True)),
        "Path": sum(1 for row in central["records"] if row["insight_authority"]["authority_type"] == "Path" and row.get("selectable", True)),
        "Method": 0,
        "Foundation": 0,
        "Background-Origin": len(origin_names),
        "Item-Equipment": 0,
        "Special": 0,
        "Unresolved": 0,
    }
    inventory = {
        "schema": "TianxiaFoundry.WIN1P1R3InsightAuthorityInventory.v1",
        "scope": "All current central cultivation Insight records plus every exact Background/Origin suggested Insight name.",
        "preservation_rule": "Current source-backed classifications are preserved; no General choices, reclassification, or Sphere grouping were invented.",
        "summary": {
            "central_unique_record_count": len(central["records"]),
            "background_origin_unique_name_count": len(origin_names),
            "background_origin_source_occurrence_count": len(origin_occurrences),
            "combined_unique_owner_facing_count": len(central["records"]) + len(origin_names),
            "authority_type_counts": counts,
            "owner_facing_selectable_authority_type_counts": selectable_counts,
            "unresolved_owner_facing_count": len(unresolved),
        },
        "sources": [
            {"path": central_path.relative_to(REPO).as_posix(), **central["source"]},
            {"path": background_path.relative_to(REPO).as_posix(), "schema": backgrounds["schema"], "background_count": backgrounds["count"]},
        ],
        "central_records": central["records"],
        "background_origin_records": [
            {
                "display_name": name,
                "authority_type": "Background-Origin",
                "background_bindings": sorted(row["background_id"] for row in origin_occurrences if row["display_name"] == name),
            }
            for name in origin_names
        ],
    }
    adjudication = {
        "schema": "TianxiaFoundry.WIN1P1R3UnresolvedInsightOwnerAdjudication.v1",
        "classification_policy": "Only actual source fields may resolve an item; no name-only or sibling-record inference is permitted.",
        "unresolved_owner_facing_count": len(unresolved),
        "items": unresolved,
        "disposition": "NO_OWNER_ADJUDICATION_REQUIRED" if not unresolved else "OWNER_ADJUDICATION_REQUIRED",
    }
    return inventory, adjudication


def method_switch_inventory() -> dict[str, Any]:
    registry_path = ROOT / "non_sphere_authority" / "authority" / "Tianxia_Methods_Typed_Registry_v0_6.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    return {
        "schema": "TianxiaFoundry.WIN1P1R3MethodSwitchPreservationInventory.v1",
        "scope": "Preservation inventory only. WIN1-P1R3 adds no switching UI, timing, window, cost, or new rule.",
        "existing_operation": "POST /api/non-sphere/projects/{project_id}/primary-method",
        "existing_service_operation": "NonSphereAuthorityService.set_primary_method",
        "backend_invariants": [
            "historical attainment is preserved",
            "the event stream is not rewritten",
            "resources are not restored",
            "future AP may be invalidated only for incompatible Paths",
            "post-creation switching still requires exact method_access evidence",
        ],
        "method_count": len(registry["methods"]),
        "methods": [
            {
                "method_id": row["method_id"],
                "name": row["name"],
                "switching_lifecycle": row["switching_lifecycle"],
                "source_evidence": row["source_evidence"],
            }
            for row in registry["methods"]
        ],
        "deferred": "Owner-conceptualized Method-switch timing/window design remains future scope.",
    }


def main() -> int:
    write_json("SPHERE_BASE_ABILITY_INVENTORY.json", sphere_inventory())
    inventory, adjudication = insight_inventories()
    write_json("INSIGHT_AUTHORITY_INVENTORY.json", inventory)
    write_json("UNRESOLVED_INSIGHT_OWNER_ADJUDICATION.json", adjudication)
    write_json("METHOD_SWITCH_PRESERVATION_INVENTORY.json", method_switch_inventory())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
