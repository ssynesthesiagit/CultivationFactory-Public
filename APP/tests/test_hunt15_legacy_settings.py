"""Legacy selectors that predate the setting-only execution flag."""
import pytest
from tests.hunt15_support import LEFT, act, fight, reload, turn


@pytest.mark.parametrize("talent,button,condition,phrase", [
    ("TAL_DESTRUCTION_DESTRUCTIVE_BLAST", "Deepen the Calamity: more dice (1 CP a blast: 1 + 1 per 2 Cultivation Levels)", "condition:typed.destruction_deepen", "1 cultivation points"),
    ("TAL_MAGMA_LAVA_WALL", "Wall point", "condition:typed.wall_plan", "does not raise a wall"),
])
def test_legacy_selector_status_is_described_after_table_reload(tmp_path, talent, button, condition, phrase):
    combat, table, mid = fight(tmp_path, [talent])
    turn(table, mid, LEFT)
    result = act(table, mid, button)
    if result["status"] == "REACTION_REQUIRED":
        # Wall point is a free square selector (no Action, no cost), so the table's deferred
        # placement picker asks which square. Answer with the first legal square the old eager
        # menu offered, then let the same action commit; no other prompt belongs to this case.
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == "choice:placement_menu.square", prompt
        result = act(table, mid, button, [{**prompt["context"], "selection": "USE",
                                          "option_ids": [prompt["choice"]["options"][0]["id"]]}])
    assert result["status"] == "COMMITTED", result
    reload(combat, mid)
    row = next(c for a in table.state(mid)["presentation"]["actors"] for c in a["conditions"] if c["condition_id"] == condition)
    assert phrase in row["rule_text"]
    assert "Rule description unavailable" not in row["detail"]
