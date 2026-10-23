"""Regression for the Dragon-Vein Gravity Circuit's hostile difficult terrain.

Sol review F11R (blocking): the gravity area must be priced square by square on
the route, not as one surcharge from the creature's starting square. The area is
published as a derived zone (combat/ext hook "zones") so the shared terrain path
(zones.difficult_cells -> SquareGrid.movement_step_multiplier) charges each square
entered, and a hostile leaving the area is not charged for it.
"""
from types import SimpleNamespace

from combat import zones as zones_module
from combat.ext import dragon_vein_geomancer as dv
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position


def _engine():
    grid = SimpleNamespace(width=12, height=12, square_size_ft=5,
                           distance_ft=lambda a, b: 5 * max(abs(a.x - b.x), abs(a.y - b.y)))
    owner = SimpleNamespace(entity_id="geomancer", team_id="team:a", position=Position(x=5, y=5, z=0))
    hostile = SimpleNamespace(entity_id="hostile", team_id="team:b", position=Position(x=9, y=5, z=0))
    return SimpleNamespace(grid=grid, state=SimpleNamespace(actors={"geomancer": owner, "hostile": hostile}))


def _patch(monkeypatch, *, gravity=True):
    anchor = SimpleNamespace(object_id="anchor:1", position=Position(x=5, y=5, z=0))
    monkeypatch.setattr(dv, "kit", lambda engine, actor: {"owned": [dv.CIRCUIT]} if actor.entity_id == "geomancer" else None)
    monkeypatch.setattr(dv, "anchors", lambda engine, actor: [anchor] if actor.entity_id == "geomancer" else [])
    monkeypatch.setattr(dv, "modes", lambda engine, actor, obj: ("gravity",) if gravity else ("earth",))
    monkeypatch.setattr(dv, "radius", lambda engine, actor, obj: 10)
    monkeypatch.setattr(zones_module, "terrain_rules", lambda: {"default_color": "#000000"})
    return anchor


def test_gravity_anchor_publishes_hostile_difficult_zone_within_radius(monkeypatch):
    _patch(monkeypatch)
    [zone] = dv.gravity_zones(_engine())
    cells = {(c.x, c.y) for c in zone.affected_cells}
    assert zone.owner_id == "geomancer" and zone.trigger_profile["difficult"] == "hostile"
    assert (7, 5) in cells and (3, 5) in cells          # two squares = 10 ft
    assert (8, 5) not in cells and (2, 5) not in cells  # three squares is outside


def test_no_gravity_mode_publishes_no_zone(monkeypatch):
    _patch(monkeypatch, gravity=False)
    assert dv.gravity_zones(_engine()) == []


def test_route_pays_for_each_square_entered_not_the_start_square(monkeypatch):
    _patch(monkeypatch)
    engine = _engine()
    [zone] = dv.gravity_zones(engine)
    difficult = {(c.x, c.y) for c in zone.affected_cells}
    grid = SquareGrid({"width_squares": 12, "height_squares": 12, "square_size_ft": 5, "starting_positions": {}})
    # Hostile starts inside (7,5) and walks out: leaving costs nothing extra.
    assert grid.movement_step_multiplier((7, 5), (8, 5), difficult_cells=difficult) == 1
    # Hostile starts outside and walks in: each square entered is difficult.
    assert grid.movement_step_multiplier((8, 5), (7, 5), difficult_cells=difficult) == 2
    assert grid.movement_step_multiplier((7, 5), (6, 5), difficult_cells=difficult) == 2
