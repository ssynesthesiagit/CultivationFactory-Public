"""Missing roll selectors identify the owning action in compiler and harm previews."""
import pytest

from combat.area_recipients import scoped_area
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
    with pytest.raises(ValueError, match="disadvantage effect from example.source requires roll_target"):
        scoped_area({"size_ft": 10}, [row], typed={"source": "example.source"})


def test_missing_roll_target_names_forged_technique_in_both_classification_passes(monkeypatch):
    from combat import forged

    source = "forged:synthetic.burst"
    technique = {"technique_id": source, "name": "Synthetic Burst",
                 "base_form": {"form_id": "burst"},
                 "primary_sphere_effect": {"talent_id": "talent:primary"}}
    missing = {"type": "advantage", "on": "attack rolls"}
    with pytest.raises(ValueError, match="advantage effect from forged:synthetic.burst requires roll_target"):
        forged.mechanic_for(technique, {"talent:primary": {"effects": [missing]}})

    calls = []
    classify = forged.classify_effect

    def tracked(row, **kwargs):
        calls.append(kwargs.get("source_id"))
        return classify(row, **kwargs)

    monkeypatch.setattr(forged, "classify_effect", tracked)
    sealed = {**missing, "roll_target": None}
    result = forged.mechanic_for(
        technique, {"talent:primary": {"effects": [{"type": "damage", "flat": 4}, sealed]}})
    assert result is not None
    assert calls == [source, source, source, source]


@pytest.mark.parametrize("packet", [True, False], ids=["trigger-packet", "continuous-row"])
def test_missing_roll_target_names_zone_source(packet):
    from types import SimpleNamespace

    from combat import zones

    zone = SimpleNamespace(source_definition_id="action:synthetic.zone")
    effect = {"type": "disadvantage", "on": "attack rolls"}
    trigger = {"effects": [effect]} if packet else effect
    with pytest.raises(ValueError, match="disadvantage effect from action:synthetic.zone requires roll_target"):
        zones._applies(None, zone, None, trigger)
