"""Reuse complete menus and pure jump reads without changing seat choices."""
from copy import deepcopy

from agent_seats.action_options import expand_menu
from combat import flight, senses
from tests.h1_support import ME, duel
from tests.test_ai_flight_options import FLYER, flyer_fight
from tests.test_agent_seats import raw_state


def test_prepared_seat_selections_equal_every_direct_menu_option(tmp_path, monkeypatch):
    combat, table, mid, runner = flyer_fight(tmp_path)
    state = raw_state(runner, mid)
    session = combat._load_session(mid)
    view, known = runner.own_view(mid, state, FLYER, session)
    menu = runner._menu(state, known)
    expected = expand_menu(menu, session.engine, view)
    candidates = combat._legal_candidates(session)
    def unexpected():
        raise AssertionError('the unchanged prepared menu was regenerated')
    monkeypatch.setattr(session.engine, 'legal_candidates', unexpected)
    assert expand_menu(menu, session.engine, view, candidates=candidates) == expected
    assert len(expected) >= len(menu)


def test_jump_search_reuses_perception_only_until_it_returns(monkeypatch):
    engine = duel([])
    actor = engine.state.actors[ME]
    actor.strength_score = 24
    engine.grid.finite_heights = True
    origin = actor.position
    walking = {origin.model_copy(update={'x': origin.x + i}): (
        (origin, origin.model_copy(update={'x': origin.x + i})), 5 * i)
        for i in (1, 2, 3)}
    native = senses.perceives
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return native(*args, **kwargs)
    monkeypatch.setattr(senses, 'perceives', counted)
    reference = getattr(flight.jumps, '__wrapped__', flight.jumps)
    before = deepcopy(engine.state.model_dump(mode='json'))
    expected = reference(engine, actor, walking)
    reference_calls = len(calls)
    calls.clear()
    assert flight.jumps(engine, actor, walking) == expected
    cached_calls = len(calls)
    assert 0 < cached_calls < reference_calls
    assert flight.jumps(engine, actor, walking) == expected
    assert len(calls) == 2 * cached_calls, 'a later search inherited an old read frame'
    assert engine.state.model_dump(mode='json') == before
