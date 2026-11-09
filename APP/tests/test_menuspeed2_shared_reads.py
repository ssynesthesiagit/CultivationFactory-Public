"""Complete state/view menus are reused without changing native decisions."""
from copy import copy

import pytest

from combat import spatial_areas, spread_areas
from combat.gate4_context import build_decision_context
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_ai_flight_options import FLYER, flyer_fight
from tests.test_agent_seats import raw_state
from tests.test_speedlate_spread import _engine, ORIGIN, AREA, _reference
from combat.gate2_runtime_models import Position


def test_persisted_full_menus_and_ai_context_shared_across_reload(tmp_path, monkeypatch):
    combat, table, mid, runner = flyer_fight(tmp_path)
    session = combat._load_session(mid)
    policy, _ = combat.policies.for_actor(FLYER)
    # The service's complete observed query now represents CELL choices lazily.
    # Compare cached/reloaded copies of that complete two-stage contract.
    expected = build_decision_context(session.engine, policy, for_ai=True,
        prepared_candidates=combat._legal_candidates(session, knowledge_only=True, progress_guard=False)).model_dump(mode='json')
    player = combat.decision(mid, session=session)['context']
    combat._derived.clear()
    native = Gate4ControllerEngine.legal_candidates
    calls = []
    def counted(engine):
        calls.append(engine.state.state_version)
        return native(engine)
    monkeypatch.setattr(Gate4ControllerEngine, 'legal_candidates', counted)
    # Real table reads, the complete seat menu, ranking/context and a reloaded
    # session all consume the same state-bound generation for each query view.
    state = raw_state(runner, mid)
    assert combat.decision(mid)['context'] == player
    first = combat.ai_decision_context(session)
    assert first.model_dump(mode='json') == expected
    assert combat.ai_decision_context(combat._load_session(mid)).model_dump(mode='json') == expected
    view, known = runner.own_view(mid, state, FLYER, session)
    menu = runner._menu(state, known)
    from agent_seats.action_options import expand_menu
    options = expand_menu(menu, session.engine, view, candidates=combat._legal_candidates(session))
    pick = runner._builtin(mid, session, known, options, view['visible_cells'])
    assert pick[0] in options
    assert len(calls) == 2, 'expected one complete player pass and one complete observed pass'
    # Every row, including movement/destination/augment choices, remains.
    assert {c['candidate_id'] for c in player['legal_candidates']} == {
        c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']}
    first.actors[0].resources['test:caller-edit'] = 99
    assert combat.ai_decision_context(session).model_dump(mode='json') == expected


def test_ai_cache_is_invalidated_by_unrecorded_state_and_control_changes(tmp_path):
    combat, _, mid, _ = flyer_fight(tmp_path)
    session = combat._load_session(mid)
    before = combat.ai_decision_context(session)
    key = combat._state_key(session)
    session.engine.typed_control_modes[FLYER] = 'LOCAL_AUTO'
    assert combat._state_key(session) != key
    session.engine.state.actors[FLYER].current_hp -= 1
    assert combat._state_key(session) is None
    after = combat.ai_decision_context(session)
    assert next(a.current_hp for a in after.actors if a.entity_id == FLYER) == (
        next(a.current_hp for a in before.actors if a.entity_id == FLYER) - 1)


def test_native_ranking_and_auto_progress_policy_share_generation_without_cutting_options(tmp_path, monkeypatch):
    from combat import turn_progress
    combat, _, mid, _ = flyer_fight(tmp_path)
    session = combat._load_session(mid)
    native = Gate4ControllerEngine.legal_candidates
    calls = []
    def counted(engine):
        calls.append(1)
        return native(engine)
    monkeypatch.setattr(Gate4ControllerEngine, 'legal_candidates', counted)
    original = turn_progress.narrow
    def guarded(session, candidates, **kwargs):
        if kwargs['for_ai']:
            return tuple(c for c in candidates if c.kind == 'END_TURN')
        return original(session, candidates, **kwargs)
    monkeypatch.setattr(turn_progress, 'narrow', guarded)
    complete = combat.ai_decision_context(session)
    automatic = combat.ai_decision_context(session, progress_guard=True)
    assert len(complete.legal_candidates) > 1
    assert all(c.kind == 'END_TURN' for c in automatic.legal_candidates)
    assert combat.ai_decision_context(session).model_dump(mode='json') == complete.model_dump(mode='json')
    assert len(calls) == 1


def test_post_commit_refresh_reuses_exact_saved_session_and_matches_reload(tmp_path, monkeypatch):
    combat, table, mid, runner = flyer_fight(tmp_path)
    runner._local.active = True
    state = table.state(mid)
    menu = state['menu']
    native = combat._load_session
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return native(*args, **kwargs)
    monkeypatch.setattr(combat, '_load_session', counted)
    result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    assert result['status'] == 'COMMITTED'
    assert len(calls) == 1, 'post-commit presentation replayed the already committed journal'
    fresh = table.state(mid)
    assert result['state'] == fresh
    assert fresh['menu']['state_version'] > state['menu']['state_version']


@pytest.mark.parametrize('edit', ['state', 'journal', 'modes', 'arena'])
def test_incremental_refresh_refuses_changed_boundary(tmp_path, edit):
    combat, table, mid, runner = flyer_fight(tmp_path)
    runner._local.active = True
    state = table.state(mid)
    menu = state['menu']
    table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], state['last_sequence'])
    session = combat._load_session(mid)
    assert combat.presentation_session(session) is session
    if edit == 'state':
        session.engine.state.actors[FLYER].current_hp -= 1
    elif edit == 'journal':
        with (combat._match_dir(mid) / 'Journal.ndjson').open('ab') as stream:
            stream.write(b'{}\n')
    elif edit == 'modes':
        session.engine.typed_control_modes[FLYER] = 'LOCAL_AUTO'
    else:
        arena = combat._match_dir(mid) / 'Arena_Battlefield.json'
        arena.write_bytes(arena.read_bytes() + b'\n')
    assert combat.presentation_session(session) is None


def test_independent_shallow_knowledge_projections_share_spread_frontier(monkeypatch):
    engine = _engine()
    # Create both views BEFORE either has an index, as area previews do.
    first, second = copy(engine), copy(engine)
    native = spread_areas._Search.__init__
    calls = []
    def counted(self, *args):
        calls.append(1)
        native(self, *args)
    monkeypatch.setattr(spread_areas._Search, '__init__', counted)
    for projection, target in [(first, Position(x=4, y=3, z=1)),
                               (second, Position(x=6, y=3, z=1))]:
        assert spatial_areas.reaches(projection, ORIGIN, ORIGIN, target, AREA) == _reference(
            engine, ORIGIN, ORIGIN, target, AREA)
    assert first._spread_area_index is second._spread_area_index
    assert len(calls) == 1
    engine.grid.blocked.update((5, y) for y in range(engine.grid.height))
    assert spatial_areas.reaches(second, ORIGIN, ORIGIN, Position(x=6, y=3, z=1), AREA) == _reference(
        engine, ORIGIN, ORIGIN, Position(x=6, y=3, z=1), AREA)
    assert first._spread_area_index is not second._spread_area_index
