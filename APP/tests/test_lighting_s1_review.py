"""Regressions for the Sol review of lighting S1 (LIGHTS1F1RSC), findings 1-4.

Each test runs on a real saved map through the fight fixture and a cold reload, and asserts the rule that failed.
Spec: docs/specs/LIGHTING_SPEC.md §2.6, §2.8, §4.1, §5.3 row 8, §7.1.
"""
import base64

from combat import lighting, zones
from combat.footprints import native_actor_footprint
from combat.typed_executor import check_mode
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload

NIGHT = ambient_light("night")
DAY = ambient_light("day")
BLINDSIGHT = [{"sense": "blindsight", "range_ft": 30}]
DARKVISION = [{"sense": "darkvision", "range_ft": 15}]
SPREAD = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 4, "y": 2}}


# Finding 1: attack modes respect the senses that see through darkness, one direction at a time.
def test_finding1_blindsight_attacker_has_advantage_on_an_unseen_foe_in_the_dark(tmp_path):
    combat, table, mid = fight(tmp_path, map_document(20, 12, ambient=NIGHT), senses=BLINDSIGHT, positions=SPREAD)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert lighting.heavily_obscured(engine, foe, owner.position)     # the foe cannot see the attacker
    assert zones.attack_mode(engine, owner, foe) == "ADVANTAGE"       # not NORMAL: the two Dark answers no longer cancel


def test_finding1_an_asymmetric_target_blindsight_gives_its_own_direction_only(tmp_path):
    # Attacker: no special sense, stands in the Dark. Target (ALLY): Blindsight 30 ft, so it sees the attacker but the
    # attacker cannot see it. Only the attacker's direction is Disadvantage; the target's sense does not cancel it.
    combat, table, mid = fight(tmp_path, map_document(20, 12, ambient=NIGHT), senses=[], ally_senses=BLINDSIGHT,
                               positions=SPREAD)
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    assert lighting.heavily_obscured(engine, owner, ally.position)
    assert zones.attack_mode(engine, owner, ally) == "DISADVANTAGE"


# Finding 2: an ordinary sight Perception check that names no hazard (Analyze's roll) takes the Dim Light Disadvantage.
def test_finding2_analyze_style_perception_check_in_dim_light_has_disadvantage(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(2, 2, bright_ft=0, dim_ft=20)])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=SPREAD)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert lighting.perception_mode(engine, owner) == "DISADVANTAGE"
    # Analyze's Perception roll (combat/ext/mind_hidden_eye.analyze_roll): against the target, no hazards.
    assert check_mode(owner, "WIS", "Perception", engine=engine, against_creature=foe) == "DISADVANTAGE"


def test_finding2_the_same_check_in_bright_light_is_normal(tmp_path):
    combat, table, mid = fight(tmp_path, map_document(20, 12, ambient=DAY), senses=[], positions=SPREAD)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert check_mode(owner, "WIS", "Perception", engine=engine, against_creature=foe) == "NORMAL"


# Finding 3: a valid large light builds its field and payload (the bright run is as long as the run, not 64).
def test_finding3_a_light_whose_bright_run_is_longer_than_64_squares_builds(tmp_path):
    document = map_document(80, 6, ambient=NIGHT, lights=[light(0, 3, bright_ft=400, dim_ft=400)])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=SPREAD)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert lighting.seen_level(engine, owner, (79, 3)) == lighting.BRIGHT
    assert len(lighting.seen_field(engine, owner)) == 80 * 6
    assert lighting.summary(engine, owner)["cells"]


# Finding 4: a Large viewer's Darkvision field matches seen_level square for square, in the payload too.
def test_finding4_a_large_viewer_payload_matches_seen_level_square_for_square(tmp_path):
    positions = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 8, "y": 8}, FOE: {"x": 10, "y": 10}}
    combat, table, mid = fight(tmp_path, map_document(20, 12, ambient=NIGHT), senses=DARKVISION, positions=positions)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    engine.actor_footprints[owner.entity_id] = native_actor_footprint(owner.entity_id, "Large")
    assert len(engine._actor_cells(owner)) == 4
    width, height = int(engine.grid.width), int(engine.grid.height)
    expected = bytes(lighting.seen_level(engine, owner, (x, y)) for y in range(height) for x in range(width))
    assert expected[2 * width + 6] == lighting.DIM        # (6,2): 15 ft from the body's (3,2) square, not the anchor
    assert base64.b64decode(lighting.summary(engine, owner)["cells"]) == lighting._pack(expected)
