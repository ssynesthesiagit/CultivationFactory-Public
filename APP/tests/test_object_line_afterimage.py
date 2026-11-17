"""Battle history reflects objects without invented hit points."""
from combat.gate2_rolls import DeterministicRollAuthority
from combat.history_feed import _object_line
from tests.hunt15_support import act, reload
from tests.test_mgr_t14_afterimage_attacks import OWNER, producer, setup  # noqa: F401


def test_afterimage_interception_history_has_one_destruction_and_no_placeholders(tmp_path, monkeypatch):
    c, table, mid = setup(tmp_path, "image-history")
    before = reload(c, mid)
    start = len(before.events)
    original_roll = DeterministicRollAuthority.roll

    def forced_one(self, dice, **kwargs):
        result = original_roll(self, dice, **kwargs)
        if kwargs["reason"].startswith("TARGET_INTERCEPT:"):
            assert dice.sides == 2
            return result.model_copy(update={"dice": (1,), "total": 1})
        return result

    monkeypatch.setattr(DeterministicRollAuthority, "roll", forced_one)
    assert act(table, mid, "Test strike", target_id=OWNER)["status"] == "COMMITTED"
    events = reload(c, mid).events[start:]
    decision = next(e for e in events if e.payload.get("kind") == "afterimage_targeting")
    assert decision.payload["result"] == 1
    sequences = {e.sequence for e in events}
    rows = [row for boundary in c.history(mid)["boundaries"] for row in boundary["feed"]
            if row["event_sequence"] in sequences]
    summaries = [row["summary"] for row in rows]
    assert not any("None" in s or "Detailed breakdown was not recorded" in s for s in summaries), [
        (r["summary"], r["raw"]) for r in rows
    ]
    assert sum("destroyed" in s.lower() and "afterimage" in s.lower() for s in summaries) == 1


def test_object_update_without_damage_keeps_recorded_hit_points():
    line = _object_line({"object": {"component": {"name": "Gate"},
                                     "current_hp": 4, "maximum_hp": 10}},
                        "Mira", "mira", "Repair", "repair")
    assert "4 of 10 hit points" in line
