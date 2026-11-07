"""Manual reminders through a committed table and a fresh saved-fight reload."""
import json
from tests.hunt15_support import LEFT, act, fight, reload, turn
from combat.history_feed import format_history_feed

REMINDER_PREFIX = ("River Keeper's Test setup: additional effect reminder. "
                   "Resolve only effects that the recorded outcomes have not already applied. Rule reminder:")


def kept_rule(rider: str) -> str:
    """The printed rule a reminder has to keep, read from the authority the engine loaded.

    The provenance note the reviewed row keeps beside the printed text is not the rule, and the card's own " ... " gap
    is written closed up by the log filter. Read from the built authority, so this holds on the public copy, whose
    exported authority carries the same words the engine loaded.
    """
    body = rider.split(" -- ")[0].strip().strip("'")
    return " ".join(body.split("...")[-1].split())


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


def test_hunt87_demon_seed_rider_is_clean_in_a_committed_table_feed(tmp_path):
    """hunt87 finding 1 at the level it showed: a reminder line in a played fight.

    A hand-played fight printed Demon Seed's reminder into the player's log naming
    the internal id ``condition:typed.stance.demon_seed`` and reporting that "the
    reaction/passive compiler ... has no generic precondition-on-condition hook".
    The row is read from the built authority the engine loads, so this fails if the
    data regresses, if the authority is not rebuilt, or if the log filter stops
    removing engine notes -- and it asserts the ruling survives, so deleting the
    reminder cannot pass. The raw event keeps the full text either way.
    """
    from pathlib import Path

    authority = json.loads((Path(__file__).resolve().parents[1] / "authority" /
                            "Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))
    riders = authority["mechanics"]["TAL_DAEMONIC_CULTIVATION_DEMON_SEED"]["riders"]
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"],
                               effects=[{"type": "rider", "evidence": rider} for rider in riders])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert [e.payload["rider"] for e in engine.events if e.event_type == "GM_RIDER"] == riders, (
        "the raw event must keep the reviewed text as evidence")
    lines = [row["summary"] for row in table.events(mid, 0)["events"] if row["event_type"] == "GM_RIDER"]
    assert len(lines) == 2, f"both Demon Seed reminders must reach the log, got {lines}"
    line = " ".join(lines)
    for junk in ("condition:typed", "compiler", "precondition-on-condition", "no generic"):
        assert junk not in line, f"engine note {junk!r} reached the player's fight log:\n{line}"
    # Heaven-Spiting Recovery left this reminder on 2026-10-25: the engine refuses it
    # while Demon Seed is down (combat/ext/daemonic_riders.py row_allowed and lethal_damage,
    # pinned by tests/test_a2_daemonic.py::test_recovery_no_seed_or_no_affordable_pool_offers_nothing),
    # so the GM is no longer asked about it. The remaining decisions are Overdraw's saving throw and Borrow the
    # Monster's Shape's, and each reminder must carry its own printed rule, not merely name the ability.
    for rider in riders:
        assert kept_rule(rider) in line, (
            f"the rule the GM is asked to apply is gone:\n{line}")
    for summary in lines:
        assert summary.startswith(REMINDER_PREFIX), summary
