"""Synthetic sealed furniture, exercised through persisted service decisions.

No catalog/map defaults change. Test-only compile/effect subscribers create one
HP record, then stock objects handles targeting, areas, collision and destruction.
"""
import pytest

from combat import ext
from combat.ext import objects
from combat.gate2_runtime_models import ActionDefinition, Position, RuntimeObjectState
from combat.gate5_service import CombatService
from combat.object_geometry import target_cells
from combat.tabletop import normalize_map, to_battlefield
from tests.test_auto_docket import ROOT, ME
from tests.test_lock_choices import install
from tests.test_lock26_movement_concentration_seams import _execute, _match

OID = "object:test.lock27c"
PLACE = "action:test.lock27c.place"
HIT = "action:test.lock27c.hit"
AREA = "action:test.lock27c.area"
COLLIDE = "action:test.lock27c.collide"


def setup(tmp_path, monkeypatch, *, rotation=0, legacy=False, me_at=(7, 6), walls=(),
          blocks=True, reach=5, area=None, collision_at=(6, 6), burst=None, foe_at=(14, 10)):
    component = {"name": "Test workbench", "blocks": blocks, "cover": "half"}
    if not legacy:
        component.update(width_cells=2, length_cells=1, rotation=rotation)

    def place(ctx, eff):
        from combat import zones
        ctx.engine._update_object(RuntimeObjectState(
            object_id=OID, object_kind="TEST", position=Position(x=5, y=6),
            unattended=True, flammable=False, ac=10, current_hp=10, maximum_hp=10,
            component=component), ctx.source, ctx.actor.entity_id)
        zones.sync_walls(ctx.engine)

    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, "test_lock27c_place", place)

    def collide(ctx, eff):
        from combat.ext.rider_movement import forced_route
        actor, engine = ctx.actor, ctx.engine
        end = Position(x=collision_at[0], y=collision_at[1])
        before = Position(x=end.x, y=end.y - 1)
        forced_route(engine, actor, (actor.position, before, end), ctx.source, actor)
        assert actor.position == before and not engine.grid.step_legal(before, end,
            occupied_cells=engine._occupied_cells_except(actor.entity_id), footprint=engine._footprint(actor))
        obj = objects.blocker_at(engine, end)
        assert obj is not None
        objects.deal(engine, actor, obj, [(2, "BLUDGEONING")], ctx.source)

    monkeypatch.setitem(ext._EFFECTS, "test_lock27c_collide", collide)

    def actions(info):
        def action(source, label, kind, effects, **typed):
            return ActionDefinition(source_definition_id=source, display_name=label,
                owner_id=info["actor_id"], economy="NONE", resolution_kind="TYPED",
                target_kind=kind, range_ft=reach if kind == "OBJECT" else 60,
                parameters={"any_cell": kind == "CELL", "typed": {
                    "source": source, "numbers": info["numbers"], "duration": {"kind": "instant"},
                    "effects": effects, **typed}})
        return [action(PLACE, "Place test workbench", "SELF", [{"type": "test_lock27c_place"}]),
                action(COLLIDE, "Test collision", "SELF", [{"type": "test_lock27c_collide"}]),
                action(HIT, "Damage test workbench", "OBJECT", [
                    {"type": "object_damage", "flat": 10, "damage_types": ["FORCE"],
                     **({"on_destroy": burst} if burst else {})}]),
                action(AREA, "Test blast", "CELL", [
                    {"type": "damage", "dice": {"count": 1, "sides": 2, "modifier": 0},
                     "damage_types": ["FORCE"]}], area=area or {"shape": "cube", "size_ft": 5})]

    install(monkeypatch, "compile_actions", actions)
    install(monkeypatch, "compile_passives", lambda rows, info: [*rows,
        {"block": "object_damage", "on": "technique", "feature_id": AREA}])
    battlefield = to_battlefield(normalize_map({"display_name": "Object cells test",
        "width_squares": 20, "height_squares": 14,
        "walls": [{"shape": "rect", "points": [[x, y], [x + 1, y + 1]], "filled": True}
                  for x, y in walls],
        "starts": {"team1": [list(me_at)], "team2": [list(foe_at)]}}))
    mid, session = _match(tmp_path, "LOCK27C", me_at=me_at, foe_at=foe_at, battlefield=battlefield)
    return mid, _execute(tmp_path, mid, lambda c: c.source_definition_id == PLACE)


def occupied(engine):
    return {(p.x, p.y) for p in target_cells(engine, engine.state.objects[OID])}


def assert_blocking(engine, cells):
    assert cells <= engine.grid.blocked
    assert cells <= engine.grid.cover
    for x, y in cells:
        assert objects.blocker_at(engine, Position(x=x, y=y)).object_id == OID
        # A ray crossing either occupied cell is stopped: full physical cover.
        start, end = Position(x=x, y=y - 1), Position(x=x, y=y + 1)
        assert not engine.grid.line_of_sight(start, end)
        assert engine.cover_from((start,), ME, engine.state.actors[ME], target_cells=(end,))["blocked"]
        assert engine.grid.cover_bonus(start, end) == 2
    moves = [c.destination for c in engine.legal_candidates() if c.kind.value == "MOVE"]
    assert not any(p is not None and (p.x, p.y) in cells for p in moves)


@pytest.mark.parametrize("rotation,cells,me_at", [
    (0, {(5, 6), (6, 6)}, (7, 6)),
    (90, {(5, 6), (5, 7)}, (5, 8)),
])
def test_both_cells_block_cover_collide_and_free_on_destruction(tmp_path, monkeypatch, rotation, cells, me_at):
    mid, session = setup(tmp_path, monkeypatch, rotation=rotation, me_at=me_at)
    assert occupied(session.engine) == cells
    assert_blocking(session.engine, cells)
    # The near (non-anchor) end alone is in 5-foot reach. Commit a real object
    # action; one damage event destroys the shared HP pool and its entire zone.
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == HIT and c.target_ids == (OID,))
    assert cold.engine.state.objects[OID].destroyed
    assert cold.engine.state.objects[OID].current_hp == 0
    assert occupied(cold.engine) == cells  # dimensions survive destruction too
    for x, y in cells:
        assert (x, y) not in cold.engine.grid.blocked | cold.engine.grid.cover
        assert objects.blocker_at(cold.engine, Position(x=x, y=y)) is None
        assert cold.engine.grid.line_of_sight(Position(x=x, y=y - 1), Position(x=x, y=y + 1))
    assert len([e for e in cold.engine.events if e.event_type == "OBJECT_UPDATED"
                and e.payload.get("damage")]) == 1
    assert cold.verify()["status"] == "PASS"
    # Both formerly occupied cells accept actual moves after destruction,
    # committed through the session and independently cold-reloaded/replayed.
    for x, y in sorted(cells, reverse=True):
        cold = _execute(tmp_path, mid, lambda c: c.kind.value == "MOVE"
                        and c.destination == Position(x=x, y=y))
        assert cold.engine.state.actors[ME].position == Position(x=x, y=y)


@pytest.mark.parametrize("me_at", [(4, 6), (7, 6), (5, 5), (6, 7)])
def test_target_either_visible_end_once_and_reload_replay(tmp_path, monkeypatch, me_at):
    mid, session = setup(tmp_path, monkeypatch, me_at=me_at)
    candidates = [c for c in session.engine.legal_candidates() if c.source_definition_id == HIT]
    assert len(candidates) == 1 and candidates[0].target_ids == (OID,)
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == HIT)
    assert cold.engine.state.objects[OID].destroyed


@pytest.mark.parametrize("cell", [(5, 6), (6, 6)])
def test_forced_collision_with_either_cell_stops_and_damages_one_object(tmp_path, monkeypatch, cell):
    mid, session = setup(tmp_path, monkeypatch, me_at=(cell[0], 4), collision_at=cell)
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == COLLIDE)
    assert cold.engine.state.actors[ME].position == Position(x=cell[0], y=5)
    assert cold.engine.state.objects[OID].current_hp == 8
    updates = [e for e in cold.engine.events if e.event_type == "OBJECT_UPDATED" and e.payload.get("damage")]
    assert len(updates) == 1 and updates[0].source_definition_id == COLLIDE
    assert_blocking(cold.engine, {(5, 6), (6, 6)})


def test_near_hidden_cell_cannot_borrow_out_of_range_visible_cell(tmp_path, monkeypatch):
    # Nonblocking furniture isolates the wall: the near anchor's ray crosses
    # (4,6); the far end's ray avoids it, but that end is outside 15-foot reach.
    mid, session = setup(tmp_path, monkeypatch, me_at=(2, 5), walls=((4, 6),), blocks=False, reach=15)
    actor = session.engine.state.actors[ME]
    assert (4, 6) in session.engine.grid.blocked
    near, far = Position(x=5, y=6), Position(x=6, y=6)
    assert session.engine._effect_distance_to_cell(actor, near) == 15
    assert not session.engine._line_of_sight_actor_to_cell(actor, near)
    assert session.engine._effect_distance_to_cell(actor, far) == 20
    assert session.engine._line_of_sight_actor_to_cell(actor, far)
    assert not any(c.source_definition_id == HIT for c in session.engine.legal_candidates())
    cold = _execute(tmp_path, mid)
    assert not cold.engine.state.objects[OID].destroyed


@pytest.mark.parametrize("aim,rotation", [((5, 6), 0), ((6, 6), 0), ((5, 6), 90), ((5, 7), 90)])
def test_area_touching_either_cell_damages_once_after_reload_and_replay(tmp_path, monkeypatch, aim, rotation):
    mid, session = setup(tmp_path, monkeypatch, rotation=rotation, me_at=(3, 4))
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == AREA
                    and c.destination == Position(x=aim[0], y=aim[1]))
    obj = cold.engine.state.objects[OID]
    updates = [e for e in cold.engine.events if e.event_type == "OBJECT_UPDATED" and e.payload.get("damage")]
    assert len(updates) == 1
    assert 0 < updates[0].payload["damage"]["taken"] <= 2
    assert obj.current_hp == 10 - updates[0].payload["damage"]["taken"]
    assert cold.verify()["status"] == "PASS"


def test_area_cannot_damage_through_an_unrelated_wall(tmp_path, monkeypatch):
    mid, session = setup(tmp_path, monkeypatch, me_at=(3, 4),
        walls=tuple((x, 5) for x in range(20)), area={"shape": "sphere", "size_ft": 15})
    # Both cells are inside the blast's radius, but behind a solid wall.
    assert all((x, 5) in session.engine.grid.blocked for x in range(20))
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == AREA
                    and c.destination == Position(x=5, y=4))
    assert cold.engine.state.objects[OID].current_hp == 10


def test_area_covering_both_cells_damages_shared_hp_only_once(tmp_path, monkeypatch):
    mid, session = setup(tmp_path, monkeypatch, me_at=(3, 4), area={"shape": "sphere", "size_ft": 10})
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == AREA
                    and c.destination == Position(x=5, y=5))
    updates = [e for e in cold.engine.events if e.event_type == "OBJECT_UPDATED" and e.payload.get("damage")]
    assert len(updates) == 1
    assert cold.engine.state.objects[OID].current_hp == 10 - updates[0].payload["damage"]["taken"]


def test_legacy_single_cell_has_no_dimension_inference(tmp_path, monkeypatch):
    mid, session = setup(tmp_path, monkeypatch, legacy=True)
    engine = session.engine
    assert occupied(engine) == {(5, 6)}
    assert (5, 6) in engine.grid.blocked and (6, 6) not in engine.grid.blocked
    assert "width_cells" not in engine.state.objects[OID].component
    assert not any(c.source_definition_id == HIT for c in engine.legal_candidates())
    cold = _execute(tmp_path, mid)
    assert cold.engine.state.objects[OID].model_dump(mode="json") == engine.state.objects[OID].model_dump(mode="json")


@pytest.mark.parametrize("component", [
    {"width_cells": 0, "length_cells": 1}, {"width_cells": True, "length_cells": 1},
    {"width_cells": 2}, {"width_cells": 2, "length_cells": 1, "rotation": 45},
    {"width_cells": 2000000, "length_cells": 1},
])
def test_malformed_dimensions_are_rejected_not_silently_single_cell(tmp_path, monkeypatch, component):
    mid, session = setup(tmp_path, monkeypatch)
    obj = session.engine.state.objects[OID].model_copy(update={"component": component})
    with pytest.raises(ValueError, match="object_target_cells"):
        target_cells(session.engine, obj)


@pytest.mark.parametrize("rotation,foe_at,legacy,affected", [
    (0, (7, 6), False, True),  # far end: ten feet from anchor, five from object
    (90, (5, 8), False, True),
    (0, (6, 7), False, True),  # adjacent to both cells: still one save/damage
    (0, (7, 6), True, False),  # dimensionless object retains anchor-only burst
    (0, (6, 7), True, True),
])
def test_destruction_burst_occupied_cells_once_commit_reload_replay(
        tmp_path, monkeypatch, rotation, foe_at, legacy, affected):
    from combat.gate2_runtime_content import AN

    # The production Shatter Vessel burst schema, without its separate choice
    # menu: this test exercises the selected burst via the real object effect.
    burst = {"radius_ft": 5, "effects": [{"type": "save", "ability": "dex",
        "dc": "technique_save_dc", "on_fail": [{"type": "damage", "applies_to": "target",
        "dice": {"count": 1, "sides": 8}, "damage_types": ["thunder"]}], "on_success": []}]}
    install(monkeypatch, "save_bonus", lambda engine, target, ability, dc, source, intent:
            -40 if source == HIT else None)
    mid, session = setup(tmp_path, monkeypatch, rotation=rotation, legacy=legacy,
        me_at=(3, 6), reach=60, blocks=False, burst=burst, foe_at=foe_at)
    before = session.engine.state.actors[AN].current_hp
    cold = _execute(tmp_path, mid, lambda c: c.source_definition_id == HIT)
    assert cold.engine.state.objects[OID].destroyed
    saves = [e for e in cold.engine.events if e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == HIT and e.actor_id == AN]
    damage = [e for e in cold.engine.events if e.event_type == "DAMAGE_COMMITTED"
              and e.source_definition_id == HIT and e.target_ids == (AN,)]
    assert len(saves) == len(damage) == int(affected)
    after = cold.engine.state.actors[AN].current_hp
    assert (1 <= before - after <= 8) if affected else after == before
    if affected:
        assert saves[0].payload["success"] is False
        assert damage[0].payload["damage_type"].upper() == "THUNDER"
        assert damage[0].payload["hp_damage"] == before - after
    assert not any(e.event_type == "SAVE_ROLLED" and e.source_definition_id == HIT
                   and e.actor_id == ME for e in cold.engine.events)
    assert cold.verify()["status"] == "PASS"
    assert cold.mechanical.replay()["status"] == "PASS"
