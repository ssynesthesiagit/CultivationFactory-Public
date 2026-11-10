"""Build-time effect subjects shared by the authority builder and data authors.

The executor requires derived subjects on effects, including code-created ones.
Null means derivation found no applicable recipient fields; missing keys are
an error. No execution-time prose interpreter exists.

Area-wide harmful-recipient permissions remain the separate area seal contract.
"""

from __future__ import annotations

import re
from typing import Any

_WITHIN_FT = re.compile(r"\bwithin (\d+) (?:feet|ft)\b", re.I)
_ONE_ALLY = re.compile(r"\b(?:one|an|a|another|that|the) (?:ally|allied creature|willing creature|friendly creature)\b", re.I)
_YOU_OR = re.compile(r"\byou or (?:an? |one |another )?(?:ally|allies|creature)", re.I)
_ALLIES = re.compile(r"\ballies\b", re.I)
_HOSTILE_SAVE = re.compile(r"\b(?:hostile creatures?|enem(?:y|ies))\b[^.!?]*\b(?:makes?|must|succeed|saving throw)", re.I)
_AREA_CREATURE = re.compile(r"\bcreatures? (?:in|inside|within)\b", re.I)
_INCLUSIVE = re.compile(r"\b(?:each|every|all|any) (?:other )?creatures?\b", re.I)
_OTHER = re.compile(r"\b(?:creatures? other than you|each other creature)\b", re.I)


def require_subjects(effect: dict[str, Any], source: str, *, reader: str | None = None) -> dict[str, Any] | None:
    """Require the sealed field and the recipient keys needed by this effect."""
    if "type" not in effect and effect.get("applies_to") != "ally" and reader is None:
        return None
    keys = ()
    if effect.get("type") == "save" or reader == "save":
        keys += ("area_scope", "exclude_self")
    if effect.get("applies_to") == "ally" or reader == "ally":
        keys += ("count", "within_ft", "or_self")
    subjects = effect.get("subjects")
    if "subjects" not in effect or (keys and (not isinstance(subjects, dict) or any(key not in subjects for key in keys))):
        detail = f" requires {', '.join(keys)}" if keys else " field is missing"
        raise ValueError(f"effect {effect.get('type')!r} from {source}: subjects{detail}")
    return subjects


def with_subjects(effect: dict[str, Any]) -> dict[str, Any]:
    """Derive subjects at the construction site and return the same effect."""
    derive_effect_subjects(effect)
    return effect


def derive_effect_subjects(node: Any, source: str | None = None) -> None:
    """Fill missing subjects throughout a final mechanic, in place, once at build.

    Authored subjects win as a whole but must satisfy the recipient contract.
    Null within_ft is
    deliberately unresolved: CL-scaled/self-centered area geometry is runtime
    context, not a number to freeze into the authority. Save area_scope applies
    only to an unscoped save in an area; explicit applies_to still wins.
    Traversal includes arbitrary extension effect containers and outcome lists.
    """
    if isinstance(node, list):
        for child in node:
            derive_effect_subjects(child, source)
    elif isinstance(node, dict):
        source = str(node.get("mechanic_id") or node.get("source_definition_id") or source or "<unattributed>")
        if "subjects" not in node:
            subjects = {}
            if node.get("applies_to") == "ally":
                text = str(node.get("evidence") or node.get("on") or "")
                found = _WITHIN_FT.search(text)
                subjects.update(
                    count="one" if _ONE_ALLY.search(text) and not _ALLIES.search(text) else "all",
                    within_ft=int(found.group(1)) if found else None,
                    or_self=bool(_YOU_OR.search(text)),
                )
            if node.get("type") == "save":
                phrase = str(node.get("recipient_text") or node.get("evidence") or "")
                scope = None
                if _HOSTILE_SAVE.search(phrase):
                    scope = "enemies_in_area"
                elif _AREA_CREATURE.search(phrase):
                    scope = "creatures_in_area" if _INCLUSIVE.search(phrase) else "enemies_in_area"
                subjects.update(area_scope=scope, exclude_self=bool(_OTHER.search(phrase)))
            if subjects or "type" in node:
                node["subjects"] = subjects or None
        require_subjects(node, source)
        for key, child in node.items():
            if key != "subjects":
                derive_effect_subjects(child, source)
