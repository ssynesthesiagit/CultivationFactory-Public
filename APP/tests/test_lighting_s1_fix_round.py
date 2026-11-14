"""Regressions for the LIGHTS1F4RSC Sol review of lighting S1 (findings 1-3).

Each test runs on a real saved map through the fight fixture and a cold reload, and asserts the rule that failed.
Spec: docs/specs/LIGHTING_SPEC.md §2.4.3, §5.4, §7.1.
"""
from combat import lighting
from combat.gate2_runtime_models import Position
from combat.read_queries import read_frame
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document
from tests.worker2_support import reload

NIGHT = ambient_light("night")
DARKVISION = [{"sense": "darkvision", "range_ft": 15}]
SPREAD = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}}


# Finding 1: a light answer depends only on the viewers the request asks for, never on earlier requests.
def test_finding1_light_answer_does_not_depend_on_earlier_viewers(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION, positions=SPREAD)
    # First read asks every viewer, populating the per-version cache for the whole table.
    everyone = table.state(mid, fog=True)["light"]
    assert {OWNER, ALLY, FOE} <= set(everyone)
    # A later own view of the owner must carry only the owner's answer, not the cached answers for the others.
    own = table.state(mid, fog=True, fog_view="own", fog_actor_ids=(OWNER,))["light"]
    assert set(own) == {OWNER}
    assert own[OWNER] == everyone[OWNER]
    # Fog off at the same version must not hand back the cached viewers either.
    off = table.state(mid, fog=False)["light"]
    assert not ({ALLY, FOE} & set(off))


def test_finding1_own_view_matches_a_fresh_table_at_the_same_version(tmp_path):
    document = map_document(20, 12, ambient=NIGHT, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION, positions=SPREAD)
    table.state(mid, fog=True, fog_view="own", fog_actor_ids=(ALLY,))   # the ally's own view first
    warm = table.state(mid, fog=True, fog_view="own", fog_actor_ids=(OWNER,))["light"]
    cold_combat, cold_table, cold_mid = fight(tmp_path / "cold", document, senses=[], ally_senses=DARKVISION,
                                              positions=SPREAD)
    cold = cold_table.state(cold_mid, fog=True, fog_view="own", fog_actor_ids=(OWNER,))["light"]
    assert set(warm) == set(cold) == {OWNER}
    assert warm[OWNER]["cells"] == cold[OWNER]["cells"]
    assert warm[OWNER]["own"] == cold[OWNER]["own"]


# Finding 2: the answer for a square depends on its altitude, whatever order the squares are asked in.
def _altitude_answers(tmp_path, order):
    document = map_document(12, 8, ambient=NIGHT)
    combat, table, mid = fight(tmp_path, document, senses=[{"sense": "darkvision", "range_ft": 10}],
                               positions={OWNER: {"x": 2, "y": 2}, ALLY: {"x": 2, "y": 6}, FOE: {"x": 10, "y": 6}})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    squares = {"ground": Position(x=3, y=2, z=0), "air": Position(x=3, y=2, z=4)}   # 20 ft up
    answers = {}
    with read_frame(engine):   # one pass: the answers share the pass's cache
        for name in order:
            answers[name] = lighting.seen_level(engine, owner, squares[name])
    return answers


def test_finding2_altitude_is_part_of_the_light_answer_in_either_order(tmp_path):
    # Darkvision 10 ft: the square on the ground is in reach (Dim); the square 20 ft up is not (Dark).
    assert _altitude_answers(tmp_path / "ground_first", ("ground", "air")) == {"ground": lighting.DIM,
                                                                               "air": lighting.DARK}
    assert _altitude_answers(tmp_path / "air_first", ("air", "ground")) == {"ground": lighting.DIM,
                                                                            "air": lighting.DARK}


# Finding 3: a positive printed radius smaller than one grid square still lights its own square.
def test_finding3_a_one_foot_light_lights_its_own_square_bright(tmp_path):
    document = map_document(12, 8, ambient=NIGHT, lights=[light(2, 2, bright_ft=1, dim_ft=1)])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=SPREAD)
    engine = reload(tmp_path, mid)
    floor = lighting.ambient(engine)["level"]
    assert lighting.base(engine, 2, 2) == lighting.BRIGHT
    assert lighting.base(engine, 3, 2) == floor   # 5 ft away is beyond a 1 ft light


def test_finding3_a_dim_only_reach_under_one_square_still_lights_its_own_square_bright(tmp_path):
    document = map_document(12, 8, ambient=NIGHT, lights=[light(2, 2, bright_ft=1, dim_ft=5)])
    combat, table, mid = fight(tmp_path, document, senses=[], positions=SPREAD)
    engine = reload(tmp_path, mid)
    assert lighting.base(engine, 2, 2) == lighting.BRIGHT
    assert lighting.base(engine, 3, 2) == lighting.DIM   # the 5 ft dim ring is one whole square
