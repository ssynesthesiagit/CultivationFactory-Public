"""ARENA1: shipped editor maps, team starts, sealed scenery and classic replays."""
import json
from pathlib import Path

import pytest
from tests.legacy_fight_support import legacy_zero_hp

from combat import zones
from combat.canonical import canonical_sha256
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService, DEFAULT_FACTORY_ARENA, FACTORY_ACTOR_PREFIX
from combat.tabletop import TabletopError, TabletopMapStore, normalize_map, rasterize, to_battlefield
from combat.tabletop_service import TabletopService
from tests.test_factory_live_match import _install
from tests.retired_arena_support import HistoricalArenaWriter

ROOT = Path(__file__).resolve().parents[1]
IDS = ["builtin-pillar-arena", "builtin-mist-courtyard", "builtin-sect-trial-platform",
       "builtin-bamboo-forest-ravine", "builtin-ruined-spirit-shrine", "builtin-mountain-pass"]
CLASSIC = ["battlefield:factory_pillar_arena", "battlefield:factory_mist_courtyard"]
NEW_IDS = ["builtin-willow-village-compound", "builtin-emerald-canopy",
           "builtin-cloudwater-crossing", "builtin-jade-sutra-hall"]
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
    assert len(store.list()) == len(ACTIVE_IDS) + len(NEW_IDS) + 1
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
        assert len(catalog["builtin"]) == len(ACTIVE_IDS) + len(NEW_IDS)
        expected = CombatService(ROOT, settings.data_dir).tabletop_maps.list()
        assert {r["map_id"] for r in catalog["builtin"]} == set(ACTIVE_IDS) | set(NEW_IDS)
        assert [r["map_id"] for r in catalog["builtin"]] == [r["map_id"] for r in expected]
        factory = client.get("/api/combat/factory-arenas").json()
        assert [r["arena_id"] for r in factory[:len(ACTIVE_IDS)]] == [r["arena_id"] for r in catalog["builtin"][:len(ACTIVE_IDS)]]
        assert not {"battlefield:map." + i for i in RETIRED_IDS}.intersection(r["arena_id"] for r in factory + catalog["builtin"])
        for row in catalog["builtin"]:
            if row["map_id"] in IDS:
                assert row["description"] and len(row["description"]) < 1000
                assert next(r for r in factory if r["arena_id"] == row["arena_id"])["description"] == row["description"]
        assert not any(r["display_name"].endswith(" (classic)") for r in catalog["builtin"])
        for map_id in IDS:
            original = CombatService(ROOT, settings.data_dir).tabletop_maps.get(map_id)
            copy = client.get("/api/tabletop/builtin-maps/battlefield:map." + map_id).json()
            assert copy == original  # keeps vectors, scenery and painted terrain
            assert client.get("/api/tabletop/maps/" + map_id).json() == original
            assert client.delete("/api/tabletop/maps/" + map_id, headers=headers).status_code == 409
            copy.update(map_id="copy-" + map_id, display_name="My " + copy["display_name"])
            assert client.post("/api/tabletop/maps", headers=headers, json={"map": copy}).status_code == 200
        catalog = client.get("/api/tabletop/maps").json()
        assert len(catalog["maps"]) == len(IDS)
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
