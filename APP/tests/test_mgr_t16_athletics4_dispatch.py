"""Supplemental Pursuit events must not own unrelated movement benefits."""
from combat import motion
from combat.ext import counterstrike
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_mgr_t16_athletics4 import PURSUIT, complete
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT, ALLY
from tests.test_walkable_roofs import route

AFTERIMAGE = 'TAL_ATHLETICS_AFTERIMAGE'
FLASH = 'TAL_ATHLETICS_FLASH_STEP'
BULL = 'TAL_RETRIBUTION_RAGING_BULL'


def snapshot(directory, mid):
    loaded = CombatService(ROOT, directory)._load_session(mid)
    actor = loaded.engine.state.actors[LEFT]
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return actor.turn_flags.get('moved_ft', 0), motion.has_afterimage(actor)


def test_real_teleport_does_not_gain_afterimage_from_unrelated_pursuit_cold_reload(tmp_path):
    results = []
    for owns_pursuit in (False, True):
        directory = tmp_path / str(owns_pursuit)
        combat, table, mid = table_fight(directory, [AFTERIMAGE, FLASH],
            ally_talents=[PURSUIT] if owns_pursuit else [],
            starts={'team1': [[1, 1], [11, 7]], 'team2': [[3, 7]]})
        route(combat, table, mid, [(1, y, 0) for y in range(1, 6)])
        assert snapshot(directory, mid) == (20, False)
        state = table.state(mid)
        menu = state['menu']
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates()
                         if c.display_name.startswith('Flash Step to ')
                         and c.destination.x == 1 and c.destination.y == 6)
        result = table.act(mid, candidate.candidate_id, menu['decision_id'],
                           menu['state_version'], state['last_sequence'], [])
        assert result['status'] == 'COMMITTED', result
        loaded = CombatService(ROOT, directory)._load_session(mid)
        mover, watcher = (loaded.engine.state.actors[a] for a in (LEFT, ALLY))
        assert loaded.engine._distance_actor_to_actor(mover, watcher) > loaded.engine._effective_speed(watcher)
        receipt = next(e for e in reversed(loaded.engine.events)
                       if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == LEFT)
        assert receipt.payload['teleport'] is True and receipt.payload['forced'] is False
        results.append(snapshot(directory, mid))
    assert results == [(20, False), (20, False)]


def test_raging_bull_producer_counts_afterimage_once_with_unrelated_pursuit_cold_reload(tmp_path, monkeypatch):
    results = []
    # Run the native charge producer inside an accepted table transaction. Its
    # receipt and subsequent ordinary moved event must share one benefit count.
    for owns_pursuit in (False, True):
        directory = tmp_path / str(owns_pursuit)
        combat, table, mid = table_fight(directory, [AFTERIMAGE, BULL],
            ally_talents=[PURSUIT] if owns_pursuit else [],
            starts={'team1': [[1, 3], [11, 7]], 'team2': [[5, 3]]})
        with monkeypatch.context() as patch:
            on_hold(patch, lambda e: counterstrike._charge(
                e, e.state.actors[LEFT], e.state.actors[RIGHT], 5, e._active_intent))
            result, prompts = complete(table, mid)
        assert result['status'] == 'COMMITTED' and not prompts
        loaded = CombatService(ROOT, directory)._load_session(mid)
        mover, watcher = (loaded.engine.state.actors[a] for a in (LEFT, ALLY))
        assert mover.position.x == 4
        assert loaded.engine._distance_actor_to_actor(mover, watcher) > loaded.engine._effective_speed(watcher)
        receipts = [e for e in loaded.engine.events if e.event_type == 'MOVEMENT_COMMITTED'
                    and e.payload.get('counterstrike') == 'raging_bull']
        assert len(receipts) == 1 and receipts[0].payload['cost_ft'] == 15
        results.append(snapshot(directory, mid))
    assert results == [(15, False), (15, False)]
