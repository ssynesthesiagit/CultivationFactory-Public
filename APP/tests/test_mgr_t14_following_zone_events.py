"""Following an existing aura is a persisted move, not a second creation."""
from combat.history_feed import format_history_feed
from combat.spatial_areas import zone_contains
from tests.h1_support import mechanics
from tests.test_sol209_aura_follow import (
    COURT, OWNER, FOE, SECOND, fixture, candidate, move, fresh, owned_zone,
)


def test_following_zone_replays_geometry_and_membership_without_creation_history(tmp_path):
    combat, table, mid, send, commit = fixture(
        tmp_path, [COURT], wide=True,
        positions={OWNER: {"x": 10, "y": 6}, FOE: {"x": 16, "y": 6},
                   SECOND: {"x": 3, "y": 6}})
    assert commit(candidate(table, mid, mechanics()[COURT]["name"]))["status"] == "COMMITTED"
    initial = fresh(tmp_path, mid)
    original = owned_zone(initial).model_dump(mode="json")
    sequence = initial.state.event_sequence
    creations = [e.model_dump(mode="json") for e in initial.events if e.event_type == "ZONE_CREATED"]
    assert {a.entity_id for a in initial.state.actors.values()
            if zone_contains(initial, a, owned_zone(initial))} == {OWNER, FOE}

    for x in (9, 8):
        move(table, mid, commit, x, 6)
        # fresh verifies the mechanical replay and opens an independent service.
        engine = fresh(tmp_path, mid)
        zone = owned_zone(engine)
        after = zone.model_dump(mode="json")
        for field in ("zone_id", "source_definition_id", "owner_id", "duration_rounds",
                      "created_round", "concentration_link", "active"):
            assert after[field] == original[field]
        assert zone.center == engine.state.actors[OWNER].position
        assert (zone.center.x, zone.center.y) == (x, 6)
        assert after["affected_cells"] != original["affected_cells"]
        # The old boundary occupant leaves, and the new boundary occupant enters.
        assert {a.entity_id for a in engine.state.actors.values()
                if zone_contains(engine, a, zone)} == {OWNER, SECOND}
        shown = next(z for z in table.state(mid)["presentation"]["zones"]
                     if z["zone_id"] == zone.zone_id)
        assert shown["center"] == after["center"]
        assert shown["affected_cells"] == after["affected_cells"]
        assert [e.model_dump(mode="json") for e in engine.events
                if e.event_type == "ZONE_CREATED"] == creations

        updates = [e.model_dump(mode="json") for e in engine.events
                   if e.sequence > sequence and e.payload.get("zone_after", {}).get("zone_id") == zone.zone_id]
        assert len(updates) == 10 - x  # one update per accepted square
        assert all(e["event_type"] == "PASSIVE_TRIGGERED" and e["payload"]["history_hidden"] == 1
                   for e in updates)
        assert updates[-1]["payload"]["zone_after"]["center"] == after["center"]
        assert updates[-1]["payload"]["zone_after"]["affected_cells"] == after["affected_cells"]
        assert format_history_feed(
            updates, [], pre_state=None, post_state=engine.state.model_dump(mode="json"),
            actor_names={}, definition_names={}) == []
