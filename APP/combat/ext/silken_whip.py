"""Iron Cloth's native item, restraint, protection and field progression.

Public family queries ``cloth_items``, ``whip``, ``whip_point`` and ``prisons``
read sealed acquisition and committed state; they never infer a fabric from an
item's name. Infusion asks the owner to identify a carried flexible fabric.
The declaration records actor, source, authority and expiry on that exact item.
New family rows use
normal choices, conditions, objects, zones, damage and source clocks throughout.
"""
from __future__ import annotations
from dataclasses import replace
from typing import Any
from . import hook, effect

PREFIX = 'tianxia.subpath.qi.iron_cloth_cultivator.feature.'
SILKEN, BINDING, FLOWING, PRISON, THOUSAND = (PREFIX + x for x in
    ('silken_whip', 'binding_ribbon', 'flowing_silk', 'silken_prison', 'thousand_ribbons'))
LEVELS = {SILKEN: 3, BINDING: 6, FLOWING: 10, PRISON: 14, THOUSAND: 18}
WHIP = 'condition:typed.silken_whip'
BIND = 'condition:typed.restrained'
SLOW = 'condition:typed.iron_cloth_slow'
FIELD = 'iron_cloth_ribbons'
ATTACK = 'silken_whip.attack'
QI = 'resource:core.qi'
CONTINUATION='tianxia.subpath.qi.iron_cloth_cultivator'


def _typed(action):
    return (getattr(action, 'parameters', None) or {}).get('typed') or {}


def _rows(engine, actor):
    return [r for r in engine.typed_passive_rows.get(actor.entity_id, []) if r.get('block') == 'iron_cloth']


def _owned(engine, actor, source):
    return any(r['feature_id'] == source for r in _rows(engine, actor))


def cultivation_numbers(numbers):
    """Source-printed Qi math, independent of a sheet's Technique DC/attack."""
    attack=int(numbers['pb'])+int(numbers['key_mod'])
    return {**numbers,'attack_bonus':attack,'save_dc':8+attack}


def _numbers(engine, actor):
    return next((r['numbers'] for r in _rows(engine, actor)), {})


def whip(actor):
    """The sole recorded infusion, including its exact physical item identity."""
    return next((c for c in actor.conditions.values() if c.condition_id == WHIP), None)


def has_whip(actor):
    return whip(actor) is not None


def infusion(actor):
    """One maintained infusion, including a temporarily suppressed native copy."""
    return next((c for c in actor.conditions.values() if c.condition_id == WHIP or
        (c.data.get('declaration_source') == SILKEN and c.data.get('item_key'))),None)


def cloth_items(engine, actor, *, prison=False):
    """Current possessions, including borrowed objects, with stable source identity.

    Fabric is an explicit owner declaration. Native transfer/quantity records
    establish possession; an identical key in another owner's inventory is a
    different object. A cloth already infused by someone else is unavailable.
    """
    from .. import carry
    from .scoundrel_riders import possessions
    from ..fact_consent_admission import combat_records
    from .needle import ai_controlled
    declared={r['scope'] for r in combat_records(engine,actor,kind='iron_cloth_fabric')
              if r['source'] in (SILKEN,PRISON) and (r['value']=='flexible_fabric' or r['value']=={'fabric_kind':'flexible_fabric'})}
    result=[]
    for i in possessions(engine,actor):
        identity=i['object']; owner_id=identity.split('|',1)[0]
        original=engine.state.actors.get(owner_id)
        if ai_controlled(engine,actor) and identity not in declared:
            continue
        if original is None or carry.quantity_exhausted(engine,original,i):
            continue
        if any(o.component.get('inventory_identity')==identity and o.destroyed for o in engine.state.objects.values()):
            continue
        if any(other is not actor and (c:=infusion(other)) and c.data.get('item_object')==identity for other in engine.state.actors.values()):
            continue
        if any(o.component.get('inventory_identity')==identity and o.component.get('iron_cloth_prison') and not o.destroyed and (not prison or o.owner_id!=actor.entity_id) for o in engine.state.objects.values()):
            continue
        result.append({**i,'item_owner':owner_id})
    return result


def whip_point(engine, actor):
    """A bound physical whip follows the existing Domain Armament location."""
    from .qi_path import armament_condition, armament_point
    from ..gate2_runtime_models import Position
    w = whip(actor)
    armed = armament_condition(actor)
    if w and w.data.get('item_key'):
        from .scoundrel_riders import object_id
        identity=w.data.get('item_object') or object_id(actor.entity_id,w.data['item_key'])
        for filed in engine.state.actors.values():
            for c in filed.conditions.values():
                data=c.data
                if not data.get('item_key') or (data.get('object_id') or object_id(filed.entity_id,data['item_key']))!=identity:
                    continue
                if data.get('dropped_at'):
                    return Position(**data['dropped_at'])
                if data.get('held_by') and data['held_by']!=actor.entity_id:
                    holder=engine.state.actors.get(data['held_by'])
                    if holder:
                        return holder.position
    if w and armed and w.data.get('domain_bound'):
        x, y = armament_point(actor)
        return Position(x=x, y=y, z=actor.position.z)
    if w:
        from .. import carry
        for c in actor.conditions.values():
            if c.data.get('item_key') == w.data.get('item_key') and c.data.get('dropped_at'):
                return Position(**c.data['dropped_at'])
    return actor.position


def prisons(engine, actor):
    return [o for o in engine.state.objects.values() if not o.destroyed and o.owner_id == actor.entity_id
            and o.component.get('iron_cloth_prison')]


def _ask(engine, actor, intent, key, options, *, labels=None, count=1, decline=False, prompt='', target=None, preferred=None, automatic_options=None):
    from .needle import ask, checkpoint_id
    return ask(engine, intent, checkpoint_id(engine, 'IRON_CLOTH', key, actor.entity_id,
        target.entity_id if target else ''), actor, 'choice:needle.iron_cloth.' + key, list(options),
        minimum=count, maximum=count, allow_decline=decline, labels=labels,
        preferred=list(preferred if preferred is not None else options[:count]),
        automatic_options=automatic_options, name='Iron Cloth Cultivator', target_id=target.entity_id if target else None, prompt=prompt)


def _drop(engine, actor, condition, source):
    from .condition_events import drop_condition
    if condition.instance_id in actor.conditions:
        drop_condition(engine, actor, condition.instance_id, source)


def _ctx(engine, actor, source, intent, target=None):
    from ..typed_executor import Context
    action = next((engine.action_catalog[aid] for aid in actor.action_ids
                   if aid in engine.action_catalog and _typed(engine.action_catalog[aid]).get('source') == source), None)
    if action is None:
        from ..gate2_runtime_models import ActionDefinition
        action = ActionDefinition(source_definition_id=source, display_name=source.rsplit('.', 1)[-1].replace('_', ' ').title(),
            owner_id=actor.entity_id, economy='NONE', resolution_kind='TYPED', target_kind='SELF')
    typed = {'source': source, 'numbers': _numbers(engine, actor), 'effects': [], 'riders': [], 'duration': {'kind': 'instant'}}
    return Context(engine, actor, action, intent, typed, [target] if target else [], target, {})


@hook('compile_actions')
def whip_attack(info):
    info={**info,'numbers':cultivation_numbers(info['numbers'])}
    owned = [s for s, level in LEVELS.items() if s in info['owned_ids'] and int(info['numbers']['cl']) >= level]
    if not owned:
        return None
    paths=info['owner_sheet'].get('path_and_subpath') or {}
    identity_path=str(info['owner_sheet'].get('identity',{}).get('path') or '').lower()
    if 'qi' not in identity_path and 'tianxia.path.qi_cultivation' not in paths.get('path_record_ids',[]):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    for source in owned:
        info['passives'].append({'block': 'iron_cloth', 'feature_id': source, 'numbers': dict(info['numbers']), 'choice_owner': True})
    def make(key, name, economy, effects, *, source=SILKEN, costs=(), target='SELF', reach=None, **params):
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.iron_cloth.{key}",
            display_name=name, owner_id=info['actor_id'], economy=economy, resolution_kind='TYPED',
            target_kind=target, range_ft=reach, costs=costs, parameters={
            'iron_cloth': key, 'typed': {'source': source, 'numbers': info['numbers'], 'effects': effects,
                'manual_inline_choice': True, 'duration': {'kind': 'instant'}, 'riders': [],
                **({'weapon':{'damage':{'count':1,'sides':8,'modifier':int(info['numbers']['key_mod'])},'damage_type':'BLUDGEONING','damage_types':['BLUDGEONING','SLASHING','FORCE'],'properties':'Finesse','weapon_group':'Flexible','weapon_family':'Flexible','proficient':True,'cultivated':True},'weapon_group':'flexible','properties':['finesse'],'qi_powered':1} if key=='attack' else {})}, **params})
    result = []
    if SILKEN in owned:
        result.append(make('attack', 'Silken Whip Attack', 'ACTION', [{'type':'attack',
            'attack_kind':'cultivation_melee', 'count':max([1,*[int(r['attacks']) for r in info['passives'] if r.get('block')=='extra_attack']]), 'on_hit':[{'type':'damage','applies_to':'target',
            'weapon_damage':True}], 'on_miss':[]}],
            source=ATTACK, target='HOSTILE_ENTITY', reach=15, expected_damage=4+int(info['numbers']['key_mod']),
            description='Action: attack with your infused cloth, reach 15 feet; 1d8 plus your Qi key modifier Bludgeoning, Slashing or Force damage. Flexible, Finesse, proficient, Qi-powered.'))
        info['weapon_kinds'].append({'action_id':result[-1].source_definition_id,'name':'Silken Whip',
            'item_id':SILKEN,'weapon_family':'Flexible','weapon_group':'Flexible','melee':True,
            'ranged':False,'thrown':False,'proficient':True,'pairable':True})
        if int(info['numbers']['cl'])>=9 and 'tianxia.path.qi_cultivation.feature.domain_armament' in info['owned_ids']:
            from copy import deepcopy
            base=result[-1]
            parameters=deepcopy(base.parameters)
            parameters['typed']['weapon_source_id']=base.source_definition_id
            parameters['typed']['effects'][0]['count']=1
            armcount=3 if int(info['numbers']['cl'])>=17 else 2 if int(info['numbers']['cl'])>=13 else 1
            move_ft=30 if 'tianxia.path.qi_cultivation.feature.domain_armament_link' in info['owned_ids'] else 20
            parameters['iron_cloth_armament_move_ft']=move_ft
            parameters['typed']['weapon']['damage']['count']=armcount
            parameters['expected_damage']=armcount*9//2+int(info['numbers']['key_mod'])
            parameters['description']=f'Bonus Action: move your bound physical Silken Whip up to {move_ft} feet, then attack one creature within 5 feet for {armcount}d8 plus your Qi key modifier Bludgeoning, Slashing or Force damage. No additional Qi cost.'
            result.append(base.model_copy(update={'source_definition_id':base.source_definition_id+'.bound_armament',
                'display_name':'Silken Whip Domain Armament Attack','economy':EconomyKind.BONUS_ACTION,'range_ft':5,
                'parameters':{**parameters,'iron_cloth':'bound_attack','armament':'attack'}}))
        from copy import deepcopy
        base=result[0];parameters=deepcopy(base.parameters)
        parameters['iron_cloth_object']=True
        parameters['description']='Action: attack an object within 15 feet with your actual Silken Whip. Choose Bludgeoning, Slashing or Force damage; apply the object’s defenses. Native Extra Attack applies.'
        parameters['typed']['weapon_source_id']=base.source_definition_id
        parameters['typed']['effects']=[{'type':'iron_cloth_object_attack'}]
        result.append(base.model_copy(update={'source_definition_id':base.source_definition_id+'.object',
            'display_name':'Silken Whip: attack an object','target_kind':'OBJECT','parameters':parameters}))
        result.append(make('end_whip', 'Silken Whip: end infusion', 'NONE', [{'type':'iron_cloth_end','which':'whip'}],
            setting_only=True,ai_state_control=True,description='End your Silken Whip infusion now without an action or Qi cost. The same real cloth remains.'))
    if BINDING in owned:
        result.append(make('end_binding', 'Binding Ribbon: release', 'NONE', [{'type':'iron_cloth_end','which':'binding'}],
            source=BINDING, setting_only=True, ai_state_control=True,
            description='Release your Binding Ribbon now without an action or Qi cost. Its creature immediately regains movement unless another effect prevents it.'))
    for source in (PRISON,THOUSAND):
        if source in owned:
            result.append(make('dismiss_'+source.rsplit('.',1)[-1],
                ('Silken Prison' if source==PRISON else 'Thousand Ribbons')+': end concentration',
                'NONE',[{'type':'iron_cloth_end','which':'zone','feature':source}],source=source,
                setting_only=True,ai_state_control=True,description=('End your Silken Prison and its Concentration, freeing its captives; no action or Qi cost.' if source==PRISON else 'End Thousand Ribbons and its Concentration now; no action or Qi cost. Its scene use remains spent.')))
    return result


@hook('compile_action')
def native_actions(action, info):
    source = _typed(action).get('source')
    if source not in LEVELS or action.parameters.get('iron_cloth'):
        return action
    typed = dict(_typed(action))
    typed['numbers']=cultivation_numbers(typed['numbers'])
    typed.update(manual_inline_choice=True, riders=[])
    typed.pop('zone_spec',None)
    if source == SILKEN:
        typed['effects'] = [{'type':'iron_cloth_infuse'}]
    elif source == PRISON:
        typed['effects'] = [{'type':'iron_cloth_prison'}]
        typed['area']={**typed.get('area',{}),'explicit_harmful_recipients':'every_creature'}
    elif source == THOUSAND:
        typed['effects'] = [{'type':'iron_cloth_field'}]
    elif source in (BINDING, FLOWING):
        # These are triggered procedures, not paid independent actions.
        return action.model_copy(update={'parameters':{**action.parameters,'iron_cloth_trigger_only':True}})
    return action.model_copy(update={'parameters':{**action.parameters, 'typed':typed,'iron_cloth_native':1}})


@hook('candidate_allowed')
def whip_candidates(engine, actor, candidate, action):
    if action is None:
        return None
    typed = _typed(action); source = typed.get('source'); kind = action.parameters.get('iron_cloth')
    if kind and kind.startswith('dismiss_'):
        from .. import zones
        return any(z.owner_id==actor.entity_id and _typed(engine.action_catalog.get(z.source_definition_id)).get('source')==source for z in zones.typed_zones(engine))
    if action.parameters.get('iron_cloth_trigger_only'):
        return False
    if action.parameters.get('iron_cloth_native') and (not _owned(engine, actor, source)
            or int(_numbers(engine, actor).get('cl',0)) < LEVELS[source]):
        return False
    if action.parameters.get('armament')=='attack' and source!=ATTACK and whip(actor) and whip(actor).data.get('domain_bound'):
        return False
    if source == ATTACK:
        w=whip(actor)
        if w is None:
            return False
        if not w.data.get('item_key'):
            return True
        origin=(candidate.metadata or {}).get('effect_origin') or {}
        if kind=='bound_attack' and not w.data.get('domain_bound'):
            return False
        if w.data.get('domain_bound'):
            from .qi_path import armament_condition
            if armament_condition(actor) and not str(origin.get('id','')).startswith('iron_cloth:'):
                return False
        return any(i['object']==w.data.get('item_object') for i in cloth_items(engine,actor))
    if kind == 'end_whip':
        return infusion(actor) is not None
    if kind == 'end_binding':
        return any(c.condition_id in (BIND,SLOW) and c.data.get('binding') and c.source_actor_id == actor.entity_id
                   for a in engine.state.actors.values() for c in a.conditions.values())
    if kind == 'bind_armament':
        return bool(whip(actor) and not whip(actor).data.get('domain_bound'))
    if source == SILKEN:
        return infusion(actor) is None and (bool(cloth_items(engine, actor)) if action.parameters.get('iron_cloth_native') else True)
    if source == PRISON:
        return bool(cloth_items(engine,actor,prison=True))
    if source == THOUSAND:
        return not any(c.condition_id == 'condition:typed.iron_cloth_scene' for c in actor.conditions.values())
    return None


def _identify_fabric(ctx,item,source):
    from .effect_durations import round_token
    from ..fact_consent_admission import admit_choice, combat_records
    records=combat_records(ctx.engine,ctx.actor,kind='iron_cloth_fabric',scope=item['object'])
    record=next((r for r in reversed(records) if r['source'] in (SILKEN,PRISON) and (r['value']=='flexible_fabric' or r['value']=={'fabric_kind':'flexible_fabric'})),None)
    if record is None:
        record=admit_choice(ctx,ctx.actor,source,'iron_cloth_fabric',item['object'],['flexible_fabric'],
            labels={'flexible_fabric':f"{item['name']} is flexible cloth, ribbon, sash, sleeve, cord, banner or similar fabric."},
            prompt=source.rsplit('.',1)[-1].replace('_',' ').title()+': Identify this exact carried item as flexible fabric for this Iron Cloth feature. This private declaration expires after one hour; declining cancels activation.',
            expires_on=round_token(ctx.engine,600))
        if record is None:
            raise ValueError('Identify the selected flexible fabric before activating this feature.')
    return record


@effect('iron_cloth_infuse')
def infuse(ctx, row):
    from .effect_durations import round_token
    items = cloth_items(ctx.engine, ctx.actor)
    options = [i['object'] for i in items]
    picked = _ask(ctx.engine, ctx.actor, ctx.intent, 'fabric', options,
        labels={i['object']:i['name'] for i in items},
        prompt='Silken Whip — Bonus Action, 1 Qi, 1 hour. Identify the carried cloth, ribbon, sash, sleeve, cord or banner you infuse. Selecting confirms it is flexible fabric; it remains the same real item.')
    if not picked:
        return
    item = next(i for i in cloth_items(ctx.engine, ctx.actor) if i['object'] == picked[0])
    record=_identify_fabric(ctx,item,SILKEN)
    ctx.engine._remove_condition(ctx.actor, WHIP, ctx.source)
    ctx.engine._apply_condition(ctx.actor, WHIP, ctx.source, ctx.actor.entity_id,
        expires_on=round_token(ctx.engine, 600), data={'item_key':item['key'], 'item_name':item['name'],'item_object':item['object'],'item_owner':item['item_owner'],
        'declaration_actor':ctx.actor.entity_id, 'declaration_authority':'item_owner' if item['item_owner']==ctx.actor.entity_id else 'item_possessor',
        'fabric_receipt':record['receipt_id'], 'declaration_source':SILKEN, 'fabric_kind':'flexible_fabric', 'source_cl':int(ctx.numbers['cl']),
        'object_id':_cloth_object(ctx.engine,ctx.actor,item,ctx.source,ctx.numbers),
        'domain_bound':int(any(c.condition_id=='condition:typed.iron_cloth_bond' and c.data['item_key']==item['key'] for c in ctx.actor.conditions.values())),
        'label':f"Silken Whip: {item['name']} — 15-foot reach, 1d8 + Qi key modifier; Flexible, Finesse, proficient, Qi-powered. Ends after 1 hour."})


@effect('iron_cloth_end')
def end(ctx, row):
    if row['which'] == 'whip':
        w = infusion(ctx.actor)
        if w:
            _drop(ctx.engine, ctx.actor, w, ctx.source)
    elif row['which']=='zone':
        from .. import concentration
        wanted=row['feature']
        for iid,state in list(concentration.held(ctx.actor)):
            if _typed(ctx.engine.action_catalog.get(state.source_definition_id)).get('source')==wanted:
                concentration.end_held(ctx.engine,ctx.actor,iid,'DISMISSED')
        if ctx.actor.concentration and _typed(ctx.engine.action_catalog.get(ctx.actor.concentration.source_definition_id)).get('source')==wanted:
            ctx.engine._end_concentration(ctx.actor,'DISMISSED')
    else:
        _release_binding(ctx.engine, ctx.actor)


def _release_binding(engine, owner):
    for target in engine.state.actors.values():
        for c in list(target.conditions.values()):
            if c.condition_id in (BIND, SLOW) and c.source_actor_id == owner.entity_id and c.data.get('binding'):
                _drop(engine, target, c, BINDING)


@hook('attack_damage_type_choice')
def whip_damage_choice(ctx, attack, target, kinds, attack_index):
    if ctx.typed.get('source') != ATTACK:
        return None
    from .needle import ask,checkpoint_id
    selected=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'silken_whip_type',str(attack_index)),
        ctx.actor,'choice:needle.silken_whip_type',kinds,minimum=1,maximum=1,preferred=kinds[:1],
        labels={k:k.title()+' damage' for k in kinds},prompt=f'Silken Whip: choose the damage type for your attack on {target.display_name}.')
    return selected[0]


@hook('after_hit_choice')
def binding_hit(ctx, target, kind):
    if ctx.typed.get('source') != ATTACK or not _owned(ctx.engine, ctx.actor, BINDING) or not has_whip(ctx.actor):
        return
    key = f"{ctx.engine.state.round_number}:{ctx.engine.state.current_slot_index}"
    if ctx.actor.resources.get(QI,0) < 2 or ctx.actor.turn_flags.get('iron_cloth_round_binding_turn') == key:
        return
    picked = _ask(ctx.engine, ctx.actor, ctx.intent, 'bind_hit', ['bind'], decline=True,
        prompt=f'Binding Ribbon: your Silken Whip hit {target.display_name}. Spend 2 Qi to bind it? Once per turn; ends at your next turn start unless renewed.', target=target)
    if not picked:
        return
    ctx.engine._spend_resource(ctx.actor, QI, 2, BINDING)
    ctx.actor.turn_flags['iron_cloth_round_binding_turn'] = key
    _release_binding(ctx.engine, ctx.actor)
    from ..typed_executor import run_effects
    inner = _ctx(ctx.engine, ctx.actor, BINDING, ctx.intent, target)
    run_effects(inner, [{'type':'save','ability':'dex','basis':'cultivation','applies_to':'target',
        'on_fail':[{'type':'iron_cloth_binding_result','restrained':1}],
        'on_success':[{'type':'iron_cloth_binding_result','restrained':0}]}])


@effect('iron_cloth_binding_result', harmful=True)
def binding_result(ctx, row):
    from .effect_durations import holder_next_turn
    restrained = bool(row['restrained'])
    ctx.engine._apply_condition(ctx.target, BIND if restrained else SLOW, ctx.source, ctx.actor.entity_id,
        expires_on=holder_next_turn(ctx.actor), data={'binding':1,'source_cl':int(ctx.numbers['cl']),

        'label':f"Binding Ribbon: {'Restrained' if restrained else 'Speed −10 feet'} until {ctx.actor.display_name}'s next turn starts."})


@hook('speed')
def cloth_slow(engine, actor):
    return -10 if any(c.condition_id == SLOW for c in actor.conditions.values()) else None


@hook('turn_boundary_start')
def binding_renew(engine, owner):
    from .needle import incapacitated
    from .effect_durations import holder_next_turn
    for target in engine.state.actors.values():
        for c in list(target.conditions.values()):
            if c.condition_id != BIND or not c.data.get('binding') or c.source_actor_id != owner.entity_id:
                continue
            if not _owned(engine, owner, BINDING) or not has_whip(owner):
                _drop(engine, target, c, BINDING); continue
            if owner.resources.get(QI,0) >= 1 and not incapacitated(owner):
                picked = _ask(engine, owner, getattr(engine,'_active_intent',None), 'renew', ['extend'], decline=True,
                    prompt=f'Binding Ribbon: before {target.display_name} is freed, spend 1 Qi to keep it Restrained until your following turn starts?', target=target)
                if picked:
                    engine._spend_resource(owner,QI,1,BINDING)
                    _drop(engine,target,c,BINDING)
                    engine._apply_condition(target,BIND,BINDING,owner.entity_id,
                        expires_on=holder_next_turn(owner),data=c.data)


@hook('turn_end')
def cloth_repeat_saves(engine, target, *, nominal=False):
    if nominal:
        return
    from ..typed_executor import run_effects
    for c in list(target.conditions.values()):
        if c.condition_id != BIND or (not c.data.get('binding') and not c.data.get('iron_cloth_prison')):
            continue
        owner = engine.state.actors.get(c.source_actor_id)
        if owner is None:
            continue
        source = PRISON if c.data.get('iron_cloth_prison') else BINDING
        ctx = _ctx(engine,owner,source,getattr(engine,'_active_intent',None),target)
        run_effects(ctx,[{'type':'save','ability':'dex','basis':'cultivation','applies_to':'target','on_fail':[],
            'on_success':[{'type':'iron_cloth_escape','instance':c.instance_id,
                'object_id':c.data.get('iron_cloth_prison','')}]}])


@effect('iron_cloth_escape', harmful=False)
def escape(ctx, row):
    c = ctx.target.conditions.get(row['instance'])
    if c:
        _drop(ctx.engine,ctx.target,c,ctx.source)
    obj = ctx.engine.state.objects.get(row.get('object_id'))
    if obj:
        _outside(ctx,ctx.target,obj)


@hook('event', nested=True)
def maintain_cloth(engine, event_type, kwargs):
    if event_type not in ('MOVEMENT_COMMITTED','CONDITION_REMOVED','CONDITION_APPLIED','CONDITION_UPDATED','OBJECT_UPDATED','ZONE_REMOVED'):
        return
    from .. import carry
    owners=[a for a in engine.state.actors.values() if _rows(engine,a) or infusion(a)]
    for owner in owners:
        w = whip(owner)
        if w and w.data.get('domain_bound'):
            from .qi_path import armament_condition
            armed=armament_condition(owner)
            if armed and armed.data.get('physical_item_key')!=w.data.get('item_key'):
                engine._update_condition_data(owner,armed,{**armed.data,'physical_item_key':w.data['item_key'],
                    'physical_item_owner':w.data.get('item_owner',owner.entity_id)},SILKEN)
        cloth = next((o for o in engine.state.objects.values() if w and o.object_id==w.data.get('object_id')),None)
        if cloth and cloth.destroyed:
            _drop(engine,owner,w,SILKEN); w = None
        if w and cloth and cloth.position != whip_point(engine,owner):
            engine._update_object(cloth.model_copy(update={'position':whip_point(engine,owner)}),SILKEN,owner.entity_id)
        for target in engine.state.actors.values():
            for c in list(target.conditions.values()):
                if c.condition_id in (BIND,SLOW) and c.data.get('binding') and c.source_actor_id == owner.entity_id:
                    if w is None or (engine.grid.distance_ft(owner.position,target.position)>30
                            and engine.grid.distance_ft(whip_point(engine,owner),target.position)>30):
                        _drop(engine,target,c,BINDING)
                oid = c.data.get('iron_cloth_prison')
                if oid and (obj := engine.state.objects.get(oid)) and obj.owner_id == owner.entity_id:
                    zone = engine.state.zones.get(obj.component.get('zone_id'))
                    if obj.destroyed or not zone or not zone.active:
                        _drop(engine,target,c,PRISON)
        for obj in prisons(engine,owner):
            zone = engine.state.zones.get(obj.component.get('zone_id'))
            if not zone or not zone.active:
                _retire_prison(engine,obj)
    if event_type == 'OBJECT_UPDATED':
        doc = kwargs.get('payload',{}).get('object',{})
        if (not doc.get('destroyed') and type(doc.get('current_hp')) is int and doc['current_hp']>0
                and doc.get('component',{}).get('physical_cloth_key')):
            identity=doc['component'].get('inventory_identity')
            owner=engine.state.actors.get(doc['component'].get('inventory_owner'))
            if owner and identity==owner.entity_id+'|'+doc['component']['physical_cloth_key']:
                for c in list(owner.conditions.values()):
                    if (c.condition_id=='condition:typed.iron_cloth_broken'
                            and c.data.get('object_id')==doc['object_id']
                            and c.data.get('item_key')==doc['component']['physical_cloth_key']):
                        _drop(engine,owner,c,SILKEN)
        if doc.get('destroyed') and doc.get('component',{}).get('physical_cloth_key'):
            owner=engine.state.actors.get(doc['component'].get('inventory_owner') or doc.get('owner_id'))
            key=doc['component']['physical_cloth_key']
            if owner and not any(c.condition_id=='condition:typed.iron_cloth_broken' and c.data.get('item_key')==key for c in owner.conditions.values()):
                engine._apply_condition(owner,'condition:typed.iron_cloth_broken',SILKEN,owner.entity_id,
                    expires_on='UNTIL_REMOVED',data={'item_key':key,'object_id':doc['object_id'],
                        'label':f"{doc['component'].get('name','Infused cloth')} is physically Broken; repair the real item before using it again."})
            if owner:
                for c in list(owner.conditions.values()):
                    if c.condition_id=='condition:typed.iron_cloth_bond' and c.data.get('item_key')==key:
                        _drop(engine,owner,c,SILKEN)
        if doc.get('destroyed') and doc.get('component',{}).get('iron_cloth_prison'):
            from .. import zones
            zone = engine.state.zones.get(doc['component'].get('zone_id'))
            if zone and zone.active:
                zones.remove(engine,zone,'PRISON_DESTROYED')


@hook('final_damage')
def flowing_guard(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    hit = engine.damage_context()
    if hit is None or hit.source_id != source_id or hit.target_id != target.entity_id :
        return None
    action = engine.action_catalog.get(source_id)
    if action is None:
        return None
    typed = _typed(action)
    attacks = [e for e in typed.get('effects',[]) if e.get('type') == 'attack']
    melee = (any(e.get('attack_kind') in ('cultivation_melee','melee','unarmed') or
        (e.get('attack_kind')=='weapon' and not typed.get('range_ft')) for e in attacks)
        if attacks else (action.reach_ft is not None or action.range_ft is None))
    if not melee:
        return None
    from ..typed_reactions import can_use_reaction, spend_reaction, open_reaction
    from ..activation_payments import reaction_completed
    from .needle import incapacitated
    from ..gate2_runtime_models import DiceSpec
    attacker = engine.state.actors.get(source_actor_id)
    if attacker is None:
        return None
    reduction = 0
    for owner in sorted(engine.state.actors.values(),key=lambda a:a.entity_id):
        pending=next((c for c in owner.conditions.values() if c.condition_id=='condition:typed.iron_cloth_flowing_pending' and c.data['roll_id']==hit.roll_id and c.data['source_id']==source_id and c.data['protected']==target.entity_id),None)
        if pending:
            saved=min(max(0,amount-reduction),int(pending.data['budget']))
            engine._update_condition_data(owner,pending,{**pending.data,'budget':int(pending.data['budget'])-saved,'applied':int(pending.data['applied'])+saved},FLOWING)
            reduction+=saved
            continue
        if not _owned(engine,owner,FLOWING) or owner.resources.get(QI,0)<3 or incapacitated(owner):
            continue
        row = {'feature_id':FLOWING}
        if owner.turn_flags.get('iron_cloth_round_flowing') == engine.state.round_number or not can_use_reaction(engine,owner,attacker,row):
            continue
        if min(engine.grid.distance_ft(owner.position,target.position),engine.grid.distance_ft(whip_point(engine,owner),target.position))>15:
            continue
        from ..senses import perceives
        picked = _ask(engine,owner,intent,'flowing',['protect'],decline=True,target=target,
            automatic_options=['protect'] if (owner is target or perceives(engine,owner,target)) and (owner is attacker or perceives(engine,owner,attacker)) else [],
            prompt=f'Flowing Silk: {attacker.display_name} hit {target.display_name} with {action.display_name}. Reaction, 3 Qi, once per round: reduce damage by 3d8 + your Qi key modifier, then the attacker saves against your redirection.')
        if not picked:
            continue
        engine._spend_resource(owner,QI,3,FLOWING)
        if not reaction_completed(engine,owner,FLOWING):
            continue
        open_reaction(engine,row,owner,(target.entity_id,),'FLOWING_SILK')
        spend_reaction(engine,owner,row)
        owner.turn_flags['iron_cloth_round_flowing'] = engine.state.round_number
        roll = engine.roller.roll(DiceSpec(count=3,sides=8,modifier=int(_numbers(engine,owner)['key_mod'])),
            actor_id=owner.entity_id,reason='FLOWING_SILK_REDUCTION')
        engine._record_roll(roll)
        saved = min(max(0,amount-reduction),max(0,roll.total)); reduction += saved
        engine._apply_condition(owner,'condition:typed.iron_cloth_flowing_pending',FLOWING,owner.entity_id,
            expires_on='END_OF_CURRENT_TURN',data={'attacker':attacker.entity_id,'protected':target.entity_id,
                'roll_id':hit.roll_id,'source_id':source_id,'budget':max(0,roll.total)-saved,'applied':saved,'remaining_damage':0,'label':'Flowing Silk: resolve redirection after the triggering damage.'})
    return {'reduction':min(amount,reduction)} if reduction else None


@hook('attack_damage_final')
def flowing_after(engine, attacking, protected, hit, intent):
    from ..typed_executor import run_effects
    for owner in engine.state.actors.values():
        for c in list(owner.conditions.values()):
            if c.condition_id != 'condition:typed.iron_cloth_flowing_pending' or (c.data['attacker'],c.data['protected'],c.data['source_id']) != (attacking.entity_id,protected.entity_id,hit.source_id):
                continue
            _drop(engine,owner,c,FLOWING)
            attacker = engine.state.actors.get(attacking.entity_id)
            if attacker:
                ctx = _ctx(engine,owner,FLOWING,intent,attacker)
                run_effects(ctx,[{'type':'save','ability':'str','basis':'cultivation','applies_to':'target','on_fail':[
                    {'type':'iron_cloth_flowing_options','protected':protected.entity_id,'count':2 if c.data['remaining_damage']==0 and c.data['applied']>0 else 1}], 'on_success':[]}])


@effect('iron_cloth_flowing_options', harmful=True)
def flowing_options(ctx,row):
    from ..typed_executor import run_effects
    from .scoundrel_riders import held_possessions, drop_held_object
    from ..carry import operation_allowed
    from .effect_durations import holder_next_turn
    victim = ctx.engine.state.actors[row['protected']]
    objects = [i for i in held_possessions(ctx.engine,ctx.target) if not i.get('artifact') and
               operation_allowed(ctx.engine,ctx.actor,ctx.target,i,'drop',FLOWING)]
    options = ['push','pull','no_reactions','move_protected'] + (['drop'] if objects else [])
    labels = {'push':f'Push {ctx.target.display_name} 10 feet','pull':f'Pull {ctx.target.display_name} 10 feet',
        'no_reactions':f'{ctx.target.display_name} cannot take Reactions until its next turn starts',
        'move_protected':f'Move {victim.display_name} up to 10 feet without Opportunity Attacks',
        'drop':f'{ctx.target.display_name} drops one held nonartifact object'}
    picked = _ask(ctx.engine,ctx.actor,ctx.intent,'redirection',options,labels=labels,count=row['count'],target=ctx.target,
        prompt=f'Flowing Silk: {ctx.target.display_name} failed its Strength save. Choose {row["count"]} different effects; no additional Qi cost.')
    for option in picked:
        if option in ('push','pull'):
            run_effects(ctx,[{'type':'forced_movement','applies_to':'target','distance_ft':10,'direction':'toward' if option=='pull' else 'away'}])
        elif option == 'no_reactions':
            ctx.engine._apply_condition(ctx.target,'condition:typed.reaction_denied',ctx.source,ctx.actor.entity_id,
                expires_on=holder_next_turn(ctx.target),data={'label':'Flowing Silk: cannot take Reactions until its next turn starts.'})
        elif option == 'drop':
            objects = [i for i in held_possessions(ctx.engine,ctx.target) if not i.get('artifact') and
               operation_allowed(ctx.engine,ctx.actor,ctx.target,i,'drop',FLOWING)]
            keys = [i['object'] for i in objects]
            selection = _ask(ctx.engine,ctx.actor,ctx.intent,'drop',keys,labels={i['object']:i['name'] for i in objects},
                prompt=f'Flowing Silk: choose the nonartifact object {ctx.target.display_name} drops.',target=ctx.target)
            if selection:
                drop_held_object(ctx.engine,ctx.target,next(i for i in objects if i['object']==selection[0]),source=FLOWING,by=ctx.actor)
        elif option == 'move_protected':
            _free_move(ctx,victim,10,'protected_move',forced=True)


def _free_move(ctx, target, feet, key, *, forced=False):
    if forced:
        from ..senses import perceives_cell
        from .rider_movement import forced_route
        reachable=ctx.engine.grid.reachable(target.position,movement_ft=feet,
            occupied_cells=ctx.engine._occupied_cells_except(target.entity_id),footprint=ctx.engine._footprint(target))
        routes=[(p,path) for p,(path,cost) in reachable.items() if p!=target.position]
        picks=_ask(ctx.engine,ctx.actor,ctx.intent,key,[str(i) for i in range(len(routes))],
            decline=True,target=target,automatic_options=[str(i) for i,(p,path) in enumerate(routes) if all(perceives_cell(ctx.engine,ctx.actor,s) for s in path)],labels={str(i):f'Move {target.display_name} to {p.x}, {p.y}' for i,(p,path) in enumerate(routes)},
            prompt=f'Flowing Silk: move {target.display_name} up to {feet} feet without Opportunity Attacks. This redirection does not spend its movement or require its willingness.')
        if picks:
            forced_route(ctx.engine,target,routes[int(picks[0])][1],ctx.source,ctx.actor)
        return
    from .granted_movement import choices, move
    from ..senses import perceives_cell
    routes = choices(ctx.engine,target,feet)
    options = [str(i) for i in range(len(routes))]
    # The feature's owner chooses the redirection, while an ally's optional
    # start-turn move belongs to that ally. Callers set ctx.actor accordingly.
    pick = _ask(ctx.engine,ctx.actor,ctx.intent,key,options,decline=True,target=target,
        labels={str(i):f'Move {target.display_name} to {r.destination.x}, {r.destination.y}, height {r.destination.z}' for i,r in enumerate(routes)},
        automatic_options=[str(i) for i,r in enumerate(routes) if perceives_cell(ctx.engine,ctx.actor,r.destination)],
        preferred=[str(i) for i,r in enumerate(routes) if perceives_cell(ctx.engine,ctx.actor,r.destination)][:1],
        prompt=f'Thousand Ribbons: choose up to {feet} feet of movement for {target.display_name}, without Opportunity Attacks, or stay put.')
    if pick:
        move(ctx.engine,target,routes[int(pick[0])],ctx.intent,feet,list(ctx.engine.state.actors),name='Silken ribbons')


def _retire_prison(engine,obj):
    from ..asset_anchor_runtime import retire,refresh
    profile=obj.component.get('physical_profile')
    if profile and not obj.destroyed:
        from ..gate2_runtime_models import RuntimeObjectState
        engine._update_object(RuntimeObjectState.model_validate({**obj.model_dump(mode='json'),**profile,
            'current_hp':min(obj.current_hp,profile['current_hp'])}),PRISON,obj.owner_id)
        refresh(engine)
    else:
        retire(engine,obj,PRISON)


@effect('iron_cloth_prison')
def prison(ctx,row):
    from .. import zones, typed_executor as te
    from ..gate2_runtime_models import RuntimeObjectState
    from ..save_dcs import save_dc
    items=cloth_items(ctx.engine,ctx.actor,prison=True)
    selected=_ask(ctx.engine,ctx.actor,ctx.intent,'prison_fabric',[i['object'] for i in items],
        labels={i['object']:i['name'] for i in items},
        prompt='Silken Prison: Action, 5 Qi, Concentration for one minute. Choose its real cloth. Using your whip ends that infusion and binding; it remains the same physical item.')
    if not selected:
        raise ValueError('Choose the real cloth forming Silken Prison.')
    item=next(i for i in items if i['object']==selected[0])
    record=_identify_fabric(ctx,item,PRISON)
    w=infusion(ctx.actor)
    if w and w.data.get('item_object')==item['object']:
        _drop(ctx.engine,ctx.actor,w,SILKEN)
    for old in prisons(ctx.engine,ctx.actor):
        zone = ctx.engine.state.zones.get(old.component['zone_id'])
        if zone and zone.active:
            zones.remove(ctx.engine,zone,'REPLACED')
    zone = zones.create(ctx,{'name':'Silken Prison','shape':'cube','size_ft':10,'placed':1,
        'duration':{'kind':'minutes','amount':1,'concentration':True},'profile':{'iron_cloth_prison':1}})
    if zone is None:
        return
    oid=_cloth_object(ctx.engine,ctx.actor,item,ctx.source,ctx.numbers)
    physical=ctx.engine.state.objects[oid]
    profile=physical.model_dump(mode='json')
    obj = RuntimeObjectState(object_id=oid,object_kind='cultivation_anchor',position=zone.center,
        owner_id=ctx.actor.entity_id,unattended=True,flammable=False,ac=save_dc(ctx.engine,ctx.actor,'cultivation'),
        current_hp=5*int(ctx.numbers['cl']),maximum_hp=5*int(ctx.numbers['cl']),
        damage_immunities=('POISON','PSYCHIC'),component={**physical.component,'name':'Silken Prison','iron_cloth_prison':1,'physical_profile':profile,'fabric_receipt':record['receipt_id'],
        'created_by':ctx.source,'source_cl':int(ctx.numbers['cl']),'zone_id':zone.zone_id,
        'resist':['BLUDGEONING','PIERCING'],'vulnerable':['FIRE'],
        'cells':[p.model_dump(mode='json') for p in zone.affected_cells]})
    ctx.engine._update_object(obj,ctx.source,ctx.actor.entity_id)
    for target in list(ctx.engine.state.actors.values()):
        if target.active and zones.actor_inside_zone(ctx.engine,target,zone):
            te.run_effects(replace(ctx,target=target,targets=[target]),[{'type':'save','ability':'dex','basis':'cultivation','applies_to':'target',
                'on_fail':[{'type':'iron_cloth_prison_capture','object_id':oid}],
                'on_success':[{'type':'iron_cloth_prison_eject','object_id':oid}]}])


@effect('iron_cloth_prison_capture', harmful=True)
def prison_capture(ctx,row):
    ctx.engine._apply_condition(ctx.target,'condition:typed.restrained',ctx.source,ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED',data={'iron_cloth_prison':row['object_id'],
            'label':'Silken Prison: Restrained; repeat the Dexterity save at each turn end. You may use your Action to attack the prison.'})


@effect('iron_cloth_prison_eject', harmful=True)
def prison_eject(ctx,row):
    obj = ctx.engine.state.objects.get(row['object_id'])
    if obj:
        _outside(ctx,ctx.target,obj)


def _outside(ctx,target,obj):
    from ..gate2_runtime_models import Position
    from .needle import step_to
    cells = {(p['x'],p['y'],p.get('z',0)) for p in obj.component['cells']}
    candidates = [Position(x=x,y=y,z=target.position.z) for y in range(ctx.engine.grid.height) for x in range(ctx.engine.grid.width)
        if (x,y,target.position.z) not in cells and ctx.engine.grid.volume_legal(Position(x=x,y=y,z=target.position.z),
            occupied_cells=ctx.engine._occupied_volumes_except(target.entity_id),footprint=ctx.engine._footprint(target))]
    if not candidates:
        return
    distance = min(ctx.engine.grid.distance_ft(target.position,p) for p in candidates)
    nearest = [p for p in candidates if ctx.engine.grid.distance_ft(target.position,p)==distance]
    opts = [str(i) for i in range(len(nearest))]
    pick = _ask(ctx.engine,target,ctx.intent,'prison_exit',opts,
        labels={str(i):f'Leave Silken Prison to {p.x}, {p.y}, height {p.z}' for i,p in enumerate(nearest)},
        prompt=f'Silken Prison: {target.display_name} succeeded. Choose a nearest unoccupied space outside; no Opportunity Attacks.')
    if pick:
        step_to(ctx.engine,target,nearest[int(pick[0])],ctx.source,forced=True)


@hook('object_target_cells')
def prison_cells(engine,obj):
    if not obj.component.get('iron_cloth_prison'):
        return None
    from ..gate2_runtime_models import Position
    return tuple(Position(**p) for p in obj.component['cells'])


@effect('iron_cloth_field')
def field(ctx,row):
    from .. import zones
    ctx.engine._apply_condition(ctx.actor,'condition:typed.iron_cloth_scene',ctx.source,ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED',data={'label':'Thousand Ribbons: used once this scene.'})
    damage = _ask(ctx.engine,ctx.actor,ctx.intent,'ribbons_damage',['slashing','force'],
        labels={'slashing':'Slashing damage','force':'Force damage'},prompt='Thousand Ribbons: Action, 8 Qi, Concentration up to 1 minute. Choose Slashing or Force damage for the field.')
    zones.create(ctx,{'name':'Thousand Ribbons','shape':'sphere','size_ft':30,'centered_on_self':True,
        'follows_owner':False,'duration':{'kind':'minutes','amount':1,'concentration':True},
        'difficult':'hostile','profile':{FIELD:1},'triggers':[{'id':FIELD,'name':'Thousand Ribbons',
        'on':['enter','start'],'who':'hostile','effects':[{'type':'save','ability':'dex','basis':'cultivation','applies_to':'target',
        'on_fail':[{'type':'damage','applies_to':'target','dice':{'count':5,'sides':8},'damage_types':damage},
            {'type':'iron_cloth_field_result','failed':1}],
        'on_success':[{'type':'half_damage'},
            {'type':'iron_cloth_field_result','failed':0}]}]}]})


@effect('iron_cloth_field_result', harmful=True)
def field_result(ctx,row):
    from .effect_durations import holder_next_turn
    failed = bool(row['failed'])
    ctx.engine._apply_condition(ctx.target,'condition:typed.restrained' if failed else SLOW,ctx.source,ctx.actor.entity_id,
        expires_on=holder_next_turn(ctx.target),data={'label':'Thousand Ribbons: '+('Restrained' if failed else 'Speed −10 feet')+' until your next turn starts.'})
    if not failed:
        return
    key = f'{ctx.engine.state.round_number}:{ctx.engine.state.current_slot_index}'
    if ctx.actor.turn_flags.get('iron_cloth_round_field_move') == key:
        return
    from .. import zones
    from .rider_movement import forced_route
    zone = next((z for z in zones.typed_zones(ctx.engine) if z.owner_id == ctx.actor.entity_id and z.trigger_profile.get('profile',{}).get(FIELD)),None)
    if zone is None:
        return
    reachable = ctx.engine.grid.reachable(ctx.target.position,movement_ft=15,
        occupied_cells=ctx.engine._occupied_cells_except(ctx.target.entity_id),footprint=ctx.engine._footprint(ctx.target))
    routes = [(p,path) for p,(path,cost) in reachable.items() if p != ctx.target.position and
        all(zones.actor_inside_zone(ctx.engine,ctx.target,zone,position=s) for s in path)]
    from ..senses import perceives_cell
    pick = _ask(ctx.engine,ctx.actor,ctx.intent,'ribbons_move',[str(i) for i in range(len(routes))],decline=True,target=ctx.target,
        automatic_options=[str(i) for i,(p,path) in enumerate(routes) if all(perceives_cell(ctx.engine,ctx.actor,s) for s in path)],
        labels={str(i):f'Move {ctx.target.display_name} to {p.x}, {p.y} inside Thousand Ribbons' for i,(p,path) in enumerate(routes)},
        prompt=f'Thousand Ribbons: after {ctx.target.display_name} failed, move it up to 15 feet inside the area? Once per turn.')
    if pick:
        ctx.actor.turn_flags['iron_cloth_round_field_move'] = key
        forced_route(ctx.engine,ctx.target,routes[int(pick[0])][1],ctx.source,ctx.actor)


@hook('turn_start')
def ribbons_ally_step(engine,target):
    from .. import zones
    from ..relations import relation, ALLY
    for zone in zones.typed_zones(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if owner and zone.trigger_profile.get('profile',{}).get(FIELD) and relation(engine,owner,target)==ALLY and zones.actor_inside_zone(engine,target,zone):
            ctx = _ctx(engine,target,THOUSAND,getattr(engine,'_active_intent',None))
            _free_move(ctx,target,10,'ally_step')


@hook('effect_origins')
def ribbons_origins(engine,actor,action):
    if _typed(action).get('source') != ATTACK or not has_whip(actor):
        return None
    from .. import zones
    result = []
    w=whip(actor)
    if w and w.data.get('domain_bound'):
        from .qi_path import armament_condition, armament_control_range
        from .spirit_assets import legal_spaces
        if armament_condition(actor):
            current=whip_point(engine,actor)
            places=[current]
            if action.parameters.get('iron_cloth')=='bound_attack':
                places+=legal_spaces(engine,current,int(action.parameters.get('iron_cloth_armament_move_ft',20)))
            for p in dict.fromkeys(places):
                if engine.grid.distance_ft(actor.position,p)<=armament_control_range(engine,actor):
                    result.append({'id':f'iron_cloth:bound_move:{p.x},{p.y},{p.z}',
                        'label':f'Silken Whip at {p.x}, {p.y}, height {p.z}', 'position':p.model_dump(mode='json')})
    for zone in zones.typed_zones(engine):
        if zone.owner_id == actor.entity_id and zone.trigger_profile.get('profile',{}).get(FIELD):
            result.extend({'id':f'iron_cloth:{zone.zone_id}:{p.x},{p.y},{p.z}',
                'label':f'Silken Whip from Thousand Ribbons ({p.x}, {p.y}, height {p.z})',
                'position':p.model_dump(mode='json')} for p in zones.area_cells(engine,zone))
    return result or None


@hook('condition_attempt')
def ribbons_disarm(ctx, target, row):
    if row.get('condition') != 'disarmed' or not whip(target):
        return None
    from .. import zones
    active = any(z.owner_id == target.entity_id and z.trigger_profile.get('profile',{}).get(FIELD)
                 for z in zones.typed_zones(ctx.engine))
    # A disarm aimed at another held weapon receives no protection. Native
    # disarm records its chosen actual weapon in condition_state downstream;
    # check the same public highest-damage held-weapon selection here.
    from .weapon_hits import available_weapons
    weapons = available_weapons(ctx.engine,target)
    best = max(weapons.values(), key=lambda a:int(a.parameters.get('expected_damage',0)),default=None)
    from ..observer_information import source_numbers
    source_cl=ctx.numbers.get('cl')
    if source_cl is None:
        source_cl=source_numbers(ctx.engine,ctx.source,ctx.actor.entity_id).get('cl')
    if active and best and _typed(best).get('source') == ATTACK and type(source_cl) is int and source_cl < int(_numbers(ctx.engine,target).get('cl') or 0):
        return False
    return None


def _travel_owned(session, aid):
    return any(r.get('block') == 'iron_cloth' and r.get('feature_id') == SILKEN
               for r in session.state['actors'][aid]['bundle'].get('typed_passives', []))


def _travel_seal(actor, session=None):
    from ..canonical import canonical_sha256
    if session is not None:
        from copy import deepcopy
        from fractions import Fraction
        persistent={k:deepcopy(v) for k,v in actor.get('source_states',{}).get(CONTINUATION,{}).items()
                    if k in ('objects','admissions')}
        state=actor['travel_effects'].get(SILKEN)
        if state:
            remaining=Fraction(state['expires_num'],state['expires_den'])-session.clock()
            if remaining>0:
                persistent['infusion']={k:deepcopy(v) for k,v in state.items() if k not in ('expires_num','expires_den')}
                persistent['remaining_num']=remaining.numerator
                persistent['remaining_den']=remaining.denominator
                if actor['bundle'].get('iron_cloth_setup'):
                    actor['bundle']['iron_cloth_setup'].update(remaining_num=remaining.numerator,remaining_den=remaining.denominator)
        if actor['bundle'].get('iron_cloth_bond'):
            persistent['bond']=deepcopy(actor['bundle']['iron_cloth_bond'])
        if persistent:
            actor.setdefault('source_states',{})[CONTINUATION]=persistent
        elif CONTINUATION in actor.get('source_states',{}):
            del actor['source_states'][CONTINUATION]
    actor['bundle'].pop('bundle_sha256',None)
    actor['bundle']['bundle_sha256'] = canonical_sha256(actor['bundle'])


@hook('journey_initialize')
def cloth_continuation(session, aid):
    from copy import deepcopy
    from fractions import Fraction
    from ..journey import require
    actor=session.state['actors'][aid]
    state=actor.get('source_states',{}).get(CONTINUATION)
    if not state:
        return
    actor['bundle']['iron_cloth_objects']=list(state.get('objects',[]))
    actor['bundle']['iron_cloth_admissions']=list(state.get('admissions',[]))
    if not _travel_owned(session,aid):
        _travel_seal(actor,session)
        return
    items=journey_cloth_items(session,aid)
    def carried(saved):
        identity=saved.get('item_object') or (saved.get('item_owner') or aid)+'|'+saved['item_key']
        return any(i['object']==identity for i in items)
    bond=state.get('bond')
    if bond and carried(bond):
        require(bond.get('actor')==aid and bond.get('source')==SILKEN,'The cloth bond belongs to another native source or creature.')
        actor['bundle']['iron_cloth_bond']=deepcopy(bond)
    infusion=state.get('infusion')
    if infusion and carried(infusion):
        require(infusion.get('declaration_actor')==aid and infusion.get('declaration_source')==SILKEN,
            'The infusion belongs to another native source or creature.')
        remaining=Fraction(state['remaining_num'],state['remaining_den'])
        require(0<remaining<=3600,'The saved infusion has an invalid remaining clock.')
        expiry=session.clock()+remaining
        restored={**deepcopy(infusion),'expires_num':expiry.numerator,'expires_den':expiry.denominator}
        actor['travel_effects'][SILKEN]=restored
        rounds=remaining/6
        actor['bundle']['iron_cloth_setup']={**restored,'remaining_rounds':(rounds.numerator+rounds.denominator-1)//rounds.denominator}
    _travel_seal(actor,session)


@hook('fact_admission_schema')
def fabric_schema(session, source, subject, kind):
    if source!=SILKEN or kind!='iron_cloth_fabric' or not _travel_owned(session,subject):
        return None
    return {'value_type':'document','maximum_seconds':3600,
            'description':'Identify one exact carried item as flexible fabric for Silken Whip.'}


@hook('journey_options')
def cloth_travel_options(session, aid):
    if not _travel_owned(session,aid) or session.state['phase'] != 'travel':
        return None
    actor = session.state['actors'][aid]
    if actor['incapacitated']:
        return None
    state = actor['travel_effects'].get(SILKEN)
    if state:
        options=[{'id':'iron_cloth.end','kind':'iron_cloth_end','payload':{},
            'label':f"End Silken Whip on {state['item_name']}; no action or Qi cost."}]
        from fractions import Fraction
        has_armament=any(a.get('parameters',{}).get('armament')=='manifest' for a in actor['bundle'].get('action_catalog',[]))
        if has_armament and not state.get('domain_bound') and Fraction(state['expires_num'],state['expires_den'])-session.clock()>600:
            options.append({'id':'iron_cloth.bind','kind':'iron_cloth_bind','payload':{'item_key':state['item_key']},
                'label':f"Bind your infused {state['item_name']} as your one real Domain Armament: 10 uninterrupted minutes touching it; no extra Qi. The actual item is never duplicated."})
        return options
    if actor['resources'].get(QI,0)<1:
        return None
    return [{'id':'iron_cloth.infuse:'+i['key'],'kind':'iron_cloth_infuse','auto_select':0,
        'payload':{'item_key':i['key'],'fabric_kind':'flexible_fabric'},
        'label':f"Silken Whip: identify {i['name']} as flexible fabric and infuse it. Bonus Action, 1 Qi, 1 hour; remains this same physical item."}
        for i in actor['bundle'].get('carrying',{}).get('items',[]) if i.get('quantity',1)>0]


@hook('journey_command')
def cloth_travel_command(session, aid, kind, payload):
    if kind not in ('iron_cloth_infuse','iron_cloth_end','iron_cloth_bind') or not _travel_owned(session,aid):
        return None
    from ..journey import require
    actor = session.state['actors'][aid]
    legal = cloth_travel_options(session,aid) or []
    require(any(o['kind']==kind and o['payload']==payload for o in legal),'Choose an available Silken Whip item and declaration.')
    if kind=='iron_cloth_bind':
        session.tick(600)
        state=actor['travel_effects'][SILKEN]
        state['domain_bound']=1
        actor['bundle']['iron_cloth_bond']={'item_key':state['item_key'],'item_name':state['item_name'],
            'authority':'item_possessor' if state.get('item_owner',aid)!=aid else 'item_owner','actor':aid,'source':SILKEN,
            'item_owner':state.get('item_owner',aid),'item_object':state.get('item_object') or aid+'|'+state['item_key']}
        actor['bundle']['iron_cloth_setup']['domain_bound']=1
        _travel_seal(actor,session)
        session.emit('TRAVEL_BINDING',aid,source=SILKEN,seconds_spent=600,
            text=f"{actor['name']} finishes binding the actual {state['item_name']} after ten uninterrupted minutes.")
        return True
    if kind == 'iron_cloth_end':
        actor['travel_effects'].pop(SILKEN,None)
        actor['bundle'].pop('iron_cloth_setup',None)
        _travel_seal(actor,session)
        session.emit('TRAVEL_EFFECT_ENDED',aid,source=SILKEN,text='Silken Whip infusion ends.')
        return True
    item = next(i for i in actor['bundle']['carrying']['items'] if i['key']==payload['item_key'])
    from ..fact_consent_admission import declare, read
    now = session.clock()
    scope=aid+'|'+item['key']
    declare(session,aid,{'source':SILKEN,'subject':aid,'kind':'iron_cloth_fabric','scope':scope,
        'value':{'fabric_kind':'flexible_fabric'},'expires_at':int(now)+3600,'readers':[]})
    record=read(session,SILKEN,aid,'iron_cloth_fabric',scope,aid)
    actor['resources'][QI] -= 1
    state = {'fabric_record':record,'fabric_receipt':record['receipt_id'],'item_key':item['key'],'item_name':item['name'],'fabric_kind':'flexible_fabric',
        'item_owner':aid,'item_object':aid+'|'+item['key'],
        'declaration_actor':aid,'declaration_authority':'item_owner','declaration_source':SILKEN,
        'expires_num':(now+3600).numerator,'expires_den':(now+3600).denominator}
    actor['travel_effects'][SILKEN]=state
    actor['bundle']['iron_cloth_setup']={**state,'remaining_rounds':600}
    _travel_seal(actor,session)
    session.emit('TRAVEL_ACTION',aid,source=SILKEN,economy='BONUS_ACTION',qi_cost=1,
        text=f"{actor['name']} infuses {item['name']} as its one Silken Whip for one hour.")
    return True


@hook('journey_elapsed')
def cloth_elapsed(session, aid, before, seconds, moving):
    from fractions import Fraction
    actor = session.state['actors'][aid]
    continuation=actor.get('source_states',{}).get(CONTINUATION,{})
    admissions=[]
    for entry in continuation.get('admissions',[]):
        remaining=Fraction(entry['remaining_num'],entry['remaining_den'])-seconds
        if remaining>0:
            admissions.append({**entry,'remaining_num':remaining.numerator,'remaining_den':remaining.denominator})
    if 'admissions' in continuation:
        continuation['admissions']=admissions
        actor['bundle']['iron_cloth_admissions']=admissions
    state = actor['travel_effects'].get(SILKEN)
    if not state or not _travel_owned(session,aid):
        _travel_seal(actor,session)
        return
    remaining = Fraction(state['expires_num'],state['expires_den'])-session.clock()
    if remaining<=0:
        actor['travel_effects'].pop(SILKEN,None)
        actor['bundle'].pop('iron_cloth_setup',None)
        session.emit('TRAVEL_EFFECT_ENDED',aid,source=SILKEN,text='Silken Whip: its one-hour infusion expires.')
    else:
        rounds = remaining/6
        actor['bundle']['iron_cloth_setup']={**state,'remaining_rounds':(rounds.numerator+rounds.denominator-1)//rounds.denominator}
    _travel_seal(actor,session)


@hook('journey_state_changed')
def cloth_enter_combat(session, aid):
    if session.state['phase'] != 'combat':
        return
    actor = session.state['actors'][aid]
    if SILKEN in actor['travel_effects']:
        # CombatService copied the sealed infusion into genesis before this
        # transition. It now lives on that fight's source clock, never twice.
        actor['travel_effects'].pop(SILKEN,None)
        actor['bundle'].pop('iron_cloth_setup',None)
        _travel_seal(actor,session)


@hook('journey_scene_end')
def cloth_scene_end(session, previous, current):
    for aid in session.state['actors']:
        import json
        actor=session.state['actors'][aid]
        snapshot=actor.get('encounter_snapshot') or {}
        conditions=snapshot.get('conditions') or {}
        retired=[iid for iid,value in conditions.items() if json.loads(value).get('condition_id')=='condition:typed.iron_cloth_scene']
        for iid in retired:
            del conditions[iid]
        restored=[]
        # The compiled once-per-scene cost is a real ledger, distinct from the
        # family condition. Reset only this acquired source's counter, on the
        # committed table-owner scene boundary; never recover Qi or other uses.
        capacities={r['resource_id']:r.get('maximum',r['initial']) for r in actor['bundle']['actor_template']['resources']}
        for action in actor['bundle'].get('action_catalog',[]):
            if action.get('parameters',{}).get('typed',{}).get('source')!=THOUSAND:
                continue
            for rid,amount in action.get('costs',[]):
                if rid.startswith('resource:uses.') and rid in capacities and actor['resources'].get(rid,0)<capacities[rid]:
                    actor['resources'][rid]=capacities[rid]
                    restored.append(rid)
        if retired or restored:
            session.emit('SCENE_ALLOWANCE_RESTORED',aid,source=THOUSAND,
                text='The declared journey scene ends; Thousand Ribbons is available in the next scene.')


@hook('match_initialize')
def cloth_genesis(engine):
    from .effect_durations import round_token
    for bundle in engine.typed_bundle_documents:
        owner=engine.state.actors.get(bundle['actor_id'])
        if owner and _rows(engine,owner):
            import json
            from ..gate2_runtime_models import RuntimeObjectState
            from ..fact_consent_admission import restore_combat_record
            for document in bundle.get('iron_cloth_objects',[]):
                obj=RuntimeObjectState.model_validate_json(document)
                identity=obj.component.get('inventory_identity')
                original=obj.component.get('inventory_owner')
                key=obj.component.get('physical_cloth_key')
                inventory=next((b.get('carrying',{}).get('items',[]) for b in engine.typed_bundle_documents if b['actor_id']==original),[])
                if (obj.owner_id!=owner.entity_id or not key or identity!=str(original)+'|'+key
                        or not any(i['key']==key and i.get('quantity',1)>0 for i in inventory)):
                    raise ValueError('The continued cloth object does not match its original physical inventory identity.')
                engine._update_object(obj,SILKEN,owner.entity_id)
            for entry in bundle.get('iron_cloth_admissions',[]):
                record=json.loads(entry['record'])
                if record.get('source') not in (SILKEN,PRISON):
                    raise ValueError('The continued cloth declaration belongs to another source.')
                from fractions import Fraction
                remaining=Fraction(entry['remaining_num'],entry['remaining_den'])
                if not 0<remaining<=3600:
                    raise ValueError('The continued cloth declaration has an invalid remaining clock.')
                restore_combat_record(engine,owner,record['source'],record,
                    expires_on=round_token(engine,(remaining.numerator+6*remaining.denominator-1)//(6*remaining.denominator)))
        bond=bundle.get('iron_cloth_bond')
        if bond and owner and _owned(engine,owner,SILKEN):
            engine._apply_condition(owner,'condition:typed.iron_cloth_bond',SILKEN,owner.entity_id,
                expires_on='UNTIL_REMOVED',data={**bond,'label':f"Physical cloth Domain Armament bond: {bond['item_name']}"})
        state = bundle.get('iron_cloth_setup')
        owner = engine.state.actors.get(bundle['actor_id'])
        if not state or owner is None or not _owned(engine,owner,SILKEN):
            continue
        # This payload was collected through the actual player's journey
        # command; restore the fact before asking an AI's possession query.
        from ..fact_consent_admission import restore_combat_record
        from ..fact_consent_admission import combat_records
        if not any(r['receipt_id']==state['fabric_record']['receipt_id'] for r in combat_records(engine,owner)):
            restore_combat_record(engine,owner,SILKEN,state['fabric_record'],
                expires_on=round_token(engine,int(state['remaining_rounds'])))
        identity=state.get('item_object') or owner.entity_id+'|'+state['item_key']
        item=next((i for i in cloth_items(engine,owner) if i['object']==identity),None)
        if item is None:
            raise ValueError('The carried cloth no longer matches its Silken Whip declaration.')
        engine._apply_condition(owner,WHIP,SILKEN,owner.entity_id,
            expires_on=round_token(engine,int(state['remaining_rounds'])),
            data={**{k:v for k,v in state.items() if k not in ('expires_num','expires_den','remaining_rounds','fabric_record')},
                'source_cl':int(_numbers(engine,owner)['cl']),'item_owner':item['item_owner'],
                'native_remaining_num':state.get('remaining_num',int(state['remaining_rounds'])*6),
                'native_remaining_den':state.get('remaining_den',1),
                'native_start_round':engine.state.round_number,'native_start_slot':engine.state.current_slot_index,
                'item_object':item['object'],
                'object_id':_cloth_object(engine,owner,item,SILKEN,_numbers(engine,owner)),
                'label':f"Silken Whip: {state['item_name']} — remaining infusion from the journey."})


def _cloth_object(engine,owner,item,source,numbers):
    from ..gate2_runtime_models import RuntimeObjectState
    oid = f"object:iron_cloth:{item['object']}"
    if oid not in engine.state.objects:
        cl = int(numbers['cl'])
        engine._update_object(RuntimeObjectState(object_id=oid,object_kind='cultivated_cloth',position=owner.position,
            owner_id=owner.entity_id,unattended=False,flammable=True,ac=12+int(numbers['pb']),
            current_hp=4*cl,maximum_hp=4*cl,damage_immunities=('POISON','PSYCHIC'),
            component={'name':item['name'],'physical_cloth_key':item['key'],'inventory_identity':item['object'],'inventory_owner':item['item_owner'],'created_by':source,'source_cl':cl,
                'blocks':False,'repair':'real_item','material':'cloth'}),source,owner.entity_id)
    else:
        obj=engine.state.objects[oid]
        maximum=4*int(numbers['cl'])
        engine._update_object(obj.model_copy(update={'owner_id':owner.entity_id,'position':owner.position,
            'ac':12+int(numbers['pb']),'maximum_hp':maximum,'current_hp':min(obj.current_hp,maximum),
            'component':{**obj.component,'created_by':source,'source_cl':int(numbers['cl'])}}),source,owner.entity_id)
    return oid


@hook('condition_applied')
def disarmed_cloth_identity(ctx,name,target):
    if name != 'disarmed' or not whip(target):
        return
    w = whip(target)
    for c in list(target.conditions.values()):
        action = ctx.engine.action_catalog.get(c.data.get('disables_action'))
        if c.condition_id == 'condition:typed.disarmed' and action and _typed(action).get('source') == ATTACK:
            ctx.engine._update_condition_data(target,c,{**c.data,'item_key':w.data.get('item_key'),'item_name':w.data.get('item_name')},ctx.source)


@hook('attack_allowed')
def physical_whip_ready(ctx,target,row):
    if ctx.typed.get('source') != ATTACK:
        return None
    w = whip(ctx.actor)
    if w is None:
        return False
    if not w.data.get('item_key'):
        return True
    return any(i['object']==w.data.get('item_object') for i in cloth_items(ctx.engine,ctx.actor))


@hook('state_event')
def flowing_packet_settled(engine,event):
    if event.event_type != 'DAMAGE_COMMITTED':
        return
    hit = engine.damage_context()
    if hit is None or hit.source_id != event.source_definition_id:
        return
    for owner in engine.state.actors.values():
        for c in list(owner.conditions.values()):
            if c.condition_id=='condition:typed.iron_cloth_flowing_pending' and c.data['roll_id']==hit.roll_id and c.data['protected'] in event.target_ids:
                engine._update_condition_data(owner,c,{**c.data,
                    'remaining_damage':c.data['remaining_damage']+int(event.payload['reduced_to'])},FLOWING)


@hook('before_target_reactions')
def bound_armament_moves(ctx):
    if ctx.action.parameters.get('iron_cloth') != 'bound_attack':
        return
    from ..action_geometry import record_for
    from ..gate2_runtime_models import Position
    from .qi_path import move_armament
    origin = record_for(ctx.engine,ctx.actor,ctx.source)
    if origin and origin['id'].startswith('iron_cloth:bound_move:'):
        destination=Position(**origin['position'])
        if destination != whip_point(ctx.engine,ctx.actor) and not move_armament(ctx.engine,ctx.actor,
                destination,ctx.source,max_distance_ft=int(ctx.action.parameters.get('iron_cloth_armament_move_ft',20)),require_clear_route=True):
            raise ValueError('The physical Silken Whip cannot move to that Domain Armament origin.')


@hook('carried_item_remaining')
def broken_real_cloth(engine,actor,item):
    if any(c.condition_id=='condition:typed.iron_cloth_broken' and c.data.get('item_key')==item['key'] for c in actor.conditions.values()):
        return 0
    if any(o.owner_id==actor.entity_id and o.component.get('physical_cloth_key')==item['key']
           and o.destroyed for o in engine.state.objects.values()):
        return 0
    return None


@hook('object_targets')
def whip_object_targets(engine,actor,action):
    if not action.parameters.get('iron_cloth_object'):
        return None
    return [o.object_id for o in engine.state.objects.values()
            if not o.destroyed and o.current_hp is not None and o.ac is not None]


@hook('object_action')
def whip_object_attack(engine,actor,action,obj,candidate,intent):
    if not action.parameters.get('iron_cloth_object'):
        return None
    from copy import deepcopy
    from .objects import object_action
    from ..object_rules import label
    typed=deepcopy(_typed(action))
    kinds=['BLUDGEONING','SLASHING','FORCE']
    selected=_ask(engine,actor,intent,'object_damage_type',kinds,
        labels={k:k.title()+' damage' for k in kinds},
        prompt=f'Silken Whip: choose the damage type for your attack on {label(obj)}.')
    weapon={**typed['weapon'],'damage_type':selected[0],'damage_types':[selected[0]]}
    typed.update(object_weapon=weapon,object_weapon_group='weapon',object_melee=True,
        effects=[{'type':'object_attack','count':max([1,*[int(r['attacks']) for r in engine.typed_passive_rows.get(actor.entity_id,[]) if r.get('block')=='extra_attack']])}])
    # Use the existing public native object dispatcher with an action-local
    # copy. No catalog edit, duplicate attack roller, or registration is made.
    delegated=action.model_copy(update={'parameters':{**action.parameters,'typed':typed,'object_attack':True}})
    return object_action(engine,actor,delegated,obj,candidate,intent)



def encounter_seconds(engine, condition):
    """Remaining native slot clock, in rational seconds; unsupported clocks reject."""
    from fractions import Fraction
    from .effect_durations import parse_round
    deadline=parse_round(condition.expires_on)
    if deadline is None:
        raise ValueError('The cloth continuation requires its native slot deadline.')
    slots=max(1,len(engine.state.initiative_order))
    remaining=Fraction(((deadline[0]-engine.state.round_number)*slots+
        deadline[1]-engine.state.current_slot_index)*6,slots)
    data=condition.data
    if 'native_remaining_num' in data:
        elapsed=Fraction(((engine.state.round_number-data['native_start_round'])*slots+
            engine.state.current_slot_index-data['native_start_slot'])*6,slots)
        remaining=min(remaining,Fraction(data['native_remaining_num'],data['native_remaining_den'])-elapsed)
    return max(Fraction(0),remaining)


def encounter_cloth_records(engine, actor):
    from ..fact_consent_admission import combat_records
    return [r for r in combat_records(engine,actor,kind='iron_cloth_fabric')
            if r['subject']==actor.entity_id and r['source'] in (SILKEN,PRISON)]


@hook('journey_snapshot_actor')
def cloth_snapshot(actor, session, aid, engine):
    """Pure copy excludes only this acquired source's exported state, never fight state."""
    if actor.entity_id!=aid or not _rows(engine,actor):
        return None
    from ..fact_consent_admission import CONDITION
    import json
    records={r['receipt_id'] for r in encounter_cloth_records(engine,actor)}
    exported={c.instance_id for c in actor.conditions.values() if
        (c is infusion(actor) or c.condition_id=='condition:typed.iron_cloth_bond') or
        (c.condition_id==CONDITION and json.loads(c.data['record'])['receipt_id'] in records)}
    if not exported:
        return None
    copy=actor.model_copy(deep=True)
    copy.conditions={k:c for k,c in copy.conditions.items() if k not in exported}
    return copy


@hook('journey_encounter_settled')
def cloth_encounter_settled(session, aid, engine, creature):
    """Export committed physical identity, damage, bond and exact remaining infusion."""
    if creature.entity_id!=aid or not _rows(engine,creature):
        return
    from copy import deepcopy
    from ..fact_consent_admission import CONDITION, canonical
    actor=session.state['actors'][aid]
    records=encounter_cloth_records(engine,creature)
    persistent={'objects':[o.model_dump_json() for o in engine.state.objects.values()
        if o.owner_id==aid and o.component.get('physical_cloth_key')],
        'admissions':[]}
    for record in records:
        c=next(c for c in creature.conditions.values() if c.condition_id==CONDITION
            and c.data['record']==canonical(record))
        remaining=encounter_seconds(engine,c)
        if remaining>0:
            persistent['admissions'].append({'record':canonical(record),
                'remaining_num':remaining.numerator,'remaining_den':remaining.denominator})
    actor['travel_effects'].pop(SILKEN,None)
    actor['bundle'].pop('iron_cloth_setup',None)
    actor['bundle'].pop('iron_cloth_bond',None)
    bond=next((c for c in creature.conditions.values() if c.condition_id=='condition:typed.iron_cloth_bond'),None)
    if bond:
        actor['bundle']['iron_cloth_bond']=deepcopy(bond.data)
    w=infusion(creature)
    if w:
        remaining=encounter_seconds(engine,w)
        record=next((r for r in records if r['receipt_id']==w.data.get('fabric_receipt')),None)
        if remaining>0 and record:
            deadline=session.clock()+remaining
            restored={**deepcopy(w.data),'fabric_record':record,'expires_num':deadline.numerator,'expires_den':deadline.denominator}
            actor['travel_effects'][SILKEN]=restored
            actor['bundle']['iron_cloth_setup']={**restored,'remaining_rounds':
                (remaining.numerator+6*remaining.denominator-1)//(6*remaining.denominator)}
    actor.setdefault('source_states',{})[CONTINUATION]=persistent
    actor['bundle']['iron_cloth_objects']=list(persistent['objects'])
    actor['bundle']['iron_cloth_admissions']=deepcopy(persistent['admissions'])
    _travel_seal(actor,session)



def journey_cloth_items(session, aid):
    """Pure possession view over acquired bundles and committed encounter transfers.

    Uses the inventory provider's public identity query. No new item, transfer or
    authority is created. Records remain filed on their original inventory owner.
    This small read adapter has no combat actions, RNG or mutable engine state.
    """
    import json
    from types import SimpleNamespace
    from ..gate2_runtime_models import ConditionInstance
    from .scoundrel_riders import possessions
    actors={}
    for who,entry in session.state['actors'].items():
        conditions={key:ConditionInstance.model_validate_json(value) for key,value in
            (entry.get('encounter_snapshot') or {}).get('conditions',{}).items()}
        actors[who]=SimpleNamespace(entity_id=who,conditions=conditions)
    view=SimpleNamespace(state=SimpleNamespace(actors=actors),
        typed_bundle_documents=[entry['bundle'] for entry in session.state['actors'].values()])
    items=possessions(view,actors[aid])
    return [i for i in items if i.get('quantity',1)>0 and not any(
        c.condition_id=='condition:typed.iron_cloth_broken' and c.data.get('item_key')==i['key']
        for c in actors[i['object'].split('|',1)[0]].conditions.values())]
