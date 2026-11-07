"""Every printed Vector of a "choose one" menu gets its own button, and a GM rider is never empty.

Hunt 105 #1 (round 24, live 42e43e14): AIR "Gather Current" prints five Vectors -- "choose one Vector:
Lift, Press, Scatter, Carry, Turn" -- but the table offered only four, so Carry was unreachable, and
because the compiler only recognised a rider clause as "some other option's text" when its head matched
an *offered* option label, the unoffered ``Carry:`` clause survived on every remaining option. Pressing
"Gather Current: Press" therefore announced a GM rider quoting the Carry Vector, as if it were the
pressed Vector's own caveat.

Hunt 105 #2: a GM rider could be emitted with no rule text at all -- "the GM must resolve this additional
effect; the table has not applied it." and nothing to apply. The hunt blamed the 480-character cap in
``combat/history_text.py``; the reported evidence does not support that (Breathless Chamber's two riders
are 89 and 174 characters). The real cause is that the commentary filter treats the bare word "GM" as
build commentary, so owner rules prose that merely mentions the GM ("against a DC set by the GM") was
discarded whole.

Both are fixed generally: ``factory_compiler._gm_lines`` now attributes a clause to any choice the printed
text of the menu offers (offered or not), and ``history_text.rider_text`` falls back to keeping any clause
that is not build scaffolding, then shortens a long reminder instead of emptying it.

MMX103f1 (review findings 1-3) -- the rules text shown to the GM is now the *whole* rule:

* finding 1: ``rider_text`` tested ``_without_asides(clause)`` but formatted the original clause, so a
  clause whose build note sat in brackets was announced *with* the note ("... may gain a Faultline Mark
  (GM: the table places Glass Surfaces on their user and its own areas, not between creatures)"). The
  cleaned clause is now what is stored and formatted.
* finding 2: a reminder over the 480-character cap whose first 240 characters held no sentence end was cut
  mid-word, so the GM was told to resolve an effect whose clause was missing. Whole sentences are now kept
  whole, and a first sentence longer than the cap is kept whole rather than cut.
* finding 3: the regressions below no longer skip a Vector that has no button, no longer accept an
  uncommitted action as a pass, and no longer use ``history_text``'s own filter as the oracle for what a
  reminder should contain: the expected Vector text and the expected reminder strings below are written out
  here, and the whole-authority guard checks both directions with a list of build notes of its own.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from combat import history_text
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

from tests.h1_support import ROOT, sheet
from tests.h48_table_support import fixture

APP = Path(__file__).resolve().parents[1]
GATHER = "AIR_BASE_GATHER_CURRENT"
OWNER = "actor:factory.r1i-owner"
PRINTED_VECTORS = ["Lift", "Press", "Scatter", "Carry", "Turn"]

# The reminder each Vector owes the GM, transcribed from the owner's printed card rather than read back out
# of the authority blob, so the table assertions state what a player must be told. Press and Turn are typed in
# full by the engine (a mark and an air-ranged row), so the table applies them itself and owes no reminder.
VECTOR_REMINDER = {
    "Lift": "A willing creature that starts in or enters the Current before it ends may add 5 feet to one "
            "jump or ignore the first 10 feet of falling damage before the Current ends.",
    "Scatter": "Nonmagical smoke, loose dust, harmless vapor, light fog, or similar airborne material in the "
               "Current is dispersed or shifted 10 feet.",
    "Carry": "A whisper, scent, ribbon, Tiny unattended object weighing no more than 1 pound, or comparable "
             "harmless sign may be carried from one point in the Current to another point in the Current.",
}
SELF_APPLIED_VECTORS = ["Press", "Turn"]
PREFIX = "additional effect reminder. Resolve only effects that the recorded outcomes have not already applied."

# A first printed sentence that is longer than the 480-character cap and has no sentence end inside it, which
# is what the old cap handling cut in half. The printed clause has to reach the GM whole or not at all.
OVERLONG_FIRST_SENTENCE = (
    "The Game Master reads the whole vessel aloud in your hearing and everyone present hears every word of it, "
    "then resolves whether the Vessel suffers backlash from the words that were spoken in that hearing, "
    "and if it does the backlash is applied to the Vessel rather than to you, "
    "and no shorter reading of this single printed sentence exists anywhere on the card at all, "
    "so the whole of it is kept even though that makes this reminder longer than a reader expects to sit "
    "through before the first thing they can do about it")

# Notes the owner wrote for the builders rather than for the players. The list belongs to this test, not to
# the module under test: a guard that imported history_text's own filter could not tell a rule that was wrongly
# hidden from one that was correctly hidden (MMX103 review finding 3). Whole words only: "nonauditory" and
# "in and out of combat" are rules prose that merely contain a build word.
BUILD_NOTE_PATTERN = re.compile(
    r"\b(?:coordinator audit|not automated|action type:|printed riders|adjudication|the table|"
    r"simplified from|simplified to|implemented|implementation)\b|\.py\b|combat/", re.I)

def _mechanic() -> dict:
    return json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"][GATHER]

def _catalog_row(mechanic: dict, actor_id: str) -> dict:
    bundle = compile_character(sheet([GATHER], cl=10, dc=16), actor_id=actor_id,
                               typed_authority={"mechanics": {GATHER: mechanic}})
    return {row["display_name"]: row
            for row in bundle["action_catalog"] if row["display_name"].startswith("Gather Current")}

def _riders(row: dict) -> list[str]:
    return list(row["parameters"]["typed"].get("riders") or [])

def _owner_menu(table, match_id, commit) -> dict:
    for _ in range(30):
        menu = table.state(match_id)["menu"]
        if menu and menu["actor_id"] == OWNER:
            return menu
        commit(menu["end_turn"])
    raise AssertionError("the owner never received a turn")

def _press(table, match_id, commit, vector: str) -> dict:
    """Choose ``vector`` on the table's own menu. A Vector with no button is a failure, not a skipped case."""
    menu = _owner_menu(table, match_id, commit)
    options = [option for group in menu["actions"] for option in group["options"]
               if option["label"].startswith(f"Gather Current: {vector} ")]
    assert options, f"{vector} has no button on the table menu: {sorted(o['label'] for g in menu['actions'] for o in g['options'])[:8]}"
    return commit(options[0]["candidate_id"])

def _feed(table, match_id, engine) -> list[dict]:
    return list(table.events(match_id, 0, engine=engine)["events"])

# ------------------------------------------------------------------ the table: every printed Vector is a button
def test_every_printed_vector_is_offered_as_its_own_button_at_the_table(tmp_path):
    """The bug showed as a missing button, so it is asserted on the table's own menu (fight, not compiler)."""
    combat, table, match_id, _send, _commit = fixture(tmp_path, [GATHER], seed="gather-vectors-offered")
    menu = table.state(match_id)["menu"]
    assert menu["actor_id"] == OWNER
    labels = [option["label"] for group in menu["actions"] for option in group["options"]]
    offered = {label.rsplit(" at ", 1)[0] for label in labels if label.startswith("Gather Current")}
    missing = [vector for vector in PRINTED_VECTORS if f"Gather Current: {vector}" not in offered]
    assert not missing, f"printed Vectors with no button: {missing}; the menu offered {sorted(offered)}"
    assert offered == {f"Gather Current: {vector}" for vector in PRINTED_VECTORS}, offered
    assert combat is not None

# ------------------------------------------------------------------ the table: pressing a Vector commits and quotes only that Vector
def test_pressing_a_vector_commits_and_announces_that_vectors_own_rule(tmp_path):
    """The hunt's evidence was a log line: pressing Press announced "Rule reminder: Carry: ...". Each Vector
    is pressed on its own turn through the real table, committed, and read back from the table's own feed."""
    for vector, reminder in VECTOR_REMINDER.items():
        combat, table, match_id, _send, commit = fixture(tmp_path / vector, [GATHER],
                                                        seed=f"gather-press-{vector.lower()}")
        result = _press(table, match_id, commit, vector)
        assert result["status"] == "COMMITTED", f"{vector} was not applied: {result['status']}"
        engine = combat._load_session(match_id).engine
        lines = [row["summary"] for row in _feed(table, match_id, engine) if row["event_type"] == "GM_RIDER"]
        assert len(lines) == 1, f"{vector} announced {len(lines)} reminders, expected its own: {lines}"
        assert lines[0] == f"Owner's Gather Current: {vector}: {PREFIX} Rule reminder: {vector}: {reminder}", lines[0]
        for other, text in VECTOR_REMINDER.items():
            if other != vector:
                assert text[:40] not in lines[0], f"pressing {vector} quoted {other}'s rule: {lines[0]}"

def test_a_fully_typed_vector_is_applied_and_remembers_no_one_else_vectors_rule(tmp_path):
    """Press is the Vector the hunt reported. The table marks Difficult Terrain itself, so it owes no reminder
    -- and above all it must not quote the Carry Vector it does not implement."""
    for vector in SELF_APPLIED_VECTORS:
        combat, table, match_id, _send, commit = fixture(tmp_path / vector, [GATHER],
                                                        seed=f"gather-self-{vector.lower()}")
        result = _press(table, match_id, commit, vector)
        assert result["status"] == "COMMITTED", f"{vector} was not applied: {result['status']}"
        engine = combat._load_session(match_id).engine
        lines = [row["summary"] for row in _feed(table, match_id, engine) if row["event_type"] == "GM_RIDER"]
        assert lines == [], f"pressing {vector} announced a rule reminder it has already applied: {lines}"
        created = [row for row in _feed(table, match_id, engine) if row["event_type"] == "ZONE_CREATED"]
        assert len(created) == 1, f"{vector} did not create its zone: {created}"

# ------------------------------------------------------------------ the table: Carry's zone is real and survives a reload
def test_carry_creates_its_current_zone_and_the_zone_survives_a_reload(tmp_path):
    """Checklist 7: whatever the fight stores must come back after a commit and a reload from disk. Carry is
    the Vector the hunt found unreachable, so it is also the one whose stored result is shown here."""
    combat, table, match_id, _send, commit = fixture(tmp_path, [GATHER], seed="gather-carry-zone")
    result = _press(table, match_id, commit, "Carry")
    assert result["status"] == "COMMITTED", result["status"]
    engine = combat._load_session(match_id).engine
    created = [event for event in engine.events
               if event.event_type == "ZONE_CREATED" and GATHER in str(event.source_definition_id)]
    assert len(created) == 1, f"Carry created {len(created)} zones"
    zone = created[0].payload["zone"]
    assert zone["source_definition_id"].endswith(f"{GATHER}#opt4"), zone["source_definition_id"]
    assert zone["owner_id"] == OWNER
    assert zone["trigger_profile"]["source_profile"]["mechanic_id"] == GATHER
    assert zone["trigger_profile"]["source_profile"]["duration_kind"] == "until_start_of_next_turn"
    assert zone["affected_cells"], "a Current with no cells under it does nothing"
    shown = [row for row in table.state(match_id)["presentation"]["zones"] if row["zone_id"] == zone["zone_id"]]
    assert len(shown) == 1, "the table does not show the Current it just created"

    fresh = CombatService(ROOT, tmp_path)
    fresh_table = TabletopService(fresh, tmp_path)
    reloaded = fresh._load_session(match_id).engine.state.zones.get(zone["zone_id"])
    assert reloaded is not None, "the Current did not survive the reload"
    assert reloaded.model_dump(mode="json") == zone, "the reloaded Current is not the one that was created"
    assert any(row["zone_id"] == zone["zone_id"] for row in fresh_table.state(match_id)["presentation"]["zones"])
    assert fresh._load_session(match_id).verify()["status"] == "PASS"
    assert fresh._load_session(match_id).mechanical.replay()["status"] == "PASS"

def test_carrys_current_uses_the_same_bounded_duration_as_the_vectors_that_existed_before_it(tmp_path):
    """Checklist 8: nothing may last the rest of the fight by accident. Carry copies the printed duration of
    the Vectors that were already on the table, so the zone it leaves behind is stored with the same bounded
    length and the same printed kind -- a number the engine already knows how to remove."""
    stored = {}
    for vector in ("Lift", "Carry"):
        combat, table, match_id, _send, commit = fixture(tmp_path / vector, [GATHER],
                                                        seed=f"gather-duration-{vector.lower()}")
        assert _press(table, match_id, commit, vector)["status"] == "COMMITTED"
        zone = next(iter(combat._load_session(match_id).engine.state.zones.values()))
        assert zone.active is True
        stored[vector] = (zone.duration_rounds, zone.trigger_profile["source_profile"]["duration_kind"])
        assert stored[vector][0] is not None, f"{vector} stored a zone with no length at all"
    assert stored["Carry"] == stored["Lift"], stored
    assert stored["Carry"][1] == "until_start_of_next_turn", stored

# ------------------------------------------------------------------ compiler: the general seam, independent of the data fix
def test_a_printed_choice_with_no_option_does_not_leak_onto_the_other_options():
    """The seam on its own, with the data fix deliberately undone (Carry removed again), so this fails
    without the compiler change and is not merely re-testing the added option."""
    mechanic = _mechanic()
    mechanic["options"] = [option for option in mechanic["options"] if option["label"] != "Carry"]
    assert "Carry:" in " ".join(mechanic["riders"]), "the printed Carry clause must be in the rider list"
    rows = _catalog_row(mechanic, "actor:factory.gather_unoffered_choice")
    assert not any("Carry" in label for label in rows), "the data fix added the option; undo it for this test"
    for label, row in rows.items():
        for rider in _riders(row):
            assert not rider.lower().startswith("carry:"), f"{label} quoted the unoffered Carry Vector: {rider!r}"

def test_each_option_keeps_only_its_own_printed_choice_text():
    rows = _catalog_row(_mechanic(), "actor:factory.gather_own_text")
    for label, row in rows.items():
        vector = label.rsplit(": ", 1)[-1]
        for rider in _riders(row):
            head = rider.split(":", 1)[0].strip().lower()
            assert head in {"", vector.lower()}, f"{label} carries another Vector's text: {rider!r}"

# ------------------------------------------------------------------ a GM rider is never emitted with no rule text

def test_no_reminder_in_the_whole_authority_shows_a_note_written_for_the_builders():
    """The removal half of the hunt's guard, over every compiled character.

    The oracle is this test's own list of build notes, not history_text's filter: a guard that imports the
    thing it is guarding cannot show that it kept the right words. Every reminder in the authority is
    produced here and read back; a note the owner wrote for the builders must not appear in any of them,
    whether it sat in brackets (MMX103 review finding 1) or in the middle of a clause.
    """
    mechanics = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"]
    leaked = []
    for mid, mechanic in sorted(mechanics.items()):
        for rider in mechanic.get("riders") or []:
            line = history_text.rider_text({"rider": str(rider)}, "Someone", mid, "")
            reminder = line.split("Rule reminder: ", 1)[1] if line and "Rule reminder: " in line else ""
            for match in BUILD_NOTE_PATTERN.finditer(reminder):
                leaked.append((mid, match.group(0), reminder[max(0, match.start() - 40):match.end() + 40]))
    assert not leaked, (f"{len(leaked)} reminders show a note written for the builders, e.g. "
                        f"{leaked[:5]}")

def test_no_reminder_in_the_whole_authority_is_cut_off_inside_a_rule():
    """The other half of finding 2, over every compiled character.

    A reminder longer than the readable limit is shortened, and says so. What it may never do is stop in the
    middle of a sentence: the old handling cut at the character limit and ended the reminder on a half word
    ("... whether the Vessel would suffer backl..."), so the GM was told to resolve an effect whose clause was
    missing. Truncated reminders therefore have to end on the end of a sentence, and untruncated ones are
    whole by construction.
    """
    mechanics = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"]
    clipped = []
    for mid, mechanic in sorted(mechanics.items()):
        for rider in mechanic.get("riders") or []:
            line = history_text.rider_text({"rider": str(rider)}, "Someone", mid, "")
            reminder = line.split("Rule reminder: ", 1)[1] if line and "Rule reminder: " in line else ""
            if not reminder.endswith(" ..."):
                continue  # whole reminder, nothing was cut
            if not reminder[:-4].rstrip().endswith((".", "!", "?", ";")):
                clipped.append((mid, reminder[-60:]))
    assert not clipped, (f"{len(clipped)} reminders stop in the middle of a rule, e.g. {clipped[:5]}")

def test_the_hunts_reported_riders_are_never_announced_without_their_rule_text():
    """The hunt's own contract, on the abilities it named, with the expected text written out here.

    It is deliberately not a claim about every rider in the authority: the filter this branch inherited
    discards ordinary rules prose that merely contains a build word ("Tame: Train one non-sapient Beast to
    obey commands in and out of combat.", "Common roles include: Field Hand; Kitchen Worker"), so while
    that stands a whole-corpus "nothing real is hidden" claim would be false. Those false positives are
    inherited, are recorded in the MMX103f1 report as a follow-up, and each one is a reminder a player
    cannot be shown -- not something this lane's two findings turned into.
    """
    reported = {
        "AIR_BASE_GATHER_CURRENT": ["Lift", "Scatter", "Carry"],
        "TAL_AIR_BREATHLESS_CHAMBER": None,
        "GLASS_BASE_FAULTLINE_MARKS": None,
    }
    mechanics = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"]
    for mid, vectors in reported.items():
        for rider in mechanics[mid]["riders"]:
            if vectors is not None and not any(rider.startswith(f"{vector}:") for vector in vectors):
                continue
            line = history_text.rider_text({"rider": rider}, "Liu Ling", mid, "")
            assert "Rule reminder: " in line, f"{mid} reaches the table with no rule text: {line}"
            assert PREFIX in line

def test_a_reminder_never_quotes_a_source_file():
    """Checklist 13: no code names in player-visible text. A build note inside an otherwise usable sentence
    is lifted out of it rather than taking the sentence with it."""
    line = history_text.rider_text(
        {"rider": "The ridge rises where you point (combat/ext/earth_ridge.py: the table cannot place it in the path)."},
        "Someone", "Spending a Burden Mark", "")
    assert "Rule reminder:" in line
    assert "earth_ridge.py" not in line and "combat/ext" not in line
    assert "The ridge rises where you point" in line, "the usable rule text must survive the stripped aside"

def test_a_pure_designer_note_is_still_not_shown_as_a_rule():
    """The other half of the contract: nothing but build commentary gets no "Rule reminder" at all."""
    line = history_text.rider_text({"rider": "Simplified from the printed triggers; coordinator audit 2026-09-28"},
                                   "Someone", "Test setup", "")
    assert line is None  # LIVE suppresses commentary-only rows rather than printing an empty reminder.

def test_the_reported_breathless_chamber_riders_keep_their_text():
    """The exact evidence from hunt 105 #2. Both riders mention the GM in ordinary owner prose, and both
    are far below the 480-character cap, so neither is about length."""
    chamber = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"]["TAL_AIR_BREATHLESS_CHAMBER"]
    assert chamber["riders"], "the reported evidence is gone; re-check the hunt report"
    for rider in chamber["riders"]:
        assert len(rider) < 480, "this test covers the commentary filter, not the length cap"
        line = history_text.rider_text({"rider": rider}, "Liu Ling", "Breathless Chamber", "")
        assert "Rule reminder:" in line, line
        assert PREFIX in line

# ------------------------------------------------------------------ a build note in brackets is not shown as part of the rule
def test_a_build_note_in_brackets_is_lifted_out_and_the_rule_around_it_survives():
    """MMX103 review finding 1, on the real Glass rider. Its last sentence is a rule; the note in brackets is
    a limitation of how the table places Glass Surfaces and is not part of the rule the GM has to apply."""
    glass = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"]["GLASS_BASE_FAULTLINE_MARKS"]
    assert glass["riders"], "the reported evidence is gone; re-check the hunt report"
    rider = glass["riders"][0]
    assert "(GM:" in rider, "this rider no longer carries the note the review reported"
    line = history_text.rider_text({"rider": rider}, "Liu Ling", "Faultline Marks", "")
    assert line == (f"Liu Ling's Faultline Marks: {PREFIX} Rule reminder: A creature that attacks through or "
                    "across a Glass Surface, or touches, breaks or relies on a Glass Surface you control, "
                    "may gain a Faultline Mark."), line
    assert "Glass Surfaces on their user" not in line, "the note came back into the rule text"

# ------------------------------------------------------------------ a long reminder is never cut inside a rule
def test_a_reminder_whose_first_sentence_is_over_the_cap_keeps_that_sentence_whole():
    """MMX103 review finding 2. The first printed sentence here is longer than the 480-character cap and has
    no sentence end inside it, so the old handling cut it mid-word and the GM was left to resolve an effect
    whose clause was missing."""
    assert len(OVERLONG_FIRST_SENTENCE) > 480, "this test needs a first sentence the cap cannot hold"
    line = history_text.rider_text(
        {"rider": f"{OVERLONG_FIRST_SENTENCE}. A second printed sentence. A third one."},
        "Someone", "Read the Vessel", "")
    assert "Rule reminder: " in line
    reminder = line.split("Rule reminder: ", 1)[1]
    assert reminder.startswith(f"{OVERLONG_FIRST_SENTENCE}."), f"the printed sentence was cut: {reminder}"
    assert not reminder.endswith(" ..."), "LIVE keeps every whole rule, including the following sentence"
    assert OVERLONG_FIRST_SENTENCE[:80] in reminder

def test_a_long_rider_preserves_every_sentence_and_is_never_emptied():
    long_rider = "First printed clause. " + " ".join(f"Clause {i} says something the GM must apply." for i in range(40))
    line = history_text.rider_text({"rider": long_rider}, "Someone", "Long Card", "")
    assert "Rule reminder:" in line
    reminder = line.split("Rule reminder:", 1)[1]
    assert "Clause 39 says something the GM must apply." in reminder, "LIVE keeps the final printed rule too"
    assert not reminder.endswith("..."), "a complete reminder is not labelled as an excerpt"
    assert "First printed clause." in reminder, "the first whole sentences are kept"
    body = reminder.rstrip(". ").removesuffix(" ...")
    assert body.endswith("apply"), f"a reminder must not end mid-sentence: {body[-40:]!r}"
