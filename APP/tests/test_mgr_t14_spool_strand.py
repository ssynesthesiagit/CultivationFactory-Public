"""Spool and Strand's paid strand clock through table commits and cold loads.

Draw the Line is the real producer, not a test-injected Qi Thread condition.
Its own printed per-use cost is distinct from the lifetime of the strand.
"""
from combat.ext.effect_durations import parse_round
from combat.ext.thread_weaving import QI_THREAD
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_a2_thread import fixture, settle
from tests.test_r4_integration import P, F, candidate, reach, send

SPOOL = "THREAD_BASE_SPOOL_AND_STRAND"
QI = "resource:core.qi"


def load(path, mid):
    return CombatService(ROOT, path)._load_session(mid)


def strands(actor):
    return [c for c in actor.conditions.values() if c.condition_id == QI_THREAD]


def end(table, mid):
    assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"


def test_base_qi_thread_is_owned_persists_reinforces_and_expires(tmp_path):
    combat, table, mid = fixture(tmp_path, [SPOOL], foe_x=8)
    reach(table, mid, P)
    before = load(tmp_path, mid).engine.state.actors[P].resources[QI]
    settle(table, mid, candidate(table, mid, "Draw the Line: Snare (Qi Thread)", F))
    session = load(tmp_path, mid)
    actor, foe = session.engine.state.actors[P], session.engine.state.actors[F]
    (strand,) = strands(actor)  # fails on the unmodified base provider
    assert strand.source_actor_id == P and not strands(foe)
    assert actor.resources[QI] == before - 1
    assert parse_round(strand.expires_on) == (session.engine.state.round_number + 10,
                                             session.engine.state.current_slot_index)
    assert "1 minute" in strand.data["reading"]
    assert all(type(value) in (str, int) for value in strand.data.values())
    assert session.mechanical.replay()["status"] == "PASS"
    old_deadline = parse_round(strand.expires_on)

    end(table, mid)
    reach(table, mid, P)
    settle(table, mid, candidate(table, mid, "Draw the Line: Snare (Qi Thread)", F))
    session = load(tmp_path, mid)
    (reinforced,) = strands(session.engine.state.actors[P])
    deadline = parse_round(reinforced.expires_on)
    assert deadline[0] == old_deadline[0] + 1
    assert session.engine.state.actors[P].resources[QI] == before - 2
    # No fabricated clock advances or direct expiry calls: use actual turns.
    for _ in range(24):
        session = load(tmp_path, mid)
        clock = (session.engine.state.round_number, session.engine.state.current_slot_index)
        if clock >= deadline:
            break
        assert strands(session.engine.state.actors[P])
        end(table, mid)
    else:
        raise AssertionError("strand expiry turn not reached")
    assert not strands(load(tmp_path, mid).engine.state.actors[P])
    assert load(tmp_path, mid).mechanical.replay()["status"] == "PASS"


def test_mundane_thread_does_not_pay_or_create_qi_and_nonowner_gets_no_options(tmp_path):
    combat, table, mid = fixture(tmp_path, [SPOOL], foe_x=6)
    reach(table, mid, P)
    before = load(tmp_path, mid).engine.state.actors[P].resources[QI]
    settle(table, mid, candidate(table, mid, "Draw the Line: Snare", F))
    session = load(tmp_path, mid)
    assert session.engine.state.actors[P].resources[QI] == before
    assert not strands(session.engine.state.actors[P])
    end(table, mid)
    reach(table, mid, F)
    session = load(tmp_path, mid)
    assert not any("thread_twin" in (action.parameters or {})
                   for aid in session.engine.state.actors[F].action_ids
                   for action in [session.engine.action_catalog[aid]])
    assert not strands(session.engine.state.actors[F])
    assert session.mechanical.replay()["status"] == "PASS"
