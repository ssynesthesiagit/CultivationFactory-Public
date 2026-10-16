"""Source-backed ordinary item outcomes consumed by consumable_payloads.

Acid, Alchemist's Fire, Ball Bearings and Caltrops use SRD 5.2.1 Equipment.
Ordinary burning uses the SRD hazard; Tianxia's separate PB-based Burn remains
untouched. Item stock is the public carried-item contract, never granted here.
"""
from . import hook, effect, placed
from ..gate2_runtime_models import ActionDefinition, EconomyKind, Position
from ..typed_executor import Context, run_effects
from .effect_durations import token

P = 'tianxia.mortal.gear.'
BURN = 'condition:typed.ordinary_item_burning'


def compiled_specs(bundle, info):
    """Public source recipes sealed from native acquired carrying records."""
    dc=8+int(info['mods'].get('DEX',0))+int(info['numbers']['pb'])
    specs={}
    for item in bundle.get('carrying',{}).get('items',()):
        key=item['item_id'].removeprefix(P)
        if key in ('ball_bearings','caltrops'):
            specs[item['item_id']]={'fragile':0,'name':'Ball Bearings' if key=='ball_bearings' else 'Caltrops',
                'area':{'shape':'cube','size_ft':10 if key=='ball_bearings' else 5},
                'effects':[{'type':'ordinary_scatter','kind':key}]}
        elif key=='alchemist_s_fire':
            specs[item['item_id']]={'name':'Alchemist’s Fire','fragile':1,'numbers':{'save_dc':dc},'effects':[
                {'type':'save','ability':'dex','on_fail':[
                    {'type':'damage','dice':{'count':1,'sides':4},'damage_types':['fire'],'applies_to':'target'},
                    {'type':'ordinary_item_burn'}]}]}
    return specs


@hook('ordinary_consumable_spec')
def specification(engine, owner, item):
    if item['item_id']==P+'acid':
        return None  # the Acid source provider already owns this definition
    bundle=next((b for b in engine.typed_bundle_documents if b['actor_id']==owner.entity_id),{})
    return (bundle.get('ordinary_item_specs') or {}).get(item['item_id'])


@effect('ordinary_scatter')
def scatter(ctx,row):
    origin=ctx.intent.destination
    kind=row['kind']
    cells=[Position(x=origin.x+dx,y=origin.y+dy,z=origin.z)
           for dx in range(2 if kind=='ball_bearings' else 1)
           for dy in range(2 if kind=='ball_bearings' else 1)]
    cells=[p for p in cells if ctx.engine.grid.volume_legal(p)]
    if not cells:
        return
    fail=([{'type':'condition','condition':'prone','applies_to':'target'}] if kind=='ball_bearings' else
          [{'type':'damage','flat':1,'damage_types':['piercing'],'applies_to':'target'}, {'type':'ordinary_caltrop_stop'}])
    placed.place(ctx.engine,ctx.actor,source=ctx.action.source_definition_id,tag='ordinary_scatter',cells=cells,
        name='Scattered Ball Bearings' if kind=='ball_bearings' else 'Scattered Caltrops',
        numbers={**ctx.numbers,'save_dc':10 if kind=='ball_bearings' else 15},
        triggers=[{'id':'ordinary:'+kind,'on':['enter'],'who':'any','effects':[
            {'type':'save','ability':'dex','on_fail':fail}]}],placed={'item':kind})


@effect('ordinary_caltrop_stop')
def stop(ctx,row):
    if ctx.target:
        ctx.engine._apply_condition(ctx.target,'condition:typed.held_fast',ctx.source,ctx.actor.entity_id,
            expires_on=token('start',ctx.target.entity_id,ctx.target.turns_started+1))


@effect('ordinary_item_burn')
def burn(ctx,row):
    if ctx.target and not any(c.condition_id==BURN for c in ctx.target.conditions.values()):
        ctx.engine._apply_condition(ctx.target,BURN,ctx.source,ctx.actor.entity_id,expires_on='UNTIL_REMOVED',
            data={'label':'Burning: 1d4 Fire damage at the start of your turn; use an Action to fall Prone and roll to extinguish it'})


@hook('turn_start')
def burn_damage(engine, actor):
    condition=next((c for c in actor.conditions.values() if c.condition_id==BURN),None)
    if condition is None:
        return
    owner=engine.state.actors.get(condition.source_actor_id)
    if owner is None:
        return
    action=next((a for a in engine.action_catalog.values() if a.owner_id==owner.entity_id),None)
    if action:
        ctx=Context(engine,owner,action,None,{'source':condition.source_definition_id,'numbers':{}},[actor],actor,{})
        run_effects(ctx,[{'type':'damage','dice':{'count':1,'sides':4},'damage_types':['fire'],'applies_to':'target'}])


@hook('compile_actions')
def extinguish(info):
    # Everyone may respond to a real ordinary item fire; hidden when absent.
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.ordinary_item_extinguish",
        display_name='Roll on the ground to extinguish ordinary fire',owner_id=info['actor_id'],
        economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='SELF',parameters={
            'requires_condition':BURN,'ordinary_item_extinguish':1,
            'typed':{'effects':[{'type':'ordinary_extinguish'}],'numbers':info['numbers'],'duration':{'kind':'instant'},'riders':[]},
            'description':'Action: give yourself the Prone condition and roll on the ground to extinguish ordinary item fire.'})]


@effect('ordinary_extinguish')
def extinguish_effect(ctx,row):
    if not any(c.condition_id==BURN for c in ctx.actor.conditions.values()):
        return
    run_effects(ctx,[{'type':'condition','condition':'prone','applies_to':'self'}])
    ctx.engine._remove_condition(ctx.actor,BURN,ctx.source)
