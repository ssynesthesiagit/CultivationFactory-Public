"""A reaction invalidates a move before its next step: real table commit/reload."""
import pytest

from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from tests.test_auto_tabik import _engine, ME, AN
from tests.test_lock2_persistence import table_match, ROOT
from tests.test_lock_choices import install


@pytest.mark.parametrize('interruption', ['dying', 'unconscious', 'grappled', 'prone'])
def test_reaction_invalidated_move_stops_without_spending_the_old_step(monkeypatch, tmp_path, interruption):
    install(monkeypatch, 'zero_hp', lambda *args: 'DYING')

    def interrupt(engine, event_type, kwargs):
        if event_type != 'REACTION_WINDOW_OPENED' or kwargs.get('payload', {}).get('checkpoint') != 'LEAVE_REACH':
            return
        mover = engine.state.actors[kwargs['actor_id']]
        if interruption == 'dying':
            engine._commit_damage(mover, mover.current_hp + 100, 'UNTYPED', 'test:interrupt',
                                  kwargs['target_ids'][0], None, reaction_depth=3)
        else:
            condition = 'condition:core.grappled' if interruption == 'grappled' else 'condition:typed.' + interruption
            engine._apply_condition(mover, condition, 'test:interrupt', kwargs['target_ids'][0],
                                    expires_on='UNTIL_REMOVED')

    install(monkeypatch, 'event', interrupt)
    combat, table, mid = table_match(tmp_path)
    state = table.state(mid)
    menu = state['menu']
    before = combat._load_session(mid).engine
    mover = before.state.actors[menu['actor_id']]
    foe = next(a for a in before.state.actors.values() if a.team_id != mover.team_id)
    move = next(c for c in menu['moves']
                if max(abs(c['destination']['x'] - foe.position.x), abs(c['destination']['y'] - foe.position.y)) > 1
                and max(abs(c['destination']['x'] - mover.position.x), abs(c['destination']['y'] - mover.position.y)) == 1)
    start = mover.position
    result = table.act(mid, move['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[mover.entity_id]
    assert actor.position == start
    assert actor.movement_remaining_ft >= 0
    committed = next(e for e in reversed(loaded.engine.events) if e.event_type == 'MOVEMENT_COMMITTED')
    assert committed.payload['interrupted'] is True and committed.payload['cost_ft'] == 0
    assert committed.payload['path'] == [start.model_dump(mode='json')]
    if interruption == 'dying':
        assert actor.active and actor.life_state == 'DYING' and actor.movement_remaining_ft == 0
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('change', ['budget', 'occupancy', 'terrain'])
def test_reaction_rechecks_actual_budget_occupancy_and_step_cost(monkeypatch, change):
    engine, _ = _engine([], foe_at=(8, 6))
    actor = engine.state.actors[ME]
    candidate = next(c for c in engine._movement_candidates(actor)
                     if engine.grid.distance_ft(actor.position, c.destination) == 5)
    start = actor.position
    actor.movement_remaining_ft = candidate.movement_cost_ft
    # Refresh the candidate binding after setting up this unit-level geometry case.
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination == candidate.destination)
    def reaction(mover, previous, nxt, request, *, ignore_oa_from=()):
        assert ignore_oa_from == ()  # Ordinary moves retain every enemy's opportunity attack.
        if change == 'budget':
            mover.movement_remaining_ft = 0
        elif change == 'occupancy':
            engine.state.actors[AN].position = nxt
        else:
            engine.grid.base_movement_cost[(nxt.x, nxt.y)] = 2
    monkeypatch.setattr(engine, '_resolve_leave_reach', reaction)
    engine.execute_intent(ActionIntent(intent_id='test:step-change', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME,
        target_ids=candidate.target_ids, destination=candidate.destination))
    assert actor.position == start and actor.movement_remaining_ft >= 0
    event = next(e for e in reversed(engine.events) if e.event_type == 'MOVEMENT_COMMITTED')
    assert event.payload['cost_ft'] == 0 and event.payload['interrupted']
