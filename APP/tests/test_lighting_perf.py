"""The measured light numbers: docs/specs/LIGHTING_SPEC.md §6.3, §8.

The budgets in the spec are targets, not gates: this test measures the same shapes on the largest shipped map and holds
a ceiling well above them so a regression fails loudly while the report carries the numbers themselves. It only runs
when LIGHTING_PERF=1, because a shared machine's timing is not a test result.
"""
import json
import os
import time

import pytest

from combat import lighting
from combat.read_queries import read_frame
from tests.h1_support import ROOT
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload

pytestmark = pytest.mark.skipif(os.environ.get("LIGHTING_PERF") != "1",
                               reason="set LIGHTING_PERF=1 to measure the light budgets (spec §6.3)")
FORTRESS = ROOT / "combat/maps/builtin-frontier-fortress-wall.json"
VIEWERS, SOURCES = 12, 60


def lit_fortress():
    document = json.loads(FORTRESS.read_text())
    width, height = document["width_squares"], document["height_squares"]
    document["display_name"] = "Lit fortress (perf)"
    document.pop("map_id", None)              # a copy, never an edit of the built-in
    document["ambient"] = {"time_of_day": "night"}
    document["lights"] = [{"id": f"t{index}", "name": "Torch", "x": 1 + (index * 7) % (width - 2),
                           "y": 1 + (index * 5) % (height - 2), "bright_ft": 20, "dim_ft": 40}
                          for index in range(SOURCES)]
    return document


def big_map(tmp_path, document=None):
    document = document or map_document(60, 40, ambient=ambient_light("night"),
                                        lights=[light(3 + (index % 10) * 5, 3 + (index // 10) * 5,
                                                      name=f"Torch {index}", light_id=f"t{index}")
                                                for index in range(SOURCES)])
    combat, table, mid = fight(tmp_path, document, senses=[],
                               positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 4, "y": 2}},
                               extra_allies=VIEWERS - 3)
    return reload(tmp_path, mid)


def timed(function, repeat=5):
    return min(one(function) for _ in range(repeat))


def one(function):
    started = time.perf_counter()
    function()
    return (time.perf_counter() - started) * 1000.0


def test_the_field_of_the_largest_map_with_sixty_sources(tmp_path):
    engine = big_map(tmp_path, lit_fortress())
    assert len(lighting.sources(engine)) == SOURCES
    cold = one(lambda: lighting.field(engine))
    steady = timed(lambda: lighting.field(engine))
    print(f"fortress {engine.grid.width}x{engine.grid.height}, {SOURCES} sources, "
          f"{len(engine.grid.sight_line_sources)} occluders: cold {cold:.2f} ms, steady {steady:.2f} ms, "
          f"{len(lighting.field(engine))} cells")
    assert steady < 60, steady                     # spec §6.3 target 8 ms; the deviation is in the S1 report


def test_the_marginal_cost_of_each_extra_viewer(tmp_path):
    """Composition, not the field: the pass has already paid for the field the table asked for."""
    engine = big_map(tmp_path, lit_fortress())
    viewers = list(engine.state.actors.values())[:VIEWERS]
    assert len(viewers) == VIEWERS
    with read_frame(engine):
        lighting.field(engine)
        one_viewer = timed(lambda: lighting.summaries(engine, viewers[:1]), repeat=3)
        all_viewers = timed(lambda: lighting.summaries(engine, viewers), repeat=3)
    print(f"composition {len(viewers)} viewers: one {one_viewer:.2f} ms, all {all_viewers:.2f} ms, "
          f"marginal {(all_viewers - one_viewer) / (len(viewers) - 1):.3f} ms a viewer")
    assert all_viewers < 20, all_viewers           # spec §6.3 target 2 ms; see the report


def test_the_payload_of_the_largest_map_fits_one_kilobyte(tmp_path):
    engine = big_map(tmp_path, lit_fortress())
    row = lighting.summary(engine, engine.state.actors[OWNER])
    print(f"payload: {len(row['cells'])} base64 chars for {engine.grid.width * engine.grid.height} squares")
    assert len(row["cells"]) <= 1024                # spec §6.3: 2,400 cells in one kilobyte
