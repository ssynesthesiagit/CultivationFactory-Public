"""Fault injection at the persisted table boundary; no model or browser calls."""
from types import SimpleNamespace

from combat.ext import summon_instinct
from combat.gate2_runtime_models import Position
from combat.gate4_controller import LocalDeterministicController
from tests.test_h47_summon_table import OWNER, table_fixture, verify_reload


def test_oscillating_free_moves_end_the_summon_turn_and_reload(tmp_path, monkeypatch):
    combat, table, mid, _, commit = table_fixture(
        tmp_path, wide=True, owner_talents=["TAL_DEATH_CORPSE_SERVANT"])
    session = combat._load_session(mid)
    creature_ids = {a.entity_id for a in session.engine.state.actors.values() if a.summon}
    starts = {cid: session.engine.state.actors[cid].position for cid in creature_ids}
    calls = dict.fromkeys(creature_ids, 0)
    candidate = SimpleNamespace(candidate_id="fault:move", kind="MOVE")
    context = SimpleNamespace(legal_candidates=(candidate,))
    monkeypatch.setattr(summon_instinct, "_context", lambda *args: context)
    monkeypatch.setattr(LocalDeterministicController, "choose_primary_action",
                        lambda self, ctx: SimpleNamespace(
                            intent=SimpleNamespace(candidate_id=candidate.candidate_id)))

    def oscillate(engine, intent):
        actor = engine.state.actors[engine.state.current_actor_id]
        calls[actor.entity_id] += 1
        # Fail promptly rather than hanging the pre-fix test. This mimics a
        # faulty executor moving back and forth without spending movement.
        assert calls[actor.entity_id] <= 128, "summon turn did not bound repeated MOVE decisions"
        start = starts[actor.entity_id]
        actor.position = (Position(x=start.x + 1, y=start.y, z=start.z)
                          if calls[actor.entity_id] % 2 else start)

    monkeypatch.setattr(summon_instinct, "_execute", oscillate)
    commit(table.state(mid)["menu"]["end_turn"])
    fresh = combat._load_session(mid).engine
    assert fresh.state.current_actor_id not in creature_ids
    assert set(calls.values()) == {128}
    lines = [e for e in fresh.events if e.event_type == "SUMMON_TURN" and e.actor_id in creature_ids]
    assert {e.actor_id for e in lines} == creature_ids
    assert all("ends its turn" in e.payload["text"] for e in lines)
    assert all(fresh.state.actors[cid].position == starts[cid] for cid in creature_ids)
    assert all(not fresh.state.actors[cid].action_available
               and fresh.state.actors[cid].movement_remaining_ft == 0 for cid in creature_ids)
    verify_reload(combat, table, mid)
