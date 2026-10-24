"""Explicit self recipients resolve saves and hearing checks before payment."""
import pytest
from combat import ext, posture
from combat.gate5_service import CombatService
from combat.ext.prone_restraints import RESTRAINT
from tests.h1_support import ROOT
from tests.test_lock8_prone import prone_table, record_setup
from tests.test_lock9_prone_review import commands
from tests.test_hidden_targeting import turn
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act


@pytest.mark.parametrize('failed', [False, True])
def test_explicit_self_kneel_resolves_and_reloads(tmp_path, monkeypatch, failed):
    install(monkeypatch, 'd20_result', lambda e, *args: {'source_id': 'test:save',
        'operation': 'replace', 'natural_result': 1 if failed and e.d20_context().get('kind') == 'save' else 20})
    service, ui, mid, left, right = prone_table(tmp_path)
    record_setup(ui, mid, [left]); turn(ui, mid, left)
    e = service._load_session(mid).engine
    before = e.state.actors[left].resources['resource:core.qi']
    c = next(c for c in commands(e) if c.target_ids == (left,))
    assert ui.act(mid, c.candidate_id, c.decision_id, c.state_version, ui.state(mid)['last_sequence'])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[left]
    assert actor.resources['resource:core.qi'] == before - 4 and not actor.action_available
    saves = [ev for ev in loaded.engine.events if ev.event_type == 'SAVE_ROLLED' and ev.actor_id == left]
    assert len(saves) == 1 and saves[0].payload['success'] is (not failed)
    assert bool(posture.prone_conditions(actor)) is failed
    assert any(c.condition_id == RESTRAINT for c in actor.conditions.values()) is failed
    assert any(c.condition_id == 'condition:typed.reaction_denied' for c in actor.conditions.values()) is (not failed)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_deafened_self_kneel_is_not_offered_and_does_not_spend(tmp_path, monkeypatch):
    service, ui, mid, left, right = prone_table(tmp_path)
    record_setup(ui, mid, [left, right]); turn(ui, mid, left)
    def deafen(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == left:
            engine._apply_condition(engine.state.actors[left], 'condition:typed.deafened', 'test:deaf', right,
                                    expires_on='UNTIL_REMOVED')
    ext.effects(); monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), deafen])
    before = service._load_session(mid).engine.state.actors[left].resources['resource:core.qi']
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not any(c.target_ids == (left,) for c in commands(loaded.engine))
    assert any(c.target_ids == (right,) for c in commands(loaded.engine))
    assert loaded.engine.state.actors[left].resources['resource:core.qi'] == before
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
