"""Sources through sight-clear rays: docs/specs/LIGHTING_SPEC.md §4.1 step 2, §4.2 E6.

A source lights only the squares it can see, using combat/sight_lines.py the way the rest of the engine does, so a wall
that stops a sight line stops a torch and a wall that stops nothing stops nothing.
"""
from combat import lighting
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload

NIGHT = ambient_light("night")
OUT_OF_THE_WAY = {OWNER: {"x": 2, "y": 12}, ALLY: {"x": 3, "y": 12}, FOE: {"x": 4, "y": 12}}
WALL = {"shape": "line", "points": [[4, 3], [4, 11]], "blocks": "sight"}


def levels(engine, cells):
    return [lighting.base(engine, x, y) for x, y in cells]


def test_worked_example_e6_a_wall_stops_the_light(tmp_path):
    document = map_document(20, 14, ambient=NIGHT, lights=[light(6, 7)], walls=[WALL])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=OUT_OF_THE_WAY)
    engine = reload(tmp_path, mid)
    assert levels(engine, [(7, 7), (5, 7)]) == [lighting.BRIGHT, lighting.BRIGHT]
    assert levels(engine, [(3, 7), (3, 6), (3, 8)]) == [lighting.DARK] * 3
    # The engine's own occluders are the ones doing it: one sight source, three opaque squares.
    sources = getattr(engine.grid, "sight_line_sources", ())
    assert len(sources) == 1


def test_a_wall_with_no_height_stops_nothing(tmp_path):
    wall = dict(WALL, height_ft=0)
    document = map_document(20, 14, ambient=NIGHT, lights=[light(6, 7)], walls=[wall])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=OUT_OF_THE_WAY)
    engine = reload(tmp_path, mid)
    # Same squares, same source, no occluder: the light crosses the mirrored squares freely.
    assert levels(engine, [(3, 7), (3, 6)]) != [lighting.DARK] * 2


def test_light_passes_a_gap_but_not_its_edges(tmp_path):
    document = map_document(20, 14, ambient=NIGHT, lights=[light(7, 7)],
                            walls=[{"shape": "line", "points": [[4, 2], [4, 6]], "blocks": "sight"},
                                   {"shape": "line", "points": [[4, 8], [4, 12]], "blocks": "sight"}])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=OUT_OF_THE_WAY)
    engine = reload(tmp_path, mid)
    assert lighting.base(engine, 3, 7) != lighting.DARK       # through the one-square gap
    assert levels(engine, [(3, 5), (3, 9), (3, 4)]) == [lighting.DARK] * 3


def test_a_source_lights_its_own_square_even_when_walls_close_it_in(tmp_path):
    # A torch in a sealed one-square room: the square it stands on is lit (the source is there), the rays are not.
    document = map_document(20, 14, ambient=NIGHT, lights=[light(6, 7)],
                            walls=[{"shape": "rect", "points": [[5, 6], [7, 8]], "blocks": "sight", "filled": False,
                                    "height_ft": 20}])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=OUT_OF_THE_WAY)
    engine = reload(tmp_path, mid)
    assert lighting.base(engine, 6, 7) == lighting.BRIGHT
    assert levels(engine, [(5, 7), (7, 7), (6, 6), (9, 7)]) == [lighting.DARK] * 4
