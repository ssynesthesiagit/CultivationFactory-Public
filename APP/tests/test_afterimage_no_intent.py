from types import SimpleNamespace

from combat.ext.afterimage_attacks import intercept_attack


def test_afterimage_interception_with_no_intent(monkeypatch):
    """Free-trigger attacks can meet an Afterimage with no action intent."""
    condition = SimpleNamespace(
        data={"label": "Afterimage"},
        source_definition_id="passive:test.afterimage",
        instance_id="condition:test.afterimage",
    )
    image = SimpleNamespace(
        component={"condition_instance_id": condition.instance_id}, object_id="image:test"
    )
    actor = SimpleNamespace(entity_id="actor:test", display_name="Attacker")
    target = SimpleNamespace(
        entity_id="actor:target", display_name="Target",
        conditions={condition.instance_id: condition},
    )
    roll = SimpleNamespace(total=1, roll_id="roll:test")
    events = []
    engine = SimpleNamespace(
        roller=SimpleNamespace(roll=lambda *args, **kwargs: roll),
        action_catalog={},
        _record_roll=lambda value: None,
        _append_event=lambda *args, **kwargs: events.append((args, kwargs)),
    )

    import combat.ext.afterimage_attacks as module
    monkeypatch.setattr(module, "perceived_image", lambda *args: image)
    monkeypatch.setattr(module, "destroy_image", lambda *args: True)
    receipt = intercept_attack(engine, actor, target, "attack:free", None, 1)

    assert receipt["recipient_object_id"] == image.object_id
    assert events[0][1]["payload"]["intent_id"] == ""
