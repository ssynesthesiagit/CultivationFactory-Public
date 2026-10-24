"""Fault injection at the persisted table boundary; no model or browser calls."""
from types import SimpleNamespace

import pytest

from combat.ext import summon_instinct
from combat.gate2_runtime_models import Position
from combat.gate4_controller import LocalDeterministicController
from tests.test_h47_summon_table import OWNER, table_fixture, verify_reload


@pytest.mark.parametrize("replay_checks", [1, 2])
def test_oscillating_free_moves_end_the_summon_turn_and_reload(tmp_path, monkeypatch, replay_checks):
    combat, table, mid, _, commit = table_fixture(
        tmp_path, wide=True, owner_talents=["TAL_DEATH_CORPSE_SERVANT"])
    session = combat._load_session(mid)
    creature_ids = {a.entity_id for a in session.engine.state.actors.values() if a.summon}
    starts = {cid: session.engine.state.actors[cid].position for cid in creature_ids}
    # The table may preview, commit and replay as separate executions. Bound
    # each invocation, not the cumulative work across those transactions.
    calls = {}
    completed = []
    invoking = {}
    original_take_turn = summon_instinct.take_turn

    def bounded_turn(engine, actor):
        calls[actor.entity_id] = 0
        invoking["actor_id"] = actor.entity_id
        original_take_turn(engine, actor)
        assert calls[actor.entity_id] == 128
        assert actor.position == starts[actor.entity_id]
        completed.append(actor.entity_id)

    monkeypatch.setattr(summon_instinct, "take_turn", bounded_turn)
    candidate = SimpleNamespace(candidate_id="fault:move", kind="MOVE", destination=None)
    # Mirror the real _context shape the turn text reads (summon_goal is always present).
    context = SimpleNamespace(legal_candidates=(candidate,),
                              tactics={"summon_goal": {"hostiles": [], "owner_position": None}})
    monkeypatch.setattr(summon_instinct, "_context", lambda *args: context)
    monkeypatch.setattr(LocalDeterministicController, "choose_primary_action",
                        lambda self, ctx: SimpleNamespace(
                            intent=SimpleNamespace(candidate_id=candidate.candidate_id)))

    def oscillate(engine, intent):
        # The engine need not make the acting summon the current actor slot
        # while its default turn runs; count and move the creature whose turn
        # this invocation is bounding.
        actor_id = invoking["actor_id"]
        calls[actor_id] += 1
        # Fail promptly rather than hanging the pre-fix test. This mimics a
        # faulty executor moving back and forth without spending movement.
        assert calls[actor_id] <= 128, "summon turn did not bound repeated MOVE decisions"
        start = starts[actor_id]
        engine.state.actors[actor_id].position = (Position(x=start.x + 1, y=start.y, z=start.z)
                                                  if calls[actor_id] % 2 else start)

    monkeypatch.setattr(summon_instinct, "_execute", oscillate)
    commit(table.state(mid)["menu"]["end_turn"])
    fresh = combat._load_session(mid).engine
    assert fresh.state.current_actor_id not in creature_ids
    assert set(completed) == creature_ids
    # A table flow may validate and commit in one execution or in two. Either
    # way every invocation above must bound at 128 and finish the turn; the
    # replay checks below prove recovery never runs another AI turn.
    lines = [e for e in fresh.events if e.event_type == "SUMMON_TURN" and e.actor_id in creature_ids]
    assert {e.actor_id for e in lines} == creature_ids
    assert all("ends its turn" in e.payload["text"] for e in lines)
    assert all(fresh.state.actors[cid].position == starts[cid] for cid in creature_ids)
    assert all(not fresh.state.actors[cid].action_available
               and fresh.state.actors[cid].movement_remaining_ft == 0 for cid in creature_ids)
    for _ in range(replay_checks):
        before_replay = len(completed)
        verify_reload(combat, table, mid)
        # Saved replay reduces committed events, rather than asking the AI to
        # decide again. Repeated recovery must not execute another summon turn.
        assert len(completed) == before_replay
