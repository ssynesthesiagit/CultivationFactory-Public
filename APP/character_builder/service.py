from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from app.core import CORE_PACK_ID, CORE_PACK_VERSION, Database, FoundryError
from catalog.coverage import Stage1CatalogCoverageService
from catalog.service import CatalogService, _exact_pack_version_matches
from canonical_catalog import CanonicalCatalogAuthorityService
from content_packs.service import ContentPackManager
from project_store.service import ProjectStore
from non_sphere_authority import NonSphereAuthorityService
from path_method_authority import (
    CANONICAL_PATH_IDS,
    compatibility_envelope,
    canonicalize_path_ids,
    method_path_compatibility,
    no_compatible_method_error,
)
from character_builder.insight_authority import classify_insight_authority, resolve_insight_occurrences
from catalog_choice_authority import COMMITTED_CATALOG_CHOICE_FIELD

ABILITY_ORDER = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
POINT_BUY_COSTS = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
POINT_BUY_BUDGET = 27

CATEGORY_CONFIG: tuple[dict[str, Any], ...] = (
    {"slot_id": "path_choice", "label": "Advancing Path Requirements", "kind": "multi", "max": 3},
    {"slot_id": "subpath_choice", "label": "Subpath or Tradition", "kind": "single", "max": 1},
    {"slot_id": "background_choice", "label": "Background", "kind": "single", "max": 1},
    {"slot_id": "background_sphere_choice", "label": "Background Sphere", "kind": "single", "max": 1},
    {"slot_id": "background_talent_choice", "label": "Background Talent", "kind": "single", "max": 1},
    {"slot_id": "origin_insight_choice", "label": "Origin Insight", "kind": "single", "max": 1},
    {"slot_id": "method_choice", "label": "Cultivation Method", "kind": "single", "max": 1},
    {"slot_id": "foundation_choice", "label": "Foundation", "kind": "single", "max": 1},
    {"slot_id": "sphere_priorities", "label": "Additional Spheres", "kind": "multiple", "max": 8},
    {"slot_id": "advancement_skeleton", "label": "Talent Priorities", "kind": "multiple", "max": None},
    {"slot_id": "insight_priorities", "label": "Additional Insights", "kind": "multiple", "max": 8},
    {"slot_id": "item_priorities", "label": "Items and Equipment", "kind": "multiple", "max": 8},
)

INTENT_OPTION_SLOTS = {
    "subpath_choice",
    "sphere_priorities",
    "advancement_skeleton",
    "insight_priorities",
}


def _version_key(value: str) -> tuple[Any, ...]:
    parts = re.split(r"([0-9]+)", value)
    return tuple(int(part) if part.isdigit() else part.casefold() for part in parts)


def _normalized_visible_name(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _authority_disposition(choice: dict[str, Any]) -> str:
    coverage = choice.get("authority_coverage")
    if not isinstance(coverage, dict):
        return ""
    return str(coverage.get("disposition") or coverage.get("authority_disposition") or "").strip().casefold()


def _dedupe_choice_rows(choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse only exact repeated IDs, preserving the first authoritative row."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for choice in choices:
        choice_id = str(choice.get("choice_id") or "")
        if not choice_id or choice_id in seen:
            continue
        seen.add(choice_id)
        result.append(choice)
    return result


def _build_sphere_talent_index(categories: list[dict[str, Any]]) -> dict[str, Any]:
    """Build exact source-backed mappings and a two-direction authority audit."""
    by_slot = {category["slot_id"]: category for category in categories}
    spheres = by_slot.get("sphere_priorities", {}).get("choices", [])
    talents = by_slot.get("advancement_skeleton", {}).get("choices", [])
    sphere_by_id = {choice["choice_id"]: choice for choice in spheres}
    talent_by_id = {choice["choice_id"]: choice for choice in talents}
    sphere_ids = set(sphere_by_id)
    talent_ids = set(talent_by_id)

    forward: dict[str, set[str]] = {talent_id: set() for talent_id in talent_ids}
    for sphere_id, sphere in sphere_by_id.items():
        for related_id in sphere.get("related_choice_ids") or []:
            if related_id in talent_ids:
                forward[related_id].add(sphere_id)

    reverse: dict[str, set[str]] = {talent_id: set() for talent_id in talent_ids}
    for talent_id, talent in talent_by_id.items():
        for related_id in talent.get("related_choice_ids") or []:
            if related_id in sphere_ids:
                reverse[talent_id].add(related_id)

    by_sphere: dict[str, list[str]] = {sphere_id: [] for sphere_id in sorted(sphere_ids)}
    by_talent: dict[str, list[str]] = {}
    ambiguous: list[dict[str, Any]] = []
    unmapped: list[str] = []
    multi_sphere = 0
    for talent_id in sorted(talent_ids):
        direct = forward[talent_id]
        backref = reverse[talent_id]
        conflicting = bool(direct and backref and direct != backref)
        candidates = sorted(direct | backref)
        talent = talent_by_id[talent_id]
        if conflicting:
            talent["mapping_status"] = "ambiguous"
            talent["sphere_choice_ids"] = []
            talent["candidate_sphere_choice_ids"] = candidates
            ambiguous.append({
                "talent_choice_id": talent_id,
                "forward_sphere_choice_ids": sorted(direct),
                "reverse_sphere_choice_ids": sorted(backref),
            })
            by_talent[talent_id] = []
        elif candidates:
            talent["mapping_status"] = "mapped"
            talent["sphere_choice_ids"] = candidates
            talent["candidate_sphere_choice_ids"] = candidates
            by_talent[talent_id] = candidates
            if len(candidates) > 1:
                multi_sphere += 1
            for sphere_id in candidates:
                by_sphere[sphere_id].append(talent_id)
        else:
            talent["mapping_status"] = "unmapped"
            talent["sphere_choice_ids"] = []
            talent["candidate_sphere_choice_ids"] = []
            by_talent[talent_id] = []
            unmapped.append(talent_id)

    per_sphere: dict[str, dict[str, Any]] = {}
    zero = one = multiple = 0
    declared_excluded = declared_missing = 0
    authority_summary: dict[str, Any] = {}
    for sphere_id, talent_choice_ids in by_sphere.items():
        talent_choice_ids.sort(key=lambda talent_id: (
            _normalized_visible_name(talent_by_id[talent_id].get("name")), talent_id,
        ))
        sphere = sphere_by_id[sphere_id]
        sphere["talent_choice_ids"] = list(talent_choice_ids)
        coverage = sphere.get("authority_coverage") if isinstance(sphere.get("authority_coverage"), dict) else {}
        if not authority_summary and isinstance(sphere.get("authority_summary"), dict):
            authority_summary = dict(sphere["authority_summary"])
        declared_excluded += len(coverage.get("declared_relation_excluded_ids") or [])
        declared_missing += len(coverage.get("declared_relation_missing_ids") or [])
        count = len(talent_choice_ids)
        zero += int(count == 0)
        one += int(count == 1)
        multiple += int(count > 1)
        disposition = str(coverage.get("disposition") or ("covered_multiple" if count > 1 else "covered_one" if count == 1 else "source_authority_gap"))
        per_sphere[sphere_id] = {
            "sphere_choice_id": sphere_id,
            "sphere_name": sphere.get("canonical_name") or sphere.get("name") or sphere_id,
            "selectable_talent_count": count,
            "source_candidate_count": int(coverage.get("source_candidate_count") or 0),
            "disposition": disposition,
            "declared_relation_excluded_ids": list(coverage.get("declared_relation_excluded_ids") or []),
            "declared_relation_missing_ids": list(coverage.get("declared_relation_missing_ids") or []),
            "honest_label": (
                f"{count} source-authorized Talent{'s' if count != 1 else ''}"
                if count else "Authority gap — no source-confirmed selectable Talents"
            ),
        }
        sphere["coverage_disposition"] = disposition
        sphere["coverage_label"] = per_sphere[sphere_id]["honest_label"]

    audit = {
        "source_talent_candidates_examined": int(authority_summary.get("source_talent_candidates_examined") or len(talent_ids)),
        "genuine_selectable_talent_count": len(talent_ids),
        "rejected_non_talent_row_count": int(authority_summary.get("rejected_non_talent_rows") or 0),
        "rejected_by_reason": dict(authority_summary.get("rejected_by_reason") or {}),
        "unresolved_talent_candidate_count": int(authority_summary.get("unresolved_talent_candidates") or 0),
        "sphere_count": len(sphere_ids),
        "talent_count": len(talent_ids),
        "mapped_count": len(talent_ids) - len(unmapped) - len(ambiguous),
        "ambiguous_count": len(ambiguous),
        "unmapped_count": len(unmapped),
        "multi_sphere_count": multi_sphere,
        "spheres_zero_talents": zero,
        "spheres_one_talent": one,
        "spheres_multiple_talents": multiple,
        "declared_relations_to_excluded_records": declared_excluded,
        "declared_relations_to_missing_records": declared_missing,
    }
    return {
        "schema_version": "TianxiaFoundry.SphereTalentIndex.v2",
        "authority_method": "exact pinned-source heading roles and exact stable Sphere IDs; no fuzzy or label inference",
        "by_sphere": by_sphere,
        "by_talent": by_talent,
        "per_sphere_coverage": per_sphere,
        "unassigned_talent_ids": sorted(set(unmapped) | {row["talent_choice_id"] for row in ambiguous}),
        "ambiguous_talents": ambiguous,
        "audit": audit,
    }


def _qualify_duplicate_visible_names(categories: list[dict[str, Any]], index: dict[str, Any]) -> None:
    sphere_category = next((row for row in categories if row["slot_id"] == "sphere_priorities"), None)
    sphere_names = {
        choice["choice_id"]: str(choice.get("name") or choice["choice_id"])
        for choice in (sphere_category or {}).get("choices", [])
    }
    for category in categories:
        groups: dict[str, list[dict[str, Any]]] = {}
        for choice in category.get("choices", []):
            groups.setdefault(_normalized_visible_name(choice.get("name")), []).append(choice)
        for rows in groups.values():
            if len(rows) < 2:
                continue
            qualifiers: dict[str, int] = {}
            provisional: dict[str, str] = {}
            for choice in rows:
                canonical = str(choice.get("name") or choice["choice_id"])
                sphere_ids = choice.get("sphere_choice_ids") or choice.get("candidate_sphere_choice_ids") or []
                if sphere_ids:
                    qualifier = " / ".join(sphere_names.get(sphere_id, sphere_id) for sphere_id in sphere_ids)
                else:
                    qualifier = f"{choice.get('pack_id') or 'authority'} {choice.get('pack_version') or ''}".strip()
                provisional[choice["choice_id"]] = qualifier
                qualifiers[qualifier] = qualifiers.get(qualifier, 0) + 1
                choice["canonical_name"] = canonical
            for choice in rows:
                qualifier = provisional[choice["choice_id"]]
                if qualifiers[qualifier] > 1:
                    qualifier = f"{qualifier} · {choice['choice_id']}"
                choice["source_qualifier"] = qualifier
                choice["name"] = f"{choice['canonical_name']} — {qualifier}"


class CharacterBuilderService:
    """Owner-facing character-sheet intake over the immutable catalog.

    This service stores human selections as blueprint locks. It does not convert
    them into advancement events or mechanics. Stage 1 remains the untrusted-AI
    planning boundary, while the local catalog remains the only source of IDs.
    """

    _OPTIONS_CACHE: dict[tuple[str, str], dict[str, Any]] = {}

    def _options_identity(self) -> tuple[str, str]:
        from app.core import sha256_json
        with self.db.connection() as conn:
            build = conn.execute("SELECT build_id,source_hash,record_count,unresolved_count FROM catalog_builds ORDER BY created_at DESC LIMIT 1").fetchone()
            packs = [
                dict(row)
                for row in conn.execute(
                    """SELECT p.pack_id,p.version,p.pack_hash,p.lifecycle_state,p.authority,
                              COALESCE(r.trust_state,'') AS trust_state
                       FROM content_packs p
                       LEFT JOIN content_pack_install_receipts r
                         ON r.pack_id=p.pack_id AND r.version=p.version AND r.canonical_content_hash=p.pack_hash
                       ORDER BY p.pack_id,p.version"""
                )
            ]
        identity = sha256_json({"build": dict(build) if build else None, "packs": packs})
        return str(self.db.settings.db_path.resolve()), identity

    def __init__(self, db: Database):
        self.db = db
        self.coverage = Stage1CatalogCoverageService(db)
        self.catalog = CatalogService(db)
        self.canonical_catalog = CanonicalCatalogAuthorityService(db.settings.root_dir)
        self.packs = ContentPackManager(db)
        self.projects = ProjectStore(db)


    def _sphere_owner_coverage(self) -> dict[str, dict[str, Any]]:
        return {
            row["display_name"]: {
                "disposition": "covered",
                "source_candidate_count": row["talent_count"],
                "genuine_selectable_talent_count": row["talent_count"],
            }
            for row in self.canonical_catalog.list_spheres()["records"]
        }

    @staticmethod
    def _zero_talent_unavailable_reason(disposition: str) -> str:
        if disposition == "source_confirms_no_selectable_talent_heading":
            return "Not currently creator-ready — no canonical selectable talent authority"
        return "Not currently creator-ready — source talent candidates remain unprojected by accepted canonical authority"

    def _canonicalize_sphere_talent_options(self, categories: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Replace owner-facing Sphere/Talent categories with compiled CAT3 authority."""
        authority_status = self.canonical_catalog.status()
        if not authority_status.get("ready"):
            raise FoundryError(
                "CHARACTER_CREATOR_CANONICAL_AUTHORITY_BLOCKED",
                "Character creation requires the validated CAT3 canonical Sphere/Talent authority.",
                details=authority_status,
                status_code=503,
            )
        sphere_rows = self.canonical_catalog.list_spheres()["records"]
        talent_rows = self.canonical_catalog.list_talents()["records"]
        owner_coverage = self._sphere_owner_coverage()
        by_slot = {row["slot_id"]: row for row in categories}
        sphere_category = by_slot["sphere_priorities"]
        talent_category = by_slot["advancement_skeleton"]
        sphere_choices: list[dict[str, Any]] = []
        for row in sphere_rows:
            coverage = deepcopy(owner_coverage.get(row["display_name"]) or {})
            talent_count = int(row.get("talent_count") or 0)
            coverage_disposition = str(coverage.get("disposition") or ("covered" if talent_count else "source_candidates_unprojected"))
            creator_ready = talent_count > 0
            unavailable_reason = None if creator_ready else self._zero_talent_unavailable_reason(coverage_disposition)
            sphere_choices.append({
                "choice_id": row["canonical_sphere_id"],
                "name": row["display_name"],
                "canonical_name": row["display_name"],
                "description": row["short_description"],
                "short_description": row["short_description"],
                "full_description": row.get("full_description") or row["short_description"],
                "content_type": "sphere",
                "minimum_cl": None,
                "pack_id": CORE_PACK_ID,
                "pack_version": CORE_PACK_VERSION,
                "related_choice_ids": [talent["canonical_talent_id"] for talent in talent_rows if talent["owning_canonical_sphere_id"] == row["canonical_sphere_id"]],
                "aliases": deepcopy(row["aliases"]),
                "source_reference": deepcopy(row["source_reference"]),
                "source_pack": row["source_pack"],
                "creator_disposition": row["creator_disposition"],
                "prerequisite_summary": row["prerequisite_summary"],
                "selectable_talent_count": talent_count,
                "source_candidate_count": int(coverage.get("source_candidate_count") or talent_count),
                "coverage_disposition": coverage_disposition,
                "creator_ready": creator_ready,
                "planning_priority_available": creator_ready,
                "automatic_planning_available": creator_ready,
                "creator_acquisition_available": creator_ready,
                "free_grant_available": creator_ready,
                "unavailable_reason": unavailable_reason,
                "browse_rules_visible": True,
                "automatic_base_abilities": deepcopy(row["automatic_base_abilities"]),
                "resolved_automatic_base_abilities": deepcopy(row.get("resolved_automatic_base_abilities") or row["automatic_base_abilities"]),
                "automatic_base_ability_package": deepcopy(row.get("automatic_base_ability_package") or {}),
                "canonical_authority": True,
                "virtual_canonical_authority": True,
                "authority_coverage": {"disposition": "canonical_owner_projection"},
                "authority_summary": {"status": "CAT3_COMPILED", "stable_id": row["canonical_sphere_id"]},
            })
        talent_choices: list[dict[str, Any]] = []
        for row in talent_rows:
            talent_choices.append({
                "choice_id": row["canonical_talent_id"],
                "name": row["display_name"],
                "canonical_name": row["display_name"],
                "description": row["short_description"],
                "short_description": row["short_description"],
                "full_description": row["full_description"],
                "content_type": "talent",
                "minimum_cl": row["minimum_cl"],
                "pack_id": CORE_PACK_ID,
                "pack_version": CORE_PACK_VERSION,
                "related_choice_ids": [row["owning_canonical_sphere_id"]],
                "sphere_choice_ids": [row["owning_canonical_sphere_id"]],
                "mapping_status": "mapped",
                "owning_canonical_sphere_id": row["owning_canonical_sphere_id"],
                "owning_canonical_sphere_name": row["owning_canonical_sphere_name"],
                "source_reference": deepcopy(row["source_reference"]),
                "acquisition_route": deepcopy(row["acquisition_route"]),
                "selection_disposition": row["selection_disposition"],
                "restriction_status": row["restriction_status"],
                "typed_constraints": deepcopy(row["typed_constraints"]),
                "prerequisite_evaluation_status": row["prerequisite_evaluation_status"],
                "creator_selectability_can_be_evaluated_safely": row["creator_selectability_can_be_evaluated_safely"],
                "unresolved_reason": row["unresolved_reason"],
                "access_category": row["access_category"],
                "acquisition_provenance_required": row["acquisition_provenance_required"],
                "planning_priority_available": True,
                "creator_ready": bool(row["creator_selectability_can_be_evaluated_safely"]),
                "restricted": row["access_category"] != "Open",
                "canonical_authority": True,
                "virtual_canonical_authority": True,
                "authority_coverage": {"disposition": "canonical_owner_projection"},
                "authority_summary": {"status": "CAT3_COMPILED", "stable_id": row["canonical_talent_id"]},
            })
        sphere_category.update({"status": "offered", "choices": sphere_choices, "canonical_count": len(sphere_choices), "projection": "CAT3_CANONICAL"})
        talent_category.update({"status": "offered", "choices": talent_choices, "canonical_count": len(talent_choices), "projection": "CAT3_CANONICAL"})
        index = {
            "schema": "TianxiaFoundry.CanonicalSphereTalentIndex.v1",
            "by_sphere": {row["canonical_sphere_id"]: sorted([talent["canonical_talent_id"] for talent in talent_rows if talent["owning_canonical_sphere_id"] == row["canonical_sphere_id"]]) for row in sphere_rows},
            "by_talent": {row["canonical_talent_id"]: [row["owning_canonical_sphere_id"]] for row in talent_rows},
            "unassigned_talent_ids": [],
            "ambiguous_talent_ids": [],
            "per_sphere_coverage": {
                choice["choice_id"]: {
                    "talent_count": choice["selectable_talent_count"],
                    "selectable_talent_count": choice["selectable_talent_count"],
                    "source_candidate_count": choice["source_candidate_count"],
                    "coverage_disposition": choice["coverage_disposition"],
                    "creator_ready": choice["creator_ready"],
                    "planning_priority_available": choice["planning_priority_available"],
                    "creator_acquisition_available": choice["creator_acquisition_available"],
                    "free_grant_available": choice["free_grant_available"],
                    "unavailable_reason": choice["unavailable_reason"],
                    "honest_label": (f"{choice['selectable_talent_count']} canonical Talent{'s' if choice['selectable_talent_count'] != 1 else ''}" if choice["creator_ready"] else choice["unavailable_reason"]),
                }
                for choice in sphere_choices
            },
            "audit": {
                "sphere_count": len(sphere_rows), "talent_count": len(talent_rows), "mapped_talent_count": len(talent_rows),
                "unassigned_talent_count": 0, "ambiguous_talent_count": 0, "multi_sphere_talent_count": 0,
                "owner_hidden_source_authority_gap_count": 0, "owner_hidden_source_authority_gap_ids": [],
                "catalog_sphere_candidate_count": len(sphere_rows),
            },
        }
        return categories, index

    def _choice_records(self, selectable_ids: set[str]) -> dict[str, dict[str, Any]]:
        if not selectable_ids:
            return {}
        placeholders = ",".join("?" for _ in selectable_ids)
        with self.db.connection() as conn:
            rows = conn.execute(
                f"""SELECT record_id,
                           json_extract(data_json, '$.display_name') AS display_name,
                           json_extract(data_json, '$.display_projection.short_description') AS short_description,
                           json_extract(data_json, '$.summary') AS summary,
                           json_extract(data_json, '$.content_type') AS content_type,
                           json_extract(data_json, '$.legality.minimum_cl') AS minimum_cl,
                           json_extract(data_json, '$.content_binding.pack_id') AS pack_id,
                           json_extract(data_json, '$.content_binding.pack_version') AS pack_version,
                           json_extract(data_json, '$.source.path') AS source_path,
                           json_extract(data_json, '$.source.source_hash') AS source_hash,
                           json_extract(data_json, '$.source.anchor') AS source_anchor,
                           json_extract(data_json, '$.publication_state') AS publication_state,
                           json_extract(data_json, '$.dependencies') AS dependencies_json,
                           json_extract(data_json, '$.compatibility.factory.raw_projection.raw_record.authority_coverage') AS authority_coverage_json,
                           json_extract(data_json, '$.compatibility.factory.raw_projection.raw_record.authority_summary') AS authority_summary_json,
                           json_extract(data_json, '$.raw_record') AS raw_record_json,
                           raw_projection_json
                    FROM catalog_records
                    WHERE selected_authority=1 AND record_id IN ({placeholders})
                    ORDER BY record_id,
                             CASE WHEN pack_id=? AND pack_version=? THEN 0 ELSE 1 END,
                             row_id""",
                [*sorted(selectable_ids), CORE_PACK_ID, CORE_PACK_VERSION],
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        insight_occurrences: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            result.setdefault(row["record_id"], {
                "record_id": row["record_id"],
                "display_name": row["display_name"],
                "description": str(row["short_description"] or row["summary"] or "")[:600],
                "content_type": row["content_type"],
                "minimum_cl": row["minimum_cl"],
                "pack_id": row["pack_id"],
                "pack_version": row["pack_version"],
                "related_choice_ids": json.loads(row["dependencies_json"] or "[]"),
                "authority_coverage": json.loads(row["authority_coverage_json"] or "{}"),
                "authority_summary": json.loads(row["authority_summary_json"] or "{}"),
            })
            raw_record = json.loads(row["raw_record_json"] or "{}")
            if not raw_record:
                raw_projection = json.loads(row["raw_projection_json"] or "{}")
                raw_record = raw_projection.get("raw_record") if isinstance(raw_projection, dict) else {}
            if row["content_type"] in {"cultivation_insight", "origin_insight", "insight"}:
                base_reference = {
                    "source_file": row["source_path"],
                    "source_file_sha256": row["source_hash"],
                    "source_anchor": row["source_anchor"],
                    "source_status": row["publication_state"],
                }
                nested_occurrences = raw_record.get("source_occurrences") if isinstance(raw_record, dict) else None
                if isinstance(nested_occurrences, list) and nested_occurrences:
                    for nested in nested_occurrences:
                        # CAT3's generated authority stores occurrence payloads
                        # as flattened R2 records.  Accept the older nested
                        # ``{raw_record, source_reference}`` envelope too so
                        # the runtime remains compatible with prior sealed
                        # projections without weakening source identity.
                        nested_raw = (
                            deepcopy(nested.get("raw_record") or nested)
                            if isinstance(nested, dict) else {}
                        )
                        if not nested_raw:
                            continue
                        # The R2 occurrence remains the source text authority;
                        # compiled CAT3 metadata supplies the explicit type and
                        # hierarchy used by the owner surface.
                        for key in (
                            "insight_authority_type", "insight_group", "hierarchy_path",
                            "owning_canonical_sphere_ids", "owning_canonical_sphere_id",
                            "source_prerequisites_text", "compiled_prerequisite_ledger",
                            "repeatable_maximum", "canonical_insight_id", "compiler_version",
                        ):
                            if key in raw_record:
                                nested_raw[key] = deepcopy(raw_record[key])
                        nested_reference = deepcopy(nested.get("source_reference") or {}) if isinstance(nested, dict) else {}
                        if isinstance(nested, dict):
                            for target_key, source_keys in {
                                "source_file": ("source_file", "path"),
                                "source_file_sha256": ("source_file_sha256", "source_hash"),
                                "source_record_id": ("source_record_id", "record_id", "canonical_id"),
                                "source_record_sha256": ("source_record_sha256",),
                                "source_status": ("source_status",),
                                "source_anchor": ("source_anchor", "anchor"),
                            }.items():
                                if target_key in nested_reference:
                                    continue
                                for source_key in source_keys:
                                    if str(nested.get(source_key) or "").strip():
                                        nested_reference[target_key] = nested[source_key]
                                        break
                        nested_reference = {**base_reference, **nested_reference}
                        insight_occurrences.setdefault(row["record_id"], []).append({
                            "raw_record": nested_raw,
                            "source_reference": nested_reference,
                        })
                else:
                    insight_occurrences.setdefault(row["record_id"], []).append({
                        "raw_record": raw_record,
                        "source_reference": base_reference,
                    })
        group_map = {
            "General": ("general_insights", "General Insights"),
            "General Cultivation": ("general_cultivation_insights", "General Cultivation Insights"),
            "Sphere": ("sphere_insights", "Sphere Insights"),
            "Path": ("path_insights", "Path Insights"),
            "Technique-Forging": ("technique_forging_insights", "Technique-Forging Insights"),
            "Metatechnique": ("metatechnique_insights", "Metatechnique Insights"),
            "Companion": ("companion_insights", "Companion Insights"),
            "Narrative / Secret": ("narrative_secret_insights", "Narrative / Secret Insights"),
            "Method": ("method_insights", "Method Insights"),
            "Foundation": ("foundation_insights", "Foundation Insights"),
            "Background-Origin": ("background_origin_insights", "Background / Origin Insights"),
            "Item-Equipment": ("item_equipment_insights", "Item / Equipment Insights"),
            "Special": ("special_insights", "Special Insights"),
            "Unresolved": ("unresolved_insights", "Unresolved Insights"),
        }
        for record_id, occurrences in insight_occurrences.items():
            resolved = resolve_insight_occurrences(occurrences, record_id=record_id)
            authority = classify_insight_authority(
                resolved["raw_record"], record_id=record_id,
                source_reference=resolved["source_reference"],
            )
            authority["source_occurrences"] = resolved["source_occurrences"]
            authority["source_occurrence_count"] = resolved["source_occurrence_count"]
            authority["collision_disposition"] = resolved["collision_disposition"]
            choice = result[record_id]
            if not resolved["resolved"]:
                authority.update({
                    "authority_type": "Unresolved",
                    "classification_code": "UNRESOLVED_DUPLICATE_INSIGHT_ID",
                    "reason": "Multiple current source records use this Insight identifier; it remains unavailable until the source resolves the collision.",
                })
                choice["planning_priority_available"] = False
                choice["unavailable_reason"] = "This Insight has conflicting source records and is not currently available."
            group, label = group_map[authority["authority_type"]]
            choice["insight_group"] = group
            choice["insight_group_label"] = label
            choice["insight_hierarchy"] = deepcopy(authority.get("hierarchy_path") or [])
            choice["insight_facets"] = deepcopy(authority.get("owning_canonical_sphere_ids") or [])
            choice["insight_authority"] = authority
        return result

    def _legacy_talent_findings(self) -> dict[str, dict[str, Any]]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT record_id,display_name,content_type,
                          json_extract(data_json, '$.compatibility.factory.raw_projection.raw_record.r6_6_5_source_role') AS source_role,
                          json_extract(data_json, '$.compatibility.factory.raw_projection.raw_record.r6_6_5_source_role_reason') AS source_role_reason
                   FROM catalog_records
                   WHERE pack_id=? AND pack_version=? AND selected_authority=0
                     AND json_extract(data_json, '$.compatibility.factory.raw_projection.raw_record.r6_6_5_source_role') IS NOT NULL
                   ORDER BY record_id""",
                (CORE_PACK_ID, CORE_PACK_VERSION),
            ).fetchall()
        return {
            row["record_id"]: {
                "choice_id": row["record_id"],
                "name": row["display_name"],
                "content_type": row["content_type"],
                "source_role": row["source_role"],
                "finding": row["source_role_reason"] or "This prior flat selection is not a source-authorized generic Talent.",
                "resolution": "Remove or replace manually; no automatic substitution was performed.",
            }
            for row in rows
        }

    @staticmethod
    def _plain_blocked_message(category: dict[str, Any]) -> str:
        reasons = category.get("blocked_reasons") or []
        if reasons:
            return str(reasons[0].get("message") or "No selectable authority is installed for this category.")
        return "No selectable authority is installed for this category."

    def _decorate_non_sphere_options(self, categories: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        authority = NonSphereAuthorityService(self.db)
        by_slot = {row["slot_id"]: row for row in categories}

        path_rows = {row["path_id"]: row for row in authority.path_catalog()["records"]}
        path_category = by_slot.get("path_choice")
        if path_category is not None:
            existing = {row["choice_id"]: row for row in path_category.get("choices", [])}
            choices = []
            for path_id, record in path_rows.items():
                base = deepcopy(existing.get(path_id) or {})
                base.update({
                    "choice_id": path_id, "name": record["display_name"],
                    "description": record["path_profile"]["primary_roles"], "content_type": "path",
                    "pack_id": CORE_PACK_ID, "pack_version": CORE_PACK_VERSION,
                    "minimum_cl": 1, "ns1r_authority": record, "canonical_non_sphere_authority": True,
                })
                choices.append(base)
            path_category["choices"] = choices
            path_category["status"] = "offered"
            path_category["kind"] = "multi"
            path_category["max"] = 3
            path_category["label"] = "Advancing Path Requirements"
            path_category["selection_semantics"] = "owner_required_advancing_paths"
            path_category["authority_contract"] = {
                "schema": "TianxiaFoundry.PathTrackAuthorityContract.v1",
                "canonical_path_ids": list(CANONICAL_PATH_IDS),
                "min_selections": 0,
                "max_selections": 3,
                "level_zero_tracks": "all_three_present_dormant",
                "selected_path_meaning": "Paths the Method must support and advance; not ownership of tracks.",
            }

        subpath_category = by_slot.get("subpath_choice")
        if subpath_category is not None:
            subpath_category["choices"] = [{
                "choice_id": row["canonical_id"], "name": row["display_name"],
                "description": row.get("identity", {}).get("primary_role") or row.get("identity", {}).get("identity") or row["display_name"],
                "content_type": row["option_type"], "option_type": row["option_type"],
                "owning_path_name": row["owning_path_name"],
                "minimum_cl": int(row.get("minimum_cl") or 3),
                "pack_id": CORE_PACK_ID, "pack_version": CORE_PACK_VERSION,
                "related_choice_ids": [row["owning_path_id"]], "owning_path_choice_ids": [row["owning_path_id"]],
                "access": deepcopy(row["access"]), "ns1r_authority": deepcopy(row), "canonical_non_sphere_authority": True,
            } for row in authority.subpath_catalog()["records"]]
            subpath_category["status"] = "offered"
            subpath_category["kind"] = "multi"
            subpath_category["max"] = 3
            subpath_category["label"] = "Subpaths or Traditions"

        method_category = by_slot.get("method_choice")
        if method_category is not None:
            method_category["choices"] = [{
                "choice_id": row["method_id"], "name": row["name"],
                "description": ((authority.methods[row["method_id"]].get("owner_readable") or {}).get("full_description") if isinstance(authority.methods[row["method_id"]].get("owner_readable"), dict) else authority.methods[row["method_id"]].get("owner_readable")) or authority.methods[row["method_id"]].get("source_text") or "",
                "content_type": "method", "minimum_cl": None,
                "pack_id": CORE_PACK_ID, "pack_version": CORE_PACK_VERSION,
                "related_choice_ids": [],
                "initial_creation_selectable": bool(row.get("initial_creation_selectable")),
                "initial_creation_unavailable_reason": row.get("initial_creation_unavailable_reason"),
                "method_planning": deepcopy(row["method_planning"]),
                "ns1r_disposition": deepcopy(row["disposition"]), "ns1r_authority": deepcopy(row),
                "canonical_non_sphere_authority": True,
            } for row in authority.method_catalog(initial_creation=True)["records"]]
            for choice in method_category["choices"]:
                choice["related_choice_ids"] = [
                    {"BODY_REFINING": "tianxia.path.body_refining", "QI_CULTIVATION": "tianxia.path.qi_cultivation", "SPIRIT_AWAKENING": "tianxia.path.spirit_awakening"}[grant["path_id"]]
                    for grant in choice["ns1r_authority"]["explicit_ap_grants"] if grant["grants_attainment_points"]
                ]
            method_category["status"] = "offered"
            method_category["selection_semantics"] = "method_acquisition_and_primary_method_authority"

        foundation_category = by_slot.get("foundation_choice")
        if foundation_category is not None:
            foundation_category["choices"] = [{
                "choice_id": row["foundation_id"], "name": row["display_name"], "description": authority.foundation_owner_description(row),
                "owner_description": authority.foundation_owner_description(row), "advanced_description": row["summary"],
                "content_type": "foundation", "minimum_cl": None,
                "pack_id": CORE_PACK_ID, "pack_version": CORE_PACK_VERSION,
                "related_choice_ids": [
                    {"BODY_REFINING": "tianxia.path.body_refining", "QI_CULTIVATION": "tianxia.path.qi_cultivation", "SPIRIT_AWAKENING": "tianxia.path.spirit_awakening"}[pid]
                    for pid in row["compatible_path_ids"]
                ],
                "repair_practice_names": deepcopy(row["repair_practice_names"]),
                "canonical_non_sphere_authority": True, "selectable": True,
            } for row in authority.foundation_catalog()["orthodox"]]
            foundation_category["status"] = "offered"
            foundation_category["theoretical_chakra_count_excluded"] = 32

        background_category = by_slot.get("background_choice")
        background_sphere_category = by_slot.get("background_sphere_choice")
        background_talent_category = by_slot.get("background_talent_choice")
        origin_insight_category = by_slot.get("origin_insight_choice")
        background_authority = authority.backgrounds
        route_authority_by_id: dict[str, dict[str, Any]] = {}
        insight_authority_by_id: dict[str, dict[str, Any]] = {}
        insight_authority_by_name: dict[str, list[dict[str, Any]]] = {}
        for background_id, background in background_authority.items():
            exact = authority.background_route_authority.get(background_id, {})
            for route in exact.get("route_options", []):
                route_authority_by_id[route["background_route_record_id"]] = {
                    **deepcopy(route), "background_id": background_id,
                }
            for insight in exact.get("origin_insight_options", []):
                enriched_insight = {
                    **deepcopy(insight), "background_id": background_id,
                    "background_source": deepcopy(background.get("source") or {}),
                }
                insight_authority_by_id[insight["origin_insight_choice_id"]] = enriched_insight
                insight_authority_by_name.setdefault(
                    _normalized_visible_name(insight["display_name"]), []
                ).append(enriched_insight)

        def decorate_background_origin_choice(
            choice: dict[str, Any], exact_insights: list[dict[str, Any]],
        ) -> None:
            """Attach the dedicated Background-Origin authority to its canonical choice.

            The background pack stores one canonical Origin record per visible
            name, while the route authority stores background-specific option
            IDs.  The owner surface must retain the canonical choice identity
            and expose every exact background binding without conflating that
            route identity with an ordinary Insight preference.
            """
            if not exact_insights:
                return
            background_ids = sorted({row["background_id"] for row in exact_insights})
            choice["insight_group"] = "background_origin_insights"
            choice["insight_group_label"] = "Background / Origin Insights"
            choice["insight_authority"] = {
                "schema": "TianxiaFoundry.InsightSourceAuthority.v1",
                "record_id": choice["choice_id"],
                "authority_type": "Background-Origin",
                "binding_records": [{
                    "authority_type": "Background-Origin",
                    "field": "background",
                    "binding_id": background_id,
                    "binding_role": "controlling",
                } for background_id in background_ids],
                "prerequisites": "",
                "preference_only": True,
                "classification_code": "EXPLICIT_BACKGROUND_ORIGIN_INSIGHT_AUTHORITY",
                "reason": "The accepted Background authority explicitly lists this suggested Origin Insight.",
                "source_reference": {
                    "source_file": "non_sphere_authority/authority/Background_Core_Authority_v1.json",
                    "source_status": "accepted_authority",
                    "source_record_id": choice["choice_id"],
                    "background_ids": background_ids,
                    "source_occurrences": [{
                        "background_id": row["background_id"],
                        **deepcopy(row["background_source"]),
                    } for row in exact_insights],
                },
            }
            choice["ns1r_exact_origin_insight_authority"] = deepcopy(exact_insights)
            choice["canonical_non_sphere_authority"] = True

        # Preserve the accepted CAT2 option inventories exactly. NS1R-R1 only
        # decorates those records with the shared authority needed for exact
        # route validation; it must not rebuild, duplicate, or broaden them.
        if background_category is not None:
            for choice in background_category.get("choices", []):
                background_id = choice["choice_id"]
                if background_id in background_authority:
                    choice["ns1r_background_core_authority"] = deepcopy(background_authority[background_id])
                    choice["ns1r_exact_route_authority"] = deepcopy(authority.background_route_authority[background_id])
                    choice["canonical_non_sphere_authority"] = True
        if background_talent_category is not None:
            for choice in background_talent_category.get("choices", []):
                route = route_authority_by_id.get(choice["choice_id"])
                if route is not None:
                    choice["ns1r_exact_route_authority"] = deepcopy(route)
                    choice["background_route_record_id"] = route["background_route_record_id"]
                    choice["record_commitment_sha256"] = route["record_commitment_sha256"]
                    choice["canonical_non_sphere_authority"] = True
        if background_sphere_category is not None:
            for choice in background_sphere_category.get("choices", []):
                exact_routes = []
                for background_id, exact in authority.background_route_authority.items():
                    exact_routes.extend(
                        {**deepcopy(route), "background_id": background_id}
                        for route in exact.get("route_options", [])
                        if route.get("background_sphere_choice_id") == choice["choice_id"]
                    )
                choice["ns1r_exact_route_authority"] = {"route_options": exact_routes}
                choice["canonical_non_sphere_authority"] = True
        if origin_insight_category is not None:
            for choice in origin_insight_category.get("choices", []):
                exact_insights = insight_authority_by_name.get(_normalized_visible_name(choice["name"]), [])
                exact_by_route_id = insight_authority_by_id.get(choice["choice_id"])
                if exact_by_route_id is not None and exact_by_route_id not in exact_insights:
                    exact_insights = [exact_by_route_id, *exact_insights]
                decorate_background_origin_choice(choice, exact_insights)

        insight_category = by_slot.get("insight_priorities")
        if insight_category is not None:
            for choice in insight_category.get("choices", []):
                exact_insights = insight_authority_by_name.get(_normalized_visible_name(choice["name"]), [])
                if choice.get("content_type") == "origin_insight" and exact_insights:
                    decorate_background_origin_choice(choice, exact_insights)
            insight_category["grouped_projection"] = "typed_insight_metadata"
            insight_category["groups"] = [
                {"id": "general_insights", "label": "General Insights"},
                {"id": "general_cultivation_insights", "label": "General Cultivation Insights"},
                {"id": "sphere_insights", "label": "Sphere Insights"},
                {"id": "path_insights", "label": "Path Insights"},
                {"id": "technique_forging_insights", "label": "Technique-Forging Insights"},
                {"id": "metatechnique_insights", "label": "Metatechnique Insights"},
                {"id": "companion_insights", "label": "Companion Insights"},
                {"id": "narrative_secret_insights", "label": "Narrative / Secret Insights"},
                {"id": "method_insights", "label": "Method Insights"},
                {"id": "foundation_insights", "label": "Foundation Insights"},
                {"id": "background_origin_insights", "label": "Background / Origin Insights"},
                {"id": "item_equipment_insights", "label": "Item / Equipment Insights"},
                {"id": "special_insights", "label": "Special Insights"},
                {"id": "unresolved_insights", "label": "Unresolved Insights"},
            ]

        return categories, authority.authority_status()

    def options(self) -> dict[str, Any]:
        cache_key = self._options_identity()
        cached = self._OPTIONS_CACHE.get(cache_key)
        if cached is not None:
            return deepcopy(cached)
        coverage = self.coverage.build()
        by_slot = {category["slot_id"]: category for category in coverage["categories"]}
        selectable_ids = {
            record_id
            for config in CATEGORY_CONFIG
            for record_id in (
                by_slot.get(config["slot_id"], {}).get(
                    "intent_selectable_record_ids" if config["slot_id"] in INTENT_OPTION_SLOTS else "selectable_record_ids"
                ) or []
            )
        }
        records = self._choice_records(selectable_ids)
        categories: list[dict[str, Any]] = []
        hidden_authority_gap_spheres: list[dict[str, Any]] = []
        for config in CATEGORY_CONFIG:
            category = by_slot.get(config["slot_id"])
            if not category:
                categories.append({
                    **config,
                    "status": "blocked_missing_authority",
                    "blocked_message": "This category is not available in the installed rules yet.",
                    "choices": [],
                })
                continue
            choices: list[dict[str, Any]] = []
            choice_key = "intent_selectable_record_ids" if config["slot_id"] in INTENT_OPTION_SLOTS else "selectable_record_ids"
            for record_id in category.get(choice_key) or []:
                record = records.get(record_id)
                if not record:
                    continue
                choices.append({
                    "choice_id": record_id,
                    "name": record.get("display_name") or record_id,
                    "description": record.get("description") or "",
                    "content_type": record.get("content_type"),
                    "minimum_cl": record.get("minimum_cl"),
                    "pack_id": record.get("pack_id"),
                    "pack_version": record.get("pack_version"),
                    "related_choice_ids": record.get("related_choice_ids") or [],
                    "authority_coverage": record.get("authority_coverage") or {},
                    "authority_summary": record.get("authority_summary") or {},
                    "insight_group": record.get("insight_group"),
                    "insight_group_label": record.get("insight_group_label"),
                    "insight_authority": deepcopy(record.get("insight_authority")),
                    "planning_priority_available": record.get("planning_priority_available", True),
                    "unavailable_reason": record.get("unavailable_reason"),
                })
            if config["slot_id"] == "sphere_priorities":
                # Source-authority-gap rows remain in the catalog and evidence, but
                # they are unresolved labels rather than proven owner-selectable
                # Spheres. The disposition is authoritative; names are never used
                # as a blacklist, alias, or fuzzy merge signal.
                hidden_authority_gap_spheres.extend(
                    deepcopy(choice) for choice in choices
                    if _authority_disposition(choice) == "source_authority_gap"
                )
                choices = [choice for choice in choices if _authority_disposition(choice) != "source_authority_gap"]
            choices = _dedupe_choice_rows(choices)
            choices.sort(key=lambda item: (_normalized_visible_name(item["name"]), item["choice_id"]))
            categories.append({
                **config,
                "status": "offered" if choices else "blocked_missing_authority",
                "blocked_message": None if choices else self._plain_blocked_message(category),
                "selection_semantics": "blueprint_intent_only" if config["slot_id"] in INTENT_OPTION_SLOTS else "strict_authority",
                "choices": choices,
            })
        categories, canonical_sphere_talent_index = self._canonicalize_sphere_talent_options(categories)
        categories, non_sphere_authority_status = self._decorate_non_sphere_options(categories)
        insight_category = next((row for row in categories if row["slot_id"] == "insight_priorities"), None)
        if insight_category is not None:
            for choice in insight_category.get("choices", []):
                if not choice.get("insight_authority"):
                    choice["insight_group"] = "unresolved_insights"
                    choice["insight_group_label"] = "Unresolved Insights"
                    choice["insight_authority"] = {
                        "schema": "TianxiaFoundry.InsightSourceAuthority.v1",
                        "record_id": choice["choice_id"],
                        "authority_type": "Unresolved",
                        "binding_records": [],
                        "prerequisites": "",
                        "preference_only": True,
                        "classification_code": "UNRESOLVED_INSIGHT_CLASSIFICATION",
                        "reason": "No explicit typed Insight source-authority record was available.",
                        "source_reference": {},
                    }
        path_category = next((row for row in categories if row["slot_id"] == "path_choice"), {"choices": []})
        subpath_category = next((row for row in categories if row["slot_id"] == "subpath_choice"), {"choices": []})
        path_ids = {choice["choice_id"] for choice in path_category.get("choices", [])}
        path_subpath_index: dict[str, list[str]] = {path_id: [] for path_id in sorted(path_ids)}
        for subpath in subpath_category.get("choices", []):
            owning_path_ids = sorted(path_ids.intersection(subpath.get("related_choice_ids") or []))
            subpath["owning_path_choice_ids"] = owning_path_ids
            for path_id in owning_path_ids:
                path_subpath_index[path_id].append(subpath["choice_id"])
        for path_id in path_subpath_index:
            path_subpath_index[path_id].sort()

        sphere_talent_index = canonical_sphere_talent_index
        _qualify_duplicate_visible_names(categories, sphere_talent_index)
        result = {
            "schema_version": "TianxiaFoundry.CharacterSheetOptions.v3",
            "point_buy": {
                "budget": POINT_BUY_BUDGET,
                "abilities": list(ABILITY_ORDER),
                "minimum": min(POINT_BUY_COSTS),
                "maximum": max(POINT_BUY_COSTS),
                "costs": {str(score): cost for score, cost in POINT_BUY_COSTS.items()},
                "auto_allowed": True,
            },
            "categories": categories,
            "sphere_talent_index": sphere_talent_index,
            "path_subpath_index": path_subpath_index,
            "category_rules": {
                "subpath_choice": {
                    "requires_slot": "path_choice",
                    "empty_prompt": "Choose a Primary Path first.",
                    "relationship_authority": "exact stable IDs from authoritative dependencies/owning_path_id",
                    "general_unlock_note": "Subpath availability follows the Path rules; no individual CL is shown unless the record has an authoritative minimum_cl.",
                }
            },
            "legacy_talent_findings": self._legacy_talent_findings(),
            "canonical_catalog_authority": self.canonical_catalog.status(),
            "non_sphere_authority": non_sphere_authority_status,
            "background_only_routes": self.canonical_catalog.diagnostics()["background_only_routes"],
            "quarantined_authority_records": self.canonical_catalog.diagnostics()["quarantined"],
            "coverage_report_hash": coverage["report_hash"],
            "owner_surface_counts": {
                "canonical_spheres": len(next(row for row in categories if row["slot_id"] == "sphere_priorities")["choices"]),
                "canonical_talents": len(next(row for row in categories if row["slot_id"] == "advancement_skeleton")["choices"]),
                "automatic_base_components": sum(len(row.get("automatic_base_abilities") or []) for row in next(row for row in categories if row["slot_id"] == "sphere_priorities")["choices"]),
                "resolved_automatic_base_components": sum(len(row.get("resolved_automatic_base_abilities") or []) for row in next(row for row in categories if row["slot_id"] == "sphere_priorities")["choices"]),
                "zero_talent_spheres": sum(1 for row in next(row for row in categories if row["slot_id"] == "sphere_priorities")["choices"] if not row.get("creator_ready")),
                "quarantined_records": int(self.canonical_catalog.diagnostics()["quarantined"]["count"]),
            },
            "honest_limit": "Manual selections are hard locks. Sphere and talent priorities are non-authoritative planning preferences; canonical acquisitions are created only by validated Stage 2 authority.",
        }
        # Remove stale entries for this database, then retain only the exact
        # catalog/pack identity used to build these options.
        for key in list(self._OPTIONS_CACHE):
            if key[0] == cache_key[0] and key != cache_key:
                self._OPTIONS_CACHE.pop(key, None)
        self._OPTIONS_CACHE[cache_key] = deepcopy(result)
        return result

    @staticmethod
    def validate_point_buy(scores: dict[str, int | None] | None) -> dict[str, Any]:
        supplied = scores or {}
        extra = sorted(set(supplied) - set(ABILITY_ORDER))
        if extra:
            raise FoundryError(
                "CHARACTER_SHEET_ABILITY_UNKNOWN",
                "The character sheet contains an unknown ability.",
                details={"unknown_abilities": extra},
            )
        fixed: dict[str, int] = {}
        automatic: list[str] = []
        for ability in ABILITY_ORDER:
            value = supplied.get(ability)
            if value is None:
                automatic.append(ability)
                continue
            if isinstance(value, bool) or value not in POINT_BUY_COSTS:
                raise FoundryError(
                    "CHARACTER_SHEET_POINT_BUY_SCORE_INVALID",
                    "Ability scores must be Auto or a legal 27-point-buy value from 8 through 15.",
                    details={"ability": ability, "value": value},
                )
            fixed[ability] = int(value)
        spent = sum(POINT_BUY_COSTS[value] for value in fixed.values())
        if spent > POINT_BUY_BUDGET:
            raise FoundryError(
                "CHARACTER_SHEET_POINT_BUY_OVER_BUDGET",
                "The chosen ability scores cost more than the 27-point-buy budget.",
                details={"points_spent": spent, "budget": POINT_BUY_BUDGET},
            )
        if not automatic and spent != POINT_BUY_BUDGET:
            raise FoundryError(
                "CHARACTER_SHEET_POINT_BUY_INCOMPLETE",
                "When every ability is fixed, the scores must use exactly 27 points. Leave at least one ability on Auto to let the Factory finish the allocation.",
                details={"points_spent": spent, "points_remaining": POINT_BUY_BUDGET - spent},
            )
        return {
            "budget": POINT_BUY_BUDGET,
            "fixed_scores": fixed,
            "auto_abilities": automatic,
            "points_spent": spent,
            "points_remaining": POINT_BUY_BUDGET - spent,
            "completion": "owner_complete" if not automatic else "factory_to_complete",
        }

    def _validated_selections(
        self, submitted: dict[str, list[str]] | None, *, target_cl: int = 20,
        access_source_records: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
        submitted = submitted or {}
        options = self.options()
        by_slot = {category["slot_id"]: category for category in options["categories"]}
        unknown_slots = sorted(set(submitted) - set(by_slot))
        if unknown_slots:
            raise FoundryError(
                "CHARACTER_SHEET_CATEGORY_UNKNOWN",
                "The character sheet contains an unknown selection category.",
                details={"unknown_categories": unknown_slots},
            )
        normalized: dict[str, list[str]] = {}
        selected_choices: dict[str, dict[str, Any]] = {}
        for slot_id, values in submitted.items():
            if not isinstance(values, list):
                raise FoundryError("CHARACTER_SHEET_SELECTION_INVALID", "Character-sheet selections must be lists.", details={"category": slot_id})
            unique = []
            for value in values:
                if not isinstance(value, str) or not value:
                    raise FoundryError("CHARACTER_SHEET_SELECTION_INVALID", "A character-sheet choice ID is invalid.", details={"category": slot_id, "choice_id": value})
                if value in unique:
                    if slot_id == "path_choice":
                        raise FoundryError("NS1R_DUPLICATE_PATH_ID", "Duplicate Path IDs are not permitted and are never silently normalized.", details={"category": slot_id, "choice_id": value})
                    if slot_id == "method_choice":
                        raise FoundryError("NS1R_DUPLICATE_METHOD_ID", "Duplicate Method IDs are not permitted and are never silently normalized.", details={"category": slot_id, "choice_id": value})
                    # Preserve the accepted CAT2 behavior for flat non-Path selections: store one stable ID.
                    continue
                unique.append(value)
            category = by_slot[slot_id]
            maximum = category.get("max")
            if maximum is not None and len(unique) > int(maximum):
                raise FoundryError(
                    "CHARACTER_SHEET_TOO_MANY_CHOICES",
                    "Too many choices were locked in one character-sheet section.",
                    details={"category": slot_id, "maximum": maximum, "actual": len(unique)},
                )
            offered = {choice["choice_id"]: choice for choice in category["choices"]}
            unavailable = [choice_id for choice_id in unique if choice_id not in offered]
            if unavailable:
                legacy_findings = options.get("legacy_talent_findings") or {}
                legacy = [legacy_findings[choice_id] for choice_id in unavailable if choice_id in legacy_findings]
                if slot_id == "advancement_skeleton" and legacy:
                    raise FoundryError(
                        "CHARACTER_SHEET_LEGACY_NON_TALENT_SELECTION",
                        "A saved flat Talent selection now has an explicit non-Talent or unresolved source classification. The draft was not rewritten and no replacement was inferred.",
                        details={"category": slot_id, "choice_ids": unavailable, "findings": legacy},
                    )
                raise FoundryError(
                    "CHARACTER_SHEET_CHOICE_UNAVAILABLE",
                    "One or more selected choices are not available in the installed authoritative rules.",
                    details={"category": slot_id, "choice_ids": unavailable},
                )
            blocked = [choice_id for choice_id in unique if offered[choice_id].get("planning_priority_available") is False]
            if blocked:
                raise FoundryError(
                    "CHARACTER_SHEET_CHOICE_SOURCE_CONFLICT",
                    offered[blocked[0]].get("unavailable_reason") or "That choice is not currently available.",
                    details={"category": slot_id, "choice_ids": blocked},
                )
            if unique:
                normalized[slot_id] = unique
                for choice_id in unique:
                    selected_choices[choice_id] = offered[choice_id]
        path_ids = normalized.get("path_choice", [])
        if path_ids:
            canonicalize_path_ids(path_ids)
        subpath_ids = normalized.get("subpath_choice", [])
        if subpath_ids and not path_ids:
            raise FoundryError(
                "CHARACTER_SHEET_SUBPATH_REQUIRES_PATH",
                "Choose a Primary Path before choosing a Subpath or Tradition.",
                details={"subpath_id": subpath_ids[0]},
            )
        if path_ids and subpath_ids:
            selected_path_set = set(path_ids)
            subpath_by_owner: dict[str, str] = {}
            for subpath_id in subpath_ids:
                subpath = selected_choices[subpath_id]
                owning_path_ids = set(subpath.get("related_choice_ids") or [])
                matched = sorted(selected_path_set & owning_path_ids)
                if len(matched) != 1:
                    raise FoundryError(
                        "CHARACTER_SHEET_PATH_SUBPATH_MISMATCH",
                        "That Subpath or Tradition must belong to exactly one selected Path.",
                        details={
                            "selected_path_ids": sorted(selected_path_set),
                            "subpath_id": subpath_id,
                            "allowed_path_ids": sorted(owning_path_ids),
                        },
                    )
                owner = matched[0]
                if owner in subpath_by_owner:
                    raise FoundryError(
                        "NS1R_MULTIPLE_SUBPATHS_FOR_ONE_PATH",
                        "Each Path may have only one current Subpath or Tradition.",
                        details={"path_id": owner, "selection_ids": [subpath_by_owner[owner], subpath_id]},
                    )
                subpath_by_owner[owner] = subpath_id

        background_ids = normalized.get("background_choice", [])
        if background_ids:
            background = selected_choices[background_ids[0]]
            allowed = set(background.get("related_choice_ids") or [])
            for slot_id in ("background_sphere_choice", "background_talent_choice", "origin_insight_choice"):
                incompatible = [choice_id for choice_id in normalized.get(slot_id, []) if choice_id not in allowed]
                if incompatible:
                    raise FoundryError(
                        "CHARACTER_SHEET_BACKGROUND_CHOICE_MISMATCH",
                        "That Background does not offer the selected Sphere, Talent, or Origin Insight.",
                        details={"background_id": background_ids[0], "category": slot_id, "choice_ids": incompatible},
                    )
        sphere_ids = normalized.get("background_sphere_choice", [])
        talent_ids = normalized.get("background_talent_choice", [])
        if background_ids and (sphere_ids or talent_ids):
            background_authority = NonSphereAuthorityService(self.db).background_route_authority[background_ids[0]]
            exact_routes = background_authority.get("route_options", [])
            supplied_sphere = sphere_ids[0] if sphere_ids else None
            supplied_talent = talent_ids[0] if talent_ids else None
            valid_partial = any(
                (not supplied_sphere or route["background_sphere_choice_id"] == supplied_sphere)
                and (not supplied_talent or route["background_talent_choice_id"] == supplied_talent)
                for route in exact_routes
            )
            if not valid_partial:
                raise FoundryError(
                    "CHARACTER_SHEET_BACKGROUND_ROUTE_MISMATCH",
                    "The selected Background Sphere and Talent are not one exact published Background route.",
                    details={
                        "background_id": background_ids[0],
                        "selected_pair": (supplied_sphere, supplied_talent),
                        "allowed_pairs": sorted(
                            (route["background_sphere_choice_id"], route["background_talent_choice_id"])
                            for route in exact_routes
                        ),
                    },
                )
        if sphere_ids and talent_ids:
            talent = selected_choices[talent_ids[0]]
            if sphere_ids[0] not in set(talent.get("related_choice_ids") or []):
                raise FoundryError(
                    "CHARACTER_SHEET_BACKGROUND_TALENT_SPHERE_MISMATCH",
                    "That Background Talent belongs to a different Background Sphere.",
                    details={"sphere_id": sphere_ids[0], "talent_id": talent_ids[0]},
                )
        # Shared initial-creator evaluator: target CL and build prerequisites
        # gate Subpaths/Traditions. Access labels are recorded provenance, not
        # a requirement for a preexisting database row.
        access_source_records = deepcopy(access_source_records or [])
        for subpath_id in subpath_ids:
            subpath = selected_choices[subpath_id]
            minimum_cl = int(subpath.get("minimum_cl") or 3)
            if target_cl < minimum_cl:
                raise FoundryError(
                    "NS1R_SUBPATH_CL3_REQUIRED",
                    f"{subpath.get('name') or subpath_id} requires Cultivation Level {minimum_cl}+.",
                    details={"selection_id": subpath_id, "target_cl": target_cl, "minimum_cl": minimum_cl},
                )
            access = subpath.get("access") or {}
            subpath["acquisition_provenance"] = {
                "schema": "TianxiaFactory.AcquisitionProvenance.v1",
                "canonical_content_id": subpath_id,
                "content_type": "Spirit Tradition" if subpath.get("option_type") == "tradition" else f"{subpath.get('owning_path_name') or 'Path'} Subpath",
                "access_category": access.get("canonical_category") or access.get("printed_category") or "Open",
                "source": "initial-character-creation",
                "recorded": True,
            }
        method_ids = normalized.get("method_choice", [])
        for method_id in method_ids:
            method_choice = selected_choices[method_id]
            disposition = method_choice.get("ns1r_disposition") or {}
            compatibility = method_path_compatibility(path_ids, method_choice)
            if not compatibility["granted_path_ids"]:
                raise FoundryError(
                    "NS1R_METHOD_NO_LEGAL_PATH",
                    "The selected Cultivation Method grants no legal starting Path for initial creation.",
                    details={"method_id": method_id},
                )
            if compatibility["missing_path_ids"]:
                raise FoundryError(
                    "NS1R_METHOD_GATED_AP_ROUTE_BLOCKED",
                    "The selected Cultivation Method does not support every required advancing Path.",
                    details={
                        "method_id": method_id,
                        "required_path_ids": compatibility["required_path_ids"],
                        "proposed_method_granted_path_ids": compatibility["granted_path_ids"],
                        "unsupported_path_ids": compatibility["missing_path_ids"],
                    },
                )
            if not method_choice.get("initial_creation_selectable") and not any(
                row.get("authority_type") == "method_access" and row.get("method_id") == method_id
                for row in access_source_records
            ):
                raise FoundryError(
                    "NS1R_METHOD_ACCESS_REQUIRED",
                    "This Method is not freely selectable; exact acquisition or access authority is required.",
                    details={"method_id": method_id, "disposition": disposition},
                )
        foundation_ids = normalized.get("foundation_choice", [])
        if path_ids and foundation_ids:
            foundation_choice = selected_choices[foundation_ids[0]]
            supported_paths = set(foundation_choice.get("related_choice_ids") or [])
            unsupported_paths = sorted(set(path_ids) - supported_paths)
            if unsupported_paths:
                raise FoundryError(
                    "NS1R_FOUNDATION_ACTIVE_PATH_UNSUPPORTED",
                    "The selected Foundation does not support every selected starting Path expression.",
                    details={"foundation_id": foundation_ids[0], "unsupported_path_ids": unsupported_paths, "supported_path_ids": sorted(supported_paths)},
                )
        return normalized, selected_choices

    def _validated_planning_preferences(
        self, sphere_priority_ids: list[str] | None, talent_priority_ids: list[str] | None,
    ) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
        options = self.options()
        by_slot = {row["slot_id"]: row for row in options["categories"]}
        spheres = {row["choice_id"]: row for row in by_slot["sphere_priorities"]["choices"]}
        talents = {row["choice_id"]: row for row in by_slot["advancement_skeleton"]["choices"]}

        def unique_ids(values: list[str] | None, label: str) -> list[str]:
            result: list[str] = []
            for value in values or []:
                if not isinstance(value, str) or not value:
                    raise FoundryError("CHARACTER_PLANNING_PREFERENCE_INVALID", f"A {label} priority ID is invalid.", details={"choice_id": value})
                if value not in result:
                    result.append(value)
            return result

        sphere_ids = unique_ids(sphere_priority_ids, "Sphere")
        talent_ids = unique_ids(talent_priority_ids, "talent")
        if len(sphere_ids) > 8:
            raise FoundryError("CHARACTER_PLANNING_TOO_MANY_SPHERES", "Choose no more than eight Sphere planning priorities.", details={"maximum": 8, "actual": len(sphere_ids)})
        unavailable_spheres = [
            {"sphere_id": sphere_id, "name": spheres.get(sphere_id, {}).get("name") or sphere_id, "reason": spheres.get(sphere_id, {}).get("unavailable_reason") or "Not available in accepted canonical authority."}
            for sphere_id in sphere_ids
            if sphere_id not in spheres or not spheres[sphere_id].get("planning_priority_available")
        ]
        if unavailable_spheres:
            raise FoundryError(
                "CHARACTER_PLANNING_SPHERE_NOT_CREATOR_READY",
                f"{unavailable_spheres[0]['name']} cannot be used as a character-planning priority: {unavailable_spheres[0]['reason']}",
                details={"spheres": unavailable_spheres, "focus_field": "sheetSphereAdd"},
            )
        unavailable_talents = [
            {"talent_id": talent_id, "name": talents.get(talent_id, {}).get("canonical_name") or talents.get(talent_id, {}).get("name") or talent_id, "reason": "Restricted content is not selectable as a planning priority."}
            for talent_id in talent_ids
            if talent_id not in talents or not talents[talent_id].get("planning_priority_available")
        ]
        if unavailable_talents:
            raise FoundryError(
                "CHARACTER_PLANNING_TALENT_NOT_AVAILABLE",
                f"{unavailable_talents[0]['name']} cannot be used as a planning priority: {unavailable_talents[0]['reason']}",
                details={"talents": unavailable_talents, "focus_field": "sheetTalentOptions"},
            )
        orphaned = [
            {"talent_id": talent_id, "talent_name": talents[talent_id].get("canonical_name") or talents[talent_id].get("name") or talent_id, "required_sphere_id": talents[talent_id].get("owning_canonical_sphere_id"), "required_sphere_name": talents[talent_id].get("owning_canonical_sphere_name")}
            for talent_id in talent_ids
            if talents[talent_id].get("owning_canonical_sphere_id") not in sphere_ids
        ]
        if orphaned:
            raise FoundryError(
                "CHARACTER_PLANNING_TALENT_REQUIRES_SPHERE_PRIORITY",
                f"Prioritize {orphaned[0]['required_sphere_name']} before prioritizing {orphaned[0]['talent_name']}.",
                details={"talents": orphaned, "focus_field": "sheetSphereAdd"},
            )
        preferences = {}
        if sphere_ids:
            preferences["sphere_priority_ids"] = sphere_ids
        if talent_ids:
            preferences["talent_priority_ids"] = talent_ids
        records = {choice_id: spheres[choice_id] for choice_id in sphere_ids}
        records.update({choice_id: talents[choice_id] for choice_id in talent_ids})
        return preferences, records

    def _validate_creator_ready_acquisitions(self, canonical_sphere_ids: list[str]) -> None:
        if not canonical_sphere_ids:
            return
        sphere_choices = {row["choice_id"]: row for row in next(row for row in self.options()["categories"] if row["slot_id"] == "sphere_priorities")["choices"]}
        blocked = [
            {"sphere_id": sphere_id, "name": sphere_choices.get(sphere_id, {}).get("name") or sphere_id, "reason": sphere_choices.get(sphere_id, {}).get("unavailable_reason") or "No legal free talent authority is available."}
            for sphere_id in canonical_sphere_ids
            if sphere_id not in sphere_choices or not sphere_choices[sphere_id].get("creator_acquisition_available")
        ]
        if blocked:
            raise FoundryError(
                "CANONICAL_SPHERE_NOT_CREATOR_READY",
                f"{blocked[0]['name']} cannot be acquired in character creation: {blocked[0]['reason']}",
                details={"spheres": blocked},
            )

    @staticmethod
    def _project_lock_values(project: dict[str, Any]) -> dict[str, Any]:
        return {
            lock.get("field"): lock.get("value")
            for lock in project.get("user_locks", [])
            if isinstance(lock, dict) and isinstance(lock.get("field"), str)
        }

    @staticmethod
    def _project_envelope(project_result: dict[str, Any]) -> dict[str, Any]:
        project = deepcopy(project_result.get("project") or project_result)
        if isinstance(project_result.get("project"), dict):
            for key in ("project_id", "revision", "working_name"):
                if key in project_result:
                    project[key] = deepcopy(project_result[key])
        return project

    def _normal_first_cycle_catalog_choices(
        self, project: dict[str, Any], locks: dict[str, Any],
    ) -> tuple[list[str], dict[str, str], list[str]]:
        """Choose one complete initial route from server-owned CAT3 authority.

        Planning preferences are only ordering hints. The returned choices are
        revalidated by ``commit_catalog_choices`` before they become the
        immutable revision-bound lock consumed by Character Creation.
        """
        target_cl = locks.get("target_cl")
        if not isinstance(target_cl, int) or not 1 <= target_cl <= 20:
            raise FoundryError(
                "CG1_NORMAL_FIRST_CYCLE_TARGET_INVALID",
                "The normal first-cycle catalog plan requires a typed target CL.",
                status_code=409,
            )

        preferences = locks.get("character_sheet.planning_preferences") or {}
        preferred_sphere_ids = list(preferences.get("sphere_priority_ids") or [])
        preferred_talent_ids = list(preferences.get("talent_priority_ids") or [])
        sphere_rows = self.canonical_catalog.list_spheres()["records"]
        sphere_by_id = {row["canonical_sphere_id"]: row for row in sphere_rows}
        ordered_sphere_ids: list[str] = []
        for sphere_id in [*preferred_sphere_ids, *(row["canonical_sphere_id"] for row in sphere_rows)]:
            canonical_id = self.canonical_catalog.resolve_sphere_id(sphere_id)
            if canonical_id and canonical_id not in ordered_sphere_ids:
                ordered_sphere_ids.append(canonical_id)

        selected_sphere_id: str | None = None
        selected_sphere_talents: list[dict[str, Any]] = []
        free_talent_id: str | None = None
        for sphere_id in ordered_sphere_ids:
            if sphere_id not in sphere_by_id:
                continue
            sphere = self.canonical_catalog.get_sphere(sphere_id)
            talents = list(sphere.get("talents") or [])
            talent_by_id = {row.get("canonical_talent_id"): row for row in talents}
            preferred_for_sphere = [
                talent_by_id[talent_id]
                for talent_id in preferred_talent_ids
                if talent_id in talent_by_id
            ]
            preferred_ids = {row.get("canonical_talent_id") for row in preferred_for_sphere}
            ordered_talents = preferred_for_sphere + [
                row for row in talents
                if row.get("canonical_talent_id") not in preferred_ids
            ]
            free = next(
                (
                    row for row in ordered_talents
                    if row.get("free_sphere_talent_eligible") is True
                    and row.get("access_category") == "Open"
                    and row.get("creator_selectability_can_be_evaluated_safely") is True
                    and isinstance(row.get("minimum_cl"), int)
                    and row["minimum_cl"] <= 1
                ),
                None,
            )
            if free is not None:
                selected_sphere_id = sphere_id
                selected_sphere_talents = ordered_talents
                free_talent_id = free["canonical_talent_id"]
                break

        if not selected_sphere_id or not free_talent_id:
            raise FoundryError(
                "CG1_NORMAL_FIRST_CYCLE_PLAN_UNAVAILABLE",
                "The current canonical catalog cannot supply a legal first-cycle Sphere and free Talent.",
                status_code=409,
            )

        locked_choices = locks.get("character_sheet.locked_choices") or {}
        selected_non_sphere_ids = sorted({
            str(choice_id)
            for values in locked_choices.values()
            if isinstance(values, list)
            for choice_id in values
            if isinstance(choice_id, str) and choice_id
        })
        context = {
            "target_cl": target_cl,
            "acquired_sphere_ids": [selected_sphere_id],
            "free_talent_grants": {selected_sphere_id: free_talent_id},
            "path_ids": selected_non_sphere_ids,
            "subpath_or_tradition_ids": selected_non_sphere_ids,
            "method_ids": selected_non_sphere_ids,
            "foundation_or_feature_ids": selected_non_sphere_ids,
            "character_feature_ids": selected_non_sphere_ids,
        }
        selected_talent_ids = {free_talent_id}
        ordinary_talent_ids: list[str] = []
        priority_ids = [
            talent_id for talent_id in preferred_talent_ids
            if talent_id != free_talent_id
            and any(row.get("canonical_talent_id") == talent_id for row in selected_sphere_talents)
        ]
        priority_id_set = set(priority_ids)
        ordered_progression = priority_ids + [
            row["canonical_talent_id"] for row in selected_sphere_talents
            if row.get("canonical_talent_id") not in {free_talent_id, *priority_id_set}
        ]
        talent_by_id = {
            row["canonical_talent_id"]: row
            for row in selected_sphere_talents
            if row.get("canonical_talent_id")
        }
        for effective_cl in range(1, target_cl + 1):
            chosen: str | None = None
            for talent_id in ordered_progression:
                if talent_id in selected_talent_ids:
                    continue
                talent = talent_by_id[talent_id]
                if (
                    talent.get("access_category") != "Open"
                    or talent.get("creator_selectability_can_be_evaluated_safely") is not True
                    or not isinstance(talent.get("minimum_cl"), int)
                    or talent["minimum_cl"] > effective_cl
                ):
                    continue
                try:
                    self.canonical_catalog.validate_grant_plan_for_initial_creation(
                        **context,
                        ordinary_talent_ids=[*ordinary_talent_ids, talent_id],
                    )
                except FoundryError as exc:
                    if exc.status_code >= 500:
                        raise
                    continue
                chosen = talent_id
                break
            if chosen is None:
                raise FoundryError(
                    "CG1_NORMAL_FIRST_CYCLE_PLAN_UNAVAILABLE",
                    "The current canonical catalog cannot supply one legal ordinary Talent for every first-cycle CL.",
                    details={"target_cl": target_cl, "effective_cl": effective_cl, "sphere_id": selected_sphere_id},
                    status_code=409,
                )
            ordinary_talent_ids.append(chosen)
            selected_talent_ids.add(chosen)

        return [selected_sphere_id], {selected_sphere_id: free_talent_id}, ordinary_talent_ids

    def _resolved_pack_locks(self, selected_choices: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
        packs = self.packs.list()
        # New projects lock one deterministic current version per pack ID.
        # Historical versions remain installed and readable for projects that
        # already locked them; they are not silently migrated.
        usable = [
            pack for pack in packs
            if pack.get("record_count", 0) > 0
            and pack.get("lifecycle_state", "published") == "published"
            and (pack.get("authority") == "canonical" or pack.get("selectable"))
        ]
        by_key = {(pack["pack_id"], pack["version"]): pack for pack in usable}
        by_id: dict[str, list[dict[str, Any]]] = {}
        for pack in usable:
            by_id.setdefault(pack["pack_id"], []).append(pack)
        for candidates in by_id.values():
            candidates.sort(key=lambda pack: _version_key(pack["version"]), reverse=True)

        required: dict[str, str] = {}
        for pack_id, candidates in by_id.items():
            canonical = [pack for pack in candidates if pack.get("authority") == "canonical"]
            if canonical:
                required[pack_id] = canonical[0]["version"]

        for choice in selected_choices.values():
            key = (str(choice.get("pack_id") or ""), str(choice.get("pack_version") or ""))
            if key not in by_key:
                raise FoundryError(
                    "CHARACTER_SHEET_CHOICE_PACK_UNAVAILABLE",
                    "A selected character choice belongs to a rules pack that cannot be locked for a new project.",
                    details={"choice_id": choice["choice_id"], "pack_id": key[0], "version": key[1]},
                )
            candidates = by_id.get(key[0], [])
            canonical = [pack for pack in candidates if pack.get("authority") == "canonical"]
            selected_version = canonical[0]["version"] if canonical else candidates[0]["version"]
            current = required.get(key[0])
            if current is None or _version_key(selected_version) > _version_key(current):
                required[key[0]] = selected_version

        queue = list(sorted(required))
        visited: set[str] = set()
        while queue:
            pack_id = queue.pop(0)
            if pack_id in visited:
                continue
            visited.add(pack_id)
            version = required[pack_id]
            pack = by_key.get((pack_id, version))
            if not pack:
                raise FoundryError(
                    "CHARACTER_SHEET_PACK_UNAVAILABLE",
                    "A required rules pack is unavailable.",
                    details={"pack_id": pack_id, "version": version},
                )
            for dependency in pack.get("manifest", {}).get("dependencies", []):
                if not isinstance(dependency, dict) or dependency.get("optional"):
                    continue
                dep_id = str(dependency.get("pack_id") or "")
                version_range = str(dependency.get("version_range") or "")
                candidates = [candidate for candidate in by_id.get(dep_id, []) if _exact_pack_version_matches(candidate["version"], version_range)]
                if not candidates:
                    raise FoundryError(
                        "CHARACTER_SHEET_PACK_DEPENDENCY_MISSING",
                        "A selected choice requires another installed rules pack that is unavailable.",
                        details={"pack_id": dep_id, "version_range": version_range},
                    )
                chosen = candidates[0]["version"]
                existing = required.get(dep_id)
                if existing is not None and not _exact_pack_version_matches(existing, version_range):
                    raise FoundryError(
                        "CHARACTER_SHEET_PACK_DEPENDENCY_CONFLICT",
                        "One current pack version cannot satisfy all exact project dependencies.",
                        details={"pack_id": dep_id, "locked_version": existing, "required_range": version_range},
                    )
                if existing is None:
                    required[dep_id] = chosen
                    queue.append(dep_id)
        if not required:
            raise FoundryError("CHARACTER_SHEET_RULES_UNAVAILABLE", "No ready-to-use authoritative rules pack is installed.")
        return [{"pack_id": pack_id, "version": required[pack_id]} for pack_id in sorted(required)]

    @staticmethod
    def _resolved_background_routes(
        locked_choices: dict[str, list[str]], supplied: dict[str, Any], *, authority: NonSphereAuthorityService,
    ) -> dict[str, Any]:
        background_ids = locked_choices.get("background_choice") or []
        if not background_ids:
            if supplied:
                raise FoundryError("NS1R_BACKGROUND_ROUTE_WITHOUT_BACKGROUND", "Background route IDs cannot be supplied without a selected Background.")
            return {}
        background_id = background_ids[0]
        exact = authority.background_route_authority[background_id]
        routes = deepcopy(supplied)
        talent_ids = locked_choices.get("background_talent_choice") or []
        sphere_ids = locked_choices.get("background_sphere_choice") or []
        insight_ids = locked_choices.get("origin_insight_choice") or []

        selected_route = None
        requested_route_id = routes.get("background_route_record_id")
        requested_talent_id = talent_ids[0] if talent_ids else routes.get("background_talent_choice_id")
        for route in exact["route_options"]:
            if requested_route_id and route["background_route_record_id"] == requested_route_id:
                selected_route = route
                break
            if requested_talent_id and route["background_talent_choice_id"] == requested_talent_id:
                selected_route = route
                break
        if selected_route is not None:
            if talent_ids and talent_ids[0] != selected_route["background_talent_choice_id"]:
                raise FoundryError(
                    "NS1R_BACKGROUND_TALENT_ROUTE_MISMATCH",
                    "The selected Background Talent does not match the exact Background route record.",
                    details={"background_id": background_id, "selected_talent_id": talent_ids[0], "route": selected_route},
                )
            if sphere_ids and sphere_ids[0] != selected_route["background_sphere_choice_id"]:
                raise FoundryError(
                    "NS1R_BACKGROUND_SPHERE_ROUTE_MISMATCH",
                    "The selected Background Sphere does not match the exact Background route record.",
                    details={"background_id": background_id, "selected_sphere_id": sphere_ids[0], "route": selected_route},
                )
            routes["background_route_record_id"] = selected_route["background_route_record_id"]
            routes["background_talent_choice_id"] = selected_route["background_talent_choice_id"]
            routes["background_sphere_choice_id"] = selected_route["background_sphere_choice_id"]
        elif talent_ids or requested_route_id:
            raise FoundryError(
                "NS1R_BACKGROUND_ROUTE_ID_INVALID",
                "The selected Background route does not exist in the exact accepted CAT2 authority.",
                details={"background_id": background_id, "background_route_record_id": requested_route_id, "background_talent_choice_id": requested_talent_id},
            )

        if insight_ids:
            routes["origin_insight_choice_id"] = insight_ids[0]
        routes.setdefault("equipment_authority_id", exact["equipment_authority_id"])
        routes.setdefault("skills_authority_id", exact["skills_authority_id"])
        routes.setdefault("tools_languages_trades_authority_id", exact["tools_languages_trades_authority_id"])
        return routes

    def commit_catalog_choices(
        self,
        project_id: str,
        *,
        acquired_sphere_ids: list[str],
        free_talent_grants: dict[str, str],
        ordinary_talent_ids: list[str],
    ) -> dict[str, Any]:
        """Freeze exact typed acquisitions before any creation compilation.

        This input contains choices only.  It has no evidence, issuance route,
        trusted flag, or client-authored authority object.  The server validates
        the records and prerequisites before appending a one-shot immutable lock.
        """
        project_result = self.projects.get_project(project_id)
        project = project_result["project"]
        target_cl = next((
            lock.get("value") for lock in project.get("user_locks", [])
            if isinstance(lock, dict) and lock.get("field") == "target_cl"
        ), None)
        if not isinstance(target_cl, int) or not 1 <= target_cl <= 20:
            raise FoundryError(
                "CATALOG_CHOICE_LOCK_TARGET_CL_MISSING",
                "The project must have an immutable typed target CL before catalog choices can be frozen.",
                status_code=409,
            )
        self._validate_creator_ready_acquisitions(acquired_sphere_ids)
        selected_non_sphere_ids = sorted({
            str(choice_id)
            for lock in project.get("user_locks", [])
            if isinstance(lock, dict) and lock.get("field") == "character_sheet.locked_choices"
            for values in (lock.get("value") or {}).values()
            if isinstance(values, list)
            for choice_id in values
        })
        plan = self.canonical_catalog.validate_grant_plan_for_initial_creation(
            target_cl=target_cl,
            acquired_sphere_ids=acquired_sphere_ids,
            free_talent_grants=free_talent_grants,
            ordinary_talent_ids=ordinary_talent_ids,
            path_ids=selected_non_sphere_ids,
            subpath_or_tradition_ids=selected_non_sphere_ids,
            method_ids=selected_non_sphere_ids,
            foundation_or_feature_ids=selected_non_sphere_ids,
            character_feature_ids=selected_non_sphere_ids,
        )
        updated = self.projects.append_user_locks(
            project_id,
            [{
                "field": COMMITTED_CATALOG_CHOICE_FIELD,
                "value": deepcopy(plan),
                "source": "server-validated-canonical-choice-commit",
            }],
            _require_unstarted_character_creation=True,
        )
        from character_creation.choice_snapshot import materialize_choice_snapshot
        snapshot_project = self._project_envelope(updated)
        return {
            "schema": "TianxiaFoundry.CanonicalCatalogChoiceCommit.v1",
            "project_id": project_id,
            "project_revision": updated["project"]["revision"],
            "grant_plan": deepcopy(plan),
            "typed_choice_snapshot": materialize_choice_snapshot(snapshot_project),
            "evidence_issued": False,
        }

    def commit_normal_first_cycle_catalog_choices(self, project_id: str) -> dict[str, Any]:
        """Freeze the normal wizard's first-cycle plan before any run starts."""
        project_result = self.projects.get_project(project_id)
        project = project_result["project"]
        locks = self._project_lock_values(project)
        committed = locks.get(COMMITTED_CATALOG_CHOICE_FIELD)
        if isinstance(committed, dict):
            accounting = committed.get("grant_accounting")
            if (
                committed.get("schema") != "TianxiaFactory.CanonicalGrantPlan.v1"
                or committed.get("ready") is not True
                or committed.get("target_cl") != locks.get("target_cl")
                or not isinstance(committed.get("acquired_canonical_sphere_ids"), list)
                or not isinstance(accounting, dict)
                or not isinstance(accounting.get("free_sphere_talent_grants"), list)
                or not isinstance(accounting.get("ordinary_talent_ids"), list)
            ):
                raise FoundryError(
                    "CG1_COMMITTED_CATALOG_CHOICE_PLAN_INVALID",
                    "The existing normal-wizard canonical catalog choice lock is invalid.",
                    status_code=409,
                )
            from character_creation.choice_snapshot import materialize_choice_snapshot
            return {
                "schema": "TianxiaFoundry.CanonicalCatalogChoiceCommit.v1",
                "project_id": project_id,
                "project_revision": project["revision"],
                "grant_plan": deepcopy(committed),
                "typed_choice_snapshot": materialize_choice_snapshot(self._project_envelope(project_result)),
                "evidence_issued": False,
                "idempotent": True,
            }

        legacy = locks.get("character_sheet.canonical_grant_plan")
        accounting = legacy.get("grant_accounting") if isinstance(legacy, dict) else None
        if isinstance(legacy, dict) and (
            legacy.get("acquired_canonical_sphere_ids")
            or (accounting or {}).get("free_sphere_talent_grants")
            or (accounting or {}).get("ordinary_talent_ids")
        ):
            acquired_sphere_ids = list(legacy.get("acquired_canonical_sphere_ids") or [])
            free_talent_grants = {
                row["sphere_id"]: row["talent_id"]
                for row in (accounting or {}).get("free_sphere_talent_grants") or []
                if isinstance(row, dict) and row.get("sphere_id") and row.get("talent_id")
            }
            ordinary_talent_ids = list((accounting or {}).get("ordinary_talent_ids") or [])
        else:
            acquired_sphere_ids, free_talent_grants, ordinary_talent_ids = self._normal_first_cycle_catalog_choices(project, locks)
        return self.commit_catalog_choices(
            project_id,
            acquired_sphere_ids=acquired_sphere_ids,
            free_talent_grants=free_talent_grants,
            ordinary_talent_ids=ordinary_talent_ids,
        )

    def create_project(
        self,
        *,
        working_name: str,
        concept: str,
        target_cl: int,
        power_band: str,
        source_reference: str | None,
        creation_mode: str,
        ability_scores: dict[str, int | None] | None,
        selections: dict[str, list[str]] | None,
        sphere_priority_ids: list[str] | None = None,
        talent_priority_ids: list[str] | None = None,
        method_planning_mode: str | None = None,
        method_preference_id: str | None = None,
        method_route_choice: str | None = None,
        method_learning_note: str | None = None,
        canonical_sphere_ids: list[str] | None = None,
        sphere_free_talent_grants: dict[str, str] | None = None,
        ordinary_talent_ids: list[str] | None = None,
        access_source_records: list[dict[str, Any]] | None = None,
        background_route_ids: dict[str, str] | None = None,
        generation_route: str = "player",
        project_id_override: str | None = None,
    ) -> dict[str, Any]:
        requested_working_name = str(working_name or "").strip()
        requested_concept = str(concept or "").strip()
        project_working_name = requested_working_name or "AI-proposed character"
        if generation_route not in {"player", "ai_bootstrap"}:
            raise FoundryError(
                "CHARACTER_SHEET_GENERATION_ROUTE_INVALID",
                "The character generation route must be player or ai_bootstrap.",
                details={"generation_route": generation_route},
            )
        point_buy = self.validate_point_buy(ability_scores)
        submitted_selections = deepcopy(selections or {})
        selected_method_ids = list(submitted_selections.get("method_choice") or [])
        # Compatibility for existing callers and accepted PR #7 fixtures: a
        # submitted Method choice before this planning field existed is the
        # same explicit hard lock, never an implicit preference or acquisition.
        legacy_method_lock = method_planning_mode is None and bool(selected_method_ids)
        method_planning_mode = str(method_planning_mode or ("HARD_LOCK" if selected_method_ids else "AUTO")).upper()
        if method_planning_mode not in {"AUTO", "PREFERENCE", "EXACT", "HARD_LOCK"}:
            raise FoundryError("CHARACTER_METHOD_PLANNING_MODE_INVALID", "Choose for me, prefer a Method, or use an exact Method.")
        if method_planning_mode == "AUTO":
            submitted_selections.pop("method_choice", None)
            method_preference_id = None
        elif method_planning_mode == "PREFERENCE":
            submitted_selections.pop("method_choice", None)
            if not method_preference_id:
                raise FoundryError("CHARACTER_METHOD_PREFERENCE_REQUIRED", "Choose one Method preference or use Auto.")
        elif len(selected_method_ids) != 1:
            raise FoundryError("CHARACTER_METHOD_EXACT_CHOICE_REQUIRED", "Choose exactly one Method to use.")
        elif not legacy_method_lock:
            # The new owner hard lock is planning authority. It must not create
            # an acquired/Primary Method before the complete plan compiles.
            submitted_selections.pop("method_choice", None)
        legacy_sphere_priorities = submitted_selections.pop("sphere_priorities", [])
        legacy_talent_priorities = submitted_selections.pop("advancement_skeleton", [])
        effective_sphere_priorities = list(sphere_priority_ids or legacy_sphere_priorities)
        effective_talent_priorities = list(talent_priority_ids or legacy_talent_priorities)
        locked_choices, selected_choice_records = self._validated_selections(
            submitted_selections, target_cl=target_cl, access_source_records=access_source_records
        )
        authority_service = NonSphereAuthorityService(self.db)
        required_path_ids = locked_choices.get("path_choice", [])
        path_method_contract = compatibility_envelope(
            required_path_ids,
            authority_service.method_catalog(initial_creation=True)["records"],
        )
        if required_path_ids and not path_method_contract["compatible_method_ids"]:
            raise no_compatible_method_error(required_path_ids)
        planning_preferences, preference_choice_records = self._validated_planning_preferences(
            effective_sphere_priorities, effective_talent_priorities
        )
        exact_method_access_plan = None
        if method_planning_mode in {"EXACT", "HARD_LOCK"} and not legacy_method_lock:
            methods = {row["choice_id"]: row for row in next(row for row in self.options()["categories"] if row["slot_id"] == "method_choice")["choices"]}
            method_id = selected_method_ids[0]
            method = methods.get(method_id)
            if method is None:
                raise FoundryError("NS1R_METHOD_ID_UNKNOWN", "The selected Method is not available.", details={"method_id": method_id})
            authority = method.get("method_planning") or {}
            compatibility = method_path_compatibility(required_path_ids, method)
            if compatibility["missing_path_ids"]:
                raise FoundryError(
                    "CHARACTER_SHEET_METHOD_PATH_MISMATCH",
                    "The selected Method does not support every required advancing Path.",
                    details={
                        "method_id": method_id,
                        "required_path_ids": compatibility["required_path_ids"],
                        "proposed_method_granted_path_ids": compatibility["granted_path_ids"],
                        "unsupported_path_ids": compatibility["missing_path_ids"],
                    },
                )
            exact_method_access_plan = authority_service.resolve_initial_method_access(
                method_id,
                route_choice=method_route_choice,
                owner_annotation=method_learning_note,
            )
            planning_preferences["method_exact_choice_id"] = method_id
        if method_preference_id:
            methods = {row["choice_id"]: row for row in next(row for row in self.options()["categories"] if row["slot_id"] == "method_choice")["choices"]}
            if method_preference_id not in methods:
                raise FoundryError("NS1R_METHOD_ID_UNKNOWN", "The Method preference is not accepted authority.", details={"method_id": method_preference_id})
            planning_preferences["method_preference_id"] = method_preference_id
        pack_locks = self._resolved_pack_locks({**selected_choice_records, **preference_choice_records})
        # Legacy character-sheet categories are blueprint intent, not acquisition
        # events. Only the explicit CAT2 grant fields may create/count canonical
        # Sphere and talent grants. This preserves existing projects while keeping
        # automatic, free-grant, and ordinary acquisition accounting fail-closed.
        explicit_grant_submission = any(
            value is not None
            for value in (canonical_sphere_ids, sphere_free_talent_grants, ordinary_talent_ids)
        )
        acquired_spheres = list(canonical_sphere_ids or [])
        ordinary_talents = list(ordinary_talent_ids or [])
        free_grants = dict(sphere_free_talent_grants or {})
        self._validate_creator_ready_acquisitions(acquired_spheres)
        exact_non_sphere_ids = sorted({choice_id for values in locked_choices.values() for choice_id in values})
        canonical_context = {
            "target_cl": target_cl,
            "acquired_sphere_ids": acquired_spheres,
            "free_talent_grants": free_grants,
            "ordinary_talent_ids": ordinary_talents,
            # Exact IDs are harmless in more than one typed set; the shared
            # evaluator checks equality against the predicate's controlling ID.
            "path_ids": exact_non_sphere_ids,
            "subpath_or_tradition_ids": exact_non_sphere_ids,
            "method_ids": exact_non_sphere_ids,
            "foundation_or_feature_ids": exact_non_sphere_ids,
            "character_feature_ids": exact_non_sphere_ids,
        }
        canonical_grant_plan = self.canonical_catalog.validate_grant_plan_for_initial_creation(
            **canonical_context
        ) if explicit_grant_submission else self.canonical_catalog.creator_projection_for_initial_creation(**canonical_context)
        canonical_character_projection = self.canonical_catalog.owner_projection_for_character(canonical_grant_plan)
        preferred_record_ids = [choice_id for values in locked_choices.values() for choice_id in values]
        preferred_record_ids.extend(planning_preferences.get("sphere_priority_ids", []))
        preferred_record_ids.extend(planning_preferences.get("talent_priority_ids", []))
        user_locks: list[dict[str, Any]] = [
            {"field": "character.identity.display_name", "value": requested_working_name or None},
            {"field": "concept", "value": requested_concept},
            {"field": "source_reference", "value": source_reference or "Original character"},
            {"field": "target_cl", "value": target_cl},
            {"field": "power_band", "value": power_band},
            {"field": "character_sheet.creation_mode", "value": creation_mode},
            {"field": "character_sheet.generation_route", "value": generation_route},
            {"field": "character_sheet.ability_point_buy", "value": point_buy},
            {"field": "character_sheet.locked_choices", "value": deepcopy(locked_choices)},
            {"field": "character_sheet.planning_preferences", "value": deepcopy(planning_preferences)},
            {"field": "character_sheet.method_planning_mode", "value": method_planning_mode},
            {"field": "character_sheet.method_access_plan", "value": deepcopy(exact_method_access_plan)},
            {"field": "character_sheet.canonical_grant_plan", "value": deepcopy(canonical_grant_plan)},
            {"field": "character_sheet.canonical_character_projection", "value": deepcopy(canonical_character_projection)},
            {"field": "character_sheet.non_sphere_access_sources", "value": deepcopy(access_source_records or [])},
            {"field": "character_sheet.path_method_compatibility", "value": deepcopy(path_method_contract)},
        ]
        if preferred_record_ids:
            user_locks.append({"field": "preferred_record_ids", "value": preferred_record_ids})
        result = self.projects.create_project(
            working_name=project_working_name,
            pack_locks=pack_locks,
            quality_target=power_band,
            user_locks=user_locks,
            source_evidence=[],
            builder_persistence_state="temporary",
            project_id_override=project_id_override,
        )
        non_sphere_state = authority_service.initialize_for_project(
            result["project_id"], target_cl=target_cl,
            path_ids=locked_choices.get("path_choice", []),
            method_id=(locked_choices.get("method_choice") or [None])[0],
            foundation_id=(locked_choices.get("foundation_choice") or [None])[0],
            background_id=(locked_choices.get("background_choice") or [None])[0],
            access_source_records=access_source_records or [],
            path_attainment_by_id={path_id: target_cl for path_id in locked_choices.get("path_choice", [])},
            subpath_ids=locked_choices.get("subpath_choice", []),
            background_route_ids=self._resolved_background_routes(
                locked_choices, background_route_ids or {}, authority=NonSphereAuthorityService(self.db)
            ),
            trusted_initial_creation=True,
        )
        return {
            **result,
            "character_sheet": {
                "creation_mode": creation_mode,
                "generation_route": generation_route,
                "ability_point_buy": point_buy,
                "locked_choices": locked_choices,
                "planning_preferences": planning_preferences,
                "method_planning_mode": method_planning_mode,
                "canonical_grant_plan": canonical_grant_plan,
                "canonical_character_projection": canonical_character_projection,
                "path_method_compatibility": path_method_contract,
                "auto_completion_required": {
                    "ability_scores": bool(point_buy["auto_abilities"]),
                    "unfilled_categories": [config["slot_id"] for config in CATEGORY_CONFIG if config["slot_id"] not in locked_choices],
                },
                "stage": "blueprint_intent_only",
                "non_sphere_state": non_sphere_state,
            },
        }
