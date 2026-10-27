"""Opt-in paired replay comparison for the AUTO17r1f1 review fixes (checklist 12).

The captures are two real-table fights played from a fixed seed, one in the baseline checkout ``fda5be3d`` and one in
this one; ``tests/auto17f1_replay_evidence.py`` makes them. Point ``AUTO17F1_PAIRED`` at four match folders --
``<baseline control>:<tip control>:<baseline smith>:<tip smith>`` -- and all the tests run::

    python -m tests.auto17f1_replay_evidence capture <owned-dir> control   # in the baseline checkout
    python -m tests.auto17f1_replay_evidence capture <owned-dir> smith     # in this checkout
    AUTO17F1_PAIRED=b:c:B:S python -m pytest tests/test_auto17f1_replay.py

The control is a fighter fight neither this lane nor the Blacksmith plug-in touches, so it must be byte-identical.
The smith pair is the Blacksmith this lane corrected, so its differences are named one path at a time and asserted to
be *exactly* those -- see ``smith_paths`` in the evidence module, which is the whole saved data of both fights and
nothing else. Each allowance names one value at its own path; nothing is allowed as a whole subtree.
"""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.auto17f1_replay_evidence import (DECLARATION_BUTTON, DECLARATION_FIELD, DECLARED, EVENT_CONDITION,
                                            MARK_CONDITION,
                                            NEW_BUTTON as NEW_ACTION,
                                            SMITH_PATHS, SNAPSHOT_DIGESTS, canonical_capture, commits,
                                            document_differences,
                                            full_differences, journal_differences, journal_sha256, smith_paths,
                                            stored_data)
from tests.hunt36_support import LEFT, ROOT

#: The one button this round added: the personal-work declaration can now be ended, not only set.
NEW_BUTTON = "seven_hammer.personal_work.end"


def _pairs():
    """The four captured match folders, as (control baseline, control tip, smith baseline, smith tip)."""
    raw = os.environ.get("AUTO17F1_PAIRED")
    if not raw:
        pytest.skip("set AUTO17F1_PAIRED to four captured match folders (baseline control:tip control:"
                    "baseline smith:tip smith) to run the paired replay comparison")
    folders = [Path(part) for part in raw.split(":") if part]
    assert len(folders) == 4, "AUTO17F1_PAIRED needs four match folders"
    control_baseline, control_tip, smith_baseline, smith_tip = folders
    return control_baseline, control_tip, smith_baseline, smith_tip


def test_the_unaffected_control_replay_is_byte_identical():
    baseline, tip, _smith_baseline, _smith_tip = _pairs()
    report = journal_differences(baseline, tip)
    assert report["baseline_journal_sha256"] == report["tip_journal_sha256"], report
    assert report["byte_identical"] is True
    assert report["baseline_transactions"] > 0 and report["transaction_counts_match"] is True
    assert report["differences"] == []
    assert _nothing_gained(report)


def test_the_smith_replay_gains_exactly_the_one_new_printed_button():
    _control_baseline, _control_tip, baseline, tip = _pairs()
    report = journal_differences(baseline, tip)
    assert report["transaction_counts_match"] is True
    gained = set(_smith_actions(tip)) - set(_smith_actions(baseline))
    assert {source for source in gained if source.endswith(NEW_BUTTON)} == gained, gained
    # The declaration's original button is still offered, and nothing the baseline offered was taken away.
    assert not set(_smith_actions(baseline)) - set(_smith_actions(tip))


def test_every_committed_transaction_is_identical():
    _control_baseline, _control_tip, baseline, tip = _pairs()
    from tests.replay_assertions import assert_replay_equal
    assert_replay_equal(commits(baseline), commits(tip))


# ----------------------------------------------------------------- the whole saved data, one named path at a time
def test_the_control_saved_data_differs_only_by_the_wall_clock():
    """The control fighter is one nothing here touches, so no *behaviour* may differ anywhere in its saved data."""
    baseline, tip, _smith_baseline, _smith_tip = _pairs()
    report = full_differences(baseline, tip, expected=DECLARED["control"])
    assert report["compared_artefacts"], "nothing was compared"
    assert report["unexpected"] == []
    assert report["allowed"], "the wall clock is recorded, so two runs cannot be identical to the byte"
    # The one difference that is not a plain timestamp is a digest, so it is worth proving what caused it rather than
    # waving at it: the lock file differs in one field, sharing that field makes the two files equal, and the digest
    # the manifest records is taken over those bytes. Nothing the fight *decided* is in there.
    assert _lock_digest_follows_only_the_clock(baseline, tip)


def _lock_digest_follows_only_the_clock(baseline: Path, tip: Path) -> bool:
    """Whether the two captures' MatchLock files differ only in when they were written, and the manifest digest is
    taken over exactly those bytes."""
    recorded = json.loads((tip / "Manifest.json").read_text())["file_identities"]["MatchLock.json"]
    if recorded != hashlib.sha256((tip / "MatchLock.json").read_bytes()).hexdigest():
        return False
    before, after = json.loads((baseline / "MatchLock.json").read_text()), json.loads(
        (tip / "MatchLock.json").read_text())
    if sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key)) != ["created_at_display"]:
        return False
    before["created_at_display"] = after["created_at_display"]
    return before == after


def test_the_smith_saved_data_differs_only_by_the_differences_this_round_intends():
    """The smith's whole saved data, compared value by value: every difference is one this round printed, and every
    printed difference actually happened (so the list cannot rot into allowing nothing).

    The allowance names each difference at the path it lives at, with both captures re-keyed by identity first
    (see ``canonical_capture``). Nothing is allowed as a whole subtree: not the compiled catalogue, not the actor's
    saved state, not the snapshots folder. A snapshot is compared as completely as the genesis state, and a snapshot
    file that exists on only one side is itself a difference."""
    _control_baseline, _control_tip, baseline, tip = _pairs()
    allowed = SMITH_PATHS + smith_paths(*_both_sides(baseline, tip))
    report = full_differences(baseline, tip, expected=allowed)
    assert report["compared_artefacts"], "nothing was compared"
    assert report["unexpected"] == []
    assert report["unused"] == [], "a declared difference no longer happens: say so, do not leave it allowed"


def _common_artefacts(baseline: Path, tip: Path) -> list[str]:
    """The files both captures wrote, which is what the snapshot allowances are named against."""
    return sorted(set(stored_data(baseline)) & set(stored_data(tip)))


def _both_sides(*matches: Path) -> tuple[dict, dict]:
    """Each capture's whole stored data, which is what the allowances are named against."""
    return tuple(stored_data(match) for match in matches)


def test_the_smith_saved_actor_state_shows_only_the_new_button():
    """The same claim, read the way a player would: the fighter is offered one action it was not offered before, and
    the rest of its sheet is untouched."""
    _control_baseline, _control_tip, baseline, tip = _pairs()
    gained = set(_smith_actions(tip)) - set(_smith_actions(baseline))
    assert gained and all(source.endswith(NEW_BUTTON) for source in gained), gained
    assert set(_smith_actions(baseline)) - set(_smith_actions(tip)) == set()


def test_the_two_saved_battles_differ_and_the_two_control_journals_do_not():
    """The per-mark deadlines are meant to change what is stored, so the smith journal is *not* byte-identical; the
    control's is. Stating both keeps "byte-identical" from being a claim nobody checked."""
    _control_baseline, control_tip, baseline, tip = _pairs()
    assert journal_sha256(control_tip) == journal_sha256(_control_baseline)
    assert journal_sha256(tip) != journal_sha256(baseline)


def test_both_tip_fights_are_real_saves_that_verify_and_replay():
    """Both tip fights are loaded by the real service and put through the real verification and the real event
    replay. This is the check that says the files the comparison reads are a save at all -- the earlier version of
    this test only asserted a file existed and compared a journal with itself, which is true of any directory."""
    _control_baseline, control_tip, baseline, tip = _pairs()
    for match in (control_tip, tip):
        session = _load_capture(match)
        assert session.verify()["status"] == "PASS", f"{match} does not verify"
        assert session.mechanical.replay()["status"] == "PASS", f"{match} does not replay to the same statuses"


def _load_capture(match: Path):
    """Open a captured fight with the real service, from the capture root (the folder holding ``Combat/Matches``)."""
    from combat.gate3_storage import decode_match_directory_name
    from combat.gate5_service import CombatService

    root = next(parent for parent in [match, *match.parents] if (parent / "Combat" / "Matches").is_dir())
    return CombatService(ROOT, root)._load_session(decode_match_directory_name(match.name))


# --------------------------------------------------------- what the narrowed comparison rejects (no captures needed)
MARK_ROW = "condition:typed.mark.forge_mark.actor:factory.smith"
CHARMED = "condition:typed.charmed"


def _row(condition_id, data):
    """One stored condition, keyed as the table keys it (by instance id) and holding what a real one holds."""
    return {f"condition-instance:{condition_id}:{LEFT}:7": {
        "condition_id": condition_id, "source_actor_id": LEFT, "expires_on": "START_OF_SLOT_AT:11:0", "data": data}}


def _state(action_ids, conditions):
    """The fighter's own saved state, in the shape a real save holds: its buttons, its pools, its turn count, its
    square and its conditions -- the Forge Mark row this round changed beside an unrelated condition that must not be
    able to change under the same allowance."""
    return {"actors": {LEFT: {"action_ids": action_ids, "resources": {"core.qi": 30}, "turns_started": 2,
                              "position": {"x": 3, "y": 6}, "conditions": conditions}}}


def _commit(mark_data, charmed_data):
    """One committed transaction: the Forge Mark row it applied, and an unrelated condition applied in the same
    journal record, which is what makes a positional comparison unable to tell whose data it is looking at."""
    return [{"record_type": "COMMIT", "record_sequence": 1, "events": [
        {"event_type": "CONDITION_APPLIED",
         "payload": {"condition_id": MARK_ROW,
                     "gate3_condition_after": {"condition_id": MARK_ROW, "source_actor_id": LEFT,
                                               "expires_on": "START_OF_SLOT_AT:11:0", "data": mark_data}}},
        {"event_type": "CONDITION_APPLIED",
         "payload": {"condition_id": CHARMED,
                     "gate3_condition_after": {"condition_id": CHARMED, "source_actor_id": LEFT,
                                               "expires_on": "START_OF_SLOT_AT:11:0", "data": charmed_data}}}]}]


def _a_capture_pair():
    """A made-up baseline/tip pair in the same shape the real captures have: one compiled bundle whose catalogue has
    an existing action, the fighter's own state, one snapshot file carrying that state, and one committed
    transaction. It holds a Forge Mark row -- the thing this round changed -- and an unrelated condition, so a test
    can show which of the two the allowance reaches."""
    action = {"source_definition_id": DECLARATION_BUTTON, "display_name": "Declare personal work",
              "parameters": {"setting_description": "old wording", "typed": {"effects": [{"type": "x", "on": True}]},
                             "economy": "NONE", "target_kind": "SELF"}}
    other = {"source_definition_id": "action:typed.other.swing", "display_name": "Swing",
             "parameters": {"setting_description": "swing", "typed": {"effects": []}, "economy": "ACTION"}}
    marks = {"count": 2, "since_round": 1, "since_slot": 0, "label": "Forge Marks (2 of 4)"}
    charmed = {"label": "Charmed"}
    state = _state([other["source_definition_id"], DECLARATION_BUTTON],
                   {**_row(MARK_ROW, marks), **_row(CHARMED, charmed)})
    bundle = {"action_catalog": [action, other], "actor_template": {"action_ids": [other["source_definition_id"],
                                                                                  DECLARATION_BUTTON]}}
    baseline = {"Typed_Character_Bundles.json": [bundle], "GenesisState.json": {"state": state},
                "Snapshots/m1.json": {"state": state}, "Journal.ndjson": _commit(marks, charmed)}
    # The tip's row keeps the count and the one shared minute the save was holding, and adds the two things this
    # round's writer adds: a deadline of its own per mark, and the count of any mark it could not date.
    tip_marks = {**marks, "undated": 0, "deadlines": [[1, 0], [2, 0]]}
    tip_actions = [dict(action, parameters=dict(action["parameters"], setting_description="new wording")),
                   dict(other), {**action, "source_definition_id": NEW_ACTION}]
    tip_state = _state([other["source_definition_id"], DECLARATION_BUTTON, NEW_ACTION],
                       {**_row(MARK_ROW, tip_marks), **_row(CHARMED, charmed)})
    tip = {"Typed_Character_Bundles.json": [{"action_catalog": tip_actions,
                                            "actor_template": {"action_ids": [other["source_definition_id"],
                                                                               DECLARATION_BUTTON, NEW_ACTION]}}],
           "GenesisState.json": {"state": tip_state}, "Snapshots/m1.json": {"state": tip_state},
           "Journal.ndjson": _commit(tip_marks, charmed)}
    return baseline, tip


def _compare(baseline, tip):
    return document_differences({name: canonical_capture(value) for name, value in baseline.items()},
                                {name: canonical_capture(value) for name, value in tip.items()},
                                expected=SMITH_PATHS + smith_paths(baseline, tip))


def test_the_narrowed_comparison_allows_exactly_this_rounds_changes():
    """The made-up pair changes exactly the four things this round changed: the new action id in the catalogue, the
    declaration's one rewritten field, the new id in the fighter's own list, and the Forge Mark row's second
    deadline. Everything else in both files is compared and equal."""
    baseline, tip = _a_capture_pair()
    report = _compare(baseline, tip)
    assert report["unexpected"] == [], report["unexpected"]
    # Every allowance this pair is meant to exercise was used, so the list cannot rot into allowing nothing. The
    # wall-clock and digest paths are not in scope here: a made-up pair has no file carrying either.
    exercised = {prefix for prefix in smith_paths(baseline, tip)
                 if not prefix.endswith(SNAPSHOT_DIGESTS)}
    assert [prefix for prefix in report["unused"] if prefix in exercised] == [], report["unused"]


def test_the_forge_mark_allowance_names_one_condition_and_no_other():
    """The allowance for this round's per-mark clock names the Forge Mark row's own identity, read out of the
    captures. A wildcard in that position ("any condition's row") is what let an unrelated duration change through,
    so the declaration itself is asserted: no allowance mentions a condition the captures do not hold, and every one
    that mentions a condition names the Forge Mark."""
    baseline, tip = _a_capture_pair()
    for prefix in smith_paths(baseline, tip):
        if ".conditions." in prefix or EVENT_CONDITION in prefix:
            assert MARK_CONDITION in prefix, f"an allowance names something other than the Forge Mark row: {prefix}"


def test_the_narrowed_comparison_rejects_an_unrelated_conditions_deadlines_in_the_genesis_state():
    """The hole finding 2 named: the per-mark clock was allowed at ``conditions.{mark}.data.deadlines`` and the
    placeholder matched any condition, so once a capture held a Forge Mark at all, another condition's own deadlines
    passed too -- in the genesis state, in every snapshot, and in the journal."""
    baseline, tip = _a_capture_pair()
    changed = copy.deepcopy(tip)
    key = f"condition-instance:{CHARMED}:{LEFT}:7"
    changed["GenesisState.json"]["state"]["actors"][LEFT]["conditions"][key]["data"]["deadlines"] = [[9, 9]]
    report = _compare(baseline, changed)
    assert [line for line in report["unexpected"] if CHARMED in line and "data.deadlines" in line], (
        f"another condition's own deadlines slipped through in the genesis state: {report['unexpected']}")


def test_the_narrowed_comparison_rejects_an_unrelated_conditions_deadlines_in_a_snapshot():
    """The same in a snapshot, which is compared whole like any other stored value."""
    baseline, tip = _a_capture_pair()
    changed = copy.deepcopy(tip)
    key = f"condition-instance:{CHARMED}:{LEFT}:7"
    changed["Snapshots/m1.json"]["state"]["actors"][LEFT]["conditions"][key]["data"]["deadlines"] = [[9, 9]]
    report = _compare(baseline, changed)
    assert [line for line in report["unexpected"] if CHARMED in line and "data.deadlines" in line], (
        f"another condition's own deadlines slipped through in a snapshot: {report['unexpected']}")


def test_the_narrowed_comparison_rejects_an_unrelated_conditions_deadlines_in_the_journal():
    """And in a committed transaction. Two condition records sit in the same journal record here, so a comparison
    that only knew the *position* of the difference could not tell them apart at all; each record is addressed by the
    condition it applied instead."""
    baseline, tip = _a_capture_pair()
    changed = copy.deepcopy(tip)
    record = changed["Journal.ndjson"][0]["events"][1]["payload"][EVENT_CONDITION]
    record["data"]["deadlines"] = [[9, 9]]
    report = _compare(baseline, changed)
    assert [line for line in report["unexpected"] if CHARMED in line and "data.deadlines" in line], (
        f"another condition's own deadlines slipped through in the journal: {report['unexpected']}")
    # And the Forge Mark's own deadlines in that same record are still allowed, which is the whole point: the
    # restriction has to name the right condition, not forbid the change.
    allowed = _compare(baseline, tip)
    assert [line for line in allowed["allowed"] if "gate3_condition_after" in line and "data.deadlines" in line], (
        "the Forge Mark row's own per-mark clock is no longer allowed to differ")


def test_the_narrowed_comparison_rejects_a_change_to_an_existing_action():
    """An existing action's effects, cost or target must not be able to change under the allowance. Before, the whole
    ``action_catalog`` was allowed, so this passed silently; the action-ID set test did not see it either, because
    the action was still offered."""
    baseline, tip = _a_capture_pair()
    changed = copy.deepcopy(tip)
    for action in changed["Typed_Character_Bundles.json"][0]["action_catalog"]:
        if action["source_definition_id"] == DECLARATION_BUTTON:
            action["parameters"]["typed"]["effects"] = [{"type": "x", "on": True}, {"type": "surprise", "amount": 99}]
            action["parameters"]["economy"] = "ACTION"
    report = _compare(baseline, changed)
    assert [line for line in report["unexpected"] if ".typed.effects" in line or ".economy" in line], \
        f"a changed existing action slipped through: {report['unexpected']}"


def test_the_narrowed_comparison_rejects_a_change_to_a_snapshots_own_state():
    """A snapshot used to be allowed as a whole folder, so nothing inside one was ever checked. A snapshot's
    resources, turn count, position or any other state must now fail the comparison like any other stored value."""
    baseline, tip = _a_capture_pair()
    for field, value in (("resources", {"core.qi": 29}), ("turns_started", 3), ("position", {"x": 4, "y": 6})):
        changed = copy.deepcopy(tip)
        changed["Snapshots/m1.json"]["state"]["actors"][LEFT][field] = value
        report = _compare(baseline, changed)
        assert [line for line in report["unexpected"] if line.startswith("Snapshots/m1.json")], \
            f"a snapshot's own {field} change slipped through: {report['unexpected']}"


def test_the_narrowed_comparison_rejects_a_snapshot_that_exists_on_only_one_side():
    """A fight that grew or lost a snapshot is a difference in what the table saved, and a folder-wide allowance
    could not see it. Naming each snapshot file can."""
    baseline, tip = _a_capture_pair()
    changed = copy.deepcopy(tip)
    changed["Snapshots/m2.json"] = changed["Snapshots/m1.json"]
    report = _compare(baseline, changed)
    assert "Snapshots/m2.json: only in tip" in report["unexpected"], report["unexpected"]


def _nothing_gained(report) -> bool:
    """No condition, damage type, rider line or spent resource appears in one journal and not the other."""
    return all(not value["gained"] and not value["lost"] for value in report["totals"].values())


def _smith_actions(match: Path) -> list[str]:
    """The captured fighter's compiled action ids: the buttons it is offered."""
    state = json.loads((match / "GenesisState.json").read_text())["state"]
    return sorted(state["actors"][LEFT].get("action_ids", []))
