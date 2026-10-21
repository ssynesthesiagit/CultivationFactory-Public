"""Exact-text Metal Insights on the shared transactional d20 rewrite transport."""
from __future__ import annotations

from typing import Any

from . import hook
from .d20_rewrite import Holder, RollCtx, Rule, register

INSIGHT = "insight.hard-meridian-breathing"


@hook("save_roll_tags")
def hard_meridian_roll_tags(ctx: Any, subject: Any, ability: str, named: frozenset[str]) -> list[str] | None:
    """Carry an established forced-movement consequence to this owner's d20.

    A manual historical Insight has no compiled rewrite row and remains inert.
    No source-name inference or metadata is borrowed from another pending save.
    """
    if str(ability).upper()[:3] not in ("STR", "CON") or "forced_movement" not in named:
        return None
    rows = (getattr(ctx.engine, "typed_passive_rows", {}) or {}).get(subject.entity_id, [])
    if any(row.get("block") == "d20_rewrite" and row.get("kind") == "metal_hard_meridian_breathing"
           and row.get("feature_id") == INSIGHT and not row.get("held_back") for row in rows):
        return ["forced_movement"]
    return None


def hard_meridian_hazard(engine: Any, holder: Holder, rc: RollCtx) -> bool:
    """Use the save's pending consequences, never its name or the owner's state.

    A pre-existing restraint does not make an unrelated save qualify. Native
    saves without consequence metadata are left alone rather than guessed.
    """
    return bool(set(rc.named) & {"forced_movement", "prone", "grappled", "restrained"})


register(Rule(
    "metal_hard_meridian_breathing", "Hard-Meridian Breathing",
    rolls=("save",), abilities=("STR", "CON"),
    costs=((("cp", 1),),), limit="fight", guard=hard_meridian_hazard,
))


@hook("decision_text")
def hard_meridian_prompt(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, str] | None:
    if (str(context.get("reaction_source_id") or "").removeprefix("reaction:typed.") != INSIGHT
            or (context.get("choice_trigger") or {}).get("d20_rewrite_name") != "Hard-Meridian Breathing"):
        return None
    return {
        "summary": "Reroll this failed Strength or Constitution saving throw against forced movement, "
                   "Prone, Grappled or Restrained. You must use the new result.",
        "table_note": "Spend 1 point from the cultivation resource shown below. This needs no Action or Reaction. "
                      "You can use it once in this fight. Declining spends nothing and keeps that use available.",
    }
