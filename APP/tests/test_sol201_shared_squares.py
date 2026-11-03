"""SOL201 (owner 2026-10-08): "I want you to be able to place objects to share space and organize its positions
dynamically to look natural if they fit in the 5ft square."

Through the real path the table uses (tests/test_son198_object_catalog_engine.py explains it; corkboard #1545):
editor-format map -> TabletopMapStore.save -> CombatService.create_factory_match -> the session's
mechanical.execute_intent -> a cold reload. Each object in a shared square keeps its own rules: the square blocks
while any blocking object in it stands, and attacking one object touches only that one."""
from __future__ import annotations

import json

import pytest

from combat import object_rules
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError, normalize_map
from combat.tabletop_service import TabletopService
from tests.test_son198_object_catalog_engine import (LEFT, RIGHT, ROOT, _install, advance_to_human, end_turn,
                                                     move_adjacent_to, run_candidate)
from tests.test_sysv2_objects import force_d20

SHARED = (8, 5)
SOFT = (8, 8)
OBJECTS = [
    # Stacked crate and barrel, each marked as filling the square (the placement's own "blocks", an existing rule key).
    {"id": 1, "kind": "crate", "x": SHARED[0], "y": SHARED[1], "blocks": True, "nudge": [6, -4]},
    {"id": 2, "kind": "barrel", "x": SHARED[0], "y": SHARED[1], "blocks": True},
    # Two tiny cushions and a look-only decor piece: nothing here blocks.
    {"id": 3, "kind": "meditation_cushion", "x": SOFT[0], "y": SOFT[1]},
    {"id": 4, "kind": "meditation_cushion", "x": SOFT[0], "y": SOFT[1]},
]


def _map(**extra):
    return {"display_name": "SOL201 Storeroom", "width_squares": 18, "height_squares": 12,
            "starts": {"team1": [[3, 5]], "team2": [[15, 10]]},
            "decor": [{"kind": "prayer_mat", "x": SOFT[0], "y": SOFT[1], "seed": 7}],
            "objects": OBJECTS, **extra}


def _start(tmp_path):
    _install(tmp_path, "left")
    _install(tmp_path, "right")
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save(_map())
    view = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[RIGHT], control_modes={LEFT: "MANUAL"},
                                       arena_id=f"battlefield:map.{saved['map_id']}", match_seed="SOL201-SHARED")
    return combat, saved, view["match_id"]


def _attack_candidate(engine, object_id):
    return next(c for c in engine.legal_candidates()
                if c.actor_id == LEFT and tuple(c.target_ids or ()) == (object_id,)
                and "Attack an object" in c.display_name and "+" not in c.display_name)


def _blocked(engine, cell):
    return tuple(cell) in engine.grid.blocked


def _sight_through(engine, cell):
    return engine.grid.line_of_sight(Position(x=cell[0] - 2, y=cell[1]), Position(x=cell[0] + 2, y=cell[1]))


def test_saved_map_keeps_shared_squares_and_the_nudge(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save(_map())
    rows = {row["id"]: row for row in saved["objects"]}
    assert rows[1]["nudge"] == [6, -4] and "nudge" not in rows[2]
    assert [list(cell) for cell in saved["cells"]["blocked"]] == [], "objects never become map walls"
    again = combat.tabletop_maps.get(saved["map_id"])
    assert again["objects"] == saved["objects"]


def test_a_packed_square_refuses_another_object_in_plain_words(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    packed = [*OBJECTS[:2], {"id": 9, "kind": "meditation_cushion", "x": SHARED[0], "y": SHARED[1]}]
    with pytest.raises(TabletopError) as refused:
        combat.tabletop_maps.save(_map(objects=packed))
    assert refused.value.code == "MAP_SQUARE_FULL"
    assert "crate, barrel and meditation cushion" in str(refused.value)
    assert "2 small ones" in str(refused.value)
    # A medium object stands alone; four tiny ones fit.
    with pytest.raises(TabletopError):
        combat.tabletop_maps.save(_map(objects=[{"id": 1, "kind": "statue", "x": 2, "y": 2}, {"id": 2, "kind": "meditation_cushion", "x": 2, "y": 2}]))
    four = [{"id": n, "kind": "meditation_cushion", "x": 2, "y": 2} for n in range(1, 5)]
    assert len(combat.tabletop_maps.save(_map(objects=four))["objects"]) == 4


def test_old_maps_load_unchanged(tmp_path):
    """One object per square: no new keys appear; a map saved overfull before this rule still opens."""
    legacy = {"map_id": "legacy-yard", "display_name": "Legacy", "width_squares": 10, "height_squares": 8,
              "objects": [{"id": 1, "kind": "crate", "x": 2, "y": 2}, {"id": 2, "kind": "barrel", "x": 3, "y": 2, "rotation": 90}]}
    assert normalize_map(legacy)["objects"] == [{"id": 1, "kind": "crate", "x": 2, "y": 2},
                                                {"id": 2, "kind": "barrel", "x": 3, "y": 2, "rotation": 90}]
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.root.mkdir(parents=True, exist_ok=True)
    overfull = {**legacy, "objects": [{"id": n, "kind": "statue", "x": 2, "y": 2} for n in (1, 2)]}
    (combat.tabletop_maps.root / "legacy-yard.json").write_text(json.dumps(overfull), encoding="utf-8")
    assert len(combat.tabletop_maps.get("legacy-yard")["objects"]) == 2


def test_shared_square_rules_targeting_and_destruction_through_the_real_fight_and_a_cold_reload(tmp_path):
    combat, saved, mid = _start(tmp_path)
    session = combat._load_session(mid)
    engine = session.engine
    advance_to_human(engine, session)
    crate, barrel = "object:map.1", "object:map.2"
    assert {crate, barrel, "object:map.3", "object:map.4"} <= set(engine.state.objects)

    # The square blocks (any blocking object), the cushions-and-decor square does not.
    assert _blocked(engine, SHARED) and not _sight_through(engine, SHARED)
    assert not _blocked(engine, SOFT) and _sight_through(engine, SOFT)

    # The table sees each object with its footprint (and the crate's nudge), in the same square.
    view = {row["id"]: row for row in TabletopService._objects(engine)}
    assert (view[crate]["x"], view[crate]["y"]) == (view[barrel]["x"], view[barrel]["y"]) == SHARED
    assert view[crate]["footprint"] == view[barrel]["footprint"] == "small"
    assert view["object:map.3"]["footprint"] == "tiny"
    assert view[crate]["nudge"] == [6, -4] and "nudge" not in view[barrel]

    # Targeting: each object in the shared square is its own candidate; aiming at the barrel touches only the barrel.
    move_adjacent_to(engine, session, barrel)
    advance_to_human(engine, session)
    force_d20(engine, 13, 19)
    crate_hp = engine.state.objects[crate].current_hp
    assert _attack_candidate(engine, crate).candidate_id != _attack_candidate(engine, barrel).candidate_id
    events = run_candidate(engine, session, LEFT, _attack_candidate(engine, barrel))
    hits = [e for e in events if e.event_type == "OBJECT_UPDATED"]
    assert hits and all(tuple(e.target_ids) == (barrel,) for e in hits)
    assert engine.state.objects[crate].current_hp == crate_hp
    end_turn(engine, session)

    # Destroy the barrel: the crate still stands and still blocks the square.
    for _ in range(10):
        if engine.state.objects[barrel].destroyed:
            break
        advance_to_human(engine, session)
        force_d20(engine, 13, 19)
        run_candidate(engine, session, LEFT, _attack_candidate(engine, barrel))
        end_turn(engine, session)
    assert engine.state.objects[barrel].destroyed

    def check(engine):
        assert engine.state.objects[barrel].destroyed and not engine.state.objects[crate].destroyed
        assert engine.state.objects[crate].current_hp == crate_hp
        assert _blocked(engine, SHARED) and not _sight_through(engine, SHARED), "the crate still fills the square"
        assert not _blocked(engine, SOFT)
        rows = {row["id"]: row for row in TabletopService._objects(engine)}
        assert barrel not in rows and rows[crate]["nudge"] == [6, -4]

    check(engine)
    check(CombatService(ROOT, tmp_path)._load_session(mid).engine)


def test_destroying_the_last_blocking_object_opens_the_square(tmp_path):
    """Crate (blocking) + cushion: once the crate is gone, the cushion alone does not block."""
    _install(tmp_path, "left")
    _install(tmp_path, "right")
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save(_map(objects=[
        {"id": 1, "kind": "crate", "x": SHARED[0], "y": SHARED[1], "blocks": True},
        {"id": 2, "kind": "meditation_cushion", "x": SHARED[0], "y": SHARED[1]}]))
    mid = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[RIGHT], control_modes={LEFT: "MANUAL"},
                                      arena_id=f"battlefield:map.{saved['map_id']}", match_seed="SOL201-OPEN")["match_id"]
    session = combat._load_session(mid)
    engine = session.engine
    advance_to_human(engine, session)
    assert _blocked(engine, SHARED)
    move_adjacent_to(engine, session, "object:map.1")
    for _ in range(10):
        if engine.state.objects["object:map.1"].destroyed:
            break
        advance_to_human(engine, session)
        force_d20(engine, 13, 19)
        run_candidate(engine, session, LEFT, _attack_candidate(engine, "object:map.1"))
        end_turn(engine, session)
    for live in (engine, CombatService(ROOT, tmp_path)._load_session(mid).engine):
        assert live.state.objects["object:map.1"].destroyed and not live.state.objects["object:map.2"].destroyed
        assert not _blocked(live, SHARED) and _sight_through(live, SHARED)


def test_footprints_come_from_the_rules_table():
    assert object_rules.footprint({"kind": "barrel"}) == "small", "a barrel is Medium for hit points, small on the floor"
    assert object_rules.footprint({"kind": "barrel", "size": "large"}) == "large", "a resized placement resizes its footprint"
    assert object_rules.footprint({"kind": "door", "mount_axis": "h"}) == "large"
    assert object_rules.square_problem([{"kind": "crate"}, {"kind": "barrel"}]) is None
    defaults = object_rules.editor_defaults()
    assert defaults["presets"]["grain_sack"]["footprint"] == "tiny" and defaults["square_capacity"] == 4
    assert all(row["footprint"] in defaults["footprint_fill"] for row in defaults["presets"].values())


# ------------------------------------------------------------------------------------------------ collisions (review finding 1)
# A creature slammed into a shared square is stopped by the blocking object there; the collision damage goes to that
# object (combat/ext/objects.py blocker_at), never to a non-blocking cushion that happens to share the square, whatever
# order the two were placed in. Same engine harness as the plug-ins' own collision tests (tests/test_riders_c7.py).
from tests import test_riders_c7 as c7  # noqa: E402


def _pair(cell, anvil_first, anvil_hp=999):
    anvil = {"kind": "blacksmith_anvil", "x": cell[0], "y": cell[1], "hp": anvil_hp}
    cushion = {"kind": "meditation_cushion", "x": cell[0], "y": cell[1], "hp": 999}
    rows = [anvil, cushion] if anvil_first else [cushion, anvil]
    ids = {}
    for number, row in enumerate(rows, start=1):
        row["id"] = number
        ids[row["kind"]] = f"object:map.{number}"
    return rows, ids["blacksmith_anvil"], ids["meditation_cushion"]


def _hurt(engine, object_id):
    obj = engine.state.objects[object_id]
    return obj.maximum_hp - obj.current_hp


@pytest.mark.parametrize("anvil_first", [True, False])
def test_sumo_strike_collision_damages_the_blocking_object_not_its_neighbour(anvil_first):
    objects, anvil, cushion = _pair((6, 6), anvil_first)
    engine, _me, foe = c7._sumo(["sumo_strike"], picks={"sumo_strike": ["Push it"]}, objects=objects)
    c7.use(engine, c7.unarmed(engine), target=c7.FOE)
    assert (foe.position.x, foe.position.y) == (5, 6), "stopped by the anvil"
    assert _hurt(engine, anvil) > 0 and _hurt(engine, cushion) == 0


@pytest.mark.parametrize("anvil_first", [True, False])
def test_body_crosses_heaven_collision_damages_the_blocking_object_not_its_neighbour(anvil_first):
    objects, anvil, cushion = _pair((9, 3), anvil_first)
    engine, _me, foe = c7._sky(["body_crosses_heaven"], me_at=(2, 6), foe_at=(9, 6), objects=objects,
                               picks={"body_crosses_heaven": ["use"], "crosses_heaven_direction": ["cell:9,0"]})
    c7.use(engine, "Move to 8,6")
    c7.use(engine, c7.unarmed(engine), target=c7.FOE)
    assert (foe.position.x, foe.position.y) == (9, 4), "stopped by the anvil"
    assert _hurt(engine, anvil) == 6 and _hurt(engine, cushion) == 0


def test_a_destroyed_blocker_no_longer_stops_a_push_and_the_cushion_beside_it_is_untouched():
    from combat.ext.objects import blocker_at, deal

    objects, anvil, cushion = _pair((6, 6), anvil_first=False, anvil_hp=1)
    engine, me, foe = c7._sumo(["sumo_strike"], picks={"sumo_strike": ["Push it"]}, objects=objects)
    deal(engine, me, engine.state.objects[anvil], [(50, "BLUDGEONING")], "test:break")
    assert engine.state.objects[anvil].destroyed and blocker_at(engine, engine.state.objects[cushion].position) is None
    c7.use(engine, c7.unarmed(engine), target=c7.FOE)
    assert (foe.position.x, foe.position.y) == (6, 6), "the square is open: the full 10 feet"
    assert _hurt(engine, cushion) == 0


def test_blocker_selection_survives_a_cold_reload_through_the_real_fight_path(tmp_path):
    """The helper reads only saved, evented object state: after a reload it still names the blocking object."""
    from combat.ext.objects import blocker_at

    _install(tmp_path, "left")
    _install(tmp_path, "right")
    combat = CombatService(ROOT, tmp_path)
    objects, anvil, _cushion = _pair(SHARED, anvil_first=False)
    saved = combat.tabletop_maps.save(_map(objects=objects))
    mid = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[RIGHT], control_modes={LEFT: "MANUAL"},
                                      arena_id=f"battlefield:map.{saved['map_id']}", match_seed="SOL201-BLOCKER")["match_id"]
    session = combat._load_session(mid)
    advance_to_human(session.engine, session)
    for engine in (session.engine, CombatService(ROOT, tmp_path)._load_session(mid).engine):
        assert blocker_at(engine, Position(x=SHARED[0], y=SHARED[1])).object_id == anvil


# ------------------------------------------------------------------------------------------------ one budget (review finding 2)
_PARITY_JS = """
import {footprintOf, squareRoom} from './static/tabletop/object-arrange.js';
const {defaults, rows, squares} = JSON.parse(process.argv[1]);
console.log(JSON.stringify({
  footprints: rows.map(row => footprintOf(row, defaults)),
  fits: squares.map(([others, object]) => squareRoom(others, object, defaults).ok),
}));
"""


def test_editor_and_server_agree_on_footprints_and_what_fits_including_resized_placements():
    """The editor (object-arrange.js fed editor_defaults) and the save check (object_rules) give the same answers, so a
    resized crate is never let in by one and refused by the other."""
    import itertools
    import subprocess

    defaults = object_rules.editor_defaults()
    kinds = ["crate", "barrel", "grain_sack", "meditation_cushion", "statue", "blacksmith_anvil", "custom"]
    rows = [{"kind": kind, **({"size": size} if size else {})}
            for kind in kinds for size in (None, "tiny", "small", "medium", "large")]
    rows.append({"kind": "door", "mount_axis": "h"})
    squares = [([a], b) for a, b in itertools.product(rows[:20], rows[:20])]
    squares += [([{"kind": "crate", "size": "large"}], {"kind": "barrel"}),
                ([{"kind": "crate", "size": "tiny"}, {"kind": "barrel"}], {"kind": "meditation_cushion"})]
    out = subprocess.run(["node", "--input-type=module", "-e", _PARITY_JS, json.dumps({"defaults": defaults, "rows": rows, "squares": squares})],
                         cwd=ROOT, capture_output=True, text=True, timeout=60, check=True)
    client = json.loads(out.stdout)
    assert client["footprints"] == [object_rules.footprint(row) for row in rows]
    assert client["fits"] == [object_rules.square_problem([*others, obj]) is None for others, obj in squares]
    assert client["fits"][-2:] == [False, True], "a large crate leaves no room; a tiny one leaves room for a cushion"


def test_the_save_refuses_exactly_what_the_editor_refuses_for_a_resized_crate(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    with pytest.raises(TabletopError):
        combat.tabletop_maps.save(_map(objects=[{"id": 1, "kind": "crate", "x": 2, "y": 2, "size": "large"},
                                                {"id": 2, "kind": "barrel", "x": 2, "y": 2}]))
    saved = combat.tabletop_maps.save(_map(objects=[{"id": 1, "kind": "crate", "x": 2, "y": 2, "size": "tiny"},
                                                    {"id": 2, "kind": "barrel", "x": 2, "y": 2},
                                                    {"id": 3, "kind": "meditation_cushion", "x": 2, "y": 2}]))
    assert len(saved["objects"]) == 3
