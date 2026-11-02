"""MAPS3: four new builtin-realm-* arenas with starts further apart and sheltered
from the enemy's first view, each with several routes and a movement-changing
terrain feature. Data-driven so it generalizes to every shipped "big arena" map."""
import heapq
import json
from pathlib import Path
from statistics import median
from time import perf_counter

import pytest

from combat.canonical import canonical_sha256
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, rasterize, to_battlefield
from combat.tabletop_service import TabletopService
from tests.test_builtin_arenas import MAPS3_IDS, ROOT, _fight

MIN_START_DISTANCE = 25
SIZES = {
    "builtin-realm-sunken-marsh": (48, 32),
    "builtin-realm-market-quarter": (52, 34),
    "builtin-realm-waterfall-gorge": (50, 36),
    "builtin-realm-maple-shrine": (48, 36),
}


def _reached_and_blocked(doc):
    blocked, _ = rasterize(doc)
    starts = [tuple(c) for side in doc["starts"].values() for c in side]
    reached, pending = {starts[0]}, [starts[0]]
    w, h = doc["width_squares"], doc["height_squares"]
    while pending:
        x, y = pending.pop()
        for p in [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]:
            if 0 <= p[0] < w and 0 <= p[1] < h and p not in blocked and p not in reached:
                reached.add(p)
                pending.append(p)
    return reached, blocked


def _shortest_path(reached, difficult, extra_blocked, origin, goals, w, h):
    """Dijkstra (difficult terrain costs double) over ``reached``, pretending
    ``extra_blocked`` cells are walls too. Returns (cost, full path incl. origin/goal)
    or (None, None) if ``goals`` is unreachable from ``origin`` under that restriction."""
    distances, came_from = {origin: 0}, {}
    queue = [(0, origin)]
    goal = None
    while queue:
        cost, p = heapq.heappop(queue)
        if cost != distances[p]:
            continue
        if p in goals:
            goal = p
            break
        x, y = p
        for c in [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]:
            if c not in reached or c in extra_blocked:
                continue
            new = cost + (2 if c in difficult else 1)
            if new < distances.get(c, 1 << 30):
                distances[c] = new
                came_from[c] = p
                heapq.heappush(queue, (new, c))
    if goal is None:
        return None, None
    path = [goal]
    while path[-1] in came_from:
        path.append(came_from[path[-1]])
    path.reverse()
    return distances[goal], path


def _has_independent_second_route(reached, difficult, origin, goals, w, h):
    """True if, after deleting the interior squares of the shortest origin->goals path
    (every square but the origin and the one goal it reached), another path still
    connects them. A later edit that removes the alternate route and leaves a single
    mandatory crossing will make this return False (see the negative-control test)."""
    cost, path = _shortest_path(reached, difficult, set(), origin, goals, w, h)
    if path is None:
        return None, None
    interior = set(path[1:-1])
    cost2, path2 = _shortest_path(reached, difficult, interior, origin, goals, w, h)
    return cost, path2 is not None


@pytest.mark.parametrize("map_id", MAPS3_IDS)
def test_editor_validation_starts_and_battlefield(tmp_path, map_id):
    doc = CombatService(ROOT, tmp_path).tabletop_maps.get(map_id)
    assert (doc["width_squares"], doc["height_squares"]) == SIZES[map_id]
    assert normalize_map(doc) == {k: v for k, v in doc.items() if k != "cells"}
    blocked, sight = rasterize(doc)
    assert blocked == set(map(tuple, doc["cells"]["blocked"]))
    assert sight == set(map(tuple, doc["cells"]["sight"]))
    starts = [tuple(c) for side in doc["starts"].values() for c in side]
    assert len(starts) == len(set(starts)) == 12
    assert all(len(side) == 6 for side in doc["starts"].values())
    assert all(0 <= x < doc["width_squares"] and 0 <= y < doc["height_squares"] for x, y in starts)
    assert not blocked.intersection(starts)
    assert doc["picker_order"] >= 50 and doc["description"]
    canonical_sha256(to_battlefield(doc))
    copied = CombatService(ROOT, tmp_path).tabletop_maps.save({**doc, "map_id": "copy-" + map_id})
    assert copied["cells"] == doc["cells"]


@pytest.mark.parametrize("map_id", MAPS3_IDS)
def test_every_start_reaches_every_enemy_start_at_25_squares_or_more(tmp_path, map_id):
    doc = CombatService(ROOT, tmp_path).tabletop_maps.get(map_id)
    reached, _ = _reached_and_blocked(doc)
    starts = [tuple(c) for side in doc["starts"].values() for c in side]
    assert set(starts) <= reached, f"{map_id}: not every start is on the same connected area"
    difficult = {tuple(c) for row in doc["terrain"] if row["type"] == "DIFFICULT" for c in row["cells"]}
    w, h = doc["width_squares"], doc["height_squares"]
    for side, other in [("team1", "team2"), ("team2", "team1")]:
        opponents = set(map(tuple, doc["starts"][other]))
        for origin in map(tuple, doc["starts"][side]):
            cost, has_second = _has_independent_second_route(reached, difficult, origin, opponents, w, h)
            assert cost is not None, f"{map_id}: {origin} cannot path to any {other} start"
            assert cost >= MIN_START_DISTANCE, (
                f"{map_id}: {origin} reaches a {other} start in {cost} squares (< {MIN_START_DISTANCE})")
            # Delete every square on the shortest route (but its two ends) and require that a
            # second, independent route still gets across: proves at least two routes share no
            # cut square, not just that two shortest-path midpoints happen to differ.
            assert has_second, (
                f"{map_id}: {origin} has no route to a {other} start independent of its shortest "
                f"path -- removing that path's interior squares leaves no alternative, i.e. a "
                f"single mandatory crossing")


def test_route_independence_check_fails_on_a_single_mandatory_crossing():
    """Negative control for the assertion above: two rooms joined by exactly one
    corridor square must make _has_independent_second_route report False, proving the
    check actually catches a map with no alternate route (and isn't vacuously true)."""
    w, h = 11, 5
    blocked = {(5, y) for y in range(h) if y != 2}  # a wall across x=5 with a single gap at y=2
    reached, pending = {(0, 2)}, [(0, 2)]
    while pending:
        x, y = pending.pop()
        for p in [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]:
            if 0 <= p[0] < w and 0 <= p[1] < h and p not in blocked and p not in reached:
                reached.add(p)
                pending.append(p)
    origin, goals = (0, 2), {(10, 2)}
    cost, has_second = _has_independent_second_route(reached, set(), origin, goals, w, h)
    assert cost == 10  # the single route still exists and is found
    assert not has_second, "a map with one mandatory crossing must fail the independent-route check"

    # Sanity: open a second gap in the wall and the same check now passes.
    blocked_two_gaps = blocked - {(5, 0)}
    reached2, pending2 = {(0, 2)}, [(0, 2)]
    while pending2:
        x, y = pending2.pop()
        for p in [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]:
            if 0 <= p[0] < w and 0 <= p[1] < h and p not in blocked_two_gaps and p not in reached2:
                reached2.add(p)
                pending2.append(p)
    cost2, has_second2 = _has_independent_second_route(reached2, set(), origin, goals, w, h)
    assert has_second2, "a second gap in the wall must give an independent second route"


@pytest.mark.parametrize("map_id", MAPS3_IDS)
def test_no_start_has_line_of_sight_to_an_enemy_start(tmp_path, map_id):
    doc = CombatService(ROOT, tmp_path).tabletop_maps.get(map_id)
    grid = SquareGrid(to_battlefield(doc))
    for a in map(tuple, doc["starts"]["team1"]):
        for b in map(tuple, doc["starts"]["team2"]):
            assert not grid.line_of_sight(Position(x=a[0], y=a[1]), Position(x=b[0], y=b[1])), (
                f"{map_id}: start {a} has line of sight to enemy start {b}")


@pytest.mark.parametrize("map_id", MAPS3_IDS)
def test_at_least_one_movement_changing_terrain_feature(tmp_path, map_id):
    doc = CombatService(ROOT, tmp_path).tabletop_maps.get(map_id)
    difficult = any(row["type"] == "DIFFICULT" for row in doc["terrain"])
    named_terrain = any(row["material"].startswith("terrain:") for row in doc["materials"])
    assert difficult or named_terrain, f"{map_id}: no difficult-ground/shallow-water/named terrain feature"
    assert any(row["type"] == "SIMPLE_COVER" for row in doc["terrain"]), f"{map_id}: no low-cover cluster"


@pytest.mark.parametrize("map_id", MAPS3_IDS)
def test_short_real_ai_fight_commit_cold_reload(tmp_path, map_id):
    combat, mid = _fight(tmp_path, "battlefield:map." + map_id, size=2, rounds=1)
    sealed = combat._load_session(mid).engine.battlefield_document
    table = TabletopService(combat, tmp_path)
    initial = table.state(mid)
    assert initial["map"]["map_id"] == map_id
    assert table.auto_step(mid, initial["last_sequence"])["status"] == "COMMITTED"
    for _ in range(180):
        if combat._load_session(mid).engine.state.terminal_result:
            break
        combat.local_step(mid)
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.engine.state.terminal_result
    assert cold.engine.battlefield_document == sealed
    assert any(e.event_type == "MOVEMENT_COMMITTED" for e in cold.engine.events)
    assert cold.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("map_id", MAPS3_IDS)
def test_twelve_person_fight_has_all_twelve_legal_starts(tmp_path, map_id):
    combat, mid = _fight(tmp_path, "battlefield:map." + map_id, size=6, rounds=1)
    engine = combat._load_session(mid).engine
    assert len(engine.state.actors) == 12
    positions = {(a.position.x, a.position.y) for a in engine.state.actors.values()}
    assert len(positions) == 12
    assert positions == {tuple(c) for side in combat.tabletop_maps.get(map_id)["starts"].values() for c in side}
    assert combat.replay(mid)["status"] == "PASS"


def test_maps3_build_and_ai_step_timing_vs_mountain_pass(tmp_path, capsys):
    results = {}
    for map_id in ["builtin-mountain-pass"] + MAPS3_IDS:
        arena_id = "battlefield:map." + map_id
        before = perf_counter()
        combat, mid = _fight(tmp_path / map_id, arena_id, size=6, rounds=2)
        build_seconds = perf_counter() - before
        timings = []
        for _ in range(180):
            if combat._load_session(mid).engine.state.terminal_result:
                break
            before = perf_counter()
            combat.local_step(mid)
            timings.append(perf_counter() - before)
        assert timings, f"{map_id}: no AI step ran"
        results[map_id] = {"build": round(build_seconds, 4), "median_step": round(median(timings), 4),
                            "mean_step": round(sum(timings) / len(timings), 4), "steps": len(timings)}
    baseline = results["builtin-mountain-pass"]
    for map_id in MAPS3_IDS:
        row = results[map_id]
        # Informational SLA: a new, larger map may cost more, but should stay in the
        # same order of magnitude as the smallest reference arena, not 5x it.
        assert row["median_step"] <= max(baseline["median_step"] * 5, 0.05), (
            f"{map_id}: median AI step {row['median_step']}s is much slower than "
            f"mountain-pass's {baseline['median_step']}s")
    with capsys.disabled():
        print("MAPS3 build/AI-step timing seconds (vs builtin-mountain-pass): " + json.dumps(results), flush=True)
