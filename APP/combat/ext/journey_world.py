"""Shared world exposure and relation helpers used by journey travel plug-ins.

Native, source-recorded world exposure and physical displacement in journeys.

The existing owner/GM journey authoring API records externally resolved damage
or restraints with explicit provenance. Actor/AI menus never offer authoring
commands. Derived ability consumers use committed receipts, the same native
condition/saving-throw/footprint models and deterministic dice, rather than
inventing a hit, consent, source DC or actor statistic.
"""
import json
from types import SimpleNamespace
from . import hook,run_strict,query
from ..journey import require,integer
from ..gate2_runtime_models import ActorState,ConditionInstance,Position
from ..relation_models import Relations,RelationChange
from ..relations import relation as native_relation


def snapshot(session,aid):
    actor=session.state['actors'][aid]
    if 'encounter_snapshot' not in actor:
        maximum=actor['bundle']['actor_template']['maximum_hp']
        actor['encounter_snapshot']={'current_hp':maximum,'maximum_hp':maximum,'temporary_hp':0,
            'active':1,'life_state':'','conditions':{}}
    return actor['encounter_snapshot']


def actor_state(session,aid):
    actor=session.state['actors'][aid];template=actor['bundle']['actor_template']
    saved=actor.get('encounter_snapshot') or {}
    values={key:value for key,value in template.items() if key in ActorState.model_fields}
    values.update(current_hp=saved.get('current_hp',template['maximum_hp']),
        maximum_hp=saved.get('maximum_hp',template['maximum_hp']),temporary_hp=saved.get('temporary_hp',0),
        active=bool(saved.get('active',1)),life_state=saved.get('life_state') or None,
        team_id=actor.get('team_id',template['team_id']),position=actor['position'],
        movement_remaining_ft=template['speed_ft'],resources=actor['resources'],
        resource_maximums={r['resource_id']:r['maximum'] for r in template['resources']},
        conditions={iid:json.loads(c) for iid,c in saved.get('conditions',{}).items()})
    return ActorState.model_validate(values)


def relation(session,left,right):
    adapter=SimpleNamespace(state=SimpleNamespace(relations=Relations.model_validate(session.state.get('relations',{}))))
    return native_relation(adapter,actor_state(session,left),actor_state(session,right))


def occupied_cells(session,excluding=None):
    """Native occupied creature volumes, shared by passage and arrival checks."""
    return session.occupied_cells(excluding=excluding)


def legal_volume(session,aid,point):
    return session.legal_volume(aid,point)


def legal_step(session,aid,old,nxt,*,barriers=()):
    from .. import route_environment
    footprint=session.footprint(aid)
    occupied=occupied_cells(session,excluding=aid)
    return (session.grid.in_bounds((nxt.x,nxt.y))
            and session.grid.volume_step_legal(old,nxt,footprint=footprint,occupied_cells=occupied)
            and session.grid.line_of_physical_transmission(old,nxt)
            and route_environment.permits(session.grid,old,nxt,barriers=barriers))


def paths(session,aid,feet,*,barriers=()):
    """All native-volume forced destinations within a finite 3D grant."""
    require(integer(feet),'Physical routes need a finite nonnegative feet budget.')
    origin=actor_state(session,aid).position
    frontier=[(origin,(origin,))];found={origin:(origin,)}
    for _ in range(feet//session.grid.square_size_ft):
        following=[]
        for old,path in frontier:
            for dz in (-1,0,1):
                for dx in (-1,0,1):
                    for dy in (-1,0,1):
                        if not (dx or dy or dz) or old.z+dz<0 or not session.grid.in_bounds((old.x+dx,old.y+dy)):continue
                        nxt=Position(x=old.x+dx,y=old.y+dy,z=old.z+dz)
                        if nxt not in found and legal_step(session,aid,old,nxt,barriers=barriers):
                            found[nxt]=(*path,nxt);following.append((nxt,found[nxt]))
        frontier=following
    return found


def relocate(session,aid,path,source,owner):
    require(path and path[0]==actor_state(session,aid).position,'The creature moved before this route could resolve.')
    # Forced journey movement settles like ordinary travel: a Carry, Sweep or
    # rescue may cross unsupported open air but must end on a supported space,
    # so nothing is left suspended when the journey has no fall to resolve.
    require(session.support_at(aid,path[-1]),'A forced journey move must end on a supported space.')
    session.state['actors'][aid]['position']=path[-1].model_dump(mode='json')
    session.emit('MOVEMENT_COMMITTED',aid,source=source,source_actor_id=owner,
        path=[p.model_dump(mode='json') for p in path],destination=session.state['actors'][aid]['position'],
        cost_ft=0,forced=1,provokes=0)
    if path[-1]!=path[0]:run_strict('journey_position_committed',session,aid,path[0],path[-1],session.state['events'][-1])


def temporary_hp(session,aid,amount,source,owner):
    from ..typed_executor import condition_rules
    if any(r.get('temp_hp_denied') for r in condition_rules(actor_state(session,aid))):return
    saved=snapshot(session,aid);before=saved['temporary_hp']
    saved['temporary_hp']=max(before,amount)
    session.emit('TEMP_HP_GRANTED',aid,source=source,source_actor_id=owner,offered=amount,before=before,after=saved['temporary_hp'])


def saving_throw(session,aid,ability,dc,source,extra_mode='NORMAL'):
    from ..gate2_rolls import DeterministicRollAuthority
    from ..typed_executor import condition_rules
    actor=actor_state(session,aid)
    rules=condition_rules(actor)
    modes=[r.get('save_mode',{}).get(ability) for r in rules]
    if any(ability in r.get('no_save_advantage',()) for r in rules):
        modes=[None if mode=='ADVANTAGE' else mode for mode in modes]
        extra_mode='NORMAL' if extra_mode=='ADVANTAGE' else extra_mode
    modes += [extra_mode,*query('journey_save_mode',session,aid,ability,dc,source)]
    require(all(v in (None,'NORMAL','ADVANTAGE','DISADVANTAGE','AUTO_FAIL') for v in modes),'Invalid native journey save mode.')
    active=set(modes)&{'ADVANTAGE','DISADVANTAGE'}
    mode=next(iter(active)) if len(active)==1 else 'NORMAL'
    roller=DeterministicRollAuthority(session.state['journey_id'],counter=session.state.get('roll_counter',0))
    roll=roller.d20(modifier=int(actor.saving_throws.get(ability,0)),actor_id=aid,reason='SAVE:'+source+':'+ability,mode=mode)
    session.state['roll_counter']=roller.counter
    success='AUTO_FAIL' not in modes and roll.total>=dc
    session.emit('SAVE_ROLLED',aid,source=source,ability=ability,dc=dc,roll=roll.model_dump(mode='json'),success=int(success))
    return success


def world_command(session,aid,kind,payload):
    if kind=='relation_change':
        change=RelationChange.model_validate(payload)
        actors=session.state['actors'];table=Relations.model_validate(session.state.get('relations',{}))
        if change.kind=='ACTOR_SIDE':
            require(change.subject in actors and change.other.startswith('team:'),'Choose a journey creature and a named side.')
            actors[change.subject]['team_id']=change.other
        else:
            allowed=set(actors) if change.kind=='ACTOR_RELATION' else {actor_state(session,a).team_id for a in actors}
            require({change.subject,change.other}<=allowed,'Choose participants in this journey.')
            pairs=table.actors if change.kind=='ACTOR_RELATION' else table.teams
            left,right=sorted((change.subject,change.other));pairs.setdefault(left,{})[right]=change.relation
        session.state['relations']=table.model_dump(mode='json')
        session.emit('RELATION_CHANGED',aid,change=change.model_dump(mode='json'))
        return True


    if kind=='record_damage':
        require(set(payload)=={'source_reference','amount','damage_type'} and isinstance(payload['source_reference'],str)
                and payload['source_reference'].strip() and integer(payload['amount'])
                and isinstance(payload['damage_type'],str) and payload['damage_type'].strip(),
                'Record externally settled damage with its actual source, nonnegative amount and damage type.')
        saved=snapshot(session,aid);amount=payload['amount'];before=saved['current_hp']
        absorbed=min(saved['temporary_hp'],amount);hp_damage=amount-absorbed
        saved['temporary_hp']-=absorbed;saved['current_hp']=max(0,before-hp_damage)
        if saved['current_hp']==0:
            saved['life_state']='DYING';session.state['actors'][aid]['incapacitated']=1
        session.emit('DAMAGE_COMMITTED',aid,source=payload['source_reference'],damage_type=payload['damage_type'],
            reduced_to=amount,temporary_hp_absorbed=absorbed,hp_damage=hp_damage,hp_before=before,
            remaining_hp=saved['current_hp'],position=dict(session.state['actors'][aid]['position']))
        run_strict('journey_damage_committed',session,aid,session.state['events'][-1])
        run_strict('journey_state_changed',session,aid)
        return True
    if kind=='record_restraint':
        require(set(payload)=={'condition','source_reference','source_actor_id','source_dc','save_ability'}
                and payload['condition'] in ('grappled','restrained','prone')
                and isinstance(payload['source_reference'],str) and payload['source_reference'].strip()
                and payload['source_actor_id'] in session.state['actors'] and integer(payload['source_dc'],1)
                and payload['save_ability'] in ('','STR','DEX','CON','INT','WIS','CHA'),
                'Record the actual restraint, its source creature, source DC and original saving throw (empty if none).')
        saved=snapshot(session,aid);iid=f'condition:journey:{len(session.state["events"])}'
        data={'escape_dc':payload['source_dc'],'label':payload['condition'].title()}
        if payload['save_ability']:data['origin_save']={'ability':payload['save_ability'],'dc':payload['source_dc']}
        condition=ConditionInstance(instance_id=iid,condition_id='condition:typed.'+payload['condition'],
            source_definition_id=payload['source_reference'],source_actor_id=payload['source_actor_id'],target_id=aid,
            applied_sequence=len(session.state['events']),expires_on='STAND_UP' if payload['condition']=='prone' else 'UNTIL_REMOVED',data=data)
        saved['conditions'][iid]=condition.model_dump_json()
        session.emit('CONDITION_APPLIED',aid,source=payload['source_reference'],condition=condition.model_dump(mode='json'))
        return True

@hook('fact_admission_schema')
def world_schema(session,source,subject,kind):
    if source=='world:journey_exposure' and kind in ('settled_damage','restraint','relations'):
        return {'value_type':'document','maximum_seconds':3600,'authority':'table_owner',
                'description':'Record a source-qualified externally resolved world exposure; never creature consent.'}


@hook('fact_admitted')
def world_exposure(session,record):
    if record['source']!='world:journey_exposure':return None
    kinds={'settled_damage':'record_damage','restraint':'record_restraint','relations':'relation_change'}
    kind=kinds.get(record['kind'])
    require(kind is not None,'Unknown world exposure kind.')
    require(not any(e['kind']=='WORLD_EXPOSURE_RESOLVED' and e['actor_id']==record['subject']
                    and e.get('source')==record['source'] and e.get('kind_name')==record['kind']
                    and e.get('scope')==record['scope'] for e in session.state['events']),
            'This world exposure has already resolved; a declaration cannot apply it twice.')
    require(world_command(session,record['subject'],kind,record['value']) is True,'That source exposure is unsupported.')
    session.emit('WORLD_EXPOSURE_RESOLVED',record['subject'],source=record['source'],kind_name=record['kind'],
                 scope=record['scope'],receipt_id=record['receipt_id'])


@hook('journey_combat_setup')
def combat_relations(session,aid):
    """Carry actual owner-recorded pair overrides, once for the full roster."""
    if aid!=next(iter(session.state['actors'])):return None
    table=Relations.model_validate(session.state.get('relations',{}))
    if table.actors or table.teams:return {'world_relations':table.model_dump(mode='json')}


@hook('match_initialize')
def initialize_relations(engine):
    from ..relations import apply_change
    for bundle in getattr(engine,'typed_bundle_documents',()):
        data=(bundle.get('journey_setup') or {}).get('world_relations')
        if data is None:continue
        table=Relations.model_validate(data)
        current=engine.state.relations or Relations()
        if current==table:continue
        for kind,pairs in (('TEAM_RELATION',table.teams),('ACTOR_RELATION',table.actors)):
            for left,others in pairs.items():
                for right,value in others.items():
                    apply_change(engine,RelationChange(kind=kind,subject=left,other=right,relation=value))


@hook('journey_snapshot_actor')
def resume_relations(creature,session,aid,engine):
    session.state['actors'][aid]['team_id']=creature.team_id
    if aid!=next(iter(session.state['actors'])):
        return creature
    session.state['relations']=(engine.state.relations or Relations()).model_dump(mode='json')
    return creature
