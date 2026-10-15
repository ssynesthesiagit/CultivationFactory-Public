"""Focused native source delivery regression."""
from tests.worker2_support import fixture, settle, candidate, reload, OWNER, ALLY, FOE
from tests.test_mgr_t14_committed_movement import set_standard


def test_momentum_help_uses_real_assistance_and_survives_reload(tmp_path):
    combat, table, mid = fixture(tmp_path,
        ['WARLEADER_BASE_MOMENTUM_MARKS', 'WARLEADER_BASE_SET_THE_STANDARD'],
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 3, 'y': 5}})
    set_standard(combat, table, mid)
    engine = reload(tmp_path, mid)
    from combat.ext import run_strict
    from combat.ext.warleader_momentum import owns_contract
    help_rows = [c for c in engine.legal_candidates() if c.source_definition_id == 'system:combat.help_attack']
    assert help_rows, {'installed': 'system:combat.help_attack' in engine.action_catalog,
        'contract': owns_contract(engine, engine.state.actors[OWNER]),
        'action_available': engine.state.actors[OWNER].action_available,
        'replacement': run_strict('help_action_replacement', engine, engine.state.actors[OWNER]),
        'additional': run_strict('additional_actions', engine, engine.state.actors[OWNER])}
    settle(table, mid, candidate(combat, mid, 'Help an ally attack', target=FOE).candidate_id,
        picks={'choice:needle.help_recipient': ALLY})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:named.momentum_mark'] == 1
    delivery = [e for e in engine.events if e.event_type == 'HELP_DELIVERED']
    assert len(delivery) == 1 and delivery[0].actor_id == OWNER and delivery[0].target_ids == (ALLY,)
    assert any(m.value == 'ADVANTAGE:' + FOE for m in engine.state.actors[ALLY].modifiers.values())

