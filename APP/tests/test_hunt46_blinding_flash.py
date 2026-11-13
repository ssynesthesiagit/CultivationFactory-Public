"""Hunt 46: chosen area recipients pause, commit, reload, and replay at the table."""
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT


def test_blinding_flash_player_selects_area_recipients_through_table_reload(tmp_path):
    combat, table, mid = table_fight(tmp_path, ["RADIANCE_TAL_BLINDING_FLASH"])
    menu = table.state(mid)["menu"]
    group = next(group for group in menu["actions"] if "10-Foot Emanation" in group["label"])
    option = group["options"][0]
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                       table.state(mid)["last_sequence"], [])
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert "Blinding Flash" in prompt["moment"]
    assert "Left" in prompt["moment"] and "Ally" in prompt["moment"] and "Right" in prompt["moment"]
    assert "Constitution saving throw" in prompt["moment"]
    assert "Blinded until the end of your next turn" in prompt["moment"]
    assert "Cannot take Reactions until the start of your next turn" in prompt["moment"]
    assert "Cost: 2 Qi" in prompt["moment"]
    assert "Qi means Cultivation Points, your technique resource" in prompt["moment"]
    assert " CP" not in prompt["moment"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before

    answers = [{**prompt["context"], "selection": "USE", "option_ids": [RIGHT]}]
    state = table.state(mid)
    committed = table.act(mid, option["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
                          state["last_sequence"], answers)
    while committed["status"] == "REACTION_REQUIRED":
        p = committed["reaction"]
        answers.append({**p["context"], "selection": "DECLINE"})
        state = table.state(mid)
        committed = table.act(mid, option["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
                              state["last_sequence"], answers)
    assert committed["status"] == "COMMITTED", committed
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    saves = [event.actor_id for event in loaded.engine.events
             if event.event_type == "SAVE_ROLLED" and "RADIANCE_TAL_BLINDING_FLASH" in event.source_definition_id]
    assert saves and all(who == RIGHT for who in saves)
    assert not [c for c in loaded.engine.state.actors[ALLY].conditions.values() if c.condition_id.endswith(".blinded")]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_blinding_flash_cone_uses_aimed_area_roster_through_reload(tmp_path):
    combat, table, mid = table_fight(tmp_path, ["RADIANCE_TAL_BLINDING_FLASH"])
    state = table.state(mid)
    group = next(group for group in state["menu"]["actions"] if "15-Foot Cone" in group["label"])
    option = next(row for row in group["options"] if row.get("destination") == {"x": 6, "y": 5})
    result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
                       state["last_sequence"], [])
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert any(row["id"] == RIGHT for row in prompt["choice"]["options"])
    answers = [{**prompt["context"], "selection": "USE", "option_ids": [RIGHT]}]
    for _ in range(10):
        current = table.state(mid)
        result = table.act(mid, option["candidate_id"], current["menu"]["decision_id"],
                           current["menu"]["state_version"], current["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    saves = [event.actor_id for event in loaded.engine.events
             if event.event_type == "SAVE_ROLLED" and "RADIANCE_TAL_BLINDING_FLASH" in event.source_definition_id]
    assert saves == [RIGHT]
    assert loaded.mechanical.replay()["status"] == "PASS"
