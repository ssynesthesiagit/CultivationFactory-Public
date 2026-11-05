"""Compile typed Method profiles into the existing causal formula contract.

The caller authenticates the registry and selected record. This module does
not select a Method, grant access, activate it, or calculate a second set of
resource totals. Stage 2 evaluates these formulas after causal activation.
"""

from copy import deepcopy
from collections.abc import Mapping
import re
from typing import Any

from app.core import FoundryError, canonical_json, sha256_json


METHOD_MECHANICS_SCHEMA = "TianxiaFoundry.MethodMechanicalAuthority.v1"
METHOD_MECHANICS_PACK_VERSION = "0.6.0-mechanics.1"
_INITIAL_METHOD_MECHANICS_POLICY_V1 = {
    "schema": "TianxiaFoundry.InitialMethodMechanicsPolicy.v1",
    "selected_primary_method": "activate_after_acquisition",
    "resource_maximum": "source_typed_profiles",
    "refill_current": False,
}
INITIAL_METHOD_MECHANICS_POLICY = {
    **_INITIAL_METHOD_MECHANICS_POLICY_V1,
    "schema": "TianxiaFoundry.InitialMethodMechanicsPolicy.v2",
    "record_version": METHOD_MECHANICS_PACK_VERSION,
}
_PATH_RESOURCES = {
    "BODY_REFINING": ("tianxia.resource.stamina", "Stamina"),
    "QI_CULTIVATION": ("tianxia.resource.qi", "Qi"),
    "SPIRIT_AWAKENING": ("tianxia.resource.resonance", "Resonance"),
}


def has_acquired_method(method: Any) -> bool:
    """Recognize ownership through activation in an authenticated projection.

    Consumers use this lifecycle predicate only after their normal projection
    proof checks. It does not grant acquisition or authenticate a record.
    """
    return (
        isinstance(method, Mapping)
        and method.get("state") in {"acquired", "active"}
        and bool(method.get("record_id"))
    )


def uses_initial_method_mechanics(request: dict[str, Any]) -> bool:
    """Read an authenticated request's version, preserving historical absence."""
    authority = request.get("server_owned_authority") or {}
    if not isinstance(authority, dict):
        raise FoundryError("CG1_METHOD_MECHANICS_POLICY_INVALID", "The frozen server authority must be an object.")
    if "initial_method_mechanics_policy" not in authority:
        return False
    if canonical_json(authority["initial_method_mechanics_policy"]) not in {
        canonical_json(_INITIAL_METHOD_MECHANICS_POLICY_V1),
        canonical_json(INITIAL_METHOD_MECHANICS_POLICY),
    }:
        raise FoundryError("CG1_METHOD_MECHANICS_POLICY_INVALID", "The frozen Method mechanics policy is unsupported or changed.")
    return True


def initial_method_record_version(request: dict[str, Any]) -> str | None:
    """Select an installed derivation from an exact authenticated policy.

    Historical v1 explicitly meant the first mechanics derivation. Absence
    retains the source snapshot's version; it never means the newest version.
    """
    return METHOD_MECHANICS_PACK_VERSION if uses_initial_method_mechanics(request) else None


def compile_method_mechanics(method: dict[str, Any], registry_sha256: str) -> dict[str, Any]:
    """Translate every independent typed Path profile without prose inference."""
    def invalid(reason: str) -> None:
        raise FoundryError(
            "NS1R_METHOD_MECHANICS_AUTHORITY_INVALID",
            "The authenticated Method has incomplete or inconsistent mechanical authority.",
            details={"method_id": method.get("method_id"), "reason": reason},
            status_code=409,
        )

    method_id = method.get("method_id")
    if not isinstance(method_id, str) or not re.fullmatch(r"METHOD-\d{3}", method_id):
        invalid("method_identity")
    if not isinstance(registry_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", registry_sha256):
        invalid("registry_commitment")
    profiles = method.get("per_path_resource_profiles")
    grants = method.get("explicit_ap_grants")
    if not isinstance(profiles, list) or not profiles or not isinstance(grants, list):
        invalid("profile_or_grant_shape")
    granted_paths = [
        row.get("path_id") for row in grants
        if isinstance(row, dict) and row.get("grants_attainment_points") is True
    ]
    if not granted_paths or len(granted_paths) != len(set(granted_paths)):
        invalid("grant_identity")
    seen = set()
    modifiers = []
    for profile in profiles:
        if not isinstance(profile, dict):
            invalid("profile_shape")
        path_id = profile.get("path_id")
        if not isinstance(path_id, str) or path_id not in _PATH_RESOURCES or path_id in seen:
            invalid("path_identity")
        seen.add(path_id)
        resource_id, name = _PATH_RESOURCES[path_id]
        units = profile.get("delta_proficiency_bonus_units")
        if (
            profile.get("resource_id") != resource_id
            or profile.get("resource_name") != name
            or type(units) is not int
            or units not in {-1, 0, 1, 2, 3}
            or profile.get("applies_independently") is not True
            or profile.get("conversion_permitted") is not False
            or profile.get("conversion_rule") is not None
            or not isinstance(profile.get("source_text"), str)
            or not profile["source_text"].strip()
        ):
            invalid("resource_profile")
        modifiers.append({
            "resource_id": resource_id,
            "formula": {
                "schema_version": "TianxiaFoundry.SafeFormula.v1",
                "formula_id": f"ns1r.{method_id}.{path_id.lower()}.resource-delta.v1",
                "root": {
                    "op": "multiply",
                    "terms": [{"op": "constant", "value": units}, {"op": "pb"}],
                },
            },
        })
    if seen != set(granted_paths):
        invalid("resource_profiles_do_not_match_granted_paths")
    return {
        "schema": METHOD_MECHANICS_SCHEMA,
        "method_id": method_id,
        "registry_sha256": registry_sha256,
        "method_record_sha256": sha256_json(method),
        "per_path_resource_profiles": deepcopy(profiles),
        "resource_modifiers": sorted(modifiers, key=lambda row: row["resource_id"]),
        "activation_min_cl": 1,
        "refill_current": False,
    }
