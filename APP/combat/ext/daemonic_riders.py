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
        from .daemonic_circulation import selected
        if selected(ctx) is not None:
            # choose_damage_type already transported and rewarded the final
            # selection; never offer a second, independently answerable menu.
            chosen = [preferred]
        else:
            chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "black_sun_damage", subject.entity_id),
                                ctx.actor, needle.CHOICE + "black_sun_damage", kinds, preferred=[preferred],
                            labels={kind: f"{kind.title()} damage" for kind in kinds},
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
                         "damage_types": [data["damage_type"]],
                         "resolved_damage_type": data["damage_type"]}])


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

    state = _claw_state(ctx.actor)
    if state is None or kind != "unarmed" or not any(c.condition_id == SEED for c in ctx.actor.conditions.values()):
        return
    flag = _claw_used_flag(ctx.engine)
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


def _claw_used_flag(engine: Any) -> str:
    """This actor-turn's once-per-turn allowance, shared by the hit menu and the row/pill display."""
    return f"black_claw:{engine.state.round_number}:{engine.state.current_slot_index}"


def _claw_allowance_text(engine: Any, actor: Any) -> str:
    """Says whether this turn's once-per-turn benefit is still open or already taken."""
    if not actor.turn_flags.get(_claw_used_flag(engine)):
        return "The once-per-turn on-hit choice is still available this turn."
    return "The once-per-turn on-hit choice is spent this turn."


def _claw_state(actor: Any):
    return next((c for c in actor.conditions.values() if c.condition_id == CLAW_STATE), None)


def _derived_attack(row: dict[str, Any]) -> dict[str, Any] | None:
    typed = (row.get("parameters") or {}).get("typed") or {}
    return next((effect for effect in typed.get("effects") or []
                 if isinstance(effect, dict) and effect.get("type") == "attack"), None)


@hook("attack_state_rows")
def claw_attack_row(engine: Any, actor: Any, row: dict[str, Any]) -> list[dict[str, str]] | None:
    """Name Black-Claw on the Unarmed Strike / natural-weapon row and state its once-per-turn status.

    Presentation only (combat/ext/__init__.py "attack_state_rows"): a character
    without the manifestation keeps its exact row, and nothing here is priced or
    persisted.
    """
    if actor is None or _claw_state(actor) is None or not _seeded(actor):
        return None
    attack = _derived_attack(row)
    source = str(row.get("source_definition_id") or "")
    if attack is None or (attack.get("attack_kind") not in ("unarmed", "natural_weapon") and ".natural." not in source):
        return None
    return [{
        "label": "Black Claw",
        "note": ("Black-Claw Manifestation is active: your Unarmed Strikes may deal Slashing, Piercing, Necrotic "
                 "or Force damage. " + _claw_allowance_text(engine, actor)),
    }]


@hook("status_description")
def claw_status(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    """The manifestation's own pill: what it changes, and whether this turn's benefit is still open."""
    if (row or {}).get("condition_id") != CLAW_STATE:
        return None
    if holder is None:
        return None
    return {
        "display_name": "Black-Claw Manifestation",
        "text": ("Your Unarmed Strikes may deal Slashing, Piercing, Necrotic or Force damage. Once per turn when "
                 "you hit with an Unarmed Strike or natural weapon, choose one benefit (Temporary HP, a 5-foot "
                 "move, -5 feet Speed, or your demonic mark). " + _claw_allowance_text(engine, holder)),
    }


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
    from ..typed_executor import choose_damage_type

    # The table's own automatic pick (the type that lands hardest) is the
    # preferred option, so an AI seat answers this menu the same way it answers
    # every other damage-type choice; a player still sees the full list.
    best = choose_damage_type(ctx, list(options), list(ctx.targets)).lower()
    preferred = [best if best in options else options[0]]
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "black_claw_damage", ctx.source), ctx.actor,
                        needle.CHOICE + "black_claw_damage", options, minimum=1, maximum=1, allow_decline=True,
                        preferred=preferred, default_count=1,
                        labels={kind: f"{kind.title()} damage" for kind in options},
                        prompt=f"Black-Claw Manifestation: choose {ctx.action.display_name} damage type against "
                               f"{', '.join(t.display_name for t in ctx.targets)}",
                        target_id=ctx.target.entity_id if ctx.target else None, name="Black-Claw Manifestation", feature_id=CLAW)
    return chosen or None


ESSENCE = "resource:named.devoured_essence"
CORRUPTION = "resource:named.corruption"
FURNACE = "TAL_DAEMONIC_CULTIVATION_SECOND_FURNACE_DEMON_HEART"
INNER = "TAL_DAEMONIC_CULTIVATION_INNER_DEMON_INCARNATION"
INNER_STATE = "condition:typed.a2_inner_incarnation"


@hook("compile_block")
def furnace_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]):
    if block != "a2_second_furnace":
        return None
    return [{**row, "pb": int(numbers.get("pb") or 0), "cl": int(numbers.get("cl") or 1),
             "choice_owner": True}]


def _furnace(engine: Any, actor: Any):
    return next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
                 if r.get("block") == "a2_second_furnace" and int(r.get("cl") or 0) >= 5), None)


def _seeded(actor: Any) -> bool:
    return any(c.condition_id == SEED for c in actor.conditions.values())


@hook("turn_start_choice")
def furnace_empty_pool(engine: Any, actor: Any) -> None:
    """Ask before the printed Corruption-for-Essence trade; absent pools are not zero pools."""
    row = _furnace(engine, actor)
    if row is None or not actor.active or actor.current_hp <= 0 or not _seeded(actor):
        return
    if not any(pool in actor.resources and actor.resources[pool] == 0
               for pool in ("resource:core.qi", "resource:core.resonance", "resource:core.stamina")):
        return
    if ESSENCE not in actor.resources or CORRUPTION not in actor.resources:
        return
    # The evented resource helper clamps at the maximum. Overflow requires
    # Demonic Debt, which has no saved-state contract yet; defer that exchange.
    corruption_before = actor.resources[CORRUPTION]
    corruption_maximum = actor.resource_maximums.get(CORRUPTION)
    if corruption_maximum is None or corruption_maximum - corruption_before < 1:
        engine._append_event("GM_RIDER", FURNACE, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"automated": False, "rider":
                                      "Second Furnace Demon Heart: the Corruption-for-Essence exchange is deferred. "
                                      "Corruption cannot increase by 1; overflow would require Demonic Debt, "
                                      "which must be resolved with the GM before this exchange can be used."})
        return
    from . import needle

    chosen = needle.ask(engine, getattr(engine, "_active_intent", None),
                        needle.checkpoint_id(engine, "second_furnace", actor.entity_id), actor,
                        needle.CHOICE + "second_furnace", ["accept"],
                        labels={"accept": "Gain 1 Corruption and 1 Devoured Essence; no Action or Reaction"},
                        allow_decline=True, default="decline", default_count=0,
                        name="Second Furnace Demon Heart", feature_id=FURNACE, target_id=actor.entity_id,
                        prompt=f"Second Furnace Demon Heart: {actor.display_name}'s turn starts with an empty "
                               "cultivation-point or Stamina pool while Demon Seed is active. Accept 1 Corruption "
                               "to gain 1 Devoured Essence, or pass.")
    if chosen:
        engine._gain_resource(actor, CORRUPTION, 1, FURNACE)
        if actor.resources[CORRUPTION] - corruption_before == 1:
            engine._gain_resource(actor, ESSENCE, 1, FURNACE)


@hook("event", nested=True)
def furnace_spend(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "RESOURCE_SPENT":
        return
    payload = kwargs.get("payload") or {}
    if payload.get("resource_id") != ESSENCE or int(payload.get("amount") or 0) <= 0:
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    row = _furnace(engine, actor) if actor is not None else None
    stamp = f"{engine.state.round_number}:{engine.state.current_slot_index}"
    if row is None or not _seeded(actor) or actor.turn_flags.get("a2_furnace_spend") == stamp:
        return
    actor.turn_flags["a2_furnace_spend"] = stamp
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context, run_effects

    action = ActionDefinition(source_definition_id=FURNACE, display_name="Second Furnace Demon Heart",
                              owner_id=actor.entity_id, economy=EconomyKind.NONE, resolution_kind="TYPED",
                              target_kind="SELF", range_ft=None, parameters={})
    run_effects(Context(engine, actor, action, getattr(engine, "_active_intent", None), {}, [actor], actor),
                [{"type": "temp_hp", "applies_to": "self", "flat": int(row["pb"])}])


@effect("rider_inner_incarnation")
def inner_incarnation(ctx: Any, spec: dict[str, Any]) -> None:
    """New activations seal a separate lifetime ledger, not current-authority inference."""
    from ..typed_executor import effect_expiry

    ctx.engine._remove_condition(ctx.actor, INNER_STATE, ctx.source)
    ctx.engine._apply_condition(ctx.actor, INNER_STATE, ctx.source, ctx.actor.entity_id,
                                expires_on=effect_expiry(ctx, spec, ctx.actor, condition=True),
                                data={"a2_incarnation": 1,
                                      "label": "Inner Demon Incarnation: magical attacks and one extra Essence per round; "
                                               "ending gains 1 Corruption, or 2 with no Essence"})


@hook("attack_magical")
def inner_magical(engine: Any, source_actor_id: str, typed: dict[str, Any]) -> bool | None:
    actor = engine.state.actors.get(source_actor_id)
    if actor is not None and any(c.condition_id == INNER_STATE for c in actor.conditions.values()):
        return True
    return None


@hook("event", nested=True)
def inner_lifecycle(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in {"RESOURCE_GAINED", "CONDITION_REMOVED"}:
        return
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_REMOVED":
        if payload.get("condition_id") != INNER_STATE:
            return
        for tid in kwargs.get("target_ids") or ():
            actor = engine.state.actors.get(tid)
            if actor is not None:
                engine._gain_resource(actor, CORRUPTION, 1 + int(actor.resources.get(ESSENCE, 0) == 0), INNER)
        return
    if payload.get("resource_id") != ESSENCE or int(payload.get("gained") or 0) <= 0:
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or not any(c.condition_id == INNER_STATE for c in actor.conditions.values()):
        return
    if actor.turn_flags.get("_round_a2_inner_essence") == engine.state.round_number:
        return
    actor.turn_flags["_round_a2_inner_essence"] = engine.state.round_number
    engine._gain_resource(actor, ESSENCE, 1, INNER)


RECOVERY_PENDING = "condition:typed.a2_heaven_spiting_followup"


@hook("compile_block")
def recovery_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]):
    if block != "a2_heaven_spiting":
        return None
    return [{**row, "pb": int(numbers.get("pb") or 0), "cl": int(numbers.get("cl") or 1),
             "choice_owner": True}]


@hook("lethal_damage")
def heaven_spiting_rescue(engine: Any, target: Any, amount: int, damage_type: str,
                         source_id: str, source_actor_id: str | None, intent: Any):
    row = next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(target.entity_id, [])
                if r.get("block") == "a2_heaven_spiting"), None)
    if (row is None or int(row.get("cl") or 0) < 5 or not _seeded(target)
            or not target.reaction_available or target.turn_flags.get("_round_a2_recovery_used")):
        return None
    from ..typed_executor import condition_rules
    if any(r.get("no_reactions") for r in condition_rules(target)):
        return None
    from . import needle
    from ..resource_labels import resource_name

    pools = [p for p in ("resource:core.qi", "resource:core.resonance", "resource:core.stamina", ESSENCE)
             if target.resources.get(p, 0) >= 3]
    if not pools:
        return None
    action = engine.action_catalog.get(source_id)
    attacker = engine.state.actors.get(source_actor_id or "")
    incoming = (f"{attacker.display_name}'s " if attacker else "") + (action.display_name if action else "incoming damage")
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "heaven_spiting", target.entity_id),
                        target, needle.CHOICE + "heaven_spiting", pools,
                        labels={p: f"Spend your Reaction and 3 {resource_name(p)}; survive at 1 HP" for p in pools},
                        allow_decline=True, name="Heaven-Spiting Recovery", feature_id=RECOVERY,
                        target_id=target.entity_id,
                        prompt=f"Heaven-Spiting Recovery: {incoming} would reduce {target.display_name} to 0 HP "
                               "while Demon Seed is active. Choose a pool to pay 3 points and your Reaction. "
                               f"Remain at 1 HP, then gain {2 * int(row['pb'])} Temporary HP, stand if Prone, "
                               "and gain 1 Corruption. Once until your next Long Rest; passing keeps your resources.",
                        prompt_context={"cost": "Reaction and 3 points from the chosen pool; once per Long Rest",
                                        "source_definition_id": source_id, "action_name": action.display_name if action else incoming,
                                        "action_actor_id": source_actor_id or "", "affected_id": target.entity_id})
    if not chosen:
        return None
    target.turn_flags["_round_a2_recovery_used"] = True
    target.reaction_available = False
    engine._spend_resource(target, chosen[0], 3, RECOVERY)
    engine._apply_condition(target, RECOVERY_PENDING, RECOVERY, target.entity_id, expires_on="UNTIL_REMOVED",
                            data={"source": source_id, "attacker": source_actor_id or "", "pb": int(row['pb'])})
    return 1


@hook("event", nested=True)
def heaven_spiting_after_packet(engine: Any, event_type: str, kwargs: dict[str, Any]):
    if event_type != "DAMAGE_COMMITTED":
        return
    from ..typed_executor import Context, run_effects
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .condition_events import drop_condition

    for tid in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(tid)
        if target is None:
            continue
        for iid, held in list(target.conditions.items()):
            if (held.condition_id != RECOVERY_PENDING or held.data["source"] != kwargs.get("source_definition_id")
                    or held.data["attacker"] != (kwargs.get("actor_id") or "")):
                continue
            drop_condition(engine, target, iid, RECOVERY)
            action = ActionDefinition(source_definition_id=RECOVERY, display_name="Heaven-Spiting Recovery",
                                      owner_id=target.entity_id, economy=EconomyKind.NONE, resolution_kind="TYPED",
                                      target_kind="SELF", range_ft=None, parameters={})
            run_effects(Context(engine, target, action, getattr(engine, "_active_intent", None), {}, [target], target),
                        [{"type": "temp_hp", "applies_to": "self", "flat": 2 * int(held.data['pb'])},
                         {"type": "remove_condition", "applies_to": "self", "condition": "prone"}])
            engine._gain_resource(target, CORRUPTION, 1, RECOVERY)


@hook('event', nested=True)
def furnace_capacity(engine, event_type, kwargs):
    """Enroll the owned Furnace when its Seed anchor becomes active."""
    if event_type != 'CONDITION_APPLIED':
        return
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context, run_effects
    for tid in kwargs.get('target_ids') or ():
        actor = engine.state.actors.get(tid)
        row = _furnace(engine, actor) if actor else None
        if not row or not _seeded(actor) or ESSENCE not in actor.resources:
            continue
        action = ActionDefinition(source_definition_id=FURNACE, display_name='Second Furnace Demon Heart',
                                  owner_id=actor.entity_id, economy=EconomyKind.NONE, resolution_kind='TYPED',
                                  target_kind='SELF', parameters={})
        run_effects(Context(engine, actor, action, getattr(engine, '_active_intent', None), {}, [actor], actor),
                    [{'type': 'resource_capacity', 'resource_id': ESSENCE, 'anchor': SEED, 'amount': row['pb']}])

CONSUME_FEAR = "TAL_DAEMONIC_CULTIVATION_CONSUME_FEAR_REFINE_COMMAND"
CONSUME_FEAR_MARK = "_consume_fear_prior_frightened"
CONSUME_FEAR_DROP_FAILED = "_consume_fear_drop_save_failed"
ESSENCE = "resource:named.devoured_essence"


def _contains_consume_fear(effects: Any) -> bool:
    return any(isinstance(row, dict) and
               (row.get("type") == "rider_consume_fear" or
                any(_contains_consume_fear(row.get(branch) or ())
                    for branch in ("on_fail", "on_success", "on_hit", "effects")))
               for row in effects or ())


@hook("save_effects")
def consume_fear_snapshot(ctx: Any, subject: Any, ability: str, fail_effects: list, success_effects: list,
                         categories: list) -> None:
    """Remember the target's state before a failed Dread Appetite save applies Frightened."""
    if ctx.typed.get("source") != DREAD or not _contains_consume_fear(fail_effects):
        return None
    ctx.damage_cache[CONSUME_FEAR_MARK] = any(
        condition.condition_id == "condition:typed.frightened" for condition in subject.conditions.values())
    return None


@effect("rider_consume_fear")
def consume_fear(ctx: Any, spec: dict[str, Any]) -> None:
    """Settle the owned failed-save benefit, then ask its prior-Frightened choice."""
    from . import needle

    target = ctx.target
    if target is None or target.entity_id not in ctx.engine.state.actors or int(ctx.numbers.get("cl") or 1) < 5:
        return
    if ESSENCE in ctx.actor.resources:
        ctx.engine._gain_resource(ctx.actor, ESSENCE, 1, CONSUME_FEAR)
    if not ctx.damage_cache.pop(CONSUME_FEAR_MARK, False):
        return

    choices = ["deny_reactions"]
    allies = sorted((actor for actor in ctx.engine.state.actors.values()
                     if actor.active and actor.team_id == ctx.actor.team_id
                     and actor.entity_id not in (ctx.actor.entity_id, target.entity_id)),
                    key=lambda actor: (ctx.engine._distance_actor_to_actor(target, actor), actor.entity_id))
    if allies:
        choices.append("no_approach")
    step_options = _consume_fear_step_options(ctx.engine, ctx.actor, target)
    if step_options:
        choices.append("move_toward")
    held = ()
    from . import scoundrel_riders
    held = tuple(item for item in scoundrel_riders.held_possessions(ctx.engine, target)
                 if not any(item.get(flag) for flag in
                            ("magical", "artifact", "soul_bound", "fused", "protected", "sealed")))
    if held:
        choices.append("drop_object")
    labels = {
        "no_approach": "Keep it from moving closer to one ally until the end of its next turn",
        "deny_reactions": "It cannot take Reactions until the end of your next turn",
        "move_toward": "Move up to 10 feet toward it without provoking its Opportunity Attacks",
    }
    if held:
        labels["drop_object"] = "It makes a Strength saving throw; on a failure, it drops one held mundane object"
    selected = needle.ask(
        ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "consume_fear", target.entity_id), ctx.actor,
        needle.CHOICE + "consume_fear", choices, labels=labels,
        prompt=f"Consume Fear, Refine Command: after {ctx.action.display_name} affects {target.display_name}, choose one additional effect",
        target_id=target.entity_id, name="Consume Fear, Refine Command", feature_id=CONSUME_FEAR,
        allow_decline=True, preferred=["deny_reactions"], default_count=1)
    if not selected:
        return
    choice = selected[0]
    if choice == "no_approach":
        ally_ids = [actor.entity_id for actor in allies]
        chosen = needle.ask(ctx.engine, ctx.intent,
                            needle.checkpoint_id(ctx.engine, "consume_fear_ally", target.entity_id), ctx.actor,
                            needle.CHOICE + "consume_fear_ally", ally_ids,
                            labels={actor.entity_id: actor.display_name for actor in allies},
                            prompt=f"Consume Fear, Refine Command: choose one ally {target.display_name} cannot willingly move closer to",
                            target_id=target.entity_id, name="Consume Fear, Refine Command", feature_id=CONSUME_FEAR,
                            allow_decline=True, default="decline", default_count=0)
        if chosen:
            ally = ctx.engine.state.actors.get(chosen[0])
            if ally is not None:
                ctx.engine._apply_condition(target, "condition:typed.no_approach", CONSUME_FEAR, ctx.actor.entity_id,
                                            expires_on="END_OF_HOLDER_NEXT_TURN",
                                            data={"avoid": ally.entity_id,
                                                  "label": f"Cannot willingly move closer to {ally.display_name}"})
    elif choice == "drop_object":
        from .. import typed_executor as te
        # The printed clause names no DC: it is the caster's Save DC, the same DC as the Dread Appetite save.
        te.block_save(ctx, {"type": "save", "ability": "str", "applies_to": "target", "basis": "save_dc",
                            "on_fail": [{"type": "rider_consume_fear_drop"}], "on_success": []})
        holder_id = ctx.damage_cache.pop(CONSUME_FEAR_DROP_FAILED, None)
        holder = ctx.engine.state.actors.get(str(holder_id or ""))
        if holder is not None:
            _consume_fear_drop_choice(ctx, holder)
    elif choice == "deny_reactions":
        ctx.engine._apply_condition(target, "condition:typed.reaction_denied", CONSUME_FEAR, ctx.actor.entity_id,
                                    expires_on=f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + 1}",
                                    data={"label": f"Cannot take Reactions until the end of {ctx.actor.display_name}'s next turn"})
    elif choice == "move_toward":
        _consume_fear_step(ctx, target, step_options)


@effect("rider_consume_fear_drop")
def consume_fear_drop(ctx: Any, spec: dict[str, Any]) -> None:
    """Record the failed Strength save for the parent effect to handle after the save settles."""
    if ctx.target is not None:
        ctx.damage_cache[CONSUME_FEAR_DROP_FAILED] = ctx.target.entity_id


def _consume_fear_drop_choice(ctx: Any, holder: Any) -> None:
    """Choose and drop one exact held mundane object after the failed save has settled."""
    from . import needle, scoundrel_riders

    items = [item for item in scoundrel_riders.held_possessions(ctx.engine, holder)
             if not any(item.get(flag) for flag in
                        ("magical", "artifact", "soul_bound", "fused", "protected", "sealed"))]
    if not items:
        return
    identities = [str(item["object"]) for item in items]
    chosen = needle.ask(ctx.engine, ctx.intent,
                        needle.checkpoint_id(ctx.engine, "consume_fear_drop", holder.entity_id), ctx.actor,
                        needle.CHOICE + "consume_fear_drop", identities,
                        labels={str(item["object"]): str(item.get("name") or "held object") for item in items},
                        prompt=f"Consume Fear, Refine Command: choose one mundane object {holder.display_name} drops",
                        target_id=holder.entity_id, name="Consume Fear, Refine Command", feature_id=CONSUME_FEAR,
                        default_count=1)
    item = next((item for item in items if chosen and str(item["object"]) == chosen[0]), None)
    if item is not None:
        scoundrel_riders.drop_held_object(ctx.engine, holder, item, source=CONSUME_FEAR, by=ctx.actor)


def _consume_fear_step_options(engine: Any, actor: Any, target: Any) -> dict[str, Any]:
    """Legal endpoints for the optional approach step under its own 10-foot budget."""
    from . import needle
    from .movement_steps import immediate_step_budget

    allowance = immediate_step_budget(engine, actor, 10)
    if allowance <= 0:
        return {}
    old_budget = actor.movement_remaining_ft
    actor.movement_remaining_ft = allowance
    try:
        before = engine._distance_actor_to_actor(actor, target)
        return {needle.cell_id(candidate.destination): candidate
                for candidate in engine._movement_candidates(actor)
                if engine._distance_actor_to_actor(actor, target, actor_position=candidate.destination) < before}
    finally:
        actor.movement_remaining_ft = old_budget


def _consume_fear_step(ctx: Any, target: Any, options: dict[str, Any]) -> None:
    """Take the printed voluntary step through legal routes, exempting only this target's OA."""
    from . import needle
    from .movement_steps import immediate_step_budget

    engine, actor = ctx.engine, ctx.actor
    allowance = immediate_step_budget(engine, actor, 10)
    if allowance <= 0 or not options:
        return
    old_budget = actor.movement_remaining_ft
    actor.movement_remaining_ft = allowance
    try:
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "consume_fear_step", target.entity_id), actor,
                            needle.CHOICE + "consume_fear_step", list(options),
                            labels={key: f"Move to ({move.destination.x}, {move.destination.y}), {move.movement_cost_ft} feet"
                                    for key, move in options.items()},
                            prompt=f"Consume Fear, Refine Command: move up to 10 feet toward {target.display_name}",
                            target_id=target.entity_id, name="Consume Fear, Refine Command", feature_id=CONSUME_FEAR,
                            allow_decline=True, default="decline", default_count=0)
        if chosen:
            actor.turn_flags["consume_fear_oa_target"] = target.entity_id
            try:
                engine._resolve_movement(actor, options[chosen[0]], ctx.intent)
            finally:
                actor.turn_flags.pop("consume_fear_oa_target", None)
    finally:
        actor.movement_remaining_ft = old_budget


@hook("opportunity_allowed")
def consume_fear_oa_exemption(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """The printed approach move exempts only the affected creature from Opportunity Attacks."""
    return False if mover.turn_flags.get("consume_fear_oa_target") == reactor.entity_id else None
