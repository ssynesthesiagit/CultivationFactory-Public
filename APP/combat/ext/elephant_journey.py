"""White Elephant's source-owned form clocks outside initiative.

Uses the native source_selections registry and journey command/clock adapters.
Acquisition remains the compiled, source-bound progression; commands cannot
declare ownership, Source CL, payment or consent. Combat effects still have one
implementation, elephant_sovereign plus the printed typed King effects.
"""
from copy import deepcopy
from fractions import Fraction
from math import ceil
import json

from . import hook
from .elephant_sovereign import PREFIX, KING, LARGE, STAMINA, sovereign_size, RECORDS, MEMORY_SOURCE, remembered_records
from ..dynamic_size import CATEGORIES, WIDTHS
from ..gate2_runtime_models import Position
from ..footprints import ActorFootprintDefinition
from ..journey import require

SOURCE = PREFIX.removesuffix('.feature.')
MOUNTAIN = PREFIX + 'mountain_walking_sovereign'
KING_SOURCE = PREFIX + KING
SETUP = 'white_elephant_forms'


def owned(actor, feature):
    bundle = actor['bundle']
    return any(row.get('feature_id') == feature for row in bundle.get('typed_passives', ())) or any(
        (row.get('parameters', {}).get('typed', {}).get('option_of') or
         row.get('parameters', {}).get('typed', {}).get('source')) == feature for row in bundle['action_catalog'])


def numbers(actor):
    return next((dict(row['numbers']) for row in actor['bundle'].get('typed_passives', ())
                 if row.get('block') == 'elephant_profile'), {})


def data(actor):
    return deepcopy(actor.get('source_selections', {}).get(SOURCE, {}))


def remaining(record):
    return Fraction(record.get('remaining_num', 0), record.get('remaining_den', 1))


def mode(actor):
    record = data(actor)
    cl = int(numbers(actor).get('cl', 0))
    if record.get('mode') == 'king' and remaining(record) > 0 and cl >= 18 and owned(actor, KING_SOURCE):
        return 'king'
    if record.get('mode') == 'mountain' and cl >= 14 and owned(actor, MOUNTAIN):
        return 'mountain'
    return 'normal'


def save(actor, record):
    actor.setdefault('source_selections', {})[SOURCE] = {**data(actor),**record}


def width(size):
    return WIDTHS[CATEGORIES.index(size)]


def footprint(size):
    return ActorFootprintDefinition.rectangle(width(size), width(size),
        footprint_id='footprint:elephant.journey', source_definition_id=SOURCE)


def occupied(session, exclude):
    cells = set()
    for aid, actor in session.state['actors'].items():
        if aid == exclude or actor.get('carried_by'):
            continue
        pos = Position.model_validate(actor['position'])
        cells.update((x, y, pos.z) for x, y in footprint(actor['size']).occupied_cells((pos.x, pos.y)))
    return cells


def fit(session, aid, size):
    actor = session.state['actors'][aid]
    old = Position.model_validate(actor['position'])
    previous = set(footprint(actor['size']).occupied_cells((old.x, old.y)))
    wanted = footprint(size)
    occupied_cells = occupied(session, aid)
    candidates = []
    for x in range(old.x-width(size)+1, old.x+width(actor['size'])):
        for y in range(old.y-width(size)+1, old.y+width(actor['size'])):
            cells = set(wanted.occupied_cells((x,y)))
            grows = width(size) > width(actor['size'])
            if not (previous <= cells if grows else bool(previous & cells)):
                continue
            at = Position(x=x,y=y,z=old.z)
            if session.grid.volume_legal(at, footprint=wanted, occupied_cells=occupied_cells):
                candidates.append(at)
    return min(candidates,key=lambda p:(abs(p.x-old.x)+abs(p.y-old.y),p.y,p.x)) if candidates else None


def sync(session, aid):
    actor = session.state['actors'][aid]
    record = data(actor)
    if not record:
        return
    selected = mode(actor)
    desired = record.get('size', 'Large') if selected == 'king' else 'Large' if selected == 'mountain' else record['base_size']
    if actor['size'] != desired:
        at = fit(session, aid, desired)
        require(at is not None, f"{actor['name']} has no legal space for the current body form.")
        actor['size'], actor['position'] = desired, at.model_dump(mode='json')


def counters(actor):
    action = next((a for a in actor['bundle']['action_catalog']
                   if a.get('parameters', {}).get('typed', {}).get('source') == KING_SOURCE), None)
    return [rid for rid, cost in (action or {}).get('costs', ()) if rid != STAMINA and cost == 1
            and any(r['resource_id'] == rid and r['maximum'] == 1 for r in actor['bundle']['actor_template']['resources'])]


@hook('journey_options')
def form_options(session, aid):
    actor = session.state['actors'][aid]
    if actor['incapacitated'] or not numbers(actor):
        return None
    result = []
    cl, current = int(numbers(actor)['cl']), mode(actor)
    if cl >= 14 and owned(actor, MOUNTAIN):
        normal = current == 'mountain'
        result.append({'id':'elephant:normal' if normal else 'elephant:mountain', 'kind':'elephant_form',
            'payload':{'form':'normal' if normal else 'mountain'},
            'label':f"{actor['name']}: Mountain-Walking Sovereign — Bonus Action; {'return to normal size' if normal else 'become Large'}, until changed or Unconscious. No Stamina cost."})
    if cl >= 18 and owned(actor, KING_SOURCE) and actor['travel_uses'].get(KING_SOURCE) != session.state['journey_id']:
        result.append({'id':'elephant:king','kind':'elephant_form','payload':{'form':'king'},
            'label':f"{actor['name']}: World-Bearing Elephant King — Bonus Action, 7 Stamina, once this scene; become Huge, or Large if Huge cannot fit, for 1 minute."})
    return result


@hook('journey_command')
def choose_form(session, aid, kind, payload):
    if kind != 'elephant_form':
        return None
    actor = session.state['actors'][aid]
    option = next((o for o in form_options(session, aid) or [] if o['payload'] == payload), None)
    require(option is not None and set(payload) == {'form'}, 'Choose an available White Elephant form.')
    selected = payload['form']
    record = data(actor)
    base = record.get('base_size') or actor['bundle']['actor_template'].get('size_category', 'Medium')
    size = base if selected == 'normal' else 'Large'
    if selected == 'king':
        require(actor['resources'].get(STAMINA, 0) >= 7, 'World-Bearing Elephant King needs 7 Stamina.')
        size = 'Huge' if fit(session, aid, 'Huge') is not None else 'Large'
    at = fit(session, aid, size)
    # Activation takes one outside-initiative action interval; the new minute
    # starts after this interval, rather than losing its first six seconds.
    session.tick(6)
    if selected == 'king':
        actor['resources'][STAMINA] -= 7
        actor['travel_uses'][KING_SOURCE] = session.state['journey_id']
        for rid in counters(actor):
            actor['resources'][rid] = 0
    if at is None:
        session.emit('BODY_FORM_FAILED', aid, source=MOUNTAIN if selected != 'king' else KING_SOURCE,
                     text=f"{actor['name']} spends the Bonus Action, but no legal {size} space exists.")
        return True
    record = {'mode':selected, 'base_size':base, 'size':size, 'source_cl':int(numbers(actor)['cl']),
              'remaining_num':60 if selected == 'king' else 0, 'remaining_den':1,
              'equipment':'Ordinary worn and carried equipment resizes to fit; item statistics and ownership remain the same.'}
    save(actor, record)
    actor['size'], actor['position'] = size, at.model_dump(mode='json')
    session.emit('BODY_FORM_CHANGED', aid, source=KING_SOURCE if selected == 'king' else MOUNTAIN,
                 text=f"{actor['name']} assumes {size} size. " + ('World-Bearing Elephant King lasts 1 minute.' if selected == 'king' else 'Mountain-Walking Sovereign lasts until changed or Unconscious.'))
    return True


@hook('journey_properties')
def form_properties(session, aid):
    actor = session.state['actors'][aid]
    if not numbers(actor):
        return None
    current, record = mode(actor), data(actor)
    result = {'white_elephant_form':current}
    if current == 'mountain':
        result['speed_delta_ft'] = -5
    if current == 'king':
        deadline = session.clock() + remaining(record)
        result.update(speed_delta_ft=20, expiry_num=deadline.numerator, expiry_den=deadline.denominator)
    return result


@hook('journey_step')
def form_step(session, aid, old, nxt, rows):
    actor = session.state['actors'][aid]
    if mode(actor) == 'normal':
        return None
    shape = footprint(actor['size'])
    require(session.grid.volume_step_legal(old,nxt,footprint=shape,occupied_cells=occupied(session,aid)),
            f"{actor['name']}'s {actor['size']} body cannot fit through that step.")
    # Retain any overlapping extraordinary/hazardous region of the same kind.
    if mode(actor) == 'mountain':
        kinds = {r['kind'] for r in rows if r['ordinary'] and not r['requires_support']}
        kinds -= {r['kind'] for r in rows if not r['ordinary'] or r['requires_support']}
        return {'ignore_slowing':sorted(kinds)}
    return None


@hook('journey_elapsed')
def elapsed(session, aid, previous, seconds, moving):
    actor = session.state['actors'][aid]
    record = data(actor)
    if record.get('mode') != 'king':
        return
    left = max(Fraction(0), remaining(record)-seconds)
    record['remaining_num'], record['remaining_den'] = left.numerator, left.denominator
    if not left:
        record['mode'] = 'normal'
    save(actor,record)
    sync(session,aid)


@hook('journey_combat_setup')
def bind_forms(session, aid):
    actor = session.state['actors'][aid]
    if not numbers(actor):
        return None
    return {SETUP:{**data(actor), 'scene_spent':int(actor['travel_uses'].get(KING_SOURCE)==session.state['journey_id'])}}


@hook('match_initialize')
def restore_forms(engine):
    from .states import context
    from .. import typed_executor as te
    for bundle in engine.typed_bundle_documents:
        record = (bundle.get('journey_setup') or {}).get(SETUP)
        if record is None:
            continue
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue
        wrapped = {'bundle':bundle}
        if owned(wrapped,MEMORY_SOURCE) and isinstance(record.get('remembered'),dict):
            actor.turn_flags[RECORDS] = deepcopy(record['remembered'])
            actor.turn_flags[RECORDS] = remembered_records(actor)
        for rid in counters(wrapped):
            actor.resources[rid] = 0 if record.get('scene_spent') else 1
        selected = record.get('mode')
        feature = KING_SOURCE if selected == 'king' else MOUNTAIN
        if selected not in {'king','mountain'} or not owned(wrapped,feature):
            continue
        profile = numbers(wrapped)
        if int(profile.get('cl',0)) < (18 if selected == 'king' else 14):
            continue
        if selected == 'mountain':
            sovereign_size(context(engine,actor,MOUNTAIN,[actor],profile),{})
        elif remaining(record) > 0:
            action = next(a for a in engine.action_catalog.values() if a.owner_id==actor.entity_id
                          and a.parameters.get('typed',{}).get('source')==KING_SOURCE)
            duration = {'kind':'rounds','amount':max(1,ceil(remaining(record)/6))}
            effects = deepcopy(action.parameters['typed']['effects'])
            for row in effects:
                if row.get('duration'):
                    row['duration'] = duration
            ctx = context(engine,actor,action.source_definition_id,[actor],profile)
            ctx.typed = {**deepcopy(action.parameters['typed']), 'duration':duration,
                         'numbers':{**profile,'cl':record.get('source_cl',profile['cl'])}}
            te.run_effects(ctx,effects)
            state = next(c for c in actor.conditions.values() if c.data.get('name')==KING)
            actor.conditions[state.instance_id] = state.model_copy(update={'data':{**state.data,
                'journey_remaining_num':record['remaining_num'], 'journey_remaining_den':record['remaining_den'],
                'journey_start_round':engine.state.round_number,'journey_start_slot':engine.state.current_slot_index}})


def combat_remaining(engine, state):
    from .effect_durations import parse_round
    slots = len(engine.state.initiative_order)
    if 'journey_remaining_num' in state.data:
        elapsed = ((engine.state.round_number-state.data['journey_start_round'])*slots
                   +engine.state.current_slot_index-state.data['journey_start_slot'])
        return max(Fraction(0), Fraction(state.data['journey_remaining_num'],state.data['journey_remaining_den'])-Fraction(elapsed*6,slots))
    deadline = parse_round(state.expires_on)
    require(deadline is not None, 'The Elephant King form needs its native remaining-duration clock.')
    count = (deadline[0]-engine.state.round_number)*slots+deadline[1]-engine.state.current_slot_index
    return max(Fraction(0),Fraction(count*6,slots))


@hook('turn_boundary_start')
def expire_transferred_king(engine, actor):
    from .elephant_sovereign import end_sovereign_form
    for creature in engine.state.actors.values():
        state = next((c for c in creature.conditions.values() if c.data.get('name')==KING
                      and 'journey_remaining_num' in c.data),None)
        if state is not None and combat_remaining(engine,state) <= 0:
            end_sovereign_form(engine,creature,KING,reason='DURATION_ENDED')


@hook('journey_encounter_actor')
def export_forms(session, aid, engine, creature, effects_ended):
    from .ability_source import mechanic_at
    actor = session.state['actors'][aid]
    if not numbers(actor):
        return None
    own_sources = {MOUNTAIN,KING_SOURCE}
    def source_of(row):
        return mechanic_at(engine,row.source_definition_id) or row.source_definition_id
    king = next((c for c in creature.conditions.values() if c.data.get('name')==KING and source_of(c)==KING_SOURCE),None)
    mountain = next((c for c in creature.conditions.values() if c.data.get('name')==LARGE and source_of(c)==MOUNTAIN),None)
    record = {'mode':'normal','base_size':creature.size_category,'size':creature.size_category,
              'source_cl':int(numbers(actor)['cl']), 'remaining_num':0,'remaining_den':1,
              'remembered':remembered_records(creature)}
    if not effects_ended and king is not None:
        left = combat_remaining(engine,king)
        record.update(mode='king' if left else 'normal',size=creature.transformed_size_category or creature.size_category,
                      remaining_num=left.numerator,remaining_den=left.denominator,
                      source_cl=int((king.data.get('numbers') or {}).get('cl') or numbers(actor)['cl']))
    elif not effects_ended and mountain is not None:
        record.update(mode='mountain',size='Large')
    save(actor,record)
    if any(creature.resources.get(rid)==0 for rid in counters(actor)):
        actor['travel_uses'][KING_SOURCE] = session.state['journey_id']
    return creature.model_copy(update={
        'conditions':{key:c for key,c in creature.conditions.items() if source_of(c) not in own_sources},
        'modifiers':{key:m for key,m in creature.modifiers.items() if source_of(m) not in own_sources},
        'transformed_size_category':creature.transformed_size_category if any(
            c.condition_id=='condition:typed.size_change' and source_of(c) not in own_sources for c in creature.conditions.values()) else None})


@hook('journey_started')
def start_journey(session, aid):
    actor = session.state['actors'][aid]
    if not numbers(actor):
        return
    if actor['travel_uses'].get(KING_SOURCE) != session.state['journey_id']:
        for rid in counters(actor):
            actor['resources'][rid] = 1
    sync(session,aid)


@hook('journey_state_changed')
def changed(session, aid):
    actor = session.state['actors'][aid]
    snapshot = actor.get('encounter_snapshot') or {}
    if session.state['phase'] == 'finished':
        if numbers(actor):
            save(actor,{'remembered':{}})
        return
    if session.state['phase'] != 'travel' or not numbers(actor):
        return
    unconscious = snapshot.get('life_state') in {'DYING','STABLE'} or any(
        str(json.loads(encoded)['condition_id']).endswith('unconscious') for encoded in snapshot.get('conditions',{}).values())
    record = data(actor)
    if record and (unconscious or int(numbers(actor)['cl'])==0 and record.get('mode')=='mountain'):
        record.update(mode='normal',remaining_num=0,remaining_den=1)
        save(actor,record)
    sync(session,aid)
