"""Shared later-hit data contract for the authority builder, factory_compiler and
typed_executor. Only the builder derives English; runtime consumers require the
sealed field. Code-built immediate extra_damage rows explicitly carry on_hit_bonus=None.
"""
from __future__ import annotations

import re
from typing import Any

_ON_HIT_BONUS = re.compile(
    r"\b(?:once (?:per|each) turn,?\s*when|the (?:first|next) time)\s+(?:(?:during each of your turns|each turn),?\s*)?"
    r"you\s+(?:hit|deal damage|damage)\b|\bonce per turn when (?:you|it) hits?\b|\byour first\b[^.;]*\bhit each turn\b", re.I)
_FIRST_NAMED_HIT = re.compile(r"\byour first\s+(.+?)\s+hit each turn\b", re.I)
_ON_HIT_CLAUSE = re.compile(r"\b(?:hits?|deal damage|damage)\b(.*?)(?:,\s*(?:you|deal|add|it|the)\b|[.;]|$)", re.I)
_ON_HIT_BOUND = re.compile(r"\bwhen you (?:damage|hit) it\b", re.I)
_DAMAGE_TRIGGER = re.compile(r"\bdamage it\b|\bdeal damage\b|\bdamage (?:a|the|that) (?:creature|target)\b", re.I)
_PER_TURN = re.compile(r"\bonce (?:per|each) turn\b|\beach turn\b|\bduring each of your turns\b", re.I)
_NEXT = re.compile(r"\bthe (?:first|next) time\b", re.I)
_HIT = re.compile(r"\bhits?\b", re.I)


def derive_on_hit(effect: dict[str, Any]) -> dict[str, Any] | None:
    """Preserve the executor's old registration, trigger and limit readings exactly.

    trigger=damage also permits non-attack damage; both triggers permit hits.
    attach_to_attack is independent: prose may mention both hit and damage.
    clause retains the existing hit-qualification grammar, not a new interpreter.
    """
    raw = str(effect.get("evidence") or "")
    if not effect.get("deferred") or not _ON_HIT_BONUS.search(raw):
        return None
    evidence = " ".join(raw.split())
    named = _FIRST_NAMED_HIT.search(evidence)
    clause = named or _ON_HIT_CLAUSE.search(
        evidence.split("when", 1)[-1] if "when" in evidence.lower() else evidence)
    limit = None
    if _PER_TURN.search(evidence):
        limit = "once_per_own_turn" if "during each of your turns" in evidence.lower() else "once_per_turn"
    elif _NEXT.search(evidence):
        limit = "next"
    return {
        "trigger": "damage" if _DAMAGE_TRIGGER.search(evidence) else "hit",
        "limit": limit,
        "bound": bool(_ON_HIT_BOUND.search(evidence)),
        "named": bool(named),
        "clause": clause.group(1) if clause else "",
        "attach_to_attack": bool(_HIT.search(evidence)),
    }


def walk_effect_containers(value: Any):
    """Walk nested typed data for the authority builder and saved-fight loader."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_effect_containers(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_effect_containers(child)


def seal_on_hit(mechanics: dict[str, dict]) -> None:
    """Builder boundary, after overlays: explicit reviewed fields (including null) win.

    Walk all containers, including modifier/options and custom effect branches.
    on_hit_bonus is deliberately distinct from the on_hit outcome-list key:
    existing branch walkers must not mistake trigger data for nested effects.
    """
    for value in walk_effect_containers(mechanics):
        if value.get("type") == "extra_damage" and "on_hit_bonus" not in value:
            value["on_hit_bonus"] = derive_on_hit(value)


def require_on_hit(effect: dict[str, Any], source: str) -> dict[str, Any] | None:
    """No runtime text fallback: an unsealed extra_damage is an authoring error."""
    if "on_hit_bonus" not in effect:
        raise ValueError(f"extra_damage missing required on_hit_bonus field (source {source})")
    value = effect["on_hit_bonus"]
    if value is None:
        return None
    if not isinstance(value, dict) or (
        value.get("trigger") not in ("hit", "damage")
        or value.get("limit", ...) not in (None, "next", "once_per_turn", "once_per_own_turn")
        or any(type(value.get(key)) is not bool for key in ("bound", "named", "attach_to_attack"))
        or not isinstance(value.get("clause"), str)
    ):
        raise ValueError(f"extra_damage invalid on_hit_bonus field (source {source})")
    return value
