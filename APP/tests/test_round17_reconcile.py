"""Ask-me AI owners still choose automatically through table commit/reload."""

import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT, script
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, table_fight


@pytest.mark.parametrize("other_turn", [False, True])
def test_ai_disaster_owner_automatically_rewrites_on_either_turn(monkeypatch, tmp_path, other_turn):
    from combat.gate4_engine import Gate4ControllerEngine

    combat, table, mid = table_fight(tmp_path, ["TAL_FATE_REWRITE_THE_DISASTER"], ask=True)
    active = RIGHT if other_turn else LEFT
    if other_turn:
        while table.state(mid)["menu"]["actor_id"] != RIGHT:
            assert act(table, mid, "end")["status"] == "COMMITTED"
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    combat.set_controller_mode(mid, actor_id=active, controller_mode="LOCAL_AUTO")
    original = Gate4ControllerEngine._append_event

    def roll(engine, event_type, *args, **kwargs):
        result = original(engine, event_type, *args, **kwargs)
        if event_type == "INTENT_ACCEPTED" and kwargs.get("actor_id") == active:
            script(engine, [2])
            engine._roll_save(engine.state.actors[LEFT], "DEX", 16, args[0])
        return result

    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", roll)
    assert table.auto_step(mid, 0)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rewrites = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN"]
    assert len(rewrites) == 1
    assert rewrites[0].payload["result"]["natural_result"] == 20
    assert loaded.engine.state.actors[LEFT].resources["resource:core.qi"] == 18
    assert loaded.mechanical.replay()["status"] == "PASS"
