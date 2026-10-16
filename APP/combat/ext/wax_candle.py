"""Funeral Candle Shelter (Wax; rider lane C11, 2026-09-30).

Source (owner text, authority/typed_mechanics/rules_text.json TAL_WAX_FUNERAL_CANDLE_SHELTER): "Reaction. Trigger: A creature you can see
within 60 feet would die, have its corpse destroyed, or have its departing trace scattered. Cost 5 CP. ... Shelter the Dying. If the
creature would die from damage, it instead falls to 0 hit points and becomes stable, provided the damage did not destroy the body
outright. The candle ends. Shelter the Departing Trace. If the creature dies, you preserve a respectful departing trace ... for 1 hour ...
A creature can benefit from Funeral Candle Shelter only once per long rest."

How it runs. The table's ordinary 0 Hit Points is a nonlethal defeat (the creature leaves the fight); a creature dies only under the
life-and-death rules (combat/ext/life_state.py: Dying, death saving throws, massive damage). This module is a death handler of that
module's public ``handler`` API (priority -50: before the soul-keeping handlers, after the delaying ones). When a creature would die from
damage (life_state's "massive damage", or a third failed death save that damage caused), each owner of the talent (feature block
``wax_candle``) that can see it within 60 feet with its Reaction and 5 CP is asked (a player; the AI shelters an ally or itself, never a
foe); the first to accept spends both and the creature stays at 0 Hit Points and becomes Stable. Once per fight per creature ("once per
long rest"). A death save rolled to three failures is not "from damage" and is left alone. Shelter the Departing Trace (a trace kept for
an hour for later rites) is the GM's.
Default-inert: nobody owns the row, nothing changes.
"""

from __future__ import annotations

from typing import Any

from . import hook, life_state, note

BLOCK = "wax_candle"
FEATURE = "TAL_WAX_FUNERAL_CANDLE_SHELTER"
USED = "typed_round_funeral_candle"  # on the sheltered creature: saved with the fight
COST = 5
RANGE_FT = 60


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "kind": spec.get("kind")}]


def _owners(engine: Any, target: Any) -> list[Any]:
    from .. import stealth, typed_executor, typed_reactions

    out = []
    for owner in engine.state.actors.values():
        if not owner.active or owner.life_state is not None or not typed_reactions._rows(engine, owner.entity_id, BLOCK):
            continue
        pool = next((p for p in typed_executor.CP_POOLS if owner.resources.get(p, 0) >= COST), None)
        if pool is None or not owner.reaction_available or any(row.get("no_reactions") for row in typed_executor.condition_rules(owner)):
            continue
        if owner.entity_id != target.entity_id and (engine._distance_actor_to_actor(owner, target) > RANGE_FT or not stealth.sees(engine, owner, target)):
            continue
        out.append((owner, pool))
    return sorted(out, key=lambda row: (row[0].team_id != target.team_id, row[0].entity_id))


def _from_damage(engine: Any, target: Any, cause: str, source_id: str) -> bool:
    if cause == "massive damage":
        return True
    # life_state settles damage failures with system:damage, and rolled death
    # saves with their save source. Its explanatory note may follow the damage.
    return cause.startswith("three failed") and source_id == "system:damage"


def shelter(engine: Any, target: Any, cause: str, source_id: str) -> bool:
    if target.turn_flags.get(USED) or not _from_damage(engine, target, str(cause), source_id):
        return False
    from .needle import CHOICE, ask, checkpoint_id
    from .choice_prompt import action_context

    damage = next((e for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED"
                   and target.entity_id in (e.target_ids or ())), None)
    source = damage.source_definition_id if damage else source_id
    attacker = engine.state.actors.get(damage.actor_id) if damage else None
    context = action_context(engine, attacker, source, target)
    action_name = context["action_name"] or "the damaging effect"

    for owner, pool in _owners(engine, target):
        friendly = owner.team_id == target.team_id
        picked = ask(engine, engine._active_intent, checkpoint_id(engine, "funeral_candle", owner.entity_id, target.entity_id), owner,
                     CHOICE + "funeral_candle", ["shelter"], allow_decline=True, preferred=["shelter"] if friendly else [],
                     default="first" if friendly else "decline", target_id=target.entity_id, name="Funeral Candle Shelter",
                     labels={"shelter": f"Spend your Reaction and {COST} CP: {target.display_name} stays at 0 Hit Points, Stable"},
                     prompt_context=context,
                     prompt=f"Funeral Candle Shelter: {action_name} would kill {target.display_name} ({cause}). Light the funeral candle?")
        if not picked:
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, owner, FEATURE, independent=True):
            owner.reaction_available = False
            engine._spend_resource(owner, pool, COST, FEATURE)
            target.turn_flags[USED] = owner.entity_id
            if target.current_hp:
                target.current_hp = 0
            if not life_state.stabilize(engine, target, FEATURE) and target.life_state != "STABLE":
                engine._set_life_state(target, "STABLE", FEATURE)
            note(engine, FEATURE, owner, f"Funeral Candle Shelter: {owner.display_name} wraps {target.display_name} in white wax light -- instead "
                 "of dying it stays at 0 Hit Points and is Stable.", (target,))
            return True
    return False


life_state.handler(shelter, priority=-50)
