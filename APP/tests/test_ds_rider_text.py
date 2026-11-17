"""Manual reminders through a committed table and a fresh saved-fight reload.

The exact printed Demon Seed reminder wording is pinned in tests/test_ds_rider_text_pins.py, which stays local (the
public copy scrambles that prose). This file holds the transform-safe half of the same regressions, so it runs on the
public copy too.
"""
from tests.hunt15_support import LEFT, act, fight, reload, turn
from combat.history_feed import format_history_feed

REMINDER_PREFIX = ("River Keeper's Test setup: additional effect reminder. "
                   "Resolve only effects that the recorded outcomes have not already applied. Rule reminder:")


def test_rider_card_and_designer_notes_do_not_become_table_outcomes(tmp_path):
    reminder = "If you deliver the dose through a weapon attack, make the weapon attack normally instead"
    raw = reminder + " / #### Deliver the Dose Action Type: Action Range: 60 feet"
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"],
        effects=[{"type": "rider", "evidence": raw},
                 {"type": "rider", "evidence": "Simplified from the printed triggers; coordinator audit 2026-09-28"}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert [e.payload["rider"] for e in engine.events if e.event_type == "GM_RIDER"] == [
        raw, "Simplified from the printed triggers; coordinator audit 2026-09-28"]
    lines = [r["summary"] for r in table.events(mid, 0)["events"] if r["event_type"] == "GM_RIDER"]
    prefix = REMINDER_PREFIX
    # DS10 #2: the designer note is a note about the typing, so it leaves no rule to
    # remind the GM about. Printing the bare prefix named no effect at all, so the
    # line is dropped; the raw event above still keeps the full evidence.
    assert lines == [prefix + " " + reminder + "."]


def test_recorded_adjudication_text_survives_table_feed():
    riders = [
        ("Speech-Knot Point", "Speech-Knot Point: the action falters and fails; its resources were not spent. "
         "The printed rule does not spend the Action either: the GM may let it act again."),
        ("Hindering Projectile", "Hindering Projectile: the target received healing. The GM decides whether it "
         "sufficiently seals each lodged wound; no numerical threshold is printed."),
    ]
    events = [{"sequence": i, "event_type": "GM_RIDER", "actor_id": "a", "target_ids": ["b"],
               "source_definition_id": source,
               "payload": {"adjudication_text": True, "rider": text}}
              for i, (source, text) in enumerate(riders, 1)]
    rows = format_history_feed(events, [], pre_state=None, post_state={},
                               actor_names={"a": "Mira", "b": "Ren"}, definition_names={})
    summaries = [row["summary"] for row in rows]
    assert "falters and fails" in summaries[0]
    assert "resources were not spent" in summaries[0]
    assert "GM may let it act again" in summaries[0]
    assert "GM decides whether it sufficiently seals each lodged wound" in summaries[1]
