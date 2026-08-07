from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterable

from app.core import EXPECTED_FACTORY_HASH, FoundryError, sha256_file, sha256_json
from sphere_component_authority import build_sphere_automatic_component_authority


CANONICAL_STATUS = "CAT3_P1R_CANONICAL_CATALOG_SOURCE_READY_FOR_INDEPENDENT_REVIEW"
AUTHORITY_RELATIVE_PATH = Path("catalog_authority") / "cat3" / "generated" / "catalog_authority.v1.json"
BUNDLED_FACTORY_RELATIVE_PATH = Path("BundledContent") / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
EXPECTED_SCHEMA = "Tianxia.CAT3.CanonicalCatalogAuthority.v1"
EXPECTED_SPHERES = 85
REALM_ENTRY_CL = {"Mortal": 1, "Foundation": 5, "Core Formation": 10, "Nascent Soul": 15, "Immortal": 20}
_INITIAL_CREATION_AUTHORITY = object()
_ACCEPTED_EVIDENCE_ROUTES = {"initial_character_finalization", "post_creation_acquisition"}
_ACCEPTED_RESOLVED_CREATION_AUTHORITIES = {
    "AUTHENTICATED_PROJECT_AUTHORITY_SERVICE",
    "COMMITTED_SOURCE",
    "TRUSTED_SERVER_INITIAL_CHARACTER_CREATION",
}


def _normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).replace("’", "'").replace("‘", "'").replace("â€™", "'").replace("â€˜", "'")
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _commitment(value: dict[str, Any], field: str = "record_commitment_sha256") -> str:
    payload = {key: item for key, item in value.items() if key != field}
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _first_line(value: str) -> str:
    return next((line.strip() for line in value.splitlines() if line.strip()), "")


def _realm_for_cl(target_cl: int) -> str:
    if target_cl >= 20:
        return "Immortal"
    if target_cl >= 15:
        return "Nascent Soul"
    if target_cl >= 10:
        return "Core Formation"
    if target_cl >= 5:
        return "Foundation"
    return "Mortal"


def _base_ability_row(row: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(row)
    # The generated CAT3 registry deliberately retains compiler diagnostics for
    # audit/recovery.  They are not part of the owner-facing automatic
    # component packet, however, and some historical diagnostics contain the
    # literal placeholder marker.  Keep the source identity/classification
    # fields while excluding only those QA prose fields from runtime
    # projections and grant locks; the generated registry itself remains
    # untouched and its record commitment is still carried below.
    result.pop("reason", None)
    result.pop("source_matrix_implementation_path", None)
    source_matrix = result.get("source_matrix")
    if isinstance(source_matrix, dict):
        source_matrix.pop("implementation_path", None)
    result["owning_canonical_sphere_id"] = row.get("mapped_canonical_sphere_id")
    result["base_ability_id"] = row.get("runtime_component_id") or row.get("candidate_record_id")
    result["source_row_id"] = row.get("source_row_id") or row.get("candidate_record_id")
    result["source_reference"] = deepcopy(row.get("source_provenance") or {})
    result["automatic_grant"] = True
    result["owner_removable"] = False
    result["counts_as_talent_choice"] = False
    result["counts_as_advancement_talent"] = False
    result["counts_as_training_talent"] = False
    return result


class CanonicalCatalogAuthorityService:
    """Sole CAT3 runtime reader and exact prerequisite evaluator."""

    _GLOBAL_DATA_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}

    def __init__(self, root_dir: Path, *, evidence_resolver: Callable[[str, str], dict[str, Any]] | None = None):
        self.root_dir = Path(root_dir).resolve()
        self.authority_path = self.root_dir / AUTHORITY_RELATIVE_PATH
        self.factory_zip = self.root_dir / BUNDLED_FACTORY_RELATIVE_PATH
        self._loaded: dict[str, Any] | None = None
        self._evidence_resolver = evidence_resolver

    def _load(self) -> dict[str, Any]:
        if self._loaded is not None:
            return self._loaded
        if not self.authority_path.is_file():
            raise FoundryError(
                "CANONICAL_CATALOG_AUTHORITY_MISSING",
                "The compiled CAT3 canonical catalog authority is missing.",
                details={"path": str(self.authority_path)}, status_code=503,
            )
        stat = self.authority_path.stat()
        cache_key = (str(self.authority_path), stat.st_size, stat.st_mtime_ns)
        cached = self._GLOBAL_DATA_CACHE.get(cache_key)
        if cached is not None:
            self._loaded = cached
            return cached
        try:
            document = json.loads(self.authority_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FoundryError(
                "CANONICAL_CATALOG_AUTHORITY_INVALID",
                "The compiled CAT3 canonical catalog authority cannot be read.",
                details={"path": str(self.authority_path)}, status_code=503,
            ) from exc
        if document.get("schema") != EXPECTED_SCHEMA:
            raise FoundryError(
                "CANONICAL_CATALOG_SCHEMA_INVALID",
                "The compiled catalog schema is not the accepted CAT3 schema.",
                details={"declared": document.get("schema"), "required": EXPECTED_SCHEMA}, status_code=503,
            )
        if not self.factory_zip.is_file() or sha256_file(self.factory_zip) != EXPECTED_FACTORY_HASH:
            raise FoundryError(
                "CANONICAL_CATALOG_SOURCE_ARCHIVE_INVALID",
                "The packaged producer corpus does not match the application source lock.",
                details={"path": str(self.factory_zip), "expected_sha256": EXPECTED_FACTORY_HASH}, status_code=503,
            )
        counts = document.get("counts") or {}
        spheres = document.get("spheres") or []
        talents = document.get("talents") or []
        memberships = document.get("memberships") or []
        insights = document.get("insights") or []
        sphere_base_ability_authority = document.get("sphere_base_ability_authority") or []
        if len(spheres) != EXPECTED_SPHERES or counts.get("canonical_spheres") != EXPECTED_SPHERES:
            raise FoundryError(
                "CANONICAL_SPHERE_IDENTITY_INVALID",
                "CAT3 authority must contain exactly 85 canonical Spheres.",
                details={"records": len(spheres), "sealed_count": counts.get("canonical_spheres")}, status_code=503,
            )
        body = {key: value for key, value in document.items() if key != "registry_commitment_sha256"}
        actual_registry = hashlib.sha256(_canonical_bytes(body)).hexdigest()
        if actual_registry != document.get("registry_commitment_sha256"):
            raise FoundryError(
                "CANONICAL_CATALOG_COMMITMENT_INVALID",
                "The compiled CAT3 registry commitment does not verify.",
                details={"expected": document.get("registry_commitment_sha256"), "actual": actual_registry}, status_code=503,
            )
        committed_groups = (
            spheres, talents, document.get("sphere_aliases_and_noncanonical_labels") or [],
            document.get("automatic_base_abilities") or [], document.get("automatic_base_ability_aliases") or [],
            sphere_base_ability_authority, insights,
            document.get("background_only_routes") or [], document.get("quarantined_decision_packets") or [],
            document.get("legacy_non_talent_findings") or [],
        )
        for group in committed_groups:
            for row in group:
                if row.get("record_commitment_sha256") != _commitment(row):
                    raise FoundryError(
                        "CANONICAL_RECORD_COMMITMENT_INVALID",
                        "A compiled CAT3 record commitment does not verify.",
                        details={"record_id": row.get("canonical_talent_id") or row.get("canonical_sphere_id") or row.get("candidate_record_id") or row.get("record_id") or row.get("legacy_id")},
                        status_code=503,
                    )
        sphere_by_id = {row["canonical_sphere_id"]: row for row in spheres}
        talent_by_id = {row["canonical_talent_id"]: row for row in talents}
        insight_by_id = {row["canonical_insight_id"]: row for row in insights if row.get("canonical_insight_id")}
        if len(insight_by_id) != len(insights):
            raise FoundryError("CANONICAL_INSIGHT_DUPLICATE_ID", "Compiled CAT3 authority contains duplicate canonical Insight IDs.", status_code=503)
        selectable_insights = [row for row in insights if row.get("selectable") is True]
        source_occurrence_count = sum(len(row.get("source_occurrences") or []) for row in insights)
        if (
            len(insights) != 547
            or len(selectable_insights) != 542
            or source_occurrence_count != 550
            or counts.get("canonical_insights") != len(insights)
            or counts.get("selectable_insights") != len(selectable_insights)
        ):
            raise FoundryError(
                "CANONICAL_INSIGHT_AUTHORITY_INVALID",
                "CAT3 R2 Insight authority counts do not match the accepted reconciliation.",
                details={"records": len(insights), "selectable": len(selectable_insights), "source_occurrences": source_occurrence_count}, status_code=503,
            )
        if len(sphere_by_id) != len(spheres) or len(talent_by_id) != len(talents):
            raise FoundryError("CANONICAL_CATALOG_DUPLICATE_ID", "Compiled CAT3 authority contains duplicate canonical IDs.", status_code=503)
        by_sphere: dict[str, list[str]] = {sphere_id: [] for sphere_id in sphere_by_id}
        seen_memberships: set[str] = set()
        for edge in memberships:
            sphere_id = edge.get("canonical_sphere_id")
            talent_id = edge.get("canonical_talent_id")
            if sphere_id not in sphere_by_id or talent_id not in talent_by_id or talent_id in seen_memberships:
                raise FoundryError("CANONICAL_MEMBERSHIP_INVALID", "Every canonical Talent must have one exact valid membership.", details=edge, status_code=503)
            if talent_by_id[talent_id]["owning_canonical_sphere_id"] != sphere_id:
                raise FoundryError("CANONICAL_MEMBERSHIP_DISAGREES", "Talent ownership and membership edge disagree.", details=edge, status_code=503)
            by_sphere[sphere_id].append(talent_id)
            seen_memberships.add(talent_id)
        if seen_memberships != set(talent_by_id):
            raise FoundryError("CANONICAL_TALENT_ORPHANED", "Every canonical Talent must have one membership edge.", status_code=503)
        alias_to_id = {_normalize_name(row["display_name"]): row["canonical_sphere_id"] for row in spheres}
        for row in document.get("sphere_aliases_and_noncanonical_labels") or []:
            if row.get("canonical_sphere_id"):
                alias_to_id[_normalize_name(row["label"])] = row["canonical_sphere_id"]
        for row in spheres:
            for alias in row.get("aliases") or []:
                alias_to_id[_normalize_name(alias)] = row["canonical_sphere_id"]
        migration_to_id = {
            row["legacy_id"]: row["canonical_id"]
            for row in document.get("stable_id_migrations") or []
            if row.get("record_type") == "talent" and row.get("legacy_id") and row.get("canonical_id")
        }
        legacy_non_talent_by_id = {
            row["record_id"]: row for row in document.get("legacy_non_talent_findings") or [] if row.get("record_id")
        }
        base_by_sphere: dict[str, list[dict[str, Any]]] = {sphere_id: [] for sphere_id in sphere_by_id}
        base_source_rows_by_component: dict[str, list[dict[str, Any]]] = {}
        seen_components: set[str] = set()
        for row in document.get("automatic_base_abilities") or []:
            sphere_id = row.get("mapped_canonical_sphere_id")
            projected = _base_ability_row(row)
            component_id = projected.get("base_ability_id")
            base_source_rows_by_component.setdefault(str(component_id), []).append(projected)
            if sphere_id in base_by_sphere and component_id not in seen_components:
                base_by_sphere[sphere_id].append(projected)
                seen_components.add(str(component_id))
        base_package_by_sphere: dict[str, list[dict[str, Any]]] = {sphere_id: [] for sphere_id in sphere_by_id}
        base_package_source_rows_by_component: dict[str, list[dict[str, Any]]] = {}
        seen_package_components: set[str] = set()
        for row in sphere_base_ability_authority:
            sphere_id = row.get("mapped_canonical_sphere_id")
            projected = _base_ability_row(row)
            component_id = str(projected.get("base_ability_id"))
            base_package_source_rows_by_component.setdefault(component_id, []).append(projected)
            if sphere_id in base_package_by_sphere and component_id not in seen_package_components:
                base_package_by_sphere[sphere_id].append(projected)
                seen_package_components.add(component_id)
        if len(base_package_by_sphere) != EXPECTED_SPHERES or any(not rows for rows in base_package_by_sphere.values()):
            raise FoundryError(
                "CANONICAL_SPHERE_BASE_PACKAGE_INVALID",
                "Every canonical Sphere must expose a non-empty source-bound automatic base package.",
                details={"empty_sphere_ids": sorted(sphere_id for sphere_id, rows in base_package_by_sphere.items() if not rows)}, status_code=503,
            )
        loaded = {
            "document": document, "source": document.get("source_authority") or {}, "counts": counts,
            "spheres": spheres, "talents": talents, "sphere_by_id": sphere_by_id,
            "talent_by_id": talent_by_id, "by_sphere": by_sphere, "alias_to_id": alias_to_id,
            "migration_to_id": migration_to_id, "legacy_non_talent_by_id": legacy_non_talent_by_id,
            "insights": insights, "insight_by_id": insight_by_id,
            "base_by_sphere": base_by_sphere, "base_source_rows_by_component": base_source_rows_by_component,
            "base_package_by_sphere": base_package_by_sphere,
            "base_package_source_rows_by_component": base_package_source_rows_by_component,
        }
        self._GLOBAL_DATA_CACHE[cache_key] = loaded
        self._loaded = loaded
        return loaded

    def status(self) -> dict[str, Any]:
        try:
            data = self._load()
        except FoundryError as exc:
            return {"ready": False, "status": "CANONICAL_CATALOG_AUTHORITY_BLOCKED", "error": exc.to_dict()["error"], "canonical_sphere_count": 0, "canonical_talent_count": 0}
        counts = data["counts"]
        return {
            "schema": "TianxiaFactory.CanonicalCatalogAuthorityStatus.v1", "ready": True,
            "status": CANONICAL_STATUS, "compiler_version": data["document"]["compiler_version"],
            "source_corpus_sha256": data["source"]["archive_sha256"], "compendium_sha256": data["source"]["compendium_sha256"],
            "canonical_sphere_count": counts["canonical_spheres"], "canonical_talent_count": counts["canonical_talents"],
            "canonical_membership_count": counts["memberships"], "ordinary_talent_count": counts["ordinary_talents"],
            "restricted_or_secret_talent_count": counts["restricted_or_secret_talents"],
            "background_only_route_count": counts["background_only_routes"], "quarantined_count": counts["quarantined_records"],
            "automatic_base_ability_source_row_count": counts["automatic_base_ability_records"],
            "automatic_base_ability_unique_count": counts["automatic_base_ability_unique_components"],
            "resolved_sphere_base_ability_source_component_count": counts.get("resolved_sphere_base_ability_source_components", 0),
            "resolved_sphere_base_ability_unique_count": counts.get("resolved_sphere_base_ability_unique_components", 0),
            "resolved_sphere_base_ability_sphere_count": counts.get("resolved_sphere_base_ability_spheres", 0),
            "canonical_insight_count": counts.get("canonical_insights", len(data["insights"])),
            "selectable_insight_count": counts.get("selectable_insights", sum(row.get("selectable") is True for row in data["insights"])),
            "insight_source_occurrence_count": counts.get("insight_source_occurrences", sum(len(row.get("source_occurrences") or []) for row in data["insights"])),
            "unresolved_acquisition_talent_count": counts.get("unresolved_acquisition_talents", 0),
            "fencing_alias_target": data["alias_to_id"].get(_normalize_name("Fencing")),
            "harvesting_alias_target": data["alias_to_id"].get(_normalize_name("Harvesting and Gathering")),
            "authority_commitment_sha256": data["document"]["registry_commitment_sha256"],
            "raw_catalog_preserved": True, "owner_projection_ready": True,
        }

    def resolve_sphere_id(self, value: str) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        data = self._load()
        return value if value in data["sphere_by_id"] else data["alias_to_id"].get(_normalize_name(value))

    def resolve_talent_id(self, value: str) -> str | None:
        data = self._load()
        if value in data["talent_by_id"]:
            return value
        migrated = data["migration_to_id"].get(value)
        return migrated if migrated in data["talent_by_id"] else None

    def _sphere_row(self, row: dict[str, Any], *, include_full: bool = False) -> dict[str, Any]:
        data = self._load()
        result = deepcopy(row)
        legacy_package = deepcopy(data["base_by_sphere"].get(row["canonical_sphere_id"], []))
        resolved_package = deepcopy(data["base_package_by_sphere"].get(row["canonical_sphere_id"], []))
        # The historical field remains the compact P1A compatibility surface;
        # the resolved package is the source-bound owner-facing authority for
        # all 85 Spheres.  ``get_sphere`` promotes it into the main field.
        result["automatic_base_abilities"] = resolved_package if include_full else legacy_package
        result["resolved_automatic_base_abilities"] = resolved_package
        result["automatic_component_authority"] = build_sphere_automatic_component_authority(
            row["canonical_sphere_id"],
            resolved_package,
            source_identity={
                "source_path": row["source_provenance"].get("source_path"),
                "source_hash": row["source_provenance"].get("source_file_sha256"),
                "source_anchor": row["source_provenance"].get("source_anchor"),
                "source_record_commitment_sha256": row.get("record_commitment_sha256"),
            },
        )
        result["automatic_base_ability_package"] = deepcopy(row.get("automatic_base_ability_package") or {
            "status": "resolved_source_bound", "component_count": len(resolved_package),
        })
        result["short_description"] = _first_line(row.get("full_description") or "")
        result["source_reference"] = deepcopy(row["source_provenance"])
        result["source_pack"] = row["source_provenance"]["source_pack"]
        result["stable_id"] = row["canonical_sphere_id"]
        result["creator_disposition"] = "selectable_with_prerequisites"
        result["prerequisite_summary"] = "Available when the character satisfies exact canonical build prerequisites."
        if not include_full:
            result.pop("full_description", None)
            result.pop("full_exact_source_text", None)
        return result

    def _talent_row(self, row: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(row)
        result["short_description"] = _first_line(row.get("full_description") or "")
        result["source_reference"] = deepcopy(row["source_provenance"])
        result["acquisition_route"] = deepcopy(row["acquisition_routes"])
        result["selection_disposition"] = "ORDINARY" if row["ordinary_talent"] else "ACCESS_PROVENANCE_REQUIRED"
        result["restriction_status"] = "ordinary" if row["access_category"] == "Open" else "provenance_labeled"
        result["typed_constraints"] = deepcopy(row["typed_prerequisites"])
        result["prerequisite_evaluation_status"] = row["prerequisite_evaluation_status"]
        result["creator_selectability_can_be_evaluated_safely"] = row["creator_selectability_can_be_evaluated_safely"]
        result["unresolved_reason"] = row.get("unresolved_reason")
        return result

    def list_spheres(self, *, q: str | None = None, include_full: bool = False) -> dict[str, Any]:
        data = self._load()
        query = _normalize_name(q or "")
        rows = [
            self._sphere_row(row, include_full=include_full) for row in data["spheres"]
            if not query or query in _normalize_name(row["display_name"]) or any(query in _normalize_name(alias) for alias in row.get("aliases") or [])
        ]
        return {"schema": "TianxiaFactory.CanonicalSphereCollection.v1", "projection": "canonical_owner_facing", "count": len(rows), "records": rows}

    def list_talents(self, *, sphere_id: str | None = None, q: str | None = None) -> dict[str, Any]:
        data = self._load()
        resolved = self.resolve_sphere_id(sphere_id) if sphere_id else None
        if sphere_id and not resolved:
            raise FoundryError("CANONICAL_SPHERE_NOT_FOUND", "That Sphere or alias does not resolve to CAT3 canonical authority.", details={"value": sphere_id}, status_code=404)
        ids = data["by_sphere"].get(resolved, []) if resolved else list(data["talent_by_id"])
        query = _normalize_name(q or "")
        rows = [
            self._talent_row(data["talent_by_id"][talent_id]) for talent_id in ids
            if not query or query in _normalize_name(data["talent_by_id"][talent_id]["display_name"] + " " + data["talent_by_id"][talent_id]["full_description"])
        ]
        rows.sort(key=lambda row: (row["owning_canonical_sphere_name"].casefold(), row["minimum_cl"], row["display_name"].casefold(), row["canonical_talent_id"]))
        return {"schema": "TianxiaFactory.CanonicalTalentCollection.v1", "projection": "canonical_owner_facing", "canonical_sphere_id": resolved, "count": len(rows), "records": rows}

    @staticmethod
    def _insight_row(row: dict[str, Any], *, include_full: bool = False) -> dict[str, Any]:
        result = deepcopy(row)
        raw = row.get("raw_source_record") or {}
        full_text = next(
            (str(raw.get(key)) for key in ("full_rules_text", "rules_text", "full_description", "description") if isinstance(raw.get(key), str) and raw.get(key).strip()),
            "",
        )
        result["short_description"] = _first_line(full_text)
        result["full_description"] = full_text
        result["source_reference"] = deepcopy(row.get("source_provenance") or {})
        result["source_prerequisites_text"] = raw.get("source_prerequisites_text") or raw.get("prerequisites") or ""
        result["prerequisite_relations"] = deepcopy(row.get("prerequisites") or [])
        result["source_occurrence_count"] = len(row.get("source_occurrences") or [])
        result["owner_selectable"] = row.get("selectable") is True
        result["selection_disposition"] = "selectable" if row.get("selectable") is True else "retained_reference_only"
        if not include_full:
            result.pop("raw_source_record", None)
            result.pop("full_exact_source_text", None)
        return result

    def list_insights(self, *, q: str | None = None, insight_type: str | None = None, include_full: bool = False) -> dict[str, Any]:
        data = self._load()
        query = _normalize_name(q or "")
        rows = [
            self._insight_row(row, include_full=include_full)
            for row in data["insights"]
            if (not insight_type or row.get("insight_authority_type") == insight_type)
            and (
                not query
                or query in _normalize_name(str(row.get("display_name") or ""))
                or query in _normalize_name(str((row.get("raw_source_record") or {}).get("full_rules_text") or ""))
            )
        ]
        rows.sort(key=lambda row: (str(row.get("insight_authority_type") or "").casefold(), str(row.get("display_name") or "").casefold(), row["canonical_insight_id"]))
        return {"schema": "TianxiaFactory.CanonicalInsightCollection.v1", "projection": "canonical_owner_facing", "count": len(rows), "records": rows}

    def get_insight(self, insight_id: str) -> dict[str, Any]:
        data = self._load()
        row = data["insight_by_id"].get(insight_id)
        if not row:
            raise FoundryError("CANONICAL_INSIGHT_NOT_FOUND", "That Insight is not in CAT3 canonical authority.", details={"insight_id": insight_id}, status_code=404)
        return self._insight_row(row, include_full=True)

    def get_sphere(self, value: str) -> dict[str, Any]:
        data = self._load()
        resolved = self.resolve_sphere_id(value)
        if not resolved:
            raise FoundryError("CANONICAL_SPHERE_NOT_FOUND", "That Sphere or alias does not resolve to CAT3 canonical authority.", details={"value": value}, status_code=404)
        sphere = self._sphere_row(data["sphere_by_id"][resolved], include_full=True)
        sphere["talents"] = [self._talent_row(data["talent_by_id"][talent_id]) for talent_id in data["by_sphere"][resolved]]
        sphere["alias_resolution"] = {"input": value, "canonical_sphere_id": resolved, "canonical_display_name": sphere["display_name"]}
        return sphere

    def get_talent(self, talent_id: str) -> dict[str, Any]:
        data = self._load()
        resolved = self.resolve_talent_id(talent_id)
        if not resolved:
            finding = data["legacy_non_talent_by_id"].get(talent_id)
            if finding:
                raise FoundryError(
                    "CANONICAL_LEGACY_NON_TALENT",
                    "That legacy identifier is preserved for review compatibility but is not a selectable Talent.",
                    details={"talent_id": talent_id, "finding": deepcopy(finding)}, status_code=404,
                )
            raise FoundryError("CANONICAL_TALENT_NOT_FOUND", "That Talent is not in CAT3 canonical authority.", details={"talent_id": talent_id}, status_code=404)
        row = self._talent_row(data["talent_by_id"][resolved])
        row["migration_resolution"] = {"input": talent_id, "canonical_talent_id": resolved}
        return row

    def diagnostics(self) -> dict[str, Any]:
        data = self._load()
        source_rows = [_base_ability_row(row) for row in data["document"]["automatic_base_abilities"]]
        runtime_records = [deepcopy(row) for rows in data["base_by_sphere"].values() for row in rows]
        resolved_records = [deepcopy(row) for rows in data["base_package_by_sphere"].values() for row in rows]
        return {
            "schema": "TianxiaFactory.CanonicalCatalogDiagnostics.v1", "status": self.status(),
            "background_only_routes": deepcopy(data["document"]["background_only_routes"]),
            "quarantined": {"count": len(data["document"]["quarantined_decision_packets"]), "label": "Exact authority decision required — not currently selectable", "decision_packets": deepcopy(data["document"]["quarantined_decision_packets"])},
            "automatic_base_abilities": {
                "source_row_count": len(source_rows), "unique_component_count": len(runtime_records),
                "source_rows": source_rows, "records": runtime_records,
                "aliases": deepcopy(data["document"].get("automatic_base_ability_aliases") or []),
            },
            "resolved_sphere_base_abilities": {
                "source_matrix": deepcopy(data["document"].get("sphere_base_ability_authority_matrix") or {}),
                "source_component_count": len(data["document"].get("sphere_base_ability_authority") or []),
                "resolved_sphere_count": len(data["base_package_by_sphere"]),
                "unique_component_count": len(resolved_records),
                "records": resolved_records,
            },
            "insights": {
                "authority_audit": deepcopy(data["document"].get("insight_authority_audit") or {}),
                "record_count": len(data["insights"]),
                "selectable_count": sum(row.get("selectable") is True for row in data["insights"]),
                "source_occurrence_count": sum(len(row.get("source_occurrences") or []) for row in data["insights"]),
                "records": [self._insight_row(row, include_full=False) for row in data["insights"]],
            },
            "stable_id_migrations": deepcopy(data["document"]["stable_id_migrations"]),
            "legacy_non_talent_findings": deepcopy(data["document"]["legacy_non_talent_findings"]),
            "noncanonical_labels": deepcopy(data["document"]["sphere_aliases_and_noncanonical_labels"]),
        }

    @staticmethod
    def _evidence_matches(
        evidence: Iterable[dict[str, Any]], predicate: dict[str, Any], raw_talent: dict[str, Any],
        *, project_id: str | None, character_id: str | None,
    ) -> bool:
        """Match only records already resolved from the immutable server store."""
        talent_id = raw_talent["canonical_talent_id"]
        for record in evidence:
            if not isinstance(record, dict):
                continue
            targets = record.get("targets") or {}
            if record.get("project_id") != project_id or targets.get("character_id") != character_id:
                continue
            if targets.get("canonical_content_id") != talent_id:
                continue
            if targets.get("catalog_record_commitment_sha256") != raw_talent.get("record_commitment_sha256"):
                continue
            binding_type = targets.get("binding_type")
            binding_id = targets.get("binding_id")
            if not (
                (binding_type == "predicate" and binding_id == predicate.get("predicate_id"))
                or (binding_type == "clause" and binding_id == predicate.get("clause_id"))
            ):
                continue
            if targets.get("issuance_route") not in _ACCEPTED_EVIDENCE_ROUTES:
                continue
            if not all(record.get(field) for field in ("evidence_id", "source_identity", "source_hash", "evidence_hash")):
                continue
            expected = "equipment_authority" if predicate["kind"] == "equipment_or_use_condition" else "talent_acquisition_provenance"
            if (
                record.get("authority_type") == expected
                and record.get("creation_authority") in _ACCEPTED_RESOLVED_CREATION_AUTHORITIES
            ):
                return True
        return False

    def _resolve_evidence_ids(
        self, *, project_id: str | None, evidence_ids: Iterable[str], expected_types: set[str],
    ) -> tuple[dict[str, Any], ...]:
        ids = tuple(evidence_ids)
        if not ids:
            return ()
        if not project_id or self._evidence_resolver is None:
            raise FoundryError(
                "CANONICAL_EVIDENCE_CONTEXT_REQUIRED",
                "Post-creation evidence must resolve through a project-bound authoritative evidence store.",
                status_code=422,
            )
        resolved: list[dict[str, Any]] = []
        for evidence_id in ids:
            if not isinstance(evidence_id, str) or not evidence_id:
                raise FoundryError("CANONICAL_EVIDENCE_ID_INVALID", "Evidence references must be immutable server record IDs.", status_code=422)
            record = self._evidence_resolver(project_id, evidence_id)
            if record.get("authority_type") not in expected_types:
                raise FoundryError(
                    "CANONICAL_EVIDENCE_TYPE_INVALID", "The resolved evidence authority type is not valid for this operation.",
                    details={"evidence_id": evidence_id, "authority_type": record.get("authority_type")}, status_code=422,
                )
            resolved.append(deepcopy(record))
        return tuple(resolved)

    def _evaluate_predicate(self, predicate: dict[str, Any], context: dict[str, Any], raw_talent: dict[str, Any]) -> dict[str, Any]:
        kind = predicate["kind"]
        scope = predicate.get("scope") or "acquisition"
        passed = True
        reason = "Satisfied."
        if kind == "minimum_cl":
            passed = context["target_cl"] >= int(predicate["value"])
            reason = f"Requires Cultivation Level {predicate['value']}+."
        elif kind == "realm":
            required = REALM_ENTRY_CL[str(predicate["value"])]
            passed = context["target_cl"] >= required
            reason = f"Requires {predicate['value']} Realm (CL{required}+)."
        elif kind in {"owning_sphere", "sphere"}:
            passed = predicate["target_id"] in context["acquired_sphere_ids"]
            reason = f"Requires the exact {predicate.get('display_name') or predicate['target_id']} Sphere."
        elif kind == "talent":
            passed = predicate["target_id"] in context["selected_talent_ids"]
            reason = f"Requires prerequisite Talent {predicate.get('display_name') or predicate['target_id']}."
        elif kind == "talent_tag_count":
            actual = int(context["selected_talent_tag_counts"].get(predicate["target_id"], 0))
            required = int(predicate["value"])
            passed = actual >= required
            reason = f"Requires at least {required} selected {predicate.get('display_name') or predicate['target_id']} Talent{'s' if required != 1 else ''}."
        elif kind == "path":
            passed = predicate["target_id"] in context["path_ids"]
            reason = f"Requires Path {predicate.get('display_name') or predicate['target_id']}."
        elif kind == "subpath_or_tradition":
            passed = predicate["target_id"] in context["subpath_or_tradition_ids"]
            reason = f"Requires Subpath/Tradition {predicate.get('display_name') or predicate['target_id']}."
        elif kind == "method":
            passed = predicate["target_id"] in context["method_ids"]
            reason = f"Requires Method {predicate.get('display_name') or predicate['target_id']}."
        elif kind == "foundation_or_feature":
            passed = predicate["target_id"] in context["foundation_or_feature_ids"]
            reason = f"Requires Foundation/feature {predicate.get('display_name') or predicate['target_id']}."
        elif kind == "structural_authority":
            if scope == "use_condition":
                passed = True
                reason = "Exact use/execution structure is preserved outside acquisition gating."
            else:
                passed = predicate["target_id"] in context["structural_authority_ids"]
                reason = f"Requires exact structural authority {predicate.get('display_name') or predicate['target_id']}."
        elif kind == "equipment_or_use_condition":
            if scope == "use_condition":
                passed = True
                reason = "Use/execution condition is preserved and does not gate acquisition."
            else:
                passed = self._evidence_matches(
                    context["equipment_evidence"], predicate, raw_talent,
                    project_id=context["project_id"], character_id=context["character_id"],
                )
                reason = predicate.get("owner_reason") or "Requires exact equipment evidence."
        elif kind == "acquisition_provenance":
            initial = context["initial_creation_authority"] is _INITIAL_CREATION_AUTHORITY
            passed = self._evidence_matches(
                context["acquisition_evidence"], predicate, raw_talent,
                project_id=context["project_id"], character_id=context["character_id"],
            ) or initial
            reason = "Exact acquisition provenance will be issued by the trusted initial-creation workflow." if passed and initial else (predicate.get("owner_reason") or "Requires exact acquisition provenance.")
        elif kind == "unresolved":
            if scope == "use_condition":
                passed = True
                reason = "Unresolved use/execution wording is preserved but does not gate acquisition."
            else:
                passed = False
                reason = predicate.get("owner_reason") or f"Unresolved exact authority phrase: {predicate.get('value')}"
        return {
            "predicate_id": predicate.get("predicate_id"), "kind": kind, "scope": scope,
            "passed": passed, "owner_reason": reason, "target_id": predicate.get("target_id"),
            "resolution_status": predicate.get("resolution_status"),
        }

    def _evaluate_talent(self, raw: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        evaluations: dict[str, dict[str, Any]] = {}
        for predicate in raw["typed_prerequisites"]:
            evaluations[predicate["predicate_id"]] = self._evaluate_predicate(predicate, context, raw)
        implicit_failures = [
            row for predicate_id, row in evaluations.items()
            if predicate_id.startswith("implicit:") and not row["passed"]
        ]
        clause_results: list[dict[str, Any]] = []
        for clause in raw.get("prerequisite_clauses") or []:
            if clause.get("scope") != "acquisition":
                clause_results.append({"clause_id": clause["clause_id"], "scope": clause.get("scope"), "passed": True, "owner_reason": "Use/execution condition retained outside acquisition gating."})
                continue
            alternatives: list[dict[str, Any]] = []
            for alternative in clause.get("alternatives") or []:
                rows = [evaluations[predicate_id] for predicate_id in alternative.get("predicate_ids") or []]
                passed = bool(rows) and all(row["passed"] for row in rows)
                alternatives.append({
                    "alternative_id": alternative["alternative_id"], "passed": passed,
                    "predicate_results": rows,
                    "owner_reason": "All exact predicates satisfied." if passed else next((row["owner_reason"] for row in rows if not row["passed"]), "No resolvable predicate was available."),
                })
            clause_passed = any(row["passed"] for row in alternatives)
            clause_results.append({
                "clause_id": clause["clause_id"], "scope": "acquisition", "passed": clause_passed,
                "alternatives": alternatives,
                "owner_reason": "An authored prerequisite alternative is satisfied." if clause_passed else next((row["owner_reason"] for row in alternatives if not row["passed"]), "Authored prerequisite is unresolved."),
            })
        failed_clauses = [row for row in clause_results if row["scope"] == "acquisition" and not row["passed"]]
        blocking_failures = list(implicit_failures)
        for clause in failed_clauses:
            for alternative in clause.get("alternatives") or []:
                blocking_failures.extend(row for row in alternative.get("predicate_results") or [] if not row["passed"])
        selectable = not implicit_failures and not failed_clauses
        first_failure = implicit_failures[0] if implicit_failures else (failed_clauses[0] if failed_clauses else None)
        return {
            "selectable": selectable,
            "owner_reason": "All exact acquisition prerequisites are satisfied." if selectable else first_failure["owner_reason"],
            "predicate_results": list(evaluations.values()), "clause_results": clause_results,
            "blocking_failures": blocking_failures,
        }

    def creator_projection(
        self, *, target_cl: int, acquired_sphere_ids: Iterable[str] = (), background_sphere_ids: Iterable[str] = (),
        free_talent_grants: dict[str, str] | None = None, ordinary_talent_ids: Iterable[str] = (),
        path_ids: Iterable[str] = (),
        subpath_or_tradition_ids: Iterable[str] = (), method_ids: Iterable[str] = (),
        foundation_or_feature_ids: Iterable[str] = (), character_feature_ids: Iterable[str] = (),
        structural_authority_ids: Iterable[str] = (), equipment_evidence_ids: Iterable[str] = (),
        acquisition_evidence_ids: Iterable[str] = (), existing_talent_ids: Iterable[str] = (),
        project_id: str | None = None, character_id: str | None = None,
        _initial_creation_authority: object | None = None,
    ) -> dict[str, Any]:
        if not isinstance(target_cl, int) or target_cl < 1:
            raise FoundryError("TARGET_CL_INVALID", "Target Cultivation Level must be a positive integer.")
        data = self._load()
        acquired: list[str] = []
        explicit_acquired: set[str] = set()
        background_acquired: set[str] = set()
        for raw in acquired_sphere_ids:
            resolved = self.resolve_sphere_id(raw)
            if not resolved:
                raise FoundryError("CANONICAL_SPHERE_REFERENCE_INVALID", "A selected Sphere or alias does not resolve to CAT3 canonical authority.", details={"value": raw})
            if resolved not in acquired:
                acquired.append(resolved)
            explicit_acquired.add(resolved)
        for raw in background_sphere_ids:
            resolved = self.resolve_sphere_id(raw)
            if not resolved:
                raise FoundryError("CANONICAL_SPHERE_REFERENCE_INVALID", "A selected Sphere or alias does not resolve to CAT3 canonical authority.", details={"value": raw})
            if resolved not in acquired:
                acquired.append(resolved)
            background_acquired.add(resolved)
        free: dict[str, str] = {}
        for raw_sphere, raw_talent in (free_talent_grants or {}).items():
            sphere_id = self.resolve_sphere_id(raw_sphere)
            talent_id = self.resolve_talent_id(raw_talent)
            if not sphere_id or not talent_id:
                raise FoundryError("FREE_SPHERE_TALENT_INVALID", "A free Sphere Talent grant requires canonical or migrated IDs.", details={"sphere": raw_sphere, "talent": raw_talent})
            free[sphere_id] = talent_id
        ordinary = [self.resolve_talent_id(value) or value for value in ordinary_talent_ids]
        existing = [self.resolve_talent_id(value) or value for value in existing_talent_ids]
        if len(ordinary) != len(set(ordinary)):
            raise FoundryError("ORDINARY_TALENT_DUPLICATE_SELECTION", "An ordinary learned Talent cannot be submitted more than once.")
        if set(free.values()).intersection(ordinary):
            raise FoundryError("TALENT_ACQUISITION_ROUTE_DOUBLE_COUNT", "A free Sphere Talent cannot also consume an ordinary Talent slot.")
        selected_ids = set(existing).union(free.values()).union(ordinary)
        selected_talent_tag_counts: dict[str, int] = {}
        for selected_id in selected_ids:
            selected_talent = data["talent_by_id"].get(selected_id)
            if selected_talent is None:
                continue
            for tag in selected_talent.get("tags") or []:
                tag_id = f"tag:{_normalize_name(tag).replace(' ', '_')}"
                selected_talent_tag_counts[tag_id] = selected_talent_tag_counts.get(tag_id, 0) + 1
        equipment_evidence = self._resolve_evidence_ids(
            project_id=project_id, evidence_ids=equipment_evidence_ids, expected_types={"equipment_authority"},
        )
        acquisition_evidence = self._resolve_evidence_ids(
            project_id=project_id, evidence_ids=acquisition_evidence_ids,
            expected_types={"talent_acquisition_provenance"},
        )
        context = {
            "target_cl": target_cl, "acquired_sphere_ids": set(acquired), "selected_talent_ids": selected_ids,
            "selected_talent_tag_counts": selected_talent_tag_counts,
            "path_ids": set(path_ids), "subpath_or_tradition_ids": set(subpath_or_tradition_ids),
            "method_ids": set(method_ids), "foundation_or_feature_ids": set(foundation_or_feature_ids).union(character_feature_ids),
            "structural_authority_ids": set(structural_authority_ids).union(character_feature_ids),
            "equipment_evidence": equipment_evidence, "acquisition_evidence": acquisition_evidence,
            "project_id": project_id, "character_id": character_id,
            "initial_creation_authority": _initial_creation_authority,
        }
        dispositions: list[dict[str, Any]] = []
        for raw in data["talents"]:
            talent_id = raw["canonical_talent_id"]
            sphere_id = raw["owning_canonical_sphere_id"]
            evaluation = self._evaluate_talent(raw, context)
            selectable = evaluation["selectable"]
            reason = evaluation["owner_reason"]
            disposition = "selectable_now" if selectable else "locked_by_prerequisite"
            failed_kinds = [row["kind"] for row in evaluation["blocking_failures"]]
            if "minimum_cl" in failed_kinds or "realm" in failed_kinds:
                disposition = "locked_by_minimum_cl"
            elif "unresolved" in failed_kinds:
                disposition = "locked_by_unresolved_prerequisite"
                reason = next(
                    (
                        row["owner_reason"]
                        for row in evaluation["blocking_failures"]
                        if row["kind"] == "unresolved" and not row["passed"]
                    ),
                    reason,
                )
            elif "owning_sphere" in failed_kinds or "sphere" in failed_kinds:
                disposition = "locked_by_sphere"
            elif "talent" in failed_kinds:
                disposition = "locked_by_prerequisite_talent"
            route = "free_sphere_talent_grant" if free.get(sphere_id) == talent_id else ("ordinary_learned_or_trained" if talent_id in ordinary else ("existing" if talent_id in existing else "none"))
            if route == "free_sphere_talent_grant" and not raw["free_sphere_talent_eligible"]:
                selectable, disposition, reason = False, "not_free_grant_eligible", "This access-provenance Talent cannot fill the Sphere's free ordinary Talent grant."
            provenance = None
            if talent_id in selected_ids and raw["acquisition_provenance_required"]:
                initial_pending = _initial_creation_authority is _INITIAL_CREATION_AUTHORITY
                provenance_predicates = [
                    row for row in raw["typed_prerequisites"]
                    if row["kind"] == "acquisition_provenance" and row.get("scope") == "acquisition"
                ]
                matching_evidence_ids = sorted({
                    record["evidence_id"]
                    for predicate in provenance_predicates
                    for record in context["acquisition_evidence"]
                    if self._evidence_matches(
                        (record,), predicate, raw,
                        project_id=context["project_id"], character_id=context["character_id"],
                    )
                })
                recorded = bool(provenance_predicates) and all(
                    self._evidence_matches(
                        context["acquisition_evidence"], predicate, raw,
                        project_id=context["project_id"], character_id=context["character_id"],
                    )
                    for predicate in provenance_predicates
                )
                provenance = {
                    "schema": "TianxiaFactory.AcquisitionProvenance.v1", "canonical_content_id": talent_id,
                    "access_category": raw["access_category"], "acquisition_route": raw["acquisition_routes"][0],
                    "source": "pending-trusted-initial-finalization" if initial_pending else "post-creation-exact-evidence",
                    "recorded": False if initial_pending else recorded,
                    "issuance_route": "initial_character_finalization" if initial_pending else "post_creation_acquisition",
                    "predicate_ids": [row["predicate_id"] for row in provenance_predicates],
                    "evidence_ids": [] if initial_pending else matching_evidence_ids,
                }
            dispositions.append({
                "canonical_talent_id": talent_id, "owning_canonical_sphere_id": sphere_id, "display_name": raw["display_name"],
                "minimum_cl": raw["minimum_cl"], "realm_band": raw["realm_band"], "access_category": raw["access_category"],
                "acquisition_provenance_required": raw["acquisition_provenance_required"], "disposition": disposition,
                "owner_reason": reason, "selectable_now": selectable, "selected_acquisition_route": route,
                "acquisition_provenance": provenance, "prerequisite_evaluation_status": raw["prerequisite_evaluation_status"],
                "creator_selectability_can_be_evaluated_safely": raw["creator_selectability_can_be_evaluated_safely"],
                "prerequisite_evaluation": evaluation,
                "short_description": _first_line(raw["full_description"]), "full_description": raw["full_description"],
                "source_reference": deepcopy(raw["source_provenance"]), "acquisition_route": deepcopy(raw["acquisition_routes"]),
            })
        disposition_by_id = {row["canonical_talent_id"]: row for row in dispositions}
        errors: list[dict[str, Any]] = []
        for sphere_id in acquired:
            talent_id = free.get(sphere_id)
            if not talent_id:
                if sphere_id in background_acquired and sphere_id not in explicit_acquired:
                    # Background route Talents are authenticated separately and
                    # never consume a free ordinary-Talent grant.
                    continue
                errors.append({"code": "FREE_SPHERE_TALENT_REQUIRED", "sphere_id": sphere_id, "message": "Each acquired Sphere requires one owner-selected free ordinary Talent."})
                continue
            talent = data["talent_by_id"].get(talent_id)
            if not talent or talent["owning_canonical_sphere_id"] != sphere_id:
                errors.append({"code": "FREE_SPHERE_TALENT_WRONG_SPHERE", "sphere_id": sphere_id, "talent_id": talent_id, "message": "The free Talent must belong to the acquired Sphere."})
            elif not disposition_by_id[talent_id]["selectable_now"]:
                errors.append({"code": "FREE_SPHERE_TALENT_NOT_SELECTABLE", "sphere_id": sphere_id, "talent_id": talent_id, "message": disposition_by_id[talent_id]["owner_reason"]})
        for talent_id in ordinary:
            if talent_id not in data["talent_by_id"]:
                errors.append({"code": "ORDINARY_TALENT_NOT_CANONICAL", "talent_id": talent_id, "message": "The ordinary Talent is not canonical."})
            elif not disposition_by_id[talent_id]["selectable_now"]:
                errors.append({"code": "ORDINARY_TALENT_NOT_SELECTABLE", "talent_id": talent_id, "message": disposition_by_id[talent_id]["owner_reason"]})
        automatic = [deepcopy(row) for sphere_id in acquired for row in data["base_package_by_sphere"].get(sphere_id, [])]
        accounting = {
            "automatic_base_abilities": automatic, "automatic_base_ability_count": len(automatic),
            "automatic_base_ability_package": "resolved_source_bound_sphere_packages",
            "legacy_automatic_base_ability_source_row_count": len(data["document"].get("automatic_base_abilities") or []),
            "legacy_automatic_base_ability_unique_component_count": len({row.get("runtime_component_id") for row in data["document"].get("automatic_base_abilities") or []}),
            "automatic_base_abilities_counted_as_talent_choices": 0,
            "free_sphere_talent_grants": [{"sphere_id": sphere_id, "talent_id": talent_id, "ordinary_slot_cost": 0, "training_slot_cost": 0} for sphere_id, talent_id in sorted(free.items())],
            "free_sphere_talent_grant_count": len(free), "ordinary_talent_ids": ordinary,
            "ordinary_talent_count": len(ordinary), "ordinary_talent_cost_count": len(ordinary),
            "total_distinct_talent_ids": len(set(free.values()).union(ordinary)), "double_count_detected": False,
            "acquisition_provenance": [row["acquisition_provenance"] for row in dispositions if row["acquisition_provenance"]],
        }
        projection_basis = {
            "target_cl": target_cl, "acquired": acquired, "free": free, "ordinary": ordinary, "existing": existing,
            "paths": sorted(context["path_ids"]), "subpaths": sorted(context["subpath_or_tradition_ids"]),
            "methods": sorted(context["method_ids"]), "foundations": sorted(context["foundation_or_feature_ids"]),
            "equipment_evidence_ids": sorted(record["evidence_id"] for record in context["equipment_evidence"]),
            "acquisition_evidence_ids": sorted(record["evidence_id"] for record in context["acquisition_evidence"]),
            "accounting": accounting, "errors": errors,
        }
        return {
            "schema": "TianxiaFactory.CanonicalCreatorProjection.v1", "ready": not errors,
            "target_cl": target_cl, "target_realm_band": _realm_for_cl(target_cl),
            "acquired_canonical_sphere_ids": acquired,
            "sphere_dispositions": [{
                "canonical_sphere_id": row["canonical_sphere_id"], "display_name": row["display_name"],
                "disposition": "selected" if row["canonical_sphere_id"] in acquired else "selectable_with_prerequisites",
                "owner_reason": "Selected for this character." if row["canonical_sphere_id"] in acquired else "Available when exact build prerequisites are satisfied.",
                "automatic_base_ability_count": len(data["base_package_by_sphere"].get(row["canonical_sphere_id"], [])),
                "canonical_talent_count": row["talent_count"],
            } for row in data["spheres"]],
            "talent_dispositions": dispositions, "grant_accounting": accounting,
            "validation_errors": errors, "projection_sha256": sha256_json(projection_basis),
        }

    def creator_projection_for_initial_creation(self, **kwargs: Any) -> dict[str, Any]:
        """Trusted server-only projection used by the normal creation service."""
        if any(key in kwargs for key in ("equipment_evidence_ids", "acquisition_evidence_ids")):
            raise FoundryError(
                "INITIAL_CREATION_EVIDENCE_REFERENCE_FORBIDDEN",
                "Initial creation issues provenance; it does not accept client evidence as authority.", status_code=422,
            )
        return self.creator_projection(**kwargs, _initial_creation_authority=_INITIAL_CREATION_AUTHORITY)

    def validate_grant_plan_for_initial_creation(self, **kwargs: Any) -> dict[str, Any]:
        projection = self.creator_projection_for_initial_creation(**kwargs)
        return self._validated_grant_plan(projection)

    @staticmethod
    def _validated_grant_plan(projection: dict[str, Any]) -> dict[str, Any]:
        if not projection["ready"]:
            raise FoundryError("CANONICAL_CREATOR_GRANT_PLAN_INVALID", "The canonical Sphere/Talent grant plan is incomplete or illegal.", details={"errors": projection["validation_errors"]}, status_code=422)
        selected = {row["talent_id"] for row in projection["grant_accounting"]["free_sphere_talent_grants"]}.union(projection["grant_accounting"]["ordinary_talent_ids"])
        return {
            "schema": "TianxiaFactory.CanonicalGrantPlan.v1", "ready": True,
            "target_cl": projection["target_cl"], "target_realm_band": projection["target_realm_band"],
            "acquired_canonical_sphere_ids": deepcopy(projection["acquired_canonical_sphere_ids"]),
            "selected_sphere_dispositions": [deepcopy(row) for row in projection["sphere_dispositions"] if row["canonical_sphere_id"] in projection["acquired_canonical_sphere_ids"]],
            "selected_talent_dispositions": [deepcopy(row) for row in projection["talent_dispositions"] if row["canonical_talent_id"] in selected],
            "grant_accounting": deepcopy(projection["grant_accounting"]), "validation_errors": [],
            "projection_sha256": projection["projection_sha256"],
        }

    def validate_grant_plan(self, **kwargs: Any) -> dict[str, Any]:
        return self._validated_grant_plan(self.creator_projection(**kwargs))

    def owner_projection_for_character(self, grant_plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": "TianxiaFactory.CanonicalCharacterGrantProjection.v1", "status": "READY",
            "automatic_base_abilities": deepcopy(grant_plan["grant_accounting"]["automatic_base_abilities"]),
            "free_sphere_talent_grants": deepcopy(grant_plan["grant_accounting"]["free_sphere_talent_grants"]),
            "ordinary_talent_ids": deepcopy(grant_plan["grant_accounting"]["ordinary_talent_ids"]),
            "acquisition_provenance": deepcopy(grant_plan["grant_accounting"]["acquisition_provenance"]),
            "cost_accounting": {"automatic_base_ability_cost": 0, "free_sphere_talent_grant_cost": 0, "ordinary_talent_cost": grant_plan["grant_accounting"]["ordinary_talent_cost_count"]},
            "projection_sha256": grant_plan["projection_sha256"],
        }
