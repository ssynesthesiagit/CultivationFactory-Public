"""Shared Stage 2 catalog-authority type contracts.

This module deliberately contains data only.  Content Pack validation and the
advancement runtime can therefore enforce the same event-kind/content-type
boundary without importing either service implementation into the other.
"""

from __future__ import annotations

import re
from typing import Any


MANUAL_CONTENT_TYPES = frozenset({"manual", "martial_manual", "manual_expression"})

RECORDED_ART_EXPRESSION_KINDS = frozenset({
    "exact_base_ability",
    "exact_named_talent",
    "base_plus_ordered_augments",
    "published_sphere_package",
    "published_multi_sphere_expression",
    "preserved_forged_expression",
})

RECORDED_ART_EXECUTION_FIELDS = frozenset({
    "action_id",
    "name",
    "timing",
    "cost",
    "range",
    "target",
    "roll_save_check",
    "effect",
    "failure",
    "duration",
    "limit",
    "counterplay",
})

# These are not rules text.  They are unresolved references to rules text and
# were the direct cause of Martial Manual cards that looked populated while
# telling a player nothing actionable.
_NON_OPERATIONAL_EXECUTION_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\buse (?:the )?reproduced package(?: resolution)?\b",
    r"\bas (?:the )?(?:reproduced )?package (?:allows|provides|lists|specifies)\b",
    r"\bas (?:listed|printed|described|written|above|applicable)\b",
    r"\bas (?:listed|printed|described) for (?:the )?fixed expression\b",
    r"\bresolve (?:the )?(?:failure|success|effect|resolution)?\s*(?:exactly )?as\b",
    r"\b(?:unspecified|to be determined|not recorded|not itemized|unknown|placeholder|tbd)\b",
    r"\bsee (?:the )?(?:source|package|talent|ability|manual)\b",
    r"\bsetup rider\b",
    r"\bpressure stability\b",
))


def _stage2_authority(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    value = record.get("compatibility", {}).get("factory", {}).get("stage2_authority")
    return value if isinstance(value, dict) else {}


def recorded_art_execution_issues(payload: Any) -> list[dict[str, Any]]:
    """Return fail-closed diagnostics for a published executable action.

    A complete key set is insufficient: fallback prose such as ``as listed``
    is an unresolved pointer, not an executable rule.  Structured values are
    accepted when non-empty; string fields are additionally checked for the
    known deictic/fallback grammar.
    """

    if not isinstance(payload, dict):
        return [{"code": "RECORDED_ART_EXECUTION_TEMPLATE_INVALID", "message": "The published action payload is not an object."}]
    issues: list[dict[str, Any]] = []
    missing = sorted(RECORDED_ART_EXECUTION_FIELDS - set(payload))
    if missing:
        issues.append({"code": "RECORDED_ART_EXECUTION_TEMPLATE_INCOMPLETE", "missing": missing})
    for field in sorted(RECORDED_ART_EXECUTION_FIELDS & set(payload)):
        value = payload.get(field)
        if value is None or value == "" or value == [] or value == {}:
            issues.append({"code": "RECORDED_ART_EXECUTION_FIELD_EMPTY", "field": field})
            continue
        if isinstance(value, str):
            text = value.strip()
            if not text:
                issues.append({"code": "RECORDED_ART_EXECUTION_FIELD_EMPTY", "field": field})
                continue
            matched = next((pattern.pattern for pattern in _NON_OPERATIONAL_EXECUTION_PATTERNS if pattern.search(text)), None)
            if matched:
                issues.append({
                    "code": "RECORDED_ART_EXECUTION_NON_OPERATIONAL",
                    "field": field,
                    "value": text,
                    "matched_pattern": matched,
                })
    effect = payload.get("effect")
    if isinstance(effect, str) and len(effect.strip()) < 12:
        issues.append({"code": "RECORDED_ART_EFFECT_NOT_CONCRETE", "field": "effect", "value": effect})
    return issues


def recorded_art_expression_issues(
    *,
    record_id: str,
    art: Any,
    record_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate the PHB Recorded-Art expression grammar against exact records.

    The component list is ordered and semantic.  It is never a bag of records
    that an AI may reinterpret into a custom action.
    """

    if not isinstance(art, dict):
        return [{"code": "RECORDED_ART_AUTHORITY_MISSING", "record_id": record_id}]
    issues: list[dict[str, Any]] = []
    kind = art.get("expression_kind")
    component_ids = art.get("reproduced_component_record_ids")
    if kind not in RECORDED_ART_EXPRESSION_KINDS:
        issues.append({"code": "RECORDED_ART_EXPRESSION_KIND_UNSUPPORTED", "record_id": record_id, "expression_kind": kind})
        return issues
    if not isinstance(component_ids, list) or not component_ids or any(not isinstance(value, str) or not value for value in component_ids):
        issues.append({"code": "RECORDED_ART_COMPONENT_AUTHORITY_MISSING", "record_id": record_id})
        return issues
    if len(component_ids) != len(set(component_ids)):
        issues.append({"code": "RECORDED_ART_COMPONENT_DUPLICATED", "record_id": record_id, "component_record_ids": component_ids})
    parent_id = art.get("parent_manual_record_id")
    derivation = art.get("execution_derivation") if isinstance(art.get("execution_derivation"), dict) else {}
    if record_id in {parent_id, derivation.get("source_record_id"), *component_ids}:
        issues.append({"code": "RECORDED_ART_SELF_REFERENCE_FORBIDDEN", "record_id": record_id})

    components = [record_map.get(value) for value in component_ids]
    for component_id, component in zip(component_ids, components):
        if not isinstance(component, dict):
            issues.append({"code": "RECORDED_ART_COMPONENT_REFERENCE_MISSING", "record_id": record_id, "component_record_id": component_id})
            continue
        if component.get("publication", {}).get("status") != "published":
            issues.append({"code": "RECORDED_ART_COMPONENT_NOT_PUBLISHED", "record_id": record_id, "component_record_id": component_id})
        if not _stage2_authority(component).get("authority_complete"):
            issues.append({"code": "RECORDED_ART_COMPONENT_AUTHORITY_INCOMPLETE", "record_id": record_id, "component_record_id": component_id})

    def component_type(index: int) -> str | None:
        value = components[index] if index < len(components) else None
        return value.get("content_type") if isinstance(value, dict) else None

    def component_authority(index: int) -> dict[str, Any]:
        value = components[index] if index < len(components) else None
        return _stage2_authority(value)

    if kind == "exact_named_talent":
        if len(component_ids) != 1 or component_type(0) != "talent":
            issues.append({"code": "RECORDED_ART_EXACT_TALENT_GRAMMAR_INVALID", "record_id": record_id, "component_record_ids": component_ids, "component_types": [x.get("content_type") if isinstance(x, dict) else None for x in components]})
    elif kind == "exact_base_ability":
        allowed_types = {"path_feature_component", "manual_expression"}
        role = component_authority(0).get("recorded_art_component_kind")
        if len(component_ids) != 1 or component_type(0) not in allowed_types or role not in {"base_ability", "published_action"}:
            issues.append({"code": "RECORDED_ART_EXACT_BASE_GRAMMAR_INVALID", "record_id": record_id, "component_record_ids": component_ids, "component_role": role})
    elif kind == "base_plus_ordered_augments":
        base_role = component_authority(0).get("recorded_art_component_kind")
        base_type = component_type(0)
        augments_valid = all(
            component_type(index) == "talent" and component_authority(index).get("recorded_art_component_kind") == "augmented_talent"
            for index in range(1, len(component_ids))
        )
        if len(component_ids) < 2 or base_type not in {"path_feature_component", "manual_expression"} or base_role not in {"base_ability", "published_action"} or not augments_valid:
            issues.append({"code": "RECORDED_ART_ORDERED_AUGMENT_GRAMMAR_INVALID", "record_id": record_id, "component_record_ids": component_ids})
    elif kind in {"published_sphere_package", "published_multi_sphere_expression"}:
        expected_package_kind = "sphere_package" if kind == "published_sphere_package" else "multi_sphere_expression"
        package = component_authority(0).get("recorded_art_package_authority")
        associated = art.get("associated_sphere_record_ids")
        package_spheres = package.get("associated_sphere_record_ids") if isinstance(package, dict) else None
        expected_sphere_count_ok = isinstance(associated, list) and (len(associated) == 1 if kind == "published_sphere_package" else len(associated) >= 2)
        if (
            len(component_ids) != 1
            or component_type(0) != "manual_expression"
            or not isinstance(package, dict)
            or package.get("package_kind") != expected_package_kind
            or package_spheres != associated
            or not expected_sphere_count_ok
        ):
            issues.append({"code": "RECORDED_ART_PUBLISHED_PACKAGE_GRAMMAR_INVALID", "record_id": record_id, "expression_kind": kind, "component_record_ids": component_ids})
    elif kind == "preserved_forged_expression":
        preserved = component_authority(0).get("preserved_forged_expression_authority")
        if (
            len(component_ids) != 1
            or component_type(0) != "forged_technique_component"
            or not isinstance(preserved, dict)
            or preserved.get("legal_status") not in {"legally_forged", "legally_preserved"}
            or not isinstance(preserved.get("provenance_record_id"), str)
            or not preserved.get("provenance_record_id")
        ):
            issues.append({"code": "RECORDED_ART_PRESERVED_FORGED_AUTHORITY_INVALID", "record_id": record_id, "component_record_ids": component_ids})

    source_id = derivation.get("source_record_id")
    if derivation.get("mode") != "copy_exact_published_template" or source_id not in component_ids:
        issues.append({"code": "RECORDED_ART_EXECUTION_DERIVATION_UNPROVEN", "record_id": record_id, "source_record_id": source_id})
        return issues
    source = record_map.get(source_id)
    template_id = derivation.get("template_id")
    if kind == "base_plus_ordered_augments":
        compiled = _stage2_authority(source).get("recorded_art_compilation_authority")
        if (
            not isinstance(compiled, dict)
            or compiled.get("expression_kind") != kind
            or compiled.get("ordered_component_record_ids") != component_ids
            or compiled.get("template_id") != template_id
        ):
            issues.append({
                "code": "RECORDED_ART_COMPILED_EXPRESSION_AUTHORITY_MISSING",
                "record_id": record_id,
                "source_record_id": source_id,
                "component_record_ids": component_ids,
            })
    template = next((
        row for row in source.get("execution_templates", [])
        if isinstance(row, dict) and row.get("template_id") == template_id and row.get("template_type") == "action"
    ), None) if isinstance(source, dict) else None
    if not isinstance(template, dict):
        issues.append({"code": "RECORDED_ART_EXECUTION_DERIVATION_UNPROVEN", "record_id": record_id, "source_record_id": source_id, "template_id": template_id})
    else:
        for issue in recorded_art_execution_issues(template.get("payload")):
            issues.append({"record_id": record_id, "source_record_id": source_id, "template_id": template_id, **issue})
    return issues

STAGE2_KIND_CONTENT_TYPES: dict[str, frozenset[str]] = {
    "starting_state": frozenset({"source_document"}),
    "level_advance": frozenset({"path_feature"}),
    "ability_score_change": frozenset({"path_feature"}),
    "cultivation_insight_acquisition": frozenset({"cultivation_insight"}),
    "background_acquisition": frozenset({"background"}),
    "background_sphere_acquisition": frozenset({"sphere"}),
    "background_talent_acquisition": frozenset({"talent"}),
    "origin_insight_acquisition": frozenset({"origin_insight"}),
    "path_acquisition": frozenset({"path"}),
    "subpath_acquisition": frozenset({"subpath"}),
    "sect_trial_sphere_acquisition": frozenset({"sphere"}),
    "sect_trial_talent_acquisition": frozenset({"talent"}),
    "ai_bootstrap_sphere_acquisition": frozenset({"sphere"}),
    "ai_bootstrap_talent_acquisition": frozenset({"talent"}),
    "level_talent_acquisition": frozenset({"talent"}),
    "method_acquisition": frozenset({"cultivation_method"}),
    "method_activation": frozenset({"cultivation_method"}),
    "foundation_acquisition": frozenset({"foundation"}),
    "foundation_expression": frozenset({"foundation_expression"}),
    "foundation_stage": frozenset({"foundation"}),
    "sphere_training_attempt": frozenset({"sphere"}),
    "talent_training_attempt": frozenset({"talent"}),
    "manual_training_attempt": frozenset({"recorded_art"}),
    "new_sphere_bonus_talent_acquisition": frozenset({"talent"}),
    "equipment_acquisition": frozenset({"item"}),
    "forged_technique_creation": frozenset({"forged_technique_component"}),
    "typed_none": frozenset({"source_document"}),
    # Explicit legacy v1 event kinds remain supported by explicit v1 clients.
    "sphere_acquisition": frozenset({"sphere"}),
    "talent_acquisition": frozenset({"talent"}),
    "manual_acquisition": frozenset({"recorded_art"}),
    "forged_technique_acquisition": frozenset({"forged_technique_component"}),
}

# Training-source access is a relation, not an acquisition of the source's
# mechanics, so several published source forms are valid.
STAGE2_TRAINING_SOURCE_CONTENT_TYPES = frozenset(
    {"source_document", "sphere", "tradition", "item", "companion", *MANUAL_CONTENT_TYPES}
)


def allowed_content_types_for_kind(kind: str) -> frozenset[str] | None:
    if kind == "training_source_access":
        return STAGE2_TRAINING_SOURCE_CONTENT_TYPES
    return STAGE2_KIND_CONTENT_TYPES.get(kind)


__all__ = [
    "MANUAL_CONTENT_TYPES",
    "RECORDED_ART_EXECUTION_FIELDS",
    "RECORDED_ART_EXPRESSION_KINDS",
    "STAGE2_KIND_CONTENT_TYPES",
    "STAGE2_TRAINING_SOURCE_CONTENT_TYPES",
    "allowed_content_types_for_kind",
    "recorded_art_execution_issues",
    "recorded_art_expression_issues",
]
