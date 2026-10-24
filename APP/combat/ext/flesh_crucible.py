"""Flesh Crucible Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Titan's Frame        named state "titan_s_frame" (1 minute; using it again refreshes it): Advantage on Strength checks and
                     Strength saves; counts one size larger for Grappling and Shoving (size_steps); Iron Fist unarmed dice
                     become 1d10 when that is larger than the strike's own dice; once during each of its turns after a melee
                     hit, a choice (asked): push the target 5 feet, move 5 feet toward it, or Advantage on the next Grapple/Shove
                     against it this turn (the target's save against it has Disadvantage). Native growth occupies the printed replacement size where legal space allows.
Titanic Frame        while Titan's Frame is on: Iron Fist dice 1d12 (2d8 with Mountain-Demon Might), Temporary HP equal to CL
                     when Titan's Frame is used, Advantage on saves against being pushed, pulled or knocked Prone, and it may
                     Grapple creatures up to two sizes larger (one more size step for Grapples).
Mountain-Demon Might named state "mountain_demon_might": starts Titan's Frame (free), Temporary HP twice CL, +5 ft melee reach
                     (reach_bonus), once per turn +CON to a melee hit's damage, one more size step for Grappling and Shoving,
                     and Titan's Frame ends when it ends.
Crushing Grip        at the start of the owner's turn, while it Grapples a creature: may spend 1 Stamina (asked) to crush one of
                     them for one Iron Fist damage roll (no attack roll, no ability modifier, no hit riders; the Grapple stays).
Every hook returns early without the owner's state or row.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.flesh_crucible.feature."
FRAME, MIGHT = "titan_s_frame", "mountain_demon_might"
GRAPPLE_ADVANTAGE = "condition:typed.titan_grapple_advantage"


def _active(engine: Any, actor: Any, name: str) -> bool:
    from .states import active

    return bool(active(engine, actor, name))


def _owns(engine: Any, actor: Any, feature: str) -> bool:
    return any(str(row.get("feature_id") or "") == PREFIX + feature for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])) \
        or any(((a.parameters or {}).get("typed") or {}).get("source") == PREFIX + feature for a in engine.action_catalog.values() if a.owner_id == actor.entity_id)


def _kind(effect: dict[str, Any]) -> str | None:
    """Grapple or Shove: the typed save a Grapple/Shove action rolls (what its failure imposes)."""
    for row in (effect or {}).get("on_fail") or []:
        if not isinstance(row, dict):
            continue
        if row.get("type") == "condition" and row.get("condition") == "grappled":
            return "grapple"
        if (row.get("type") == "condition" and row.get("condition") == "prone") or row.get("type") == "forced_movement":
            return "shove"
    return None


@hook("size_steps")
def count_as_larger(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    if role != "act":
        return None
    kind = "grapple" if "grapple" in purposes else "shove" if "shove" in purposes else None
    if kind is None:
        return None
    steps = 0
    if _active(engine, creature, FRAME):
        steps += 1
        if kind == "grapple" and _owns(engine, creature, "titanic_frame"):
            steps += 1
    if _active(engine, creature, MIGHT):
        steps += 1
    return steps or None


def _unarmed(ctx: Any) -> bool:
    return ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                            for e in ctx.typed.get("effects") or [])


@hook("attack_damage")
def frame_die(ctx: Any, dice: Any) -> Any:
    """"Your Iron Fist damage die becomes 1d10" (1d12 with Titanic Frame, 2d8 with Mountain-Demon Might): the larger expression wins."""
    if dice is None or not _unarmed(ctx) or not _active(ctx.engine, ctx.actor, FRAME):
        return None
    count, sides = 1, 10
    if _owns(ctx.engine, ctx.actor, "titanic_frame"):
        count, sides = (2, 8) if _active(ctx.engine, ctx.actor, MIGHT) else (1, 12)
    if count * (sides + 1) <= int(dice.count) * (int(dice.sides) + 1):
        return None
    return dice.model_copy(update={"count": count, "sides": sides})


@hook("save")
def frame_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    modes = []
    if _active(ctx.engine, subject, FRAME):
        if str(ability).upper() == "STR":
            modes.append("ADVANTAGE")
        if _owns(ctx.engine, subject, "titanic_frame") and {"prone", "forced_movement"} & set(named or ()):
            modes.append("ADVANTAGE")
    held = next((c for c in subject.conditions.values() if c.condition_id == GRAPPLE_ADVANTAGE
                 and c.source_actor_id == ctx.actor.entity_id), None)
    if held is not None and ctx.actor is not subject and _kind({"on_fail": _fail_rows(ctx)}) is not None:
        subject.conditions.pop(held.instance_id)
        ctx.engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                 payload={"condition_id": GRAPPLE_ADVANTAGE, "instance_id": held.instance_id})
        modes.append("DISADVANTAGE")
    return {"bonus": 0, "modes": sorted(set(modes))} if modes else None


def _fail_rows(ctx: Any) -> list[dict[str, Any]]:
    return [row for eff in ctx.typed.get("effects") or [] if isinstance(eff, dict) and eff.get("type") == "save"
            for row in eff.get("on_fail") or []]


@hook("ability_check_mode")
def frame_checks(engine: Any, actor: Any, ability: str, skill: Any, against: Any) -> str | None:
    return "ADVANTAGE" if str(ability).upper() == "STR" and _active(engine, actor, FRAME) else None


def _melee(ctx: Any) -> bool:
    from .thunder_charges import melee_attack

    return melee_attack(ctx)


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


@hook("after_hit")
def frame_hit(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or not _melee(ctx):
        return
    from .. import typed_executor as te

    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    if _active(engine, actor, MIGHT) and actor.turn_flags.get("_round_might_con") != _stamp(engine):
        actor.turn_flags["_round_might_con"] = _stamp(engine)
        con = int(ctx.numbers.get("key_mod") or 0)
        if con > 0:
            types = [str(t).lower() for t in ((ctx.typed.get("weapon") or {}).get("damage_types") or ["bludgeoning"])]
            te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": con, "damage_types": types[:1],
                                  "evidence": "Mountain-Demon Might: +Constitution modifier to one damage roll"}])
    if not _active(engine, actor, FRAME) or engine.state.current_actor_id != actor.entity_id or not target.active \
            or actor.turn_flags.get("_round_titan_hit") == _stamp(engine):
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "titan_frame_hit", target.entity_id), actor, "choice:needle.titan_frame_hit",
                 ["push", "approach", "grapple_advantage"], allow_decline=True, target_id=target.entity_id,
                 labels={"push": f"Push {target.display_name} 5 feet", "approach": f"Move 5 feet toward {target.display_name} without provoking it",
                         "grapple_advantage": f"Advantage on your next Grapple or Shove against {target.display_name} this turn"},
                 prompt=f"Titan's Frame: {ctx.action.display_name} hit {target.display_name} (once per turn).")
    if not picked:
        return
    actor.turn_flags["_round_titan_hit"] = _stamp(engine)
    if picked[0] == "push":
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    elif picked[0] == "approach":
        from .rider_movement import routes, step

        closer = [path for path in routes(engine, actor, 5).values()
                  if engine.grid.distance_ft(path[-1], target.position) < engine.grid.distance_ft(actor.position, target.position)]
        if closer:
            step(engine, actor, min(closer, key=lambda path: (engine.grid.distance_ft(path[-1], target.position), path[-1].y, path[-1].x)),
                 PREFIX + "titan_s_frame")
    else:
        engine._apply_condition(target, GRAPPLE_ADVANTAGE, PREFIX + "titan_s_frame", actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"label": f"{actor.display_name} has Advantage on its next Grapple or Shove against this creature this turn"})


@hook("carry_capacity_multiplier")
def frame_capacity(engine: Any, actor: Any) -> int | None:
    """Titan's Frame: "Double your carrying, dragging, lifting, and pushing capacity" (Titanic Frame: quadrupled rather than doubled)."""
    if not _active(engine, actor, FRAME):
        return None
    return 4 if _owns(engine, actor, "titanic_frame") else 2


@hook("event")
def frame_changes_the_load(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The Frame starting or ending changes the capacity, so the load (and the Speed it costs) is weighed again at once."""
    if event_type not in ("CONDITION_APPLIED", "CONDITION_REMOVED"):
        return
    from . import states
    from .. import carry

    if (kwargs.get("payload") or {}).get("condition_id") != states.PREFIX + states.slug(FRAME):
        return
    actor = engine.state.actors.get(str(kwargs.get("actor_id") or (kwargs.get("target_ids") or ("",))[0]))
    if actor is not None and actor.active:
        carry.refresh(engine, actor, PREFIX + "titan_s_frame")


@hook("technique_used")
def frame_used(ctx: Any) -> None:
    """Titanic Frame: "Gain Temporary Hit Points equal to your CL when you activate it" (Titan's Frame, also through Mountain-Demon Might)."""
    source = str(ctx.typed.get("source") or "")
    if source == PREFIX + FRAME and _active(ctx.engine, ctx.actor, FRAME):
        # Actual footprint growth and the distinct functional size permission
        # now have separate records. Name both in the player's activation log.
        capacity = 'quadrupled' if _owns(ctx.engine, ctx.actor, 'titanic_frame') else 'doubled'
        ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
            payload={'log': f"{ctx.actor.display_name} activates Titan's Frame (2 Stamina, 1 minute): "
                "counts as one size larger for Grappling and Shoving, carrying, dragging, lifting and pushing. "
                f"Carrying, dragging, lifting and pushing capacity is {capacity}; reach does not increase."})
    if source not in (PREFIX + "titan_s_frame", PREFIX + "mountain_demon_might") or not _owns(ctx.engine, ctx.actor, "titanic_frame"):
        return
    ctx.engine._grant_temp_hp(ctx.actor, int(ctx.numbers.get("cl") or 1), PREFIX + "titanic_frame", ctx.actor.entity_id)


def _end_frame(engine: Any, holder: Any) -> None:
    from .states import PREFIX as STATE
    from ..dynamic_size import CONDITION as SIZE

    for held in list(holder.conditions.values()):
        if held.condition_id != STATE + FRAME and not (held.condition_id == SIZE and held.source_definition_id == PREFIX + FRAME):
            continue
        holder.conditions.pop(held.instance_id)
        engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=holder.entity_id, target_ids=(holder.entity_id,),
                             payload={"condition_id": held.condition_id, "instance_id": held.instance_id, "reason": "MOUNTAIN_DEMON_MIGHT_ENDED"})


@hook("effect_expiring")
def might_ends_frame(engine: Any, holder: Any, row: Any) -> None:
    """End the linked state and occupied growth before Might expires."""
    from .states import PREFIX as STATE
    if getattr(row, "condition_id", None) == STATE + MIGHT:
        _end_frame(engine, holder)


@hook("state_event")
def might_removed(engine: Any, event: Any) -> None:
    from .states import PREFIX as STATE
    if event.event_type == 'CONDITION_REMOVED' and event.payload.get('condition_id') == STATE + MIGHT:
        for actor_id in event.target_ids:
            _end_frame(engine, engine.state.actors[actor_id])


@hook("turn_start_choice")
def crushing_grip(engine: Any, actor: Any) -> None:
    if not actor.active or actor.resources.get("resource:core.stamina", 0) < 1 or not _owns(engine, actor, "crushing_grip"):
        return
    held = [other for other in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if other.active and any(
        c.condition_id == "condition:typed.grappled" and c.source_actor_id == actor.entity_id for c in other.conditions.values())]
    if not held:
        return
    from .needle import ask, checkpoint_id

    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "crushing_grip", actor.entity_id),
                 actor, "choice:needle.crushing_grip", [other.entity_id for other in held], allow_decline=True,
                 labels={other.entity_id: f"Crush {other.display_name} (1 Stamina)" for other in held},
                 prompt=f"Crushing Grip: {actor.display_name} may spend 1 Stamina to crush a creature it is Grappling.")
    if not picked:
        return
    victim = engine.state.actors[picked[0]]
    unarmed = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and ".natural." in a.source_definition_id
                    and ((a.parameters or {}).get("typed") or {}).get("weapon")), None)
    dice = ((unarmed.parameters["typed"]["weapon"].get("damage") or {}) if unarmed is not None else {}) or {"count": 1, "sides": 4}
    engine._spend_resource(actor, "resource:core.stamina", 1, PREFIX + "crushing_grip")
    from .. import typed_executor as te
    from .states import context

    ctx = context(engine, actor, PREFIX + "crushing_grip", [victim])
    te.run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": int(dice.get("count") or 1), "sides": int(dice.get("sides") or 4)},
                          "damage_types": ["bludgeoning"], "evidence": "Crushing Grip: one Iron Fist damage roll"}])
    note(engine, PREFIX + "crushing_grip", actor, f"Crushing Grip: {actor.display_name} crushes {victim.display_name}.", (victim,))


@hook('compile_actions')
def huge_stomp(info: dict[str, Any]) -> list[Any] | None:
    import copy
    source = PREFIX + 'world_shaking_stomp'
    out=[]
    for action in info['actions']:
        typed=action.parameters.get('typed') or {}
        if typed.get('source')!=source or '#' in action.source_definition_id:
            continue
        params=copy.deepcopy(action.parameters)
        params['typed']['area']['size_ft']=40
        if params.get('zone_spec'):
            params['zone_spec']['size_ft']=40
        params['flesh_huge_stomp']=True
        out.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'#huge',
            'display_name':'World-Shaking Stomp (40-foot cone)', 'range_ft':40,'parameters':params}))
    return out or None


@hook('candidate_allowed')
def stomp_size(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from ..dynamic_size import current_category
    if action is None or (action.parameters.get('typed') or {}).get('source')!=PREFIX+'world_shaking_stomp':
        return None
    huge=current_category(engine,actor)=='Huge'
    return huge if action.parameters.get('flesh_huge_stomp') else not huge


@effect('flesh_frame_growth')
def frame_growth(ctx: Any, row: dict[str, Any]) -> None:
    from .. import dynamic_size
    from ..typed_executor import effect_expiry
    from .needle import ask, checkpoint_id
    engine,actor=ctx.engine,ctx.actor
    might=row.get('might',False)
    base=dynamic_size.base_category(engine,actor)
    if might and _active(engine,actor,FRAME):
        current=dynamic_size.current_category(engine,actor)
        wanted=dynamic_size.CATEGORIES[min(dynamic_size.CATEGORIES.index('Huge'),dynamic_size.CATEGORIES.index(current)+1)]
    elif _owns(engine,actor,'titanic_frame'):
        selected=ask(engine,ctx.intent,checkpoint_id(engine,'titan_size',actor.entity_id),actor,
            'choice:needle.titan_size',['Large','Huge'],labels={'Large':'Become Large','Huge':'Become Huge'},
            prompt="Titanic Frame: choose Large or Huge. Your body grows only as far as legal space allows.")
        wanted=(selected or ['Large'])[0]
    else:
        wanted=dynamic_size.CATEGORIES[min(dynamic_size.CATEGORIES.index('Large'),dynamic_size.CATEGORIES.index(base)+1)]
    dynamic_size.apply_growth(engine,actor,wanted,PREFIX+FRAME,source_actor_id=actor.entity_id,
                             expires_on=effect_expiry(ctx,{'duration':'one_minute'},actor,condition=True))


@hook('forced_movement_bonus')
def might_push(ctx: Any, subject: Any, row: dict[str, Any]) -> int | None:
    # Explicit rider attribution wins over the triggering action's typing.
    source=str(ctx.effect_source or ctx.typed.get('source') or '')
    body=source.startswith(('tianxia.path.body_refining.','tianxia.subpath.body.'))
    if body and _active(ctx.engine,ctx.actor,MIGHT) and row.get('direction')=='away':
        return 5
    return None
