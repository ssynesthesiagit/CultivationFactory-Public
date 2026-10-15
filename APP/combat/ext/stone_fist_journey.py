"""Stone Fist's consumers of the native Journey source-state/clock contracts.

Only actual committed Stone Fist conditions, modifiers and physical terrain are
exported. Acquisition never fabricates a hit, an object or a creature category.
Scene uses follow explicit scene boundaries; rests and combat entry do not reset
Heaven-Cracking Blow. Failed-save guard clocks retain their remaining seconds.
"""
from copy import deepcopy
from fractions import Fraction
import json
from . import hook
from .stone_fist import PREFIX, PALM, GUARD_FLAG, body_level

KEY = PREFIX+'continuation'
HEAVEN = PREFIX+'heaven_cracking_blow'
LIMIT = 'condition:typed.path_hit_limit.'


def owned(actor):
    return any(row.get('block')=='stone_fist_profile' for row in actor['bundle'].get('typed_passives',()))


def seal(actor):
    rows=actor['bundle'].setdefault('typed_passives',[])
    rows[:]=[r for r in rows if r.get('block') not in {'stone_fist_continuation','stone_fist_terrain'}]
    state=actor.get('source_states',{}).get(KEY)
    if state:
        rows.append({'block':'stone_fist_continuation','state':deepcopy(state)})
    terrain=actor.get('source_states',{}).get(KEY+'.terrain')
    if terrain:rows.append({'block':'stone_fist_terrain','zones':list(terrain)})


@hook('journey_initialized')
def initialize(session):
    for actor in session.state['actors'].values():
        if owned(actor):
            actor.setdefault('source_states',{}).setdefault(KEY,{'scene_used':0,'guards':[],'conditions':[]})
        seal(actor)


@hook('journey_acquired')
def acquired(session,actor_id,source,acquisition_id):
    if source==PREFIX.removesuffix('.feature.'):
        initialize(session)


@hook('journey_snapshot_actor')
def snapshot(creature,session,aid,engine):
    source_conditions={key for key,c in creature.conditions.items() if c.source_definition_id.startswith(PREFIX) and (c.condition_id.startswith(LIMIT) or c.condition_id.endswith('reaction_denied'))}
    source_modifiers={key for key,m in creature.modifiers.items() if m.source_definition_id==PALM}
    if not source_conditions and not source_modifiers:
        return None
    result=creature.model_copy(deep=True)
    result.conditions={key:c for key,c in result.conditions.items() if key not in source_conditions}
    result.modifiers={key:m for key,m in result.modifiers.items() if key not in source_modifiers}
    return result


@hook('journey_encounter_settled')
def settled(session,aid,engine,creature):
    from .effect_durations import parse_round
    actor=session.state['actors'][aid]
    guards=[]
    # A dormant guard is retained by its existing source ledger while the
    # caster's effective Body level is too low. Combat time still expires it.
    prior=actor.get('source_states',{}).get(KEY,{})
    for row in prior.get('guards',()):
        owner=engine.state.actors.get(row.get('repeat',{}).get('owner'))
        remaining=max(0,row['remaining']-max(0,engine.state.round_number-1)*6)
        if owner is not None and body_level(engine,owner)<10 and remaining:
            guards.append({**deepcopy(row),'remaining':remaining})
    for modifier in creature.modifiers.values():
        if modifier.source_definition_id!=PALM:
            continue
        end=parse_round(modifier.expires_on)
        # Round/slot identity preserves the fraction of the original minute.
        remaining=(max(0,(end[0]-engine.state.round_number)*6) if end else 6)
        if end and end[1]<engine.state.current_slot_index:
            remaining=max(0,remaining-6)
        if remaining:
            guards.append({'modifier':modifier.model_dump_json(), 'remaining':remaining,
                'repeat':deepcopy(creature.turn_flags.get(GUARD_FLAG,{}))})
    conditions=[{'condition':c.model_dump_json(),'remaining':6} for c in creature.conditions.values()
        if c.source_definition_id.startswith(PREFIX) and c.condition_id.endswith('reaction_denied')]
    used=int(any(c.condition_id==LIMIT+HEAVEN for c in creature.conditions.values()))
    if owned(actor) or guards or conditions:
        actor.setdefault('source_states',{})[KEY]={'scene_used':used,'guards':guards,'conditions':conditions}
        seal(actor)
    # Physical disruption persists until repaired, independent of its creator.
    if aid==next(iter(session.state['actors'])):
        records=[z.model_dump_json() for z in engine.state.zones.values()
                 if z.active and z.source_definition_id.endswith(PREFIX+'earth_shattering_fist')]
        actor.setdefault('source_states',{})[KEY+'.terrain']=records
        rows=actor['bundle'].setdefault('typed_passives',[])
        rows[:]=[r for r in rows if r.get('block')!='stone_fist_terrain']
        if records:rows.append({'block':'stone_fist_terrain','zones':records})
        project_ground(session,actor)


def project_ground(session,holder):
    """Project committed physical zones into the existing native travel regions.

    The retained list identifies only this producer's appended regions. Remove
    one matching occurrence from the end, preserving identical authored terrain.
    Each altitude is separate; this never slows creatures on another surface.
    """
    states=holder.setdefault('source_states',{})
    regions=session.state['battlefield'].setdefault('travel_regions',[])
    for prior in states.get(KEY+'.travel_regions',()):
        for index in range(len(regions)-1,-1,-1):
            if regions[index]==prior:
                del regions[index]
                break
    projected=[]
    for raw in states.get(KEY+'.terrain',()):
        zone=json.loads(raw)
        if not zone.get('active'):continue
        heights={cell.get('z',0) for cell in zone['affected_cells']}
        for height in sorted(heights):
            cells=sorted({(cell['x'],cell['y']) for cell in zone['affected_cells'] if cell.get('z',0)==height})
            if cells:
                projected.append({'kind':'broken_terrain','cells':[list(cell) for cell in cells],
                    'movement_cost':2,'ordinary':1,'requires_support':0,'min_z':height,'max_z':height})
    regions.extend(deepcopy(projected))
    states[KEY+'.travel_regions']=projected


def repairable_ground(session,aid):
    """Use actual compiled tools and retained native possession, never a flag."""
    if session.state['phase']!='travel' or session.state['actors'][aid]['incapacitated']:return {}
    if not any(a.get('source_states',{}).get(KEY+'.terrain') for a in session.state['actors'].values()):return {}
    from ..journey_assets import JourneyAssetContext
    from ..gate2_runtime_models import ConditionInstance, Position
    from .. import carry
    context=JourneyAssetContext(session)
    context.typed_bundle_documents=[a['bundle'] for a in session.state['actors'].values()]
    for actor_id,creature in context.state.actors.items():
        saved=session.state['actors'][actor_id].get('encounter_snapshot',{})
        creature.conditions={key:ConditionInstance.model_validate_json(raw) for key,raw in saved.get('conditions',{}).items()}
        creature.turn_flags={}
    actor=context.state.actors[aid]
    tools={item['item_id'] for item in (carry.carrying_of(context,aid) or {}).get('items',())
           if carry.holds(context,actor,item['key'])}
    pool={}
    for holder_id,holder in session.state['actors'].items():
        for raw in holder.get('source_states',{}).get(KEY+'.terrain',()):
            zone=json.loads(raw)
            required=((zone.get('trigger_profile') or {}).get('profile') or {}).get('repair_tools',())
            if not zone.get('active') or not tools.intersection(required):continue
            for cell in zone['affected_cells']:
                position=Position.model_validate(cell)
                if (context.grid.distance_ft(actor.position,position)<=5
                        and context.grid.line_of_sight(actor.position,position)
                        and context.grid.line_of_physical_transmission(actor.position,position)):
                    key=f'{position.x}|{position.y}|{position.z}'
                    pool[key]={'cell':cell}
    return pool


@hook('journey_options')
def repair_options(session,aid):
    return [{'id':'stone_fist_repair:'+key,'kind':'stone_fist_repair','payload':{'cell':key},'auto_select':0,
        'label':f"{session.state['actors'][aid]['name']}: clear broken ground at {key} with suitable tools (one Action, 6 seconds)."}
        for key in repairable_ground(session,aid)]


@hook('journey_command')
def repair_command(session,aid,kind,payload):
    if kind!='stone_fist_repair':return None
    from ..journey import require
    pool=repairable_ground(session,aid)
    require(set(payload)=={'cell'} and payload['cell'] in pool,'Choose a reachable broken-ground square and carry suitable tools.')
    cell=pool[payload['cell']]['cell']
    for holder in session.state['actors'].values():
        states=holder.get('source_states',{})
        if KEY+'.terrain' not in states:continue
        records=[]
        for raw in states[KEY+'.terrain']:
            zone=json.loads(raw)
            zone['affected_cells']=[c for c in zone['affected_cells'] if c!=cell]
            if zone['affected_cells']:records.append(json.dumps(zone,sort_keys=True))
        states[KEY+'.terrain']=records
        project_ground(session,holder)
        seal(holder)
    session.tick(6)
    session.emit('BROKEN_GROUND_REPAIRED',aid,source=PREFIX+'earth_shattering_fist',cell=cell,
        text=f"{session.state['actors'][aid]['name']} clears one 5-foot square with suitable tools and an Action.")
    return True


@hook('journey_elapsed')
def elapsed(session,aid,before,seconds,moving):
    actor=session.state['actors'][aid]
    state=actor.get('source_states',{}).get(KEY)
    if not state:return
    # Retain the exact native clock fraction instead of rounding the start
    # down on a movement step. Combat import rounds remaining time upward to
    # the next supported round boundary; travel expiry itself remains exact.
    for name in ('guards','conditions'):
        live=[]
        for row in state[name]:
            deadline=(Fraction(row['expires_num'],row['expires_den']) if 'expires_num' in row else
                Fraction(row['expires_at']) if 'expires_at' in row else before+row['remaining'])
            row['expires_num'],row['expires_den']=deadline.numerator,deadline.denominator
            remaining=max(Fraction(0),deadline-session.clock())
            row['remaining']=(remaining.numerator+remaining.denominator-1)//remaining.denominator
            if session.clock()<deadline:live.append(row)
        state[name]=live
    seal(actor)


@hook('journey_scene_end')
def scene_end(session,previous,current):
    for actor in session.state['actors'].values():
        state=actor.get('source_states',{}).get(KEY)
        if state:
            state['scene_used']=0
            seal(actor)


@hook('match_initialize')
def restore(engine):
    from ..gate2_runtime_models import ModifierInstance, ZoneState
    from ..typed_executor import clock_expiry
    from .effect_durations import holder_next_turn
    for bundle in engine.typed_bundle_documents:
        actor=engine.state.actors[bundle['actor_id']]
        held=next((row['state'] for row in bundle.get('typed_passives',()) if row.get('block')=='stone_fist_continuation'),None)
        if held:
            if held['scene_used']:
                engine._apply_condition(actor,LIMIT+HEAVEN,HEAVEN,actor.entity_id,
                    expires_on='UNTIL_REMOVED',data={'stamp':'fight','label':'Heaven-Cracking Blow: used this scene'})
            for row in held['guards']:
                modifier=ModifierInstance.model_validate_json(row['modifier'])
                record=row['repeat']
                owner=engine.state.actors.get(record.get('owner') or modifier.source_actor_id)
                if owner is not None and body_level(engine,owner)<10:
                    continue  # dormant, duration still runs in its retained ledger
                modifier.expires_on=clock_expiry(engine,'rounds',max(1,(row['remaining']+5)//6))
                actor.modifiers[modifier.modifier_id]=modifier
                actor.turn_flags[GUARD_FLAG]=deepcopy(record)
                engine._append_event('MODIFIER_APPLIED',PALM,actor_id=modifier.source_actor_id,
                    target_ids=(actor.entity_id,),payload={'modifier_id':modifier.modifier_id,'target_field':'armor_class',
                    'operation':'ADD','value':modifier.value,'applies_to':modifier.applies_to,'expires_on':modifier.expires_on})
            for row in held['conditions']:
                c=json.loads(row['condition'])
                engine._apply_condition(actor,c['condition_id'],c['source_definition_id'],c['source_actor_id'],
                    expires_on=holder_next_turn(actor),data=c.get('data') or {})
        for row in bundle.get('typed_passives',()):
            if row.get('block')!='stone_fist_terrain':continue
            for raw in row['zones']:
                z=ZoneState.model_validate_json(raw)
                engine.state.zones[z.zone_id]=z
                engine._append_event('ZONE_CREATED',z.source_definition_id,actor_id=z.owner_id,
                    payload={'zone':z.model_dump(mode='json')})


STAMINA='resource:core.stamina'
SHORT='tianxia.path.body_refining.short_recoveries'
CULTIVATION='tianxia.path.body_refining.cultivation_used'


def stamina_maximum(actor):
    return next((r['maximum'] for r in actor['bundle']['actor_template']['resources'] if r['resource_id']==STAMINA),0)


def recover(session,aid,amount,procedure):
    actor=session.state['actors'][aid];before=actor['resources'].get(STAMINA,0)
    actor['resources'][STAMINA]=min(stamina_maximum(actor),before+amount)
    session.emit('STAMINA_RECOVERED',aid,source=PREFIX.removesuffix('.feature.'),procedure=procedure,
        amount=actor['resources'][STAMINA]-before,remaining=actor['resources'][STAMINA])


@hook('journey_options')
def rest_options(session,aid):
    actor=session.state['actors'][aid]
    if not owned(actor) or session.state['phase']!='travel' or actor['incapacitated']:return
    uses=actor['travel_uses'];missing=stamina_maximum(actor)-actor['resources'].get(STAMINA,0)
    choices=[]
    if uses.get(SHORT,0)<2:
        choices.append({'id':'stone_fist_short_rest','kind':'stone_fist_short_rest','payload':{},'auto_select':0,
            'label':f"{actor['name']}: take a one-hour Short Rest to recover up to {stamina_maximum(actor)//2} Stamina (twice per Long Rest)."})
    if not uses.get(CULTIVATION):
        choices.append({'id':'stone_fist_cultivation','kind':'stone_fist_cultivation','payload':{},'auto_select':0,
            'label':f"{actor['name']}: cultivate for two uninterrupted hours to recover {missing} Stamina (once per Long Rest)."})
    return choices


@hook('journey_command')
def rest_command(session,aid,kind,payload):
    if kind not in {'stone_fist_short_rest','stone_fist_cultivation'}:return
    from ..journey import require
    actor=session.state['actors'][aid]
    require(owned(actor) and session.state['phase']=='travel' and not actor['incapacitated'] and not payload,
            'Choose this creature’s full Stone Fist rest procedure outside combat.')
    uses=actor['travel_uses']
    if kind=='stone_fist_short_rest':
        require(uses.get(SHORT,0)<2,'Both Short Rest recoveries are spent until a Long Rest.')
        session.tick(3600);uses[SHORT]=uses.get(SHORT,0)+1
        recover(session,aid,stamina_maximum(actor)//2,'short_rest')
    else:
        require(not uses.get(CULTIVATION),'This Cultivation Session recovery is spent until a Long Rest.')
        session.tick(7200);uses[CULTIVATION]=1
        recover(session,aid,stamina_maximum(actor),'cultivation_session')
    return True


@hook('journey_rest')
def long_rest(session,aid):
    actor=session.state['actors'][aid]
    if owned(actor):
        actor['travel_uses'][SHORT]=0;actor['travel_uses'][CULTIVATION]=0
        recover(session,aid,stamina_maximum(actor),'long_rest')
