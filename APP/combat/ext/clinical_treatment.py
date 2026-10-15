"""Default-inert source collection, exact treatment and suppression consumers.

The same clinical source contract serves Purify, Coagulate, toxin diagnosis,
Medicine/Alchemy procedures and externally authored diseases/bleeding. Native
conditions are linked only to their actual compiled source. World facts are
separately admitted; actors cannot declare their own clinical authority.
"""
from dataclasses import replace
from copy import deepcopy
import json
from . import hook, effect
from .. import clinical_sources as cs

PURIFY = 'LIFE_BASE_PURIFY_THE_PULSE'
THREAD = 'BLOOD_BASE_BLOOD_THREAD'


@hook('condition_provenance')
def clinical_provenance(engine, subject, condition_id, source, source_actor, data):
    if data.get('clinical') or condition_id == cs.SUPPRESSION:
        return None
    from ..source_instances import current
    from .source_eligibility import catalog_action
    from types import SimpleNamespace
    ctx=current(engine,source,source_actor)
    action=ctx.action if ctx is not None else catalog_action(engine,source)
    actor=engine.state.actors.get(source_actor)
    if action is None or actor is None:return None
    typed=action.parameters.get('typed') or {}
    if ctx is None:
        ctx=SimpleNamespace(engine=engine,actor=actor,action=action,source=source,
                            typed=typed,numbers=typed.get('numbers') or {},intent=getattr(engine,'_active_intent',None),
                            damage_cache={'_clinical_zone_instance':data.get('zone_id')})
    # Counters, consent, and beneficial area grants are not ailments. The
    # reviewed source supplies category; committed adverse mechanics supply
    # the actual clinical manifestation, independently of that category.
    from ..typed_executor import rules
    from ..effect_harm import classify_effect
    name=condition_id.removeprefix('condition:typed.')
    harmful=name in ('blinded','deafened','paralyzed','poisoned','sickened','bleeding') or (rules()['conditions'].get(name) or {}).get('effect_kind')=='harmful'
    manifestation={**(rules()['conditions'].get(name) or {}),**(data.get('rule') or {})}
    harmful=harmful or classify_effect({'rule':manifestation}) is True
    harmful=harmful or int(data.get('speed') or 0)<0 or bool(data.get('periodic'))
    if not harmful:
        return None
    facts=cs.native_metadata(ctx,subject,{})
    if not facts:
        return None
    groups={c.data['source_instance'] for c in subject.conditions.values() if c.condition_id==cs.SUPPRESSION}
    return {'clinical':facts,**({'suppressed':1} if facts['source_instance'] in groups else {})}


@hook('state_event')
def restore_clinical_source(engine, event):
    if event.event_type != 'CONDITION_REMOVED':
        return
    # Removing one overlapping suppressor must not release another one's source.
    payload = event.payload or {}
    if payload.get('condition_id') != cs.SUPPRESSION:
        return
    for aid in event.target_ids:
        holder = engine.state.actors[aid]
        groups = {c.data['source_instance'] for c in holder.conditions.values() if c.condition_id == cs.SUPPRESSION}
        for c in list(holder.conditions.values()):
            facts = c.data.get('clinical') or {}
            if c.data.get('suppressed') and facts.get('source_instance') not in groups:
                data = dict(c.data); data.pop('suppressed', None)
                engine._update_condition_data(holder, c, data, event.source_definition_id)


@effect('clinical_treatment')
def treatment(ctx, row):
    from .needle import ask, checkpoint_id, CHOICE
    for holder in ([ctx.target] if ctx.target is not None else ctx.targets):
        options = cs.eligible(ctx.engine, holder, ctx.actor, row['category'])
        if not options:
            continue
        ids = [iid for iid,_,_ in options]
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,'clinical_treatment',ctx.source,holder.entity_id),
            ctx.actor, CHOICE+'clinical_treatment', ids,
            labels={iid: facts['label'] for iid,_,facts in options}, preferred=ids[:1],
            prompt=f'{ctx.action.display_name}: choose one source on {holder.display_name}. '
                   'An ongoing source is suppressed, rather than ended, by Purify the Pulse.')
        for iid,condition,facts in options:
            if iid not in (chosen or []):
                continue
            if row.get('operation') == 'purify' and facts['ongoing']:
                cs.suppress(ctx.engine,ctx.actor,holder,facts,max(1,int(ctx.numbers.get('key_mod') or 0)),ctx.source)
            else:
                cs.end(ctx.engine,holder,facts,ctx.source)
            break


@hook('compile_action')
def purify_source_treatment(action, info):
    params=deepcopy(action.parameters or {}); typed=params.get('typed') or {}
    if PURIFY not in (typed.get('source'),typed.get('option_of')):
        return None
    for r in typed.get('effects') or []:
        if r.get('type') == 'remove_condition':
            r.update(type='clinical_treatment',category=r['condition'],operation='purify')
    typed['manual_inline_choice']=True
    params['description']='Purify the Pulse: Action, touch, 1 CP. Remove one disease or one Blinded, Deafened, Paralyzed or Poisoned source. Ongoing sources are suppressed for your key modifier (minimum 1) rounds. Excluded sources cannot be treated.'
    return action.model_copy(update={'parameters':params})


@hook('compile_actions')
def purify_disease_and_recipients(info):
    from ..gate2_runtime_models import ActionDefinition
    result=[]
    for action in info.get('actions') or []:
        typed=action.parameters.get('typed') or {}
        if PURIFY not in (typed.get('source'),typed.get('option_of')):
            continue
        if action.target_kind=='ALLY_OR_SELF':
            result.append(action.model_copy(update={'source_definition_id':action.source_definition_id+'#any_living',
                'target_kind':'HOSTILE_ENTITY','display_name':action.display_name+' (any living creature)'}))
    if PURIFY in info.get('owned_ids',()):
        original=next((a for a in info['actions'] if PURIFY in ((a.parameters.get('typed') or {}).get('source'),(a.parameters.get('typed') or {}).get('option_of'))),None)
        if original:
            params=deepcopy(original.parameters)
            params['typed']['effects']=[{'type':'clinical_treatment','category':'disease','operation':'purify'}]
            params['typed']['source']=PURIFY
            params['typed']['manual_inline_choice']=True
            for kind,suffix in [('ALLY_OR_SELF',''),('HOSTILE_ENTITY',' (any living creature)')]:
                result.append(original.model_copy(update={'source_definition_id':original.source_definition_id+'.disease'+suffix,
                    'display_name':'Purify the Pulse: Remove Disease'+suffix,'parameters':deepcopy(params),'target_kind':kind}))
    return result or None


@hook('candidate_allowed')
def clinical_target(engine, actor, candidate, action):
    if action is None:
        return None
    typed=action.parameters.get('typed') or {}; source=typed.get('source') or ''
    from ..physiology import trait
    if source.startswith(THREAD):
        return all(trait(engine.state.actors[aid],'meaningful_circulation') is True for aid in candidate.target_ids)
    if PURIFY in (source,typed.get('option_of')):
        return all(trait(engine.state.actors[aid],'living') is True for aid in candidate.target_ids)
    return None


@hook('fact_admission_schema')
def clinical_fact_schema(session, source, subject, kind):
    if source == 'clinical_source' and kind in ('clinical_source','clinical_protocol','clinical_anatomy'):
        return {'value_type':'document','maximum_seconds':31536000,'authority':'table_owner',
                'subject_access':kind!='clinical_source',
                'description':'An external clinical source or appropriate treatment protocol; never creature consent or a roll result.'}
    return None


@hook('fact_admission_validate')
def validate_clinical_fact(session,source,subject,kind,value):
    if source!='clinical_source':return
    from ..journey import require,integer
    if kind=='clinical_source':
        cs.external_value(value)
    elif kind=='clinical_anatomy':
        require(value and set(value)<= {'living','meaningful_circulation'} and all(type(v) is int and v in (0,1) for v in value.values()),
                'Supply explicit 0/1 anatomy declarations; unknown traits must be omitted.')
    elif kind=='clinical_protocol':
        require(set(value)=={'method','ability','skill','seconds','costs','operation','source_instance'},
            'Supply the appropriate method, ability, skill, elapsed seconds, costs and identify/treat operation.')
        require(value['method'] in ('Medicine','Alchemy','Life','Poison','purification')
                and value['ability'] in ('STR','DEX','CON','INT','WIS','CHA')
                and type(value['skill']) is str and value['skill'] and type(value['source_instance']) is str and value['source_instance']
                and integer(value['seconds'],1) and value['operation'] in ('identify','treat'), 'Supply a complete clinical procedure.')
        require(isinstance(value['costs'],dict) and all(type(k) is str and integer(v,1) for k,v in value['costs'].items()),
                'Resource costs must name existing pools and positive whole quantities.')


@hook('fact_admitted')
def collect_external_source(session,record):
    if record['source']!='clinical_source':return
    if record['kind']=='clinical_anatomy':
        from ..physiology import printed_labels
        from ..canonical import canonical_sha256
        bundle=session.state['actors'][record['subject']]['bundle']; template=bundle['actor_template']
        prefix=tuple(t for t in template.get('creature_types',[]) if not any(t.startswith('physiology:'+k+':') for k in record['value']))
        reserved=tuple(t for t in prefix if t.startswith('physiology:'))
        declared=printed_labels({'physiology':{k:bool(v) for k,v in record['value'].items()}},reserved)
        template['creature_types']=[t for t in prefix if not t.startswith('physiology:')]+list(declared)
        bundle.pop('bundle_sha256',None); bundle['bundle_sha256']=canonical_sha256(bundle)
        return
    if record['kind']!='clinical_source':return
    from ..gate2_runtime_models import ConditionInstance
    actor=session.state['actors'][record['subject']]
    value=cs.external_value(record['value'])
    # Build a real encounter snapshot from this imported creature, retaining HP,
    # resources and all previously committed clinical sources.
    if 'encounter_snapshot' not in actor:
        template=actor['bundle']['actor_template']
        hp=template['maximum_hp']
        actor['encounter_snapshot']={'current_hp':hp,'maximum_hp':hp,'temporary_hp':0,'active':1,
            'life_state':'','conditions':{}}
    snapshot=actor['encounter_snapshot']
    source_id=record['receipt_id']
    for index,name in enumerate(value['conditions']):
        key='clinical:'+source_id+':'+str(index)
        facts={'source_instance':source_id,'source':'external:'+record['scope'],'owner':'table_owner',
            'category':value['category'],'ongoing':value['ongoing'],'excluded':value['excluded'],
            'readers':record['readers'],'private':1,'label':value['label'],'dc':value['dc']}
        model=ConditionInstance(instance_id=key,condition_id='condition:typed.'+name,
            source_definition_id='external:'+record['scope'],source_actor_id=record['subject'],target_id=record['subject'],
            applied_sequence=len(session.state['events'])+1,expires_on='UNTIL_REMOVED',
            data={'clinical':facts,'label':value['label'],'external_expiry':record['expires_at']})
        snapshot['conditions'][key]=model.model_dump_json(exclude_none=True)
    session.emit('CLINICAL_SOURCE_COLLECTED',record['subject'],source_instance=source_id,
                 receipt_id=source_id,source_scope=record['scope'])


@hook('journey_elapsed')
def clinical_elapsed(session,actor_id,before,seconds,moving):
    actor=session.state['actors'][actor_id]; snapshot=actor.get('encounter_snapshot')
    if not snapshot:return
    expired_groups=set()
    for key,encoded in list(snapshot['conditions'].items()):
        c=json.loads(encoded)
        if c.get('condition_id')==cs.SUPPRESSION and c.get('data',{}).get('clinical_suppressed_until',10**30)<=session.clock():
            expired_groups.add(c['data']['source_instance'])
            snapshot['conditions'].pop(key)
            session.emit('CLINICAL_SUPPRESSION_ENDED',actor_id,source_instance=c['data']['source_instance'])
            continue
        if c.get('data',{}).get('external_expiry',10**30)<=session.clock():
            snapshot['conditions'].pop(key)
            session.emit('CLINICAL_SOURCE_ENDED',actor_id,instance_id=key,reason='source_expired')

    if expired_groups:
        for key,encoded in list(snapshot['conditions'].items()):
            c=json.loads(encoded)
            if (c.get('data',{}).get('clinical') or {}).get('source_instance') in expired_groups:
                c['data'].pop('suppressed',None)
                snapshot['conditions'][key]=json.dumps(c,sort_keys=True)


@hook('fact_admission_schema')
def clinical_consent_schema(session,source,subject,kind):
    if source=='clinical_source' and kind=='clinical_consent':
        return {'value_type':'flag','maximum_seconds':3600,'authority':'subject',
                'description':'Willingly receive the named clinical procedure on the named source.'}
    return None


@hook('journey_command')
def clinical_procedure(session,actor_id,kind,payload):
    if kind not in ('clinical_identify','clinical_treat'):return None
    from ..journey import require
    from ..fact_consent_admission import read
    from ..gate2_rolls import DeterministicRollAuthority
    require(set(payload)=={'target','source_instance','protocol_scope'},'Choose a patient, source instance and appropriate protocol.')
    target_id=payload['target']; require(target_id in session.state['actors'],'Choose a patient in this scene.')
    actor=session.state['actors'][actor_id]; target=session.state['actors'][target_id]
    require(not actor['incapacitated'] and (target_id==actor_id or session.near_visible(actor_id,target_id)),
            'Clinical procedures need a conscious practitioner and physical contact.')
    protocol=read(session,'clinical_source',target_id,'clinical_protocol',payload['protocol_scope'],actor_id)
    require(protocol is not None,'This practitioner needs an appropriate table-authored clinical protocol.')
    value=protocol['value']; require(value['operation']==kind.removeprefix('clinical_') and value['source_instance']==payload['source_instance'],'Choose a protocol for this operation and exact source.')
    snapshot=target.get('encounter_snapshot') or {}; records=snapshot.get('conditions') or {}
    models={k:json.loads(v) for k,v in records.items()}
    matches={k:c for k,c in models.items() if (c.get('data',{}).get('clinical') or {}).get('source_instance')==payload['source_instance']}
    require(bool(matches),'That source is no longer present.')
    facts=next(iter(matches.values()))['data']['clinical']
    require(type(facts.get('dc')) is int and facts['dc']>0,'This source has no admitted treatment DC; its value stays unknown.')
    require(not facts.get('excluded'),'This procedure cannot treat an excluded source.')
    if kind=='clinical_treat':
        require(not facts.get('private') or actor_id in facts.get('readers',[]),
                'Identify this source before treating it.')
    scope=payload['protocol_scope']+':'+payload['source_instance']+':'+actor_id
    consent=read(session,'clinical_source',target_id,'clinical_consent',scope,actor_id)
    require(actor_id==target_id or consent is not None and consent['value']==1,'The patient must consent to this exact source and procedure.')
    if value['method'] in ('Life','Poison'):
        sphere='tianxia.sphere.'+value['method'].lower()
        require(any((a.get('parameters',{}).get('typed') or {}).get('sphere')==sphere
                    for a in actor['bundle'].get('action_catalog',())),
                'This practitioner has not acquired the sphere required by that treatment method.')
    skills=actor['bundle'].get('skills') or {}
    require(value['skill'] in skills,'This imported practitioner needs the protocol’s actual skill statistic.')
    costs=value['costs']; require(all(actor['resources'].get(k,0)>=v for k,v in costs.items()),'The practitioner cannot pay this procedure’s resource costs.')
    for pool,amount in costs.items():
        actor['resources'][pool]-=amount
        session.emit('CLINICAL_RESOURCE_SPENT',actor_id,resource=pool,amount=amount)
    session.tick(value['seconds'])
    roller=DeterministicRollAuthority(f"clinical:{session.state['journey_id']}:{session.state['revision']}")
    roll=roller.d20(modifier=int(skills[value['skill']]),actor_id=actor_id,reason='CHECK:'+value['skill'])
    success=roll.total>=facts['dc']
    session.emit('CLINICAL_CHECK_ROLLED',actor_id,target=target_id,source_instance=payload['source_instance'],
        method=value['method'],dc=facts['dc'],natural=roll.natural_result,total=roll.total,success=int(success))
    if success:
        for key in matches:
            if key not in records:continue
            if kind=='clinical_treat':records.pop(key)
            else:
                c=json.loads(records[key]); data=c['data']['clinical']; data['readers']=sorted(set([*data.get('readers',[]),actor_id]))
                records[key]=json.dumps(c,sort_keys=True)
        session.emit('CLINICAL_SOURCE_TREATED' if kind=='clinical_treat' else 'CLINICAL_SOURCE_IDENTIFIED',actor_id,
            target=target_id,source_instance=payload['source_instance'])
    return True


@hook('journey_options')
def clinical_options(session,actor_id):
    from ..fact_consent_admission import read
    result=[]
    for target_id,target in session.state['actors'].items():
        if target_id!=actor_id and not session.near_visible(actor_id,target_id):continue
        groups={}
        for encoded in (target.get('encounter_snapshot') or {}).get('conditions',{}).values():
            c=json.loads(encoded); facts=c.get('data',{}).get('clinical')
            if facts and not facts.get('excluded'):groups[facts['source_instance']]=facts
        for record in session.state.get('fact_consent_admission',[]):
            if record['source']!='clinical_source' or record['kind']!='clinical_protocol' or record['subject']!=target_id:continue
            protocol=read(session,'clinical_source',target_id,'clinical_protocol',record['scope'],actor_id)
            if protocol is None or protocol['receipt_id']!=record['receipt_id']:continue
            for group,facts in groups.items():
                if protocol['value']['source_instance']!=group:continue
                known=not facts.get('private') or actor_id in facts.get('readers',[])
                operation=protocol['value']['operation']
                if operation=='treat' and not known:continue
                source_label=facts['label'] if known else 'an unidentified ailment'
                value=protocol['value']
                result.append({'id':'clinical:'+operation+':'+group+':'+record['scope'],
                    'kind':'clinical_'+operation,'payload':{'target':target_id,'source_instance':group,'protocol_scope':record['scope']},
                    'label':f"{value['method']}: {operation} {source_label} on {target['name']}; {value['seconds']} seconds, "
                            +(', '.join(f'{v} {k}' for k,v in value['costs'].items()) or 'no resource cost')})
    return result or None


@hook('choice_reactors')
def clinical_choice_reactors(engine):
    # Ask-me recipients remain owners of decisions during an automatic turn.
    if any((a.parameters.get('typed') or {}).get('manual_inline_choice')
           and ((a.parameters.get('typed') or {}).get('sphere') in
                ('tianxia.sphere.blood','tianxia.sphere.life','tianxia.sphere.poison'))
           for a in engine.action_catalog.values()):
        return tuple(engine.state.actors)
    return None


@hook('match_initialize', priority=100)
def clinical_external_clock(engine):
    from .effect_durations import round_token
    for bundle in getattr(engine,'typed_bundle_documents',()):
        setup=bundle.get('journey_setup') or {}
        if 'elapsed_seconds' not in setup:continue
        actor=engine.state.actors.get(bundle['actor_id'])
        if actor is None:continue
        for key,c in list(actor.conditions.items()):
            expiry=c.data.get('external_expiry')
            if expiry is None:continue
            remaining=int(expiry)-int(setup['elapsed_seconds'])
            if remaining<=0:
                actor.conditions.pop(key)
                continue
            c.expires_on=round_token(engine,max(1,(remaining+5)//6))
            c.data['external_remaining_seconds']=remaining


@hook('zone_trigger_context')
def clinical_zone_context(ctx,zone,creature,moment):
    # This is the actual delayed area's identity, never the first matching name.
    ctx.damage_cache['_clinical_zone_instance']=zone.zone_id


@hook('zone_recipient_allowed')
def clinical_zone_suppressed(engine,zone,actor,spec):
    if any(c.condition_id==cs.SUPPRESSION and c.data.get('source_instance')==zone.zone_id
           for c in cs.active_suppressions(engine,actor)):
        return False
    return None


COMPONENT='condition:typed.clinical_component'

@hook('event',nested=True)
def clinical_modifier_source(engine,event_type,kwargs):
    if event_type=='MODIFIER_REMOVED':
        mid=(kwargs.get('payload') or {}).get('modifier_id')
        # A temporarily suppressed component keeps its source link for ending.
        if (kwargs.get('payload') or {}).get('reason')=='SUPPRESSED':return
        for holder in engine.state.actors.values():
            for iid,c in list(holder.conditions.items()):
                if c.condition_id==COMPONENT and c.data.get('clinical_modifier')==mid:
                    engine._remove_condition_instance(holder,iid,c.source_definition_id,expected=c)
        return
    if event_type!='MODIFIER_APPLIED':return
    from ..source_instances import current
    source=kwargs.get('source_definition_id'); owner=kwargs.get('actor_id')
    ctx=current(engine,source,owner)
    if ctx is None:return
    mid=(kwargs.get('payload') or {}).get('modifier_id')
    for aid in kwargs.get('target_ids') or ():
        holder=engine.state.actors[aid]; modifier=holder.modifiers.get(mid)
        if modifier is None:return
        facts=cs.native_metadata(ctx,holder,{})
        if facts is None:return
        facts['selectable']=0
        engine._apply_condition(holder,COMPONENT,source,owner,expires_on=modifier.expires_on,
            data={'clinical':facts,'clinical_modifier':mid,'label':facts['label']})


@hook('journey_encounter_elapsed')
def clinical_encounter_elapsed(session,engine):
    if any(c.data.get('external_expiry') for a in engine.state.actors.values() for c in a.conditions.values()):
        # The source clock uses the rules' six-second round, including the
        # partially completed terminal round, before returning to travel.
        return int(engine.state.round_number)*6
    return None


@hook('journey_actor_snapshot')
def clinical_snapshot(actor,session,engine):
    from .effect_durations import parse_round
    relevant=[c for c in actor.conditions.values() if c.data.get('external_expiry') or c.condition_id==cs.SUPPRESSION]
    if not relevant:return None
    result=actor.model_copy(deep=True)
    for original in relevant:
        c=result.conditions[original.instance_id]
        if c.data.get('external_expiry',10**30)<=session.clock():
            result.conditions.pop(c.instance_id);continue
        c.expires_on='UNTIL_REMOVED'; c.expires_actor_id=None; c.expires_turn_count=None
        if c.condition_id==cs.SUPPRESSION:
            deadline=parse_round(original.expires_on)
            if deadline is None:continue
            rounds=max(0,deadline[0]-engine.state.round_number)
            c.data['clinical_suppressed_until']=int(session.clock())+rounds*6
    return result


@hook('presentation_hidden_conditions')
def private_clinical_conditions(engine,target):
    return tuple(c.instance_id for c in target.conditions.values()
                 if (c.data.get('clinical') or {}).get('private') or c.condition_id==COMPONENT)


@hook('observer_information_rows')
def clinical_observer_information(engine,viewer):
    rows=[];seen=set()
    for patient in engine.state.actors.values():
        for c in patient.conditions.values():
            facts=c.data.get('clinical') or {}; group=facts.get('source_instance')
            if not group or not facts.get('private') or viewer.entity_id not in facts.get('readers',[]) or group in seen:continue
            seen.add(group)
            rows.append({'kind':'declaration','viewer_id':viewer.entity_id,'authority_actor_id':facts['owner'],
                'source_id':facts['source'],'details':{'patient_id':patient.entity_id,'diagnosis':facts['label'],
                    'source_instance':group,'category':facts['category']}})
    return rows or None


@hook('observer_information_rows')
def clinical_personal_symptoms(engine,viewer):
    symptoms={}
    for c in viewer.conditions.values():
        facts=c.data.get('clinical') or {}
        if not facts.get('private') or viewer.entity_id in facts.get('readers',[]) or c.condition_id==COMPONENT:continue
        # Symptoms describe actual mechanical state without revealing a private
        # diagnosis, DC, source actor or source ability identifier.
        label=(str(c.data.get('label') or '').partition(':')[2].strip() if c.data.get('choice') else
               c.condition_id.removeprefix('condition:typed.').replace('_',' ').title())
        if label:symptoms.setdefault(facts['source_instance'],[]).append(label)
    return [{'kind':'declaration','viewer_id':viewer.entity_id,'authority_actor_id':viewer.entity_id,
             'source_id':'clinical_symptoms','details':{'symptoms':list(dict.fromkeys(labels))}}
            for labels in symptoms.values()] or None


@hook('condition_application_attempt')
def clinical_reapplication(engine,subject,condition_id,source,owner_id):
    blockers=cs.active_suppressions(engine,subject)
    if not blockers:return None
    from ..source_instances import current
    from types import SimpleNamespace
    ctx=current(engine,source,owner_id)
    if ctx is None:
        action=engine.action_catalog.get(source); owner=engine.state.actors.get(owner_id)
        if action is None or owner is None:return None
        typed=action.parameters.get('typed') or {}
        ctx=SimpleNamespace(engine=engine,actor=owner,action=action,source=source,typed=typed,
            numbers=typed.get('numbers') or {},intent=None,damage_cache={})
    facts=cs.native_metadata(ctx,subject,{})
    if facts and any(c.data.get('source_instance')==facts['source_instance'] for c in blockers):return False
    return None


@hook('effect_subject_allowed')
def clinical_whole_effect_suppression(ctx,effect,subject):
    blockers=cs.active_suppressions(ctx.engine,subject)
    if not blockers:return None
    facts=cs.native_metadata(ctx,subject,{})
    if facts and any(c.data.get('source_instance')==facts['source_instance'] for c in blockers):return False
    return None
