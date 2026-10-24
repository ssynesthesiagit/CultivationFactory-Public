"""Native White-Heron Crescent Body progression and physical Polearm consumers.

The existing table advancement journal acquires this Open School from its
canonical source hashes and actual Body Path profile. One family provider
consumes public Body availability/scene, inventory/readiness, movement-progress,
roll-phase, granted-attack and damage-packet contracts. No ownership creates
anatomy, an item, a Sphere, another Attack action or a source fact.

Passing Cut reads committed voluntary steps and attaches its selected damage
to the triggering hit. White Wing grants one native through-creature route,
exempting only the triggering creature from Opportunity Attacks. The sweep
replaces one attack and settles one mixed-die save packet per chosen hostile.
Moon uses continuous physical routes, actual per-step eligibility, expiring
stance/reach and one reaction-free entry Opportunity Attack. Guard resolves
its paid granted attack before the original roll and preserves the protected
creature's own movement consent. Every player-owned choice uses Ask on both
human and AI turns; automatic actors receive only their own information.

All hooks are inert without an owned row, exact source or live scoped route.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note, query
from ..relations import relation, ENEMY

PREFIX = "tianxia.subpath.body.white_heron_crescent_body.feature."
REAPING = PREFIX + "crescent_reaping_circle"
STANCE = "moon_reed_stance"
STAMINA = "resource:core.stamina"
SOURCE = PREFIX.removesuffix('.feature.')
FEATURE_LEVELS = {PREFIX + name: level for name, level in (
    ('crescent_body_integration', 3), ('one_legged_guard', 6), ('crescent_reaping_circle', 10),
    ('white_wing_crosses_the_reed_field', 14), ('moon_over_the_reed_sea', 18))}
ROLE_FEATURE = dict(zip(('integration', 'guard', 'white_wing', 'moon'),
    (PREFIX+n for n in ('crescent_body_integration', 'one_legged_guard',
                       'white_wing_crosses_the_reed_field', 'moon_over_the_reed_sea'))))


def _available(engine, actor, feature):
    from .body_modes_scene_resources import available
    return available(engine, actor, feature, FEATURE_LEVELS[feature], requires_conscious=False)


def _ready(engine, actor):
    from ..weapon_delivery import ready_weapons
    from ..acquisition_inventory import read,controlled,location
    items=read(actor)
    def usable(key):
        item=next((i for i in items.values() if key in i.get('weapon_actions',[])),None)
        if item is None:return True
        place=location(actor,item.get('inventory_key'))
        return (controlled(actor,item) and item.get('quantity',1)>0
                and not any(item['profile']['flags'].get(k) for k in ('broken','consumed'))
                and (place is None or place=='hand' or place.startswith('hand:')))
    return {key:a for key,a in ready_weapons(engine,actor).items()
            if _polearm(a.parameters.get('typed') or {}) and usable(key)}


def _owns(engine, actor, feature):
    from .body_modes_scene_resources import bundle_of,feature_owned
    bundle = bundle_of(engine, actor)
    return (feature_owned(bundle,feature)
            or any(((a.get('parameters') or {}).get('typed') or {}).get('source') == feature
                   or (a.get('parameters') or {}).get('attack_line') == feature
                   for a in bundle.get('action_catalog', [])))



def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "heron"
            and row.get('role') in ROLE_FEATURE and _available(engine, actor, ROLE_FEATURE[row['role']])}


def _stamp(engine: Any) -> str:
    from .body_modes_scene_resources import turn_key
    return turn_key(engine)


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _polearm(typed: dict[str, Any]) -> bool:
    from .integrated_weapons import in_group

    return in_group(typed or {}, "polearm") and not (typed or {}).get("range_ft")


def _moved(engine: Any, actor: Any) -> int:
    record=next((c for c in actor.conditions.values() if c.condition_id==PROGRESS
                 and c.data.get('turn')==_stamp(engine)),None)
    return int(record.data.get('feet') or 0) if record else 0


def _reach(engine,actor,action,*,opportunity=False):
    from .reach_bonus import current_reach
    from ..attack_reach import bonus
    action=action.model_copy(update={'parameters':{**action.parameters,'outside_turn_reach':int(opportunity)}})
    return current_reach(engine,actor,action,opportunity=opportunity)+bonus(engine,actor,action,opportunity=opportunity)


def _attack_reach(engine,actor,action,*,opportunity=False):
    from ..attack_reach import maximum
    return int(maximum(engine,actor,action,opportunity=opportunity) or 0)


def _polearm_attacks(engine: Any, actor: Any, target: Any | None, *, opportunity: bool = False) -> dict[str, Any]:
    """The owner's Polearm attack actions (and their integrated variants) that reach ``target``, the longest reach first."""
    from .reach_bonus import MARK, applies, current_reach

    from ..weapon_delivery import physical_weapon_id
    ready = _ready(engine, actor)
    out = {}
    for action in sorted(engine.action_catalog.values(), key=lambda a: (-int(a.range_ft or 5), a.source_definition_id)):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != actor.entity_id or not _polearm(typed) or (action.parameters or {}).get("player_only") \
                or str(getattr(action.economy, "value", action.economy)) != "ACTION" or ("#" in action.source_definition_id and "#integrated" not in action.source_definition_id):
            continue
        from .hand_occupancy import weapon_allowed
        if physical_weapon_id(action.source_definition_id, action.parameters) not in ready or weapon_allowed(engine,actor,action) is False:
            continue
        if not any(isinstance(e, dict) and e.get("type") == "attack" for e in typed.get("effects") or []):
            continue
        rule = (action.parameters or {}).get(MARK)
        if rule and not applies(engine, actor, rule, opportunity=opportunity):
            continue
        base_reach = current_reach(engine, actor, action, opportunity=opportunity)
        reach = _reach(engine,actor,action,opportunity=opportunity)
        if target is None or engine._distance_actor_to_actor(actor, target) <= reach:
            actual=action.model_copy(update={'range_ft':base_reach,'target_kind':'ANY_CREATURE',
                'parameters':{**action.parameters,'harmful':True,'outside_turn_reach':int(opportunity)}})
            if target is not None:
                from ..recipients import allowed
                if not allowed(engine,actor,target,actual,allow_remembered=True):continue
            out[action.source_definition_id] = actual
    return out


def _label(engine,viewer,target):
    from ..target_knowledge import knowledge
    if target.entity_id not in engine.state.actors:return target.display_name
    known=knowledge(engine,viewer,target)
    return target.display_name if known is not None else 'an unperceived creature'


def _hostile_choices(engine,actor,intent,checkpoint,choice_id,*,name,prompt,eligible):
    """Choose physical sweep recipients without revealing hidden occupants.

    Individually known creatures use native viewer knowledge. An unconditional
    all-hostiles option also reaches unperceived creatures; blind square choices
    are offered for every public map square, independent of its occupancy.
    Resolution alone intersects the selection with actual eligible hostiles.
    """
    from .needle import ask
    from ..target_knowledge import actors_for
    known={a.entity_id:a for a in actors_for(engine,actor) if a.active and relation(engine,actor,a)==ENEMY}
    choices={'all':'Every hostile creature the sweep can reach',**{k:a.display_name for k,a in known.items()}}
    # Square choices identify space, not an actor or an observation. Ground
    # and the map's admitted vertical extent are supplied independently of foes.
    from ..gate2_runtime_models import Position
    reach=max((_attack_reach(engine,actor,a) for a in _polearm_attacks(engine,actor,None).values()),default=5)
    radius=reach+(2*int(engine._effective_speed(actor)) if name=='Moon over the Reed Sea' else 0)
    height=actor.position.z+radius//engine.grid.square_size_ft
    cells={f'square:{x},{y},{z}':Position(x=x,y=y,z=z)
           for x in range(engine.grid.width) for y in range(engine.grid.height) for z in range(height+1)
           if engine.grid.distance_ft(actor.position,Position(x=x,y=y,z=z))<=radius}
    choices.update({k:f'Hostile creatures occupying ({c.x}, {c.y}), {c.z*engine.grid.square_size_ft} feet high'
                    for k,c in cells.items()})
    picked=[];remaining=dict(choices);batch=0
    while remaining:
        # The transport accepts 64 selections per answer. Every option remains
        # reachable: a full batch opens another answer, with an explicit finish.
        labels={**({'finish':'Finish selecting sweep recipients'} if batch else {}),**remaining}
        answer=ask(engine,intent,checkpoint+':batch:'+str(batch),actor,choice_id,list(labels),labels=labels,
            minimum=1,maximum=min(64,len(labels)),default_count=1,
            preferred=['finish'] if batch else ['all'],allow_decline=True,
            target_id=actor.entity_id,name=name,prompt=prompt) or []
        if 'all' in answer:return set(eligible)
        picked.extend(key for key in answer if key in remaining)
        for key in answer:remaining.pop(key,None)
        if 'finish' in answer or len(answer)<64:break
        batch+=1
    selected={k for k in picked if k in known}
    chosen_cells={cells[k] for k in picked if k in cells}
    for key,target in eligible.items():
        if any(c in chosen_cells for c in (Position(x=x,y=y,z=z) for x,y,z in engine._actor_volume(target))):selected.add(key)
    return selected


def _pick(engine: Any, intent: Any, actor: Any, target: Any, name: str, *, optional: bool = False, opportunity: bool = False) -> Any:
    from .needle import ask, checkpoint_id

    attacks = _polearm_attacks(engine, actor, target, opportunity=opportunity)
    if len(attacks) == 0:
        return None
    if not optional and len(attacks) <= 1:
        return next(iter(attacks.values()), None)
    preferred = [k for k in attacks if k.endswith("#integrated_con")] or list(attacks)
    picked = ask(engine, intent, checkpoint_id(engine, "heron_attack", target.entity_id), actor, "choice:needle.heron_polearm_attack", list(attacks),
                 labels={k: a.display_name for k, a in attacks.items()}, preferred=preferred[:1], target_id=target.entity_id, name=name,
                 allow_decline=optional,
                 prompt=(f"{name}: {_label(engine,actor,target)} entered your reach. Take one Polearm Opportunity Attack without spending your Reaction?"
                         if optional else f"{name}: which Polearm attack against {_label(engine,actor,target)}?"))
    return attacks.get(picked[0]) if picked else None


def _granted(engine: Any, actor: Any, action: Any, target: Any, intent: Any, *, outside_turn_reach=False, opportunity=False) -> bool:
    """One Granted Attack with ``action``; True on a hit."""
    from .. import typed_executor as te

    action=action.model_copy(update={'target_kind':'ANY_CREATURE','parameters':{**action.parameters,'harmful':True}})
    from ..recipients import allowed
    if not allowed(engine,actor,target,action,allow_remembered=True):return False
    if outside_turn_reach:
        action=action.model_copy(update={'parameters':{**action.parameters,'outside_turn_reach':1}})
    typed = (action.parameters or {}).get("typed") or {}
    if opportunity:typed={**typed,'opportunity_of':action.source_definition_id}
    attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return False
    attack.update(count=1, granted_attack_root=True)
    start = len(engine.events)
    result=[]
    token=_GRANTED.set((engine,actor.entity_id,target.entity_id,action.source_definition_id,result))
    try:
        from ..target_knowledge import attack_aim
        with attack_aim(engine,actor,target,action):
            te.run_effects(te.Context(engine, actor, action, intent, {**typed, "effects": [attack], "granted_attack": True}, [target], target, {}), [attack])
    finally:_GRANTED.reset(token)
    return any(result)


def _free_move(engine: Any, intent: Any, actor: Any, feet: int, choice_id: str, name: str, *, source: str) -> None:
    from .needle import ask, checkpoint_id
    from ..granted_movement import routes, Route, resolve_path
    from .needle import cell_id

    paths = {cell_id(c): Route(tuple(path), mode) for c, (path, cost, mode) in routes(engine, actor, feet).items()}
    if not paths:
        return
    picked = ask(engine, intent, checkpoint_id(engine, "heron_move", actor.entity_id), actor, choice_id, sorted(paths), allow_decline=True, default="decline",
                 labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=actor.entity_id, name=name,
                 prompt=f"{name}: move up to {feet} feet without provoking Opportunity Attacks?")
    if picked and picked[0] in paths:
        resolve_path(engine, actor, paths[picked[0]], source,
                     feet=feet, intent=intent, provokes=False)


# ----------------------------------------------------------------------------------- Heron's Passing Cut and White Wing
@hook("after_hit")
def heron_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if not roles or target is None or not _delivered_polearm(ctx):
        return
    stamp = _stamp(engine)
    mine = engine.state.current_actor_id == actor.entity_id
    if not (ctx.strike_record or {}).get('heron_passing_cut_checked') and "integration" in roles and actor.turn_flags.get("_round_passing_cut") != stamp and _moved(engine, actor) >= 10 \
            and _passing_affordable(engine,actor):
        _passing_cut(ctx, target)
    if "white_wing" in roles and mine and actor.turn_flags.get("_round_white_wing") != stamp:
        _white_wing(ctx, target)


def _passing_cut(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import forced_routes, forced_route

    engine, actor = ctx.engine, ctx.actor
    from .body_modes_scene_resources import effective_body_cl
    cl = effective_body_cl(engine, actor)
    count = 3 if cl >= 17 else 2 if cl >= 11 else 1
    labels = {"move": "Move 10 feet without provoking", "push": "Push it 10 feet", "pull": "Pull it 5 feet toward you (still within reach)",
              "damage": f"+ {count}d8 Slashing or Force"}
    from .choice_costs import quote
    costs=engine.effective_costs(actor,PREFIX+'crescent_body_integration',((STAMINA,1),))
    price=quote(costs) or 'no additional resource'
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "passing_cut", target.entity_id), actor, "choice:needle.herons_passing_cut", list(labels), labels=labels,
                 allow_decline=True, default="decline", target_id=target.entity_id, name="Heron's Passing Cut",
                 prompt=f"Heron's Passing Cut: your Polearm hit {_label(engine,actor,target)} after 10 feet of movement. Spend {price}; choose one.",
                 prompt_context={"cost":quote(costs),"paying_pool":STAMINA})
    if not picked or picked[0] not in labels:
        return
    from ..paid_relocation import activation
    from .body_modes_scene_resources import notify_paid
    with activation(engine,actor,PREFIX+'crescent_body_integration',independent=True):
        actor.turn_flags["_round_passing_cut"] = _stamp(engine)
        engine._spend_costs(actor, ((STAMINA,1),), PREFIX + "crescent_body_integration")
        from dataclasses import replace
        sub = replace(ctx,targets=[target],target=target).with_source(PREFIX+'crescent_body_integration')
        cl=effective_body_cl(engine,actor)
        count=3 if cl>=17 else 2 if cl>=11 else 1
        choice = picked[0]
        if choice == "move":
            _free_move(engine, ctx.intent, actor, 10, "choice:needle.passing_cut_move", "Heron's Passing Cut",source=PREFIX+"crescent_body_integration")
        elif choice == "push":
            te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
        elif choice == "pull":
            from .reach_bonus import current_reach
            reach = _reach(engine,actor,ctx.action)
            found = forced_routes(engine,target,actor,target,5)
            here = engine._distance_actor_to_actor(actor,target)
            def endpoint_distance(cell):
                return engine.grid.distance_between_cell_sets(engine._actor_volume(actor),engine._actor_volume(target,cell))*engine.grid.square_size_ft
            paths = {cell_id(c): p for c,p in found.items()
                     if (len(p)-1)*engine.grid.square_size_ft==5
                     and endpoint_distance(c)<here and endpoint_distance(c)<=reach}
            if paths:
                pick = ask(engine, ctx.intent, checkpoint_id(engine, "passing_pull", target.entity_id), actor, "choice:needle.passing_cut_pull", sorted(paths),
                           labels={k: "Pull it to " + k.removeprefix("cell:") for k in paths}, target_id=target.entity_id,
                           prompt="Heron's Passing Cut: where do you pull it?")
                if pick and pick[0] in paths:
                    forced_route(engine, target, paths[pick[0]], PREFIX + "crescent_body_integration", actor)
        else:
            te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": 8}, "damage_types": ["slashing", "force"],
                                  "evidence": "Heron's Passing Cut"}])
        provenance=ctx.attack_damage_context
        if provenance is not None and (ctx.strike_record or {}).get('heron_passing_cut_checked'):
            engine._apply_condition(actor,'condition:typed.heron_passing_cut_pending',PREFIX+'crescent_body_integration',actor.entity_id,
                expires_on='END_OF_CURRENT_TURN',data={'roll_id':provenance.roll_id,'target_id':target.entity_id,
                    'source_id':provenance.source_id,'label':'Heron’s Passing Cut: settling the triggering hit'})
        else:
            notify_paid(engine,actor,PREFIX+'crescent_body_integration','INTENT_ACCEPTED')


def _white_wing(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import step
    from .frightened_movement import path_allowed

    engine, actor = ctx.engine, ctx.actor
    from ..attack_declaration import is_granted_attack
    # A granted hit still allows movement and non-attack endings, but cannot
    # generate another attack. Lack of Attack-action provenance is not a grant.
    can_grant_attack = not is_granted_attack(engine, actor, ctx.action, ctx.typed)
    half = int(engine._effective_speed(actor)) // 2
    paths = {cell_id(cell): route for cell, (route,cost) in _heron_routes(engine,actor,half,through=target.entity_id).items()}
    if not paths:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "white_wing", target.entity_id), actor, "choice:needle.white_wing_move", sorted(paths),
                 labels={k: "Pass through to " + k.removeprefix("cell:") for k in paths}, allow_decline=True, default="decline", target_id=target.entity_id,
                 name="White Wing Crosses the Reed Field", prompt=f"White Wing Crosses the Reed Field: pass through {_label(engine,actor,target)}'s space?")
    if not picked or picked[0] not in paths:
        return
    actor.turn_flags["_round_white_wing"] = _stamp(engine)
    from ..granted_movement import resolve_path
    route=_route_choice(ctx,paths[picked[0]],half,through=target.entity_id)
    with _route_scope(engine,actor,through=target.entity_id):
        resolve_path(engine,actor,route,PREFIX+'white_wing_crosses_the_reed_field',feet=half,
                     intent=ctx.intent,provokes=True,ignore_oa_from=(target.entity_id,))
    if actor.position != route[-1]:return
    if not actor.active:
        return
    from ..target_knowledge import actors_for
    others = {c.entity_id: c for c in actors_for(engine,actor) if c.active and c.entity_id not in (target.entity_id,actor.entity_id)
              and _polearm_attacks(engine, actor, c)}
    labels = {**({"attack": "One Polearm attack against a different creature in reach"} if others and can_grant_attack else {}),
              **({"push": f"Push {_label(engine,actor,target)} 10 feet", "prone": f"Knock {_label(engine,actor,target)} Prone if it fails a Strength save"} if target.active else {}),
              "ac": "+ 2 AC until the start of your next turn"}
    choice = ask(engine, ctx.intent, checkpoint_id(engine, "white_wing_result", target.entity_id), actor, "choice:needle.white_wing_result", list(labels),
                 labels=labels, target_id=target.entity_id, name="White Wing Crosses the Reed Field", prompt="White Wing Crosses the Reed Field: choose one.")
    choice = choice[0] if choice and choice[0] in labels else "ac"
    from .body_modes_scene_resources import effective_body_pb,effective_body_cl
    pb=effective_body_pb(engine,actor);numbers=dict(ctx.numbers)
    numbers['save_dc']=int(numbers['save_dc'])+min(0,pb-int(actor.proficiency_bonus))
    numbers.update(pb=pb,cl=effective_body_cl(engine,actor))
    sub = te.Context(engine, actor, ctx.action, ctx.intent, {**ctx.typed,'numbers':numbers}, [target], target, {}).with_source(PREFIX+'white_wing_crosses_the_reed_field')
    if choice == "attack":
        pick = ask(engine, ctx.intent, checkpoint_id(engine, "white_wing_other", actor.entity_id), actor, "choice:needle.white_wing_target", list(others),
                   labels={k: c.display_name for k, c in others.items()}, target_id=actor.entity_id, prompt="White Wing: attack whom?")
        other = engine.state.actors.get(pick[0] if pick else next(iter(others)))
        action = _pick(engine, ctx.intent, actor, other, "White Wing Crosses the Reed Field") if other is not None else None
        if action is not None:
            _granted(engine, actor, action, other, ctx.intent)
    elif choice == "push" and target.active:
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
    elif choice == "prone" and target.active:
        te.run_effects(sub, [{"type": "save", "ability": "str", "evidence": "White Wing: Strength saving throw",
                              "on_fail": [{"type": "condition", "applies_to": "target", "condition": "prone"}], "on_success": []}])
    else:
        engine._add_modifier(actor, PREFIX + "white_wing_crosses_the_reed_field", "armor_class", "ADD", 2, "SELF", expires_on="START_OF_SOURCE_NEXT_TURN")


# ------------------------------------------------------------------------------------------------------ One-Legged Guard
def _pending(engine: Any) -> dict[str, Any]:
    from ..attack_declaration import current_pending
    return current_pending(engine) or {}


@hook("row_allowed")
def guard_needs_reach(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """One-Legged Guard: only against a creature within your Polearm's reach (off your turn: no turn-only reach)."""
    if row.get("feature_id") != PREFIX + "one_legged_guard":
        return None
    if _pending(engine).get('granted_attack') or not _available(engine, actor, PREFIX + 'one_legged_guard'):
        return False
    attacker = engine.state.actors.get(str(_pending(engine).get("attacker") or ""))
    return None if attacker is not None and _polearm_attacks(engine, actor, attacker, opportunity=True) else False


@hook("ally_row_allowed")
def guard_needs_reach_ally(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") != PREFIX + "one_legged_guard":
        return None
    if _pending(engine).get('granted_attack') or not _available(engine, reactor, PREFIX + 'one_legged_guard'):
        return False
    attacker = engine.state.actors.get(str(_pending(engine).get("attacker") or ""))
    near = engine._distance_actor_to_actor(reactor, subject) <= engine.grid.square_size_ft
    return None if near and attacker is not None and _polearm_attacks(engine, reactor, attacker, opportunity=True) else False


@effect("one_legged_guard")
def one_legged_guard(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask,cell_id,checkpoint_id
    from .rider_movement import forced_routes,forced_route
    from .body_modes_scene_resources import unconscious
    engine,me,attacker=ctx.engine,ctx.actor,ctx.target
    pending=dict(_pending(engine))
    protected=engine.state.actors.get(str(pending.get('target') or ctx.typed.get('protects') or me.entity_id))
    if attacker is None or protected is None:return
    action=_pick(engine,ctx.intent,me,attacker,'One-Legged Guard',opportunity=True)
    if action is None or not _granted(engine,me,action,attacker,ctx.intent,outside_turn_reach=True) or not attacker.active:return
    forced=unconscious(protected)
    if forced:
        moves={cell_id(cell):path for cell,path in forced_routes(engine,protected,me,protected,5).items()}
    else:
        from ..granted_movement import routes,Route
        moves={cell_id(cell):Route(tuple(path),mode) for cell,(path,cost,mode) in routes(engine,protected,5).items()}
    labels={'minus':f'Subtract your Proficiency Bonus ({int(me.proficiency_bonus or 2)}) from this triggering attack roll',
        **({'move':f'Move {_label(engine,me,protected)} 5 feet without provoking, if it accepts'} if moves else {}),
        'push':f'Push {_label(engine,me,attacker)} 5 feet away from you',
        'deny':f'{_label(engine,me,attacker)} cannot take Reactions until the start of its next turn'}
    picked=ask(engine,ctx.intent,checkpoint_id(engine,'one_legged_guard',attacker.entity_id),me,
        'choice:needle.one_legged_guard',list(labels),labels=labels,target_id=attacker.entity_id,
        name='One-Legged Guard',prompt=f'One-Legged Guard: your Polearm hit {_label(engine,me,attacker)} before its attack against {_label(engine,me,protected)}. Choose one result.')
    choice=(picked or ['minus'])[0]
    if choice=='move':
        destination=ask(engine,ctx.intent,checkpoint_id(engine,'guard_move',protected.entity_id),me if unconscious(protected) else protected,
            'choice:needle.one_legged_guard_move',list(moves),labels={k:'Move to '+k.removeprefix('cell:') for k in moves},
            allow_decline=not unconscious(protected),default='first' if unconscious(protected) else 'decline',target_id=protected.entity_id,name='One-Legged Guard',
            prompt=f'One-Legged Guard: accept a 5-foot move to escape {_label(engine,me,attacker)}’s attack? This movement does not provoke.')
        if destination:
            if forced:forced_route(engine,protected,moves[destination[0]],PREFIX+'one_legged_guard',me)
            else:
                from ..granted_movement import resolve_path
                resolve_path(engine,protected,moves[destination[0]],PREFIX+'one_legged_guard',
                    feet=5,intent=ctx.intent,provokes=False)
        else:
            alternatives={k:v for k,v in labels.items() if k!='move'}
            picked=ask(engine,ctx.intent,checkpoint_id(engine,'guard_declined',attacker.entity_id),me,
                'choice:needle.one_legged_guard_alternate',list(alternatives),labels=alternatives,target_id=attacker.entity_id,
                name='One-Legged Guard',prompt=f'{_label(engine,me,protected)} declined movement. Choose another One-Legged Guard result.')
            choice=(picked or ['minus'])[0]
    sub=te.Context(engine,me,action,ctx.intent,action.parameters['typed'],[attacker],attacker,{}).with_source(PREFIX+'one_legged_guard')
    if choice=='minus':
        spec=ctx.typed.get('triggering_attack_spec')
        if spec is not None:spec['attack_bonus']=int(spec.get('attack_bonus') or 0)-int(me.proficiency_bonus or 2)
    elif choice=='push':te.run_effects(sub,[{'type':'forced_movement','applies_to':'target','distance_ft':5,'direction':'away'}])
    elif choice=='deny':te.run_effects(sub,[{'type':'reaction_denied','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'}])
    # The original native target_check rechecks both participants before its
    # d20. Movement outside reach or through a new obstruction cancels the
    # declared attack without rolling; no synthetic hit-response flag is used.


@hook("hit_response")
def guard_turns_the_blow(engine: Any, attacker: Any, target: Any, spec: Any, total: int, natural: int, effective_ac: int) -> Any:
    record = target.turn_flags.get("_one_legged_guard")
    if not record or record.get("attacker") != attacker.entity_id:
        return None
    target.turn_flags.pop("_one_legged_guard", None)
    if record.get("miss"):
        from ..attack_outcomes import unconditional_miss

        return unconditional_miss()
    minus = int(record.get("minus") or 0)
    if natural != 20 and total - minus < effective_ac:
        return effective_ac + minus, False  # equivalent threshold for this one attack; retain terminal eligibility
    return None


@hook("attack_resolved")
def guard_record_ends(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    if target is not None and (target.turn_flags.get("_one_legged_guard") or {}).get("attacker") == ctx.actor.entity_id:
        target.turn_flags.pop("_one_legged_guard", None)


# ------------------------------------------------------------------------------------------------ Crescent Reaping Circle
@hook("compile_actions")
def reaping_circle_actions(info: dict[str, Any]) -> list[Any] | None:
    if REAPING not in info["owned_ids"]:
        return None
    info={**info,'numbers':_body_numbers(info)}
    from ..gate2_runtime_models import EconomyKind
    from .attack_lines import line_variants

    bases = [a for a in info["actions"] if a.economy == EconomyKind.ACTION and _polearm((a.parameters or {}).get("typed") or {})]
    actions=line_variants(info, REAPING, bases, replace=1, area=None, stamina=2, name="Crescent Reaping Circle", lead="reaping_circle")
    by_id={a.source_definition_id:a for a in bases}
    for action in actions:
        typed=action.parameters['typed'];base=by_id[typed['attack_line_of']]
        typed['hold_victory_until_resolved']=True
        typed['heron_weapon_sides']=int(base.parameters['typed']['weapon']['damage']['sides'])
        typed['heron_con_mod']=int(info['mods'].get('CON',0))
        typed['numbers'].update(cl=info['numbers']['cl'])
        action.parameters['description']=('Replace one attack of your Attack action; spend 2 Stamina, once per turn. '
            'Choose hostile creatures within your Polearm reach and clear physical sweep. Each makes a Dexterity save: '
            'one current weapon die + Constitution + 3d8 Slashing or Force, half total on success. '
            'For each failure, push it 5 feet or deny Reactions until its next turn starts. '
            'After every target resolves, move up to 10 feet without provoking Opportunity Attacks. '
            'This is a Body technique; it has no attack-hit, critical or weapon-mastery riders.')
    return actions or None


@effect("reaping_circle")
def reaping_circle(ctx: Any, row: dict[str, Any]) -> None:
    """The sweep: chosen hostile creatures within the Polearm's reach (with this turn's reach increases) save; you choose each failed
    creature's push or Reaction denial; then the asked 10-foot move."""
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    from .attack_lines import claim_line
    claim_line(engine,actor,REAPING)
    from .reach_bonus import current_reach

    base_id = ctx.typed.get("attack_line_of")
    base = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and a.source_definition_id == base_id), None)
    reach = _reach(engine, actor, base) if base is not None else int(row.get("reach_ft") or 5)
    foes = {c.entity_id: c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and relation(engine,actor,c)==ENEMY
            and engine._distance_actor_to_actor(actor, c) <= reach and not engine.cover_from(engine._actor_volume(actor),actor.entity_id,c)['blocked']}
    if foes:
        chosen = _hostile_choices(engine,actor,ctx.intent,checkpoint_id(engine,'reaping_targets',actor.entity_id),
            'choice:needle.reaping_circle_targets',name='Crescent Reaping Circle',eligible=foes,
            prompt='Crescent Reaping Circle: choose hostile creatures or occupied squares in Polearm reach. '
                   '2 Stamina, once per turn. Each makes a Dexterity save against one weapon die + Constitution + 3d8 Slashing or Force; '
                   'half damage on success. Each failure also suffers a 5-foot push or loses Reactions until its next turn. '
                   'After all targets, you may move 10 feet without provoking. Hidden creatures are not identified.')
        sides=int(ctx.typed.get('heron_weapon_sides') or 4)
        from .hand_occupancy import versatile_die_sides
        if base is not None:
            current_sides=versatile_die_sides(engine,actor,base)
            if current_sides is not None:sides=current_sides
        damage_type=ask(engine,ctx.intent,checkpoint_id(engine,'reaping_type',actor.entity_id),actor,
            'choice:needle.heron_damage_type',['SLASHING','FORCE'],preferred=['SLASHING'],target_id=actor.entity_id,name='Crescent Reaping Circle',
            prompt='Crescent Reaping Circle: choose Slashing or Force for every target of this sweep.')
        damage_type=(damage_type or ['SLASHING'])[0]
        damage={'type':'damage','applies_to':'target','dice':{'count':1,'sides':sides},
                'additional_dice':[{'count':3,'sides':8}],
                'flat':int(ctx.typed.get('heron_con_mod') or 0),'damage_types':[damage_type]}
        cache={}
        for key in [k for k in foes if k in chosen]:
            foe=foes[key]
            save={'type':'save','ability':'dex','applies_to':'creatures_in_area','on_fail':[damage,{'type':'reaping_rider'}],
                  'on_success':[{'type':'half_damage'}]}
            te.run_effects(te.Context(engine,actor,ctx.action,ctx.intent,ctx.typed,[foe],foe,cache,
                save_geometry={'origin_ids':[actor.entity_id],'range_ft':int(reach)}),[save])
    if actor.active:
        _free_move(engine, ctx.intent, actor, 10, "choice:needle.reaping_circle_move", "Crescent Reaping Circle",source=REAPING)


@effect("reaping_rider")
def reaping_rider(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    foe = ctx.target
    if foe is None or not foe.active:
        return
    labels = {"push": f"Push {_label(ctx.engine,ctx.actor,foe)} 5 feet", "deny": f"{_label(ctx.engine,ctx.actor,foe)} cannot take Reactions until its next turn"}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "reaping_rider", foe.entity_id), ctx.actor, "choice:needle.reaping_circle_rider", list(labels),
                 labels=labels, target_id=foe.entity_id, name="Crescent Reaping Circle", prompt=f"Crescent Reaping Circle: {_label(ctx.engine,ctx.actor,foe)} failed its save. Choose one.")
    if (picked[0] if picked else "push") == "push":
        te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    else:
        te.run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])


# ------------------------------------------------------------------------------------------------- Moon over the Reed Sea
def _moon_paths(engine: Any, actor: Any):
    from ..paid_relocation import preserve_pending
    preserve_pending(engine,'_heron_moon_routes')
    key=(id(engine.state),id(engine.grid),id(actor),actor.entity_id,engine.state.event_sequence,actor.position.x,actor.position.y,actor.position.z,
         int(engine._effective_speed(actor)))
    cache=engine.__dict__.setdefault('_heron_moon_routes',{})
    if key not in cache:
        cache.clear()
        cache[key]={(cell.x,cell.y,cell.z): route for cell,(route,cost)
            in _heron_routes(engine,actor,2*int(engine._effective_speed(actor)),moon=True).items()}
    return cache[key]


@hook('compile_action')
def moon_aim(action,info):
    if ((action.parameters or {}).get('typed') or {}).get('source')!=PREFIX+'moon_over_the_reed_sea':return
    return action.model_copy(update={'target_kind':'CELL','range_ft':None,'radius_ft':None,
        'parameters':{**action.parameters,'any_cell':True,'moon_reed':True,
            'typed':{**action.parameters['typed'],'numbers':_body_numbers(info),'hold_victory_until_resolved':True}}})


@hook("candidate_allowed")
def moon_reachable(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("moon_reed") or getattr(candidate, "destination", None) is None:
        return None
    return None if (candidate.destination.x, candidate.destination.y, candidate.destination.z) in _moon_paths(engine, actor) else False


@effect("moon_over_the_reed_sea")
def moon_over_the_reed_sea(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .states import PREFIX as STATE, slug
    from ..granted_movement import resolve_path
    from ..target_knowledge import actors_for
    engine, actor = ctx.engine, ctx.actor
    aim=ctx.damage_cache.get('_checkpoint_aim') or ctx.destination
    path=_moon_paths(engine,actor).get((aim.x,aim.y,aim.z)) if aim is not None else None
    if path is None:
        from ..granted_movement import Route
        path=Route((actor.position,),'walk')
    path=_route_choice(ctx,path,2*int(engine._effective_speed(actor)),moon=True)
    foes={a.entity_id:a for a in engine.state.actors.values() if a.active and relation(engine,actor,a)==ENEMY}
    selected=_hostile_choices(engine,actor,ctx.intent,checkpoint_id(engine,'moon_reed',actor.entity_id),
        'choice:needle.moon_over_the_reed_sea',eligible=foes,name='Moon over the Reed Sea',
        prompt='Moon over the Reed Sea: choose hostile creatures or occupied squares to sweep when your route reaches them. '
               '7 Stamina, one Action, once per scene. Each makes one Dexterity save against 10d8 Slashing or Force; '
               'half damage on success. Failure permits a push up to 15 feet and denies Reactions through its next turn; '
               'success pushes 5 feet and denies Reactions until its next turn starts. '
               'Then gain +2 AC, +5 feet reach and one free entry Opportunity Attack until your next turn. '
               'Hidden creatures are not identified.')
    token=_MOON.set((engine,actor.entity_id,ctx,set(selected or []),set()))
    try:
        with _route_scope(engine,actor,moon=True):
            _moon_sweep(engine,actor)
            if len(path)>1:
                resolve_path(engine,actor,path,PREFIX+'moon_over_the_reed_sea',feet=2*int(engine._effective_speed(actor)),
                             intent=ctx.intent,provokes=False)
    finally:
        _MOON.reset(token)
    if actor.active:
        engine._apply_condition(actor,STATE+slug(STANCE),PREFIX+'moon_over_the_reed_sea',actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN',data={'label':'Moon over the Reed Sea: +2 AC, +5 feet reach, one free Opportunity Attack until your next turn','name':STANCE,'strike_available':1})
        engine._add_modifier(actor,PREFIX+'moon_over_the_reed_sea','armor_class','ADD',2,'SELF',expires_on='START_OF_SOURCE_NEXT_TURN')
        actor.turn_flags['_round_moon_free_strike']=1


@effect("moon_push")
def moon_push(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    foe = ctx.target
    if foe is None or not foe.active:
        return
    options = ["15", "10", "5", "0"]
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "moon_push", foe.entity_id), ctx.actor, "choice:needle.moon_push_distance", options,
                 labels={o: f"Push {_label(ctx.engine,ctx.actor,foe)} {o} feet" if o != "0" else f"Leave {_label(ctx.engine,ctx.actor,foe)} in place" for o in options},
                 target_id=foe.entity_id, name="Moon over the Reed Sea", prompt=f"Moon over the Reed Sea: {_label(ctx.engine,ctx.actor,foe)} failed its save. Push it how far (up to 15 feet)?")
    feet = int(picked[0]) if picked and picked[0] in options else 15
    te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": feet, "direction": "away"}])


@hook("event")
def moon_free_strike(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Legacy per-step event adapter; one entry implementation is shared below."""
    if event_type!='MOVEMENT_COMMITTED':return
    payload=kwargs.get('payload') or {}
    if payload.get('teleport') or payload.get('without_provoking') or 'planned_cost_ft' in payload:return
    path=payload.get('path') or [];mover=engine.state.actors.get(kwargs.get('actor_id'))
    if mover is None or not mover.active or len(path)<2:return
    from ..gate2_runtime_models import Position
    _stance_entry(engine,mover,Position.model_validate(path[-2]),Position.model_validate(path[-1]),_intent(engine),forced=bool(payload.get('forced')))


# Source-owned continuation on the public acquisition, wielding and Body seams.
@hook('body_mode_profiles')
def heron_scene_profile(bundle):
    owned = {r.get('feature_id') for r in bundle.get('typed_passives', [])}
    owned.update(((a.get('parameters') or {}).get('typed') or {}).get('source')
                 for a in bundle.get('action_catalog', []))
    if not owned.intersection(FEATURE_LEVELS):
        return None
    limits = sorted({cost[0] for action in bundle.get('action_catalog', [])
                     if ((action.get('parameters') or {}).get('typed') or {}).get('source') == PREFIX+'moon_over_the_reed_sea'
                     for cost in action.get('costs', []) if cost[0].startswith('resource:uses.')})
    return [{'source': SOURCE, 'name': 'White-Heron Crescent Body',
             'feature_levels': FEATURE_LEVELS, 'scene_limits': limits}]


@hook('cultivation_feature_available')
def heron_availability(engine, actor, feature):
    if feature not in FEATURE_LEVELS:
        return None
    # Do not call available here: it queries this same hook.
    from .body_modes_scene_resources import effective_body_cl, SUPPRESSION
    if effective_body_cl(engine, actor) < FEATURE_LEVELS[feature]:
        return False
    for condition in actor.conditions.values():
        d=condition.data
        if condition.condition_id == SUPPRESSION and (d.get('feature_id') == feature or
                (d.get('system') in ('body','all','tianxia.path.body_refining') and d.get('suppressed') == 1)):
            return False
    return None


@hook('weapon_proficiency')
def heron_proficiency(info):
    if PREFIX+'crescent_body_integration' not in info['owned_ids']:
        return None
    return True if _polearm({'source':info['weapon']['item_id'], 'weapon':info['weapon']}) else None


@hook('compile_actions', priority=-30)
def heron_profiles(info):
    if PREFIX+'crescent_body_integration' not in info['owned_ids']:
        return None
    body_numbers=_body_numbers(info)
    for a in info['actions']:
        t=(a.parameters or {}).get('typed') or {}
        if not _polearm(t):continue
        t['heron_profile']={'con_attack': int(info['pb'])+int(info['mods'].get('CON',0))+int(t.get('magic_bonus') or 0),
            'cultivation_attack':int(body_numbers['attack_bonus'])+int(t.get('magic_bonus') or 0),
            'save_dc':int(body_numbers['save_dc']),'source_cl':int(body_numbers['cl']),
            'con_damage':int(info['mods'].get('CON',0))+int(t.get('magic_bonus') or 0),
            'fist_permissions':[f for f in ('refined_iron_fist','heavenly_fist')
                if 'tianxia.path.body_refining.feature.'+f in info['owned_ids']]}


@hook('attack_spec_choice')
def heron_strike_profile(ctx, target, attack, spec, attack_index):
    if 'integration' not in _roles(ctx.engine,ctx.actor) or not _delivered_polearm(ctx):return
    from ..weapon_delivery import weapon_identity
    if weapon_identity(ctx.engine,ctx.source,ctx.typed,ctx.action.parameters,owner_id=ctx.actor.entity_id) not in _ready(ctx.engine,ctx.actor):return
    profile=ctx.typed.get('heron_profile')
    if not profile:return
    from .needle import ask,checkpoint_id
    from .body_modes_scene_resources import effective_body_pb
    shift=min(0,effective_body_pb(ctx.engine,ctx.actor)-int(ctx.actor.proficiency_bonus))
    options={'Constitution':profile['con_attack']+shift,'Cultivation':profile['cultivation_attack']+shift}
    choice=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'heron_ability',target.entity_id,attack_index),ctx.actor,
        'choice:needle.heron_ability',list(options),labels={'Constitution':'Constitution for attack and damage',
            'Cultivation':'Cultivation Attack Modifier for attack; Constitution for damage'},
        preferred=[max(options,key=options.get)],target_id=target.entity_id,name='Crescent-Body Integration',
        prompt=f'Crescent-Body Integration: choose the attack modifier for {ctx.action.display_name} against {_label(ctx.engine,ctx.actor,target)}. '
               'Damage uses Constitution. No extra attack or cost.')
    if not choice:return
    typed=copy.deepcopy(spec['typed'])
    before=int(typed['numbers']['attack_bonus']);damage=int(typed['weapon']['damage'].get('modifier') or 0)
    spec['attack_bonus']+=options[choice[0]]-before
    if spec.get('damage') is not None:
        spec['damage']=spec['damage'].model_copy(update={'modifier':spec['damage'].modifier+profile['con_damage']-damage})
    typed['weapon']['damage']['modifier']=profile['con_damage']
    typed['numbers']['attack_bonus']=spec['attack_bonus'];typed['resolved_attack_ability']=choice[0]
    typed['heron_polearm_delivery']=1
    if any(_fist(ctx.engine,ctx.actor,typed,p) for p in ('refined_iron_fist','heavenly_fist')):
        typed['cultivation_powered']=1
    if _fist(ctx.engine,ctx.actor,typed,'heavenly_fist'):typed['adamantine']=1
    spec['typed']=typed


def _fist(engine,actor,typed,permission):
    if 'integration' not in _roles(engine,actor):return False
    from ..weapon_delivery import weapon_identity
    original=typed.get('object_attack_profile') or typed
    identity=weapon_identity(engine,str(original.get('source') or ''),original,{},owner_id=actor.entity_id)
    ready=_ready(engine,actor)
    base=ready.get(identity)
    if base is None:
        base=next((a for a in ready.values() if a.parameters['typed'].get('source')==original.get('source')),None)
    if base is None or not _polearm(base.parameters['typed']):return False
    if permission not in (base.parameters['typed'].get('heron_profile') or {}).get('fist_permissions',[]):return False
    from .body_modes_scene_resources import available
    return available(engine,actor,'tianxia.path.body_refining.feature.'+permission,
                     17 if permission=='heavenly_fist' else 5,requires_conscious=False)


@hook('attack_magical')
def integrated_polearm_magical(engine,actor_id,typed):
    actor=engine.state.actors.get(actor_id)
    if actor and typed.get('heron_polearm_delivery')==1 and any(_fist(engine,actor,typed,p) for p in ('refined_iron_fist','heavenly_fist')):return True


@hook('attack_damage_types')
def heavenly_polearm_types(ctx,attack,kinds):
    if _delivered_polearm(ctx,attack) and _fist(ctx.engine,ctx.actor,ctx.typed,'heavenly_fist'):return list(dict.fromkeys([*kinds,'FORCE']))


@hook('attack_damage_type_choice')
def heavenly_polearm_choice(ctx,attack,target,kinds,attack_index):
    if not _delivered_polearm(ctx,attack) or not _fist(ctx.engine,ctx.actor,ctx.typed,'heavenly_fist'):return
    from .needle import ask,checkpoint_id
    chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'heron_heavenly_type',target.entity_id,attack_index),ctx.actor,
        'choice:needle.heron_heavenly_type',kinds,preferred=kinds[:1],target_id=target.entity_id,name='Heavenly Fist',
        prompt=f'Heavenly Fist: choose the damage type for your integrated Polearm hit against {_label(ctx.engine,ctx.actor,target)}. No extra cost.')
    return chosen[0] if chosen else None


@hook('opportunity_choices')
def heron_opportunity_profiles(engine,actor,default):
    if 'integration' not in _roles(engine,actor):return None
    attacks = list(_polearm_attacks(engine,actor,None,opportunity=engine.state.current_actor_id!=actor.entity_id).values())
    return [default, *attacks] if attacks else None


@hook('candidate_allowed')
def heron_action_guard(engine,actor,candidate,action):
    if action is None:return
    typed=(action.parameters or {}).get('typed') or {}
    source=typed.get('source')
    if source in (REAPING,PREFIX+'moon_over_the_reed_sea'):
        if not _available(engine,actor,source) or not _ready(engine,actor):return False
        from .hand_occupancy import weapon_allowed
        if source==REAPING:
            base=engine.action_catalog.get(typed.get('attack_line_of'))
            if base is None or base.source_definition_id not in _ready(engine,actor) or weapon_allowed(engine,actor,base) is False:return False
        elif not _polearm_attacks(engine,actor,None):return False
    if typed.get('heron_profile') and not _available(engine,actor,PREFIX+'crescent_body_integration'):
        if '#integrated_con' in action.source_definition_id:
            from .integrated_weapons import in_group
            others=[r for r in engine.typed_passive_rows.get(actor.entity_id,[]) if r.get('kind')=='integrated_weapon'
                    and r.get('feature_id')!=PREFIX+'crescent_body_integration' and in_group(typed,str(r.get('group')))]
            if not others:return False


@hook('damage_type_choice')
def heron_damage_choice(ctx,kinds,targets):
    if ctx.typed.get('source') not in FEATURE_LEVELS and not ('integration' in _roles(ctx.engine,ctx.actor) and _delivered_polearm(ctx)):
        return
    if len(kinds)<2:return
    from .needle import ask,checkpoint_id
    target=targets[0] if targets else ctx.actor
    pick=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'heron_damage',ctx.source,target.entity_id),ctx.actor,
        'choice:needle.heron_damage_type',kinds,preferred=kinds[:1],target_id=target.entity_id,name='White-Heron Crescent Body',
        prompt=f'{ctx.action.display_name}: choose '+ ' or '.join(kinds) +' damage for this use. No additional cost.')
    return pick[0] if pick else None


@hook('subpath_acquisition_policy')
def heron_one_subpath(source,sheet):
    from ..subpath_acquisition import selected_subpaths
    selected=selected_subpaths(sheet)
    if source!=SOURCE and SOURCE not in selected:return
    others={mid for mid in selected|{source} if mid.startswith('tianxia.subpath.body.') and mid!=SOURCE}
    if others:
        return {'allowed':False,'reason':'Body Refining CL3 chooses one Subpath. White-Heron Crescent Body cannot be added alongside another Body Subpath.'}


@hook('subpath_acquisition')
def acquire_heron(source, sheet):
    """Open School progression, with no Sphere or sibling grants."""
    if source != PREFIX.removesuffix('.feature.'):
        return None
    import hashlib
    from .qiweaving_common import rules_text
    paths = sheet.get('path_and_subpath') or {}
    identity = sheet.get('identity') or {}
    ids = set(identity.get('path_ids') or paths.get('path_record_ids') or [])
    if paths.get('path_record_id'):
        ids.add(paths['path_record_id'])
    profile_rows = paths.get('paths') or []
    if isinstance(profile_rows,dict):profile_rows=list(profile_rows.values())
    body = next((p for p in profile_rows if isinstance(p, dict) and p.get('path_id') == 'tianxia.path.body_refining'), None)
    if body is not None:
        ids.add('tianxia.path.body_refining')
    legal = 'tianxia.path.body_refining' in ids if ids else identity.get('path') == 'Body Refining'
    level = int(identity.get('cultivation_level') or 1)
    if body is not None:
        # Existing Path profile fields: explicit effective CL is authoritative;
        # NS1R attainment otherwise caps the sheet's effective cultivation CL.
        attained = next((body[k] for k in ('effective_cl', 'attainment', 'owning_path_level') if k in body), None)
        if type(attained) is not int or attained < 0:
            legal, level = False, 0
        else:
            level = min(level, attained)
    elif profile_rows or len(ids)>1:
        legal, level = False, 0
    if level<3:legal=False
    printed = rules_text()
    return {'name': 'White-Heron Crescent Body', 'legal': legal, 'effective_cl': level,
        'reasons': [] if legal else ['White-Heron Crescent Body requires an acquired Body Refining Path at effective CL3 or higher.'],
        'features': [{'id': PREFIX + name, 'minimum_cl': cl,
            'text_sha256': hashlib.sha256(printed[PREFIX + name].encode()).hexdigest()}
            for name, cl in [(name.removeprefix(PREFIX), level) for name, level in FEATURE_LEVELS.items()]]}



@hook('attack_resolution_scope')
def passing_cut_packet_scope(engine,attacker,target,spec,intent):
    if 'integration' not in _roles(engine,attacker) or not _polearm_spec(engine,attacker,spec):return
    from ..attack_delivery import resolving
    return resolving(engine,attacker,target,spec,buffer_attached=True)


@hook('attack_packet_buffer_enabled')
def passing_cut_packet_enabled(engine,attacker,target,spec):
    if 'integration' in _roles(engine,attacker) and _polearm_spec(engine,attacker,spec):return True


@hook('attack_payload_prepare')
def passing_cut_in_packet(ctx):
    if (ctx.target is not None and 'integration' in _roles(ctx.engine,ctx.actor)
            and _delivered_polearm(ctx) and ctx.engine.state.current_actor_id is not None
            and ctx.actor.turn_flags.get('_round_passing_cut')!=_stamp(ctx.engine)
            and _moved(ctx.engine,ctx.actor)>=10 and _passing_affordable(ctx.engine,ctx.actor)):
        if ctx.strike_record is not None:ctx.strike_record['heron_passing_cut_checked']=1
        _passing_cut(ctx,ctx.target)


# Source-scoped permissions exist only while pricing/resolving the printed route.
# They are not anatomy, flight, persistent passage, or actor-supplied receipts.
from contextlib import contextmanager
from contextvars import ContextVar
_ROUTE = ContextVar('white_heron_route',default=None)


@contextmanager
def _route_scope(engine,actor,*,through=None,moon=False):
    token=_ROUTE.set((engine,actor.entity_id,through,moon))
    try:yield
    finally:_ROUTE.reset(token)


def _route_mode(engine,actor):
    value=_ROUTE.get()
    return value if value and value[:2]==(engine,actor.entity_id) else None


@hook('pass_through')
def heron_route_passage(engine,actor,occupant):
    mode=_route_mode(engine,actor)
    if mode and (occupant.entity_id==mode[2] or mode[3] or relation(engine,actor,occupant)!=ENEMY):
        return 'difficult'


@hook('movement_step_capability')
def moon_surface_step(engine,actor,previous,destination,mode):
    scope=_route_mode(engine,actor)
    if not scope or not scope[3] or mode!='walk':return
    from ..roof_movement import faces
    if (destination.z==0 or engine.grid.roof_supported(destination,engine._footprint(actor))
            or faces(engine,actor,destination,include_virtual=False)):
        return True
    # Moon permits moving over liquids; ordinary height-zero ground routes
    # already carry the authoritative map's water and terrain prices.
    if previous.z==destination.z==0:return True
    return False


@hook('support_surface')
def moon_transit_support(engine,actor,position):
    scope=_route_mode(engine,actor)
    if scope and scope[3]:
        # Kept only until this activation's traversal completes; then falling
        # queries the real roof/liquid/ground and other actual support sources.
        return True


from ..read_queries import pure


@pure
def _heron_routes(engine,actor,feet,*,through=None,moon=False):
    """Printed physical traversal with native per-edge geometry and costs.

    White Wing keeps the state 'has crossed this target' in the search so a
    cheaper route around it cannot hide a legal through route. Moon admits
    only real walls/ground for vertical travel. No query changes positions.
    """
    import heapq
    from itertools import product
    from ..gate2_runtime_models import Position
    from ..flight import step_allowed,step_cost,profile
    from ..voluntary_movement import path_allowed
    from ..granted_movement import Route
    from ..target_knowledge import actors_for
    if not actor.active:return {}
    if engine._effective_speed(actor)<=0:
        return {actor.position:(Route((actor.position,),'walk'),0)} if moon else {}
    target=engine.state.actors.get(through) if through else None
    target_cells=set(engine._actor_volume(target)) if target else set()
    occupied={p for other in actors_for(engine,actor) if other.active and other.entity_id!=actor.entity_id
              for p in engine._actor_volume(other)}
    modes=['walk']+(['fly'] if profile(engine,actor).speed_ft else [])
    out={}
    if moon:
        out[actor.position]=(Route((actor.position,),'walk'),0)
    for mode in modes:
        spatial=moon or bool(actor.position.z) or mode=='fly'
        directions=list(product((-1,0,1),repeat=3 if spatial else 2))
        directions=[d for d in directions if any(d)]
        start=(actor.position,False);costs={start:0};paths={start:(actor.position,)}
        queue=[(0,0,start)];serial=0
        with _route_scope(engine,actor,through=through,moon=moon):
            from ..creature_passage import geometry
            difficult=engine._hostile_difficult_cells(actor)|geometry(engine,actor,observed=True)[2]
            while queue:
                spent,_,key=heapq.heappop(queue);cell,passed=key
                if spent!=costs[key]:continue
                if spent and (passed or not through) and not (set(engine._actor_volume(actor,cell)) & occupied):
                    if cell not in out or spent<out[cell][1]:out[cell]=(Route(paths[key],mode),spent)
                if spent>=feet:continue
                for delta in directions:
                    dx,dy,*zs=delta;dz=zs[0] if zs else 0
                    x,y,z=cell.x+dx,cell.y+dy,cell.z+dz
                    if z<0 or z>actor.position.z+feet//engine.grid.square_size_ft or not engine.grid.in_bounds((x,y)):continue
                    nxt=Position(x=x,y=y,z=z)
                    if not step_allowed(engine,actor,cell,nxt,mode=mode,observed=True):continue
                    # Native voluntary restrictions include fear and bindings.
                    path=(*paths[key],nxt)
                    if not path_allowed(engine,actor,path):continue
                    amount=spent+step_cost(engine,actor,cell,nxt,mode,difficult)
                    crosses=passed or bool(set(engine._actor_volume(actor,nxt))&target_cells)
                    nextkey=(nxt,crosses)
                    if amount>feet or amount>=costs.get(nextkey,feet+1):continue
                    costs[nextkey]=amount;paths[nextkey]=path;serial+=1
                    heapq.heappush(queue,(amount,serial,nextkey))
    return out

_MOON=ContextVar('white_heron_moon_traversal',default=None)


def _moon_sweep(engine,actor):
    traversal=_MOON.get()
    if not traversal or traversal[:2]!=(engine,actor.entity_id):return
    _,_,ctx,chosen,affected=traversal
    from ..typed_executor import Context,run_effects
    from .effect_durations import token
    reach=max((_attack_reach(engine,actor,a) for a in _polearm_attacks(engine,actor,None).values()),default=0)
    for key in sorted(chosen-affected):
        foe=engine.state.actors.get(key)
        if not foe or not foe.active or relation(engine,actor,foe)!=ENEMY or engine._distance_actor_to_actor(actor,foe)>reach:continue
        if engine.cover_from(engine._actor_volume(actor),actor.entity_id,foe)['blocked']:continue
        affected.add(key)
        run_effects(Context(engine,actor,ctx.action,ctx.intent,ctx.typed,[foe],foe,{},save_geometry={'origin_ids':[actor.entity_id],'range_ft':int(reach)}),[
            {'type':'save','ability':'dex','applies_to':'creatures_in_area','evidence':'Moon over the Reed Sea: Dexterity save',
             'on_fail':[{'type':'damage','applies_to':'target','dice':{'count':10,'sides':8},'damage_types':['slashing','force']},
                 {'type':'reaction_denied','applies_to':'target','expires_on':token('end',foe.entity_id,int(foe.turns_started)+1)},
                 {'type':'moon_push','up_to':15}],
             'on_success':[{'type':'half_damage','applies_to':'target'},
                 {'type':'reaction_denied','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'},
                 {'type':'forced_movement','applies_to':'target','distance_ft':5,'direction':'away'}]}])


@hook('movement_step')
def moon_completed_step(engine,actor,previous,nxt,intent):
    _moon_sweep(engine,actor)
    _stance_entry(engine,actor,previous,nxt,intent)


@hook('forced_movement_step')
def moon_forced_entry(engine,actor,previous,nxt,intent):
    _stance_entry(engine,actor,previous,nxt,intent,forced=True)


def _stance_entry(engine,mover,previous,nxt,intent,*,forced=False):
    from .states import active
    for guard in engine.state.actors.values():
        if (relation(engine,guard,mover)!=ENEMY or not _owns(engine,guard,PREFIX+'moon_over_the_reed_sea') or not guard.turn_flags.get('_round_moon_free_strike')
                or not active(engine,guard,STANCE) or not _available(engine,guard,PREFIX+'moon_over_the_reed_sea')):continue
        from .needle import incapacitated
        outside=engine.state.current_actor_id!=guard.entity_id
        attacks=_polearm_attacks(engine,guard,mover,opportunity=outside)
        if not attacks:continue
        reach=max(_attack_reach(engine,guard,a,opportunity=outside) for a in attacks.values())
        if engine.grid.distance_between_cell_sets(engine._actor_volume(guard),engine._actor_volume(mover,previous))*engine.grid.square_size_ft<=reach:continue
        # Forced movement and source-authored no-OA routes do not provoke.
        # The first eligible physical entry consumes the optional opportunity,
        # even if its owner declines; a prohibited movement creates no use.
        from ..movement_steps import opportunity_exempt
        if forced or opportunity_exempt(engine,mover,guard.entity_id) or incapacitated(guard):continue
        from ..typed_reactions import opportunity_permitted_against
        if not opportunity_permitted_against(engine,guard,mover,uses_reaction=False):continue
        _consume_stance_strike(engine,guard)
        action=_pick(engine,intent,guard,mover,'Moon over the Reed Sea',optional=True,opportunity=outside)
        if action is not None:_granted(engine,guard,action,mover,intent,opportunity=True)

PROGRESS='condition:typed.heron_voluntary_movement'
INTEGRATED='condition:typed.heron_integrated_weapon'


@hook('movement_progress_committed')
def heron_committed_distance(engine,actor,receipt):
    if ('integration' not in _roles(engine,actor) or not receipt.get('voluntary')
            or engine.state.current_actor_id is None):return
    old=next((c for c in actor.conditions.values() if c.condition_id==PROGRESS),None)
    feet=(int(old.data.get('feet') or 0) if old and old.data.get('turn')==_stamp(engine) else 0)+int(receipt['distance_ft'])
    if old:engine._remove_condition_instance(actor,old.instance_id,PREFIX+'crescent_body_integration',expected=old)
    engine._apply_condition(actor,PROGRESS,PREFIX+'crescent_body_integration',actor.entity_id,
        expires_on='END_OF_CURRENT_TURN',data={'feet':feet,'turn':_stamp(engine),'label':'Heron’s Passing Cut: '+str(feet)+' feet of voluntary movement this turn'})


def _integration_records(engine,actor):
    if 'integration' not in _roles(engine,actor):return []
    from .body_modes_scene_resources import effective_body_cl
    out=[]
    for key,action in _ready(engine,actor).items():
        typed=action.parameters['typed'];profile=typed.get('heron_profile') or {}
        out.append({'weapon_id':key,'item':typed['source'],'group':'polearm','source_cl':effective_body_cl(engine,actor),
            'attack_choices':'Constitution; Cultivation Attack Modifier','damage_ability':'CON',
            'path_features':__import__('json').dumps([p for p in profile.get('fist_permissions',[]) if _fist(engine,actor,typed,p)]),
            'damage_types':'normal; Force' if _fist(engine,actor,typed,'heavenly_fist') else 'normal',
            'label':'Crescent-Body Integration: '+action.display_name.removesuffix(' attack')+' is the wielded integrated Polearm; no separate weapon or Sphere is granted.'})
    return out


def _reconcile_integration(engine,actor):
    desired=_integration_records(engine,actor)
    held=[c for c in actor.conditions.values() if c.condition_id==INTEGRATED and c.source_definition_id==PREFIX+'crescent_body_integration']
    if [c.data for c in held]==desired:return
    for c in held:engine._remove_condition_instance(actor,c.instance_id,PREFIX+'crescent_body_integration',expected=c)
    for data in desired:engine._apply_condition(actor,INTEGRATED,PREFIX+'crescent_body_integration',actor.entity_id,expires_on='UNTIL_REMOVED',data=data)


@hook('match_start',priority=100)
def heron_wielded_records(engine):
    for actor in engine.state.actors.values():
        if _owns(engine,actor,PREFIX+'crescent_body_integration'):_reconcile_integration(engine,actor)


@hook('state_event')
def heron_equipment_committed(engine,event):
    if (event.event_type not in ('CONDITION_APPLIED','CONDITION_REMOVED','RESOURCE_SPENT','RESOURCE_GAINED')
            or event.source_definition_id==PREFIX+'crescent_body_integration'):return
    for actor in engine.state.actors.values():
        if _owns(engine,actor,PREFIX+'crescent_body_integration'):_reconcile_integration(engine,actor)


@hook('ac')
def heron_suppressed_ac(engine,actor):
    total=0
    for m in actor.modifiers.values():
        if (m.source_definition_id in (PREFIX+'white_wing_crosses_the_reed_field',PREFIX+'moon_over_the_reed_sea')
                and m.target_field=='armor_class' and m.operation=='ADD'
                and not _available(engine,actor,m.source_definition_id)):
            total-=int(m.value)
    return total or None


@hook('weapon_impairment_allowed')
def heavenly_polearm_integrity(engine,holder,weapon_id,operation,source_id):
    if operation not in ('break','rust','dull','unusable','disarm'):return
    weapon=engine.action_catalog.get(weapon_id);source=engine.action_catalog.get(source_id)
    if (weapon is not None and source is not None and (source.parameters.get('typed') or {}).get('mundane')
            and _fist(engine,holder,weapon.parameters.get('typed') or {},'heavenly_fist')):return False


@hook('object_attack_sources')
def heron_object_profiles(info):
    if PREFIX+'crescent_body_integration' not in info['owned_ids']:return
    return [a for a in info['actions'] if a.economy.value=='ACTION' and '#' not in a.source_definition_id
            and _polearm(a.parameters.get('typed') or {})]


@hook('weapon_variant_parent')
def heron_object_parent(parameters):
    profile=(parameters.get('typed') or {}).get('object_attack_profile')
    if profile and profile.get('heron_profile') and _polearm(profile):return parameters.get('object_source_weapon')


@hook('object_strike_profile')
def heron_object_strike(ctx,obj,index):
    from dataclasses import replace
    from types import SimpleNamespace
    from ..gate2_runtime_models import DiceSpec
    original=ctx.typed.get('object_attack_profile')
    if not original or not _polearm(original) or 'integration' not in _roles(ctx.engine,ctx.actor):return
    if ctx.action.parameters.get('object_source_weapon') not in _ready(ctx.engine,ctx.actor):
        raise ValueError('This object strike requires the wielded integrated Polearm.')
    from ..object_rules import label
    target=SimpleNamespace(entity_id=obj.object_id,display_name=label(obj))
    strike=replace(ctx,typed=original,attack_effect=next((e for e in original.get('effects',[]) if e.get('type')=='attack'),None))
    spec={'typed':original,'attack_bonus':int(original['numbers']['attack_bonus']),'damage':DiceSpec(**original['weapon']['damage'])}
    heron_strike_profile(strike,target,{},spec,index)
    from .hand_occupancy import versatile_die_sides
    physical=ctx.engine.action_catalog.get(ctx.action.parameters.get('object_source_weapon'))
    if physical is not None:
        sides=versatile_die_sides(ctx.engine,ctx.actor,physical)
        if sides is not None:spec['damage']=spec['damage'].model_copy(update={'sides':sides})
    weapon=copy.deepcopy(original['weapon']);weapon['damage']=spec['damage'].model_dump(mode='json')
    if _fist(ctx.engine,ctx.actor,original,'heavenly_fist'):
        from .needle import ask,checkpoint_id
        kinds=list(dict.fromkeys([str(weapon.get('damage_type') or 'SLASHING').upper(),'FORCE']))
        picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'heron_object_type',obj.object_id,index),ctx.actor,
            'choice:needle.heron_heavenly_type',kinds,preferred=kinds[:1],target_id=obj.object_id,name='Heavenly Fist',
            prompt=f'Heavenly Fist: choose normal or Force damage against {label(obj)}. No extra cost.')
        if picked:weapon['damage_type']=picked[0]
    return {'weapon':weapon,'attack_bonus':spec['attack_bonus']}


@hook('object_hit_modifiers')
def heavenly_polearm_object(ctx,obj,packets):
    original=ctx.typed.get('object_attack_profile')
    if not original or not _fist(ctx.engine,ctx.actor,original,'heavenly_fist'):return
    component=obj.component or {};level=component.get('source_cl')
    from .body_modes_scene_resources import effective_body_cl
    if (obj.unattended and type(level) is int and component.get('source_rule')
            and not component.get('physical_force_immune') and level<=effective_body_cl(ctx.engine,ctx.actor)):
        protected=set(component.get('protected_defenses') or ())
        if component.get('artifact'):protected.update(('threshold','resistance'))
        result={}
        if 'damage_multiplier' not in protected:result['multiplier']=2
        if 'threshold' not in protected:result['ignore_threshold']=True
        if 'resistance' not in protected:result['ignore_resistance_types']=('BLUDGEONING','PIERCING','SLASHING','FORCE')
        return result or None


@hook('object_attack_max_reach')
def heron_object_range(info,action):
    if PREFIX+'crescent_body_integration' not in info['owned_ids'] or not _polearm(action.parameters.get('typed') or {}):return
    return int(action.range_ft or 5)+(10 if PREFIX+'white_wing_crosses_the_reed_field' in info['owned_ids'] else 5)

_GRANTED=ContextVar('white_heron_granted_attack',default=None)


@hook('attack_resolved')
def heron_granted_outcome(ctx,target,hit,attack):
    frame=_GRANTED.get()
    if (frame and target is not None and frame[:4]==(ctx.engine,ctx.actor.entity_id,target.entity_id,ctx.action.source_definition_id)
            and ctx.typed.get('granted_attack') and attack.get('granted_attack_root')):
        frame[4].append(bool(hit))


@hook('save_bonus_details')
def heron_physical_sweep_cover(engine,target,ability,dc,source_id,intent):
    if ability!='DEX':return
    action=engine.action_catalog.get(source_id)
    source=((action.parameters or {}).get('typed') or {}).get('source') if action else source_id
    if source not in (REAPING,PREFIX+'moon_over_the_reed_sea'):return
    context=engine.d20_context() or {};origins=context.get('effect_origin_cells') or []
    if not origins:return
    bonus=engine.cover_from(origins,context.get('source_actor_id'),target)['bonus']
    return {'bonus':bonus,'contributions':{'cover':bonus}} if bonus else None


def _route_choice(ctx,proposed,feet,*,through=None,moon=False):
    """Player-owned route choice, including detours and revisiting open squares.

    The native menu proposes one economical route; the waypoint choice keeps
    every legal continuous route within the printed distance reachable. Queries
    never move an actor or create a movement receipt.
    """
    from .needle import ask,checkpoint_id,cell_id
    from ..granted_movement import Route
    from ..gate2_runtime_models import Position
    from ..flight import step_allowed,step_cost,profile
    from ..creature_passage import geometry
    from ..voluntary_movement import path_allowed
    from itertools import product
    engine,actor=ctx.engine,ctx.actor
    pick=ask(engine,ctx.intent,checkpoint_id(engine,'heron_route',ctx.source),actor,
        'choice:needle.heron_route',['proposed','waypoints'],preferred=['proposed'],labels={'proposed':'Follow the proposed legal route',
            'waypoints':'Choose each step, within the same movement limit'},target_id=actor.entity_id,
        name=ctx.action.display_name,prompt=f'{ctx.action.display_name}: follow the proposed route or choose each step? No extra cost.')
    if not pick or pick[0]=='proposed':return proposed
    mode=proposed.mode
    if profile(engine,actor).speed_ft:
        selected=ask(engine,ctx.intent,checkpoint_id(engine,'heron_route_mode',ctx.source),actor,
            'choice:needle.heron_route_mode',['walk','fly'],preferred=['walk'],labels={'walk':'Move on ground or permitted surfaces','fly':'Use your actual Fly Speed'},
            target_id=actor.entity_id,prompt=f'{ctx.action.display_name}: choose your movement mode for this route.')
        mode=(selected or ['walk'])[0]
    path=[actor.position];spent=0;crossed=not through
    target=engine.state.actors.get(through) if through else None
    with _route_scope(engine,actor,through=through,moon=moon):
        while spent<=feet:
            current=path[-1]
            from ..target_knowledge import actors_for
            occupied={p for other in actors_for(engine,actor) if other.active and other.entity_id!=actor.entity_id
                      for p in engine._actor_volume(other)}
            free=not bool(set(engine._actor_volume(actor,current))&occupied)
            options={};costs={}
            difficult=engine._hostile_difficult_cells(actor)|geometry(engine,actor,observed=True)[2]
            for dx,dy,dz in product((-1,0,1),repeat=3):
                if not (dx or dy or dz):continue
                x,y,z=current.x+dx,current.y+dy,current.z+dz
                if z<0 or not engine.grid.in_bounds((x,y)):continue
                cell=Position(x=x,y=y,z=z)
                if not step_allowed(engine,actor,current,cell,mode=mode,observed=True) or not path_allowed(engine,actor,[*path,cell]):continue
                cost=step_cost(engine,actor,current,cell,mode,difficult)
                if spent+cost<=feet:options[cell_id(cell)]=cell;costs[cell_id(cell)]=cost
            labels={k:'Step to '+k.removeprefix('cell:') for k in options}
            if free and crossed and (moon or spent>=5):labels={'finish':'End this route here',**labels}
            if len(path)>1:labels['undo']='Undo the last planned step'
            if not labels:return proposed
            selected=ask(engine,ctx.intent,checkpoint_id(engine,'heron_waypoint',ctx.source,len(path)),actor,
                'choice:needle.heron_waypoint',list(labels),preferred=list(labels)[:1],labels=labels,target_id=actor.entity_id,name=ctx.action.display_name,
                prompt=f'{ctx.action.display_name}: {feet-spent} feet remain. Choose the next legal step or finish in a free space.')
            key=(selected or list(labels))[0]
            if key=='finish':return Route(tuple(path),mode)
            if key=='undo':
                last=path.pop();spent-=step_cost(engine,actor,path[-1],last,mode,difficult)
                crossed=not through or any(set(engine._actor_volume(actor,c))&set(engine._actor_volume(target)) for c in path[1:])
                continue
            path.append(options[key]);spent+=costs[key]
            if target and set(engine._actor_volume(actor,path[-1]))&set(engine._actor_volume(target)):crossed=True
    return proposed


def _consume_stance_strike(engine,actor):
    actor.turn_flags.pop('_round_moon_free_strike',None)
    c=next((c for c in actor.conditions.values() if c.condition_id=='condition:typed.state.'+STANCE
        and c.source_definition_id==PREFIX+'moon_over_the_reed_sea'),None)
    if c is not None and c.data.get('strike_available'):
        engine._update_condition_data(actor,c,{**c.data,'strike_available':0},PREFIX+'moon_over_the_reed_sea')


@hook('match_start',priority=200)
def restore_moon_entry_allowance(engine):
    for actor in engine.state.actors.values():
        if (_owns(engine,actor,PREFIX+'moon_over_the_reed_sea') and any(c.condition_id=='condition:typed.state.'+STANCE
                and c.source_definition_id==PREFIX+'moon_over_the_reed_sea' and c.data.get('strike_available')==1
                for c in actor.conditions.values())):
            actor.turn_flags['_round_moon_free_strike']=1


@hook('ac')
def imported_moon_stance_ac(engine,actor):
    from .states import active
    if (not _owns(engine,actor,PREFIX+'moon_over_the_reed_sea') or not active(engine,actor,STANCE)
            or not _available(engine,actor,PREFIX+'moon_over_the_reed_sea')):return
    if not any(m.source_definition_id==PREFIX+'moon_over_the_reed_sea' and m.target_field=='armor_class'
               and m.operation=='ADD' for m in actor.modifiers.values()):return 2

_JOURNEY_MOON=ContextVar('white_heron_journey_moon',default=None)


def _journey_moon_available(session,aid):
    from .body_modes_scene_resources import feature_owned,journey_available
    from ..journey_equipment import projection
    actor=session.state['actors'][aid];source=PREFIX+'moon_over_the_reed_sea'
    if not feature_owned(actor['bundle'],source) or not journey_available(session,aid,source,18):return False
    if actor['resources'].get(STAMINA,0)<7:return False
    ps=heron_scene_profile(actor['bundle']) or []
    if not ps or any(actor['resources'].get(r,0)<1 for r in ps[0]['scene_limits']):return False
    engine,creature=projection(session,aid)
    from .hand_occupancy import weapon_allowed
    return any(weapon_allowed(engine,creature,a) is not False for a in _ready(engine,creature).values())


@hook('journey_step')
def moon_journey_surfaces(session,aid,old,nxt,regions):
    if _JOURNEY_MOON.get()==(id(session),aid):
        return {'supported_kinds':['water','river','vertical_surface','cliff'],'ignore_slowing':['water','river','vertical_surface','cliff']}


@hook('journey_granted_passage')
def moon_journey_passage(session,aid,other):
    if _JOURNEY_MOON.get()==(id(session),aid):return 'difficult'


@hook('journey_properties')
def moon_journey_transit_support(session,aid):
    if _JOURNEY_MOON.get()==(id(session),aid):return {'flight_hover':1}


@hook('journey_options')
def moon_journey_options(session,aid):
    if not _journey_moon_available(session,aid):return
    from ..gate2_runtime_models import Position
    from ..journey_granted_movement import step_cost,speed
    from itertools import product
    import heapq
    actor=session.state['actors'][aid];start=Position.model_validate(actor['position'])
    budget=2*speed(session,aid)
    costs={start:0};paths={start:[start]};queue=[(0,0,start)];serial=0
    token=_JOURNEY_MOON.set((id(session),aid))
    try:
        while queue:
            spent,_,cell=heapq.heappop(queue)
            if spent!=costs[cell]:continue
            for dx,dy,dz in product((-1,0,1),repeat=3):
                if not (dx or dy or dz):continue
                x,y,z=cell.x+dx,cell.y+dy,cell.z+dz
                if z<0 or z>start.z+budget//5 or not session.grid.in_bounds((x,y)):continue
                nxt=Position(x=x,y=y,z=z)
                try:amount=spent+step_cost(session,aid,cell,nxt)
                except ValueError:continue
                if amount>budget or amount>=costs.get(nxt,budget+1):continue
                costs[nxt]=amount;paths[nxt]=[*paths[cell],nxt];serial+=1;heapq.heappush(queue,(amount,serial,nxt))
    finally:_JOURNEY_MOON.reset(token)
    from ..journey_granted_movement import occupied,footprint
    return [{'id':f'heron_moon:{cell.x},{cell.y},{cell.z}','kind':'heron_moon',
        'payload':{'path':[p.model_dump(mode='json') for p in path]},'auto_select':0,
        'label':f"{actor['name']}: Moon over the Reed Sea to ({cell.x}, {cell.y}), {cell.z*5} feet high; "
                f"{costs[cell]} of {budget} feet, 7 Stamina, one Action (6 seconds), once this scene. "
                '+2 AC, +5 feet Polearm reach and one free entry Opportunity Attack until your next turn.'}
        for cell,path in sorted(paths.items(),key=lambda item:(costs[item[0]],item[0].z,item[0].y,item[0].x))
        if session.grid.volume_legal(cell,footprint=footprint(session,aid),occupied_cells=occupied(session,aid))]


@hook('journey_command')
def moon_journey_command(session,aid,kind,payload):
    if kind!='heron_moon':return
    from ..journey import require
    from ..journey_granted_movement import resolve,speed
    from .body_modes_scene_resources import AUTHORITY,complete_journey_activation
    from .journey_flight import settle
    import json
    require(set(payload)=={'path'} and _journey_moon_available(session,aid),'Moon over the Reed Sea requires its acquired source, a wielded Polearm, 7 Stamina and an unspent scene use.')
    actor=session.state['actors'][aid];source=PREFIX+'moon_over_the_reed_sea';start=len(session.state['events'])
    token=_JOURNEY_MOON.set((id(session),aid))
    try:
        # The outer journey revision transaction discards all changes on an
        # invalid route. The source owns payment; the shared helper owns travel.
        actor['resources'][STAMINA]-=7
        session.emit('RESOURCE_SPENT',aid,source=source,resource_id=STAMINA,amount=7)
        state=actor.setdefault('source_states',{}).setdefault(AUTHORITY,{})
        record=state.setdefault('records',{}).get(SOURCE,{})
        balances={}
        for resource in heron_scene_profile(actor['bundle'])[0]['scene_limits']:
            actor['resources'][resource]-=1;balances[resource]=actor['resources'][resource]
            session.emit('RESOURCE_SPENT',aid,source=source,resource_id=resource,amount=1)
        record['scene_limits']=balances
        resolve(session,aid,payload['path'],feet=2*speed(session,aid),source=source,seconds=6)
        model={'condition_id':'condition:typed.state.'+STANCE,'source_definition_id':source,'source_actor_id':aid,
               'data':{'label':'Moon over the Reed Sea: +2 AC, +5 feet reach, one free entry Opportunity Attack until your next turn',
                       'name':STANCE,'strike_available':1,'journey_until_next_turn':1}}
        effects=state.setdefault('effects',[])
        effects[:]=[r for r in effects if not (r['kind']=='condition' and json.loads(r['model'])['condition_id']==model['condition_id'])]
        effects.append({'kind':'condition','model':json.dumps(model,sort_keys=True),'remaining_num':6,'remaining_den':1})
        complete_journey_activation(session,aid,source,start)
    finally:_JOURNEY_MOON.reset(token)
    settle(session,aid)
    return True


@hook('turn_start',priority=-190)
def moon_journey_stance_next_turn(engine,actor):
    for c in list(actor.conditions.values()):
        if c.condition_id=='condition:typed.state.'+STANCE and c.data.get('journey_until_next_turn')==1:
            engine._remove_condition_instance(actor,c.instance_id,PREFIX+'moon_over_the_reed_sea',expected=c)


def _delivered_polearm(ctx,attack=None):
    """Exact public weapon delivery, including native attached weapon profiles.

    Unarmed/cultivation-only packets cannot borrow carried gear metadata. The
    actual delivery must identify the owner's real currently wielded Polearm.
    """
    from .weapon_hits import is_weapon_hit,weapon_identity
    if not is_weapon_hit(ctx,attack or ctx.attack_effect or {}):return False
    identity=weapon_identity(ctx)
    base=_ready(ctx.engine,ctx.actor).get(identity)
    return base is not None and _polearm(base.parameters.get('typed') or {})


def _polearm_spec(engine,actor,spec):
    from ..attack_provenance import describe
    packet=describe(engine,actor,spec,spec.get('resolution_source_id') or spec.get('source_definition_id'))
    if packet['delivery']!='weapon':return False
    base=_ready(engine,actor).get(packet.get('weapon_source_id'))
    return base is not None and _polearm(base.parameters.get('typed') or {})


@hook('compile_bundle',priority=50)
def bind_integrated_delivery_profiles(bundle,info):
    if not heron_scene_profile(bundle):return
    from ..weapon_delivery import weapon_variant_base
    actions={a['source_definition_id']:a for a in bundle['action_catalog']}
    from .body_modes_scene_resources import feature_owned
    if feature_owned(bundle,PREFIX+'one_legged_guard'):
        for action in actions.values():
            typed=(action.get('parameters') or {}).get('typed') or {}
            if _polearm(typed):typed['manual_inline_choice']=True
    for raw in actions.values():
        params=raw.get('parameters') or {};typed=params.get('typed') or {}
        identity=typed.get('delivered_by') or typed.get('weapon_source_id') or typed.get('opportunity_of') or weapon_variant_base(params)
        base=actions.get(str(identity)) if identity else None
        profile=((base or {}).get('parameters',{}).get('typed') or {}).get('heron_profile')
        if profile and typed.get('weapon'):
            typed['heron_profile']=copy.deepcopy(profile)
    return bundle


@hook('cell_action_destinations')
def moon_native_destinations(engine,actor,action):
    if not action.parameters.get('moon_reed'):return
    if not _owns(engine,actor,PREFIX+'moon_over_the_reed_sea') or not _available(engine,actor,PREFIX+'moon_over_the_reed_sea') or not _ready(engine,actor):return []
    from ..gate2_runtime_models import Position
    return [Position(x=x,y=y,z=z) for x,y,z in sorted(_moon_paths(engine,actor),key=lambda p:(p[2],p[1],p[0]))]


@hook('cell_candidate_metadata')
def moon_route_metadata(engine,actor,action,destination):
    if not action.parameters.get('moon_reed'):return
    path=_moon_paths(engine,actor).get((destination.x,destination.y,destination.z))
    if path is None:return {'expected_damage':0,'hostiles_in_area':0,'empty_area':True}
    from ..target_knowledge import actors_for
    reach=max((_attack_reach(engine,actor,a) for a in _polearm_attacks(engine,actor,None).values()),default=0)
    targets={foe.entity_id for foe in actors_for(engine,actor) if foe.active and relation(engine,actor,foe)==ENEMY
             and any(engine.grid.distance_between_cell_sets(engine._actor_volume(actor,cell),engine._actor_volume(foe))*engine.grid.square_size_ft<=reach
                 and not engine.cover_from(engine._actor_volume(actor,cell),actor.entity_id,foe)['blocked'] for cell in path)}
    return {'expected_damage':45*len(targets),'hostiles_in_area':len(targets),'empty_area':not bool(targets)}


@hook('movement_segment_surcharge')
def white_wing_hit_space_cost(engine,actor,previous,nxt,mode):
    scope=_route_mode(engine,actor)
    if not scope or not scope[2]:return
    target=engine.state.actors.get(scope[2])
    if target is None or target.active:return
    if not (set(engine._actor_volume(actor,nxt))&set(engine._actor_volume(target))):return
    # A lethal triggering hit does not erase the printed difficult traversal
    # through its space. Do not stack difficult terrain over existing terrain.
    from ..creature_passage import geometry
    difficult=engine._hostile_difficult_cells(actor)|geometry(engine,actor,observed=True)[2]
    if engine.grid.movement_step_multiplier(previous,nxt,footprint=engine._footprint(actor),difficult_cells=difficult)>1:return
    return engine.grid.square_size_ft


@hook('attack_line_turn_key')
def reaping_turn_identity(engine,actor,mechanic):
    if mechanic==REAPING and _owns(engine,actor,REAPING):return _stamp(engine)


def _passing_affordable(engine,actor):
    return engine._can_pay(actor,((STAMINA,1),),source_id=PREFIX+'crescent_body_integration')


def _body_numbers(info):
    """Existing Path profile; explicit effective CL precedes NS1R attainment."""
    numbers=dict(info.get('numbers') or {})
    paths=(info.get('owner_sheet',{}).get('path_and_subpath') or {}).get('paths') or []
    if isinstance(paths,dict):paths=list(paths.values())
    body=next((p for p in paths if isinstance(p,dict) and p.get('path_id')=='tianxia.path.body_refining'),None)
    if body is None:return numbers
    profile=acquire_heron(SOURCE,info['owner_sheet'])
    numbers['cl']=profile['effective_cl']
    key=str(body.get('key_ability') or 'CON').upper()[:3]
    numbers['key_mod']=int((info.get('mods') or numbers.get('ability_mods') or {}).get(key,0))
    numbers['attack_bonus']=int(numbers['pb'])+numbers['key_mod']
    numbers['save_dc']=8+numbers['attack_bonus']
    return numbers


@hook('compile_actions',priority=100)
def heron_passive_source_numbers(info):
    if not set(info['owned_ids']).intersection(FEATURE_LEVELS):return
    numbers=_body_numbers(info)
    for row in info['passives']:
        if row.get('feature_id') in FEATURE_LEVELS:
            row.update(cl=int(numbers['cl']),pb=int(numbers['pb']),save_dc=int(numbers['save_dc']))


@hook('attack_packet_resolved')
def passing_cut_completed_packet(engine,target,provenance,intent):
    actor=engine.state.actors.get(provenance.attacker_id)
    if actor is None:return
    for c in list(actor.conditions.values()):
        if (c.condition_id!='condition:typed.heron_passing_cut_pending' or c.data.get('roll_id')!=provenance.roll_id
                or c.data.get('target_id')!=target.entity_id or c.data.get('source_id')!=provenance.source_id):continue
        engine._remove_condition_instance(actor,c.instance_id,PREFIX+'crescent_body_integration',expected=c)
        from .body_modes_scene_resources import notify_paid
        notify_paid(engine,actor,PREFIX+'crescent_body_integration','INTENT_ACCEPTED')


@hook('native_attack_reactions')
def heron_native_declaration(engine,attacker,target,source,spec):
    feature=PREFIX+'one_legged_guard'
    if spec.get('range_ft') is not None:return
    if any(_owns(engine,a,feature) and _available(engine,a,feature) for a in engine.state.actors.values()):
        return [feature]


@hook('status_description')
def integrated_polearm_description(engine,holder,row,data):
    if (row.get('condition_id')!=INTEGRATED or row.get('source_definition_id')!=PREFIX+'crescent_body_integration'
            or row.get('source_actor_id')!=holder.entity_id):return
    import json
    permissions=data.get('path_features') or []
    if isinstance(permissions,str):permissions=json.loads(permissions)
    text=('You are proficient with this wielded Polearm. Use Constitution for attack and damage, or your Cultivation '
        'Attack Modifier to attack. Its reach increases by 5 feet during your turn; White Wing adds another 5 feet if active. ')
    if 'heavenly_fist' in permissions:
        text+=('It counts as magical, cultivation-powered and adamantine, and can deal Force. Mundane weapon impairment cannot '
            'break or disable it while wielded. Against unattended objects with Source CL no higher than yours, your Body attacks '
            'deal double damage and ignore Bludgeoning, Piercing, Slashing and Force Resistance and Damage Threshold. '
            'Immunity and explicitly protected defenses still apply. ')
    elif 'refined_iron_fist' in permissions:
        text+='It counts as magical and cultivation-powered against Resistance and Immunity. '
    return {'rules':text+'Integration grants no Sphere or additional attack.',
        'duration':'While wielded and the relevant Body feature is available. No Action or Stamina cost.'}
