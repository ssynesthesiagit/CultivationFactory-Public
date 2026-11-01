"""SON202 (owner 2026-10-08): indoor floors/tiles and grass/forest variants (static/tabletop/floor-art-indoor.js)
change only the look, never the rules, in a real fight through CombatService and the session's own
execute_intent path (table.act wraps it), including after a cold reload."""
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_sol196_map_art import _grid_rules, _map, _moves, _start

NEW_STYLES = (
    "wood_palace", "tatami", "clay_tile", "glazed_green_tile", "lacquer_red", "jade_marble",
    "herringbone_brick", "hex_stone", "bamboo_slat", "taiji_medallion", "cloud_stone", "alchemy_scorch",
    "sutra_hall_wood", "formation_floor", "temple_moss_flagstone", "rug_geometric", "rug_lotus",
    "grass_meadow", "grass_autumn", "grass_lawn", "grass_wildflower", "grass_trampled", "grass_alpine",
    "forest_pine_needle", "forest_moss", "forest_fern", "forest_leaf_litter", "forest_mushroom_loam",
    "forest_root_tangle",
)


def test_every_new_style_is_whitelisted_and_only_a_look():
    from combat.ground_text import floor_reading
    from combat.tabletop import BACKGROUND_STYLES

    assert set(NEW_STYLES) <= set(BACKGROUND_STYLES)
    for style in NEW_STYLES:
        assert "only the look" in floor_reading(style)["lines"][0]


def test_floor_art_changes_nothing_in_a_fight_through_execute_intent_and_a_cold_reload(tmp_path):
    floors = [{"material": f"floor:{style}", "cells": [[i % 8, i // 8]]} for i, style in enumerate(NEW_STYLES)]
    bare_combat, bare, bare_mid = _start(tmp_path / "bare", _map(map_id="son202-bare"))
    combat, painted, mid = _start(tmp_path / "painted",
                                   _map(map_id="son202-painted", background={"style": "wood_palace"}, materials=floors))
    assert painted["background"]["style"] == "wood_palace"
    assert len(painted["materials"]) == len(NEW_STYLES)

    # The engine's own grid: identical movement costs, cover, blocked squares and centrelines either way.
    engine, bare_engine = combat._load_session(mid).engine, bare_combat._load_session(bare_mid).engine
    assert _grid_rules(engine.grid) == _grid_rules(bare_engine.grid)
    positions = lambda e: sorted((a.entity_id, a.position.x, a.position.y) for a in e.state.actors.values())
    assert positions(engine) == positions(bare_engine)

    table, bare_table = TabletopService(combat, tmp_path / "painted"), TabletopService(bare_combat, tmp_path / "bare")
    state, bare_state = table.state(mid, fog=True), bare_table.state(bare_mid, fog=True)
    assert _moves(state["menu"]) == _moves(bare_state["menu"]) and _moves(state["menu"])
    assert state["fog_perception"] == bare_state["fog_perception"]

    # A real committed action through the session's own execute_intent path (table.act wraps it): the same
    # move is legal and costs the same whether or not the floor underneath it is painted.
    menu, bare_menu = state["menu"], bare_state["menu"]
    move, bare_move = menu["moves"][0], bare_menu["moves"][0]
    assert (move["destination"]["x"], move["destination"]["y"], move.get("cost_ft")) == \
        (bare_move["destination"]["x"], bare_move["destination"]["y"], bare_move.get("cost_ft"))
    acted = table.act(mid, move["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], [])
    bare_acted = bare_table.act(bare_mid, bare_move["candidate_id"], bare_menu["decision_id"], bare_menu["state_version"], bare_state["last_sequence"], [])
    assert acted["status"] == bare_acted["status"] == "COMMITTED"

    # Cold reload: a fresh CombatService loading the same saved session still applies the same rules, and the
    # session itself still verifies and replays clean.
    cold, bare_cold = CombatService(ROOT, tmp_path / "painted"), CombatService(ROOT, tmp_path / "bare")
    cold_session, bare_cold_session = cold._load_session(mid), bare_cold._load_session(bare_mid)
    assert _grid_rules(cold_session.engine.grid) == _grid_rules(bare_cold_session.engine.grid)
    assert positions(cold_session.engine) == positions(bare_cold_session.engine)
    assert cold_session.verify()["status"] == cold_session.mechanical.replay()["status"] == "PASS"
    assert bare_cold_session.verify()["status"] == bare_cold_session.mechanical.replay()["status"] == "PASS"

    # Exact floor-art persistence (SON202 review finding 3): identical grid rules and a clean replay would also be
    # true if the cold reload silently dropped every floor patch and reset the background -- the art is mechanically
    # inert, so nothing above would notice. Re-read the map the way the editor would after a save -> reload, through
    # a fresh CombatService's own map store (the same on-disk map, not the in-memory document), and check the exact
    # background style and every floor patch's exact style key and cells survived, not just their count.
    reloaded = cold.tabletop_maps.get(painted["map_id"])
    assert reloaded["background"]["style"] == "wood_palace"
    expected_floor_materials = {f"floor:{style}": [[i % 8, i // 8]] for i, style in enumerate(NEW_STYLES)}
    actual_floor_materials = {row["material"]: row["cells"] for row in reloaded["materials"] if row["material"].startswith("floor:")}
    assert actual_floor_materials == expected_floor_materials
    assert bare_cold.tabletop_maps.get(bare["map_id"])["background"].get("style", "flagstone") != "wood_palace"
