"""AURALOG1: an aura that moves with its owner is re-centred in place, not logged again on every square.

Each square the owner walks used to append a fresh ZONE_CREATED, so the combat log repeated "created the ... area"
per step. A follower now keeps its zone id and records the move as a hidden PASSIVE_TRIGGERED carrying zone_after
(combat/zones.py follow). A real new creation still logs ZONE_CREATED once.
"""
from combat import zones
from tests.h1_support import mechanics
from tests.test_sol209_aura_follow import COURT, OWNER, FOE, SECOND, fixture, candidate, move, fresh, owned_zone


def _zone_created(engine):
    return [e for e in engine.events if e.event_type == "ZONE_CREATED"]


def test_moving_three_squares_keeps_one_zone_and_logs_no_new_creation(tmp_path):
    label = mechanics()[COURT]["name"]
    radius = int((mechanics()[COURT].get("area") or {}).get("size_ft") or 30) // 5
    combat, table, mid, send, commit = fixture(tmp_path, [COURT], wide=True,
        positions={OWNER: {"x": 10, "y": 6}, FOE: {"x": 10 + radius, "y": 6}, SECOND: {"x": 9 - radius, "y": 6}})
    assert commit(candidate(table, mid, label))["status"] == "COMMITTED"
    before = fresh(tmp_path, mid)
    zone_id = owned_zone(before).zone_id
    created_before = len(_zone_created(before))
    for x in (9, 8, 7):
        move(table, mid, commit, x, 6)
    engine = fresh(tmp_path, mid)
    assert len(_zone_created(engine)) == created_before, "a move logged a new ZONE_CREATED"
    zone = owned_zone(engine)
    assert zone.zone_id == zone_id
    assert [z.zone_id for z in zones.typed_zones(engine) if z.owner_id == OWNER] == [zone_id]
    assert zone.center == engine.state.actors[OWNER].position
    shown = next(z for z in table.state(mid)["presentation"]["zones"] if z["zone_id"] == zone_id)
    assert shown["center"] == zone.center.model_dump(mode="json")
