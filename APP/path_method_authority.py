"""Shared Path/Method authority-contract helpers.

The character builder and the Stage 1 clipboard must derive the same
compatibility envelope.  This module deliberately contains no planning or
selection policy beyond the source-backed Path grant predicate: prose and
visible names are never used to decide compatibility.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from app.core import FoundryError

PATH_ORDER = (
    ("BODY_REFINING", "tianxia.path.body_refining", "Body Refining"),
    ("QI_CULTIVATION", "tianxia.path.qi_cultivation", "Qi Cultivation"),
    ("SPIRIT_AWAKENING", "tianxia.path.spirit_awakening", "Spirit Awakening"),
)
COMPACT_TO_CANONICAL = {compact: canonical for compact, canonical, _ in PATH_ORDER}
CANONICAL_TO_COMPACT = {canonical: compact for compact, canonical, _ in PATH_ORDER}
PATH_DISPLAY_NAMES = {canonical: display for _, canonical, display in PATH_ORDER}
CANONICAL_PATH_IDS = tuple(canonical for _, canonical, _ in PATH_ORDER)
MAX_ADVANCING_PATHS = len(CANONICAL_PATH_IDS)
NO_COMPATIBLE_METHOD_MESSAGE = "No compatible Cultivation Method supports every required advancing Path."


def canonicalize_path_ids(
    values: Iterable[str] | None,
    *,
    allow_empty: bool = True,
    max_paths: int = MAX_ADVANCING_PATHS,
) -> list[str]:
    """Validate and preserve canonical advancing-Path IDs in caller order."""

    if values is None:
        values = []
    if not isinstance(values, (list, tuple)):
        raise FoundryError(
            "NS1R_PATH_SELECTION_INVALID",
            "Advancing Path requirements must be a list of canonical Path IDs.",
        )
    if not values and not allow_empty:
        raise FoundryError(
            "NS1R_PATH_SELECTION_REQUIRED",
            "Choose at least one canonical advancing Path requirement.",
        )
    result: list[str] = []
    for path_id in values:
        if not isinstance(path_id, str) or not path_id:
            raise FoundryError(
                "NS1R_PATH_ID_INVALID",
                "Advancing Path requirements must use non-empty canonical Path IDs.",
                details={"path_id": path_id},
            )
        if path_id not in CANONICAL_TO_COMPACT:
            raise FoundryError(
                "NS1R_PATH_ID_UNKNOWN",
                "The selected Path ID is not canonical.",
                details={"path_id": path_id, "allowed_path_ids": list(CANONICAL_PATH_IDS)},
            )
        if path_id in result:
            raise FoundryError(
                "NS1R_DUPLICATE_PATH_ID",
                "Duplicate Path IDs are not permitted and are never silently normalized.",
                details={"path_id": path_id, "path_ids": list(values)},
            )
        result.append(path_id)
    if len(result) > max_paths:
        raise FoundryError(
            "NS1R_TOO_MANY_PATH_IDS",
            "No more than three canonical advancing Path requirements may be selected.",
            details={"maximum": max_paths, "actual": len(result)},
        )
    return result


def method_granted_path_ids(method: dict[str, Any]) -> list[str]:
    """Return the canonical Paths for which a Method explicitly grants AP."""

    canonical_candidates = method.get("related_choice_ids")
    if isinstance(canonical_candidates, list) and canonical_candidates:
        return canonicalize_path_ids(canonical_candidates)
    result: list[str] = []
    for grant in method.get("explicit_ap_grants") or []:
        if not isinstance(grant, dict) or not grant.get("grants_attainment_points"):
            continue
        raw_path_id = grant.get("path_id")
        canonical = COMPACT_TO_CANONICAL.get(raw_path_id, raw_path_id)
        if canonical in CANONICAL_TO_COMPACT and canonical not in result:
            result.append(canonical)
    return result


def method_path_compatibility(
    required_path_ids: Iterable[str] | None,
    method: dict[str, Any],
) -> dict[str, Any]:
    required = canonicalize_path_ids(required_path_ids)
    granted = method_granted_path_ids(method)
    missing = [path_id for path_id in required if path_id not in granted]
    return {
        "method_id": method.get("method_id"),
        "required_path_ids": required,
        "granted_path_ids": granted,
        "missing_path_ids": missing,
        "compatible": not missing,
    }


def compatible_method_ids(
    required_path_ids: Iterable[str] | None,
    methods: Iterable[dict[str, Any]],
) -> list[str]:
    required = canonicalize_path_ids(required_path_ids)
    result: list[str] = []
    for method in methods:
        if not isinstance(method, dict) or not isinstance(method.get("method_id"), str):
            continue
        if not method_path_compatibility(required, method)["missing_path_ids"]:
            result.append(method["method_id"])
    return sorted(set(result))


def compatibility_envelope(
    required_path_ids: Iterable[str] | None,
    methods: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic, readable authority envelope for planner callers."""

    required = canonicalize_path_ids(required_path_ids)
    method_rows = [deepcopy(row) for row in methods if isinstance(row, dict)]
    compatible = compatible_method_ids(required, method_rows)
    granted_by_method = {
        row["method_id"]: method_granted_path_ids(row)
        for row in method_rows
        if isinstance(row.get("method_id"), str)
    }
    return {
        "schema": "TianxiaFoundry.PathMethodAuthorityEnvelope.v1",
        "selection_semantics": "owner_required_advancing_paths",
        "all_path_ids": list(CANONICAL_PATH_IDS),
        "required_advancing_path_ids": required,
        "compatible_method_ids": compatible,
        "method_granted_path_ids": granted_by_method,
        "method_compatibility_predicate": "every required Path has an explicit Method AP grant",
        "level_zero_track_semantics": {
            "all_tracks_present": True,
            "initial_attainment": 0,
            "active_features": False,
            "foundation_expression": False,
            "resource_progression": False,
            "dormant_tracks_visible": True,
        },
        "method_access_note": "Compatibility does not grant access. Initial-creation and exact acquisition evidence remain separate server checks.",
    }


def no_compatible_method_error(required_path_ids: Iterable[str] | None) -> FoundryError:
    required = canonicalize_path_ids(required_path_ids, allow_empty=False)
    return FoundryError(
        "NS1R_NO_COMPATIBLE_METHOD_FOR_REQUIRED_PATHS",
        NO_COMPATIBLE_METHOD_MESSAGE,
        details={
            "required_path_ids": required,
            "expected": "one Method with an explicit AP grant for every required Path",
        },
    )
