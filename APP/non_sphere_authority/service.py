from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import unicodedata
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core import Database, FoundryError, canonical_json, sha256_json, utcnow
from contracts.canonical import canonical_record_hash, normalize_core_catalog_record
from catalog_choice_authority import committed_catalog_grant_plan
from .semantic_validator import NonSphereSemanticStateValidator

_TRUSTED_INITIAL_CATALOG_FINALIZATION = object()
_TRUSTED_INITIAL_CREATION_BOUNDARY = object()
_TRUSTED_PROJECT_IMPORT_BOUNDARY = object()


@dataclass(frozen=True, slots=True)
class _InitialCatalogFinalizationContext:
    run_id: str
    project_id: str
    starting_revision: int
    content_lock_hash: str
    typed_choice_snapshot_sha256: str
    phase: str
    candidate_identity: str | None
    _seal: object


def _server_initial_catalog_finalization_context(
    *,
    run_id: str,
    project_id: str,
    starting_revision: int,
    content_lock_hash: str,
    typed_choice_snapshot_sha256: str,
    phase: str = "finalization",
    candidate_identity: str | None = None,
    _authority: object | None = None,
) -> _InitialCatalogFinalizationContext:
    if _authority is not _TRUSTED_INITIAL_CATALOG_FINALIZATION:
        raise FoundryError(
            "NS1R_INITIAL_CATALOG_CONTEXT_FORBIDDEN",
            "Only the server finalization operation can create initial catalog issuance context.",
            status_code=403,
        )
    if phase not in {"scratch_compile", "finalization"}:
        raise FoundryError("NS1R_INITIAL_CATALOG_CONTEXT_PHASE_INVALID", "The server issuance phase is invalid.", status_code=409)
    return _InitialCatalogFinalizationContext(
        run_id=run_id,
        project_id=project_id,
        starting_revision=int(starting_revision),
        content_lock_hash=content_lock_hash,
        typed_choice_snapshot_sha256=typed_choice_snapshot_sha256,
        phase=phase,
        candidate_identity=candidate_identity,
        _seal=_TRUSTED_INITIAL_CATALOG_FINALIZATION,
    )

PATH_ORDER = (
    ("BODY_REFINING", "tianxia.path.body_refining", "Body Refining", "tianxia.resource.stamina", "Stamina"),
    ("QI_CULTIVATION", "tianxia.path.qi_cultivation", "Qi Cultivation", "tianxia.resource.qi", "Qi"),
    ("SPIRIT_AWAKENING", "tianxia.path.spirit_awakening", "Spirit Awakening", "tianxia.resource.resonance", "Resonance"),
)
COMPACT_TO_CANONICAL = {compact: canonical for compact, canonical, *_ in PATH_ORDER}
CANONICAL_TO_COMPACT = {canonical: compact for compact, canonical, *_ in PATH_ORDER}
PATH_NAMES = {canonical: name for _, canonical, name, _, _ in PATH_ORDER}
RESOURCE_BY_PATH = {canonical: {"resource_id": rid, "resource_name": name} for _, canonical, _, rid, name in PATH_ORDER}
REALM_BOUNDARIES = (5, 10, 15, 20)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _unique_strings(values: list[str], *, code: str, field: str) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
        raise FoundryError(code, f"{field} must contain non-empty stable IDs.", details={"field": field})
    if len(values) != len(set(values)):
        raise FoundryError(code, f"Duplicate {field} IDs are not permitted and are never silently normalized.", details={"field": field, "values": values})
    return list(values)


def _norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value)).casefold().replace("’", "'")
    value = re.sub(r"[`*_()]+", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _norm_text(value)).strip("_")


class NonSphereAuthorityService:
    """Shared, fail-closed non-Sphere authority service.

    NS1R-R1 keeps authored Method/Foundation data byte-identical. The service stores
    only character-specific state, AP transactions, invalidations, and adjudication
    evidence. It never stores or consumes the 3,060-row audit as runtime authority.
    """

    STATE_SCHEMA = "Tianxia.NonSphereCharacterState.v1"
    AUTHORITY_STATUS = "NS1R_R2_BOUND_EVIDENCE_AND_PROJECT_PACKAGE_COMPATIBILITY_READY"
    CANONICAL_TO_COMPACT = CANONICAL_TO_COMPACT
    COMPACT_TO_CANONICAL = COMPACT_TO_CANONICAL
    canonical_json = staticmethod(canonical_json)

    def __init__(self, db: Database):
        self.db = db
        self.root = db.settings.root_dir
        self.authority_root = self.root / "non_sphere_authority" / "authority"
        self.identity = _read_json(self.authority_root / "NS1R_AUTHORITY_IDENTITIES.json")
        self._verify_authority_identity()

        method_registry_path = self.authority_root / "Tianxia_Methods_Typed_Registry_v0_6.json"
        registry = _read_json(method_registry_path)
        self.method_registry = registry
        self.method_registry_commitment_sha256 = _hash_file(method_registry_path)
        override_doc = _read_json(self.authority_root / "Exact_Named_Method_Foundation_Overrides_v0_6.json")
        foundation_traits = _read_json(self.authority_root / "Foundation_Trait_Reference_v0_6.json")
        foundation_runtime = _read_json(self.authority_root / "Foundation_Runtime_Authority_v0_4C.json")
        paths_master = _read_json(self.authority_root / "Tianxia_Path_Index_Master_P2A.json")
        subpaths = _read_json(self.authority_root / "Tianxia_Subpath_Tradition_Index_Master_P2B.json")
        backgrounds = _read_json(self.authority_root / "Background_Core_Authority_v1.json")

        self.methods = {row["method_id"]: row for row in registry["methods"]}
        self.overrides = {f"{row['method_id']}::{row['foundation_id']}": row for row in override_doc["overrides"]}
        self.foundation_traits = {row["foundation_id"]: row for row in foundation_traits["foundations"]}
        self.foundations = {row["foundation_id"]: row for row in foundation_runtime["orthodox"]}
        self.theoretical_foundations = list(foundation_runtime["theoretical_chakra"])
        self.paths_master = paths_master
        self.path_profiles = {
            _read_json(self.authority_root / row["index_file"])["canonical_id"]: _read_json(self.authority_root / row["index_file"])
            for row in paths_master["paths"]
        }
        self.subpaths = {row["canonical_id"]: row for row in subpaths["entries"]}
        self.backgrounds = {row["background_id"]: row for row in backgrounds["backgrounds"]}
        self._resolver = self._load_resolver()
        self.authority_snapshot_hash = sha256_json({name: meta["sha256"] for name, meta in sorted(self.identity["files"].items())})

        self.cat2_background_routes = _read_json(self.root / "catalog_authority/cat1/data/background_origin_talent_routes.v1.json")["records"]
        self.cat2_spheres = {row["canonical_sphere_id"]: row for row in _read_json(self.root / "catalog_authority/cat1/data/canonical_spheres.v1.json")["records"]}
        self.background_route_authority = self._build_background_route_authority()
        self.semantic_validator = NonSphereSemanticStateValidator(self)
        self._validate_loaded_authority()

    def _verify_authority_identity(self) -> None:
        if self.identity.get("operative_pairwise_authority_rows") != 0 or self.identity.get("audit_rows_runtime_consumed") is not False:
            raise FoundryError("NS1R_PAIRWISE_AUTHORITY_FORBIDDEN", "The runtime authority identity attempts to enable exhaustive pairwise authority.", status_code=500)
        for name, metadata in self.identity.get("files", {}).items():
            path = self.authority_root / name
            if not path.is_file() or path.resolve().parent != self.authority_root.resolve():
                raise FoundryError("NS1R_AUTHORITY_POINTER_INVALID", "A declared authority file is missing or unsafe.", details={"file": name}, status_code=500)
            if name.startswith("SOURCE_REFERENCES") or "SOURCE_REFERENCES/" in name:
                raise FoundryError("NS1R_SOURCE_REFERENCE_RUNTIME_FORBIDDEN", "Source-reference artifacts cannot be used as runtime authority.", details={"file": name}, status_code=500)
            actual = _hash_file(path)
            if actual != metadata.get("sha256") or path.stat().st_size != metadata.get("size"):
                raise FoundryError("NS1R_AUTHORITY_HASH_MISMATCH", "A declared non-Sphere authority file changed.", details={"file": name, "expected": metadata, "actual_sha256": actual, "actual_size": path.stat().st_size}, status_code=500)

    def _load_resolver(self):
        path = self.authority_root / "open_ended_compatibility_resolver.py"
        spec = importlib.util.spec_from_file_location("tianxia_ns1r_compatibility_resolver", path)
        if spec is None or spec.loader is None:
            raise FoundryError("NS1R_RESOLVER_LOAD_FAILED", "The accepted compatibility resolver could not be loaded.", status_code=500)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _validate_loaded_authority(self) -> None:
        if len(self.methods) != 102 or len(self.overrides) != 22 or len(self.foundations) != 30 or len(self.theoretical_foundations) != 32:
            raise FoundryError("NS1R_AUTHORITY_COUNT_MISMATCH", "The accepted non-Sphere authority counts are incomplete.", details=self.identity.get("counts"), status_code=500)
        if set(self.path_profiles) != set(CANONICAL_TO_COMPACT):
            raise FoundryError("NS1R_PATH_AUTHORITY_MISMATCH", "Exactly the three orthodox Path profiles are required.", details={"paths": sorted(self.path_profiles)}, status_code=500)
        if len(self.subpaths) != 156 or len(self.backgrounds) != 31:
            raise FoundryError("NS1R_CHARACTER_AUTHORITY_COUNT_MISMATCH", "Subpath/tradition or background authority is incomplete.", status_code=500)
        if len(self.cat2_background_routes) != 77:
            raise FoundryError("NS1R_BACKGROUND_ROUTE_COUNT_MISMATCH", "The accepted CAT2 background-only route registry is incomplete.", status_code=500)
        for method in self.methods.values():
            pointer = method.get("foundation_compatibility_authority", {}).get("exact_named_override_registry")
            if pointer != "AUTHORITY/Exact_Named_Method_Foundation_Overrides_v0_6.json":
                raise FoundryError("NS1R_METHOD_AUTHORITY_POINTER_STALE", "A Method declares a stale exact-override authority pointer.", details={"method_id": method["method_id"], "pointer": pointer}, status_code=500)
        expected_repairs = {
            "mud_lotus_dantian_v0_2A": ["Clean-Water Lotus Bath", "Root-and-Silt Circulation", "Humble Bloom Service"],
            "glass_heart_meridian_v0_2A": ["Warm Mirror-Meridian Treatment", "Trusted Witness Truth Rite", "Break the False Image"],
        }
        for foundation_id, expected in expected_repairs.items():
            if self.foundations[foundation_id]["repair_practice_names"] != expected:
                raise FoundryError("NS1R_REPAIR_NORMALIZATION_MISMATCH", "A required Foundation repair practice set is not normalized.", details={"foundation_id": foundation_id}, status_code=500)

    def _build_background_route_authority(self) -> dict[str, dict[str, Any]]:
        by_source: dict[str, list[dict[str, Any]]] = {}
        for route in self.cat2_background_routes:
            by_source.setdefault(_norm_text(route["source_text"]), []).append(route)
        result: dict[str, dict[str, Any]] = {}
        for background_id, background in self.backgrounds.items():
            options: list[dict[str, Any]] = []
            for bullet in background["background_sphere_talent_routes"]["route_bullets"]:
                hits = by_source.get(_norm_text(bullet), [])
                if not hits:
                    # One accepted CAT2 row is intentionally abbreviated to the exact
                    # authored talent name (Iron Courtesy) rather than repeating its
                    # full background bullet. Resolve only when both the stable talent
                    # display name and canonical Sphere are an exact unique match.
                    bullet_norm = _norm_text(bullet)
                    hits = [
                        route
                        for route in self.cat2_background_routes
                        if _norm_text(re.sub(r"\s*\([^)]*\)\s*$", "", route["display_name"])) in bullet_norm
                        and (not route.get("canonical_sphere_name") or _norm_text(route["canonical_sphere_name"]) in bullet_norm)
                    ]
                if len(hits) != 1:
                    raise FoundryError("NS1R_BACKGROUND_ROUTE_AUTHORITY_AMBIGUOUS", "A background bullet did not map to exactly one accepted CAT2 route.", details={"background_id": background_id, "bullet": bullet, "matches": len(hits)}, status_code=500)
                route = deepcopy(hits[0])
                options.append({
                    "background_route_record_id": route["background_route_record_id"],
                    # The route registry names the canonical Sphere. The creator
                    # slot selects the existing Background Sphere projection, so
                    # bind the tuple to that stable choice ID without creating a
                    # second catalog.
                    "background_sphere_choice_id": f"tianxia.background_sphere.{_slug(route.get('canonical_sphere_name') or route.get('canonical_sphere_id') or '')}",
                    "canonical_sphere_id": route.get("canonical_sphere_id"),
                    "background_sphere_name": route.get("canonical_sphere_name"),
                    "background_talent_choice_id": route["background_route_record_id"],
                    "background_talent_display_name": re.sub(r"\s*\([^)]*\)\s*$", "", route["display_name"]),
                    "record_commitment_sha256": route["record_commitment_sha256"],
                    "source_text": route["source_text"],
                })
            insight_options = [
                {"origin_insight_choice_id": f"{background_id}.origin_insight.{_slug(name)}", "display_name": name}
                for name in background["origin_insight"]["suggested_options"]
            ]
            ability_modes = [
                {"ability_grant_mode_id": f"{background_id}.ability_mode.{index + 1}", **deepcopy(mode)}
                for index, mode in enumerate(background["ability_score_grants"]["modes"])
            ]
            result[background_id] = {
                "route_options": options,
                "origin_insight_options": insight_options,
                "ability_grant_modes": ability_modes,
                "equipment_authority_id": f"{background_id}.starting_equipment",
                "skills_authority_id": f"{background_id}.skills",
                "tools_languages_trades_authority_id": f"{background_id}.tools_languages_trades",
            }
        return result

    def authority_status(self) -> dict[str, Any]:
        return {
            "ready": True,
            "status": self.AUTHORITY_STATUS,
            "authority_snapshot_hash": self.authority_snapshot_hash,
            "method_count": len(self.methods),
            "exact_override_count": len(self.overrides),
            "path_count": len(self.path_profiles),
            "subpath_tradition_count": len(self.subpaths),
            "orthodox_foundation_count": len(self.foundations),
            "theoretical_chakra_foundation_count": len(self.theoretical_foundations),
            "background_count": len(self.backgrounds),
            "operative_pairwise_authority_rows": 0,
            "cross_catalog_audit_runtime_consumed": False,
            "compatibility_resolver": "open_ended_provenance_gated_v0_6",
            "semantic_validator": "Tianxia.NonSphereSemanticValidation.v1",
            "ap_allocation_contract": "Tianxia.MethodAPAllocationTransaction.v1",
        }

    def path_catalog(self) -> dict[str, Any]:
        records = []
        for _, canonical, name, _, _ in PATH_ORDER:
            profile = deepcopy(self.path_profiles[canonical])
            records.append({
                "path_id": canonical,
                "compact_path_id": CANONICAL_TO_COMPACT[canonical],
                "display_name": name,
                "path_profile": profile["path_profile"],
                "resource_rules": profile["resource_rules"],
                "progression": profile["progression"],
                "features": profile["features"],
                "source_cl_rules": profile["source_cl_rules"],
                "ap_authority": "Primary Method explicit_ap_grants and typed allocation transaction only",
            })
        return {"schema": "Tianxia.NonSpherePathCatalog.v1", "records": records, "count": 3}

    def method_owner_route_options(self, method: dict[str, Any]) -> list[dict[str, str]]:
        """Project source-backed routes into stable owner-facing provenance types."""
        acquisition = method.get("acquisition") or {}
        routes = [str(value or "").strip() for value in acquisition.get("routes") or [] if str(value or "").strip()]
        if not routes:
            return []
        combined = " ".join([str(acquisition.get("access_tier") or ""), *routes]).casefold()
        definitions = (
            ("PERSONAL_TEACHER", "Personal teacher", ("teacher", "physician", "mentor", "supervised")),
            ("INHERITANCE", "Inheritance", ("inheritance", "lineage", "ancestor", "clan")),
            ("OATH_TRIAL_OR_SERVICE", "Oath, trial, or service", ("oath", "covenant", "trial", "service", "reward")),
        )
        options: list[dict[str, str]] = []
        for route_type, label, keywords in definitions:
            matching = [route for route in routes if any(keyword in route.casefold() for keyword in keywords)]
            if not matching and any(keyword in combined for keyword in keywords):
                matching = list(routes)
            if matching:
                options.append({
                    "choice_id": "route-" + route_type.casefold().replace("_", "-"),
                    "label": label, "description": matching[0], "typed_route": route_type,
                    "source_route_sha256": sha256_json(matching), "requires_explanation": False,
                })
        options.append({
            "choice_id": "route-custom", "label": "Custom", "description": routes[0],
            "typed_route": "CUSTOM_DOCUMENTED_ROUTE", "source_route_sha256": sha256_json(routes),
            "requires_explanation": True,
        })
        return options

    def resolve_initial_method_access(
        self, method_id: str, *, route_choice: str | None, owner_annotation: str | None
    ) -> dict[str, Any]:
        """Generate the exact internal access plan from one server-projected choice."""
        method = self.methods.get(method_id)
        if method is None:
            raise FoundryError("NS1R_METHOD_ID_UNKNOWN", "The selected Method is not available.", details={"method_id": method_id})
        acquisition = method.get("acquisition") or {}
        access_tier = str(acquisition.get("access_tier") or "UNRESOLVED")
        source_reference = {
            "registry_schema": self.method_registry.get("schema"),
            "registry_version": self.method_registry.get("version"),
            "method_record_sha256": sha256_json(method),
            "source_evidence": deepcopy(method.get("source_evidence") or []),
        }
        if self.method_initial_creation_satisfied(method):
            route_type = "PUBLISHED_OPEN_INITIAL_AUTHORITY"
            route_label = "Open sect training"
        else:
            options = self.method_owner_route_options(method)
            selected = next((row for row in options if row["choice_id"] == route_choice), None)
            if selected is None:
                message = (
                    "This Method has no legal learning route for initial character creation."
                    if not options
                    else "Choose how this character learned the selected Method."
                )
                raise FoundryError(
                    "CHARACTER_METHOD_LEARNING_ROUTE_REQUIRED",
                    message,
                    details={"method_id": method_id, "available_choice_count": len(options)},
                )
            if selected.get("requires_explanation") and not str(owner_annotation or "").strip():
                raise FoundryError(
                    "CHARACTER_METHOD_CUSTOM_EXPLANATION_REQUIRED",
                    "Describe the custom learning route for this Method.",
                    details={"method_id": method_id, "route_choice": selected["choice_id"]},
                )
            route_type = selected["typed_route"]
            route_label = selected["label"]
        source_route_sha256 = selected.get("source_route_sha256") if not self.method_initial_creation_satisfied(method) else sha256_json(acquisition.get("routes") or [])
        route_commitment = sha256_json({
            "method_id": method_id,
            "access_tier": access_tier,
            "route_type": route_type,
            "source_route_sha256": source_route_sha256,
        })
        return {
            "schema": "TianxiaFoundry.MethodAccessPlan.v2",
            "method_id": method_id,
            "access_tier": access_tier,
            "route_type": route_type,
            "route_label": route_label,
            "owner_annotation": str(owner_annotation or "").strip(),
            "source_reference": source_reference,
            "source_route_sha256": source_route_sha256,
            "route_commitment_sha256": route_commitment,
            "method_registry_commitment_sha256": self.method_registry_commitment_sha256,
            "status": "COMPLETE_SERVER_AUTHORITY",
        }

    def project_locked_method_catalog_record(self, method_id: str) -> dict[str, Any]:
        """Project one exact registry Method into the locked catalog contract.

        The non-sphere registry is an authenticated authority surface, but it is
        not part of the ordinary HF2 catalog-pack membership.  Exact initial
        Method access therefore needs a deterministic record projection for the
        Stage 2 subject/binding contract.  This projection is intentionally
        narrow: it authorizes only the initial ``method_acquisition`` event and
        remains bound to the registry file and the complete authority snapshot.
        Callers must still prove the project access plan before using it.
        """
        method = self.methods.get(method_id)
        if method is None:
            raise FoundryError(
                "NS1R_METHOD_ID_UNKNOWN",
                "The selected Method is not available in the authenticated registry.",
                details={"method_id": method_id},
            )
        registry_version = str(self.method_registry.get("version") or "0.6")
        source_path = self.authority_root.joinpath("Tianxia_Methods_Typed_Registry_v0_6.json").relative_to(self.root).as_posix()
        stage2_authority = {
            "authority_complete": True,
            "allowed_kinds": ["method_acquisition"],
            "allowed_channels": ["method-acquisition"],
            "method_id": method_id,
            "rule_id": f"ns1r.{method_id}.initial-method-acquisition.v1",
        }
        projection = {
            "record_id": method_id,
            "content_type": "cultivation_method",
            "display_name": method.get("name") or method_id,
            "pack_id": "tianxia.non_sphere.authority",
            "pack_version": registry_version,
            "authority": "canonical",
            "publication_state": "published",
            "source": {
                "path": source_path,
                "anchor": f"method:{method_id}",
                "source_hash": self.method_registry_commitment_sha256,
            },
            "summary": (method.get("owner_readable") or {}).get("full_description") or method_id,
            "minimum_cl": None,
            "prerequisites": [],
            "acquisition_channels": ["method-acquisition"],
            "grants": [],
            "execution_records": [],
            "compatibility": {"factory": {"stage2_authority": stage2_authority}},
            "dependencies": [],
            "supersedes": None,
            "unresolved_normalization_notes": [],
            "selected_authority": True,
        }
        return normalize_core_catalog_record(
            projection,
            pack_hash=self.authority_snapshot_hash,
        )

    def project_locked_path_catalog_record(self, path_id: str) -> dict[str, Any]:
        """Project one authenticated Path into the locked catalog contract.

        The normal catalog still contains the historical Path rows, but some
        of those rows predate the typed Stage 2 authority fields.  Initial
        multi-Path creation must use the exact source-backed Path index instead
        of silently treating an incomplete catalog row as executable authority.
        """
        profile = self.path_profiles.get(path_id)
        if profile is None:
            raise FoundryError(
                "NS1R_PATH_ID_UNKNOWN",
                "The selected Path is not available in the authenticated Path authority.",
                details={"path_id": path_id},
            )
        path_row = next((row for row in self.paths_master.get("paths", []) if row.get("canonical_id") == path_id), None)
        if not isinstance(path_row, dict):
            raise FoundryError(
                "NS1R_PATH_MASTER_ROW_MISSING",
                "The selected Path is missing from the authenticated Path master index.",
                details={"path_id": path_id},
            )
        source_file = self.authority_root / str(path_row["index_file"])
        source_path = source_file.relative_to(self.root).as_posix()
        source_hash = _hash_file(source_file)
        profile_rules = profile.get("path_profile") or {}
        ability_options = profile_rules.get("key_ability", {}).get("options") or []
        ability_code = {
            "Strength": "STR",
            "Dexterity": "DEX",
            "Constitution": "CON",
            "Intelligence": "INT",
            "Wisdom": "WIS",
            "Charisma": "CHA",
        }.get(str(ability_options[0]) if ability_options else "", "CON")
        hit_die = str(profile_rules.get("hit_die") or "d8")
        try:
            hit_die_value = int(hit_die.removeprefix("d"))
        except ValueError:
            hit_die_value = 8

        def safe_formula(formula_id: str, root: dict[str, Any]) -> dict[str, Any]:
            return {"formula_id": formula_id, "root": root, "schema_version": "TianxiaFoundry.SafeFormula.v1"}

        hp_level1 = safe_formula(
            f"ns1r.{path_id}.hp.cl1",
            {"op": "add", "terms": [{"op": "constant", "value": hit_die_value}, {"op": "ability_modifier", "ability": "CON"}]},
        )
        hp_later = safe_formula(
            f"ns1r.{path_id}.hp.later",
            {"op": "add", "terms": [{"op": "constant", "value": max(1, hit_die_value // 2 + 1)}, {"op": "ability_modifier", "ability": "CON"}]},
        )
        resource_rules = profile.get("resource_rules") or {}
        resource_id = str(resource_rules.get("canonical_id") or "")
        resource_root = {
            "op": "multiply",
            "terms": [{"op": "cl"}, {"op": "ability_modifier", "ability": ability_code}],
        }
        if resource_rules.get("minimum_formula"):
            resource_root = {
                "op": "maximum",
                "terms": [
                    resource_root,
                    {"op": "multiply", "terms": [{"op": "constant", "value": 2}, {"op": "cl"}]},
                ],
            }
        progression = deepcopy(profile.get("progression") or [])
        features = deepcopy(profile.get("features") or [])
        feature_by_id = {
            row.get("canonical_id"): row
            for row in features
            if isinstance(row, dict) and isinstance(row.get("canonical_id"), str)
        }
        required_milestones: list[dict[str, Any]] = []
        for feature in features:
            feature_kind = feature.get("feature_kind")
            if feature_kind == "subpath_selection":
                allowed_kinds = ["subpath_acquisition"]
            elif feature_kind == "advancement_choice":
                allowed_kinds = ["ability_score_change", "cultivation_insight_acquisition"]
            else:
                continue
            for milestone_cl in feature.get("granted_at_cl") or [feature.get("minimum_cl")]:
                if not isinstance(milestone_cl, int):
                    continue
                required_milestones.append({
                    "allowed_kinds": allowed_kinds,
                    "cl": milestone_cl,
                    "count": 1,
                    "path_id": path_id,
                    "milestone_id": f"{feature.get('canonical_id')}.cl{milestone_cl}",
                    "feature_record_id": feature.get("canonical_id"),
                    "feature_kind": feature_kind,
                    "source_path": source_path,
                    "source_hash": source_hash,
                })
        required_milestones.sort(key=lambda row: (row["cl"], row["milestone_id"]))
        progression_by_cl = {
            str(row.get("cl")): {
                "cl": row.get("cl"),
                "feature_record_ids": [
                    feature.get("canonical_id")
                    for feature in row.get("features") or []
                    if isinstance(feature, dict)
                    and isinstance(feature.get("canonical_id"), str)
                    and feature.get("canonical_id") in feature_by_id
                ],
                "all_feature_ids": [
                    feature.get("canonical_id")
                    for feature in row.get("features") or []
                    if isinstance(feature, dict) and isinstance(feature.get("canonical_id"), str)
                ],
                "component_feature_ids": [
                    feature.get("canonical_id")
                    for feature in row.get("features") or []
                    if isinstance(feature, dict)
                    and isinstance(feature.get("canonical_id"), str)
                    and feature.get("canonical_id") not in feature_by_id
                ],
                "features": deepcopy(row.get("features") or []),
            }
            for row in progression
            if isinstance(row, dict) and isinstance(row.get("cl"), int)
        }
        automatic_feature_record_ids_by_cl = {
            cl: list(value.get("feature_record_ids") or [])
            for cl, value in progression_by_cl.items()
        }
        stage2_authority = {
            "authority_complete": True,
            "allowed_kinds": ["path_acquisition"],
            "allowed_channels": ["path-selection"],
            "hp_later_formula": hp_later,
            "hp_level1_formula": hp_level1,
            "key_ability": ability_code,
            "required_milestones": required_milestones,
            "progression": progression,
            "progression_by_cl": progression_by_cl,
            "features": features,
            "automatic_feature_record_ids_by_cl": automatic_feature_record_ids_by_cl,
            "path_index_source": {
                "path_id": path_id,
                "source_path": source_path,
                "source_hash": source_hash,
                "authority_snapshot_hash": self.authority_snapshot_hash,
            },
            "resources": [{
                "base_formula": safe_formula(f"ns1r.{path_id}.resource.maximum", resource_root),
                "resource_id": resource_id,
            }],
            "rule_id": f"ns1r.{path_id}.initial-path-acquisition.v1",
        }
        projection = {
            "record_id": path_id,
            "content_type": "path",
            "display_name": profile.get("display_name") or path_row.get("display_name") or path_id,
            "pack_id": "tianxia.non_sphere.authority",
            "pack_version": str(profile.get("publication_revision") or "P2A"),
            "authority": "canonical",
            "publication_state": "published",
            "source": {
                "path": source_path,
                "anchor": f"path:{path_id}",
                "source_hash": source_hash,
            },
            "summary": profile_rules.get("primary_roles") or path_id,
            "minimum_cl": 1,
            "prerequisites": [],
            "acquisition_channels": ["path-selection"],
            "grants": [],
            "execution_records": [],
            "compatibility": {"factory": {"stage2_authority": stage2_authority}},
            "dependencies": [],
            "supersedes": None,
            "unresolved_normalization_notes": [],
            "selected_authority": True,
        }
        return normalize_core_catalog_record(
            projection,
            pack_hash=self.authority_snapshot_hash,
        )

    def project_locked_path_feature_catalog_record(self, path_id: str, feature_id: str) -> dict[str, Any]:
        """Project one exact Path-index feature into Stage 2 authority.

        This is a proof-bound projection of the authenticated P2A Path index,
        not a second catalog.  It lets Stage 2 retain one exact source-bound
        representative for a level event while preserving the complete
        progression feature set in the event calculation evidence.
        """
        path_record = self.project_locked_path_catalog_record(path_id)
        path_authority = path_record.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
        feature = next(
            (
                row for row in path_authority.get("features") or []
                if isinstance(row, dict) and row.get("canonical_id") == feature_id
            ),
            None,
        )
        if feature is None:
            raise FoundryError(
                "NS1R_PATH_FEATURE_ID_UNKNOWN",
                "The selected Path feature is not present in the authenticated Path index.",
                details={"path_id": path_id, "feature_id": feature_id},
            )
        feature_kind = str(feature.get("feature_kind") or "")
        granted_at_cl = [
            value for value in feature.get("granted_at_cl") or [feature.get("minimum_cl")]
            if isinstance(value, int)
        ]
        allowed_kinds = ["level_advance"]
        allowed_channels = ["level-advance"]
        ability_change = None
        if feature_kind == "advancement_choice":
            allowed_kinds.append("ability_score_change")
            allowed_channels.append("level-choice")
            ability_change = {
                "allowed_cls": granted_at_cl,
                "allowed_deltas": [1, 2],
                "budget": 2,
                "cap": 20,
            }
        if feature_kind == "subpath_selection":
            allowed_kinds.append("subpath_acquisition")
            allowed_channels.append("subpath-selection")
        source = path_record["source"]
        stage2_authority = {
            "authority_complete": True,
            "allowed_kinds": allowed_kinds,
            "allowed_channels": allowed_channels,
            "minimum_cl": feature.get("minimum_cl"),
            "granted_at_cl": granted_at_cl,
            "feature_kind": feature_kind,
            "path_id": path_id,
            "feature_record_id": feature_id,
            "ability_change": ability_change,
            "path_index_source": deepcopy(
                path_record.get("compatibility", {}).get("factory", {}).get("stage2_authority", {}).get("path_index_source") or {}
            ),
            "rule_id": f"ns1r.{path_id}.{feature_id.rsplit('.', 1)[-1]}.v1",
        }
        projection = {
            "record_id": feature_id,
            "content_type": "path_feature",
            "display_name": feature.get("display_name") or feature_id,
            "pack_id": "tianxia.non_sphere.authority",
            "pack_version": path_record.get("pack_version") or "P2A",
            "authority": "canonical",
            "publication_state": "published",
            "source": {
                "path": source.get("path"),
                "anchor": f"path-feature:{path_id}:{feature_id}",
                "source_hash": source.get("source_hash"),
            },
            "summary": feature.get("summary") or feature.get("display_name") or feature_id,
            "minimum_cl": feature.get("minimum_cl"),
            "prerequisites": deepcopy(feature.get("prerequisites") or []),
            "acquisition_channels": allowed_channels,
            "grants": [],
            "execution_records": [],
            "compatibility": {"factory": {"stage2_authority": stage2_authority}},
            "dependencies": [path_id],
            "supersedes": None,
            "unresolved_normalization_notes": [],
            "selected_authority": True,
            "path_feature": deepcopy(feature),
        }
        return normalize_core_catalog_record(
            projection,
            pack_hash=self.authority_snapshot_hash,
        )

    def method_catalog(self, state: dict[str, Any] | None = None, *, initial_creation: bool | None = None) -> dict[str, Any]:
        """Project the one typed Method authority for the requested workflow.

        Initial character creation has a deliberately separate access surface:
        Methods whose typed access tier is an open sect offering are creator
        choices.  The normal ``state`` projection remains strict so a later
        Method switch still requires the immutable post-creation evidence path.
        """
        initial_creation = state is None if initial_creation is None else initial_creation
        known = set((state or {}).get("known_method_ids") or [])
        primary = (state or {}).get("primary_method_id")
        access = list((state or {}).get("access_source_records") or [])
        rows = []
        for method in self.methods.values():
            initial_legal = self.method_initial_creation_satisfied(method)
            disposition = self._method_disposition(method, known, primary, access)
            acquisition = deepcopy(method.get("acquisition") or {})
            method_id = method["method_id"]
            exact_access_present = self.has_exact_access_record(access, "method_access", method_id=method_id)
            route_options = self.method_owner_route_options(method)
            direct_access = bool(initial_legal)
            route_configurable = bool(route_options)
            access_authorized = bool(direct_access or exact_access_present)
            currently_acquired = initial_legal if initial_creation else self.method_acquisition_satisfied(method, access)
            method_planning = {
                "schema": "TianxiaFoundry.MethodPlanningAuthority.v1",
                "method_id": method_id,
                "display_name": method["name"],
                "access_tier": acquisition.get("access_tier") or "UNRESOLVED",
                "access_routes": list(acquisition.get("routes") or []),
                 "owner_route_options": route_options,
                "access_text": acquisition.get("becoming_primary") or "",
                "currently_acquired": bool(currently_acquired),
                "direct_selection_allowed": bool(initial_legal),
                "direct_initial_acquisition_available": bool(initial_legal),
                "preference_allowed": True,
                "planning_preference_available": True,
                # A hard lock is a complete-plan requirement, not an assertion
                # that this Method is already acquired. Non-open Methods remain
                # gated by an exact owner-supplied route at local compilation.
                "hard_lock_allowed": True,
                "hard_lock_available": True,
                 "exact_selection_available": bool(initial_legal or route_configurable),
                 "owner_unavailable_reason": None if (initial_legal or route_configurable) else "This Method cannot be used during initial character creation.",
                "auto_allowed": True,
                "automatic_planning_available": True,
                "required_access_record_type": "method_access",
                "required_typed_access_fields": ["method_id", "access_tier", "route_type", "source_name", "source_reference"],
                 "required_record": {
                    "authority_type": "method_access",
                    "required_target_fields": {"method_id": method_id},
                     "exact_access_record_present": exact_access_present,
                 },
                 "route_configurable": route_configurable,
                 "access_authorized": access_authorized,
                 "exact_access_record_present": exact_access_present,
                "unavailable_code": None,
                "unavailable_reason": None,
                "source_reference": {
                    "registry_schema": self.method_registry.get("schema"),
                    "registry_version": self.method_registry.get("version"),
                    "method_record_sha256": sha256_json(method),
                    "source_evidence": deepcopy(method.get("source_evidence") or []),
                },
            }
            if initial_creation:
                disposition = {
                    "state": "INITIAL_CREATION_AVAILABLE" if initial_legal else "INITIAL_CREATION_ACCESS_REQUIRED",
                    "selectable_as_primary": initial_legal,
                    "reason": (
                        "Available as a trusted initial-creation Method choice; later switching still requires exact acquisition evidence."
                        if initial_legal
                        else f"{method.get('acquisition', {}).get('access_tier')}; exact acquisition authority is required before this Method can be selected."
                    ),
                }
            rows.append({
                "method_id": method["method_id"], "name": method["name"],
                "attainment_scope": method["attainment_scope"], "ap_routing_mode": method["ap_routing_mode"],
                "allocation_rule": method["allocation_rule"], "ap_cost_multiplier_authority": method["ap_cost_multiplier_authority"],
                "explicit_ap_grants": deepcopy(method["explicit_ap_grants"]),
                "per_path_resource_profiles": deepcopy(method["per_path_resource_profiles"]),
                "per_path_breakthrough_profiles": deepcopy(method["per_path_breakthrough_profiles"]),
                "acquisition": deepcopy(method["acquisition"]), "switching_lifecycle": deepcopy(method["switching_lifecycle"]),
                 "initial_creation_selectable": initial_legal,
                "initial_creation_unavailable_reason": None if initial_legal else disposition["reason"],
                 "method_planning": method_planning,
                 "direct_access": direct_access,
                 "route_configurable": route_configurable,
                 "access_authorized": access_authorized,
                 "exact_access_record_present": exact_access_present,
                 "disposition": disposition,
            })
        return {"schema": "Tianxia.NonSphereMethodCatalog.v1", "count": len(rows), "records": rows}

    @staticmethod
    def method_initial_creation_satisfied(method: dict[str, Any]) -> bool:
        """Return whether typed access makes a Method legal in the trusted wizard."""
        tier = str(method.get("acquisition", {}).get("access_tier") or "")
        return tier.startswith("OPEN_SECT_")

    def method_acquisition_satisfied(self, method: dict[str, Any], records: list[dict[str, Any]]) -> bool:
        tier = str(method.get("acquisition", {}).get("access_tier") or "UNRESOLVED")
        if tier == "OPEN_SECT_BASIC":
            return True
        return self.has_exact_access_record(records, "method_access", method_id=method["method_id"])

    def _method_disposition(self, method: dict[str, Any], known: set[str], primary: str | None, access_records: list[dict[str, Any]]) -> dict[str, Any]:
        method_id = method["method_id"]
        acquired = self.method_acquisition_satisfied(method, access_records)
        if primary == method_id:
            return {"state": "PRIMARY" if acquired else "PRIMARY_BLOCKED_MISSING_ACQUISITION", "selectable_as_primary": acquired, "reason": "Current Primary Method; acquisition evidence is enforced."}
        if method_id in known:
            return {"state": "KNOWN_NOT_PRIMARY" if acquired else "KNOWN_BLOCKED_MISSING_ACQUISITION", "selectable_as_primary": acquired, "reason": "Known Method; exact acquisition evidence remains required."}
        if acquired:
            return {"state": "AVAILABLE_NOW", "selectable_as_primary": True, "reason": "Exact Method acquisition authority is satisfied."}
        return {"state": "ACCESS_EVIDENCE_REQUIRED", "selectable_as_primary": False, "reason": f"{method.get('acquisition', {}).get('access_tier')}; exact character-specific evidence is required."}

    def foundation_catalog(self) -> dict[str, Any]:
        orthodox = []
        for row in sorted(self.foundations.values(), key=lambda x: x["catalog_number"]):
            projected = deepcopy(row)
            projected["owner_description"] = self.foundation_owner_description(row)
            orthodox.append(projected)
        return {
            "schema": "Tianxia.NonSphereFoundationCatalog.v1",
            "orthodox": orthodox,
            "theoretical_chakra": deepcopy(sorted(self.theoretical_foundations, key=lambda x: x["catalog_number"])),
            "orthodox_count": 30, "theoretical_chakra_count": 32,
        }

    @staticmethod
    def foundation_owner_description(foundation: dict[str, Any]) -> str:
        """Project canonical Foundation mechanics into concise owner-facing text.

        The authoritative summary remains available in the full/advanced
        surfaces.  Only implementation-process wording is removed from the
        normal dropdown projection; no mechanics are inferred or rewritten.
        """
        description = str(foundation.get("summary") or foundation.get("display_name") or "").strip()
        description = re.sub(r"\s+without creating (?:a|an) [^.]*\.", ".", description, flags=re.IGNORECASE)
        description = re.sub(r"\s+without creating (?:a|an) [^.]*$", "", description, flags=re.IGNORECASE)
        description = re.sub(r"\s+", " ", description).strip()
        return description.rstrip() or str(foundation.get("display_name") or "Foundation")

    def background_catalog(self) -> dict[str, Any]:
        rows = []
        for row in sorted(self.backgrounds.values(), key=lambda x: x["display_name"]):
            projected = deepcopy(row)
            projected["exact_route_authority"] = deepcopy(self.background_route_authority[row["background_id"]])
            projected["creator_ready"] = not bool(row["blockers"])
            rows.append(projected)
        return {"schema": "Tianxia.NonSphereBackgroundCatalog.v2", "count": 31, "records": rows}

    def subpath_catalog(self, path_id: str | None = None) -> dict[str, Any]:
        if path_id is not None and path_id not in CANONICAL_TO_COMPACT:
            raise FoundryError("NS1R_PATH_ID_UNKNOWN", "The requested Path ID is not canonical.", details={"path_id": path_id})
        rows = [deepcopy(x) for x in self.subpaths.values() if path_id is None or x["owning_path_id"] == path_id]
        rows.sort(key=lambda x: (x["owning_path_id"], x["catalog_order"], x["canonical_id"]))
        for row in rows:
            row["minimum_cl"] = self.subpath_minimum_cl(row)
        return {"schema": "Tianxia.NonSphereSubpathCatalog.v2", "count": len(rows), "records": rows}

    def project_locked_subpath_catalog_record(
        self,
        selection_id: str,
        *,
        snapshot_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Project one authenticated Subpath/Tradition into Stage 2 authority.

        The public content-pack row carries the owner-facing choice, while the
        executable parent/selection event contract lives in the typed NS1R
        subpath registry.  Keep the two surfaces separate and bind the
        projection to the registry source hash, just as Path features are
        projected above.

        When a project-scoped snapshot is supplied, every owner and feature
        value is reconstructed from that immutable row.  The live NS1R
        registry remains the authenticated schema/identity authority, but it
        must not become a project-specific fallback for a persisted Subpath.
        """
        canonical_snapshot_top_level: dict[str, Any] = {}
        snapshot_raw_projection: dict[str, Any] = {}
        snapshot_raw_record: dict[str, Any] | None = None
        snapshot_stage2_authority: dict[str, Any] = {}
        if snapshot_record is not None:
            canonical_snapshot_top_level = snapshot_record if isinstance(snapshot_record, dict) else {}
            snapshot_factory = (canonical_snapshot_top_level.get("compatibility") or {}).get("factory") or {}
            snapshot_raw_projection = (
                snapshot_factory.get("raw_projection")
                if isinstance(snapshot_factory, dict)
                and isinstance(snapshot_factory.get("raw_projection"), dict)
                else {}
            )
            snapshot_raw_record = (
                deepcopy(snapshot_raw_projection.get("raw_record"))
                if isinstance(snapshot_raw_projection.get("raw_record"), dict)
                else None
            )
            source_record = snapshot_raw_record
            if not isinstance(source_record, dict):
                raise FoundryError(
                    "PROJECT_LOCK_SUBPATH_AUTHORITY_MISSING",
                    "The immutable Subpath snapshot has no complete source-backed Subpath authority.",
                    details={"selection_id": selection_id},
                    status_code=409,
                )
            if source_record.get("canonical_id") != selection_id:
                raise FoundryError(
                    "PROJECT_LOCK_SUBPATH_IDENTITY_MISMATCH",
                    "The immutable Subpath snapshot identity does not match the requested selection.",
                    details={"selection_id": selection_id, "snapshot_id": source_record.get("canonical_id")},
                    status_code=409,
                )
            snapshot_stage2_authority = (
                deepcopy(snapshot_factory.get("stage2_authority"))
                if isinstance(snapshot_factory, dict)
                and isinstance(snapshot_factory.get("stage2_authority"), dict)
                else deepcopy(
                    (
                        ((snapshot_raw_projection.get("compatibility") or {}).get("factory") or {}).get(
                            "stage2_authority"
                        )
                    )
                    if isinstance(snapshot_raw_projection.get("compatibility"), dict)
                    and isinstance(
                        (((snapshot_raw_projection.get("compatibility") or {}).get("factory") or {}).get("stage2_authority")),
                        dict,
                    )
                    else {}
                )
            )
        else:
            source_record = next(
                (row for row in self.subpath_catalog()["records"] if row.get("canonical_id") == selection_id),
                None,
            )
        if not isinstance(source_record, dict):
            raise FoundryError(
                "NS1R_SUBPATH_ID_UNKNOWN",
                "The selected Subpath or Tradition is not accepted authority.",
                details={"selection_id": selection_id},
            )
        # Ownership is intentionally reconciled across every representation
        # that can be persisted in a project snapshot.  Keep each layer named:
        # the immutable canonical row, its outer raw projection, the nested
        # source record, and the immutable Stage 2 authority.  In particular,
        # do not reuse ``raw_projection`` for the nested source record; the
        # outer raw projection is itself an ownership mirror.
        source_factory = (source_record.get("compatibility") or {}).get("factory") or {}
        source_stage2_authority = (
            deepcopy(source_factory.get("stage2_authority"))
            if isinstance(source_factory, dict)
            and isinstance(source_factory.get("stage2_authority"), dict)
            else {}
        )

        nested_source_records: list[tuple[str, dict[str, Any]]] = []

        def collect_nested_source_records(label: str, container: dict[str, Any] | None) -> None:
            if not isinstance(container, dict):
                return
            for nested_key in ("raw_record", "source_record"):
                nested = container.get(nested_key)
                if isinstance(nested, dict):
                    nested_source_records.append((f"{label}.{nested_key}", nested))
            nested_projection = container.get("raw_projection")
            if isinstance(nested_projection, dict) and isinstance(nested_projection.get("raw_record"), dict):
                nested_source_records.append((f"{label}.raw_projection.raw_record", nested_projection["raw_record"]))

        collect_nested_source_records("snapshot_raw_projection", snapshot_raw_projection)
        collect_nested_source_records("snapshot_raw_record", snapshot_raw_record)
        collect_nested_source_records("source_record", source_record)

        ownership_containers: list[tuple[str, dict[str, Any]]] = [
            ("snapshot_top_level", canonical_snapshot_top_level),
            ("snapshot_raw_projection", snapshot_raw_projection),
            ("source_record", source_record),
            *nested_source_records,
        ]
        if isinstance(snapshot_raw_record, dict):
            ownership_containers.insert(2, ("snapshot_raw_record", snapshot_raw_record))
        owner_sources: dict[str, Any] = {}
        for label, container in ownership_containers:
            owner_sources[f"{label}_owning_path_id"] = container.get("owning_path_id")
            owner_sources[f"{label}_parent_path_id"] = container.get("parent_path_id")
        owner_sources["snapshot_stage2_owning_path_id"] = snapshot_stage2_authority.get("owning_path_id")
        owner_sources["snapshot_stage2_parent_path_id"] = snapshot_stage2_authority.get("parent_path_id")
        owner_sources["source_stage2_owning_path_id"] = source_stage2_authority.get("owning_path_id")
        owner_sources["source_stage2_parent_path_id"] = source_stage2_authority.get("parent_path_id")

        relation_sources: dict[str, str] = {}

        def canonical_path_values(value: Any) -> list[str]:
            if isinstance(value, str):
                return [value] if value in CANONICAL_TO_COMPACT else []
            if isinstance(value, list):
                result: list[str] = []
                for item in value:
                    result.extend(canonical_path_values(item))
                return result
            if isinstance(value, dict):
                result: list[str] = []
                for item in value.values():
                    result.extend(canonical_path_values(item))
                return result
            return []

        for label, container in ownership_containers:
            for relation_key in (
                "dependencies",
                "parent_relationships",
                "parent_variant_relationship",
                "relationships",
                "relations",
                "owning_path_choice_ids",
                "related_choice_ids",
                "linked_procedure_modules",
            ):
                for index, path_id in enumerate(canonical_path_values(container.get(relation_key))):
                    relation_sources[f"{label}.{relation_key}[{index}]"] = path_id

        invalid_owner_sources = {
            key: value
            for key, value in owner_sources.items()
            if key.endswith("owning_path_id")
            and value is not None
            and (not isinstance(value, str) or value not in CANONICAL_TO_COMPACT)
        }
        owner_values = {
            value
            for key, value in owner_sources.items()
            if key.endswith("owning_path_id")
            and isinstance(value, str)
            and value in CANONICAL_TO_COMPACT
        }
        invalid_parent_sources = {
            key: value
            for key, value in owner_sources.items()
            if key.endswith("parent_path_id")
            and value is not None
            and (not isinstance(value, str) or value not in CANONICAL_TO_COMPACT)
        }
        parent_values = {
            value
            for key, value in owner_sources.items()
            if key.endswith("parent_path_id")
            and isinstance(value, str)
            and value in CANONICAL_TO_COMPACT
        }
        owner_mismatch_details = {
            "selection_id": selection_id,
            "owner_sources": owner_sources,
            "relation_sources": relation_sources,
        }
        if (
            invalid_owner_sources
            or invalid_parent_sources
            or len(owner_values) != 1
            or (parent_values and (len(parent_values) != 1 or parent_values != owner_values))
            or (relation_sources and set(relation_sources.values()) != owner_values)
        ):
            raise FoundryError(
                "PROJECT_LOCK_SUBPATH_OWNER_MISMATCH",
                "The immutable Subpath snapshot contains conflicting Path-ownership representations.",
                details={**owner_mismatch_details, "invalid_owner_sources": invalid_owner_sources, "invalid_parent_sources": invalid_parent_sources},
                status_code=409,
            )
        owning_path_id = next(iter(owner_values))
        source_rows = source_record.get("feature_progression") or []
        source = (source_rows[0].get("source") if isinstance(source_rows[0], dict) else {}) if source_rows else {}
        source = source if isinstance(source, dict) else {}
        source_path = str(source.get("factory_source_path") or source.get("corpus_path") or "non-sphere-authority.subpath")
        source_hash = str(source.get("source_file_sha256") or source.get("section_sha256") or self.authority_snapshot_hash)
        minimum_cl = self.subpath_minimum_cl(source_record)
        stage2_authority = {
            "authority_complete": True,
            "allowed_kinds": ["subpath_acquisition"],
            "allowed_channels": ["subpath-selection"],
            "minimum_cl": minimum_cl,
            "parent_path_id": owning_path_id,
            "owning_path_id": owning_path_id,
            "feature_progression": deepcopy(source_record.get("feature_progression") or []),
            "subpath_index_source": {
                "selection_id": selection_id,
                "owning_path_id": owning_path_id,
                "source_path": source_path,
                "source_hash": source_hash,
                "authority_snapshot_hash": self.authority_snapshot_hash,
            },
            "rule_id": f"ns1r.{selection_id}.initial-subpath-acquisition.v1",
        }
        projection = {
            "record_id": selection_id,
            # Stage 2's acquisition reducer treats both ordinary Subpaths and
            # Spirit Traditions as the same parent-bound Subpath content type;
            # retain the original option_type in ``non_sphere_subpath``.
            "content_type": "subpath",
            "display_name": source_record.get("display_name") or selection_id,
            "owning_path_id": owning_path_id,
            "parent_path_id": owning_path_id,
            "pack_id": "tianxia.non_sphere.authority",
            "pack_version": "P2A",
            "authority": "canonical",
            "publication_state": "published",
            "source": {
                "path": source_path,
                "anchor": f"subpath:{selection_id}",
                "source_hash": source_hash,
            },
            "summary": (source_record.get("identity") or {}).get("primary_role") or source_record.get("display_name") or selection_id,
            "minimum_cl": minimum_cl,
            "prerequisites": [],
            "acquisition_channels": ["subpath-selection"],
            "grants": [],
            "execution_records": [],
            "compatibility": {"factory": {"stage2_authority": stage2_authority}},
            "dependencies": [owning_path_id],
            "supersedes": None,
            "unresolved_normalization_notes": [],
            "selected_authority": True,
            "non_sphere_subpath": deepcopy(source_record),
        }
        return normalize_core_catalog_record(projection, pack_hash=self.authority_snapshot_hash)

    def project_locked_foundation_catalog_record(
        self,
        foundation_id: str,
        *,
        snapshot_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Project one orthodox Foundation into the initial Stage 2 boundary.

        A project snapshot may contain a source-backed Foundation projection
        whose bytes predate the typed NS1R projection.  In that case the live
        authority supplies only the accepted identity/schema boundary; display
        and authored Foundation values are rebuilt from the immutable snapshot,
        just as Subpaths are.
        """
        if snapshot_record is not None:
            if (
                snapshot_record.get("record_id") != foundation_id
                or snapshot_record.get("content_type") != "foundation"
            ):
                raise FoundryError(
                    "PROJECT_LOCK_FOUNDATION_IDENTITY_MISMATCH",
                    "The immutable Foundation snapshot identity does not match the requested selection.",
                    details={
                        "foundation_id": foundation_id,
                        "snapshot_id": snapshot_record.get("record_id"),
                        "snapshot_content_type": snapshot_record.get("content_type"),
                    },
                    status_code=409,
                )
            raw_projection = (
                (snapshot_record.get("compatibility") or {})
                .get("factory", {})
                .get("raw_projection")
                or {}
            )
            snapshot_foundation = deepcopy(raw_projection.get("raw_record"))
            if not isinstance(snapshot_foundation, dict):
                raise FoundryError(
                    "PROJECT_LOCK_FOUNDATION_AUTHORITY_MISSING",
                    "The immutable Foundation snapshot has no complete source-backed Foundation authority.",
                    details={"foundation_id": foundation_id},
                    status_code=409,
                )
            foundation = snapshot_foundation
            display_name = snapshot_record.get("display_name") or foundation.get("display_name") or foundation.get("name") or foundation_id
            summary = snapshot_record.get("summary") or foundation.get("summary") or foundation.get("overview") or display_name
            source = snapshot_record.get("source") if isinstance(snapshot_record.get("source"), dict) else {}
            source_path = str(source.get("path") or "non-sphere-authority.foundation")
            source_hash = str(source.get("source_hash") or self.authority_snapshot_hash)
        else:
            foundation = self.foundations.get(foundation_id)
            display_name = None
            summary = None
            source_path = None
            source_hash = None
        if not isinstance(foundation, dict):
            raise FoundryError(
                "NS1R_FOUNDATION_ID_UNKNOWN",
                "The selected Foundation is not orthodox authority.",
                details={"foundation_id": foundation_id},
            )
        if display_name is None:
            display_name = foundation.get("display_name") or foundation_id
        if summary is None:
            summary = foundation.get("summary") or foundation.get("display_name") or foundation_id
        if source_path is None or source_hash is None:
            source = foundation.get("source") if isinstance(foundation.get("source"), dict) else {}
            source_path = str(source.get("path") or source.get("artifact") or "Foundation_Trait_Reference_v0_6.json")
            source_hash = str(source.get("source_hash") or source.get("file_sha256") or source.get("artifact_sha256") or self.authority_snapshot_hash)
        stage2_authority = {
            "authority_complete": True,
            "allowed_kinds": ["foundation_acquisition"],
            "allowed_channels": ["foundation-selection"],
            "minimum_cl": 1,
            "foundation_id": foundation_id,
            "foundation_index_source": {
                "foundation_id": foundation_id,
                "source_path": source_path,
                "source_hash": source_hash,
                "authority_snapshot_hash": self.authority_snapshot_hash,
            },
            "rule_id": f"ns1r.{foundation_id}.initial-foundation-acquisition.v1",
        }
        projection = {
            "record_id": foundation_id,
            "content_type": "foundation",
            "display_name": display_name,
            "pack_id": "tianxia.non_sphere.authority",
            "pack_version": "P2A",
            "authority": "canonical",
            "publication_state": "published",
            "source": {"path": source_path, "anchor": f"foundation:{foundation_id}", "source_hash": source_hash},
            "summary": summary,
            "minimum_cl": 1,
            "prerequisites": [],
            "acquisition_channels": ["foundation-selection"],
            "grants": [],
            "execution_records": [],
            "compatibility": {"factory": {"stage2_authority": stage2_authority}},
            "dependencies": [],
            "supersedes": None,
            "unresolved_normalization_notes": [],
            "selected_authority": True,
            "non_sphere_foundation": deepcopy(foundation),
        }
        return normalize_core_catalog_record(projection, pack_hash=self.authority_snapshot_hash)

    @staticmethod
    def subpath_minimum_cl(choice: dict[str, Any]) -> int:
        return int(choice.get("minimum_cl") or choice.get("prerequisites", {}).get("minimum_cl") or choice.get("prerequisites", {}).get("selection_level") or 3)

    def blank_state(self, project_id: str, target_cl: int = 1) -> dict[str, Any]:
        if not isinstance(target_cl, int) or not 1 <= target_cl <= 20:
            raise FoundryError("NS1R_TARGET_CL_INVALID", "Target CL must be from 1 through 20.")
        paths = []
        for compact, canonical, name, rid, rname in PATH_ORDER:
            profile = self.path_profiles[canonical]
            paths.append({
                "path_id": canonical, "compact_path_id": compact, "display_name": name,
                "attainment": 0, "status": "DORMANT", "subpath_or_tradition_id": None,
                "resource": {"resource_id": rid, "resource_name": rname, "active": False, "current": None, "maximum": None, "base_formula": profile["resource_rules"]["maximum_formula"], "method_profile": None},
                "invalidations": [],
            })
        state = {
            "schema_version": self.STATE_SCHEMA, "project_id": project_id,
            "authority_snapshot_hash": self.authority_snapshot_hash, "target_cl": target_cl,
            "paths": paths, "known_method_ids": [], "primary_method_id": None,
            "initial_creation_method_ids": [], "initial_creation_method_active": False,
            "initial_creation_subpath_ids": [],
            "access_source_records": [], "foundation_id": None, "background": None,
            "compatibility_result": None, "migration": {"status": "NATIVE_NS1R_R1"},
            "ap_transaction_history": [], "revision": 0, "updated_at": utcnow(),
        }
        return self._derive_state(state, operation="blank_state")

    def _project_exists(self, project_id: str) -> bool:
        with self.db.connection() as conn:
            return conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone() is not None

    def get_state(self, project_id: str, *, create_legacy_shell: bool = True) -> dict[str, Any]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT state_json,state_hash FROM non_sphere_character_states WHERE project_id=?", (project_id,)).fetchone()
            project = conn.execute("SELECT project_json FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if project is None:
            raise FoundryError("PROJECT_NOT_FOUND", "Project not found.", details={"project_id": project_id}, status_code=404)
        if row:
            state = json.loads(row["state_json"])
            if sha256_json(state) != row["state_hash"]:
                raise FoundryError("NS1R_STATE_HASH_MISMATCH", "The persisted non-Sphere state failed its integrity check.", details={"project_id": project_id}, status_code=500)
            # Revalidate on every read so UI/API readiness cannot use stale semantics.
            return self._derive_state(state, operation="get_state")
        if not create_legacy_shell:
            raise FoundryError("NS1R_STATE_NOT_FOUND", "No NS1R state exists for this project.", status_code=404)
        project_doc = json.loads(project["project_json"])
        target = 1
        for lock in project_doc.get("user_locks", []):
            if lock.get("field") == "target_cl" and isinstance(lock.get("value"), int):
                target = lock["value"]
        shell = self.blank_state(project_id, target)
        shell["migration"] = {"status": "MIGRATION_REQUIRED", "blockers": [{"code": "PRIMARY_METHOD_MIGRATION_REQUIRED", "message": "Legacy history does not deterministically identify one current Primary Method. The legacy project and event stream were retained unchanged."}]}
        return self.save_state(project_id, shell, operation="legacy_shell")

    def initialize_for_project(
        self, project_id: str, *, target_cl: int, path_ids: list[str] | None = None,
        method_id: str | None = None, foundation_id: str | None = None,
        background_id: str | None = None, access_source_records: list[dict[str, Any]] | None = None,
        path_attainment_by_id: dict[str, int] | None = None,
        subpath_ids: list[str] | None = None, background_route_ids: dict[str, Any] | None = None,
        trusted_initial_creation: bool = False,
        _initial_creation_authority: object | None = None,
    ) -> dict[str, Any]:
        if not self._project_exists(project_id):
            raise FoundryError("PROJECT_NOT_FOUND", "Project not found.", details={"project_id": project_id}, status_code=404)
        trusted_initial_creation_active = trusted_initial_creation is True
        if trusted_initial_creation_active and _initial_creation_authority is not _TRUSTED_INITIAL_CREATION_BOUNDARY:
            raise FoundryError(
                "NS1R_INITIAL_CREATION_AUTHORITY_FORBIDDEN",
                "Trusted initial Subpath/Tradition issuance is available only at the Character Builder initial-creation boundary.",
                status_code=403,
            )
        state = self.blank_state(project_id, target_cl)
        records, access_blockers = self._resolve_access_records(project_id, deepcopy(access_source_records or []))
        if access_blockers:
            raise FoundryError("NS1R_ACCESS_SOURCE_INVALID", "Initialization contains invalid access evidence.", details={"blockers": access_blockers})
        state["access_source_records"] = records
        path_ids = _unique_strings(path_ids or [], code="NS1R_DUPLICATE_PATH_ID", field="Path")
        requested_attainment = deepcopy(path_attainment_by_id or {})
        if set(requested_attainment) - set(path_ids):
            raise FoundryError("NS1R_PATH_ATTAINMENT_WITHOUT_SELECTION", "Initial attainment can only be assigned to selected Paths.", details={"path_ids": sorted(set(requested_attainment) - set(path_ids))})
        for path_id in path_ids:
            if path_id not in CANONICAL_TO_COMPACT:
                raise FoundryError("NS1R_PATH_ID_UNKNOWN", "The selected Path ID is not canonical.", details={"path_id": path_id})
            attainment = requested_attainment.get(path_id, 1)
            if not isinstance(attainment, int) or not 1 <= attainment <= target_cl:
                raise FoundryError("NS1R_INITIAL_PATH_ATTAINMENT_INVALID", "Initial selected-Path attainment must be from 1 through target CL.", details={"path_id": path_id, "attainment": attainment, "target_cl": target_cl})
            next(row for row in state["paths"] if row["path_id"] == path_id)["attainment"] = attainment
        if method_id:
            if method_id not in self.methods:
                raise FoundryError("NS1R_METHOD_ID_UNKNOWN", "The selected Method ID is not accepted authority.", details={"method_id": method_id})
            method_legal = (
                self.method_initial_creation_satisfied(self.methods[method_id])
                or self.method_acquisition_satisfied(self.methods[method_id], records)
                if trusted_initial_creation_active
                else self.method_acquisition_satisfied(self.methods[method_id], records)
            )
            if not method_legal:
                raise FoundryError("NS1R_METHOD_ACCESS_REQUIRED", "This Method cannot initialize as Primary without exact acquisition evidence.", details={"method_id": method_id, "access_tier": self.methods[method_id]["acquisition"].get("access_tier")})
            state["known_method_ids"] = [method_id]
            state["primary_method_id"] = method_id
        if foundation_id:
            if foundation_id not in self.foundations:
                raise FoundryError("NS1R_FOUNDATION_ID_UNKNOWN", "The selected Foundation is not orthodox authority.", details={"foundation_id": foundation_id})
            state["foundation_id"] = foundation_id
        if background_id:
            if background_id not in self.backgrounds:
                raise FoundryError("NS1R_BACKGROUND_ID_UNKNOWN", "The selected Background ID is not accepted authority.", details={"background_id": background_id})
            state["background"] = {"background_id": background_id, "validated_routes": deepcopy(background_route_ids or {})}
        for selection_id in _unique_strings(subpath_ids or [], code="NS1R_DUPLICATE_SUBPATH_ID", field="Subpath or Tradition"):
            choice = self.subpaths.get(selection_id)
            if choice is None:
                raise FoundryError("NS1R_SUBPATH_ID_UNKNOWN", "The selected Subpath or Tradition is not accepted authority.", details={"selection_id": selection_id})
            path_id = choice["owning_path_id"]
            if path_id not in path_ids:
                raise FoundryError("NS1R_SUBPATH_PATH_NOT_SELECTED", "A Subpath or Tradition requires its owning Path.", details={"selection_id": selection_id, "path_id": path_id})
            path = next(row for row in state["paths"] if row["path_id"] == path_id)
            if path["subpath_or_tradition_id"]:
                raise FoundryError("NS1R_MULTIPLE_SUBPATHS_PER_PATH", "Only one Subpath or Tradition may be selected for each Path.", details={"path_id": path_id})
            if path["attainment"] < self.subpath_minimum_cl(choice):
                raise FoundryError("NS1R_SUBPATH_CL_NOT_MET", "The selected Subpath or Tradition is not legal at current attainment.", details={"selection_id": selection_id, "minimum_cl": self.subpath_minimum_cl(choice), "attainment": path["attainment"]})
            path["subpath_or_tradition_id"] = selection_id
            access = choice.get("access") or {}
            path["subpath_or_tradition_acquisition_provenance"] = {
                "schema": "TianxiaFactory.AcquisitionProvenance.v1",
                "canonical_content_id": selection_id,
                "content_type": "Spirit Tradition" if choice.get("option_type") == "tradition" else f"{choice.get('owning_path_name') or 'Path'} Subpath",
                "access_category": access.get("canonical_category") or access.get("printed_category") or "Open",
                "source": "initial-character-creation",
                "recorded": True,
            }
        state["migration"] = {"status": "NATIVE_NS1R_R1"}
        if path_ids:
            method = self.methods[method_id] if method_id else None
            if method is not None:
                allocation_blockers = self.validate_allocation_state(state, method)
                if allocation_blockers:
                    raise FoundryError("NS1R_INITIAL_ALLOCATION_RULE_VIOLATION", "Initial Path attainments violate exact Method allocation authority.", details={"blockers": allocation_blockers})
            multiplier = self.method_burden_multiplier(method) if method is not None else 1
            state["ap_transaction_history"].append({
                "schema": "Tianxia.MethodAPAllocationTransaction.v1",
                "kind": "INITIALIZATION",
                "method_id": method_id,
                "allocations": {path_id: next(row for row in state["paths"] if row["path_id"] == path_id)["attainment"] for path_id in path_ids},
                "attainment_points_allocated": sum(next(row for row in state["paths"] if row["path_id"] == path_id)["attainment"] for path_id in path_ids),
                "burden_multiplier": multiplier,
                "ap_spent": sum(next(row for row in state["paths"] if row["path_id"] == path_id)["attainment"] for path_id in path_ids) * multiplier,
                "source_record_id": "native_initialization",
                "at": utcnow(),
            })
        if trusted_initial_creation_active and method_id:
            state["initial_creation_method_ids"] = [method_id]
            state["initial_creation_method_active"] = True
        if trusted_initial_creation_active and subpath_ids:
            state["initial_creation_subpath_ids"] = list(subpath_ids)
        state = self._derive_state(state, operation="initialize_for_project")
        if not trusted_initial_creation_active and state["readiness"]["status"] == "BLOCKED" and any(b["code"] == "METHOD_ACQUISITION_EVIDENCE_REQUIRED" for b in state["readiness"]["blockers"]):
            raise FoundryError("NS1R_METHOD_ACCESS_REQUIRED", "Initialization failed Method acquisition authority.", details={"blockers": state["readiness"]["blockers"]})
        return self._persist_state(project_id, state)

    def _validate_state_shape(
        self,
        state: dict[str, Any],
        *,
        project_document: dict[str, Any] | None = None,
    ) -> None:
        if state.get("schema_version") != self.STATE_SCHEMA:
            raise FoundryError("NS1R_STATE_SCHEMA_INVALID", "The non-Sphere state schema is unsupported.")
        if state.get("authority_snapshot_hash") != self.authority_snapshot_hash:
            raise FoundryError("NS1R_STATE_AUTHORITY_STALE", "The state was resolved against a different non-Sphere authority identity.")
        rows = state.get("paths")
        if not isinstance(rows, list) or len(rows) != 3:
            raise FoundryError("NS1R_PATH_TRACK_COUNT_INVALID", "Every character must contain exactly three orthodox Path tracks.")
        ids = [row.get("path_id") for row in rows]
        _unique_strings(ids, code="NS1R_DUPLICATE_PATH_ID", field="Path")
        if set(ids) != set(CANONICAL_TO_COMPACT):
            raise FoundryError("NS1R_PATH_TRACK_SET_INVALID", "The persistent Path tracks must be exactly the three orthodox Paths.", details={"path_ids": ids})
        if not isinstance(state.get("target_cl"), int) or not 1 <= state["target_cl"] <= 20:
            raise FoundryError("NS1R_TARGET_CL_INVALID", "Target CL must be from 1 through 20.")
        for row in rows:
            attainment = row.get("attainment")
            if not isinstance(attainment, int) or not 0 <= attainment <= state["target_cl"]:
                raise FoundryError("NS1R_PATH_ATTAINMENT_INVALID", "Path attainment must be from 0 through target CL.", details={"path_id": row.get("path_id"), "attainment": attainment})
            resource = row.get("resource") or {}
            expected = RESOURCE_BY_PATH[row["path_id"]]
            if resource.get("resource_id") != expected["resource_id"] or resource.get("resource_name") != expected["resource_name"]:
                raise FoundryError("NS1R_RESOURCE_IDENTITY_INVALID", "Path resources cannot be merged, converted, or substituted.", details={"path_id": row["path_id"]})
            current, maximum = resource.get("current"), resource.get("maximum")
            if current is not None and (not isinstance(current, int) or current < 0):
                raise FoundryError("NS1R_RESOURCE_VALUE_INVALID", "Current Path resource must be a nonnegative integer or unresolved.")
            if maximum is not None and (not isinstance(maximum, int) or maximum < 0):
                raise FoundryError("NS1R_RESOURCE_VALUE_INVALID", "Maximum Path resource must be a nonnegative integer or unresolved.")
            if current is not None and maximum is not None and current > maximum:
                raise FoundryError("NS1R_RESOURCE_OVER_MAXIMUM", "Current Path resource cannot exceed its maximum.")
        _unique_strings(state.get("known_method_ids") or [], code="NS1R_DUPLICATE_METHOD_ID", field="known Method")
        for method_id in state.get("known_method_ids") or []:
            if method_id not in self.methods:
                raise FoundryError("NS1R_METHOD_ID_UNKNOWN", "A known Method ID is not accepted authority.", details={"method_id": method_id})
        primary = state.get("primary_method_id")
        if primary is not None and (primary not in self.methods or primary not in set(state.get("known_method_ids") or [])):
            raise FoundryError("NS1R_PRIMARY_METHOD_INVALID", "The Primary Method must be one accepted Method the character knows.", details={"method_id": primary})
        foundation_id = state.get("foundation_id")
        if foundation_id is not None and foundation_id not in self.foundations:
            if any(row["foundation_id"] == foundation_id for row in self.theoretical_foundations):
                raise FoundryError("THEORETICAL_CHAKRA_FOUNDATION_NONPLAYABLE", "Theoretical Chakra concepts cannot be selected or exported.", details={"foundation_id": foundation_id})
            raise FoundryError("NS1R_FOUNDATION_ID_UNKNOWN", "The selected Foundation is not orthodox authority.", details={"foundation_id": foundation_id})

        # A non-empty initial-creation restricted-selection grant is not a
        # caller-authored flag. It must match both the immutable Character
        # Builder lock and the exact active Path-owned selections. The field
        # remains optional for pre-field state.
        if "initial_creation_subpath_ids" in state:
            initial_ids = _unique_strings(
                state.get("initial_creation_subpath_ids"),
                code="NS1R_INITIAL_CREATION_SUBPATH_IDS_INVALID",
                field="initial-creation Subpath",
            )
            if initial_ids:
                project_id = state.get("project_id")
                if project_document is None:
                    with self.db.connection() as conn:
                        project_row = conn.execute(
                            "SELECT project_json FROM projects WHERE project_id=?",
                            (project_id,),
                        ).fetchone()
                    if project_row is None:
                        raise FoundryError(
                            "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                            "Trusted initial Subpath provenance requires the exact existing project lock.",
                            details={"project_id": project_id},
                        )
                    try:
                        project_doc = json.loads(project_row["project_json"])
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise FoundryError(
                            "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                            "Trusted initial Subpath provenance requires valid immutable project JSON.",
                            details={"project_id": project_id},
                        ) from exc
                else:
                    project_doc = deepcopy(project_document)
                if not isinstance(project_doc, dict) or project_doc.get("project_id") != project_id:
                    raise FoundryError(
                        "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                        "Trusted initial Subpath provenance requires the exact existing project identity.",
                        details={"project_id": project_id},
                    )
                locks = {
                    item.get("field"): item.get("value")
                    for item in project_doc.get("user_locks") or []
                    if isinstance(item, dict) and isinstance(item.get("field"), str)
                }
                locked_choices = locks.get("character_sheet.locked_choices")
                if not isinstance(locked_choices, dict):
                    raise FoundryError(
                        "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                        "Trusted initial Subpath provenance requires the exact typed Character Builder choice lock.",
                        details={"project_id": project_id},
                    )
                locked_subpath_ids = locked_choices.get("subpath_choice")
                if not isinstance(locked_subpath_ids, list):
                    raise FoundryError(
                        "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                        "Trusted initial Subpath provenance requires a typed locked Subpath selection list.",
                        details={"project_id": project_id, "locked_subpath_ids": locked_subpath_ids},
                    )
                locked_subpath_ids = _unique_strings(
                    locked_subpath_ids,
                    code="NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                    field="locked initial Subpath",
                )
                locked_path_values = locked_choices.get("path_choice")
                if not isinstance(locked_path_values, list):
                    raise FoundryError(
                        "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                        "Trusted initial Subpath provenance requires an exact typed Path choice lock.",
                        details={"project_id": project_id, "locked_path_ids": locked_path_values},
                    )
                locked_path_ids = set(_unique_strings(
                    locked_path_values,
                    code="NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                    field="locked initial Path",
                ))
                if not locked_path_ids.issubset(CANONICAL_TO_COMPACT):
                    raise FoundryError(
                        "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                        "Trusted initial Subpath provenance names a noncanonical locked Path.",
                        details={"project_id": project_id, "locked_path_ids": sorted(locked_path_ids)},
                    )
                active_subpath_ids: list[str] = []
                for path in rows:
                    selection_id = path.get("subpath_or_tradition_id")
                    if selection_id is None:
                        continue
                    if not isinstance(selection_id, str) or not selection_id:
                        raise FoundryError(
                            "NS1R_INITIAL_CREATION_SUBPATH_IDS_INVALID",
                            "Active Path Subpath selections must be non-empty stable IDs.",
                            details={"path_id": path.get("path_id"), "selection_id": selection_id},
                        )
                    choice = self.subpaths.get(selection_id)
                    if choice is None:
                        raise FoundryError(
                            "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                            "Initial restricted-selection provenance names an unknown active Subpath or Tradition.",
                            details={"selection_id": selection_id},
                        )
                    if choice.get("owning_path_id") != path.get("path_id"):
                        raise FoundryError(
                            "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                            "Active Subpath selection is not owned by its Path track.",
                            details={"selection_id": selection_id, "path_id": path.get("path_id"), "owning_path_id": choice.get("owning_path_id")},
                        )
                    active_subpath_ids.append(selection_id)
                if (
                    len(initial_ids) != len(locked_subpath_ids)
                    or set(initial_ids) != set(locked_subpath_ids)
                    or len(initial_ids) != len(active_subpath_ids)
                    or set(initial_ids) != set(active_subpath_ids)
                ):
                    raise FoundryError(
                        "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                        "Initial restricted-selection provenance must equal the immutable locked and active Subpath selections.",
                        details={
                            "project_id": project_id,
                            "initial_creation_subpath_ids": initial_ids,
                            "locked_subpath_ids": locked_subpath_ids,
                            "active_subpath_ids": active_subpath_ids,
                        },
                    )
                for selection_id in initial_ids:
                    choice = self.subpaths.get(selection_id)
                    if choice is None:
                        raise FoundryError(
                            "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                            "Initial restricted-selection provenance names an unknown Subpath or Tradition.",
                            details={"selection_id": selection_id},
                        )
                    owner = choice.get("owning_path_id")
                    if owner not in locked_path_ids:
                        raise FoundryError(
                            "NS1R_INITIAL_CREATION_SUBPATH_BINDING_INVALID",
                            "Initial restricted-selection provenance does not bind the selected choice to its exact selected Path.",
                            details={"selection_id": selection_id, "owning_path_id": owner, "locked_path_ids": sorted(locked_path_ids)},
                        )

    def _method_profile_for_path(self, method: dict[str, Any] | None, compact_path_id: str) -> dict[str, Any] | None:
        if not method:
            return None
        return deepcopy(next((row for row in method.get("per_path_resource_profiles", []) if row.get("path_id") == compact_path_id), None))

    def _derive_state(
        self,
        state: dict[str, Any],
        *,
        operation: str,
        prevalidated_access_records: list[dict[str, Any]] | None = None,
        project_document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_state_shape(state, project_document=project_document)
        state = deepcopy(state)
        method = self.methods.get(state.get("primary_method_id"))
        granted = {row["path_id"] for row in (method or {}).get("explicit_ap_grants", []) if row.get("grants_attainment_points")}
        active_compact = []
        for row in state["paths"]:
            row["compact_path_id"] = CANONICAL_TO_COMPACT[row["path_id"]]
            row["display_name"] = PATH_NAMES[row["path_id"]]
            active = row["attainment"] > 0
            row["status"] = "ACTIVE" if active else "DORMANT"
            row["resource"]["active"] = active
            row["resource"]["method_profile"] = self._method_profile_for_path(method, row["compact_path_id"])
            if active:
                active_compact.append(row["compact_path_id"])
        state["active_path_ids"] = [COMPACT_TO_CANONICAL[x] for x in active_compact]
        state["method_granted_compact_path_ids"] = sorted(granted)
        state["foundation_projection"] = self._foundation_projection(state)
        if method and state.get("foundation_id") and active_compact:
            state["compatibility_result"] = self.resolve_compatibility(method["method_id"], state["foundation_id"], active_compact)
        else:
            state["compatibility_result"] = None
        result = self.semantic_validator.validate(
            state,
            operation=operation,
            prevalidated_access_records=prevalidated_access_records,
        )
        state = result["state"]
        state["semantic_validation"] = result["validation"]
        state["readiness"] = deepcopy(result["validation"])
        return state

    def _persist_state(self, project_id: str, state: dict[str, Any]) -> dict[str, Any]:
        state_hash = sha256_json(state)
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM projects WHERE project_id=?", (project_id,)).fetchone() is None:
                raise FoundryError("PROJECT_NOT_FOUND", "Project not found.", details={"project_id": project_id}, status_code=404)
            conn.execute(
                """INSERT INTO non_sphere_character_states(project_id,schema_version,authority_snapshot_hash,state_json,state_hash,updated_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET schema_version=excluded.schema_version,
                   authority_snapshot_hash=excluded.authority_snapshot_hash,state_json=excluded.state_json,state_hash=excluded.state_hash,updated_at=excluded.updated_at""",
                (project_id, self.STATE_SCHEMA, self.authority_snapshot_hash, canonical_json(state), state_hash, state["updated_at"]),
            )
        return deepcopy(state)

    _NATIVE_REJECTION_CODES = {
        "METHOD_ACQUISITION_EVIDENCE_REQUIRED",
        "PRIMARY_METHOD_NOT_KNOWN",
        "ACTIVE_PATH_NOT_GRANTED_BY_PRIMARY_METHOD",
        "AP_ALLOCATED_TO_UNGRANTED_PATH",
        "PATH_ATTAINMENT_HISTORY_MISMATCH",
        "EQUAL_SPLIT_CUMULATIVE_AP_VIOLATION",
        "PRIMARY_SECONDARY_MINIMUM_VIOLATION",
        "MILESTONE_LOCKED_STEP_VIOLATION",
        "MILESTONE_LOCKED_REALM_BOUNDARY_VIOLATION",
        "OWNER_DISTRIBUTED_REALM_MINIMUM_VIOLATION",
        "METHOD_ALLOCATION_RULE_UNSUPPORTED",
        "PRIMARY_SECONDARY_MINIMUM_AUTHORITY_UNRESOLVED",
        "OWNER_DISTRIBUTED_MINIMUM_AUTHORITY_UNRESOLVED",
        "ALL_METHOD_AP_RULE_AUTHORITY_AMBIGUOUS",
        "BACKGROUND_ROUTE_FIELD_UNKNOWN",
        "BACKGROUND_ROUTE_ID_UNKNOWN",
        "BACKGROUND_SPHERE_ROUTE_MISMATCH",
        "BACKGROUND_TALENT_ROUTE_MISMATCH",
        "BACKGROUND_ORIGIN_INSIGHT_ROUTE_UNKNOWN",
        "BACKGROUND_ABILITY_MODE_UNKNOWN",
        "BACKGROUND_AUTHORITY_ROUTE_MISMATCH",
    }

    def save_state(
        self,
        project_id: str,
        state: dict[str, Any],
        *,
        operation: str = "save_state",
    ) -> dict[str, Any]:
        if state.get("project_id") != project_id:
            raise FoundryError("NS1R_PROJECT_STATE_MISMATCH", "The non-Sphere state belongs to a different project.")
        current_revision = int(state.get("revision") or 0)
        state = deepcopy(state)
        with self.db.connection() as conn:
            persisted = conn.execute(
                "SELECT state_json FROM non_sphere_character_states WHERE project_id=?",
                (project_id,),
            ).fetchone()
        try:
            persisted_state = json.loads(persisted["state_json"]) if persisted else None
        except (TypeError, json.JSONDecodeError) as exc:
            raise FoundryError(
                "NS1R_STATE_HASH_MISMATCH",
                "The persisted non-Sphere state failed its integrity check.",
                details={"project_id": project_id},
            ) from exc
        persisted_initial_ids = (persisted_state or {}).get("initial_creation_subpath_ids")
        incoming_initial_ids = state.get("initial_creation_subpath_ids")
        if isinstance(persisted_initial_ids, list) and persisted_initial_ids:
            persisted_initial_ids = _unique_strings(
                persisted_initial_ids,
                code="NS1R_INITIAL_CREATION_SUBPATH_IDS_INVALID",
                field="persisted initial-creation Subpath",
            )
        if "initial_creation_subpath_ids" in state:
            incoming_initial_ids = _unique_strings(
                incoming_initial_ids,
                code="NS1R_INITIAL_CREATION_SUBPATH_IDS_INVALID",
                field="initial-creation Subpath",
            )
        if incoming_initial_ids != persisted_initial_ids:
            if incoming_initial_ids or persisted_initial_ids:
                raise FoundryError(
                    "NS1R_INITIAL_CREATION_STATE_MUTATION_FORBIDDEN",
                    "Trusted initial restricted-selection provenance is immutable and may only be preserved exactly.",
                    details={
                        "project_id": project_id,
                        "persisted_initial_creation_subpath_ids": persisted_initial_ids,
                        "incoming_initial_creation_subpath_ids": incoming_initial_ids,
                    },
                    status_code=403,
                )
        state["updated_at"] = utcnow()
        state["revision"] = current_revision + 1
        state = self._derive_state(state, operation=operation)
        migration_status = str((state.get("migration") or {}).get("status") or "")
        blockers = list((state.get("readiness") or {}).get("blockers") or [])
        rejection_blockers = [row for row in blockers if row.get("code") in self._NATIVE_REJECTION_CODES]
        if migration_status.startswith("NATIVE") and rejection_blockers:
            raise FoundryError(
                "NS1R_NATIVE_SEMANTIC_MUTATION_REJECTED",
                "The requested native-state mutation violates accepted non-Sphere authority and was not persisted.",
                details={"operation": operation, "blockers": rejection_blockers},
            )
        if state["readiness"]["status"] == "BLOCKED":
            state["mutation_disposition"] = "MIGRATION_BLOCKED_HISTORY_PRESERVED" if not migration_status.startswith("NATIVE") else "AUTHORITY_BLOCKED_INCOMPLETE_NATIVE_STATE"
        else:
            state.pop("mutation_disposition", None)
        return self._persist_state(project_id, state)

    def set_target_cl(self, project_id: str, target_cl: int) -> dict[str, Any]:
        state = self.get_state(project_id)
        if not isinstance(target_cl, int) or not 1 <= target_cl <= 20:
            raise FoundryError("NS1R_TARGET_CL_INVALID", "Target CL must be from 1 through 20.")
        highest = max(int(row["attainment"]) for row in state["paths"])
        if target_cl < highest:
            raise FoundryError("NS1R_TARGET_CL_BELOW_HISTORICAL_ATTAINMENT", "Target CL cannot be lowered below preserved Path attainment.", details={"target_cl": target_cl, "highest_path_attainment": highest})
        state["target_cl"] = target_cl
        return self.save_state(project_id, state, operation="set_target_cl")

    EVIDENCE_TYPES = {
        "method_access", "subpath_access", "ap_award", "compatibility_adjudication", "repair_completion",
        "transformation_completion", "background_choice", "talent_acquisition_provenance", "equipment_authority",
    }

    def _project_revision(self, project_id: str) -> int:
        with self.db.connection() as conn:
            row = conn.execute("SELECT revision FROM projects WHERE project_id=?", (project_id,)).fetchone()
        if row is None:
            raise FoundryError("PROJECT_NOT_FOUND", "Project not found.", details={"project_id": project_id}, status_code=404)
        return int(row["revision"])

    AUTHORITY_EVENT_SCHEMA = "TianxiaFoundry.AdvancementEvent.v3"
    AUTHORITY_EVENT_KINDS = {
        "method_access": "non_sphere_method_access",
        "subpath_access": "non_sphere_restricted_access",
        "ap_award": "non_sphere_ap_award",
        "compatibility_adjudication": "non_sphere_compatibility_adjudication",
        "repair_completion": "non_sphere_repair_completion",
        "transformation_completion": "non_sphere_transformation_completion",
        "background_choice": "non_sphere_background_choice",
        "talent_acquisition_provenance": "canonical_talent_acquisition_provenance",
        "equipment_authority": "canonical_talent_equipment_authority",
    }

    def _validate_authority_targets(self, authority_type: str, targets: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(targets, dict):
            raise FoundryError(
                "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                "Authority evidence targets must be an object.",
                details={"authority_type": authority_type, "supplied_type": type(targets).__name__},
            )
        exact = {
            "method_access": {
                "method_id": str,
                "access_tier": str,
                "route_type": str,
                "route_label": str,
                "owner_annotation": str,
                "source_reference": dict,
                "source_route_sha256": str,
                "route_commitment_sha256": str,
                "method_registry_commitment_sha256": str,
            },
            "subpath_access": {"path_id": str, "selection_id": str},
            "ap_award": {"method_id": str, "target_cl": int},
            "compatibility_adjudication": {"method_id": str, "foundation_id": str, "adjudication_outcome": str},
            "repair_completion": {"method_id": str, "foundation_id": str, "repair_interface": str, "repair_practice_name": str},
            "transformation_completion": {"method_id": str, "foundation_id": str, "transformation_route": str, "completion_type": str},
            "background_choice": {"background_id": str, "route_ids": list},
            "talent_acquisition_provenance": {
                "canonical_content_id": str, "binding_type": str, "binding_id": str,
                "catalog_record_commitment_sha256": str, "character_id": str, "issuance_route": str,
            },
            "equipment_authority": {
                "canonical_content_id": str, "binding_type": str, "binding_id": str,
                "catalog_record_commitment_sha256": str, "character_id": str, "issuance_route": str,
            },
        }
        spec = ({"method_id": str} if authority_type == "method_access" and set(targets) == {"method_id"} else exact.get(authority_type))
        if spec is None or set(targets) != set(spec):
            raise FoundryError("NS1R_AUTHORITY_TARGET_SCHEMA_INVALID", "Authority evidence targets do not match the exact accepted schema.", details={"authority_type":authority_type,"required":sorted(spec or {}),"supplied":sorted(targets) if isinstance(targets,dict) else None})
        for key, typ in spec.items():
            value=targets.get(key)
            if typ is int:
                if not isinstance(value,int) or isinstance(value,bool) or not 1 <= value <= 20:
                    raise FoundryError("NS1R_AUTHORITY_TARGET_SCHEMA_INVALID", "Authority evidence target value is invalid.", details={"field":key})
            elif typ is list:
                if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value) or len(value) != len(set(value)):
                    raise FoundryError("NS1R_AUTHORITY_TARGET_SCHEMA_INVALID", "Authority evidence target list is invalid.", details={"field": key})
            elif typ is dict:
                if not isinstance(value, dict) or not value:
                    raise FoundryError("NS1R_AUTHORITY_TARGET_SCHEMA_INVALID", "Authority evidence target object is invalid.", details={"field": key})
            elif authority_type == "method_access" and key == "owner_annotation":
                if not isinstance(value, str):
                    raise FoundryError("NS1R_AUTHORITY_TARGET_SCHEMA_INVALID", "Method learning notes must be text.", details={"field": key})
            elif not isinstance(value,str) or not value.strip():
                raise FoundryError("NS1R_AUTHORITY_TARGET_SCHEMA_INVALID", "Authority evidence target value is invalid.", details={"field":key})
        method_id = targets.get("method_id")
        foundation_id = targets.get("foundation_id")
        if method_id is not None and method_id not in self.methods:
            raise FoundryError("NS1R_AUTHORITY_TARGET_UNKNOWN", "Authority event references an unknown Method.", details={"method_id": method_id})
        path_id = targets.get("path_id")
        if path_id is not None and path_id not in CANONICAL_TO_COMPACT:
            raise FoundryError("NS1R_AUTHORITY_TARGET_UNKNOWN", "Authority event references an unknown Path.", details={"path_id": path_id})
        if authority_type == "method_access" and "route_type" in targets:
            method = self.methods[method_id]
            acquisition = method.get("acquisition") or {}
            open_route = self.method_initial_creation_satisfied(method) and targets["route_type"] == "PUBLISHED_OPEN_INITIAL_AUTHORITY"
            owner_options = self.method_owner_route_options(method)
            matched_option = next((row for row in owner_options if row.get("typed_route") == targets["route_type"]), None)
            expected_source_reference = {
                "registry_schema": self.method_registry.get("schema"),
                "registry_version": self.method_registry.get("version"),
                "method_record_sha256": sha256_json(method),
                "source_evidence": deepcopy(method.get("source_evidence") or []),
            }
            expected_route_commitment = sha256_json({
                "method_id": method_id,
                "access_tier": acquisition.get("access_tier") or "UNRESOLVED",
                "route_type": targets["route_type"],
                "source_route_sha256": targets["source_route_sha256"],
            })
            invalid = (
                targets["access_tier"] != (acquisition.get("access_tier") or "UNRESOLVED")
                or (not open_route and matched_option is None)
                or targets["route_label"] != ("Open sect training" if open_route else (matched_option or {}).get("label"))
                or targets["source_route_sha256"] != (sha256_json(acquisition.get("routes") or []) if open_route else (matched_option or {}).get("source_route_sha256"))
                or targets["source_reference"] != expected_source_reference
                or targets["route_commitment_sha256"] != expected_route_commitment
                or targets["method_registry_commitment_sha256"] != self.method_registry_commitment_sha256
            )
            if invalid:
                raise FoundryError(
                    "NS1R_METHOD_ACCESS_ROUTE_INVALID",
                    "The selected Method learning route no longer matches the installed Method record.",
                    details={"method_id": method_id},
                )
        if foundation_id is not None and foundation_id not in self.foundations:
            raise FoundryError("NS1R_AUTHORITY_TARGET_UNKNOWN", "Authority event references an unknown Foundation.", details={"foundation_id": foundation_id})
        if authority_type == "subpath_access":
            choice = self.subpaths.get(targets["selection_id"])
            if choice is None:
                raise FoundryError("NS1R_AUTHORITY_TARGET_UNKNOWN", "Authority event references an unknown Subpath or Tradition.", details={"selection_id": targets["selection_id"]})
            if choice.get("owning_path_id") != targets["path_id"]:
                raise FoundryError("NS1R_AUTHORITY_TARGET_RELATIONSHIP_INVALID", "Restricted selection does not belong to the declared Path.")
        if authority_type == "compatibility_adjudication" and targets["adjudication_outcome"] not in {"WORKABLE", "WORKABLE_WITH_FRICTION", "STRAINED", "NATURAL_AFFINITY"}:
            raise FoundryError("NS1R_AUTHORITY_TARGET_SCHEMA_INVALID", "Compatibility adjudication outcome is not accepted.")
        if authority_type == "repair_completion":
            foundation = self.foundations[targets["foundation_id"]]
            interfaces = foundation.get("compatibility_traits", {}).get("repair_interfaces", [])
            matched = next((row for row in interfaces if row.get("tag") == targets["repair_interface"]), None)
            accepted = set((matched or {}).get("repair_practice_names") or foundation.get("repair_practice_names") or [])
            if matched is None:
                raise FoundryError("NS1R_AUTHORITY_TARGET_UNKNOWN", "Authority event references an unknown Foundation repair interface.", details={"foundation_id": targets["foundation_id"], "repair_interface": targets["repair_interface"]})
            if targets["repair_practice_name"] not in accepted:
                raise FoundryError("NS1R_AUTHORITY_TARGET_RELATIONSHIP_INVALID", "Repair completion does not match the exact Foundation repair interface and practice.")
        if authority_type == "transformation_completion":
            if targets["completion_type"] not in {"FOUNDATION_CHALLENGE", "GM_AUTHORED_TRANSFORMATION_EVENT"}:
                raise FoundryError("NS1R_AUTHORITY_TARGET_SCHEMA_INVALID", "Transformation completion type is not accepted.")
            routes = foundation_id and self.foundations[foundation_id].get("compatibility_traits", {}).get("transformation_routes", [])
            if not any(row.get("tag") == targets["transformation_route"] for row in routes or []):
                raise FoundryError("NS1R_AUTHORITY_TARGET_UNKNOWN", "Authority event references an unknown Foundation transformation route.", details={"foundation_id": foundation_id, "transformation_route": targets["transformation_route"]})
        if authority_type == "background_choice":
            if targets["background_id"] not in self.backgrounds:
                raise FoundryError("NS1R_AUTHORITY_TARGET_UNKNOWN", "Authority event references an unknown background.")
            valid_routes = {row["background_route_record_id"] for row in self.background_route_authority[targets["background_id"]].get("route_options", [])}
            unknown_routes = sorted(set(targets["route_ids"]) - valid_routes)
            if unknown_routes:
                raise FoundryError(
                    "NS1R_AUTHORITY_TARGET_UNKNOWN",
                    "Authority event references an unknown Background route.",
                    details={"background_id": targets["background_id"], "route_ids": unknown_routes},
                )
            if not set(targets["route_ids"]).issubset(valid_routes):
                raise FoundryError("NS1R_AUTHORITY_TARGET_RELATIONSHIP_INVALID", "Background evidence references a route outside the exact background relationship.")
            # Lists in evidence semantics are sets unless the registered schema
            # explicitly defines positional meaning. Canonicalize before hashing.
            targets = {**targets, "route_ids": sorted(targets["route_ids"])}
        if authority_type in {"talent_acquisition_provenance", "equipment_authority"}:
            if targets["binding_type"] not in {"predicate", "clause"}:
                raise FoundryError("NS1R_AUTHORITY_TARGET_SCHEMA_INVALID", "Catalog evidence must bind one exact predicate or clause.")
            if targets["issuance_route"] not in {"initial_character_finalization", "post_creation_acquisition"}:
                raise FoundryError("NS1R_AUTHORITY_ISSUANCE_ROUTE_INVALID", "Catalog evidence issuance route is not accepted.")
            if not re.fullmatch(r"[a-f0-9]{64}", targets["catalog_record_commitment_sha256"]):
                raise FoundryError("NS1R_AUTHORITY_TARGET_SCHEMA_INVALID", "Catalog record commitment must be an exact SHA-256 digest.")
            from canonical_catalog.service import CanonicalCatalogAuthorityService
            try:
                talent = CanonicalCatalogAuthorityService(self.root).get_talent(targets["canonical_content_id"])
            except FoundryError as exc:
                if exc.code in {"CANONICAL_TALENT_NOT_FOUND", "CANONICAL_LEGACY_NON_TALENT"}:
                    raise FoundryError(
                        "NS1R_AUTHORITY_TARGET_UNKNOWN",
                        "Authority event references an unknown canonical catalog record.",
                        details={"canonical_content_id": targets["canonical_content_id"]},
                    ) from None
                raise
            if talent["record_commitment_sha256"] != targets["catalog_record_commitment_sha256"]:
                raise FoundryError("NS1R_AUTHORITY_TARGET_STALE", "Catalog evidence targets a stale canonical Talent commitment.")
            predicate = next((row for row in talent["typed_prerequisites"] if row["predicate_id"] == targets["binding_id"]), None)
            clause = next((row for row in talent["prerequisite_clauses"] if row["clause_id"] == targets["binding_id"]), None)
            if (targets["binding_type"] == "predicate" and predicate is None) or (targets["binding_type"] == "clause" and clause is None):
                raise FoundryError("NS1R_AUTHORITY_TARGET_RELATIONSHIP_INVALID", "Catalog evidence binding is not present on the committed Talent record.")
        return deepcopy(targets)

    def _validate_initial_catalog_finalization_context(
        self,
        conn,
        project_id: str,
        targets: dict[str, Any],
        context: object | None,
    ) -> None:
        if (
            not isinstance(context, _InitialCatalogFinalizationContext)
            or context._seal is not _TRUSTED_INITIAL_CATALOG_FINALIZATION
            or context.project_id != project_id
        ):
            raise FoundryError(
                "NS1R_INITIAL_CATALOG_EVIDENCE_ISSUANCE_FORBIDDEN",
                "Initial catalog evidence can be issued only by the active trusted character-finalization context.",
                status_code=403,
            )
        run = conn.execute(
            "SELECT * FROM character_creation_runs WHERE run_id=? AND project_id=?",
            (context.run_id, project_id),
        ).fetchone()
        project = conn.execute(
            "SELECT revision,project_json FROM projects WHERE project_id=?", (project_id,),
        ).fetchone()
        if run is None or project is None:
            raise FoundryError("NS1R_INITIAL_CATALOG_CONTEXT_STALE", "The trusted finalization context no longer exists.", status_code=409)
        request = json.loads(run["request_json"] or "{}")
        quality = json.loads(run["quality_json"] or "{}")
        candidate = json.loads(run["dry_run_json"] or "{}")
        snapshot = request.get("typed_choice_snapshot") or {}
        project_doc = json.loads(project["project_json"] or "{}")
        phase_valid = (
            context.phase == "scratch_compile"
            and run["status"] in {"PREPARING_REQUEST", "WAITING_FOR_RESPONSE"}
            and context.candidate_identity is None
        ) or (
            context.phase == "finalization"
            and run["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW"}
            and quality.get("status") == "CLEAN"
            and bool(context.candidate_identity)
            and candidate.get("candidate_identity") == context.candidate_identity
        )
        if (
            not phase_valid
            or run["owner_decision"] is not None
            or run["completed_at"] is not None
            or int(run["starting_revision"]) != context.starting_revision
            or request.get("project_revision") != context.starting_revision
            or request.get("content_lock_hash") != context.content_lock_hash
            or snapshot.get("canonical_project_id") != project_id
            or snapshot.get("project_revision") != context.starting_revision
            or snapshot.get("content_lock_hash") != context.content_lock_hash
            or snapshot.get("snapshot_sha256") != context.typed_choice_snapshot_sha256
            or project_doc.get("content_lock", {}).get("lock_hash") != context.content_lock_hash
            or int(project["revision"]) < context.starting_revision
        ):
            raise FoundryError(
                "NS1R_INITIAL_CATALOG_CONTEXT_STALE",
                "Initial catalog evidence requires the exact active clean revision-bound reviewed candidate.",
                status_code=409,
            )
        grant_plan = committed_catalog_grant_plan(project_doc)
        disposition = next((
            item for item in (grant_plan or {}).get("selected_talent_dispositions", [])
            if isinstance(item, dict) and item.get("canonical_talent_id") == targets.get("canonical_content_id")
        ), None)
        provenance = (disposition or {}).get("acquisition_provenance") or {}
        if (
            not isinstance(grant_plan, dict)
            or grant_plan.get("schema") != "TianxiaFactory.CanonicalGrantPlan.v1"
            or not disposition
            or disposition.get("acquisition_provenance_required") is not True
            or provenance.get("source") != "pending-trusted-initial-finalization"
            or provenance.get("recorded") is not False
            or targets.get("binding_id") not in (provenance.get("predicate_ids") or [])
        ):
            raise FoundryError(
                "NS1R_INITIAL_CATALOG_SELECTION_NOT_FROZEN",
                "Initial catalog evidence must match an exact gated Talent in the frozen grant-plan lock.",
                status_code=409,
            )

    def _locked_target_bindings(self, conn, project_id: str, targets: dict[str, Any], lock_proof: dict[str, Any]) -> list[dict[str, Any]]:
        """Resolve the complete semantic target set through immutable project records.

        Every semantic role is retained even when multiple roles are embedded in
        one parent record.  A role's relationship identity and its exact source
        record identity are separate values: nested Foundation/Background
        relationships bind their parent record, never an unrelated record that
        happens to mention the nested ID.  The relationship payload is canonical
        and independently hashed, so caller ordering cannot alter evidence
        identity.
        """
        if not isinstance(targets, dict):
            raise FoundryError(
                "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                "Authority target bindings must be resolved from an object.",
                details={"supplied_type": type(targets).__name__},
            )
        for field in (
            "method_id",
            "path_id",
            "selection_id",
            "foundation_id",
            "background_id",
            "canonical_content_id",
            "repair_interface",
            "repair_practice_name",
            "transformation_route",
        ):
            if field in targets and (
                not isinstance(targets[field], str) or not targets[field].strip()
            ):
                raise FoundryError(
                    "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                    "Authority target IDs and nested relationship values must be non-empty stable strings.",
                    details={"field": field, "value": targets[field]},
                )
        if "route_ids" in targets and (
            not isinstance(targets["route_ids"], list)
            or any(
                not isinstance(route_id, str) or not route_id.strip()
                for route_id in targets["route_ids"]
            )
        ):
            raise FoundryError(
                "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                "Background route IDs must be non-empty stable strings.",
                details={"field": "route_ids", "value": targets["route_ids"]},
            )

        identifiers: list[tuple[str, str, str, dict[str, Any]]] = []

        def authority_lookup(mapping: dict[str, Any], value: Any, *, kind: str) -> Any:
            if not isinstance(value, str) or not value.strip():
                raise FoundryError(
                    "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                    f"Authority target {kind} must be a non-empty stable ID.",
                    details={"target": kind, "value": value},
                )
            result = mapping.get(value)
            if result is None:
                raise FoundryError(
                    "NS1R_AUTHORITY_TARGET_UNKNOWN",
                    f"Authority event references an unknown {kind}.",
                    details={f"{kind}_id": value},
                )
            return result

        def add(
            role: str,
            stable_id: str,
            source_record_id: str,
            relationship: dict[str, Any] | None = None,
        ) -> None:
            identifiers.append((
                role,
                stable_id,
                source_record_id,
                relationship or {"role": role, "stable_id": stable_id},
            ))

        if isinstance(targets.get("method_id"), str):
            mid = targets["method_id"]
            method = authority_lookup(self.methods, mid, kind="Method")
            add("method", mid, mid, {"method_id": mid, "authority": method})
        if isinstance(targets.get("path_id"), str):
            pid = targets["path_id"]
            path = authority_lookup(self.path_profiles, pid, kind="Path")
            add("path", pid, pid, {"path_id": pid, "authority": path})
        if isinstance(targets.get("selection_id"), str):
            sid = targets["selection_id"]
            choice = authority_lookup(self.subpaths, sid, kind="Subpath or Tradition")
            add(
                "restricted_selection",
                sid,
                sid,
                {"selection_id": sid, "owning_path_id": choice["owning_path_id"], "authority": choice},
            )
        if isinstance(targets.get("foundation_id"), str):
            fid = targets["foundation_id"]
            foundation = authority_lookup(self.foundations, fid, kind="Foundation")
            add("foundation", fid, fid, {"foundation_id": fid, "authority": foundation})
            if targets.get("repair_interface"):
                if not isinstance(targets["repair_interface"], str) or not targets["repair_interface"].strip():
                    raise FoundryError(
                        "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                        "Foundation repair interface must be a non-empty stable ID.",
                        details={"foundation_id": fid, "repair_interface": targets["repair_interface"]},
                    )
                interface = next((
                    row
                    for row in foundation.get("compatibility_traits", {}).get("repair_interfaces", [])
                    if row.get("tag") == targets["repair_interface"]
                ), None)
                if interface is None:
                    raise FoundryError(
                        "NS1R_AUTHORITY_TARGET_UNKNOWN",
                        "Authority event references an unknown Foundation repair interface.",
                        details={"foundation_id": fid, "repair_interface": targets["repair_interface"]},
                    )
                add(
                    "repair_interface",
                    targets["repair_interface"],
                    fid,
                    {"foundation_id": fid, "repair_interface": interface},
                )
            if targets.get("repair_practice_name"):
                if not isinstance(targets["repair_practice_name"], str) or not targets["repair_practice_name"].strip():
                    raise FoundryError(
                        "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                        "Foundation repair practice must be a non-empty stable name.",
                        details={"foundation_id": fid, "repair_practice_name": targets["repair_practice_name"]},
                    )
                if not targets.get("repair_interface"):
                    raise FoundryError(
                        "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                        "A Foundation repair practice target requires its exact repair interface target.",
                        details={"foundation_id": fid, "repair_practice_name": targets["repair_practice_name"]},
                    )
                matched_interface = next(
                    row
                    for row in foundation.get("compatibility_traits", {}).get("repair_interfaces", [])
                    if row.get("tag") == targets["repair_interface"]
                )
                accepted = set(
                    matched_interface.get("repair_practice_names")
                    or foundation.get("repair_practice_names")
                    or []
                )
                if targets["repair_practice_name"] not in accepted:
                    raise FoundryError(
                        "NS1R_AUTHORITY_TARGET_RELATIONSHIP_INVALID",
                        "Repair completion does not match the exact Foundation repair interface and practice.",
                        details={"foundation_id": fid, "repair_interface": targets["repair_interface"], "repair_practice_name": targets["repair_practice_name"]},
                    )
                add(
                    "repair_practice",
                    targets["repair_practice_name"],
                    fid,
                    {
                        "foundation_id": fid,
                        "repair_interface": targets.get("repair_interface"),
                        "repair_practice_name": targets["repair_practice_name"],
                    },
                )
            elif targets.get("repair_interface"):
                raise FoundryError(
                    "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                    "A Foundation repair interface target requires its exact repair practice target.",
                    details={"foundation_id": fid, "repair_interface": targets["repair_interface"]},
                )
            if targets.get("transformation_route"):
                if not isinstance(targets["transformation_route"], str) or not targets["transformation_route"].strip():
                    raise FoundryError(
                        "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                        "Foundation transformation route must be a non-empty stable ID.",
                        details={"foundation_id": fid, "transformation_route": targets["transformation_route"]},
                    )
                routes = foundation.get("compatibility_traits", {}).get("transformation_routes", [])
                if not any(row.get("tag") == targets["transformation_route"] for row in routes or []):
                    raise FoundryError(
                        "NS1R_AUTHORITY_TARGET_UNKNOWN",
                        "Authority event references an unknown Foundation transformation route.",
                        details={"foundation_id": fid, "transformation_route": targets["transformation_route"]},
                    )
                add(
                    "transformation_route",
                    targets["transformation_route"],
                    fid,
                    {
                        "foundation_id": fid,
                        "transformation_route": targets["transformation_route"],
                        "completion_type": targets.get("completion_type"),
                    },
                )
        if isinstance(targets.get("background_id"), str):
            bid = targets["background_id"]
            background = authority_lookup(self.backgrounds, bid, kind="Background")
            add("background", bid, bid, {"background_id": bid, "authority": background})
            route_authority = self.background_route_authority.get(bid)
            if not isinstance(route_authority, dict):
                raise FoundryError(
                    "NS1R_AUTHORITY_TARGET_UNKNOWN",
                    "Authority event references a Background without route authority.",
                    details={"background_id": bid},
                )
            route_ids = targets.get("route_ids")
            if not isinstance(route_ids, list) or any(not isinstance(route_id, str) or not route_id.strip() for route_id in route_ids):
                raise FoundryError(
                    "NS1R_AUTHORITY_TARGET_SCHEMA_INVALID",
                    "Background route IDs must be non-empty stable IDs.",
                    details={"background_id": bid, "route_ids": route_ids},
                )
            route_by_id = {
                r["background_route_record_id"]: r
                for r in route_authority.get("route_options", [])
            }
            for route_id in sorted(route_ids):
                route = route_by_id.get(route_id)
                if route is None:
                    raise FoundryError(
                        "NS1R_AUTHORITY_TARGET_UNKNOWN",
                        "Authority event references an unknown Background route.",
                        details={"background_id": bid, "route_id": route_id},
                    )
                add(
                    "background_route",
                    route_id,
                    bid,
                    {"background_id": bid, "route_id": route_id, "relationship": route},
                )
        if isinstance(targets.get("canonical_content_id"), str):
            cid = targets["canonical_content_id"]
            from canonical_catalog.service import CanonicalCatalogAuthorityService
            try:
                talent = CanonicalCatalogAuthorityService(self.root).get_talent(cid)
            except FoundryError:
                raise FoundryError(
                    "NS1R_AUTHORITY_TARGET_UNKNOWN",
                    "Authority event references an unknown canonical catalog record.",
                    details={"canonical_content_id": cid},
                ) from None
            add(
                "canonical_talent",
                cid,
                cid,
                {
                    "canonical_content_id": cid,
                    "binding_type": targets.get("binding_type"),
                    "binding_id": targets.get("binding_id"),
                    "catalog_record_commitment_sha256": targets.get("catalog_record_commitment_sha256"),
                },
            )

        from project_store.service import ProjectStore

        store = ProjectStore(self.db)
        reconstructable_roles = {
            "method",
            "path",
            "restricted_selection",
            "foundation",
            "repair_interface",
            "repair_practice",
            "transformation_route",
            "background",
            "background_route",
        }
        bindings: list[dict[str, Any]] = []
        for role, stable_id, source_record_id, relationship in identifiers:
            # The record ID is the only source identity accepted here.  A
            # nested relationship (for example a repair practice) deliberately
            # uses its parent Foundation/Background record ID.  Never search
            # arbitrary record fields: a bundle or unrelated record may mention
            # the same stable ID without being that authority record.
            exact_rows = [dict(row) for row in conn.execute(
                """SELECT r.record_id,r.pack_id,r.pack_version,r.record_hash,r.record_json,l.pack_hash
                   FROM project_locked_records r
                   JOIN project_content_locks l ON l.project_id=r.project_id AND l.pack_id=r.pack_id AND l.version=r.pack_version
                   WHERE r.project_id=? AND r.record_id=?""",
                (project_id, source_record_id),
            ).fetchall()]
            if len(exact_rows) > 1:
                raise FoundryError(
                    "NS1R_LOCKED_TARGET_RESOLUTION_FAILED",
                    "Authority target has more than one exact immutable project-locked record.",
                    details={
                        "project_id": project_id,
                        "role": role,
                        "stable_id": stable_id,
                        "source_record_id": source_record_id,
                        "matches": [row["record_id"] for row in exact_rows],
                    },
                )
            row = exact_rows[0] if exact_rows else None
            if row is None and role in reconstructable_roles:
                # The caller has already proved the complete project lock above.
                # This resolver may reconstruct only an authenticated
                # project-bound non-Sphere record; it is never a live-catalog
                # fallback and its returned identity must remain exact.
                fallback = store._resolve_locked_record_after_proof(
                    conn,
                    project_id,
                    source_record_id,
                    authority_service=self,
                )
                if fallback is not None:
                    if fallback.get("record_id") != source_record_id:
                        raise FoundryError(
                            "NS1R_LOCKED_TARGET_RESOLUTION_FAILED",
                            "Proof-bound authority reconstruction returned a different record identity.",
                            details={
                                "project_id": project_id,
                                "role": role,
                                "stable_id": stable_id,
                                "source_record_id": source_record_id,
                                "resolved_record_id": fallback.get("record_id"),
                            },
                        )
                    binding = fallback["content_binding"]
                    row = {
                        "record_id": fallback["record_id"],
                        "pack_id": binding["pack_id"],
                        "pack_version": binding["pack_version"],
                        "record_hash": fallback["record_hash"],
                        "record_json": canonical_json(fallback),
                        "pack_hash": binding["pack_hash"],
                    }
            if row is None:
                raise FoundryError(
                    "NS1R_LOCKED_TARGET_RESOLUTION_FAILED",
                    "Authority target must resolve to exactly one immutable project-locked record.",
                    details={
                        "project_id": project_id,
                        "role": role,
                        "stable_id": stable_id,
                        "source_record_id": source_record_id,
                        "matches": [],
                    },
                )
            if row["record_id"] != source_record_id:
                raise FoundryError(
                    "NS1R_LOCKED_TARGET_RESOLUTION_FAILED",
                    "Authority target resolved to a record with a different immutable source identity.",
                    details={
                        "project_id": project_id,
                        "role": role,
                        "stable_id": stable_id,
                        "source_record_id": source_record_id,
                        "resolved_record_id": row["record_id"],
                    },
                )
            try:
                locked_doc = json.loads(row["record_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise FoundryError(
                    "NS1R_LOCKED_TARGET_HASH_DRIFT",
                    "A project-locked authority record is not valid canonical JSON.",
                    details={"project_id": project_id, "record_id": source_record_id},
                ) from exc
            if not isinstance(locked_doc, dict):
                raise FoundryError(
                    "NS1R_LOCKED_TARGET_HASH_DRIFT",
                    "A project-locked authority record must be a JSON object.",
                    details={"project_id": project_id, "record_id": source_record_id},
                )
            if locked_doc.get("record_id") != source_record_id:
                raise FoundryError(
                    "NS1R_LOCKED_TARGET_RESOLUTION_FAILED",
                    "The immutable authority record body does not match its exact source identity.",
                    details={
                        "project_id": project_id,
                        "role": role,
                        "stable_id": stable_id,
                        "source_record_id": source_record_id,
                        "record_body_id": locked_doc.get("record_id"),
                    },
                )
            # The exact immutable bytes are independently rehashed at use time.
            if canonical_record_hash(locked_doc) != row["record_hash"]:
                raise FoundryError(
                    "NS1R_LOCKED_TARGET_HASH_DRIFT",
                    "A project-locked authority record no longer matches its immutable hash.",
                    details={"record_id": row["record_id"]},
                )
            relationship_hash = sha256_json(relationship)
            bindings.append({
                "role": role,
                "relationship_id": f"{role}:{stable_id}",
                "relationship_hash": relationship_hash,
                "record_id": row["record_id"],
                "record_hash": row["record_hash"],
                "pack_id": row["pack_id"],
                "pack_version": row["pack_version"],
                "pack_hash": row["pack_hash"],
                "source_id": row["record_id"],
                "source_hash": row["record_hash"],
                "source_anchor": (
                    "non_sphere_authority_registry"
                    if row["pack_id"] == "tianxia.non_sphere.authority"
                    else "project_locked_records"
                ),
                "source_path": (
                    "non_sphere_authority/authority/" + row["record_id"]
                    if row["pack_id"] == "tianxia.non_sphere.authority"
                    else "project_locked_records/" + row["record_id"]
                ),
                "causal_event_id": None,
            })
        if not bindings:
            raise FoundryError("NS1R_LOCKED_TARGET_BINDING_REQUIRED", "Authority events require at least one exact locked target binding.")
        bindings.sort(key=lambda r:(r["role"],r["record_id"],r["relationship_id"],r["relationship_hash"]))
        bindings.append({
            "role":"project_lock_proof","relationship_id":"project_lock_proof","relationship_hash":lock_proof["lock_proof_hash"],
            "record_id":"project_lock_proof","record_hash":lock_proof["lock_proof_hash"],"pack_id":"project.lock","pack_version":"HF2",
            "pack_hash":lock_proof["lock_proof_hash"],"source_id":"project_lock_proof","source_hash":lock_proof["lock_proof_hash"],
            "source_anchor":"immutable_hf2_project_lock","source_path":"project_store/project_lock_proof","causal_event_id":None,
        })
        return bindings

    INITIAL_CATALOG_CREATION_AUTHORITY = "TRUSTED_SERVER_INITIAL_CHARACTER_CREATION"
    INITIAL_TALENT_ACQUISITION_KINDS = {
        "sect_trial_talent_acquisition",
        "ai_bootstrap_talent_acquisition",
        "level_talent_acquisition",
        "new_sphere_bonus_talent_acquisition",
    }

    def _validate_initial_talent_acquisition_source(
        self,
        conn,
        project_id: str,
        source_identity: str,
        targets: dict[str, Any],
        *,
        minimum_project_revision: int | None = None,
    ) -> dict[str, Any]:
        """Re-prove a server-committed Talent acquisition as initial evidence."""
        from contracts.canonical import canonical_event_hash
        row = conn.execute(
            "SELECT sequence_no,event_hash,event_json,contract_status FROM events WHERE project_id=? AND event_id=?",
            (project_id, source_identity),
        ).fetchone()
        if row is None:
            raise FoundryError("NS1R_EVIDENCE_SOURCE_NOT_FOUND", "The initial Talent acquisition event does not exist.")
        event = json.loads(row["event_json"] or "{}")
        content_id = targets.get("canonical_content_id")
        binding = event.get("content_binding") or {}
        locked = conn.execute(
            """SELECT r.record_hash,r.pack_id,r.pack_version,l.pack_hash
               FROM project_locked_records r
               JOIN project_content_locks l
                 ON l.project_id=r.project_id AND l.pack_id=r.pack_id AND l.version=r.pack_version
               WHERE r.project_id=? AND r.record_id=?""",
            (project_id, content_id),
        ).fetchone()
        valid = bool(
            row["contract_status"] == "valid"
            and event.get("schema_version") == self.AUTHORITY_EVENT_SCHEMA
            and event.get("project_id") == project_id
            and event.get("event_id") == source_identity
            and int(event.get("sequence") or -1) == int(row["sequence_no"])
            and event.get("event_hash") == row["event_hash"]
            and canonical_event_hash(event) == row["event_hash"]
            and event.get("event_type") == "acquire"
            and (event.get("advancement") or {}).get("kind") in self.INITIAL_TALENT_ACQUISITION_KINDS
            and (event.get("subject") or {}).get("content_type") == "talent"
            and (event.get("subject") or {}).get("record_id") == content_id
            and content_id in (event.get("created_records") or [])
            and locked is not None
            and binding.get("record_hash") == locked["record_hash"]
            and binding.get("pack_id") == locked["pack_id"]
            and binding.get("pack_version") == locked["pack_version"]
            and binding.get("pack_hash") == locked["pack_hash"]
            and (
                minimum_project_revision is None
                or int(event.get("project_revision") or 0) > minimum_project_revision
            )
        )
        if not valid:
            raise FoundryError(
                "NS1R_INITIAL_CATALOG_ACQUISITION_SOURCE_INVALID",
                "Initial provenance must bind the exact current server-committed Talent acquisition event.",
                status_code=409,
            )
        return {
            "source_hash": row["event_hash"],
            "event_sequence": int(row["sequence_no"]),
            "project_revision": int(event["project_revision"]),
        }

    def _materialize_initial_catalog_evidence(
        self,
        conn,
        project_id: str,
        authority_type: str,
        targets: dict[str, Any],
        context: _InitialCatalogFinalizationContext,
    ) -> str:
        candidates = []
        for row in conn.execute(
            "SELECT event_id,event_json FROM events WHERE project_id=? ORDER BY sequence_no",
            (project_id,),
        ):
            event = json.loads(row["event_json"] or "{}")
            if (
                (event.get("subject") or {}).get("record_id") == targets["canonical_content_id"]
                and (event.get("advancement") or {}).get("kind") in self.INITIAL_TALENT_ACQUISITION_KINDS
                and int(event.get("project_revision") or 0) > context.starting_revision
            ):
                candidates.append(row["event_id"])
        if len(candidates) != 1:
            raise FoundryError(
                "NS1R_INITIAL_CATALOG_ACQUISITION_SOURCE_AMBIGUOUS",
                "Initial provenance requires exactly one matching acquisition in the active creation run.",
                details={"canonical_content_id": targets["canonical_content_id"], "candidate_event_ids": candidates},
                status_code=409,
            )
        source_identity = candidates[0]
        source = self._validate_initial_talent_acquisition_source(
            conn,
            project_id,
            source_identity,
            targets,
            minimum_project_revision=context.starting_revision,
        )
        payload = {
            "project_id": project_id,
            "authority_type": authority_type,
            "targets": targets,
            "source_kind": "PROJECT_EVENT",
            "source_identity": source_identity,
            "source_hash": source["source_hash"],
            "project_revision": source["project_revision"],
            "event_sequence": source["event_sequence"],
            "amount_awarded": None,
            "creation_authority": self.INITIAL_CATALOG_CREATION_AUTHORITY,
        }
        evidence_hash = sha256_json(payload)
        evidence_id = "nse_" + evidence_hash[:32]
        prior = conn.execute(
            "SELECT evidence_id,evidence_hash,targets_json FROM non_sphere_authority_evidence "
            "WHERE project_id=? AND authority_type=? AND source_kind='PROJECT_EVENT' AND source_identity=?",
            (project_id, authority_type, source_identity),
        ).fetchone()
        if prior:
            if (
                prior["evidence_id"] != evidence_id
                or prior["evidence_hash"] != evidence_hash
                or json.loads(prior["targets_json"]) != targets
            ):
                raise FoundryError("NS1R_EVIDENCE_SOURCE_BINDING_CONFLICT", "The acquisition event already has different evidence semantics.")
            return evidence_id
        conn.execute(
            """INSERT INTO non_sphere_authority_evidence
               (evidence_id,project_id,authority_type,targets_json,source_kind,source_identity,source_hash,
                project_revision,event_sequence,amount_awarded,amount_consumed,creation_authority,valid,
                revoked_at,evidence_hash,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,NULL,0,?,1,NULL,?,?)""",
            (
                evidence_id, project_id, authority_type, canonical_json(targets), "PROJECT_EVENT",
                source_identity, source["source_hash"], source["project_revision"], source["event_sequence"],
                self.INITIAL_CATALOG_CREATION_AUTHORITY, evidence_hash, utcnow(),
            ),
        )
        return evidence_id

    def commit_authority_event(
        self, project_id: str, authority_type: str, targets: dict[str, Any], *,
        amount_awarded: int | None = None, creation_authority: str | None = None,
        idempotency_key: str,
        _initial_finalization_authority: object | None = None,
    ) -> dict[str, Any]:
        """Commit exact non-Sphere authority through the registered canonical v3 event family."""
        from contracts.canonical import ZERO_HASH, canonical_event_hash
        from project_store.service import ProjectStore
        if creation_authority not in (None, "PROJECT_AUTHORITY_SERVICE", "TEST_COMMITTED_EVENT"):
            raise FoundryError("NS1R_CALLER_AUTHORITY_FORBIDDEN", "Creation authority is derived from the authenticated commit operation.")
        targets=self._validate_authority_targets(authority_type, targets)
        initial_catalog_issuance = (
            authority_type in {"talent_acquisition_provenance", "equipment_authority"}
            and targets.get("issuance_route") == "initial_character_finalization"
        )
        if initial_catalog_issuance and not isinstance(_initial_finalization_authority, _InitialCatalogFinalizationContext):
            raise FoundryError(
                "NS1R_INITIAL_CATALOG_EVIDENCE_ISSUANCE_FORBIDDEN",
                "Initial catalog evidence can be issued only by the active trusted character-finalization context.",
                status_code=403,
            )
        if authority_type in {"talent_acquisition_provenance", "equipment_authority"} and targets["character_id"] != project_id:
            raise FoundryError("NS1R_EVIDENCE_CHARACTER_BINDING_INVALID", "Canonical catalog evidence must bind this project's canonical character identity.")
        if authority_type == "ap_award":
            if not isinstance(amount_awarded, int) or amount_awarded <= 0:
                raise FoundryError("NS1R_AP_AWARD_SOURCE_INVALID", "AP awards require a positive exact event amount.")
        elif amount_awarded is not None:
            raise FoundryError("NS1R_EVIDENCE_AMOUNT_FORBIDDEN", "Only AP-award events may carry an amount.")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise FoundryError("NS1R_AUTHORITY_EVENT_IDEMPOTENCY_REQUIRED", "Authority event commit requires an idempotency key.")
        if initial_catalog_issuance:
            with self.db.transaction() as conn:
                self._validate_initial_catalog_finalization_context(
                    conn, project_id, targets, _initial_finalization_authority,
                )
                evidence_id = self._materialize_initial_catalog_evidence(
                    conn,
                    project_id,
                    authority_type,
                    targets,
                    _initial_finalization_authority,
                )
            return self.resolve_evidence(project_id, evidence_id)
        kind=self.AUTHORITY_EVENT_KINDS[authority_type]
        operation_core={"project_id":project_id,"kind":kind,"details":targets,"amount_awarded":amount_awarded,"idempotency_key":idempotency_key}
        operation_hash=sha256_json(operation_core)
        store=ProjectStore(self.db)
        with self.db.transaction() as conn:
            if initial_catalog_issuance:
                self._validate_initial_catalog_finalization_context(
                    conn, project_id, targets, _initial_finalization_authority,
                )
            prior=conn.execute("SELECT event_json FROM events WHERE project_id=? AND canonical_schema_version=? AND idempotency_key=?",(project_id,self.AUTHORITY_EVENT_SCHEMA,idempotency_key)).fetchone() if False else None
            # SQLite JSON lookup is portable across the supported builds.
            prior=conn.execute("SELECT event_json FROM events WHERE project_id=? AND canonical_schema_version=? AND json_extract(event_json,'$.idempotency_key')=?",(project_id,self.AUTHORITY_EVENT_SCHEMA,idempotency_key)).fetchone()
            if prior:
                doc=json.loads(prior["event_json"])
                details=doc.get("advancement",{}).get("details",{})
                if details.get("operation_hash") != operation_hash:
                    raise FoundryError("NS1R_AUTHORITY_EVENT_RETRY_CONFLICT", "Authority-event idempotency key was replayed with different semantics.")
                event_id=doc["event_id"]
            else:
                project=conn.execute("SELECT revision,project_json,catalog_build_hash FROM projects WHERE project_id=?",(project_id,)).fetchone()
                if project is None: raise FoundryError("PROJECT_NOT_FOUND","Project not found.",status_code=404)
                last=conn.execute("SELECT sequence_no,event_hash FROM events WHERE project_id=? ORDER BY sequence_no DESC LIMIT 1",(project_id,)).fetchone()
                seq=int(last["sequence_no"])+1 if last else 1; prev=last["event_hash"] if last else ZERO_HASH
                lock_proof=store.project_lock_proof(conn, project_id)
                locked_bindings=self._locked_target_bindings(conn, project_id, targets, lock_proof)
                before=store._replay_events(conn,project_id,lock_proof_already_verified=True)
                event_id="nsae_"+operation_hash[:32]
                details={**targets,"authority_type":authority_type,"amount_awarded":amount_awarded,"creation_authority":"AUTHENTICATED_PROJECT_AUTHORITY_SERVICE","operation_hash":operation_hash}
                target_bindings = [row for row in locked_bindings if row.get("role") != "project_lock_proof"]
                canonical_target_set = [{
                    "role": row["role"], "record_id": row["record_id"], "record_hash": row["record_hash"],
                    "relationship_id": row["relationship_id"], "relationship_hash": row["relationship_hash"],
                    "pack_id": row["pack_id"], "pack_version": row["pack_version"], "pack_hash": row["pack_hash"]
                } for row in sorted(target_bindings, key=lambda r:(r["role"],r["record_id"],r["relationship_id"],r["relationship_hash"]))]
                complete_target_hash = sha256_json({"schema":"Tianxia.CompleteLockedTargetBinding.v1","targets":canonical_target_set})
                # The canonical v3 content_binding surface is singular. Represent
                # the deterministic complete target set with an aggregate binding;
                # retain every role-specific member in authority_bindings.
                complete_content_binding = {
                    "pack_id": "project.locked.target-set",
                    "pack_version": "1",
                    "pack_hash": lock_proof["lock_proof_hash"],
                    "record_hash": complete_target_hash,
                    "catalog_build_id": project["catalog_build_hash"] or "catalog.unbuilt",
                }
                provisional={
                    "schema_version":self.AUTHORITY_EVENT_SCHEMA,"event_id":event_id,"project_id":project_id,"project_revision":int(project["revision"])+1,
                    "sequence":seq,"event_type":"author_metadata","effective_point":{"kind":"other","character_cl":int(targets.get("target_cl",0)),"order":seq,"label":"Canonical non-Sphere authority"},
                    "legal_channel":"authenticated_project_authority_service","subject":{"record_id":next((v for k,v in targets.items() if k.endswith("_id")),project_id),"content_type":"non_sphere_authority","display_name":authority_type},
                    "content_binding":complete_content_binding,
                    "source_evidence":[{"source_id":"authenticated_project_authority_service","source_hash":self.authority_snapshot_hash,"source_anchor":"normal_authority_commit","source_path":"non_sphere_authority/service.py"}],
                    "created_records":[],"updated_records":[],"retired_records":[],"idempotency_key":idempotency_key,"previous_event_hash":prev,
                    "state_before_hash":before["state_hash"],"state_after_hash":ZERO_HASH,"created_at":utcnow(),
                    "advancement":{"kind":kind,"target_cl":int(targets.get("target_cl",0)),"details":details,"authority_bindings":[{
                        key: row[key] for key in (
                            "role", "record_id", "record_hash", "relationship_id", "relationship_hash",
                            "pack_id", "pack_version", "pack_hash",
                            "source_id", "source_hash", "source_anchor", "source_path", "causal_event_id"
                        )
                    } for row in locked_bindings],"calculation":{"rule_id":"non_sphere_authority_commit","formula":None,"inputs":operation_core,"outputs":{"authority_type":authority_type,"amount_awarded":amount_awarded},"trace":{"authenticated":True}},"training_transaction":None,"none_state":None}
                }
                after=store._reduce_events(store._event_rows(conn,project_id)+[provisional],project_id,conn,lock_already_proved=True)
                provisional["state_after_hash"]=sha256_json(after); provisional["event_hash"]=canonical_event_hash(provisional)
                store._validate_or_raise(provisional,boundary="non_sphere_authority_commit",family="advancement_event",key=event_id,conn=conn)
                conn.execute("INSERT INTO events(project_id,sequence_no,event_id,event_hash,previous_event_hash,created_at,event_json,canonical_schema_version,contract_status) VALUES(?,?,?,?,?,?,?,?,?)",(project_id,seq,event_id,provisional["event_hash"],prev,provisional["created_at"],canonical_json(provisional),self.AUTHORITY_EVENT_SCHEMA,"valid"))
                replay=store._replay_events(conn,project_id,lock_proof_already_verified=True)
                store._update_project_after_commit(conn,project_id,replay)
                conn.execute(
                    "INSERT OR REPLACE INTO snapshots(project_id,sequence_no,state_hash,state_json,created_at) VALUES(?,?,?,?,?)",
                    (project_id, seq, replay["state_hash"], canonical_json(replay["state"]), utcnow()),
                )
                self._materialize_evidence_in_transaction(conn, project_id, event_id)
        return self.resolve_evidence(project_id, self._evidence_id_for_source(project_id, event_id))

    def _source_authority_semantics(
        self,
        conn,
        project_id: str,
        source_kind: str,
        source_identity: str,
        expected_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if source_kind == "PROJECT_EVENT":
            if (
                isinstance(expected_evidence, dict)
                and expected_evidence.get("creation_authority") == self.INITIAL_CATALOG_CREATION_AUTHORITY
            ):
                targets = self._validate_authority_targets(
                    str(expected_evidence.get("authority_type") or ""),
                    json.loads(expected_evidence.get("targets_json") or "{}"),
                )
                source = self._validate_initial_talent_acquisition_source(
                    conn, project_id, source_identity, targets,
                )
                return {
                    "authority": {
                        "authority_type": expected_evidence["authority_type"],
                        "targets": targets,
                        "amount_awarded": None,
                        "creation_authority": self.INITIAL_CATALOG_CREATION_AUTHORITY,
                    },
                    "source_hash": source["source_hash"],
                    "event_sequence": source["event_sequence"],
                }
            row = conn.execute("SELECT sequence_no,event_hash,event_json FROM events WHERE project_id=? AND event_id=?", (project_id, source_identity)).fetchone()
            if row is None:
                raise FoundryError("NS1R_EVIDENCE_SOURCE_NOT_FOUND", "The project event used as evidence does not exist in this project.")
            doc = json.loads(row["event_json"])
            if doc.get("schema_version") != self.AUTHORITY_EVENT_SCHEMA or doc.get("contract_status", "valid") != "valid":
                raise FoundryError("NS1R_EVIDENCE_SOURCE_SCHEMA_INVALID", "The source event is not valid under the accepted canonical advancement-event schema.")
            from contracts.canonical import canonical_event_hash
            from project_store.service import ProjectStore
            # Resolution is also invoked while an AP allocation owns the write
            # transaction. Revalidate purely here; the event's canonical write
            # boundary already persisted its validation receipt atomically.
            ProjectStore(self.db)._validate_or_raise(
                doc,
                boundary="non_sphere_evidence_resolve",
                family="advancement_event",
                key=source_identity,
            )
            details=doc.get("advancement",{}).get("details",{})
            authority_type=details.get("authority_type")
            expected_kind=self.AUTHORITY_EVENT_KINDS.get(authority_type)
            if doc.get("advancement",{}).get("kind") != expected_kind or doc.get("project_id") != project_id or doc.get("event_id") != source_identity or int(doc.get("sequence",-1)) != int(row["sequence_no"]):
                raise FoundryError("NS1R_EVIDENCE_SOURCE_SCHEMA_INVALID", "The canonical source event has mismatched authority identity.")
            targets={k:v for k,v in details.items() if k not in {"authority_type","amount_awarded","creation_authority","operation_hash"}}
            targets=self._validate_authority_targets(authority_type,targets)
            core={"project_id":project_id,"kind":expected_kind,"details":targets,"amount_awarded":details.get("amount_awarded"),"idempotency_key":doc.get("idempotency_key")}
            if sha256_json(core) != details.get("operation_hash") or canonical_event_hash(doc) != row["event_hash"] or doc.get("event_hash") != row["event_hash"]:
                raise FoundryError("NS1R_EVIDENCE_SOURCE_HASH_INVALID", "The source authority event failed deterministic hash validation.")
            authority={"authority_type":authority_type,"targets":targets,"amount_awarded":details.get("amount_awarded"),"creation_authority":details.get("creation_authority")}
            return {"authority": authority, "source_hash": row["event_hash"], "event_sequence": int(row["sequence_no"])}
        if source_kind == "LOCKED_AUTHORITY_RECORD":
            row = conn.execute("SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?", (project_id, source_identity)).fetchone()
            if row is None:
                raise FoundryError("NS1R_EVIDENCE_SOURCE_NOT_FOUND", "The project-scoped locked authority record does not exist.")
            doc = json.loads(row["record_json"])
            authority = doc.get("non_sphere_authority")
            if not isinstance(authority, dict):
                raise FoundryError("NS1R_EVIDENCE_SOURCE_SEMANTICS_MISSING", "The locked record does not commit non-Sphere authority semantics.")
            return {"authority": authority, "source_hash": row["record_hash"], "event_sequence": None}
        raise FoundryError("NS1R_EVIDENCE_SOURCE_KIND_INVALID", "Evidence must resolve to a project event or project-scoped locked authority record.")

    def _evidence_id_for_source(self, project_id: str, source_identity: str) -> str:
        with self.db.connection() as conn:
            row = conn.execute("SELECT evidence_id FROM non_sphere_authority_evidence WHERE project_id=? AND source_kind='PROJECT_EVENT' AND source_identity=?", (project_id, source_identity)).fetchone()
        if row is None:
            raise FoundryError("NS1R_EVIDENCE_NOT_FOUND", "Canonical evidence was not materialized atomically with its source event.")
        return row["evidence_id"]

    def _materialize_evidence_in_transaction(self, conn, project_id: str, source_identity: str) -> str:
        source = self._source_authority_semantics(conn, project_id, "PROJECT_EVENT", source_identity)
        semantic = source["authority"]
        targets = semantic["targets"]
        source_event = conn.execute("SELECT event_json FROM events WHERE project_id=? AND event_id=?", (project_id, source_identity)).fetchone()
        doc = json.loads(source_event["event_json"])
        source_revision = int(doc["project_revision"])
        payload = {"project_id": project_id, "authority_type": semantic["authority_type"], "targets": targets,
                   "source_kind": "PROJECT_EVENT", "source_identity": source_identity, "source_hash": source["source_hash"],
                   "project_revision": source_revision, "event_sequence": source["event_sequence"],
                   "amount_awarded": semantic.get("amount_awarded"), "creation_authority": semantic.get("creation_authority")}
        evidence_hash = sha256_json(payload)
        evidence_id = "nse_" + evidence_hash[:32]
        prior = conn.execute("SELECT evidence_id,evidence_hash FROM non_sphere_authority_evidence WHERE project_id=? AND source_kind='PROJECT_EVENT' AND source_identity=?", (project_id, source_identity)).fetchone()
        if prior:
            if prior["evidence_id"] != evidence_id or prior["evidence_hash"] != evidence_hash:
                raise FoundryError("NS1R_EVIDENCE_SOURCE_BINDING_CONFLICT", "One immutable source event cannot materialize conflicting evidence.")
            return evidence_id
        conn.execute("""INSERT INTO non_sphere_authority_evidence
            (evidence_id,project_id,authority_type,targets_json,source_kind,source_identity,source_hash,project_revision,event_sequence,
             amount_awarded,amount_consumed,creation_authority,valid,revoked_at,evidence_hash,created_at)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,NULL,?,?)""",
            (evidence_id, project_id, semantic["authority_type"], canonical_json(targets), "PROJECT_EVENT", source_identity,
             source["source_hash"], source_revision, source["event_sequence"], semantic.get("amount_awarded"), 0,
             semantic.get("creation_authority"), evidence_hash, utcnow()))
        return evidence_id

    def commit_evidence(self, project_id: str, *, authority_type: str | None = None, targets: dict[str, Any] | None = None,
                        source_kind: str, source_identity: str, creation_authority: str | None = None,
                        amount_awarded: int | None = None) -> dict[str, Any]:
        """Materialize immutable evidence strictly from committed source semantics.

        Caller fields are assertions only. They never create or broaden authority.
        """
        with self.db.transaction() as conn:
            source = self._source_authority_semantics(conn, project_id, source_kind, source_identity)
            semantic = source["authority"]
            derived_type = semantic.get("authority_type")
            derived_targets = semantic.get("targets")
            derived_amount = semantic.get("amount_awarded")
            derived_creation = semantic.get("creation_authority") or "COMMITTED_SOURCE"
            if derived_type not in self.EVIDENCE_TYPES or not isinstance(derived_targets, dict):
                raise FoundryError("NS1R_EVIDENCE_SOURCE_SEMANTICS_INVALID", "Committed authority semantics are invalid.")
            if authority_type is not None and authority_type != derived_type:
                raise FoundryError("NS1R_EVIDENCE_TYPE_MISMATCH", "Caller authority type differs from the committed source.")
            if targets is not None and targets != derived_targets:
                raise FoundryError("NS1R_EVIDENCE_TARGET_MISMATCH", "Caller targets differ from the committed source.")
            if creation_authority is not None and creation_authority != derived_creation:
                raise FoundryError("NS1R_EVIDENCE_CREATION_AUTHORITY_MISMATCH", "Caller creation authority differs from the committed source.")
            if derived_type == "ap_award":
                if source_kind != "PROJECT_EVENT" or not isinstance(derived_amount, int) or derived_amount <= 0:
                    raise FoundryError("NS1R_AP_AWARD_SOURCE_INVALID", "AP amount and scope must come from an exact AP-award project event.")
                if amount_awarded is not None and amount_awarded != derived_amount:
                    raise FoundryError("NS1R_AP_AWARD_AMOUNT_MISMATCH", "Caller AP amount differs from the committed award event.")
            elif derived_amount is not None or amount_awarded is not None:
                raise FoundryError("NS1R_EVIDENCE_AMOUNT_FORBIDDEN", "Only AP-award evidence may carry an amount.")
            if source_kind == "PROJECT_EVENT":
                source_row = conn.execute("SELECT event_json FROM events WHERE project_id=? AND event_id=?", (project_id, source_identity)).fetchone()
                revision = int(json.loads(source_row["event_json"])["project_revision"])
            else:
                revision = self._project_revision(project_id)
            payload = {"project_id": project_id, "authority_type": derived_type, "targets": derived_targets,
                       "source_kind": source_kind, "source_identity": source_identity, "source_hash": source["source_hash"],
                       "project_revision": revision, "event_sequence": source["event_sequence"], "amount_awarded": derived_amount,
                       "creation_authority": derived_creation}
            evidence_hash = sha256_json(payload)
            evidence_id = "nse_" + evidence_hash[:32]
            conn.execute("""INSERT OR IGNORE INTO non_sphere_authority_evidence
                (evidence_id,project_id,authority_type,targets_json,source_kind,source_identity,source_hash,project_revision,event_sequence,
                 amount_awarded,amount_consumed,creation_authority,valid,revoked_at,evidence_hash,created_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,NULL,?,?)""",
                (evidence_id, project_id, derived_type, canonical_json(derived_targets), source_kind, source_identity, source["source_hash"],
                 revision, source["event_sequence"], derived_amount, 0, derived_creation, evidence_hash, utcnow()))
        return self.resolve_evidence(project_id, evidence_id)

    def resolve_evidence(self, project_id: str, evidence_id: str, *, authority_type: str | None = None,
                         targets: dict[str, Any] | None = None, require_available_ap: int | None = None) -> dict[str, Any]:
        if not isinstance(evidence_id, str) or not evidence_id:
            raise FoundryError("NS1R_EVIDENCE_ID_REQUIRED", "An immutable evidence ID is required.")
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM non_sphere_authority_evidence WHERE evidence_id=? AND project_id=?", (evidence_id, project_id)).fetchone()
            if row is None:
                raise FoundryError("NS1R_EVIDENCE_NOT_FOUND", "Evidence is missing or belongs to another project.")
            record = dict(row)
            if not record["valid"] or record["revoked_at"]:
                raise FoundryError("NS1R_EVIDENCE_REVOKED", "Evidence is no longer valid.")
            stored_targets = json.loads(record["targets_json"])
            if record["authority_type"] in {"talent_acquisition_provenance", "equipment_authority"} and stored_targets.get("character_id") != project_id:
                raise FoundryError("NS1R_EVIDENCE_CHARACTER_BINDING_INVALID", "Catalog evidence is not bound to this project's canonical character identity.")
            if authority_type and record["authority_type"] != authority_type:
                raise FoundryError("NS1R_EVIDENCE_TYPE_MISMATCH", "Evidence authority type does not match the operation.")
            if targets and any(stored_targets.get(k) != v for k, v in targets.items()):
                raise FoundryError("NS1R_EVIDENCE_TARGET_MISMATCH", "Evidence targets do not match the operation.")
            if record["source_kind"] == "PROJECT_EVENT":
                source = self._source_authority_semantics(
                    conn, project_id, record["source_kind"], record["source_identity"], record,
                )
                if source["source_hash"] != record["source_hash"] or int(source["event_sequence"]) != int(record["event_sequence"]):
                    raise FoundryError("NS1R_EVIDENCE_SOURCE_STALE", "Evidence no longer resolves to its exact project event.")
            else:
                source = self._source_authority_semantics(
                    conn, project_id, record["source_kind"], record["source_identity"],
                )
                if source["source_hash"] != record["source_hash"]:
                    raise FoundryError("NS1R_EVIDENCE_SOURCE_STALE", "Evidence no longer resolves to its exact locked authority record.")
            immutable_payload = {
                "project_id": project_id,
                "authority_type": record["authority_type"],
                "targets": stored_targets,
                "source_kind": record["source_kind"],
                "source_identity": record["source_identity"],
                "source_hash": record["source_hash"],
                "project_revision": int(record["project_revision"]),
                "event_sequence": record["event_sequence"],
                "amount_awarded": record["amount_awarded"],
                "creation_authority": record["creation_authority"],
            }
            expected_hash = sha256_json(immutable_payload)
            if record["evidence_hash"] != expected_hash or evidence_id != "nse_" + expected_hash[:32]:
                raise FoundryError("NS1R_EVIDENCE_HASH_INVALID", "The immutable evidence record failed deterministic hash validation.")
            if require_available_ap is not None:
                remaining = int(record["amount_awarded"] or 0) - int(record["amount_consumed"] or 0)
                if record["authority_type"] != "ap_award" or remaining < require_available_ap:
                    raise FoundryError("NS1R_AP_AWARD_INSUFFICIENT", "The AP award is missing, exhausted, or smaller than the required spend.", details={"remaining": remaining, "required": require_available_ap})
        record["targets"] = stored_targets
        record["remaining_amount"] = None if record["amount_awarded"] is None else int(record["amount_awarded"]) - int(record["amount_consumed"])
        record.pop("targets_json", None)
        return record

    def available_evidence(self, project_id: str) -> dict[str, Any]:
        with self.db.connection() as conn:
            rows=[dict(r) for r in conn.execute("SELECT * FROM non_sphere_authority_evidence WHERE project_id=? AND valid=1 AND revoked_at IS NULL ORDER BY authority_type,evidence_id",(project_id,))]
        items=[]
        for r in rows:
            r["targets"]=json.loads(r.pop("targets_json")); r["remaining_amount"]=None if r["amount_awarded"] is None else int(r["amount_awarded"])-int(r["amount_consumed"]); items.append(r)
        return {"schema":"Tianxia.NonSphereAvailableEvidence.v1","project_id":project_id,"evidence":items}

    def _resolve_access_records(self, project_id: str, records: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        resolved, blockers = [], []
        if not isinstance(records, list):
            return [], [{"code": "ACCESS_SOURCE_LIST_INVALID"}]
        for index, supplied in enumerate(records):
            evidence_id = supplied if isinstance(supplied, str) else supplied.get("evidence_id") if isinstance(supplied, dict) else None
            try:
                record = self.resolve_evidence(project_id, evidence_id)
                projected = {"evidence_id": record["evidence_id"], "authority_type": record["authority_type"], "source_record_id": record["source_identity"], **record["targets"], "source_hash": record["source_hash"]}
                resolved.append(projected)
            except FoundryError as exc:
                blockers.append({"code": exc.code, "index": index})
        return resolved, blockers

    def validate_access_source_records(self, records: list[dict[str, Any]], project_id: str | None = None) -> list[dict[str, Any]]:
        if project_id is None:
            # Unbound legacy objects are preserved only as migration blockers.
            return [] if records == [] else [{"code": "UNBOUND_EVIDENCE_MIGRATION_REQUIRED"}]
        _, blockers = self._resolve_access_records(project_id, records)
        return blockers

    @staticmethod
    def has_exact_access_record(records: list[dict[str, Any]], authority_type: str, **matches: str) -> bool:
        return any(
            row.get("authority_type") == authority_type
            and isinstance(row.get("source_record_id"), str) and bool(row["source_record_id"].strip())
            and all(row.get(key) == value for key, value in matches.items())
            for row in records
        )

    _has_access_record = has_exact_access_record

    def set_access_sources(self, project_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        records, blockers = self._resolve_access_records(project_id, records)
        if blockers:
            raise FoundryError("NS1R_ACCESS_SOURCE_INVALID", "Access-source records must be exact typed objects.", details={"blockers": blockers})
        state = self.get_state(project_id)
        state["access_source_records"] = deepcopy(records)
        return self.save_state(project_id, state, operation="set_access_sources")

    def set_primary_method(self, project_id: str, method_id: str, access_source_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if method_id not in self.methods:
            raise FoundryError("NS1R_METHOD_ID_UNKNOWN", "The selected Method ID is not accepted authority.", details={"method_id": method_id})
        state = self.get_state(project_id)
        records = deepcopy(state.get("access_source_records") or [])
        if access_source_records:
            added, added_blockers = self._resolve_access_records(project_id, deepcopy(access_source_records))
            if added_blockers:
                raise FoundryError("NS1R_ACCESS_SOURCE_INVALID", "Primary Method mutation contains invalid evidence.", details={"blockers": added_blockers})
            records.extend(added)
        blockers = self.validate_access_source_records([row["evidence_id"] for row in records], project_id)
        if blockers:
            raise FoundryError("NS1R_ACCESS_SOURCE_INVALID", "Primary Method mutation contains invalid evidence.", details={"blockers": blockers})
        if not self.method_acquisition_satisfied(self.methods[method_id], records):
            raise FoundryError("NS1R_METHOD_ACCESS_REQUIRED", "This Method cannot become Primary without exact acquisition evidence.", details={"method_id": method_id, "access_tier": self.methods[method_id]["acquisition"].get("access_tier")})
        previous = state.get("primary_method_id")
        if previous and previous != method_id and state.get("initial_creation_method_ids"):
            state["initial_creation_method_active"] = False
        if method_id not in state["known_method_ids"]:
            state["known_method_ids"].append(method_id)
            state["known_method_ids"].sort()
        state["access_source_records"] = records
        state["primary_method_id"] = method_id
        grants = {row["path_id"] for row in self.methods[method_id]["explicit_ap_grants"] if row.get("grants_attainment_points")}
        invalidated_paths = []
        for path in state["paths"]:
            if path.get("attainment", 0) > 0 and CANONICAL_TO_COMPACT[path["path_id"]] not in grants:
                record = {"code": "PRIMARY_METHOD_NO_FUTURE_AP_ROUTE", "method_id": method_id, "path_id": path["path_id"], "historical_attainment_preserved": True, "subpath_or_tradition_preserved": bool(path.get("subpath_or_tradition_id")), "resource_values_preserved": True}
                if record not in path.setdefault("invalidations", []):
                    path["invalidations"].append(record)
                invalidated_paths.append(path["path_id"])
        state.setdefault("method_switch_history", []).append({"from_method_id": previous, "to_method_id": method_id, "at": utcnow(), "historical_attainment_preserved": True, "event_stream_rewritten": False, "resources_restored": False, "future_ap_invalidated_path_ids": invalidated_paths})
        state.setdefault("ap_transaction_history", []).append({
            "schema": "Tianxia.MethodAPAllocationTransaction.v1", "kind": "METHOD_SWITCH_BASELINE",
            "method_id": method_id, "allocations": {row["path_id"]: int(row.get("attainment") or 0) for row in state["paths"]}, "attainment_points_allocated": 0,
            "burden_multiplier": self.method_burden_multiplier(self.methods[method_id]), "ap_spent": 0,
            "source_record_id": f"method_switch:{previous or 'none'}->{method_id}", "at": utcnow(),
            "historical_attainment_preserved": True, "resources_restored": False,
        })
        return self.save_state(project_id, state, operation="set_primary_method")

    def method_burden_multiplier(self, method: dict[str, Any]) -> int:
        match = re.search(r"(\d+)×", str(method.get("ap_cost_multiplier_authority") or ""))
        if not match:
            raise FoundryError("NS1R_AP_BURDEN_UNRESOLVED", "The Method lacks exact machine-readable AP burden authority.", details={"method_id": method["method_id"]})
        multiplier = int(match.group(1))
        expected = {"SINGLE_PATH": 1, "DUAL_PATH": 3, "TRIPLE_ORTHODOX_PATH": 5}.get(method.get("attainment_scope"))
        if multiplier != expected:
            raise FoundryError("NS1R_AP_BURDEN_AUTHORITY_MISMATCH", "Method burden does not match accepted attainment scope.", details={"method_id": method["method_id"], "multiplier": multiplier, "expected": expected})
        return multiplier

    def ap_eligibility(self, state_or_project: dict[str, Any] | str, path_id: str | None = None) -> dict[str, Any]:
        state = self.get_state(state_or_project) if isinstance(state_or_project, str) else state_or_project
        method_id = state.get("primary_method_id")
        if not method_id:
            return {"eligible": False, "blocker": {"code": "PRIMARY_METHOD_REQUIRED", "message": "Choose one acquired Primary Method before future Path AP can be routed."}}
        method = self.methods[method_id]
        targets = [path_id] if path_id else [row["path_id"] for row in state["paths"]]
        rows = []
        for canonical in targets:
            if canonical not in CANONICAL_TO_COMPACT:
                raise FoundryError("NS1R_PATH_ID_UNKNOWN", "The requested Path ID is not canonical.", details={"path_id": canonical})
            compact = CANONICAL_TO_COMPACT[canonical]
            grant = next(row for row in method["explicit_ap_grants"] if row["path_id"] == compact)
            rows.append({"path_id": canonical, "compact_path_id": compact, "eligible": bool(grant["grants_attainment_points"]), "grant": deepcopy(grant), "compatibility_can_grant_ap": False})
        return {"schema": "Tianxia.MethodGatedAPEligibility.v2", "primary_method_id": method_id, "allocation_rule": method["allocation_rule"], "attainment_scope": method["attainment_scope"], "ap_cost_multiplier_authority": method["ap_cost_multiplier_authority"], "numeric_burden_multiplier": self.method_burden_multiplier(method), "paths": rows, "thematic_compatibility_grants_ap": False}

    def _method_allocation_values(self, state: dict[str, Any], method: dict[str, Any]) -> dict[str, int]:
        values = {row["path_id"]: 0 for row in method["explicit_ap_grants"] if row.get("grants_attainment_points")}
        found = False
        for transaction in state.get("ap_transaction_history") or []:
            if transaction.get("method_id") != method["method_id"]:
                continue
            if transaction.get("kind") not in {"INITIALIZATION", "ADVANCEMENT", "METHOD_SWITCH_BASELINE"}:
                continue
            found = True
            for canonical_path_id, amount in (transaction.get("allocations") or {}).items():
                compact = CANONICAL_TO_COMPACT.get(canonical_path_id)
                if compact in values:
                    values[compact] += int(amount)
        if not found:
            # Used only before the initialization transaction is appended. Existing
            # native states must otherwise carry an exact ledger or be migration-blocked.
            return {
                compact: int(next(row for row in state["paths"] if CANONICAL_TO_COMPACT[row["path_id"]] == compact)["attainment"])
                for compact in values
            }
        return values

    def validate_attainment_history(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        expected = {canonical: 0 for canonical in CANONICAL_TO_COMPACT}
        for transaction in state.get("ap_transaction_history") or []:
            if transaction.get("kind") in {"INITIALIZATION", "ADVANCEMENT"}:
                for path_id, amount in (transaction.get("allocations") or {}).items():
                    if path_id in expected:
                        expected[path_id] += int(amount)
        for record in state.get("administrative_attainment_history") or []:
            path_id = record.get("path_id")
            if path_id in expected:
                expected[path_id] = int(record.get("after") or 0)
        actual = {row["path_id"]: int(row["attainment"]) for row in state["paths"]}
        if actual != expected:
            return [{"code": "PATH_ATTAINMENT_HISTORY_MISMATCH", "expected": expected, "actual": actual}]
        return []

    def validate_allocation_state(self, state: dict[str, Any], method: dict[str, Any]) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        grants = [row for row in method["explicit_ap_grants"] if row.get("grants_attainment_points")]
        granted_values = self._method_allocation_values(state, method)
        rule = method.get("allocation_rule")
        values = list(granted_values.values())
        if rule == "ALL_METHOD_AP_TO_GRANTED_PATH":
            if len(grants) != 1:
                blockers.append({"code": "ALL_METHOD_AP_RULE_AUTHORITY_AMBIGUOUS", "method_id": method["method_id"]})
        elif rule == "EQUAL_SPLIT":
            if values and len(set(values)) != 1:
                blockers.append({"code": "EQUAL_SPLIT_CUMULATIVE_AP_VIOLATION", "method_id": method["method_id"], "method_earned_attainment": granted_values})
        elif rule == "PRIMARY_WITH_SECONDARY_MINIMUM":
            text = " ".join(str(row.get("minimum_commitment") or "") for row in grants)
            match = re.search(r"For every\s+(\d+)\s+AP to\s+([A-Za-z ]+),\s+at least\s+(\d+)\s+AP to\s+([A-Za-z ]+)", text)
            name_map = {"Body Refining": "BODY_REFINING", "Qi Cultivation": "QI_CULTIVATION", "Spirit Awakening": "SPIRIT_AWAKENING"}
            if not match or match.group(2).strip() not in name_map or match.group(4).strip() not in name_map:
                blockers.append({"code": "PRIMARY_SECONDARY_MINIMUM_AUTHORITY_UNRESOLVED", "method_id": method["method_id"]})
            else:
                primary_ratio, primary_name, secondary_ratio, secondary_name = int(match.group(1)), match.group(2).strip(), int(match.group(3)), match.group(4).strip()
                primary_value = granted_values[name_map[primary_name]]
                secondary_value = granted_values[name_map[secondary_name]]
                if secondary_value * primary_ratio < primary_value * secondary_ratio:
                    blockers.append({"code": "PRIMARY_SECONDARY_MINIMUM_VIOLATION", "method_id": method["method_id"], "method_earned_attainment": granted_values, "authority": match.group(0)})
        elif rule == "MILESTONE_LOCKED":
            if values and max(values) - min(values) > 1:
                blockers.append({"code": "MILESTONE_LOCKED_STEP_VIOLATION", "method_id": method["method_id"], "method_earned_attainment": granted_values})
            for boundary in REALM_BOUNDARIES:
                if values and max(values) >= boundary and min(values) < boundary:
                    blockers.append({"code": "MILESTONE_LOCKED_REALM_BOUNDARY_VIOLATION", "method_id": method["method_id"], "boundary": boundary, "method_earned_attainment": granted_values})
        elif rule == "OWNER_DISTRIBUTED":
            text = " ".join(str(row.get("minimum_commitment") or "") for row in grants)
            if "At least 1 AP to each" not in text:
                blockers.append({"code": "OWNER_DISTRIBUTED_MINIMUM_AUTHORITY_UNRESOLVED", "method_id": method["method_id"]})
            for boundary in REALM_BOUNDARIES:
                if values and max(values) >= boundary and min(values) < boundary:
                    blockers.append({"code": "OWNER_DISTRIBUTED_REALM_MINIMUM_VIOLATION", "method_id": method["method_id"], "boundary": boundary, "method_earned_attainment": granted_values})
        else:
            blockers.append({"code": "METHOD_ALLOCATION_RULE_UNSUPPORTED", "method_id": method["method_id"], "allocation_rule": rule})
        return blockers

    def allocate_advancement(self, project_id: str, allocations: dict[str, int], *, evidence_id: str, idempotency_key: str) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise FoundryError("NS1R_AP_IDEMPOTENCY_REQUIRED", "AP allocation requires an idempotency key.")
        if not isinstance(allocations, dict) or not allocations or any(path_id not in CANONICAL_TO_COMPACT or not isinstance(amount, int) or amount < 0 for path_id, amount in allocations.items()):
            raise FoundryError("NS1R_AP_ALLOCATION_INVALID", "AP allocations must map canonical Path IDs to nonnegative integers.")
        with self.db.transaction() as conn:
            row=conn.execute("SELECT state_json,state_hash FROM non_sphere_character_states WHERE project_id=?",(project_id,)).fetchone()
            if row is None: raise FoundryError("NS1R_STATE_NOT_FOUND","No NS1R state exists for this project.")
            state=json.loads(row["state_json"]); before_hash=row["state_hash"]
            if sha256_json(state)!=before_hash: raise FoundryError("NS1R_STATE_HASH_MISMATCH","The persisted non-Sphere state failed its integrity check.")
            method_id=state.get("primary_method_id")
            if not method_id: raise FoundryError("PRIMARY_METHOD_REQUIRED","A Primary Method is required for AP allocation.")
            method=self.methods[method_id]; total=sum(allocations.values()); multiplier=self.method_burden_multiplier(method); required_spend=total*multiplier
            operation_core={"evidence_id":evidence_id,"method_id":method_id,"target_cl":state["target_cl"],"allocations":allocations,"burden_multiplier":multiplier,"ap_spent":required_spend}
            operation_hash=sha256_json(operation_core)
            prior=conn.execute("SELECT operation_hash,transaction_json FROM non_sphere_ap_consumptions WHERE project_id=? AND idempotency_key=?",(project_id,idempotency_key)).fetchone()
            if prior:
                if prior["operation_hash"]!=operation_hash: raise FoundryError("NS1R_AP_RETRY_CONFLICT","An idempotency key cannot be replayed for another award, Method, target CL, or allocation.")
                return json.loads(prior["transaction_json"])["state"]
            erow=conn.execute("SELECT * FROM non_sphere_authority_evidence WHERE project_id=? AND evidence_id=?",(project_id,evidence_id)).fetchone()
            if not erow: raise FoundryError("NS1R_EVIDENCE_NOT_FOUND","Evidence is missing or belongs to another project.")
            targets=json.loads(erow["targets_json"]); remaining=int(erow["amount_awarded"] or 0)-int(erow["amount_consumed"] or 0)
            if erow["authority_type"]!="ap_award" or targets!={"method_id":method_id,"target_cl":state["target_cl"]} or not erow["valid"] or erow["revoked_at"] or remaining<required_spend:
                raise FoundryError("NS1R_AP_AWARD_INSUFFICIENT","The AP award is invalid, mismatched, or exhausted.")
            source=self._source_authority_semantics(conn,project_id,erow["source_kind"],erow["source_identity"])
            if source["source_hash"]!=erow["source_hash"] or source["authority"].get("amount_awarded")!=erow["amount_awarded"]: raise FoundryError("NS1R_EVIDENCE_SOURCE_STALE","The AP award source no longer matches.")
            before={r["path_id"]:r["attainment"] for r in state["paths"]}; eligibility={r["path_id"]:r for r in self.ap_eligibility(state)["paths"]}
            for path_id,amount in allocations.items():
                if amount and not eligibility[path_id]["eligible"]: raise FoundryError("NS1R_METHOD_GATED_AP_ROUTE_BLOCKED","The Primary Method does not grant AP to this Path.",details=eligibility[path_id])
                prow=next(r for r in state["paths"] if r["path_id"]==path_id)
                if prow["attainment"]+amount>state["target_cl"]: raise FoundryError("NS1R_PATH_ATTAINMENT_EXCEEDS_TARGET_CL","Allocated AP would exceed target CL.")
                prow["attainment"]+=amount
            tx={"schema":"Tianxia.MethodAPAllocationTransaction.v1","kind":"ADVANCEMENT","method_id":method_id,"allocations":deepcopy(allocations),"attainment_points_allocated":total,"burden_multiplier":multiplier,"ap_spent":required_spend,"evidence_id":evidence_id,"source_record_id":erow["source_identity"],"idempotency_key":idempotency_key,"operation_hash":operation_hash,"before_state_hash":before_hash,"before":before,"after":{r["path_id"]:r["attainment"] for r in state["paths"]},"at":utcnow(),"compatibility_granted_ap":False,"resources_restored":False}
            state.setdefault("ap_transaction_history",[]).append(tx); blockers=self.validate_allocation_state(state,method)
            if blockers: raise FoundryError("NS1R_METHOD_ALLOCATION_RULE_VIOLATION","The AP transaction violates exact Method allocation authority.",details={"blockers":blockers})
            state["revision"]=int(state.get("revision") or 0)+1; state["updated_at"]=utcnow(); state=self._derive_state(state,operation="allocate_advancement"); state_hash=sha256_json(state)
            cur=conn.execute("UPDATE non_sphere_authority_evidence SET amount_consumed=amount_consumed+? WHERE project_id=? AND evidence_id=? AND amount_awarded-amount_consumed>=?",(required_spend,project_id,evidence_id,required_spend))
            if cur.rowcount!=1: raise FoundryError("NS1R_AP_AWARD_INSUFFICIENT","Concurrent AP consumption exhausted this award.")
            cur=conn.execute("UPDATE non_sphere_character_states SET state_json=?,state_hash=?,updated_at=? WHERE project_id=? AND state_hash=?",(canonical_json(state),state_hash,state["updated_at"],project_id,before_hash))
            if cur.rowcount!=1: raise FoundryError("NS1R_STATE_CONCURRENT_MODIFICATION","The advancement state changed concurrently; retry with a new operation.")
            conn.execute("INSERT INTO non_sphere_ap_consumptions(project_id,evidence_id,idempotency_key,operation_hash,amount,transaction_json,created_at) VALUES(?,?,?,?,?,?,?)",(project_id,evidence_id,idempotency_key,operation_hash,required_spend,canonical_json({"state":state,"transaction":tx}),utcnow()))
        return deepcopy(state)

    def set_path_attainment(
        self, project_id: str, path_id: str, attainment: int, *,
        operation_mode: str = "ADMINISTRATIVE_PRESERVATION", source_record_id: str = "validated_administrative_attainment_reduction",
    ) -> dict[str, Any]:
        state = self.get_state(project_id)
        if path_id not in CANONICAL_TO_COMPACT:
            raise FoundryError("NS1R_PATH_ID_UNKNOWN", "The requested Path ID is not canonical.", details={"path_id": path_id})
        if not isinstance(attainment, int) or not 0 <= attainment <= state["target_cl"]:
            raise FoundryError("NS1R_PATH_ATTAINMENT_INVALID", "Path attainment must be from 0 through target CL.")
        row = next(item for item in state["paths"] if item["path_id"] == path_id)
        delta = attainment - row["attainment"]
        if delta > 0:
            raise FoundryError(
                "NS1R_RAW_ATTAINMENT_ADVANCEMENT_FORBIDDEN",
                "Normal advancement must use the typed AP allocation operation so Method routing and burden cannot be bypassed.",
                details={"path_id": path_id, "current": row["attainment"], "requested": attainment},
            )
        if operation_mode not in {"ADMINISTRATIVE_PRESERVATION", "MIGRATION_PRESERVATION"}:
            raise FoundryError("NS1R_ATTAINMENT_OPERATION_MODE_INVALID", "Raw attainment reduction is restricted to deterministic administrative or migration preservation.")
        if not isinstance(source_record_id, str) or not source_record_id.strip():
            raise FoundryError("NS1R_AP_SOURCE_RECORD_REQUIRED", "Administrative attainment preservation requires exact source-record identity.")
        before = row["attainment"]
        row["attainment"] = attainment
        state.setdefault("administrative_attainment_history", []).append({
            "path_id": path_id, "before": before, "after": attainment, "kind": operation_mode,
            "source_record_id": source_record_id, "at": utcnow(), "event_stream_rewritten": False,
            "resources_restored": False, "normal_advancement_bypass": False,
        })
        return self.save_state(project_id, state, operation="set_path_attainment")

    def set_resource(self, project_id: str, path_id: str, *, current: int | None, maximum: int | None) -> dict[str, Any]:
        state = self.get_state(project_id)
        if path_id not in CANONICAL_TO_COMPACT:
            raise FoundryError("NS1R_PATH_ID_UNKNOWN", "The requested Path ID is not canonical.")
        row = next(item for item in state["paths"] if item["path_id"] == path_id)
        before = deepcopy(row["resource"])
        row["resource"]["current"] = current
        row["resource"]["maximum"] = maximum
        state.setdefault("resource_change_history", []).append({"path_id": path_id, "before": before, "after": {"current": current, "maximum": maximum}, "conversion": False, "substitution": False, "automatic_refill": False})
        return self.save_state(project_id, state, operation="set_resource")

    def select_subpath(self, project_id: str, path_id: str, selection_id: str, access_source_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        state = self.get_state(project_id)
        if path_id not in CANONICAL_TO_COMPACT:
            raise FoundryError("NS1R_PATH_ID_UNKNOWN", "The requested Path ID is not canonical.")
        choice = self.subpaths.get(selection_id)
        if not choice:
            raise FoundryError("NS1R_SUBPATH_ID_UNKNOWN", "The selected Subpath or Tradition is not accepted authority.", details={"selection_id": selection_id})
        if choice["owning_path_id"] != path_id:
            raise FoundryError("NS1R_PATH_SUBPATH_MISMATCH", "That Subpath or Tradition belongs to a different Path.", details={"path_id": path_id, "selection_id": selection_id, "owning_path_id": choice["owning_path_id"]})
        row = next(item for item in state["paths"] if item["path_id"] == path_id)
        minimum_cl = self.subpath_minimum_cl(choice)
        if row["attainment"] < minimum_cl:
            raise FoundryError("NS1R_SUBPATH_CL3_REQUIRED", "The choice requires its exact minimum Path attainment.", details={"path_id": path_id, "attainment": row["attainment"], "minimum_cl": minimum_cl})
        records = deepcopy(state.get("access_source_records") or [])
        if access_source_records:
            added, added_blockers = self._resolve_access_records(project_id, deepcopy(access_source_records))
            if added_blockers:
                raise FoundryError("NS1R_ACCESS_SOURCE_INVALID", "Primary Method mutation contains invalid evidence.", details={"blockers": added_blockers})
            records.extend(added)
        blockers = self.validate_access_source_records([row["evidence_id"] for row in records], project_id)
        if blockers:
            raise FoundryError("NS1R_ACCESS_SOURCE_INVALID", "Subpath mutation contains invalid evidence.", details={"blockers": blockers})
        access = choice.get("access") or {}
        if access.get("access_source_record_required") and not self.has_exact_access_record(
            records,
            "subpath_access",
            selection_id=selection_id,
            path_id=path_id,
        ):
            raise FoundryError(
                "NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED",
                "The restricted Subpath or Spirit Tradition requires its exact access-source record.",
                details={"selection_id": selection_id, "content_type": "Spirit Tradition" if choice.get("option_type") == "tradition" else f"{choice.get('owning_path_name') or 'Path'} Subpath"},
            )
        state["access_source_records"] = records
        row["subpath_or_tradition_id"] = selection_id
        row["subpath_or_tradition_acquisition_provenance"] = {
            "schema": "TianxiaFactory.AcquisitionProvenance.v1",
            "canonical_content_id": selection_id,
            "content_type": "Spirit Tradition" if choice.get("option_type") == "tradition" else f"{choice.get('owning_path_name') or 'Path'} Subpath",
            "access_category": access.get("canonical_category") or access.get("printed_category") or "Open",
            "source": "post-creation-authority-selection",
            "recorded": True,
        }
        return self.save_state(project_id, state, operation="select_subpath")

    def select_foundation(self, project_id: str, foundation_id: str | None) -> dict[str, Any]:
        state = self.get_state(project_id)
        if foundation_id is not None and foundation_id not in self.foundations:
            if any(row["foundation_id"] == foundation_id for row in self.theoretical_foundations):
                raise FoundryError("THEORETICAL_CHAKRA_FOUNDATION_NONPLAYABLE", "Theoretical Chakra concepts cannot be selected, exported, or used in tournament play.")
            raise FoundryError("NS1R_FOUNDATION_ID_UNKNOWN", "The selected Foundation is not orthodox authority.")
        state["foundation_id"] = foundation_id
        return self.save_state(project_id, state, operation="select_foundation")

    def _foundation_projection(self, state: dict[str, Any]) -> dict[str, Any] | None:
        foundation_id = state.get("foundation_id")
        if not foundation_id:
            return None
        foundation = self.foundations[foundation_id]
        active = {CANONICAL_TO_COMPACT[row["path_id"]] for row in state["paths"] if row["attainment"] > 0}
        supported = set(foundation["compatible_path_ids"])
        activated = sorted(active & supported)
        unsupported = sorted(active - supported)
        return {
            "foundation_id": foundation_id, "display_name": foundation["display_name"],
            "active_expression_path_ids": [COMPACT_TO_CANONICAL[x] for x in activated],
            "dormant_expression_path_ids": [row["path_id"] for row in state["paths"] if row["attainment"] == 0 and CANONICAL_TO_COMPACT[row["path_id"]] in supported],
            "unsupported_active_path_ids": [COMPACT_TO_CANONICAL[x] for x in unsupported],
            "expressions": [row for row in foundation["path_expressions"] if row["path_id"] in activated],
            "compatibility_grants_ap": False, "grants_spheres_talents_methods_resources_or_combat_actions": False,
        }

    def resolve_compatibility(self, method_id: str, foundation_id: str, active_path_ids: list[str]) -> dict[str, Any]:
        if method_id not in self.methods or foundation_id not in self.foundations:
            raise FoundryError("NS1R_COMPATIBILITY_INPUT_UNKNOWN", "Compatibility inputs must be accepted Method and orthodox Foundation IDs.")
        active = _unique_strings(active_path_ids, code="NS1R_DUPLICATE_PATH_ID", field="active Path")
        compact = []
        for path_id in active:
            if path_id in CANONICAL_TO_COMPACT:
                compact.append(CANONICAL_TO_COMPACT[path_id])
            elif path_id in COMPACT_TO_CANONICAL:
                compact.append(path_id)
            else:
                raise FoundryError("NS1R_PATH_ID_UNKNOWN", "Compatibility contains a noncanonical Path ID.", details={"path_id": path_id})
        result = self._resolver.resolve(self.methods[method_id]["compatibility_traits"], self.foundation_traits[foundation_id], compact, self.overrides)
        result["authority_snapshot_hash"] = self.authority_snapshot_hash
        result["method_authority_sha256"] = self.identity["files"]["Tianxia_Methods_Typed_Registry_v0_6.json"]["sha256"]
        result["foundation_authority_sha256"] = self.identity["files"]["Foundation_Trait_Reference_v0_6.json"]["sha256"]
        result["override_authority_sha256"] = self.identity["files"]["Exact_Named_Method_Foundation_Overrides_v0_6.json"]["sha256"]
        result["runtime_pairwise_authority_rows"] = 0
        return result

    @staticmethod
    def _matched_evidence_tag(result: dict[str, Any], prefix: str) -> str | None:
        for item in result.get("evidence") or []:
            if isinstance(item, str) and item.startswith(prefix + "="):
                return item.split("=", 1)[1]
        return None

    def compatibility_readiness(self, result: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        state = result.get("state")
        method_id = result.get("method_id")
        foundation_id = result.get("foundation_id")
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if state == "INCOMPATIBLE":
            blockers.append({"code": "METHOD_FOUNDATION_INCOMPATIBLE", "method_id": method_id, "foundation_id": foundation_id, "evidence": deepcopy(result.get("evidence") or [])})
        elif state == "GM_REVIEW_REQUIRED":
            valid = any(row.get("authority_type") == "compatibility_adjudication" and row.get("method_id") == method_id and row.get("foundation_id") == foundation_id and row.get("adjudication_outcome") in {"WORKABLE", "WORKABLE_WITH_FRICTION", "STRAINED", "NATURAL_AFFINITY"} and row.get("source_record_id") for row in records)
            if not valid:
                blockers.append({"code": "COMPATIBILITY_GM_ADJUDICATION_REQUIRED", "method_id": method_id, "foundation_id": foundation_id})
        elif state == "CORRECTIVE_OPPORTUNITY":
            interface = self._matched_evidence_tag(result, "matched_repair_interface")
            foundation = self.foundations[foundation_id]
            interface_row = next((row for row in foundation["compatibility_traits"].get("repair_interfaces", []) if row.get("tag") == interface), None)
            accepted_practices = {name.removeprefix("Repair Practice — ") for name in (interface_row or {}).get("repair_practices", [])}
            valid = any(row.get("authority_type") == "repair_completion" and row.get("method_id") == method_id and row.get("foundation_id") == foundation_id and row.get("repair_interface") == interface and row.get("repair_practice_name") in accepted_practices and row.get("source_record_id") for row in records)
            if not valid:
                blockers.append({"code": "SPECIFIC_REPAIR_COMPLETION_REQUIRED", "method_id": method_id, "foundation_id": foundation_id, "repair_interface": interface, "accepted_repair_practices": sorted(accepted_practices)})
        elif state == "TRANSFORMATION_OPPORTUNITY":
            route = self._matched_evidence_tag(result, "matched_transformation_route")
            valid = any(row.get("authority_type") == "transformation_completion" and row.get("method_id") == method_id and row.get("foundation_id") == foundation_id and row.get("transformation_route") == route and row.get("completion_type") in {"FOUNDATION_CHALLENGE", "GM_AUTHORED_TRANSFORMATION_EVENT"} and row.get("source_record_id") for row in records)
            if not valid:
                blockers.append({"code": "SPECIFIC_TRANSFORMATION_COMPLETION_REQUIRED", "method_id": method_id, "foundation_id": foundation_id, "transformation_route": route})
        elif state in {"STRAINED", "WORKABLE_WITH_FRICTION"}:
            warnings.append({"code": "METHOD_FOUNDATION_COMPATIBILITY_WARNING", "state": state, "method_id": method_id, "foundation_id": foundation_id, "evidence": deepcopy(result.get("evidence") or [])})
        elif state not in {"NATURAL_AFFINITY", "WORKABLE"}:
            blockers.append({"code": "COMPATIBILITY_STATE_UNSUPPORTED", "state": state})
        return {"blockers": blockers, "warnings": warnings}

    def validate_background(self, background_id: str, *, selected_route_ids: dict[str, Any] | None = None, require_complete: bool = False) -> dict[str, Any]:
        row = self.backgrounds.get(background_id)
        if not row:
            raise FoundryError("NS1R_BACKGROUND_ID_UNKNOWN", "The selected Background is not accepted authority.")
        blockers = deepcopy(row["blockers"])
        routes = deepcopy(selected_route_ids or {})
        authority = self.background_route_authority[background_id]
        allowed_fields = {"background_route_record_id", "background_sphere_choice_id", "background_talent_choice_id", "origin_insight_choice_id", "ability_grant_mode_id", "equipment_authority_id", "skills_authority_id", "tools_languages_trades_authority_id"}
        for key in routes:
            if key not in allowed_fields:
                blockers.append({"code": "BACKGROUND_ROUTE_FIELD_UNKNOWN", "field": key})
        route_id = routes.get("background_route_record_id")
        matched_route = next((option for option in authority["route_options"] if option["background_route_record_id"] == route_id), None)
        if route_id and not matched_route:
            blockers.append({"code": "BACKGROUND_ROUTE_ID_UNKNOWN", "background_route_record_id": route_id})
        if matched_route:
            if routes.get("background_sphere_choice_id") != matched_route["background_sphere_choice_id"]:
                blockers.append({"code": "BACKGROUND_SPHERE_ROUTE_MISMATCH", "expected": matched_route["background_sphere_choice_id"], "actual": routes.get("background_sphere_choice_id")})
            if routes.get("background_talent_choice_id") != matched_route["background_talent_choice_id"]:
                blockers.append({"code": "BACKGROUND_TALENT_ROUTE_MISMATCH", "expected": matched_route["background_talent_choice_id"], "actual": routes.get("background_talent_choice_id")})
        insight_ids = {option["origin_insight_choice_id"] for option in authority["origin_insight_options"]}
        if routes.get("origin_insight_choice_id") and routes["origin_insight_choice_id"] not in insight_ids:
            blockers.append({"code": "BACKGROUND_ORIGIN_INSIGHT_ROUTE_UNKNOWN", "origin_insight_choice_id": routes["origin_insight_choice_id"]})
        ability_ids = {option["ability_grant_mode_id"] for option in authority["ability_grant_modes"]}
        if routes.get("ability_grant_mode_id") and routes["ability_grant_mode_id"] not in ability_ids:
            blockers.append({"code": "BACKGROUND_ABILITY_MODE_UNKNOWN", "ability_grant_mode_id": routes["ability_grant_mode_id"]})
        for field in ("equipment_authority_id", "skills_authority_id", "tools_languages_trades_authority_id"):
            if routes.get(field) and routes[field] != authority[field]:
                blockers.append({"code": "BACKGROUND_AUTHORITY_ROUTE_MISMATCH", "field": field, "expected": authority[field], "actual": routes[field]})
        if require_complete:
            required = {"background_route_record_id", "background_sphere_choice_id", "background_talent_choice_id", "origin_insight_choice_id", "ability_grant_mode_id", "equipment_authority_id", "skills_authority_id", "tools_languages_trades_authority_id"}
            for field in sorted(required):
                if field not in routes:
                    blockers.append({"code": "BACKGROUND_ROUTE_SELECTION_REQUIRED", "field": field})
        return {
            "schema": "Tianxia.BackgroundGrantValidation.v2", "background": deepcopy(row),
            "exact_route_authority": deepcopy(authority), "selected_routes": routes,
            "background_talent_separate_from_ordinary_talents": True,
            "ready": not blockers, "status": "READY" if not blockers else "BLOCKED", "blockers": blockers,
        }

    def readiness(self, state_or_project: dict[str, Any] | str) -> dict[str, Any]:
        state = self.get_state(state_or_project) if isinstance(state_or_project, str) else self._derive_state(state_or_project, operation="readiness")
        return deepcopy(state["readiness"])

    def migration_preview(self, legacy: dict[str, Any]) -> dict[str, Any]:
        path_ids = _unique_strings(list(legacy.get("path_ids") or []), code="NS1R_DUPLICATE_PATH_ID", field="legacy Path")
        method_ids = _unique_strings(list(legacy.get("method_ids") or []), code="NS1R_DUPLICATE_METHOD_ID", field="legacy Method")
        blockers: list[dict[str, Any]] = []
        inferred = None
        records = list(legacy.get("access_source_records") or [])
        blockers.extend(self.validate_access_source_records(records))
        for path_id in path_ids:
            if path_id not in CANONICAL_TO_COMPACT:
                blockers.append({"code": "LEGACY_PATH_MAPPING_REQUIRED", "path_id": path_id})
        if len(method_ids) == 1 and method_ids[0] in self.methods:
            candidate = self.methods[method_ids[0]]
            if not self.method_acquisition_satisfied(candidate, records):
                blockers.append({"code": "LEGACY_METHOD_ACQUISITION_EVIDENCE_REQUIRED", "method_id": method_ids[0]})
            active_compact = {CANONICAL_TO_COMPACT[path] for path in path_ids if path in CANONICAL_TO_COMPACT}
            granted = {row["path_id"] for row in candidate["explicit_ap_grants"] if row["grants_attainment_points"]}
            if not active_compact <= granted:
                blockers.append({"code": "LEGACY_PRIMARY_METHOD_ROUTE_CONFLICT", "method_id": method_ids[0], "active_path_ids": path_ids})
            if not blockers:
                inferred = method_ids[0]
        else:
            blockers.append({"code": "PRIMARY_METHOD_MIGRATION_REQUIRED", "message": "Exactly one accepted historical Method is required for deterministic inference."})
        return {"schema": "Tianxia.NS1RMigrationPreview.v2", "status": "DETERMINISTIC" if not blockers else "MIGRATION_REQUIRED", "inferred_primary_method_id": inferred, "persistent_path_tracks": [{"path_id": canonical, "attainment": int((legacy.get("path_attainment") or {}).get(canonical, 0))} for _, canonical, *_ in PATH_ORDER], "event_stream_rewrite": False, "retroactive_resource_grants": False, "blockers": blockers}

    def export_state(self, project_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row=conn.execute("SELECT state_json,state_hash FROM non_sphere_character_states WHERE project_id=?",(project_id,)).fetchone()
            evidence=[dict(r) for r in conn.execute("SELECT * FROM non_sphere_authority_evidence WHERE project_id=? ORDER BY evidence_id",(project_id,))]
            consumptions=[dict(r) for r in conn.execute("SELECT * FROM non_sphere_ap_consumptions WHERE project_id=? ORDER BY evidence_id,idempotency_key",(project_id,))]
        if not row: return None
        state=json.loads(row["state_json"])
        if sha256_json(state)!=row["state_hash"]: raise FoundryError("NS1R_STATE_HASH_MISMATCH","The persisted non-Sphere state failed its integrity check.")
        ledger={"evidence":evidence,"ap_consumptions":consumptions}
        return {"schema":"Tianxia.NonSphereStateExport.v2","state":state,"state_hash":sha256_json(state),"authority_snapshot_hash":self.authority_snapshot_hash,"evidence_ledger":ledger,"evidence_ledger_hash":sha256_json(ledger)}

    def validate_import_payload(
        self,
        project_id: str,
        payload: dict[str, Any],
        *,
        project_document: dict[str, Any] | None = None,
        _project_document_authority: object | None = None,
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        if project_document is not None and _project_document_authority is not _TRUSTED_PROJECT_IMPORT_BOUNDARY:
            raise FoundryError(
                "NS1R_IMPORTED_PROJECT_DOCUMENT_FORBIDDEN",
                "Imported trusted provenance may use a project document only at the authenticated project-import boundary.",
                status_code=403,
            )
        if payload.get("schema")!="Tianxia.NonSphereStateExport.v2" or payload.get("authority_snapshot_hash")!=self.authority_snapshot_hash:
            raise FoundryError("NS1R_IMPORTED_STATE_AUTHORITY_MISMATCH","Imported non-Sphere state uses an unsupported authority identity.")
        state=deepcopy(payload.get("state")); ledger=payload.get("evidence_ledger")
        if not isinstance(state,dict) or sha256_json(state)!=payload.get("state_hash") or not isinstance(ledger,dict) or sha256_json(ledger)!=payload.get("evidence_ledger_hash"):
            raise FoundryError("NS1R_IMPORTED_STATE_HASH_MISMATCH","Imported non-Sphere state or evidence ledger hash mismatch.")
        state["project_id"]=project_id
        evidence=ledger.get("evidence"); consumptions=ledger.get("ap_consumptions")
        if not isinstance(evidence,list) or not isinstance(consumptions,list): raise FoundryError("NS1R_IMPORTED_EVIDENCE_LEDGER_INVALID","Imported evidence ledger is malformed.")
        by_id={}
        for e in evidence:
            targets=json.loads(e["targets_json"]); core={"project_id":project_id,"authority_type":e["authority_type"],"targets":targets,"source_kind":e["source_kind"],"source_identity":e["source_identity"],"source_hash":e["source_hash"],"project_revision":e["project_revision"],"event_sequence":e["event_sequence"],"amount_awarded":e["amount_awarded"],"creation_authority":e["creation_authority"]}
            h=sha256_json(core); eid="nse_"+h[:32]
            if e["evidence_hash"]!=h or e["evidence_id"]!=eid or e["project_id"]!=project_id: raise FoundryError("NS1R_IMPORTED_EVIDENCE_MISMATCH","Imported evidence ID or hash is not deterministic.")
            if eid in by_id: raise FoundryError("NS1R_IMPORTED_EVIDENCE_DUPLICATE","Imported evidence is duplicated.")
            by_id[eid]=e
        seen=set(); sums={k:0 for k in by_id}; history={tx.get("idempotency_key"):tx for tx in state.get("ap_transaction_history",[]) if tx.get("kind")=="ADVANCEMENT"}
        for c in consumptions:
            key=c["idempotency_key"]
            if c["project_id"]!=project_id or c["evidence_id"] not in by_id or key in seen: raise FoundryError("NS1R_IMPORTED_AP_CONSUMPTION_INVALID","Imported AP consumption is duplicated or cross-project.")
            seen.add(key); blob=json.loads(c["transaction_json"]); tx=blob.get("transaction",{}); op={"evidence_id":c["evidence_id"],"method_id":tx.get("method_id"),"target_cl":by_id[c["evidence_id"]] and json.loads(by_id[c["evidence_id"]]["targets_json"]).get("target_cl"),"allocations":tx.get("allocations"),"burden_multiplier":tx.get("burden_multiplier"),"ap_spent":tx.get("ap_spent")}
            if sha256_json(op)!=c["operation_hash"] or tx.get("operation_hash")!=c["operation_hash"] or int(c["amount"])!=int(tx.get("ap_spent",-1)) or history.get(key,{}).get("operation_hash")!=c["operation_hash"]: raise FoundryError("NS1R_IMPORTED_AP_CONSUMPTION_MISMATCH","Imported AP consumption does not reconcile with operation history.")
            sums[c["evidence_id"]]+=int(c["amount"])
        for eid,e in by_id.items():
            if int(e.get("amount_consumed") or 0)!=sums[eid] or sums[eid]>int(e.get("amount_awarded") or 0): raise FoundryError("NS1R_IMPORTED_AP_BALANCE_MISMATCH","Imported AP balances do not reconcile with exact consumption rows.")

        # Import semantic validation runs before the destination evidence rows are
        # inserted. Resolve only the state's declared access evidence from the
        # already hash-verified imported ledger. Normal runtime validation remains
        # database-backed through resolve_evidence().
        imported_access_records: list[dict[str, Any]] = []
        for index, supplied in enumerate(state.get("access_source_records") or []):
            if not isinstance(supplied, dict) or not isinstance(supplied.get("evidence_id"), str):
                raise FoundryError(
                    "NS1R_IMPORTED_EVIDENCE_MISMATCH",
                    "Imported state contains malformed access evidence.",
                    details={"index": index},
                )
            evidence_row = by_id.get(supplied["evidence_id"])
            if evidence_row is None:
                raise FoundryError(
                    "NS1R_IMPORTED_EVIDENCE_MISMATCH",
                    "Imported state references evidence absent from its verified ledger.",
                    details={"index": index, "evidence_id": supplied["evidence_id"]},
                )
            targets = json.loads(evidence_row["targets_json"])
            projected = {
                "evidence_id": evidence_row["evidence_id"],
                "authority_type": evidence_row["authority_type"],
                "source_record_id": evidence_row["source_identity"],
                **targets,
                "source_hash": evidence_row["source_hash"],
            }
            if supplied != projected:
                raise FoundryError(
                    "NS1R_IMPORTED_EVIDENCE_MISMATCH",
                    "Imported access evidence projection differs from its verified ledger.",
                    details={"index": index, "evidence_id": supplied["evidence_id"]},
                )
            imported_access_records.append(projected)

        # Replay the authoritative attainment history. A resealed final state is not authority.
        history_rows=state.get("ap_transaction_history") or []
        if not isinstance(history_rows,list) or not history_rows:
            if any(int(row.get("attainment") or 0) for row in state.get("paths",[])):
                raise FoundryError("NS1R_IMPORTED_STATE_REPLAY_MISSING","Imported attained Paths require an exact initialization/advancement history.")
        replay={canonical:0 for canonical in CANONICAL_TO_COMPACT}
        prior_after=None
        advancement_keys=set()
        for index,tx in enumerate(history_rows):
            if not isinstance(tx,dict) or tx.get("schema")!="Tianxia.MethodAPAllocationTransaction.v1":
                raise FoundryError("NS1R_IMPORTED_STATE_REPLAY_INVALID","Imported AP history contains an invalid transaction.",details={"index":index})
            kind=tx.get("kind")
            if kind in {"INITIALIZATION","ADVANCEMENT"}:
                before=tx.get("before")
                if kind=="ADVANCEMENT":
                    expected_before=dict(replay)
                    if before!=expected_before or (prior_after is not None and before!=prior_after):
                        raise FoundryError("NS1R_IMPORTED_STATE_REPLAY_CHAIN_MISMATCH","Imported advancement before-state does not equal the prior replay state.",details={"index":index})
                    key=tx.get("idempotency_key")
                    if not isinstance(key,str) or key in advancement_keys:
                        raise FoundryError("NS1R_IMPORTED_STATE_REPLAY_DUPLICATE","Imported advancement history is duplicated or lacks idempotency identity.",details={"index":index})
                    advancement_keys.add(key)
                allocations=tx.get("allocations") or {}
                if not isinstance(allocations,dict):
                    raise FoundryError("NS1R_IMPORTED_STATE_REPLAY_INVALID","Imported allocation history is malformed.",details={"index":index})
                for path_id,amount in allocations.items():
                    if path_id not in replay or not isinstance(amount,int) or amount<0:
                        raise FoundryError("NS1R_IMPORTED_STATE_REPLAY_INVALID","Imported allocation history contains an invalid Path or amount.",details={"index":index})
                    replay[path_id]+=amount
                if kind=="ADVANCEMENT":
                    if tx.get("after")!=replay:
                        raise FoundryError("NS1R_IMPORTED_STATE_REPLAY_CHAIN_MISMATCH","Imported advancement after-state does not equal replay.",details={"index":index})
                    prior_after=dict(replay)
            elif kind=="METHOD_SWITCH_BASELINE":
                allocations=tx.get("allocations") or {}
                if any(int(allocations.get(pid,0))!=replay[pid] for pid in replay):
                    raise FoundryError("NS1R_IMPORTED_METHOD_SWITCH_REPLAY_MISMATCH","Imported Method-switch baseline differs from replayed attainment.",details={"index":index})
            else:
                raise FoundryError("NS1R_IMPORTED_STATE_REPLAY_INVALID","Imported AP history contains an unsupported transaction kind.",details={"index":index,"kind":kind})
        for record in state.get("administrative_attainment_history") or []:
            path_id=record.get("path_id")
            if path_id not in replay or int(record.get("before",-1))!=replay[path_id]:
                raise FoundryError("NS1R_IMPORTED_ADMIN_REPLAY_MISMATCH","Imported administrative attainment history does not continue replay.")
            replay[path_id]=int(record.get("after",-1))
        actual={row["path_id"]:int(row["attainment"]) for row in state.get("paths",[])}
        if replay!=actual or self.validate_attainment_history(state):
            raise FoundryError("NS1R_IMPORTED_FINAL_STATE_REPLAY_MISMATCH","Imported final Path attainments do not equal authoritative replay.",details={"replayed":replay,"actual":actual})
        if int(state.get("revision") or 0) < len([tx for tx in history_rows if tx.get("kind")=="ADVANCEMENT"]):
            raise FoundryError("NS1R_IMPORTED_STATE_REVISION_MISMATCH","Imported state revision is behind its advancement history.")
        derived=self._derive_state(
            deepcopy(state),
            operation="validate_import_payload",
            prevalidated_access_records=imported_access_records,
            project_document=project_document,
        )
        authority_fields=("paths","primary_method_id","known_method_ids","foundation_id","compatibility_result","revision")
        readiness_fields=("status","ready","blockers","warnings","blocker_count","warning_count","authority_snapshot_hash")
        if any(derived.get(field)!=state.get(field) for field in authority_fields) or any((derived.get("readiness") or {}).get(field)!=(state.get("readiness") or {}).get(field) for field in readiness_fields):
            raise FoundryError("NS1R_IMPORTED_FINAL_STATE_SEMANTIC_MISMATCH","Imported final state differs from shared semantic derivation.")
        return state, sha256_json(state), deepcopy(ledger)

    def import_state(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        state, _, _ = self.validate_import_payload(project_id, payload)
        return self.save_state(project_id, state, operation="import_state")
