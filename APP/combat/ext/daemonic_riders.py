"""Daemonic rider gates, Black-Claw's hit menu and Black Sun's spend consequence.

Demon-Shadow Step enforces printed adjacency/sight; Heaven-Spiting Recovery
requires active Demon Seed. ``rider_black_claw`` carries its hit options and
numbers in a timed state; ``rider_claw_step`` resolves the printed target-only
OA exemption through ordinary legal movement. ``rider_black_sun_spend`` arms
one positive CP/Stamina spend consequence using the existing event hook.
No inferred creature taxonomy
or Realm is assigned. Sources: rules_text.json, Daemonic Cultivation.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

SHADOW = "TAL_DAEMONIC_CULTIVATION_DEMON_SHADOW_STEP"
RECOVERY = "TAL_DAEMONIC_CULTIVATION_HEAVEN_SPITING_RECOVERY"
SEED = "condition:typed.stance.demon_seed"
CLAW = "TAL_DAEMONIC_CULTIVATION_BLACK_CLAW_MANIFESTATION"
CLAW_STATE = "condition:typed.state.black_claw_manifestation"
BLACK_SUN_STATE = "condition:typed.black_sun_spend"
DREAD = "TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE"


@hook('flight')
def inner_demon_flight(engine, actor):
    if any((c.data or {}).get('auto63_walking_flight') for c in actor.conditions.values()):
        return {'fly_speed_ft': max(0, engine._effective_speed(actor)), 'flight_hover': 0}
    return None


@hook("candidate_allowed")
def dread_appetite_immunity(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """A successful save protects against this caster until their Short Rest.

    Fights have no rest transition; the owner-qualified mark persists for the
    fight, just like other rest-bound protections. Other casters are unaffected.
    """
    from ..typed_executor import bears_mark

    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if (typed.get("option_of") or typed.get("source")) != DREAD:
        return None
    if any(e.get('auto63_dread_senses') for e in typed.get('effects') or []):
        from ..target_knowledge import can_see
        from ..typed_executor import cant_hear, condition_rules
        for tid in candidate.target_ids:
            subject = engine.state.actors.get(tid)
            if subject is None:
                return False
            if any(e.get('auto63_requires_frightened') for e in typed.get('effects') or []):
                if not any(c.condition_id == 'condition:typed.frightened' for c in subject.conditions.values()):
                    return False
            hears = not cant_hear(subject) and not any(r.get('cant_speak') for r in condition_rules(actor))
            if not (can_see(engine, subject, actor) or hears):
                return False
    if any(bears_mark(engine.state.actors[t], actor.entity_id, "Dread Appetite immunity")
           for t in candidate.target_ids if t in engine.state.actors):
        return False
    return None


@effect("rider_black_sun_spend")
def black_sun_spend(ctx: Any, spec: dict[str, Any]) -> None:
    """Arm one spend consequence, not damage on the initial Wisdom save.

    Choose its printed damage type when applying the effect, while the caster's
    intent is available. Persist only scalar damage numbers/type; the ordinary
    caster-turn expiry also removes an untriggered consequence. Typed conditions
    separately carry the reviewed native CP-gain denial.
    """
    from .. import typed_executor as te
    from . import needle

    for subject in te._default_subject(ctx, spec, harmful=True):
        kinds = ["psychic", "necrotic"]
        preferred = te.choose_damage_type(ctx, [k.upper() for k in kinds], [subject]).lower()
        chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "black_sun_damage", subject.entity_id),
                            ctx.actor, needle.CHOICE + "black_sun_damage", kinds, preferred=[preferred],
                            labels={"psychic": "Psychic damage", "necrotic": "Necrotic damage"},
                            name="Black Sun Over the Dantian",
                            prompt=f"Black Sun Over the Dantian on {subject.display_name}: choose the damage type for its first "
                                   "Qi, Stamina or Resonance spend during this effect. This choice costs no extra action or resource.",
                            target_id=subject.entity_id)
        # A mandatory type choice may use its normal automatic default.
        kind = (chosen or [preferred])[0]
        count, sides = int(spec.get("count") or 0), int(spec.get("sides") or 0)
        flat = ctx.formula(spec.get("formula"))
        damage = (f"{count}d{sides}" + (f" + {flat}" if flat else "")) if count else str(flat)
        expiry = te.effect_expiry(ctx, spec, subject, condition=True)
        edge = 'end' if str(expiry).startswith('END_') else 'start'
        ctx.engine._apply_condition(subject, BLACK_SUN_STATE, ctx.source, ctx.actor.entity_id,
                                    expires_on=expiry,
                                    data={"count": count, "sides": sides, "flat": flat, "damage_type": kind,
                                          "label": f"Black Sun: {subject.display_name}'s next cultivation-point spend hurts",
                                          "reading": f"Until the {edge} of {ctx.actor.display_name}'s next turn, the first time "
                                          f"{subject.display_name} spends Qi, Stamina or Resonance, it takes {damage} {kind} damage. "
                                          "This damage trigger then ends."})

@hook("event", nested=True)
def black_sun_resource_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Consume the armed consequence after an observed positive CP/Stamina spend.

    Opt into bounded child-event delivery so a spend inside another event rider
    consumes the same first-spend consequence as an ordinary action payment.
    Damage resolves through the native typed effect path, whose committed event
    reaches nested-aware damage subscribers and reactions.
    """
    if event_type != "RESOURCE_SPENT":
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("amount") or 0) <= 0 or not str(payload.get("resource_id") or "").endswith((".qi", ".stamina", ".resonance")):
        return
    subject = engine.state.actors.get(kwargs.get("actor_id") or "")
    if subject is None:
        return
    from .. import typed_executor as te

    for instance_id, state in list(subject.conditions.items()):
        if state.condition_id != BLACK_SUN_STATE:
            continue
        caster = engine.state.actors.get(state.source_actor_id)
        action = engine.action_catalog.get(state.source_definition_id)
        if caster is None or action is None:
            continue
        # Remove this exact source instance before damage/reactions can recurse.
        subject.conditions.pop(instance_id)
        engine._append_event("CONDITION_REMOVED", state.source_definition_id, actor_id=subject.entity_id,
                             target_ids=(subject.entity_id,), payload={"condition_id": BLACK_SUN_STATE,
                                                                     "instance_id": instance_id, "reason": "CONSUMED"})
        data = state.data
        # As with ordinary deferred watches, retain the source's compiled
        # context without granting activation potency a second time.
        te.run_effects(te.Context(engine, caster, action, getattr(engine, "_active_intent", None),
                                  action.parameters.get("typed") or {}, [subject], subject,
                                  {"_potency_used": True}),
                       [{"type": "damage", "applies_to": "target", "flat": data["flat"],
                         "dice": {"count": data["count"], "sides": data["sides"]} if data["count"] else None,
                         "damage_types": [data["damage_type"]]}])


@hook("candidate_allowed")
def shadow_destination(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from .. import typed_executor as te

    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") != SHADOW or not any(row.get("type") == "rider_shadow_gate" for row in typed.get("effects") or []):
        return None
    destination = candidate.destination
    if destination is None or not engine._line_of_sight_actor_to_cell(actor, destination):
        return False
    return any(other.active and engine.grid.distance_ft(destination, other.position) <= 5
               and (te.bears_mark(other, actor.entity_id, "Demon Mark") or other.current_hp * 2 < other.maximum_hp
                    or any(c.condition_id == te.CONDITION_PREFIX + "frightened" for c in other.conditions.values()))
               for other in engine.state.actors.values())


@hook("row_allowed")
def recovery_requires_seed(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") == RECOVERY and any(effect.get("type") == "rider_seed_gate" for effect in row.get("effects") or []):
        return any(c.condition_id == SEED for c in actor.conditions.values())
    return None


# Declarative markers keep the gates opt-in for freshly compiled characters.
@effect("rider_shadow_gate")
@effect("rider_seed_gate")
def marker(ctx: Any, spec: dict[str, Any]) -> None:
    pass


@effect("rider_black_claw")
def black_claw(ctx: Any, spec: dict[str, Any]) -> None:
    """Store the printed hit menu for this paid manifestation, while Seed lasts.

    Options are resolved after a hit, never during activation. The once-turn
    allowance is shared across targets, unarmed strikes and natural weapons.
    """
    import copy

    ctx.engine._remove_condition(ctx.actor, CLAW_STATE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CLAW_STATE, ctx.source, ctx.actor.entity_id,
                                expires_on="UNTIL_REMOVED",
                                data={"options": copy.deepcopy(spec["options"]), "numbers": dict(ctx.numbers)})


@hook("candidate_allowed")
def claw_requires_seed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") == CLAW and any(e.get("type") == "rider_black_claw" for e in typed.get("effects") or []):
        return None if any(c.condition_id == SEED for c in actor.conditions.values()) else False
    return None


@hook("event")
def claw_seed_ended(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in {"CONDITION_REMOVED", "TURN_STARTED"}:
        return
    for actor in list(engine.state.actors.values()):
        if not any(c.condition_id == SEED for c in actor.conditions.values()):
            engine._remove_condition(actor, CLAW_STATE, CLAW)


@hook("after_hit")
def claw_hit(ctx: Any, target: Any, kind: str) -> None:
    from .. import typed_executor as te
    from . import needle

    state = next((c for c in ctx.actor.conditions.values() if c.condition_id == CLAW_STATE), None)
    if state is None or kind != "unarmed" or not any(c.condition_id == SEED for c in ctx.actor.conditions.values()):
        return
    flag = f"black_claw:{ctx.engine.state.round_number}:{ctx.engine.state.current_slot_index}"
    if ctx.actor.turn_flags.get(flag):
        return
    from dataclasses import replace

    action = ctx.engine.action_catalog[state.source_definition_id]
    inner = replace(ctx, action=action, typed={**action.parameters["typed"], "numbers": state.data["numbers"]},
                    targets=[target], target=target, damage_cache={})
    options = state.data["options"]
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "black_claw", target.entity_id), ctx.actor,
                        needle.CHOICE + "black_claw", [o["id"] for o in options],
                        labels={o["id"]: o["label"] for o in options}, minimum=1, maximum=1,
                        allow_decline=True, preferred=[options[0]["id"]], default_count=1,
                        prompt=f"Black-Claw Manifestation: choose one benefit after {ctx.action.display_name} hits {target.display_name}",
                        target_id=target.entity_id, name="Black-Claw Manifestation", feature_id=CLAW)
    if not chosen:
        return
    ctx.actor.turn_flags[flag] = True
    for option in options:
        if option["id"] in chosen:
            from .rider_outcomes import settle

            settle(replace(inner, typed={**inner.typed, "triggering_action": ctx.action.display_name}), option["effects"])


@effect("rider_claw_step")
def claw_step(ctx: Any, spec: dict[str, Any]) -> None:
    """An immediate ordinary 5-foot move; only the struck target cannot provoke.

    Use legal movement candidates and the ordinary movement resolver so other
    enemies, terrain, hazards and movement reactions retain their rules.
    """
    from . import needle
    from .movement_steps import immediate_step_budget

    engine, actor = ctx.engine, ctx.actor
    allowance = immediate_step_budget(engine, actor, 5)
    if allowance <= 0:
        return
    previous_budget = actor.movement_remaining_ft
    actor.movement_remaining_ft = allowance
    try:
        # Existing actor-specific reducer supplies this owner's paths even
        # during another actor's turn; never borrow the current actor's menu.
        candidates = engine._movement_candidates(actor)
        options = {needle.cell_id(c.destination): c for c in candidates}
        if not options:
            return
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "black_claw_step", actor.entity_id), actor,
                            needle.CHOICE + "black_claw_step", list(options), minimum=0, maximum=1,
                            labels={key: f"Move to ({c.destination.x}, {c.destination.y}), {c.movement_cost_ft} feet"
                                    for key, c in options.items()},
                            allow_decline=True, default_count=0, default="decline",
                            prompt=f"Black-Claw Manifestation: after {ctx.typed.get('triggering_action') or ctx.action.display_name} "
                                   f"hits {ctx.target.display_name}, move {actor.display_name} up to 5 feet",
                            target_id=ctx.target.entity_id, name="Black-Claw Manifestation", feature_id=CLAW)
        if chosen:
            actor.turn_flags["black_claw_step_target"] = ctx.target.entity_id
            try:
                engine._resolve_movement(actor, options[chosen[0]], ctx.intent)
            finally:
                actor.turn_flags.pop("black_claw_step_target", None)
    finally:
        actor.movement_remaining_ft = previous_budget


@hook("opportunity_allowed")
def claw_step_no_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    return False if mover.turn_flags.get("black_claw_step_target") == reactor.entity_id else None


@hook("attack_damage_types")
def claw_damage_types(ctx: Any, attack: dict[str, Any], kinds: list[str]) -> list[str] | None:
    """Only Unarmed Strikes gain the printed optional damage types, not natural weapons."""
    from . import needle

    if attack.get("attack_kind") != "unarmed" or not any(c.condition_id == CLAW_STATE for c in ctx.actor.conditions.values()) \
            or not any(c.condition_id == SEED for c in ctx.actor.conditions.values()):
        return None
    options = list(dict.fromkeys([*[str(k).lower() for k in kinds], "slashing", "piercing", "necrotic", "force"]))
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "black_claw_damage", ctx.source), ctx.actor,
                        needle.CHOICE + "black_claw_damage", options, minimum=1, maximum=1, allow_decline=True,
                        preferred=options[:1], default_count=1,
                        prompt=f"Black-Claw Manifestation: choose {ctx.action.display_name} damage type against "
                               f"{', '.join(t.display_name for t in ctx.targets)}",
                        target_id=ctx.target.entity_id if ctx.target else None, name="Black-Claw Manifestation", feature_id=CLAW)
    return chosen or None
