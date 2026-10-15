"""Returning-Heaven Momentum Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Returning-Heaven Momentum Body (Momentum and the features, with their Normalized
Procedures). Momentum (resource:named.momentum, maximum PB, PB + 3 with Avalanche Meridian Circuit) is gained by
combat/ext/subpath_pools.py. Owned rows: ``{"type": "path_passive", "kind": "momentum", "role": "gather" | "store" |
"avalanche"}``; Store Impact is the compiled Reaction; Heaven-Returning Impact's action runs ``heaven_returning_impact``.

Gather and Return  once per turn after an unarmed hit, 1 Momentum (asked): + 1d8 Bludgeoning or Force (2d8 at CL11, 3d8 at
                   CL17) and one choice: push 5 feet, move 5 feet without provoking, +1 AC against it until your next turn, or
                   + 5 feet on the next push or pull you impose this turn. With Avalanche Meridian Circuit: 1 to 3 Momentum,
                   one asked choice per point (another die, 5 more feet of push, 5 feet of movement), repeats allowed.
Store the Collision  Store Movement (asked when a hostile push or pull is about to move you): your Reaction and 1 Stamina, 15 feet
                   less; at 0 feet the same effect's Prone does not land and you gain 1 Momentum. Store Impact is its compiled
                   Reaction (2d8 + CON off Bludgeoning, Force or Thunder damage; 1 Momentum when that brings it to 0). Once per
                   round between them.
Heaven-Returning Impact  move to the aimed space (a physical route, no Opportunity Attacks), then each creature within 5 feet of
                   the straight line from where you started makes a Dexterity save against one 6d10 + 1d10 per Momentum spent
                   Force roll: failure, full damage, pushed 20 feet away from the line, Prone and no Reactions until its next turn;
                   success, half and pushed 5 feet.
Every hook returns early for a creature without these rows.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.returning_heaven_momentum_body.feature."
MOMENTUM = "resource:named.momentum"
NEXT_PUSH = "condition:typed.gather_next_push"
STORE = PREFIX + "store_the_collision"


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "momentum"}


def _cl(engine: Any, actor: Any) -> int:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor.entity_id), None)
    from ..path_levels import effective_cl
    own_rows = [r for r in getattr(engine,"typed_passive_rows",{}).get(actor.entity_id,[]) if r.get("kind")=="momentum"]
    if own_rows:
        return int(own_rows[0].get("cl") or (bundle or {}).get("cl") or 1)
    sheet = (bundle or {}).get("owner_sheet") or {}
    return effective_cl(sheet, "tianxia.path.body_refining", int((bundle or {}).get("cl") or 1))


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _move(ctx: Any, mover: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from ..granted_movement import routes,resolve_path
    from .needle import cell_id
    found=routes(ctx.engine,mover,feet)
    paths={cell_id(cell):(path,mode) for cell,(path,cost,mode) in found.items()}
    if not paths:
        return
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,"momentum_move",mover.entity_id),mover,choice_id,sorted(paths),
        allow_decline=True,default="decline",labels={key:"Move to "+key.removeprefix("cell:") for key in paths},
        target_id=mover.entity_id,name=name,prompt=f"{name}: {mover.display_name} may move up to {feet} feet without Opportunity Attacks; no additional cost.")
    if picked and picked[0] in paths:
        path,mode=paths[picked[0]]
        resolve_path(ctx.engine,mover,path,PREFIX+'gather_and_return',feet=feet,intent=ctx.intent,provokes=False,mode=mode)


# Gather's declaration is a confirmed-hit choice, before the packet resolves.
@hook("confirmed_hit")
def prepare_gather(engine, actor, target, spec, provenance, intent):
    from ..typed_executor import Context
    from ..gate2_runtime_models import DiceSpec
    from .needle import ask, checkpoint_id
    roles = _roles(engine, actor)
    if provenance.kind != "unarmed" or "gather" not in roles or _cl(engine, actor) < 3:
        return
    if actor.turn_flags.get("_round_gather") == _stamp(engine) or int(actor.resources.get(MOMENTUM, 0)) < 1:
        return
    action = engine.action_catalog[provenance.source_id]
    typed = (action.parameters or {}).get("typed") or {}
    cl = _cl(engine, actor)
    dice = 3 if cl >= 17 else 2 if cl >= 11 else 1
    avalanche = "avalanche" in roles and cl >= 14
    labels = ({"die": f"Add {dice}d8 damage", "push": f"Push {target.display_name} 5 feet", "move": "Move 5 feet without provoking Opportunity Attacks"}
              if avalanche else {"push": f"Push {target.display_name} 5 feet", "move": "Move 5 feet without provoking Opportunity Attacks",
              "ac": f"+1 AC against {target.display_name} until your next turn", "next_push": "+5 feet to your next forced movement this turn"})
    picks = []
    limit = min(3, int(actor.resources[MOMENTUM])) if avalanche else 1
    for index in range(limit):
        picked = ask(engine, intent, checkpoint_id(engine, "gather_prepare", provenance.roll_id, index), actor,
            "choice:needle.gather_and_return", list(labels), labels=labels, allow_decline=True,
            default="decline" if picks else "first", target_id=target.entity_id, name="Gather and Return",
            prompt=f"Gather and Return: {action.display_name} hit {target.display_name}. Spend 1 Momentum for this benefit ({index+1} of {limit})?")
        if not picked or picked[0] not in labels:
            break
        picks.append(picked[0])
    if not picks:
        return
    count = dice * picks.count("die") if avalanche else dice
    kind = "bludgeoning"
    if count:
        picked = ask(engine, intent, checkpoint_id(engine, "gather_type", provenance.roll_id), actor,
            "choice:needle.gather_damage_type", ["bludgeoning", "force"],
            labels={"bludgeoning": "Bludgeoning", "force": "Force"}, target_id=target.entity_id,
            name="Gather and Return", prompt=f"Gather and Return: choose the additional {count}d8 damage type against {target.display_name}.")
        kind = picked[0]
    engine._spend_resource(actor, MOMENTUM, len(picks), PREFIX + "gather_and_return")
    actor.turn_flags["_round_gather"] = _stamp(engine)
    if count:
        roll = engine.roller.roll(DiceSpec(count=count,sides=8,modifier=0), actor_id=actor.entity_id,
            reason="Gather and Return", critical=provenance.critical)
        engine._record_roll(roll)
        spec.setdefault("damage_components", []).append({"amount": int(roll.total), "damage_type": kind.upper()})
    engine.__dict__.setdefault("_momentum_gather_hits", {})[provenance.roll_id] = {
        "push": 5*picks.count("push"), "move": 5*picks.count("move"),
        "ac": "ac" in picks, "next_push": "next_push" in picks}


@hook("hit_final")
def gather_and_return(ctx, target, kind):
    from .. import typed_executor as te
    provenance = ctx.attack_damage_context
    if provenance is None:
        return
    selected = ctx.engine.__dict__.get("_momentum_gather_hits", {}).pop(provenance.roll_id, None)
    if selected is None:
        return
    sub = ctx.on_hit_context(target).with_source(PREFIX+"gather_and_return")
    if selected["push"] and target.active:
        te.run_effects(sub, [{"type":"forced_movement", "applies_to":"target", "distance_ft":selected["push"], "direction":"away"}])
    if selected["move"]:
        _move(sub, ctx.actor, selected["move"], "choice:needle.gather_move", "Gather and Return")
    if selected["ac"]:
        te.run_effects(sub, [{"type":"ac_against", "amount":1, "expires_on":"START_OF_SELF_NEXT_TURN"}])
    if selected["next_push"]:
        ctx.engine._apply_condition(ctx.actor, NEXT_PUSH, PREFIX+"gather_and_return", ctx.actor.entity_id,
            expires_on="END_OF_CURRENT_TURN", data={"label":"Gather and Return: +5 feet to your next forced movement this turn"})


@hook("forced_movement_bonus")
def next_push(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> int:
    held = next((c for c in ctx.actor.conditions.values() if c.condition_id == NEXT_PUSH), None)
    if held is None:
        return 0
    ctx.actor.conditions.pop(held.instance_id)
    ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "gather_and_return", actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                             payload={"condition_id": NEXT_PUSH, "instance_id": held.instance_id, "reason": "CONSUMED"})
    return 5


# ---------------------------------------------------------------------------------------------- Store the Collision
def _store_ready(engine: Any, owner: Any) -> bool:
    from ..typed_executor import condition_rules

    key = "once_per_round:typed." + STORE
    return ("store" in _roles(engine, owner) and _cl(engine, owner) >= 6 and owner.turn_flags.get(key) != int(engine.state.round_number) and owner.active
            and owner.reaction_available and int(owner.resources.get("resource:core.stamina", 0) or 0) >= 1
            and not any(rule.get("no_reactions") for rule in condition_rules(owner)))


@hook("forced_movement_reduction")
def store_movement(ctx: Any, subject: Any) -> int:
    engine = ctx.engine
    if subject is not None:
        ctx.damage_cache.pop(("stored_movement", subject.entity_id, ctx.source), None)
    if subject is None or ctx.actor is subject or not _store_ready(engine, subject) \
            or int(ctx.forced_movement_distance_ft or 0) <= 0:
        return 0
    from .needle import ask, checkpoint_id

    picked = ask(engine, ctx.intent, checkpoint_id(engine, "store_movement", subject.entity_id), subject, "choice:needle.store_the_collision_move", ["store"],
                 labels={"store": "Reaction and 1 Stamina: 15 feet less (at 0, no Prone and 1 Momentum)"}, allow_decline=True,
                 target_id=subject.entity_id, name="Store the Collision",
                 prompt=f"Store the Collision: {ctx.action.display_name} would move {subject.display_name} {ctx.forced_movement_distance_ft} feet.")
    if not picked:
        return 0
    from .. import typed_reactions

    with activation(engine, subject, STORE):
        typed_reactions.open_reaction(engine, {"feature_id": STORE}, subject, (ctx.actor.entity_id,), "FORCED_MOVEMENT")
        typed_reactions.spend_reaction(engine, subject, {"feature_id": STORE})
        subject.turn_flags["once_per_round:typed." + STORE] = int(engine.state.round_number)
        engine._spend_resource(subject, "resource:core.stamina", 1, STORE)
        distance = int(ctx.forced_movement_distance_ft or 0)
        if distance and distance <= 15:
            # Shared only by contexts of this resolving activation, never by the engine
            # or a later use of the same action. The associated Prone rider consumes it.
            ctx.damage_cache[("stored_movement", subject.entity_id, ctx.source)] = True
            from .subpath_pools import gain

            gain(engine, subject, MOMENTUM, STORE, normal=False)
        return 15


@hook("condition_attempt")
def stored_no_prone(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    if subject is None:
        return None
    if str((effect_row or {}).get("condition") or "").lower() != "prone":
        return None
    return False if ctx.damage_cache.pop(("stored_movement", subject.entity_id, ctx.source), False) else None


@effect("momentum_gain")
def momentum_gain(ctx: Any, row: dict[str, Any]) -> None:
    """Store Impact brought the packet to 0: "gain 1 Momentum" (past the round's limit, not past the maximum)."""
    from .subpath_pools import gain

    gain(ctx.engine, ctx.actor, MOMENTUM, STORE, normal=False)


# ------------------------------------------------------------------------------------------ Heaven-Returning Impact
def _line(start: Any, end: Any) -> list[tuple[int, int]]:
    """The squares of the straight segment between two squares (Bresenham)."""
    x0, y0, x1, y1 = start.x, start.y, end.x, end.y
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err, out = dx + dy, []
    while True:
        out.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return out
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


HEAVEN=PREFIX+'heaven_returning_impact'


def _impact_destination(engine,actor,end):
    from .. import senses
    return (end is not None and end!=actor.position and end.z==actor.position.z
        and engine.grid.distance_ft(actor.position,end)<=120
        and engine.grid.volume_legal(end,footprint=engine._footprint(actor),occupied_cells=engine._occupied_volumes_except(actor.entity_id))
        and senses.perceives_cell(engine,actor,end))


@hook('candidate_allowed')
def impact_candidate(engine,actor,candidate,action):
    if action and ((action.parameters or {}).get('typed') or {}).get('source')==HEAVEN:
        return _cl(engine,actor)>=18 and _impact_destination(engine,actor,candidate.destination)
    return None


@hook('pass_through')
def impact_passage(engine,mover,occupant):
    if engine.__dict__.get('_momentum_impact_mover')==mover.entity_id and mover.team_id!=occupant.team_id:
        return 'free'
    return None


def _impact_push(ctx,target,start,end,feet,up_to):
    from math import gcd
    from ..gate2_runtime_models import Position
    from ..movement_paths import resolve
    from .needle import ask,checkpoint_id,cell_id
    from .. import ext
    dx,dy=end.x-start.x,end.y-start.y
    divisor=gcd(abs(dx),abs(dy)) or 1
    px,py=-dy//divisor,dx//divisor
    options={}
    for sign in (-1,1):
        for step in range(1,feet//5+1):
            dest=Position(x=target.position.x+sign*px*step,y=target.position.y+sign*py*step,z=target.position.z)
            distance=int(ctx.engine.grid.distance_ft(target.position,dest))
            if distance>feet or (not up_to and distance!=feet):
                continue
            path=[Position(x=x,y=y,z=target.position.z) for x,y in _line(target.position,dest)]
            if all(ctx.engine.grid.volume_step_legal(a,b,footprint=ctx.engine._footprint(target),
                    occupied_cells=ctx.engine._occupied_volumes_except(target.entity_id)) for a,b in zip(path,path[1:])):
                options[cell_id(dest)]=(path,distance)
    if not options:
        return
    labels={key:f'Push {target.display_name} {dist} feet perpendicular to the line to '+key.removeprefix('cell:') for key,(path,dist) in options.items()}
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'impact_push',target.entity_id),ctx.actor,
        'choice:needle.impact_push',list(options),labels=labels,allow_decline=up_to,target_id=target.entity_id,
        name='Heaven-Returning Impact',prompt=f'Heaven-Returning Impact: choose the perpendicular push for {target.display_name} (up to {feet} feet).')
    if picked:
        path,distance=options[picked[0]]
        resolve(ctx.engine,target,path,ctx.source,kind='forced',feet=distance,intent=ctx.intent,
            source_actor_id=ctx.actor.entity_id,ctx=ctx)


@effect('momentum_impact_push')
def impact_push_effect(ctx,row):
    start,end=ctx.damage_cache['impact_line']
    _impact_push(ctx,ctx.target,start,end,int(row['feet']),bool(row.get('up_to')))


@effect('heaven_returning_impact')
def heaven_returning_impact(ctx,row):
    from .. import typed_executor as te, zones, granted_movement
    from ..gate2_runtime_models import DiceSpec,Position
    from ..object_geometry import target_cells
    from .objects import deal
    from .docket_walls import damage_section,defense_stats
    from . import placed
    engine,actor=ctx.engine,ctx.actor
    start,end=actor.position,ctx.destination
    if not _impact_destination(engine,actor,end):
        raise ValueError('Heaven-Returning Impact needs a visible, unoccupied destination on a straight line within 120 feet.')
    left=int(actor.resources.get(MOMENTUM,0));spent=3+left
    if left:
        engine._spend_resource(actor,MOMENTUM,left,HEAVEN)
    roll=engine.roller.roll(DiceSpec(count=6+spent,sides=10,modifier=0),actor_id=actor.entity_id,reason='DAMAGE:'+HEAVEN)
    engine._record_roll(roll)
    line=[Position(x=x,y=y,z=start.z) for x,y in _line(start,end)]
    hit_objects=set();hit_creatures=set();travelled=[start];blocked=False
    previous=engine.__dict__.get('_momentum_impact_mover')
    engine._momentum_impact_mover=actor.entity_id
    try:
        for cell in line:
            for obj in sorted(engine.state.objects.values(),key=lambda o:o.object_id):
                component=obj.component or {}
                if obj.destroyed or obj.object_id in hit_objects or cell not in target_cells(engine,obj):
                    continue
                eligible=(obj.unattended or component.get('temporary_barrier') or component.get('structure')
                    or component.get('formation_anchor') or obj.object_kind in ('vehicle','terrain_section'))
                if eligible and not component.get('world_scale'):
                    hit_objects.add(obj.object_id)
                    deal(engine,actor,obj,[(2*int(roll.total),'FORCE')],HEAVEN)
                current=engine.state.objects[obj.object_id]
                if not current.destroyed and component.get('blocks'):
                    blocked=True
            for zone in list(engine.state.zones.values()):
                wall=(zone.trigger_profile or {}).get('wall')
                if not zone.active or not wall or cell not in zone.affected_cells:
                    continue
                if (zone.trigger_profile or {}).get('sealed_formation') or (zone.trigger_profile or {}).get('spatial_lock'):
                    blocked=True
                    continue
                key=(zone.zone_id,cell.x,cell.y,cell.z)
                if key not in hit_objects:
                    hit_objects.add(key)
                    stats=defense_stats(ctx,zone)
                    if stats is not None:
                        damage=0 if 'FORCE' in stats['immune'] else 2*int(roll.total)
                        if 'FORCE' in stats.get('resist',[]): damage//=2
                        if 'FORCE' in stats.get('vulnerable',[]): damage*=2
                        damage_section(engine,zone,cell,damage,HEAVEN,'FORCE')
                if zone.active and cell in zone.affected_cells:
                    blocked=True
            if blocked:
                break
            if cell!=actor.position:
                try:
                    granted_movement.resolve_path(engine,actor,[actor.position,cell],HEAVEN,feet=120,intent=ctx.intent,provokes=False)
                except ValueError:
                    break
                if actor.position!=cell:
                    break
                travelled.append(cell)
            for target in sorted(engine.state.actors.values(),key=lambda a:a.entity_id):
                if target is actor or not target.active or target.entity_id in hit_creatures:
                    continue
                if not any(engine.grid.distance_ft(cell,p)<=5 for p in engine._actor_cells(target)):
                    continue
                hit_creatures.add(target.entity_id)
                sub=te.Context(engine,actor,ctx.action,ctx.intent,ctx.typed,[target],target,{'impact_line':(start,end)})
                te.run_effects(sub,[{'type':'save','ability':'dex','on_fail':[
                    {'type':'damage','applies_to':'target','flat':int(roll.total),'damage_types':['force']},
                    {'type':'momentum_impact_push','feet':20,'up_to':True},
                    {'type':'condition','applies_to':'target','condition':'prone'},
                    {'type':'reaction_denied','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'}],
                    'on_success':[{'type':'damage','applies_to':'target','flat':int(roll.total)//2,'damage_types':['force']},
                    {'type':'momentum_impact_push','feet':5}]}])
        if blocked:
            engine._commit_damage(actor,2*_cl(engine,actor),'FORCE',HEAVEN,actor.entity_id,ctx.intent,
                reaction_depth=0,source_flags=('momentum_recoil',))
        zone=placed.place(engine,actor,source=ctx.source,tag='momentum_impact',cells=placed.area(engine,actor.position,'sphere',10),
            name='Heaven-Returning Impact: broken ground (difficult terrain until cleared or repaired)',difficult='all',
            numbers=ctx.numbers,duration_rounds=None,
            extra={'profile':{'repair_tools':['item:tool.shovel','item:tool.masons_tools'], 'repair_work_seconds':60,'source_cl':_cl(engine,actor)}})
        note(engine,HEAVEN,actor,f'Heaven-Returning Impact: spent {spent} Momentum; {6+spent}d10 Force damage ({roll.total}).')
    finally:
        engine._momentum_impact_mover=previous


# Source selection uses the shared installed-sheet journey acquisition contract.
PARENT = PREFIX.removesuffix('.feature.')
BODY = 'tianxia.path.body_refining'
LEVELS = [(3,'gather_and_return'),(6,'store_the_collision'),(10,'rebounding_assault'),
          (14,'avalanche_meridian_circuit'),(18,'heaven_returning_impact')]


def _selection_legal(sheet):
    from ..path_levels import effective_cl
    paths = sheet.get('path_and_subpath') or {}
    return (BODY in paths.get('path_record_ids', ())
        and effective_cl(sheet,BODY,int(sheet['identity']['cultivation_level'])) >= 3
        and not any(str(key).startswith('tianxia.subpath.body.') for key in paths.get('subpath_record_ids', ())))


@hook('journey_acquisition_options')
def momentum_selection_options(session,actor_id,source,sheet):
    if source != PARENT:
        return None
    if PARENT in session.state['actors'][actor_id].get('source_states', {}) or not _selection_legal(sheet):
        return []
    return [{'source':PARENT, 'label':'Choose Returning-Heaven Momentum Body as your Body Refining Subpath (Open School; no resource cost)',
             'payload':{'select':True}}]


@hook('journey_source_sheet')
def momentum_sheet(sheet,session,actor_id):
    from copy import deepcopy
    from ..path_levels import effective_cl
    state=session.state['actors'][actor_id].get('source_states',{}).get(PARENT)
    if not state:
        return None
    paths=sheet.get('path_and_subpath') or {}
    if BODY not in paths.get('path_record_ids', ()):
        return None
    # Never overlay a second or replacement Body progression on a later sheet.
    if any(str(key).startswith('tianxia.subpath.body.') and key != PARENT for key in paths.get('subpath_record_ids', ())):
        raise ValueError('Returning-Heaven cannot coexist with another Body Refining Subpath.')
    result=deepcopy(sheet); fields=result.setdefault('path_and_subpath',{})
    cl=effective_cl(sheet,BODY,int(sheet['identity']['cultivation_level']))
    fields['subpath_record_ids']=list(dict.fromkeys([*(fields.get('subpath_record_ids') or []),PARENT]))
    fields['path_feature_record_ids']=list(dict.fromkeys([*(fields.get('path_feature_record_ids') or []),
        *[PREFIX+name for level,name in LEVELS if level<=cl]]))
    return result


@hook('journey_acquisition')
def momentum_select(session,actor_id,source,payload,sheet):
    if source != PARENT:
        return None
    from ..journey import require
    from ..fact_consent_admission import digest
    actor=session.state['actors'][actor_id]
    require(payload=={'select':True},'Choose the Returning-Heaven Subpath; feature IDs are derived from your Body Refining level.')
    require(not actor['incapacitated'] and _selection_legal(sheet),'Choose one Body Refining Subpath at Body CL3 or higher.')
    require(PARENT not in actor.get('source_states',{}),'Returning-Heaven was already selected.')
    record={'source':PARENT,'actor_id':actor_id,'clock':int(session.clock())}
    record['acquisition_id']=digest(record)
    actor.setdefault('source_states',{})[PARENT]=record
    session.emit('SUBPATH_SELECTED',actor_id,source=PARENT,acquisition_id=record['acquisition_id'])
    return {'sheet':momentum_sheet(sheet,session,actor_id),'acquisition_id':record['acquisition_id']}

REBOUND=PREFIX+'rebounding_assault'


@hook('compile_passives')
def momentum_levels(rows,info):
    from ..path_levels import effective_cl
    cl=effective_cl(info.get('owner_sheet') or {},BODY,int(info['numbers'].get('cl') or 1))
    rows=[{**r,'cl':cl,'momentum_con':next((int(a.get('modifier',0)) for a in ((info.get('owner_sheet') or {}).get('ability_scores_and_statistics') or {}).get('abilities',[]) if str(a.get('ability','')).upper()=='CON'),0)} if r.get('kind')=='momentum' else r for r in rows]
    return rows


@hook('reaction_rows')
def replace_rebound(engine,actor_id,block,rows):
    actor=engine.state.actors.get(actor_id)
    if actor and 'rebound' in _roles(engine,actor):
        return [r for r in rows if r.get('feature_id') != REBOUND]
    return rows


@hook('pass_through')
def rebound_passage(engine,mover,occupant):
    if engine.__dict__.get('_momentum_passage') == (mover.entity_id,occupant.entity_id):
        return 'difficult'
    return None


def _rebound(engine,owner,other,intent):
    from .. import typed_reactions,typed_executor as te,granted_movement as movement
    from .needle import ask,checkpoint_id,cell_id
    from copy import deepcopy
    if ('rebound' not in _roles(engine,owner) or _cl(engine,owner)<10 or not owner.active or not other.active
            or owner.team_id==other.team_id or engine._distance_actor_to_actor(owner,other)>60
            or int(owner.resources.get(MOMENTUM,0))<2
            or owner.turn_flags.get('_round_rebound')==engine.state.round_number
            or not typed_reactions.can_use_reaction(engine,owner,other,{'feature_id':REBOUND})):
        return
    chosen=ask(engine,intent,checkpoint_id(engine,'rebound',owner.entity_id,other.entity_id),owner,
        'choice:needle.rebounding_assault',['use'],labels={'use':'Reaction and 2 Momentum: approach '+other.display_name},
        allow_decline=True,target_id=other.entity_id,name='Rebounding Assault',
        prompt=f'Rebounding Assault: after {other.display_name} resolves its effect, spend your Reaction and 2 Momentum to move up to your Speed without Opportunity Attacks, then make one unarmed strike if it is in reach?')
    if not chosen:
        return
    with activation(engine,owner,REBOUND):
        typed_reactions.open_reaction(engine,{'feature_id':REBOUND},owner,(other.entity_id,),'AFTER_EFFECT')
        typed_reactions.spend_reaction(engine,owner,{'feature_id':REBOUND})
        engine._spend_resource(owner,MOMENTUM,2,REBOUND)
        owner.turn_flags['_round_rebound']=engine.state.round_number
        previous=engine.__dict__.get('_momentum_passage')
        engine._momentum_passage=(owner.entity_id,other.entity_id)
        try:
            routes=movement.routes(engine,owner,engine._effective_speed(owner))
            paths={cell_id(cell):(path,mode) for cell,(path,cost,mode) in routes.items()
                if all(engine.grid.distance_ft(b,other.position)<engine.grid.distance_ft(a,other.position)
                       for a,b in zip(path,path[1:]))}
            if paths:
                step=ask(engine,intent,checkpoint_id(engine,'rebound_path',owner.entity_id),owner,
                    'choice:needle.rebound_move',list(paths),labels={key:'Move closer to '+other.display_name+' at '+key.removeprefix('cell:') for key in paths},
                    allow_decline=True,target_id=other.entity_id,name='Rebounding Assault',
                    prompt=f'Rebounding Assault: choose a route that approaches {other.display_name} on every segment. No Opportunity Attacks.')
                if step and step[0] in paths:
                    path,mode=paths[step[0]]
                    movement.resolve_path(engine,owner,path,REBOUND,feet=engine._effective_speed(owner),intent=intent,provokes=False,mode=mode)
        finally:
            engine._momentum_passage=previous
        strikes=[a for a in engine.action_catalog.values() if a.owner_id==owner.entity_id
            and any(e.get('type')=='attack' and e.get('attack_kind')=='unarmed'
                    for e in ((a.parameters or {}).get('typed') or {}).get('effects',[]))]
        if strikes:
            action=sorted(strikes,key=lambda a:a.source_definition_id)[0]
            typed=deepcopy(action.parameters['typed'])
            attack=next(e for e in typed['effects'] if e.get('type')=='attack' and e.get('attack_kind')=='unarmed')
            if typed_reactions.attack_reaches(engine,owner,other,attack,action=action):
                attack.update(count=1,granted_attack_root=True)
                attack['on_hit']=[*(attack.get('on_hit') or []),{'type':'momentum_rebound_hit'}]
                typed.update(effects=[attack],granted_attack=True,reaction_attack=True,momentum_rebound=True)
                te.run_effects(te.Context(engine,owner,action,intent,typed,[other],other,{}),[attack])
        engine._append_event('REACTION_RESOLVED',REBOUND,actor_id=owner.entity_id,target_ids=(other.entity_id,),payload={'checkpoint':'AFTER_EFFECT'})


@hook('confirmed_hit')
def rebound_packet(engine,actor,target,spec,provenance,intent):
    if (spec.get('typed') or {}).get('momentum_rebound') and 'rebound' in _roles(engine,actor):
        spec.setdefault('damage_components',[]).append({'amount':int(actor.proficiency_bonus),'damage_type':'FORCE'})


@effect('momentum_rebound_hit')
def rebound_hit(ctx,row):
    from .needle import ask,checkpoint_id
    from ..typed_executor import run_effects
    target=ctx.target
    if target is None or not target.active:
        return
    choice=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'rebound_hit',target.entity_id),ctx.actor,
        'choice:needle.rebound_hit',['push','prone'],labels={'push':'Push '+target.display_name+' 10 feet directly away','prone':'Knock '+target.display_name+' Prone'},
        name='Rebounding Assault',target_id=target.entity_id,prompt=f'Rebounding Assault hit {target.display_name}: choose a 10-foot push or Prone. No collision damage is created.')
    run_effects(ctx,[{'type':'forced_movement','applies_to':'target','distance_ft':10,'direction':'away'}]
                if choice[0]=='push' else [{'type':'condition','applies_to':'target','condition':'prone'}])


@hook('attack_completed')
def rebound_attack(engine,notice,intent):
    owner=engine.state.actors.get(notice.target_id); other=engine.state.actors.get(notice.attacker_id)
    if owner is None or other is None or not notice.melee:
        return
    damaged=False
    for event in reversed(engine.events):
        if event.event_type=='ATTACK_ROLLED' and event.actor_id==other.entity_id:
            break
        if event.event_type=='DAMAGE_COMMITTED' and event.actor_id==other.entity_id and owner.entity_id in event.target_ids and int(event.payload.get('reduced_to',0))>0:
            damaged=True
    if not notice.hit or damaged:
        _rebound(engine,owner,other,intent)


@hook('action_completed')
def rebound_displacement(engine,actor,economy,source_definition_id):
    moved=set()
    for event in reversed(engine.events):
        if event.event_type=='INTENT_ACCEPTED':
            break
        if (event.event_type=='MOVEMENT_COMMITTED' and event.source_definition_id==source_definition_id
                and event.payload.get('forced') and len(event.payload.get('path') or [])>1):
            moved.add(event.actor_id)
    for actor_id in sorted(moved):
        owner=engine.state.actors.get(actor_id)
        if owner:
            _rebound(engine,owner,actor,getattr(engine,'_active_intent',None))

@hook('reaction_rows')
def replace_store_impact(engine,actor_id,block,rows):
    actor=engine.state.actors.get(actor_id)
    if actor and 'store' in _roles(engine,actor):
        return [r for r in rows if r.get('feature_id')!=STORE]
    return rows


@hook('final_damage')
def store_impact(engine,owner,pending,kind,source,source_actor_id,intent):
    from ..pending_damage import current,packet_scratch
    from .. import typed_reactions
    from ..gate2_runtime_models import DiceSpec
    from .needle import ask,checkpoint_id
    packet=current(engine)
    kinds={str(kind).upper(), *[str(p['damage_type']).upper() for p in (packet.components if packet else ()) if p['amount']>0]}
    falling=getattr(engine,'_fall_packet',None) is not None
    if (pending<=0 or not _store_ready(engine,owner) or (not falling and not kinds.intersection({'BLUDGEONING','FORCE','THUNDER'}))
            or (packet and 'momentum_recoil' in packet.source_flags)):
        return None
    chosen=ask(engine,intent,checkpoint_id(engine,'store_impact',owner.entity_id,engine.state.event_sequence),owner,
        'choice:needle.store_impact',['store'],labels={'store':'Reaction and 1 Stamina: reduce this damage by 2d8 + Constitution modifier'},
        allow_decline=True,target_id=owner.entity_id,name='Store the Collision',
        prompt=f'Store the Collision: {owner.display_name} would take {pending} damage after defenses and Stamina Guard. Spend your Reaction and 1 Stamina to store the impact?')
    if not chosen:
        return None
    typed_reactions.open_reaction(engine,{'feature_id':STORE},owner,(source_actor_id,) if source_actor_id else (),'DAMAGE_APPLICATION')
    typed_reactions.spend_reaction(engine,owner,{'feature_id':STORE})
    owner.turn_flags['once_per_round:typed.'+STORE]=int(engine.state.round_number)
    engine._spend_resource(owner,'resource:core.stamina',1,STORE)
    con=int((getattr(owner,'ability_mods',{}) or {}).get('con',0))
    # Compiled passive rows retain the actual Constitution modifier separately
    # from the cultivator's attack/key ability.
    row=next((r for r in getattr(engine,'typed_passive_rows',{}).get(owner.entity_id,[]) if r.get('feature_id')==STORE),{})
    con=int(row.get('momentum_con',con))
    roll=engine.roller.roll(DiceSpec(count=2,sides=8,modifier=con),actor_id=owner.entity_id,reason='Store the Collision')
    engine._record_roll(roll)
    reduction=max(0,int(roll.total))
    def settle(applied):
        if applied>0 and packet_scratch(engine) is not None:
            packet_scratch(engine)['momentum_store_applied']=owner.entity_id
        engine._append_event('REACTION_RESOLVED',STORE,actor_id=owner.entity_id,
            target_ids=(source_actor_id,) if source_actor_id else (),payload={'checkpoint':'DAMAGE_APPLICATION','reduction':min(pending,reduction),'pending_after':max(0,pending-reduction)})
    return {'reduction':reduction,'settle':settle}


@hook('event',nested=True)
def store_zero(engine,event_type,kwargs):
    if event_type!='DAMAGE_COMMITTED' or int((kwargs.get('payload') or {}).get('reduced_to',-1))!=0:
        return
    from ..pending_damage import packet_scratch
    scratch=packet_scratch(engine)
    actor_id=scratch.pop('momentum_store_applied',None) if scratch else None
    owner=engine.state.actors.get(actor_id)
    if owner:
        from .subpath_pools import gain
        gain(engine,owner,MOMENTUM,STORE,normal=False)

@hook('compile_actions')
def seal_momentum_levels(info):
    from ..path_levels import effective_cl
    cl=effective_cl(info['owner_sheet'],BODY,int(info['numbers'].get('cl') or 1))
    for row in info['passives']:
        if row.get('kind')=='momentum':
            row['cl']=cl
            row['momentum_con']=int(info['mods'].get('con',0))
    return None


@hook('match_start')
def fresh_momentum_scene(engine):
    for actor in engine.state.actors.values():
        if MOMENTUM in actor.resources and int(actor.resources[MOMENTUM]):
            engine._spend_resource(actor,MOMENTUM,int(actor.resources[MOMENTUM]),PARENT)


@hook('event',nested=True)
def end_momentum_scene(engine,event_type,kwargs):
    if event_type!='MATCH_ENDED':
        return
    fresh_momentum_scene(engine)
