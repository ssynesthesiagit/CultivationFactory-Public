"""Owner-contract integration through native acquisition and table world input."""
import pytest

from tests.test_returning_heaven_native import (
    OWNER, ALLY, FOE, P, M, IRON, start, move, strike, checked, settle, turn,
)
from tests.hunt12_support import hit_dice

AUTHORITY = 'system:body_modes_scene_resources'


def declare_suppression(combat, table, mid, value, *, subject=OWNER):
    engine = combat._load_session(mid).engine
    return table.world_fact(mid, engine.state.state_version, {
        'source': AUTHORITY, 'subject': subject, 'kind': 'cultivation_suppression',
        'scope': 'native-momentum-seal',
        'value': {'source_rule': 'The declared Body seal suppresses this recorded scope.',
                  'source_cl': 18, 'system': 'body', **value},
        'expires_at': 3600, 'readers': [],
    }, 'native-momentum-seal')


@pytest.mark.parametrize('effective_cl,expected,maximum', [(2, 2, 2), (11, 3, 4)])
def test_native_suppression_caps_future_momentum_without_erasing_held_points(
        tmp_path, effective_cl, expected, maximum):
    combat, table, mid = start(tmp_path, cl=14)
    move(combat, table, mid, 7)
    assert checked(tmp_path, mid).state.actors[OWNER].resources[M] == 2
    declare_suppression(combat, table, mid, {'effective_cl': effective_cl})
    engine = checked(tmp_path, mid)
    from combat.ext.subpath_pools import maximum as pool_maximum
    assert engine.state.actors[OWNER].resources[M] == 2
    assert pool_maximum(engine, engine.state.actors[OWNER], M) == maximum
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    turn(table, mid, OWNER)
    move(combat, table, mid, 3)
    engine = checked(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[M] == expected
    assert any(e.event_type == 'WORLD_FACT_DECLARED' for e in engine.events)
    from combat.history_feed import concealed_condition_instances
    private = {c.instance_id for c in engine.state.actors[OWNER].conditions.values()
               if c.condition_id in ('condition:world.fact_history', 'condition:typed.cultivation_suppression')}
    assert len(private) == 2
    assert private <= concealed_condition_instances(engine.state.model_dump(mode='json'))


def test_native_suppression_restores_the_base_gather_menu_and_scaling(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = start(tmp_path, cl=14)
    move(combat, table, mid, 7)
    declare_suppression(combat, table, mid, {'effective_cl': 11})
    prompts = settle(table, mid, strike(combat, mid, FOE).candidate_id, choices={
        'choice:needle.gather_and_return': 'ac', 'choice:needle.gather_damage_type': 'force'})
    engine = checked(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.gather_and_return' for p in prompts)
    assert engine.state.actors[OWNER].resources[M] == 1
    assert any(c.condition_id == 'condition:typed.ac_against' for c in engine.state.actors[OWNER].conditions.values())
    assert next(r for r in reversed(engine.rolls) if r.reason == 'Gather and Return').expression.startswith('2d8')


def test_native_named_feature_suppression_keeps_the_other_momentum_procedures(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = start(tmp_path, cl=14)
    move(combat, table, mid, 7)
    declare_suppression(combat, table, mid, {'feature_id': P + 'gather_and_return'})
    prompts = settle(table, mid, strike(combat, mid, FOE).candidate_id, choices={})
    engine = checked(tmp_path, mid)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.gather_and_return' for p in prompts)
    assert engine.state.actors[OWNER].resources[M] == 2
    assert not any(r.reason == 'Gather and Return' for r in engine.rolls)


@pytest.mark.parametrize('suppressed', [False, True])
def test_native_existing_gather_ac_is_dormant_under_its_named_seal(tmp_path, monkeypatch, suppressed):
    hit_dice(monkeypatch)
    combat, table, mid = start(tmp_path, cl=11, foe_features=[IRON])
    move(combat, table, mid, 7)
    settle(table, mid, strike(combat, mid, FOE).candidate_id, choices={
        'choice:needle.gather_and_return': 'ac', 'choice:needle.gather_damage_type': 'force'})
    owner = checked(tmp_path, mid).state.actors[OWNER]
    guard = next(c for c in owner.conditions.values() if c.condition_id == 'condition:typed.ac_against')
    if suppressed:
        declare_suppression(combat, table, mid, {'feature_id': P + 'gather_and_return'})
    from tests.test_lock_choices import install
    install(monkeypatch, 'd20_result', lambda engine, roll, intent: {
        'source_id': 'test:boundary-die', 'operation': 'replace',
        'natural_result': engine.state.actors[OWNER].armor_class - roll.modifier
        if roll.actor_id == FOE else 18})
    turn(table, mid, FOE)
    settle(table, mid, strike(combat, mid, OWNER).candidate_id, choices={
        'choice:needle.fact_admission.momentum_eligibility': 'genuine'})
    engine = checked(tmp_path, mid)
    after = engine.state.actors[OWNER]
    assert (after.current_hp < owner.current_hp) is suppressed
    assert guard.instance_id in after.conditions


def test_native_world_suppression_rejects_an_unowned_subject_atomically(tmp_path):
    from combat.tabletop_service import TabletopError
    combat, table, mid = start(tmp_path, cl=14)
    before = checked(tmp_path, mid)
    with pytest.raises(TabletopError, match='does not admit'):
        declare_suppression(combat, table, mid, {'effective_cl': 2}, subject=FOE)
    after = checked(tmp_path, mid)
    assert [e.model_dump() for e in after.events] == [e.model_dump() for e in before.events]


def test_native_world_suppression_request_is_idempotent_and_rejects_rebinding(tmp_path):
    from combat.tabletop_service import TabletopError
    combat, table, mid = start(tmp_path, cl=14)
    first = declare_suppression(combat, table, mid, {'effective_cl': 11})
    second = declare_suppression(combat, table, mid, {'effective_cl': 11})
    assert first == second
    with pytest.raises(TabletopError, match='identifier belongs'):
        declare_suppression(combat, table, mid, {'effective_cl': 2})
    engine = checked(tmp_path, mid)
    assert len([e for e in engine.events if e.event_type == 'WORLD_FACT_DECLARED']) == 1


def test_native_world_suppression_uses_the_real_journey_clock_and_resumes_without_ledger_conditions(tmp_path):
    from combat.combat_world_facts import records
    combat, table, mid, jid = start(tmp_path, cl=14, journey=True, maximum_rounds=1, precombat_wait=120)
    declare_suppression(combat, table, mid, {'effective_cl': 11})
    engine = checked(tmp_path, mid)
    record = next(r for r in records(engine) if r['source'] == AUTHORITY)
    assert record['created_at'] >= 120
    for _ in range(6):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    assert checked(tmp_path, mid).state.terminal_result is not None
    state = combat.journey_state(jid)
    resumed = combat.journey_resume(jid, state['revision'])
    assert resumed['seconds'] > 120
    held = resumed['actors'][OWNER]['source_states'][AUTHORITY]['sources']
    assert held['cultivation_suppression:native-momentum-seal']['receipt_id'] == record['receipt_id']
    assert 'condition:world.fact_history' not in str(resumed['actors'][OWNER]['encounter_snapshot'])


def test_native_qualified_source_blocks_staged_damage_even_if_the_controller_answers_genuine(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = start(tmp_path, cl=14, foe_features=[IRON],
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':4,'y':6}})
    engine = checked(tmp_path, mid)
    table.world_fact(mid, engine.state.state_version, {
        'source': AUTHORITY, 'subject': OWNER, 'kind': 'qualified_source', 'scope': 'staged-source',
        'value': {'source_rule': 'The table owner records this encounter as staged resource farming.',
                  'source_cl': 18, 'source_actor_id': FOE, 'hostile': 1, 'staged': 1},
        'expires_at': 3600, 'readers': [],
    }, 'native-staged-source')
    before = checked(tmp_path, mid).state.actors[OWNER]
    turn(table, mid, FOE)
    settle(table, mid, strike(combat, mid, OWNER).candidate_id, choices={
        'choice:needle.fact_admission.momentum_eligibility': 'genuine'})
    after = checked(tmp_path, mid).state.actors[OWNER]
    assert after.current_hp == before.current_hp - 1
    assert after.resources[M] == 0
