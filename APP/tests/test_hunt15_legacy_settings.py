"""Legacy selectors that predate the setting-only execution flag."""
import pytest
from tests.hunt15_support import LEFT, act, fight, reload, turn


@pytest.mark.parametrize("talent,button,condition,phrase", [
    ("TAL_DESTRUCTION_DESTRUCTIVE_BLAST", "Deepen the Calamity: on", "condition:typed.destruction_deepen", "1 cultivation points"),
    ("TAL_MAGMA_LAVA_WALL", "Wall point", "condition:typed.wall_plan", "does not raise a wall"),
])
def test_legacy_selector_status_is_described_after_table_reload(tmp_path, talent, button, condition, phrase):
    combat, table, mid = fight(tmp_path, [talent])
    turn(table, mid, LEFT)
    assert act(table, mid, button)["status"] == "COMMITTED"
    reload(combat, mid)
    row = next(c for a in table.state(mid)["presentation"]["actors"] for c in a["conditions"] if c["condition_id"] == condition)
    assert phrase in row["rule_text"]
    assert "Rule description unavailable" not in row["detail"]
