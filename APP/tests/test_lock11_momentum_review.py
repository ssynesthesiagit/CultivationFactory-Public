"""Owned Steal Momentum range/perception and Ask-me Table persistence."""
import pytest

from combat import senses
from combat.ext.steal_momentum import FEATURE, FLAG
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.target_knowledge import can_see, located
from tests.h1_support import ROOT
from tests.test_lock8_movement_steps import portable
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import on_hold, HOLD
from tests.r10_fixup_support import answer


@pytest.mark.parametrize('case,use', [('60_out',True), ('60_out',False), ('65_in',True),
                                    ('invisible_sense',True), ('invisible_memory',True)])
def test_momentum_beginning_range_current_perception_and_consent(monkeypatch, tmp_path, case, use):
    start = 15 if case == '60_out' else 16 if case == '65_in' else 6
    destination = 14 if case == '65_in' else start + 2
    expected_prompt = case in {'60_out', 'invisible_sense'}
    combat, table, mid, left, right = portable(tmp_path, 'SAND_BASE_SCOURING_HAND', FEATURE,
        left_at=(start, 6), right_at=(3, 6), dc=1)
    install(monkeypatch, 'd20_result', lambda *args: {'source_id':'test:roll','operation':'replace','natural_result':10})
    def ready(engine):
        mover, reactor = engine.state.actors[left], engine.state.actors[right]
        engine._gain_resource(reactor, 'resource:core.martial_focus', 1, 'test:ready')
        if case.startswith('invisible'):
            engine._apply_condition(mover, 'condition:typed.invisible', 'test:conceal', left, expires_on=None)
            if case == 'invisible_sense':
                engine._apply_condition(reactor, senses.SENSE, 'test:sense', right, expires_on=None,
                                       data={'sense':'tremorsense','range_ft':60})
            assert not can_see(engine, reactor, mover)
            assert located(engine, reactor, mover) is (case == 'invisible_sense')
            assert left in engine.state.observations[reactor.team_id]  # prior location is known even in the negative case
    on_hold(monkeypatch, ready)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    before = engine.state.model_dump(mode='json')
    c = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination == Position(x=destination,y=6))
    sequence = table.state(mid)['last_sequence']
    def send(answers=()):
        return table.act(mid, c.candidate_id, c.decision_id, c.state_version, sequence, list(answers))
    result = send()
    answers = []
    if expected_prompt:
        assert result['status'] == 'REACTION_REQUIRED'
        assert result['reaction']['context']['reaction_source_id'] == 'choice:needle.steal_momentum'
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        answers.append(answer(result['reaction'], 'use', use=use))
        result = send(answers)
        if result['status'] == 'REACTION_REQUIRED':
            # Decline the reactor's follow-up step; no hidden auto-selection.
            answers.append(answer(result['reaction'], use=False))
            result = send(answers)
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    mover, reactor = loaded.engine.state.actors[left], loaded.engine.state.actors[right]
    stopped = expected_prompt and use
    assert mover.position == Position(x=start+1 if stopped else destination, y=6)
    assert mover.movement_remaining_ft == before['actors'][left]['movement_remaining_ft'] - (5 if stopped else 10)
    assert reactor.resources['resource:core.martial_focus'] == (0 if stopped else 1)
    assert reactor.reaction_available is not stopped
    assert (reactor.turn_flags.get(FLAG) == loaded.engine.state.round_number) is stopped
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
