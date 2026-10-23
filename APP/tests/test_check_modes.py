"""Advantage and Disadvantage on ability checks (owner 2026-09-28: "make sure all the talents ... is applied"): a typed
"on ... checks" effect is a condition carrying the check mode, and the table's checks read it."""

from combat.typed_executor import _check_keys, check_mode
from combat.gate2_runtime_models import ActorState, ConditionInstance, Position


def test_check_keys_read_abilities_and_skills():
    assert _check_keys("wisdom (perception) checks until the end of your next turn") == ["Perception"]
    assert _check_keys("strength, dexterity, and constitution ability checks") == ["STR", "DEX", "CON"]
    assert _check_keys("the next attack roll") == []


def test_a_check_mode_condition_sets_the_mode_for_that_skill_only():
    actor = ActorState(entity_id="a", display_name="A", team_id="t", primary_combatant=True, armor_class=10, maximum_hp=10, current_hp=10,
                       position=Position(x=0, y=0), speed_ft=30, movement_remaining_ft=30, initiative_bonus=0, dexterity_score=10,
                       proficiency_bonus=2, saving_throws={}, resources={}, resource_maximums={})
    actor.conditions["c"] = ConditionInstance(instance_id="c", condition_id="condition:typed.check_mode", source_definition_id="s", source_actor_id="b",
                                              target_id="a", applied_sequence=1, data={"rule": {"check_mode": {"Perception": "DISADVANTAGE"}}})
    assert check_mode(actor, "WIS", "Perception") == "DISADVANTAGE"
    assert check_mode(actor, "WIS", "Insight") == "NORMAL"


def test_disadvantage_on_ability_checks_covers_every_check(monkeypatch):
    import combat.typed_executor as te

    assert te._check_keys("ability checks") == ["ALL"]
    assert te._check_keys("checks made to hold a door") == []
    monkeypatch.setattr(te, "condition_rules", lambda actor, *, engine=None: [{"check_mode": {"ALL": "DISADVANTAGE"}}])
    assert te.check_mode(object(), "DEX", "Stealth") == "DISADVANTAGE"
