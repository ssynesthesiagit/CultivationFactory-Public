"""ARENA1: shipped editor maps, team starts, sealed scenery and classic replays."""
import heapq
import json
from pathlib import Path
from time import perf_counter

import pytest
from tests.legacy_fight_support import legacy_zero_hp

from combat import object_rules, zones
from combat.canonical import canonical_sha256
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService, DEFAULT_FACTORY_ARENA, FACTORY_ACTOR_PREFIX
from combat.tabletop import TabletopError, TabletopMapStore, normalize_map, rasterize, to_battlefield, _segment_cells
from combat.tabletop_service import TabletopService
from tests.test_factory_live_match import _install
from tests.retired_arena_support import HistoricalArenaWriter

ROOT = Path(__file__).resolve().parents[1]
IDS = ["builtin-pillar-arena", "builtin-mist-courtyard", "builtin-sect-trial-platform",
       "builtin-bamboo-forest-ravine", "builtin-ruined-spirit-shrine", "builtin-mountain-pass"]
CLASSIC = ["battlefield:factory_pillar_arena", "battlefield:factory_mist_courtyard"]
NEW_IDS = ["builtin-willow-village-compound", "builtin-emerald-canopy",
           "builtin-cloudwater-crossing", "builtin-jade-sutra-hall"]
MAPS3_IDS = ["builtin-realm-sunken-marsh", "builtin-realm-market-quarter",
             "builtin-realm-waterfall-gorge", "builtin-realm-maple-shrine"]
# MAPS4 (owner 2026-10-13: "further away, bigger areas, interesting layouts"): four big
# builtin-frontier-* arenas, 6 sheltered starts per team, >=25 squares apart, no enemy LoS.
MAPS4_IDS = ["builtin-frontier-bandit-camp", "builtin-frontier-salt-caravanserai",
             "builtin-frontier-bamboo-imperial-tomb", "builtin-frontier-frozen-fishing-lake"]
# movement-changing terrains a shipped map may use (must be an existing terrain.json entry).
MAPS_DIFFICULT_TERRAINS = {"loose rubble", "bamboo thicket", "mundane ice", "mundane snow"}
# MAPS1 (owner 2026-10-13): bigger arenas with starts at least 25 squares apart by path,
# several routes, chokepoints and open ground, and a start never in the far side's line of sight.
MAPS1_IDS = ["builtin-river-delta-isles", "builtin-ruined-sect-terraces", "builtin-ricefield-bamboo-valley",
             "builtin-sunken-cavern-lake", "builtin-frontier-fortress-wall"]
# Retired 2026-10-13 (owner: stamped rubble rows look bad) until MAPART1 redraws it; still loads for old fights.
MAPS1_RETIRED: set[str] = set()  # Fortress Wall back after MAPART1 redrew its rubble (2026-10-13)
MAPS1_ACTIVE = [m for m in MAPS1_IDS if m not in MAPS1_RETIRED]
RETIRED_IDS = IDS[:2]
ACTIVE_IDS = IDS[2:]
# Lock20 admits friendly-fire and compiled-cost scoring: harmful Mountain-Moving
# Palm cones lose to Dash in these typed fixtures. Stock controls remain separate.
# Old/new hashes, first decisions and passing replay: astra/lock20-run/arena-comparison.json.
CLASSIC_FINAL_HASHES = {
    CLASSIC[0]: "86c0cb7580d19b8b0fe8294979161317e4fde0fd37133da4bf51b8f932032ffb",
    CLASSIC[1]: "fbe971259fde34c67401783d943d044c0cbbd86cd1d21d9e24e5e84b679037b4",
}
CLASSIC_EVENT_HASHES = {
    CLASSIC[0]: "c42860f1c937646f5abd93f46e2b3b52caa3e731456702bd382cb4e6289d0283",
    CLASSIC[1]: "a2722433dce06966c996ff667def8c69b46854ce3a9e3ef11fb42f6a99e9ba24",
}


def _fight(tmp_path, arena_id, size=2, rounds=3):
    left = [f"west-{i}" for i in range(size)]
    right = [f"east-{i}" for i in range(size)]
    for pid in left + right:
        _install(tmp_path, pid)
    service = (HistoricalArenaWriter if arena_id in CLASSIC else CombatService)(ROOT, tmp_path)
    view = service.create_factory_match(
        project_ids=left, opponent_actor_ids=[FACTORY_ACTOR_PREFIX + pid for pid in right],
        arena_id=arena_id, maximum_rounds=rounds, match_seed=f"ARENA1-{arena_id}-{size}",
    )
    return service, view["match_id"]


@pytest.mark.parametrize("map_id", IDS)
def test_shipped_maps_validate_and_have_reachable_safe_starts(tmp_path, map_id):
    store = CombatService(ROOT, tmp_path).tabletop_maps
    doc = store.get(map_id)
    normalized = normalize_map(doc)
    assert {k: v for k, v in doc.items() if k != "cells"} == normalized
    blocked, _ = rasterize(doc)
    assert set(map(tuple, doc["cells"]["blocked"])) == blocked
    starts = [tuple(cell) for side in doc["starts"].values() for cell in side]
    assert len(starts) == len(set(starts)) == 6
    assert not blocked.intersection(starts)
    # A flood fill catches an accidentally sealed start or a divided arena.
    reached, pending = {starts[0]}, [starts[0]]
    while pending:
        x, y = pending.pop()
        for point in [(x-1,y), (x+1,y), (x,y-1), (x,y+1)]:
            if (0 <= point[0] < doc["width_squares"] and 0 <= point[1] < doc["height_squares"]
                    and point not in blocked and point not in reached):
                reached.add(point)
                pending.append(point)
    assert set(starts) <= reached
    # Sect Trial deliberately has no trees so its edge pillars stay unobstructed.
    assert doc["background"]["style"] != "plain" and doc["materials"]
    assert doc["trees"] or map_id == "builtin-sect-trial-platform"
    canonical_sha256(to_battlefield(doc))  # no floats in the sealed battlefield
    if "picker_order" in doc:
        assert doc["description"] and doc["walls"]
        assert any(row["type"] == "SIMPLE_COVER" for row in doc["terrain"])
        assert any(row["material"].startswith("terrain:") for row in doc["materials"])
        assert len({row["material"] for row in doc["materials"] if row["material"].startswith("floor:")}) >= 2
        assert not set(starts).intersection(cell for row in doc["materials"]
                                            if row["material"].startswith("terrain:") for cell in map(tuple, row["cells"]))


def test_picker_descriptions_are_visible_and_update_with_selection():
    """Deterministic wiring check; browser rendering remains opt-in for the lead."""
    for file, picker in (("tabletop/tabletop.js", "mapSelect"), ("app.js", "arena")):
        source = (ROOT / "static" / file).read_text()
        assert f'{picker}.addEventListener("change", describeArena)' in source
        assert "arenaDescription.textContent" in source
        assert "describeArena();" in source
    source = (ROOT / "static/tabletop/tabletop.js").read_text()
    preset_load = source[source.index('bar.querySelector("[data-preset-load]")'):]
    assert "onArenaChange();" in preset_load
    assert "presetBar(sides, name, mapSelect, characters, describeArena)" in source
    assert "describeArena();" not in preset_load


def test_sect_trial_platform_keeps_pillars_visible_without_moving_starts():
    doc = json.loads((ROOT / "combat/maps/builtin-sect-trial-platform.json").read_text())
    assert doc["trees"] == []
    assert doc["starts"] == {
        "team1": [[4, 5], [4, 7], [4, 9]],
        "team2": [[15, 5], [15, 7], [15, 9]],
    }
    pillars = {wall["id"] for wall in doc["walls"] if wall["id"].startswith("pavilion-")}
    assert pillars == {"pavilion-nw", "pavilion-ne", "pavilion-sw", "pavilion-se"}


def test_picker_order_tolerates_invalid_optional_metadata():
    from combat.tabletop import arena_picker_order
    assert arena_picker_order({"arena_id": "battlefield:map.owner", "picker_order": "bad"}) == (1000, "battlefield:map.owner")


def test_bamboo_bridge_is_open_and_stream_costs_double_movement(tmp_path):
    doc = CombatService(ROOT, tmp_path).tabletop_maps.get("builtin-bamboo-forest-ravine")
    blocked, sight = rasterize(doc)
    assert (5, 2) in sight  # dense bamboo screen
    difficult = {tuple(cell) for row in doc["terrain"] if row["type"] == "DIFFICULT" for cell in row["cells"]}
    assert (9, 5) in difficult and (9, 6) not in difficult
    assert not blocked.intersection({(9, 5), (9, 6), (10, 6), (10, 7)})
    arena = to_battlefield(doc)
    stream = next(row for row in arena["terrain_regions"] if row["region_id"].startswith("terrain.") and row["movement_cost"] == 2)
    assert {"x": 9, "y": 5} in stream["cells"]
    assert {"x": 9, "y": 6} not in stream["cells"]


def test_shrine_brazier_paint_preserves_current_map_fire_semantics(tmp_path):
    service, mid = _fight(tmp_path, "battlefield:map.builtin-ruined-spirit-shrine")
    fire = next(zone for zone in zones.map_zones(service._load_session(mid).engine)
                if zone.trigger_profile["terrain"] == ["fire terrain"])
    assert len(fire.affected_cells) == 4
    assert fire.trigger_profile["obscured"] == "light"
    assert fire.trigger_profile["visual"]["material"] == "fire"
    assert fire.duration_rounds is None
    # H51's shared painted-terrain adapter applies the printed fire rule, not a new ability effect.
    rule = zones.terrain_rules()["terrains"]["fire terrain"]["enter_start"]
    trigger, = fire.trigger_profile["triggers"]
    assert trigger["on"] == ["enter", "start"]
    assert trigger["effects"] == [{"type": "save", "ability": rule["ability"],
                                   "on_fail": rule["on_fail"], "on_success": rule["on_success"]}]
    assert service.replay(mid)["status"] == "PASS"


def test_builtins_are_read_only_and_owner_maps_still_work(tmp_path):
    store = CombatService(ROOT, tmp_path).tabletop_maps
    doc = store.get(IDS[0])
    before = (ROOT / "combat/maps" / f"{IDS[0]}.json").read_bytes()
    for edit in (lambda: store.save(doc), lambda: store.delete(IDS[0])):
        with pytest.raises(TabletopError, match="Copy this built-in"):
            edit()
    store.save({**doc, "map_id": "my-ring", "display_name": "My ring"})
    assert store.get("my-ring")["walls"] == doc["walls"]
    assert len(store.list()) == len(ACTIVE_IDS) + len(NEW_IDS) + len(MAPS4_IDS) + len(MAPS1_ACTIVE) + len(MAPS3_IDS) + 1
    store.delete("my-ring")
    assert (ROOT / "combat/maps" / f"{IDS[0]}.json").read_bytes() == before
    assert TabletopMapStore(tmp_path / "empty").list() == []


@pytest.mark.parametrize("map_id", ACTIVE_IDS)
@pytest.mark.parametrize("size", [2, 3])
def test_new_team_fights_start_and_reload_with_painted_scenery(tmp_path, map_id, size):
    service, mid = _fight(tmp_path, "battlefield:map." + map_id, size)
    saved = service._load_session(mid).engine.battlefield_document
    table = TabletopService(service, tmp_path)
    state = table.state(mid)
    assert state["map"]["map_id"] == map_id and state["map"]["walls"] and state["map"]["floors"]
    actors = {a["entity_id"]: a for a in state["presentation"]["actors"]}
    for side, prefix in (("team1", "west"), ("team2", "east")):
        for i in range(size):
            assert actors[FACTORY_ACTOR_PREFIX + f"{prefix}-{i}"]["position"] == saved["team_starts"][side][i]
    # Commit a real table-driven AI turn, then reopen through a new service.
    table.auto_step(mid, state["last_sequence"])
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert reloaded.battlefield_document == saved
    positions = [tuple((p["x"], p["y"])) for side in saved["team_starts"].values() for p in side[:size]]
    assert len(set(positions)) == 2 * size
    ground = zones.map_zones(reloaded)
    assert any(z.trigger_profile["terrain"] == ["loose rubble"] for z in ground)
    if map_id in (IDS[1], IDS[5]):
        expected_mist = "mountain mist" if map_id == IDS[5] else "courtyard mist"
        mist = next(z for z in ground if z.trigger_profile["terrain"] == [expected_mist])
        assert mist.trigger_profile["obscured"] == "light" and mist.duration_rounds is None
    assert service.replay(mid)["status"] == "PASS"


@pytest.mark.parametrize("arena_id", ["battlefield:map." + i for i in ACTIVE_IDS] + CLASSIC)
def test_ai_short_fights_complete_and_classic_saves_replay(tmp_path, arena_id, legacy_zero_hp):
    service, mid = _fight(tmp_path, arena_id)
    saved = service._load_session(mid).engine.battlefield_document
    for _ in range(350):
        service.local_step(mid)
        if service._load_session(mid).engine.state.terminal_result:
            break
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert engine.state.terminal_result is not None
    assert any(e.event_type == "ATTACK_ROLLED" for e in engine.events)
    assert engine.battlefield_document == saved
    result = CombatService(ROOT, tmp_path).replay(mid)
    assert result["status"] == "PASS"
    assert result["canonical_state_sha256"] == canonical_state_sha256(engine.state)
    if arena_id in CLASSIC:
        assert result["canonical_state_sha256"] == CLASSIC_FINAL_HASHES[arena_id]
        assert not saved["display_name"].endswith(" (classic)")
        assert canonical_sha256([e.model_dump(mode="json") for e in engine.events]) == CLASSIC_EVENT_HASHES[arena_id]


def test_classic_labels_leave_arena_documents_unchanged(tmp_path):
    from combat.tabletop import arena_picker_name

    arenas = CombatService(ROOT, tmp_path).factory_arenas(include_retired=True)
    for arena_id in CLASSIC:
        arena = arenas[arena_id]
        before = canonical_sha256(arena)
        assert arena_picker_name(arena) == arena["display_name"]
        assert canonical_sha256(arena) == before


def test_map_api_exposes_builtins_defaults_and_lossless_editor_copies(tmp_path):
    import asyncio
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings

    def polling_loop():
        loop = asyncio.new_event_loop()
        def tick():
            loop.call_later(0.01, tick)
        loop.call_soon(tick)
        return loop

    settings = Settings.from_env(ROOT, tmp_path / "UserData")
    with TestClient(create_app(settings), backend_options={"loop_factory": polling_loop}) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        catalog = client.get("/api/tabletop/maps").json()
        assert catalog["default_arena_id"] == DEFAULT_FACTORY_ARENA
        assert catalog["maps"] == []
        assert len(catalog["builtin"]) == len(ACTIVE_IDS) + len(NEW_IDS) + len(MAPS4_IDS) + len(MAPS1_ACTIVE) + len(MAPS3_IDS)
        expected = CombatService(ROOT, settings.data_dir).tabletop_maps.list()
        assert {r["map_id"] for r in catalog["builtin"]} == set(ACTIVE_IDS) | set(NEW_IDS) | set(MAPS4_IDS) | set(MAPS1_ACTIVE) | set(MAPS3_IDS)
        assert [r["map_id"] for r in catalog["builtin"]] == [r["map_id"] for r in expected]
        factory = client.get("/api/combat/factory-arenas").json()
        assert [r["arena_id"] for r in factory[:len(ACTIVE_IDS)]] == [r["arena_id"] for r in catalog["builtin"][:len(ACTIVE_IDS)]]
        assert not {"battlefield:map." + i for i in RETIRED_IDS}.intersection(r["arena_id"] for r in factory + catalog["builtin"])
        for row in catalog["builtin"]:
            if row["map_id"] in IDS or row["map_id"] in MAPS4_IDS:
                assert row["description"] and len(row["description"]) < 1000
                assert next(r for r in factory if r["arena_id"] == row["arena_id"])["description"] == row["description"]
        assert not any(r["display_name"].endswith(" (classic)") for r in catalog["builtin"])
        for map_id in IDS + MAPS4_IDS:
            original = CombatService(ROOT, settings.data_dir).tabletop_maps.get(map_id)
            copy = client.get("/api/tabletop/builtin-maps/battlefield:map." + map_id).json()
            assert copy == original  # keeps vectors, scenery and painted terrain
            assert client.get("/api/tabletop/maps/" + map_id).json() == original
            assert client.delete("/api/tabletop/maps/" + map_id, headers=headers).status_code == 409
            copy.update(map_id="copy-" + map_id, display_name="My " + copy["display_name"])
            assert client.post("/api/tabletop/maps", headers=headers, json={"map": copy}).status_code == 200
        catalog = client.get("/api/tabletop/maps").json()
        assert len(catalog["maps"]) == len(IDS) + len(MAPS4_IDS)
        assert client.get("/api/combat/factory-arenas").json()[0]["arena_id"] == DEFAULT_FACTORY_ARENA


def test_default_map_places_catalog_opponents_at_east_team_starts(tmp_path):
    _install(tmp_path, "west")
    service = CombatService(ROOT, tmp_path)
    view = service.create_factory_match(project_ids=["west"], opponent_actor_ids=["an_eui_early_book1_cl5"],
                                       match_seed="ARENA1-CATALOG")
    assert view["metadata"]["battlefield_id"] == DEFAULT_FACTORY_ARENA
    actors = {a["entity_id"]: a for a in view["state"]["actors"]}
    starts = service.factory_arenas()[DEFAULT_FACTORY_ARENA]["team_starts"]
    assert actors[FACTORY_ACTOR_PREFIX + "west"]["position"] == starts["team1"][0]
    assert actors["an_eui_early_book1_cl5"]["position"] == starts["team2"][0]


def _los_clear(a, b, blocked, sight, width, height):
    """True if the straight line between cell centres a, b passes no blocking cell (endpoints excluded)."""
    cells = _segment_cells([a[0] + 0.5, a[1] + 0.5], [b[0] + 0.5, b[1] + 0.5], width, height)
    cells -= {tuple(a), tuple(b)}
    return not cells & (blocked | sight)


def _path_distance(start, blocked, difficult, width, height):
    """Dijkstra, 8-directional, cost 1 (2 through difficult terrain) -- squares of movement to every cell."""
    import heapq

    dist = {tuple(start): 0}
    pending = [(0, tuple(start))]
    while pending:
        d, (x, y) = heapq.heappop(pending)
        if d > dist.get((x, y), 1 << 30):
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height) or (nx, ny) in blocked:
                    continue
                nd = d + (2 if (nx, ny) in difficult else 1)
                if nd < dist.get((nx, ny), 1 << 30):
                    dist[(nx, ny)] = nd
                    heapq.heappush(pending, (nd, (nx, ny)))
    return dist


@pytest.mark.parametrize("map_id", MAPS1_IDS)
def test_maps1_big_arenas_have_sheltered_distant_starts(tmp_path, map_id):
    """MAPS1 (owner 2026-10-13): bigger, more distant, sheltered starts on every new big arena."""
    doc = CombatService(ROOT, tmp_path).tabletop_maps.get(map_id)
    width, height = doc["width_squares"], doc["height_squares"]
    assert 40 <= width <= 60 and 30 <= height <= 40
    blocked = set(map(tuple, doc["cells"]["blocked"]))
    sight = set(map(tuple, doc["cells"]["sight"]))
    difficult = {tuple(c) for row in doc["terrain"] if row["type"] == "DIFFICULT" for c in row["cells"]}
    team1 = [tuple(c) for c in doc["starts"]["team1"]]
    team2 = [tuple(c) for c in doc["starts"]["team2"]]
    assert len(team1) == len(team2) == 6
    closest = None
    for start in team1:
        reach = _path_distance(start, blocked, difficult, width, height)
        for enemy in team2:
            assert enemy in reach, f"{map_id}: {start} cannot path to enemy start {enemy}"
            closest = reach[enemy] if closest is None else min(closest, reach[enemy])
        for enemy in team2:
            assert not _los_clear(start, enemy, blocked, sight, width, height), \
                f"{map_id}: {start} has line of sight to enemy start {enemy}"
    assert closest >= 25, f"{map_id}: closest start pair only {closest} squares apart by path"
    to_battlefield(doc)  # the full conversion still succeeds for every new big arena


@pytest.mark.parametrize("map_id", MAPS1_ACTIVE)
def test_maps1_big_arenas_run_a_short_ai_fight_and_replay(tmp_path, map_id, legacy_zero_hp):
    service, mid = _fight(tmp_path, "battlefield:map." + map_id, size=2, rounds=3)
    saved = service._load_session(mid).engine.battlefield_document
    table = TabletopService(service, tmp_path)
    state = table.state(mid)
    assert state["map"]["map_id"] == map_id and state["map"]["walls"] is not None
    table.auto_step(mid, state["last_sequence"])
    for _ in range(100):
        service.local_step(mid)
        if service._load_session(mid).engine.state.terminal_result:
            break
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert engine.battlefield_document == saved
    assert service.replay(mid)["status"] == "PASS"


def test_map_scenery_tooltips_explain_effect_duration_and_cost():
    import subprocess

    subprocess.run(["node", "--input-type=module", "-e", """
      import assert from 'node:assert/strict';
      const {zoneLook, zoneTooltip} = await import(process.argv[1]);
      for (const [name, property] of [['Loose rubble', {difficult:'all'}],
                                       ['Courtyard mist', {obscured:'light'}]]) {
        const zone = {zone_id:'zone:map:1', duration_rounds:null, trigger_profile:{
          name, map:true, ...property}};
        const tip = zoneTooltip(zone, zoneLook(zone));
        assert.equal(tip.title, name);
        assert(tip.lines.some(line => line.includes('everyone') && line.includes('whole fight') && line.includes('No action or resource cost')));
        assert(tip.lines.some(line => line.includes(name === 'Loose rubble' ? 'twice as much movement' : 'not automatically Hidden')));
      }
    """, (ROOT / "static/tabletop/zones.js").as_uri()], check=True, timeout=30)


def test_editor_preview_zones_include_map_scenery_explanations():
    import subprocess

    subprocess.run(["node", "--input-type=module", "-e", """
      import assert from 'node:assert/strict';
      const {previewTerrainZones} = await import(process.argv[1]);
      const {zoneLook, zoneTooltip} = await import(process.argv[2]);
      const zones = previewTerrainZones([{material:'terrain:Courtyard mist', cells:[[2,3]]}],
        [{name:'Courtyard mist', label:'Courtyard mist', obscured:'light', material:'smoke'}], true);
      assert.equal(zones.length, 1);
      const zone = zones[0];
      assert.equal(zone.trigger_profile.map, true);
      assert.equal(zone.trigger_profile.natural_haze, true);
      const tip = zoneTooltip(zone, zoneLook(zone));
      assert(tip.lines.some(line => line.includes('everyone') && line.includes('whole fight') && line.includes('No action or resource cost')));
      assert(tip.lines.some(line => line.includes('not automatically Hidden')));
    """, (ROOT / "static/tabletop/mapeditor-zones.js").as_uri(),
          (ROOT / "static/tabletop/zones.js").as_uri()], check=True, timeout=30)


# --------------------------------------------------------------- MAPS4 arenas
def _nearest_path_cost(seed, targets, solid, w, h):
    """Shortest 4-neighbour path length from seed to the nearest target cell."""
    dist = {seed: 0}
    queue = [(0, seed)]
    while queue:
        cost, p = heapq.heappop(queue)
        if cost != dist.get(p):
            continue
        if p in targets:
            return cost
        x, y = p
        for nxt in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nxt in solid or not (0 <= nxt[0] < w and 0 <= nxt[1] < h):
                continue
            if cost + 1 < dist.get(nxt, 1 << 30):
                dist[nxt] = cost + 1
                heapq.heappush(queue, (cost + 1, nxt))
    return 1 << 30


def _frontier_audit(tmp_path, map_id):
    """Load one frontier arena through the real pipeline and prove its guarantees."""
    from combat.gate2_grid import SquareGrid
    from combat.gate2_runtime_models import Position

    doc = CombatService(ROOT, tmp_path).tabletop_maps.get(map_id)
    normalized = normalize_map(doc)
    assert normalize_map(normalized) == normalized, "normalize_map must be idempotent"
    w, h = normalized["width_squares"], normalized["height_squares"]
    assert 40 <= w <= 60 and 30 <= h <= 40, f"size {w}x{h} outside the big-arena band"
    blocked, sight = rasterize(normalized)
    assert set(map(tuple, doc["cells"]["blocked"])) == blocked
    assert set(map(tuple, doc["cells"]["sight"])) == sight
    object_blocks = {(o["x"], o["y"]) for o in normalized["objects"]
                     if object_rules.stats(o)["blocks"] and not o.get("door_open")}
    solid = blocked | object_blocks
    t1 = [tuple(c) for c in normalized["starts"]["team1"]]
    t2 = [tuple(c) for c in normalized["starts"]["team2"]]
    starts = t1 + t2
    assert len(t1) == len(t2) == 6 and len(set(starts)) == 12, "six starts per team, twelve unique"
    assert all(0 <= x < w and 0 <= y < h for x, y in starts)
    assert not solid & set(starts), "no start on a blocked square or blocking object"
    named = {tuple(c) for row in normalized["materials"] if row["material"].startswith("terrain:")
             for c in row["cells"]}
    assert not set(starts) & named, "no start on a named-terrain square"
    # every start reaches every other start (so each start paths to every enemy start)
    reached, pending = {starts[0]}, [starts[0]]
    while pending:
        x, y = pending.pop()
        for nxt in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nxt not in solid and nxt not in reached and 0 <= nxt[0] < w and 0 <= nxt[1] < h:
                reached.add(nxt); pending.append(nxt)
    assert set(starts) <= reached, "a start is walled off"
    # closest starts are at least 25 squares apart by path (125 ft)
    t2set, t1set = set(t2), set(t1)
    least = min(min(_nearest_path_cost(s, t2set, solid, w, h) for s in t1),
                min(_nearest_path_cost(s, t1set, solid, w, h) for s in t2))
    assert least >= 25, f"closest starts only {least} squares apart by path"
    # to_battlefield seals without floats, and no start begins in enemy line of sight
    arena = to_battlefield(normalized)
    canonical_sha256(arena)
    grid = SquareGrid(arena)
    assert not any(grid.line_of_sight(Position(x=a[0], y=a[1]), Position(x=b[0], y=b[1]))
                   for a in t1 for b in t2), "a start is in enemy line of sight"
    # shipped-map feature/description invariants
    assert normalized["background"]["style"] != "plain" and normalized["materials"]
    assert normalized["walls"], "needs blocking walls/palisades"
    assert normalized["description"] and len(normalized["description"]) < 1000
    assert 60 <= normalized["picker_order"] <= 69, normalized["picker_order"]
    assert any(t["type"] == "SIMPLE_COVER" for t in normalized["terrain"]), "needs +2 AC cover"
    assert any(m["material"].startswith("terrain:") for m in normalized["materials"]), "needs a terrain paint"
    floors = {m["material"] for m in normalized["materials"] if m["material"].startswith("floor:")}
    assert len(floors) >= 2, f"needs two floor styles, got {floors}"
    mats = {m["material"].split(":", 1)[1] for m in normalized["materials"] if m["material"].startswith("terrain:")}
    assert (any(t["type"] == "DIFFICULT" for t in normalized["terrain"])
            or (mats & MAPS_DIFFICULT_TERRAINS)), "needs a movement-changing terrain feature"
    return normalized, grid, least, blocked


@pytest.mark.parametrize("map_id", MAPS4_IDS)
def test_frontier_arenas_are_legal_big_sheltered_maps(tmp_path, map_id):
    normalized, grid, least, blocked = _frontier_audit(tmp_path, map_id)
    assert grid.blocked  # real terrain shelters the starts


def test_frontier_map_runs_a_full_ai_fight_and_reloads(tmp_path, legacy_zero_hp):
    map_id = MAPS4_IDS[0]  # one representative end-to-end fight; the rest are proven above
    service, mid = _fight(tmp_path, "battlefield:map." + map_id, size=2, rounds=3)
    sealed = service._load_session(mid).engine.battlefield_document
    for _ in range(350):
        service.local_step(mid)
        if service._load_session(mid).engine.state.terminal_result:
            break
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.engine.state.terminal_result is not None
    assert any(e.event_type == "MOVEMENT_COMMITTED" for e in cold.engine.events)
    assert cold.engine.battlefield_document == sealed
    result = CombatService(ROOT, tmp_path).replay(mid)
    assert result["status"] == "PASS"
    assert result["canonical_state_sha256"] == canonical_state_sha256(cold.engine.state)


def test_frontier_map_table_build_and_ai_step_timing(tmp_path, capsys):
    """Owner priority: measure building one TableState and one AI step per map vs mountain-pass."""
    arenas = ["battlefield:map.builtin-mountain-pass"] + ["battlefield:map." + m for m in MAPS4_IDS]
    rows = {}
    for index, arena in enumerate(arenas):
        sub = tmp_path / f"tm{index}"  # a fresh user-data folder per fight (actors id "west-0" repeat)
        service, mid = _fight(sub, arena, size=2, rounds=2)
        table = TabletopService(service, sub)
        start = perf_counter(); state = table.state(mid); build_s = perf_counter() - start
        assert state["map"]["map_id"]
        start = perf_counter(); table.auto_step(mid, state["last_sequence"]); step_s = perf_counter() - start
        rows[arena.split(".", 2)[-1]] = {"state_build_s": round(build_s, 3), "ai_step_s": round(step_s, 3)}
    with capsys.disabled():
        print("MAPS4 timings (build one TableState / one AI step): " + json.dumps(rows), flush=True)
    base = rows["builtin-mountain-pass"]["ai_step_s"]
    for name, row in rows.items():  # smoke guard: each step really ran; the printed numbers are the report
        assert 0 < row["ai_step_s"] < max(base * 20, 2.0) + 5.0, f"{name} AI step unexpectedly slow: {row}"
