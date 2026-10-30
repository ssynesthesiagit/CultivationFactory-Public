"""Light's share of movement and of the gates that read the darkness: docs/specs/LIGHTING_SPEC.md §5.2 rows 1-2.

The teleport gates and the teleport destination filter both ask motion.obscured / motion.obscured_at, so those two
answers are what they see: Dim Light counts as lightly obscured, Bright does not, and Dark does.
"""
from combat import lighting, motion
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload

NIGHT = ambient_light("night")


def field(tmp_path, positions):
    document = map_document(24, 12, ambient=NIGHT, lights=[light(6, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=positions)
    return reload(tmp_path, mid)


def test_dim_light_is_lightly_obscured_and_bright_is_not(tmp_path):
    engine = field(tmp_path, {OWNER: {"x": 7, "y": 6}, ALLY: {"x": 11, "y": 6}, FOE: {"x": 2, "y": 2}})
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    assert lighting.base(engine, 7, 6) == lighting.BRIGHT      # 5 ft from the torch
    assert lighting.base(engine, 11, 6) == lighting.DIM        # 25 ft from it
    assert motion.obscured(engine, owner) is False
    assert motion.obscured(engine, ally) is True


def test_darkness_obscures_the_square_and_the_creature_in_it(tmp_path):
    engine = field(tmp_path, {OWNER: {"x": 2, "y": 11}, ALLY: {"x": 3, "y": 11}, FOE: {"x": 18, "y": 6}})
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert lighting.base(engine, 18, 6) == lighting.DARK
    assert motion.obscured(engine, owner) is True
    assert motion.obscured(engine, foe) is True
    assert motion.obscured_at(engine, lighting._position_of((18, 6))) is True
    assert motion.obscured_at(engine, lighting._position_of((6, 6))) is False
