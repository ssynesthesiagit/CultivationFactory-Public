"""Public regressions for owner-approved summon wording without editing printed Rules."""
import pytest

from factory_authoring.player_rules import card_default_text, card_sha, project_player_card
from tools.card_lint import catalogue, lint_card

RECORDS = (
    "TAL_DEATH_LESSER_CORPSE_SERVANT_STAT_BLOCK",
    "TAL_DEATH_ROUSE_LESSER_DEAD",
    "TAL_DEATH_GRAVE_FORMATION",
    "tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation",
)


@pytest.mark.parametrize("source_id", RECORDS)
def test_owner_instinct_cards_keep_the_full_stat_block_and_pass_lint(source_id):
    card = catalogue(RECORDS)[source_id]
    assert card["reviewed"]
    assert "Without a command, it acts on its instincts:" in card["clarified"]
    assert lint_card(card) == []
    assert "within 30 feet of you" in card_default_text(card)
    # The archived source is untouched; the owner's override belongs to the overview.
    assert "Dodge" in card["rules"]
    if source_id == RECORDS[0]:
        assert "Inert Servant: Without a command, it acts on its instincts:" in card["clarified"]


def _card(visible, clarified):
    printed = "Servant\nReach: 5 feet."
    return project_player_card(clarified, printed, {"player_card": {
        "source_sha256": card_sha(clarified), "rules_sha256": card_sha(printed),
        "summary": "Command a servant.", "groups": {"Effect": [visible]},
    }})


def test_reviewed_owner_distance_is_supported_but_printed_reach_is_still_required():
    clarified = "Servant\nReach: 5 feet.\nRemain within 30 feet of your owner."
    card = _card("Reach: 5 feet. Remain within 30 feet of your owner.", clarified)
    assert lint_card(card) == []
    assert card["rules"] == "Servant\nReach: 5 feet."
    missing_reach = _card("Remain within 30 feet of your owner.", clarified)
    assert any(issue.startswith("incomplete-") for issue in lint_card(missing_reach))


def test_scoped_catalogue_does_not_hide_stale_selected_or_full_catalogue_edits(tmp_path, monkeypatch):
    import json
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
