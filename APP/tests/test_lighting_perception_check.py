"""What a Dim Light does to a sight check: docs/specs/LIGHTING_SPEC.md §2.6, §5.3 rows 8-9.

Two hooks, both inert on any map without light data: the Search/Sweep seam (stealth.search_modes) and the ability-check
hazard seam (typed_executor check_modes). Dim Light is the only level that changes a check; Bright and Dark leave every
check exactly as its print says, and no other skill is touched.
"""
from combat import lighting, stealth, typed_executor
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload

NIGHT = ambient_light("night")


def engine_at(tmp_path, position):
    document = map_document(24, 12, ambient=NIGHT, lights=[light(6, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[],
                               positions={OWNER: position, ALLY: {"x": 2, "y": 10}, FOE: {"x": 3, "y": 10}})
    return reload(tmp_path, mid), position


def test_a_search_in_dim_light_is_at_disadvantage(tmp_path):
    engine, position = engine_at(tmp_path, {"x": 11, "y": 6})
    owner = engine.state.actors[OWNER]
    assert lighting.seen_level(engine, owner, owner.position) == lighting.DIM
    assert stealth.search_modes(engine, owner) >= {"DISADVANTAGE"}
    assert stealth.resolved_search_mode(engine, owner) == "DISADVANTAGE"


def test_a_search_in_bright_or_dark_light_is_unchanged(tmp_path):
    bright, _ = engine_at(tmp_path, {"x": 7, "y": 6})
    assert lighting.seen_level(bright, bright.state.actors[OWNER], bright.state.actors[OWNER].position) == lighting.BRIGHT
    assert stealth.resolved_search_mode(bright, bright.state.actors[OWNER]) == "NORMAL"


def test_a_wisdom_perception_check_names_the_hazard_it_adds(tmp_path):
    engine, _ = engine_at(tmp_path, {"x": 11, "y": 6})
    owner = engine.state.actors[OWNER]
    assert typed_executor.check_mode(owner, "WIS", "Perception", engine=engine, against_creature=None,
                                     hazards=("dim_light",)) == "DISADVANTAGE"
    assert typed_executor.check_mode(owner, "INT", "Investigation", engine=engine, against_creature=None,
                                     hazards=("dim_light",)) == "NORMAL"


def test_a_check_the_light_does_not_touch_is_unchanged(tmp_path):
    engine, _ = engine_at(tmp_path, {"x": 11, "y": 6})
    owner = engine.state.actors[OWNER]
    assert lighting.perception_mode(engine, owner) == "DISADVANTAGE"
    assert typed_executor.check_mode(owner, "STR", "Athletics", engine=engine, against_creature=None,
                                     hazards=()) == "NORMAL"
