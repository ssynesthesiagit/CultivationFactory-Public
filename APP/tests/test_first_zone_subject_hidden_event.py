"""Hidden aura recenter records must not retrigger a first-zone-subject rider."""
from types import SimpleNamespace

from combat import typed_executor
from combat.ext import riders_metal


def test_hidden_recenter_is_not_a_first_subject_activation(monkeypatch):
    calls = []
    monkeypatch.setattr(typed_executor, "bears_mark", lambda *args: False)
    monkeypatch.setattr(typed_executor, "block_mark", lambda *args: calls.append("mark"))
    monkeypatch.setattr(typed_executor, "run_effects", lambda *args: calls.append("effect"))
    event = SimpleNamespace(event_type="PASSIVE_TRIGGERED", source_definition_id="zone-source",
                             payload={"zone_id": "moving-aura", "history_hidden": 1})
    ctx = SimpleNamespace(engine=SimpleNamespace(events=[event]), source="zone-source",
                          actor=SimpleNamespace(entity_id="owner"))
    riders_metal.first_zone_subject(ctx, {"effects": [{"type": "test"}]})
    assert calls == []
