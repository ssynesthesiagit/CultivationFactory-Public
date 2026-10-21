from types import SimpleNamespace

from combat.attack_declaration import intercepted


def test_free_trigger_interception_accepts_missing_intent():
    """Reaction/zone attacks can be declared with no action intent in flight."""
    actor = SimpleNamespace(entity_id="actor:attacker")
    target = SimpleNamespace(entity_id="actor:target")
    engine = SimpleNamespace(state=SimpleNamespace(objects={}, map_images={}))
    spec = {}

    assert intercepted(engine, actor, target, "attack:free-trigger", None, spec=spec) is False
    assert spec["target_interception"]["key"] == (
        "actor:attacker", "actor:target", "attack:free-trigger", "", 1
    )
