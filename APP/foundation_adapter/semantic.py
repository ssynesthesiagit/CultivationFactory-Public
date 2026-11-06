from __future__ import annotations

import copy
import re
from collections import Counter
from typing import Any

from app.core import sha256_json

from .handoff import CATALOG_PATHS, FoundationHandoff


PATH_TO_EXPRESSION_TYPE = {
    "Body Refining": "body_aspect",
    "Qi Cultivation": "cultivation_root",
    "Spirit Awakening": "soul_anchor",
}
PATH_TO_RECORD_ID = {
    "Body Refining": "tianxia.path.body_refining",
    "Qi Cultivation": "tianxia.path.qi_cultivation",
    "Spirit Awakening": "tianxia.path.spirit_awakening",
}
EXPRESSION_TYPE_TO_DECISION_KEY = {
    "body_aspect": "body_aspect",
    "cultivation_root": "cultivation_root",
    "soul_anchor": "soul_anchor",
}
STAGES = ("awakened", "refined", "perfected")
STAGE_LABELS = {"Awakened": 0, "Refined": 1, "Perfected": 2}
_COMBAT_REST_RECHARGE = re.compile(r"\b(?:short|long)\s+rest\b", re.IGNORECASE)


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "severity": "blocker", "details": details}


def _as_list(value: Any, *, code: str, issues: list[dict[str, Any]]) -> list[Any]:
    if not isinstance(value, list):
        issues.append(_issue(code, "Required catalog collection is not an array."))
        return []
    return value


def _index_unique(rows: list[Any], key: str, *, code: str, issues: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or not row[key]:
            issues.append(_issue(code, "Catalog row has no valid stable ID.", index=index, key=key))
            continue
        if row[key] in result:
            issues.append(_issue(code, "Catalog contains a duplicate stable ID.", stable_id=row[key]))
            continue
        result[row[key]] = row
    return result


def normalized_stage_progression(expression: dict[str, Any]) -> dict[str, Any]:
    """Rebuild cumulative stage membership from authoritative available_at fields."""

    normalized = copy.deepcopy(expression.get("stage_progression") or {})
    passives = expression.get("passives") or []
    features = expression.get("features") or []
    for stage_index, stage in enumerate(STAGES):
        row = normalized.setdefault(stage, {})
        row["passive_ids"] = [
            item["passive_id"]
            for item in passives
            if isinstance(item, dict) and STAGE_LABELS.get(item.get("available_at")) is not None
            and STAGE_LABELS[item["available_at"]] <= stage_index
        ]
        row["feature_ids"] = [
            item["feature_id"]
            for item in features
            if isinstance(item, dict) and STAGE_LABELS.get(item.get("available_at")) is not None
            and STAGE_LABELS[item["available_at"]] <= stage_index
        ]
    return normalized


def stage_progression_repair_receipt(
    expression: dict[str, Any],
    *,
    source_hash: str,
    expression_index: int,
) -> dict[str, Any] | None:
    before = expression.get("stage_progression")
    after = normalized_stage_progression(expression)
    if before == after:
        return None
    changed_stages = []
    for stage in STAGES:
        before_row = before.get(stage, {}) if isinstance(before, dict) else {}
        after_row = after.get(stage, {})
        if before_row.get("passive_ids") != after_row.get("passive_ids") or before_row.get("feature_ids") != after_row.get("feature_ids"):
            changed_stages.append({
                "stage": stage,
                "before_passive_ids": list(before_row.get("passive_ids") or []),
                "after_passive_ids": list(after_row.get("passive_ids") or []),
                "before_feature_ids": list(before_row.get("feature_ids") or []),
                "after_feature_ids": list(after_row.get("feature_ids") or []),
            })
    return {
        "schema_version": "TianxiaFoundry.FoundationNormalizationReceipt.v1",
        "repair_id": f"foundation-stage-progression:{expression['expression_id']}",
        "expression_id": expression["expression_id"],
        "source_path": CATALOG_PATHS["expressions"],
        "source_hash": source_hash,
        "source_anchor": f"/expressions/{expression_index}",
        "rule_basis": "features[].available_at and passives[].available_at are controlling; stage snapshots are cumulative derived views",
        "controlling_fields": ["passives[].available_at", "features[].available_at"],
        "changed_stages": changed_stages,
        "before_hash": sha256_json(before),
        "normalized_hash": sha256_json(after),
    }


def validate_foundation_handoff(
    handoff: FoundationHandoff,
    *,
    authorize_stage_repairs: bool = False,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    expected_schemas = {
        "families": "Tianxia.FoundationFamilies.v2",
        "expressions": "Tianxia.FoundationExpressions.v2",
        "selection_index": "Tianxia.FoundationSelectionIndex.v2",
        "readable_projection": "Tianxia.FoundationUnifiedReadableProjection.v2",
        "legacy_alias_map": "Tianxia.FoundationLegacyAliasMap.v2",
    }
    catalogs = {
        "families": handoff.families_catalog,
        "expressions": handoff.expressions_catalog,
        "selection_index": handoff.selection_index,
        "readable_projection": handoff.readable_projection,
        "legacy_alias_map": handoff.legacy_alias_map,
    }
    for logical_name, expected_schema in expected_schemas.items():
        if catalogs[logical_name].get("schema") != expected_schema:
            issues.append(_issue(
                "FOUNDATION_CATALOG_SCHEMA_MISMATCH",
                "Foundation catalog schema does not match the adapter contract.",
                logical_name=logical_name,
                expected=expected_schema,
                actual=catalogs[logical_name].get("schema"),
            ))

    family_rows = _as_list(handoff.families_catalog.get("families"), code="FOUNDATION_FAMILIES_NOT_ARRAY", issues=issues)
    expression_rows = _as_list(handoff.expressions_catalog.get("expressions"), code="FOUNDATION_EXPRESSIONS_NOT_ARRAY", issues=issues)
    selection_rows = _as_list(handoff.selection_index.get("families"), code="FOUNDATION_SELECTION_NOT_ARRAY", issues=issues)
    readable_rows = _as_list(handoff.readable_projection.get("foundations"), code="FOUNDATION_READABLE_NOT_ARRAY", issues=issues)
    alias_rows = _as_list(handoff.legacy_alias_map.get("aliases"), code="FOUNDATION_ALIASES_NOT_ARRAY", issues=issues)

    families = _index_unique(family_rows, "family_id", code="FOUNDATION_FAMILY_ID_INVALID", issues=issues)
    expressions = _index_unique(expression_rows, "expression_id", code="FOUNDATION_EXPRESSION_ID_INVALID", issues=issues)
    selections = _index_unique(selection_rows, "family_id", code="FOUNDATION_SELECTION_FAMILY_ID_INVALID", issues=issues)
    readables = _index_unique(readable_rows, "foundation_id", code="FOUNDATION_READABLE_ID_INVALID", issues=issues)
    aliases = _index_unique(alias_rows, "family_id", code="FOUNDATION_ALIAS_FAMILY_ID_INVALID", issues=issues)

    expected_counts = {
        "families": 46,
        "expressions": 113,
        "body_aspects": 36,
        "cultivation_roots": 42,
        "soul_anchors": 35,
        "intentional_exclusions": 25,
    }
    actual_counts = {
        "families": len(families),
        "expressions": len(expressions),
        "body_aspects": sum(row.get("expression_type") == "body_aspect" for row in expression_rows if isinstance(row, dict)),
        "cultivation_roots": sum(row.get("expression_type") == "cultivation_root" for row in expression_rows if isinstance(row, dict)),
        "soul_anchors": sum(row.get("expression_type") == "soul_anchor" for row in expression_rows if isinstance(row, dict)),
        "intentional_exclusions": sum(
            decision.get("decision") == "EXCLUDE"
            for family in family_rows if isinstance(family, dict)
            for decision in (family.get("expression_decisions") or {}).values()
            if isinstance(decision, dict)
        ),
    }
    for name, expected in expected_counts.items():
        if actual_counts[name] != expected:
            issues.append(_issue("FOUNDATION_COUNT_MISMATCH", "Foundation catalog count is not the accepted 46/113 contract.", count=name, expected=expected, actual=actual_counts[name]))
        manifest_value = (handoff.manifest.get("counts") or {}).get(name)
        if manifest_value != expected:
            issues.append(_issue("FOUNDATION_MANIFEST_COUNT_MISMATCH", "Handoff manifest count does not match the accepted contract.", count=name, expected=expected, actual=manifest_value))

    family_ids = set(families)
    expression_ids = set(expressions)
    if set(selections) != family_ids or set(aliases) != family_ids:
        issues.append(_issue(
            "FOUNDATION_FAMILY_CROSSWALK_COVERAGE_MISMATCH",
            "Selection-index and alias-map family coverage must exactly match the family catalog.",
            missing_selection=sorted(family_ids - set(selections)),
            extra_selection=sorted(set(selections) - family_ids),
            missing_alias=sorted(family_ids - set(aliases)),
            extra_alias=sorted(set(aliases) - family_ids),
        ))
    if set(readables) != expression_ids:
        issues.append(_issue(
            "FOUNDATION_READABLE_COVERAGE_MISMATCH",
            "Readable projection must contain exactly one row per expression.",
            missing=sorted(expression_ids - set(readables)),
            unexpected=sorted(set(readables) - expression_ids),
        ))

    all_resource_ids: set[str] = set()
    all_passive_ids: set[str] = set()
    all_feature_ids: set[str] = set()
    repair_receipts: list[dict[str, Any]] = []
    expression_source_hash = handoff.source_blobs["expressions"].sha256

    for expression_index, expression in enumerate(expression_rows):
        if not isinstance(expression, dict) or not isinstance(expression.get("expression_id"), str):
            continue
        expression_id = expression["expression_id"]
        family_id = expression.get("family_id")
        path = expression.get("path")
        expression_type = expression.get("expression_type")
        if family_id not in families:
            issues.append(_issue("FOUNDATION_EXPRESSION_FAMILY_MISSING", "Expression references a missing family.", expression_id=expression_id, family_id=family_id))
        expected_type = PATH_TO_EXPRESSION_TYPE.get(path)
        if expected_type is None or expression_type != expected_type:
            issues.append(_issue(
                "FOUNDATION_PATH_EXPRESSION_TYPE_MISMATCH",
                "Expression Path and expression_type contradict one another.",
                expression_id=expression_id,
                path=path,
                expression_type=expression_type,
                expected_type=expected_type,
            ))
        if expression.get("source_cl") is None or not isinstance(expression.get("source_cl"), int) or expression["source_cl"] < 1:
            issues.append(_issue("FOUNDATION_SOURCE_CL_INVALID", "Expression Source CL must be a positive integer.", expression_id=expression_id))

        resource = expression.get("resource")
        passives = expression.get("passives")
        features = expression.get("features")
        if not isinstance(resource, dict) or not isinstance(resource.get("resource_id"), str):
            issues.append(_issue("FOUNDATION_RESOURCE_INVALID", "Expression must define exactly one structured Foundation resource.", expression_id=expression_id))
            resource = {}
        elif resource["resource_id"] in all_resource_ids:
            issues.append(_issue("FOUNDATION_RESOURCE_ID_DUPLICATE", "Foundation resource IDs must be globally unique.", expression_id=expression_id, resource_id=resource["resource_id"]))
        else:
            all_resource_ids.add(resource["resource_id"])
        if not isinstance(passives, list) or len(passives) != 3:
            issues.append(_issue("FOUNDATION_PASSIVE_COUNT_INVALID", "Expression must contain exactly three stage passives.", expression_id=expression_id))
            passives = []
        if not isinstance(features, list) or len(features) not in {3, 4}:
            issues.append(_issue("FOUNDATION_FEATURE_COUNT_INVALID", "Expression must contain three or four executable features.", expression_id=expression_id))
            features = []

        local_passives: set[str] = set()
        local_features: set[str] = set()
        for kind, rows, id_key, global_ids in (
            ("passive", passives, "passive_id", all_passive_ids),
            ("feature", features, "feature_id", all_feature_ids),
        ):
            local_ids = local_passives if kind == "passive" else local_features
            for row in rows:
                stable_id = row.get(id_key) if isinstance(row, dict) else None
                if not isinstance(stable_id, str) or not stable_id:
                    issues.append(_issue("FOUNDATION_MECHANIC_ID_INVALID", "Foundation mechanic lacks a stable ID.", expression_id=expression_id, mechanic_type=kind))
                    continue
                if stable_id in global_ids:
                    issues.append(_issue("FOUNDATION_MECHANIC_ID_DUPLICATE", "Foundation mechanic IDs must be globally unique.", expression_id=expression_id, mechanic_type=kind, mechanic_id=stable_id))
                global_ids.add(stable_id)
                local_ids.add(stable_id)
                if row.get("available_at") not in STAGE_LABELS:
                    issues.append(_issue("FOUNDATION_AVAILABLE_AT_INVALID", "Mechanic has an invalid available_at stage.", expression_id=expression_id, mechanic_id=stable_id, available_at=row.get("available_at")))

        stage_progression = expression.get("stage_progression")
        if not isinstance(stage_progression, dict) or tuple(stage_progression) != STAGES:
            issues.append(_issue("FOUNDATION_STAGE_PROGRESSION_INVALID", "Expression must define awakened, refined, and perfected stage snapshots in order.", expression_id=expression_id))
        else:
            normalized = normalized_stage_progression(expression)
            receipt = stage_progression_repair_receipt(expression, source_hash=expression_source_hash, expression_index=expression_index)
            if receipt is not None:
                repair_receipts.append(receipt)
                row = _issue(
                    "FOUNDATION_STAGE_PROGRESSION_CONTRADICTS_AVAILABLE_AT",
                    "Derived stage snapshot contradicts controlling mechanic available_at fields.",
                    expression_id=expression_id,
                    changed_stages=receipt["changed_stages"],
                )
                if authorize_stage_repairs:
                    row["severity"] = "repaired"
                    row["details"]["repair_id"] = receipt["repair_id"]
                issues.append(row)
            for stage in STAGES:
                maximum = (resource.get("maximum_by_stage") or {}).get(stage)
                if stage_progression.get(stage, {}).get("resource_maximum") != maximum:
                    issues.append(_issue(
                        "FOUNDATION_STAGE_RESOURCE_MAXIMUM_MISMATCH",
                        "Stage resource maximum contradicts the expression resource table.",
                        expression_id=expression_id,
                        stage=stage,
                    ))
                if not set(normalized.get(stage, {}).get("passive_ids") or []).issubset(local_passives):
                    issues.append(_issue("FOUNDATION_STAGE_PASSIVE_REFERENCE_MISSING", "Stage snapshot references an absent passive.", expression_id=expression_id, stage=stage))
                if not set(normalized.get(stage, {}).get("feature_ids") or []).issubset(local_features):
                    issues.append(_issue("FOUNDATION_STAGE_FEATURE_REFERENCE_MISSING", "Stage snapshot references an absent feature.", expression_id=expression_id, stage=stage))

        spend_ids = set(resource.get("spend_feature_ids") or [])
        paid_feature_ids = {
            feature["feature_id"]
            for feature in features
            if isinstance(feature, dict)
            and isinstance(feature.get("cost"), str)
            and feature["cost"].strip().lower() not in {"", "none", "none."}
        }
        if spend_ids != paid_feature_ids:
            issues.append(_issue(
                "FOUNDATION_RESOURCE_SPEND_COVERAGE_MISMATCH",
                "Resource spend_feature_ids must exactly cover resource-paid features.",
                expression_id=expression_id,
                missing=sorted(paid_feature_ids - spend_ids),
                unexpected=sorted(spend_ids - paid_feature_ids),
            ))

        for mechanic in features:
            if not isinstance(mechanic, dict):
                continue
            required = ("timing", "action_type", "cost", "trigger", "range", "target", "attack_or_save", "effect", "duration", "limits", "counterplay")
            missing = [key for key in required if mechanic.get(key) in (None, "", [])]
            if missing:
                issues.append(_issue("FOUNDATION_EXECUTABLE_FEATURE_INCOMPLETE", "Foundation feature lacks required execution fields.", expression_id=expression_id, feature_id=mechanic.get("feature_id"), missing=missing))
            if _COMBAT_REST_RECHARGE.search(" ".join(str(mechanic.get(key) or "") for key in required)):
                issues.append(_issue("FOUNDATION_COMBAT_REST_REFRESH_FORBIDDEN", "Foundation combat feature cannot refresh on a short or long rest.", expression_id=expression_id, feature_id=mechanic.get("feature_id")))

        for collection_name, minimum in (("injuries", 1), ("strains", 1), ("deviations", 1), ("repair_procedures", 1), ("advancement_challenges", 2), ("counterplay", 1)):
            collection = expression.get(collection_name)
            if not isinstance(collection, list) or len(collection) < minimum:
                issues.append(_issue("FOUNDATION_LIFECYCLE_COLLECTION_INCOMPLETE", "Foundation expression lacks required lifecycle mechanics.", expression_id=expression_id, collection=collection_name, minimum=minimum))

        readable = readables.get(expression_id)
        if readable is not None:
            readable_path = (readable.get("profile") or {}).get("primary_path")
            crosswalk = {
                "family_id": readable.get("family_id"),
                "expression_type": readable.get("expression_type"),
                "catalog_code": readable.get("catalog_code"),
                "display_name": readable.get("name"),
                "path": readable_path,
            }
            expected = {
                "family_id": family_id,
                "expression_type": expression_type,
                "catalog_code": expression.get("catalog_code"),
                "display_name": expression.get("display_name"),
                "path": path,
            }
            if crosswalk != expected:
                issues.append(_issue("FOUNDATION_READABLE_METADATA_MISMATCH", "Readable projection metadata contradicts the expression source.", expression_id=expression_id, expected=expected, actual=crosswalk))

    for family_id, family in families.items():
        decisions = family.get("expression_decisions")
        if not isinstance(decisions, dict) or set(decisions) != set(EXPRESSION_TYPE_TO_DECISION_KEY):
            issues.append(_issue("FOUNDATION_DECISION_MATRIX_INVALID", "Family must decide all three expression types.", family_id=family_id))
            decisions = {}
        expected_expression_ids: set[str] = set()
        expected_exclusions: dict[str, str] = {}
        for expression_type in EXPRESSION_TYPE_TO_DECISION_KEY:
            decision = decisions.get(expression_type) or {}
            target_id = decision.get("target_expression_id")
            if decision.get("decision") == "EXCLUDE":
                if target_id is not None or not decision.get("reason"):
                    issues.append(_issue("FOUNDATION_EXCLUSION_INVALID", "Excluded expression must have a reason and no target ID.", family_id=family_id, expression_type=expression_type))
                expected_exclusions[expression_type] = str(decision.get("reason") or "")
            elif decision.get("decision") in {"ADD", "REBUILD", "TRANSLATE"}:
                if target_id not in expressions:
                    issues.append(_issue("FOUNDATION_DECISION_TARGET_MISSING", "Family decision points to a missing expression.", family_id=family_id, expression_type=expression_type, target_expression_id=target_id))
                else:
                    expected_expression_ids.add(target_id)
                    target = expressions[target_id]
                    if target.get("family_id") != family_id or target.get("expression_type") != expression_type:
                        issues.append(_issue("FOUNDATION_DECISION_TARGET_MISMATCH", "Family decision target has the wrong family or expression type.", family_id=family_id, expression_type=expression_type, target_expression_id=target_id))
            else:
                issues.append(_issue("FOUNDATION_DECISION_VALUE_INVALID", "Family expression decision is unsupported.", family_id=family_id, expression_type=expression_type, decision=decision.get("decision")))

        actual_family_expression_ids = {eid for eid, expression in expressions.items() if expression.get("family_id") == family_id}
        if actual_family_expression_ids != expected_expression_ids:
            issues.append(_issue("FOUNDATION_FAMILY_EXPRESSION_SET_MISMATCH", "Family decision matrix does not exactly cover its expressions.", family_id=family_id, expected=sorted(expected_expression_ids), actual=sorted(actual_family_expression_ids)))

        selection = selections.get(family_id)
        if selection is not None:
            selected_expression_rows = selection.get("expressions") or []
            selected_ids = {row.get("expression_id") for row in selected_expression_rows if isinstance(row, dict)}
            if selected_ids != expected_expression_ids:
                issues.append(_issue("FOUNDATION_SELECTION_EXPRESSION_SET_MISMATCH", "Selection index expression set contradicts the family decision matrix.", family_id=family_id))
            selected_exclusions = {
                row.get("type"): row.get("reason")
                for row in (selection.get("excluded") or [])
                if isinstance(row, dict)
            }
            if selected_exclusions != expected_exclusions:
                issues.append(_issue("FOUNDATION_SELECTION_EXCLUSION_MISMATCH", "Selection index exclusions contradict the family decision matrix.", family_id=family_id))
            for row in selected_expression_rows:
                if not isinstance(row, dict) or row.get("expression_id") not in expressions:
                    continue
                expression = expressions[row["expression_id"]]
                expected_row = {
                    "catalog_code": expression.get("catalog_code"),
                    "type": expression.get("expression_type"),
                    "path": expression.get("path"),
                    "display_name": expression.get("display_name"),
                    "aspect": (expression.get("aspect") or {}).get("name"),
                }
                actual_row = {key: row.get(key) for key in expected_row}
                if actual_row != expected_row:
                    issues.append(_issue("FOUNDATION_SELECTION_METADATA_MISMATCH", "Selection index row contradicts the expression source.", family_id=family_id, expression_id=row["expression_id"], expected=expected_row, actual=actual_row))

        alias = aliases.get(family_id)
        if alias is not None:
            expected_by_path = {
                expressions[eid]["path"]: eid
                for eid in expected_expression_ids
            }
            if alias.get("expression_by_path") != expected_by_path:
                issues.append(_issue("FOUNDATION_ALIAS_PATH_MAP_MISMATCH", "Legacy alias path map contradicts the family expression set.", family_id=family_id, expected=expected_by_path, actual=alias.get("expression_by_path")))
            if alias.get("default_expression_id") not in expected_expression_ids:
                issues.append(_issue("FOUNDATION_ALIAS_DEFAULT_INVALID", "Legacy alias default expression is not part of the family.", family_id=family_id, default_expression_id=alias.get("default_expression_id")))

    blocking = [row for row in issues if row["severity"] == "blocker"]
    repaired = [row for row in issues if row["severity"] == "repaired"]
    return {
        "schema_version": "TianxiaFoundry.FoundationHandoffSemanticReport.v1",
        "handoff_archive_sha256": handoff.archive_sha256,
        "source_hashes": {name: blob.sha256 for name, blob in sorted(handoff.source_blobs.items())},
        "policy": {
            "stage_progression_controlling_fields": ["passives[].available_at", "features[].available_at"],
            "stage_snapshots_are_cumulative_derived_views": True,
            "raw_source_payload_is_immutable": True,
            "authorized_stage_repairs": authorize_stage_repairs,
        },
        "counts": actual_counts,
        "mechanic_counts": {
            "resources": len(all_resource_ids),
            "passives": len(all_passive_ids),
            "features": len(all_feature_ids),
            "repair_receipts": len(repair_receipts),
        },
        "repair_receipts": repair_receipts,
        "issues": issues,
        "summary": {
            "status": "PASS" if not blocking else "FAIL",
            "blocker_count": len(blocking),
            "repaired_count": len(repaired),
            "issue_count": len(issues),
            "selectable_after_validation": not blocking,
        },
    }
