from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.authorities import GM_SCREEN_SHA256
from app.core import Database, FoundryError, Settings, canonical_json, sha256_bytes, sha256_file, sha256_json
from catalog.service import CatalogService
from character_sheet import CharacterSheetService
from factory_authoring import FactoryAuthoringWorkspaceService
from factory_authoring.command5_profile import CHARACTER_GM_PROFILE, CharacterGMCommand5Profile
from gm_export import GMCharacterExportService
from portable_character import PortableCharacterPackageService
from project_store.service import ProjectStore
from projector.verification import ProjectionVerifier
from vendor_adapter.service import FactoryAdapter


COMBAT_EVIDENCE_SCHEMA = "TianxiaFoundry.CharacterProductionCombatEvidence.v2"
COMBAT_RAW_SCHEMA = "TianxiaFoundry.CharacterProductionCombatRawEvidence.v2"
_COMBAT_FIELD_NAMES = frozenset({
    "combat",
    "combat_execution",
    "combat_runtime",
    "combat_sheet",
    "combat_ready_semantics",
    "combat_execution_pending",
    "combat_execution_ready",
    "combat_supported",
    "combat_requested",
    "combat_ready",
    "encounter",
    "controller_selection",
    "encounter_setup_required",
    "current_resource_requirements",
    "current_resources_required",
    "resource_initialization_requirements",
    "current_qi_required",
    "current_martial_focus_required",
    "qi_current_required",
    "martial_focus_current_required",
    "opponent_team_completion_required",
    "opponent_team_complete",
    "opponent_team_completed",
    "battlefield_choice",
    "battlefield_owner_choice",
    "battlefield_owner_choice_committed",
    "battlefield_selected",
    "battlefield_id",
    "token_placement",
    "token_placement_required",
    "token_placement_committed",
    "tokens_placed",
    "initiative",
    "initiative_attempted",
    "initiative_order",
    "initiative_method",
})
_COMBAT_REQUIRED_FIELDS = (
    "combat",
    "combat_execution",
    "combat_runtime",
    "combat_sheet",
    "combat_ready_semantics",
    "encounter",
    "controller_selection",
    "encounter_setup_required",
    "current_resource_requirements",
    "current_qi_required",
    "current_martial_focus_required",
    "opponent_team_completion_required",
    "battlefield_choice",
    "battlefield_owner_choice_committed",
    "token_placement",
    "token_placement_committed",
    "initiative",
    "initiative_attempted",
)
_COMBAT_READY_CLAIMS = frozenset({
    "COMBAT_READY",
    "COMBAT_RUNTIME_READY",
    "COMBAT_SHEET_READY",
    "RUNTIME_READY_PRE_ENCOUNTER",
    "RUNTIME_READY",
})
_COMBAT_RAW_EVIDENCE_NAMES = (
    "producer",
    "producer_output_profile",
    "producer_sheet",
    "producer_command5",
    "package",
    "clean_import",
    "installed",
    "reopened_sheet",
)
_COMBAT_EQUALITY_NAMES = frozenset({
    "producer_sheet_reopened_sheet_status_equal",
    "producer_command5_package_combat_execution_equal",
    "producer_command5_package_combat_surfaces_equal",
    "package_installed_audit_status_equal",
    "package_import_status_equal",
    "package_clean_import_installed_readiness_equal",
    "package_reopened_sheet_combat_semantics_equal",
    "all_corresponding_combat_semantics_equal",
    "evidence_schema_complete",
    "no_false_combat_ready",
})
_COMMAND5_COMBAT_STATUS_PATHS = {
    "report": ("report", "combat_execution"),
    "model_metadata": ("model", "metadata", "combat_execution"),
    "model_capability_readiness": ("model", "capability_readiness", "combat_execution"),
    "view_metadata": ("view", "metadata", "combat_execution"),
    "view_capability_readiness": ("view", "capability_readiness", "combat_execution"),
}
_PACKAGE_COMBAT_STATUS_PATHS = {
    "manifest": ("manifest", "combat_execution"),
    "readiness": ("readiness", "combat_execution"),
}


class CharacterProductionReleaseAdapter:
    """Bounded adapter over the established Command 5/6 release route."""

    def __init__(self, db: Database):
        self.db = db
        self.vendor = FactoryAdapter(db)
        self.portable = PortableCharacterPackageService(db)
        self.gm_export = GMCharacterExportService(db)

    _LOCATION_ROOT_FIELDS = {
        "artifact_path",
        "build",
        "build_manifest_path",
        "candidate_zip",
        "consumer_root",
        "copied_factory_zip",
        "deep_audit_path",
        "gm_model_path",
        "gm_view_model_path",
        "harness_package_path",
        "original_factory_zip",
        "package_path",
        "portable_character_zip",
        "seal_path",
        "workspace",
        "workspace_path",
    }
    _LOCATION_PATHS = {
        ("command5", "workspace"), ("command5", "build"), ("command5", "candidate_zip"),
        ("command5", "gm_model_path"), ("command5", "gm_view_model_path"),
        ("command5", "deep_audit_path"), ("command5", "build_manifest_path"),
        ("command6", "candidate_zip"), ("command6", "portable_character_zip"),
        ("command6", "workspace"), ("command6", "harness_package_path"),
        ("command6", "consumer_report", "consumer_root"),
        ("command6", "consumer_report", "harness_package_path"),
        ("command6", "consumer_report", "package_path"),
        ("portable_audit", "path"), ("clean_import", "first", "package_path"),
        ("clean_import", "second", "package_path"), ("registration", "package_path"),
        ("gm_export", "path"), ("consumer", "package_path"), ("consumer", "consumer_root"),
        ("consumer", "harness_package_path"),
        ("clean_import", "first", "installed_audit", "path"),
        ("clean_import", "second", "installed_audit", "path"),
        ("clean_import", "gm_model", "installed_package_path"),
        ("factory_authoring", "workspace_path"),
        ("completion_proof", "gm", "installed_package_path"),
        ("completion_proof", "gm", "producer_command5", "model_path"),
        ("completion_proof", "gm", "producer_command5", "view_path"),
    }
    _TIMESTAMP_ROOT_FIELDS = {"created_at", "updated_at", "verified_at"}
    _TIMESTAMP_PATHS = {
        ("command5", "created_at"), ("command6", "created_at"),
        ("portable_audit", "verified_at"), ("clean_import", "first", "verified_at"),
        ("clean_import", "second", "verified_at"), ("registration", "verified_at"),
    }
    _EXECUTION_LOG_ROOT_FIELDS = {"harness_run", "seal_run", "stdout", "stderr"}
    _EXECUTION_LOG_PATHS = {
        ("command5", "seal_run"), ("command6", "harness_run"),
        ("consumer", "harness_run"), ("consumer", "stdout"), ("consumer", "stderr"),
        ("command6", "consumer_report", "harness_run"),
        ("command6", "consumer_report", "duration_seconds"),
    }

    @classmethod
    def _is_location_path(cls, parent: tuple[str, ...], key: str) -> bool:
        path = (*parent, key.casefold())
        return (not parent and key.casefold() in cls._LOCATION_ROOT_FIELDS) or path in cls._LOCATION_PATHS

    @classmethod
    def _is_timestamp_path(cls, parent: tuple[str, ...], key: str) -> bool:
        path = (*parent, key.casefold())
        return (not parent and key.casefold() in cls._TIMESTAMP_ROOT_FIELDS) or path in cls._TIMESTAMP_PATHS

    @classmethod
    def _is_execution_log_path(cls, parent: tuple[str, ...], key: str) -> bool:
        path = (*parent, key.casefold())
        return (not parent and key.casefold() in cls._EXECUTION_LOG_ROOT_FIELDS) or path in cls._EXECUTION_LOG_PATHS

    @classmethod
    def _stable(cls, value: Any, *, _context: tuple[str, ...] = ()) -> Any:
        """Project release evidence without erasing mechanical identity.

        This projection deliberately does not use a recursive global blacklist:
        IDs, selected IDs, build values, source package keys, and fields nested
        under mechanics/content/identity remain identity-bearing.  Only known
        process locations, timestamps, and execution-log envelopes are omitted
        from the receipt identity.
        """
        if isinstance(value, dict):
            context = tuple(str(part).casefold() for part in _context)
            semantic_context = bool(
                set(context)
                & {"identity", "mechanics", "content", "model", "stats", "cultivation", "paths", "talents", "insights", "actions", "features", "readiness"}
            )
            normalized: dict[str, Any] = {}
            for key, item in sorted(value.items()):
                key_text = str(key)
                key_folded = key_text.casefold()
                path = (*context, key_folded)
                if cls._is_timestamp_path(context, key_text):
                    continue
                if cls._is_location_path(context, key_text):
                    continue
                if cls._is_execution_log_path(context, key_text) and not semantic_context:
                    continue
                if key_folded == "id" and "package_identity" in context:
                    continue
                if key_folded == "selected_id" and ("consumer" in context or "consumer_report" in context):
                    continue
                if key_folded == "path" and not (set(context) & {"identity", "mechanics", "cultivation", "paths"}):
                    continue
                normalized[key_text] = cls._stable(item, _context=(*_context, key_text))
            return normalized
        if isinstance(value, list):
            return [cls._stable(item, _context=_context) for item in value]
        return value

    @classmethod
    def _semantic_projection(cls, value: Any, *, _context: tuple[str, ...] = ()) -> Any:
        """Keep semantic/mechanical content while dropping only locations/time."""
        if isinstance(value, dict):
            normalized: dict[str, Any] = {}
            for key, item in sorted(value.items()):
                key_text = str(key)
                key_folded = key_text.casefold()
                context = tuple(str(part).casefold() for part in _context)
                if cls._is_timestamp_path(context, key_text):
                    continue
                if cls._is_location_path(context, key_text):
                    # Character identity/cultivation paths are mechanics; file
                    # and workspace paths are locations.  Preserve the former.
                    continue
                normalized[key_text] = cls._semantic_projection(item, _context=(*_context, key_text))
            return normalized
        if isinstance(value, list):
            return [cls._semantic_projection(item, _context=_context) for item in value]
        return value

    @classmethod
    def _semantic_hash(cls, value: Any) -> str:
        return sha256_json(cls._semantic_projection(value))

    @classmethod
    def _semantic_differences(cls, left: Any, right: Any, *, _path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        if len(_path) > 8:
            return [] if left == right else [{"path": ".".join(_path), "left": left, "right": right}]
        if isinstance(left, dict) and isinstance(right, dict):
            differences: list[dict[str, Any]] = []
            for key in sorted(set(left) | set(right)):
                if key not in left or key not in right:
                    differences.append({"path": ".".join((*_path, str(key))), "left": left.get(key), "right": right.get(key)})
                else:
                    differences.extend(cls._semantic_differences(left[key], right[key], _path=(*_path, str(key))))
                if len(differences) >= 20:
                    return differences[:20]
            return differences
        if isinstance(left, list) and isinstance(right, list):
            differences = []
            for index in range(max(len(left), len(right))):
                if index >= len(left) or index >= len(right):
                    differences.append({"path": ".".join((*_path, str(index))), "left": left[index] if index < len(left) else None, "right": right[index] if index < len(right) else None})
                else:
                    differences.extend(cls._semantic_differences(left[index], right[index], _path=(*_path, str(index))))
                if len(differences) >= 20:
                    return differences[:20]
            return differences
        return [] if left == right else [{"path": ".".join(_path), "left": left, "right": right}]

    @classmethod
    def _character_sheet_semantic_hash(cls, sheet: dict[str, Any], *, expected_gm_screen: str | None = None) -> str:
        """Hash owner-facing mechanical Sheet surfaces, not pipeline status."""
        readiness = deepcopy(sheet.get("readiness") or {})
        if expected_gm_screen is not None:
            readiness["gm_screen"] = expected_gm_screen
        return cls._semantic_hash(
            {
                "identity": sheet.get("identity"),
                "readiness": readiness,
                "owner_character_sheet": sheet.get("owner_character_sheet"),
            }
        )

    @classmethod
    def _package_model_proof(cls, package: Path) -> dict[str, Any]:
        with zipfile.ZipFile(package) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
            model_member = "Tianxia_GM_Character_Model_v2.json"
            view_member = "Tianxia_GM_Character_View_Model_v2.json"
            source_model_member = f"source/C2B3_{model_member}"
            source_view_member = f"source/C2B3_{view_member}"
            if source_model_member not in names or source_view_member not in names:
                raise FoundryError(
                    "CG1_GM_SOURCE_MODEL_EVIDENCE_MISSING",
                    "The completed package does not contain both authenticated source GM model files.",
                    details={"missing": sorted({source_model_member, source_view_member} - names)},
                    status_code=409,
                )
            model_bytes = archive.read(model_member)
            view_bytes = archive.read(view_member)
            source_model_bytes = archive.read(source_model_member)
            source_view_bytes = archive.read(source_view_member)
            model = json.loads(model_bytes)
            view = json.loads(view_bytes)
            source_model = json.loads(source_model_bytes)
            source_view = json.loads(source_view_bytes)
        identity = model.get("identity") or {}
        stats = model.get("stats") or {}
        cultivation = model.get("cultivation") or {}
        return {
            "model_sha256": sha256_bytes(model_bytes),
            "view_sha256": sha256_bytes(view_bytes),
            "source_model_sha256": sha256_bytes(source_model_bytes),
            "source_view_sha256": sha256_bytes(source_view_bytes),
            "model_semantic_hash": cls._semantic_hash(model),
            "view_semantic_hash": cls._semantic_hash(view),
            "source_model_semantic_hash": cls._semantic_hash(source_model),
            "source_view_semantic_hash": cls._semantic_hash(source_view),
            "source_package_view_semantic_hash": cls._semantic_hash(source_view),
            "source_conversion": deepcopy(manifest.get("source_model_conversion") or {}),
            "source_model_member": source_model_member,
            "source_view_member": source_view_member,
            "model_identity": cls._semantic_projection(model.get("identity") or {}),
            "model_current_cl": identity.get("cultivation_level") or identity.get("CL") or stats.get("cultivation_level") or stats.get("CL") or cultivation.get("cultivation_level") or cultivation.get("CL"),
            "model_paths": cls._semantic_projection((model.get("cultivation") or {}).get("paths") or (model.get("paths_subpaths_insights") or {}).get("paths") or []),
        }

    @classmethod
    def _command5_model_proof(cls, command5: dict[str, Any]) -> dict[str, Any]:
        model_path = Path(str(command5.get("gm_model_path") or ""))
        view_path = Path(str(command5.get("gm_view_model_path") or ""))
        if not model_path.is_file() or not view_path.is_file():
            raise FoundryError(
                "CG1_COMMAND5_MODEL_EVIDENCE_MISSING",
                "The durable Command 5 model/view files are missing.",
                details={"model_path": str(model_path), "view_path": str(view_path)},
                status_code=409,
            )
        model_bytes = model_path.read_bytes()
        view_bytes = view_path.read_bytes()
        model_sha256 = sha256_bytes(model_bytes)
        view_sha256 = sha256_bytes(view_bytes)
        expected_model_sha256 = command5.get("gm_model_sha256")
        expected_view_sha256 = command5.get("gm_view_model_sha256")
        if model_sha256 != expected_model_sha256 or view_sha256 != expected_view_sha256:
            raise FoundryError(
                "CG1_COMMAND5_MODEL_HASH_MISMATCH",
                "The durable Command 5 model/view bytes do not match their Command 5 receipt hashes.",
                details={
                    "model": {"expected": expected_model_sha256, "actual": model_sha256},
                    "view": {"expected": expected_view_sha256, "actual": view_sha256},
                },
                status_code=409,
            )
        try:
            model = json.loads(model_bytes)
            view = json.loads(view_bytes)
        except (TypeError, json.JSONDecodeError) as exc:
            raise FoundryError(
                "CG1_COMMAND5_MODEL_EVIDENCE_INVALID",
                "The durable Command 5 model/view files are not valid JSON.",
                details={"error": type(exc).__name__},
                status_code=409,
            ) from exc
        combat_evidence = cls._combat_raw({
            "report": command5,
            "model": model,
            "view": view,
        })
        command5_layer_status = cls._layer_combat_execution_status(
            combat_evidence,
            layer="command5",
        )
        if not command5_layer_status["valid"]:
            raise FoundryError(
                "CG1_COMMAND5_COMBAT_EXECUTION_STATUS_INVALID",
                "The Command-5 report/model/view layer-level combat execution statuses are missing or inconsistent.",
                details=command5_layer_status,
                status_code=409,
            )
        return {
            "model_sha256": model_sha256,
            "view_sha256": view_sha256,
            "model_semantic_hash": cls._semantic_hash(json.loads(model_bytes)),
            "view_semantic_hash": cls._semantic_hash(json.loads(view_bytes)),
            "model_path": str(model_path),
            "view_path": str(view_path),
            # Command 5 is a first-class producer layer.  Keep the report,
            # authoritative model, and derived view as separate nested inputs
            # so a status mismatch cannot be hidden by a model-wide hash.
            "combat_evidence": combat_evidence,
            "command5_layer_status": command5_layer_status,
        }

    @classmethod
    def _combat_raw(cls, value: dict[str, Any] | None) -> dict[str, Any]:
        """Project only explicitly combat-relevant evidence, losslessly.

        The release receipt contains large manifests, model documents, and
        import reports.  Hashing those whole objects would make unrelated
        process/audit details part of combat equality.  Instead, retain every
        occurrence of the named combat/setup fields with its source path and
        retain the exact output profile when one is supplied.  ``surface_values``
        is a path-independent, duplicate-free semantic view used only for
        cross-layer equality; ``occurrences`` remains the raw evidence.
        """
        source = value if isinstance(value, dict) else {}
        occurrences: list[dict[str, Any]] = []
        output_profile_present = "output_profile" in source
        output_profile = deepcopy(source.get("output_profile")) if output_profile_present else None

        def walk(node: Any, path: tuple[str, ...]) -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    key_text = str(key)
                    folded = key_text.casefold()
                    child_path = (*path, key_text)
                    if folded in _COMBAT_FIELD_NAMES:
                        occurrences.append({
                            "field": folded,
                            "path": ".".join(child_path),
                            "value": deepcopy(child),
                        })
                    walk(child, child_path)
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    walk(child, (*path, str(index)))

        walk(source, ())
        fields: dict[str, dict[str, Any]] = {}
        for occurrence in occurrences:
            field = occurrence["field"]
            bucket = fields.setdefault(field, {"occurrences": [], "values": []})
            bucket["occurrences"].append({
                "path": occurrence["path"],
                "value": deepcopy(occurrence["value"]),
            })

        # Values are sorted by canonical bytes so equality does not depend on
        # whether a producer writes readiness before manifest or vice versa.
        for bucket in fields.values():
            unique: dict[str, Any] = {}
            for occurrence in bucket["occurrences"]:
                encoded = canonical_json(occurrence["value"])
                unique.setdefault(encoded, deepcopy(occurrence["value"]))
            bucket["values"] = [unique[key] for key in sorted(unique)]

        surface_values = {
            field: deepcopy(bucket["values"])
            for field, bucket in sorted(fields.items())
        }
        result: dict[str, Any] = {
            "schema_version": COMBAT_RAW_SCHEMA,
            "output_profile_present": output_profile_present,
            "output_profile": output_profile,
            "occurrences": occurrences,
            "fields": fields,
            "surface_values": surface_values,
        }
        # Preserve the compact historical access shape for callers while the
        # lossless occurrence/value maps above remain authoritative.
        for field in _COMBAT_FIELD_NAMES:
            values = surface_values.get(field)
            if values:
                result[field] = deepcopy(values[0] if len(values) == 1 else values)
            else:
                result[field] = None
        return result

    @staticmethod
    def _path_tuple(path: Any) -> tuple[str, ...]:
        return tuple(part.casefold() for part in str(path or "").split(".") if part)

    @classmethod
    def _field_occurrences_at_paths(
        cls,
        raw: dict[str, Any] | None,
        field: str,
        paths: dict[str, tuple[str, ...]],
    ) -> dict[str, list[dict[str, Any]]]:
        fields = raw.get("fields") if isinstance(raw, dict) else None
        bucket = fields.get(field) if isinstance(fields, dict) else None
        occurrences = bucket.get("occurrences") if isinstance(bucket, dict) else None
        result = {name: [] for name in paths}
        if not isinstance(occurrences, list):
            return result
        normalized_paths = {name: tuple(part.casefold() for part in path) for name, path in paths.items()}
        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                continue
            path = cls._path_tuple(occurrence.get("path"))
            for name, expected in normalized_paths.items():
                if path == expected:
                    result[name].append(occurrence)
        return result

    @classmethod
    def _layer_combat_execution_status(
        cls,
        raw: dict[str, Any] | None,
        *,
        layer: str,
    ) -> dict[str, Any]:
        """Recompute exact layer-level combat execution status paths.

        Command 5 has one report status plus duplicated model/view envelope
        statuses.  Package readiness has manifest and readiness copies.  These
        paths are deliberately explicit: per-record action capabilities remain
        raw evidence but are never substituted for a layer-level status.
        """
        if layer == "command5":
            paths = _COMMAND5_COMBAT_STATUS_PATHS
            schema = "TianxiaFoundry.Command5LayerCombatExecutionStatus.v1"
        elif layer == "package":
            paths = _PACKAGE_COMBAT_STATUS_PATHS
            schema = "TianxiaFoundry.PackageLayerCombatExecutionStatus.v1"
        else:
            raise ValueError(f"Unsupported combat status layer: {layer}")
        occurrences = cls._field_occurrences_at_paths(raw, "combat_execution", paths)
        errors: list[dict[str, Any]] = []
        statuses: dict[str, Any] = {}
        for name in paths:
            matches = occurrences[name]
            if len(matches) != 1:
                errors.append({
                    "code": "COMBAT_EXECUTION_AUTHORITATIVE_PATH_MISSING_OR_DUPLICATE",
                    "layer": layer,
                    "path_name": name,
                    "path": ".".join(paths[name]),
                    "occurrence_count": len(matches),
                })
                continue
            value = matches[0].get("value")
            if not isinstance(value, str) or not value.strip():
                errors.append({
                    "code": "COMBAT_EXECUTION_AUTHORITATIVE_STATUS_INVALID",
                    "layer": layer,
                    "path_name": name,
                    "path": ".".join(paths[name]),
                    "value": deepcopy(value),
                })
                continue
            statuses[name] = value
        if statuses:
            distinct = sorted(set(statuses.values()))
            if len(distinct) != 1:
                errors.append({
                    "code": "COMBAT_EXECUTION_AUTHORITATIVE_STATUS_CONFLICT",
                    "layer": layer,
                    "statuses": deepcopy(statuses),
                })
        report_value = statuses.get("report") if layer == "command5" else None
        if layer == "command5" and "report" not in statuses:
            errors.append({
                "code": "COMMAND5_REPORT_COMBAT_EXECUTION_REQUIRED",
                "path": "report.combat_execution",
            })
        return {
            "schema_version": schema,
            "layer": layer,
            "required_paths": {name: ".".join(path) for name, path in paths.items()},
            "statuses": statuses,
            "report_combat_execution": report_value,
            "valid": not errors,
            "errors": errors,
        }

    @classmethod
    def _is_command5_combat_raw(cls, raw: dict[str, Any] | None) -> bool:
        fields = raw.get("fields") if isinstance(raw, dict) else None
        bucket = fields.get("combat_execution") if isinstance(fields, dict) else None
        occurrences = bucket.get("occurrences") if isinstance(bucket, dict) else None
        if not isinstance(occurrences, list):
            return False
        return any(
            cls._path_tuple(occurrence.get("path"))[:1] in {("report",), ("model",), ("view",)}
            for occurrence in occurrences
            if isinstance(occurrence, dict)
        )

    @classmethod
    def _combat_semantics(cls, raw: dict[str, Any] | None) -> dict[str, list[Any]]:
        if not isinstance(raw, dict):
            return {}
        fields = raw.get("fields")
        if isinstance(fields, dict):
            # A Character Sheet also contains owner-facing descriptions and
            # statistic subtrees whose names overlap the readiness vocabulary
            # (for example an initiative calculation and pending record
            # capabilities).  The corresponding cross-layer semantic surface
            # is the explicit readiness/model/manifest envelope.  Preserve all
            # other occurrences in the raw evidence, but do not compare those
            # unrelated containers as if they were package readiness claims.
            authoritative_markers = {
                "readiness",
                "combat_readiness",
                "capability_readiness",
                "metadata",
                "manifest",
            }
            semantic: dict[str, list[Any]] = {}
            for field, bucket in sorted(fields.items()):
                if not isinstance(bucket, dict) or not isinstance(bucket.get("occurrences"), list):
                    continue
                occurrences = bucket["occurrences"]
                if field == "combat_execution" and cls._is_command5_combat_raw(raw):
                    command5_paths = {
                        tuple(part.casefold() for part in path)
                        for path in _COMMAND5_COMBAT_STATUS_PATHS.values()
                    }
                    preferred = [
                        occurrence
                        for occurrence in occurrences
                        if cls._path_tuple(occurrence.get("path")) in command5_paths
                    ]
                else:
                    preferred = [
                        occurrence
                        for occurrence in occurrences
                        if authoritative_markers.intersection(
                            set(cls._path_tuple(occurrence.get("path")))
                        )
                    ]
                selected = preferred or occurrences
                unique: dict[str, Any] = {}
                for occurrence in selected:
                    if not isinstance(occurrence, dict) or "value" not in occurrence:
                        continue
                    encoded = canonical_json(occurrence["value"])
                    unique.setdefault(encoded, deepcopy(occurrence["value"]))
                if unique:
                    semantic[str(field)] = [unique[key] for key in sorted(unique)]
            return semantic
        values = raw.get("surface_values")
        if isinstance(values, dict):
            return {
                str(field): deepcopy(rows)
                for field, rows in values.items()
                if isinstance(rows, list)
            }
        # Compatibility with a pre-v2 in-memory evidence fixture.  It is
        # intentionally conservative: missing fields remain missing rather
        # than being replaced by a truthiness-based fallback.
        return {
            field: [deepcopy(raw[field])]
            for field in _COMBAT_FIELD_NAMES
            if field in raw and raw[field] is not None
        }

    @classmethod
    def _combat_fields_equal(
        cls,
        left: dict[str, Any] | None,
        right: dict[str, Any] | None,
        *,
        fields: tuple[str, ...] = _COMBAT_REQUIRED_FIELDS,
    ) -> bool:
        left_values = cls._combat_semantics(left)
        right_values = cls._combat_semantics(right)
        return all(left_values.get(field) == right_values.get(field) for field in fields)

    @staticmethod
    def _combat_value_contains_ready_claim(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().upper() in _COMBAT_READY_CLAIMS
        if isinstance(value, dict):
            return any(CharacterProductionReleaseAdapter._combat_value_contains_ready_claim(item) for item in value.values())
        if isinstance(value, list):
            return any(CharacterProductionReleaseAdapter._combat_value_contains_ready_claim(item) for item in value)
        return False

    @classmethod
    def _combat_no_false_ready_claim(
        cls,
        layers: dict[str, dict[str, Any]],
        output_profile: dict[str, Any] | None,
    ) -> bool:
        profile = output_profile if isinstance(output_profile, dict) else {}
        requested = profile.get("combat_ready") is True
        supported = profile.get("combat_supported")
        if supported is False:
            requested = False
        if requested:
            return True
        for raw in layers.values():
            semantics = cls._combat_semantics(raw)
            for field, values in semantics.items():
                if field in {"combat", "combat_execution", "combat_runtime", "combat_sheet", "combat_ready_semantics"}:
                    if any(cls._combat_value_contains_ready_claim(value) for value in values):
                        return False
        return True

    def _clean_import_proof(
        self,
        project_id: str,
        package: Path,
        *,
        producer_sheet: dict[str, Any],
        producer_command5: dict[str, Any],
        producer_output_profile: dict[str, Any] | None,
        package_model: dict[str, Any],
        consumer: dict[str, Any],
        audit: dict[str, Any],
        clean_import_root: Path | None = None,
    ) -> dict[str, Any]:
        producer_sheet_hash = self._character_sheet_semantic_hash(
            producer_sheet,
            expected_gm_screen="GM_READY_SOURCE_VERIFIED",
        )
        if clean_import_root is None:
            import_root_context = tempfile.TemporaryDirectory(prefix="cg1-clean-import-", ignore_cleanup_errors=True)
        else:
            durable_root = clean_import_root.resolve()
            shutil.rmtree(durable_root, ignore_errors=True)
            durable_root.mkdir(parents=True, exist_ok=True)
            import_root_context = nullcontext(str(durable_root))
        with import_root_context as td:
            root = Path(td)
            data = root / "data"
            data.mkdir()
            # Preserve authenticated producer/catalog configuration, but remove the character.
            for child in self.db.settings.data_dir.iterdir():
                if child.name == self.db.settings.db_path.name or child.name.endswith(("-wal", "-shm")):
                    continue
                dest = data / child.name
                if child.is_dir(): shutil.copytree(child, dest, symlinks=True)
                else: shutil.copy2(child, dest)
            # A clean import proof is an actually new database, not a copied
            # database with immutable project rows surgically removed. The
            # authenticated Factory/configuration files remain available, while
            # the portable package supplies the complete project snapshot.
            shutil.rmtree(data / "portable_characters" / project_id, ignore_errors=True)
            settings = Settings.from_env(self.db.settings.root_dir, data)
            clean_db = Database(settings); clean_db.migrate()
            clean_vendor = FactoryAdapter(clean_db).status()
            factory_root = Path(clean_vendor.get("factory_root") or "")
            if not factory_root.is_dir():
                raise FoundryError("CG1_CLEAN_IMPORT_FACTORY_NOT_READY", "The clean import root does not retain authenticated Factory authority.", details=clean_vendor)
            CatalogService(clean_db).rebuild_core(factory_root)
            service = PortableCharacterPackageService(clean_db)
            first = service.import_into_factory(package)
            reopened_db = Database(settings)
            reopened_db.migrate()
            reopened_project = ProjectStore(reopened_db).get_project(project_id)
            reopened_sheet = CharacterSheetService(reopened_db).sheet(project_id)
            second = PortableCharacterPackageService(reopened_db).import_into_factory(package)
            if first.get("status") != "IMPORTED" or second.get("status") != "ALREADY_INSTALLED_IDENTICAL":
                raise FoundryError("CG1_CLEAN_IMPORT_PROOF_FAILED", "The portable Character did not pass clean import and identical re-import.", details={"first": first, "second": second})
            installed_path = Path(str(first.get("package_path") or (settings.data_dir / "portable_characters" / project_id / "current.zip")))
            installed_sha256 = sha256_file(installed_path) if installed_path.is_file() else None
            if installed_sha256 != audit.get("sha256"):
                raise FoundryError(
                    "CG1_CLEAN_IMPORT_INSTALLED_PACKAGE_MISMATCH",
                    "The clean-root installed package does not match the original completed package.",
                    details={"original_sha256": audit.get("sha256"), "installed_sha256": installed_sha256, "installed_path": str(installed_path)},
                    status_code=409,
                )
            installed_audit = self.portable.audit(installed_path)
            installed_model = self._package_model_proof(installed_path)
            reopened_sheet_hash = self._character_sheet_semantic_hash(
                reopened_sheet,
                expected_gm_screen="GM_READY_SOURCE_VERIFIED",
            )
            sheet_equality = producer_sheet_hash == reopened_sheet_hash
            if not sheet_equality:
                producer_sheet_semantics = self._semantic_projection(
                    {
                        "identity": producer_sheet.get("identity"),
                        "readiness": {
                            **(producer_sheet.get("readiness") or {}),
                            "gm_screen": "GM_READY_SOURCE_VERIFIED",
                        },
                        "owner_character_sheet": producer_sheet.get("owner_character_sheet"),
                    }
                )
                reopened_sheet_semantics = self._semantic_projection(
                    {
                        "identity": reopened_sheet.get("identity"),
                        "readiness": {
                            **(reopened_sheet.get("readiness") or {}),
                            "gm_screen": "GM_READY_SOURCE_VERIFIED",
                        },
                        "owner_character_sheet": reopened_sheet.get("owner_character_sheet"),
                    }
                )
                raise FoundryError(
                    "CG1_CLEAN_IMPORT_SHEET_SEMANTICS_DIVERGED",
                    "The clean-root Character Sheet semantic projection differs from the producer Sheet.",
                    details={
                        "producer_semantic_hash": producer_sheet_hash,
                        "reopened_semantic_hash": reopened_sheet_hash,
                        "differences": self._semantic_differences(producer_sheet_semantics, reopened_sheet_semantics),
                    },
                )
            conversion = package_model.get("source_conversion") or {}
            conversion_evidence = {
                "schema_version": conversion.get("schema_version"),
                "command5_model_sha256": conversion.get("command5_model_sha256"),
                "command5_view_model_sha256": conversion.get("command5_view_model_sha256"),
                "package_source_model_sha256": conversion.get("package_source_model_sha256"),
                "package_source_view_sha256": conversion.get("package_source_view_sha256"),
                "producer_model_bytes_bound": producer_command5.get("model_sha256") == conversion.get("command5_model_sha256"),
                "producer_view_bytes_bound": producer_command5.get("view_sha256") == conversion.get("command5_view_model_sha256"),
                "package_source_model_bound": package_model.get("source_model_sha256") == conversion.get("package_source_model_sha256"),
                "package_source_view_bound": package_model.get("source_view_sha256") == conversion.get("package_source_view_sha256"),
                "producer_source_view_semantic_equal": producer_command5.get("view_semantic_hash") == package_model.get("source_view_semantic_hash"),
            }
            conversion_evidence["valid"] = all(
                conversion_evidence[key]
                for key in (
                    "producer_model_bytes_bound",
                    "producer_view_bytes_bound",
                    "package_source_model_bound",
                    "package_source_view_bound",
                    "producer_source_view_semantic_equal",
                )
            )
            gm_equalities = {
                "producer_package_conversion_equal": conversion_evidence["valid"],
                "package_installed_model_semantic_equal": package_model.get("model_semantic_hash") == installed_model.get("model_semantic_hash"),
                "package_installed_view_semantic_equal": package_model.get("view_semantic_hash") == installed_model.get("view_semantic_hash"),
                "package_installed_source_model_semantic_equal": package_model.get("source_model_semantic_hash") == installed_model.get("source_model_semantic_hash"),
                "package_installed_source_view_semantic_equal": package_model.get("source_view_semantic_hash") == installed_model.get("source_view_semantic_hash"),
                "package_installed_bytes_equal": installed_sha256 == audit.get("sha256"),
            }
            gm_equality = all(gm_equalities.values())
            if not gm_equality:
                raise FoundryError(
                    "CG1_CLEAN_IMPORT_GM_SEMANTICS_DIVERGED",
                    "The clean-root import did not preserve the authoritative GM model semantics.",
                    details={
                        "producer_command5": producer_command5,
                        "package": package_model,
                        "installed": installed_model,
                        "conversion": conversion_evidence,
                        "equalities": gm_equalities,
                    },
                )
            producer_output_profile_combat = self._combat_raw({
                "output_profile": deepcopy(producer_output_profile) if isinstance(producer_output_profile, dict) else {},
            })
            producer_sheet_combat = self._combat_raw(producer_sheet)
            producer_command5_combat = (
                deepcopy(producer_command5.get("combat_evidence"))
                if isinstance(producer_command5, dict) and isinstance(producer_command5.get("combat_evidence"), dict)
                else self._combat_raw(producer_command5)
            )
            package_combat = self._combat_raw(audit)
            clean_import_combat = self._combat_raw(first)
            installed_combat = self._combat_raw(installed_audit)
            reopened_sheet_combat = self._combat_raw(reopened_sheet)
            command5_layer_status = self._layer_combat_execution_status(
                producer_command5_combat,
                layer="command5",
            )
            package_layer_status = self._layer_combat_execution_status(
                package_combat,
                layer="package",
            )
            combat_layers = {
                "producer_sheet": producer_sheet_combat,
                "producer_command5": producer_command5_combat,
                "package": package_combat,
                "clean_import": clean_import_combat,
                "installed": installed_combat,
                "reopened_sheet": reopened_sheet_combat,
            }
            complete_schema = {
                name: all(field in self._combat_semantics(raw) for field in _COMBAT_REQUIRED_FIELDS)
                for name, raw in combat_layers.items()
            }
            complete_schema["producer_command5"] = complete_schema["producer_command5"] and command5_layer_status["valid"]
            complete_schema["package"] = complete_schema["package"] and package_layer_status["valid"]
            producer_sheet_reopened_equal = self._combat_fields_equal(
                producer_sheet_combat,
                reopened_sheet_combat,
            )
            command5_package_execution_equal = (
                command5_layer_status["valid"]
                and package_layer_status["valid"]
                and command5_layer_status.get("report_combat_execution")
                == package_layer_status.get("statuses", {}).get("manifest")
                == package_layer_status.get("statuses", {}).get("readiness")
                and self._combat_fields_equal(
                    producer_command5_combat,
                    package_combat,
                    fields=("combat_execution",),
                )
            )
            command5_package_surfaces_equal = self._combat_fields_equal(
                producer_command5_combat,
                package_combat,
            ) and command5_package_execution_equal
            package_installed_equal = self._combat_fields_equal(
                package_combat,
                installed_combat,
            )
            package_import_equal = self._combat_fields_equal(
                package_combat,
                clean_import_combat,
            )
            package_clean_installed_equal = self._combat_fields_equal(
                clean_import_combat,
                installed_combat,
            )
            package_reopened_equal = self._combat_fields_equal(
                package_combat,
                reopened_sheet_combat,
            )
            no_false_combat_ready = self._combat_no_false_ready_claim(
                combat_layers,
                producer_output_profile if isinstance(producer_output_profile, dict) else {},
            )
            combat_equalities = {
                "producer_sheet_reopened_sheet_status_equal": producer_sheet_reopened_equal,
                "producer_command5_package_combat_execution_equal": command5_package_execution_equal,
                "producer_command5_package_combat_surfaces_equal": command5_package_surfaces_equal,
                "package_installed_audit_status_equal": package_installed_equal,
                "package_import_status_equal": package_import_equal,
                "package_clean_import_installed_readiness_equal": package_clean_installed_equal,
                "package_reopened_sheet_combat_semantics_equal": package_reopened_equal,
                "all_corresponding_combat_semantics_equal": all(
                    (
                        producer_sheet_reopened_equal,
                        command5_package_execution_equal,
                        command5_package_surfaces_equal,
                        package_installed_equal,
                        package_import_equal,
                        package_clean_installed_equal,
                        package_reopened_equal,
                    )
                ),
                "evidence_schema_complete": all(complete_schema.values()),
                "no_false_combat_ready": no_false_combat_ready,
            }
            producer_combat = {
                "output_profile_requested": (
                    isinstance(producer_output_profile, dict)
                    and producer_output_profile.get("combat_ready") is True
                ),
                "output_profile": producer_output_profile_combat,
                "character_sheet": producer_sheet_combat,
                "command5": producer_command5_combat,
            }
            combat_evidence = {
                "schema_version": COMBAT_EVIDENCE_SCHEMA,
                "producer": producer_combat,
                "package": package_combat,
                "clean_import": {"import_report": clean_import_combat, "installed_audit": installed_combat, "reopened_sheet": reopened_sheet_combat},
                "raw_evidence_hashes": {
                    "producer": sha256_json(producer_combat),
                    "producer_output_profile": sha256_json(producer_output_profile_combat),
                    "producer_sheet": sha256_json(producer_sheet_combat),
                    "producer_command5": sha256_json(producer_command5_combat),
                    "package": sha256_json(package_combat),
                    "clean_import": sha256_json(clean_import_combat),
                    "installed": sha256_json(installed_combat),
                    "reopened_sheet": sha256_json(reopened_sheet_combat),
                },
                "semantic_projections": {
                    name: self._combat_semantics(raw)
                    for name, raw in {
                        "producer_output_profile": producer_output_profile_combat,
                        **combat_layers,
                    }.items()
                },
                "layer_status": {
                    "producer_command5": command5_layer_status,
                    "package": package_layer_status,
                },
                "schema_presence": complete_schema,
                "equalities": combat_equalities,
                "equality": all(combat_equalities.values()),
            }
            if not combat_evidence["equality"]:
                raise FoundryError(
                    "CG1_CLEAN_IMPORT_COMBAT_EVIDENCE_DIVERGED",
                    "Producer, package, installed, and reopened combat evidence did not match exactly.",
                    details=combat_evidence,
                    status_code=409,
                )
            return {
                "first": first,
                "reopen": {
                    "project_id": reopened_project["project"]["project_id"],
                    "project_revision": reopened_project["project"]["revision"],
                    "character_sheet_project_id": reopened_sheet["project_id"],
                    "character_sheet_build_status": reopened_sheet["build_status"],
                },
                "second": second,
                "character_sheet": {
                    "producer_semantic_hash": producer_sheet_hash,
                    "reopened_semantic_hash": reopened_sheet_hash,
                    "semantic_equal": sheet_equality,
                },
                "gm_model": {
                    "producer_semantic_hash": producer_command5.get("model_semantic_hash"),
                    "producer_model_sha256": producer_command5.get("model_sha256"),
                    "producer_view_semantic_hash": producer_command5.get("view_semantic_hash"),
                    "package_semantic_hash": package_model.get("model_semantic_hash"),
                    "installed_semantic_hash": installed_model.get("model_semantic_hash"),
                    "source_model_semantic_hash": package_model.get("source_model_semantic_hash"),
                    "source_view_semantic_hash": package_model.get("source_view_semantic_hash"),
                    "package_view_semantic_hash": package_model.get("view_semantic_hash"),
                    "installed_source_model_semantic_hash": installed_model.get("source_model_semantic_hash"),
                    "installed_source_view_semantic_hash": installed_model.get("source_view_semantic_hash"),
                    "model_current_cl": package_model.get("model_current_cl"),
                    "model_paths": deepcopy(package_model.get("model_paths") or []),
                    "semantic_equal": gm_equality,
                    "source_conversion": conversion_evidence,
                    "equalities": gm_equalities,
                    "package_sha256": audit.get("sha256"),
                    "installed_package_sha256": installed_sha256,
                    "installed_package_path": str(installed_path),
                },
                "consumer": {
                    "status": consumer.get("status"),
                    "semantic_hash": consumer.get("semantic_hash"),
                    "status_equal": consumer.get("status") == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED",
                },
                "combat": combat_evidence,
            }

    def readiness(self) -> dict[str, Any]:
        vendor = self.vendor.status()
        gm_archive = self.gm_export.bundled_gm_zip
        gm_hash = sha256_file(gm_archive) if gm_archive.is_file() else None
        checks = {
            "authenticated_factory": bool(vendor.get("configured") and vendor.get("health") == "READY"),
            "physical_gm_screen": bool(gm_hash == GM_SCREEN_SHA256),
            "exact_consumer_runtime": bool((self.db.settings.root_dir / "gm_export" / "exact_consumer_harness.py").is_file()),
            "command5_command6_route": bool(
                callable(getattr(CharacterGMCommand5Profile, "command5", None))
                and callable(getattr(ProjectionVerifier, "command6", None))
            ),
            "portable_audit_import_registration": all(
                callable(getattr(self.portable, name, None))
                for name in ("audit", "import_into_factory", "register_verified")
            ),
        }
        return {
            "schema": "TianxiaFoundry.CharacterProductionAuthorityReadiness.v1",
            "ready": all(checks.values()),
            "checks": checks,
            "factory": vendor,
            "gm_screen": {"expected_sha256": GM_SCREEN_SHA256, "actual_sha256": gm_hash},
        }

    @staticmethod
    def _fail(phase: str, fail_after: str | None) -> None:
        aliases = {
            "factory_authoring": "factory_authoring",
            "command5": "command5",
            "command6": "command6",
            "gm_consumer": "exact_gm_consumer",
            "portable_audit": "package_audit",
            "clean_import": "first_clean_import",
            "identical_reimport": "identical_reimport",
            "portable_registration": "verified_registration",
            "gm_export": "downstream_gm_export",
        }
        if fail_after == phase or aliases.get(fail_after or "") == phase:
            raise RuntimeError(f"forced production failure after {phase}")

    def compile(
        self,
        project_id: str,
        *,
        output_root: Path,
        register: bool = False,
        fail_after: str | None = None,
        output_profile: dict[str, Any] | None = None,
        clean_import_root: Path | None = None,
    ) -> dict[str, Any]:
        readiness = self.readiness()
        if not readiness["ready"]:
            raise FoundryError("CG1_PRODUCTION_AUTHORITY_NOT_READY", "The production release authority is not ready.", details=readiness)
        vendor = readiness["factory"]
        factory_root = Path(vendor["factory_root"])
        gm_root = self.gm_export._gm_screen_root()
        authoring = FactoryAuthoringWorkspaceService(self.db).build(project_id)
        self._fail("factory_authoring", fail_after)
        command5 = CharacterGMCommand5Profile(self.db, factory_root=factory_root).command5(project_id, output_root=output_root / "command5")
        self._fail("command5", fail_after)
        verifier = ProjectionVerifier(self.db, factory_root=factory_root, gm_screen_root=gm_root)
        command6 = verifier.command6(project_id, command5_report=command5, workspace=Path(command5["workspace"]), output_dir=output_root / "portable", build_profile=CHARACTER_GM_PROFILE)
        self._fail("command6", fail_after)
        package = Path(command6["portable_character_zip"])
        consumer = command6.get("consumer_report") or {}
        if consumer.get("status") != "GM_SCREEN_SOURCE_CONSUMER_VERIFIED":
            raise FoundryError("CG1_EXACT_GM_CONSUMER_FAILED", "The exact bundled GM consumer did not verify the portable Character.", details=consumer)
        self._fail("exact_gm_consumer", fail_after)
        audit = self.portable.audit(package)
        self._fail("package_audit", fail_after)
        producer_sheet = CharacterSheetService(self.db).sheet(project_id)
        producer_command5 = self._command5_model_proof(command5)
        package_model = self._package_model_proof(package)
        imports = self._clean_import_proof(
            project_id,
            package,
            producer_sheet=producer_sheet,
            producer_command5=producer_command5,
            producer_output_profile=output_profile,
            package_model=package_model,
            consumer=consumer,
            audit=audit,
            clean_import_root=clean_import_root,
        )
        self._fail("first_clean_import", fail_after)
        self._fail("identical_reimport", fail_after)
        registration = None; gm_export = None
        if register:
            registration = self.portable.register_verified(project_id, package=package, command6_report=command6, consumer_report=consumer, factory_import_report=imports["first"])
            self._fail("verified_registration", fail_after)
            gm_export = self.gm_export.export(project_id)
            self._fail("downstream_gm_export", fail_after)
        package_sha256 = sha256_file(package)
        completion_proof = {
            "schema": "TianxiaFoundry.CharacterProductionCompletionProof.v1",
            "package": {
                "filename": package.name,
                "path": str(package),
                "bytes": package.stat().st_size,
                "sha256": package_sha256,
                "audit_sha256": audit.get("sha256"),
                "audit_bytes": audit.get("bytes"),
                "member_inventory_sha256": audit.get("member_inventory_sha256"),
                "member_inventory": deepcopy(audit.get("member_inventory") or []),
                "checksum_manifest": deepcopy(audit.get("checksum_manifest") or {}),
                "crc_validation": deepcopy(audit.get("crc_validation") or {}),
            },
            "character_sheet": deepcopy(imports.get("character_sheet") or {}),
            "gm": {
                **deepcopy(imports.get("gm_model") or {}),
                "producer_command5": deepcopy(producer_command5),
                "producer_command5_model_sha256": command5.get("gm_model_sha256"),
                "source_package_sha256": package_sha256,
            },
            "consumer": deepcopy(imports.get("consumer") or {}),
            "clean_import": {
                "first_status": imports.get("first", {}).get("status"),
                "second_status": imports.get("second", {}).get("status"),
                "identical_reimport": imports.get("second", {}).get("status") == "ALREADY_INSTALLED_IDENTICAL",
            },
            "combat": deepcopy(imports.get("combat") or {}),
        }
        receipt = {
            "schema": "TianxiaFoundry.CharacterProductionReleaseReceipt.v1",
            "project_id": project_id,
            "authority_readiness": readiness,
            "factory_authoring": authoring,
            "command5": command5,
            "gm_model_sha256": command5.get("candidate_sha256"),
            "command6": command6,
            "portable_zip_sha256": package_sha256,
            "portable_audit": audit,
            "consumer": consumer,
            "clean_import": imports,
            "registration": registration,
            "gm_export": gm_export,
            "combat_readiness": completion_proof["combat"],
            "completion_proof": completion_proof,
        }
        receipt["production_artifact_identity"] = sha256_json(self._stable({
            key: receipt[key]
            for key in (
                "project_id", "authority_readiness", "factory_authoring",
                "command5", "gm_model_sha256", "command6",
                "portable_zip_sha256", "portable_audit", "consumer",
                "clean_import", "combat_readiness",
            )
        }))
        receipt["stable_identity"] = sha256_json(self._stable(receipt))
        return receipt
