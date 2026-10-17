"""Bloodless Devouring: pay only after dealing damage to a creature below half HP."""

from __future__ import annotations

from typing import Any

from . import hook
from ..creature_types import has_type

SOURCE = "TAL_DAEMONIC_CULTIVATION_BLOODLESS_DEVOURING"
ESSENCE = "resource:named.devoured_essence"


def _owns(engine: Any, actor: Any) -> bool:
    return any(row.get("block") == "bloodless_devouring" for row in
               (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


@hook("compile_block")
def compile_bloodless_devouring(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": "bloodless_devouring", "kind": spec.get("kind"), "pb": numbers.get("pb"),
             "key_mod": numbers.get("key_mod"),
             **({"auto63": True} if spec.get("auto63") else {})} ] if block == "bloodless_devouring" else None


@hook("damage_dealt")
def bloodless_devouring(ctx: Any, target: Any, amount: int) -> None:
    """Run the printed once-per-turn choice after positive damage to a creature below half HP."""
    engine, actor = ctx.engine, ctx.actor
    row = next((r for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])
                if r.get('block') == 'bloodless_devouring'), {})
    corrected = bool(row.get('auto63'))
    stamp = f"{engine.state.round_number}:{engine.state.current_actor_id}"
    packet = next((event for event in reversed(engine.events)
                   if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == ctx.damage_source
                   and event.actor_id == actor.entity_id and target is not None and target.entity_id in event.target_ids), None)
    hp_before_damage = (target.current_hp + int(packet.payload.get("hp_damage") or 0)
                        if packet is not None and target is not None else (target.current_hp if target is not None else 0))
    if (amount <= 0 or target is None or not target.active or target.team_id == actor.team_id or not _owns(engine, actor)
            or hp_before_damage * 2 >= target.maximum_hp
            or actor.turn_flags.get("_round_bloodless_devouring") == stamp
            or int(actor.resources.get(ESSENCE, 0)) < 1):
        return

    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    choices = ["hp", "resource", "temporary_hp", "corruption"]
    pb = int(ctx.numbers.get("pb") or 2)
    modifier = int(ctx.numbers.get("key_mod") or 0)
    pools = ("resource:core.qi", "resource:core.stamina", "resource:core.resonance")
    can_regain = any(int(actor.resources.get(r, 0)) < int(actor.resource_maximums.get(r, 0)) for r in pools)
    kinds = ("demonic", "undead", "fiend", "possessing", "demon", "possessing entity", "active inner demon manifestation") if corrected else ("demonic", "undead", "fiend", "possessing")
    can_reduce_corruption = any(has_type(target, kind) for kind in kinds)
    labels = {
        "hp": f"Spend 1 Devoured Essence: regain {pb + modifier} HP",
        "resource": "Spend 1 Devoured Essence: regain 1 Cultivation Point (CP) or 1 Stamina",
        "temporary_hp": f"Spend 1 Devoured Essence: gain {2 * pb} Temporary HP",
        "corruption": "Spend 1 Devoured Essence: reduce Corruption by 1 (eligible creature only)",
    }
    if not can_regain:
        choices.remove("resource")
    if not can_reduce_corruption:
        choices.remove("corruption")
    if corrected:
        choices = [c for c in choices if c != 'resource']
        from ..resource_labels import resource_name
        for pool in pools:
            if int(actor.resources.get(pool, 0)) < int(actor.resource_maximums.get(pool, 0)):
                choices.append(pool)
                labels[pool] = f'Spend 1 Devoured Essence: regain 1 {resource_name(pool)}'
        if actor.resources.get('resource:named.corruption', 0) < 1 and 'corruption' in choices:
            choices.remove('corruption')
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "BLOODLESS_DEVOURING", ctx.source, target.entity_id), actor,
                 CHOICE + "bloodless_devouring", [*choices, "skip"], labels={**labels, "skip": "Do not use Bloodless Devouring"},
                 allow_decline=corrected,
                 name="Bloodless Devouring", prompt=f"Bloodless Devouring (once per turn): {ctx.action.display_name} dealt damage to {target.display_name}, who is below half HP.",
                 prompt_context=action_context(engine, actor, ctx.source, target))
    if not picked or picked[0] == "skip":
        return

    actor.turn_flags["_round_bloodless_devouring"] = stamp
    engine._spend_resource(actor, ESSENCE, 1, SOURCE)
    from ..typed_executor import Context, run_effects

    effect_context = Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [actor], actor, {})
    if picked[0] == "hp":
        run_effects(effect_context, [{"type": "healing", "applies_to": "self", "flat": pb + modifier,
                                     "evidence": "Regain HP equal to Proficiency Bonus + your Daemonic key ability modifier."}])
    elif corrected and picked[0] in pools:
        engine._gain_resource(actor, picked[0], 1, SOURCE)
    elif picked[0] == "resource":
        pool = next((r for r in pools
                     if int(actor.resources.get(r, 0)) < int(actor.resource_maximums.get(r, 0))), None)
        if pool is not None:
            engine._gain_resource(actor, pool, 1, SOURCE)
    elif picked[0] == "temporary_hp":
        run_effects(effect_context, [{"type": "temp_hp", "applies_to": "self", "flat": 2 * pb,
                                     "evidence": "Gain Temporary HP equal to twice your Proficiency Bonus."}])
    elif corrected:
        engine._spend_resource(actor, 'resource:named.corruption', 1, SOURCE)
    else:
        engine._append_event("GM_RIDER", SOURCE, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                             payload={"rider": "Reduce Corruption by 1 if the creature was a demon, undead, fiend, possessing entity, or active inner demon manifestation."})
