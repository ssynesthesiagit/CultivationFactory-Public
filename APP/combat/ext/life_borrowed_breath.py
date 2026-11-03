"""Borrowed Breath's accepted-pool clock and optional Lasting Breath.

Reuses native grants, stabilization, injury limits and grant identity. Existing
compile_actions, event and boundary hooks suffice; no core overrides. Only an
accepted grant from an owned Life action creates a receipt. Journey continuation
uses the existing encounter snapshots and elapsed/rest hooks; clocks and grant
identity are rebound at the next encounter, never copied from another fight.
"""
import copy
import json
from fractions import Fraction

from . import effect, hook
from .ability_source import mechanic_of
from .effect_durations import due, round_token
from .riders_shared import remove_benefit_condition
from .temp_hp_grants import held_grant

SOURCE = 'LIFE_BASE_BORROWED_BREATH'
POOL = 'condition:typed.mark.borrowed_breath_pool'
EXTEND = 'life_lasting_breath'


def owns_pool(engine, holder, condition):
    held = held_grant(engine.events, holder.entity_id)
    return (held is None and condition.data.get('imported_pool') == 1 or
            held is not None and held[2] == condition.data.get('grant_sequence'))


@hook('compile_action')
def living_recipients(action, info):
    if mechanic_of(action) != SOURCE:
        return None
    parameters = copy.deepcopy(action.parameters)
    if any(row.get('type') == EXTEND for row in parameters['typed'].get('effects') or []):
        return None
    for row in parameters['typed'].get('effects') or []:
        row.setdefault('unless_kind', {'kinds': ['undead', 'construct'],
            'except_owner_modifier': 'tianxia.talent.life.esoteric_vitality'})
    return action.model_copy(update={'parameters': parameters, 'target_kind': 'ANY_CREATURE'})


def pools(engine, owner):
    """Return proven, unextended pools belonging to this caster, never guesses."""
    return [(holder, c) for holder in engine.state.actors.values()
            for c in holder.conditions.values() if c.condition_id == POOL
            and c.source_actor_id == owner.entity_id and not c.data.get('lasting')
            and not due(engine, c.data.get('end_clock'))
            and holder.temporary_hp > 0
            and owns_pool(engine, holder, c)]


@hook('compile_actions')
def actions(info):
    if SOURCE not in info['owned_ids']:
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    pool = RESOURCE_IDS.get(info['primary'])
    if not pool:
        return None
    out = []
    for base in info['actions']:
        if mechanic_of(base) != SOURCE:
            continue
        parameters = copy.deepcopy(base.parameters)
        parameters['typed']['lasting_breath'] = 1
        costs = dict(base.costs)
        costs[pool] = costs.get(pool, 0) + 1
        out.append(base.model_copy(update={
            'source_definition_id': base.source_definition_id + '.lasting_breath',
            'display_name': base.display_name + ' + Lasting Breath (1 extra cultivation point; until your Long Rest)',
            'parameters': parameters, 'costs': tuple(costs.items())}))
    out.append(ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.life.lasting_breath",
        display_name='Lasting Breath: extend your Borrowed Breath (1 cultivation point; no action; until your Long Rest)',
        owner_id=info['actor_id'], economy=EconomyKind.NONE,
        resolution_kind='TYPED', target_kind='SELF', costs=((pool, 1),),
        parameters={'typed': {'source': SOURCE, 'numbers': info['numbers'],
                             'effects': [{'type': EXTEND}], 'riders': []}}))
    return out


@hook('candidate_allowed')
def allowed(engine, actor, candidate, action):
    if action is None or mechanic_of(action) != SOURCE:
        return None
    typed = action.parameters.get('typed') or {}
    if any(row.get('type') == EXTEND for row in typed.get('effects') or []):
        return engine.state.current_actor_id == actor.entity_id and bool(pools(engine, actor))
    return None


@hook('event', nested=True)
def record_pool(engine, event_type, kwargs):
    if event_type == 'MATCH_ENDED':
        expire(engine)
        from .effect_durations import parse_round
        from .retained_updates import record_instance_update
        slots = len(engine.state.initiative_order)
        for holder in engine.state.actors.values():
            for c in holder.conditions.values():
                if c.condition_id != POOL or c.data.get('lasting'):
                    continue
                end_round, end_slot = parse_round(c.data['end_clock'])
                c.data['remaining_num'] = max(0, ((end_round - engine.state.round_number) * slots
                    + end_slot - engine.state.current_slot_index) * 6)
                c.data['remaining_den'] = slots
                record_instance_update(engine, holder, 'condition', c.instance_id, c)
        return
    if event_type != 'TEMP_HP_GRANTED':
        return
    payload = kwargs.get('payload') or {}
    if int(payload.get('after') or 0) <= int(payload.get('before') or 0):
        return
    source = kwargs.get('source_definition_id')
    action = engine.action_catalog.get(source)
    for aid in kwargs.get('target_ids') or ():
        holder = engine.state.actors[aid]
        for old in list(holder.conditions.values()):
            if old.condition_id == POOL:
                remove_benefit_condition(engine, holder, old, 'TEMPORARY_HP_REPLACED')
        if action is None or mechanic_of(action) != SOURCE or action.owner_id != kwargs.get('actor_id'):
            continue
        held = held_grant(engine.events, aid)
        if held is None:
            continue
        lasting = int(bool((action.parameters.get('typed') or {}).get('lasting_breath')))
        engine._apply_condition(holder, POOL, source, action.owner_id,
            expires_on='UNTIL_REMOVED', data={
                'grant_sequence': held[2], 'lasting': lasting,
                'end_clock': '' if lasting else round_token(engine, 600),
                'label': 'Borrowed Breath: Temporary HP until depleted or ' +
                         ('the caster finishes a Long Rest' if lasting else '1 hour passes')})


@effect(EXTEND)
def extend(ctx, row):
    from .needle import ask, checkpoint_id
    available = pools(ctx.engine, ctx.actor)
    options = {holder.entity_id: (holder, c) for holder, c in available}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, EXTEND), ctx.actor,
        'choice:needle.lasting_breath', list(options),
        labels={aid: holder.display_name for aid, (holder, _) in options.items()},
        preferred=list(options)[:1], allow_decline=False,
        prompt=f'Lasting Breath: extend your Borrowed Breath on one creature for 1 cultivation point '
               f'and no action. Its remaining Temporary HP last until depleted or until '
               f'{ctx.actor.display_name} finishes a Long Rest. Choose the affected creature.')
    if not selected:
        return
    holder, c = options[selected[0]]
    data = {**c.data, 'lasting': 1, 'end_clock': '',
            'label': 'Borrowed Breath: Temporary HP until depleted or the caster finishes a Long Rest'}
    remove_benefit_condition(ctx.engine, holder, c, 'LASTING_BREATH')
    ctx.engine._apply_condition(holder, POOL, c.source_definition_id, ctx.actor.entity_id,
                               expires_on='UNTIL_REMOVED', data=data)


def expire(engine):
    for holder in engine.state.actors.values():
        for c in list(holder.conditions.values()):
            if c.condition_id != POOL:
                continue
            owns = owns_pool(engine, holder, c)
            expired = not c.data.get('lasting') and due(engine, c.data.get('end_clock'))
            if not owns or not holder.temporary_hp or expired:
                remove_benefit_condition(engine, holder, c, 'BORROWED_BREATH_ENDED')
                if owns and expired and holder.temporary_hp:
                    before, holder.temporary_hp = holder.temporary_hp, 0
                    engine._append_event('TEMP_HP_GRANTED', c.source_definition_id,
                        actor_id=c.source_actor_id, target_ids=(holder.entity_id,),
                        payload={'offered': 0, 'before': before, 'after': 0,
                                 'log': 'Borrowed Breath ends after 1 hour.'})


@hook('turn_boundary_start')
def boundary(engine, actor, **kwargs):
    expire(engine)


@hook('nominal_slot_boundary')
def nominal(engine, actor, checkpoint):
    if checkpoint == 'START_OF_TURN':
        expire(engine)


def journey_pools(session, aid):
    snapshot = session.state['actors'][aid].get('encounter_snapshot')
    if snapshot is None:
        return
    for key, raw in list(snapshot['conditions'].items()):
        condition = json.loads(raw)
        if condition['condition_id'] == POOL:
            yield snapshot, key, condition


def end_journey_pool(session, aid, snapshot, key, reason):
    snapshot['conditions'].pop(key)
    snapshot['temporary_hp'] = 0
    session.emit('BORROWED_BREATH_ENDED', aid,
                 text='Borrowed Breath Temporary HP end: ' + reason + '.')


@hook('journey_elapsed')
def travel_clock(session, aid, before, seconds, moving):
    for snapshot, key, c in journey_pools(session, aid):
        data = c['data']
        if data.get('lasting'):
            continue
        remaining = Fraction(data['remaining_num'], data['remaining_den']) - seconds
        if remaining <= 0:
            end_journey_pool(session, aid, snapshot, key, '1 hour has passed')
        else:
            data['remaining_num'], data['remaining_den'] = remaining.numerator, remaining.denominator
            snapshot['conditions'][key] = json.dumps(c, sort_keys=True)


@hook('journey_rest')
def caster_rest(session, aid):
    for recipient in session.state['actors']:
        for snapshot, key, c in journey_pools(session, recipient):
            if c['source_actor_id'] == aid and c['data'].get('lasting'):
                end_journey_pool(session, recipient, snapshot, key, 'the caster finished a Long Rest')


@hook('match_initialize', priority=100)
def import_pool(engine):
    from .retained_updates import record_instance_update
    for bundle in engine.typed_bundle_documents:
        snapshot = (bundle.get('journey_setup') or {}).get('encounter_snapshot')
        holder = engine.state.actors.get(bundle['actor_id'])
        if snapshot is None or holder is None:
            continue
        for key, c in holder.conditions.items():
            if c.condition_id != POOL or key not in snapshot['conditions']:
                continue
            c.data['imported_pool'] = 1
            c.data['grant_sequence'] = 0
            if not c.data.get('lasting'):
                slots = len(engine.state.initiative_order)
                seconds = Fraction(c.data['remaining_num'], c.data['remaining_den'])
                fraction = seconds * slots / 6
                ticks = -(-fraction.numerator // fraction.denominator)
                turns, slot = divmod(engine.state.current_slot_index + ticks, slots)
                c.data['end_clock'] = f'START_OF_SLOT_AT:{engine.state.round_number + turns}:{slot}'
            record_instance_update(engine, holder, 'condition', key, c)
