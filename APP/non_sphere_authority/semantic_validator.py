from __future__ import annotations

from copy import deepcopy
from typing import Any


class NonSphereSemanticStateValidator:
    """Single semantic validator for NS1R-R1 state, import, API, UI, and persistence.

    Structural schema validation remains in the service. This validator applies only
    accepted Method, Path, Foundation, Background, acquisition, allocation, and
    compatibility authority. It mutates only deterministic derived/invalidation
    fields and never authored catalogs.
    """

    def __init__(self, service: Any):
        self.service = service

    def validate(
        self,
        state: dict[str, Any],
        *,
        operation: str,
        prevalidated_access_records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        state = deepcopy(state)
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        records = list(
            prevalidated_access_records
            if prevalidated_access_records is not None
            else state.get("access_source_records") or []
        )
        if prevalidated_access_records is None:
            blockers.extend(self.service.validate_access_source_records(records, state.get("project_id")))

        migration = state.get("migration") or {}
        migration_status = str(migration.get("status") or "")
        migration_preservation = migration_status.startswith("MIGRATION") or migration_status.startswith("LEGACY")

        # Method acquisition is required for every known/primary Method except the
        # one exact trusted initial-creation issuance context. That context is
        # recorded as immutable initial provenance; later re-selection/switching
        # still uses post-creation evidence.
        initial_method_ids = set(state.get("initial_creation_method_ids") or [])
        initial_method_active = bool(state.get("initial_creation_method_active"))
        primary = state.get("primary_method_id")
        for method_id in state.get("known_method_ids") or []:
            method = self.service.methods[method_id]
            if method_id in initial_method_ids and (method_id != primary or initial_method_active):
                continue
            if not self.service.method_acquisition_satisfied(method, records):
                blockers.append({
                    "code": "METHOD_ACQUISITION_EVIDENCE_REQUIRED",
                    "method_id": method_id,
                    "access_tier": method.get("acquisition", {}).get("access_tier"),
                    "migration_preservation": migration_preservation,
                    "message": "Exact character-specific Method acquisition evidence is required.",
                })
        primary = state.get("primary_method_id")
        if primary and primary not in set(state.get("known_method_ids") or []):
            blockers.append({"code": "PRIMARY_METHOD_NOT_KNOWN", "method_id": primary})

        method = self.service.methods.get(primary)
        granted = {
            row["path_id"]
            for row in (method or {}).get("explicit_ap_grants", [])
            if row.get("grants_attainment_points")
        }
        active_rows = [row for row in state["paths"] if row.get("attainment", 0) > 0]
        if active_rows and not primary:
            blockers.append({"code": "PRIMARY_METHOD_REQUIRED", "message": "Active Paths require one current Primary Method."})
        for row in active_rows:
            compact = self.service.CANONICAL_TO_COMPACT[row["path_id"]]
            if method and compact not in granted:
                historical_switch = any(
                    item.get("code") == "PRIMARY_METHOD_NO_FUTURE_AP_ROUTE" and item.get("method_id") == primary
                    for item in row.get("invalidations") or []
                )
                finding = {
                    "code": "ACTIVE_PATH_NOT_GRANTED_BY_PRIMARY_METHOD",
                    "path_id": row["path_id"],
                    "method_id": primary,
                    "historical_attainment_preserved": historical_switch,
                    "message": "Historical attainment is preserved, but the current Primary Method does not grant future AP to this Path.",
                }
                (warnings if historical_switch else blockers).append(finding)

        blockers.extend(self.service.validate_attainment_history(state))
        if method:
            blockers.extend(self.service.validate_allocation_state(state, method))

        # Exact dependent-choice invalidation. Invalid selections are cleared from
        # the active projection but their identity and cause remain in history.
        for path in state["paths"]:
            selection_id = path.get("subpath_or_tradition_id")
            if selection_id:
                choice = self.service.subpaths.get(selection_id)
                cause: dict[str, Any] | None = None
                if choice is None:
                    cause = {"code": "SUBPATH_AUTHORITY_UNKNOWN"}
                elif choice.get("owning_path_id") != path["path_id"]:
                    cause = {"code": "SUBPATH_PATH_AUTHORITY_MISMATCH", "owning_path_id": choice.get("owning_path_id")}
                else:
                    minimum_cl = self.service.subpath_minimum_cl(choice)
                    if int(path.get("attainment") or 0) < minimum_cl:
                        cause = {"code": "SUBPATH_MINIMUM_CL_NO_LONGER_MET", "minimum_cl": minimum_cl, "attainment": path.get("attainment")}
                    elif (choice.get("access") or {}).get("access_source_record_required") and not self.service.has_exact_access_record(
                        records,
                        "subpath_access",
                        selection_id=selection_id,
                        path_id=path["path_id"],
                    ):
                        cause = {
                            "code": "SUBPATH_EXACT_ACCESS_NO_LONGER_PRESENT",
                            "selection_id": selection_id,
                        }
                if cause:
                    invalidation = {
                        "code": "DEPENDENT_CHOICE_INVALIDATED",
                        "previous_selection_id": selection_id,
                        "path_id": path["path_id"],
                        "cause": cause,
                        "authority_identity": self.service.authority_snapshot_hash,
                        "preserved_history": True,
                        "operation": operation,
                    }
                    if invalidation not in path.setdefault("invalidations", []):
                        path["invalidations"].append(invalidation)
                    path["subpath_or_tradition_id"] = None
                    blockers.append(deepcopy(invalidation))

            minimum_required = 3
            if int(path.get("attainment") or 0) >= minimum_required and not path.get("subpath_or_tradition_id"):
                blockers.append({
                    "code": "MANDATORY_SUBPATH_OR_TRADITION_REQUIRED",
                    "path_id": path["path_id"],
                    "minimum_cl": minimum_required,
                    "message": "An active Path at CL3 or higher requires its exact Subpath or Tradition choice.",
                })

        foundation_projection = state.get("foundation_projection") or self.service._foundation_projection(state)
        if foundation_projection:
            for path_id in foundation_projection.get("unsupported_active_path_ids") or []:
                blockers.append({
                    "code": "FOUNDATION_ACTIVE_PATH_UNSUPPORTED",
                    "path_id": path_id,
                    "foundation_id": state.get("foundation_id"),
                    "message": "The selected Foundation does not support this active Path expression.",
                })

        compatibility = state.get("compatibility_result")
        if compatibility:
            compatibility_gate = self.service.compatibility_readiness(compatibility, records)
            blockers.extend(compatibility_gate["blockers"])
            warnings.extend(compatibility_gate["warnings"])

        background = state.get("background")
        if background:
            background_id = background.get("background_id")
            validation = self.service.validate_background(
                background_id,
                selected_route_ids=background.get("validated_routes") or {},
                require_complete=True,
            )
            background["validation"] = validation
            blockers.extend(deepcopy(validation["blockers"]))

        blockers.extend(deepcopy(migration.get("blockers") or []))

        # De-duplicate exact blocker/warning objects deterministically.
        def unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            seen: set[str] = set()
            out: list[dict[str, Any]] = []
            for row in rows:
                key = self.service.canonical_json(row)
                if key not in seen:
                    seen.add(key)
                    out.append(row)
            return out

        blockers = unique(blockers)
        warnings = unique(warnings)
        return {
            "state": state,
            "validation": {
                "schema": "Tianxia.NonSphereSemanticValidation.v1",
                "operation": operation,
                "status": "READY" if not blockers else "BLOCKED",
                "ready": not blockers,
                "blockers": blockers,
                "warnings": warnings,
                "blocker_count": len(blockers),
                "warning_count": len(warnings),
                "authority_snapshot_hash": self.service.authority_snapshot_hash,
            },
        }
