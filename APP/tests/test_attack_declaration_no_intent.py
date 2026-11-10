from types import SimpleNamespace

from combat.attack_declaration import intercepted


def test_free_trigger_interception_accepts_missing_intent():
    """Reaction/zone attacks can be declared with no action intent in flight."""
    # A real fighter always carries these; the afterimage provider reads them before any intent check.
    actor = SimpleNamespace(entity_id="actor:attacker", active=False, position=None)
    target = SimpleNamespace(entity_id="actor:target")
    engine = SimpleNamespace(state=SimpleNamespace(objects={}, map_images={}))
    spec = {}

    assert intercepted(engine, actor, target, "attack:free-trigger", None, spec=spec) is False
    assert spec["target_interception"]["key"] == (
        "actor:attacker", "actor:target", "attack:free-trigger", "", 1
    )


def test_second_free_strike_in_one_spec_is_not_served_the_cached_receipt(monkeypatch):
    """The "" intent id must not make every free strike in a spec share one receipt; the strike index still keys it."""
    import combat.attack_declaration as declaration

    receipt = {"source_id": "passive:test.afterimage", "recipient_object_id": "image:test",
               "condition_instance_id": "condition:test"}
    calls = []

    def checkpoint(point, engine, actor, target, source, intent, index):
        calls.append(index)
        return [] if index == 1 else [receipt]

    monkeypatch.setattr(declaration.ext, "run_checkpoint", checkpoint)
    events = []
    engine = SimpleNamespace(state=SimpleNamespace(objects={"image:test": {}}, map_images={}),
                             _append_event=lambda *args, **kwargs: events.append((args, kwargs)))
    actor = SimpleNamespace(entity_id="actor:attacker", active=True, position=None)
    target = SimpleNamespace(entity_id="actor:target")
    spec = {}

    assert declaration.intercepted(engine, actor, target, "attack:free-trigger", None, 1, spec=spec) is False
    assert declaration.intercepted(engine, actor, target, "attack:free-trigger", None, 2, spec=spec) is True
    assert calls == [1, 2]
    assert len(events) == 1  # only the intercepted (second) strike records a receipt
