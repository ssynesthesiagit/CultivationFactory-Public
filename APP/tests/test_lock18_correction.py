"""Correction retains the attack's die, damage and table transaction."""
import pytest
from combat import typed_executor
from combat.ext.seven_star_correction import FEATURE
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as table_helpers
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, HOLD, on_hold
from tests.h1_support import ROOT

POOL = 'resource:foundation.star_intent'


def fight(monkeypatch, tmp_path, *, marked=True, resource=1, natural=3,
          foe_talents=(), key_score=None, setup=None):
    original = table_helpers.sheet
    def sheet(mids, **kwargs):
        if FEATURE in mids and key_score is not None:
            kwargs['score'] = key_score
        result = original(mids or list(foe_talents), **kwargs)
        if FEATURE in mids:
            result['foundation']['stage'] = 'Awakened'
            result['foundation']['resource'] = {'name': 'Star Intent', 'resource_id': 'star_intent',
                                                'maximum': 1, 'current': resource}
        return result
    monkeypatch.setattr(table_helpers, 'sheet', sheet)
    svc, table, mid = table_helpers.table_fight(tmp_path, [FEATURE, 'SOURCE_BASE_SOURCE_PULSE'], ask=True)
    def mark(engine):
        if marked:
            target = engine.state.actors[RIGHT]
            engine._apply_condition(target, typed_executor.mark_condition_id('Star Mark', LEFT),
                'test:mark', LEFT, expires_on='UNTIL_REMOVED')
        if setup is not None:
            setup(engine)
    on_hold(monkeypatch, mark)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    install(monkeypatch, 'd20_result', lambda e, r, i:
            {'source_id': 'test:die', 'operation': 'replace', 'natural_result': natural}
            if r.reason.startswith('ATTACK:') else None)
    state = table.state(mid)
    group = next(g for g in state['menu']['actions'] if g['label'] == 'Source Pulse')
    return svc, table, mid, state, group['options'][0]['candidate_id']


def submit(table, mid, state, cid, answers=()):
    return table.act(mid, cid, state['menu']['decision_id'], state['menu']['state_version'],
                     state['last_sequence'], list(answers))


@pytest.mark.parametrize('use', [True, False])
def test_actual_table_attack_corrects_once_and_reloads(monkeypatch, tmp_path, use):
    svc, table, mid, state, cid = fight(monkeypatch, tmp_path)
    before = svc._load_session(mid).engine.state.model_dump(mode='json')
    result = submit(table, mid, state, cid)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['reaction'] == 'Seven-Star Correction'
    assert all(word in prompt['moment'] for word in ('Source Pulse', 'Right', '1 Star Intent', 'no action'))
    assert svc._load_session(mid).engine.state.model_dump(mode='json') == before
    answer = {**prompt['context'], 'selection': 'USE' if use else 'DECLINE',
              'option_ids': ['correct'] if use else []}
    result = submit(table, mid, state, cid, [answer])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    events = [e for e in loaded.engine.events if e.sequence > state['last_sequence']]
    attacks = [e for e in events if e.event_type == 'ATTACK_ROLLED']
    assert len(attacks) == 1 and not attacks[0].payload['provisional_hit']
    corrections = [e for e in events if e.payload.get('attack_correction')]
    damage = [e for e in events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == attacks[0].source_definition_id]
    assert len(corrections) == len(damage) == int(use)
    if use:
        assert corrections[0].payload['roll_id'] == attacks[0].payload['roll_id']
        assert damage[0].payload['combined_total'] == damage[0].payload['total'] + 4
        assert any(e.event_type == 'DAMAGE_COMMITTED' and e.payload['damage_type'] == 'RADIANT' for e in events)
    spent = [e for e in events if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == POOL]
    assert len(spent) == int(use)
    if use:
        assert spent[0].payload['amount'] == 1 and spent[0].sequence < damage[0].sequence
    # The already-existing generation rule can refill Star Intent after the hit.
    assert loaded.verify()['status'] == 'PASS'


@pytest.mark.parametrize('kwargs', [{'marked': False}, {'resource': 0}, {'natural': 1}, {'natural': 20}])
def test_correction_inert_without_eligible_miss(monkeypatch, tmp_path, kwargs):
    svc, table, mid, state, cid = fight(monkeypatch, tmp_path, **kwargs)
    assert submit(table, mid, state, cid)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not any(e.payload.get('attack_correction') for e in loaded.engine.events)
    assert loaded.verify()['status'] == 'PASS'


@pytest.mark.parametrize('defense', ['ac', 'veto'])
def test_general_checkpoint_preserves_hit_defenses_without_a_provider(monkeypatch, defense):
    from combat import typed_reactions
    from tests.h1_support import duel, attack, script, ME, FOE
    engine = duel([])
    engine.typed_actor_ids.add(FOE)
    monkeypatch.setattr(typed_reactions, 'on_attack_hit',
                        lambda e, a, t, s, total, natural, ac, **kwargs: (ac + (20 if defense == 'ac' else 0), False))
    script(engine, [10])
    assert not attack(engine, ME, FOE, bonus=5, ac=12)
    assert not any(e.payload.get('attack_correction') for e in engine.events)


def test_corrected_hit_still_runs_defense_and_does_not_spend_twice(monkeypatch):
    from combat import typed_reactions
    from tests.h1_support import duel, attack, script, ME, FOE
    engine = duel([])
    engine.typed_actor_ids.add(FOE)
    calls = []
    def correction(*args):
        calls.append('correction')
        return {'source_id': 'test:correction', 'label': 'Test correction', 'bonus': 5, 'bonus_damage': 4}
    def defense(e, a, t, s, total, natural, ac, **kwargs):
        calls.append('defense')
        assert total == 15
        return ac + 10, False
    install(monkeypatch, 'attack_miss_correction', correction)
    monkeypatch.setattr(typed_reactions, 'on_attack_hit', defense)
    script(engine, [5])
    assert not attack(engine, ME, FOE, bonus=5, ac=12)
    assert calls == ['correction', 'defense']
    assert not any(e.event_type == 'DAMAGE_COMMITTED' for e in engine.events)


def test_forced_miss_does_not_offer_correction(monkeypatch):
    from tests.h1_support import duel, attack, script, ME, FOE
    engine = duel([])
    install(monkeypatch, 'before_attack', lambda *args:
            {'force_miss': True, 'source_id': 'test:ward', 'label': 'Protective ward'})
    def forbidden(*args):
        raise AssertionError('forced misses cannot be corrected')
    install(monkeypatch, 'attack_miss_correction', forbidden)
    script(engine, [10])
    assert not attack(engine, ME, FOE, bonus=5, ac=12)


def test_manual_owner_is_asked_when_attacking_on_another_turn(monkeypatch, tmp_path):
    from combat.typed_executor import Context, block_attack
    svc, table, mid, _, _ = fight(monkeypatch, tmp_path)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert table.state(mid)['menu']['actor_id'] != LEFT
    def strike(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == LEFT and a.display_name == 'Source Pulse')
        typed = action.parameters['typed']
        ctx = Context(engine, actor, action, engine._active_intent, typed, [target], target, {})
        block_attack(ctx, next(e for e in typed['effects'] if e['type'] == 'attack'))
    on_hold(monkeypatch, strike)
    state = table.state(mid)
    cid = next(g['options'][0]['candidate_id'] for g in state['menu']['actions']
               if g['source_definition_id'] == HOLD)
    before = svc._load_session(mid).engine.state.model_dump(mode='json')
    result = submit(table, mid, state, cid)
    assert result['status'] == 'REACTION_REQUIRED'
    assert result['reaction']['reactor'] == 'Left'
    assert result['reaction']['reaction'] == 'Seven-Star Correction'
    assert svc._load_session(mid).engine.state.model_dump(mode='json') == before
    answer = {**result['reaction']['context'], 'selection': 'USE', 'option_ids': ['correct']}
    assert submit(table, mid, state, cid, [answer])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.payload.get('attack_correction') for e in loaded.engine.events)
    assert loaded.verify()['status'] == 'PASS'


def test_ai_owner_corrects_without_a_player_prompt(monkeypatch, tmp_path):
    svc, table, mid, _, _ = fight(monkeypatch, tmp_path)
    svc.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, 0, [])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.payload.get('attack_correction') for e in loaded.engine.events)
    assert loaded.verify()['status'] == 'PASS'
