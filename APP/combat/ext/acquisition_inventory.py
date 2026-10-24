"""Opt-in OwnerItemStore acquisitions, native property costs and item state.

Public contract lives in combat.acquisition_inventory. General hooks:
item_activation_payment(ctx,item,property) -> {'charges': int} | None, queried
before paying; item_activation_complete(ctx,item,property,receipt) -> None after
native resolution. Missing providers preserve printed charges. A receipt is
created here from actual expenditure, never accepted from an intent payload.
"""
import copy
from . import hook, effect, query, run_strict
from .. import acquisition_inventory as inv


def action(info, key, label, economy, source, effects, **parameters):
    from ..gate2_runtime_models import ActionDefinition
    return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.inventory.{key}",
        display_name=label, owner_id=info['actor_id'], economy=economy,
        resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'source': source, 'numbers': info['numbers'], 'effects': effects,
                              'duration': {'kind':'instant'}, 'riders': [], 'manual_inline_choice': True}, **parameters})


@hook('compile_bundle')
def acquire(bundle, info):
    items = inv.collect(info.get('acquisition_items',info['owner_items']), info['actor_id'])
    if items:
        bundle = copy.deepcopy(bundle)
        attuned = set((bundle.get('carrying',{}).get('attunement') or {}).get('attuned',()))
        for item in items.values():
            item['attuned'] = int(item['inventory_key'] in attuned)
            item['compiled_attuned']=item['attuned']
            item['weapon_actions'] = [a['source_definition_id'] for a in bundle['action_catalog']
                if (a.get('parameters',{}).get('typed') or {}).get('inventory_key') == item['inventory_key']]
        bundle['inventory_other_attunement_slots']=max(0,int((bundle.get('carrying',{}).get('attunement') or {}).get('used',0))-sum(i['profile']['attunement_slots'] for i in items.values() if i['attuned']))
        carrying=bundle.get('carrying',{})
        aliases={}
        for index,row in enumerate(info['owner_items']):
            item=items.get(row.get('item_uid'))
            chassis=(row.get('record') or {}).get('chassis') or {}
            if item and row.get('equipped') and chassis.get('armor_category') not in {None,'shield'}:
                old=item['inventory_key'];item['inventory_key']='treasure_armor';aliases[old]='treasure_armor'
        if aliases:
            duplicated=[row for row in carrying.get('items',[]) if row.get('key') in aliases]
            carrying['weight_lb']=str(max(0,float(carrying.get('weight_lb') or 0)-sum(float(row.get('weight_lb') or 0) for row in duplicated)))
            carrying['items']=[row for row in carrying.get('items',[]) if row.get('key') not in aliases]
            bundle['inventory_aliases']=aliases
            attuning=carrying.get('attunement',{})
            for old,primary in aliases.items():
                if old in attuning.get('attuned',[]) and primary in attuning['attuned']:
                    attuning['attuned'].remove(old)
                    tracked=next(i for i in items.values() if i['inventory_key']==primary)
                    attuning['used']=max(0,int(attuning.get('used',0))-tracked['profile']['attunement_slots'])
            bundle['inventory_other_attunement_slots']=max(0,int(attuning.get('used',0))-sum(i['profile']['attunement_slots'] for i in items.values() if i['attuned']))
        for item in items.values():
            row=next((row for row in carrying.get('items',[]) if row.get('key')==item['inventory_key']),None)
            if row and row.get('worn'):item['location']='worn';item['placement_declared']=1
        weight_delta=0
        for item in items.values():
            if not any(row.get('key')==item['inventory_key'] for row in carrying.get('items',[])):
                carrying.setdefault('items',[]).append({'key':item['inventory_key'],'item_id':'item:'+item['id'],'name':item['name'],'quantity':item['quantity'],'weight_lb':'0','kind':item['profile']['kind'],'worn':False,**({'shield':1} if item['profile']['kind']=='shield' else {})})
        for item in items.values():
            for row in carrying.get('items',[]):
                if row.get('key')==item['inventory_key']:
                    try: old_weight=float(row.get('weight_lb') or 0)
                    except (TypeError,ValueError): old_weight=0
                    if old_weight>0:
                        item['profile']['weight_lb']=int(old_weight) if old_weight.is_integer() else str(old_weight)
                        item['weight_authority']='native_equipment'
                    else:
                        weight_delta+=float(inv.weight_lb(item['profile']))-old_weight
                        row['weight_lb']=f"{float(inv.weight_lb(item['profile'])):g}"
        if weight_delta:
            carrying['weight_lb']=f"{float(carrying.get('weight_lb') or 0)+weight_delta:g}"
        bundle['acquisition_inventory'] = items
        facts=info.get('equipment_facts')
        worn=next((i for i in items.values() if i['location']=='worn' and i['profile']['kind']=='armor'),None)
        if facts and worn:
            from .. import armour
            kit=copy.deepcopy(info['kit'])
            kit.pop('resolved_treasure_armor',None)
            kit['items']=[r for r in kit.get('items',[]) if (armour.catalog().get(r.get('item_id')) or {}).get('armor_category') in (None,'shield')]
            always,choice=armour.sheet_ac_bonuses(info['owner_sheet'],kit,facts['mods'],bundle.get('typed_passives',[]))
            bare=armour.armor_class(facts['base_ac'],kit,facts['mods'],always_on=always,choice_ac=choice,calculations=facts['calculations'],shield_override=facts['shield_ac'])
            bundle['inventory_armor']={'key':worn['inventory_key'],'unworn_ac':bare,'worn_ac':bundle['actor_template']['armor_class'],'speed_penalty':facts['strength_penalty']}
        bundle['inventory_compile']={'actor_id':info['actor_id'],'primary':info['primary'],'numbers':info['numbers']}
        from ..factory_compiler import compile_native_reaction,compile_native_enchantment_hits
        for index,row in enumerate(info.get('acquisition_items',info['owner_items'])):
            item=items.get(row.get('item_uid'))
            if item is not None:
                item['printed_refinement']=int((row.get('record') or {}).get('refinement_bonus') or 0)
                import json
                item['printed_on_hit']=json.dumps([e for e in compile_native_enchantment_hits((row.get('record') or {}).get('enchantments',[])) if e.get('type')!='rider'],sort_keys=True)
        for uid,item in items.items():
            for index,prop in enumerate(item['profile']['properties']):
                if prop['economy']!='REACTION' or not prop.get('known'):continue
                source='item:'+uid+':'+str(index)
                mechanic={'name':item['name']+': '+prop['name'],'activation':{'economy':'reaction','trigger':prop['trigger']},
                    'effects':[{'type':'inventory_activate','item':uid,'property':index}],
                    'range':{'kind':'ranged','feet':prop.get('range_ft',0)},'costs':[]}
                result=compile_native_reaction(source,mechanic,numbers={**info['numbers'],'cl':info['numbers']['cl'] if item['profile']['flags'].get('channels_user') else item['profile']['source_cl']},primary=info['primary'])
                if result:
                    rows,resources,_=result
                    for r in rows:r.update(inventory_item=uid,inventory_property=index,ask=bundle.get('reaction_plan',{}).get('mode')=='ask')
                    plan=bundle.get('reaction_plan',{})
                    plan.setdefault('choices',[]).append({'id':source,'name':mechanic['name'],'when':prop['trigger']})
                    plan.setdefault('order',[]).append(source)
                    bundle['typed_reactions'].extend(rows)
    return bundle


@hook('match_initialize',priority=50)
def initialize(engine):
    for bundle in engine.typed_bundle_documents:
        items = bundle.get('acquisition_inventory')
        actor = engine.state.actors.get(bundle['actor_id'])
        if items and actor is not None and not inv.read(actor):
            from .hand_occupancy import weapon_grips,occupancy
            occupied=occupancy(engine,actor,grips=weapon_grips(engine,actor))
            items=copy.deepcopy(items)
            for item in items.values():
                parts=[part for part,occupants in occupied.items() if any('weapon:'+weapon in occupants for weapon in item.get('weapon_actions',[]))]
                if parts:item.update(location='hand',hand=parts[0],placement_declared=1)
        if items and actor is not None and (inv.read(actor)!=items or sum(c.condition_id==inv.CONDITION for c in actor.conditions.values())!=1):
            inv.write(engine, actor, items, 'inventory:acquisition')


@hook('compile_actions')
def property_actions(info):
    items = info.get('recorded_inventory')
    if items is None:items=inv.collect(info.get('owner_items', []), info['actor_id'])
    out = []
    for uid, item in items.items():
        for index, prop in enumerate(item['profile']['properties']):
            if prop['economy']=='REACTION' or prop.get('trigger')=='on_hit' or not prop.get('known'):
                continue
            made=action(info, uid+'.'+str(index), item['name']+': '+prop['name'], prop['economy'],
                item['profile']['source_rule'], [{'type':'inventory_activate', 'item':uid,'property':index}],
                inventory_item=uid, inventory_property=index,
                description=f"{prop['economy'].replace('_',' ').title()}; {prop['charge_cost']} charges; "+('instantaneous. ' if prop['duration_seconds']==0 else f"lasts {prop['duration_seconds']} seconds. " )+prop['text'])
            typed={**made.parameters['typed'],'numbers':{**info['numbers'],'cl':info['numbers']['cl'] if item['profile']['flags'].get('channels_user') else item['profile']['source_cl']},'duration':{'kind':'instant'} if prop['duration_seconds']==0 else {'kind':'rounds','amount':max(1,(prop['duration_seconds']+5)//6)}}
            out.append(made.model_copy(update={'target_kind':prop.get('target_kind','SELF'),'range_ft':prop.get('range_ft'),'parameters':{**made.parameters,'typed':typed}}))
    return out


@hook('candidate_allowed')
def property_allowed(engine, actor, candidate, action):
    if action is None or 'inventory_item' not in action.parameters:
        return None
    item = inv.read(actor).get(action.parameters['inventory_item'])
    if item is None or not inv.usable(item,actor.entity_id) or not inv.controlled(actor,item):return False
    prop=item['profile']['properties'][action.parameters['inventory_property']]
    if not prop.get('known') or not prop.get('prerequisites_met') or not materials_available(actor,inv.read(actor),prop) or not property_requirements(engine,actor,prop):return False
    if not prop.get('repeat_same_turn') and actor.turn_flags.get('inventory_property:'+prop['name']) and (action.parameters.get('property_accelerated') or actor.turn_flags.get('inventory_accelerated:'+prop['name'])):return False
    cost=action.parameters.get('inventory_charge_cost',prop['charge_cost'])
    surge=item['surge'] if not set(prop.get('flags',[])).intersection(inv.BARRIERS-{'expensive_material'}) and item.get('surge_property',action.parameters['inventory_property'])==action.parameters['inventory_property'] else 0
    return item['charges']+surge>=cost or any(v is True for v in query('item_charge_waiver_available',engine,actor,item,prop))


@effect('inventory_activate')
def activate(ctx, row):
    if ctx.intent is None:
        from dataclasses import replace
        ctx=replace(ctx,intent=getattr(ctx.engine,'_active_intent',None))
    inv.require(ctx.intent is not None,'Item activation requires an admitted native intent.')
    items = inv.read(ctx.actor)
    item = items.get(row['item'])
    inv.require(item is not None and inv.usable(item, ctx.actor.entity_id) and inv.controlled(ctx.actor,item), 'This item is not available, attuned or lawfully controlled.')
    prop = item['profile']['properties'][row['property']]
    inv.require(prop.get('known',0) and prop.get('prerequisites_met', 0) and materials_available(ctx.actor,items,prop) and property_requirements(ctx.engine,ctx.actor,prop), 'Pay the property prerequisites and materials first.')
    key = 'inventory_property:' + prop['name']
    inv.require(prop.get('repeat_same_turn') or not ctx.actor.turn_flags.get(key) or not (ctx.action.parameters.get('property_accelerated') or ctx.actor.turn_flags.get('inventory_accelerated:'+prop['name'])), 'This named item property cannot be activated twice using Accelerated Activation this turn.')
    run_strict('item_activation_declaration',ctx,item,prop)
    cost = prop['charge_cost']
    for reply in query('item_activation_payment', ctx, item, prop):
        if reply is not None:
            cost = reply['charges']
    inv.require(type(cost) is int and 0 <= cost <= prop['charge_cost'], 'Invalid charge payment.')
    surge_spent = min(item['surge'], cost) if not set(prop.get('flags',[])).intersection(inv.BARRIERS-{'expensive_material'}) and item.get('surge_property',row['property']) == row['property'] else 0
    inv.require(item['charges'] + surge_spent >= cost, 'This property has insufficient eligible charges.')
    for cost_row in prop.get('resource_costs',[]):ctx.engine._spend_resource(ctx.actor,cost_row['resource_id'],cost_row['amount'],ctx.source)
    from ..activation_payments import reaction_completed
    if not reaction_completed(ctx.engine,ctx.actor,ctx.source,consumes_reaction=prop['economy']=='REACTION'):return
    items=inv.read(ctx.actor);item=items[row['item']]
    inv.require(inv.usable(item,ctx.actor.entity_id) and inv.controlled(ctx.actor,item),'This item is no longer available after paying its resource cost.')
    pay_materials(ctx,items,prop)
    item['surge'] -= surge_spent
    item['charges'] -= cost - surge_spent
    item['spent'] += cost - surge_spent
    item['version'] += 1
    if 'destroy_on_use' in prop.get('flags', []):
        item['profile']['flags']['consumed'] = 1
        item.update(attuned=0,bound=0,expanded_slots=0,attunement_slot='normal')
        item['location'] = 'consumed';item['quantity']=0;item['placement_declared']=1
    ctx.actor.turn_flags[key] = 1
    if ctx.action.parameters.get('property_accelerated'):
        ctx.actor.turn_flags['inventory_accelerated:'+prop['name']]=1
    inv.write(ctx.engine, ctx.actor, items, ctx.source)
    from ..typed_executor import run_effects
    run_effects(ctx, prop['effects'])
    receipt = {'id':ctx.intent.intent_id + ':' + item['id'] + ':' + str(row['property']),
               'charges_spent':cost, 'charges_waived':prop['charge_cost']-cost, 'surge_spent':surge_spent,
               'consumed':int(item['location'] == 'consumed'), 'attuned':item['attuned']}
    ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
        payload={'trigger':f"{ctx.actor.display_name} activates {item['name']}: {prop['name']} ({cost} charges).", **receipt})
    run_strict('item_activation_complete', ctx, item, prop, receipt)


@hook('journey_options')
def journey_options(session, aid):
    actor = session.state['actors'][aid]
    items = actor.get('recorded_inventory', actor['bundle'].get('acquisition_inventory', {}))
    rows=[{'id':'inventory:attune:'+uid, 'kind':'inventory_attune', 'payload':{'item':uid},
             'auto_select':0, 'label':f"{actor['name']}: attune {item['name']} in one hour; meet its requirements."}
            for uid,item in items.items() if not item['attuned'] and item['profile']['attunement_slots']]
    for uid,item in items.items():
        if item['attuned'] or not item['profile']['attunement_slots']:continue
        for reply in query('inventory_attunement_options',actor['bundle'],items,item):
            for option in reply or []:
                rows.append({'id':'inventory:attune:'+uid+':'+option['id'],'kind':'inventory_attune',
                    'payload':{'item':uid,'slot':option['id']},'auto_select':0,
                    'label':f"{actor['name']}: attune {item['name']} in {option['label']}; one hour."})
    return rows


@hook('journey_owner_command')
def journey_owner_command(session, aid, kind, payload):
    if kind == 'inventory_record':
        actor=session.state['actors'][aid];bundle=actor['bundle']
        inv.require(set(payload)=={'key','profile'},'Choose one existing equipment key and its source-scoped profile.')
        real=next((i for i in bundle.get('carrying',{}).get('items',[]) if i['key']==payload['key']),None)
        inv.require(real is not None,'This item must already exist in the native acquired equipment list.')
        items=copy.deepcopy(actor.get('recorded_inventory',bundle.get('acquisition_inventory',{})))
        inv.require(not any(i['inventory_key']==real['key'] for i in items.values()),'This actual item is already recorded; update its profile instead.')
        profile=inv.normalize_profile(payload['profile'])
        if real.get('weapon_action'):
            from ..weapon_delivery import physical_weapon_id
            for native in bundle['action_catalog']:
                params=native.get('parameters') or {};typed=params.get('typed') or {}
                if typed.get('weapon') and physical_weapon_id(native['source_definition_id'],params)==real['weapon_action']:
                    typed['inventory_key']=real['key']
        import hashlib
        uid=hashlib.sha256((aid+':'+real['key']).encode()).hexdigest()[:24]
        items[uid]={'id':uid,'name':real['name'],'owner':aid,'holder':aid,'location':'worn' if real.get('worn') else 'carried',
            'profile':profile,'charges':profile['charges'],'spent':0,'surge':0,'version':0,
            'attuned':int(real['key'] in bundle.get('carrying',{}).get('attunement',{}).get('attuned',[])),
            'bound':0,'quantity':profile['quantity'],'inventory_key':real['key'],
            'weapon_actions':[a['source_definition_id'] for a in bundle['action_catalog'] if (a.get('parameters',{}).get('typed') or {}).get('inventory_key')==real['key']],
            'acquisition':{'route':'compiled_equipment','authority':profile['authority'],'source_rule':profile['source_rule'],'recorded_at':str(session.state['seconds'])}}
        actor['recorded_inventory']=items;bundle['acquisition_inventory']=copy.deepcopy(items)
        rebuild_properties(bundle,aid)
        session.emit('ITEM_RECORDED',aid,item=uid,authority=profile['authority'],source_rule=profile['source_rule'],text=f"{actor['name']} records the existing {real['name']}; no item is created.")
        return True
    if kind == 'inventory_profile':
        actor=session.state['actors'][aid]
        items=copy.deepcopy(actor.get('recorded_inventory',actor['bundle'].get('acquisition_inventory',{})))
        inv.require(set(payload)=={'item','profile'} and payload['item'] in items,'Choose an acquired item and a source-scoped owner profile.')
        item=items[payload['item']]
        inv.require(item['owner']==aid,'Only this item’s native owner may declare its profile.')
        profile=inv.normalize_profile(payload['profile'])
        inv.require(profile['max_charges']>=item['charges']+item['surge'],'The new profile cannot erase or duplicate current charges.')
        if item.get('weight_authority')=='native_equipment':profile['weight_lb']=item['profile']['weight_lb']
        for key in ('damaged','broken','consumed','suppressed'):
            if key in item['profile']['flags']:profile['flags'][key]=item['profile']['flags'][key]
        if profile.get('object_profile') and item['profile'].get('object_profile'):
            inv.require(profile['object_profile']['hp']>=item['profile']['object_profile']['current_hp'],'A profile update cannot erase real item durability.')
            profile['object_profile']['current_hp']=item['profile']['object_profile']['current_hp']
        item['profile']=profile;item['version']+=1
        actor['recorded_inventory']=items;actor['bundle']['acquisition_inventory']=copy.deepcopy(items)
        rebuild_properties(actor['bundle'],aid)
        session.emit('ITEM_PROFILE_DECLARED',aid,item=item['id'],authority=profile['authority'],source_rule=profile['source_rule'])
        return True
    if kind == 'inventory_evidence':
        actor=session.state['actors'][aid]
        items=copy.deepcopy(actor.get('recorded_inventory',actor['bundle'].get('acquisition_inventory',{})))
        inv.require(set(payload)=={'item','authority','source_rule','expiry','detail'} and payload['item'] in items,
                    'Choose a recorded item and supply scoped new evidence.')
        inv.require(items[payload['item']]['owner']==aid and all(type(payload[k]) is str and payload[k].strip() for k in ('authority','source_rule','expiry','detail')),
                    'Evidence needs its native owner, authority, Source Rule, expiry and observation.')
        item=items[payload['item']]
        item.setdefault('evidence',[]).append({'actor':aid,**payload})
        item['version']+=1
        actor['recorded_inventory']=items;actor['bundle']['acquisition_inventory']=copy.deepcopy(items)
        session.emit('ITEM_EVIDENCE',aid,item=item['id'],authority=payload['authority'],source_rule=payload['source_rule'],expiry=payload['expiry'])
        return True
    return None


@hook('journey_command')
def journey_command(session, aid, kind, payload):
    if kind != 'inventory_attune':
        return None
    actor = session.state['actors'][aid]
    items = copy.deepcopy(actor.get('recorded_inventory', actor['bundle'].get('acquisition_inventory', {})))
    inv.require(set(payload) in ({'item'},{'item','slot'}) and payload['item'] in items, 'Choose a recorded item and its capacity.')
    item = items[payload['item']]; p = item['profile']
    inv.require(item['owner'] == aid and item['holder'] == aid and item['location'] == 'carried'
                and p['flags'].get('prerequisites_met') and not p['flags'].get('suppressed'), 'This item cannot be attuned now.')
    inv.require(not inv.resonance_refused(item,'attune',int(actor['bundle']['cl'])),'The item’s printed authority refuses this attunement.')
    slot=payload.get('slot','normal')
    options=[o for reply in query('inventory_attunement_options',actor['bundle'],items,item) for o in (reply or [])]
    inv.require(slot=='normal' or any(o['id']==slot for o in options), 'That additional attunement capacity is unavailable.')
    normal_used=int(actor['bundle'].get('inventory_other_attunement_slots',0))+sum(i['profile']['attunement_slots']-int(i.get('expanded_slots',0)) for i in items.values() if i['attuned'])
    inv.require(normal_used+p['attunement_slots']-int(slot!='normal')<=4,'No normal attunement capacity remains for this item.')
    maximum = 4
    for value in query('inventory_attunement_capacity', actor['bundle']):
        maximum += int(value or 0)
    for reply in query('inventory_attunement_allowed', actor['bundle'], items, item, maximum):
        inv.require(reply is not False, 'This item cannot occupy expanded attunement capacity.')
    inv.require(p['attunement_slots']>0 and not item['attuned'] and inv.attunement_used(actor['bundle'],items)+p['attunement_slots'] <= maximum, 'No legal attunement capacity remains.')
    session.tick(3600)
    item['attuned'] = 1
    item['attunement_slot']=slot;item['expanded_slots']=int(slot!='normal')
    actor['recorded_inventory'] = items
    actor['bundle']['acquisition_inventory'] = copy.deepcopy(items)
    session.emit('ITEM_ATTUNED', aid, item=item['id'], text=f"{actor['name']} attunes {item['name']}.")
    return True


@hook('journey_encounter_settled')
def settle_journey_inventory(session, aid, engine, creature):
    items=inv.read(creature)
    if items:
        actor=session.state['actors'][aid]
        actor['recorded_inventory']=items
        actor['bundle']['acquisition_inventory']=copy.deepcopy(items)


@hook('reaction_geometry_allowed')
def property_reaction_eligibility(engine,reactor,source,subject,row):
    if not row.get('inventory_item'):return None
    item=inv.read(reactor).get(row['inventory_item'])
    if item is None or not inv.usable(item,reactor.entity_id) or not inv.controlled(reactor,item):return False
    prop=item['profile']['properties'][row['inventory_property']]
    if not materials_available(reactor,inv.read(reactor),prop) or not property_requirements(engine,reactor,prop):return False
    return item['charges']+item['surge']>=prop['charge_cost'] or any(v is True for v in query('item_charge_waiver_available',engine,reactor,item,prop))


@hook('hand_occupants')
def held_recorded_items(engine,actor):
    return {i['hand']:'recorded_item:'+uid for uid,i in inv.read(actor).items()
            if i['location']=='hand' and i.get('hand') and not i.get('weapon_actions') and i['profile']['kind']!='shield'} or None


@hook('presentation_hidden_conditions')
def hide_inventory_bookkeeping(engine,actor):
    return {c.instance_id for c in actor.conditions.values() if c.condition_id==inv.CONDITION} or None


def material_pool(actor,items,requirement,available):
    return {uid:i for uid,i in items.items() if inv.controlled(actor,i) and i['location'] in {'hand','carried','worn'}
        and i['profile']['source_rule']==requirement['source_rule'] and i['profile'].get('unit_value',0)>=requirement.get('minimum_value',0)
        and available.get(uid,0)>0}


def materials_available(actor,items,prop):
    available={uid:i.get('quantity',1) for uid,i in items.items()}
    for m in sorted(prop.get('materials',[]),key=lambda r:-r.get('minimum_value',0)):
        needed=m['quantity']
        for uid,item in sorted(material_pool(actor,items,m,available).items(),key=lambda pair:pair[1]['profile'].get('unit_value',0)):
            used=min(needed,available[uid]);available[uid]-=used;needed-=used
        if needed:return False
    return True


def pay_materials(ctx,items,prop):
    from .needle import ask,checkpoint_id
    available={uid:i.get('quantity',1) for uid,i in items.items()}
    for index,m in enumerate(prop.get('materials',[])):
        needed=m['quantity']
        while needed:
            pool=material_pool(ctx.actor,items,m,available)
            inv.require(bool(pool),'The required real material is unavailable.')
            picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'item_material:'+str(index)+':'+str(needed),ctx.source),ctx.actor,
                'choice:needle.item_material',list(pool),labels={uid:f"{i['name']} ({available[uid]} available)" for uid,i in pool.items()},minimum=1,maximum=1,
                preferred=list(pool)[:1],prompt=f"{ctx.actor.display_name}: choose {needed} real material units for {ctx.action.display_name}. "+('These units are consumed.' if m['consume'] else 'They remain intact.'))
            inv.require(bool(picked),'Choose an actual required material.')
            uid=picked[0];count=min(needed,available[uid]);available[uid]-=count;needed-=count
            if m['consume']:
                item=items[uid];item['quantity']=item.get('quantity',1)-count;item['version']+=1
                if item['quantity']==0:item['location']='consumed';item['surge']=0;item['profile']['flags']['consumed']=1;item['placement_declared']=1
            ctx.engine._append_event('PASSIVE_TRIGGERED',ctx.source,actor_id=ctx.actor.entity_id,
                payload={'trigger':f"{ctx.actor.display_name} {'consumes' if m['consume'] else 'uses'} {count} units of {items[uid]['name']} as the item’s required material.",'material_id':uid,'quantity':count,'consumed':m['consume']})


def rebuild_properties(bundle,aid):
    """Recompile opted-in property actions from the same persisted actual ledger.

    Used by source profile input and existing-equipment recording. The general
    inventory_property_variants hook adds legal source-owned alternate economies.
    No ownership or charges are inferred from the generated actions.
    """
    import hashlib
    from ..factory_compiler import compile_native_reaction
    items=bundle.get('acquisition_inventory',{})
    sealed=bundle.get('inventory_compile') or {}
    first=next((a.get('parameters',{}).get('typed',{}).get('numbers') for a in bundle['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('numbers')), {})
    info={'actor_id':aid,'short':hashlib.sha256(aid.encode()).hexdigest()[:10],
        'numbers':sealed.get('numbers') or first,'recorded_inventory':items,
        'owned_ids':{r.get('feature_id') for r in bundle.get('typed_passives',[]) if r.get('feature_id')}}
    result=property_actions(info)
    for reply in query('inventory_property_variants',result,info):result.extend(reply or [])
    result.extend(item_interactions(info))
    removed={a['source_definition_id'] for a in bundle['action_catalog'] if 'inventory_item' in a.get('parameters',{}) or a.get('parameters',{}).get('inventory_interaction')}
    bundle['action_catalog']=[a for a in bundle['action_catalog'] if a['source_definition_id'] not in removed]+[a.model_dump(mode='json') for a in result]
    bundle['actor_template']['action_ids']=[a for a in bundle['actor_template']['action_ids'] if a not in removed]+[a.source_definition_id for a in result]
    bundle['typed_reactions']=[r for r in bundle.get('typed_reactions',[]) if not r.get('inventory_item')]
    plan=bundle.get('reaction_plan',{})
    plan['order']=[i for i in plan.get('order',[]) if not i.startswith('item:')]
    plan['choices']=[i for i in plan.get('choices',[]) if not i['id'].startswith('item:')]
    for uid,item in items.items():
        for index,prop in enumerate(item['profile']['properties']):
            if prop['economy']!='REACTION' or not prop.get('known'):continue
            source='item:'+uid+':'+str(index)
            mechanic={'name':item['name']+': '+prop['name'],'activation':{'economy':'reaction','trigger':prop['trigger']},
                'effects':[{'type':'inventory_activate','item':uid,'property':index}],
                'range':{'kind':'ranged','feet':prop.get('range_ft',0)},'costs':[]}
            reply=compile_native_reaction(source,mechanic,numbers={**info['numbers'],'cl':info['numbers']['cl'] if item['profile']['flags'].get('channels_user') else item['profile']['source_cl']},primary=sealed.get('primary','qi'))
            if reply:
                rows,_,_=reply
                for row in rows:row.update(inventory_item=uid,inventory_property=index,ask=plan.get('mode')=='ask')
                bundle['typed_reactions'].extend(rows)
                plan['order'].append(source);plan['choices'].append({'id':source,'name':mechanic['name'],'when':prop['trigger']})


@hook('journey_rest')
def printed_item_rest(session,aid):
    actor=session.state['actors'][aid]
    items=copy.deepcopy(actor.get('recorded_inventory',actor['bundle'].get('acquisition_inventory',{})))
    changed=[]
    for uid,item in items.items():
        if item['profile']['recharge'] in {'long_rest','short_rest'} and item['location']!='consumed' and not item['profile']['flags'].get('broken') and item['charges']!=item['profile']['max_charges']:
            item['charges']=item['profile']['max_charges'];item['surge']=0;item.pop('unstable_to_qi_sensing',None);item['version']+=1;changed.append(item['name'])
    if changed:
        actor['recorded_inventory']=items;actor['bundle']['acquisition_inventory']=copy.deepcopy(items)
        session.emit('ITEM_RECHARGE',aid,text='Printed rest recovery restores charges to '+', '.join(changed)+'. No other recharge or permanent cost is waived.')


@hook('compile_actions')
def item_interactions(info):
    items=info.get('recorded_inventory')
    if items is None:items=inv.collect(info.get('owner_items',[]),info['actor_id'])
    if not items:return []
    return [action(info,'interaction.'+cmd,label,'NONE','inventory:interaction',
        [{'type':'inventory_interact','command':cmd}],inventory_interaction=cmd,free_primary=True,
        description=text) for cmd,label,text in (
            ('pickup','Pick up a recorded item','Free: pick up one owned, unattended item you can touch into a legal free hand.'),
            ('drop','Drop a recorded item','Free: drop one carried or held item at your feet. The actual item leaves your hands.'))]


def interaction_pool(engine,actor,cmd):
    return {uid:item for uid,item in inv.read(actor).items() if
        (inv.touching(engine,actor,item) and (item['location']=='space' or inv.location(actor,item['inventory_key'])=='space') if cmd=='pickup'
         else inv.controlled(actor,item) and item['location'] in {'carried','hand'})}


@hook('candidate_allowed')
def interaction_available(engine,actor,candidate,action):
    if action is None or not action.parameters.get('inventory_interaction'):return None
    from .hand_occupancy import free_hands
    cmd=action.parameters['inventory_interaction']
    return bool(interaction_pool(engine,actor,cmd)) and (cmd!='pickup' or bool(free_hands(engine,actor)))


@effect('inventory_interact')
def interact(ctx,row):
    from .needle import ask,checkpoint_id
    from .hand_occupancy import free_hands
    cmd=row['command'];pool=interaction_pool(ctx.engine,ctx.actor,cmd)
    inv.require(bool(pool),'No recorded item is legally available for this interaction.')
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'inventory_interact:'+cmd,ctx.source),ctx.actor,
        'choice:needle.inventory.interact',list(pool),labels={uid:i['name'] for uid,i in pool.items()},minimum=1,maximum=1,
        preferred=list(pool)[:1],prompt=f'{ctx.actor.display_name}: choose the actual item to {cmd}.')
    inv.require(bool(selected),'Choose one actual item.')
    items=inv.read(ctx.actor);item=items[selected[0]]
    if cmd=='pickup':
        hands=free_hands(ctx.engine,ctx.actor)
        inv.require(bool(hands),'A legal free hand is required.')
        selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'inventory_hand',ctx.source),ctx.actor,
            'choice:needle.inventory.hand',list(hands),labels={h:h.replace('_',' ').title() for h in hands},minimum=1,maximum=1,
            preferred=list(hands)[:1],prompt='Choose the free hand receiving the actual item.')
        inv.require(bool(selected),'Choose a free hand.')
        item.update(location='hand',holder=ctx.actor.entity_id,hand=selected[0]);item.pop('position',None)
    else:item.update(location='space',holder='',position=ctx.actor.position.model_dump(mode='json'))
    item['placement_declared']=1;item['placement_revision']=item.get('placement_revision',0)+1;item['version']+=1
    inv.write(ctx.engine,ctx.actor,items,ctx.source)


def property_requirements(engine,actor,prop):
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    if int(bundle.get('cl',0))<prop.get('min_cl',0):return False
    totals={}
    for row in prop.get('resource_costs',[]):totals[row['resource_id']]=totals.get(row['resource_id'],0)+row['amount']
    return all(actor.resources.get(rid,0)>=amount for rid,amount in totals.items())



def attack_item(ctx):
    items=inv.read(ctx.actor)
    if not items:return None
    from .weapon_hits import weapon_identity
    identity=weapon_identity(ctx)
    return next((i for i in items.values() if identity in i.get('weapon_actions',[])),None)


@hook('attack_bonus')
def current_item_refinement(ctx,target,kind=None):
    item=attack_item(ctx)
    if item is None:return None
    desired=int(item.get('printed_refinement',0)) if item['attuned'] or not item['profile']['attunement_slots'] else 0
    return desired-int((ctx.typed.get('object_attack_profile') or ctx.typed).get('magic_bonus',0)) or None


@hook('attack_damage')
def current_item_damage_refinement(ctx,dice):
    if dice is None or not ctx.weapon_damage_dice:return None
    item=attack_item(ctx)
    if item is None:return None
    desired=int(item.get('printed_refinement',0)) if item['attuned'] or not item['profile']['attunement_slots'] else 0
    delta=desired-int((ctx.typed.get('object_attack_profile') or ctx.typed).get('magic_bonus',0))
    return dice.model_copy(update={'modifier':dice.modifier+delta}) if delta else None


@hook('effect_allowed')
def actual_item_enchantment(ctx,row):
    key=row.get('inventory_enchantment_key')
    if key is None:return None
    item=next((i for i in inv.read(ctx.actor).values() if i['inventory_key']==key),None)
    return None if item is None else bool(inv.usable(item,ctx.actor.entity_id))


@hook('hit_final')
def automatic_item_properties(ctx,target,kind):
    item=attack_item(ctx)
    proof=ctx.attack_damage_context
    if item is None or proof is None or not proof.roll_id or not inv.usable(item,ctx.actor.entity_id):return
    from dataclasses import replace
    from ..typed_executor import run_effects
    import json
    local=replace(ctx,targets=[target],target=target,intent=ctx.intent or getattr(ctx.engine,'_active_intent',None))
    if local.intent is None:return
    automatic=[p for p in item['profile']['properties'] if p.get('trigger')=='on_hit' and p.get('known') and p.get('prerequisites_met') and property_requirements(ctx.engine,ctx.actor,p)
        and (not p.get('requires_physical_grip') or item['location']=='hand')
        and (not p.get('requires_target_condition') or any(c.condition_id==p['requires_target_condition'] for c in target.conditions.values()))]
    printed=json.loads(item.get('printed_on_hit','[]'))
    # Initially unattuned native weapon actions have no enchantment effects.
    # A later real ritual restores their actual printed automatic properties.
    if item['attuned'] and not item.get('compiled_attuned') and not ctx.action.parameters.get('artifact_real_armament'):
        run_effects(local,printed)
    for prop in automatic:run_effects(local,prop['effects'])
    if not automatic and not printed:return
    receipt={'id':local.intent.intent_id+':'+item['id']+':'+proof.roll_id,'charges_spent':0,'charges_waived':0,'surge_spent':0,'consumed':0,'attuned':item['attuned']}
    ctx.engine._append_event('PASSIVE_TRIGGERED',ctx.source,actor_id=ctx.actor.entity_id,target_ids=(target.entity_id,),payload={
        'trigger':f"{item['name']} resolves its legal automatic on-hit properties.",**receipt})
    run_strict('item_activation_complete',local,item,automatic[0] if automatic else {'name':'Automatic item property'},receipt)



@hook('ac')
def stored_body_armor(engine,actor):
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    facts=bundle.get('inventory_armor')
    if not facts:return None
    item=next((i for i in inv.read(actor).values() if i['inventory_key']==facts['key']),None)
    if item and item['location']!='worn':return facts['unworn_ac']-facts['worn_ac']
    return None



@hook('inventory_committed',priority=10)
def armor_strength_requirement(engine,actor,items,source):
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==actor.entity_id),{})
    facts=bundle.get('inventory_armor')
    if not facts or not facts['speed_penalty']:return
    item=next((i for i in items.values() if i['inventory_key']==facts['key']),None)
    wanted=bool(item and item['location']!='worn')
    condition='condition:typed.recorded_armor_strength'
    existing=next((c for c in actor.conditions.values() if c.condition_id==condition),None)
    if wanted==bool(existing):return
    before=engine._effective_speed(actor)
    if wanted:engine._apply_condition(actor,condition,source,actor.entity_id,expires_on='UNTIL_REMOVED',data={'speed_delta':facts['speed_penalty'],'label':'Body armor removed: its Strength requirement no longer slows you'})
    else:
        from .condition_ownership import remove_instance
        remove_instance(engine,actor,existing.instance_id,source)
    from ..movement_budget import speed_changed
    speed_changed(engine,actor,engine._effective_speed(actor)-before,source,reason='body armor Strength requirement')


@hook('compile_weapon_traits')
def recorded_weapon_identity(info):
    """Bind a real owner-granted profile to its exact compiled equipment key.

    Only owner inventory rows that actually contain a runtime profile opt in.
    Unrecorded weapons keep their historical typed bytes and carrying identity.
    """
    if info['weapon'].get('held_from'):
        return None
    key=info['weapon'].get('inventory_key')
    for index,row in enumerate(info.get('owner_items',[])):
        if key==f'given.{index}' and (row.get('record') or {}).get('runtime_profile') is not None:
            inv.require(type(row.get('item_uid')) is str and bool(row['item_uid']), 'Recorded weapons require their actual acquired item identity.')
            return {'inventory_key':key}
    return None
