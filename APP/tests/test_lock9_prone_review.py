"""Kneel uses the printed creature domain and recorded understanding for AI."""
import pytest
from combat import ext, posture
from combat.ext.prone_restraints import understands
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_lock8_prone import prone_table, record_setup
from tests.test_hidden_targeting import turn
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act


def commands(engine):
    return [c for c in engine.legal_candidates() if c.display_name == 'Imperial Command: Kneel']


@pytest.mark.parametrize('confirm', [False, True])
def test_manual_unknown_understanding_pauses_and_records_only_confirmation(tmp_path, monkeypatch, confirm):
    service, ui, mid, left, right = prone_table(tmp_path)
    record_setup(ui, mid, []); turn(ui, mid, left)
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    c = next(c for c in commands(service._load_session(mid).engine) if c.target_ids == (right,))
    first = ui.act(mid, c.candidate_id, c.decision_id, c.state_version, ui.state(mid)['last_sequence'])
    assert first['status'] == 'REACTION_REQUIRED'
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    result = ui.act(mid, c.candidate_id, c.decision_id, c.state_version, ui.state(mid)['last_sequence'],
        [{**first['reaction']['context'], 'selection': 'USE' if confirm else 'DECLINE', 'option_ids': [right] if confirm else []}])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert understands(loaded.engine.state.actors[right], loaded.engine.state.actors[left]) == confirm
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('confirmed', [False, True])
def test_ai_context_and_service_respect_recorded_understanding(tmp_path, monkeypatch, confirmed):
    service, ui, mid, left, right = prone_table(tmp_path, ally=True)
    record_setup(ui, mid, [right, 'actor:factory.ally'] if confirmed else [])
    turn(ui, mid, left)
    engine = service._load_session(mid).engine
    policy, _ = service.policies.for_actor(left)
    context = build_decision_context(engine, policy, for_ai=True)
    choices = [c for c in context.legal_candidates if c.display_name == 'Imperial Command: Kneel']
    assert bool(choices) == confirmed
    assert all(c.target_ids == (right,) for c in choices)  # no arbitrary friendly debuffs
    assert understands(engine.state.actors[right], engine.state.actors[left]) == confirmed
    service.set_controller_mode(mid, actor_id=left, controller_mode='LOCAL_AUTO')
    # A tactical preference is policy data, not a forced action or an invented fact.
    source = next(c.source_definition_id for c in commands(engine))
    preferred = policy.model_copy(update={'action_priorities': {**policy.action_priorities, source: 100}})
    monkeypatch.setattr(service.policies, 'for_actor', lambda aid: (preferred, False))
    result = service.auto_step(mid)
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    used = any(e.source_definition_id == source and e.event_type == 'RESOURCE_SPENT' for e in loaded.engine.events)
    assert used == confirmed
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('target_id', ['actor:factory.ally', 'actor:factory.right'])
def test_allied_and_hostile_kneel_commit_reload(tmp_path, monkeypatch, target_id):
    install(monkeypatch, 'd20_result', lambda e, *args: {'source_id': 'test:save',
        'operation': 'replace', 'natural_result': 1 if e.d20_context().get('kind') == 'save' else 20})
    service, ui, mid, left, right = prone_table(tmp_path, ally=True)
    record_setup(ui, mid, [target_id]); turn(ui, mid, left)
    e = service._load_session(mid).engine
    c = next(c for c in commands(e) if c.target_ids == (target_id,))
    before = e.state.actors[left].resources['resource:core.qi']
    assert ui.act(mid, c.candidate_id, c.decision_id, c.state_version, ui.state(mid)['last_sequence'])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert posture.prone_conditions(loaded.engine.state.actors[target_id])
    assert loaded.engine.state.actors[left].resources['resource:core.qi'] == before - 4
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('restriction', ['charm', 'deafened'])
def test_team_neutral_harmful_action_keeps_recipient_safeguards(tmp_path, monkeypatch, restriction):
    service, ui, mid, left, right = prone_table(tmp_path, ally=True)
    ally = 'actor:factory.ally'
    record_setup(ui, mid, [ally]); turn(ui, mid, left)
    def restrict(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == left:
            target = engine.state.actors[left if restriction == 'charm' else ally]
            engine._apply_condition(target, 'condition:typed.charmed' if restriction == 'charm' else 'condition:typed.deafened',
                'test:restriction', ally, expires_on='UNTIL_REMOVED')
    ext.effects(); monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), restrict])
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    e = service._load_session(mid).engine
    assert not any(c.target_ids == (ally,) for c in commands(e))
    assert any(c.target_ids == (right,) for c in commands(e))
