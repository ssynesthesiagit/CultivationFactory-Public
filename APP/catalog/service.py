from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from copy import deepcopy
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from contracts.canonical import normalize_core_catalog_record
from contracts.registry import SchemaRegistry, ContractValidationError
from content_packs.membership import create_direct_install_receipt, verify_pack_seal
from security.integrity import IntegrityService

from app.core import (
    APP_VERSION,
    FACTORY_VERSION,
    GM_SCREEN_VERSION,
    CORE_PACK_ID,
    CORE_PACK_VERSION,
    Database,
    FoundryError,
    canonical_json,
    sha256_file,
    sha256_json,
    utcnow,
)

ALLOWED_AUTHORITIES = {
    "canonical",
    "published-extension",
    "reference-only",
    "deprecated",
    "unresolved",
    "test-only",
}

PROJECT_SCHEMA_VERSION = "TianxiaFoundry.CharacterProject.v1"
CATALOG_SCHEMA_VERSION = "TianxiaFoundry.RulesCatalogRecord.v1"
TRUSTED_EXTENSION_STATES = {"trusted_signed", "human_trusted_exact_archive"}
HISTORICAL_LOCK_STATES = {"published", "superseded", "retired"}
_SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$")
BACKGROUND_PACK_ID = "tianxia.core.backgrounds.origins"
BACKGROUND_PACK_VERSION = "0.6.0"
CAT3_AUTHORITY_PATH = Path(__file__).resolve().parents[1] / "catalog_authority" / "cat3" / "generated" / "catalog_authority.v1.json"
C1A_TYPED_AUTHORITY_PATH = Path(__file__).with_name("typed_authority") / "C1A_Canonical_Typed_Authority_Pack_v1.json"


def _exact_pack_version_matches(version: str, version_range: str) -> bool:
    """Match the deliberately small, fail-closed Content Pack range grammar.

    Pack lock closure currently needs exact versions.  Supporting an
    unreviewed subset of npm/PEP-440 syntax here would turn an unfamiliar
    constraint into an accidental allow, so only ``==x.y.z`` and a bare exact
    semver are accepted.
    """
    constraint = version_range.strip()
    expected = constraint[2:].strip() if constraint.startswith("==") else constraint
    if not _SEMVER.fullmatch(expected):
        raise ValueError(version_range)
    return version == expected


def _natural_version_key(value: str) -> tuple[tuple[int, Any], ...]:
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token.casefold())
        for token in re.findall(r"[0-9]+|[A-Za-z]+", value)
    )


def _foundry_version_matches(version: str, version_range: str) -> bool:
    """Recognize the exact/one-sided ranges emitted by current pack tooling."""
    constraint = version_range.strip()
    if constraint.startswith("=="):
        return version == constraint[2:].strip()
    if constraint.startswith(">="):
        minimum = constraint[2:].strip()
        if not minimum:
            raise ValueError(version_range)
        return _natural_version_key(version) >= _natural_version_key(minimum)
    if constraint and not any(char in constraint for char in "<>=!~,* "):
        return version == constraint
    raise ValueError(version_range)


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _string_list(value: Any) -> list[str]:
    out: list[str] = []
    for item in _as_list(value):
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            for key in ("canonical_id", "record_id", "target_id", "id", "dependency_id"):
                if isinstance(item.get(key), str) and item[key].strip():
                    out.append(item[key].strip())
                    break
    return list(dict.fromkeys(out))


def _summary(raw: dict[str, Any], keys: tuple[str, ...] = ()) -> str:
    for key in keys + (
        "summary",
        "prose_summary",
        "overview",
        "identity",
        "full_rules_text",
        "description",
        "use_as",
    ):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:8000]
        if isinstance(value, dict):
            return canonical_json(value)[:8000]
    return ""


def _first_line(value: str) -> str:
    return next((line.strip() for line in value.splitlines() if line.strip()), "")


def _source_anchor(record_id: str, index: int | None = None) -> str:
    return f"record:{record_id}" if index is None else f"record:{record_id}:index:{index}"


def _minimum_cl(raw: dict[str, Any]) -> int | None:
    for key in ("minimum_cl", "granted_at_cl", "cl", "source_cl"):
        value = raw.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, dict):
            for sub in ("minimum_cl", "base", "normal", "default"):
                if isinstance(value.get(sub), int):
                    return value[sub]
    return None


def _name_key(value: str) -> str:
    """Compare printed rule names without weakening their stored spelling."""
    folded = unicodedata.normalize("NFKD", value).replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z0-9]+", "", folded.casefold())


def _rule_slug(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z0-9]+", "_", folded.casefold()).strip("_")


def _normalize_record(
    *,
    record_id: str,
    content_type: str,
    display_name: str,
    source_path: str,
    source_hash: str,
    raw: dict[str, Any],
    pack_id: str = CORE_PACK_ID,
    pack_version: str = CORE_PACK_VERSION,
    authority: str = "canonical",
    publication_state: str = "published",
    source_anchor: str | None = None,
    summary: str = "",
    dependencies: Iterable[str] = (),
    acquisition_channels: Iterable[str] = (),
    unresolved_notes: Iterable[str] = (),
    selected_authority: bool = True,
) -> dict[str, Any]:
    if authority not in ALLOWED_AUTHORITIES:
        raise ValueError(authority)
    deps = list(dict.fromkeys(x for x in dependencies if isinstance(x, str) and x))
    channels = list(dict.fromkeys(x for x in acquisition_channels if isinstance(x, str) and x)) or [
        "catalog-defined"
    ]
    normalized = {
        "schema_version": "TianxiaFoundry.CatalogProjection.v1",
        "record_id": record_id,
        "content_type": content_type,
        "display_name": display_name,
        "pack_id": pack_id,
        "pack_version": pack_version,
        "authority": authority,
        "publication_state": publication_state,
        "source": {
            "path": source_path,
            "anchor": source_anchor or _source_anchor(record_id),
            "source_hash": source_hash,
        },
        "summary": summary,
        "minimum_cl": _minimum_cl(raw),
        "realm": raw.get("realm") if isinstance(raw.get("realm"), str) else None,
        "prerequisites": raw.get("prerequisites", []),
        "acquisition_channels": channels,
        "grants": raw.get("grants", []),
        "execution_records": raw.get("execution_templates")
        or raw.get("execution_records")
        or raw.get("mechanics")
        or raw.get("components")
        or [],
        "compatibility": raw.get("compatibility", {}),
        "dependencies": deps,
        "supersedes": raw.get("supersedes") or raw.get("superseded_by"),
        "unresolved_normalization_notes": list(unresolved_notes),
        "raw_record": raw,
    }
    normalized["record_hash"] = sha256_json({k: v for k, v in normalized.items() if k != "record_hash"})
    normalized["selected_authority"] = selected_authority
    return normalized


class CoreCatalogImporter:
    """Read-only importer for the structured authority surfaces in HF05ZVK-R1H."""

    def __init__(self, factory_root: Path):
        self.factory_root = factory_root.resolve()
        self.rules_root = self.factory_root / "09_RULES"
        if not (self.factory_root / "FACTORY_MANIFEST.json").exists():
            raise FoundryError(
                "FACTORY_ROOT_INVALID",
                "The selected directory is not the expected extracted Factory root.",
                details={"factory_root": str(self.factory_root)},
            )

    def _typed_authority_pack(self) -> dict[str, Any]:
        pack = _json(C1A_TYPED_AUTHORITY_PATH)
        seal = pack.get("seal_sha256")
        unsigned = {k: v for k, v in pack.items() if k != "seal_sha256"}
        if not isinstance(seal, str) or sha256_json(unsigned) != seal:
            raise FoundryError("TYPED_AUTHORITY_PACK_SEAL_INVALID", "The C1A typed authority pack seal does not match its canonical content.")
        for record_id, entry in pack.get("records", {}).items():
            source = entry.get("source") or {}
            source_path = self.factory_root / str(source.get("path", ""))
            if not source_path.is_file() or sha256_file(source_path) != source.get("source_hash"):
                raise FoundryError("TYPED_AUTHORITY_SOURCE_HASH_MISMATCH", "A C1A typed authority source hash does not match the authenticated Factory corpus.", details={"record_id": record_id, "source": source})
        return pack

    def _apply_typed_authority(self, records: Iterable[dict[str, Any]], *, supplemental_pack_id: str = CORE_PACK_ID, supplemental_pack_version: str = CORE_PACK_VERSION, emit_supplemental: bool = True) -> Iterable[dict[str, Any]]:
        pack = self._typed_authority_pack()
        entries = pack.get("records", {})
        seen: set[str] = set()
        for record in records:
            rid = record["record_id"]
            entry = entries.get(rid)
            is_cat3 = str((record.get("raw_record") or {}).get("compiler_version", "")).startswith("CAT3-P1")
            if entry:
                catalog_source = record.get("source") or {}
                authority_source = entry.get("source") or {}
                source_matches = (
                    catalog_source.get("path") == authority_source.get("path")
                    and catalog_source.get("source_hash") == authority_source.get("source_hash")
                    and (is_cat3 or catalog_source.get("anchor") == authority_source.get("anchor"))
                )
                if not source_matches:
                    raise FoundryError("TYPED_AUTHORITY_SOURCE_BINDING_MISMATCH", "The typed authority entry is not bound to the exact canonical catalog source.", details={"record_id": rid, "catalog_source": record.get("source"), "authority_source": entry.get("source")})
                record = deepcopy(record)
                compatibility = deepcopy(record.get("compatibility") or {})
                compatibility.setdefault("factory", {})["stage2_authority"] = deepcopy(entry["stage2_authority"])
                record["compatibility"] = compatibility
                record["raw_record"] = deepcopy(record.get("raw_record") or {})
                record["raw_record"]["compatibility"] = deepcopy(compatibility)
                # C1A is a sealed official design-time normalization for only
                # these exact source-bound records. Promote this bounded slice
                # to selectable published authority without changing any other
                # catalog record or parsing prose at runtime.
                record["authority"] = "canonical"
                record["publication_state"] = "published"
                record["selected_authority"] = True
                record["unresolved_normalization_notes"] = []
                allowed_channels = entry["stage2_authority"].get("allowed_channels") or []
                if allowed_channels:
                    record["acquisition_channels"] = list(allowed_channels)
                record["record_hash"] = sha256_json({k: v for k, v in record.items() if k not in {"record_hash", "selected_authority"}})
                seen.add(rid)
            elif record.get("content_type") == "path_feature" and isinstance(record.get("minimum_cl"), int):
                record = deepcopy(record)
                compatibility = deepcopy(record.get("compatibility") or {})
                compatibility.setdefault("factory", {})["stage2_authority"] = {
                    "authority_complete": True,
                    "allowed_kinds": ["level_advance"],
                    "allowed_channels": ["level-advance"],
                    "minimum_cl": record["minimum_cl"],
                    "level_talent_capacity": 1,
                    "trained_choice_capacity": 3,
                    "rule_id": f"catalog.{rid}.path-progression.v1",
                }
                record["compatibility"] = compatibility
                record["raw_record"] = deepcopy(record.get("raw_record") or {})
                record["raw_record"]["compatibility"] = deepcopy(compatibility)
                record["record_hash"] = sha256_json({k: v for k, v in record.items() if k not in {"record_hash", "selected_authority"}})
                seen.add(rid)
            elif is_cat3:
                raw = record.get("raw_record") or {}
                content_type = record.get("content_type")
                stage2_authority: dict[str, Any] | None = None
                if content_type == "sphere":
                    stage2_authority = {
                        "authority_complete": True,
                        "allowed_kinds": [
                            "sect_trial_sphere_acquisition",
                            "ai_bootstrap_sphere_acquisition",
                            "sphere_training_attempt",
                        ],
                        "allowed_channels": [
                            "sect-trial-cl1-sphere",
                            "ai-bootstrap-free-cl1-sphere",
                            "known-source-training",
                        ],
                        "rule_id": f"cat3.{rid}.sphere-acquisition.v1",
                    }
                elif content_type == "talent" and raw.get("creator_selectability_can_be_evaluated_safely") is True:
                    stage2_authority = {
                        "authority_complete": True,
                        "allowed_kinds": [
                            "sect_trial_talent_acquisition",
                            "ai_bootstrap_talent_acquisition",
                            "level_talent_acquisition",
                            "talent_training_attempt",
                            "new_sphere_bonus_talent_acquisition",
                        ],
                        "allowed_channels": [
                            "sect-trial-cl1-level-talent",
                            "ai-bootstrap-free-cl1-talent",
                            "level-choice",
                            "known-source-training",
                            "new-sphere-bonus",
                        ],
                        "sphere_id": raw.get("owning_canonical_sphere_id"),
                        "minimum_cl": raw.get("minimum_cl"),
                        "access_category": raw.get("access_category", "Open"),
                        "acquisition_provenance_predicate_ids": [
                            p["predicate_id"]
                            for p in raw.get("typed_prerequisites", [])
                            if isinstance(p, dict)
                            and p.get("scope") == "acquisition"
                            and p.get("kind") == "acquisition_provenance"
                            and isinstance(p.get("predicate_id"), str)
                        ],
                        "rule_id": f"cat3.{rid}.talent-acquisition.v1",
                    }
                    if (
                        raw.get("acquisition_provenance_required") is True
                        and not stage2_authority["acquisition_provenance_predicate_ids"]
                    ):
                        stage2_authority["acquisition_provenance_predicate_ids"] = [
                            f"implicit:{rid}:acquisition_provenance"
                        ]
                if stage2_authority:
                    record = deepcopy(record)
                    compatibility = deepcopy(record.get("compatibility") or {})
                    compatibility.setdefault("factory", {})["stage2_authority"] = stage2_authority
                    record["compatibility"] = compatibility
                    record["raw_record"] = deepcopy(raw)
                    record["raw_record"]["compatibility"] = deepcopy(compatibility)
                    if content_type == "talent":
                        predicates = [
                            p for p in raw.get("typed_prerequisites", [])
                            if isinstance(p, dict)
                            and p.get("scope") == "acquisition"
                            and p.get("resolution_status") == "resolved"
                            and isinstance(p.get("target_id"), str)
                            and p.get("kind") in {"talent", "path", "subpath_or_tradition", "method", "foundation_or_feature", "character_feature"}
                        ]
                        # The Stage-2 relation contract is conjunctive. Only
                        # publish relations from authored clauses with one
                        # alternative; OR clauses remain governed by the shared
                        # canonical evaluator and are not flattened here.
                        clause_alternatives = {
                            clause_id: {
                                p.get("alternative_id")
                                for p in predicates
                                if p.get("clause_id") == clause_id
                            }
                            for clause_id in {
                                p.get("clause_id") for p in predicates if p.get("clause_id")
                            }
                        }
                        record["prerequisites"] = [
                            {"operator": "requires", "target_id": p["target_id"]}
                            for p in predicates
                            if not p.get("clause_id")
                            or len(clause_alternatives[p.get("clause_id")]) == 1
                        ]
                    record["record_hash"] = sha256_json({k: v for k, v in record.items() if k not in {"record_hash", "selected_authority"}})
                seen.add(rid)
            yield record
        if not emit_supplemental:
            return
        for rid, entry in sorted(entries.items()):
            supplemental = entry.get("supplemental_record")
            if not supplemental or rid in seen:
                continue
            raw = {"compatibility": {"factory": {"stage2_authority": deepcopy(entry["stage2_authority"])}}}
            yield _normalize_record(
                record_id=rid,
                content_type=supplemental["content_type"],
                display_name=supplemental["display_name"],
                source_path=entry["source"]["path"],
                source_hash=entry["source"]["source_hash"],
                source_anchor=entry["source"]["anchor"],
                raw=raw,
                pack_id=supplemental_pack_id,
                pack_version=supplemental_pack_version,
                summary=supplemental.get("summary", ""),
                dependencies=supplemental.get("dependencies", []),
                acquisition_channels=entry["stage2_authority"].get("allowed_channels", []) or entry["stage2_authority"].get("allowed_kinds", []) or ["grant-only"],
            )

    def iter_records(self) -> Iterable[dict[str, Any]]:
        base = list(self._paths()) + list(self._subpaths()) + list(self._cat3_talents_and_spheres()) + list(self._foundations()) + list(self._items()) + list(self._methods()) + list(self._insights()) + list(self._reference_sources())
        yield from self._apply_typed_authority(base)

    def source_inventory_hash(self) -> str:
        paths = [
            self.rules_root / "RULES_SOURCE_MANIFEST.json",
            self.rules_root / "CANON_AUTHORITY_MANIFEST_P2A.json",
            self.rules_root / "Indexes/Canonical_Talent_Catalog.json",
            CAT3_AUTHORITY_PATH,
            C1A_TYPED_AUTHORITY_PATH,
            self.rules_root / "Foundation_Runtime/Authoritative_Foundations_v0_4B.json",
            self.rules_root / "Items/ItemCatalog_R2.json",
            self.rules_root / "Indexes/Cultivation_Methods_AI_Index_v0_1.json",
            self.rules_root / "Indexes/Paths/Tianxia_Path_Index_Master_P2A.json",
            self.rules_root / "Indexes/Subpaths/Tianxia_Subpath_Tradition_Index_Master_P2B.json",
            self.rules_root / "Source_Text/Insights/Tianxia_Central_Cultivation_Insights_AI_Reference_R4.json",
        ]
        inventory: dict[str, str] = {}
        for source_path in paths:
            try:
                key = str(source_path.relative_to(self.factory_root))
            except ValueError:
                key = f"runtime_authority/{source_path.name}"
            inventory[key] = sha256_file(source_path)
        return sha256_json(inventory)

    def iter_background_records(self) -> Iterable[dict[str, Any]]:
        yield from self._apply_typed_authority(list(self._origins()) + list(self._backgrounds()), supplemental_pack_id=BACKGROUND_PACK_ID, supplemental_pack_version=BACKGROUND_PACK_VERSION, emit_supplemental=False)

    def background_source_inventory_hash(self) -> str:
        paths = [
            self.rules_root / "Source_Text/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md",
            self.rules_root / "Source_Text/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md",
        ]
        return sha256_json({str(p.relative_to(self.factory_root)): sha256_file(p) for p in paths})

    def _cat3_talents_and_spheres(self) -> Iterable[dict[str, Any]]:
        """Project the compiled CAT3 registry; never parse Markdown at runtime."""
        authority = _json(CAT3_AUTHORITY_PATH)
        source = authority["source_authority"]
        for sphere in authority["spheres"]:
            yield _normalize_record(
                record_id=sphere["canonical_sphere_id"],
                content_type="sphere",
                display_name=sphere["display_name"],
                source_path=source["compendium_path"],
                source_hash=source["compendium_sha256"],
                source_anchor=sphere["source_provenance"]["source_anchor"],
                raw={
                    **deepcopy(sphere),
                    "authority_coverage": {"disposition": "cat3_compiled"},
                    "authority_summary": {"status": "CAT3_COMPILED", "stable_id": sphere["canonical_sphere_id"]},
                },
                summary=_first_line(sphere.get("full_description") or ""),
                dependencies=[],
                acquisition_channels=["sphere-acquisition"],
            )
        for talent in authority["talents"]:
            yield _normalize_record(
                record_id=talent["canonical_talent_id"],
                content_type="talent",
                display_name=talent["display_name"],
                source_path=source["compendium_path"],
                source_hash=source["compendium_sha256"],
                source_anchor=talent["source_provenance"]["source_anchor"],
                raw={
                    **deepcopy(talent),
                    "authority_coverage": {"disposition": "cat3_compiled"},
                    "authority_summary": {"status": "CAT3_COMPILED", "stable_id": talent["canonical_talent_id"]},
                    "summary": _first_line(talent.get("full_description") or ""),
                    "minimum_cl": talent["minimum_cl"],
                },
                summary=_first_line(talent.get("full_description") or ""),
                dependencies=[talent["owning_canonical_sphere_id"]],
                acquisition_channels=deepcopy(talent["acquisition_routes"]),
            )
        role_to_content_type = {
            "path_expression": "sphere_path_expression",
            "sphere_base_ability": "sphere_base_ability",
            "cultivation_insight": "sphere_cultivation_insight",
            "variant_expression": "sphere_variant_expression",
            "structural_label": "sphere_source_structure",
            "sphere_rule": "sphere_rule",
            "sphere_route_anchor": "sphere_route_anchor",
            "unresolved_candidate": "unresolved_talent_candidate",
            "unresolved_source_heading": "unresolved_talent_candidate",
            "descriptive_or_unclassified": "sphere_source_structure",
        }
        for finding in authority["legacy_non_talent_findings"]:
            role = finding["source_role"]
            raw = {
                **deepcopy(finding),
                "compiler_version": authority["compiler_version"],
                "r6_6_5_source_role": role,
                "r6_6_5_source_role_reason": finding["source_role_reason"],
                "r6_6_5_source_citation": deepcopy(finding["source_citation"]),
                "r6_6_5_selectable_talent": False,
            }
            yield _normalize_record(
                record_id=finding["record_id"],
                content_type=role_to_content_type.get(role, "sphere_source_structure"),
                display_name=finding["display_name"],
                source_path=finding["source_path"],
                source_hash=finding["source_hash"],
                source_anchor=finding["source_anchor"],
                raw=raw,
                authority="unresolved" if role.startswith("unresolved") else "reference-only",
                publication_state="reference-only",
                summary=finding["source_role_reason"],
                dependencies=[],
                acquisition_channels=["reference-only"],
                unresolved_notes=[finding["source_role_reason"]] if role.startswith("unresolved") else [],
                selected_authority=False,
            )

    def _paths(self) -> Iterable[dict[str, Any]]:
        rel = "09_RULES/Indexes/Paths/Tianxia_Path_Index_Master_P2A.json"
        path = self.factory_root / rel
        data = _json(path)
        source_hash = sha256_file(path)
        for raw in data.get("paths", []):
            rid = raw["canonical_id"]
            yield _normalize_record(
                record_id=rid,
                content_type="path",
                display_name=raw["display_name"],
                source_path=rel,
                source_hash=source_hash,
                raw=raw,
                summary=_summary(raw, ("display_name",)),
                dependencies=_string_list(raw.get("dependencies")),
                acquisition_channels=["path-selection"],
            )
        for detailed_name in (
            "body_refining.path_index.p2a.json",
            "qi_cultivation.path_index.p2a.json",
            "spirit_awakening.path_index.p2a.json",
        ):
            p = self.rules_root / "Indexes/Paths" / detailed_name
            d = _json(p)
            h = sha256_file(p)
            relp = str(p.relative_to(self.factory_root)).replace("\\", "/")
            for raw in d.get("features", []):
                rid = raw["canonical_id"]
                yield _normalize_record(
                    record_id=rid,
                    content_type="path_feature",
                    display_name=raw.get("display_name", rid),
                    source_path=relp,
                    source_hash=h,
                    raw=raw,
                    summary=_summary(raw, ("effective_rules_text", "source_rules_text")),
                    dependencies=_string_list(raw.get("shared_rule_id"))
                    + _string_list(raw.get("dependencies")),
                    acquisition_channels=["path-progression"],
                )
                for component in raw.get("components", []) if isinstance(raw.get("components"), list) else []:
                    if not isinstance(component, dict):
                        continue
                    cid = component.get("canonical_id") or component.get("component_id")
                    if not isinstance(cid, str):
                        continue
                    yield _normalize_record(
                        record_id=cid,
                        content_type="path_feature_component",
                        display_name=component.get("display_name") or component.get("name") or cid,
                        source_path=relp,
                        source_hash=h,
                        raw=component,
                        summary=_summary(component, ("rules_text", "effect")),
                        dependencies=[rid],
                        acquisition_channels=["path-feature-component"],
                    )

    def _subpaths(self) -> Iterable[dict[str, Any]]:
        rel = "09_RULES/Indexes/Subpaths/Tianxia_Subpath_Tradition_Index_Master_P2B.json"
        path = self.factory_root / rel
        data = _json(path)
        h = sha256_file(path)
        for raw in data.get("entries", []):
            rid = raw["canonical_id"]
            option_type = str(raw.get("option_type", "subpath")).lower()
            ctype = "tradition" if "tradition" in option_type else "subpath"
            deps = [raw.get("owning_path_id")] + _string_list(raw.get("linked_procedure_modules"))
            yield _normalize_record(
                record_id=rid,
                content_type=ctype,
                display_name=raw.get("display_name", rid),
                source_path=rel,
                source_hash=h,
                raw=raw,
                summary=_summary(raw, ("identity",)),
                dependencies=[x for x in deps if isinstance(x, str)],
                acquisition_channels=["subpath-selection" if ctype == "subpath" else "tradition-selection"],
            )
            for fp in raw.get("feature_progression", []) if isinstance(raw.get("feature_progression"), list) else []:
                if not isinstance(fp, dict):
                    continue
                cl = fp.get("cl")
                features = fp.get("features") or fp.get("feature") or []
                for idx, feature in enumerate(_as_list(features)):
                    if isinstance(feature, dict):
                        fid = feature.get("canonical_id") or feature.get("feature_id")
                        if not fid:
                            fid = f"{rid}.feature.cl{cl}.{idx+1}"
                        name = feature.get("display_name") or feature.get("name") or fid
                        raw_feature = dict(feature)
                    else:
                        name = str(feature)
                        fid = f"{rid}.feature.cl{cl}.{idx+1}"
                        raw_feature = {"name": name, "cl": cl}
                    yield _normalize_record(
                        record_id=fid,
                        content_type=f"{ctype}_feature",
                        display_name=name,
                        source_path=rel,
                        source_hash=h,
                        raw=raw_feature,
                        summary=_summary(raw_feature, ("rules_text", "effect")),
                        dependencies=[rid],
                        acquisition_channels=["subpath-progression"],
                    )

    def _talents_and_spheres(self) -> Iterable[dict[str, Any]]:
        """Retired CAT1 compatibility implementation; it is not a runtime authority.

        CAT3 callers use ``_cat3_talents_and_spheres``. Keeping this fail-closed
        stub boundary makes accidental resurrection of the split-brain manifest
        immediately visible while older source history remains reviewable.
        """
        raise FoundryError(
            "RETIRED_SPHERE_TALENT_AUTHORITY",
            "The CAT1 operational manifest is retired; use the compiled CAT3 authority.",
        )
        # Historical implementation below is intentionally unreachable pending
        # deletion after independent review confirms migration preservation.
        rel = "09_RULES/Indexes/Canonical_Talent_Catalog.json"
        path = self.factory_root / rel
        data = _json(path)
        catalog_hash = sha256_file(path)
        manifest = _json(SPHERE_TALENT_AUTHORITY_PATH)
        if manifest.get("catalog_sha256") != catalog_hash:
            raise FoundryError(
                "SPHERE_TALENT_AUTHORITY_CATALOG_MISMATCH",
                "The Sphere/Talent authority manifest is not bound to this pinned canonical catalog.",
                details={"expected": manifest.get("catalog_sha256"), "actual": catalog_hash},
            )
        compendium_rel = str(manifest.get("compendium_path") or "")
        compendium_path = self.factory_root / compendium_rel
        if not compendium_rel or not compendium_path.is_file():
            raise FoundryError(
                "SPHERE_TALENT_AUTHORITY_SOURCE_MISSING",
                "The pinned Sphere source required by the authority manifest is missing.",
                details={"source_path": compendium_rel},
            )
        compendium_hash = sha256_file(compendium_path)
        if manifest.get("compendium_sha256") != compendium_hash:
            raise FoundryError(
                "SPHERE_TALENT_AUTHORITY_SOURCE_MISMATCH",
                "The Sphere/Talent authority manifest is not bound to the installed pinned Sphere source.",
                details={"expected": manifest.get("compendium_sha256"), "actual": compendium_hash},
            )

        classifications = manifest.get("records") if isinstance(manifest.get("records"), dict) else {}
        coverage = manifest.get("sphere_coverage") if isinstance(manifest.get("sphere_coverage"), dict) else {}
        genuine_by_sphere: dict[str, list[str]] = defaultdict(list)
        emitted_ids: set[str] = set()

        role_content_type = {
            "path_expression": "sphere_path_expression",
            "sphere_base_ability": "sphere_base_ability",
            "cultivation_insight": "sphere_cultivation_insight",
            "variant_expression": "sphere_variant_expression",
            "structural_label": "sphere_source_structure",
            "sphere_rule": "sphere_rule",
            "sphere_route_anchor": "sphere_route_anchor",
            "unresolved_candidate": "unresolved_talent_candidate",
            "unresolved_source_heading": "unresolved_talent_candidate",
            "descriptive_or_unclassified": "sphere_source_structure",
        }
        for raw in data.get("records", []):
            record_id = raw.get("canonical_talent_id")
            if not isinstance(record_id, str):
                continue
            classification = classifications.get(record_id)
            if not isinstance(classification, dict):
                raise FoundryError(
                    "SPHERE_TALENT_AUTHORITY_RECORD_MISSING",
                    "A canonical Talent-candidate row lacks an audited source-role disposition.",
                    details={"record_id": record_id},
                )
            sphere_name = str(raw.get("canonical_source_sphere") or "Unclassified")
            display_name = raw.get("canonical_talent_name") or raw.get("source_talent_name") or record_id
            role = str(classification.get("classification") or "unresolved_candidate")
            source_citation = classification.get("source_citation") if isinstance(classification.get("source_citation"), dict) else None
            raw_projection = dict(raw)
            raw_projection["r6_6_5_source_role"] = role
            raw_projection["r6_6_5_source_role_reason"] = classification.get("reason")
            raw_projection["r6_6_5_source_citation"] = source_citation
            raw_projection["r6_6_5_selectable_talent"] = role == "actual_talent"
            if role == "actual_talent":
                sphere_id = f"tianxia.sphere.{_rule_slug(sphere_name)}"
                dependencies = [sphere_id, *_string_list(raw.get("modifies_basic_action_ids"))]
                source_path = str(source_citation.get("path")) if source_citation else rel
                source_hash = compendium_hash if source_citation else catalog_hash
                source_anchor = (
                    f"line:{source_citation.get('line')}:heading:{_rule_slug(str(source_citation.get('heading') or display_name))}"
                    if source_citation else _source_anchor(record_id)
                )
                yield _normalize_record(
                    record_id=record_id,
                    content_type="talent",
                    display_name=display_name,
                    source_path=source_path,
                    source_hash=source_hash,
                    source_anchor=source_anchor,
                    raw=raw_projection,
                    summary=_summary(raw),
                    dependencies=dependencies,
                    acquisition_channels=["known-sphere-talent-training", "level-talent"],
                )
                genuine_by_sphere[sphere_name].append(record_id)
            else:
                unresolved = [str(classification.get("reason") or "Source role is not an acquirable Talent.")]
                yield _normalize_record(
                    record_id=record_id,
                    content_type=role_content_type.get(role, "unresolved_talent_candidate"),
                    display_name=display_name,
                    source_path=(str(source_citation.get("path")) if source_citation else rel),
                    source_hash=(compendium_hash if source_citation else catalog_hash),
                    source_anchor=(
                        f"line:{source_citation.get('line')}:heading:{_rule_slug(str(source_citation.get('heading') or display_name))}"
                        if source_citation else _source_anchor(record_id)
                    ),
                    raw=raw_projection,
                    summary=_summary(raw),
                    dependencies=[],
                    acquisition_channels=["reference-only"],
                    unresolved_notes=unresolved,
                    authority="unresolved" if role.startswith("unresolved") else "reference-only",
                    publication_state="validated",
                    selected_authority=False,
                )
            if record_id in emitted_ids:
                raise FoundryError(
                    "SPHERE_TALENT_AUTHORITY_DUPLICATE_ID",
                    "The audited catalog projection emitted one stable ID more than once.",
                    details={"record_id": record_id},
                )
            emitted_ids.add(record_id)

        for synthetic in manifest.get("synthesized_talents", []):
            if not isinstance(synthetic, dict):
                continue
            record_id = str(synthetic.get("record_id") or "")
            sphere_name = str(synthetic.get("sphere_name") or "")
            if not record_id or not sphere_name or record_id in emitted_ids:
                raise FoundryError(
                    "SPHERE_TALENT_AUTHORITY_SYNTHETIC_INVALID",
                    "A source-projected Talent has an absent or colliding stable ID.",
                    details={"record_id": record_id, "sphere_name": sphere_name},
                )
            sphere_id = f"tianxia.sphere.{_rule_slug(sphere_name)}"
            raw_projection = {
                "name": synthetic.get("display_name") or record_id,
                "full_rules_text": synthetic.get("raw_source_text") or "",
                "minimum_cl": synthetic.get("minimum_cl"),
                "r6_6_5_source_role": "actual_talent",
                "r6_6_5_selectable_talent": True,
                "r6_6_5_source_citation": {
                    "path": synthetic.get("source_path"),
                    "line": synthetic.get("source_line"),
                    "heading": synthetic.get("source_heading"),
                    "sphere_section": synthetic.get("source_section"),
                },
                "r6_6_5_projection_reason": synthetic.get("reason"),
            }
            yield _normalize_record(
                record_id=record_id,
                content_type="talent",
                display_name=synthetic.get("display_name") or record_id,
                source_path=str(synthetic.get("source_path") or compendium_rel),
                source_hash=compendium_hash,
                source_anchor=f"line:{synthetic.get('source_line')}:heading:{_rule_slug(str(synthetic.get('source_heading') or record_id))}",
                raw=raw_projection,
                summary=str(synthetic.get("summary") or ""),
                dependencies=[sphere_id],
                acquisition_channels=["known-sphere-talent-training", "level-talent"],
            )
            emitted_ids.add(record_id)
            genuine_by_sphere[sphere_name].append(record_id)

        # Preserve the existing canonical Sphere surface. Source-only chapters
        # are audited in the manifest but are not silently added as new choices.
        canonical_spheres = sorted({
            str(raw.get("canonical_source_sphere") or "Unclassified")
            for raw in data.get("records", []) if isinstance(raw, dict)
        })
        for sphere_name in canonical_spheres:
            record_id = f"tianxia.sphere.{_rule_slug(sphere_name)}"
            sphere_coverage = coverage.get(sphere_name) if isinstance(coverage.get(sphere_name), dict) else {}
            talent_ids = sorted(set(genuine_by_sphere.get(sphere_name, [])))
            expected_ids = sorted(set(sphere_coverage.get("selectable_talent_ids") or []))
            if talent_ids != expected_ids:
                raise FoundryError(
                    "SPHERE_TALENT_AUTHORITY_COVERAGE_MISMATCH",
                    "Emitted Talent relationships differ from the audited per-Sphere coverage disposition.",
                    details={"sphere_name": sphere_name, "expected_ids": expected_ids, "actual_ids": talent_ids},
                )
            raw_sphere = {
                "name": sphere_name,
                "talent_ids": talent_ids,
                "authority_coverage": sphere_coverage,
                "authority_summary": manifest.get("summary") or {},
            }
            disposition = str(sphere_coverage.get("disposition") or "source_authority_gap")
            honest_summary = (
                f"Exact source-authorized Talent index for {sphere_name}: {len(talent_ids)} selectable Talent(s); "
                f"coverage disposition {disposition}."
            )
            yield _normalize_record(
                record_id=record_id,
                content_type="sphere",
                display_name=sphere_name,
                source_path=compendium_rel if sphere_coverage.get("source_section") else rel,
                source_hash=compendium_hash if sphere_coverage.get("source_section") else catalog_hash,
                source_anchor=f"sphere-authority:{_rule_slug(sphere_name)}",
                raw=raw_sphere,
                summary=honest_summary,
                dependencies=talent_ids,
                acquisition_channels=["sphere-acquisition"],
                authority="reference-only",
                publication_state="validated",
                unresolved_notes=[
                    "This is a source-backed selection index, not an executable Sphere-mechanics grant."
                ],
            )

    def _origins(self) -> Iterable[dict[str, Any]]:
        rel = "09_RULES/Source_Text/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md"
        path = self.factory_root / rel
        text = path.read_text(encoding="utf-8")
        source_hash = sha256_file(path)
        matches = list(re.finditer(r"(?m)^##\s+(\d+)\.\s+(.+?)\s*$", text))
        if len(matches) != 50:
            raise FoundryError(
                "ORIGIN_INSIGHT_SOURCE_INVALID",
                "The authoritative Origin Insight book did not contain the expected 50 records.",
                details={"source_path": rel, "record_count": len(matches)},
            )
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            name = match.group(2).strip()
            section = text[match.start():end].strip()
            benefit_match = re.search(r"(?m)^\*\*Benefit\.\*\*\s*(.+)$", section)
            if not benefit_match:
                raise FoundryError(
                    "ORIGIN_INSIGHT_SOURCE_INVALID",
                    "An authoritative Origin Insight is missing its Benefit rule.",
                    details={"source_path": rel, "origin_insight": name},
                )
            record_id = f"tianxia.origin_insight.{_rule_slug(name)}"
            raw = {
                "number": int(match.group(1)),
                "name": name,
                "benefit": benefit_match.group(1).strip(),
                "full_rules_text": section,
            }
            yield _normalize_record(
                record_id=record_id,
                content_type="origin_insight",
                display_name=name,
                source_path=rel,
                source_hash=source_hash,
                source_anchor=f"heading:{match.group(1)}-{_rule_slug(name)}",
                raw=raw,
                summary=raw["benefit"],
                acquisition_channels=["origin-insight-selection"],
                pack_id=BACKGROUND_PACK_ID,
                pack_version=BACKGROUND_PACK_VERSION,
            )

    def _backgrounds(self) -> Iterable[dict[str, Any]]:
        rel = "09_RULES/Source_Text/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md"
        path = self.factory_root / rel
        text = path.read_text(encoding="utf-8")
        source_hash = sha256_file(path)

        origin_path = self.rules_root / "Source_Text/Tianxia_PHB_Origin_Insights_v0_4_READABILITY_SELF_CONTAINED.md"
        origin_text = origin_path.read_text(encoding="utf-8")
        origin_id_by_name = {
            _name_key(match.group(2)): f"tianxia.origin_insight.{_rule_slug(match.group(2))}"
            for match in re.finditer(r"(?m)^##\s+(\d+)\.\s+(.+?)\s*$", origin_text)
        }

        summary_spheres: dict[str, list[str]] = {}
        for line in text.splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) != 4 or cells[0] in {"Background", "---"}:
                continue
            summary_spheres[_name_key(cells[0])] = [value.strip() for value in cells[3].split(",") if value.strip()]

        headings = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
        parsed: list[dict[str, Any]] = []
        background_spheres: dict[str, dict[str, Any]] = {}
        background_talents: dict[str, dict[str, Any]] = {}
        problems: list[dict[str, Any]] = []
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            section = text[heading.start():end].strip()
            if "### Background Sphere and Talent" not in section or "### Origin Insight Options" not in section:
                continue
            name = heading.group(1).strip()
            sphere_names = summary_spheres.get(_name_key(name), [])
            sphere_ids = [f"tianxia.background_sphere.{_rule_slug(sphere_name)}" for sphere_name in sphere_names]
            for sphere_name, sphere_id in zip(sphere_names, sphere_ids):
                sphere = background_spheres.setdefault(sphere_id, {"name": sphere_name, "backgrounds": []})
                sphere["backgrounds"].append(name)

            choice_text = section.split("### Background Sphere and Talent", 1)[1].split("### Starting Equipment", 1)[0]
            talent_ids: list[str] = []
            for bullet in re.findall(r"(?m)^-\s+(.+)$", choice_text):
                bold_names = re.findall(r"\*\*(.+?)\*\*", bullet)
                if not bold_names:
                    continue
                explicit_sphere = next((re.sub(r"(?i)\s+sphere\.?$", "", value).strip() for value in bold_names if value.casefold().rstrip(".").endswith(" sphere")), None)
                talent_name = bold_names[-1]
                if explicit_sphere and _name_key(talent_name) == _name_key(explicit_sphere + " Sphere"):
                    continue
                candidate_spheres = [explicit_sphere] if explicit_sphere else sphere_names
                if len(candidate_spheres) != 1 or not candidate_spheres[0]:
                    problems.append({"background": name, "kind": "talent_sphere", "name": talent_name, "spheres": candidate_spheres})
                    continue
                sphere_name = candidate_spheres[0]
                sphere_id = f"tianxia.background_sphere.{_rule_slug(sphere_name)}"
                talent_id = f"tianxia.background_talent.{_rule_slug(sphere_name)}.{_rule_slug(talent_name)}"
                talent = background_talents.setdefault(talent_id, {
                    "name": talent_name,
                    "sphere_name": sphere_name,
                    "sphere_id": sphere_id,
                    "printed_rule": bullet.strip(),
                    "backgrounds": [],
                })
                talent["backgrounds"].append(name)
                talent_ids.append(talent_id)

            origin_text_section = section.split("### Origin Insight Options", 1)[1].split("### Social Hook", 1)[0]
            origin_ids: list[str] = []
            for origin_name in re.findall(r"(?m)^-\s+(.+?)\s*$", origin_text_section):
                origin_id = origin_id_by_name.get(_name_key(origin_name))
                if origin_id:
                    origin_ids.append(origin_id)
                else:
                    problems.append({"background": name, "kind": "origin_insight", "name": origin_name})
            parsed.append({
                "name": name,
                "section": section,
                "sphere_ids": list(dict.fromkeys(sphere_ids)),
                "talent_ids": list(dict.fromkeys(talent_ids)),
                "origin_insight_ids": list(dict.fromkeys(origin_ids)),
            })

        if len(parsed) != 31 or problems:
            raise FoundryError(
                "BACKGROUND_SOURCE_INVALID",
                "The authoritative Background book could not be linked exactly to its Sphere, Talent, and Origin records.",
                details={"source_path": rel, "background_count": len(parsed), "unresolved_links": problems},
            )
        for record_id, raw in sorted(background_spheres.items()):
            raw["backgrounds"] = list(dict.fromkeys(raw["backgrounds"]))
            yield _normalize_record(
                record_id=record_id,
                content_type="background_sphere",
                display_name=raw["name"],
                source_path=rel,
                source_hash=source_hash,
                source_anchor="heading:background-spheres-and-talents",
                raw=raw,
                summary=f"A Background may grant the {raw['name']} sphere at character creation as printed in the authoritative Background book.",
                acquisition_channels=["background-sphere-selection"],
                pack_id=BACKGROUND_PACK_ID,
                pack_version=BACKGROUND_PACK_VERSION,
            )
        for record_id, raw in sorted(background_talents.items()):
            raw["backgrounds"] = list(dict.fromkeys(raw["backgrounds"]))
            yield _normalize_record(
                record_id=record_id,
                content_type="background_talent",
                display_name=f"{raw['name']} ({raw['sphere_name']})",
                source_path=rel,
                source_hash=source_hash,
                source_anchor="heading:background-spheres-and-talents",
                raw=raw,
                summary=raw["printed_rule"],
                dependencies=[raw["sphere_id"]],
                acquisition_channels=["background-talent-selection"],
                pack_id=BACKGROUND_PACK_ID,
                pack_version=BACKGROUND_PACK_VERSION,
            )
        for raw in parsed:
            record_id = f"tianxia.background.{_rule_slug(raw['name'])}"
            dependencies = raw["sphere_ids"] + raw["talent_ids"] + raw["origin_insight_ids"]
            yield _normalize_record(
                record_id=record_id,
                content_type="background",
                display_name=raw["name"],
                source_path=rel,
                source_hash=source_hash,
                source_anchor=f"heading:{_rule_slug(raw['name'])}",
                raw=raw,
                summary=raw["section"],
                dependencies=dependencies,
                acquisition_channels=["background-selection"],
                pack_id=BACKGROUND_PACK_ID,
                pack_version=BACKGROUND_PACK_VERSION,
            )

    def _foundations(self) -> Iterable[dict[str, Any]]:
        rel = "09_RULES/Foundation_Runtime/Authoritative_Foundations_v0_4B.json"
        path = self.factory_root / rel
        data = _json(path)
        h = sha256_file(path)
        for raw in data.get("foundations", []):
            rid = raw["foundation_id"]
            yield _normalize_record(
                record_id=rid,
                content_type="foundation",
                display_name=raw.get("name", rid),
                source_path=rel,
                source_hash=h,
                raw=raw,
                summary=_summary(raw),
                dependencies=_string_list(raw.get("compatibility")),
                acquisition_channels=["foundation-establishment", "foundation-evolution"],
                unresolved_notes=_string_list(raw.get("source_gaps")),
                authority="canonical" if not raw.get("source_gaps") else "unresolved",
                publication_state="published" if not raw.get("source_gaps") else "validated",
            )

    def _items(self) -> Iterable[dict[str, Any]]:
        for filename, key, ctype, id_key in (
            ("ItemCatalog_R2.json", "items", "item", "item_id"),
            ("TreasureSetCatalog_R2.json", "sets", "treasure_set", "set_id"),
        ):
            path = self.rules_root / "Items" / filename
            rel = str(path.relative_to(self.factory_root)).replace("\\", "/")
            data = _json(path)
            h = sha256_file(path)
            for raw in data.get(key, []):
                rid = raw[id_key]
                deps = _string_list(raw.get("set_membership")) + _string_list(raw.get("components"))
                yield _normalize_record(
                    record_id=rid,
                    content_type=ctype,
                    display_name=raw.get("name", rid),
                    source_path=rel,
                    source_hash=h,
                    raw=raw,
                    summary=_summary(raw, ("proper_use",)),
                    dependencies=deps,
                    acquisition_channels=["item-acquisition"],
                )

    def _methods(self) -> Iterable[dict[str, Any]]:
        rel = "09_RULES/Indexes/Cultivation_Methods_AI_Index_v0_1.json"
        path = self.factory_root / rel
        data = _json(path)
        h = sha256_file(path)
        for raw in data.get("methods", []):
            rid = raw["id"]
            execution_known = bool(raw.get("resource_shape") and raw.get("breakthrough_shape"))
            notes = [] if execution_known else ["Method execution template is incomplete in the current structured index."]
            yield _normalize_record(
                record_id=rid,
                content_type="cultivation_method",
                display_name=raw.get("name", rid),
                source_path=rel,
                source_hash=h,
                raw=raw,
                summary=_summary(raw),
                dependencies=[],
                acquisition_channels=["method-acquisition", "method-replacement"],
                unresolved_notes=notes,
                authority="canonical" if execution_known else "unresolved",
                publication_state="published" if execution_known else "validated",
            )

    def _insights(self) -> Iterable[dict[str, Any]]:
        rel = "09_RULES/Source_Text/Insights/Tianxia_Central_Cultivation_Insights_AI_Reference_R4.json"
        path = self.factory_root / rel
        data = _json(path)
        h = sha256_file(path)
        seen: set[str] = set()
        for raw in data.get("records", []):
            rid = raw.get("canonical_id") or raw.get("record_id")
            if not isinstance(rid, str) or rid in seen:
                continue
            seen.add(rid)
            selectable = bool(raw.get("selectable"))
            execution_status = str(raw.get("execution_status", "")).lower()
            resolved = selectable and not any(x in execution_status for x in ("missing", "incomplete", "unresolved"))
            notes = []
            if not selectable:
                notes.append(str(raw.get("nonselectable_reason") or "Record is not selectable in the authority source."))
            if not resolved and selectable:
                notes.append("Execution normalization is not complete enough for publication.")
            yield _normalize_record(
                record_id=rid,
                content_type="cultivation_insight",
                display_name=raw.get("display_name") or raw.get("name") or rid,
                source_path=rel,
                source_hash=h,
                raw=raw,
                summary=_summary(raw),
                dependencies=_string_list(raw.get("rules_dependencies")),
                acquisition_channels=["cultivation-insight-selection"],
                unresolved_notes=notes,
                authority="canonical" if resolved else "unresolved",
                publication_state="published" if resolved else "validated",
            )

    def _reference_sources(self) -> Iterable[dict[str, Any]]:
        rel = "09_RULES/RULES_SOURCE_MANIFEST.json"
        path = self.factory_root / rel
        data = _json(path)
        h = sha256_file(path)
        for idx, raw in enumerate(data.get("files", [])):
            source_path = raw.get("path")
            if not isinstance(source_path, str):
                continue
            rid = "tianxia.source." + re.sub(r"[^a-z0-9]+", ".", source_path.lower()).strip(".")
            yield _normalize_record(
                record_id=rid[:200],
                content_type="source_document",
                display_name=Path(source_path).name,
                source_path=rel,
                source_hash=h,
                source_anchor=_source_anchor(rid[:200], idx),
                raw=raw,
                summary=f"Reference-only source inventory entry for {source_path}.",
                acquisition_channels=["not-selectable"],
                authority="reference-only",
                publication_state="validated",
                selected_authority=False,
            )


class CatalogService:
    def __init__(self, db: Database, *, integrity: IntegrityService | None = None):
        self.db = db
        self.integrity = integrity or IntegrityService.for_database(db)

    def rebuild_core(self, factory_root: Path) -> dict[str, Any]:
        importer = CoreCatalogImporter(factory_root)
        projections = list(importer.iter_records())
        source_hash = importer.source_inventory_hash()
        # The pack hash is bound to the immutable Factory source inventory and the
        # legacy projection hashes, avoiding a circular dependency on record hashes
        # that themselves include the pack hash.
        pack_hash = sha256_json(
            {
                "pack_id": CORE_PACK_ID,
                "version": CORE_PACK_VERSION,
                "source_inventory_hash": source_hash,
                "projection_hashes": sorted(r["record_hash"] for r in projections),
            }
        )
        records = [normalize_core_catalog_record(r, pack_hash=pack_hash) for r in projections]
        registry = SchemaRegistry(self.db.settings.root_dir)
        validation_errors: list[dict[str, Any]] = []
        for record in records:
            report = registry.report(record)
            if not report["valid"]:
                validation_errors.append({"record_id": record.get("record_id"), "diagnostics": report["diagnostics"]})
        if validation_errors:
            raise FoundryError(
                "CORE_CATALOG_CONTRACT_INVALID",
                "One or more canonical core catalog records failed the runtime schema.",
                details=validation_errors[:50],
            )
        supplement_result = self._rebuild_background_supplement(importer, factory_root)
        manifest = {
            "schema_version": "TianxiaFoundry.CorePackProjection.v1",
            "pack_id": CORE_PACK_ID,
            "version": CORE_PACK_VERSION,
            "pack_hash": pack_hash,
            "source_inventory_hash": source_hash,
            "factory_root": str(factory_root),
            "record_count": len(records),
            "canonical_record_schema": "TianxiaFoundry.RulesCatalogRecord.v1",
        }
        counts = Counter()
        unresolved = 0
        by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        projection_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for projection, record in zip(projections, records):
            authority = record["compatibility"]["factory"].get("authority_classification", "unresolved")
            counts[(authority, record["content_type"])] += 1
            notes = record["compatibility"]["factory"].get("unresolved_normalization_notes", [])
            unresolved += int(bool(notes))
            by_id[record["record_id"]].append(record)
            projection_by_key[(record["record_id"], record["record_hash"])] = projection
        build_id = sha256_json(
            {"source_hash": source_hash, "records": sorted((r["record_id"], r["record_hash"]) for r in records)}
        )
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?",
                (CORE_PACK_ID, CORE_PACK_VERSION),
            ).fetchone()
            if existing:
                if existing["pack_hash"] != pack_hash:
                    locked_count = conn.execute(
                        "SELECT COUNT(*) FROM project_content_locks WHERE pack_id=? AND version=?",
                        (CORE_PACK_ID, CORE_PACK_VERSION),
                    ).fetchone()[0]
                    raise FoundryError(
                        "CORE_PACK_VERSION_HASH_CONFLICT",
                        "The canonical core pack ID/version is already bound to different bytes. Publish a new version and install it side-by-side instead of overwriting immutable authority.",
                        details={
                            "pack_id": CORE_PACK_ID,
                            "version": CORE_PACK_VERSION,
                            "installed_pack_hash": existing["pack_hash"],
                            "candidate_pack_hash": pack_hash,
                            "project_lock_count": locked_count,
                        },
                    )
                installed_hashes = {
                    row["record_hash"]
                    for row in conn.execute(
                        "SELECT record_hash FROM catalog_records WHERE pack_id=? AND pack_version=?",
                        (CORE_PACK_ID, CORE_PACK_VERSION),
                    )
                }
                candidate_hashes = {record["record_hash"] for record in records}
                if installed_hashes != candidate_hashes:
                    raise FoundryError(
                        "CORE_PACK_INSTALLATION_INCONSISTENT",
                        "The installed core identity matches, but its catalog rows do not. Refusing a destructive in-place repair; restore the pinned database or publish a new core version.",
                        details={
                            "pack_id": CORE_PACK_ID,
                            "version": CORE_PACK_VERSION,
                            "pack_hash": pack_hash,
                            "installed_record_count": len(installed_hashes),
                            "candidate_record_count": len(candidate_hashes),
                        },
                    )
                verify_pack_seal(
                    conn,
                    pack_id=CORE_PACK_ID,
                    version=CORE_PACK_VERSION,
                    expected_pack_hash=pack_hash,
                    integrity=self.integrity,
                )
                return {
                    "build_id": build_id,
                    "pack_id": CORE_PACK_ID,
                    "pack_version": CORE_PACK_VERSION,
                    "pack_hash": pack_hash,
                    "record_count": len(records),
                    "unresolved_count": unresolved,
                    "canonical_valid_count": len(records),
                    "canonical_invalid_count": 0,
                    "counts": self._counts_to_json(counts),
                    "idempotent": True,
                    "background_supplement": supplement_result,
                }
            conn.execute("DELETE FROM content_packs WHERE pack_id=? AND version=?", (CORE_PACK_ID, CORE_PACK_VERSION))
            conn.execute(
                "INSERT INTO content_packs(pack_id,version,pack_hash,lifecycle_state,authority,installed_path,manifest_json,installed_at) VALUES(?,?,?,?,?,?,?,?)",
                (CORE_PACK_ID, CORE_PACK_VERSION, pack_hash, "published", "canonical", str(factory_root), canonical_json(manifest), utcnow()),
            )
            conn.execute(
                "DELETE FROM catalog_conflicts WHERE record_id IN (SELECT record_id FROM catalog_records WHERE pack_id=? AND pack_version=?)",
                (CORE_PACK_ID, CORE_PACK_VERSION),
            )
            conn.execute(
                "DELETE FROM catalog_records WHERE pack_id=? AND pack_version=?",
                (CORE_PACK_ID, CORE_PACK_VERSION),
            )
            for record in records:
                authority = record["compatibility"]["factory"].get("authority_classification", "unresolved")
                selected = bool(record["compatibility"]["factory"].get("selected_authority", True))
                notes = record["compatibility"]["factory"].get("unresolved_normalization_notes", [])
                projection = projection_by_key[(record["record_id"], record["record_hash"])]
                cur = conn.execute(
                    """INSERT INTO catalog_records(
                        record_id,content_type,display_name,pack_id,pack_version,authority,publication_state,
                        source_path,source_anchor,source_hash,record_hash,minimum_cl,realm,selected_authority,
                        data_json,unresolved_notes_json,raw_projection_json,canonical_schema_version,contract_status
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        record["record_id"], record["content_type"], record["display_name"],
                        record["content_binding"]["pack_id"], record["content_binding"]["pack_version"],
                        authority, record["publication"]["status"], record["source"].get("path", ""),
                        record["source"]["anchor"], record["source"]["source_hash"], record["record_hash"],
                        record["legality"].get("minimum_cl"),
                        record["legality"].get("realm_rules", {}).get("realm"), 1 if selected else 0,
                        canonical_json(record), canonical_json(notes), canonical_json(projection),
                        record["schema_version"], "valid",
                    ),
                )
                row_id = int(cur.lastrowid)
                for dep in record.get("dependencies", []):
                    conn.execute("INSERT INTO catalog_dependencies(source_row_id,dependency_record_id,relation) VALUES(?,?,?)", (row_id, dep, "depends_on"))
                conn.execute(
                    "INSERT INTO canonical_object_validations(object_family,object_key,schema_version,boundary,valid,diagnostics_json,object_hash,validated_at) VALUES(?,?,?,?,?,?,?,?)",
                    ("rules_catalog_record", record["record_id"], record["schema_version"], "catalog_publish", 1, "[]", record["record_hash"], utcnow()),
                )
            for rid, variants in by_id.items():
                unique_hashes = {v["record_hash"] for v in variants}
                if len(unique_hashes) > 1:
                    rows = conn.execute("SELECT row_id,selected_authority FROM catalog_records WHERE record_id=? AND pack_id=? ORDER BY selected_authority DESC,row_id", (rid, CORE_PACK_ID)).fetchall()
                    selected = rows[0]["row_id"] if rows else None
                    for row in rows[1:]:
                        conn.execute("INSERT INTO catalog_conflicts(record_id,selected_row_id,competing_row_id,status,reason,created_at) VALUES(?,?,?,?,?,?)", (rid, selected, row["row_id"], "recorded", "Multiple structured source records disagree.", utcnow()))
            selected_records: list[tuple[str, dict[str, Any]]] = []
            for rid in sorted(by_id):
                variants = sorted(
                    by_id[rid],
                    key=lambda record: (
                        not bool(record["compatibility"]["factory"].get("selected_authority", True)),
                        record["record_hash"],
                    ),
                )
                selected_records.append((f"core-records/{rid}.json", variants[0]))
            create_direct_install_receipt(
                conn,
                pack_id=CORE_PACK_ID,
                version=CORE_PACK_VERSION,
                pack_hash=pack_hash,
                authority="canonical",
                trust_state="trusted_core",
                records=selected_records,
                integrity=self.integrity,
            )
            self._rebuild_fts(conn)
            conn.execute(
                "INSERT OR REPLACE INTO catalog_builds(build_id,created_at,source_hash,record_count,unresolved_count,counts_json) VALUES(?,?,?,?,?,?)",
                (build_id, utcnow(), source_hash, len(records), unresolved, canonical_json(self._counts_to_json(counts))),
            )
        return {"build_id": build_id, "pack_id": CORE_PACK_ID, "pack_version": CORE_PACK_VERSION, "pack_hash": pack_hash, "record_count": len(records), "unresolved_count": unresolved, "canonical_valid_count": len(records), "canonical_invalid_count": 0, "counts": self._counts_to_json(counts), "idempotent": False, "background_supplement": supplement_result}

    def _rebuild_background_supplement(self, importer: CoreCatalogImporter, factory_root: Path) -> dict[str, Any]:
        projections = list(importer.iter_background_records())
        source_hash = importer.background_source_inventory_hash()
        pack_hash = sha256_json({
            "pack_id": BACKGROUND_PACK_ID,
            "version": BACKGROUND_PACK_VERSION,
            "source_inventory_hash": source_hash,
            "projection_hashes": sorted(record["record_hash"] for record in projections),
        })
        records = [normalize_core_catalog_record(record, pack_hash=pack_hash) for record in projections]
        registry = SchemaRegistry(self.db.settings.root_dir)
        errors = [
            {"record_id": record.get("record_id"), "diagnostics": report["diagnostics"]}
            for record in records
            for report in [registry.report(record)]
            if not report["valid"]
        ]
        if errors:
            raise FoundryError(
                "BACKGROUND_SUPPLEMENT_CONTRACT_INVALID",
                "One or more Background or Origin records failed the runtime schema.",
                details=errors[:50],
            )
        manifest = {
            "schema_version": "TianxiaFoundry.BuiltinBackgroundPack.v1",
            "pack_id": BACKGROUND_PACK_ID,
            "version": BACKGROUND_PACK_VERSION,
            "pack_hash": pack_hash,
            "source_inventory_hash": source_hash,
            "factory_root": str(factory_root),
            "record_count": len(records),
            "dependencies": [],
        }
        projection_by_key = {
            (record["record_id"], canonical["record_hash"]): record
            for record, canonical in zip(projections, records)
        }
        with self.db.transaction() as conn:
            existing = conn.execute(
                "SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?",
                (BACKGROUND_PACK_ID, BACKGROUND_PACK_VERSION),
            ).fetchone()
            if existing:
                if existing["pack_hash"] != pack_hash:
                    raise FoundryError(
                        "BACKGROUND_PACK_VERSION_HASH_CONFLICT",
                        "The installed Background rules version is bound to different bytes.",
                        details={"pack_id": BACKGROUND_PACK_ID, "version": BACKGROUND_PACK_VERSION},
                    )
                verify_pack_seal(
                    conn,
                    pack_id=BACKGROUND_PACK_ID,
                    version=BACKGROUND_PACK_VERSION,
                    expected_pack_hash=pack_hash,
                    integrity=self.integrity,
                )
                return {
                    "pack_id": BACKGROUND_PACK_ID,
                    "pack_version": BACKGROUND_PACK_VERSION,
                    "pack_hash": pack_hash,
                    "record_count": len(records),
                    "idempotent": True,
                }
            conn.execute(
                "INSERT INTO content_packs(pack_id,version,pack_hash,lifecycle_state,authority,installed_path,manifest_json,installed_at) VALUES(?,?,?,?,?,?,?,?)",
                (BACKGROUND_PACK_ID, BACKGROUND_PACK_VERSION, pack_hash, "published", "canonical", str(factory_root), canonical_json(manifest), utcnow()),
            )
            for record in records:
                projection = projection_by_key[(record["record_id"], record["record_hash"])]
                authority = record["compatibility"]["factory"].get("authority_classification", "unresolved")
                selected = bool(record["compatibility"]["factory"].get("selected_authority", True))
                notes = record["compatibility"]["factory"].get("unresolved_normalization_notes", [])
                cur = conn.execute(
                    """INSERT INTO catalog_records(
                       record_id,content_type,display_name,pack_id,pack_version,authority,publication_state,
                       source_path,source_anchor,source_hash,record_hash,minimum_cl,realm,selected_authority,
                       data_json,unresolved_notes_json,raw_projection_json,canonical_schema_version,contract_status)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        record["record_id"], record["content_type"], record["display_name"],
                        BACKGROUND_PACK_ID, BACKGROUND_PACK_VERSION, authority, record["publication"]["status"],
                        record["source"].get("path", ""), record["source"]["anchor"], record["source"]["source_hash"],
                        record["record_hash"], record["legality"].get("minimum_cl"),
                        record["legality"].get("realm_rules", {}).get("realm"), 1 if selected else 0,
                        canonical_json(record), canonical_json(notes), canonical_json(projection),
                        record["schema_version"], "valid",
                    ),
                )
                row_id = int(cur.lastrowid)
                for dependency in record.get("dependencies", []):
                    conn.execute(
                        "INSERT INTO catalog_dependencies(source_row_id,dependency_record_id,relation) VALUES(?,?,?)",
                        (row_id, dependency, "depends_on"),
                    )
                conn.execute(
                    "INSERT INTO canonical_object_validations(object_family,object_key,schema_version,boundary,valid,diagnostics_json,object_hash,validated_at) VALUES(?,?,?,?,?,?,?,?)",
                    ("rules_catalog_record", record["record_id"], record["schema_version"], "catalog_publish", 1, "[]", record["record_hash"], utcnow()),
                )
            create_direct_install_receipt(
                conn,
                pack_id=BACKGROUND_PACK_ID,
                version=BACKGROUND_PACK_VERSION,
                pack_hash=pack_hash,
                authority="canonical",
                trust_state="trusted_core",
                records=[(f"background-records/{record['record_id']}.json", record) for record in records],
                integrity=self.integrity,
            )
            self._rebuild_fts(conn)
        return {
            "pack_id": BACKGROUND_PACK_ID,
            "pack_version": BACKGROUND_PACK_VERSION,
            "pack_hash": pack_hash,
            "record_count": len(records),
            "idempotent": False,
        }

    @staticmethod
    def _counts_to_json(counts: Counter) -> dict[str, Any]:
        by_authority: dict[str, int] = Counter()
        by_type: dict[str, int] = Counter()
        for (authority, ctype), count in counts.items():
            by_authority[authority] += count
            by_type[ctype] += count
        return {
            "by_authority": dict(sorted(by_authority.items())),
            "by_content_type": dict(sorted(by_type.items())),
        }

    @staticmethod
    def _rebuild_fts(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM catalog_fts")
        rows = conn.execute("SELECT row_id,record_id,display_name,content_type,data_json FROM catalog_records")
        for row in rows:
            data = json.loads(row["data_json"])
            summary = data.get("summary", "")
            search_text = " ".join(
                [
                    row["record_id"],
                    row["display_name"],
                    row["content_type"],
                    summary,
                    " ".join(data.get("dependencies", [])),
                    canonical_json(data.get("compatibility", {}).get("factory", {}).get("raw_projection", {}))[:10000],
                ]
            )
            conn.execute(
                "INSERT INTO catalog_fts(row_id,record_id,display_name,content_type,summary,search_text) VALUES(?,?,?,?,?,?)",
                (row["row_id"], row["record_id"], row["display_name"], row["content_type"], summary, search_text),
            )

    def status(self) -> dict[str, Any]:
        with self.db.connection() as conn:
            build = conn.execute("SELECT * FROM catalog_builds ORDER BY created_at DESC LIMIT 1").fetchone()
            total = conn.execute("SELECT COUNT(*) FROM catalog_records").fetchone()[0]
            packs = conn.execute("SELECT COUNT(*) FROM content_packs").fetchone()[0]
            unresolved = conn.execute(
                "SELECT COUNT(*) FROM catalog_records WHERE unresolved_notes_json!='[]'"
            ).fetchone()[0]
            return {
                "record_count": total,
                "installed_pack_count": packs,
                "unresolved_count": unresolved,
                "latest_build": dict(build) if build else None,
            }

    @staticmethod
    def _fts_query(q: str) -> str:
        tokens = re.findall(r"[\w.:-]+", q, flags=re.UNICODE)
        return " AND ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)

    def search(
        self,
        *,
        q: str | None = None,
        content_type: str | None = None,
        authority: str | None = None,
        publication_state: str | None = None,
        pack_id: str | None = None,
        pack_version: str | None = None,
        minimum_cl_lte: int | None = None,
        include_test: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        join = ""
        order = "r.display_name COLLATE NOCASE"
        if q and q.strip():
            fts = self._fts_query(q)
            if fts:
                join = "JOIN catalog_fts f ON f.row_id=r.row_id"
                clauses.append("catalog_fts MATCH ?")
                params.append(fts)
                order = "bm25(catalog_fts), r.display_name COLLATE NOCASE"
        for column, value in (
            ("r.content_type", content_type),
            ("r.authority", authority),
            ("r.publication_state", publication_state),
            ("r.pack_id", pack_id),
            ("r.pack_version", pack_version),
        ):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        if minimum_cl_lte is not None:
            clauses.append("(r.minimum_cl IS NULL OR r.minimum_cl<=?)")
            params.append(minimum_cl_lte)
        if not include_test:
            clauses.append("r.authority!='test-only'")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""SELECT r.row_id,r.record_id,r.content_type,r.display_name,r.pack_id,r.pack_version,
                    r.authority,r.publication_state,r.source_path,r.source_anchor,r.source_hash,
                    r.record_hash,r.minimum_cl,r.realm,r.selected_authority,r.unresolved_notes_json
                  FROM catalog_records r {join} {where} ORDER BY {order} LIMIT ? OFFSET ?"""
        params.extend([min(max(limit, 1), 500), max(offset, 0)])
        with self.db.connection() as conn:
            rows = [dict(r) for r in conn.execute(sql, params)]
            for row in rows:
                row["unresolved_notes"] = json.loads(row.pop("unresolved_notes_json"))
            return {"records": rows, "count": len(rows), "offset": offset, "limit": limit}

    def get(self, record_id: str, *, include_all_versions: bool = False) -> dict[str, Any]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT * FROM catalog_records WHERE record_id=?
                   ORDER BY selected_authority DESC,
                            CASE publication_state WHEN 'published' THEN 0 WHEN 'validated' THEN 1 ELSE 2 END,
                            pack_version DESC,row_id""",
                (record_id,),
            ).fetchall()
            if not rows:
                raise FoundryError("CATALOG_RECORD_NOT_FOUND", "No catalog record has that stable ID.", details={"record_id": record_id}, status_code=404)
            variants = [json.loads(r["data_json"]) for r in rows]
            registry = SchemaRegistry(self.db.settings.root_dir)
            for variant in variants:
                report = registry.report(variant, "TianxiaFoundry.RulesCatalogRecord.v1")
                if not report["valid"]:
                    raise FoundryError(
                        "CATALOG_RECORD_CONTRACT_INVALID",
                        "A stored catalog record failed canonical reconstruction validation.",
                        details={"record_id": record_id, "diagnostics": report["diagnostics"]},
                        status_code=500,
                    )
            conflicts = [
                dict(r)
                for r in conn.execute("SELECT * FROM catalog_conflicts WHERE record_id=?", (record_id,))
            ]
            if include_all_versions:
                return {"selected": variants[0], "variants": variants, "conflicts": conflicts}
            # A canonical-object endpoint returns the canonical document without
            # transport metadata. Conflict detail is available through
            # include_all_versions=True and dedicated dependency/conflict views.
            return variants[0]

    def dependencies(self, record_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT d.dependency_record_id,d.relation
                   FROM catalog_dependencies d JOIN catalog_records r ON r.row_id=d.source_row_id
                   WHERE r.record_id=? ORDER BY d.dependency_record_id""",
                (record_id,),
            ).fetchall()
            return {"record_id": record_id, "dependencies": [dict(r) for r in rows]}

    def reverse_dependencies(self, record_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """SELECT DISTINCT r.record_id,r.display_name,r.content_type,d.relation
                   FROM catalog_dependencies d JOIN catalog_records r ON r.row_id=d.source_row_id
                   WHERE d.dependency_record_id=? ORDER BY r.display_name""",
                (record_id,),
            ).fetchall()
            return {"record_id": record_id, "reverse_dependencies": [dict(r) for r in rows]}

    def validate_all_canonical(self) -> dict[str, Any]:
        registry = SchemaRegistry(self.db.settings.root_dir)
        total = valid = invalid = 0
        diagnostics: list[dict[str, Any]] = []
        with self.db.connection() as conn:
            for row in conn.execute("SELECT row_id,record_id,data_json FROM catalog_records ORDER BY row_id"):
                total += 1
                record = json.loads(row["data_json"])
                report = registry.report(record, "TianxiaFoundry.RulesCatalogRecord.v1")
                if report["valid"]:
                    valid += 1
                else:
                    invalid += 1
                    diagnostics.append({"row_id": row["row_id"], "record_id": row["record_id"], "diagnostics": report["diagnostics"]})
        return {"schema_version": "TianxiaFoundry.RulesCatalogRecord.v1", "total": total, "valid": valid, "invalid": invalid, "diagnostics": diagnostics}

    def legal_choices(self, *, content_type: str | None = None, include_test: bool = False) -> list[dict[str, Any]]:
        # Record publication/selection are immutable within-pack metadata.  A
        # Content Pack's mutable lifecycle and immutable trust receipt decide
        # whether those records may be offered to a new/global choice context.
        clauses = [
            "r.publication_state='published'",
            "r.selected_authority=1",
            "p.lifecycle_state='published'",
        ]
        params: list[Any] = []
        if content_type:
            clauses.append("r.content_type=?")
            params.append(content_type)
        authority_clause = """(
            p.authority='canonical'
            OR (p.authority='published-extension' AND receipt.trust_state IN ('trusted_signed','human_trusted_exact_archive'))
        """
        if include_test:
            authority_clause += " OR p.authority='test-only'"
        authority_clause += ")"
        clauses.append(authority_clause)
        with self.db.connection() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    f"""SELECT r.record_id,r.display_name,r.content_type,r.pack_id,r.pack_version,r.record_hash
                         FROM catalog_records r
                         JOIN content_packs p
                           ON p.pack_id=r.pack_id AND p.version=r.pack_version
                         LEFT JOIN content_pack_install_receipts receipt
                           ON receipt.pack_id=p.pack_id AND receipt.version=p.version
                          AND receipt.canonical_content_hash=p.pack_hash
                         WHERE {' AND '.join(clauses)}
                         ORDER BY r.display_name""",
                    params,
                )
            ]

    @staticmethod
    def _effective_catalog_with_conn(
        conn: sqlite3.Connection,
        project_id: str,
        *,
        content_types: set[str] | None = None,
        include_test: bool = False,
        include_replaced: bool = False,
    ) -> dict[str, Any]:
        """Resolve exact project locks without changing process-global authority.

        Foundation replacement packs are overlays on a project lock, not edits to
        the pinned Factory catalog. A replacement suppresses only its exact source
        ``foundation`` row. The replacement pack's ``foundation_family`` records
        remain reference authority and its ``foundation_expression`` records are
        the selectable choices.
        """
        project = conn.execute(
            "SELECT project_id,catalog_build_hash FROM projects WHERE project_id=?",
            (project_id,),
        ).fetchone()
        if not project:
            raise FoundryError("PROJECT_NOT_FOUND", "No character project has that ID.", status_code=404)

        locks = [
            dict(row)
            for row in conn.execute(
                "SELECT pack_id,version,pack_hash FROM project_content_locks WHERE project_id=? ORDER BY pack_id,version",
                (project_id,),
            )
        ]
        lock_set = {(row["pack_id"], row["version"], row["pack_hash"]) for row in locks}
        for lock in locks:
            installed = conn.execute(
                "SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?",
                (lock["pack_id"], lock["version"]),
            ).fetchone()
            if not installed or installed["pack_hash"] != lock["pack_hash"]:
                raise FoundryError(
                    "PROJECT_CONTENT_LOCK_UNAVAILABLE",
                    "An exact project Content Pack lock is missing or has different bytes.",
                    details=lock,
                )

        rows = conn.execute(
            """SELECT r.record_id,r.pack_id,r.pack_version,r.record_hash,r.record_json,
                      p.authority AS locked_pack_authority,
                      p.lifecycle_state AS locked_pack_lifecycle_state,
                      receipt.trust_state AS locked_pack_trust_state
               FROM project_locked_records r
               JOIN project_content_locks l
                 ON l.project_id=r.project_id AND l.pack_id=r.pack_id AND l.version=r.pack_version
               JOIN content_packs p
                 ON p.pack_id=l.pack_id AND p.version=l.version AND p.pack_hash=l.pack_hash
               LEFT JOIN content_pack_install_receipts receipt
                 ON receipt.pack_id=p.pack_id AND receipt.version=p.version
                AND receipt.canonical_content_hash=p.pack_hash
               WHERE r.project_id=?
               ORDER BY r.record_id,r.pack_id,r.pack_version""",
            (project_id,),
        ).fetchall()

        replacement_rows = [
            dict(row)
            for row in conn.execute(
                """SELECT x.*,
                          p.authority AS replacement_pack_authority,
                          p.lifecycle_state AS replacement_pack_lifecycle_state,
                          receipt.trust_state AS replacement_pack_trust_state
                   FROM project_locked_replacements x
                   JOIN project_content_locks l
                     ON l.project_id=x.project_id
                    AND l.pack_id=x.replacement_pack_id
                    AND l.version=x.replacement_pack_version
                    AND l.pack_hash=x.replacement_pack_hash
                   JOIN content_packs p
                     ON p.pack_id=x.replacement_pack_id
                    AND p.version=x.replacement_pack_version
                    AND p.pack_hash=x.replacement_pack_hash
                   LEFT JOIN content_pack_install_receipts receipt
                     ON receipt.pack_id=x.replacement_pack_id
                    AND receipt.version=x.replacement_pack_version
                    AND receipt.canonical_content_hash=x.replacement_pack_hash
                   WHERE x.project_id=?
                   ORDER BY x.source_record_id,x.source_pack_id,x.source_pack_version,x.replacement_id""",
                (project_id,),
            )
        ]

        source_to_replacement: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        applied: list[dict[str, Any]] = []
        for replacement in replacement_rows:
            replacement_authority = replacement["replacement_pack_authority"]
            replacement_trust = replacement["replacement_pack_trust_state"]
            if replacement_authority == "test-only" and not include_test:
                # Test authority can prove resolver behavior but cannot suppress
                # ordinary production choices.
                continue
            trusted_replacement = (
                replacement_authority == "test-only"
                or (
                    replacement_authority == "published-extension"
                    and replacement_trust in {"trusted_signed", "human_trusted_exact_archive"}
                )
            )
            if not trusted_replacement:
                raise FoundryError(
                    "PROJECT_REPLACEMENT_PACK_UNTRUSTED",
                    "A quarantined or untrusted Content Pack cannot suppress canonical Foundation authority.",
                    details={
                        "replacement_pack_id": replacement["replacement_pack_id"],
                        "replacement_pack_version": replacement["replacement_pack_version"],
                        "authority": replacement_authority,
                        "trust_state": replacement_trust,
                    },
                )
            if replacement["replacement_pack_lifecycle_state"] not in {"published", "superseded", "retired"}:
                raise FoundryError(
                    "PROJECT_REPLACEMENT_PACK_NOT_PUBLISHED",
                    "Foundation replacement authority must originate from a published pack; only later retirement/supersession preserves an existing exact lock.",
                    details={
                        "replacement_pack_id": replacement["replacement_pack_id"],
                        "replacement_pack_version": replacement["replacement_pack_version"],
                        "lifecycle_state": replacement["replacement_pack_lifecycle_state"],
                    },
                )
            source_key = (
                replacement["source_record_id"],
                replacement["source_record_hash"],
                replacement["source_pack_id"],
                replacement["source_pack_version"],
                replacement["source_pack_hash"],
            )
            prior = source_to_replacement.get(source_key)
            if prior and (
                prior["target_record_id"], prior["target_record_hash"]
            ) != (
                replacement["target_record_id"], replacement["target_record_hash"]
            ):
                raise FoundryError(
                    "PROJECT_REPLACEMENT_AUTHORITY_CONFLICT",
                    "Two locked Content Packs replace the same exact Foundation authority.",
                    details={"source": list(source_key), "replacement_ids": [prior["replacement_id"], replacement["replacement_id"]]},
                )
            source_lock = (
                replacement["source_pack_id"],
                replacement["source_pack_version"],
                replacement["source_pack_hash"],
            )
            if source_lock not in lock_set:
                raise FoundryError(
                    "PROJECT_REPLACEMENT_SOURCE_NOT_LOCKED",
                    "A Foundation replacement requires the exact source pack lock it was authored against.",
                    details={"replacement_id": replacement["replacement_id"], "source_lock": list(source_lock)},
                )
            source = conn.execute(
                """SELECT record_json FROM project_locked_records
                   WHERE project_id=? AND record_id=? AND record_hash=? AND pack_id=? AND pack_version=? LIMIT 1""",
                (
                    project_id, replacement["source_record_id"], replacement["source_record_hash"],
                    replacement["source_pack_id"], replacement["source_pack_version"],
                ),
            ).fetchone()
            if not source or json.loads(source["record_json"]).get("content_type") != "foundation":
                raise FoundryError(
                    "PROJECT_REPLACEMENT_SOURCE_INVALID",
                    "Replacement source must be the exact locked legacy Foundation record.",
                    details={"replacement_id": replacement["replacement_id"]},
                )
            target = conn.execute(
                """SELECT record_json FROM project_locked_records
                   WHERE project_id=? AND record_id=? AND record_hash=? AND pack_id=? AND pack_version=? LIMIT 1""",
                (
                    project_id, replacement["target_record_id"], replacement["target_record_hash"],
                    replacement["replacement_pack_id"], replacement["replacement_pack_version"],
                ),
            ).fetchone()
            if not target or json.loads(target["record_json"]).get("content_type") != "foundation_expression":
                raise FoundryError(
                    "PROJECT_REPLACEMENT_TARGET_INVALID",
                    "Replacement target must be an exact Foundation Expression owned by the locked replacement pack.",
                    details={"replacement_id": replacement["replacement_id"]},
                )
            source_to_replacement[source_key] = replacement
            applied.append({
                "replacement_id": replacement["replacement_id"],
                "source_record_id": replacement["source_record_id"],
                "source_record_hash": replacement["source_record_hash"],
                "source_pack_id": replacement["source_pack_id"],
                "source_pack_version": replacement["source_pack_version"],
                "source_pack_hash": replacement["source_pack_hash"],
                "target_record_id": replacement["target_record_id"],
                "target_record_hash": replacement["target_record_hash"],
                "replacement_pack_id": replacement["replacement_pack_id"],
                "replacement_pack_version": replacement["replacement_pack_version"],
                "replacement_pack_hash": replacement["replacement_pack_hash"],
                "mode": replacement["mode"],
            })

        records: list[dict[str, Any]] = []
        suppressed: list[dict[str, Any]] = []
        for row in rows:
            pack_authority = row["locked_pack_authority"]
            pack_trust = row["locked_pack_trust_state"]
            trusted_pack = (
                pack_authority == "canonical"
                or (pack_authority == "test-only" and include_test)
                or (
                    pack_authority == "published-extension"
                    and pack_trust in {"trusted_signed", "human_trusted_exact_archive"}
                )
            )
            if not trusted_pack:
                continue
            record = json.loads(row["record_json"])
            binding = record.get("content_binding", {})
            key = (
                record["record_id"], record["record_hash"], binding.get("pack_id"),
                binding.get("pack_version"), binding.get("pack_hash"),
            )
            replacement = source_to_replacement.get(key)
            if replacement and record.get("content_type") == "foundation":
                suppressed.append({
                    "record_id": record["record_id"],
                    "record_hash": record["record_hash"],
                    "replacement_id": replacement["replacement_id"],
                    "target_record_id": replacement["target_record_id"],
                })
                if not include_replaced:
                    continue
            if content_types and record.get("content_type") not in content_types:
                continue
            authority = str(record.get("compatibility", {}).get("factory", {}).get("authority_classification") or pack_authority)
            if not include_test and authority == "test-only":
                continue
            records.append(record)

        applied.sort(key=lambda item: (item["source_record_id"], item["replacement_id"]))
        suppressed.sort(key=lambda item: (item["record_id"], item["record_hash"]))
        records.sort(key=lambda item: (item["record_id"], item["record_hash"]))
        identity = {
            "project_id": project_id,
            "catalog_build_id": project["catalog_build_hash"],
            "content_locks": locks,
            "record_hashes": [record["record_hash"] for record in records],
            "replacements": applied,
        }
        return {
            "schema_version": "TianxiaFoundry.EffectiveProjectCatalog.v1",
            "project_id": project_id,
            "catalog_build_id": project["catalog_build_hash"],
            "content_locks": locks,
            "effective_catalog_hash": sha256_json(identity),
            "records": records,
            "replacements_applied": applied,
            "suppressed_records": suppressed,
        }

    def effective_catalog(
        self,
        project_id: str,
        *,
        content_types: set[str] | None = None,
        include_test: bool = False,
        include_replaced: bool = False,
    ) -> dict[str, Any]:
        with self.db.connection() as conn:
            return self._effective_catalog_with_conn(
                conn,
                project_id,
                content_types=content_types,
                include_test=include_test,
                include_replaced=include_replaced,
            )

    @staticmethod
    def validate_project_lock_set(
        conn: sqlite3.Connection,
        locks: list[dict[str, str]],
        *,
        allow_inactive: bool = False,
        allow_test_fixtures: bool = False,
    ) -> None:
        """Validate the exact, trusted, closed Content Pack authority set."""
        lock_ids = [x["pack_id"] for x in locks]
        if len(lock_ids) != len(set(lock_ids)):
            raise FoundryError(
                "PACK_LOCK_DUPLICATE",
                "A project may lock only one exact version of a Content Pack ID.",
                details={"pack_ids": lock_ids},
            )
        lock_set = {(x["pack_id"], x["version"], x["pack_hash"]) for x in locks}
        locks_by_id = {x["pack_id"]: x for x in locks}
        manifests: dict[str, dict[str, Any]] = {}
        for lock in locks:
            row = conn.execute(
                """SELECT p.lifecycle_state,p.pack_hash,p.authority,p.manifest_json,receipt.trust_state
                   FROM content_packs p
                   LEFT JOIN content_pack_install_receipts receipt
                     ON receipt.pack_id=p.pack_id AND receipt.version=p.version
                    AND receipt.canonical_content_hash=p.pack_hash
                   WHERE p.pack_id=? AND p.version=?""",
                (lock["pack_id"], lock["version"]),
            ).fetchone()
            if not row or row["pack_hash"] != lock["pack_hash"]:
                raise FoundryError("PACK_LOCK_NOT_INSTALLED", "A requested exact Content Pack lock is unavailable.", details=lock)
            lifecycle_state = row["lifecycle_state"]
            authority = row["authority"]
            trust_state = row["trust_state"]
            explicit_test_pack = authority == "test-only" and lock["pack_id"].upper().startswith("TEST")
            if allow_inactive:
                # Historical production imports require a released lifecycle.
                # Explicit TEST-only fixture packs may also round-trip while
                # validated; their authority and TEST namespace keep them out
                # of every ordinary production-choice path.
                lifecycle_allowed = (
                    lifecycle_state in HISTORICAL_LOCK_STATES
                    or (
                        allow_test_fixtures
                        and explicit_test_pack
                        and lifecycle_state == "validated"
                    )
                )
            elif explicit_test_pack:
                # Validated TEST-only packs are deliberate local fixtures. They
                # remain outside production authority.
                lifecycle_allowed = lifecycle_state in {"validated", "published"}
            else:
                lifecycle_allowed = lifecycle_state == "published"
            if not lifecycle_allowed:
                raise FoundryError(
                    "PACK_LOCK_LIFECYCLE_INACTIVE",
                    "The exact Content Pack lifecycle is not eligible for this project lock operation.",
                    details={**lock, "lifecycle_state": lifecycle_state, "allow_inactive": allow_inactive},
                )
            trusted_authority = (
                authority == "canonical"
                or explicit_test_pack
                or (authority == "published-extension" and trust_state in TRUSTED_EXTENSION_STATES)
            )
            if not trusted_authority:
                raise FoundryError(
                    "PACK_LOCK_UNTRUSTED",
                    "A project lock requires canonical authority, an explicitly isolated TEST pack, or an immutable trusted extension receipt.",
                    details={**lock, "authority": authority, "trust_state": trust_state},
                )
            try:
                manifest = json.loads(row["manifest_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise FoundryError(
                    "PACK_LOCK_MANIFEST_INVALID",
                    "The installed Content Pack manifest cannot be parsed for lock validation.",
                    details=lock,
                ) from exc
            manifests[lock["pack_id"]] = manifest

            compatibility = manifest.get("compatibility")
            if authority == "published-extension" and not isinstance(compatibility, dict):
                raise FoundryError(
                    "PACK_LOCK_COMPATIBILITY_MISMATCH",
                    "A selected extension has no usable compatibility contract.",
                    details={**lock, "field": "compatibility", "declared": compatibility},
                )
            if authority == "published-extension":
                expected = {
                    "project_schema": PROJECT_SCHEMA_VERSION,
                    "catalog_schema": CATALOG_SCHEMA_VERSION,
                }
                for field, current in expected.items():
                    if compatibility.get(field) != current:
                        raise FoundryError(
                            "PACK_LOCK_COMPATIBILITY_MISMATCH",
                            "A selected extension does not support the active Foundry contract.",
                            details={**lock, "field": field, "required": current, "declared": compatibility.get(field)},
                        )
                producer_targets = compatibility.get("factory_producers") or []
                if producer_targets and FACTORY_VERSION not in producer_targets:
                    raise FoundryError(
                        "PACK_LOCK_COMPATIBILITY_MISMATCH",
                        "A selected extension does not support the active Factory producer.",
                        details={**lock, "field": "factory_producers", "required": FACTORY_VERSION, "declared": producer_targets},
                    )
                consumer_targets = compatibility.get("gm_screen_consumers") or []
                if consumer_targets and GM_SCREEN_VERSION not in consumer_targets:
                    raise FoundryError(
                        "PACK_LOCK_COMPATIBILITY_MISMATCH",
                        "A selected extension does not support the active GM Screen consumer.",
                        details={**lock, "field": "gm_screen_consumers", "required": GM_SCREEN_VERSION, "declared": consumer_targets},
                    )
                foundry_range = compatibility.get("foundry")
                if isinstance(foundry_range, str):
                    try:
                        foundry_matches = _foundry_version_matches(APP_VERSION, foundry_range)
                    except ValueError as exc:
                        raise FoundryError(
                            "PACK_LOCK_VERSION_RANGE_UNSUPPORTED",
                            "The extension uses an unsupported Foundry version range.",
                            details={**lock, "field": "foundry", "version_range": foundry_range},
                        ) from exc
                    if not foundry_matches:
                        raise FoundryError(
                            "PACK_LOCK_COMPATIBILITY_MISMATCH",
                            "A selected extension does not support this Foundry version.",
                            details={**lock, "field": "foundry", "required": APP_VERSION, "declared": foundry_range},
                        )

        # Dependencies are project authority, not machine-global availability:
        # an installed-but-unlocked pack can never satisfy closure.
        for lock in locks:
            manifest = manifests[lock["pack_id"]]
            for dependency in manifest.get("dependencies") or []:
                dependency_id = dependency.get("pack_id")
                selected = locks_by_id.get(dependency_id)
                if selected is None:
                    if dependency.get("optional", False):
                        continue
                    raise FoundryError(
                        "PACK_LOCK_DEPENDENCY_MISSING",
                        "A required Content Pack dependency is not part of the selected exact lock set.",
                        details={**lock, "dependency": dependency},
                    )
                version_range = dependency.get("version_range", "")
                try:
                    matches = _exact_pack_version_matches(selected["version"], version_range)
                except ValueError as exc:
                    raise FoundryError(
                        "PACK_LOCK_VERSION_RANGE_UNSUPPORTED",
                        "The Content Pack dependency uses an unsupported version range; exact ==version locks are required.",
                        details={**lock, "dependency": dependency},
                    ) from exc
                if not matches:
                    raise FoundryError(
                        "PACK_LOCK_DEPENDENCY_VERSION_MISMATCH",
                        "The selected dependency version does not satisfy the exact manifest requirement.",
                        details={**lock, "dependency": dependency, "selected_version": selected["version"]},
                    )
            for conflict in manifest.get("conflicts") or []:
                selected = locks_by_id.get(conflict.get("pack_id"))
                if selected is None:
                    continue
                version_range = conflict.get("version_range")
                if version_range:
                    try:
                        applies = _exact_pack_version_matches(selected["version"], version_range)
                    except ValueError as exc:
                        raise FoundryError(
                            "PACK_LOCK_VERSION_RANGE_UNSUPPORTED",
                            "The Content Pack conflict uses an unsupported version range; exact ==version ranges are required.",
                            details={**lock, "conflict": conflict},
                        ) from exc
                    if not applies:
                        continue
                raise FoundryError(
                    "PACK_LOCK_CONFLICT",
                    "Two selected Content Packs declare an incompatible lock combination.",
                    details={**lock, "conflict": conflict, "selected_conflict": selected},
                )

        selected_record_owners: dict[str, set[str]] = defaultdict(set)
        selected_rows_by_pack: dict[str, list[sqlite3.Row]] = {}
        for lock in locks:
            rows = list(conn.execute(
                "SELECT row_id,record_id FROM catalog_records WHERE pack_id=? AND pack_version=?",
                (lock["pack_id"], lock["version"]),
            ))
            selected_rows_by_pack[lock["pack_id"]] = rows
            for record in rows:
                selected_record_owners[record["record_id"]].add(lock["pack_id"])

        # Native Content Pack records may refer to records owned by another
        # pack.  Resolve those references against the selected exact lock set,
        # never against the machine-global catalog, and require the owning pack
        # to appear in the source manifest's dependency contract.
        for lock in locks:
            manifest = manifests[lock["pack_id"]]
            if manifest.get("schema_version") != "TianxiaFoundry.ContentPackManifest.v1":
                continue
            declared_pack_dependencies = {
                dependency.get("pack_id")
                for dependency in manifest.get("dependencies") or []
                if isinstance(dependency, dict) and isinstance(dependency.get("pack_id"), str)
            }
            for source_record in selected_rows_by_pack[lock["pack_id"]]:
                for dependency in conn.execute(
                    "SELECT dependency_record_id FROM catalog_dependencies WHERE source_row_id=?",
                    (source_record["row_id"],),
                ):
                    dependency_id = dependency["dependency_record_id"]
                    owners = selected_record_owners.get(dependency_id, set())
                    if lock["pack_id"] in owners:
                        continue
                    external_owners = owners - {lock["pack_id"]}
                    if not external_owners:
                        installed_candidates = [
                            {"pack_id": row["pack_id"], "version": row["pack_version"]}
                            for row in conn.execute(
                                "SELECT DISTINCT pack_id,pack_version FROM catalog_records WHERE record_id=? ORDER BY pack_id,pack_version",
                                (dependency_id,),
                            )
                        ]
                        raise FoundryError(
                            "PACK_LOCK_RECORD_DEPENDENCY_MISSING",
                            "A catalog-record dependency does not resolve inside the selected exact lock set.",
                            details={
                                **lock,
                                "source_record_id": source_record["record_id"],
                                "dependency_record_id": dependency_id,
                                "installed_candidates": installed_candidates,
                            },
                        )
                    declared_owners = external_owners & declared_pack_dependencies
                    if not declared_owners:
                        raise FoundryError(
                            "PACK_LOCK_RECORD_DEPENDENCY_UNDECLARED",
                            "An external catalog-record dependency is supplied by a selected pack that the source manifest did not declare.",
                            details={
                                **lock,
                                "source_record_id": source_record["record_id"],
                                "dependency_record_id": dependency_id,
                                "selected_owner_pack_ids": sorted(external_owners),
                                "declared_dependency_pack_ids": sorted(declared_pack_dependencies),
                            },
                        )
        replacements: dict[tuple[str, str, str, str, str], tuple[str, str]] = {}
        for lock in locks:
            for row in conn.execute(
                """SELECT x.*,p.authority AS replacement_pack_authority,
                          p.lifecycle_state AS replacement_pack_lifecycle_state,
                          receipt.trust_state AS replacement_pack_trust_state
                   FROM catalog_record_replacements x
                   JOIN content_packs p
                     ON p.pack_id=x.replacement_pack_id AND p.version=x.replacement_pack_version
                    AND p.pack_hash=x.replacement_pack_hash
                   LEFT JOIN content_pack_install_receipts receipt
                     ON receipt.pack_id=x.replacement_pack_id AND receipt.version=x.replacement_pack_version
                    AND receipt.canonical_content_hash=x.replacement_pack_hash
                   WHERE x.replacement_pack_id=? AND x.replacement_pack_version=? AND x.replacement_pack_hash=?""",
                (lock["pack_id"], lock["version"], lock["pack_hash"]),
            ):
                trusted_replacement = (
                    row["replacement_pack_authority"] == "test-only"
                    or (
                        row["replacement_pack_authority"] == "published-extension"
                        and row["replacement_pack_trust_state"] in {"trusted_signed", "human_trusted_exact_archive"}
                    )
                )
                if not trusted_replacement:
                    raise FoundryError(
                        "PROJECT_REPLACEMENT_PACK_UNTRUSTED",
                        "A quarantined or untrusted pack cannot replace canonical Foundation authority.",
                        details={
                            "replacement_pack_id": row["replacement_pack_id"],
                            "replacement_pack_version": row["replacement_pack_version"],
                            "authority": row["replacement_pack_authority"],
                            "trust_state": row["replacement_pack_trust_state"],
                        },
                    )
                if not allow_inactive and row["replacement_pack_lifecycle_state"] != "published":
                    raise FoundryError(
                        "PROJECT_REPLACEMENT_PACK_NOT_PUBLISHED",
                        "A new project may apply only a published replacement pack.",
                        details={
                            "replacement_pack_id": row["replacement_pack_id"],
                            "replacement_pack_version": row["replacement_pack_version"],
                            "lifecycle_state": row["replacement_pack_lifecycle_state"],
                        },
                    )
                source_lock = (row["source_pack_id"], row["source_pack_version"], row["source_pack_hash"])
                if source_lock not in lock_set:
                    raise FoundryError(
                        "PROJECT_REPLACEMENT_SOURCE_NOT_LOCKED",
                        "A replacement pack must be locked with the exact source pack it replaces.",
                        details={"replacement_id": row["replacement_id"], "source_lock": list(source_lock)},
                    )
                source = conn.execute(
                    """SELECT content_type FROM catalog_records
                       WHERE record_id=? AND record_hash=? AND pack_id=? AND pack_version=? LIMIT 1""",
                    (row["source_record_id"], row["source_record_hash"], row["source_pack_id"], row["source_pack_version"]),
                ).fetchone()
                target = conn.execute(
                    """SELECT content_type FROM catalog_records
                       WHERE record_id=? AND record_hash=? AND pack_id=? AND pack_version=? LIMIT 1""",
                    (row["target_record_id"], row["target_record_hash"], row["replacement_pack_id"], row["replacement_pack_version"]),
                ).fetchone()
                if not source or source["content_type"] != "foundation":
                    raise FoundryError(
                        "PROJECT_REPLACEMENT_SOURCE_INVALID",
                        "A replacement source must resolve to the exact legacy Foundation row.",
                        details={"replacement_id": row["replacement_id"]},
                    )
                if not target or target["content_type"] != "foundation_expression":
                    raise FoundryError(
                        "PROJECT_REPLACEMENT_TARGET_INVALID",
                        "A replacement target must resolve to a Foundation Expression in the replacement pack.",
                        details={"replacement_id": row["replacement_id"]},
                    )
                key = (
                    row["source_record_id"], row["source_record_hash"], row["source_pack_id"],
                    row["source_pack_version"], row["source_pack_hash"],
                )
                value = (row["target_record_id"], row["target_record_hash"])
                if key in replacements and replacements[key] != value:
                    raise FoundryError(
                        "PROJECT_REPLACEMENT_AUTHORITY_CONFLICT",
                        "Two selected packs provide different replacements for the same exact Foundation.",
                        details={"source": list(key), "targets": [list(replacements[key]), list(value)]},
                    )
                replacements[key] = value
