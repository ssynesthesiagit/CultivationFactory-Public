"""Resource denial is readable in the actual history feed."""
import pytest

from combat.history_feed import format_history_feed
from combat.gate5_service import CombatService
from tests.test_auto_tabik import _engine, ME
from tests.test_lock_choices import install
from tests.test_lock2_persistence import ROOT, table_match, act


@pytest.mark.parametrize('resource,label', [
    ('resource:core.stamina', 'Stamina'), ('resource:core.qi', 'Qi'),
    ('resource:core.cp', 'Cultivation Points (CP)'), ('resource:focus', 'Focus'),
    ('resource:named.thunder_charge', 'Thunder Charge')])
def test_denial_message_uses_player_names(monkeypatch, resource, label):
    install(monkeypatch, 'resource_gain_allowed', lambda *args: False)
    engine, _ = _engine([])
    actor = engine.state.actors[ME]
    actor.resources[resource] = 0
    actor.resource_maximums[resource] = 4
    engine._gain_resource(actor, resource, 2, 'test:gain')
    event = engine.events[-1]
    expected = f'{actor.display_name} cannot regain {label} right now: 2 not regained.'
    assert event.payload['rider'] == expected
    feed = format_history_feed([event.model_dump(mode='json')], [], pre_state=None, post_state={},
        actor_names={ME: actor.display_name}, definition_names={})
    assert any(expected in str(row) for row in feed)
    assert 'Not automated' not in str(feed)
    assert actor.resources[resource] == 0


def test_denial_at_table_survives_reload_and_uses_stamina(monkeypatch, tmp_path):
    def gain(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED':
            engine._gain_resource(engine.state.actors[kwargs['actor_id']], 'resource:core.stamina', 1, 'test:gain')
    install(monkeypatch, 'event', gain)
    install(monkeypatch, 'resource_gain_allowed', lambda *args: False)
    service, table, mid = table_match(tmp_path)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    assert 'cannot regain Stamina' in str(table.events(mid, 0)['events'])
    assert 'cannot regain resource:' not in str(table.events(mid, 0)['events'])
    assert CombatService(ROOT, tmp_path)._load_session(mid).verify()['status'] == 'PASS'
