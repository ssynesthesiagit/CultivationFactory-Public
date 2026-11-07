"""Emergency Repairs: native object commits and explicit Construct healing.

Only sealed emergency_repair actions opt in. Reinforcement is a source-clock
condition plus an object component receipt. Removing/expiring that condition
restores only the bonuses this receipt added, preserving unrelated changes.
Adjacent friendly creatures query the live receipt at their save's location.
"""
from typing import Any
from . import hook, effect

REPAIRS = 'tianxia.subpath.qi.mason_cultivator.feature.emergency_repairs'
REINFORCED = 'condition:typed.mason_reinforcement'
MARKER = 'mason_reinforcement'


def repairable(obj: Any) -> bool:
    return not obj.destroyed and obj.current_hp is not None and obj.maximum_hp is not None


def reinforceable(obj: Any) -> bool:
    return repairable(obj) and bool((obj.component or {}).get('structure') or obj.object_kind in
        ('barrier','formation_anchor','vehicle','cart','rowboat','ballista'))


@hook('compile_actions')
def repair_variants(info: dict[str, Any]) -> list[Any] | None:
    if REPAIRS not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    typed={'source':REPAIRS,'numbers':info['numbers'],'duration':{'kind':'instant'},'effects':[{'type':'mason_repair_declaration'}], 'riders':[]}
    def action(key,label,target,economy,range_ft,cost,mode):
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mason.{key}",
            display_name='Emergency Repairs: '+label,owner_id=info['actor_id'],economy=economy,
            resolution_kind='TYPED',target_kind=target,range_ft=range_ft,costs=(('resource:core.qi',cost),),
            parameters={'typed':typed,'emergency_repair':mode,'expected_damage':0, **({'player_only':True} if mode=='construct_hostile' else {}),
                'description': ('Action, 2 Qi: restore 3d8 plus your Qi key ability modifier Hit Points to the selected damaged object or Construct within 5 feet. Cannot exceed its maximum.' if mode!='reinforce' else 'Bonus Action, 1 Qi: one structure within 30 feet gains +2 AC and increases its Damage Threshold by your Proficiency Bonus until your next turn starts. Adjacent allies gain Advantage against Prone and forced movement. Repeated reinforcement does not stack.')})
    return [action('repair','Repair Structure','OBJECT','ACTION',5,2,'repair'),
            action('reinforce','Reinforce Position','OBJECT','BONUS_ACTION',30,1,'reinforce'),
            # Enumerate the printed creature domain so the sealed candidate
            # check can retain Neutral Constructs as valid manual recipients.
            action('construct','Repair Construct','ANY_CREATURE','ACTION',5,2,'construct'),
            action('construct_hostile','Repair Construct (other side)','HOSTILE_ENTITY','ACTION',5,2,'construct_hostile')]


@hook('object_targets')
def repair_targets(engine: Any, actor: Any, action: Any) -> list[str]:
    mode=action.parameters.get('emergency_repair')
    if mode not in ('repair','reinforce'):
        return []
    return [o.object_id for o in engine.state.objects.values() if
            (reinforceable(o) if mode=='reinforce' else repairable(o)) and
            (mode!='repair' or o.current_hp<o.maximum_hp)]


@hook('candidate_allowed')
def repair_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    mode=(action.parameters if action is not None else {}).get('emergency_repair')
    if not mode:
        return None
    target_id=next(iter(candidate.target_ids),None)
    if mode in ('construct','construct_hostile'):
        from .creature_kinds import matches
        from ..relations import relation, ALLY, ENEMY
        target=engine.state.actors.get(target_id)
        expected = ENEMY if mode=='construct_hostile' else ALLY
        return target is not None and (relation(engine,actor,target)==expected if mode=='construct_hostile' else relation(engine,actor,target)!=ENEMY) and matches(target,['construct']) and target.current_hp<target.maximum_hp
    obj=engine.state.objects.get(target_id)
    return obj is not None and (reinforceable(obj) if mode=='reinforce' else repairable(obj))


@hook('object_action')
def repair_object(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    mode=action.parameters.get('emergency_repair')
    if mode not in ('repair','reinforce'):
        return None
    from .. import typed_executor as te
    from ..gate2_runtime_models import DiceSpec
    typed=action.parameters['typed'];source=action.source_definition_id
    ctx=te.Context(engine,actor,action,intent,typed,[],None,{})
    if mode=='repair':
        amount=te._roll(ctx,DiceSpec(count=3,sides=8,modifier=int(ctx.numbers.get('key_mod') or 0)),'REPAIR')
        after=obj.model_copy(update={'current_hp':min(obj.maximum_hp,obj.current_hp+max(0,amount))})
        engine._update_object(after,source,actor.entity_id)
        return True
    if not reinforceable(obj):
        return True
    old=(obj.component or {}).get(MARKER)
    if old:
        owner=engine.state.actors.get(old['owner'])
        if owner is not None and old['instance'] in owner.conditions:
            condition=owner.conditions.pop(old['instance'])
            engine._append_event('CONDITION_REMOVED',source,actor_id=owner.entity_id,target_ids=(owner.entity_id,),
                payload={'condition_id':condition.condition_id,'instance_id':condition.instance_id})
        obj=engine.state.objects[obj.object_id]
    pb=int(ctx.numbers.get('pb') or 0)
    object_name=str((obj.component or {}).get('display_name') or (obj.component or {}).get('name') or
                    obj.object_kind.replace('_',' '))
    engine._apply_condition(actor,REINFORCED,source,actor.entity_id,expires_on='START_OF_SOURCE_NEXT_TURN',
        data={'object_id':obj.object_id,'label':f"{object_name} — +2 AC, Damage Threshold +{pb} (ignores hits below its threshold); adjacent allies have Advantage against Prone and forced movement. Ends at {actor.display_name}'s next turn start."})
    instance=next(c.instance_id for c in reversed(list(actor.conditions.values())) if c.condition_id==REINFORCED and c.data.get('object_id')==obj.object_id)
    marker={'owner':actor.entity_id,'instance':instance,'ac':2,'threshold':pb}
    engine._update_object(obj.model_copy(update={'ac':int(obj.ac or 0)+2,'damage_threshold':int(obj.damage_threshold or 0)+pb,
        'component':{**(obj.component or {}),MARKER:marker}}),source,actor.entity_id)
    return True


@effect('mason_repair_declaration', harmful=False)
def repair_construct(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.action.parameters.get('emergency_repair') not in ('construct','construct_hostile') or ctx.target is None:
        return
    from .. import typed_executor as te
    te.run_effects(ctx,[{'type':'healing','applies_to':'target','dice':{'count':3,'sides':8,'bonus_formula':'key_ability_modifier'}}])


@hook('event')
def reinforcement_expired(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type!='CONDITION_REMOVED' or (kwargs.get('payload') or {}).get('condition_id')!=REINFORCED:
        return
    instance=(kwargs.get('payload') or {}).get('instance_id')
    for obj in list(engine.state.objects.values()):
        marker=(obj.component or {}).get(MARKER)
        if marker and marker['instance']==instance:
            component=dict(obj.component);component.pop(MARKER)
            engine._update_object(obj.model_copy(update={'ac':max(0,int(obj.ac or 0)-marker['ac']),
                'damage_threshold':max(0,int(obj.damage_threshold or 0)-marker['threshold']),
                'component':component}),REPAIRS,marker['owner'])


@hook('save')
def reinforced_save(ctx: Any, target: Any, ability: str, named: Any) -> dict | None:
    if not {'prone','forced_movement'} & set(named or ()):
        return None
    from ..object_geometry import target_cells
    from ..relations import relation, ALLY
    for obj in ctx.engine.state.objects.values():
        marker=(obj.component or {}).get(MARKER)
        if not marker or obj.destroyed:
            continue
        owner=ctx.engine.state.actors.get(marker['owner'])
        if owner is not None and relation(ctx.engine, target, owner)==ALLY and marker['instance'] in owner.conditions and any(
                ctx.engine.grid.distance_ft(target.position,cell)<=5 for cell in target_cells(ctx.engine,obj)):
            return {'modes':['ADVANTAGE']}
    return None
