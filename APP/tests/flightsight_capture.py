"""Task-owned headless captures; base modules load from Git, without a copy."""
import json
from pathlib import Path
import sys

if len(sys.argv) > 3:
    from tests.sol150_replay_capture import APP, baseline
    baseline(sys.argv[3], APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json")

if sys.argv[2] == "routes":
    from combat import flight
    from combat.gate2_grid import SquareGrid
    from combat.gate2_runtime_models import Position
    from tests.h1_support import ME, duel
    from tests.test_lock10_flight_movement import grant
    engine = duel([])
    engine.grid = SquareGrid({"width_squares": 9, "height_squares": 9, "square_size_ft": 5,
        "starting_positions": {}, "terrain_regions": [
            {"terrain_type": "BLOCKED", "height_ft": 10, "movement_cost": 0,
             "cells": [{"x": 5, "y": y} for y in (4, 5, 6)]},
            {"terrain_type": "OPEN", "movement_cost": 2, "cells": [{"x": 6, "y": 6}]}]})
    actor = engine.state.actors[ME]
    actor.position = Position(x=3, y=6, z=6)
    grant(engine, actor, flight_hover=1)
    result = {f"{p.x},{p.y},{p.z}": [cost, mode] for p, (_path, cost, mode) in flight.reachable(engine, actor).items()}
else:
    from tests.test_save_reload_equivalence import _play, _start_stock
    seed = sys.argv[2]
    result = _play(Path(sys.argv[1]), lambda root: _start_stock(root, seed))

print(json.dumps(result, sort_keys=True, separators=(",", ":")))
