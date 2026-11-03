"""INTERCEPTMSG1 table-level regressions: the plain interception sentence on a real campaign table, and the
interception die reaching a visible table row for both outcomes.

LOCAL-ONLY BY DESIGN. This walk-through compiles a real character from the typed-mechanics authority and drives
the shipped table service, so its import closure includes the owner authority files and ``APP/combat/ext/``; the
public publish gate withholds those today (``contains text of a redacted source passage``). tests/ and the report
explain the gate reason. The feed wording itself is covered publicly by tests/test_intercept_msg_1_log.py.
"""
from tests.hunt15_support import act, reload
from tests.test_mgr_t14_afterimage_attacks import ATTACKER, OWNER, producer, setup  # noqa: F401 (autouse seed fixture)


def _strike(tmp_path, seed):
    c, t, mid = setup(tmp_path, seed)
    start = len(reload(c, mid).events)
    assert act(t, mid, "Test strike", target_id=OWNER)["status"] == "COMMITTED"
    e = reload(c, mid)
    decision = next(v for v in e.events[start:] if v.payload.get("kind") == "afterimage_targeting")
    feed = [item for boundary in c.history(mid)["boundaries"] for item in boundary["feed"]]
    return e, decision.payload["result"], feed


def test_real_table_roll_one_names_attacker_ability_target_and_afterimage(tmp_path):
    for seed in ("image-1", "image-2", "image-3", "image-4"):
        e, result, feed = _strike(tmp_path / seed, seed)
        if result == 1:
            break
    else:
        raise AssertionError("no seed rolled 1")
    attacker, target = e.state.actors[ATTACKER].display_name, e.state.actors[OWNER].display_name
    lines = [i["summary"] for i in feed if "rolled 1" in i["summary"]]
    assert len(lines) == 1, lines
    line = lines[0]
    assert attacker in line and "Test strike" in line and target in line and "afterimage" in line.lower()
    assert "rolled 1" in line and ATTACKER not in line and OWNER not in line


def test_real_table_roll_two_targets_normally(tmp_path):
    for seed in ("image-1", "image-2", "image-3", "image-4"):
        e, result, feed = _strike(tmp_path / seed, seed)
        if result == 2:
            break
    else:
        raise AssertionError("no seed rolled 2")
    target = e.state.actors[OWNER].display_name
    lines = [i["summary"] for i in feed if "rolled 2" in i["summary"]]
    assert len(lines) == 1, lines
    assert "targets" in lines[0] and target in lines[0] and "normally" in lines[0]
    assert not any("instead" in i["summary"] for i in feed)


def _strike_with_roll(tmp_path, seed):
    c, t, mid = setup(tmp_path, seed)
    start = len(reload(c, mid).events)
    assert act(t, mid, "Test strike", target_id=OWNER)["status"] == "COMMITTED"
    e = reload(c, mid)
    decision = next(v for v in e.events[start:] if v.payload.get("kind") == "afterimage_targeting")
    return e, decision.payload["result"], decision.payload["roll_id"], t, mid


def test_table_links_the_afterimage_die_to_a_visible_row_for_both_outcomes(tmp_path):
    # Finding 2: the table animates a die only through a visible row carrying its roll_id.
    seen = set()
    for seed in ("image-1", "image-2", "image-3", "image-4"):
        e, result, roll_id, t, mid = _strike_with_roll(tmp_path / seed, seed)
        seen.add(result)
        out = t.events(mid, 0)
        assert [r for r in out["events"] if r.get("roll_id") == roll_id], (result, [r.get("summary") for r in out["events"]])
        assert [d["roll_id"] for d in out["dice"] if d["roll_id"] == roll_id] == [roll_id]
        if {1, 2} <= seen:
            break
    assert {1, 2} <= seen
