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
             **({"a2_packets": True, "choice_owner": True} if spec.get("a2_packets") else {}),
             **({"auto63": True} if spec.get("auto63") else {})} ] if block == "bloodless_devouring" else None


@hook("damage_dealt")
def bloodless_devouring(ctx: Any, target: Any, amount: int, *, committed_packet: dict | None = None) -> None:
    """Run the printed once-per-turn choice after positive damage to a creature below half HP."""
    engine, actor = ctx.engine, ctx.actor
    row = next((r for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])
                if r.get('block') == 'bloodless_devouring'), {})
    corrected = bool(row.get('auto63'))
    modern = bool(row.get("a2_packets"))
    if modern and committed_packet is None:
        return  # The packet event is the sole modern delivery; typed notification must not double-fire.
    stamp = f"{engine.state.round_number}:{engine.state.current_slot_index if modern else engine.state.current_actor_id}"
    packet = next((event for event in reversed(engine.events)
                   if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == ctx.damage_source
                   and event.actor_id == actor.entity_id and target is not None and target.entity_id in event.target_ids), None)
    hp_before_damage = (int(committed_packet["hp_before"])
                        if committed_packet is not None else target.current_hp + int(packet.payload.get("hp_damage") or 0)
                        if packet is not None and target is not None else (target.current_hp if target is not None else 0))
    if (amount <= 0 or target is None or (not modern and (not target.active or target.team_id == actor.team_id)) or not _owns(engine, actor)
            or hp_before_damage * 2 >= target.maximum_hp
            or actor.turn_flags.get("_round_bloodless_devouring") == stamp
            or int(actor.resources.get(ESSENCE, 0)) < 1):
        return

    from .choice_prompt import action_context
    from .needle import CHOICE, ask, checkpoint_id

    choices = ["hp", "resource", "temporary_hp", "corruption"]
    pb = int((row if modern else ctx.numbers).get("pb") or 2)
    modifier = int((row if modern else ctx.numbers).get("key_mod") or 0)
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
    from .choice_costs import Payment
    payment = Payment(ESSENCE, 1) if modern else None
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "BLOODLESS_DEVOURING", ctx.source, target.entity_id), actor,
                 CHOICE + "bloodless_devouring", [*choices, "skip"], labels={**labels, "skip": "Do not use Bloodless Devouring"},
                 allow_decline=corrected,
                 name="Bloodless Devouring", prompt=f"Bloodless Devouring (once per turn): {ctx.action.display_name} dealt damage to {target.display_name}, who is below half HP.",
                 prompt_context=action_context(engine, actor, ctx.source, target), payment=payment)
    if not picked or picked[0] == "skip":
        return

    actor.turn_flags["_round_bloodless_devouring"] = stamp
    if payment is not None:
        payment.pay(engine, actor, SOURCE)
    else:
        engine._spend_resource(actor, ESSENCE, 1, SOURCE)
    from ..typed_executor import Context, run_effects

    benefit_action = ctx.action
    if modern:
        from ..gate2_runtime_models import ActionDefinition, EconomyKind
        benefit_action = ActionDefinition(source_definition_id=SOURCE, display_name="Bloodless Devouring",
                                          owner_id=actor.entity_id, economy=EconomyKind.NONE, resolution_kind="TYPED",
                                          target_kind="SELF", range_ft=None, parameters={})
    effect_context = Context(engine, actor, benefit_action, ctx.intent,
                             {"numbers": {"pb": pb, "key_mod": modifier}} if modern else ctx.typed, [actor], actor, {})
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


@hook("event", nested=True)
def bloodless_packet(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Fresh owned rows respond to all positive committed damage, native or typed.

    The event's HP receipt qualifies the creature before this packet, including
    a lethal hit. There is no hostile-only clause in the printed talent.
    Legacy rows retain their original typed-only notification path.
    """
    if event_type != "DAMAGE_COMMITTED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    row = next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(
        getattr(actor, "entity_id", ""), []) if r.get("block") == "bloodless_devouring" and r.get("a2_packets")), None)
    payload = kwargs.get("payload") or {}
    amount = int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0)
    source = kwargs.get("source_definition_id") or ""
    action = engine.action_catalog.get(source)
    if row is None or amount <= 0:
        return
    from ..typed_executor import Context
    from ..pending_damage import current
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .ability_source import source_label

    if action is None:
        action = ActionDefinition(source_definition_id=source, display_name=source_label(engine, source) or "Damage",
                                  owner_id=actor.entity_id, economy=EconomyKind.NONE, resolution_kind="TYPED",
                                  target_kind="ENTITY", range_ft=None, parameters={})
    packet = current(engine)
    typed = {**((action.parameters or {}).get("typed") or {}),
             "numbers": {"pb": int(row.get("pb") or 0), "key_mod": int(row.get("key_mod") or 0)}}
    for tid in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(tid)
        if target is not None:
            ctx = Context(engine, actor, action, getattr(engine, "_active_intent", None), typed, [target], target)
            before = (packet.hp_before if packet is not None and
                      (packet.source_id, packet.source_actor_id, packet.target_id) == (source, actor.entity_id, tid)
                      else int(payload.get("remaining_hp") or 0) + int(payload.get("hp_damage") or 0))
            bloodless_devouring(ctx, target, amount, committed_packet={**payload, "hp_before": before})
