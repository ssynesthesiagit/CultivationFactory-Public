"""Method standing obeys posture restrictions and survives a table reload."""
import pytest

from combat import ext
from combat.ext import foundation_sacred_body as body
from combat.gate5_service import CombatService
from tests.test_a2r03_fix_round import _play_picked, _prepare_pressure
from tests import test_a2r11_foundations as f


@pytest.mark.parametrize('restriction', ['grappled', 'restrained', 'zero_speed', 'veto', None])
def test_method_free_stand_uses_native_transition_at_table(tmp_path, monkeypatch, restriction):
    def prepare(bundles):
        _prepare_pressure('CON', 16, 'poisoned')(bundles)
        owner = next(b for b in bundles if b['actor_id'] == f.FIGHTER)
        if restriction == 'zero_speed':
            owner['actor_template']['speed_ft'] = 0
        foe = next(b for b in bundles if b['actor_id'] == f.SERVICE_FOE)
        action = next(a for a in foe['action_catalog'] if a['display_name'] == 'Body pressure')
        conditions = ['prone'] + ([restriction] if restriction in {'grappled', 'restrained'} else [])
        action['parameters']['typed']['effects'][:0] = [
            {'type': 'condition', 'condition': condition, 'applies_to': 'target'}
            for condition in conditions]

    original = ext.run_strict

    def queries(point, *args, **kwargs):
        answers = original(point, *args, **kwargs)
        if point == 'stand_allowed' and restriction == 'veto' and args[1].entity_id == f.FIGHTER:
            return [*answers, False]
        return answers

    monkeypatch.setattr(ext, 'run_strict', queries)
    _, table, mid = f._service_fight(tmp_path, monkeypatch, f._sacred(), f.SACRED_BARE, prepare=prepare)
    before = f._engine(CombatService(f.ROOT, tmp_path), mid).state.actors[f.FIGHTER]

    def pick(prompt):
        options = [o['id'] for o in prompt.get('choice', {}).get('options', [])]
        if prompt['reaction'] == 'Pressure Becomes Method':
            assert ('stand' in options) is (restriction is None)
            assert 'release' not in options  # Prone is not a minor speed penalty.
            return 'stand' if restriction is None else 'DECLINE'
        return 'DECLINE'

    result, prompts = _play_picked(table, mid, f._candidate(table, mid, 'Body pressure', f.FIGHTER), pick)
    assert result['status'] == 'COMMITTED'
    assert sum(p['reaction'] == 'Pressure Becomes Method' for p in prompts) == 1
    cold = f._engine(CombatService(f.ROOT, tmp_path), mid)
    actor = cold.state.actors[f.FIGHTER]
    assert actor.resources[f.PULSE] == 1
    assert actor.movement_remaining_ft == before.movement_remaining_ft
    assert actor.reaction_available == before.reaction_available
    conditions = {c.condition_id for c in actor.conditions.values()}
    assert ('condition:typed.prone' in conditions) is (restriction is not None)
    if restriction in {'grappled', 'restrained'}:
        assert 'condition:typed.' + restriction in conditions
        assert cold._effective_speed(actor) == 0
    stood = [e for e in cold.events if e.event_type == 'STOOD_UP' and e.actor_id == f.FIGHTER]
    assert len(stood) == int(restriction is None)
    if stood:
        assert stood[0].source_definition_id == body.METHOD
        assert stood[0].payload['cost_ft'] == 0


def test_method_release_keeps_prone_but_ends_speed_penalty_at_table(tmp_path, monkeypatch):
    def prepare(bundles):
        _prepare_pressure('CON', 16, 'poisoned')(bundles)
        foe = next(b for b in bundles if b['actor_id'] == f.SERVICE_FOE)
        action = next(a for a in foe['action_catalog'] if a['display_name'] == 'Body pressure')
        action['parameters']['typed']['effects'][:0] = [
            {'type': 'condition', 'condition': name, 'applies_to': 'target'}
            for name in ['prone', 'slowed']]

    _, table, mid = f._service_fight(tmp_path, monkeypatch, f._sacred(), f.SACRED_BARE, prepare=prepare)

    def pick(prompt):
        options = prompt.get('choice', {}).get('options', [])
        if any(o['id'] == 'release' for o in options):
            return 'release'
        releases = [o for o in options if o['id'].startswith('release:')]
        if releases:
            assert 'Prone' not in prompt['moment']
            assert len(releases) == 1
            assert 'slowed' in str(releases[0]).lower()
            assert 'prone' not in str(releases[0]).lower()
            return releases[0]['id']
        return 'DECLINE'

    _, prompts = _play_picked(table, mid, f._candidate(table, mid, 'Body pressure', f.FIGHTER), pick)
    assert any(any(o['id'].startswith('release:') for o in p.get('choice', {}).get('options', []))
               for p in prompts)
    cold = f._engine(CombatService(f.ROOT, tmp_path), mid)
    conditions = {c.condition_id for c in cold.state.actors[f.FIGHTER].conditions.values()}
    assert 'condition:typed.prone' in conditions
    assert 'condition:typed.slowed' not in conditions
    assert not any(e.event_type == 'STOOD_UP' and e.actor_id == f.FIGHTER for e in cold.events)
