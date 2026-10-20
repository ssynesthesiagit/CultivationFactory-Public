"""The actual Living Painting card and all four projected form reminders agree."""
import json
from pathlib import Path

import pytest

from combat.player_text import reviewed_wording
from factory_authoring.player_rules import card_default_text
from tools.card_lint import catalogue, lint_card

ROOT = Path(__file__).resolve().parents[1]
FEATURE = "tianxia.subpath.qi.painting_cultivator.feature.living_painting"


def test_living_painting_card_explains_instincts_without_rewriting_printed_rules():
    card = catalogue([FEATURE])[FEATURE]
    assert card["reviewed"]
    assert lint_card(card) == []
    visible = card_default_text(card)
    assert "acts on its instincts" in visible
    assert "nearest enemy it can see and reach" in visible
    assert "30 feet of you when none is in sight" in visible
    assert "next turn, then instincts resume" in visible
    assert "Dodge" not in visible
    for form in ("Tiger", "Crane", "Tortoise", "Serpent"):
        assert form in visible
    assert "4 Qi" in visible and "Concentration" in visible
    # The source has no default-turn clause to replace; only evidence was stale.
    raw = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[FEATURE]
    assert "Dodge" not in raw and "instinct" not in raw


@pytest.mark.parametrize("form", ["Tiger", "Crane", "Tortoise", "Serpent"])
def test_every_form_evidence_projects_to_instincts(form):
    # Read the public reviewed row, not the private aggregate/history.
    record = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/sys_menus-forms.json").read_text())["mechanics"][FEATURE]
    option = next(o for o in record["options"] if o["label"] == form)
    raw = next(line for line in option["riders"] if "Dodges unless commanded" in line)
    visible = reviewed_wording(raw)
    assert visible is not None, form
    assert "acts on its instincts" in visible
    assert "Bonus Action" in visible
    assert "Dodge" not in visible
    assert "combat/" not in visible
