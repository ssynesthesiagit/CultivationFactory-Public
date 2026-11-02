"""Direct Encumbered setup (review script-2), committed and cold-replayed.

The setup action applies a condition through the normal typed executor; it
does not change inventory or call carry.refresh. Imported barrel loads are
covered separately by test_mgr_t15_swift_movement.
"""
import pytest

from combat import carry, factory_compiler, flight, movement_speeds, read_queries
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from tests.cw2_service_support import add_action
from tests.test_mgr_t15_swift_movement import (
    A, build, cold, encounter, offline, candidate_id, ROOT,
)


@pytest.mark.parametrize('learn', (True, False))
@pytest.mark.parametrize('exhausted', (False, True))
def test_script2_applied_encumbered_refuses_long_route_after_reload(tmp_path, monkeypatch, learn, exhausted):
    compile_character = factory_compiler.compile_character

    def compile_with_setup(*args, **kwargs):
        bundle = compile_character(*args, **kwargs)
        if bundle['actor_id'] == A:
            # This is script-2's add_condition: Encumbered path, not a load edit.
            add_action(bundle, 'Apply Encumbered', [
                {'type': 'condition', 'condition': 'Encumbered', 'applies_to': 'self',
                 'expires_on': 'UNTIL_REMOVED'}], target='SELF')
        return bundle

    monkeypatch.setattr(factory_compiler, 'compile_character', compile_with_setup)
    service, table, _ = build(tmp_path, monkeypatch, learn=learn)
    mid = encounter(service, table)
    engine = cold(service, mid)
    assert not carry.status(engine, engine.state.actors[A])['over']
    if exhausted:
        # Replacing a spent pool changes its mode-conversion basis, not its
        # remaining feet. That zero-distance replacement must still replay.
        feet = engine.state.actors[A].movement_remaining_ft
        path = [{'x': x, 'y': 1} for x in range(3, 4 + feet // 5)]
        state = table.state(mid)
        menu = state['menu']
        quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], A, path,
                                        movement_mode='walk')
        assert quote['candidate']['movement_cost_ft'] == feet
        assert table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
            menu['state_version'], A, path, movement_mode='walk',
            after=state['last_sequence'])['status'] == 'COMMITTED'
    state = table.state(mid)
    menu = state['menu']
    assert table.act(mid, candidate_id(menu, 'Apply Encumbered'), menu['decision_id'],
                     menu['state_version'], state['last_sequence'])['status'] == 'COMMITTED'

    # Native execution slugged the printed setup condition and saved it.
    engine = cold(service, mid)
    actor = engine.state.actors[A]
    assert any(c.condition_id == carry.ENCUMBERED for c in actor.conditions.values())
    assert not carry.status(engine, actor)['over']  # no barrels, no refresh
    assert all(movement_speeds.speed(engine, actor, mode) == 5
               for mode in movement_speeds.MODES)
    remaining = 0 if exhausted else 5
    assert actor.movement_remaining_ft == remaining
    assert actor.speed_ft + actor.turn_flags.get('movement_allowance_adjustment_ft', 0) == 5
    assert all(flight.remaining(engine, actor, mode) == remaining for mode in movement_speeds.MODES)

    fresh = CombatService(ROOT, tmp_path)
    table = TabletopService(fresh, tmp_path)
    state = table.state(mid)
    menu = state['menu']
    path = [{'x': x, 'y': 1} for x in range(actor.position.x, actor.position.x + 8)]
    with pytest.raises(TabletopError, match='more movement than remains'):
        table.preview_move_path(mid, menu['decision_id'], menu['state_version'], A, path,
                                movement_mode='walk')
    # Preserve the original cost-quote check alongside refusal of the long route.
    short = path[:2]
    if exhausted:
        with pytest.raises(TabletopError, match='more movement than remains'):
            table.preview_move_path(mid, menu['decision_id'], menu['state_version'], A, short,
                                    movement_mode='walk')
        return
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], A, short,
                                    movement_mode='walk')
    candidate = quote.get('candidate') or {}
    assert candidate.get('movement_cost_ft', 0) <= 5
    assert candidate['movement_cost_ft'] == 5
    assert table.commit_move_path(mid, candidate['candidate_id'], menu['decision_id'],
        menu['state_version'], A, short, movement_mode='walk',
        after=state['last_sequence'])['status'] == 'COMMITTED'
    engine = cold(fresh, mid)
    assert engine.state.actors[A].position.x == 4
    assert all(flight.remaining(engine, engine.state.actors[A], mode) == 0
               for mode in movement_speeds.MODES)


@pytest.mark.parametrize('scope', (read_queries.read_frame, read_queries.candidate_pass))
def test_prior_load_query_does_not_replace_live_cached_read(tmp_path, monkeypatch, scope):
    from combat.speed_contributions import effective_speed
    service, table, _ = build(tmp_path, monkeypatch)
    mid = encounter(service, table)
    engine = cold(service, mid)
    actor = engine.state.actors[A]
    with scope(engine):
        live = effective_speed(engine, actor)
        assert live == 40
        carrying = carry.carrying_of(engine, A)
        with read_queries.fresh_reads():
            carrying['weight_lb'] = int(carrying['capacity_lb']) + 1
            assert effective_speed(engine, actor) == 5
            carrying['weight_lb'] = int(carrying['capacity_lb'])
            assert effective_speed(engine, actor) == 40
            assert carry.status(engine, actor)['over'] is False
        assert effective_speed(engine, actor) == live
    assert effective_speed(engine, actor) == live
