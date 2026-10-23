"""Late correction preserves later consent and actual forced-natural defenses."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.ext.karma_consumers import REVERSAL
from combat.ext.karma_imprints import place, held
from tests.test_lock18_correction import fight, submit, POOL
from tests.test_tabletop_hunt6 import LEFT, RIGHT, PROJECTS
from tests.h1_support import ROOT

ARMOR = 'tianxia.path.qi_cultivation.feature.qi_armor'


def ask_defender(tmp_path):
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(
        PROJECTS['right'], {'mode': 'ask'}, {'opportunity_attack'})


@pytest.mark.parametrize('use_armor', [True, False])
def test_late_correction_resumes_unvisited_qi_armor_consent(monkeypatch, tmp_path, use_armor):
    ask_defender(tmp_path)
    def guard(engine):
        target = engine.state.actors[RIGHT]
        # Domain Armament's existing conditional-AC field, followed by real Qi Armor.
        engine._add_modifier(target, 'test:domain_armament', 'armor_class_vs_ranged',
                             'ADD', 2, 'SELF', expires_on='UNTIL_REMOVED')
    svc, table, mid, state, cid = fight(monkeypatch, tmp_path, natural=7,
        foe_talents=[ARMOR], key_score=10, setup=guard)
    before = svc._load_session(mid).engine.state.model_dump(mode='json')
    result = submit(table, mid, state, cid)
    assert result['status'] == 'REACTION_REQUIRED'
    assert result['reaction']['reaction'] == 'Seven-Star Correction'
    answers = [{**result['reaction']['context'], 'selection': 'USE', 'option_ids': ['correct']}]
    result = submit(table, mid, state, cid, answers)
    assert result['status'] == 'REACTION_REQUIRED'
    assert result['reaction']['reaction'] == 'Qi Armor'
    assert result['reaction']['reactor'] == 'Right'
    assert svc._load_session(mid).engine.state.model_dump(mode='json') == before
    answers.append({**result['reaction']['context'], 'selection': 'USE' if use_armor else 'DECLINE'})
    assert submit(table, mid, state, cid, answers)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    events = [e for e in loaded.engine.events if e.sequence > state['last_sequence']]
    assert sum(e.event_type == 'ATTACK_ROLLED' for e in events) == 1
    assert sum(e.payload.get('attack_correction', False) for e in events) == 1
    assert sum(e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == 'test:domain_armament'
               for e in events) == 1
    assert sum(e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == POOL for e in events) == 1
    assert sum(e.event_type == 'RESOURCE_SPENT' and e.actor_id == RIGHT for e in events) == int(use_armor)
    damage = [e for e in events if e.event_type == 'DAMAGE_ROLLED']
    assert len(damage) == int(not use_armor)
    if damage:
        assert damage[0].payload['combined_total'] == damage[0].payload['total'] + 4


def test_actual_reversal_natural_one_cannot_be_corrected_back_to_a_critical(monkeypatch, tmp_path):
    ask_defender(tmp_path)
    def imprint(engine):
        assert place(engine, engine.state.actors[RIGHT], engine.state.actors[LEFT],
                     'debt', REVERSAL, 'test:reversal')
    svc, table, mid, state, cid = fight(monkeypatch, tmp_path, natural=20,
        foe_talents=[REVERSAL], setup=imprint)
    result = submit(table, mid, state, cid)
    assert result['status'] == 'REACTION_REQUIRED'
    assert result['reaction']['reaction'] == 'Reversal of Due Fortune'
    answer = {**result['reaction']['context'], 'selection': 'USE'}
    assert submit(table, mid, state, cid, [answer])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    events = [e for e in loaded.engine.events if e.sequence > state['last_sequence']]
    assert sum(e.event_type == 'ATTACK_ROLLED' and e.payload.get('natural_result') == 20 for e in events) == 1
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == REVERSAL
               and e.payload.get('natural') == 1 for e in events)
    assert sum(e.event_type == 'RESOURCE_SPENT' and e.actor_id == RIGHT
               and e.payload.get('amount') == 4 for e in events) == 1
    assert not held(loaded.engine.state.actors[LEFT], RIGHT, 'debt')
    assert not any(e.payload.get('attack_correction') or e.event_type == 'DAMAGE_ROLLED' for e in events)
    assert loaded.engine.state.actors[LEFT].resources[POOL] == 1


def test_paid_generic_correction_reaches_ally_defense_once_outside_payment_scope(monkeypatch):
    from combat import typed_reactions as tr
    from combat.technique_interception import frame
    from tests.h1_support import duel, ME, FOE, ALLY
    engine = duel([], ally_mids=[])
    target, attacker, ally = (engine.state.actors[x] for x in (ME, FOE, ALLY))
    qi = 'resource:core.qi'
    rows = {
        (ME, 'hit'): [{'feature_id': 'test:first', 'name': 'First guard', 'block': 'generic',
            'kind': 'hit', 'costs': [{'resource_id': qi, 'amount': 1}],
            'effects': [{'type': 'ac_bonus', 'flat': 2}], 'numbers': {'cl': 10, 'pb': 4}}],
        (ALLY, 'ally_hit'): [{'feature_id': 'test:second', 'name': 'Ally guard', 'block': 'generic',
            'kind': 'ally_hit', 'costs': [{'resource_id': qi, 'amount': 1}],
            'effects': [{'type': 'ac_bonus', 'flat': 4}], 'numbers': {'cl': 10, 'pb': 4}}],
    }
    original = tr._ordered_generic_rows
    monkeypatch.setattr(tr, '_ordered_generic_rows',
                        lambda e, who, kind: rows.get((who, kind), original(e, who, kind)))
    calls = []
    def correction(total, ac):
        assert not frame(engine, ME, 'test:first')
        assert not frame(engine, ALLY, 'test:second')
        calls.append((total, ac))
        return total + 4 if len(calls) == 1 else total
    before = target.resources[qi], ally.resources[qi]
    assert tr.on_attack_hit(engine, attacker, target, {}, 15, 10, 14,
                            correct_ac_miss=correction) == (20, False)
    assert calls == [(15, 16), (19, 20)]
    assert (target.resources[qi], ally.resources[qi]) == (before[0] - 1, before[1] - 1)
    assert [e.source_definition_id for e in engine.events if e.event_type == 'REACTION_RESOLVED'
            and e.source_definition_id in ('test:first', 'test:second')] == ['test:first', 'test:second']
