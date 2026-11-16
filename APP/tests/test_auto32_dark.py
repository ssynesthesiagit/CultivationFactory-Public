"""One With The Night's actual flight is retained by table commits and reloads."""
import pytest

from combat.flight import profile
from combat.ext.states import active
from combat.gate5_service import CombatService
from tests.worker2_support import ROOT, OWNER, fixture, candidate, act

TALENT = 'TAL_DARK_ONE_WITH_THE_NIGHT'


@pytest.mark.parametrize('owned', [True, False])
def test_night_flight_table_commit_reload_and_concentration_binding(tmp_path, owned):
    combat, table, mid = fixture(tmp_path, [TALENT] if owned else [], seed='AUTO32', owner_speed=45)
    if owned:
        cast = candidate(combat, mid, 'One With The Night')
        assert act(table, mid, cast.candidate_id)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[OWNER]
    assert loaded.engine._effective_speed(actor) == 45
    assert profile(loaded.engine, actor).speed_ft == (30 if owned else 0)
    assert profile(loaded.engine, actor).hover == owned
    if owned:
        state = active(loaded.engine, actor, 'one_with_the_night')
        assert state.expires_on == 'CONCENTRATION_END'
        assert actor.concentration.source_definition_id == state.source_definition_id
        start = actor.position
        move = next(c for c in loaded.engine.legal_candidates() if c.destination and c.destination.z == 1
                    and (c.destination.x, c.destination.y) == (start.x, start.y))
        assert act(table, mid, move.candidate_id)['status'] == 'COMMITTED'
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        actor = loaded.engine.state.actors[OWNER]
        assert actor.position.z == 1
        assert profile(loaded.engine, actor).hover
        # Supplementary pure-query check on a detached copy: a stale state in
        # an older save must never grant flight after Concentration has ended.
        detached = actor.model_copy(deep=True)
        detached.concentration = None
        assert profile(loaded.engine, detached).speed_ft == 0
    assert loaded.mechanical.replay()['status'] == 'PASS'
