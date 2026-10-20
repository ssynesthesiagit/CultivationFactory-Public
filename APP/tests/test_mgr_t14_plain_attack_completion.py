"""A normal attack completion remains safe with every extension loaded."""
from types import SimpleNamespace

from combat.attack_completion import notify


def test_plain_attack_completion_without_true_reflection_owner_is_inert():
    engine = SimpleNamespace(
        state=SimpleNamespace(actors={}, terminal_result=None),
        action_catalog={},
    )
    attacker = SimpleNamespace(entity_id="ordinary-attacker")
    target = SimpleNamespace(entity_id="ordinary-target")

    # This is the same settled completion entry point used by native attacks.
    # True Reflection is globally subscribed, but this actor owns no summon.
    assert notify(
        engine, attacker, target, {"range_ft": 5}, intent=None,
        source="test:ordinary-attack", hit=True,
    )
