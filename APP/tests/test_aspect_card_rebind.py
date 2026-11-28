"""Reviewed cards can follow a terminology change, but not a new rule."""
import pytest

from factory_authoring.player_rules import build_player_text, card_sha, project_player_card
from tools.apply_aspect_terms import _prepare_card_rebinds


def test_rebind_reviewed_card_only_across_the_term_rename():
    old = {"sample": "Guard\nChoose a Fire Sphere talent, then move 10 feet."}
    new = {"sample": "Guard\nChoose a Way of Fire talent, then move 10 feet."}
    old_override = "Guard\nChoose a Fire Sphere talent before moving 10 feet."
    edits = {"sample": {"player_text": old_override, "player_card": {
        "rules_sha256": card_sha(old["sample"]),
        "summary": "Choose a Fire Sphere talent.",
        "groups": {"Effect": ["Move 10 feet."]},
    }}}
    old_clarified = build_player_text(old, edits)["records"]["sample"]
    edits["sample"]["player_card"]["source_sha256"] = card_sha(old_clarified)

    rebound = _prepare_card_rebinds(old, new, edits)
    new_clarified = build_player_text(new, rebound)["records"]["sample"]
    assert "Choose a Way of Fire talent before moving 10 feet." in new_clarified
    card = project_player_card(new_clarified, new["sample"], rebound["sample"])
    assert card["summary"] == "Choose a Way of Fire talent."
    assert card["groups"]["Effect"] == ["Move 10 feet."]
    assert card["rules"] == new["sample"]
    assert _prepare_card_rebinds(old, new, rebound) == {}
    assert edits["sample"]["player_text"] == old_override

    changed_distance = {"sample": new["sample"].replace("10 feet", "15 feet")}
    with pytest.raises(ValueError, match="printed rules changed beyond the Aspect terminology"):
        _prepare_card_rebinds(old, changed_distance, edits)
