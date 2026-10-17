"""Guard ordinary scalar damage against accidental component-pipeline opt-in."""
from types import SimpleNamespace

from combat.attack_components import collect, needs_component_settlement
from combat.ext.dreamweaver import REFUGE_ON, refuge_resistance_scalar


def test_homogeneous_unarmed_damage_keeps_legacy_scalar_settlement():
    parts = collect(3, "BLUDGEONING", [{"amount": 5, "damage_type": "BLUDGEONING"}])
    assert sum(part["amount"] for part in parts) == 8
    assert not needs_component_settlement(parts)


def test_mixed_or_explicitly_permitted_damage_uses_component_settlement():
    mixed = collect(3, "BLUDGEONING", [{"amount": 5, "damage_type": "FORCE"}])
    permitted = collect(3, "BLUDGEONING", [{"amount": 5, "damage_type": "BLUDGEONING",
                                             "ignore_resistance": True}])
    assert needs_component_settlement(mixed)
    assert needs_component_settlement(permitted)


def test_dream_refuge_scalar_resistance_is_gated_to_its_condition():
    engine = object()
    target = SimpleNamespace(conditions={"refuge": SimpleNamespace(condition_id=REFUGE_ON)})
    assert refuge_resistance_scalar(engine, target, 7, "BLUDGEONING", "attack", "attacker") == 4
    assert refuge_resistance_scalar(engine, target, 7, "FORCE", "attack", "attacker") is None
    target.conditions.clear()
    assert refuge_resistance_scalar(engine, target, 7, "BLUDGEONING", "attack", "attacker") is None
