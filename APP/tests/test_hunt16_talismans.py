"""Talisman Wall pays only with prepared talismans, through table commit/reload."""
import pytest

from combat.ext.talismans import EMERGENCY, PREPARED
from combat.ext.docket_walls import stats
from tests.hunt12_support import FOE, ME, STAMINA, candidate, fight, reload, send
from tests.test_lock2_persistence import act

WALL = "tianxia.talent.talismans.talisman_wall"


def next_turn(table, mid):
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("strokes", [0, 2])
@pytest.mark.parametrize("all_prepared", [False, True])
def test_wall_consumption_matches_hp_after_reload(tmp_path, auto, strokes, all_prepared):
    combat, table, mid = fight(tmp_path, [WALL])
    for _ in range(strokes):
        stroke = candidate(combat, mid, lambda c: c.display_name == "Emergency Stroke")
        assert send(combat, table, mid, stroke)["status"] == "COMMITTED"
        next_turn(table, mid)
    before = reload(tmp_path, mid).state.actors[ME].resources.copy()
    assert before[EMERGENCY] == strokes
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    foe_at = combat._load_session(mid).engine.state.actors[FOE].position
    chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith(WALL) and c.destination == foe_at)
    response = send(combat, table, mid, chosen, auto=auto)
    answers = []
    if response["status"] == "REACTION_REQUIRED":
        prompt = response["reaction"]
        options = prompt["choice"]["options"]
        assert len(options) == before[PREPARED]
        assert "Talisman Wall" in options[0]["label"]
        selected = options[0 if all_prepared else -1]["id"]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [selected]})
        response = send(combat, table, mid, chosen, answers, auto=auto)
    assert response["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    after = engine.state.actors[ME].resources
    consumed = before[PREPARED] - after[PREPARED]
    assert consumed == (before[PREPARED] if auto or all_prepared else 1)
    assert after[EMERGENCY] == strokes
    assert before[STAMINA] - after[STAMINA] == consumed
    walls = [z for z in engine.state.zones.values() if z.source_definition_id.endswith(WALL)]
    assert walls
    assert all(z.trigger_profile["numbers"]["talismans"] == consumed for z in walls)
    assert all(stats(z)["hp"] == consumed * 10 for z in walls)
    notes = [e.payload.get("rider", "") for e in engine.events if e.event_type == "GM_RIDER"]
    assert any(f"{consumed * 10} hit points" in n and f"{consumed} talisman" in n for n in notes)
    if consumed == before[PREPARED]:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="MANUAL")
        next_turn(table, mid)
        chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith(WALL))
        assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
        empty = reload(tmp_path, mid)
        assert empty.state.actors[ME].resources == after
        assert len(empty.state.zones) == len(engine.state.zones)
