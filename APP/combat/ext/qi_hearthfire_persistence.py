"""Hearthfire's durable source clock on native encounter-snapshot conditions.

No general registry or clock is added. The existing Journey registry preserves
encounter_snapshot; a nonbeneficial, permanent source record there carries this
family's remaining durations/asset health across a new journey or encounter.
Actual native round/zone/object events update the same record during combat.
Only committed elapsed time advances it; reopening never restores eight hours.
"""
import json
from copy import deepcopy
from . import hook
from .qi_hearthfire import HEARTH, BLOCK
from .qi_hearthfire_sanctuary import PAVILION,RECOVERED,FEAR
from ..gate2_runtime_models import ConditionInstance
from .retained_updates import record_instance_update

CLOCK='condition:typed.hearthfire_source_clock'
SCHEMA='hearthfire-source-clock-v1'


def saved_record(actor):
    for value in (actor.get('encounter_snapshot') or {}).get('conditions',{}).values():
        c=json.loads(value)
        if c.get('condition_id')==CLOCK and c.get('data',{}).get('schema')==SCHEMA:
            return c['data']


def family_state(session,aid):
    """Pure source-scoped reconstruction; query reads never extend a deadline."""
    actor=session.state['actors'][aid];f=actor.get('hearthfire')
    record=saved_record(actor)
    if not record or f and f.get('clock_epoch')==record['epoch']:
        return f or {}
    state=json.loads(record['family_json'])
    if record['mode']=='combat':
        base=next((e['seconds'] for e in reversed(session.state['events'])
                   if e['kind']=='TRAVEL_RESUMED' and e.get('match_id')==record['epoch']),0)
    elif record['epoch']==session.state['journey_id']:
        base=record['seconds']
    else:
        base=0  # the new journey begins at zero committed elapsed seconds
    camp=state.get('camp')
    if camp:
        camp['until']=base+record['remaining']
        if camp.get('pavilion'):
            camp['pavilion']['until']=base+record.get('pavilion_remaining',0)
    state['clock_epoch']=record['epoch']
    return state


def hydrate(session,aid):
    state=family_state(session,aid)
    if state:
        session.state['actors'][aid]['hearthfire']=deepcopy(state)
    return state


def persist(session,aid):
    actor=session.state['actors'][aid];f=actor.get('hearthfire')
    if not f:
        return
    now=int(session.clock());camp=f.get('camp',{})
    f['clock_epoch']=session.state['journey_id']
    record={'schema':SCHEMA,'mode':'journey','epoch':session.state['journey_id'],'seconds':now,
            'remaining':max(0,camp.get('until',now)-now),
            'pavilion_remaining':max(0,camp.get('pavilion',{}).get('until',now)-now),'family_json':json.dumps(f,sort_keys=True)}
    snapshot=actor.get('encounter_snapshot')
    if snapshot is None:
        maximum=actor['bundle']['actor_template']['maximum_hp']
        # Native genesis baseline, before this creature has ever fought. This
        # records no healing, resource grant, acquisition or trigger receipt.
        snapshot={'current_hp':maximum,'maximum_hp':maximum,'temporary_hp':0,'active':1,
                  'life_state':'','conditions':{},'death_saves':{'ok':0,'bad':0}}
        actor['encounter_snapshot']=snapshot
    condition=ConditionInstance(instance_id=CLOCK+':'+aid,condition_id=CLOCK,source_definition_id=HEARTH,
        source_actor_id=aid,target_id=aid,applied_sequence=0,expires_on='UNTIL_REMOVED',data=record)
    snapshot['conditions'][condition.instance_id]=condition.model_dump_json()


def setup_from_snapshot(bundle):
    actor={'encounter_snapshot':(bundle.get('journey_setup') or {}).get('encounter_snapshot')}
    record=saved_record(actor)
    if not record:
        return
    f=json.loads(record['family_json']);c=f.pop('camp',None);camps=[]
    if c and record['remaining']>0:
        c['remaining']=record['remaining'];c['owner']=bundle['actor_id']
        if c.get('pavilion'):c['pavilion']['remaining']=record['pavilion_remaining']
        camps=[c]
    return {'camps':camps,'recipient':f,'long_rests':0}


@hook('event',nested=True)
def native_clock_event(engine,event_type,kwargs):
    if event_type not in ('TURN_STARTED','OBJECT_UPDATED','ZONE_CREATED','ZONE_REMOVED','MOVEMENT_COMMITTED','TELEPORT_COMMITTED','ROUND_STARTED','MATCH_ENDED'):
        return
    # Retained zone bookkeeping is not another tick or another activation.
    if event_type=='ZONE_CREATED' and (kwargs.get('payload') or {}).get('retained_instance_update'):
        return
    update_clocks(engine)


def update_clocks(engine):
    from .qi_hearthfire import hearths
    for owner in engine.state.actors.values():
        held=next((c for c in owner.conditions.values() if c.condition_id==CLOCK),None)
        if held is None and not any(r.get('block')==BLOCK and r.get('feature_id')==HEARTH
                   for r in getattr(engine,'typed_passive_rows',{}).get(owner.entity_id,())):
            continue
        zones=[z for z in engine.state.zones.values() if z.active and z.owner_id==owner.entity_id
            and (z.trigger_profile.get('profile') or {}).get('hearth_object')
            and not (z.trigger_profile.get('profile') or {}).get('pavilion')
            and (obj:=engine.state.objects.get(z.trigger_profile['profile']['hearth_object'])) is not None
            and not obj.destroyed and obj.current_hp]
        if not zones and held is None:
            continue
        old=deepcopy(held.data) if held else {}
        f=json.loads(old.get('family_json','{}'));f.pop('temporary_hp',None);f.pop('hp',None)
        if not any(c.condition_id==FEAR for c in owner.conditions.values()):f.pop('fear_scene',None)
        camp=f.get('camp')
        if zones:
            z=zones[0];p=z.trigger_profile['profile'];obj=engine.state.objects[p['hearth_object']]
            remaining=max(0,(int(z.duration_rounds or 0)-(engine.state.round_number-z.created_round))*6)
            camp={'position':z.center.model_dump(mode='json'),'invited':list(p.get('chosen_recipients',())),
                'host':(camp or {}).get('host',owner.entity_id),'until':remaining,'source_cl':int(z.trigger_profile['numbers']['cl']),
                'hp':obj.current_hp,'native_object':obj.model_dump(mode='json'),'suppressed':int(bool(obj.suppressed)),
                'scene':(getattr(engine,'battlefield_document',{}) or {}).get('stable_id',''),'ac':13,'bright_ft':15,'dim_ft':30,'source':HEARTH,
                'number':(camp or {}).get('number',engine.state.event_sequence+1)}
            ward=next((w for w in engine.state.zones.values() if w.active and (w.trigger_profile.get('profile') or {}).get('pavilion')
                       and (w.trigger_profile.get('profile') or {}).get('hearth_zone')==z.zone_id),None)
            pavilion_remaining=max(0,(int(ward.duration_rounds or 0)-(engine.state.round_number-ward.created_round))*6) if ward else 0
            if ward:
                wp=ward.trigger_profile['profile']
                camp['pavilion']={'position':wp['civic_center'],'until':pavilion_remaining,
                    'physical_capacity':wp.get('civic_capacity',0),'permitted_weather':wp.get('permitted_weather',[])}
            f['camp']=camp
        else:
            remaining=pavilion_remaining=0
            if camp:camp['until']=0;camp['destroyed']=1
        record={'schema':SCHEMA,'mode':'combat','epoch':engine.state.match_id,'seconds':0,
                'remaining':remaining,'pavilion_remaining':pavilion_remaining,'family_json':json.dumps(f,sort_keys=True)}
        if held is None:
            engine._apply_condition(owner,CLOCK,HEARTH,owner.entity_id,expires_on='UNTIL_REMOVED',data=record)
        elif record!=old:
            held.data=record
            record_instance_update(engine,owner,'condition',held.instance_id,held)


@hook('match_initialize')
def clear_delivered_recovery(engine):
    for actor in engine.state.actors.values():
        for held in actor.conditions.values():
            if held.condition_id==CLOCK and held.data.get('schema')==SCHEMA:
                f=json.loads(held.data['family_json'])
                if 'temporary_hp' in f or 'hp' in f:
                    f.pop('temporary_hp',None);f.pop('hp',None)
                    held.data['family_json']=json.dumps(f,sort_keys=True)
                    record_instance_update(engine,actor,'condition',held.instance_id,held)
