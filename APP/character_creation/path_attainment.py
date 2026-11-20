"""Versioned initial-creation attainment; global milestones remain separate."""
from copy import deepcopy
from app.core import FoundryError, canonical_json


INITIAL_PATH_ATTAINMENT_POLICY = {
    "schema": "TianxiaFoundry.InitialPathAttainmentPolicy.v1",
    "selected_path_level": "target_cl",
    "unselected_path_level": 0,
    "character_level": "highest_path_level",
}
CANONICAL_PATH_IDS = (
    "tianxia.path.body_refining",
    "tianxia.path.qi_cultivation",
    "tianxia.path.spirit_awakening",
)


def mortal_level0_path_attainment() -> dict[str, int]:
    """Represent the owner's internal all-Paths-zero mortal baseline."""

    return {path_id: 0 for path_id in CANONICAL_PATH_IDS}


FACTORY_SUPPORT_BLOCKER_CODES = frozenset({
    "CG1_IMMORTAL_ART_AUTHORITY_MISSING",
    "CG1_IMMORTAL_ART_SOURCE_UNAVAILABLE",
    "CG1_IMMORTAL_ART_SOURCE_DEPENDENCY_UNAVAILABLE",
    "CG1_PATH_ATTAINMENT_AUTHORITY_INVALID",
    "CG1_PATH_ATTAINMENT_POLICY_INVALID",
})


def factory_support_blocker(value):
    if isinstance(value, dict):
        if value.get("code") in FACTORY_SUPPORT_BLOCKER_CODES:
            return True
        return any(factory_support_blocker(value.get(key)) for key in ("blockers", "issues", "errors", "details"))
    return isinstance(value, list) and any(factory_support_blocker(item) for item in value)


def equal_initial_path_attainment(request):
    """Inspect an already-authenticated request, preserving legacy absence.

    This is a representation check, not an authorization capability. Callers
    must authenticate the frozen request before using it to execute a build.
    """
    authority = request.get("server_owned_authority") or {}
    if not isinstance(authority, dict):
        raise FoundryError("CG1_PATH_ATTAINMENT_POLICY_INVALID", "Frozen server authority must be an object.")
    if "initial_path_attainment_policy" not in authority:
        return False
    if canonical_json(authority["initial_path_attainment_policy"]) != canonical_json(INITIAL_PATH_ATTAINMENT_POLICY):
        raise FoundryError(
            "CG1_PATH_ATTAINMENT_POLICY_INVALID",
            "The frozen initial Path attainment policy is unsupported or changed.",
        )
    return True


def initial_path_attainment_vector(selected_path_ids, target_cl):
    if (
        type(target_cl) is not int or not 1 <= target_cl <= 20
        or not isinstance(selected_path_ids, (list, tuple)) or not selected_path_ids
        or any(not isinstance(path_id, str) for path_id in selected_path_ids)
        or len(set(selected_path_ids)) != len(selected_path_ids)
        or any(path_id not in CANONICAL_PATH_IDS for path_id in selected_path_ids)
    ):
        raise FoundryError("CG1_PATH_ATTAINMENT_POLICY_INVALID", "Initial attainment requires exact selected Paths and target CL.")
    return {path_id: target_cl if path_id in selected_path_ids else 0 for path_id in CANONICAL_PATH_IDS}


def native_path_progressions(path_records, cl):
    """Derive entries from authenticated Path records, never authored totals."""
    entries = []
    for record in path_records:
        authority = record.get("compatibility", {}).get("factory", {}).get("stage2_authority") or {}
        progression = (authority.get("progression_by_cl") or {}).get(str(cl)) or {}
        feature_ids = progression.get("feature_record_ids")
        if not isinstance(feature_ids, list) or not feature_ids or any(not isinstance(x, str) for x in feature_ids):
            raise FoundryError("PATH_PROGRESSION_ENTRY_MISSING", "A selected Path lacks its exact native feature progression.", details={"path_id": record["record_id"], "cl": cl})
        entries.append({"path_id": record["record_id"], "cl": cl, "automatic_feature_record_ids": list(feature_ids), "source": deepcopy(authority.get("path_index_source") or {})})
    return sorted(entries, key=lambda entry: entry["path_id"])
