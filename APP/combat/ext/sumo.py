"""Sumo riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Sumo (Rooted Stance, Sumo Strike, Ring Breaker, Yokozuna Presence, Immovable God and
their Normalized Procedures). Rooted Stance is the stance condition ``condition:typed.stance.rooted_stance`` (its ending on
movement and Unconscious: this provider; Yokozuna Presence's aura: docket_terrain's aura block). Owned row:
``{"type": "path_passive", "kind": "sumo", "role": "immovable"}``. Sumo Strike is a path_riders ``paid_hit`` row running
``sumo_push``; Ring Breaker's action runs ``ring_breaker_push`` and ``ring_breaker_step_in``; ``sumo_mark`` names the
activation whose pushes collide.

Rooted Stance      Advantage on checks to escape a grapple (hook escape_mode); counts one size larger when grappling or shoving
                   and when resisting forced movement (hook size_steps); forced movement on it is 5 feet shorter, once per
                   movement (hook forced_distance).
Immovable God      always Rooted while conscious (entered at the start of its turns and again whenever it ends, no Bonus
                   Action); two more sizes larger for the same things; forced movement from a lower Source CL (a typed
                   effect's committed source numbers) does not move it, nor does a lower-CL effect knock it Prone (hook
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
from contextvars import ContextVar

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.sumo.feature."
ROOTED = "condition:typed.stance.rooted_stance"
_CAPACITY_REFRESH = ContextVar('sumo_capacity_refresh',default=frozenset())
_ROOT_REFRESH = ContextVar("sumo_root_refresh",default=frozenset())


def _rooted(actor: Any) -> bool:
    return actor is not None and any(c.condition_id == ROOTED for c in actor.conditions.values())


def _immovable(engine: Any, actor: Any) -> bool:
    from ..sumo_state import owns, touching, conscious
    from .surface_contact import solid_contact
    return owns(engine, actor, 'immovable_god') and touching(engine, actor) and solid_contact(engine,actor)


def _cl(engine: Any, actor_id: str) -> int:
    """Current effective Body CL; created effects keep their own source numbers."""
    from ..sumo_state import level
    actor=engine.state.actors.get(actor_id)
    return level(engine,actor) if actor is not None else 0


def _stamp(engine: Any) -> str:
    return f"{engine.state.current_actor_id}:{engine.state.actors[engine.state.current_actor_id].turns_started}"


def _conscious(actor: Any) -> bool:
    from ..sumo_state import conscious
    return conscious(actor)


# ------------------------------------------------------------------------------------------------------ Rooted Stance
@hook("escape_mode")
def rooted_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    from ..sumo_state import rooted
    return "ADVANTAGE" if rooted(engine,escaper) else None  # "Advantage on checks ... against Grapples"


@hook("size_steps")
def rooted_size(engine: Any, creature: Any, role: str, purposes: Any) -> dict[str, int] | None:
    """"Count as one size larger for Grappling, Shoving ... and resisting forced movement" (Immovable God: two more)."""
    from ..sumo_state import rooted
    named=set(purposes)
    # Generic legacy save outcomes also contain "shove" for a push/Prone.
    # Those outcomes are not themselves the Shove operation on the acting side.
    shove='brutal_shove' in named or ('shove' in named and not named & {'forced','prone'})
    common=bool(named & {'grapple','carrying'}) or shove or ('forced' in named and role!='act')
    steps=1 if rooted(engine,creature) and (common or 'lifting' in named) else 0
    extra=2 if _immovable(engine,creature) and common else 0
    return {'minimum':steps,'additional':extra} if steps or extra else None


def _opposed(engine: Any, mover: Any, source: Any, *, hazards=('forced_movement',), source_numbers=None) -> bool:
    from .cultivation_contests import holds_position
    return holds_position(engine, mover, source, PREFIX + "immovable_god",hazards=hazards,source_numbers=source_numbers)


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
    if type(ctx.numbers.get("cl")) is not int or ctx.numbers["cl"] >= _cl(ctx.engine, subject.entity_id):
        return None
    return False


def _enter(engine: Any, actor: Any) -> None:
    """Immovable God: enter Rooted Stance without an action (the stance's own effects, as its button runs them)."""
    from ..sumo_state import touching, DECLINED
    if (id(engine),actor.entity_id) in _ROOT_REFRESH.get() or _rooted(actor) or not _conscious(actor) or not touching(engine, actor) or any(c.condition_id == DECLINED for c in actor.conditions.values()):
        return
    action = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                   and ((a.parameters or {}).get("typed") or {}).get("source") == PREFIX + "rooted_stance"
                   and any(e.get('type') in ('sumo_root','stance') for e in ((a.parameters or {}).get('typed') or {}).get('effects',[]))), None)
    if action is None:
        return
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    ctx = te.Context(engine, actor, action, getattr(engine, "_active_intent", None), typed, [actor], actor, {})
    enter_root(ctx,{})


@hook("turn_start")
def immovable_rooted(engine: Any, actor: Any) -> None:
    if _immovable(engine, actor):
        _enter(engine, actor)


@hook("event",priority=20)
def immovable_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Automatic rooting observes committed contact/consciousness changes; the
    separate strike observes actual own-turn voluntary movement."""
    if event_type in ("HEALING_APPLIED","CONDITION_REMOVED","CONDITION_APPLIED"):
        actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
        if actor is not None and _immovable(engine, actor):
            _enter(engine, actor)  # conscious again: "it automatically resumes when the conditions are again met"
        return
    if event_type != "MOVEMENT_COMMITTED":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    from ..sumo_state import owns
    if actor is None or not owns(engine,actor,'immovable_god') or not actor.active:
        return
    _enter(engine, actor)
    payload = kwargs.get("payload") or {}
    if payload.get("forced") or payload.get("teleport") or payload.get("dragged_by") or engine.state.current_actor_id != actor.entity_id:
        return
    from ..typed_executor import condition_rules
    if any(r.get("no_actions") for r in condition_rules(actor)):
        return
    stamp = _stamp(engine)
    path = payload.get("path") or []
    if _willing_total(engine,actor)<10 or actor.turn_flags.get("_round_immovable_strike")==stamp or len(path)<2:return
    scope=engine.movement_scope(actor.entity_id,include_episode=True) or {}
    episode=scope.get('episode_id') if scope.get('source_id')==kwargs.get('source_definition_id') else None
    entries=(actor.turn_flags.get('_round_sumo_entries') or {}).pop(episode,None) if episode else None
    _entered_strike(engine,actor,path,entries)



def _unarmed_strike(engine: Any, actor: Any) -> Any:
    for action in sorted(engine.action_catalog.values(), key=lambda a: a.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id == actor.entity_id and ".natural." in action.source_definition_id and "#" not in action.source_definition_id \
                and not (action.parameters or {}).get("player_only") and any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                                                            for e in typed.get("effects") or []):
            return action
    return None


def _entered_strike(engine: Any, actor: Any, path: Any, entries=None) -> None:
    """"make one unarmed strike against one creature that entered your reach during that movement" (Granted Attack)."""
    from ..gate2_runtime_models import Position
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    action = _unarmed_strike(engine, actor)
    if action is None:
        return
    from ..attack_reach import maximum
    from ..target_knowledge import knowledge
    reach = int(maximum(engine,actor,action) or 5)
    points = [Position.model_validate(p) if isinstance(p, dict) else p for p in path]
    before = engine._actor_cells(actor, points[0])
    foes = {c.entity_id: c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.entity_id != actor.entity_id
            and engine._distance_actor_to_actor(actor, c) <= reach and engine._line_of_sight_actor_to_actor(actor, c)
            and (known:=knowledge(engine,actor,c,action)) is not None and known.mode=='DIRECT'
            and ((c.entity_id in entries) if entries is not None else any(
                engine.grid.distance_between_cell_sets(engine._actor_cells(actor,a),engine._actor_cells(c))*engine.grid.square_size_ft>reach and
                engine.grid.distance_between_cell_sets(engine._actor_cells(actor,b),engine._actor_cells(c))*engine.grid.square_size_ft<=reach
                for a,b in zip(points,points[1:])))}
    if not foes:
        return
    intent = getattr(engine, "_active_intent", None)
    picked = ask(engine, intent, checkpoint_id(engine, "immovable_god", actor.entity_id), actor, "choice:needle.immovable_god", list(foes),
                 labels={k: c.display_name for k, c in foes.items()}, allow_decline=True, target_id=actor.entity_id, name="Immovable God",
                 prompt="Immovable God: make an unarmed strike against a creature that came within your reach?")
    if not picked or picked[0] not in foes:
        return
    actor.turn_flags["_round_immovable_strike"] = _stamp(engine)
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
    from ..sumo_state import owns,level
    slug=str(row.get('feature') or '')
    if slug not in ('sumo_strike','ring_breaker') or not owns(ctx.engine,ctx.actor,slug):return
    ctx.typed={**ctx.typed,'numbers':{**ctx.numbers,'cl':level(ctx.engine,ctx.actor)}}
    ctx.damage_cache["_sumo"] = slug


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
    ctx.damage_cache["_ring_breaker_from"] = (target.position.x, target.position.y, target.position.z)
    te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": feet, "direction": "away"}])


@effect("ring_breaker_step_in")
def ring_breaker_step_in(ctx: Any, row: dict[str, Any]) -> None:
    """"you may enter its former space" (only if it actually left, and the space is legal for you)."""
    from ..gate2_runtime_models import Position
    from .needle import ask, checkpoint_id
    from ..granted_movement import routes,resolve_path,path_cost

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    spot = ctx.damage_cache.get("_ring_breaker_from")
    if spot is None or target is None or not actor.active:
        return
    former = Position(x=spot[0], y=spot[1],z=spot[2])
    start = actor.position
    if target.position == former or not engine.grid.placement_legal(former, footprint=engine._footprint(actor), occupied_cells=engine._occupied_cells_except(actor.entity_id)):
        return
    # The printed grant names one destination, not an ordinary movement pool.
    # Find its shortest legal native route, then grant only that route's cost.
    budget=engine.grid.width*engine.grid.height*engine.grid.square_size_ft*8
    found=routes(engine,actor,budget)
    route=found.get(former)
    if route is None:return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "ring_breaker_step", actor.entity_id), actor, "choice:needle.ring_breaker_step", ["enter"],
                 labels={"enter": f"Step into {former.x},{former.y}"}, allow_decline=True, default="decline", target_id=actor.entity_id, name="Ring Breaker",
                 prompt="Ring Breaker: step into the space it was driven from?")
    if not picked:
        return
    if actor.active and actor.position == start:
        path,cost,mode=route
        cost=path_cost(engine,actor,path,mode=mode)
        resolve_path(engine,actor,path,PREFIX+"ring_breaker",feet=int(cost),intent=ctx.intent,provokes=True,mode=mode)


@hook("collision")
def sumo_collision(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    kind = ctx.damage_cache.get("_sumo")
    if kind not in ("sumo_strike", "ring_breaker") or target is None or not target.active:
        return
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    done = ctx.damage_cache.setdefault("_sumo_collided", [])
    proposed=set(engine._actor_volume(target,blocked_at))
    others=[c for c in engine.state.actors.values() if c.active and c.entity_id!=target.entity_id
        and engine._on_battlefield(c) and not engine._shared_occupancy_pair(target.entity_id,c.entity_id)
        and proposed & set(engine._actor_volume(c))]
    from .objects import blocker_at
    from ..gate2_runtime_models import Position
    objects={}
    solid=False
    for x,y,z in sorted(proposed):
        point=Position(x=x,y=y,z=z)
        obj=blocker_at(engine,point)
        if obj is not None:objects[obj.object_id]=obj
        if obj is not None or engine.grid.terrain_at((x,y,z),'BLOCKED'):solid=True
    if not others and not solid:return
    cl = _cl(engine, actor.entity_id)
    dice = {"count": 3, "sides": 8} if kind == "ring_breaker" else {"count": 3 if cl >= 17 else 2 if cl >= 11 else 1, "sides": 6}
    name = "Ring Breaker" if kind == "ring_breaker" else "Sumo Strike"
    hurt = {"type": "damage", "applies_to": "target", "dice": dice, "damage_types": ["bludgeoning"], "evidence": f"{name}: collision"}

    def hit(creature: Any, rows: list[dict[str, Any]]) -> None:
        if creature.active and creature.entity_id not in done:
            done.append(creature.entity_id)
            te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [creature], creature, {},effect_source=PREFIX+kind), rows)

    if solid:
        note(engine,PREFIX+kind,actor,f'{name}: {target.display_name} slams into a solid surface.',(target.entity_id,))
    if kind=='sumo_strike' or solid:hit(target,[hurt])
    from ..target_knowledge import knowledge
    for other in others:
        known=knowledge(engine,actor,other)
        label=other.display_name if known is not None and known.mode=='DIRECT' else 'a creature'
        note(engine,PREFIX+kind,actor,f'{name}: {target.display_name} is driven into {label}.',(target.entity_id,other.entity_id))
        if kind=='ring_breaker':
            hit(other,[{'type':'save','ability':'dex','evidence':"Ring Breaker: the second creature's Dexterity saving throw",
                'on_fail':[hurt,{'type':'condition','applies_to':'target','condition':'prone'}],
                'on_success':[{'type':'half_damage','applies_to':'target','damage_types':['bludgeoning']}]}])
        else:
            hit(other,[{'type':'save','ability':'dex','evidence':"Sumo Strike: the second creature's Dexterity saving throw",'on_fail':[hurt],'on_success':[]}])
    if kind=='sumo_strike':
        from ..gate2_runtime_models import DiceSpec
        from .objects import deal
        for obj in objects.values():
            roll=engine.roller.roll(DiceSpec(count=dice['count'],sides=dice['sides'],modifier=0),actor_id=actor.entity_id,reason=f'DAMAGE:{PREFIX}{kind}:object')
            engine._record_roll(roll)
            deal(engine,actor,obj,[(int(roll.total),'BLUDGEONING')],PREFIX+kind)


@effect('sumo_root')
def enter_root(ctx: Any, row: dict[str, Any]) -> None:
    from ..sumo_state import touching, owns, DECLINED
    if not owns(ctx.engine,ctx.actor,'rooted_stance') or not touching(ctx.engine,ctx.actor) or not _conscious(ctx.actor):
        return
    token=_ROOT_REFRESH.set(_ROOT_REFRESH.get() | {(id(ctx.engine),ctx.actor.entity_id)})
    try:
        ctx.engine._remove_condition(ctx.actor, DECLINED, ctx.source)
        ctx.engine._remove_condition(ctx.actor, ROOTED, ctx.source)
        ctx.engine._apply_condition(ctx.actor,ROOTED,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'label':'Rooted Stance','source_cl':int(row.get('source_cl',_cl(ctx.engine,ctx.actor.entity_id)))})
        movement=ctx.actor.turn_flags.get('_round_sumo_willing') or {}
        if ctx.engine.state.current_actor_id==ctx.actor.entity_id and movement.get('stamp')==_stamp(ctx.engine) and not owns(ctx.engine,ctx.actor,'immovable_god') and int(movement.get('ft',0))>ctx.engine._effective_speed(ctx.actor)//2:
            ctx.engine._remove_condition(ctx.actor,ROOTED,ctx.source)
            note(ctx.engine,PREFIX+'rooted_stance',ctx.actor,'Rooted Stance ends: this turn’s willing movement already exceeds half your current Speed.')
    finally:
        _ROOT_REFRESH.reset(token)


@hook('forced_displacement_attempt')
def immovable_motion(engine: Any, subject: Any, source: Any, source_id: str, numbers: dict[str, Any]) -> bool | None:
    from ..sumo_state import owns
    if not owns(engine,subject,'immovable_god') or source is None or type(numbers.get('cl')) is not int:
        return None
    if numbers['cl'] < _cl(engine,subject.entity_id):
        return False if _immovable(engine,subject) else None
    # The opposed-check paragraph is separate from the solid-contact bullets.
    return False if _opposed(engine,subject,source,source_numbers=numbers) else None


@hook('unwilling_teleport_attempt')
def immovable_teleport(ctx: Any, subject: Any, previous: Any, destination: Any) -> bool | None:
    from ..sumo_state import owns
    if not owns(ctx.engine,subject,'immovable_god') or type(ctx.numbers.get('cl')) is not int:
        return None
    if ctx.numbers['cl'] < _cl(ctx.engine,subject.entity_id):
        return False if _immovable(ctx.engine,subject) else None
    return False if _opposed(ctx.engine,subject,ctx.actor,hazards=('unwilling_teleport',),source_numbers=ctx.numbers) else None


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


@hook('event',priority=10)
def rooted_state_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ('MOVEMENT_COMMITTED','CONDITION_APPLIED','CONDITION_REMOVED','MODIFIER_APPLIED','MODIFIER_REMOVED'):
        return
    from ..sumo_state import touching,acquired,owns
    actor=engine.state.actors.get(kwargs.get('actor_id') or '') if event_type=='MOVEMENT_COMMITTED' else engine.state.actors.get(next(iter(kwargs.get('target_ids') or ()),''))
    if actor is None or not acquired(engine,actor,'rooted_stance'):
        return
    payload=kwargs.get('payload') or {}
    if _rooted(actor) and (not _conscious(actor) or not touching(engine,actor)):
        engine._remove_condition(actor,ROOTED,PREFIX+'rooted_stance')
        return
    if event_type=='MOVEMENT_COMMITTED' and not payload.get('teleport') and not any(payload.get(k) for k in ('forced','dragged_by','carried_by','mounting','dismounting','platform_motion','vehicle_motion','world_motion')):
        from ..typed_executor import condition_rules
        if engine.state.current_actor_id==actor.entity_id and not any(r.get('no_actions') for r in condition_rules(actor)):
            stamp=_stamp(engine);record=actor.turn_flags.get('_round_sumo_willing') or {}
            from ..gate2_runtime_models import Position
            points=[Position.model_validate(p) for p in payload.get('path') or ()]
            distance=sum(int(engine.grid.distance_ft(a,b)) for a,b in zip(points,points[1:]))
            actor.turn_flags['_round_sumo_willing']={'stamp':stamp,'ft':(int(record.get('ft',0)) if record.get('stamp')==stamp else 0)+distance}
            scope=engine.movement_scope(actor.entity_id,include_episode=True) or {}
            if scope.get('source_id')==kwargs.get('source_definition_id'):
                pending=actor.turn_flags.get('_round_sumo_progress') or {}
                pending.pop(scope.get('episode_id'),None)
    if _rooted(actor) and engine.state.current_actor_id==actor.entity_id and _willing_total(engine,actor)>engine._effective_speed(actor)//2 and not owns(engine,actor,'immovable_god'):
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
    if PREFIX+'immovable_god' in info['owned_ids']:
        out.append(ActionDefinition(source_definition_id='action:typed.'+info['actor_id']+'.sumo.free_enter',
            display_name='Rooted Stance (free; Immovable God)',owner_id=info['actor_id'],economy=EconomyKind.NONE,
            resolution_kind='TYPED',target_kind='SELF',parameters={'free_primary':True,'sumo_god_entry':True,
            'typed':{'source':PREFIX+'rooted_stance','numbers':info['numbers'],'effects':[{'type':'sumo_root'}],
                'riders':[],'duration':{'kind':'instant'}}}))
    return out


@effect('sumo_control')
def control_stance(ctx: Any, row: dict[str, Any]) -> None:
    from ..sumo_state import DECLINED,owns,acquired
    if not acquired(ctx.engine,ctx.actor,'rooted_stance') or (row['operation']!='end' and not owns(ctx.engine,ctx.actor,'immovable_god')):
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
    if action is None:return None
    typed=(action.parameters or {}).get('typed') or {}
    source=str(typed.get('option_of') or typed.get('source') or '')
    if not source.startswith(PREFIX):return None
    slug=source.removeprefix(PREFIX)
    if slug not in ('rooted_stance','ring_breaker','yokozuna_presence'):return None
    from ..sumo_state import acquired
    operation=(action.parameters or {}).get('sumo_control')
    if operation=='end':return None if acquired(engine,actor,'rooted_stance') and _rooted(actor) else False
    if not owns(engine,actor,slug):return False
    if operation=='resume':return None if _immovable(engine,actor) and any(c.condition_id==DECLINED for c in actor.conditions.values()) else False
    god=owns(engine,actor,'immovable_god')
    if (action.parameters or {}).get('sumo_god_entry') and not god:return False
    if slug=='rooted_stance' and not operation and not (action.parameters or {}).get('sumo_god_entry') and god:return False
    if action.parameters.get('sumo_brace'):return None if brace_surfaces(engine,actor) else False
    if slug=='rooted_stance':return None if touching(engine,actor) else False
    if slug=='ring_breaker':
        from ..attack_reach import maximum
        target=engine.state.actors.get(next(iter(candidate.target_ids or ()),''))
        strike=_unarmed_strike(engine,actor)
        return None if target is not None and strike is not None and engine._distance_actor_to_actor(actor,target)<=int(maximum(engine,actor,strike) or 5) else False
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


@hook('teleport_settled')
def rooted_after_teleport(ctx: Any, actor: Any, previous: Any, destination: Any, unwilling: bool) -> None:
    from ..sumo_state import touching
    if _rooted(actor) and not touching(ctx.engine,actor):ctx.engine._remove_condition(actor,ROOTED,PREFIX+'rooted_stance')


@hook('movement_edge_cost_active')
def presence_route_cost(engine: Any, actor: Any) -> bool | None:
    from ..sumo_state import owns,rooted
    return True if any(guard.team_id!=actor.team_id and owns(engine,guard,'yokozuna_presence') and rooted(engine,guard)
        for guard in engine.state.actors.values()) else None


@hook('movement_difficult_segment')
def presence_start_space(engine: Any, actor: Any, previous: Any, destination: Any, mode: str) -> bool | None:
    from ..sumo_state import owns,rooted
    from ..motion import ignores_area_difficult
    if ignores_area_difficult(engine,actor):return None
    for guard in engine.state.actors.values():
        if guard.team_id!=actor.team_id and owns(engine,guard,'yokozuna_presence') and rooted(engine,guard) and (
            engine._distance_actor_to_actor(actor,guard,actor_position=previous)<=10):
            return True
    return None


BRACE='condition:typed.sumo_braced'


def brace_surfaces(engine: Any, actor: Any) -> list[Any]:
    from ..gate2_runtime_models import Position
    pos=actor.position
    return [Position(x=pos.x+dx,y=pos.y+dy,z=pos.z) for dx,dy in ((-1,0),(1,0),(0,-1),(0,1))
        if engine.grid.terrain_at((pos.x+dx,pos.y+dy,pos.z),'BLOCKED')]


@hook('surface_contact')
def braced_contact(engine: Any, actor: Any) -> dict[str, Any] | None:
    if not any(c.condition_id==BRACE for c in actor.conditions.values()):return None
    points={(p.x,p.y,p.z) for p in brace_surfaces(engine,actor)}
    if any(c.condition_id==BRACE and tuple(c.data.get(k) for k in ('x','y','z')) in points for c in actor.conditions.values()):
        return {'material':'solid','stable':True,'solid':True,'touching':True}
    return None


@hook('compile_actions')
def brace_action(info: dict[str, Any]) -> list[Any] | None:
    if PREFIX+'rooted_stance' not in info['owned_ids']:return None
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    action=ActionDefinition(source_definition_id='action:typed.'+info['short']+'.sumo_brace',
        display_name='Brace against a solid surface and enter Rooted Stance (Bonus Action)',owner_id=info['actor_id'],
        economy=EconomyKind.BONUS_ACTION,resolution_kind='TYPED',target_kind='SELF',parameters={'sumo_brace':True,
        'typed':{'source':PREFIX+'rooted_stance','numbers':info['numbers'],'effects':[{'type':'sumo_brace'}],
        'riders':[],'duration':{'kind':'instant'}}})
    out=[action]
    if PREFIX+'immovable_god' in info['owned_ids']:
        out.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'.free',
            'display_name':'Brace against a solid surface and enter Rooted Stance (free; Immovable God)',
            'economy':EconomyKind.NONE,'parameters':{**action.parameters,'free_primary':True,'sumo_god_entry':True}}))
    return out


@effect('sumo_brace')
def brace(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask,checkpoint_id
    from ..sumo_state import owns
    if not owns(ctx.engine,ctx.actor,'rooted_stance'):return
    points=brace_surfaces(ctx.engine,ctx.actor)
    options={str(i):p for i,p in enumerate(points)}
    if not options:return
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'sumo_brace',ctx.actor.entity_id),ctx.actor,'choice:needle.sumo_brace',list(options),
        labels={k:f'Brace against the solid surface at {p.x},{p.y}, {p.z*5} feet high' for k,p in options.items()},
        prompt='Rooted Stance: choose the substantial surface to brace against with a limb; '+('this is free with Immovable God.' if _cl(ctx.engine,ctx.actor.entity_id)>=18 else 'this costs your Bonus Action.'),name='Rooted Stance')
    if not picked or picked[0] not in options:return
    p=options[picked[0]]
    ctx.engine._remove_condition(ctx.actor,BRACE,ctx.source)
    ctx.engine._apply_condition(ctx.actor,BRACE,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',data={'x':p.x,'y':p.y,'z':p.z,'label':'Braced against solid surface'})
    enter_root(ctx,{})


@hook('save_effects')
def rooted_pending_save(ctx: Any, subject: Any, ability: str, fail: Any, success: Any, categories: Any) -> dict[str, Any] | None:
    from ..sumo_state import rooted
    if not rooted(ctx.engine,subject):return None
    from ..typed_executor import _walk_rows
    if any((r.get('type') in ('sumo_push','ring_breaker_push')) or
        (r.get('type')=='teleport' or r.get('type')=='movement' and r.get('mode')=='teleport') and
        r.get('applies_to')=='target' and r.get('unwilling') is not False for r in _walk_rows(fail)):
        return {'bonus':0,'modes':['ADVANTAGE']}
    return None


@hook('support_surface')
def physical_brace_support(engine: Any, actor: Any, position: Any) -> bool | None:
    if position!=actor.position:return None
    return True if braced_contact(engine,actor) is not None else None


@hook('forced_movement_direction')
def shared_space_push(ctx: Any, target: Any, distance_ft: int) -> tuple[int, int] | None:
    kind=ctx.damage_cache.get('_sumo')
    if kind not in ('sumo_strike','ring_breaker') or not (set(ctx.engine._actor_cells(ctx.actor)) & set(ctx.engine._actor_cells(target))):return None
    from .needle import ask,checkpoint_id
    footprint=ctx.engine._footprint(ctx.actor);other=ctx.engine._footprint(target)
    dx=2*(target.position.x-ctx.actor.position.x)+other.width_cells-footprint.width_cells
    dy=2*(target.position.y-ctx.actor.position.y)+other.height_cells-footprint.height_cells
    directions={'North':(0,-1),'Northeast':(1,-1),'East':(1,0),'Southeast':(1,1),
        'South':(0,1),'Southwest':(-1,1),'West':(-1,0),'Northwest':(-1,-1)}
    options={name:step for name,step in directions.items() if not (dx or dy) or dx*step[0]+dy*step[1]>0}
    name='Sumo Strike' if kind=='sumo_strike' else 'Ring Breaker'
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'sumo_shared_space',target.entity_id),ctx.actor,
        'choice:needle.sumo_shared_space',list(options),labels={k:k for k in options},name=name,target_id=target.entity_id,
        prompt=name+': '+target.display_name+' shares your space. Choose a direction away from the center of your space.')
    return options[picked[0]] if picked and picked[0] in options else (0,0)


@hook('row_allowed')
def sumo_row_access(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    from ..sumo_state import owns,LEVELS
    source=str(row.get('feature_id') or '')
    slug=source.removeprefix(PREFIX)
    if source.startswith(PREFIX) and slug in LEVELS and not owns(engine,actor,slug):return False
    return None


@hook('event')
def sumo_capacity_events(engine: Any,event_type: str,kwargs: dict[str, Any]) -> None:
    # Capacity is dynamic; refresh the existing source-neutral encumbrance
    # consumer when stance/contact/suppression/health changes. Nested refresh
    # conditions cannot recursively reapply the same Speed adjustment.
    if event_type not in ('CONDITION_APPLIED','CONDITION_REMOVED','MOVEMENT_COMMITTED','HEALING_APPLIED'):return
    actor=engine.state.actors.get(kwargs.get('actor_id') or '') if event_type=='MOVEMENT_COMMITTED' else engine.state.actors.get(next(iter(kwargs.get('target_ids') or ()),''))
    from ..sumo_state import acquired
    if actor is None or not acquired(engine,actor,'rooted_stance'):return
    key=(id(engine),actor.entity_id)
    if key in _CAPACITY_REFRESH.get():return
    token=_CAPACITY_REFRESH.set(_CAPACITY_REFRESH.get() | {key})
    try:
        from ..carry import refresh
        refresh(engine,actor,PREFIX+'rooted_stance')
    finally:_CAPACITY_REFRESH.reset(token)


def _willing_total(engine,actor):
    record=actor.turn_flags.get('_round_sumo_willing') or {};stamp=_stamp(engine)
    total=int(record.get('ft',0)) if record.get('stamp')==stamp else 0
    return total+sum(int(row['ft']) for row in (actor.turn_flags.get('_round_sumo_progress') or {}).values() if row.get('stamp')==stamp)


def _reach_entry(engine,owner,mover,previous,destination,episode):
    from ..sumo_state import owns
    if not episode or not owns(engine,owner,'immovable_god'):return
    action=_unarmed_strike(engine,owner)
    if action is None:return
    from ..attack_reach import maximum
    reach=int(maximum(engine,owner,action) or 5)
    entries=owner.turn_flags.setdefault('_round_sumo_entries',{}).setdefault(episode,[])
    candidates=engine.state.actors.values() if mover is owner else (mover,)
    for other in candidates:
        if not other.active or other is owner:continue
        before=engine._actor_cells(owner,previous) if mover is owner else engine._actor_cells(owner)
        after=engine._actor_cells(owner,destination) if mover is owner else before
        old=engine._actor_cells(other) if mover is owner else engine._actor_cells(other,previous)
        new=engine._actor_cells(other) if mover is owner else engine._actor_cells(other,destination)
        if engine.grid.distance_between_cell_sets(before,old)*engine.grid.square_size_ft>reach and engine.grid.distance_between_cell_sets(after,new)*engine.grid.square_size_ft<=reach and other.entity_id not in entries:entries.append(other.entity_id)


@hook('movement_progress_committed')
def rooted_progress(engine,actor,receipt):
    from ..sumo_state import acquired,owns
    if not acquired(engine,actor,'rooted_stance') or not receipt['voluntary'] or not receipt['own_turn']:return
    from ..typed_executor import condition_rules
    if any(r.get('no_actions') for r in condition_rules(actor)):return
    episode=receipt.get('episode_id')
    if not episode:return
    pending=actor.turn_flags.setdefault('_round_sumo_progress',{})
    row=pending.setdefault(episode,{'stamp':_stamp(engine),'ft':0})
    row['ft']+=int(receipt['distance_ft'])
    if _rooted(actor) and not owns(engine,actor,'immovable_god') and _willing_total(engine,actor)>engine._effective_speed(actor)//2:
        engine._remove_condition(actor,ROOTED,PREFIX+'rooted_stance')


@hook('movement_landed')
def rooted_landing(engine,mover,previous,destination,intent,forced):
    from ..sumo_state import acquired,touching
    if acquired(engine,mover,'rooted_stance'):
        if _rooted(mover) and (not _conscious(mover) or not touching(engine,mover)):
            engine._remove_condition(mover,ROOTED,PREFIX+'rooted_stance')
            note(engine,PREFIX+'rooted_stance',mover,f'Rooted Stance ends: {mover.display_name} is airborne without a supporting surface.')
        if _immovable(engine,mover):_enter(engine,mover)
    for owner in engine.state.actors.values():
        if engine.state.current_actor_id!=owner.entity_id:continue
        scope=engine.movement_scope(owner.entity_id,include_episode=True) if engine.movement_scope(owner.entity_id) else None
        if scope:_reach_entry(engine,owner,mover,previous,destination,scope.get('episode_id'))


@hook('falling_prepare')
def rooted_fall(engine,actors,cause,intent):
    from ..sumo_state import acquired,touching
    for actor in actors:
        if acquired(engine,actor,'rooted_stance') and _rooted(actor) and not touching(engine,actor):
            engine._remove_condition(actor,ROOTED,PREFIX+'rooted_stance')


@hook('forced_drag_step')
def rooted_drag(engine,grappler,subject,grip,previous,destination,episode):
    from ..sumo_state import acquired,owns,rooted,level
    if not acquired(engine,subject,'rooted_stance'):return None
    record=subject.turn_flags.get('_sumo_drag') or {}
    if record.get('episode')!=episode:record={'episode':episode,'opposed':-1}
    if owns(engine,subject,'immovable_god'):
        from .source_eligibility import catalog_action
        action=catalog_action(engine,grip.source_definition_id) if grip else None
        numbers=dict(((action.parameters or {}).get('typed') or {}).get('numbers') or {}) if action else {}
        cl=(grip.data or {}).get('source_cl',numbers.get('cl')) if grip else numbers.get('cl')
        if type(cl) is int:
            if cl<level(engine,subject) and _immovable(engine,subject):return False
            if cl>=level(engine,subject):
                if record['opposed']==-1:record['opposed']=int(not _opposed(engine,subject,grappler,source_numbers=numbers))
                subject.turn_flags['_sumo_drag']=record
                if not record['opposed']:return False
    # Native dragging adjusts one five-foot step when the hold stretches beyond
    # its reach. Reducing that first step to zero leaves the hold out of reach;
    # the existing native caller releases it instead of relocating the subject.
    return False if rooted(engine,subject) else None
