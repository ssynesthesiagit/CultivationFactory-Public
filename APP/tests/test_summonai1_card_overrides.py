"""Synthetic public regressions; original-authority cards are audited in test_clarity5_cards."""
import json

import pytest

from factory_authoring.player_rules import card_sha, project_player_card
from tools.card_lint import catalogue, lint_card


def _reviewed(printed, clarified, visible):
    return project_player_card(clarified, printed, {"player_card": {
        "source_sha256": card_sha(clarified), "rules_sha256": card_sha(printed),
        "summary": "Command a servant.", "groups": {"Effect": [visible]},
    }})


def _card(visible, clarified):
    return _reviewed("Servant\nReach: 5 feet.", clarified, visible)


@pytest.mark.parametrize("approved,invented,field", [
    ("Remain within 30 feet.", "Remain within 60 feet.", "quantities"),
    ("Spend 2 Qi.", "Spend 3 Qi.", "resource amounts"),
    ("Become Poisoned.", "Become Frightened.", "conditions"),
    ("Make a Wisdom save.", "Make a Dexterity save.", "save abilities"),
    ("Use Cultivation Save DC.", "Use DC 15.", "save DCs"),
    ("Until the start of your next turn.", "Until the end of your next turn.", "duration boundaries"),
    ("Use once per turn.", "Use twice per turn.", "use rates"),
])
def test_approved_clarified_fact_is_supported_but_unapproved_fact_is_not(approved, invented, field):
    clarified = "Servant\nReach: 5 feet.\n" + approved
    assert lint_card(_card("Reach: 5 feet. " + approved, clarified)) == []
    findings = lint_card(_card("Reach: 5 feet. " + invented, clarified))
    assert any(issue.startswith("unsupported-" + field) for issue in findings)


def test_reviewed_owner_distance_is_supported_but_printed_reach_is_still_required():
    clarified = "Servant\nReach: 5 feet.\nRemain within 30 feet of your owner."
    card = _card("Reach: 5 feet. Remain within 30 feet of your owner.", clarified)
    assert lint_card(card) == []
    assert card["rules"] == "Servant\nReach: 5 feet."
    missing_reach = _card("Remain within 30 feet of your owner.", clarified)
    assert any(issue.startswith("incomplete-") for issue in lint_card(missing_reach))


def test_instinct_override_keeps_the_printed_stat_block_clause_label():
    printed = "Servant\nInert Servant: It takes Dodge when not commanded."
    effect = "Inert Servant: It acts on instinct and stays within 30 feet of you."
    card = _reviewed(printed, "Servant\n" + effect, effect)
    assert lint_card(card) == []
    missing_label = _reviewed(printed, "Servant\n" + effect, effect.removeprefix("Inert Servant: "))
    assert "incomplete-choice: Inert Servant" in lint_card(missing_label)


def test_scoped_catalogue_does_not_hide_stale_selected_or_full_catalogue_edits(tmp_path, monkeypatch):
    from tools import card_lint

    (tmp_path / "rules_text.json").write_text(json.dumps({
        "good": "Servant\nReach: 5 feet.", "bad": "Other\nReach: 10 feet."}))
    (tmp_path / "owner_text_edits.json").write_text(json.dumps({"records": {
        "bad": {"player_replace": [{"old": "rider", "new": "effect", "count": 1}]}}}))
    monkeypatch.setattr(card_lint, "DATA", tmp_path)
    assert set(catalogue(["good"])) == {"good"}
    with pytest.raises(ValueError, match="player_replace"):
        catalogue(["bad"])
    with pytest.raises(ValueError, match="player_replace"):
        catalogue()


def test_reviewed_overview_cannot_invent_an_unapproved_distance():
    card = _card("Reach: 5 feet. Remain within 60 feet of your owner.",
                 "Servant\nReach: 5 feet.\nRemain within 30 feet of your owner.")
    issues = lint_card(card)
    assert any(issue.startswith("unsupported-quantities") for issue in issues)
    assert any(issue.startswith("unsupported-numbers/dice") for issue in issues)
