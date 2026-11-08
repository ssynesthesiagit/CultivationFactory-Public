"""Explicit obstacle heights reach maps, native geometry and saved Table state."""
import pytest

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position, RuntimeObjectState
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield, TabletopError
from combat import zones
from tests.h1_support import ROOT, ME, FOE, duel
from tests.test_tabletop_hunt6 import table_fight, on_hold, HOLD
from tests.test_lock2_persistence import act


def document(height=None):
    wall = {"shape": "rect", "points": [[5, 2], [6, 3]], "blocks": "sight_and_movement"}
    if height is not None:
        wall["height_ft"] = height
    return {"display_name": "Height yard", "width_squares": 12, "height_squares": 8, "walls": [wall],
            "starts": {"team1": [[3, 4]], "team2": [[8, 4]]}}


def test_explicit_five_foot_wall_clears_sight_at_its_top():
    normalized = normalize_map(document(5))
    assert normalized["walls"][0]["height_ft"] == 5
    g = SquareGrid(to_battlefield(normalized))
    assert g.line_of_sight(Position(x=4, y=2, z=1), Position(x=7, y=2, z=1))
    assert not g.line_of_sight(Position(x=4, y=2), Position(x=7, y=2))


def test_default_ten_foot_wall_blocks_below_its_top_and_clears_at_it():
    normalized = normalize_map(document())
    assert normalized["walls"][0]["height_ft"] == 10
    g = SquareGrid(to_battlefield(normalized))
    assert not g.line_of_sight(Position(x=4, y=2, z=1), Position(x=7, y=2, z=1))
    assert g.line_of_sight(Position(x=4, y=2, z=2), Position(x=7, y=2, z=2))
    assert not g.line_of_sight(Position(x=4, y=2), Position(x=7, y=2))


@pytest.mark.parametrize("height", [True, -1, 1.5])
def test_bad_height_is_a_readable_map_error(height):
    with pytest.raises(TabletopError, match="whole number"):
        normalize_map(document(height))


def test_overlapping_default_wall_blocks_above_short_wall_but_has_a_finite_top():
    doc = document(5)
    doc["walls"].append({**doc["walls"][0], "height_ft": None})
    g = SquareGrid(to_battlefield(normalize_map(doc)))
    assert not g.line_of_sight(Position(x=4, y=2, z=1), Position(x=7, y=2, z=1))
    assert g.line_of_sight(Position(x=4, y=2, z=20), Position(x=7, y=2, z=20))


def test_raised_finite_object_blocks_only_its_vertical_span_and_reloads(monkeypatch, tmp_path):
    combat, table, mid = table_fight(tmp_path, [])
    def place(engine):
        engine._update_object(RuntimeObjectState(object_id="object:test.height", object_kind="pillar",
            position=Position(x=6, y=2, z=2), height_ft=10, unattended=True, flammable=False,
            ac=12, current_hp=20, maximum_hp=20, component={"blocks": True, "name": "Raised pillar"}),
            "test:place", None)
        zones.sync_walls(engine)
    on_hold(monkeypatch, place)
    assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    e = loaded.engine
    for z, clear in [(0, True), (2, False), (3, False), (4, True)]:
        assert e.grid.line_of_sight(Position(x=5, y=2, z=z), Position(x=7, y=2, z=z)) is clear
    obj = e.state.objects["object:test.height"]
    assert obj.height_ft == 10 and obj.position.z == 2
    row = next(row for row in table.state(mid)["objects"] if row["id"] == obj.object_id)
    assert row["height_ft"] == row["altitude_ft"] == 10
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_contact_does_not_reveal_or_block_a_concealed_creature_on_another_level():
    from combat.target_knowledge import movement_contact
    e = duel([])
    actor, target = e.state.actors[ME], e.state.actors[FOE]
    target.fly_speed_ft = 30
    target.position = target.position.model_copy(update={"z": 2})
    e._apply_condition(target, "condition:typed.invisible", "test:invisible", FOE, expires_on=None)
    ground = target.position.model_copy(update={"z": 0})
    assert not movement_contact(e, actor, ground)
    assert not actor.turn_flags.get("unseen_contact_cells")
    actor.fly_speed_ft = 30
    actor.position = actor.position.model_copy(update={"z": 2})
    assert movement_contact(e, actor, target.position)
    assert all(cell["z"] == 2 for cell in actor.turn_flags["unseen_contact_cells"])
    actor.position = actor.position.model_copy(update={"z": 0})
    assert (ground.x, ground.y) not in e._occupied_cells_except(ME, observed=True)
