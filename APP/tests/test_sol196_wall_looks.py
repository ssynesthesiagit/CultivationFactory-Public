"""SOL196 phase 6 (owner 2026-10-08: "build different walls ... Ancient China and cultivation"): a wall's `look` is only
how it is drawn. The same map with and without looks gives identical squares, sight, movement and fight results,
through the editor's store, a table fight, a committed action and a cold reload; the look reaches the table."""
import re
from pathlib import Path

from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop import MAP_PREFIX, WALL_LOOKS, normalize_map, rasterize, to_battlefield
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT

TABLETOP = Path(__file__).resolve().parents[1] / "static" / "tabletop"
LOOKS = list(WALL_LOOKS)


def _walls(looks=True):
    walls = []
    for i, look in enumerate(LOOKS):
        y = 1 + i
        style = {"look": look} if looks else {}
        walls.append({"shape": "line", "points": [[2, y], [9, y]], "filled": False,
                      "blocks": "sight" if look in ("timber_lattice", "formation_barrier") else "sight_and_movement", **style})
    walls.append({"shape": "rect", "points": [[11, 2], [13, 4]], "filled": True, "blocks": "sight_and_movement", **({"look": "red_palace"} if looks else {})})
    walls.append({"shape": "circle", "points": [[12, 8], [13, 8]], "filled": False, "blocks": "sight_and_movement", **({"look": "jade_marble"} if looks else {})})
    return walls


def _map(name, looks=True):
    return {"map_id": name, "display_name": name, "width_squares": 15, "height_squares": 13, "walls": _walls(looks),
            "terrain": [], "trees": [], "starts": {"team1": [[0, 0]], "team2": [[14, 12]]},
            "objects": [{"id": 1, "kind": "door", "x": 4, "y": 3, "mount_axis": "h", "mount_line": 300, "blocks": True,
                         "interaction": "simple_door", "door_open": 0, "door_locked": 0, "door_jammed": 0}]}


def test_server_looks_match_the_drawn_looks():
    source = (TABLETOP / "wall-art.js").read_text()
    block = re.search(r"export const WALL_LOOKS = Object\.freeze\(\{(.*?)\}\);", source, re.S).group(1)
    assert set(WALL_LOOKS) == set(re.findall(r"^\s+(\w+):", block, re.M))


def test_a_look_is_kept_and_an_old_map_is_unchanged():
    looked, plain = normalize_map(_map("a")), normalize_map(_map("a", looks=False))
    assert [wall.get("look") for wall in looked["walls"]] == LOOKS + ["red_palace", "jade_marble"]
    assert all("look" not in wall for wall in plain["walls"]), "a wall saved without a look stays exactly as it was"
    odd = normalize_map({**_map("b"), "walls": [{"shape": "line", "points": [[0, 0], [3, 0]], "look": "neon"}]})
    assert "look" not in odd["walls"][0]
    assert rasterize(looked) == rasterize(plain)
    battle, bare = to_battlefield(looked), to_battlefield(plain)
    assert battle["terrain_regions"] == bare["terrain_regions"]
    assert [wall.get("look") for wall in battle["tabletop"]["walls"]] == LOOKS + ["red_palace", "jade_marble"]
    assert all("look" not in wall for wall in bare["tabletop"]["walls"])


def _start(root, document):
    from tests.test_save_reload_equivalence import _install_factory
    ids, _ = _install_factory(root, "sol196w", [], None)
    combat = CombatService(ROOT, root)
    saved = combat.tabletop_maps.save(document)
    mid = combat.create_factory_match(project_ids=[ids[0].removeprefix("actor:factory.")], opponent_actor_ids=[ids[1]],
                                      control_modes={a: "MANUAL" for a in ids}, arena_id=MAP_PREFIX + saved["map_id"],
                                      match_seed="SOL196-WALLS")["match_id"]
    return combat, saved, mid


def _rules(engine):
    grid = engine.grid
    cells = [(x, y) for x in range(grid.width) for y in range(grid.height)]
    sight = [(a, b) for a in ((0, 0), (7, 0), (0, 12), (5, 6)) for b in ((14, 12), (7, 12), (14, 0), (10, 6))]
    return (sorted(grid.base_movement_cost.items()), sorted(map(tuple, grid.centerline_cells)),
            [cell for cell in cells if grid.terrain_at(cell, "BLOCKED")], [cell for cell in cells if grid.terrain_at(cell, "SIGHT_BLOCKED")],
            [grid.line_of_sight(Position(x=a[0], y=a[1], z=0), Position(x=b[0], y=b[1], z=0)) for a, b in sight],
            sorted((a.entity_id, a.position.x, a.position.y) for a in engine.state.actors.values()))


def _moves(menu):
    return sorted((m["destination"]["x"], m["destination"]["y"], m.get("cost_ft")) for m in (menu or {}).get("moves") or [])


def test_wall_looks_change_nothing_in_a_fight_and_survive_a_cold_reload(tmp_path):
    combat, looked, mid = _start(tmp_path / "looked", _map("walls"))
    bare_combat, bare, bare_mid = _start(tmp_path / "bare", _map("walls", looks=False))
    assert [w.get("look") for w in looked["walls"]][:len(LOOKS)] == LOOKS
    engine, bare_engine = combat._load_session(mid).engine, bare_combat._load_session(bare_mid).engine
    assert _rules(engine) == _rules(bare_engine)
    table = TabletopService(combat, tmp_path / "looked")
    state = table.state(mid, fog=True)
    bare_state = TabletopService(bare_combat, tmp_path / "bare").state(bare_mid, fog=True)
    assert [w.get("look") for w in state["map"]["walls"]][:len(LOOKS)] == LOOKS
    assert _moves(state["menu"]) == _moves(bare_state["menu"]) and _moves(state["menu"])
    assert state["fog_perception"] == bare_state["fog_perception"]
    menu = state["menu"]
    assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], [])["status"] == "COMMITTED"
    cold = CombatService(ROOT, tmp_path / "looked")
    loaded = cold._load_session(mid)
    assert _rules(loaded.engine) == _rules(bare_engine)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    assert TabletopService(cold, tmp_path / "looked").state(mid, fog=True)["map"]["walls"] == state["map"]["walls"]
