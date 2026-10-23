"""Fear-aware saddle choices persist and replay at the tabletop boundary."""

import pytest

from combat.ext import mounts
from combat.target_knowledge import can_see
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.hunt19_support import fight, send
from tests.test_tabletop_hunt6 import LEFT, ALLY, on_hold
from tests.test_lock2_persistence import act


def _stage_fear(engine, *, every_landing_closer):
    rider = engine.state.actors[LEFT]
    mount = mounts.mount_of(engine, rider)
    source = engine.state.actors[ALLY]
    # Pick a visible source position that makes the current nearest landing
    # closer; the second layout makes every free landing closer.
    around = mounts._cells(engine, mount)
    taken = engine._occupied_cells_except(rider.entity_id) | around
    reach = {(x + dx, y + dy) for x, y in around for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    free = [p for p in reach if engine.grid.in_bounds(p) and p not in engine.grid.blocked and p not in taken]
    default = mounts._landing(engine, rider, mount)
    candidates = [(x, y) for x in range(engine.grid.width) for y in range(engine.grid.height)
                  if (x, y) not in around and (x, y) != (rider.position.x, rider.position.y)]
    for cell in candidates:
        start_distance = engine.grid.distance_ft(rider.position, cell)
        if engine.grid.distance_ft(default, cell) >= start_distance:
            continue
        closer = [p for p in free if engine.grid.distance_ft(p, cell) < start_distance]
        if not closer:
            continue
        blocked = set(free) - set(closer)
        if every_landing_closer and not blocked:
            continue
        if cell in mounts._cells(engine, source):
            continue
        old = source.position
        source.position = Position(x=cell[0], y=cell[1])
        if not can_see(engine, rider, source):
            source.position = old
            continue
        engine._append_event("MOVEMENT_COMMITTED", "test:saddle-fear-layout", actor_id=source.entity_id,
            payload={"destination": source.position.model_dump(mode="json"), "cost_ft": 0, "forced": True,
                     "path": [old.model_dump(mode="json"), source.position.model_dump(mode="json")]})
        engine._apply_condition(rider, "condition:typed.frightened", "test:visible-fear", source.entity_id,
                                expires_on="UNTIL_REMOVED")
        assert engine.grid.distance_ft(default, source.position) < start_distance
        return rider, mount, source, len(closer), len(free), blocked
    raise AssertionError("could not stage required saddle fear layout")


def test_dismount_uses_legal_landing_at_table_commit_reload_and_replay(tmp_path, monkeypatch):
    combat, table, mid = fight(tmp_path, ["BEASTMASTERY_BASE_RIDER_PACKAGE"])
    staged = {}

    def stage(engine):
        rider, mount, source, closer, total, blocked = _stage_fear(engine, every_landing_closer=False)
        staged.update(rider=rider.entity_id, mount=mount.entity_id, source=source.entity_id,
                      closer=closer, total=total, blocked=blocked, start=rider.position.model_dump(mode="json"))

    on_hold(monkeypatch, stage)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    state = table.state(mid)
    while state["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
        state = table.state(mid)
    has_dismount = any(g["label"] == "Dismount" and g["options"] for g in state["menu"]["actions"])
    assert has_dismount and staged["closer"] < staged["total"]
    result = send(table, mid, "Dismount")([])
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    rider, source = loaded.engine.state.actors[LEFT], loaded.engine.state.actors[staged["source"]]
    assert mounts.mount_of(loaded.engine, rider) is None
    assert loaded.engine.grid.distance_ft(rider.position, source.position) >= loaded.engine.grid.distance_ft(
        Position(**staged["start"]), source.position)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_dismount_is_not_offered_when_every_free_landing_is_closer_commit_reload(tmp_path, monkeypatch):
    # Find the fixture's geometry, then save a real map with walls over the
    # non-closer squares. The map must survive reload, not just a grid mutation.
    probe, _, probe_mid = fight(tmp_path / "layout", ["BEASTMASTERY_BASE_RIDER_PACKAGE"])
    engine = probe._load_session(probe_mid).engine
    _, _, source, _, _, blocked = _stage_fear(engine, every_landing_closer=True)
    source_at = source.position
    walls = [{"shape": "rect", "points": [[x, y], [x + 1, y + 1]], "filled": True}
             for x, y in sorted(blocked)]
    data = tmp_path / "table"
    combat, table, mid = fight(data, ["BEASTMASTERY_BASE_RIDER_PACKAGE"], walls=walls)

    def stage(engine):
        rider = engine.state.actors[LEFT]
        source = engine.state.actors[ALLY]
        old = source.position
        source.position = source_at
        engine._append_event("MOVEMENT_COMMITTED", "test:saddle-fear-layout", actor_id=source.entity_id,
            payload={"destination": source.position.model_dump(mode="json"), "cost_ft": 0, "forced": True,
                     "path": [old.model_dump(mode="json"), source.position.model_dump(mode="json")]})
        engine._apply_condition(rider, "condition:typed.frightened", "test:visible-fear", source.entity_id,
                                expires_on="UNTIL_REMOVED")

    on_hold(monkeypatch, stage)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    state = table.state(mid)
    assert state["menu"]["actor_id"] == LEFT
    assert not any(g["label"] == "Dismount" and g["options"] for g in state["menu"]["actions"])
    before = combat._load_session(mid).engine.state.actors[LEFT]
    loaded = CombatService(combat.source_root, data)._load_session(mid)
    rider = loaded.engine.state.actors[LEFT]
    mount = mounts.mount_of(loaded.engine, rider)
    assert mount is not None and can_see(loaded.engine, rider, loaded.engine.state.actors[ALLY])
    assert mounts._landing(loaded.engine, rider, mount) is not None  # free squares exist
    assert mounts._landing(loaded.engine, rider, mount, fear_legal=True) is None
    assert (rider.position, rider.movement_remaining_ft, rider.resources) == (before.position, before.movement_remaining_ft, before.resources)
    assert blocked <= loaded.engine.grid.blocked
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
