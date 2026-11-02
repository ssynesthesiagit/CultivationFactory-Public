"""The table's light answer: docs/specs/LIGHTING_SPEC.md §4.2 E9, §7.1, §7.2 and §8.

One viewer, one block, quantised to two bits a square and only for squares that are not the floor level; a map that
declares no light sends nothing at all, which is what every saved fight already expects.
"""
import base64

from combat import lighting
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document, payload
from tests.worker2_support import reload

NIGHT = ambient_light("night")
DARKVISION = [{"sense": "darkvision", "range_ft": 60}]


def test_the_payload_is_one_short_block_per_viewer(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION,
                               positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}})
    block = payload(table, mid, OWNER)
    assert block["schema"] == lighting.SCHEMA == "TianxiaTabletopLight.v1"
    assert block["by"] == OWNER
    assert block["ambient"] == {"time_of_day": "night", "level": lighting.DARK}
    assert len(block["cells"]) <= 1024 and len(base64.b64decode(block["cells"])) == 60   # 20 x 12 squares, 2 bits each
    assert block["own"] == []


def test_two_viewers_get_different_payloads_on_the_same_pass(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION,
                               positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}})
    assert payload(table, mid, OWNER)["cells"] != payload(table, mid, ALLY)["cells"]
    assert payload(table, mid, FOE)["cells"] == payload(table, mid, OWNER)["cells"]   # both without Darkvision


def test_a_carried_light_is_named_for_its_bearer(tmp_path):
    document = map_document(20, 12, ambient=NIGHT)
    combat, table, mid = fight(tmp_path, document, senses=[],
                               positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}})
    engine = reload(tmp_path, mid)
    engine._apply_condition(engine.state.actors[FOE], lighting.LIGHT, "test:lighting.ember", OWNER, expires_on=None,
                            data={"name": "Revealing Ember", "bright_ft": 0, "dim_ft": 5})
    # The table's block is versioned, and a condition applied outside a commit does not move the version, so ask the
    # model itself for the fresh answer (a real carried light is applied by a commit and lands in the payload).
    assert [row["name"] for row in lighting.summary(engine, engine.state.actors[FOE])["own"]] == ["Revealing Ember"]
    assert lighting.summary(engine, engine.state.actors[OWNER])["own"] == []


def test_the_payload_survives_a_cold_reload(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], positions={OWNER: {"x": 2, "y": 2},
                                                                        ALLY: {"x": 3, "y": 2},
                                                                        FOE: {"x": 9, "y": 2}})
    before = payload(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert payload(table, mid, OWNER) == before
    assert lighting.summary(engine, engine.state.actors[OWNER]) == before


def test_a_map_without_light_data_sends_no_block(tmp_path):
    combat, table, mid = fight(tmp_path, map_document(12, 10), senses=[],
                               positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 4, "y": 2}})
    assert table.state(mid, fog=True)["light"] == {}
