"""Capped movement is not a Disengage effect; later ordinary steps still provoke."""
import pytest
from combat import typed_executor
from combat.gate2_runtime_models import ActionDefinition, Position
from combat.technique_interception import activation
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.h1_support import ROOT, duel, ME, FOE

CAPPED_MOVEMENT = 'test:capped-movement'


@pytest.mark.parametrize('cap', [0, 10])
def test_exhausted_native_grants_do_not_suppress_later_table_opportunity_attack(monkeypatch, tmp_path, cap):
    service, table, mid = H.table_fight(tmp_path, [])
    def limit(engine, actor, action, *args):
        if action.source_definition_id == CAPPED_MOVEMENT:
            return {'source_id': 'test:cap', 'label': 'Movement limited by interception', 'movement_cap_ft': cap}
    install(monkeypatch, 'technique_declared', limit)
    def grants(engine):
        actor = engine.state.actors[H.LEFT]
        candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == H.HOLD)
        action = ActionDefinition(source_definition_id=CAPPED_MOVEMENT, display_name='Capped movement', owner_id=H.LEFT,
            economy='ACTION', resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {'source': CAPPED_MOVEMENT}})
        # C8's reviewed Sacral plug-in (004984c2) replaced the old duplicate
        # authority movement rows. Keep this generic cap regression explicit:
        # an ordinary grant exhausts the budget before the protected grant.
        with activation(engine, actor, action, candidate, engine._active_intent) as (declared, _, canceled):
            assert not canceled
            ctx = typed_executor.Context(engine, actor, declared, engine._active_intent, declared.parameters['typed'], [], None)
            for effect in ({'type': 'movement', 'distance_ft': 10},
                           {'type': 'movement', 'distance_ft': 10, 'no_opportunity_attacks': True}):
                typed_executor.block_movement(ctx, effect)
    H.on_hold(monkeypatch, grants)
    before = service._load_session(mid).engine.state.actors[H.LEFT].movement_remaining_ft
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[H.LEFT]
    assert actor.movement_remaining_ft == before + cap
    assert not actor.turn_flags.get('disengaged') and not actor.turn_flags.get('oa_free_ft')
    e = loaded.engine
    c = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination == Position(x=2, y=4))
    assert table.act(mid, c.candidate_id, c.decision_id, c.state_version, table.state(mid)['last_sequence'])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(ev.event_type == 'REACTION_RESOLVED' and ev.actor_id == H.RIGHT and
               ev.source_definition_id == 'system:combat.opportunity_attack' for ev in loaded.engine.events)
    assert not loaded.engine.state.actors[H.RIGHT].reaction_available
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_explicit_zero_distance_disengage_keeps_its_existing_meaning():
    e = duel([])
    actor = e.state.actors[ME]
    action = next(a for a in e.action_catalog.values() if a.owner_id == ME)
    ctx = typed_executor.Context(e, actor, action, None, {}, [], None)
    typed_executor.block_movement(ctx, {'distance_ft': 0, 'no_opportunity_attacks': True})
    assert actor.turn_flags['disengaged'] is True
