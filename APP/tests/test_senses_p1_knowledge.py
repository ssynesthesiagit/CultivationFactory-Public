"""Observers receive only knowledge supported by their own live perception."""
from combat import senses
from tests.test_effect_durations import _fight


def test_paired_world_visibility_is_observer_specific():
    engine, observer, target = _fight("INVISIBLE")
    engine._apply_condition(target, "condition:typed.invisible", "test:vanish",
                            target.entity_id, expires_on="UNTIL_REMOVED")
    other, other_observer, other_target = _fight("INVISIBLE")
    other._apply_condition(other_target, "condition:typed.invisible", "test:vanish",
                           other_target.entity_id, expires_on="UNTIL_REMOVED")

    # The target's own observer-side projection knows its own location; an
    # opposing observer without a locating sense does not gain that knowledge.
    own = senses.assess(engine, target, senses.creature_subject(target), purpose="known_location")
    opposing = senses.assess(engine, observer, senses.creature_subject(target), purpose="known_location")
    paired = senses.assess(other, other_observer, senses.creature_subject(other_target),
                           purpose="known_location")
    assert own["allowed"] is True
    assert opposing["allowed"] is False
    assert paired["allowed"] is False
    assert opposing["rejection"] == "You cannot perceive that from here."


def test_location_only_subject_does_not_imply_visual_sight(monkeypatch):
    engine, observer, target = _fight("INVISIBLE")
    monkeypatch.setattr(senses, "perceives", lambda *_a, **_kw: False)
    monkeypatch.setattr(senses, "pinpoints", lambda *_a: True)
    result = senses.assess(engine, observer, senses.creature_subject(target), purpose="known_location")
    assert result["location"] and result["allowed"]
    assert not result["sight"]
