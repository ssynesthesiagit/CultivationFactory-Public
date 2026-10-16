"""Object delivery for the existing Imbuement base providers.

Intrinsic/special-Vessel facts are declared by the GM in the native map editor
through fact_consent_admission; item-bearer consent still belongs to the live
bearer. Physical identity, dimensions, damage and lifetime use native objects,
conditions, concentration, object damage defenses and committed events.
"""
import copy
from . import hook, effect
from ..fact_consent_admission import object_fact,KEY
PLACE='IMBUEMENT_BASE_PLACE_MANDATE'
FRAY='IMBUEMENT_BASE_FRAY_MANDATE'
ANCHOR='condition:typed.object_mandate'
VULNERABLE='condition:typed.object_mandate_vulnerability'
FAMILY='tianxia.talent.imbuement.harden_and_brittle'
PHYSICAL=['BLUDGEONING','PIERCING','SLASHING']


def valid_vessel(value):
    if set(value)!={'category','nature','intelligent_actor','legal_sources','contest'} or not all(type(value[k]) is str for k in ('category','nature','intelligent_actor')):
        return False
    contest=value['contest']
    return (value['category'] in {'object','weapon','armor','tool','corpse','plant','prepared_body','special'}
        and value['nature'] in {'mundane','magic','artifact','soul_bound','sect_treasure','inheritance'}
        and type(value['intelligent_actor']) is str
        and isinstance(value['legal_sources'],list) and len(value['legal_sources'])<=16
        and all(type(v) is str and v for v in value['legal_sources'])
        and isinstance(contest,dict) and set(contest)=={'mode','dc'}
        and type(contest['mode']) is str and contest['mode'] in {'none','check','opposed'} and type(contest['dc']) is int and contest['dc']>=0)


@hook('fact_admission_schema')
def vessel_schema(session,source,subject,kind):
    if session is None and source==PLACE and subject.startswith('map-object:') and kind=='vessel':
        return {'value_type':'document','authority':'gm:map','validate':valid_vessel,
                'description':'Object nature, special-Vessel source permission and the required contest statistics'}
    return None


@hook('compile_actions')
def object_options(info):
    from ..gate2_runtime_models import ActionDefinition
    owned=set(info.get('owned_ids') or ())
    if FAMILY not in owned:
        return None
    reach=120 if 'tianxia.talent.imbuement.sovereign_of_the_true_name_of_things' in owned else 30
    out=[]
    for base,side,name,rule in ((PLACE,'imbue','Harden',{'resistance':PHYSICAL}),
                                (FRAY,'fray','Brittle',{'brittle':PHYSICAL})):
        if base not in owned:
            continue
        source=f"action:typed.{info['short']}.mandate.{side}.{name.lower()}_object"
        out.append(ActionDefinition(source_definition_id=source,display_name=f'{"Place" if side=="imbue" else "Fray"} Mandate: {name} (object)',
            owner_id=info['actor_id'],economy='ACTION',resolution_kind='TYPED',target_kind='OBJECT',range_ft=reach,
            concentration=True,parameters={'mandate':True,'object_mandate':1,'expected_damage':0,
                'description':f'{name} on one legal object or structure section no larger than a 10-foot cube; Action, {reach} feet, 0 CP, Concentration up to 10 minutes. A bearer or intelligent item resists with a Wisdom save.',
                'typed':{'source':FAMILY,'sphere':'tianxia.sphere.imbuement','numbers':dict(info['numbers']),
                    'mandate':{'side':side,'label':name},'vessel_permissions':sorted(owned),
                    'duration':{'kind':'minutes','amount':10,'concentration':True},'riders':[],
                    'effects':[{'type':'object_mandate_rule','rule':rule}]}}))
    return out


def anchors(engine,obj):
    return [(actor,held) for actor in engine.state.actors.values() for held in actor.conditions.values()
            if held.condition_id==ANCHOR and held.data.get('object')==obj.object_id]


@hook('object_targets')
def targets(engine,actor,action):
    if (action.parameters or {}).get('object_mandate'):
        from ..object_geometry import target_cells
        return [obj.object_id for obj in engine.state.objects.values() if not obj.destroyed
                and len({c.x for c in target_cells(engine,obj)})<=2
                and len({c.y for c in target_cells(engine,obj)})<=2 and int(obj.height_ft or 5)<=10]
    if (action.parameters or {}).get('counter_mandate') and action.source_definition_id.endswith('.ally'):
        from ..property_commands import active
        return [obj.object_id for obj in engine.state.objects.values() if not obj.destroyed and active(engine,obj)]
    return []


@hook('property_command_instances')
def object_instances(engine,obj):
    if getattr(obj,'object_id',None) is None:
        return None
    return [(actor,'condition',held.instance_id) for actor,held in anchors(engine,obj)]


@hook('object_action')
def deliver(engine,actor,action,obj,candidate,intent):
    from ..typed_executor import Context,run_effects,activation_start,activation_reactions
    from .needle import ask,checkpoint_id,CHOICE
    from ..object_rules import label
    params=action.parameters or {}
    if not (params.get('object_mandate') or params.get('counter_mandate')):
        return None
    ctx=Context(engine,actor,action,intent,copy.deepcopy(params.get('typed') or {}),[],None,{'_object':obj})
    if not activation_start(ctx):
        return True
    if params.get('counter_mandate'):
        from .imbuement_mandates import counter_mandate
        if activation_reactions(ctx):
            counter_mandate(ctx,{'type':'counter_mandate'})
        return True
    fact=object_fact(obj,PLACE,'vessel')
    if fact is None:
        ctx.rider(f'{label(obj)} has no declared Vessel nature. The GM must supply its source facts before a Mandate can take hold.')
        return True
    permissions=set(ctx.typed.get('vessel_permissions') or ())
    special=fact['category'] in {'corpse','plant','prepared_body','special'} or fact['nature'] in {'artifact','soul_bound','sect_treasure','inheritance'}
    if special and not (permissions & set(fact['legal_sources'])):
        ctx.rider(f'{label(obj)} requires an explicitly permitted Vessel feature that {actor.display_name} owns.')
        return True
    side=ctx.typed['mandate']['side']
    contest=fact['contest']
    if side=='fray' and fact['nature']!='mundane' and contest['mode']=='none':
        ctx.rider(f'{label(obj)} needs the GM-declared Imbuement contest for hostile magic-item delivery.')
        return True
    if contest['mode']!='none':
        modifier=int(ctx.numbers.get('pb') or 0)+int(ctx.numbers.get('key_mod') or 0)
        roll=engine.roller.d20(modifier=modifier,actor_id=actor.entity_id,reason=f'CHECK:{ctx.source}:imbuement')
        engine._record_roll(roll)
        dc=contest['dc']
        if contest['mode']=='opposed':
            opponent=engine.state.actors.get(obj.owner_id) or engine.state.actors.get(fact['intelligent_actor'])
            own_numbers=next((((a.parameters or {}).get('typed') or {}).get('numbers') for a in engine.action_catalog.values()
                if opponent is not None and a.owner_id==opponent.entity_id
                and type((((a.parameters or {}).get('typed') or {}).get('numbers') or {}).get('key_mod')) is int),None)
            if opponent is None or own_numbers is None:
                ctx.rider('An opposed Cultivation Check needs the actual opposing creature and its native key ability statistics.')
                return True
            opposing=engine.roller.d20(modifier=int(own_numbers['pb'])+int(own_numbers['key_mod']),
                actor_id=opponent.entity_id,reason=f'CHECK:{ctx.source}:opposed_cultivation')
            engine._record_roll(opposing)
            dc=opposing.total+1  # ties preserve the defended property
        engine._append_event('CHECK_ROLLED',ctx.source,actor_id=actor.entity_id,target_ids=(obj.object_id,),
                            payload={'actor':roll.model_dump(mode='json'),'dc':dc,'success':roll.total>=dc,'skill':'Imbuement Check'})
        if roll.total<dc:
            return True
    resister=engine.state.actors.get(fact['intelligent_actor'])
    if not obj.unattended:
        # Mechanical bearer identity must come from the native object producer.
        resister=engine.state.actors.get(obj.owner_id) or resister
        if resister is None:
            ctx.rider(f'{label(obj)} has no native bearer identity; no Mandate is placed.')
            return True
    needs_save=side=='fray' and resister is not None
    if resister is not None and side=='imbue':
        from ..fact_consent_admission import admit_choice
        record=admit_choice(ctx,resister,PLACE,'willingness',ctx.source,['willing','resist'],
            labels={'willing':'Accept the item Mandate','resist':'Resist with a Wisdom saving throw'},
            prompt=f'{actor.display_name} places {action.display_name} on {label(obj)}. {resister.display_name}, declare your response.',
            expires_on='END_OF_CURRENT_TURN',readers=[actor.entity_id],automatic_options=['resist'])
        if record is None:
            return True
        needs_save=record['value']=='resist'
    elif resister is None and fact['intelligent_actor']:
        ctx.rider('The intelligent Vessel has no live native actor to make its required saving throw.')
        return True
    ctx.damage_cache['_object_resister']=resister.entity_id if resister is not None else ''
    if not activation_reactions(ctx):
        return True
    engine._start_concentration(actor,ctx.source)
    if needs_save:
        from dataclasses import replace
        saving=replace(ctx,targets=[resister],target=resister)
        run_effects(saving,[{'type':'save','ability':'wis','applies_to':'target','dc':'technique_save_dc',
            'on_fail':copy.deepcopy(ctx.typed['effects']),'on_success':[]}])
    else:
        run_effects(ctx,ctx.typed['effects'])
    from .imbuement_mandates import mandate_load
    mandate_load(ctx)
    run_effects(ctx,[{'type':'limit_concentration_duration'}])
    return True


@effect('object_mandate_rule')
def apply_rule(ctx,row):
    from ..typed_executor import effect_expiry
    obj=ctx.damage_cache.get('_object')
    if obj is None:
        return
    rule=copy.deepcopy(row['rule'])
    if rule.get('brittle'):
        from .objects import damage_defenses
        resistance=damage_defenses(ctx.engine,ctx.actor,obj,[(1,kind) for kind in PHYSICAL],ctx.source)['resistance']
        rule['had_resistance']=int(bool(resistance & set(rule['brittle'])))
        rule['vulnerability_live']=int(not rule['had_resistance'])
        if rule['vulnerability_live']:
            ctx.engine._apply_condition(ctx.actor,VULNERABLE,ctx.source,ctx.actor.entity_id,
                expires_on='START_OF_SOURCE_NEXT_TURN',data={'object':obj.object_id,'hidden':1,
                    'label':'Brittle: vulnerability to the next physical damage instance until your next turn'})
    ctx.engine._apply_condition(ctx.actor,ANCHOR,ctx.source,ctx.actor.entity_id,
        expires_on=effect_expiry(ctx,row,ctx.actor,condition=True),data={'object':obj.object_id,'rule':rule,
        'resister':ctx.damage_cache.get('_object_resister',''),
        'label':object_rule_label(ctx.action,obj,rule)})


def object_rule_label(action,obj,rule):
    """Name the Vessel, actual defense and the concentration/Set clock plainly."""
    from ..object_rules import label
    if rule.get('resistance'):
        outcome='Resistance to Bludgeoning, Piercing and Slashing damage'
    else:
        outcome='loses Resistance to Bludgeoning, Piercing and Slashing damage'
        if rule.get('vulnerability_live'):
            outcome+='; Vulnerability to its next Bludgeoning, Piercing or Slashing damage before the start of your next turn'
    return (f'{getattr(action,"display_name","Brittle")} on {label(obj)}: {outcome}; '
            'up to 10 minutes from placement, ending when concentration ends '
            'unless Set for the remaining duration without concentration.')


@hook('object_damage_defenses')
def defenses(engine,actor,obj,packets,source):
    out=[]
    for owner,held in anchors(engine,obj):
        rule=held.data.get('rule') or {}
        if rule.get('resistance'):
            out.append({'kind':'resistance','damage_types':rule['resistance']})
        if rule.get('brittle'):
            # Resistance is lost for the whole Mandate, including later grants.
            # Only the additional next-instance Vulnerability has a short clock.
            out.append({'kind':'ignore_resistance','damage_types':rule['brittle']})
            if rule.get('vulnerability_live') and any(c.condition_id==VULNERABLE and c.source_definition_id==held.source_definition_id and c.data.get('object')==obj.object_id for c in owner.conditions.values()):
                out.append({'kind':'vulnerability','damage_types':rule['brittle']})
    return out


def retire_vulnerability(engine,owner,held,obj):
    """Retain resistance loss while retiring the spent/expired one-hit rider."""
    if owner.conditions.get(held.instance_id) is not held:
        return
    rule=held.data.get('rule') or {}
    if not rule.get('vulnerability_live'):
        return
    rule={**rule,'vulnerability_live':0}
    action=engine.action_catalog.get(held.source_definition_id)
    engine._update_condition_data(owner,held,{**held.data,'rule':rule,
        'label':object_rule_label(action,obj,rule)},held.source_definition_id)


@hook('event',nested=True)
def consume_brittle(engine,event_type,kwargs):
    payload=kwargs.get('payload') or {}
    if event_type=='CONDITION_APPLIED':
        if payload.get('condition_id')!=ANCHOR:
            return
        owner=engine.state.actors.get(next(iter(kwargs.get('target_ids') or ()),None))
        held=owner.conditions.get(payload.get('instance_id')) if owner is not None else None
        obj=engine.state.objects.get((held.data or {}).get('object')) if held is not None else None
        # A restored/suppression-ended anchor must not revive an expired rider.
        if obj is not None and not any(c.condition_id==VULNERABLE
                and c.source_definition_id==held.source_definition_id and c.data.get('object')==obj.object_id
                for c in owner.conditions.values()):
            retire_vulnerability(engine,owner,held,obj)
        return
    if event_type=='CONDITION_REMOVED':
        ended=kwargs.get('ended_effect') or {}
        if ended.get('condition_id')!=VULNERABLE:
            return
        obj=engine.state.objects.get((ended.get('data') or {}).get('object'))
        if obj is not None:
            for owner,held in list(anchors(engine,obj)):
                if owner.entity_id==ended.get('target_id') and held.source_definition_id==ended.get('source_definition_id'):
                    retire_vulnerability(engine,owner,held,obj)
        return
    if event_type!='OBJECT_UPDATED':
        return
    # Application/setup updates carry no actual damage. Only committed packets
    # consume the next-instance branch; damage immunity/threshold does not.
    damage=payload.get('damage') or {}
    if int(damage.get('taken') or 0)<=0 or not (set(str(damage.get('kinds') or '').upper().split(', ')) & set(PHYSICAL)):
        return
    obj=engine.state.objects.get((payload.get('object') or {}).get('object_id'))
    if obj is None:
        return
    for owner,held in list(anchors(engine,obj)):
        rule=held.data.get('rule') or {}
        if rule.get('vulnerability_live'):
            retire_vulnerability(engine,owner,held,obj)
            for marker in list(owner.conditions.values()):
                if (marker.condition_id==VULNERABLE and marker.source_definition_id==held.source_definition_id
                        and marker.data.get('object')==obj.object_id):
                    engine._remove_condition_instance(owner,marker.instance_id,held.source_definition_id,expected=marker)




@hook('property_command_subject_instance_allowed')
def actual_object_subject(engine,subject,holder,kind,key,item):
    action=engine.action_catalog.get(item.source_definition_id)
    if not (getattr(action,'parameters',None) or {}).get('object_mandate'):
        return None
    return bool(kind=='condition' and item.condition_id==ANCHOR
                and getattr(subject,'object_id',None)==(item.data or {}).get('object'))


@hook('event',nested=True)
def ended_object_mandate(engine,event_type,kwargs):
    if event_type!='CONDITION_REMOVED':
        return
    ended=kwargs.get('ended_effect') or {}
    if ended.get('condition_id')!=ANCHOR:
        return
    source=ended.get('source_definition_id')
    actor=engine.state.actors.get(ended.get('source_actor_id'))
    if actor is None or not source:
        return
    # Set Mandate retimes its retained anchor; that removal is not an ending.
    from .persist_augment import ACTION_TAG,MANDATE,persisted,end_persisted
    cause=engine.action_catalog.get(kwargs.get('source_definition_id'))
    if (getattr(cause,'parameters',None) or {}).get(ACTION_TAG)==MANDATE:
        return
    suppressed=ANCHOR.replace('condition:typed.','condition:typed.suppressed.',1)
    if any(c.condition_id in {ANCHOR,suppressed} and c.source_definition_id==source for c in actor.conditions.values()):
        return
    if actor.concentration is not None and actor.concentration.source_definition_id==source:
        engine._end_concentration(actor,'OBJECT_MANDATE_ENDED')
    for iid,record in list(persisted(engine,actor,MANDATE)):
        if record.source_definition_id==source:
            end_persisted(engine,actor,iid,kwargs.get('source_definition_id') or source,'OBJECT_MANDATE_ENDED')


@hook('turn_end',priority=-10)
def repeat_object_fray(engine,subject):
    from ..typed_executor import Context,run_effects
    from .needle import ask,checkpoint_id,CHOICE
    from ..object_rules import label
    for obj in engine.state.objects.values():
        for owner,held in list(anchors(engine,obj)):
            if held.data.get('resister')!=subject.entity_id:
                continue
            action=engine.action_catalog.get(held.source_definition_id)
            typed=copy.deepcopy((getattr(action,'parameters',None) or {}).get('typed') or {})
            if action is None or typed.get('mandate',{}).get('side')!='fray':
                continue
            intent=getattr(engine,'_active_intent',None)
            picked=ask(engine,intent,checkpoint_id(engine,'OBJECT_FRAY_REPEAT',subject.entity_id,held.instance_id),subject,
                CHOICE+'fray_repeat',['repeat'],labels={'repeat':f'Repeat the Wisdom save to end {action.display_name} on {label(obj)}'},
                prompt=f'{subject.display_name} ends its turn. Repeat the Wisdom save against {action.display_name} on {label(obj)}?',
                name='Fray Mandate',allow_decline=True,preferred=['repeat'])
            if not picked:
                continue
            ctx=Context(engine,owner,action,intent,typed,[subject],subject,{'_object':obj})
            run_effects(ctx,[{'type':'save','ability':'wis','applies_to':'target','dc':'technique_save_dc',
                'on_fail':[],'on_success':[{'type':'object_mandate_repeat_end','owner':owner.entity_id,'instance':held.instance_id}]}])


@effect('object_mandate_repeat_end')
def end_repeated(ctx,row):
    from .end_effect import remove_instance
    owner=ctx.engine.state.actors.get(row['owner'])
    held=owner.conditions.get(row['instance']) if owner is not None else None
    obj=ctx.damage_cache.get('_object')
    if (held is not None and obj is not None and held.condition_id==ANCHOR
            and held.source_definition_id==ctx.source and held.data.get('object')==obj.object_id):
        remove_instance(ctx,owner,'condition',held.instance_id,held)
