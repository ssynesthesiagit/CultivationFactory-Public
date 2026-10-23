"""What a light level does to sight: §2.5, §2.8, §4.2 E7, E8, E11.

The light model never answers "can this creature see that one" -- combat/senses.py does, and it asks the model for one
level. These tests keep the two layers apart: the level is the model's, the gate, the Darkvision step and the Pure
Darkness clipping are the sense system's, unchanged.
"""
from combat import lighting, senses
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import candidate, reload, settle, turn

NIGHT = ambient_light("night")
DARKVISION = [{"sense": "darkvision", "range_ft": 60}]
PURE = ["TAL_DARK_PURE_DARKNESS"]


def test_darkvision_raises_the_level_one_step_not_two(tmp_path):
    document = map_document(24, 12, ambient=NIGHT, lights=[light(6, 7, bright_ft=0, dim_ft=20)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION,
                               positions={OWNER: {"x": 2, "y": 7}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 2}})
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    outside = lighting._position_of((12, 7))          # 30 ft from the dim light: Dark for everyone
    edge = lighting._position_of((9, 7))              # 15 ft: Dim
    assert lighting.seen_level(engine, owner, outside) == lighting.DARK
    assert lighting.seen_level(engine, ally, outside) == lighting.DIM
    assert lighting.seen_level(engine, owner, edge) == lighting.DIM
    assert lighting.seen_level(engine, ally, edge) == lighting.BRIGHT


def test_darkvision_past_its_range_leaves_the_square_dark(tmp_path):
    document = map_document(24, 12, ambient=NIGHT)
    combat, table, mid = fight(tmp_path, document, senses=[],
                               ally_senses=[{"sense": "darkvision", "range_ft": 10}],
                               positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 4, "y": 2}})
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert lighting.seen_level(engine, ally, lighting._position_of((5, 2))) == lighting.DIM      # 10 ft, in range
    assert lighting.seen_level(engine, ally, lighting._position_of((6, 2))) == lighting.DARK     # 15 ft, out of it


def test_a_creature_without_a_sense_into_darkness_does_not_perceive(tmp_path):
    document = map_document(20, 12, ambient=NIGHT)
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION,
                               positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}})
    engine = reload(tmp_path, mid)
    owner, ally, foe = (engine.state.actors[i] for i in (OWNER, ALLY, FOE))
    assert lighting.seen_level(engine, owner, foe.position) == lighting.DARK
    assert senses.perceives(engine, owner, foe) is False
    assert senses.perceives(engine, ally, foe) is True


def test_worked_example_e11_pure_darkness_clips_every_sense(tmp_path):
    # The ally holds Pure Darkness and shapes it on its own turn, the way the table offers it (a2r13 darken()); the
    # owner is the viewer. The Darkness is placed on the foe's square, one step past the owner's reach to the ally.
    document = map_document(24, 14, ambient=NIGHT)
    combat, table, mid = fight(tmp_path, document, senses=DARKVISION, ally_talents=PURE,
                               ally_senses=[{"sense": "blindsight", "range_ft": 30}],
                               positions={OWNER: {"x": 12, "y": 6}, ALLY: {"x": 14, "y": 6}, FOE: {"x": 2, "y": 2}})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, "Shape Darkness: Pure Darkness").candidate_id)
    settle(table, mid, candidate(combat, mid, "Darkness", at=(10, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    inside, five_feet_away, thirty_feet_away = (lighting._position_of(cell) for cell in ((11, 6), (12, 6), (14, 6)))
    assert lighting._darkvision(engine, owner, inside) == 5
    assert lighting.seen_level(engine, owner, five_feet_away) == lighting.DIM
    assert lighting.seen_level(engine, owner, thirty_feet_away) == lighting.DARK
    assert senses.reach(engine, ally, "blindsight", senses.cell_probe(inside)) == 15   # half of 30
    assert senses.reach(engine, ally, "blindsight", senses.cell_probe(lighting._position_of((2, 2)))) == 30