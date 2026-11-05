"""OCF7 blocker 1: a self-teleport's log line named the square it came from as "unknown cell".

    Evidence (oc11-A01 s0, verbatim from the fight journal):
        "MOVEMENT_COMMITTED | Tabik Damu teleported from unknown cell to (4, 1)."

"unknown cell" is neither a place nor a rule, so every 25.x self-teleport in the
playtest read that way (six fights, eight events). The movement record itself always
carried the route -- combat/typed_executor.py ``_teleport`` writes
``path=[start, destination]`` and every other teleport producer does the same, which is
the documented movement-record contract ("``path`` is the whole route the mover actually
stood on", combat/ext/__init__.py) -- but the table's incremental feed never sees a
pre-move state (combat/tabletop_service.py ``events`` passes ``pre_state=None``), so
combat/history_feed.py had nothing to name and printed the literal instead.

Pinned here at the level the owner saw it: a real table, the real unbindable self-teleport
(the same one combat/ext/teleport_steps.py asks about), the real journal feed, and the
feed of a fight read back by a brand new service after a save.
"""
from __future__ import annotations

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_mmx108_teleport_map_pick import OWNER, _first_pause, _group, _menu, _moved, _send, _table

OWNER_NAME = OWNER.rsplit(".", 1)[-1]


def _teleport(table, mid, wanted_index=-1):
    """Land the owner's teleport on one of the squares it offers; return (before, after)."""
    group = _group(_menu(table, mid), "Empty Step")
    prompt = _first_pause(table, mid, group)
    assert prompt is not None, "the teleport must pause to ask where to land"
    before = _moved(table.combat, mid)
    option = prompt["choice"]["options"][wanted_index]
    result = _send(table, mid, group["options"][0]["candidate_id"],
                   [{**prompt["context"], "selection": "USE", "option_ids": [option["id"]]}])
    assert result["status"] == "COMMITTED", result["status"]
    return before, _moved(table.combat, mid)


def _feed(service, mid):
    return [row for row in service.events(mid, 0)["events"] if row.get("event_type") == "MOVEMENT_COMMITTED"]


def test_a_self_teleport_log_line_names_the_square_it_came_from(tmp_path):
    combat, table, mid = _table(tmp_path)
    before, after = _teleport(table, mid)
    assert (before.x, before.y) != (after.x, after.y), "the teleport did not move the creature"
    lines = [row["summary"] for row in _feed(table, mid)]
    assert lines, "the feed showed no movement at all"
    assert not [line for line in lines if "unknown cell" in line], (
        f"the feed still names a square it does not know: {lines}")
    teleports = [line for line in lines if "teleport" in line]
    assert teleports, f"no teleport line in the feed: {lines}"
    # The feed names the fighter by its sheet name where it has one and by its id otherwise.
    assert teleports[-1].endswith(f" teleported from ({before.x}, {before.y}) to ({after.x}, {after.y})."), teleports[-1]
    assert teleports[-1].startswith(OWNER_NAME), teleports[-1]


def test_the_origin_is_read_back_out_of_the_saved_fight(tmp_path):
    """Item 7: the line is read from the saved journal by a new service, not recomputed live."""
    combat, table, mid = _table(tmp_path)
    before, after = _teleport(table, mid)
    fresh = TabletopService(CombatService(ROOT, combat.userdata_root), combat.userdata_root)
    line = next(row["summary"] for row in _feed(fresh, mid) if "teleport" in row["summary"])
    assert f"from ({before.x}, {before.y})" in line, line
    assert f"to ({after.x}, {after.y})" in line, line


def test_no_movement_line_in_the_feed_names_a_square_it_does_not_know(tmp_path):
    """The whole feed, not just the teleport: "unknown cell" is never a place a player is shown."""
    combat, table, mid = _table(tmp_path)
    _teleport(table, mid)
    lines = [row["summary"] for row in table.events(mid, 0)["events"]]
    assert not [line for line in lines if "unknown cell" in line], lines
