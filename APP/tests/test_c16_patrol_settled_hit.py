"""Patrol rewards follow settled table attack outcomes, not provisional rolls."""

import pytest

from tests.r1i_service_support import FOE, OWNER, candidate, fixture
from tests.test_r1i_round3 import reload, resolve
from tests.test_riders_c16 import G, PATROL, SEED


@pytest.mark.parametrize("force_miss", [False, True])
def test_patrol_rewards_only_a_settled_hit_at_table(tmp_path, monkeypatch, force_miss):
    from tests.test_lock_choices import install

    install(monkeypatch, "d20_result", lambda *args: {
        "source_id": "test:c16.patrol_nat20", "operation": "replace", "natural_result": 20})
    if force_miss:
        install(monkeypatch, "before_attack", lambda *args: {
            "force_miss": True, "source_id": "test:c16.patrol_forced_miss", "label": "Patrol test: force a miss"})

    combat, table, mid, send, commit = fixture(
        tmp_path, [PATROL, G + "STAND_STILL", G + "STEEL_HEDGE", G + "COMPLEX_PATROL", G + "GUARDIAN_S_FOCUS"],
        foe_talents=[SEED], foe_ac=0,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 6}})
    patrol_id = candidate(table, mid, "Patrol Practice")
    answers = []
    for _ in range(8):
        result = send(patrol_id, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": prompt["choice"]["preferred"][:2]})
    else:
        raise AssertionError("Complex Patrol did not settle after choosing its two Zone talents")
    assert reload(tmp_path, mid).state.actors[OWNER].resources["resource:core.martial_focus"] == 0
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"]
               if o["destination"] == {"x": 4, "y": 5})
    _, prompts = resolve(combat, mid, send, cid, {"choice:needle.patrol_response": "respond"})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.patrol_response" for p in prompts)

    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]
    assert rolls and rolls[-1].payload["provisional_hit"] is True
    assert any(e.event_type == "ATTACK_FORCED_MISS" for e in engine.events) is force_miss
    guardian, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    if force_miss:
        assert guardian.resources.get("resource:core.martial_focus", 0) == 0
        assert engine._effective_speed(foe) > 0
    else:
        assert guardian.resources.get("resource:core.martial_focus", 0) == 1
        assert engine._effective_speed(foe) == 0
