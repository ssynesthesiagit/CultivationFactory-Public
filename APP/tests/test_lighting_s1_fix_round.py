"""Regressions for the LIGHTS1F2RSC Sol review of lighting S1: findings 1-3.

Each test runs on a real saved map through the fight fixture and a cold reload, and asserts the rule that failed.
Spec: docs/specs/LIGHTING_SPEC.md §2.4.3, §5.4, §7.1.
"""
from combat import lighting
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document, payload
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


# Finding 2: a centreline-mode wall stops emitted light exactly as it stops sight.
def test_finding2_a_centreline_wall_stops_the_light(tmp_path):
    wall = {"shape": "line", "points": [[4, 3], [4, 11]], "blocks": "sight", "occluder": "centerline"}
    document = map_document(20, 14, ambient=NIGHT, lights=[light(2, 4)], walls=[wall])
    combat, table, mid = fight(tmp_path, document, senses=[],
                               positions={OWNER: {"x": 2, "y": 12}, ALLY: {"x": 3, "y": 12}, FOE: {"x": 4, "y": 12}})
    engine = reload(tmp_path, mid)
    # The torch at (2,4) is on the near side of the centreline at x=4; (6,4) is beyond it.
    assert lighting.base(engine, 3, 4) != lighting.DARK
    assert lighting.base(engine, 6, 4) == lighting.DARK
