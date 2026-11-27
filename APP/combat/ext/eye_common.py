"""Shared helpers for the Hidden Eye talents that depend on Analyze or on being hidden (eye, 2026-09-28).

Ownership at fight time: a talent that needs to know "does this actor have talent X" from a runtime hook (after_hit,
event, save...) -- where no ``info["owned_ids"]`` is available -- reads it off the character's own compiled passive
rows, tagged by combat/rules/feature_blocks.d/eye.json under the shared "hidden_eye" block (the same block name
mind_hidden_eye.py already uses for Identify Rhythms) with a "kind" of its own. ``has(engine, actor_id, kind)`` below
is the generic check.
"""

from __future__ import annotations

from typing import Any
from ..ability_checks import ability_modifier, passive_score

from .mind_hidden_eye import ANALYZED, BASE_ID, FOCUS, analyzed_by  # read-only reuse, not an edit

__all__ = ["ANALYZED", "BASE_ID", "FOCUS", "analyzed_by", "has", "numbers_of", "passive_perception", "skill"]


def has(engine: Any, actor_id: str, kind: str) -> bool:
    """Whether ``actor_id``'s compiled bundle carries a "hidden_eye" passive row of this ``kind`` (a feature_blocks.d
    tag for a talent this module automates)."""
    return any(row.get("block") == "hidden_eye" and row.get("kind") == kind
              for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, []))


def skill(engine: Any, creature: Any, name: str, fallback: int) -> int:
    """A creature's skill bonus: its compiled bundle's sheet "skills" (combat/ext/tabik_scoundrel.py), else the
    fallback (usually the related ability-check modifier)."""
    from .tabik_scoundrel import skill as _skill

    return _skill(engine, creature, name, fallback)


def numbers_of(engine: Any, actor: Any) -> dict[str, Any]:
    """Actor-wide casting numbers; infer from actions only for legacy actors."""
    from ..compiled_numbers import sealed_actor_numbers

    sealed = sealed_actor_numbers(engine, actor)
    if sealed is not None:
        return sealed
    for action in engine.action_catalog.values():
        if action.owner_id == actor.entity_id:
            numbers = (((action.parameters or {}).get("typed") or {}).get("numbers") or {})
            if numbers:
                return numbers
    return {}


def passive_perception_baseline(engine: Any, creature: Any) -> int:
    """Per-creature passive Perception used by detection and Beastmastery lookouts."""
    from . import run

    bonus = skill(engine, creature, "Perception", ability_modifier(creature, "WIS"))
    return passive_score(bonus) + sum(run("passive_perception", engine, creature))


def passive_perception(engine: Any, creature: Any, observed: Any = None) -> int:
    """The creature's passive Perception including any applicable overrides."""
    from . import run

    baseline = passive_perception_baseline(engine, creature)
    overrides = [n for n in run("passive_perception_override", engine, creature, observed, baseline) if n is not None]
    return max([baseline, *overrides])
