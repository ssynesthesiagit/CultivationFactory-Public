"""A normal attack completion remains safe with every extension loaded."""
from types import SimpleNamespace

from combat.attack_completion import notify


def test_plain_attack_completion_without_true_reflection_owner_is_inert(monkeypatch):
    from combat import ext
    from combat.ext.true_reflection import fixate_original

    engine = SimpleNamespace(
        state=SimpleNamespace(actors={}, terminal_result=None),
        action_catalog={},
    )
    attacker = SimpleNamespace(entity_id="ordinary-attacker")
    target = SimpleNamespace(entity_id="ordinary-target")

    # Isolate the globally registered True Reflection observer while still
    # driving the normal settled attack-completion dispatcher.
    monkeypatch.setattr(
        ext, "subscribers",
        lambda event: [fixate_original] if event == "attack_completed" else [],
    )
    assert notify(
        engine, attacker, target, {"range_ft": 5}, intent=None,
        source="test:ordinary-attack", hit=True,
    )
