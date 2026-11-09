"""Missing roll selectors identify the owning action in compiler and harm previews."""
import pytest

from combat.effect_harm import classify_effect
from combat.rider_value import estimate_rider_utility


def test_missing_roll_target_names_source_in_rider_preview():
    typed = {"source": "example.source", "effects": [{"type": "advantage", "on": "attack rolls"}]}
    with pytest.raises(ValueError, match="advantage effect from example.source requires roll_target"):
        estimate_rider_utility(typed, target_kind="SELF")


def test_missing_nested_roll_target_names_source_in_harm_classification():
    row = {"type": "save", "on_fail": [{"type": "disadvantage", "on": "attack rolls"}]}
    with pytest.raises(ValueError, match="disadvantage effect from example.source requires roll_target"):
        classify_effect(row, source_id="example.source")
