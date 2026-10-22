"""Cauldron scene continuity and the printed rest/purification caller.

Consumes the shared source_states, native scene-end and elapsed-time contracts.
Only actually committed Cauldron conditions enter this ledger. Reopening a
journey, resting or starting another encounter never resets a scene allowance.
"""
from copy import deepcopy
import json

from . import hook
from . import black_cauldron as C


def state(session, aid):
    return session.state['actors'][aid].get('source_states', {}).get(C.PARENT)


def has_bundle(actor):
    return any(r.get('block') == 'black_cauldron' for r in actor['bundle'].get('typed_passives', []))


@hook('journey_snapshot_actor')
def separate_source_clock(actor, session, aid, engine):
    if not C.owned(engine, actor) and not C.condition(actor, C.STORE):
        return None
    clone = actor.model_copy(deep=True)
    clone.conditions = {key: c for key, c in clone.conditions.items()
                        if not c.condition_id.startswith('condition:typed.black_cauldron_')}
    return clone


@hook('journey_encounter_settled')
def export(session, aid, engine, actor):
    rows = [c.model_dump(mode='json', exclude_none=True) for c in actor.conditions.values()
            if c.condition_id.startswith('condition:typed.black_cauldron_') and c.source_actor_id == aid]
    if not rows and not C.owned(engine, actor):
        return
    session.state['actors'][aid].setdefault('source_states', {})[C.PARENT] = {
        'conditions': [json.dumps(row, sort_keys=True) for row in rows],
        'maximum_qi': int(actor.resource_maximums.get(C.QI, 0))}


@hook('journey_combat_setup')
def setup(session, aid):
    saved = state(session, aid)
    if saved is not None:
        return {'black_cauldron': deepcopy(saved)}


@hook('match_initialize', priority=50)
def import_state(engine):
    changed = False
    for bundle in engine.typed_bundle_documents:
        saved = (bundle.get('journey_setup') or {}).get('black_cauldron')
        actor = engine.state.actors.get(bundle['actor_id'])
        if saved is None or actor is None:
            continue
        from ..gate2_runtime_models import ConditionInstance
        for encoded in saved['conditions']:
            row = ConditionInstance.model_validate(json.loads(encoded))
            if (row.source_actor_id != actor.entity_id or row.target_id != actor.entity_id
                    or not row.condition_id.startswith('condition:typed.black_cauldron_')):
                raise ValueError('Cauldron continuation must retain its original source owner.')
            if row.condition_id == C.LOCK:
                from .effect_durations import holder_next_turn
                row.expires_on = holder_next_turn(actor)
                row.expires_turn_count = None
            actor.conditions[row.instance_id] = row
        if C.QI in actor.resource_maximums:
            actor.resource_maximums[C.QI] = int(saved['maximum_qi'])
            actor.resources[C.QI] = min(actor.resources[C.QI], actor.resource_maximums[C.QI])
        changed = True
    return True if changed else None


@hook('journey_scene_end')
def scene_end(session, previous, current):
    holders = [aid for aid in session.state['actors'] if state(session, aid) is not None]
    if not holders:
        return
    from ..journey_resolution import resolve
    def backlash(engine):
        for aid in holders:
            actor = engine.state.actors[aid]
            entries = C.store(actor)
            C.save_store(engine, actor, [])
            C.save_scene(engine, actor, {})
            for entry in entries:
                C.raw_damage(engine, actor, 1, 6, 'FORCE', C.RESIDUE, unpreventable=True)
    resolve(session, C.RESIDUE, backlash)


@hook('journey_rest')
def long_rest(session, aid):
    saved = state(session, aid)
    if saved is None:
        return
    encoded = []
    for text in saved['conditions']:
        row = json.loads(text)
        if row['condition_id'] == C.RUPTURE:
            row['data']['long_rest'] = 1
        encoded.append(json.dumps(row, sort_keys=True))
    saved['conditions'] = encoded
    recover(session, aid)


def recover(session, aid):
    saved = state(session, aid)
    if saved is None:
        return
    kept = []
    for text in saved['conditions']:
        row = json.loads(text)
        data = row.get('data') or {}
        if row['condition_id'] == C.RUPTURE and data.get('long_rest') and data.get('purification_seconds', 0) >= 3600:
            saved['maximum_qi'] += int(data['penalty'])
            session.emit('CAULDRON_STABILIZED', aid,
                source=C.RESIDUE, text=f"{session.state['actors'][aid]['name']} completes Cauldron purification after a Long Rest; maximum Qi restored, spent Qi unchanged.")
        else:
            kept.append(text)
    saved['conditions'] = kept


@hook('journey_options')
def purification_option(session, aid):
    saved = state(session, aid)
    if (saved is None or session.state['phase'] != 'travel' or session.state['actors'][aid]['incapacitated']
            or not any(json.loads(row)['condition_id'] == C.RUPTURE for row in saved['conditions'])):
        return None
    return [{'id': 'black_cauldron:purify', 'kind': 'black_cauldron_purify', 'payload': {},
             'auto_select': 0, 'label': 'Cauldron Rupture: spend 1 hour purifying or stabilizing the Cauldron; a completed Long Rest is also required to restore maximum Qi.'}]


@hook('journey_command')
def purification(session, aid, kind, payload):
    if kind != 'black_cauldron_purify':
        return None
    from ..journey import require
    require(not payload and bool(purification_option(session, aid)), 'A ruptured Cauldron and one uninterrupted hour are required.')
    session.tick(3600)
    saved = state(session, aid)
    encoded = []
    for text in saved['conditions']:
        row = json.loads(text)
        if row['condition_id'] == C.RUPTURE:
            row['data']['purification_seconds'] = 3600
        encoded.append(json.dumps(row, sort_keys=True))
    saved['conditions'] = encoded
    session.emit('CAULDRON_PURIFICATION_COMPLETED', aid, source=C.RESIDUE, seconds=3600)
    recover(session, aid)
    return True
