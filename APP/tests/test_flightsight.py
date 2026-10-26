"""Physical flight routes and perception, including persisted table decisions."""
import pytest

from combat import flight, senses, target_knowledge
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, duel
from tests.test_lock10_flight_movement import grant
from tests.test_save_reload_equivalence import _install_factory


def p(x, y, z=0):
    return Position(x=x, y=y, z=z)


@pytest.mark.parametrize("destination", [p(6, 6), p(0, 6), p(6, 8), p(1, 3), p(3, 6)])
def test_descent_has_shortest_monotone_horizontal_projection(destination):
    engine = duel([])
    engine.grid = SquareGrid({"width_squares": 12, "height_squares": 12, "square_size_ft": 5,
                              "starting_positions": {}, "terrain_regions": []})
    actor = engine.state.actors[ME]
    actor.position = p(3, 6, 6)
    grant(engine, actor, flight_hover=1)
    path, cost, mode = flight.reachable(engine, actor)[destination]
    assert cost == 30 and mode == "fly" and len(path) == 7
    assert sum(a.x != b.x or a.y != b.y for a, b in zip(path, path[1:])) == max(
        abs(destination.x - actor.position.x), abs(destination.y - actor.position.y))
    for coordinate in ("x", "y"):
        delta = getattr(destination, coordinate) - getattr(actor.position, coordinate)
        steps = [getattr(b, coordinate) - getattr(a, coordinate) for a, b in zip(path, path[1:])]
        assert all(step == 0 or (step > 0) == (delta > 0) for step in steps)
        if delta == 0:
            assert not any(steps)
    assert flight.reachable(engine, actor)[destination] == (path, cost, mode)


def table_yard(tmp_path, obstacle, *, mode="cell", airborne=False, altitude=6, roof_cells=()):
    ids, bundles = _install_factory(tmp_path, "flightsight", [], None)
    combat = CombatService(ROOT, tmp_path)
    document = normalize_map({"display_name": "Flight sight yard", "width_squares": 10,
        "height_squares": 8, "walls": [],
        "starts": {"team1": [[2, 3]], "team2": [[5, 3]]}})
    arena = to_battlefield(document)
    arena['roof_cells'] = list(roof_cells)
    if obstacle in ("object", "tall-object"):
        arena["map_objects"] = [{"id": 1, "kind": "pillar", "x": 3, "y": 3,
                                  "height_ft": 60 if obstacle == "tall-object" else 10, "blocks": True}]
    else:
        height, bottom = obstacle
        arena["terrain_regions"] = [{"region_id": "test:wall", "terrain_type": "SIGHT_BLOCKED",
            "occluder": mode, "movement_cost": 1, "cells": [{"x": 3, "y": y} for y in range(8)],
            "height_ft": height, "base_altitude_ft": bottom}]
    # Seal intrinsic flight into synthetic input; do not wrap engine methods
    # to grant it during a transaction. Starting altitude is independent.
    from combat.canonical import canonical_sha256
    bundles[0]["actor_template"].update(fly_speed_ft=30, hover=True)
    bundles[0].pop("bundle_sha256")
    bundles[0]["bundle_sha256"] = canonical_sha256(bundles[0])
    mid = combat._finish_factory_match(bundles, ids, {ids[0]: "team:a", ids[1]: "team:b"},
        {ids[0]: {"x": 2, "y": 3, "z": altitude if airborne else 0}, ids[1]: {"x": 5, "y": 3}}, arena, [ids[0]], [ids[1]],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed="FLIGHTSIGHT", display_name="Flight sight",
        maximum_rounds=10)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid, ids


@pytest.mark.parametrize("obstacle", [(10, 0), (60, 0), (10, 20), "object", "tall-object"])
@pytest.mark.parametrize("mode", ["cell", "centerline"])
def test_table_fog_creature_and_ai_sight_use_height_after_commit_and_cold_reload(tmp_path, obstacle, mode):
    combat, table, mid, (viewer_id, target_id) = table_yard(tmp_path, obstacle, mode=mode)
    for _ in range(4):
        state = table.state(mid)
        if state["menu"]["actor_id"] == viewer_id:
            break
        menu = state["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    state = table.state(mid, fog=True)
    visible_on_ground = obstacle == (10, 20)
    assert ([5, 3] in state["fog_perception"][viewer_id]["cells"]) == visible_on_ground
    assert (target_id in state["fog_perception"][viewer_id]["creatures"]) == visible_on_ground
    engine = combat._load_session(mid).engine
    move = next(c for c in engine.legal_candidates() if c.kind == "MOVE" and c.destination == p(2, 3, 6))
    assert table.act(mid, move.candidate_id, move.decision_id, move.state_version, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
    fresh_combat = CombatService(ROOT, tmp_path)
    fresh = TabletopService(fresh_combat, tmp_path).state(mid, fog=True)
    loaded = fresh_combat._load_session(mid)
    viewer, target = (loaded.engine.state.actors[aid] for aid in (viewer_id, target_id))
    assert viewer.position == p(2, 3, 6)
    visible = obstacle in ((10, 0), "object")
    perception = fresh["fog_perception"][viewer_id]
    assert ([5, 3] in perception["cells"]) == visible
    assert (target_id in perception["creatures"]) == visible
    assert senses.perception(loaded.engine, viewer) == perception
    assert target_knowledge.can_see(loaded.engine, viewer, target) == visible
    known = target_knowledge.knowledge(loaded.engine, viewer, target)
    assert bool(known and known.mode == "DIRECT") == visible
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("bottom,height,visible", [(0, 8, False), (10, 5, True)])
def test_cell_obstacle_uses_actual_ray_height_not_rounded_voxel(bottom, height, visible):
    grid = SquareGrid({"width_squares": 8, "height_squares": 8, "square_size_ft": 5,
        "starting_positions": {}, "terrain_regions": [{"terrain_type": "SIGHT_BLOCKED", "movement_cost": 1,
        "height_ft": height, "base_altitude_ft": bottom, "cells": [{"x": 2, "y": 3}]}]})
    # Ray height in the obstacle is 5.625..9.375 ft, despite a rounded 10-ft voxel.
    assert grid.line_of_sight(p(0, 3), p(4, 3, 3)) == visible
    assert grid.line_of_sight(p(4, 3, 3), p(0, 3)) == visible


def test_perception_uses_physical_viewer_not_scoped_attack_origin():
    from combat.action_geometry import activate
    engine = duel([])
    viewer, target = engine.state.actors[ME], next(a for aid, a in engine.state.actors.items() if aid != ME)
    engine.grid = SquareGrid({"width_squares": 12, "height_squares": 12, "square_size_ft": 5,
        "starting_positions": {}, "terrain_regions": [{"terrain_type": "SIGHT_BLOCKED", "movement_cost": 1,
        "height_ft": 10, "cells": [{"x": 4, "y": y} for y in range(12)]}]})
    viewer.position, target.position = p(3, 6, 6), p(6, 6)
    with activate(engine, viewer, "test:origin", {"id": "test:ground", "label": "Ground origin", "position": {"x": 3, "y": 6}}):
        assert senses.perceives_cell(engine, viewer, target.position)
        assert target_knowledge.can_see(engine, viewer, target)


def test_table_descent_uses_short_projection_in_menu_commit_and_reload(tmp_path):
    combat, table, mid, (viewer_id, _) = table_yard(tmp_path, (0, 0), airborne=True)
    for _ in range(4):
        state = table.state(mid)
        menu = state["menu"]
        if menu["actor_id"] == viewer_id:
            break
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    move = next(c for c in engine.legal_candidates() if c.kind == "MOVE" and c.destination == p(5, 4))
    path = move.canonical_path
    assert move.movement_cost_ft == 30 and len(path) == 7
    assert sum(a.x != b.x or a.y != b.y for a, b in zip(path, path[1:])) == 3
    assert all(a.x <= b.x and a.y <= b.y for a, b in zip(path, path[1:]))
    option = next(o for o in state["menu"]["moves"] if o["candidate_id"] == move.candidate_id)
    assert option["cost_ft"] == 30
    assert option["path"] == [cell.model_dump(mode="json") for cell in path]
    assert table.act(mid, move.candidate_id, move.decision_id, move.state_version, state["last_sequence"])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[viewer_id].position == p(5, 4)
    event = next(e for e in reversed(loaded.engine.events) if e.event_type == "MOVEMENT_COMMITTED")
    assert event.payload["path"] == [cell.model_dump(mode="json") for cell in path]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_spatial_safety_selector_compares_with_short_projected_default():
    from combat.movement_routes import safe_selector
    from combat.spatial_routes import horizontal_steps, projected_path
    engine = duel([])
    start, left, right, goal = (3, 6, 6), (2, 5, 5), (3, 6, 5), (3, 6, 4)
    previous = {left: frozenset({start}), right: frozenset({start}), goal: frozenset({left, right})}
    costs = {start: 0, left: 5, right: 5, goal: 10}
    parents = {left: start, right: start, goal: left}  # old arbitrary default wanders left
    engine.grid.qi_hazard.update({(3, 6, 5), (3, 6, 4)})
    # Projection stays in the hazardous column twice; the detour enters once.
    chosen = safe_selector(engine, engine.state.actors[ME])(start, previous, costs, parents)
    default = tuple(reversed(projected_path(start, goal, previous, horizontal_steps(start, previous, costs))))
    assert default == (start, right, goal)
    assert chosen[goal] == (start, left, goal)


@pytest.mark.parametrize("mode", ["cell", "centerline"])
def test_vertical_sight_cannot_pass_through_a_raised_roof(mode):
    grid = SquareGrid({"width_squares": 8, "height_squares": 8, "square_size_ft": 5,
        "starting_positions": {}, "terrain_regions": [{"terrain_type": "SIGHT_BLOCKED", "movement_cost": 1,
        "occluder": mode, "height_ft": 5, "base_altitude_ft": 10, "cells": [{"x": 2, "y": 3}]}]})
    assert not grid.line_of_sight(p(2, 3, 6), p(2, 3))
    assert not grid.line_of_sight(p(2, 3), p(2, 3, 6))
    assert grid.line_of_sight(p(2, 3, 6), p(2, 3, 4))


@pytest.mark.parametrize("mode", ["cell", "centerline"])
def test_zero_height_obstacle_and_near_side_endpoint_remain_visible(mode):
    def grid(height):
        return SquareGrid({"width_squares": 8, "height_squares": 8, "square_size_ft": 5,
            "starting_positions": {}, "terrain_regions": [{"terrain_type": "SIGHT_BLOCKED", "movement_cost": 1,
            "occluder": mode, "height_ft": height, "base_altitude_ft": 2, "cells": [{"x": 2, "y": 3}]}]})
    assert grid(0).line_of_sight(p(2, 3), p(2, 3, 1))
    assert not grid(1).line_of_sight(p(2, 3), p(2, 3, 1))
    assert grid(10).line_of_sight(p(2, 3), p(2, 3, 1))  # see the roof's near side
