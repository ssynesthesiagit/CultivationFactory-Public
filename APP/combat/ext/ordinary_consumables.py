"""Source-backed ordinary item outcomes consumed by consumable_payloads.

Shared helper module: its compiled_specs/specification API is read by
consumable_payloads, trap and the ordinary delivery path, so one source defines
an item's typed nature instead of each caller inventing effects.

Acid, Alchemist's Fire, Ball Bearings and Caltrops use SRD 5.2.1 Equipment.
Ordinary burning uses the SRD hazard; Tianxia's separate PB-based Burn remains
untouched. Item stock is the public carried-item contract, never granted here.
"""
from copy import deepcopy
import json

from . import hook, effect, placed
from ..gate2_runtime_models import ActionDefinition, EconomyKind, Position
from ..typed_executor import Context, run_effects
from .effect_durations import token

P = 'tianxia.mortal.gear.'
BURN = 'condition:typed.ordinary_item_burning'


@hook('journey_persistent_fields')
def scatter_fields():
    return ('ordinary_scatter_areas',)


def map_scatter(session, aid):
    """Source-owned physical spills on the current map, with no invented expiry."""
    map_id = session.state['battlefield'].get('stable_id')
    return [r for r in session.state['actors'][aid].get('ordinary_scatter_areas', ())
            if r['map_id'] == map_id]


@hook('journey_view')
def scatter_view(state, viewer):
    if not any('ordinary_scatter_areas' in a for a in state['actors'].values()):
        return None
    out = deepcopy(state)
    out.pop('replay_base', None)
    out.pop('command_journal', None)
    for aid, actor in out['actors'].items():
        if aid != viewer:
            actor.pop('ordinary_scatter_areas', None)
        elif 'ordinary_scatter_areas' in actor:
            actor['ordinary_scatter_areas'] = [r for r in actor['ordinary_scatter_areas']
                if r['map_id'] == out['battlefield'].get('stable_id')]
    return out


@hook('journey_encounter_settled')
def remember_scatter(session, aid, engine, creature):
    actor = session.state['actors'][aid]
    map_id = session.state['battlefield'].get('stable_id')
    current = placed.of(engine, 'ordinary_scatter', owner_id=aid)
    if not current and not actor.get('ordinary_scatter_areas'):
        return
    # Replace this map's snapshot so removed areas cannot reappear. Preserve
    # other maps' actual spills when this creature travels elsewhere.
    actor['ordinary_scatter_areas'] = [r for r in actor.get('ordinary_scatter_areas', ())
        if r['map_id'] != map_id] + [
        {'map_id': map_id, 'zone': json.dumps(z.model_dump(mode='json'), sort_keys=True, separators=(',', ':'))}
        for z in current]


@hook('journey_combat_bundle')
def scatter_bundle(bundle, session, aid):
    records = map_scatter(session, aid)
    if not records:
        return None
    return {**deepcopy(bundle), 'ordinary_scatter_areas': deepcopy(records)}


@hook('match_initialize')
def restore_scatter(engine):
    from ..gate2_runtime_models import ZoneState
    from .. import zones
    for bundle in engine.typed_bundle_documents:
        for record in bundle.get('ordinary_scatter_areas', ()):
            raw = json.loads(record['zone'])
            if raw['zone_id'] in engine.state.zones or raw['owner_id'] != bundle['actor_id']:
                continue
            raw.update(created_round=engine.state.round_number, per_turn_triggered={})
            zone = ZoneState.model_validate(raw)
            engine.state.zones[zone.zone_id] = zone
            engine._append_event('ZONE_CREATED', zone.source_definition_id, actor_id=zone.owner_id,
                                 payload={'zone': zone.model_dump(mode='json')})
            zones.sync_inside(engine, zone.source_definition_id)


@hook('journey_step')
def scatter_contact(session, aid, old, nxt, regions):
    here = (nxt.x, nxt.y, nxt.z)
    for owner in session.state['actors']:
        for record in map_scatter(session, owner):
            zone = json.loads(record['zone'])
            if any(here == (c['x'], c['y'], c.get('z', 0)) for c in zone['affected_cells']):
                return {'native_scene_required': 'This route enters scattered Ball Bearings or Caltrops. '
                        'Open a table scene to resolve movement and its Dexterity save.'}
    return None


@hook('journey_options')
def scatter_scene(session, aid):
    if (session.state['phase'] != 'travel' or session.state['actors'][aid]['incapacitated'] or
            not any(map_scatter(session, owner) for owner in session.state['actors'])):
        return None
    return [{'id': 'resolve_scattered_items', 'kind': 'open_scene', 'payload': {
                'teams': {a: 'team:journey_party' for a in session.state['actors']}}, 'auto_select': 0,
             'label': 'Open a six-second table scene to move through scattered Ball Bearings or Caltrops '
                      'and resolve their Dexterity saves, then resume travel.'}]


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
