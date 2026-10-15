"""Ryujin's source-specific continuation over the owner's general journey seams.

Consumers: ryujin.py's actual acquired source and native form activation. Only
committed native form conditions/modifiers/zones can produce a carried form.
No declaration, payload, reopening or absent form can create one or refill a
scene token. Integer numerator/denominator clocks retain exact elapsed time;
JSON model strings preserve native effect identity without opaque state leaves.
This adapter grants no generic body-mode travel or dynamic realm suppression.
"""
from copy import deepcopy
from fractions import Fraction
from . import hook
from .ryujin import PARENT, PREFIX, FORM, source_record
from .states import active
from .effect_durations import parse_round
from ..canonical import canonical_sha256


def _now(engine):
    # A whole round is six seconds. Initiative slots retain their exact phase
    # when a duration crosses the encounter/travel boundary.
    return Fraction((engine.state.round_number - 1) * 6) + Fraction(
        engine.state.current_slot_index * 6, max(1, len(engine.state.initiative_order)))


def _sources(engine, aid):
    return {action.source_definition_id for action in engine.action_catalog.values()
            if action.owner_id == aid and action.parameters.get('typed', {}).get('source') == PREFIX + FORM}


def _remaining(engine, condition):
    data = condition.data or {}
    if 'ryujin_deadline_num' in data:
        return max(Fraction(0), Fraction(data['ryujin_deadline_num'], data['ryujin_deadline_den']) - _now(engine))
    deadline = parse_round(condition.expires_on)
    if deadline is None:
        raise ValueError('Ryūjin form continuation requires its native counted duration.')
    round_number, slot = deadline
    return max(Fraction(0), Fraction((round_number - 1) * 6)
               + Fraction(slot * 6, max(1, len(engine.state.initiative_order))) - _now(engine))


def _bind(session, aid):
    record = source_record(session, aid)
    if not record:
        return
    actor = session.state['actors'][aid]
    continuation = record.get('form')
    if continuation:
        if continuation['epoch'] != session.state['journey_id']:
            remaining = Fraction(continuation['remaining_num'], continuation['remaining_den'])
            deadline = session.clock() + remaining
            continuation.update(epoch=session.state['journey_id'], deadline_num=deadline.numerator,
                                deadline_den=deadline.denominator)
        remaining = max(Fraction(0), Fraction(continuation['deadline_num'], continuation['deadline_den']) - session.clock())
        continuation.update(remaining_num=remaining.numerator, remaining_den=remaining.denominator)
        if not remaining:
            record.pop('form')
            continuation = None
            session.emit('RYUJIN_FORM_EXPIRED', aid, source=PREFIX + FORM)
    bundle = actor['bundle']
    if continuation:
        bundle['ryujin_continuation'] = deepcopy(continuation)
    else:
        bundle.pop('ryujin_continuation', None)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


@hook('journey_initialize')
@hook('journey_state_changed')
def bind_source_clock(session, aid):
    _bind(session, aid)


@hook('journey_elapsed')
def elapsed_source_clock(session, aid, before, seconds, moving):
    _bind(session, aid)


@hook('journey_encounter_settled')
def export_native_form(session, aid, engine, creature):
    record = source_record(session, aid)
    if not record:
        return
    condition = active(engine, creature, FORM)
    if condition is None:
        record.pop('form', None)
        _bind(session, aid)
        return
    sources = _sources(engine, aid)
    remaining = _remaining(engine, condition)
    if not remaining:
        record.pop('form', None)
        _bind(session, aid)
        return
    deadline = session.clock() + remaining
    record['form'] = {'epoch': session.state['journey_id'], 'deadline_num': deadline.numerator,
                      'deadline_den': deadline.denominator, 'remaining_num': remaining.numerator,
                      'remaining_den': remaining.denominator,
                      'conditions': [c.model_dump_json() for c in creature.conditions.values() if c.source_definition_id in sources],
                      'modifiers': [m.model_dump_json() for m in creature.modifiers.values() if m.source_definition_id in sources],
                      'zones': [z.model_dump_json() for z in engine.state.zones.values()
                                if z.active and z.owner_id == aid and z.source_definition_id in sources]}
    session.emit('RYUJIN_FORM_CONTINUED', aid, source=PREFIX + FORM,
                 remaining_num=remaining.numerator, remaining_den=remaining.denominator)
    _bind(session, aid)


@hook('journey_snapshot_actor')
def source_snapshot(actor, session, aid, engine):
    if not source_record(session, aid):
        return None
    sources = _sources(engine, aid)
    if not any(c.source_definition_id in sources for c in actor.conditions.values()):
        return None
    projected = actor.model_copy(deep=True)
    growth = any(c.condition_id == 'condition:typed.size_change' and c.source_definition_id in sources
                 for c in actor.conditions.values())
    projected.conditions = {key: c for key, c in projected.conditions.items() if c.source_definition_id not in sources}
    projected.modifiers = {key: m for key, m in projected.modifiers.items() if m.source_definition_id not in sources}
    if growth:
        # The generic snapshot still rejects an independent ongoing growth.
        # Strip only this source's own temporary size, never someone else's.
        independent = any(c.condition_id == 'condition:typed.size_change' for c in projected.conditions.values())
        if not independent:
            projected.transformed_size_category = None
    return projected


@hook('match_initialize', priority=50)
def restore_native_form(engine):
    from ..gate2_runtime_models import ConditionInstance, ModifierInstance, ZoneState
    from .retained_updates import record_instance_update, record_zone_update
    from .. import dynamic_size, zones
    for bundle in engine.typed_bundle_documents:
        saved = bundle.get('ryujin_continuation')
        actor = engine.state.actors.get(bundle['actor_id'])
        if not saved or actor is None:
            continue
        if not any(r.get('block') == 'ryujin_native' for r in bundle.get('typed_passives', [])):
            raise ValueError('A carried Ryūjin form requires its actual acquired source.')
        remaining = Fraction(saved['remaining_num'], saved['remaining_den'])
        if remaining <= 0:
            continue
        deadline = _now(engine) + remaining
        for document in saved['conditions']:
            row = ConditionInstance.model_validate_json(document)
            if row.source_definition_id not in _sources(engine, actor.entity_id) or row.source_actor_id != actor.entity_id:
                raise ValueError('A carried Ryūjin condition lost its native source owner.')
            row.expires_on = 'UNTIL_REMOVED'
            if row.condition_id == 'condition:typed.state.' + FORM:
                row.data = {**row.data, 'ryujin_deadline_num': deadline.numerator, 'ryujin_deadline_den': deadline.denominator}
            actor.conditions[row.instance_id] = row
            record_instance_update(engine, actor, 'condition', row.instance_id, row)
        for document in saved['modifiers']:
            row = ModifierInstance.model_validate_json(document)
            if row.source_definition_id not in _sources(engine, actor.entity_id) or row.source_actor_id != actor.entity_id:
                raise ValueError('A carried Ryūjin modifier lost its native source owner.')
            row.expires_on = 'UNTIL_REMOVED'
            actor.modifiers[row.modifier_id] = row
            record_instance_update(engine, actor, 'modifier', row.modifier_id, row)
        dynamic_size.sync(engine, PREFIX + FORM)
        for document in saved['zones']:
            row = ZoneState.model_validate_json(document)
            if row.owner_id != actor.entity_id or row.source_definition_id not in _sources(engine, actor.entity_id):
                raise ValueError('A carried Ryūjin aura lost its native source owner.')
            row.center = actor.position
            row.created_round = engine.state.round_number
            row.duration_rounds = None
            row.affected_cells = zones.area_cells(engine, row)
            row.per_turn_triggered = {}
            engine.state.zones[row.zone_id] = row
            record_zone_update(engine, row)


@hook('turn_start', priority=-90)
@hook('turn_end', priority=-90)
def expire_continued_form(engine, current):
    from .. import zones
    for actor in engine.state.actors.values():
        condition = active(engine, actor, FORM)
        if condition is None or 'ryujin_deadline_num' not in condition.data:
            continue
        if _now(engine) < Fraction(condition.data['ryujin_deadline_num'], condition.data['ryujin_deadline_den']):
            continue
        sources = _sources(engine, actor.entity_id)
        for key, row in list(actor.conditions.items()):
            if row.source_definition_id in sources:
                engine._remove_condition_instance(actor, key, PREFIX + FORM, actor_id=actor.entity_id)
        for key, row in list(actor.modifiers.items()):
            if row.source_definition_id in sources:
                engine._remove_modifier_instance(actor, key, PREFIX + FORM, actor_id=actor.entity_id)
        for row in list(engine.state.zones.values()):
            if row.owner_id == actor.entity_id and row.source_definition_id in sources:
                zones.remove(engine, row, 'Ryūjin Ascendant Form expires')
