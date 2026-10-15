"""Hearthfire consumers for native map objects and real empowered-item custody.

Map object presets and objects.seed are the existing physical-object producer.
Object interaction and hand_occupancy own pickup economy and free hands. This
module supplies only the family's empowerment, custody and fuel operations.
"""
from copy import deepcopy
from . import hook, run_strict
from .qi_hearthfire import HEARTH, BLOCK
from ..gate2_runtime_models import ActionDefinition
from ..object_interaction import used,claim
from .hand_occupancy import free_hands
from .needle import ask,CHOICE,checkpoint_id

# These native scenery presets explicitly contain a burning candle/coals/firebox
# in objects.json. A name, Fire damage or flammability alone never qualifies.
CONTAINED_PRESETS={'stone_lantern','war_brazier','alchemy_furnace'}
HOLD='condition:typed.hearth_item_custody'


def empowerable(obj):
    return not obj.destroyed and (obj.component or {}).get('kind') in CONTAINED_PRESETS


def held_item(engine,obj,actor):
    return any(c.condition_id==HOLD and c.data.get('object_id')==obj.object_id for c in actor.conditions.values())


@hook('compile_actions')
def empower_existing(info):
    result=[]
    for a in info['actions']:
        typed=a.parameters.get('typed') or {}
        if typed.get('source')!=HEARTH:
            continue
        params=deepcopy(a.parameters)
        params['typed']['effects']=[{'type':'qi_hearth_asset','applies_to':'self','existing':1}]
        params['hearth_empower_existing']=1
        result.append(a.model_copy(update={'source_definition_id':a.source_definition_id+'.empower_existing',
            'display_name':'Kindled Hearth: empower an existing contained flame','target_kind':'OBJECT','range_ft':30,
            'parameters':params}))
    return result or None


@hook('object_targets')
def hearth_item_targets(engine,actor,action):
    params=action.parameters or {}
    if params.get('hearth_empower_existing'):
        return [o.object_id for o in engine.state.objects.values() if empowerable(o)]
    if params.get('hearth_item_operation'):
        take=params['hearth_item_operation']=='take'
        if used(actor)!=(params['hearth_item_payment']=='utilize'):
            return []
        return [o.object_id for o in engine.state.objects.values() if not o.destroyed and ((take and (o.component or {}).get('hearth_original') and o.unattended and free_hands(engine,actor))
            or (not take and held_item(engine,o,actor)))]
    return []


@hook('match_start')
def item_operations(engine):
    # Only a genuinely acquired Kindled Hearth introduces this family menu.
    if not any(r.get('block')==BLOCK and r.get('feature_id')==HEARTH
               for rows in getattr(engine,'typed_passive_rows',{}).values() for r in rows):
        return
    for operation in ('take','put_down'):
        for payment in ('free','utilize'):
            sid='system:hearth.item.'+operation+'.'+payment
            engine.action_catalog[sid]=ActionDefinition(source_definition_id=sid,owner_id='*',
                display_name=('Pick up' if operation=='take' else 'Put down')+' the real empowered Hearth item ('+
                    ('free interaction' if payment=='free' else 'Utilize action')+')',economy='NONE' if payment=='free' else 'ACTION',
                resolution_kind='TYPED',target_kind='OBJECT',range_ft=5,
                parameters={'hearth_item_operation':operation,'hearth_item_payment':payment,'player_only':True})


@hook('additional_actions')
def offer_item_operations(engine,actor):
    return [sid for sid,a in engine.action_catalog.items() if a.parameters.get('hearth_item_operation')
            and hearth_item_targets(engine,actor,a)]


@hook('object_action')
def operate_item(engine,actor,action,obj,candidate,intent):
    params=action.parameters or {}
    if params.get('hearth_empower_existing'):
        from .placed import context
        from .qi_hearthfire import create_hearth
        ctx=context(engine,actor,action.source_definition_id,params['typed']['numbers'],action=action)
        ctx.intent=intent
        create_hearth(ctx,{'existing':1})
        return True
    if not params.get('hearth_item_operation'):
        return
    if obj.object_id not in hearth_item_targets(engine,actor,action):
        raise ValueError('The empowered item is no longer available for that interaction.')
    if False in run_strict('object_operation_gate',engine,actor,obj,'move',action.source_definition_id,intent):
        raise ValueError('This object cannot be moved by that interaction.')
    if params['hearth_item_payment']=='free':
        claim(engine,actor,action.source_definition_id)
    if params['hearth_item_operation']=='take':
        hand=free_hands(engine,actor)[0]
        engine._apply_condition(actor,HOLD,HEARTH,actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'object_id':obj.object_id,'hand':hand,'label':'Carrying the real empowered Hearth item'})
        engine._update_object(obj.model_copy(update={'unattended':False,'position':actor.position}),HEARTH,actor.entity_id)
    else:
        from .condition_ownership import remove_instance
        for c in list(actor.conditions.values()):
            if c.condition_id==HOLD and c.data.get('object_id')==obj.object_id:
                remove_instance(engine,actor,c.instance_id,HEARTH)
        engine._update_object(obj.model_copy(update={'unattended':True,'position':actor.position}),HEARTH,actor.entity_id)
    return True


@hook('hand_occupants')
def item_hand(engine,actor):
    return {c.data['hand']:c.data['object_id'] for c in actor.conditions.values() if c.condition_id==HOLD
            and (obj:=engine.state.objects.get(c.data['object_id'])) is not None and not obj.destroyed}


@hook('movement_landed')
def real_item_step(engine,actor,previous,nxt,intent,forced):
    for c in actor.conditions.values():
        if c.condition_id==HOLD:
            obj=engine.state.objects.get(c.data['object_id'])
            if obj is not None and not obj.destroyed and obj.position!=nxt:
                engine._update_object(obj.model_copy(update={'position':nxt}),HEARTH,actor.entity_id)


@hook('match_start')
def fuel_operation(engine):
    if not any(r.get('block')==BLOCK and r.get('feature_id')==HEARTH
               for rows in getattr(engine,'typed_passive_rows',{}).values() for r in rows):
        return
    sid='system:hearth.ignite_fuel'
    engine.action_catalog[sid]=ActionDefinition(source_definition_id=sid,display_name='Kindled Hearth: ignite ordinary fuel',
        owner_id='*',economy='NONE',resolution_kind='TYPED',target_kind='OBJECT',
        parameters={'hearth_ignite_fuel':1,'player_only':True,
            'description':'Permit your active Kindled Hearth to ignite one ordinary flammable object touching its flame, at no action or Qi cost. It does not spread fire to other objects.'})


@hook('object_targets')
def fuel_targets(engine,actor,action):
    if not action.parameters.get('hearth_ignite_fuel'):
        return []
    from .qi_hearthfire import hearths
    return [o.object_id for o in engine.state.objects.values() if o.flammable and o.unattended and not o.destroyed and not o.ignited
            and not (o.component or {}).get('artifact') and any(engine.grid.distance_ft(z.center,o.position)<=5 for z in hearths(engine,actor))]


@hook('additional_actions')
def offer_fuel(engine,actor):
    sid='system:hearth.ignite_fuel'
    action=engine.action_catalog.get(sid)
    return [sid] if action and fuel_targets(engine,actor,action) else []


@hook('object_action')
def kindle_fuel(engine,actor,action,obj,candidate,intent):
    if not action.parameters.get('hearth_ignite_fuel'):
        return
    if obj.object_id not in fuel_targets(engine,actor,action):
        raise ValueError('Choose ordinary unattended fuel touching your active Hearth.')
    from .objects import ignite
    ignite(engine,obj.object_id,HEARTH,actor.entity_id)
    return True
