"""Sumo riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Sumo (Rooted Stance, Sumo Strike, Ring Breaker, Yokozuna Presence, Immovable God and
their Normalized Procedures). Rooted Stance is the stance condition ``condition:typed.stance.rooted_stance`` (its ending on
movement and Unconscious: combat/ext/docket_terrain.py; Yokozuna Presence's aura: docket_terrain's aura block). Owned row:
``{"type": "path_passive", "kind": "sumo", "role": "immovable"}``. Sumo Strike is a path_riders ``paid_hit`` row running
``sumo_push``; Ring Breaker's action runs ``ring_breaker_push`` and ``ring_breaker_step_in``; ``sumo_mark`` names the
activation whose pushes collide.

Rooted Stance      Advantage on checks to escape a grapple (hook escape_mode); counts one size larger when grappling or shoving
                   and when resisting forced movement (hook size_steps); forced movement on it is 5 feet shorter, once per
                   movement (hook forced_distance).
Immovable God      always Rooted while conscious (entered at the start of its turns and again whenever it ends, no Bonus
                   Action); two more sizes larger for the same things; forced movement from a lower Source CL (a typed
                   fighter's CL, any other creature 0) does not move it, nor does a lower-CL effect knock it Prone (hook
                   condition_attempt); from an equal or higher one, an opposed Cultivation Check (d20 + Proficiency Bonus + key
                   modifier each; a tie leaves it where it is); once during each of its turns, after 10+ feet of willing
                   movement, an asked unarmed strike (a Granted Attack) against a creature that came within its reach during
                   the movement.
Sumo Strike        push 10 feet, or, against a creature more than one size larger, a Strength save: 10 feet or 5; a collision
                   deals 1d6 Bludgeoning (2d6 at CL11, 3d6 at CL17) to the target and to what it hit: a map object, or a
                   creature that fails a Dexterity save.
Ring Breaker       failure: pushed up to 20 feet (you choose how far), Prone, and you may step into its former space;
                   success: pushed 5 feet, and you may step in if it left. A collision with a solid surface deals 3d8
                   Bludgeoning to the target; with a creature, that creature makes a Dexterity save: 3d8 and Prone, or half.
Every hook returns early for a creature without the stance, row or marker.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.sumo.feature."
ROOTED = "condition:typed.stance.rooted_stance"


def _rooted(actor: Any) -> bool:
    return actor is not None and any(c.condition_id == ROOTED for c in actor.conditions.values())


def _immovable(engine: Any, actor: Any) -> bool:
    from ..sumo_state import owns, touching, conscious
    from .surface_contact import solid_contact
    return owns(engine, actor, 'immovable_god') and conscious(actor) and touching(engine, actor) and solid_contact(engine,actor)


def _cl(engine: Any, actor_id: str) -> int:
    """A fighter's Source CL: a typed fighter's CL; anything else is mundane (0)."""
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor_id), None)
    return int((bundle or {}).get("cl") or 0)


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _conscious(actor: Any) -> bool:
    return actor.active and not any(c.condition_id == "condition:typed.unconscious" for c in actor.conditions.values())


# ------------------------------------------------------------------------------------------------------ Rooted Stance
@hook("escape_mode")
def rooted_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if _rooted(escaper) else None  # "Advantage on checks ... against Grapples"


@hook("size_steps")
def rooted_size(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    """"Count as one size larger for Grappling, Shoving ... and resisting forced movement" (Immovable God: two more)."""
    from ..sumo_state import rooted
    named=set(purposes)
    steps=1 if rooted(engine,creature) and named & {'grapple','shove','carrying','lifting','forced','prone'} else 0
    extra=2 if _immovable(engine,creature) and named & {'grapple','shove','carrying','forced'} else 0
    if role=='act' and named & {'forced','prone'} and not named & {'grapple','shove'}:return None
    return {'steps':steps,'additional':extra} if steps or extra else None


def _opposed(engine: Any, mover: Any, source: Any) -> bool:
    from .cultivation_contests import holds_position
    return holds_position(engine, mover, source, PREFIX + "immovable_god")


@hook("forced_distance")
def rooted_forced(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    if mover is None:
        return None
    from ..sumo_state import rooted
    return 5 if rooted(engine, mover) else None  # "Reduce forced movement affecting you by 5 feet"


@hook("condition_attempt")
def immovable_prone(ctx: Any, subject: Any, effect: Any) -> bool | None:
    """An effect whose Source CL is lower than yours cannot knock you Prone."""
    if str((effect or {}).get("condition") or "").lower() != "prone" or subject is None or not _immovable(ctx.engine, subject):
        return None
    if ctx.actor is subject or int(ctx.numbers.get("cl") or 0) >= _cl(ctx.engine, subject.entity_id):
        return None
    return False


def _enter(engine: Any, actor: Any) -> None:
    """Immovable God: enter Rooted Stance without an action (the stance's own effects, as its button runs them)."""
    from ..sumo_state import touching, DECLINED
    if _rooted(actor) or not _conscious(actor) or not touching(engine, actor) or any(c.condition_id == DECLINED for c in actor.conditions.values()):
        return
    action = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                   and ((a.parameters or {}).get("typed") or {}).get("source") == PREFIX + "rooted_stance"), None)
    if action is None:
        return
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    ctx = te.Context(engine, actor, action, getattr(engine, "_active_intent", None), typed, [actor], actor, {})
    te.run_effects(ctx, [e for e in typed.get("effects") or [] if e.get("type") == "sumo_root"])


@hook("turn_start")
def immovable_rooted(engine: Any, actor: Any) -> None:
    if _immovable(engine, actor):
        _enter(engine, actor)


@hook("event")
def immovable_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The stance comes back as soon as it can (Rooted Stance's own ending on movement is docket_terrain.py's event hook, which
    runs first in this same dispatch; a removal made inside an event hook is not itself dispatched), and the strike after moving."""
    if event_type == "HEALING_APPLIED":
        actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if actor is not None and _immovable(engine, actor):
            _enter(engine, actor)  # conscious again: "it automatically resumes when the conditions are again met"
        return
    if event_type != "MOVEMENT_COMMITTED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or not _immovable(engine, actor) or not actor.active:
        return
    _enter(engine, actor)
    payload = kwargs.get("payload") or {}
    if payload.get("forced") or payload.get("teleport") or payload.get("dragged_by") or engine.state.current_actor_id != actor.entity_id:
        return
    stamp = _stamp(engine)
    path = payload.get("path") or []
    moved = max(0, len(path) - 1) * engine.grid.square_size_ft
    record = actor.turn_flags.get("_round_immovable_moved") or {}
    total = (int(record.get("ft") or 0) if record.get("stamp") == stamp else 0) + moved
    actor.turn_flags["_round_immovable_moved"] = {"stamp": stamp, "ft": total}
    if total < 10 or actor.turn_flags.get("_round_immovable_strike") == stamp or len(path) < 2:
        return
    _entered_strike(engine, actor, path)


def _unarmed_strike(engine: Any, actor: Any) -> Any:
    for action in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id == actor.entity_id and ".natural." in action.source_definition_id and "#" not in action.source_definition_id \
                and not (action.parameters or {}).get("player_only") and any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                                                            for e in typed.get("effects") or []):
            return action
    return None


def _entered_strike(engine: Any, actor: Any, path: Any) -> None:
    """"make one unarmed strike against one creature that entered your reach during that movement" (Granted Attack)."""
    from ..gate2_runtime_models import Position
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    action = _unarmed_strike(engine, actor)
    if action is None:
        return
    reach = int(action.range_ft or 5)
    points = [Position.model_validate(p) if isinstance(p, dict) else p for p in path]
    before = engine._actor_cells(actor, points[0])
    foes = {c.entity_id: c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.team_id != actor.team_id
            and engine._distance_actor_to_actor(actor, c) <= reach and engine._line_of_sight_actor_to_actor(actor, c)
            and engine.grid.distance_between_cell_sets(before, engine._actor_cells(c)) * engine.grid.square_size_ft > reach
            and any(engine.grid.distance_between_cell_sets(engine._actor_cells(actor,p), engine._actor_cells(c)) * engine.grid.square_size_ft <= reach for p in points[1:])}
    if not foes:
        return
    intent = getattr(engine, "_active_intent", None)
    actor.turn_flags["_round_immovable_strike"] = _stamp(engine)  # asked once a turn: a declined strike is not offered again
    picked = ask(engine, intent, checkpoint_id(engine, "immovable_god", actor.entity_id), actor, "choice:needle.immovable_god", list(foes),
                 labels={k: c.display_name for k, c in foes.items()}, allow_decline=True, target_id=actor.entity_id, name="Immovable God",
                 prompt="Immovable God: make an unarmed strike against a creature that came within your reach?")
    if not picked or picked[0] not in foes:
        return
    foe = foes[picked[0]]
    typed = (action.parameters or {}).get("typed") or {}
    attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return
    attack.update(count=1, granted_attack_root=True)
    te.run_effects(te.Context(engine, actor, action, intent, {**typed, "effects": [attack], "granted_attack": True}, [foe], foe, {}), [attack])


# ------------------------------------------------------------------------------------------ Sumo Strike and Ring Breaker
@effect("sumo_mark")
def sumo_mark(ctx: Any, row: dict[str, Any]) -> None:
    ctx.damage_cache["_sumo"] = str(row.get("feature") or "")


@effect("sumo_push")
def sumo_push(ctx: Any, row: dict[str, Any]) -> None:
    """Sumo Strike: "Push the target 10 feet. If the target is more than one size larger than you, it makes a Strength saving
    throw. On a failure, push it 10 feet; on a success, 5 feet."."""
    from .. import typed_executor as te

    target = ctx.target
    if target is None or not target.active:
        return
    push = lambda ft: {"type": "forced_movement", "applies_to": "target", "distance_ft": ft, "direction": "away"}
    from .effective_size import rank
    if rank(ctx.engine, target, "resist", set()) > rank(ctx.engine, ctx.actor, "act", set()) + 1:
        te.run_effects(ctx, [{"type": "save", "ability": "str", "evidence": "Sumo Strike: Strength saving throw", "on_fail": [push(10)], "on_success": [push(5)]}])
    else:
        te.run_effects(ctx, [push(10)])


@effect("ring_breaker_push")
def ring_breaker_push(ctx: Any, row: dict[str, Any]) -> None:
    """"push the target up to 20 feet": you choose how far along the line away from you."""
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    target = ctx.target
    if target is None or not target.active:
        return
    most = int(row.get("up_to") or 5)
    square = ctx.engine.grid.square_size_ft
    options = [str(ft) for ft in range(most, -1, -square)] if most > 5 else [str(most)]
    feet = most
    if len(options) > 1:
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "ring_breaker", target.entity_id), ctx.actor, "choice:needle.ring_breaker_distance",
                     options, labels={o: f"Push it {o} feet" for o in options}, target_id=target.entity_id, name="Ring Breaker",
                     prompt=f"Ring Breaker: how far do you push {target.display_name} (up to {most} feet)?")
        feet = int(picked[0]) if picked and picked[0] in options else most
    ctx.damage_cache["_ring_breaker_from"] = (target.position.x, target.position.y)
    te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": feet, "direction": "away"}])


@effect("ring_breaker_step_in")
def ring_breaker_step_in(ctx: Any, row: dict[str, Any]) -> None:
    """"you may enter its former space" (only if it actually left, and the space is legal for you)."""
    from ..gate2_runtime_models import Position
    from .needle import ask, checkpoint_id
    from .rider_movement import step

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    spot = ctx.damage_cache.get("_ring_breaker_from")
    if spot is None or target is None or not actor.active:
        return
    former = Position(x=spot[0], y=spot[1])
    start = actor.position
    if target.position == former or not engine.grid.placement_legal(former, footprint=engine._footprint(actor), occupied_cells=engine._occupied_cells_except(actor.entity_id)):
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "ring_breaker_step", actor.entity_id), actor, "choice:needle.ring_breaker_step", ["enter"],
                 labels={"enter": f"Step into {former.x},{former.y}"}, allow_decline=True, default="decline", target_id=actor.entity_id, name="Ring Breaker",
                 prompt="Ring Breaker: step into the space it was driven from?")
    if not picked:
        return
    engine._resolve_leave_reach(actor, start, former, ctx.intent)  # an ordinary step: it can provoke
    if actor.active and actor.position == start:
        step(engine, actor, [start, former], PREFIX + "ring_breaker")


@hook("collision")
def sumo_collision(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    kind = ctx.damage_cache.get("_sumo")
    if kind not in ("sumo_strike", "ring_breaker") or target is None or not target.active:
        return
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    done = ctx.damage_cache.setdefault("_sumo_collided", [])
    spot = (blocked_at.x, blocked_at.y)
    other = next((c for c in engine.state.actors.values() if c.active and c.entity_id != target.entity_id and spot in engine._actor_cells(c)), None)
    cl = _cl(engine, actor.entity_id)
    dice = {"count": 3, "sides": 8} if kind == "ring_breaker" else {"count": 3 if cl >= 17 else 2 if cl >= 11 else 1, "sides": 6}
    name = "Ring Breaker" if kind == "ring_breaker" else "Sumo Strike"
    hurt = {"type": "damage", "applies_to": "target", "dice": dice, "damage_types": ["bludgeoning"], "evidence": f"{name}: collision"}

    def hit(creature: Any, rows: list[dict[str, Any]]) -> None:
        if creature.active and creature.entity_id not in done:
            done.append(creature.entity_id)
            te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [creature], creature, {}), rows)

    if other is None:
        from .objects import blocker_at
        obj = blocker_at(engine, blocked_at)
        if obj is None and not engine.grid.terrain_at((blocked_at.x,blocked_at.y,blocked_at.z), 'BLOCKED'):
            return
        note(engine, PREFIX + kind, actor, f"{name}: {target.display_name} slams into a solid surface.", (target.entity_id,))
        hit(target, [hurt])
        from .objects import blocker_at
        obj = blocker_at(engine, blocked_at)  # the object that stopped it, not one sharing its square
        if obj is not None and kind == "sumo_strike":  # Sumo Strike: "both take" -- the map object it hit as well
            from ..gate2_runtime_models import DiceSpec
            from .objects import deal

            roll = engine.roller.roll(DiceSpec(count=dice["count"], sides=dice["sides"], modifier=0), actor_id=actor.entity_id, reason=f"DAMAGE:{PREFIX}{kind}:object")
            engine._record_roll(roll)
            deal(engine, actor, obj, [(int(roll.total), "BLUDGEONING")], PREFIX + kind)
        return
    note(engine, PREFIX + kind, actor, f"{name}: {target.display_name} is driven into {other.display_name}.", (target.entity_id, other.entity_id))
    if kind == "ring_breaker":
        hit(other, [{"type": "save", "ability": "dex", "evidence": "Ring Breaker: the second creature's Dexterity saving throw",
                     "on_fail": [hurt, {"type": "condition", "applies_to": "target", "condition": "prone"}],
                     "on_success": [{"type": "half_damage", "applies_to": "target", "damage_types": ["bludgeoning"]}]}])
        return
    hit(target, [hurt])
    hit(other, [{"type": "save", "ability": "dex", "evidence": "Sumo Strike: the second creature's Dexterity saving throw", "on_fail": [hurt], "on_success": []}])


@effect('sumo_root')
def enter_root(ctx: Any, row: dict[str, Any]) -> None:
    from ..sumo_state import touching, owns, DECLINED
    if not owns(ctx.engine,ctx.actor,'rooted_stance') or not touching(ctx.engine,ctx.actor) or not _conscious(ctx.actor):
        return
    ctx.engine._remove_condition(ctx.actor, DECLINED, ctx.source)
    ctx.engine._remove_condition(ctx.actor, ROOTED, ctx.source)
    ctx.engine._apply_condition(ctx.actor,ROOTED,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
        data={'label':'Rooted Stance','source_cl':_cl(ctx.engine,ctx.actor.entity_id)})


@hook('forced_movement_restriction')
def immovable_motion(ctx: Any, subject: Any, row: dict[str, Any], distance: int) -> int | None:
    if not _immovable(ctx.engine,subject) or subject is ctx.actor:
        return None
    if int(ctx.numbers.get('cl') or 0) < _cl(ctx.engine,subject.entity_id) or _opposed(ctx.engine,subject,ctx.actor):
        return 0
    return None


@hook('unwilling_teleport_attempt')
def immovable_teleport(ctx: Any, subject: Any, previous: Any, destination: Any) -> bool | None:
    if not _immovable(ctx.engine,subject):
        return None
    if int(ctx.numbers.get('cl') or 0) < _cl(ctx.engine,subject.entity_id) or _opposed(ctx.engine,subject,ctx.actor):
        return False
    return None


@hook('committed_teleport_receipt')
def rooted_teleport(engine: Any, receipt: dict[str, Any]) -> None:
    if not receipt['willing']:
        return
    actor=engine.state.actors.get(receipt['actor_id'])
    if actor is not None and _rooted(actor):
        engine._remove_condition(actor,ROOTED,PREFIX+'rooted_stance')
        if _immovable(engine,actor):
            _enter(engine,actor)


@hook('contest_mode')
def rooted_contest(engine: Any, actor: Any, role: str, purpose: str, other: Any) -> str | None:
    from ..sumo_state import rooted
    return 'ADVANTAGE' if rooted(engine,actor) and role=='resist' and purpose in ('grapple','shove','forced','prone') else None


@hook('save')
def rooted_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    from ..sumo_state import rooted
    if rooted(ctx.engine,subject) and set(named or ()) & {'grappled','grapple','shove','forced_movement','prone','unwilling_teleport'}:
        return {'bonus':0,'modes':['ADVANTAGE']}
    return None


@hook('contest_check_mode')
def rooted_check(ctx: Any, subject: Any, opponent: Any, spec: dict[str, Any]) -> str | None:
    from ..sumo_state import rooted
    if rooted(ctx.engine,subject) and set(spec.get('hazards') or ()) & {'grapple','shove','forced_movement','prone','unwilling_teleport'}:
        return 'ADVANTAGE'
    return None


@hook('event')
def rooted_state_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ('MOVEMENT_COMMITTED','CONDITION_APPLIED','CONDITION_REMOVED'):
        return
    from ..sumo_state import touching
    actor=engine.state.actors.get(kwargs.get('actor_id') or '') if event_type=='MOVEMENT_COMMITTED' else engine.state.actors.get(next(iter(kwargs.get('target_ids') or ()),''))
    if actor is None or not _rooted(actor):
        return
    payload=kwargs.get('payload') or {}
    if not _conscious(actor) or not touching(engine,actor):
        engine._remove_condition(actor,ROOTED,PREFIX+'rooted_stance')
        return
    if event_type!='MOVEMENT_COMMITTED' or payload.get('teleport') or any(payload.get(k) for k in ('forced','dragged_by','carried_by','mounting','dismounting')):
        return
    from ..typed_executor import condition_rules
    if engine.state.current_actor_id!=actor.entity_id or any(r.get('no_actions') for r in condition_rules(actor)):
        return
    stamp=_stamp(engine)
    record=actor.turn_flags.get('_round_sumo_willing') or {}
    total=(int(record.get('ft') or 0) if record.get('stamp')==stamp else 0)+max(0,len(payload.get('path') or ())-1)*engine.grid.square_size_ft
    actor.turn_flags['_round_sumo_willing']={'stamp':stamp,'ft':total}
    if total>engine._effective_speed(actor)//2 and not _immovable(engine,actor):
        engine._remove_condition(actor,ROOTED,PREFIX+'rooted_stance')


@hook('match_initialize')
def initial_root(engine: Any) -> None:
    for actor in engine.state.actors.values():
        if _immovable(engine,actor):
            _enter(engine,actor)


@hook('compile_actions')
def stance_controls(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    if PREFIX+'rooted_stance' not in info['owned_ids']:
        return None
    out=[]
    for operation,label in (('end','End Rooted Stance (free; remain unrooted)'),('resume','Resume automatic Rooted Stance (free)')):
        out.append(ActionDefinition(source_definition_id='action:typed.'+info['actor_id']+'.sumo.'+operation,
            display_name=label,owner_id=info['actor_id'],economy=EconomyKind.NONE,resolution_kind='TYPED',target_kind='SELF',
            parameters={'free_primary':True,'sumo_control':operation,'typed':{'source':PREFIX+'rooted_stance','numbers':info['numbers'],
                'effects':[{'type':'sumo_control','operation':operation}],'riders':[],'duration':{'kind':'instant'}}}))
    return out


@effect('sumo_control')
def control_stance(ctx: Any, row: dict[str, Any]) -> None:
    from ..sumo_state import DECLINED,owns
    if not owns(ctx.engine,ctx.actor,'rooted_stance'):
        return
    if row['operation']=='end':
        ctx.engine._apply_condition(ctx.actor,DECLINED,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',data={'label':'Automatic rooting declined'})
        ctx.engine._remove_condition(ctx.actor,ROOTED,ctx.source)
    else:
        ctx.engine._remove_condition(ctx.actor,DECLINED,ctx.source)
        _enter(ctx.engine,ctx.actor)


@hook('candidate_allowed')
def sumo_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from ..sumo_state import owns,touching,DECLINED
    typed=(action.parameters or {}).get('typed') or {}
    source=str(typed.get('option_of') or typed.get('source') or '')
    if not source.startswith(PREFIX):return None
    slug=source.removeprefix(PREFIX)
    if slug not in ('rooted_stance','ring_breaker','yokozuna_presence'):return None
    if not owns(engine,actor,slug):return False
    operation=(action.parameters or {}).get('sumo_control')
    if operation=='end':return None if _rooted(actor) else False
    if operation=='resume':return None if _immovable(engine,actor) and any(c.condition_id==DECLINED for c in actor.conditions.values()) else False
    if slug=='rooted_stance':return None if touching(engine,actor) else False
    if slug=='ring_breaker':
        target=engine.state.actors.get(next(iter(candidate.target_ids or ()),''))
        strike=_unarmed_strike(engine,actor)
        return None if target is not None and strike is not None and engine._distance_actor_to_actor(actor,target)<=int(strike.range_ft or 5) else False
    return None


@hook('compile_action')
def sumo_reach(action: Any, info: dict[str, Any]) -> Any:
    if ((action.parameters or {}).get('typed') or {}).get('source')==PREFIX+'ring_breaker':
        # Candidate gate uses the live unarmed reach; the compiler must not
        # truncate its candidates to the parser's unknown "special" range.
        return action.model_copy(update={'range_ft':600})
    return None


@hook('pass_through')
def yokozuna_passage(engine: Any, mover: Any, occupant: Any) -> str | None:
    from ..sumo_state import owns,rooted
    from .effective_size import rank
    if owns(engine,occupant,'yokozuna_presence') and rooted(engine,occupant) and rank(engine,mover,'act',set())>=rank(engine,occupant,'resist',set())+2:
        return 'difficult'
    return None
