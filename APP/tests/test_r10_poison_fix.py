"""Virulent Presence applied at the real victim turn start survives the owner turn."""
import pytest
from combat.ext import poison
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_tabletop_hunt6 import LEFT, RIGHT, table_fight
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import fixed_dice, cast_sender, commit, answer


@pytest.mark.parametrize("option", ["Poisoned", "No Reactions", "Healing halved"])
def test_presence_target_turn_expiry_through_cast_commit_and_reload(monkeypatch, tmp_path, option):
    combat, table, mid = table_fight(tmp_path, [poison.SOVEREIGN, poison.PRESENCE], cl=20, ask=True, ally_talents=[])
    fixed_dice(monkeypatch, [1] * 40)
    commit(cast_sender(combat, table, mid, "Venom-Sovereign Incarnation"))
    for _ in range(4):
        state = table.state(mid)
        menu = state["menu"]
        send = lambda answers=(): table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
        result = send()
        if result["status"] == "REACTION_REQUIRED":
            prompt = result["reaction"]
            assert "Right" in prompt["moment"] and "starts" in prompt["moment"]
            assert send([answer(prompt, option)])["status"] == "COMMITTED"
            break
        assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    victim = loaded.engine.state.actors[RIGHT]
    deadline = f"START_OF_TURN_AT:{RIGHT}:{victim.turns_started + 1}"
    rows = {**victim.conditions, **victim.modifiers}
    affected = {iid for iid, row in rows.items() if row.expires_on == deadline or
                row.expires_on == "START_OF_SOURCE_NEXT_TURN" and row.source_actor_id == RIGHT}
    assert affected, [(e.event_type, e.payload) for e in loaded.engine.events[-8:]]
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    victim = loaded.engine.state.actors[RIGHT]
    assert affected <= set(victim.conditions) | set(victim.modifiers)
    # Travel out of the aura so the next victim turn cannot replace the effect.
    commit(cast_sender(combat, table, mid, "Dash"))
    commit(cast_sender(combat, table, mid, "Move", at=(9, 3)))
    for _ in range(4):
        assert act(table, mid, "end")["status"] == "COMMITTED"
        if table.state(mid)["menu"]["actor_id"] == RIGHT:
            break
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    victim = loaded.engine.state.actors[RIGHT]
    assert loaded.engine.state.current_actor_id == RIGHT
    assert not affected & (set(victim.conditions) | set(victim.modifiers))
    assert loaded.mechanical.replay()["status"] == "PASS"
