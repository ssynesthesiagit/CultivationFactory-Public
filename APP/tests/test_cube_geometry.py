"""Square-side dimensions agree at the saved table and shared area boundary."""
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import area_cells, in_area, _area_targets
from combat.zones import _cells
from tests.h1_support import sheet
from tests.test_menuspeed3_review import offline_menu_embeddings

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("shape", ["cube", "square"])
@pytest.mark.parametrize("size", [5, 10, 15, 20, 25, 30])
def test_square_sides_cover_exactly_the_printed_number_of_cells(shape, size):
    engine = Gate2Engine(ROOT, match_seed="SQUARE-SIDES")
    aim = Position(x=10, y=6)
    area = {"shape": shape, "size_ft": size}
    count = size // 5
    expected = {Position(x=10 + dx, y=6 + dy)
                for dx in range(-(count // 2), count - count // 2)
                for dy in range(-(count // 2), count - count // 2)}
    assert set(area_cells(engine, aim, aim, area)) == expected
    assert set(_cells(engine, aim, area)) == expected
    for x in range(6, 15):
        for y in range(2, 11):
            point = Position(x=x, y=y)
            assert in_area(engine, aim, aim, point, area) == (point in expected)


@pytest.mark.parametrize("shape", ["sphere", "cylinder", "emanation", "line", "cone"])
@pytest.mark.parametrize("size", [10, 15, 20])
def test_radius_and_ray_shapes_keep_their_existing_geometry(shape, size):
    import math

    engine = Gate2Engine(ROOT, match_seed="OTHER-SHAPES")
    vertex, aim = Position(x=3, y=6), Position(x=8, y=6)
    area = {"shape": shape, "size_ft": size, "width_ft": 10}
    expected = set()
    for y in range(engine.grid.height):
        for x in range(engine.grid.width):
            if shape in ("line", "cone"):
                along, perp = (x - vertex.x) * 5, abs(y - vertex.y) * 5
                inside = 0 <= along <= size and perp <= (5 if shape == "line" else along * .5)
            else:
                inside = math.hypot(x - aim.x, y - aim.y) * 5 <= size + 1e-9
            if inside:
                expected.add(Position(x=x, y=y))
    assert set(area_cells(engine, vertex, aim, area)) == expected
    assert set(_cells(engine, aim, area, vertex)) == expected


def test_gather_current_preview_shading_and_zone_agree_after_table_reload(tmp_path):
    ids = ["actor:factory.caster", "actor:factory.foe"]
    bundles = [compile_character(sheet(["AIR_BASE_GATHER_CURRENT"], cl=1), actor_id=ids[0]),
               compile_character(sheet([], cl=1), actor_id=ids[1])]
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    arena = service.tabletop_maps.save({"display_name": "Cube dimensions", "width_squares": 16,
        "height_squares": 12, "walls": [], "materials": [], "objects": [],
        "starts": {"team1": [[3, 5]], "team2": [[6, 5]]}})
    battlefield = service.tabletop_maps.arenas()["battlefield:map." + arena["map_id"]]
    match_id = service._finish_factory_match(bundles, ids,
        {ids[0]: "team:factory", ids[1]: "team:opponents"},
        {ids[0]: {"x": 3, "y": 5}, ids[1]: {"x": 6, "y": 5}},
        battlefield, ids[:1], ids[1:], control_modes={a: "MANUAL" for a in ids},
        match_seed="CUBE-TABLE", display_name="Cube dimensions", maximum_rounds=3)["match_id"]
    state = table.state(match_id)
    for _ in range(4):
        if state["menu"]["actor_id"] == ids[0]:
            break
        menu = state["menu"]
        result = table.act(match_id, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
        assert result["status"] == "COMMITTED"
        state = result["state"]
    menu = state["menu"]
    action = next(g for g in menu["actions"] if g["label"].startswith("Gather Current"))
    option = action['options'][0]
    assert action['placement_picker']
    # Inspect the actual paused picker, never substitute a concrete candidate
    # into a private menu renderer: that bypassed the player's lazy path.
    from combat.placement_menu import CHOICE
    from combat.ext.needle import cell_id
    expected = [{"x": 4, "y": 4}, {"x": 5, "y": 4}, {"x": 4, "y": 5}, {"x": 5, "y": 5}]
    answers = []
    picker = None
    for _ in range(10):
        result = table.act(match_id, option["candidate_id"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        if prompt['context']['reaction_source_id'] == CHOICE:
            picker = prompt
            chosen_id = cell_id(Position(x=5, y=5), include_altitude=True)
            assert picker['choice']['map_pick']['areas'][chosen_id] == expected
            from tests.test_menuspeed3j_preview import assert_client_preview
            assert_client_preview(picker['choice'], {'x': 5, 'y': 5}, 0, expected)
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            answer["option_ids"] = ([cell_id(Position(x=5, y=5), include_altitude=True)]
                if prompt['context']['reaction_source_id'] == CHOICE
                else [prompt["choice"]["options"][0]["id"]])
        answers.append(answer)
    assert result["status"] == "COMMITTED"
    assert picker is not None
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(match_id)
    zone = next(z for z in session.engine.state.zones.values() if z.active)
    assert [p.model_dump(mode="json") for p in zone.affected_cells] == expected
    # The table's presentation feeds the board's zone mask without recomputing geometry.
    reloaded = TabletopService(fresh, tmp_path).state(match_id)
    painted = next(z for z in reloaded["presentation"]["zones"] if z["zone_id"] == zone.zone_id)
    assert painted["affected_cells"] == expected
    assert reloaded == result["state"]
    engine = session.engine
    caster = engine.state.actors[ids[0]]
    typed_area = engine.action_catalog[action["source_definition_id"]].parameters["typed"]["area"]
    assert engine.state.actors[ids[1]] not in _area_targets(engine, caster, Position(x=5, y=5), typed_area)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    from combat.ext.air_currents import in_current

    foe = engine.state.actors[ids[1]]
    assert not in_current(engine, caster, foe)
    # Check the real Air Current consumer too, on the freshly loaded scratch state.
    for point in expected:
        foe.position = Position(**point)
        assert in_current(engine, caster, foe)
        assert foe in _area_targets(engine, caster, Position(x=5, y=5), typed_area)
