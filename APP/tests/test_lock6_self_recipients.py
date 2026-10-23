"""The round5 recipient contract also applies to the table's self targets."""
import pytest

from combat.attack_declaration import can_target
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.recipients import allowed
from tests.test_lock2_persistence import ROOT, table_match, act
from tests.test_lock_choices import install

SOURCE = 'test:self-recipient:'
CELL = 'test:cell-target:'
BAR = 'condition:test.self_bar'


@pytest.mark.parametrize('kind', ['SELF', 'SELF_OR_CELL'])
@pytest.mark.parametrize('blocked', [True, False])
def test_owned_self_veto_agrees_with_query_and_table_after_reload(monkeypatch, tmp_path, kind, blocked):
    def actions(info):
        common = dict(owner_id=info['actor_id'], economy=EconomyKind.ACTION, resolution_kind='TYPED',
                      parameters={'typed': {'effects': [{'type': 'temp_hp', 'flat': 1, 'applies_to': 'self'}],
                                            'numbers': info['numbers']}})
        return [ActionDefinition(source_definition_id=SOURCE+info['actor_id'], display_name='Practice self ward', target_kind=kind, **common),
                ActionDefinition(source_definition_id=CELL+info['actor_id'], display_name='Mark a square', target_kind='CELL',
                                 range_ft=5, **common)]
    install(monkeypatch, 'compile_actions', actions)
    def veto(engine, actor, target, action):
        if action.source_definition_id.startswith(SOURCE) and target is actor and engine._has_condition(actor, BAR):
            return False
    install(monkeypatch, 'recipient_allowed', veto)
    service, table, mid = table_match(tmp_path)
    initial = table.state(mid)['menu']
    assert any(g['source_definition_id'].startswith(SOURCE) for g in initial['actions'])
    def mark(engine, event_type, kwargs):
        if event_type == 'HOLD_POSITION_COMMITTED' and blocked:
            actor = engine.state.actors[kwargs['actor_id']]
            engine._apply_condition(actor, BAR, 'test:owned-self-veto', actor.entity_id, expires_on='START_OF_SELF_NEXT_TURN')
    install(monkeypatch, 'event', mark)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[loaded.engine.state.current_actor_id]
    action = loaded.engine.action_catalog[SOURCE+actor.entity_id]
    assert allowed(loaded.engine, actor, actor, action) is not blocked
    assert can_target(loaded.engine, actor, actor, action.source_definition_id) is not blocked
    state = table.state(mid)
    in_menu = any(g['source_definition_id'] == action.source_definition_id for g in state['menu']['actions'])
    assert in_menu is not blocked
    assert any(c.source_definition_id.startswith(CELL) and c.destination is not None and not c.target_ids
               for c in loaded.engine.legal_candidates())  # cell targeting has its own rules
    assert loaded.verify()['status'] == 'PASS'
