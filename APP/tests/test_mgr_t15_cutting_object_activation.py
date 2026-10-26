"""Cutting Current objects retain the native typed-object activation lifecycle."""
import hashlib
import pytest
from combat import ext
from tests.test_mgr_t15_close_cutting_current import (
    APP, CUTTING, OWNER, FOE, native, cold,
)

# Literal dynamic feature-block dependencies for the public safe exporter.
DEPENDENCIES = ('combat/rules/feature_blocks.d/mgr_t14_ink_base_actions.json',)
COUNTER = 'TAL_QIWEAVING_COUNTERWEAVE'
REACTION = 'reaction:typed.' + COUNTER


def counter_reading(record):
    """The reviewed reading of Counterweave's own current printed trigger, self-derived.

    The public export clears authority/typed_mechanics/trigger_readings.jsonl, so a test that
    reads that pairing out of repo data is red there for a reason that has nothing to do with
    this branch. reaction_triggers.readings_for keys a reading on the hash of the mechanic's own
    trigger text, so the row is built from the record in hand.
    """
    trigger = (record.get('activation') or {}).get('trigger') or ''
    return {'mechanic_id': COUNTER, 'text_sha256': hashlib.sha256(trigger.encode('utf-8')).hexdigest(),
            'reading': 'A creature within range uses a technique', 'status': 'auto',
            'events': [{'kind': 'technique_used'}]}


def fixture(tmp_path, delivery, monkeypatch, *, counter=False):
    for path in DEPENDENCIES:
        assert (APP / path).is_file()
    mids, name = ([CUTTING], 'Water Lash') if delivery == 'cutting' else (['INK_BASE_INK_LASH'], 'Ink Lash')
    combat, table, mid = native(tmp_path, material='rope', owner_mids=mids,
        foe_mids=[COUNTER] if counter else None, cl=5, dc=1)
    candidates = [c for c in combat._load_session(mid).engine.legal_candidates()
                  if c.display_name == name and 'object:map.81' in c.target_ids]
    assert len(candidates) == 1
    if counter:
        from combat import reaction_triggers
        from combat.factory_compiler import compile_character
        from tests.h1_support import mechanics
        raw = combat._factory_owner_sheet('bbbbbbbb')
        assert COUNTER in raw['spheres_and_talents']['learned_talent_record_ids'], raw['spheres_and_talents']
        record = mechanics()[COUNTER]
        assert record['activation']['economy'] == 'reaction', record['activation']
        row = counter_reading(record)
        monkeypatch.setattr(reaction_triggers, '_reading_rows',
                            lambda: {(row['mechanic_id'], row['text_sha256']): row})
        readings = reaction_triggers.readings_for(record)
        assert readings is not None, 'Counterweave needs a reading of its current printed trigger'
        assert [match.kind for match in readings] == ['technique_used'], readings
        compiled = compile_character(raw, actor_id=FOE, reaction_plan={'ask': True})
        rows = [r for r in compiled['typed_reactions'] if r.get('feature_id') == COUNTER]
        assert rows, compiled['diagnostics']
        # The counter answers the reading's event, not the phrase classifier's guess.
        assert [r.get('kind') for r in rows] == ['technique_used'], rows
    return combat, table, mid, candidates[0]


def send(table, mid, candidate, answers=()):
    s = table.state(mid)
    return table.act(mid, candidate.candidate_id, s['menu']['decision_id'],
                     s['menu']['state_version'], s['last_sequence'], list(answers))


def finish(table, mid, candidate, answers=()):
    answers = list(answers)
    for _ in range(10):
        result = send(table, mid, candidate, answers)
        if result['status'] == 'COMMITTED':
            return
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        choice = p.get('choice') or {}
        required = choice and not choice.get('allow_decline', True)
        answers.append({**p['context'], 'selection': 'USE' if required else 'DECLINE',
                        'option_ids': [choice['options'][0]['id']] if required else []})
    raise AssertionError('unresolved object activation')


@pytest.mark.parametrize('delivery', ['cutting', 'generic'])
@pytest.mark.parametrize('use', [False, True])
def test_native_object_counterweave_matches_generic_and_cold_replays(tmp_path, monkeypatch, delivery, use):
    _, table, mid, candidate = fixture(tmp_path, delivery, monkeypatch, counter=True)
    _, _, before = cold(tmp_path, mid)
    rows = before.typed_reaction_rows[FOE]
    assert any(r.get('feature_id') == COUNTER and r.get('kind') == 'technique_used' for r in rows), rows
    assert before.state.actors[FOE].reaction_available
    assert before.state.actors[FOE].resources['resource:core.martial_focus'] == 1
    saved = before.state.model_dump(mode='json')
    first = len(before.events)
    def resolution_enabled(ctx):
        return True if ctx.action.source_definition_id == candidate.source_definition_id else None
    def resolved(ctx, receipt):
        if ctx.action.source_definition_id == candidate.source_definition_id:
            ctx.engine._append_event('PASSIVE_TRIGGERED', 'test:completion_subscriber',
                actor_id=ctx.actor.entity_id, payload={'completion_subscriber': True})
    monkeypatch.setitem(ext._HOOKS, 'technique_resolution_enabled',
                       [*ext._HOOKS['technique_resolution_enabled'], resolution_enabled])
    monkeypatch.setitem(ext._HOOKS, 'technique_resolved',
                       [*ext._HOOKS['technique_resolved'], resolved])
    result = send(table, mid, candidate)
    assert result['status'] == 'REACTION_REQUIRED', result
    p = result['reaction']
    assert p['context']['reaction_source_id'] == REACTION, (p, rows, before.state.actors[FOE])
    assert p['context']['reactor_id'] == FOE
    assert p['reaction'] == 'Counterweave'
    assert candidate.display_name in p['moment']
    assert cold(tmp_path, mid)[2].state.model_dump(mode='json') == saved
    finish(table, mid, candidate, [{**p['context'], 'selection': 'USE' if use else 'DECLINE'}])
    _, _, engine = cold(tmp_path, mid)
    events = engine.events[first:]
    assert not any(e.source_definition_id == 'test:completion_subscriber' for e in events)
    assert not engine.state.actors[OWNER].action_available
    assert engine.state.actors[FOE].reaction_available is not use
    assert (engine.state.actors[FOE].resources['resource:core.qi']
            < before.state.actors[FOE].resources['resource:core.qi']) is use
    counters = [e for e in events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == COUNTER]
    assert bool(counters) is use
    attacks = [e for e in events if e.event_type == 'ATTACK_ROLLED']
    assert bool(attacks) is not use
    obj = engine.state.objects['object:map.81']
    if use:
        assert obj.current_hp == before.state.objects[obj.object_id].current_hp
        assert not any(e.event_type in {'DAMAGE_ROLLED', 'GM_RIDER'}
                       and e.source_definition_id == candidate.source_definition_id for e in events)
        assert not any(e.payload.get('scouring_erosion') for e in events)
    else:
        attack = attacks[0]
        hit = attack.payload['provisional_hit']
        assert (obj.current_hp < before.state.objects[obj.object_id].current_hp) is hit


@pytest.mark.parametrize('delivery', ['cutting', 'generic'])
@pytest.mark.parametrize('veto', [False, True])
def test_native_object_accept_start_veto_and_completion_match_generic(tmp_path, monkeypatch, delivery, veto):
    _, table, mid, candidate = fixture(tmp_path, delivery, monkeypatch)
    _, _, before = cold(tmp_path, mid)
    first = len(before.events)

    # Synthetic subscribers exercise the documented lifecycle contract, not
    # patched engine methods or an invented ability. Durable events prove order
    # after table commit and mechanical cold replay.
    def record(engine, actor, action, stage):
        if action.source_definition_id == candidate.source_definition_id:
            engine._append_event('PASSIVE_TRIGGERED', action.source_definition_id,
                actor_id=actor.entity_id, payload={'activation_probe': stage})
    def accepted(engine, actor, action):
        record(engine, actor, action, 'accepted')
    def start(engine, actor, action):
        record(engine, actor, action, 'start')
        return True if veto and action.source_definition_id == candidate.source_definition_id else None
    def used(ctx):
        record(ctx.engine, ctx.actor, ctx.action, 'used')
    def resolution_enabled(ctx):
        return True if ctx.action.source_definition_id == candidate.source_definition_id else None
    def resolved(ctx, receipt):
        if ctx.action.source_definition_id == candidate.source_definition_id:
            ctx.engine._append_event('PASSIVE_TRIGGERED', 'test:completion_subscriber',
                actor_id=ctx.actor.entity_id,
                payload={'activation_probe': 'resolved', 'source': ctx.action.source_definition_id})
    for point, callback in [('technique_accepted', accepted), ('technique_start', start),
                             ('technique_used', used), ('technique_resolution_enabled', resolution_enabled),
                             ('technique_resolved', resolved)]:
        monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS[point], callback])

    finish(table, mid, candidate)
    _, _, engine = cold(tmp_path, mid)
    events = engine.events[first:]
    stages = [e.payload['activation_probe'] for e in events if 'activation_probe' in e.payload]
    assert stages == (['accepted', 'start'] if veto else ['accepted', 'start', 'used', 'resolved'])
    resolutions = [e for e in events if e.source_definition_id == 'test:completion_subscriber']
    assert bool(resolutions) is not veto
    assert not engine.state.actors[OWNER].action_available
    attacks = [i for i, e in enumerate(events) if e.event_type == 'ATTACK_ROLLED']
    assert bool(attacks) is not veto
    if veto:
        assert engine.state.objects['object:map.81'].current_hp == 100
        assert not any(e.payload.get('scouring_erosion') for e in events)
    else:
        accepted_at, start_at, used_at = [i for i, e in enumerate(events) if 'activation_probe' in e.payload]
        assert accepted_at < start_at < attacks[0] < used_at
