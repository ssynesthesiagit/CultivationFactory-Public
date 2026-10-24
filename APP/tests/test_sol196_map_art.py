"""SOL196 (owner 2026-10-08): tree kinds and biome decoration change only the look, never the rules or old maps."""
import copy
import re
from pathlib import Path

from combat.tabletop import DECOR_KINDS, DECOR_RULE_LOOKS, TREE_LOOKS, normalize_map, rasterize, to_battlefield

TABLETOP = Path(__file__).resolve().parents[1] / "static" / "tabletop"


def _map(**extra):
    document = {"map_id": "sol196", "display_name": "Glade", "width_squares": 8, "height_squares": 8,
                "walls": [], "terrain": [], "starts": {"team1": [[0, 0]], "team2": [[7, 7]]},
                "trees": [{"x": 2, "y": 2, "size": 1, "seed": 4}, {"x": 4, "y": 4, "size": 2, "seed": 9}]}
    document.update(extra)
    return document


def _pieces():
    source = (TABLETOP / "decor-art.js").read_text()
    rows = re.findall(r'^  (\w+): \{(?:scale: [\d.]+, )?biome: "\w+", name: "[^"]+", rule: (null|"\w+")', source, re.M)
    assert len(rows) >= 48, "decor-art.js pieces not found"
    return {kind: (None if rule == "null" else rule.strip('"')) for kind, rule in rows}


def test_server_lists_match_the_drawn_pieces_and_tree_kinds():
    pieces = _pieces()
    assert set(DECOR_KINDS) == {kind for kind, rule in pieces.items() if rule is None}
    assert set(DECOR_RULE_LOOKS) == {kind for kind, rule in pieces.items() if rule}
    assert {rule for rule in pieces.values() if rule} <= {"SIMPLE_COVER", "DIFFICULT"}, "only existing rule terrain types"
    looks = re.search(r"export const TREE_LOOKS = Object\.freeze\(\{(.*?)\}\);", (TABLETOP / "tree-art.js").read_text(), re.S).group(1)
    assert set(TREE_LOOKS) == set(re.findall(r"^\s+(\w+):", looks, re.M))


def test_a_saved_map_without_looks_or_decor_normalizes_exactly_as_before():
    plain = normalize_map(_map())
    assert "decor" not in plain
    assert all("look" not in tree for tree in plain["trees"])
    assert "decor" not in to_battlefield(plain).get("tabletop", {})


def test_tree_look_is_kept_but_the_trunk_rules_do_not_change():
    plain = normalize_map(_map())
    looked = normalize_map(_map(trees=[{"x": 2, "y": 2, "size": 1, "seed": 4, "look": "willow"},
                                       {"x": 4, "y": 4, "size": 2, "seed": 9, "look": "pine"}]))
    assert [tree.get("look") for tree in looked["trees"]] == ["willow", "pine"]
    assert rasterize(looked) == rasterize(plain)
    bad = normalize_map(_map(trees=[{"x": 2, "y": 2, "size": 1, "look": "palm"}, {"x": 4, "y": 4, "size": 1, "look": "broadleaf"}]))
    assert all("look" not in tree for tree in bad["trees"]), "unknown looks and the default are not stored"


def test_decor_is_look_only_and_never_reaches_the_rules():
    decor = [{"kind": "fern", "x": 1, "y": 1, "seed": 3}, {"kind": "prayer_flags", "x": 5, "y": 1, "rotation": 90},
             {"kind": "brazier", "x": 6, "y": 6}, {"kind": "dragon", "x": 3, "y": 3}, {"kind": "reeds", "x": 9, "y": 1}]
    plain, decorated = normalize_map(_map()), normalize_map(_map(decor=decor))
    assert [(row["kind"], row["x"], row["y"]) for row in decorated["decor"]] == [("fern", 1, 1), ("prayer_flags", 5, 1)]
    assert decorated["decor"][1]["rotation"] == 90
    assert rasterize(decorated) == rasterize(plain)
    without_look = copy.deepcopy(to_battlefield(decorated))
    without_look.get("tabletop", {}).pop("decor", None)
    assert without_look == to_battlefield(plain), "decor may only add its own look to the table section"


def test_a_ruled_piece_is_ordinary_cover_or_difficult_terrain():
    for look, kind in (("brazier", "SIMPLE_COVER"), ("snow_drift", "DIFFICULT")):
        styled = normalize_map(_map(terrain=[{"type": kind, "look": look, "cells": [[1, 5]]}]))
        assert styled["terrain"][0]["look"] == look
        # The scenery catalog now supplies a physical height for ruled looks.
        # Compare the terrain mechanics at that same height: the look must not
        # introduce a different terrain type, movement cost or footprint.
        height = styled["terrain"][0]["height_ft"]
        assert height == 3
        plain = normalize_map(_map(terrain=[{"type": kind, "cells": [[1, 5]], "height_ft": height}]))
        regions = lambda doc: to_battlefield(doc)["terrain_regions"]
        assert regions(styled) == regions(plain)


# ---------------------------------------------------------------- through the real engine (owner 2026-10-08: "make
# sure everything is tied into the game engine as well"): a map saved the way the editor saves it, a fight started from
# it the way the table starts one, the engine's own grid asked, then one committed table action and a cold reload.
import pytest  # noqa: E402

from combat.gate2_grid import SquareGrid  # noqa: E402
from combat.gate2_runtime_models import Position  # noqa: E402
from combat.gate5_service import CombatService  # noqa: E402
from combat.tabletop import MAP_PREFIX  # noqa: E402
from combat.tabletop_service import TabletopService  # noqa: E402
from tests.h1_support import ROOT  # noqa: E402

TREE_ROW = [(x, 2) for x in range(1, 12, 2)] + [(x, 9) for x in range(1, 8, 2)]


def _editor_map(name, *, looks=True, decor=True, pieces=True, tree_looks=TREE_LOOKS):
    trees = [{"x": x, "y": y, "size": 1, "seed": 7 + i, **({"look": look} if looks else {})}
             for i, ((x, y), look) in enumerate(zip(TREE_ROW, tree_looks))]
    terrain = [{"type": "SIMPLE_COVER", **({"look": "brazier", "rotation": 90} if pieces else {}), "cells": [[6, 5]]},
               {"type": "DIFFICULT", **({"look": "snow_drift"} if pieces else {}), "cells": [[6, 7]]}]
    return {"map_id": name, "display_name": name, "width_squares": 13, "height_squares": 12, "walls": [], "terrain": terrain,
            "starts": {"team1": [[1, 5]], "team2": [[11, 5]]}, "trees": trees,
            **({"decor": [{"kind": kind, "x": 3 + i % 6, "y": 4 + (i // 6) * 2, "seed": i} for i, kind in enumerate(DECOR_KINDS[:12])]} if decor else {})}


def _grid_rules(grid):
    """Everything a rule reads from the grid."""
    return (sorted(grid.base_movement_cost.items()), sorted(map(tuple, grid.centerline_cells)),
            sorted((x, y) for x in range(grid.width) for y in range(grid.height) if grid.terrain_at((x, y), "SIMPLE_COVER")),
            sorted((x, y) for x in range(grid.width) for y in range(grid.height) if not grid.in_bounds((x, y)) or grid.terrain_at((x, y), "BLOCKED")))


def _assert_engine_rules(grid, *, pieces=True):
    # Cover: a shot across the brazier square gets the +2 cover bonus; one beside it does not.
    assert grid.cover_bonus(Position(x=1, y=5, z=0), Position(x=11, y=5, z=0)) == 2
    assert grid.cover_bonus(Position(x=1, y=6, z=0), Position(x=11, y=6, z=0)) == 0
    # Difficult: entering the snow drift square costs double.
    assert grid.movement_step_multiplier((5, 7), (6, 7)) == 2
    assert grid.movement_step_multiplier((5, 6), (6, 6)) == 1
    # Every tree, whatever it looks like: its trunk can't be entered and a sight line across it is cut.
    for x, y in TREE_ROW[:len(TREE_LOOKS)]:
        assert not grid.step_legal((x - 1, y), (x, y)), (x, y)
        assert not grid.line_of_sight(Position(x=x - 1, y=y, z=0), Position(x=x + 1, y=y, z=0)), (x, y)
    assert grid.line_of_sight(Position(x=0, y=3, z=0), Position(x=12, y=3, z=0))


def _start(root, document):
    """Save the map through the editor's store and start a fight from it the way the table does, in its own data root
    (same seed, so the same initiative in both fights)."""
    from tests.test_save_reload_equivalence import _install_factory
    ids, _ = _install_factory(root, "sol196", [], None)
    combat = CombatService(ROOT, root)
    saved = combat.tabletop_maps.save(document)
    mid = combat.create_factory_match(project_ids=[ids[0].removeprefix("actor:factory.")], opponent_actor_ids=[ids[1]],
                                      control_modes={a: "MANUAL" for a in ids}, arena_id=MAP_PREFIX + saved["map_id"],
                                      match_seed="SOL196-ART")["match_id"]
    return combat, saved, mid


def _moves(menu):
    """The legal moves, without their per-fight ids."""
    return sorted((m["destination"]["x"], m["destination"]["y"], m.get("cost_ft"), tuple((p["x"], p["y"]) for p in m.get("path") or []))
                  for m in (menu or {}).get("moves") or [])


@pytest.mark.parametrize("bamboo", [False, True], ids=["non-bamboo", "with-bamboo"])
def test_rule_pieces_trees_and_decor_reach_the_engine_and_survive_a_cold_reload(tmp_path, bamboo):
    assert len(TREE_ROW) >= len(TREE_LOOKS)
    # Keep the same footprints in both cases; only the two bamboo looks are
    # allowed to change sight. All other tree looks keep the full fog assertion.
    tree_looks = tuple(look if bamboo or look not in {"bamboo_stand", "golden_bamboo"} else "maple"
                       for look in TREE_LOOKS)
    combat, looked, mid = _start(tmp_path / "looked", _editor_map("sol196", tree_looks=tree_looks))
    bare_combat, bare, bare_mid = _start(tmp_path / "bare", _editor_map("sol196", looks=False, decor=False, pieces=False))
    assert [tree.get("look") for tree in looked["trees"]][1:len(TREE_LOOKS)] == list(tree_looks)[1:]
    assert len(looked["decor"]) == 12 and "decor" not in bare
    engine, bare_engine = combat._load_session(mid).engine, bare_combat._load_session(bare_mid).engine
    _assert_engine_rules(engine.grid)
    # The looks and the decoration change nothing a rule reads, nor where anyone stands, can go or can see.
    assert _grid_rules(engine.grid) == _grid_rules(bare_engine.grid)
    positions = lambda e: sorted((a.entity_id, a.position.x, a.position.y) for a in e.state.actors.values())
    assert positions(engine) == positions(bare_engine)
    table = TabletopService(combat, tmp_path / "looked")
    look_state = table.state(mid, fog=True)
    bare_state = TabletopService(bare_combat, tmp_path / "bare").state(bare_mid, fog=True)
    assert [t.get("look") for t in look_state["map"]["trees"]][1:len(TREE_LOOKS)] == list(tree_looks)[1:]
    assert len(look_state["map"]["decor"]) == 12 and "decor" not in bare_state["map"]
    assert {row.get("look") for row in look_state["map"]["terrain"]} == {"brazier", "snow_drift"}
    # The turned brazier (the editor's Turn control) reaches the fight's table section, with no effect on any rule.
    assert [row.get("rotation") for row in look_state["map"]["terrain"] if row.get("look") == "brazier"] == [90]
    assert _moves(look_state["menu"]) == _moves(bare_state["menu"]) and _moves(look_state["menu"])
    from combat.terrain_occlusion import sight_geometry
    looked_sight = sight_geometry(engine.grid)
    if bamboo:
        # Bamboo alone has physical culm placements instead of a broadleaf
        # trunk; this explicit exception must not weaken the other looks.
        assert {tree.get('look') for tree in looked['trees']} & {'bamboo_stand', 'golden_bamboo'}
        expected_lines = copy.deepcopy(sight_geometry(bare_engine.grid)['lines'])
        # Recorded physical culms, in hundredths of one square. Only the four
        # >=1-ft-diameter stems block sight; the two tiny shoots do not.
        culm_crosses = [
            ((30, 42), (54, 42)), ((42, 30), (42, 54)),
            ((47, 38), (69, 38)), ((58, 27), (58, 49)),
            ((52, 56), (76, 56)), ((64, 44), (64, 68)),
            ((38, 66), (58, 66)), ((48, 56), (48, 76)),
        ]
        heights = {
            "broadleaf": 30, "maple": 30, "cherry": 20, "willow": 25,
            "pine": 40, "snowy_pine": 40, "dead": 20, "ancient": 60,
            "bamboo_stand": 20, "golden_bamboo": 25,
        }
        for tree in looked['trees']:
            x, y, size = tree['x'], tree['y'], tree['size']
            row = next(r for r in expected_lines if r['cells'] == [(x, y)])
            # The scenery catalog gives the looks different finite heights.
            row['top_ft'] = heights[tree.get('look', 'broadleaf')]
            if tree.get('look') not in {'bamboo_stand', 'golden_bamboo'}:
                continue
            row['segments'] = [
                tuple((x * 100 + px * size, y * 100 + py * size) for px, py in segment)
                for segment in culm_crosses
            ]
        # Exact full-source equality also protects every non-bamboo tree and
        # all metadata (height, footprint, scale and solid/sight classification).
        assert looked_sight['lines'] == expected_lines
    else:
        assert look_state["fog_perception"] == bare_state["fog_perception"]
    # A real table transaction, then a cold reload: the engine still applies the same rules, the table the same looks.
    menu = look_state["menu"]
    assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], look_state["last_sequence"], [])["status"] == "COMMITTED"
    cold = CombatService(ROOT, tmp_path / "looked")
    loaded = cold._load_session(mid)
    assert sight_geometry(loaded.engine.grid) == looked_sight
    _assert_engine_rules(loaded.engine.grid)
    assert _grid_rules(loaded.engine.grid) == _grid_rules(bare_engine.grid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    fresh = TabletopService(cold, tmp_path / "looked").state(mid, fog=True)["map"]
    assert fresh["decor"] == look_state["map"]["decor"] and fresh["trees"] == look_state["map"]["trees"]
    assert fresh["terrain"] == look_state["map"]["terrain"], "the turned piece survives the cold reload"


@pytest.mark.parametrize("look", DECOR_RULE_LOOKS)
def test_every_rule_piece_is_its_rule_in_the_engine_grid(look):
    rule = _pieces()[look]
    doc = normalize_map({"display_name": look, "width_squares": 9, "height_squares": 9, "walls": [],
                         "terrain": [{"type": rule, "look": look, "cells": [[4, 4]]}]})
    grid = SquareGrid(to_battlefield(doc))
    plain = SquareGrid(to_battlefield(normalize_map({**doc, "terrain": [{"type": rule, "cells": [[4, 4]]}]})))
    assert _grid_rules(grid) == _grid_rules(plain)
    if rule == "SIMPLE_COVER":
        assert grid.cover_bonus(Position(x=0, y=4, z=0), Position(x=8, y=4, z=0)) == 2
    else:
        assert grid.movement_step_multiplier((3, 4), (4, 4)) == 2


def test_biome_floors_are_whitelisted_painted_and_only_a_look():
    from combat.ground_text import floor_reading
    from combat.tabletop import BACKGROUND_STYLES
    source = (TABLETOP / "textures.js").read_text()
    styles = re.findall(r"^  (\w+): \"[^\"]+\",", re.search(r"export const STYLES = \{(.*?)\n\};", source, re.S).group(1), re.M)
    # Indoor floors/tiles and grass/forest variants (SON202) live in their own module, spread into STYLES.
    indoor_source = (TABLETOP / "floor-art-indoor.js").read_text()
    for export in ("INDOOR_STYLES", "GRASS_STYLES", "FOREST_STYLES"):
        block = re.search(rf"export const {export} = Object\.freeze\(\{{(.*?)\n\}}\);", indoor_source, re.S).group(1)
        styles += re.findall(r"^  (\w+): \"[^\"]+\",", block, re.M)
    assert set(styles) == set(BACKGROUND_STYLES)
    new = ("jungle", "forest_loam", "scree_ground", "dunes", "snowfield", "swamp_mud", "temple_court", "packed_dirt", "churned_earth")
    for style in new:
        assert f'if (style === "{style}")' in source, f"{style} has no painter"
        assert "only the look" in floor_reading(style)["lines"][0]
    # A floor patch changes no rule: the same map with and without the new floors rasterizes and battles the same.
    floors = [{"material": f"floor:{style}", "cells": [[i % 8, i // 8]]} for i, style in enumerate(new)]
    plain = normalize_map(_map())
    painted = normalize_map(_map(materials=floors))
    assert len(painted["materials"]) == len(new)
    assert rasterize(painted) == rasterize(plain)
    assert _rule_regions(to_battlefield(painted)["terrain_regions"]) == _rule_regions(
        to_battlefield(plain)["terrain_regions"])


def _rule_regions(regions):
    """Only discard material metadata after proving it has no terrain effect."""
    rules = []
    for row in regions:
        if row.get("material_only"):
            assert row["terrain_type"] == "OPEN", row
            assert row["movement_cost"] == 1, row
            assert not row.get("occluder") and not row.get("sight_segments"), row
        else:
            rules.append(row)
    return rules


@pytest.mark.parametrize("effect", [
    {"terrain_type": "SIGHT_BLOCKED"},
    {"terrain_type": "BLOCKED"},
    {"terrain_type": "SIMPLE_COVER"},
    {"movement_cost": 2},
    {"occluder": "centerline"},
    {"sight_segments": {"scale": 100, "segments": [[[0, 50], [100, 50]]]}},
])
def test_material_only_filter_rejects_rule_bearing_floor_records(effect):
    row = {"material_only": True, "terrain_type": "OPEN", "movement_cost": 1}
    assert _rule_regions([row]) == []
    with pytest.raises(AssertionError):
        _rule_regions([{**row, **effect}])


def test_normalize_keeps_only_quarter_turns_of_biome_pieces():
    """Normalizer detail for the Turn control (the full editor-save, fight, commit and cold-reload path is
    test_rule_pieces_trees_and_decor_reach_the_engine_and_survive_a_cold_reload, with a turned brazier)."""
    turned = normalize_map(_map(terrain=[{"type": "SIMPLE_COVER", "look": "wooden_fence", "rotation": 90, "cells": [[1, 5]]},
                                         {"type": "SIMPLE_COVER", "look": "boulder", "rotation": 90, "cells": [[2, 5]]},
                                         {"type": "DIFFICULT", "look": "caltrops", "rotation": 45, "cells": [[3, 5]]}]))
    assert turned["terrain"][0]["rotation"] == 90
    assert "rotation" not in turned["terrain"][1], "only biome pieces turn; the original looks are drawn as they are"
    assert "rotation" not in turned["terrain"][2], "only quarter turns"
    assert to_battlefield(turned)["tabletop"]["terrain"][0]["rotation"] == 90
    plain = normalize_map(_map(terrain=[{"type": "SIMPLE_COVER", "look": "wooden_fence", "cells": [[1, 5]]},
                                        {"type": "SIMPLE_COVER", "look": "boulder", "cells": [[2, 5]]},
                                        {"type": "DIFFICULT", "look": "caltrops", "cells": [[3, 5]]}]))
    assert to_battlefield(turned)["terrain_regions"] == to_battlefield(plain)["terrain_regions"]
