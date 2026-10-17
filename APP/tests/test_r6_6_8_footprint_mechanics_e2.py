from __future__ import annotations

from pathlib import Path

import pytest

from combat.footprint_registry import ACTOR_FOOTPRINTS
from combat.footprints import ActorFootprintDefinition
from combat.gate2_engine import Gate2Engine
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_content import ACTIONS, AN, LEE
from combat.gate2_runtime_models import Position, ZoneState
from combat.gate3_storage import Gate3Persistence


ROOT = Path(__file__).resolve().parents[1]


def _grid_document(*, blocked=(), cover=(), hazard=(), difficult=()) -> dict:
    regions = []
    if blocked:
        regions.append({
            "region_id": "blocked",
            "terrain_type": "BLOCKED",
            "movement_cost": 0,
            "cells": [{"x": x, "y": y} for x, y in blocked],
        })
    if cover:
        regions.append({
            "region_id": "cover",
            "terrain_type": "SIMPLE_COVER",
            "movement_cost": 1,
            "cells": [{"x": x, "y": y} for x, y in cover],
        })
    if hazard:
        regions.append({
            "region_id": "hazard",
            "terrain_type": "QI_HAZARD",
            "movement_cost": 2,
            "cells": [{"x": x, "y": y} for x, y in hazard],
        })
    if difficult:
        regions.append({
            "region_id": "difficult",
            "terrain_type": "OPEN",
            "movement_cost": 2,
            "cells": [{"x": x, "y": y} for x, y in difficult],
        })
    return {
        "width_squares": 7,
        "height_squares": 7,
        "square_size_ft": 5,
        "starting_positions": {},
        "terrain_regions": regions,
    }


def _large() -> ActorFootprintDefinition:
    return ActorFootprintDefinition.rectangle(
        2,
        2,
        footprint_id="footprint:test.large.2x2",
        source_definition_id="test:large.2x2",
    )


def test_multicell_placement_collision_and_diagonal_corner_rules() -> None:
    grid = SquareGrid(_grid_document(blocked={(2, 0)}))
    large = _large()

    assert grid.placement_legal(Position(x=0, y=0), footprint=large)
    assert not grid.placement_legal(Position(x=1, y=0), footprint=large)
    assert not grid.placement_legal(
        Position(x=2, y=2),
        footprint=large,
        occupied_cells={(3, 3)},
    )
    assert not grid.step_legal(
        Position(x=0, y=0),
        Position(x=1, y=1),
        footprint=large,
    )


def test_multicell_pathfinding_uses_all_occupied_cells_and_entered_terrain() -> None:
    grid = SquareGrid(_grid_document(blocked={(2, 1)}, difficult={(1, 2)}))
    large = _large()

    assert grid.shortest_path(
        Position(x=0, y=0),
        Position(x=1, y=0),
        footprint=large,
    ) is None
    assert grid.shortest_path(
        Position(x=0, y=0),
        Position(x=2, y=0),
        footprint=large,
        occupied_cells={(3, 1)},
    ) is None

    multiplier = grid.movement_step_multiplier(
        Position(x=0, y=1),
        Position(x=1, y=1),
        footprint=large,
        difficult_cells={(2, 2)},
    )
    assert multiplier == 2


def test_multicell_distance_los_cover_and_radius_use_cell_sets() -> None:
    grid = SquareGrid(_grid_document(cover={(2, 0)}))
    large_cells = _large().occupied_cells(Position(x=0, y=0))
    target_cells = ((3, 1),)

    assert grid.distance_between_cell_sets_ft(large_cells, target_cells) == 10
    assert grid.line_of_sight_between_cell_sets(large_cells, target_cells)
    # One exposed sight line from the lower-right occupied cell avoids the
    # typed cover, so the deterministic best legal line has no cover bonus.
    assert grid.cover_bonus_between_cell_sets(large_cells, target_cells) == 0

    radius = {(p.x, p.y) for p in grid.cells_in_radius_of_cells(large_cells, 1)}
    assert (2, 2) in radius
    assert (3, 3) not in radius


def test_engine_uses_typed_multicell_footprint_for_movement_range_hazard_zone_and_invariants() -> None:
    footprints = dict(ACTOR_FOOTPRINTS)
    footprints[AN] = _large()
    engine = Gate2Engine(
        ROOT,
        match_seed="R668-E2-MULTICELL",
        actor_footprints=footprints,
    )
    an = engine.state.actors[AN]
    lee = engine.state.actors[LEE]

    assert set(engine._actor_cells(an)) == {(2, 8), (3, 8), (2, 9), (3, 9)}
    engine._assert_invariants()

    for candidate in engine._movement_candidates(an):
        assert candidate.destination is not None
        assert engine.grid.placement_legal(
            candidate.destination,
            footprint=engine._footprint(an),
            occupied_cells=engine._occupied_cells_except(AN),
        )

    lee.position = Position(x=4, y=8)
    melee = ACTIONS["action:an_eui.paired_bi_shou_assault"]
    assert engine._target_in_range(an, lee, melee)

    zone = ZoneState(
        zone_id="zone:test",
        source_definition_id="test:zone",
        owner_id=LEE,
        center=Position(x=3, y=9),
        radius_cells=0,
        affected_cells=(Position(x=3, y=9),),
        concentration_link=False,
        duration_rounds=1,
        created_round=1,
    )
    assert engine._in_zone(an, zone)

    an.position = Position(x=8, y=5)
    assert engine._footprint_intersects(an, engine.grid.qi_hazard)

    an.position = Position(x=2, y=8)
    lee.position = Position(x=3, y=8)
    with pytest.raises(ValueError, match="occupied footprint invariant"):
        engine._assert_invariants()


def test_new_match_lock_pins_footprint_and_grid_authority(tmp_path: Path) -> None:
    persistence = Gate3Persistence(ROOT, tmp_path / "UserData")
    rows = persistence._content_identity_rows()
    paths = {row.relative_path for row in rows}
    assert {
        "combat/gate2_grid.py",
        "combat/footprints.py",
        "combat/footprint_registry.py",
    } <= paths


def test_review_focus_correction_restores_exact_replacement_token() -> None:
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "restoreTokenFocus" in script
    assert 'sourceElement.matches?.(".combat-token")' in script
    assert 'data-actor-id="${CSS.escape(actorId)}"' in script
    assert "replacement?.focus({preventScroll: true})" in script
    assert "sourceElement?.isConnected" in script
