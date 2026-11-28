"""Pure, source-bound descriptive Dao and I Ching response contract."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from app.core import FoundryError


GM_THEME_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "display_name", "core_theme", "principles", "strengths", "risks",
        "roleplay_expression", "tactical_expression", "gm_usage_notes",
        "relevant_record_ids", "mechanical_effects",
    ],
    "properties": {
        "display_name": {"type": "string", "minLength": 1},
        "core_theme": {"type": "string", "minLength": 1},
        "principles": {"type": "array", "minItems": 2, "items": {"type": "string", "minLength": 1}},
        "strengths": {"type": "array", "minItems": 2, "items": {"type": "string", "minLength": 1}},
        "risks": {"type": "array", "minItems": 2, "items": {"type": "string", "minLength": 1}},
        "roleplay_expression": {"type": "string", "minLength": 1},
        "tactical_expression": {"type": "string", "minLength": 1},
        "gm_usage_notes": {"type": "string", "minLength": 1},
        "relevant_record_ids": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
        "mechanical_effects": {"const": []},
    },
}

GM_THEMES_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["dao", "i_ching"],
    "properties": {
        "dao": deepcopy(GM_THEME_RESPONSE_SCHEMA),
        "i_ching": deepcopy(GM_THEME_RESPONSE_SCHEMA),
    },
}


def build_gm_themes_schema(allowed_record_ids: Iterable[str] | None = None) -> dict[str, Any]:
    """Return the shared schema with an optional server-owned ID enum."""
    schema = deepcopy(GM_THEMES_RESPONSE_SCHEMA)
    # Bound what the model may write (grammar-constrained local models follow
    # the schema); a CL18 build's unbounded themes overran the 6144-token
    # output cap.  Stored themes are still validated with the base schema.
    for kind in ("dao", "i_ching"):
        properties = schema["properties"][kind]["properties"]
        for field in ("display_name", "core_theme"):
            properties[field]["maxLength"] = 200
        for field in ("roleplay_expression", "tactical_expression", "gm_usage_notes"):
            properties[field]["maxLength"] = 480
        for field in ("principles", "strengths", "risks"):
            properties[field]["maxItems"] = 4
            properties[field]["items"]["maxLength"] = 200
        # llama.cpp grammars cannot enforce uniqueItems (a model repeated an
        # ID); the server drops repeats in validate_gm_themes instead.
        properties["relevant_record_ids"].pop("uniqueItems", None)
    if allowed_record_ids is not None:
        ids = sorted({value for value in allowed_record_ids if isinstance(value, str) and value})
        if not ids:
            raise FoundryError(
                "GM_AUTHORING_THEME_SOURCE_INVALID",
                "Descriptive themes require at least one selected source record.",
            )
        for kind in ("dao", "i_ching"):
            schema["properties"][kind]["properties"]["relevant_record_ids"]["items"] = {
                "type": "string",
                "enum": ids,
            }
            # Without uniqueItems (unenforceable) the grammar must still bound
            # the list: build 34's model repeated IDs to the 6144-token cap.
            # Distinct IDs can never exceed the allowed set.
            schema["properties"][kind]["properties"]["relevant_record_ids"]["maxItems"] = len(ids)
    else:
        for kind in ("dao", "i_ching"):
            schema["properties"][kind]["properties"]["relevant_record_ids"]["maxItems"] = 16
    return schema


def validate_gm_themes(value: Any, selected_ids: Iterable[str]) -> dict[str, Any]:
    """Validate descriptive themes and prohibit narrative mechanics claims."""
    if not isinstance(value, Mapping):
        raise FoundryError("GM_AUTHORING_THEME_INVALID", "The descriptive GM themes must be one object.")
    normalized = deepcopy(dict(value))
    for kind in ("dao", "i_ching"):
        theme = normalized.get(kind)
        if isinstance(theme, dict) and isinstance(theme.get("relevant_record_ids"), list):
            theme["relevant_record_ids"] = list(dict.fromkeys(theme["relevant_record_ids"]))
    try:
        Draft202012Validator(GM_THEMES_RESPONSE_SCHEMA).validate(normalized)
    except Exception as exc:
        raise FoundryError(
            "GM_AUTHORING_THEME_INVALID",
            "The descriptive GM themes failed their strict schema.",
            details={"reason": str(exc)},
        ) from exc
    selected = set(selected_ids)
    for kind in ("dao", "i_ching"):
        theme = normalized[kind]
        unknown = sorted(set(theme["relevant_record_ids"]) - selected)
        if unknown:
            raise FoundryError(
                "GM_AUTHORING_PROVIDER_SOURCE_UNKNOWN",
                "The descriptive GM theme referenced an unselected record.",
                details={"kind": kind, "record_ids": unknown},
            )
        if theme.get("mechanical_effects") != []:
            raise FoundryError(
                "GM_AUTHORING_PROVIDER_MECHANICS_FORBIDDEN",
                "Descriptive GM themes cannot introduce mechanical effects.",
                details={"kind": kind},
            )
    return normalized


__all__ = [
    "GM_THEME_RESPONSE_SCHEMA",
    "GM_THEMES_RESPONSE_SCHEMA",
    "build_gm_themes_schema",
    "validate_gm_themes",
]
