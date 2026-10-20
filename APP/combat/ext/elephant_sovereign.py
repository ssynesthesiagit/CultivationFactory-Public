"""White Elephant Sovereign Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, White Elephant Sovereign Body (the five features and their Normalized Procedures). Owned
rows: ``{"type": "path_passive", "kind": "elephant", "role": "frame" | "tusks" | "remembers" | "mountain" | "king"}``; the Large form
is the named state "mountain_walking_large" (toggled by Mountain-Walking Sovereign's Bonus Action, ``sovereign_size``); the King is
the named state "world_bearing_elephant_king". Both forms use native dynamic_size growth; functional size
bonuses are separate from their actual footprints. Trampling is owned by elephant_trample.py.

Sovereign Frame     one size larger (hook size_steps) for grappling, shoving and pushing and when something tries to move you;
                    Advantage on saves against being pushed, pulled, knocked Prone or moved.
Ivory Charge        once per turn, an unarmed hit after 15+ feet of this turn's willing movement straight toward the target (every
                    step closer): + PB Bludgeoning or Force, then a Strength save: pushed 10 feet, or 5.
Shelter Beneath the Tusks  when an ally within 15 feet is hit (asked; Reaction, 1 Stamina, once per round; hook hit_response): move
                    up to 10 feet toward it without provoking; next to it, choose: become the target (the same roll against your
                    AC; on a hit the damage is yours), Half Cover (+ 2 AC against that roll) or 2d10 + CON off its damage.
The Body Remembers  a hostile creature that damages your Hit Points is Remembered for the fight (a typed mark; PB of them, a new one
                    past the limit asks which to forget, or is declined): it gets no Advantage from being unseen against you, once
                    per turn + 2d8 Bludgeoning or Force on a hit against one, + PB on your saves against its moves, grapples,
                    Frightened and Restrained.
Mountain-Walking Sovereign  the Bonus Action turns the Large form on or off: + 5 feet unarmed reach, three sizes larger for the size
                    counts (Large plus two), Speed - 5 feet, ordinary difficult terrain ignored, and once per turn after 10 feet of
                    willing movement an asked 5-foot push of an adjacent creature no more than two sizes larger.
World-Bearing Elephant King  its state (typed: Resistance but Psychic, Void; Speed + 20; a following zone of hostile difficult
                    terrain): unarmed strikes roll 2d8 (hook attack_damage), once per turn + 4d8 on a hit, allies within 10 feet
                    get Half Cover when a ranged attack's line crosses your space, and a creature of your CL or lower cannot push,
                    pull or knock you Prone. Huge counts as two sizes larger.
Every hook returns early for a creature without these rows or states.
"""

from __future__ import annotations

from ..paid_relocation import activation, capture, causal_scope, retain, take

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.white_elephant_sovereign_body.feature."
LARGE = "mountain_walking_large"
KING = "world_bearing_elephant_king"
STAMINA = "resource:core.stamina"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "elephant"}


def _state(engine: Any, actor: Any, name: str) -> Any:
    from .states import active

    return active(engine, actor, name) if actor is not None else None


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _cl(engine: Any, actor_id: str) -> int:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor_id), None)
    return int((bundle or {}).get("cl") or 0)


def _con(engine: Any, actor: Any) -> int:
    return next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") or 0)
                 for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                 and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") is not None), 0)


# -------------------------------------------------------------------------------------------------- size and saves
@hook("size_steps")
def sovereign_size_steps(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    roles = _roles(engine, creature)
    if not roles:
        return None
    large, king = _state(engine, creature, LARGE), _state(engine, creature, KING)
    functional = 2 if large else 1 if "frame" in roles else 0  # Mountain-Walking's two replace the Frame's one
    return functional or None  # actual size now comes from the native footprint


@hook("save")
def sovereign_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if ctx is None or subject is None:
        return None
    roles = _roles(ctx.engine, subject)
    names = {str(n).lower() for n in named or ()}
    out: dict[str, Any] = {"bonus": 0, "modes": []}
    if "frame" in roles and names & {"forced_movement", "prone"}:
        out["modes"].append("ADVANTAGE")  # Sovereign Frame: Advantage on saves against being pushed or pulled, knocked Prone or moved
    if "remembers" in roles and _remembered(ctx.actor, subject) and names & {"forced_movement", "grappled", "frightened", "restrained"}:
        out["bonus"] += int(subject.proficiency_bonus or 2)
    return out if out["bonus"] or out["modes"] else None


# ------------------------------------------------------------------------------------------------------ Ivory Charge
def _charged_ft(engine: Any, actor: Any, target: Any) -> int:
    """Feet of this turn's willing movement in the latest run of steps each ending closer to ``target``."""
    steps: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            break
        payload = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not payload.get("forced") and not payload.get("teleport"):
            path = [(int(p["x"]), int(p["y"])) for p in payload.get("path") or [] if isinstance(p, dict)]
            steps = list(zip(path, path[1:])) + steps
    run = 0
    goal = (target.position.x, target.position.y)
    for a, b in reversed(steps):
        if engine.grid.distance_ft(b, goal) < engine.grid.distance_ft(a, goal):
            run += engine.grid.square_size_ft
        else:
            break
    return run


# ------------------------------------------------------------------------------------------------------ hit riders
@hook("after_hit")
def sovereign_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if (not roles and not _state(engine, actor, KING)) or target is None or not target.active or target.team_id == actor.team_id:
        return
    from .. import typed_executor as te

    stamp = _stamp(engine)
    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    if "frame" in roles and kind == "unarmed" and engine.state.current_actor_id == actor.entity_id and actor.turn_flags.get("_round_ivory_charge") != stamp \
            and _charged_ft(engine, actor, target) >= 15:
        actor.turn_flags["_round_ivory_charge"] = stamp
        push = lambda ft: {"type": "forced_movement", "applies_to": "target", "distance_ft": ft, "direction": "away"}
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": int(actor.proficiency_bonus or 2), "damage_types": ["bludgeoning", "force"],
                              "evidence": "Ivory Charge: + Proficiency Bonus"},
                             {"type": "save", "ability": "str", "evidence": "Ivory Charge: Strength saving throw", "on_fail": [push(10)], "on_success": [push(5)]}])
    if "remembers" in roles and target.active and _remembered(target, actor) and actor.turn_flags.get("_round_remembered_hit") != stamp:
        actor.turn_flags["_round_remembered_hit"] = stamp
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["bludgeoning", "force"],
                              "evidence": "The Body Remembers: + 2d8"}])
    if _state(engine, actor, KING) and target.active and actor.turn_flags.get("_round_king_hit") != stamp:
        actor.turn_flags["_round_king_hit"] = stamp
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": ["bludgeoning", "force"],
                              "evidence": "World-Bearing Elephant King: + 4d8"}])


@hook("attack_damage")
def king_unarmed_die(ctx: Any, dice: Any) -> Any:
    """"Unarmed strikes deal 2d8 before modifiers" while the King lasts."""
    if dice is None or not _state(ctx.engine, ctx.actor, KING):
        return None
    if not any(isinstance(e, dict) and e.get("attack_kind") == "unarmed" for e in (ctx.typed or {}).get("effects") or []):
        return None
    return dice.model_copy(update={"count": 2, "sides": 8})


# ---------------------------------------------------------------------------------------------- The Body Remembers
def _mark(owner: Any) -> str:
    from ..typed_executor import mark_condition_id

    return mark_condition_id("Remembered", owner.entity_id)


def _remembered(creature: Any, owner: Any) -> bool:
    return creature is not None and owner is not None and any(c.condition_id == _mark(owner) for c in creature.conditions.values())


@hook("event")
def remember_the_blow(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED" or int((kwargs.get("payload") or {}).get("hp_damage") or 0) < 1:
        return
    source = engine.state.actors.get(kwargs.get("actor_id") or "")
    for target_id in kwargs.get("target_ids") or ():
        owner = engine.state.actors.get(target_id)
        if owner is None or source is None or source.team_id == owner.team_id or "remembers" not in _roles(engine, owner) or _remembered(source, owner):
            continue
        mark = _mark(owner)
        held = [c for c in engine.state.actors.values() if any(h.condition_id == mark for h in c.conditions.values())]
        if len(held) >= int(owner.proficiency_bonus or 2):
            from .needle import ask, checkpoint_id

            options = {c.entity_id: c for c in held}
            picked = ask(engine, _intent(engine), checkpoint_id(engine, "remembered", source.entity_id), owner, "choice:needle.body_remembers", list(options),
                         labels={k: f"Forget {c.display_name}" for k, c in options.items()}, allow_decline=True, target_id=source.entity_id,
                         name="The Body Remembers", prompt=f"The Body Remembers: forget one creature to remember {source.display_name}, or decline?")
            if not picked or picked[0] not in options:
                continue
            gone = options[picked[0]]
            for iid, h in list(gone.conditions.items()):
                if h.condition_id == mark:
                    del gone.conditions[iid]
                    engine._append_event("CONDITION_REMOVED", PREFIX + "the_body_remembers", actor_id=owner.entity_id, target_ids=(gone.entity_id,),
                                         payload={"condition_id": mark, "instance_id": iid, "reason": "FORGOTTEN"})
        engine._apply_condition(source, mark, PREFIX + "the_body_remembers", owner.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": f"Remembered by {owner.display_name}"})


@hook("masked_conditions")
def remembered_unseen(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """"It cannot gain Advantage against you merely by being unseen"."""
    if target is None or attacker is None or "remembers" not in _roles(engine, target) or not _remembered(attacker, target):
        return None
    from ..senses import rules as sense_rules

    hidden = set(sense_rules().get("hidden_conditions") or [])
    ids = {iid for iid, held in attacker.conditions.items() if held.condition_id in hidden}
    return {attacker.entity_id: ids} if ids else None


# ------------------------------------------------------------------------------------------ Shelter Beneath the Tusks
@hook("hit_response")
def shelter_beneath_the_tusks(engine: Any, attacker: Any, target: Any, spec: Any, total: int, natural: int, effective_ac: int) -> Any:
    guards = [g for g in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if g.active and g.entity_id != target.entity_id
              and g.team_id == target.team_id and "tusks" in _roles(engine, g) and g.reaction_available and int(g.resources.get(STAMINA, 0) or 0) >= 1
              and g.turn_flags.get("_round_tusks") != int(engine.state.round_number) and engine._distance_actor_to_actor(g, target) <= 15]
    for guard in guards:
        answer = _tusks(engine, guard, attacker, target, spec, total, natural, effective_ac)
        if answer is not False:
            return answer
    return None


def _tusks(engine: Any, guard: Any, attacker: Any, target: Any, spec: Any, total: int, natural: int, effective_ac: int) -> Any:
    from ..gate2_runtime_models import DiceSpec
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    intent = _intent(engine)
    picked = ask(engine, intent, checkpoint_id(engine, "tusks", target.entity_id), guard, "choice:needle.shelter_beneath_the_tusks", ["use"],
                 labels={"use": "Reaction, 1 Stamina: move up to 10 feet toward it and shield it"}, allow_decline=True, default="decline",
                 target_id=target.entity_id, name="Shelter Beneath the Tusks",
                 prompt=f"Shelter Beneath the Tusks: {attacker.display_name}'s attack hits {target.display_name}. Step in?")
    if not picked:
        return False
    with activation(engine, guard, PREFIX + "shelter_beneath_the_tusks"):
        guard.reaction_available = False
        guard.turn_flags["_round_tusks"] = int(engine.state.round_number)
        engine._spend_resource(guard, STAMINA, 1, PREFIX + "shelter_beneath_the_tusks")
        engine._append_event("REACTION_RESOLVED", PREFIX + "shelter_beneath_the_tusks", actor_id=guard.entity_id, target_ids=(attacker.entity_id,),
                             payload={"checkpoint": "ALLY_HIT", "protects": target.entity_id})
        now = engine._distance_actor_to_actor(guard, target)
        if now > engine.grid.square_size_ft:
            paths = {k: p for k, p in routes(engine, guard, 10).items() if engine.grid.distance_ft(p[-1], target.position) < now}
            if paths:
                nearest = min(paths, key=lambda k: (engine.grid.distance_ft(paths[k][-1], target.position), len(paths[k]), k))
                move = ask(engine, intent, checkpoint_id(engine, "tusks_move", guard.entity_id), guard, "choice:needle.tusks_move", sorted(paths),
                           labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, preferred=[nearest], target_id=guard.entity_id,
                           name="Shelter Beneath the Tusks", prompt="Shelter Beneath the Tusks: move up to 10 feet toward it.")
                chosen = move[0] if move and move[0] in paths else nearest
                step(engine, guard, paths[chosen], PREFIX + "shelter_beneath_the_tusks")
        if engine._distance_actor_to_actor(guard, target) > engine.grid.square_size_ft or not guard.active:
            return None  # not adjacent: the attack resolves normally
        from ..typed_reactions import attack_reaches

        labels = {"cover": "Grant it Half Cover against this attack", "reduce": "Take 2d10 + Constitution modifier off its damage"}
        if attack_reaches(engine, attacker, guard, {"attack_kind": "ranged" if int((spec or {}).get("range_ft") or 0) > 5 else "melee"}):
            labels = {"target": "Become the target instead", **labels}
        option = ask(engine, intent, checkpoint_id(engine, "tusks_option", target.entity_id), guard, "choice:needle.tusks_option", list(labels), labels=labels,
                     target_id=target.entity_id, name="Shelter Beneath the Tusks", prompt="Shelter Beneath the Tusks: choose one.")
        choice = option[0] if option and option[0] in labels else "reduce"
        if choice == "cover":
            return (effective_ac + 2, False) if natural != 20 and total < effective_ac + 2 else None
        if choice == "reduce":
            roll = engine.roller.roll(DiceSpec(count=2, sides=10, modifier=_con(engine, guard)), actor_id=guard.entity_id, reason=f"REDUCTION:{PREFIX}shelter_beneath_the_tusks")
            engine._record_roll(roll)
            target.turn_flags["_tusk_reduce"] = {"by": attacker.entity_id, "amount": max(0, int(roll.total))}
            return None
        guard_ac = int(guard.armor_class) + int(engine._ac_modifier(guard))  # the same roll against your AC (gate2_engine's own sum)
        if natural != 20 and total < guard_ac:
            note(engine, PREFIX + "shelter_beneath_the_tusks", guard, f"Shelter Beneath the Tusks: {guard.display_name} takes the blow on the tusks; it misses.")
            return guard_ac, False  # terminal numerical comparison against the replacement target
        target.turn_flags["_tusk_redirect"] = {"by": attacker.entity_id, "to": guard.entity_id}
        retain(engine, ("_tusk_redirect", target.entity_id, attacker.entity_id), capture(engine))
        return None


@hook("damage_pending")
def tusks_damage(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str) -> int | None:
    reduce = target.turn_flags.get("_tusk_reduce")
    if reduce and reduce.get("by") == source_actor_id:
        target.turn_flags.pop("_tusk_reduce", None)  # one triggering packet
        return max(0, pending - int(reduce.get("amount") or 0))
    redirect = target.turn_flags.get("_tusk_redirect")
    if not redirect or redirect.get("by") != source_actor_id:
        return None
    with causal_scope(engine, take(engine, ("_tusk_redirect", target.entity_id, source_actor_id))):
        target.turn_flags.pop("_tusk_redirect", None)
        guard = engine.state.actors.get(str(redirect.get("to") or ""))
        if guard is None or not guard.active:
            return None
        from .. import typed_reactions

        kind = str(getattr(engine, "_typed_pending_damage_type", None) or "BLUDGEONING").upper()
        taken = typed_reactions.defend(engine, guard, pending, kind, source_definition_id, source_actor_id)
        previous = getattr(engine, "_damage_unreduced", None)
        engine._damage_unreduced = guard.entity_id  # its own defenses have run: the commit must not reduce it again
        try:
            engine._commit_damage(guard, taken, kind, source_definition_id, source_actor_id, None, reaction_depth=2)
        finally:
            engine._damage_unreduced = previous
        note(engine, PREFIX + "shelter_beneath_the_tusks", guard, f"Shelter Beneath the Tusks: {guard.display_name} takes the blow meant for {target.display_name}.")
        return 0


# ------------------------------------------------------------------------------------------- Mountain-Walking Sovereign
@effect("sovereign_size")
def sovereign_size(ctx: Any, row: dict[str, Any]) -> None:
    """The Bonus Action: become Large, or return to normal size."""
    from .states import PREFIX as STATE, slug

    engine, actor = ctx.engine, ctx.actor
    from .. import dynamic_size
    held = _state(engine, actor, LARGE)
    if held is not None:
        for iid, h in list(actor.conditions.items()):
            if h.condition_id in (STATE + slug(LARGE), "condition:typed.ignore_difficult", dynamic_size.CONDITION) and h.source_definition_id == PREFIX + "mountain_walking_sovereign":
                del actor.conditions[iid]
                engine._append_event("CONDITION_REMOVED", PREFIX + "mountain_walking_sovereign", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                     payload={"condition_id": h.condition_id, "instance_id": iid, "reason": "NORMAL_SIZE"})
        dynamic_size.sync(engine, ctx.source)
        return
    category = dynamic_size.fitting_category(engine, actor, "Large")
    if category != "Large":
        note(engine, ctx.source, actor, f"Mountain-Walking Sovereign: there is no room for {actor.display_name} to become Large.")
        return
    dynamic_size.apply_growth(engine, actor, "Large", PREFIX + "mountain_walking_sovereign", source_actor_id=actor.entity_id, expires_on="UNTIL_REMOVED")
    engine._apply_condition(actor, STATE + slug(LARGE), PREFIX + "mountain_walking_sovereign", actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Mountain-Walking Sovereign: Large", "name": LARGE})
    engine._apply_condition(actor, "condition:typed.ignore_difficult", PREFIX + "mountain_walking_sovereign", actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Large: ordinary difficult terrain costs no extra movement"})


@hook("event")
def sovereign_growth(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from .states import PREFIX as STATE, slug
    from .. import dynamic_size
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_APPLIED" and payload.get("condition_id") == STATE + slug(KING):
        actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if actor is not None and _state(engine, actor, KING) is not None:
            held = _state(engine, actor, KING)
            dynamic_size.apply_growth(engine, actor, "Huge", held.source_definition_id, source_actor_id=actor.entity_id,
                                      expires_on=payload.get("expires_on"))
    if event_type == "CONDITION_APPLIED" and str(payload.get("condition_id") or "").endswith("unconscious"):
        actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if actor is not None:
            from .condition_ownership import remove_instance
            for held in list(actor.conditions.values()):
                if held.source_definition_id in (PREFIX + KING, PREFIX + "mountain_walking_sovereign"):
                    remove_instance(engine, actor, held.instance_id, held.source_definition_id)


@hook("speed")
def large_is_slower(engine: Any, actor: Any) -> int | None:
    return -5 if _state(engine, actor, LARGE) else None


@hook("event")
def mountain_push(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Mountain-Walking Sovereign: once a turn, after 10 feet of movement, an adjacent creature is pushed 5 feet unless it is more
    than two sizes larger (asked; the push is forced movement, so it never provokes)."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    payload = kwargs.get("payload") or {}
    if actor is None or payload.get("forced") or payload.get("teleport") or engine.state.current_actor_id != actor.entity_id \
            or not _state(engine, actor, LARGE) or actor.turn_flags.get("_round_mountain_push") == _stamp(engine):
        return
    moved = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            break
        p = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not p.get("forced") and not p.get("teleport"):
            moved += max(0, len(p.get("path") or []) - 1) * engine.grid.square_size_ft
    if moved < 10:
        return
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id
    from .states import context

    ctx = context(engine, actor, PREFIX + "mountain_walking_sovereign", [actor], {})
    near = {c.entity_id: c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.entity_id != actor.entity_id
            and engine._distance_actor_to_actor(actor, c) <= engine.grid.square_size_ft
            and te.size_width(ctx, c, "subject", {}) <= te.size_width(ctx, actor, "actor", {}) + 2}
    if not near:
        return
    actor.turn_flags["_round_mountain_push"] = _stamp(engine)
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "mountain_push", actor.entity_id), actor, "choice:needle.mountain_push", list(near),
                 labels={k: f"Push {c.display_name} 5 feet" for k, c in near.items()}, allow_decline=True, target_id=actor.entity_id,
                 name="Mountain-Walking Sovereign", prompt="Mountain-Walking Sovereign: shoulder an adjacent creature 5 feet aside?")
    if picked and picked[0] in near:
        push_ctx = context(engine, actor, PREFIX + "mountain_walking_sovereign", [near[picked[0]]], {})
        push_ctx.target = near[picked[0]]
        te.run_effects(push_ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])


# ------------------------------------------------------------------------------------------ World-Bearing Elephant King
@hook("cover")
def king_shelters_allies(engine: Any, attacker: Any, target: Any) -> int | None:
    best = None
    for king in engine.state.actors.values():
        if not king.active or king.entity_id == target.entity_id or king.team_id != target.team_id or not _state(engine, king, KING):
            continue
        if engine._distance_actor_to_actor(king, target) > 10:
            continue
        space = {(c.x, c.y) if hasattr(c, "x") else tuple(c) for c in engine._actor_cells(king)}
        if space & set(engine.grid.ray_cells(attacker.position, target.position)[1:-1]):
            best = 2
    return best


@hook("forced_distance")
def king_is_anchored(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    if mover is None or source is None or source.entity_id == mover.entity_id or not _state(engine, mover, KING):
        return None
    return distance_ft if _cl(engine, source.entity_id) <= _cl(engine, mover.entity_id) else None


@hook("condition_attempt")
def king_stays_up(ctx: Any, subject: Any, effect: Any) -> bool | None:
    if str((effect or {}).get("condition") or "").lower() != "prone" or subject is None or not _state(ctx.engine, subject, KING):
        return None
    if ctx.actor is subject or _cl(ctx.engine, ctx.actor.entity_id) > _cl(ctx.engine, subject.entity_id):
        return None
    return False


@hook("subject_teleport_attempt")
def king_resists_hostile_teleport(ctx: Any, subject: Any, start: Any, destination: Any) -> bool | None:
    if (subject is ctx.actor or subject.team_id == ctx.actor.team_id
            or not _state(ctx.engine, subject, KING) or ctx.typed.get("ignores_bodily_anchoring")):
        return None
    return False if int(ctx.numbers.get("cl") or 1) <= _cl(ctx.engine, subject.entity_id) else None
