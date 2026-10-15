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
from .qi_hearthfire_sanctuary import PAVILION,RECOVERED,FEAR,WELCOME
from ..gate2_runtime_models import ConditionInstance
from .retained_updates import record_instance_update
from .qi_hearthfire_state import pavilions,welcomes,keep_pavilions,keep_welcomes

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
        if camp.get('carry'):camp['carry']['until']=base+record.get('carry_remaining',0)
        if camp.get('pavilion'):
            camp['pavilion']['until']=base+record.get('pavilion_remaining',0)
    if state.get('welcome'):state['welcome']['until']=base+record.get('welcome_remaining',0)
    if state.get('private_hearth_result'):
        state['private_hearth_result']['expires_at']=base+record.get('information_remaining',0)
        state['private_hearth_result']['remaining']=record.get('information_remaining',0)
    anchor_field_clocks(state,base)
    state['clock_epoch']=record['epoch']
    return state


def hydrate(session,aid):
    state=family_state(session,aid)
    if state:
        session.state['actors'][aid]['hearthfire']=deepcopy(state)
        return session.state['actors'][aid]['hearthfire']
    return state


def persist(session,aid):
    actor=session.state['actors'][aid];f=actor.get('hearthfire')
    if f is None:
        return
    project_field_clocks(f,session.clock())
    now=int(session.clock());camp=f.get('camp',{})
    f['clock_epoch']=session.state['journey_id']
    record={'schema':SCHEMA,'mode':'journey','epoch':session.state['journey_id'],'seconds':now,
            'welcome_remaining':max(0,f.get('welcome',{}).get('until',now)-now),
            'information_remaining':max(0,f.get('private_hearth_result',{}).get('expires_at',now)-now),
            'remaining':max(0,camp.get('until',now)-now),
            'carry_remaining':max(0,camp.get('carry',{}).get('until',now)-now),
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
    snapshot['conditions']={k:v for k,v in snapshot['conditions'].items() if json.loads(v).get('condition_id')!=CLOCK}
    snapshot['conditions'][condition.instance_id]=condition.model_dump_json()


def setup_from_snapshot(bundle):
    actor={'encounter_snapshot':(bundle.get('journey_setup') or {}).get('encounter_snapshot')}
    record=saved_record(actor)
    if not record:
        return
    f=json.loads(record['family_json']);c=f.pop('camp',None);camps=[]
    if f.get('welcome'):f['welcome']['remaining']=record.get('welcome_remaining',0)
    if f.get('private_hearth_result'):
        f['private_hearth_result']['remaining']=record.get('information_remaining',0)
    if c and record['remaining']>0:
        c['remaining']=record['remaining'];c['owner']=bundle['actor_id']
        if c.get('carry'):c['carry']['remaining']=record.get('carry_remaining',0)
        if c.get('pavilion'):c['pavilion']['remaining']=record['pavilion_remaining']
        camps=[c]
    return {'camps':camps,'recipient':f,'long_rests':0}


@hook('event',nested=True)
def native_clock_event(engine,event_type,kwargs):
    if event_type not in ('TURN_STARTED','OBJECT_UPDATED','ZONE_CREATED','ZONE_REMOVED','MOVEMENT_COMMITTED','TELEPORT_COMMITTED','ROUND_STARTED','MATCH_ENDED','CONCENTRATION_ENDED'):
        return
    # Retained zone bookkeeping is not another tick or another activation.
    if event_type=='ZONE_CREATED' and (kwargs.get('payload') or {}).get('retained_instance_update'):
        return
    update_clocks(engine)


def update_clocks(engine):
    from .qi_hearthfire import hearths
    for owner in engine.state.actors.values():
        held_rows=[(k,c) for k,c in owner.conditions.items() if c.condition_id==CLOCK]
        held=held_rows[0][1] if held_rows else None
        for key,duplicate in held_rows[1:]:
            engine._remove_condition_instance(owner,key,HEARTH,expected=duplicate)
        if held is None and not any(r.get('block')==BLOCK and r.get('feature_id')==HEARTH
                   for r in getattr(engine,'typed_passive_rows',{}).get(owner.entity_id,())):
            continue
        zones=[z for z in engine.state.zones.values() if z.active and z.owner_id==owner.entity_id
            and (z.trigger_profile.get('profile') or {}).get('hearth_object')
            and not (z.trigger_profile.get('profile') or {}).get('pavilion')
            and (obj:=engine.state.objects.get(z.trigger_profile['profile']['hearth_object'])) is not None
            and not obj.destroyed and obj.current_hp]
        live_fields=live_welcomes(engine,owner)
        if not zones and held is None and not live_fields:
            continue
        old=deepcopy(held.data) if held else {}
        f=json.loads(old.get('family_json','{}'));f.pop('temporary_hp',None);f.pop('hp',None)
        if not any(c.condition_id==FEAR for c in owner.conditions.values()):
            f.pop('fear_scene',None);f.pop('fear_boundaries',None)
        elif 'fear_boundaries' not in f:f['fear_boundaries']=2
        camp=f.get('camp')
        carry_remaining=0
        if zones:
            z=zones[0];p=z.trigger_profile['profile'];obj=engine.state.objects[p['hearth_object']]
            remaining=max(0,(int(z.duration_rounds or 0)-(engine.state.round_number-z.created_round))*6)
            camp={'position':z.center.model_dump(mode='json'),'invited':list(p.get('chosen_recipients',())),
                'host':(camp or {}).get('host',owner.entity_id),'until':remaining,'source_cl':int(z.trigger_profile['numbers']['cl']),
                'hp':obj.current_hp,'empowered_real':int(bool((obj.component or {}).get('hearth_original'))),
                'native_object':obj.model_dump(mode='json'),'suppressed':int(bool(obj.suppressed)),
                'scene':(getattr(engine,'battlefield_document',{}) or {}).get('stable_id',''),'ac':13,'bright_ft':15,'dim_ft':30,'source':HEARTH,
                'number':(camp or {}).get('number',engine.state.event_sequence+1)}
            from .area_suppression import export_continuation
            camp['area_suppression']=export_continuation(engine,z)
            if p.get('hearth_carrier'):
                carry_remaining=max(0,(int(p['carry_until'])-owner.turns_started)*6)
                camp['carry']={'center':'domain_armament' if p.get('carry_armament') else p['hearth_carrier'],'until':carry_remaining,'damage_type':p.get('hearth_initial_damage')}
            wards=[w for w in engine.state.zones.values() if w.active and (w.trigger_profile.get('profile') or {}).get('pavilion')
                       and (w.trigger_profile.get('profile') or {}).get('hearth_zone')==z.zone_id]
            pavilion_states=[];pavilion_remaining=0
            for ward in wards:
                wp=ward.trigger_profile['profile']
                pavilion_remaining=max(0,(int(ward.duration_rounds or 0)-(engine.state.round_number-ward.created_round))*6)
                pavilion_states.append({'id':wp.get('activation_ref') or ward.zone_id,'position':wp['civic_center'],
                    'until':pavilion_remaining,'remaining':pavilion_remaining,'numbers':dict(ward.trigger_profile['numbers']),
                    'physical_capacity':wp.get('civic_capacity',0),'permitted_weather':wp.get('permitted_weather',[]),
                    'people':wp.get('civic_people',0),'space_record':json.loads(wp.get('civic_space_record_json','{}')),
                    'space_remaining':max(0,int(wp.get('civic_space_seconds',0))-(engine.state.round_number-ward.created_round)*6),
                    'area_suppression':export_continuation(engine,ward)})
            keep_pavilions(camp,pavilion_states)
            f['camp']=camp
        else:
            remaining=pavilion_remaining=0
            if camp:
                camp['until']=0;camp['destroyed']=1
                oid=camp.get('native_object',{}).get('object_id')
                obj=engine.state.objects.get(oid)
                if camp.get('empowered_real') and obj is not None:
                    camp['native_object']=obj.model_dump(mode='json')
                    from .qi_hearthfire import remember_hearth_item
                    remember_hearth_item(f,camp.get('scene',''),obj)
        welcome_remaining=0;welcome_states=[]
        from .area_suppression import export_continuation
        for welcome in live_fields:
            wp=welcome.trigger_profile['profile']
            welcome_remaining=max(0,(int(welcome.duration_rounds or 0)-(engine.state.round_number-welcome.created_round))*6)
            welcome_states.append({'until':welcome_remaining,'remaining':welcome_remaining,
                'area_suppression':export_continuation(engine,welcome),
                'activation_ref':wp.get('activation_ref') or welcome.zone_id,'numbers':dict(welcome.trigger_profile['numbers']),
                'position':welcome.center.model_dump(mode='json'),'center':'self' if wp.get('center_actor') else 'hearth',
                'invited':list(wp.get('chosen_recipients',())),
                'scene':(getattr(engine,'battlefield_document',{}) or {}).get('stable_id',''),
                'concentration':1,'source_cl':int(welcome.trigger_profile['numbers']['cl']),
                'pb':int(welcome.trigger_profile['numbers']['pb']),
                'activation_ledger':{k:int(v) for k,v in welcome.per_turn_triggered.items() if k.startswith('welcome_saved:')}})
        keep_welcomes(f,welcome_states)
        record={'schema':SCHEMA,'mode':'combat','epoch':engine.state.match_id,'seconds':engine.state.round_number,
                'information_remaining':max(0,int(old.get('information_remaining',0))-6) if event_clock_elapsed(engine,old) else int(old.get('information_remaining',0)),
                'welcome_remaining':welcome_remaining,'remaining':remaining,'carry_remaining':carry_remaining,'pavilion_remaining':pavilion_remaining,'family_json':json.dumps(f,sort_keys=True)}
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


def event_clock_elapsed(engine,record):
    return record.get('mode')=='combat' and int(record.get('seconds',0))<engine.state.round_number


def live_welcomes(engine,owner):
    """Only an actual zone still bound to a current/held Concentration copy."""
    from ..concentration import held,technique_of
    copies=[c for _,c in held(owner)]
    if owner.concentration is not None:copies.append(owner.concentration)
    ids={c.zone_id for c in copies if technique_of(engine,c.source_definition_id)==WELCOME}
    return [z for z in engine.state.zones.values() if z.active and z.owner_id==owner.entity_id
        and z.zone_id in ids and z.concentration_link and (z.trigger_profile.get('profile') or {}).get('welcome')]


@hook('journey_snapshot_actor')
def welcome_snapshot(actor,session,aid,engine):
    """Pure copy: the family clock exports only this source's timed state.

    Other concentration copies and unrelated timed effects still face generic
    admission. The terminal fight and its event history remain immutable.
    """
    from ..concentration import HELD,technique_of
    from .concentration_duration import DEADLINE
    clock=next((c for c in actor.conditions.values() if c.condition_id==CLOCK),None)
    if clock is None:return
    copy=actor.model_copy(deep=True)
    if copy.concentration is not None and technique_of(engine,copy.concentration.source_definition_id)==WELCOME:
        copy.concentration=None
    copy.conditions={k:c for k,c in copy.conditions.items() if not (
        technique_of(engine,c.source_definition_id)==WELCOME and c.condition_id in (HELD,DEADLINE))}
    return copy


@hook('journey_encounter_settled')
def welcome_settled(session,aid,engine,creature):
    """Hydrate from the committed terminal clock, including cancelled fields."""
    actor=session.state['actors'][aid]
    record=saved_record(actor)
    if record is None:return
    # Force reconstruction even when this encounter was entered from travel.
    actor.get('hearthfire',{}).pop('clock_epoch',None)
    # TRAVEL_RESUMED is committed after all actors settle; this encounter's
    # remaining durations start at the current journey clock, not at zero.
    f=json.loads(record['family_json']);now=int(session.clock())
    camp=f.get('camp')
    if camp:
        camp['until']=now+record['remaining']
        if camp.get('carry'):camp['carry']['until']=now+record.get('carry_remaining',0)
        if camp.get('pavilion'):camp['pavilion']['until']=now+record.get('pavilion_remaining',0)
    if session.state['events'] and session.state['events'][-1]['kind']=='ENCOUNTER_EFFECTS_RESOLVED' and session.state['events'][-1]['actor_id']==aid:
        keep_welcomes(f,[])
    if f.get('welcome'):f['welcome']['until']=now+record.get('welcome_remaining',0)
    if f.get('private_hearth_result'):f['private_hearth_result']['expires_at']=now+record.get('information_remaining',0)
    anchor_field_clocks(f,now)
    actor['hearthfire']=f
    persist(session,aid)


THRESHOLD_CLOCK='condition:typed.hearthfire_threshold_clock'


def threshold_records(actor):
    return [(k,json.loads(value)) for k,value in (actor.get('encounter_snapshot') or {}).get('conditions',{}).items()
            if json.loads(value).get('condition_id')==THRESHOLD_CLOCK]


@hook('journey_snapshot_actor')
def hospitality_snapshot(actor,session,aid,engine):
    """Export actual next-turn conditions; never infer a save or a creature kind."""
    from .qi_hearthfire_sanctuary import THRESHOLD
    held=[(k,c) for k,c in actor.conditions.items() if c.condition_id==THRESHOLD]
    if not held:return
    copy=actor.model_copy(deep=True)
    for key,c in held:
        original=c.model_copy(deep=True)
        zone=engine.state.zones.get(c.data['zone_id'])
        if zone is not None:original.data['center']=zone.center.model_dump(mode='json')
        copy.conditions[key]=c.model_copy(update={'condition_id':THRESHOLD_CLOCK,'expires_on':'UNTIL_REMOVED',
            'expires_actor_id':None,'expires_turn_count':None,
            'data':{'condition_json':original.model_dump_json(),'remaining':6,'until':0}})
    return copy


@hook('journey_encounter_settled')
def hospitality_settled(session,aid,engine,creature):
    actor=session.state['actors'][aid]
    for key,c in threshold_records(actor):
        # Explicit GM termination applies to this actual subject, independently
        # of cancellation of the source's Concentration.
        if session.state['events'] and session.state['events'][-1]['kind']=='ENCOUNTER_EFFECTS_RESOLVED' and session.state['events'][-1]['actor_id']==aid:
            del actor['encounter_snapshot']['conditions'][key]
        else:
            c['data']['until']=int(session.clock())+c['data']['remaining']
            actor['encounter_snapshot']['conditions'][key]=json.dumps(c,sort_keys=True)


@hook('journey_elapsed')
def hospitality_elapsed(session,aid,before,seconds,moving):
    actor=session.state['actors'][aid]
    for key,c in threshold_records(actor):
        if session.clock()>=c['data']['until']:
            del actor['encounter_snapshot']['conditions'][key]
            session.emit('HOSPITALITY_THRESHOLD_ENDED',aid,source=WELCOME)


@hook('journey_step')
def hospitality_travel_step(session,aid,start,end,regions):
    from ..gate2_runtime_models import Position
    from ..journey import require
    for _,clock in threshold_records(session.state['actors'][aid]):
        if clock['data']['until']<=session.clock():continue
        c=json.loads(clock['data']['condition_json'])
        if not c['data'].get('failed'):continue
        center=c['data']['center']
        if c['source_actor_id'] in session.state['actors']:
            welcome=next((w for w in welcomes(family_state(session,c['source_actor_id'])) if w.get('activation_ref')==c['data'].get('activation_ref')), {})
            if welcome.get('until',0)>session.clock():center=welcome['position']
        center=Position.model_validate(center)
        require(session.grid.distance_ft(end,center)>=session.grid.distance_ft(start,center),
            'Threshold of Hospitality prevents willingly approaching the sanctuary center until your next turn.')


@hook('journey_combat_bundle')
def hospitality_bundle(bundle,session,aid):
    records=[]
    for _,clock in threshold_records(session.state['actors'][aid]):
        if clock['data']['until']>session.clock():
            records.append(clock['data']['condition_json'])
    if records:return {**bundle,'hospitality_setup':records}


@hook('match_initialize',priority=20)
def hospitality_combat_setup(engine):
    from .qi_hearthfire_sanctuary import THRESHOLD
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None:continue
        for key,c in list(actor.conditions.items()):
            if c.condition_id==THRESHOLD_CLOCK:
                engine._remove_condition(actor,THRESHOLD_CLOCK,WELCOME)
        for value in bundle.get('hospitality_setup',()):
            original=ConditionInstance.model_validate_json(value)
            from .effect_durations import parse,token
            parsed=parse(original.expires_on)
            if original.condition_id!=THRESHOLD or not parsed or parsed[:2]!=('start',actor.entity_id):
                raise ValueError('Hospitality continuation requires its actual native next-turn condition.')
            for zone in engine.state.zones.values():
                profile=zone.trigger_profile.get('profile') or {}
                if zone.active and zone.owner_id==original.source_actor_id and profile.get('activation_ref')==original.data.get('activation_ref') and profile.get('welcome'):
                    original.data={**original.data,'zone_id':zone.zone_id,'center':zone.center.model_dump(mode='json')}
                    break
            engine._apply_condition(actor,THRESHOLD,original.source_definition_id,original.source_actor_id,
                expires_on=token('start',actor.entity_id,actor.turns_started+1),data=original.data)


def source_fields(family):
    camp=family.get('camp',{})
    return [field for field in [camp,*pavilions(camp),*welcomes(family)] if field]


def anchor_field_clocks(family,base):
    for field in source_fields(family):
        if field is not family.get('camp') and 'remaining' in field:field['until']=base+field['remaining']
        for record in field.get('area_suppression',()):
            record['until_seconds']=base+record['remaining']
        if 'space_remaining' in field and field.get('space_record'):
            field['space_record']['expires_at']=base+field['space_remaining']
    if family.get('camp'):keep_pavilions(family['camp'],pavilions(family['camp']))
    keep_welcomes(family,welcomes(family))


def project_field_clocks(family,now):
    from math import ceil
    for field in source_fields(family):
        if field is not family.get('camp') and 'until' in field:field['remaining']=max(0,ceil(field['until']-now))
        for record in field.get('area_suppression',()):
            record['remaining']=max(0,ceil(record.get('until_seconds',now)-now))
        if field.get('space_record'):
            field['space_remaining']=max(0,ceil(field['space_record']['expires_at']-now))
    if family.get('camp'):keep_pavilions(family['camp'],pavilions(family['camp']))
    keep_welcomes(family,welcomes(family))
