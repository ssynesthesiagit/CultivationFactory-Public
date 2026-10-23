"""Homefire Recovery: recipient-owned choices and current resource balances.

Uses the same current Exhaustion provenance as journey continuation. Completed
recovery and the per-recipient Long Rest allowance outlive the originating asset.
Shared receive(ctx, subject) serves qi_welcoming_flame using the same choice,
current-level provenance and persisted cadence as the short-rest consumer.
"""
import json
from dataclasses import replace
from itertools import combinations

from . import hook
from .qi_hearthfire import HEARTH, RECOVERY, BLOCK, hearths, aura_contains
from .passive_rows import row_of
from .exhaustion_sources import journey_causes

USED = 'condition:typed.homefire_recovery_used'
FEAR = 'condition:typed.homefire_courage'
CAUSES = {'travel', 'hunger', 'thirst', 'exposure', 'ordinary_smoke', 'environmental_hardship'}
PENALTIES = {'cold', 'rain', 'smoke', 'altitude', 'poor_shelter', 'damp'}


def owned_action(actor, source):
    """Saved native acquisition, not a caller's claim to own a source."""
    return next((a for a in actor['bundle'].get('action_catalog', ())
                 if (a.get('parameters', {}).get('typed') or {}).get('source') == source), None)


def recovery_row(actor):
    return next((r for r in actor['bundle'].get('typed_passives', ())
                 if r.get('block') == BLOCK and r.get('kind') == 'shield'), None)


def snapshot(actor):
    """Create an ordinary healthy encounter snapshot only when none exists."""
    if 'encounter_snapshot' not in actor:
        hp = actor['bundle']['actor_template']['maximum_hp']
        actor['encounter_snapshot'] = {'current_hp': hp, 'maximum_hp': hp,
            'temporary_hp': 0, 'active': 1, 'life_state': '', 'conditions': {},
            'death_saves': {'ok': 0, 'bad': 0}}
    return actor['encounter_snapshot']


def condition_rows(actor):
    return [json.loads(raw) for raw in (actor.get('encounter_snapshot') or {}).get('conditions', {}).values()]


def used(actor):
    return any(c['condition_id'] == USED for c in condition_rows(actor))


def penalty(data):
    return data.get('ordinary_environmental') == 1 and data.get('environmental_cause') in PENALTIES


def available(actor):
    options = ['hp', 'temp_hp', 'fear']
    if any(c in CAUSES for c in journey_causes(actor)):
        options.append('exhaustion')
    options += ['penalty:' + c['instance_id'] for c in condition_rows(actor) if penalty(c.get('data') or {})]
    return options


def put_condition(actor, aid, owner, cid, data):
    from ..gate2_runtime_models import ConditionInstance
    key = cid + ':' + aid
    snapshot(actor)['conditions'][key] = ConditionInstance(
        instance_id=key, condition_id=cid, source_definition_id=RECOVERY,
        source_actor_id=owner, target_id=aid, applied_sequence=0,
        expires_on='UNTIL_REMOVED', data=data).model_dump_json(exclude_none=True)


def travel_hearth(session, owner):
    actor = session.state['actors'].get(owner)
    if actor is None or owned_action(actor, HEARTH) is None:
        return None
    held = actor['travel_effects'].get(HEARTH)
    return held if held and session.clock() < held['expires_at'] and held['current_hp'] > 0 else None


def rest_allowed(session, aid, owner):
    from ..gate2_runtime_models import Position
    h = travel_hearth(session, owner)
    return bool(h and recovery_row(session.state['actors'][owner])
                and session.grid.distance_ft(Position.model_validate(session.state['actors'][aid]['position']),
                                             Position.model_validate(h['position'])) <= 15)


@hook('journey_options')
def options(session, aid):
    if session.state['phase'] != 'travel':
        return None
    from ..gate2_runtime_models import Position
    actor = session.state['actors'][aid]
    out = []
    if not actor['incapacitated'] and owned_action(actor, HEARTH) and actor['resources'].get('resource:core.qi', 0):
        # Offer every recipient subset the command accepts. The owner is not implicitly
        # protected; they may choose any combination of journey creatures.
        origin = Position.model_validate(actor['position'])
        ids = list(session.state['actors'])
        guests = [list(group) for size in range(len(ids) + 1)
                  for group in combinations(ids, size)]
        for x in range(session.grid.width):
            for y in range(session.grid.height):
                pos = Position(x=x, y=y)
                if session.grid.distance_ft(pos, origin) > 30 or not session.grid.placement_legal(pos, occupied_cells=set()):
                    continue
                cell = {'x': x, 'y': y}   # ground height stays implicit, as in Journey.adjacent
                for recipients in guests:
                    names = ' and '.join(session.state['actors'][g]['name'] for g in recipients[1:])
                    who = f"with {names}" if names else "alone"
                    out.append({'id': 'hearth_kindle:' + json.dumps({'position': cell, 'recipients': recipients}, sort_keys=True),
                        'kind': 'hearth_kindle', 'auto_select': 0, 'payload': {'position': cell, 'recipients': recipients},
                        'label': f"{actor['name']}: Kindled Hearth at ({x},{y}) {who} — Action, 1 Qi; create one flame for 8 hours, protecting chosen guests within 15 feet."})
    if used(actor):
        return out
    for owner in session.state['actors']:
        if rest_allowed(session, aid, owner):
            amount = 2 * int(recovery_row(session.state['actors'][owner])['numbers']['pb'])
            for benefit in available(actor):
                labels = {'hp': f'regain {amount} additional Hit Points', 'temp_hp': f'gain {amount} Temporary Hit Points',
                          'fear': 'Advantage on your next save against Frightened through the next scene',
                          'exhaustion': 'end one level of travel or environmental Exhaustion'}
                out.append({'id': 'hearth_rest:' + owner + ':' + benefit, 'kind': 'hearth_short_rest',
                    'auto_select': 0, 'payload': {'owner_id': owner, 'benefit': benefit},
                    'label': f"{actor['name']}: Homefire Recovery — finish a 1-hour Short Rest in the Hearth aura and {labels.get(benefit, 'end one ordinary environmental penalty')}; once per Long Rest."})
    return out


@hook('journey_command')
def command(session, aid, kind, payload):
    from ..journey import require
    from ..gate2_runtime_models import Position
    actor = session.state['actors'][aid]
    if kind == 'hearth_kindle':
        action = owned_action(actor, HEARTH)
        require(action is not None and not actor['incapacitated'], 'Kindled Hearth requires its owned ability.')
        require(set(payload) == {'position', 'recipients'} and isinstance(payload['recipients'], list)
                and all(type(i) is str and i in session.state['actors'] for i in payload['recipients']),
                'Kindled Hearth needs a location and chosen guests.')
        pos = Position.model_validate(payload['position'])
        require(session.grid.distance_ft(pos, Position.model_validate(actor['position'])) <= 30
                and session.grid.placement_legal(pos, occupied_cells=set()), 'Place the Hearth within 30 feet in an open square.')
        require(actor['resources'].get('resource:core.qi', 0) >= 1, 'Kindled Hearth costs 1 Qi.')
        numbers = action['parameters']['typed']['numbers']
        actor['resources']['resource:core.qi'] -= 1
        session.tick(6)
        actor['travel_effects'][HEARTH] = {'position': pos.model_dump(mode='json'),
            'recipients': list(dict.fromkeys(payload['recipients'])), 'expires_at': session.state['seconds'] + 28800,
            'current_hp': 3 * int(numbers['cl']), 'maximum_hp': 3 * int(numbers['cl']), 'ac': 13}
        session.emit('HEARTH_KINDLED', aid, source=HEARTH, economy='ACTION', qi_cost=1,
            text=f"{actor['name']} spends 1 Qi and an Action to kindle one Hearth for 8 hours.")
        return True
    if kind != 'hearth_short_rest':
        return None
    require(set(payload) == {'owner_id', 'benefit'} and type(payload['owner_id']) is str
            and type(payload['benefit']) is str, 'Choose a Hearth and one Homefire Recovery benefit.')
    owner, benefit = payload['owner_id'], payload['benefit']
    require(not used(actor), 'Homefire Recovery is available once per long rest.')
    require(not actor['incapacitated'] and rest_allowed(session, aid, owner),
            'Finish the Short Rest inside an active Homefire Recovery aura.')
    require(benefit in available(actor), 'No eligible Exhaustion level or ordinary environmental penalty for this benefit.')
    session.tick(3600)
    require(rest_allowed(session, aid, owner), 'The Hearth expired before this Short Rest finished.')
    pb = int(recovery_row(session.state['actors'][owner])['numbers']['pb'])
    held = snapshot(actor)
    if benefit == 'hp':
        held['current_hp'] = min(held['maximum_hp'], held['current_hp'] + 2 * pb)
    elif benefit == 'temp_hp':
        held['temporary_hp'] = max(held['temporary_hp'], 2 * pb)
    elif benefit == 'fear':
        put_condition(actor, aid, owner, FEAR, {'remaining_scenes': 2,
            'label': 'Homefire Recovery: Advantage on your next save against Frightened through the next scene'})
    elif benefit == 'exhaustion':
        causes = journey_causes(actor)
        causes.pop(next(i for i, c in enumerate(causes) if c in CAUSES))
        actor['exhaustion'] -= 1
        held['conditions'] = {k: raw for k, raw in held['conditions'].items()
                              if json.loads(raw)['condition_id'] != 'condition:typed.exhaustion'}
        if causes:
            put_condition(actor, aid, owner, 'condition:typed.exhaustion',
                          {'level': len(causes), 'speed_delta': -5 * len(causes), 'causes': causes})
    else:
        held['conditions'].pop(benefit.removeprefix('penalty:'))
    put_condition(actor, aid, owner, USED, {'label': 'Homefire Recovery received; available again after your Long Rest'})
    session.emit('HOMEFIRE_RECOVERY', aid, source=RECOVERY, owner_id=owner, benefit=benefit,
                 text=f"{actor['name']} receives one Homefire Recovery benefit after a Short Rest; once per Long Rest.")
    return True


@hook('effect_removal_allowed')
def keep_usage_receipt(engine, holder, kind, row, source):
    # A usage allowance is not a condition that a dispel can recharge.
    if kind == 'condition' and row.condition_id == USED:
        return False


@hook('journey_rest')
def rested(session, aid):
    actor = session.state['actors'][aid]
    held = actor.get('encounter_snapshot')
    if held:
        held['conditions'] = {k: raw for k, raw in held['conditions'].items()
                              if json.loads(raw)['condition_id'] != USED}


def combat_available(engine, subject):
    from .forged_exhaustion import level, locked_level
    from .exhaustion_sources import causes
    options = ['hp', 'temp_hp', 'fear']
    if level(subject) > locked_level(engine, subject) and any(
            c in CAUSES for c in causes(subject.conditions.values(), level(subject))):
        options.append('exhaustion')
    options += ['penalty:' + c.instance_id for c in subject.conditions.values() if penalty(c.data)]
    return options


def receive(ctx, subject):
    """Shared short-rest and Welcome consumer; returns whether a benefit resolved."""
    if any(c.condition_id == USED for c in subject.conditions.values()):
        return False
    from .needle import ask, CHOICE, checkpoint_id
    from ..typed_executor import run_effects
    from .forged_exhaustion import level, set_level
    from .exhaustion_sources import causes
    from .riders_shared import remove_benefit_condition
    pb = int(ctx.numbers['pb'])
    choices = combat_available(ctx.engine, subject)
    labels = {'hp': f'Regain {2 * pb} Hit Points', 'temp_hp': f'Gain {2 * pb} Temporary Hit Points',
        'fear': 'Advantage on your next save against Frightened before the end of the next scene',
        'exhaustion': 'End one level of travel or environmental Exhaustion'}
    for c in subject.conditions.values():
        if 'penalty:' + c.instance_id in choices:
            labels['penalty:' + c.instance_id] = 'End ' + str(c.data.get('label') or 'one ordinary environmental penalty')
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'homefire_recovery', subject.entity_id),
        subject, CHOICE + 'homefire_recovery', choices, labels=labels, allow_decline=True,
        feature_id=RECOVERY, name='Homefire Recovery', preferred=['hp' if subject.current_hp < subject.maximum_hp else 'temp_hp'],
        prompt=f"Homefire Recovery: {subject.display_name} may choose one free recovery benefit from {ctx.actor.display_name}'s sanctuary; once per Long Rest.")
    if not selected:
        return False
    benefit = selected[0]
    target_ctx = replace(ctx, target=subject, targets=[subject])
    if benefit in ('hp', 'temp_hp'):
        run_effects(target_ctx, [{'type': 'heal' if benefit == 'hp' else 'temp_hp',
                                 'applies_to': 'target', 'formula': 'double_pb'}])
    elif benefit == 'exhaustion':
        held = causes(subject.conditions.values(), level(subject))
        held.pop(next(i for i, c in enumerate(held) if c in CAUSES))
        set_level(ctx.engine, subject, level(subject) - 1, ctx.source, causes=held)
    elif benefit == 'fear':
        ctx.engine._apply_condition(subject, FEAR, RECOVERY, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'remaining_scenes': 2, 'label': 'Homefire Recovery: Advantage on your next save against Frightened through the next scene'})
    else:
        remove_benefit_condition(ctx.engine, subject, subject.conditions[benefit.removeprefix('penalty:')], ctx.source)
    ctx.engine._apply_condition(subject, USED, RECOVERY, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'label': 'Homefire Recovery received; available again after your Long Rest'})
    ctx.engine._append_event('PASSIVE_TRIGGERED', RECOVERY, actor_id=ctx.actor.entity_id,
        target_ids=(subject.entity_id,), payload={'receipt_kind': 'homefire_recovery', 'benefit': benefit,
            'text': f'Homefire Recovery: {subject.display_name} receives one recovery benefit; available again after a Long Rest.'})
    return True


@hook('save_effects')
def courage(ctx, subject, ability, fail_effects, success_effects, categories):
    from ..typed_executor import _walk_rows
    fear = 'frightened' in {e.get('condition') for e in _walk_rows(fail_effects)}
    if fear and any(c.condition_id == FEAR for c in subject.conditions.values()):
        # This hook is actual save resolution, not a preview. A cancelled
        # activation rolls the condition removal back with the save.
        ctx.engine._remove_condition(subject, FEAR, RECOVERY)
        return {'modes': ['ADVANTAGE']}


@hook('event', nested=True)
def scene_end(engine, event_type, kwargs):
    if event_type != 'MATCH_ENDED':
        return
    from .retained_updates import record_instance_update
    for actor in engine.state.actors.values():
        for c in list(actor.conditions.values()):
            if c.condition_id != FEAR:
                continue
            c.data['remaining_scenes'] -= 1
            if c.data['remaining_scenes'] <= 0:
                engine._remove_condition(actor, FEAR, RECOVERY)
            else:
                record_instance_update(engine, actor, 'condition', c.instance_id, c)


def fact_models(session, subject, kind, value):
    """Validate GM classification against an exact held native condition."""
    from ..journey import require
    require(isinstance(value, dict) and set(value) == {'condition_instance_id', 'cause'},
            'Classify one existing condition and its ordinary environmental cause.')
    require(type(value['condition_instance_id']) is str, 'Name an exact current condition.')
    rows = (session.state['actors'][subject].get('encounter_snapshot') or {}).get('conditions', {})
    raw = rows.get(value['condition_instance_id'])
    require(raw is not None, 'The environmental condition no longer exists.')
    row = json.loads(raw)
    if kind == 'exhaustion_cause':
        require(row['condition_id'] == 'condition:typed.exhaustion'
                and type(value['cause']) is list and len(value['cause']) == int(row['data']['level'])
                and all(type(c) is str and c in CAUSES | {'unknown'} for c in value['cause']),
                'Classify each current Exhaustion level without adding, curing or replacing levels.')
        require(not row['data'].get('scene_locked_levels'), 'Protected Exhaustion cannot be reclassified as environmental.')
    else:
        require(type(value['cause']) is str and value['cause'] in PENALTIES
                and row['condition_id'] not in (USED, FEAR, 'condition:typed.exhaustion'),
                'Choose cold, rain, smoke, altitude, poor shelter or damp for an actual ordinary penalty.')
    return row


@hook('combat_fact_admission_allowed')
def fact_allowed(session, source, subject, kind):
    if source == RECOVERY and kind in ('ordinary_environmental_penalty', 'exhaustion_cause'):
        return True if any(recovery_row(a) for a in session.state['actors'].values()) else None


@hook('fact_admission_schema')
def fact_schema(session, source, subject, kind):
    if source != RECOVERY or kind not in ('ordinary_environmental_penalty', 'exhaustion_cause'):
        return
    if not any(recovery_row(a) for a in session.state['actors'].values()):
        return
    rows = (session.state['actors'][subject].get('encounter_snapshot') or {}).get('conditions', {})
    keys = ['causes'] if kind == 'exhaustion_cause' else ['ordinary_environmental', 'environmental_cause']
    return {'authority': 'table_owner', 'value_type': 'document', 'maximum_seconds': 86400,
        'description': 'Classify the cause of an exact existing ordinary environmental penalty; no condition or level is granted.',
        'combat_condition_data_paths': [[key] for key in keys]}


@hook('fact_admission_validate')
def validate_fact(session, source, subject, kind, value):
    if source == RECOVERY and kind in ('ordinary_environmental_penalty', 'exhaustion_cause'):
        fact_models(session, subject, kind, value)


@hook('fact_admitted')
def classify_fact(session, record):
    if record['source'] != RECOVERY or record['kind'] not in ('ordinary_environmental_penalty', 'exhaustion_cause'):
        return
    from ..journey import require
    from ..fact_consent_admission import digest
    value = record['value']
    require(hasattr(session, 'engine') and record['scope'] == digest([
        session.engine.state.match_id, value['condition_instance_id']]),
        'Bind this classification to the exact fight and condition.')
    row = fact_models(session, record['subject'], record['kind'], value)
    if record['kind'] == 'exhaustion_cause':
        row['data']['causes'] = list(value['cause'])
    else:
        row['data'].update(ordinary_environmental=1, environmental_cause=value['cause'])
    session.state['actors'][record['subject']]['encounter_snapshot']['conditions'][value['condition_instance_id']] = json.dumps(row, sort_keys=True)
