"""Returning-Heaven Momentum Body: native acquisition, Momentum and five consumers.

Momentum derives from committed movement, damage and Stamina Guard, with a
source-controller declaration only for subjective anti-farming exclusions.
Gather declares and pays on a confirmed unarmed hit, joining the attack packet.
Store answers native forced movement or final damage; Rebound waits for the
triggering effect and uses native granted movement/attack. Heaven traverses and
settles its line incrementally, including actual objects and retained ground.
Journey contracts preserve scene resources and ground outside combat. Hooks
return early without acquired source rows; core contains no ability-ID cases.
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
    profile=next((r for r in getattr(engine,"typed_passive_rows",{}).get(actor.entity_id,[]) if r.get("block")=="momentum_profile"),None)
    if profile:
        return int(profile['cl'])
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
    if "next_push" in picks:
        engine._apply_condition(actor,NEXT_PUSH,PREFIX+"gather_and_return",actor.entity_id,
            expires_on="END_OF_CURRENT_TURN",data={"label":"Gather and Return: +5 feet to your next forced movement this turn"})
    if count:
        roll = engine.roller.roll(DiceSpec(count=count,sides=8,modifier=0), actor_id=actor.entity_id,
            reason="Gather and Return", critical=provenance.critical)
        engine._record_roll(roll)
        spec.setdefault("damage_components", []).append({"amount": int(roll.total), "damage_type": kind.upper()})
    engine.__dict__.setdefault("_momentum_gather_hits", {})[provenance.roll_id] = {
        "push": 5*picks.count("push"), "move": 5*picks.count("move"),
        "ac": "ac" in picks}


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


@hook("forced_movement_bonus")
def next_push(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> int:
    if _cl(ctx.engine,ctx.actor)<3:
        return 0
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
    from ..typed_reactions import can_react

    key = "once_per_round:typed." + STORE
    return ("store" in _roles(engine, owner) and _cl(engine, owner) >= 6 and owner.turn_flags.get(key) != int(engine.state.round_number) and owner.active
            and can_react(engine,owner,{'feature_id':STORE}) and int(owner.resources.get("resource:core.stamina", 0) or 0) >= 1
            and not any(rule.get("no_reactions") for rule in condition_rules(owner)))


@hook("forced_movement_reduction")
def store_movement(ctx: Any, subject: Any) -> int:
    engine = ctx.engine
    if subject is not None:
        ctx.damage_cache.pop(("stored_movement", subject.entity_id, ctx.source), None)
    if subject is None or not _store_ready(engine, subject) \
            or int(ctx.forced_movement_distance_ft or 0) <= 0:
        return 0
    from .needle import ask, checkpoint_id

    maximum=min(15,int(ctx.forced_movement_distance_ft))
    labels={str(n):f'Reaction and 1 Stamina: reduce the movement by {n} feet' for n in range(maximum,-1,-1)}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "store_movement", subject.entity_id), subject, "choice:needle.store_the_collision_move", list(labels),
                 labels=labels, preferred=[str(maximum)], allow_decline=True,
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
        reduction=int(picked[0])
        ctx.damage_cache[("store_selection",subject.entity_id,ctx.source)]=True
        return reduction


@hook("condition_attempt")
def stored_no_prone(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    if subject is None:
        return None
    if str((effect_row or {}).get("condition") or "").lower() != "prone":
        return None
    return False if (effect_row.get('caused_by_movement') is True
        and ctx.damage_cache.get(("stored_movement",subject.entity_id,ctx.source))) else None


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
    from fractions import Fraction
    from ..gate2_runtime_models import Position
    from ..movement_paths import resolve
    from .needle import ask,checkpoint_id,cell_id
    from .. import ext
    feet+=sum(int(value) for value in ext.run('forced_movement_bonus',ctx,target,{'type':'forced_movement','direction':'perpendicular'}) if type(value) is int and value>0)
    dx,dy=end.x-start.x,end.y-start.y
    divisor=max(abs(dx),abs(dy)) or 1
    px,py=Fraction(-dy,divisor),Fraction(dx,divisor)
    options={}
    for sign in (-1,1):
        for step in range(1,feet//5+1):
            dest=Position(x=target.position.x+round(sign*px*step),y=target.position.y+round(sign*py*step),z=target.position.z)
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
    start,end=actor.position,ctx.damage_cache.get('_checkpoint_aim') or ctx.destination
    if not _impact_destination(engine,actor,end):
        raise ValueError('Heaven-Returning Impact needs a visible, unoccupied destination on a straight line within 120 feet.')
    spent=0
    for event in reversed(engine.events):
        if event.event_type=='INTENT_ACCEPTED':
            break
        if (event.event_type=='RESOURCE_SPENT' and event.actor_id==actor.entity_id
                and event.source_definition_id==ctx.action.source_definition_id
                and event.payload.get('resource_id')==MOMENTUM):
            spent+=int(event.payload['amount'])
    roll=engine.roller.roll(DiceSpec(count=6+spent,sides=10,modifier=0),actor_id=actor.entity_id,reason='DAMAGE:'+HEAVEN)
    engine._record_roll(roll)
    line=[Position(x=x,y=y,z=start.z) for x,y in _line(start,end)]
    hit_objects=set();hit_creatures=set();travelled=[start];blocked=False;recoil=False;movement_left=120
    previous=engine.__dict__.get('_momentum_impact_mover')
    engine._momentum_impact_mover=actor.entity_id
    try:
        with engine.victory_deferred():
            for cell in line:
                swept=set(engine._actor_volume(actor,cell))
                for obj in sorted(engine.state.objects.values(),key=lambda o:o.object_id):
                    component=obj.component or {}
                    occupied={(p.x,p.y,p.z+height) for p in target_cells(engine,obj)
                              for height in range(max(1,(int(obj.height_ft or 5)+4)//5))}
                    if not swept.intersection(occupied):
                        continue
                    # These are independently declared active source facts.
                    # Destroying their associated object does not silently end
                    # a Formation or spatial lock; its owner must end the fact.
                    if component.get('sealed_formation') or component.get('spatial_lock'):
                        blocked=True
                    if obj.destroyed or obj.object_id in hit_objects:
                        continue
                    eligible=(obj.unattended or component.get('temporary_barrier') or component.get('structure')
                        or component.get('formation_anchor') or component.get('vehicle') or component.get('terrain_section')
                        or obj.object_kind in ('vehicle','terrain_section'))
                    if eligible and not component.get('world_scale'):
                        hit_objects.add(obj.object_id)
                        deal(engine,actor,obj,[(int(roll.total),'FORCE')],HEAVEN,multiplier=2)
                    current=engine.state.objects[obj.object_id]
                    if not current.destroyed and component.get('blocks'):
                        blocked=True;recoil=True
                for zone in list(engine.state.zones.values()):
                    wall=(zone.trigger_profile or {}).get('wall')
                    if not zone.active or not wall or cell not in zone.affected_cells:
                        continue
                    if (zone.trigger_profile or {}).get('sealed_formation') or (zone.trigger_profile or {}).get('spatial_lock'):
                        blocked=True
                        continue
                    stats=defense_stats(ctx,zone)
                    key=(zone.zone_id,) if stats and stats.get('scope')=='wall' else (zone.zone_id,cell.x,cell.y,cell.z)
                    if key not in hit_objects:
                        hit_objects.add(key)
                        if stats is not None:
                            damage=0 if 'FORCE' in stats['immune'] else int(roll.total)
                            if 'FORCE' in stats.get('resist',[]): damage//=2
                            if 'FORCE' in stats.get('vulnerable',[]): damage*=2
                            damage_section(engine,zone,cell,2*damage,HEAVEN,'FORCE')
                    if zone.active and cell in zone.affected_cells and wall.get('blocks_movement'):
                        blocked=True;recoil=True
                if blocked:
                    break
                occupants=[other for other in engine.state.actors.values() if other is not actor and other.active
                           and (cell.x,cell.y) in engine._actor_cells(other) and other.position.z==cell.z]
                if cell!=actor.position and not occupants:
                    segment=[Position(x=x,y=y,z=start.z) for x,y in _line(actor.position,cell)]
                    try:
                        used=granted_movement.resolve_path(engine,actor,segment,HEAVEN,feet=movement_left,intent=ctx.intent,provokes=False)
                        movement_left-=used
                    except ValueError:
                        break
                    if actor.position!=cell:
                        break
                    travelled.append(cell)
                for target in sorted(engine.state.actors.values(),key=lambda a:a.entity_id):
                    if target is actor or not target.active or target.entity_id in hit_creatures:
                        continue
                    if not any(engine.grid.distance_ft(a,b)<=5 for a in swept for b in engine._actor_volume(target)):
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
            if recoil:
                engine._commit_damage(actor,2*_cl(engine,actor),'FORCE',HEAVEN,actor.entity_id,ctx.intent,
                    reaction_depth=0,source_flags=('momentum_recoil',))
            zone=placed.place(engine,actor,source=ctx.source,tag='momentum_impact',cells=[actor.position,*[p for p in placed.area(engine,actor.position,'sphere',10) if p!=actor.position]],
                name='Heaven-Returning Impact: broken ground (difficult terrain until cleared or repaired)',difficult='all',
                numbers=ctx.numbers,duration_rounds=None,shape='sphere',size_ft=10,
                extra={'profile':{'repair_tools':['tianxia.mortal.gear.shovel','tianxia.mortal.tool.mason_s_tools'], 'repair_work_seconds':60,'source_cl':_cl(engine,actor)}})
            from .terrain_repair import ensure_action
            ensure_action(engine)
            note(engine,HEAVEN,actor,f'Heaven-Returning Impact: spent {spent} Momentum; {6+spent}d10 Force damage ({roll.total}).')
    finally:
        engine._momentum_impact_mover=previous


# Source selection uses the shared installed-sheet journey acquisition contract.
PARENT = PREFIX.removesuffix('.feature.')
BODY = 'tianxia.path.body_refining'
LEVELS = [(3,'gather_and_return'),(6,'store_the_collision'),(10,'rebounding_assault'),
          (14,'avalanche_meridian_circuit'),(18,'heaven_returning_impact')]


def _selected_body_sources(sheet):
    paths=sheet.get('path_and_subpath') or {}
    # Canonical source IDs carry registered progression identity. Display
    # names, damage types and feature flavor never establish a Subpath.
    return {str(key) for key in paths.get('subpath_record_ids',()) if str(key).startswith('tianxia.subpath.body.')} | {
        str(key).split('.feature.',1)[0] for key in paths.get('path_feature_record_ids',())
        if str(key).startswith('tianxia.subpath.body.') and '.feature.' in str(key)}


def _selection_legal(sheet):
    from ..path_levels import effective_cl
    paths = sheet.get('path_and_subpath') or {}
    return (BODY in paths.get('path_record_ids', ())
        and effective_cl(sheet,BODY,int(sheet['identity']['cultivation_level'])) >= 3
        and not _selected_body_sources(sheet))


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
    if _selected_body_sources(sheet)-{PARENT}:
        raise ValueError('Returning-Heaven cannot coexist with another Body Refining Subpath.')
    result=deepcopy(sheet); fields=result.setdefault('path_and_subpath',{})
    cl=effective_cl(sheet,BODY,int(sheet['identity']['cultivation_level']))
    fields['subpath_record_ids']=list(dict.fromkeys([*(fields.get('subpath_record_ids') or []),PARENT]))
    fields['path_feature_record_ids']=list(dict.fromkeys([*[key for key in fields.get('path_feature_record_ids',[]) if not str(key).startswith(PREFIX)],
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
    if any(str(key).startswith(PREFIX) for key in info.get('owned_ids',())):
        con=next((int(a.get('modifier',0)) for a in ((info.get('owner_sheet') or {}).get('ability_scores_and_statistics') or {}).get('abilities',[]) if str(a.get('ability','')).upper()=='CON'),0)
        rows=[*rows,{'block':'momentum_profile','feature_id':PREFIX+'gather_and_return','cl':cl,'momentum_con':con,'choice_owner':True}]
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
        previous_segment=engine.__dict__.get('_momentum_rebound_segment')
        try:
            remaining=engine._effective_speed(owner)
            spent=0
            while remaining>0 and owner.active and other.active:
                start=owner.position
                distance=engine._distance_actor_to_actor(owner,other)
                # A chosen continuous route is one movement segment. Its
                # intermediate squares may include the triggering creature;
                # it must end legally and closer than this segment began.
                routes=movement.routes(engine,owner,remaining)
                paths={cell_id(cell):(path,mode) for cell,(path,cost,mode) in routes.items()
                    if engine._distance_actor_to_actor(owner,other,actor_position=cell)<distance}
                if not paths:
                    break
                step=ask(engine,intent,checkpoint_id(engine,'rebound_path',owner.entity_id,spent),owner,
                    'choice:needle.rebound_move',list(paths),labels={key:'End this segment closer to '+other.display_name+' at '+key.removeprefix('cell:') for key in paths},
                    allow_decline=spent>0,target_id=other.entity_id,name='Rebounding Assault',
                    prompt=f'Rebounding Assault: choose a closer unoccupied endpoint for this movement segment (up to {remaining} feet remaining). You may pass through {other.display_name} as difficult terrain, without Opportunity Attacks.')
                if not step:
                    break
                path,mode=paths[step[0]]
                engine._momentum_rebound_segment=(start,path[-1])
                used=movement.resolve_path(engine,owner,path,REBOUND,feet=remaining,intent=intent,provokes=False,mode=mode)
                engine._momentum_rebound_segment=None
                remaining-=used
                spent+=used
                if used<=0 or owner.position==start:
                    break
        finally:
            engine._momentum_passage=previous
            engine._momentum_rebound_segment=previous_segment
        strikes=[a for a in engine.action_catalog.values() if owner.active and a.owner_id==owner.entity_id
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
        if event.event_type=='INTENT_ACCEPTED':break
        if (event.event_type=='MOVEMENT_COMMITTED' and (event.payload.get('forced') or event.payload.get('teleport'))
                and len(event.payload.get('path') or [])>1):
            source=event.payload.get('source_actor_id') or event.payload.get('dragged_by')
            if source in engine.state.actors:moved.add((event.actor_id,source))
    for actor_id,source in sorted(moved):
        owner=engine.state.actors.get(actor_id)
        if owner:_rebound(engine,owner,engine.state.actors[source],getattr(engine,'_active_intent',None))

@hook('reaction_rows')
def replace_family_reactions(engine,actor_id,block,rows):
    actor=engine.state.actors.get(actor_id)
    if actor is None:
        return None
    roles=_roles(engine,actor)
    replaced=({STORE} if 'store' in roles else set()) | ({REBOUND} if 'rebound' in roles else set())
    return [row for row in rows if row.get('feature_id') not in replaced] if replaced else None


@hook('final_damage')
def store_impact(engine,owner,pending,kind,source,source_actor_id,intent):
    from ..pending_damage import current,packet_scratch
    from .. import typed_reactions
    from ..gate2_runtime_models import DiceSpec
    from .needle import ask,checkpoint_id
    packet=current(engine)
    kinds=({str(p['damage_type']).upper() for p in packet.components if p['amount']>0}
           if packet and packet.components else {str(kind).upper()})
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
    row=next((r for r in getattr(engine,'typed_passive_rows',{}).get(owner.entity_id,[]) if r.get('block')=='momentum_profile'),{})
    con=int(row.get('momentum_con',con))
    roll=engine.roller.roll(DiceSpec(count=2,sides=8,modifier=con),actor_id=owner.entity_id,reason='Store the Collision')
    engine._record_roll(roll)
    reduction=max(0,int(roll.total))
    def settle(applied):
        if applied>0 and packet_scratch(engine) is not None:
            packet_scratch(engine)['momentum_store_applied']=owner.entity_id
        engine._append_event('REACTION_RESOLVED',STORE,actor_id=owner.entity_id,
            target_ids=(source_actor_id,) if source_actor_id else (),payload={'checkpoint':'DAMAGE_APPLICATION','reduction':min(pending,reduction),'pending_after':max(0,pending-reduction)})
    return {'reduction':min(pending,reduction),'settle':settle}


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
    for action in info['actions']:
        if ((action.parameters or {}).get('typed') or {}).get('source')==HEAVEN:
            action.parameters['creates_repairable_terrain']=True
            action.parameters['typed']['area']={**(action.parameters['typed'].get('area') or {}),'shape':'line','size_ft':120,'width_ft':15,'explicit_harmful_recipients':'every_creature'}
            action.parameters['description']='Action: requires at least 3 Momentum; spend 5 Stamina and all current Momentum. Move up to 120 feet along a visible straight line without Opportunity Attacks; Force damage, perpendicular pushes and damaged ground follow the line.'
    for row in info['passives']:
        if row.get('kind')=='momentum':
            row['cl']=cl
            row['momentum_con']=int(info['mods'].get('con',0))
    return None


@hook('match_start')
def fresh_momentum_scene(engine):
    continued={b['actor_id'] for b in getattr(engine,'typed_bundle_documents',[]) if b.get('momentum_scene_continuation')}
    for actor in engine.state.actors.values():
        if actor.entity_id not in continued and MOMENTUM in actor.resources and int(actor.resources[MOMENTUM]):
            engine._spend_resource(actor,MOMENTUM,int(actor.resources[MOMENTUM]),PARENT)


@hook('event',nested=True)
def end_momentum_scene(engine,event_type,kwargs):
    if event_type!='MATCH_ENDED':
        return
    fresh_momentum_scene(engine)


def generation_allowed(engine,owner,source,*,source_actor_id=None,require_hostile=False):
    """Admit the source controller's subjective anti-farming declaration.

    The collector already derives distance/damage from committed events. This
    declares only the controller's own intent, never another actor's consent.
    Automatic actors with no declared intent knowledge cannot invent a fact.
    """
    from types import SimpleNamespace
    from ..fact_consent_admission import admit_choice,digest
    from ..pending_damage import current
    intent=getattr(engine,'_active_intent',None)
    if intent is None or not _roles(engine,owner):
        return False
    packet=current(engine)
    last=engine.events[-1] if engine.events else None
    source_id=source_actor_id or (packet.source_actor_id if packet else ((last.payload or {}).get('source_actor_id') if last else None))
    source_id=source_id or getattr(intent,'actor_id',None)
    chooser=engine.state.actors.get(source_id) or owner
    context=SimpleNamespace(engine=engine,intent=intent,action=SimpleNamespace(display_name='Momentum'))
    scope=digest({'intent':intent.intent_id,'event':engine.state.event_sequence,'owner':owner.entity_id,'source':source})
    classification='a genuine hostile effect on '+owner.display_name if require_hostile else 'a genuine qualifying encounter event'
    declaration=admit_choice(context,chooser,PARENT,'momentum_eligibility',scope,['genuine','excluded'],
        labels={'genuine':('This was '+classification),'excluded':'Staged, harmless, willing allied, self-inflicted, repeated stationary-object or resource-loop event'},
        prompt=f'Momentum for {owner.display_name}: {chooser.display_name}’s controller must confirm their own intent. Was this {classification}, rather than an excluded staged or resource-loop event? No cost.',
        expires_on='END_OF_CURRENT_TURN',readers=[owner.entity_id] if chooser is not owner else [],
        automatic_options=['genuine'] if getattr(intent,'actor_id',None)==chooser.entity_id and (not require_hostile or chooser.team_id!=owner.team_id) else [])
    return declaration is not None and declaration['value']=='genuine'

GROUND=PARENT+'.damaged_ground'


def _ground_map(session):
    from ..canonical import canonical_sha256
    return canonical_sha256(session.state['battlefield'])


def _saved_ground(session,actor):
    return actor.get('source_states',{}).get(GROUND,{}).get('maps',{}).get(_ground_map(session),{})


@hook('journey_encounter_settled')
def retain_impact_ground(session,actor_id,engine,creature):
    actor=session.state['actors'][actor_id]
    ground=[zone.model_dump_json() for zone in engine.state.zones.values() if zone.active
            and zone.owner_id==actor_id and placed_impact(zone)]
    if ground or GROUND in actor.get('source_states',{}):
        record=actor.setdefault('source_states',{}).setdefault(GROUND,{'maps':{}})
        record['maps'][_ground_map(session)]={'zones':ground}


def placed_impact(zone):
    from .placed import data
    return data(zone).get('tag')=='momentum_impact'


@hook('journey_combat_bundle')
def restore_ground_bundle(bundle,session,actor_id):
    from copy import deepcopy
    saved=_saved_ground(session,session.state['actors'][actor_id])
    if MOMENTUM not in session.state['actors'][actor_id]['resources'] and not saved:
        return None
    result=deepcopy(bundle)
    result['momentum_scene_continuation']=True
    result['momentum_ground']=list((saved or {}).get('zones',[]))
    return result


@hook('match_start')
def restore_ground(engine):
    from ..gate2_runtime_models import ZoneState
    for bundle in getattr(engine,'typed_bundle_documents',[]) or []:
        for saved in bundle.get('momentum_ground',[]):
            zone=ZoneState.model_validate_json(saved)
            engine.state.zones[zone.zone_id]=zone
            engine._append_event('ZONE_CREATED',zone.source_definition_id,actor_id=zone.owner_id,payload={'zone':zone.model_dump(mode='json')})
    from .terrain_repair import ensure_action
    ensure_action(engine)


def _ground_choices(session,actor_id):
    import json
    from ..gate2_runtime_models import Position
    actor=session.state['actors'][actor_id]
    from types import SimpleNamespace
    from ..gate2_runtime_models import ConditionInstance
    from .. import carry
    snapshot=actor.get('encounter_snapshot') or {}
    holder=SimpleNamespace(conditions={k:ConditionInstance.model_validate_json(v) for k,v in snapshot.get('conditions',{}).items()})
    tools={item.get('item_id') for item in actor['bundle'].get('carrying',{}).get('items',[])
           if int(item.get('quantity',0))>0 and not carry.dropped(holder,item['key']) and not carry.lost_to_another_hand(holder,item['key'])}
    options={}
    for maker,saved_actor in session.state['actors'].items():
        saved=_saved_ground(session,saved_actor)
        for value in saved.get('zones',[]):
            zone=json.loads(value)
            needed=set((zone.get('trigger_profile',{}).get('profile') or {}).get('repair_tools',[]))
            if not tools.intersection(needed):
                continue
            for cell in zone['affected_cells']:
                if session.grid.distance_ft(Position.model_validate(actor['position']),Position.model_validate(cell))<=5:
                    key=zone['zone_id']+f':{cell["x"]},{cell["y"]},{cell.get("z",0)}'
                    options[key]=(maker,zone['zone_id'],cell)
    return options


@hook('journey_options')
def ground_options(session,actor_id):
    if session.state['phase']!='travel' or session.state['actors'][actor_id]['incapacitated']:
        return None
    return [{'id':'clear-impact:'+key,'kind':'clear_impact_ground','payload':{'square':key},
        'label':f'Clear broken ground at {cell["x"]},{cell["y"]} with suitable tools (1 minute; no resource cost)'}
        for key,(maker,zone_id,cell) in _ground_choices(session,actor_id).items()]


@hook('journey_command')
def clear_ground(session,actor_id,kind,payload):
    if kind!='clear_impact_ground':
        return None
    from ..journey import require
    import json
    actor=session.state['actors'][actor_id]
    require(not actor['incapacitated'] and set(payload)=={'square'},'Choose a reachable impact square and suitable tools.')
    options=_ground_choices(session,actor_id)
    require(payload['square'] in options,'That square is out of reach or you have no suitable tools.')
    maker,zone_id,cell=options[payload['square']]
    work=0
    updates=[]
    key=f'{cell["x"]},{cell["y"]},{cell.get("z",0)}'
    for saved_actor in session.state['actors'].values():
        state=_saved_ground(session,saved_actor)
        if not state:continue
        remaining=[]
        for value in state['zones']:
            zone=json.loads(value)
            if cell in zone['affected_cells']:
                profile=(zone.get('trigger_profile',{}).get('profile') or {})
                progress=zone.get('trigger_profile',{}).get('repair_progress') or {}
                work=max(work,max(0,int(profile.get('repair_work_seconds',60))-int(progress.get(key,0))))
                zone['affected_cells']=[p for p in zone['affected_cells'] if p!=cell]
            if zone['affected_cells']:
                remaining.append(json.dumps(zone,sort_keys=True,separators=(',',':')))
        updates.append((state,remaining))
    session.tick(work)
    for state,remaining in updates:state['zones']=remaining
    session.emit('IMPACT_GROUND_CLEARED',actor_id,source=HEAVEN,square=payload['square'],seconds_worked=work)
    return True


@hook('technique_cost_floor')
def impact_all_momentum(engine,actor,source_id,printed,current):
    action=engine.action_catalog.get(source_id)
    if (action is not None and action.owner_id==actor.entity_id
            and ((action.parameters or {}).get('typed') or {}).get('source')==HEAVEN
            and MOMENTUM in printed):
        return {MOMENTUM:max(3,int(actor.resources.get(MOMENTUM,0)))}
    return None


@hook('forced_movement_reduced')
def store_movement_settled(ctx,subject,before_ft,after_ft):
    if (subject is not None and before_ft>0 and after_ft==0
            and ctx.damage_cache.pop(('store_selection',subject.entity_id,ctx.source),False)):
        ctx.damage_cache[('stored_movement',subject.entity_id,ctx.source)]=True
        from .subpath_pools import gain
        gain(ctx.engine,subject,MOMENTUM,STORE,normal=False,source_actor_id=ctx.actor.entity_id)


@hook('choice_reactors')
def momentum_source_controllers(engine):
    # A human source may need to declare its own intent during an off-turn
    # reaction, even when only the recipient owns Returning-Heaven.
    if any(row.get('block')=='momentum_profile' for rows in getattr(engine,'typed_passive_rows',{}).values() for row in rows):
        return tuple(engine.state.actors)
    return ()


@hook('journey_scene_end')
def clear_scene_momentum(session,old,new):
    for actor_id,actor in session.state['actors'].items():
        if MOMENTUM in actor['resources']:
            removed=int(actor['resources'][MOMENTUM])
            actor['resources'][MOMENTUM]=0
            session.emit('MOMENTUM_SCENE_ENDED',actor_id,source=PARENT,removed=removed,scene=new)


@hook('movement_route_attempt')
def rebound_closer_segment(engine,mover,previous,nxt,intent):
    passage=engine.__dict__.get('_momentum_passage')
    segment=engine.__dict__.get('_momentum_rebound_segment')
    if not passage or passage[0]!=mover.entity_id or not segment:
        return None
    target=engine.state.actors.get(passage[1])
    start,end=segment
    if target is None or not target.active or engine._distance_actor_to_actor(mover,target,actor_position=end)>=engine._distance_actor_to_actor(mover,target,actor_position=start):
        return {'stop':True,'source_id':REBOUND,'label':'Rebounding Assault must end this segment closer to the triggering creature.'}
    return None


@hook('journey_regions')
def impact_ground_travel(session,cell):
    import json
    rows=[]
    for actor in session.state['actors'].values():
        for value in _saved_ground(session,actor).get('zones',[]):
            zone=json.loads(value)
            if cell.model_dump(mode='json') in zone['affected_cells']:
                rows.append({'id':zone['zone_id'],'kind':'broken_terrain','ordinary':True,
                    'requires_support':False,'movement_cost':2})
    return rows or None


@hook('movement_source_enabled')
def momentum_movement_provenance(engine):
    return any(_roles(engine,a) for a in engine.state.actors.values())
