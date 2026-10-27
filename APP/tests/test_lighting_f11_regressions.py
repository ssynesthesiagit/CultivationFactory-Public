"""Regressions for F11: light obeys the physical wall boundary, including at ray endpoints."""
from combat import lighting
from tests.lighting_support import FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload


def test_light_does_not_paint_the_occupied_cell_at_a_wall_endpoint(tmp_path):
    wall = {"shape": "rect", "points": [[5, 6], [7, 8]], "blocks": "sight", "filled": False,
            "height_ft": 20}
    document = map_document(20, 14, ambient=ambient_light("night"), lights=[light(6, 7)], walls=[wall])
    positions = {OWNER: {"x": 2, "y": 12}, FOE: {"x": 4, "y": 12}}
    _, _, match_id = fight(tmp_path, document, senses=[], positions=positions)
    engine = reload(tmp_path, match_id)

    assert lighting.base(engine, 6, 7) == lighting.BRIGHT
    assert [lighting.base(engine, x, y) for x, y in ((5, 7), (7, 7), (6, 6), (9, 7))] == [
        lighting.DARK
    ] * 4
