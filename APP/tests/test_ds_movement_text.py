"""Manual owner's prompt for another creature's voluntary move."""
from combat import typed_reactions
from tests.test_tabletop_hunt6 import table_fight, on_hold, RIGHT, HOLD
from tests.test_lock2_persistence import act


def test_unbroken_pursuit_names_the_mover_once(tmp_path, monkeypatch):
    combat, table, mid = table_fight(tmp_path, ["TAL_ATHLETICS_UNBROKEN_PURSUIT"], ask=True, ally_talents=[])
    on_hold(monkeypatch, lambda engine: typed_reactions.on_creature_event(engine, engine.state.actors[RIGHT], "moved", moved_ft=5))
    result = act(table, mid, HOLD)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["reaction"] == "Unbroken Pursuit"
    assert prompt["trigger"] == "Right moved willingly."
    assert prompt["moment"] == "Right moved willingly."
