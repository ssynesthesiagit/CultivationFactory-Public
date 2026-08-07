from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.core import CORE_PACK_ID, CORE_PACK_VERSION, Database, FoundryError, sha256_json
from catalog.service import CatalogService
from contracts.canonical import canonical_record_hash


REPORT_SCHEMA = "TianxiaFoundry.Stage1CatalogAuthorityCoverage.v1"
PUBLISHED_AUTHORITIES = ("canonical", "published-extension")
NON_AUTHORITATIVE_CHANNELS = {"administrative", "catalog-defined", "reference-only"}
HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
INTENT_RELAXED_SLOTS = {
    "subpath_choice",
    "sphere_priorities",
    "advancement_skeleton",
    "insight_priorities",
}


@dataclass(frozen=True)
class CategorySpec:
    slot_id: str
    label: str
    content_types: tuple[str, ...]
    parent_type_groups: tuple[tuple[str, ...], ...] = ()
    coverage_role: str = "decision_slot"


# This is an authority-coverage contract, not a copy of a UI envelope.  In
# particular, a background Sphere/Talent needs an authoritative relationship
# to a published Background, and a Talent needs an authoritative parent Sphere.
STAGE1_CATEGORY_SPECS: tuple[CategorySpec, ...] = (
    CategorySpec("path_choice", "Primary Path", ("path",)),
    CategorySpec("subpath_choice", "Subpath or Tradition", ("subpath", "tradition"), (("path",),)),
    CategorySpec("background_choice", "Background", ("background",)),
    CategorySpec("background_sphere_choice", "Background Sphere", ("background_sphere",), (("background",),)),
    CategorySpec("background_talent_choice", "Background Talent", ("background_talent",), (("background_sphere",), ("background",))),
    CategorySpec("origin_insight_choice", "Origin Insight", ("origin_insight",)),
    CategorySpec("method_choice", "Proposed Cultivation Method", ("cultivation_method",)),
    CategorySpec("foundation_choice", "Proposed Foundation Expression", ("foundation_expression", "foundation")),
    CategorySpec("sphere_priorities", "Additional Sphere Priorities", ("sphere",)),
    CategorySpec("advancement_skeleton", "Published Talent Priorities", ("talent",), (("sphere",),)),
    CategorySpec("insight_priorities", "Additional Insight Priorities", ("cultivation_insight", "insight")),
    CategorySpec("item_priorities", "Preferred Items and Equipment", ("item", "equipment", "weapon", "armor", "treasure", "treasure_set", "consumable", "growth_treasure")),
    CategorySpec(
        "equipment_reference",
        "Item and Equipment Authority",
        ("item", "equipment", "weapon", "armor", "treasure_set"),
        coverage_role="reference",
    ),
    CategorySpec(
        "martial_manual_recorded_art_reference",
        "Martial Manual and Recorded Art Classification Authority",
        ("martial_manual", "recorded_art", "manual", "manual_technique"),
        coverage_role="reference",
    ),
    CategorySpec(
        "forged_technique_reference",
        "Forged Technique Classification Authority",
        ("forged_technique", "forged_technique_rule", "forging_rule"),
        coverage_role="reference",
    ),
)


def _block(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "reason_type": "blocked_missing_authority",
        "code": code,
        "message": message,
        "details": details,
    }


def _record_targets(record: dict[str, Any]) -> set[str]:
    targets = {value for value in record.get("dependencies", []) if isinstance(value, str)}
    for item in record.get("legality", {}).get("prerequisites", []):
        if isinstance(item, dict) and isinstance(item.get("target_id"), str):
            targets.add(item["target_id"])
    for item in record.get("grants", []):
        if isinstance(item, dict) and isinstance(item.get("target_id"), str):
            targets.add(item["target_id"])
    return targets


def _record_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    binding = record.get("content_binding", {})
    return (
        record["record_id"],
        str(binding.get("pack_id") or ""),
        str(binding.get("pack_version") or ""),
        str(record.get("record_hash") or ""),
    )


class Stage1CatalogCoverageService:
    """Deterministically prove which Stage 1 categories have usable authority.

    A record being present in SQLite is deliberately insufficient.  Selection
    requires a selected, published authority row, a valid immutable record hash,
    a real acquisition channel, resolved prerequisites, and every category-level
    parent relationship required by the Stage 1 decision contract.
    """

    def __init__(self, db: Database):
        self.db = db

    def _scope(self, conn, project_id: str | None) -> tuple[list[tuple[str, str, str]], dict[str, Any], str | None]:
        if project_id is None:
            return [], {"kind": "catalog", "project_id": None, "content_locks": [], "catalog_build_id": None}, None
        project = conn.execute("SELECT catalog_build_hash FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if not project:
            raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)
        catalog_build_id = str(project["catalog_build_hash"] or "catalog.unbuilt")
        locks = [
            (row["pack_id"], row["version"], row["pack_hash"])
            for row in conn.execute(
                "SELECT pack_id,version,pack_hash FROM project_content_locks WHERE project_id=? ORDER BY pack_id,version",
                (project_id,),
            )
        ]
        return locks, {
            "kind": "project_content_lock",
            "project_id": project_id,
            "catalog_build_id": catalog_build_id,
            "content_locks": [
                {"pack_id": pack_id, "pack_version": version, "pack_hash": pack_hash}
                for pack_id, version, pack_hash in locks
            ],
        }, catalog_build_id

    @staticmethod
    def _base_evaluation(record: dict[str, Any], *, include_test: bool) -> dict[str, Any]:
        compatibility = record.get("compatibility", {}).get("factory", {})
        authority = str(compatibility.get("authority_classification") or "unresolved")
        selected = bool(compatibility.get("selected_authority"))
        publication = str(record.get("publication", {}).get("status") or "draft")
        stored_hash = record.get("record_hash")
        computed_hash = canonical_record_hash(record)
        hash_valid = isinstance(stored_hash, str) and bool(HASH_PATTERN.fullmatch(stored_hash)) and stored_hash == computed_hash
        source_hash = record.get("source", {}).get("source_hash")
        source_hash_valid = isinstance(source_hash, str) and bool(HASH_PATTERN.fullmatch(source_hash))
        unresolved = list(compatibility.get("unresolved_normalization_notes") or [])
        retained_prereqs = list(compatibility.get("retained_prerequisites") or [])
        channels = sorted(set(record.get("legality", {}).get("acquisition_channels") or []))
        usable_channels = [channel for channel in channels if channel not in NON_AUTHORITATIVE_CHANNELS]
        allowed_authorities = set(PUBLISHED_AUTHORITIES) | ({"test-only"} if include_test else set())

        prerequisites = record.get("legality", {}).get("prerequisites") or []
        target_ids = sorted({item.get("target_id") for item in prerequisites if isinstance(item, dict) and isinstance(item.get("target_id"), str)})
        blockers: list[dict[str, Any]] = []
        if authority not in allowed_authorities:
            blockers.append(_block("AUTHORITY_NOT_SELECTABLE", "Record lacks canonical or published-extension authority.", authority=authority))
        if not selected:
            blockers.append(_block("AUTHORITY_VARIANT_NOT_SELECTED", "Record is not the selected authority variant."))
        if publication != "published":
            blockers.append(_block("PUBLICATION_NOT_PUBLISHED", "Record is not published.", publication_status=publication))
        if not hash_valid:
            blockers.append(_block("RECORD_HASH_UNPROVEN", "Stored record hash does not match canonical record bytes.", stored_hash=stored_hash, computed_hash=computed_hash))
        if not source_hash_valid:
            blockers.append(_block("SOURCE_HASH_UNPROVEN", "Record source hash is absent or malformed.", source_hash=source_hash))
        if unresolved:
            blockers.append(_block("UNRESOLVED_NORMALIZATION", "Record still has unresolved normalization notes.", notes=unresolved))
        if retained_prereqs:
            blockers.append(_block("PREREQUISITE_NOT_NORMALIZED", "Record retains prerequisite expressions outside the canonical prerequisite contract.", retained=retained_prereqs))
        if not usable_channels:
            blockers.append(_block("ACQUISITION_CHANNEL_AUTHORITY_MISSING", "Record has no authoritative acquisition channel.", channels=channels))
        return {
            "authority": authority,
            "selected_authority": selected,
            "publication_status": publication,
            "record_hash": stored_hash,
            "computed_record_hash": computed_hash,
            "record_hash_valid": hash_valid,
            "source_hash": source_hash,
            "source_hash_valid": source_hash_valid,
            "channel_coverage": {
                "status": "covered" if usable_channels else "blocked_missing_authority",
                "declared_channels": channels,
                "usable_channels": usable_channels,
            },
            "prerequisite_coverage": {
                "status": "pending_fixed_point" if target_ids and not retained_prereqs else ("covered" if not retained_prereqs else "blocked_missing_authority"),
                "declared_target_ids": target_ids,
                "resolved_target_ids": [],
                "missing_target_ids": [],
                "retained_unnormalized_count": len(retained_prereqs),
            },
            "intrinsic_selectable": not blockers,
            "base_selectable": False,
            "blocked_reasons": blockers,
        }

    @staticmethod
    def _validated_reference_index(evaluation: dict[str, Any]) -> bool:
        """Allow a trusted index to name blueprint preferences, not mechanics."""
        codes = {reason["code"] for reason in evaluation["blocked_reasons"]}
        return (
            evaluation["authority"] == "reference-only"
            and evaluation["selected_authority"]
            and evaluation["publication_status"] == "validated"
            and evaluation["record_hash_valid"]
            and evaluation["source_hash_valid"]
            and evaluation["channel_coverage"]["status"] == "covered"
            and codes == {
                "AUTHORITY_NOT_SELECTABLE",
                "PUBLICATION_NOT_PUBLISHED",
                "UNRESOLVED_NORMALIZATION",
            }
        )

    @staticmethod
    def _resolve_prerequisite_authority(
        records: list[dict[str, Any]],
        base: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> None:
        """Resolve prerequisites with a deterministic least fixed point.

        Starting from intrinsically usable records with no prerequisites means
        authority chains become selectable only when every target already has a
        fully selectable variant.  Unrooted cycles therefore remain blocked
        instead of mutually laundering authority.
        """
        ordered = sorted(records, key=_record_key)
        by_id: dict[str, list[dict[str, Any]]] = {}
        for record in ordered:
            by_id.setdefault(record["record_id"], []).append(record)

        selectable: set[tuple[str, str, str, str]] = set()
        changed = True
        while changed:
            changed = False
            for record in ordered:
                key = _record_key(record)
                evaluation = base[key]
                if key in selectable or not evaluation["intrinsic_selectable"]:
                    continue
                targets = evaluation["prerequisite_coverage"]["declared_target_ids"]
                if all(any(_record_key(variant) in selectable for variant in by_id.get(target, [])) for target in targets):
                    selectable.add(key)
                    changed = True

        for record in ordered:
            key = _record_key(record)
            evaluation = base[key]
            targets = evaluation["prerequisite_coverage"]["declared_target_ids"]
            resolved = sorted(
                target
                for target in targets
                if any(_record_key(variant) in selectable for variant in by_id.get(target, []))
            )
            missing = sorted(set(targets) - set(resolved))
            evaluation["prerequisite_coverage"] = {
                "status": "covered" if not missing and evaluation["prerequisite_coverage"]["retained_unnormalized_count"] == 0 else "blocked_missing_authority",
                "declared_target_ids": targets,
                "resolved_target_ids": resolved,
                "missing_target_ids": missing,
                "retained_unnormalized_count": evaluation["prerequisite_coverage"]["retained_unnormalized_count"],
            }
            if missing:
                evaluation["blocked_reasons"].append(_block(
                    "PREREQUISITE_TARGET_AUTHORITY_MISSING",
                    "One or more prerequisite targets lack fully selectable published authority.",
                    target_ids=missing,
                ))
            evaluation["base_selectable"] = key in selectable

    @staticmethod
    def _parent_coverage(
        record: dict[str, Any],
        parent_type_groups: tuple[tuple[str, ...], ...],
        selectable_by_id: dict[str, list[dict[str, Any]]],
        reverse_targets: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        if not parent_type_groups:
            return {"status": "not_required", "required_type_groups": [], "groups": []}
        candidate_targets = _record_targets(record)
        reverse_parents = reverse_targets.get(record["record_id"], [])
        groups: list[dict[str, Any]] = []
        complete = True
        for allowed_types in parent_type_groups:
            allowed = set(allowed_types)
            matching: set[str] = set()
            for target_id in candidate_targets:
                for parent in selectable_by_id.get(target_id, []):
                    if parent.get("content_type") in allowed:
                        matching.add(parent["record_id"])
            for parent in reverse_parents:
                if parent.get("content_type") in allowed:
                    matching.add(parent["record_id"])
            ordered = sorted(matching)
            if not ordered:
                complete = False
            groups.append({
                "required_parent_types": list(allowed_types),
                "status": "covered" if ordered else "blocked_missing_authority",
                "published_parent_record_ids": ordered,
            })
        return {
            "status": "covered" if complete else "blocked_missing_authority",
            "required_type_groups": [list(group) for group in parent_type_groups],
            "groups": groups,
        }

    def build(self, *, project_id: str | None = None, include_test: bool = False) -> dict[str, Any]:
        with self.db.connection() as conn:
            locks, scope, scoped_build_id = self._scope(conn, project_id)
            if project_id is None:
                build_row = conn.execute("SELECT build_id,source_hash,record_count,unresolved_count FROM catalog_builds ORDER BY created_at DESC LIMIT 1").fetchone()
            elif scoped_build_id and scoped_build_id != "catalog.unbuilt":
                build_row = conn.execute(
                    "SELECT build_id,source_hash,record_count,unresolved_count FROM catalog_builds WHERE build_id=?",
                    (scoped_build_id,),
                ).fetchone()
            else:
                build_row = None
            if project_id is None:
                rows = conn.execute(
                    """SELECT r.data_json,p.authority AS pack_authority,receipt.trust_state
                       FROM catalog_records r
                       JOIN content_packs p ON p.pack_id=r.pack_id AND p.version=r.pack_version
                       LEFT JOIN content_pack_install_receipts receipt
                         ON receipt.pack_id=p.pack_id AND receipt.version=p.version
                        AND receipt.canonical_content_hash=p.pack_hash
                       WHERE r.selected_authority=1 AND p.lifecycle_state='published'
                       ORDER BY r.record_id,r.pack_id,r.pack_version,r.row_id"""
                ).fetchall()
                scoped_records = []
                for row in rows:
                    record = json.loads(row["data_json"])
                    binding = record.get("content_binding", {})
                    if binding.get("pack_id") == CORE_PACK_ID and binding.get("pack_version") != CORE_PACK_VERSION:
                        # Retain historical core versions for locked saved projects,
                        # but expose only the current core authority in unscoped owner options.
                        continue
                    trusted = (
                        row["pack_authority"] == "canonical"
                        or (row["pack_authority"] == "test-only" and include_test)
                        or (
                            row["pack_authority"] == "published-extension"
                            and row["trust_state"] in {"trusted_signed", "human_trusted_exact_archive"}
                        )
                    )
                    if trusted:
                        scoped_records.append(record)
                effective = None
            else:
                effective = CatalogService._effective_catalog_with_conn(conn, project_id, include_test=include_test)
                scoped_records = effective["records"]
        scoped_records.sort(key=lambda item: (item["record_id"], item["record_hash"]))

        base = {
            _record_key(record): self._base_evaluation(record, include_test=include_test)
            for record in scoped_records
        }
        self._resolve_prerequisite_authority(scoped_records, base)
        validated_reference_indexes = [
            record
            for record in scoped_records
            if record.get("content_type") == "sphere"
            and self._validated_reference_index(base[_record_key(record)])
        ]
        selectable_by_id: dict[str, list[dict[str, Any]]] = {}
        reverse_targets: dict[str, list[dict[str, Any]]] = {}
        for candidate in scoped_records:
            if not base[_record_key(candidate)]["base_selectable"]:
                continue
            selectable_by_id.setdefault(candidate["record_id"], []).append(candidate)
            for target_id in _record_targets(candidate):
                reverse_targets.setdefault(target_id, []).append(candidate)

        categories: list[dict[str, Any]] = []
        for spec in STAGE1_CATEGORY_SPECS:
            candidates = [record for record in scoped_records if record.get("content_type") in spec.content_types]
            record_rows: list[dict[str, Any]] = []
            for record in candidates:
                evaluation = base[_record_key(record)]
                parent = self._parent_coverage(record, spec.parent_type_groups, selectable_by_id, reverse_targets)
                blocked = list(evaluation["blocked_reasons"])
                if parent["status"] == "blocked_missing_authority":
                    blocked.append(_block(
                        "PARENT_RELATIONSHIP_AUTHORITY_MISSING",
                        "Record lacks a published authoritative relationship to every required parent category.",
                        required_type_groups=parent["required_type_groups"],
                    ))
                strict_selectable = not blocked
                intent_selectable = strict_selectable
                intent_limitations: list[str] = []
                block_codes = {reason["code"] for reason in blocked}
                if spec.slot_id == "subpath_choice" and block_codes == {"PREREQUISITE_NOT_NORMALIZED"}:
                    intent_selectable = parent["status"] != "blocked_missing_authority"
                    intent_limitations.append("Prerequisite text is retained for later Factory validation.")
                elif spec.slot_id == "sphere_priorities" and self._validated_reference_index(evaluation):
                    intent_selectable = True
                    intent_limitations.append("Sphere index selection expresses blueprint preference and does not grant Sphere mechanics.")
                elif spec.slot_id == "advancement_skeleton" and block_codes == {"PARENT_RELATIONSHIP_AUTHORITY_MISSING"}:
                    linked_indexes = sorted(
                        parent_record["record_id"]
                        for parent_record in validated_reference_indexes
                        if record["record_id"] in _record_targets(parent_record)
                    )
                    if linked_indexes:
                        intent_selectable = True
                        intent_limitations.append("Talent-to-Sphere linkage is proven by the validated Sphere index; acquisition remains ungranted.")
                elif spec.slot_id == "insight_priorities" and block_codes == {"PREREQUISITE_NOT_NORMALIZED"}:
                    intent_selectable = True
                    intent_limitations.append("Insight prerequisite text is retained for later Factory validation.")
                binding = record.get("content_binding", {})
                record_rows.append({
                    "record_id": record["record_id"],
                    "display_name": record["display_name"],
                    "content_type": record["content_type"],
                    "record_hash": evaluation["record_hash"],
                    "computed_record_hash": evaluation["computed_record_hash"],
                    "record_hash_valid": evaluation["record_hash_valid"],
                    "source_hash": evaluation["source_hash"],
                    "source_hash_valid": evaluation["source_hash_valid"],
                    "authority": evaluation["authority"],
                    "publication_status": evaluation["publication_status"],
                    "selected_authority": evaluation["selected_authority"],
                    "content_binding": {
                        "pack_id": binding.get("pack_id"),
                        "pack_version": binding.get("pack_version"),
                        "pack_hash": binding.get("pack_hash"),
                    },
                    "parent_coverage": parent,
                    "prerequisite_coverage": evaluation["prerequisite_coverage"],
                    "channel_coverage": evaluation["channel_coverage"],
                    "selectable": strict_selectable,
                    "intent_selectable": intent_selectable,
                    "intent_limitations": intent_limitations,
                    "blocked_reasons": blocked,
                })
            selectable = [row for row in record_rows if row["selectable"]]
            intent_selectable = [row for row in record_rows if row["intent_selectable"]]
            category_reasons: list[dict[str, Any]] = []
            if not candidates:
                category_reasons.append(_block("CATEGORY_RECORDS_MISSING", "No catalog records exist for this Stage 1 category.", content_types=list(spec.content_types)))
            elif not selectable:
                codes = sorted({reason["code"] for row in record_rows for reason in row["blocked_reasons"]})
                category_reasons.append(_block("CATEGORY_SELECTABLE_AUTHORITY_MISSING", "No record in this Stage 1 category has complete selectable authority.", record_block_codes=codes))
            categories.append({
                "slot_id": spec.slot_id,
                "label": spec.label,
                "coverage_role": spec.coverage_role,
                "content_types": list(spec.content_types),
                "status": "selectable" if selectable else "blocked_missing_authority",
                "record_count": len(record_rows),
                "selectable_record_count": len(selectable),
                "selectable_record_ids": [row["record_id"] for row in selectable],
                "intent_selectable_record_count": len(intent_selectable),
                "intent_selectable_record_ids": [row["record_id"] for row in intent_selectable],
                "intent_selection_enabled": spec.slot_id in INTENT_RELAXED_SLOTS,
                "blocked_reasons": category_reasons,
                "records": record_rows,
            })

        blocked_categories = [category["slot_id"] for category in categories if category["status"] == "blocked_missing_authority"]
        blocked_slots = [category["slot_id"] for category in categories if category["coverage_role"] == "decision_slot" and category["status"] == "blocked_missing_authority"]
        blocked_references = [category["slot_id"] for category in categories if category["coverage_role"] == "reference" and category["status"] == "blocked_missing_authority"]
        decision_count = sum(category["coverage_role"] == "decision_slot" for category in categories)
        reference_count = len(categories) - decision_count
        report: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA,
            "catalog_build": dict(build_row) if build_row else None,
            "scope": scope,
            "policy": {
                "published_authorities": list(PUBLISHED_AUTHORITIES) + (["test-only"] if include_test else []),
                "test_authority_included": include_test,
                "non_authoritative_channels": sorted(NON_AUTHORITATIVE_CHANNELS),
                "record_hash_recomputation_required": True,
                "prerequisite_target_authority_required": True,
                "parent_relationship_authority_required": True,
                "prerequisite_resolution": "deterministic_least_fixed_point_cycles_blocked",
                "decision_slots_and_reference_coverage_are_distinct": True,
                "blueprint_intent_does_not_grant_mechanics": True,
                "intent_relaxed_slots": sorted(INTENT_RELAXED_SLOTS),
            },
            "summary": {
                "category_count": len(categories),
                "selectable_category_count": len(categories) - len(blocked_categories),
                "blocked_category_count": len(blocked_categories),
                "blocked_category_ids": blocked_categories,
                "decision_slot_count": decision_count,
                "blocked_decision_slot_ids": blocked_slots,
                "reference_category_count": reference_count,
                "blocked_reference_category_ids": blocked_references,
                "blocked_slot_ids": blocked_slots,
                "status": "complete" if not blocked_categories else "blocked_missing_authority",
            },
            "categories": categories,
        }
        if effective is not None:
            report["scope"]["effective_catalog_hash"] = effective["effective_catalog_hash"]
            report["scope"]["replacements_applied"] = effective["replacements_applied"]
            report["scope"]["suppressed_records"] = effective["suppressed_records"]
        report["report_hash"] = sha256_json(report)
        return report
