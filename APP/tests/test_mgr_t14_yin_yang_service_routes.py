"""Public synthetic regressions for the journey service routes."""

from combat.gate5_service import CombatService


def test_gate5_import_and_journey_routes_delegate_to_journey_store(monkeypatch):
    calls = []

    class JourneyStore:
        def record_world_fact(self, journey_id, revision, payload):
            calls.append(("world_fact", journey_id, revision, payload))
            return {"revision": revision + 1}

        def end_scene(self, journey_id, revision, reason):
            calls.append(("end_scene", journey_id, revision, reason))
            return {"scene": "ended"}

    store = JourneyStore()
    monkeypatch.setattr(CombatService, "journeys", property(lambda _self: store))
    service = object.__new__(CombatService)

    payload = {"source": "table", "subject": "actor:test", "kind": "weather", "value": "rain"}
    assert service.journey_world_fact("journey:test", 7, payload) == {"revision": 8}
    assert service.journey_end_scene("journey:test", 8, "The expedition is over.") == {"scene": "ended"}
    assert calls == [
        ("world_fact", "journey:test", 7, payload),
        ("end_scene", "journey:test", 8, "The expedition is over."),
    ]
