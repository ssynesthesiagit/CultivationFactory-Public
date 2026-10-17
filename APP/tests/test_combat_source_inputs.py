"""Native source-input transport guards, not ability-delivery certification.

Test-only declaration kinds use a genuinely acquired Spirit packet. They grant
no mechanic: production consumers must publish their own source/value schema.
"""
import json

import pytest

from combat import ext
from combat.fact_consent_admission import combat_records, digest
from combat.gate5_service import CombatService
from combat.source_inputs import binding, intent_for
from tests.h1_support import ROOT
from tests.test_mgr_t14_spiritual_state import (
    game as spirit_game, spirit_acquisition, WINGS as BOLT, A as LEFT, B as RIGHT, turn,
)


def native_fight(tmp_path, monkeypatch):
    """Reuse the cohort's public Path/Subpath acquisition, never seeded ownership."""
    factory, table, mid = spirit_game(tmp_path, monkeypatch, [BOLT])
    return factory(), table, mid


@ext.hook('fact_admission_schema')
def native_test_schema(context, source, subject, kind):
    if source != BOLT or kind not in ('native_test_world', 'native_test_consent'):
        return None
    if not getattr(context, 'is_combat_fact_context', False):
        return None
    engine = context.engine
    actor = engine.state.actors.get(subject)
    if actor is None or not any((engine.action_catalog[aid].parameters.get('typed') or {}).get('source') == BOLT
                                for aid in actor.action_ids if aid in engine.action_catalog):
        return None
    return {'value_type': 'text', 'maximum_seconds': 60, 'combat': True, 'validate_value': True,
        'authority': 'table_owner' if kind == 'native_test_world' else 'subject',
        'description': 'Native transport regression input, without an ability effect.'}


@ext.hook('fact_admission_value')
def native_test_value(context, payload):
    if payload.get('source') != BOLT or payload.get('kind') not in ('native_test_world', 'native_test_consent'):
        return None
    return payload.get('scope') == 'native-test:reference' and payload.get('value') == 'named reference'


def payload(engine, *, kind='native_test_world', readers=(), lifetime=60):
    return {'source': BOLT, 'subject': LEFT, 'kind': kind, 'scope': 'native-test:reference',
        'value': 'named reference', 'expires_at': (engine.state.round_number - 1) * 6 + lifetime,
        'readers': list(readers)}


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session


def test_native_world_input_preserves_economy_privacy_and_cold_replay(tmp_path, monkeypatch):
    service, table, mid = native_fight(tmp_path, monkeypatch)
    before = cold(tmp_path, mid).engine
    doc = payload(before)
    result = service.declare_combat_world_fact(mid, state_version=before.state.state_version, payload=doc)
    after = cold(tmp_path, mid).engine
    rows = combat_records(after, after.state.actors[LEFT], source=BOLT)
    assert len(rows) == 1 and rows[0]['receipt_id'] == result['receipt_id']
    assert rows[0]['authority'] == 'table_owner'
    assert rows[0]['receipt_id'] == digest({k: v for k, v in rows[0].items() if k != 'receipt_id'})
    assert not combat_records(after, after.state.actors[RIGHT], source=BOLT)
    assert doc['value'] not in json.dumps(table.state(mid, fog=True, fog_actor_ids=(RIGHT,), include_menu=False))
    assert after.state.roll_counter == before.state.roll_counter
    assert after.state.current_actor_id == before.state.current_actor_id
    for aid, actor in before.state.actors.items():
        final = after.state.actors[aid]
        for key in ('resources', 'action_available', 'bonus_action_available', 'reaction_available', 'position', 'current_hp'):
            assert getattr(final, key) == getattr(actor, key)
    assert after.state.state_version == before.state.state_version + 1


def test_native_actor_and_world_boundaries_reject_wrong_authority_and_unknown_facts(tmp_path, monkeypatch):
    service, _, mid = native_fight(tmp_path, monkeypatch)
    before = cold(tmp_path, mid).engine
    doc = payload(before)
    bad = [lambda: service.declare_combat_actor_fact(mid, LEFT, state_version=before.state.state_version, payload=doc),
           lambda: service.declare_combat_actor_fact(mid, RIGHT, state_version=before.state.state_version, payload=doc),
           lambda: service.declare_combat_world_fact(mid, state_version=before.state.state_version,
               payload={**doc, 'kind': 'native_test_consent'}),
           lambda: service.declare_combat_world_fact(mid, state_version=before.state.state_version,
               payload={**doc, 'kind': 'unregistered_mechanical_event'}),
           lambda: service.declare_combat_world_fact(mid, state_version=before.state.state_version,
               payload={**doc, 'value': 'fabricated damage receipt'}),
           lambda: service.declare_combat_world_fact(mid, state_version=before.state.state_version,
               payload={**doc, 'readers': [{}]})]
    snapshot = before.state.model_dump(mode='json')
    for submit in bad:
        with pytest.raises(ValueError):
            submit()
        assert cold(tmp_path, mid).engine.state.model_dump(mode='json') == snapshot
    result = service.declare_combat_actor_fact(mid, LEFT, state_version=before.state.state_version,
        payload={**doc, 'kind': 'native_test_consent', 'readers': [RIGHT]})
    engine = cold(tmp_path, mid).engine
    assert combat_records(engine, engine.state.actors[RIGHT])[0]['receipt_id'] == result['receipt_id']
    assert combat_records(engine, engine.state.actors[LEFT])[0]['authority'] == LEFT
    service.declare_combat_actor_fact(mid, LEFT, state_version=engine.state.state_version,
        payload={**doc, 'kind': 'native_test_consent', 'readers': []})
    engine = cold(tmp_path, mid).engine
    assert not combat_records(engine, engine.state.actors[RIGHT])
    assert len(combat_records(engine, engine.state.actors[LEFT])) == 1


def test_native_input_expires_at_the_committed_round_boundary(tmp_path, monkeypatch):
    service, table, mid = native_fight(tmp_path, monkeypatch)
    engine = cold(tmp_path, mid).engine
    service.declare_combat_world_fact(mid, state_version=engine.state.state_version,
                                      payload=payload(engine, lifetime=6))
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    engine = cold(tmp_path, mid).engine
    assert not combat_records(engine, engine.state.actors[LEFT])


@pytest.mark.parametrize('gap', ['prepared', 'controller_commit'])
def test_native_source_binding_recovers_exactly_once_without_fabricated_decisions(tmp_path, monkeypatch, gap):
    service, _, mid = native_fight(tmp_path, monkeypatch)
    session = service._load_session(mid)
    policy = binding('table_owner', payload(session.engine))
    intent = intent_for(session.engine, policy, session.engine.state.state_version)
    if gap == 'prepared':
        def interrupt(stage, info):
            if stage == 'after_prepare_flush':
                raise RuntimeError('simulated stopped writer')
        with pytest.raises(RuntimeError, match='simulated stopped writer'):
            session.submit_intent(intent, primary_decision_record=None, reaction_provider=None,
                                  settings_binding=policy, failure_injector=interrupt)
    else:
        session.submit_intent(intent, primary_decision_record=None, reaction_provider=None, settings_binding=policy)
        path = session.controller_journal_path
        rows = path.read_text().splitlines()
        assert json.loads(rows[-1])['record_type'] == 'CONTROLLER_COMMIT'
        path.write_text('\n'.join(rows[:-1]) + '\n')
    recovered = cold(tmp_path, mid)
    actor = recovered.engine.state.actors[LEFT]
    assert len(combat_records(recovered.engine, actor)) == 1
    assert recovered.verify()['controller_open_transactions'] == []
    assert all(not row.get('reaction_decision_records') for row in
               map(json.loads, recovered.controller_journal_path.read_text().splitlines()))
