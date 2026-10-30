"""Advantage or Disadvantage on the next Opportunity Attack (one shared seam for every "next Opportunity Attack" row).

typed_executor.block_advantage gives a creature the condition "condition:typed.opportunity_attack_mode" carrying
{"opportunity_attack_mode": {"mode", "next": bool, "side": "maker" | "target"}}:

* side "maker" (the default, Turn the Foot's failed-save choice: "it has Disadvantage on the next Opportunity Attack it
  makes") sits on the creature that makes the attack and changes the Opportunity Attacks that creature rolls;
* side "target" (Storm-Heart Engine: "impose Disadvantage on the next Opportunity Attack made against you") sits on the
  creature that is attacked and changes the Opportunity Attacks rolled against it.

Both sides are read through the documented accessor combat/typed_reactions.current_opportunity_attacker, which is set only
while the engine rolls an Opportunity Attack. A "next" condition is used up by the first such attack it changes, on that
attack's ATTACK_ROLLED. Any other plug-in that needs a "next Opportunity Attack" row adds the same condition through
apply_next_opportunity_attack_mode() below rather than writing its own hooks.
"""

from __future__ import annotations

from typing import Any

from . import hook
from ..typed_executor import CONDITION_PREFIX, is_active_typed_condition

CONDITION = CONDITION_PREFIX + "opportunity_attack_mode"
MAKER = "maker"
TARGET = "target"


def apply_next_opportunity_attack_mode(engine: Any, holder: Any, mode: str, *, side: str, source_definition_id: str,
                                       source_actor_id: Any, expires_on: str, label: str, source_ability: str = "Opportunity Attack",
                                       origin_save: dict[str, Any] | None = None) -> None:
    """Give `holder` one "next Opportunity Attack" mode (side MAKER or TARGET) until `expires_on`."""
    data = {"rule": {"opportunity_attack_mode": {"mode": mode, "next": True, "side": side, "source_ability": source_ability}},
            "label": label, **({"origin_save": origin_save} if origin_save else {})}
    engine._apply_condition(holder, CONDITION, source_definition_id, source_actor_id, expires_on=expires_on, data=data)


def _in_opportunity_attack_window(engine: Any, actor_id: Any) -> bool:
    from ..typed_reactions import current_opportunity_attacker
    return actor_id is not None and current_opportunity_attacker(engine) == actor_id


def _held_rules(creature: Any, side: str) -> list[tuple[Any, dict[str, Any]]]:
    out = []
    for held in creature.conditions.values():
        if held.condition_id == CONDITION and is_active_typed_condition(held):
            rule = ((held.data or {}).get("rule") or {}).get("opportunity_attack_mode") or {}
            if rule.get("side", MAKER) == side:
                out.append((held, rule))
    return out


@hook("attack_mode")
def opportunity_attack_mode(ctx: Any, target: Any) -> str | None:
    """Read-only: the mode a "maker" condition on the attacker gives the Opportunity Attack being rolled."""
    if not _in_opportunity_attack_window(ctx.engine, ctx.actor.entity_id):
        return None
    return next((rule["mode"] for _held, rule in _held_rules(ctx.actor, MAKER)
                 if rule.get("mode") in ("ADVANTAGE", "DISADVANTAGE")), None)


@hook("attack_mode")
def opportunity_attack_mode_against_target(ctx: Any, target: Any) -> str | None:
    """Read-only: the mode a "target" condition on the attacked creature gives the Opportunity Attack made against it."""
    if target is None or not _in_opportunity_attack_window(ctx.engine, ctx.actor.entity_id):
        return None
    return next((rule["mode"] for _held, rule in _held_rules(target, TARGET)
                 if rule.get("mode") in ("ADVANTAGE", "DISADVANTAGE")), None)


def _spend(creature: Any, engine: Any, side: str) -> None:
    for held, rule in _held_rules(creature, side):
        if rule.get("next"):
            engine._remove_condition(creature, CONDITION, held.source_definition_id)
            return


@hook("event")
def opportunity_attack_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A "next" Opportunity Attack uses its condition up on the roll it was answered for (either side)."""
    actor_id = kwargs.get("actor_id")
    if event_type != "ATTACK_ROLLED" or not _in_opportunity_attack_window(engine, actor_id):
        return
    if (actor := engine.state.actors.get(actor_id)) is not None:
        _spend(actor, engine, MAKER)
    for target_id in kwargs.get("target_ids") or ():
        if (target := engine.state.actors.get(target_id)) is not None:
            _spend(target, engine, TARGET)
