"""Nine-Star Meridian Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, "27. Nine-Star Meridian Body". Celestial Marks (resource:named.celestial_mark) are
gained by combat/ext/subpath_pools.py (1 at Initiative, 3 with Constellation Circuit; once a round after a Stamina-spending Body
Refining activation; maximum PB, PB + 3 with Constellation Circuit via factory_compiler ``max_if_owned``). Owned rows:
``{"type": "path_passive", "kind": "nine_star", "role": "constellation"}``; effects ``star_step``, ``ac_against``, ``orbital_step``,
``nine_star_state``.

Star-Lit Acupoints   paid hit (1 Mark, once per turn): + 1d8 Force or Radiant and the asked result (move 5 ft, push 5, pull 5,
                     or +1 AC against that creature until the start of your next turn).
Orbital Body         its Reaction (1 Mark) after an attack hits you: 2d8 + CON off the damage, then (asked) a move of 10 feet
                     without provoking, 15 if the damage was brought to 0, once the attack is over.
Constellation Circuit  while you have 3 or more Marks you count one size larger when resisting forced movement (size_steps);
                     a Mark gained at maximum gives one overflow benefit instead (asked; each at most once a round): Temporary
                     HP PB, a 5-foot move without provoking, or + PB on your next Strength or Dexterity save.
Nine-Star Incarnation  state "nine_star_incarnation": unarmed strikes may deal Force or Radiant, once per turn + 4d8 on a hit,
                     once per round after an unarmed hit a Strength save (asked push or pull: 20 feet and Prone, or 5 feet), and a
                     creature of your CL or lower cannot push, pull, knock you Prone or move you against your will.
Every hook returns early for a creature without these rows or states.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.nine_star_meridian_body.feature."
MARKS = "resource:named.celestial_mark"
INCARNATION = "nine_star_incarnation"
GUARD = "condition:typed.ac_against"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "nine_star"}


def _state(engine: Any, actor: Any) -> bool:
    from .states import active

    return actor is not None and bool(active(engine, actor, INCARNATION))


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _cl(engine: Any, actor: Any) -> int:
    """The fighter's Cultivation Level (its compiled bundle's)."""
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor.entity_id), None)
    return int((bundle or {}).get("cl") or 1)


def _move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(ctx.engine, mover, feet)
    if not paths:
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "nine_star_move", mover.entity_id), mover, choice_id, sorted(paths),
                 allow_decline=True, default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=mover.entity_id,
                 prompt=f"{name}: {mover.display_name} may move up to {feet} feet without provoking Opportunity Attacks.")
    if picked and picked[0] in paths:
        step(ctx.engine, mover, paths[picked[0]], PREFIX + "nine_star")


@effect("star_step")
def star_step(ctx: Any, row: dict[str, Any]) -> None:
    _move(ctx, ctx.actor, int(row.get("feet") or 5), "choice:needle.star_step", str(row.get("name") or "Star-Lit Acupoints"))


# ------------------------------------------------------------------------------------- +1 AC against one creature
@effect("ac_against")
def ac_against(ctx: Any, row: dict[str, Any]) -> None:
    """+N AC against attacks made by the triggering target (a condition on you; hit_response turns a hit that would miss)."""
    target = ctx.target
    if target is None:
        return
    for iid, held in list(ctx.actor.conditions.items()):
        if held.condition_id == GUARD and held.source_definition_id == ctx.source:
            ctx.engine._remove_condition_instance(ctx.actor, iid, ctx.source, expected=held)
    ctx.engine._apply_condition(ctx.actor, GUARD, ctx.source, ctx.actor.entity_id, expires_on=str(row.get("expires_on") or "START_OF_SELF_NEXT_TURN"),
                                data={"against": target.entity_id, "amount": int(row.get("amount") or 1),
                                      "label": f"+{int(row.get('amount') or 1)} AC against {target.display_name}"})


@hook("hit_response")
def ac_against_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    bonus = sum(int((c.data or {}).get("amount") or 0) for c in target.conditions.values()
                if c.condition_id == GUARD and (c.data or {}).get("against") == attacker.entity_id)
    if not bonus or natural == 20 or total >= effective_ac + bonus:
        return None
    return effective_ac + bonus, False


# -------------------------------------------------------------------------------------------------- Orbital Body
@effect("orbital_step")
def orbital_step(ctx: Any, row: dict[str, Any]) -> None:
    """Park the move for after the attack (15 feet replaces 10 when the reduction brought the damage to 0)."""
    other = ctx.target
    if other is None:
        return
    held = dict(ctx.actor.turn_flags.get("_round_orbital_step") or {})
    held.update({"attacker": other.entity_id, "feet": max(int(held.get("feet") or 0), int(row.get("feet") or 10)),
                 "stamp": f"{ctx.engine.state.event_sequence}"})
    ctx.actor.turn_flags["_round_orbital_step"] = held


@hook("attack_resolved")
def orbital_move(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    if target is None:
        return
    held = target.turn_flags.get("_round_orbital_step")
    if not isinstance(held, dict) or held.get("attacker") != ctx.actor.entity_id:
        return
    target.turn_flags.pop("_round_orbital_step", None)
    if target.active:
        from .states import context

        sub = context(ctx.engine, target, PREFIX + "orbital_body", [target], {})
        sub.intent = ctx.intent
        _move(sub, target, int(held.get("feet") or 10), "choice:needle.orbital_body_move", "Orbital Body")


# ----------------------------------------------------------------------------------------- Constellation Circuit
@hook("size_steps")
def steady_constellation(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    if role != "resist" or creature is None or "constellation" not in _roles(engine, creature):
        return None
    if int(creature.resources.get(MARKS, 0) or 0) < 3:
        return None
    return 1 if "forced" in purposes else None


def _overflow(engine: Any, actor: Any, intent: Any) -> None:
    key = "_round_pool_overflow:" + MARKS
    pending = int(actor.turn_flags.get(key) or 0)
    if pending <= 0 or "constellation" not in _roles(engine, actor):
        actor.turn_flags.pop(key, None)
        return
    actor.turn_flags.pop(key, None)
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .states import context

    used = set(str(actor.turn_flags.get("_round_constellation_used") or "").split("|")) if str(actor.turn_flags.get("_round_constellation_round")) == str(engine.state.round_number) else set()
    for _ in range(pending):
        labels = {k: v for k, v in {"temp_hp": f"Gain {int(actor.proficiency_bonus or 2)} Temporary Hit Points", "move": "Move 5 feet without provoking",
                                    "save": "+ Proficiency Bonus on your next Strength or Dexterity save"}.items() if k not in used}
        if not labels:
            return
        picked = ask(engine, intent, checkpoint_id(engine, "constellation", actor.entity_id), actor, "choice:needle.constellation_overflow", list(labels),
                     labels=labels, target_id=actor.entity_id, name="Constellation Circuit",
                     prompt="Constellation Circuit: a Celestial Mark at maximum becomes one benefit.")
        choice = picked[0] if picked else next(iter(labels))
        used.add(choice)
        actor.turn_flags["_round_constellation_used"] = "|".join(sorted(used))
        actor.turn_flags["_round_constellation_round"] = str(engine.state.round_number)
        ctx = context(engine, actor, PREFIX + "constellation_circuit", [actor], {"pb": int(actor.proficiency_bonus or 2)})
        ctx.intent = intent
        if choice == "temp_hp":
            te.run_effects(ctx, [{"type": "temp_hp", "applies_to": "self", "formula": "pb"}])
        elif choice == "move":
            _move(ctx, actor, 5, "choice:needle.constellation_move", "Constellation Circuit")
        else:
            which = ask(engine, intent, checkpoint_id(engine, "constellation_save", actor.entity_id), actor, "choice:needle.constellation_save",
                        ["Strength", "Dexterity"], target_id=actor.entity_id, prompt="Constellation Circuit: your next Strength or Dexterity save?")
            engine._apply_condition(actor, "condition:typed.constellation_save", PREFIX + "constellation_circuit", actor.entity_id,
                                    expires_on="START_OF_SELF_NEXT_TURN",
                                    data={"ability": (which or ["Strength"])[0][:3].upper(), "bonus": int(actor.proficiency_bonus or 2),
                                          "label": f"+ Proficiency Bonus on your next {(which or ['Strength'])[0]} save"})


@hook("action_completed")
def overflow_after_action(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:

    _overflow(engine, actor, getattr(engine, "_active_intent", None))


@hook("turn_start_choice")
def overflow_at_turn_start(engine: Any, actor: Any) -> None:

    _overflow(engine, actor, getattr(engine, "_active_intent", None))


@hook("save")
def constellation_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None:
        return None
    held = next((c for c in subject.conditions.values() if c.condition_id == "condition:typed.constellation_save"
                 and str((c.data or {}).get("ability")) == str(ability).upper()[:3]), None)
    if held is None:
        return None
    subject.conditions.pop(held.instance_id)
    ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "constellation_circuit", actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                             payload={"condition_id": held.condition_id, "instance_id": held.instance_id, "reason": "CONSUMED"})
    return {"bonus": int(held.data.get("bonus") or 0), "modes": []}


# ----------------------------------------------------------------------------------------- Nine-Star Incarnation
@hook("attack_damage_types")
def incarnation_types(ctx: Any, attack: Any, kinds: Any) -> list[str] | None:
    unarmed = ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                              for e in ctx.typed.get("effects") or [])
    if not _state(ctx.engine, ctx.actor) or not unarmed:
        return None
    return list(dict.fromkeys([*(str(k).upper() for k in kinds or []), "FORCE", "RADIANT"]))


@hook("after_hit")
def incarnation_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or target.team_id == actor.team_id or not _state(engine, actor):
        return
    from .. import typed_executor as te

    if actor.turn_flags.get("_round_nine_star_hit") != _stamp(engine):
        actor.turn_flags["_round_nine_star_hit"] = _stamp(engine)
        te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                       [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": ["force", "radiant"],
                         "evidence": "Nine-Star Incarnation: once per turn + 4d8"}])
    if kind != "unarmed" or not target.active or actor.turn_flags.get("_round_nine_star_pull") == int(engine.state.round_number):
        return
    actor.turn_flags["_round_nine_star_pull"] = int(engine.state.round_number)
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "nine_star_pull", target.entity_id), actor, "choice:needle.nine_star_pull", ["away", "toward"],
                 labels={"away": f"Push {target.display_name}", "toward": f"Pull {target.display_name}"}, target_id=target.entity_id,
                 name="Nine-Star Incarnation", prompt=f"Nine-Star Incarnation: {target.display_name} makes a Strength save; push or pull it?")
    direction = (picked or ["away"])[0]
    row = next((r for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if r.get("block") == "path_rider"), {})
    dc = int(row.get("save_dc") or (ctx.typed.get("numbers") or {}).get("save_dc") or 10)
    sub = ctx.on_hit_context(target, action=ctx.action, typed={**ctx.typed, 'numbers': {**(ctx.typed.get('numbers') or {}), 'save_dc': dc}}, damage_cache={})
    te.run_effects(sub, [{"type": "save", "ability": "str", "evidence": "Nine-Star Incarnation: Strength saving throw",
                          "on_fail": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 20, "direction": direction},
                                      {"type": "condition", "applies_to": "target", "condition": "prone"}],
                          "on_success": [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": direction}]}])


@hook("forced_movement_reduction")
def anchored(ctx: Any, subject: Any) -> int:
    if subject is None or ctx.actor is subject or not _state(ctx.engine, subject):
        return 0
    return 1000 if int(ctx.numbers.get("cl") or 0) <= _cl(ctx.engine, subject) else 0


@hook("condition_attempt")
def anchored_prone(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    if subject is None or ctx.actor is subject or str((effect_row or {}).get("condition") or "").lower() != "prone" or not _state(ctx.engine, subject):
        return None
    return False if int(ctx.numbers.get("cl") or 0) <= _cl(ctx.engine, subject) else None


@hook('flight')
def constellation_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    if 'constellation' in _roles(engine, actor) and int(actor.resources.get(MARKS, 0)) >= 3:
        return {'fly_speed_ft': 30, 'flight_hover': 1}
    return None


@hook('condition_attempt')
def airborne_constellation(ctx: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    from ..falling import supported
    if (subject is not None and str(row.get('condition', '')).lower() == 'prone'
            and 'constellation' in _roles(ctx.engine, subject)
            and int(subject.resources.get(MARKS, 0)) >= 3 and not supported(ctx.engine, subject)):
        return False
    return None


@effect('nine_star_impact_ground')
def impact_ground(ctx: Any, row: dict[str, Any]) -> None:
    from . import placed
    from ..gate2_runtime_models import Position
    from ..targeting import line_of_effect
    center = ctx.actor.position
    # Only supporting ground/floors struck by the radial impact become rubble;
    # an airborne impact cannot turn the empty sky into difficult terrain.
    cells = [Position(x=x, y=y, z=center.z) for x in range(ctx.engine.grid.width)
             for y in range(ctx.engine.grid.height)
             if ctx.engine.grid.distance_ft(center, Position(x=x, y=y, z=center.z)) <= int(row['radius_ft'])
             and (center.z == 0 or ctx.engine.grid.terrain_at((x, y, center.z-1), 'BLOCKED'))
             and line_of_effect(ctx.engine, ctx.actor, destination=Position(x=x, y=y, z=center.z))]
    if cells:
        placed.place(ctx.engine, ctx.actor, source=ctx.source, tag='nine_star_rubble', cells=cells,
                     name='Falling-Star Descent rubble: difficult terrain until repaired',
                     difficult='all', duration_rounds=None, numbers=ctx.numbers)


@hook('state_event')
def constellation_mark_change(engine: Any, event: Any) -> None:
    if event.event_type not in {'RESOURCE_SPENT', 'RESOURCE_GAINED', 'RESOURCE_EXPIRED'} or event.payload.get('resource_id') != MARKS:
        return
    actor=engine.state.actors.get(event.actor_id)
    if actor is not None and 'constellation' in _roles(engine, actor):
        # A paid activation may spend the Marks that sustain this flight and
        # establish replacement flight later in the same resolution. Defer
        # fall settlement to the activation boundary in that case. The payer
        # can be a reacting creature, so retain its id rather than assuming
        # the action's actor is the one that lost flight.
        if getattr(engine, '_active_intent', None) is not None:
            pending = engine.__dict__.setdefault('_constellation_flight_loss_pending', set())
            pending.add(actor.entity_id)
        else:
            from ..falling import settle
            settle(engine, event.source_definition_id, None)


@hook('resolution_final')
def settle_constellation_flight_loss(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    """Settle all deferred Mark-flight losses after the current activation."""
    pending = engine.__dict__.pop('_constellation_flight_loss_pending', set())
    if 'constellation' in _roles(engine, actor):
        pending.add(actor.entity_id)
    from ..falling import settle
    if pending:
        settle(engine, action.source_definition_id, intent)
