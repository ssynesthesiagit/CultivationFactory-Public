"""Printed wording regressions for sheet and table option tooltips.

The listing itself (presence, count, order, cost, reload equality) is checked in
tests/test_option_tooltips.py; this file holds only the printed prose an
ordinary wording edit may change, so it is never exported to the public suite.
"""
import json
import subprocess
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.option_text import CHOICE_LINE
from combat.status_text import printed_rules
from tests.option_tooltip_support import OWNER, ROOT, option_match, rows
from tests.test_option_tooltips import synthetic_printed_options  # noqa: F401 (fixtures)


@pytest.fixture(autouse=True)
def _synthetic_printed_options(synthetic_printed_options):
    """Replace public-export redactions with stable synthetic prose."""


@pytest.mark.parametrize("locked_expression", [False, True, "legacy"])
def test_printed_option_wording_reaches_sheet_and_table(tmp_path, locked_expression):
    parts = option_match(tmp_path, locked_expression)
    buttons, mid = parts["buttons"], parts["mid"]
    if locked_expression == "legacy":
        # Pre-SOL155 sealed Core Tempering rows had this same contextual
        # description and cte_choice marker, but no setting_lifetime field.
        # That catalog is persisted, not recompiled on reload.
        sealed = [a for a in parts["combat"]._load_session(mid).engine.action_catalog.values()
                  if a.owner_id == OWNER and a.parameters.get("cte_choice")]
        assert len(sealed) == 3
        assert all("setting_lifetime" not in a.parameters for a in sealed)
        assert all("permanent until a later Realm breakthrough" in a.parameters["setting_description"]
                   for a in sealed)
    menu = parts["state"]["menu"]["actions"]
    expected = {
        "Open the Gate: Breath-Checking Strike":
            "The target cannot take Opportunity Attacks until the start of its next turn.",
        "Open the Gate: Centerline Impact":
            "When the triggering attack deals damage, add your Proficiency Bonus to that damage.",
        "Open the Gate: Hooking Step": "Move yourself 5 feet without provoking Opportunity Attacks.",
        "Shape Darkness: Numbing Darkness": "Apply Numbing Darkness to the selected area.",
        "Augment Darkness: Persistent Darkness": "The selected area lasts without Concentration.",
        "Overdraw: ready": "On the next qualifying hit, add bonus Ruin damage.",
    }
    for rows in (buttons, menu):
        for label, sentence in expected.items():
            matched = [r for r in rows if r["label"] == label]
            assert matched, f"Missing option: {label}"
            row = matched[0]
            assert sentence in row["description"]
            assert sentence in row["hover"]["text"]
            assert row["description"].count(CHOICE_LINE) == 1
            assert row["hover"]["text"].count(CHOICE_LINE) == 1
            for text in (row["description"], row["hover"]["text"]):
                assert text.index(sentence) < text.index(CHOICE_LINE)
    # The printed rule sentence, verbatim. This file asserts printed words, so it
    # must never reach the scrambled public copy (tools/public_test_redact.py
    # keeps a file local while it holds an exact expected-prose comparison).
    breath = next(r for r in buttons if r["label"] == "Open the Gate: Breath-Checking Strike")
    assert "The target cannot take Opportunity Attacks until the start of its next turn." in breath["description"]
    assert "When you Open a creature".lower() in printed_rules()["printed_option:Breath-Checking Strike"].lower()
    for rows in (buttons, menu):
        row = next(r for r in rows if r["label"].startswith("Nullifying Strike"))
        assert "The target makes a Constitution saving throw" in row["description"]
        for text in (row["description"], row["hover"]["text"]):
            assert "Cost: 2 cultivation points (your Path resource) or 2 Stamina" in text
            assert "2 CP" not in text
    for payload in (buttons, menu):
        # The sheet groups modifier choices; the table exposes each rider.
        nullifying = [r for r in payload if r["label"].startswith("Nullifying Strike")]
        assert nullifying
        if locked_expression:
            expressions = [r for r in payload if r["label"].startswith("Core Tempering Expression:")]
            assert len(expressions) == 3, [r["label"] for r in payload]
            for row in expressions:
                text = row["hover"]["context"]
                assert "permanent until a later Realm breakthrough" in text
                assert "cannot change it during this fight" in text
                assert "stays selected until you change it" not in text
        for row in nullifying:
            for text in (row["description"], row["hover"]["text"]):
                assert "Failed Save:" in text
                evidence = row["label"].partition(" — ")[2]
                if evidence:
                    assert "Failed Save: " + evidence.rstrip(";") in text.replace("’", "'")

    # A wording edit can precede rebuilding its reviewed card. It must not
    # turn a reference-text read into an unavailable action menu.
    from factory_authoring import record_display
    from factory_authoring.player_rules import card_sha, project_player_card
    key = "printed_option:Breath-Checking Strike"
    data = record_display.DATA
    clarified = json.loads((data / "player_text.json").read_text())["records"][key]
    printed = json.loads((data / "rules_text.json").read_text())[key]
    edits = {"player_card": {"source_sha256": card_sha(clarified + "\nOld wording."),
                             "rules_sha256": card_sha(printed),
                             "summary": "Obsolete overview.", "groups": {}}}
    (data / "owner_text_edits.json").write_text(json.dumps({"records": {key: edits}}))
    with pytest.raises(ValueError, match="Stale player_card overview"):
        project_player_card(clarified, printed, edits)
    display = record_display.record_display(key)
    assert display["text"] == clarified.partition("\n")[2].strip()
    assert "Obsolete overview." not in display["html"]
    assert '<details><summary>Rules</summary>' in display["html"]
    assert "<details open" not in display["html"]
    assert "Opportunity Attacks until the start of its next turn" in display["html"]
    resumed = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)
    option = next(row for row in resumed["menu"]["actions"]
                  if row["label"] == "Open the Gate: Breath-Checking Strike")
    assert option["hover"]["player_card"]["record_id"] == key
    assert "Obsolete overview." not in option["description"]


def test_node_sheet_and_table_builders(tmp_path):
    # Rows go through a file, not the environment: the payload is larger than
    # one exec argument/environment string allows (E2BIG on Linux).
    rows_file = tmp_path / "sol155-rows.json"
    rows_file.write_text(json.dumps(rows()))
    subprocess.run(["node", "tests/option_tooltips.test.mjs", str(rows_file)], cwd=ROOT, check=True)


def test_inline_riders_use_their_own_printed_option_and_keep_cost_and_expiry():
    from combat.ext.foundation_sacred_body import REBUKE, rebuke_choices
    from combat.tabletop import engine_button_description
    info = {"owned_ids": {REBUKE}, "short": "sol155", "actor_id": OWNER, "numbers": {}}
    actions = rebuke_choices(info)
    push = next(a for a in actions if a.display_name.endswith("Push 5 ft"))
    text = engine_button_description(push.model_dump(mode="json"))
    assert text.startswith("push the target 5 feet if it is no more than one size larger than you.")
    assert "Cost: 1 Golden Sea Pulse" in text
    assert "cannot take Reactions against you" not in text
    frame = next(a for a in actions if a.display_name.endswith("Frame Advantage"))
    text = engine_button_description(frame.model_dump(mode="json"))
    assert text.startswith("you gain Advantage on the next eligible Saint-Body Frame resistance roll")
    assert "before the start of your next turn" in text
    assert "push the target 5 feet" not in text
