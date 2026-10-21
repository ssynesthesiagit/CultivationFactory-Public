"""Formations talents whose printed lines were left to the GM (rider lane 9, 2026-09-29; owner: "i want everything we can automated").
Built on combat/ext/formations.py (the array, its Eye and Nodes, keyed creatures, Pulse) and the round-16 hooks.  Owner's text first
(authority/typed_mechanics/rules_text.json); nothing here is invented.

  Formation Maze      (CL 10) "When a hostile creature enters one of your arrays or starts its turn inside it, you may use your Reaction and
                      spend 2 CP ... The creature makes a Wisdom saving throw. Failed Save: Until the start of your next turn, the creature
                      cannot willingly move closer to a chosen keyed ally, Array Eye, exit, door, or Node inside the array. Successful
                      Save: Its next 10 feet of movement inside the array costs 10 additional feet."
                      The owner picks the anchor (the Eye, a Node, or a keyed ally inside) or passes; a failure leaves a
                      ``formation_maze_lost`` condition naming the anchor, enforced at every voluntary step (``movement_attempt``,
                      the way the engine keeps a Frightened creature from nearing its fear, so a move granted by an ability is
                      refused too) and offered no nearer square in the first place (``candidate_allowed``); a success leaves
                      a plain GM rider for the successful-save tax. New arrays also offer perceived map doors and gates;
                      an abstract exit without a map object remains manual. Accurate bounded tax pricing needs a route-aware cost seam in the locked
                      engine; charging after payment or consuming tax before payment is unsafe.
  Reflecting Gate     (CL 5) Reaction, 2 CP, when a creature outside one of your arrays targets a creature inside it with a ranged attack
                      or a single-target supernatural effect: a Formation Check against the attack roll (or the Cultivation Save DC);
                      success: the effect misses, is redirected to another legal target inside or adjacent to the array, or rebounds
                      on the attacker.  A ranged attack that hits is answered on ``hit_response`` (the roll is known then); a
                      redirected or rebounding attack is compared, with the same roll, to the new target's AC on ``after_miss`` (the
                      way Redirecting Shield sends a missed attack on).  A single-target technique without an attack roll is answered
                      before payment (``technique_declared``): miss, redirect and rebound use the real activation pipeline.
                      It never answers an effect from inside the array or an area effect.
  Nine Palaces        (CL 15) "When you Pulse the Killing Line Pattern, choose up to three hostile creatures inside the array. Make one
  Killing Array       Formation Attack roll and compare it to each target's AC. Hit: A target takes 4d8 + your Formation key ability
                      modifier damage."  The Pulse's creature and up to two more hostile creatures inside the array share one d20;
                      each hit takes 4d8 + key modifier of the array's damage type (Harmonized and Elemental riders ride it as on
                      an ordinary Killing Line Pulse).  The killing line between two Nodes stays with the GM: the printed rules never
                      say where a Flow Line runs.
"""

from __future__ import annotations

from ..paid_relocation import activation, capture, causal_scope, retain, take, preserve_pending

import dataclasses
from typing import Any

from . import effect, hook
from . import formations as F
from .needle import CHOICE, ask, checkpoint_id

MAZE, REFLECT, NINE = "formation_maze", "reflecting_gate", "nine_palaces_killing_array"
LOST, SLOWED = "condition:typed.formation_maze_lost", "condition:typed.formation_maze_slowed"
SOURCE_MAZE, SOURCE_REFLECT, SOURCE_NINE = "formation:formation_maze", "formation:reflecting_gate", "formation:nine_palaces"
PARKED = "_formation_reflect_parked"


def _owner_ready(engine: Any, zone: Any, talent: str, cl: int, cost: int) -> Any:
    """The array's owner, when it knows ``talent`` at CL ``cl`` or higher and can spend its Reaction and ``cost`` CP now."""
    from .formation_masters import incapacitated

    record = F.record(zone)
    numbers = record.get("numbers") or {}
    owner = engine.state.actors.get(zone.owner_id)
    pool = str(numbers.get("formation_pool") or "resource:core.qi")
    if owner is None or not owner.active or talent not in F.talents_of(numbers) or int(numbers.get("cl") or 1) < cl or incapacitated(owner) \
            or not owner.reaction_available or owner.resources.get(pool, 0) < cost or F.has_condition(owner, "formation_cp_locked") is not None:
        return None
    from .. import typed_reactions

    if not typed_reactions._can_react(engine, owner):
        return None
    return owner


def _pay(engine: Any, owner: Any, zone: Any, cost: int, source: str, targets: tuple[str, ...]) -> None:
    pool = str((F.record(zone).get("numbers") or {}).get("formation_pool") or "resource:core.qi")
    owner.reaction_available = False
    engine._spend_resource(owner, pool, cost, source)
    engine._append_event("REACTION_RESOLVED", source, actor_id=owner.entity_id, target_ids=targets, payload={"reaction": source.split(":", 1)[-1]})


def _intent(engine: Any) -> Any:
    return getattr(engine, "_active_intent", None)


# ------------------------------------------------------------------------------------------------ Formation Maze
MAZE_FOOT = 10  # "Its next 10 feet of movement inside the array costs 10 additional feet"


@hook('compile_action')
def maze_map_permission(action: Any, info: dict[str, Any]) -> Any | None:
    """Seal new map-anchor support without changing historical array choices."""
    typed = action.parameters.get('typed') or {}
    if not action.parameters.get(F.TAG) or 'tianxia.talent.formations.' + MAZE not in (info.get('owned_ids') or []):
        return None
    return action.model_copy(update={'parameters': {**action.parameters,
        'typed': {**typed, 'numbers': {**(typed.get('numbers') or {}), 'formation_maze_map_anchors': 1}}}})


def _maze_zone(engine: Any, creature: Any, *, entering: bool, previous: Any = None, nxt: Any = None) -> Any:
    """The array whose Formation Maze may answer this creature: one any part of whose body it has just stepped into, or
    starts its turn inside.  Entry is read at the square before and the square after with the array's own whole-body
    membership (``formations.inside_at``), so a Large creature is caught crossing the boundary with its leading squares."""
    if creature is None or not creature.active:
        return None
    for zone in F.arrays(engine):
        if not F.hostile_to(engine, zone, creature):
            continue
        if nxt is not None:
            here = F.inside_at(engine, creature, zone, nxt)
            if entering and previous is not None and here == F.inside_at(engine, creature, zone, previous):
                continue  # it was already inside before this step: that is the start-of-turn question, not an entry
        else:
            here = F.inside(engine, creature, zone)
        if here and _owner_ready(engine, zone, MAZE, 10, 2) is not None:
            return zone
    return None


def _maze_anchors(engine: Any, zone: Any, creature: Any) -> dict[str, tuple[str, tuple[int, int]]]:
    """Live array parts, keyed allies, and (for new arrays) perceived map doors/gates."""
    profile = F.record(zone)
    found: dict[str, tuple[str, tuple[int, int]]] = {}
    for oid in [profile.get("eye"), *(profile.get("nodes") or [])]:
        row = engine.state.objects.get(str(oid or ""))
        if row is None or row.destroyed:
            continue
        role = str((row.component or {}).get("role") or "node").title()
        found[f"object:{row.object_id}"] = (f"the Array {role}", (row.position.x, row.position.y))
    for ally in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if ally.active and ally.entity_id != creature.entity_id and F.keyed(engine, zone, ally) and F.inside(engine, ally, zone):
            found[f"actor:{ally.entity_id}"] = (ally.display_name, (ally.position.x, ally.position.y))
    if (profile.get('numbers') or {}).get('formation_maze_map_anchors'):
        from ..object_rules import label
        from ..senses import perceives_cell
        owner = engine.state.actors.get(zone.owner_id)
        for obj in sorted(engine.state.objects.values(), key=lambda row: row.object_id):
            if (not obj.destroyed and obj.object_kind in ('door', 'gate')
                    and (obj.position.x, obj.position.y) in F.cells_of(zone)
                    and owner is not None and perceives_cell(engine, owner, obj.position)):
                found[f'object:{obj.object_id}'] = (label(obj), (obj.position.x, obj.position.y))
    return found


def _maze_owner_until(engine: Any, owner: Any) -> str:
    """"Until the start of your next turn" -- the Maze owner's own next turn, named exactly
    (``combat.ext.effect_durations.token``), so neither the affected creature's own turn nor an intervening one takes it early."""
    from . import effect_durations

    return effect_durations.token("start", owner.entity_id, int(owner.turns_started) + 1)


def _anchor_live(engine: Any, held: Any) -> tuple[str, Any] | None:
    """The chosen anchor as it stands now: (readable name, its live position), or None once it is gone.

    The condition stores the anchor's identity, not the square it stood on when it was chosen, so a keyed ally, or a moving
    Eye or Node, is turned away from where it actually is.  A condition saved before this reading (a bare x/y pair, no
    identity) preserves its old square-based behavior because the saved record cannot identify the anchor."""
    data = held.data or {}
    kind, _, identity = str(data.get("anchor") or "").partition(":")
    if kind == "actor":
        row = engine.state.actors.get(identity)
        return (row.display_name, row.position) if row is not None and row.active else None
    if kind == "object":
        row = engine.state.objects.get(identity)
        if row is None or row.destroyed:
            return None
        if not (row.component or {}).get(F.KEY):
            from ..object_rules import label
            return label(row), row.position
        role = str((row.component or {}).get("role") or "node").title()
        return f"the Array {role}", row.position
    if data.get("x") is None and data.get("y") is None:
        return None
    from ..gate2_runtime_models import Position

    return str(data.get("anchor_name") or "the anchor"), Position(x=int(data.get("x") or 0), y=int(data.get("y") or 0))


def _maze_path_turned(engine: Any, zone: Any, creature: Any, trigger: str) -> None:
    """The printed resolution: the owner spends its Reaction and 2 CP, the creature saves, and that outcome lands."""
    owner = _owner_ready(engine, zone, MAZE, 10, 2)
    if owner is None:
        return
    anchors = _maze_anchors(engine, zone, creature)
    numbers = F.record(zone).get("numbers") or {}
    dc = int(numbers.get("save_dc") or 10)
    map_notice = ("An exit without a door or gate on the map still needs the GM to identify it."
                  if numbers.get('formation_maze_map_anchors') else "Doors and exits also need the GM to resolve them.")
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "FORMATION_MAZE", zone.zone_id, creature.entity_id), owner,
                 CHOICE + MAZE, list(anchors), labels={key: value[0] for key, value in anchors.items()},
                 preferred=list(anchors)[:1], allow_decline=True, target_id=creature.entity_id,
                 name='Formation Maze', feature_id='tianxia.talent.formations.' + MAZE,
                 prompt_context={'cost': 'Reaction; 2 CP',
                                 'paying_pool': str(numbers.get('formation_pool') or 'resource:core.qi')},
                 prompt=f"Formation Maze (spend your Reaction and 2 Cultivation Points): {creature.display_name} {trigger} your array. Choose what the maze "
                        f"turns it away from. If it fails its Wisdom save against DC {dc}, it cannot willingly move closer to that "
                        f"until the start of your next turn. If it saves, its next {MAZE_FOOT} feet of movement inside the array "
                        f"costs {MAZE_FOOT} additional feet; the GM tracks and charges that tax manually. "
                        f"{map_notice}")
    if not picked:
        return
    with activation(engine, owner, SOURCE_MAZE):
        roll = engine._roll_save(creature, "WIS", dc, SOURCE_MAZE)
        if roll is None:  # no dice available: nothing is paid and the GM keeps the printed line
            F.say(engine, SOURCE_MAZE, owner.entity_id,
                  f"Formation Maze: {creature.display_name} must make its Wisdom save against DC {dc}; the GM resolves it here.")
            return
        _pay(engine, owner, zone, 2, SOURCE_MAZE, (creature.entity_id,))
        if roll.total < dc:
            name, cell = anchors[picked[0]]
            engine._apply_condition(creature, LOST, SOURCE_MAZE, owner.entity_id, expires_on=_maze_owner_until(engine, owner),
                data={"zone": zone.zone_id, "anchor": picked[0], "anchor_name": name, "x": cell[0], "y": cell[1],
                      "label": f"Formation Maze: cannot willingly move closer to {name} until the start of {owner.display_name}'s next turn"})
            F.say(engine, SOURCE_MAZE, owner.entity_id,
                  f"Formation Maze: {creature.display_name} fails its Wisdom save ({roll.total} against DC {dc}), "
                  f"so it cannot willingly move closer to {name} until the start of {owner.display_name}'s next turn.")
            return
        F.say(engine, SOURCE_MAZE, owner.entity_id,
              f"Formation Maze: {creature.display_name} succeeds on its Wisdom save ({roll.total} against DC {dc}). "
              f"GM: charge 10 additional feet for its next 10 feet of movement inside this array, counting only movement "
              f"actually completed inside. Unused tax has no turn deadline. The table does not charge this tax automatically.")


def _maze_bar_blocks(engine: Any, creature: Any, previous: Any, nxt: Any) -> tuple[Any, str] | None:
    """Whether this one step closes on the anchor, as (condition, anchor name).  One reader for both callers: the step gate,
    which walks the path the engine is walking, and the menu filter, which walks the whole candidate, so a square the table is
    offered is never one the engine then refuses. Check all owned restrictions; a missing/destroyed anchor is ignored
    until ordinary expiry. This query never mutates fight state."""
    for held in creature.conditions.values():
        if held.condition_id != LOST:
            continue
        live = _anchor_live(engine, held)
        if live is None:
            continue
        name, spot = live
        if engine.grid.distance_ft(nxt, spot) < engine.grid.distance_ft(previous, spot):
            return held, name
    return None


@hook("movement_attempt")
def maze_entry(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> Any:
    """A hostile creature stepping into one of your arrays: the owner may turn the path against it.

    Then the standing restriction is asked of this same step.  A failed save reads "cannot willingly move closer ... until the
    start of your next turn", so the step that triggered it is the step that is refused, and every later one, and any movement
    an ability granted that never passed through the move menu at all."""
    zone = _maze_zone(engine, mover, entering=True, previous=previous, nxt=nxt)
    if zone is not None:
        _maze_path_turned(engine, zone, mover, "steps into")
    blocked = _maze_bar_blocks(engine, mover, previous, nxt)
    if blocked is None:
        return None
    held, name = blocked
    owner = engine.state.actors.get(str(held.source_actor_id or ""))
    whose = f"{owner.display_name}'s" if owner is not None else "the array owner's"
    return {"stop": True, "source_id": SOURCE_MAZE,
            "label": f"Formation Maze: {mover.display_name} cannot willingly move closer to {name} until the start of {whose} next turn."}


@hook("turn_start_choice")
def maze_turn_start(engine: Any, actor: Any) -> None:
    """A hostile creature starts its turn inside one of your arrays; the owner may turn its path against it."""
    zone = _maze_zone(engine, actor, entering=False)
    if zone is not None:
        _maze_path_turned(engine, zone, actor, "starts its turn inside")


@hook("candidate_allowed")
def maze_closer(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Failed Maze: no Move square nearer the chosen anchor anywhere on its canonical path, detours included."""
    if getattr(candidate.kind, "value", candidate.kind) != "MOVE" or candidate.destination is None:
        return None
    previous = actor.position
    for square in (*candidate.canonical_path, candidate.destination):
        if square == previous:
            continue
        if _maze_bar_blocks(engine, actor, previous, square) is not None:
            return False
        previous = square
    return None


# ------------------------------------------------------------------------------------------------ Reflecting Gate
def _gate_for(engine: Any, attacker: Any, target: Any) -> tuple[Any, Any] | None:
    """(array, owner) whose Reflecting Gate may answer an effect from ``attacker`` at ``target``: the target inside the array, the
    attacker outside it (an effect "that originates inside the array" is never answered), the owner able to pay."""
    from . import ai_controlled
    from ..target_knowledge import located
    for zone in F.arrays(engine):
        if not F.inside(engine, target, zone) or F.inside(engine, attacker, zone):
            continue
        owner = _owner_ready(engine, zone, REFLECT, 5, 2)
        if owner is None:
            continue
        if ai_controlled(engine, owner) and (owner.team_id != target.team_id or owner.team_id == attacker.team_id
                                           or not located(engine, owner, attacker) or not located(engine, owner, target)):
            continue
        return zone, owner
    return None


def _near_array(engine: Any, zone: Any, who: Any) -> bool:
    """Inside the array or adjacent to it (within 5 feet of one of its squares)."""
    return F.inside(engine, who, zone) or any(engine._distance_actor_to_cell(who, cell) <= 5 for cell in zone.affected_cells)


def _reflect_options(engine: Any, zone: Any, attacker: Any, target: Any, range_ft: int | None, attack: bool) -> dict[str, str]:
    from .redirection import legal_target

    options = {"miss": f"Reflecting Gate: the effect misses {target.display_name}"}
    if not attack:
        return options  # a technique's save target cannot be re-aimed on this table
    for other in engine.state.actors.values():
        if other.entity_id in (attacker.entity_id, target.entity_id) or not _near_array(engine, zone, other):
            continue
        if legal_target(engine, attacker, other, range_ft):
            options[f"redirect:{other.entity_id}"] = f"Reflecting Gate: redirect it to {other.display_name}"
    options["rebound"] = f"Reflecting Gate: it rebounds on {attacker.display_name}"
    return options


@hook("hit_response")
def reflecting_gate_attack(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> Any:
    """A ranged attack from outside the array hits a creature inside it: the owner may answer (Reaction, 2 CP, Formation Check against
    the attack roll)."""
    from ..technique_interception import frame

    # The resolving packet owns the source, including nested/reaction attacks.
    # Its activation frame retains the actual action even for triggered rows
    # absent from the catalog. Never classify the unrelated foreground intent.
    source = spec.get("source_definition_id")
    action = frame(engine, attacker.entity_id, source).get("action") or engine.action_catalog.get(source)
    if action is not None and _excluded_technique(action):
        return None
    if not (spec.get("range_ft") is not None and int(spec.get("range_ft") or 0) > 5) or getattr(engine, "_redirection_busy", False):
        return None
    found = _gate_for(engine, attacker, target)
    if found is None:
        return None
    zone, owner = found
    typed_attacker = attacker.entity_id in (getattr(engine, "typed_actor_ids", set()) or set())
    options = _reflect_options(engine, zone, attacker, target, int(spec.get("range_ft") or 0), typed_attacker)
    ac = {row.entity_id: row.armor_class + engine._ac_modifier(row) for row in engine.state.actors.values()}
    hostile_first = sorted((key for key in options if key.startswith("redirect:")),
                           key=lambda key: (engine.state.actors[key.split(":", 1)[1]].team_id == owner.team_id, ac[key.split(":", 1)[1]]))
    from ..target_knowledge import located
    good = [key for key in hostile_first if located(engine, owner, engine.state.actors[key.split(":", 1)[1]]) and engine.state.actors[key.split(":", 1)[1]].team_id != owner.team_id and natural != 1
            and (natural == 20 or total >= ac[key.split(":", 1)[1]])]
    preferred = good[:1] or (["rebound"] if typed_attacker and natural != 1 and (natural == 20 or total >= ac[attacker.entity_id]) else ["miss"])
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "REFLECTING_GATE", owner.entity_id, attacker.entity_id, target.entity_id), owner,
                 CHOICE + REFLECT, list(options), labels=options, preferred=preferred, automatic_options=["miss", *good, *(["rebound"] if "rebound" in options else [])], allow_decline=True, target_id=target.entity_id,
                 prompt=f"Reflecting Gate (Reaction, 2 CP): {attacker.display_name}'s attack ({total}) hits {target.display_name} inside your array.")
    if not picked:
        return None
    with activation(engine, owner, SOURCE_REFLECT):
        _pay(engine, owner, zone, 2, SOURCE_REFLECT, (attacker.entity_id, target.entity_id))
        numbers = F.record(zone).get("numbers") or {}
        if not F.formation_check(engine, owner, numbers, int(total), SOURCE_REFLECT, "Reflecting Gate against the attack roll"):
            F.say(engine, SOURCE_REFLECT, owner.entity_id, "Reflecting Gate: the Formation Check fails; the attack hits.")
            return None
        choice = picked[0]
        if choice != "miss":
            aim = attacker.entity_id if choice == "rebound" else choice.split(":", 1)[1]
            preserve_pending(engine, PARKED)
            engine.__dict__.setdefault(PARKED, {})[attacker.entity_id] = {"target": aim, "total": int(total), "natural": int(natural), "from": target.entity_id}
            retain(engine, (PARKED, attacker.entity_id), capture(engine))
        F.say(engine, SOURCE_REFLECT, owner.entity_id, options[choice].replace("Reflecting Gate: ", "Reflecting Gate: the check succeeds; "))
        from ..attack_outcomes import unconditional_miss

        return unconditional_miss()


@hook("after_miss")
def reflecting_gate_resend(ctx: Any, target: Any) -> None:
    """The redirected (or rebounding) attack: the same roll against the new target's AC; its hit runs the attack's own on-hit effects."""
    from ..typed_executor import Context, run_effects

    preserve_pending(ctx.engine, PARKED)
    parked = (ctx.engine.__dict__.get(PARKED) or {}).pop(ctx.actor.entity_id, None)
    if not parked or parked.get("from") != target.entity_id:
        return
    with causal_scope(ctx.engine, take(ctx.engine, (PARKED, ctx.actor.entity_id))):
        engine = ctx.engine
        chosen = engine.state.actors.get(parked["target"])
        attack = next((row for row in ctx.typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), None)
        if chosen is None or not chosen.active or attack is None:
            return
        total, natural = int(parked["total"]), int(parked["natural"])
        ac = chosen.armor_class + engine._ac_modifier(chosen)
        hit = natural != 1 and (natural == 20 or total >= ac)
        engine._append_event("PASSIVE_TRIGGERED", SOURCE_REFLECT, actor_id=ctx.actor.entity_id, target_ids=(chosen.entity_id,),
                             payload={"trigger": "Reflecting Gate", "total": total, "ac": ac, "hit": hit,
                                      "log": f"Reflecting Gate: the attack ({total}) turns on {chosen.display_name} (AC {ac}): {'hit' if hit else 'miss'}."})
        if not hit:
            return
        on_hit = [row for row in attack.get("on_hit") or [] if isinstance(row, dict)]
        if not any(row.get("type") == "damage" for row in on_hit) and not attack.get("no_damage"):
            on_hit = [{"type": "damage", "weapon_damage": True}, *on_hit]
        engine._redirection_busy = True
        try:
            run_effects(Context(engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [chosen], chosen, {}), on_hit)
        finally:
            engine._redirection_busy = False


def _excluded_technique(action: Any) -> bool:
    """Printed authority categories that a boundary defence cannot redirect."""
    from .qiweaving_common import is_secret_inheritance
    return is_secret_inheritance(action) or str(action.economy).lower() in {
        "legendary_action", "lair_action", "legendary action", "lair action"}



@hook("technique_declared")
def reflecting_gate_technique(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> dict[str, Any] | None:
    """Re-aim the real single-creature save/effect before payment and delivery.

    The native declaration seam retains the accepted intent and catalog, charges
    the triggering activation even on a miss, and runs saves on the new recipient.
    A redirection can legally hit the original caster's ally; recipient side is
    measured for the reflector's automatic choice, not the caster's declaration.
    """
    from ..recipients import allowed
    from ..target_knowledge import located
    typed = action.parameters.get("typed") or {}
    if (not typed or typed.get("weapon") is not None or (typed.get("area") or {}).get("size_ft")
            or len(candidate.target_ids or ()) != 1 or candidate.destination is not None
            or candidate.kind.value == "REACTION" or _excluded_technique(action)):
        return None
    if any(isinstance(row, dict) and row.get("type") == "attack" for row in typed.get("effects") or []):
        return None
    if action.parameters.get(F.TAG) or action.target_kind not in ("HOSTILE_ENTITY", "ANY_CREATURE", "ALLY_OR_SELF"):
        return None
    target = engine.state.actors.get(candidate.target_ids[0])
    if target is None or target is actor:
        return None
    found = _gate_for(engine, actor, target)
    if found is None:
        return None
    zone, owner = found
    from . import ai_controlled
    if ai_controlled(engine, owner) and not (action.target_kind == "HOSTILE_ENTITY" or action.parameters.get("harmful") is True):
        return None  # Do not automatically redirect a beneficial or unclassified effect to an enemy.
    # The temporary side-neutral targeting domain must not erase the action's
    # hostile/harmful nature (for example, Charm's source protection).
    from ..technique_interception import redirected_action
    check_action = redirected_action(action, "ANY_CREATURE")
    options = {"miss": f"Reflecting Gate: {action.display_name} misses {target.display_name}"}
    for other in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if other is target or not located(engine, owner, other) or not allowed(engine, actor, other, check_action):
            continue
        if other is actor:
            options["rebound"] = f"Reflecting Gate: {action.display_name} rebounds on {actor.display_name}"
        elif _near_array(engine, zone, other):
            options["redirect:" + other.entity_id] = f"Reflecting Gate: redirect {action.display_name} to {other.display_name}"
    # Harm goes to a perceived enemy of the reflector. Allies remain available
    # to a manual player, but are never an automatic fallback.
    enemies = [key for key in options if key.startswith("redirect:")
               and engine.state.actors[key.split(":", 1)[1]].team_id != owner.team_id]
    preferred = (["rebound"] if "rebound" in options else enemies[:1]) or ["miss"]
    picked = ask(engine, intent, checkpoint_id(engine, "REFLECTING_GATE_T", owner.entity_id, actor.entity_id, target.entity_id), owner,
                 CHOICE + REFLECT, list(options), labels=options, preferred=preferred, automatic_options=["miss", *enemies, *(["rebound"] if "rebound" in options else [])], allow_decline=True, target_id=target.entity_id,
                 name="Reflecting Gate", feature_id="tianxia.talent.formations." + REFLECT,
                 prompt_context={"cost": "Reaction; 2 CP"},
                 prompt=f"Reflecting Gate (Reaction, 2 CP): {actor.display_name}'s {action.display_name} crosses into your array at {target.display_name}. Choose how to turn it aside.")
    if not picked:
        return None
    with activation(engine, owner, SOURCE_REFLECT):
        _pay(engine, owner, zone, 2, SOURCE_REFLECT, (actor.entity_id, target.entity_id))
        dc = int((typed.get("numbers") or {}).get("save_dc") or 10)
        if not F.formation_check(engine, owner, F.record(zone).get("numbers") or {}, dc, SOURCE_REFLECT, "Reflecting Gate against the Cultivation Save DC"):
            F.say(engine, SOURCE_REFLECT, owner.entity_id, f"Reflecting Gate: the Formation Check fails; {action.display_name} crosses the boundary.")
            return None
        choice = picked[0]
        reply = {"source_id": SOURCE_REFLECT, "label": options[choice]}
        if choice == "miss":
            return {**reply, "cancel": True, "spend_activation": True}
        return {**reply, "retarget_id": actor.entity_id if choice == "rebound" else choice.split(":", 1)[1],
                "retarget_kind": "ANY_CREATURE"}


# ------------------------------------------------------------------------------------------------ Nine Palaces Killing Array
def nine_palaces(ctx: Any, zone: Any, victim: Any) -> bool:
    """GM-managed until a normal-attack shared-d20 seam exists.

    Never roll, spend, target extra creatures or dispatch partial attacks here.
    Returning False preserves the ordinary Killing Line Pulse pipeline.
    """
    return False


# ------------------------------------------------------------------------------------------------ Mountain-Sealing Great Array
def _sealed(engine: Any, zone: Any, who: Any) -> bool:
    """Who the sealing rules touch: hostile creatures, and the owner unless she keyed herself ("You are also affected by the sealing rules
    unless you are keyed to the array")."""
    record = F.record(zone)
    if who.entity_id == zone.owner_id:
        return who.entity_id not in (record.get("keyed") or [])
    return F.hostile_to(engine, zone, who)


@hook("speed")
def mountain_suppresses_movement_boosts(engine: Any, actor: Any) -> int | None:
    """Mountain-Sealing Great Array: "ongoing non-Secret movement-enhancing effects are suppressed while their source remains inside".  An
    ongoing Speed increase on a creature the seal touches (a timed modifier some ability put on it) counts for nothing while the creature
    that made it stands inside the array."""
    mountains = [zone for zone in F.arrays(engine) if F.record(zone).get("domain") == "mountain"]
    if not mountains:
        return None
    taken = 0
    for zone in mountains:
        if not _sealed(engine, zone, actor):
            continue
        for modifier in actor.modifiers.values():
            source = engine.state.actors.get(modifier.source_actor_id or "")
            if modifier.target_field == "speed_ft" and modifier.operation == "ADD" and int(modifier.value) > 0 and not modifier.consumed \
                    and source is not None and F.inside(engine, source, zone):
                taken += int(modifier.value)
        break
    return -taken if taken else None


# ------------------------------------------------------------------------------------------------ Formation Devours Technique
# "Reaction. Trigger: A hostile technique, sphere effect, spell-like effect, or active Qi pattern crosses the boundary of one of your arrays.
# Cost: 3 CP. Make a Formation Check against the effect's save DC, or against 10 + the effect's ... CP cost ... Success: ... Choose one:
# reduce the effect's damage by 4d8; give keyed creatures inside Advantage on the saving throw against that effect; prevent the effect from
# crossing the boundary this turn; suppress one ongoing non-Secret effect until the start of your next turn if its source remains inside the
# array. At CL 17, the damage reduction becomes 6d8."  (CL 10.)
# How it runs: a hostile creature's technique (no weapon) that reaches a creature on the other side of an array's boundary from its user is
# answered as it starts (technique_start).  "Reduce" rolls the dice once and takes them off each damage packet the technique deals to a
# creature on the far side (damage_pending); "Advantage" gives the owner's keyed creatures inside Advantage on their saves against it (save);
# "prevent" excludes each reached creature across the boundary before any save or effect; other recipients are unchanged.  Suppressing another
# ongoing effect stays with the GM (no effect on this table can be suppressed by another).
# Array That Swallows the Attack (CL 15): after a successful "reduce", 3 more CP store what was prevented (at most 80, the most 10d8 can
# be); the owner's next Pulse of that array before the end of her next turn may release it: a Formation Attack roll against one hostile
# creature inside the array, the stored amount as damage of the caught technique's type on a hit.
DEVOURS, SWALLOW = "formation_devours_technique", "array_that_swallows_the_attack"
SOURCE_DEVOURS, SOURCE_SWALLOW = "formation:formation_devours_technique", "formation:array_that_swallows_the_attack"
CAUGHT = "_formation_devoured"   # engine attribute: {"source", "actor", "zone", "mode", "amount", "far", "prevented", "type"}


def _reached(engine: Any, actor: Any, action: Any, typed: dict[str, Any]) -> list[Any]:
    from ..typed_executor import _area_targets

    intent = _intent(engine)
    area = typed.get("area") or {}
    if area.get("size_ft"):
        aim = getattr(intent, "destination", None)
        return list(_area_targets(engine, actor, aim if aim is not None else actor.position, area, typed=typed))
    # Declaration redirects are activation-local and leave the accepted intent
    # untouched for replay. Use the final recipient contract for single-target
    # activations, including a rebound onto the caster.
    redirected = typed.get("_activation_redirect_recipient_id")
    target_ids = (redirected,) if redirected else (getattr(intent, "target_ids", None) or ())
    return [engine.state.actors[tid] for tid in target_ids if tid in engine.state.actors and tid != actor.entity_id]


def _damage_type(typed: dict[str, Any]) -> str:
    from ..typed_executor import _walk_rows

    for row in _walk_rows(typed.get("effects")):
        if row.get("type") == "damage" and row.get("damage_types"):
            return str(row["damage_types"][0]).lower()
    return "force"


@hook("technique_start")
def formation_devours(engine: Any, actor: Any, action: Any) -> bool | None:
    typed = (action.parameters or {}).get("typed") or {}
    if typed.get("weapon") is not None or (action.parameters or {}).get(F.TAG) or getattr(engine, "_formation_devouring", False):
        return None
    reached = _reached(engine, actor, action, typed)
    if not reached:
        return None
    for zone in F.arrays(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or owner.team_id == actor.team_id:
            continue
        user_inside = F.inside(engine, actor, zone)
        far = [row for row in reached if F.inside(engine, row, zone) != user_inside]
        if not far or _owner_ready(engine, zone, DEVOURS, 10, 3) is None:
            continue
        return _devour(engine, actor, action, typed, zone, owner, far, reached)
    return None


def _devour(engine: Any, actor: Any, action: Any, typed: dict[str, Any], zone: Any, owner: Any, far: list[Any], reached: list[Any]) -> bool | None:
    numbers = F.record(zone).get("numbers") or {}
    cl = int(numbers.get("cl") or 1)
    dice = 6 if cl >= 17 else 4
    has_damage = any(row.get("type") in ("damage", "half_damage") for row in _walk(typed.get("effects")))
    has_save = any(row.get("type") == "save" for row in _walk(typed.get("effects")))
    options = {}
    if has_damage:
        options["reduce"] = f"Formation Devours Technique: reduce its damage by {dice}d8"
    if has_save and any(F.keyed(engine, zone, row) and F.inside(engine, row, zone) for row in reached):
        options["advantage"] = "Formation Devours Technique: keyed creatures inside have Advantage on the save against it"
    if far:
        options["prevent"] = "Formation Devours Technique: it does not cross the boundary"
    if not options:
        return None
    preferred = ["prevent"] if "prevent" in options and any(owner.team_id == row.team_id for row in far) else \
        ["reduce"] if "reduce" in options else list(options)[:1]
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "FORMATION_DEVOURS", owner.entity_id, actor.entity_id), owner, CHOICE + DEVOURS,
                 list(options), labels=options, preferred=preferred, allow_decline=True, target_id=actor.entity_id,
                 name='Formation Devours Technique', feature_id='tianxia.talent.formations.' + DEVOURS,
                 prompt_context={'cost': 'Reaction; 3 CP',
                                 'paying_pool': str(numbers.get('formation_pool') or 'resource:core.qi')},
                 prompt=f"Formation Devours Technique (Reaction, 3 CP): {actor.display_name}'s {action.display_name} crosses your array's boundary.")
    if not picked or not any(owner.team_id == row.team_id or F.keyed(engine, zone, row) for row in far):
        return None
    with activation(engine, owner, SOURCE_DEVOURS):
        _pay(engine, owner, zone, 3, SOURCE_DEVOURS, (actor.entity_id,))
        tnumbers = typed.get("numbers") or {}
        dc = int(tnumbers.get("save_dc") or 10) if has_save else 10 + sum(int(amount) for _resource, amount in action.costs)
        if not F.formation_check(engine, owner, numbers, dc, SOURCE_DEVOURS, "Formation Devours Technique"):
            F.say(engine, SOURCE_DEVOURS, owner.entity_id, f"Formation Devours Technique: the check fails; {action.display_name} crosses the boundary.")
            return None
        choice = picked[0]
        F.say(engine, SOURCE_DEVOURS, owner.entity_id, options[choice].replace("Formation Devours Technique: ", "Formation Devours Technique: the array catches it; "))
        if choice == "prevent" and len(far) == len(reached):
            return True
        amount = 0
        if choice == "reduce":
            from ..gate2_runtime_models import DiceSpec

            rolled = engine.roller.roll(DiceSpec(count=dice, sides=8, modifier=0), actor_id=owner.entity_id, reason=f"DAMAGE_REDUCTION:{SOURCE_DEVOURS}")
            engine._record_roll(rolled)
            amount = int(rolled.total)
        engine.__dict__[CAUGHT] = {"source": action.source_definition_id, "actor": actor.entity_id, "zone": zone.zone_id, "mode": choice, "amount": amount,
                                   "far": [row.entity_id for row in far], "prevented": 0, "type": _damage_type(typed),
                                   "activation_intent": id(_intent(engine))}
        return None


def _walk(effects: Any):
    from ..typed_executor import _walk_rows

    return _walk_rows(effects)


@hook("effect_subject_allowed")
def devoured_recipient(ctx: Any, effect: dict[str, Any], subject: Any) -> bool | None:
    """A caught crossing is excluded before its save or any nested effect."""
    caught = ctx.engine.__dict__.get(CAUGHT)
    if (caught and caught["mode"] == "prevent" and caught["source"] == ctx.source
            and caught["actor"] == ctx.actor.entity_id and subject.entity_id in caught["far"]):
        return False
    return None


@hook("damage_pending")
def devoured_damage(engine: Any, target: Any, pending: int, source_definition_id: Any, source_actor_id: Any) -> int | None:
    caught = engine.__dict__.get(CAUGHT)
    if not caught or caught["mode"] != "reduce" or caught["source"] != source_definition_id or target.entity_id not in caught["far"]:
        return None
    from .attack_reduction import remember, used
    if used(engine, target, SOURCE_DEVOURS):
        return None
    taken = min(int(pending), int(caught["amount"]))
    caught["prevented"] = int(caught["prevented"]) + taken
    if taken:
        F.say(engine, SOURCE_DEVOURS, source_actor_id, f"Formation Devours Technique: {taken} of the damage to {target.display_name} is caught by the array.")
    return remember(engine, target, int(pending), int(pending) - taken,
                    [(int(caught['amount']), ())], feature=SOURCE_DEVOURS)


@hook('reaction_reduction_carried')
def devoured_carry(engine: Any, target: Any, feature: str, amount: int) -> None:
    caught = engine.__dict__.get(CAUGHT)
    if feature == SOURCE_DEVOURS and caught and target.entity_id in caught['far']:
        caught['prevented'] = int(caught['prevented']) + amount


@hook("save")
def devoured_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    caught = ctx.engine.__dict__.get(CAUGHT)
    if not caught or caught["mode"] != "advantage" or caught["source"] != ctx.source:
        return None
    zone = ctx.engine.state.zones.get(caught["zone"])
    if zone is None or not F.keyed(ctx.engine, zone, subject) or not F.inside(ctx.engine, subject, zone):
        return None
    return {"bonus": 0, "modes": ["ADVANTAGE"]}


@hook("technique_used")
def devoured_done(ctx: Any) -> None:
    """The technique has run: what the array caught may be stored (Array That Swallows the Attack)."""
    caught = ctx.engine.__dict__.pop(CAUGHT, None)
    if not caught or caught["source"] != ctx.source or caught["mode"] != "reduce" or not int(caught["prevented"]):
        return
    engine = ctx.engine
    zone = engine.state.zones.get(caught["zone"])
    if zone is None or not zone.active:
        return
    record = F.record(zone)
    numbers = record.get("numbers") or {}
    owner = engine.state.actors.get(zone.owner_id)
    pool = str(numbers.get("formation_pool") or "resource:core.qi")
    if owner is None or SWALLOW not in F.talents_of(numbers) or int(numbers.get("cl") or 1) < 15 or owner.resources.get(pool, 0) < 3:
        return
    amount = min(int(caught["prevented"]), 80)
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "FORMATION_SWALLOW", owner.entity_id), owner, CHOICE + SWALLOW, ["store"],
                 labels={"store": f"Array That Swallows the Attack: spend 3 CP to store {amount} caught damage"}, allow_decline=True, target_id=owner.entity_id,
                 prompt="Array That Swallows the Attack: store the caught force in the array?")
    if not picked:
        return
    with activation(engine, owner, SOURCE_SWALLOW):
        engine._spend_resource(owner, pool, 3, SOURCE_SWALLOW)
        turns = 2 if engine.state.current_actor_id == owner.entity_id else 1  # "before the end of your next turn"
        F.save_zone(engine, zone, SOURCE_SWALLOW, {**record, "stored": {"amount": amount, "type": caught["type"], "turns": turns}})
        F.say(engine, SOURCE_SWALLOW, owner.entity_id, f"Array That Swallows the Attack: {amount} {caught['type']} damage is stored in the array until the end of your next turn.")


@hook("activation_end")
def devoured_activation_end(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    """Retire this activation's transient boundary policy even if it was countered or interrupted."""
    caught = engine.__dict__.get(CAUGHT)
    if (caught and caught.get("source") == action.source_definition_id
            and caught.get("actor") == actor.entity_id
            and caught.get("activation_intent") == id(intent)):
        engine.__dict__.pop(CAUGHT, None)


def release_stored(ctx: Any, zone: Any) -> None:
    """Called by formations.formation_pulse after a Pulse of ``zone``: its stored force may be released on one hostile creature inside."""
    engine, actor = ctx.engine, ctx.actor
    record = F.record(zone)
    stored = record.get("stored")
    if not stored or zone.owner_id != actor.entity_id:
        return
    foes = [row for row in engine.state.actors.values() if row.active and F.hostile_to(engine, zone, row) and F.inside(engine, row, zone)]
    if not foes:
        return
    labels = {row.entity_id: f"Array That Swallows the Attack: release {stored['amount']} damage at {row.display_name}" for row in foes}
    victim = ctx.target if ctx.target is not None and ctx.target.entity_id in labels else None
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "FORMATION_RELEASE", actor.entity_id), actor, CHOICE + SWALLOW + ".release", list(labels),
                 labels=labels, preferred=[victim.entity_id] if victim is not None else [foes[0].entity_id], allow_decline=True,
                 prompt="Release the force stored in the array?")
    target = next((row for row in foes if picked and row.entity_id == picked[0]), None)
    if target is None:
        return
    F.save_zone(engine, zone, SOURCE_SWALLOW, {**record, "stored": None})
    numbers = record.get("numbers") or {}
    roll = engine.roller.d20(modifier=int(numbers.get("attack_bonus") or 0), actor_id=actor.entity_id, reason=f"ATTACK:{SOURCE_SWALLOW}",
                             mode=engine._attack_mode(actor, target))
    engine._record_roll(roll)
    ac = target.armor_class + engine._ac_modifier(target)
    natural = int(roll.natural_result or 0)
    hit = natural != 1 and (natural == 20 or int(roll.total) >= ac)
    engine._append_event("ATTACK_ROLLED", SOURCE_SWALLOW, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={
        **roll.model_dump(mode="json"), "modified_total": int(roll.total), "target_ac": ac, "cover_bonus": 0, "provisional_hit": hit})
    if not hit:
        F.say(engine, SOURCE_SWALLOW, actor.entity_id, f"Array That Swallows the Attack: the released force misses {target.display_name} and dissipates.")
        return
    from ..typed_executor import run_effects

    run_effects(dataclasses.replace(ctx, target=target, targets=[target]),
                [{"type": "damage", "flat": int(stored["amount"]), "formula": "none", "damage_types": [str(stored.get("type") or "force")],
                  "applies_to": "target", "evidence": "Array That Swallows the Attack: damage equal to the amount prevented or reduced, maximum 10d8"}])


@hook("turn_end")
def stored_force_fades(engine: Any, actor: Any) -> None:
    for zone in F.arrays(engine, actor.entity_id):
        stored = F.record(zone).get("stored")
        if not stored:
            continue
        left = int(stored.get("turns") or 1) - 1
        F.save_zone(engine, zone, SOURCE_SWALLOW, {**F.record(zone), "stored": {**stored, "turns": left} if left > 0 else None})
        if left <= 0:
            F.say(engine, SOURCE_SWALLOW, actor.entity_id, "Array That Swallows the Attack: the stored force dissipates harmlessly.")
