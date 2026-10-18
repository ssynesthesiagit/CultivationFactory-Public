"""Consecrated zone protection follows the engine's area membership, not the anchor cell.

A Large creature whose anchor sits outside a Consecrated Boundary but whose footprint overlaps it is
inside the zone. The Consecrated check must read that through the shared spatial_areas query used by
zones, so the protection applies through the real table, execute_intent, and a cold reload.
"""
from combat import spatial_areas
from combat.ext import devil_heart_second_furnace as dhsf
from tests import r1i_service_support as s
from tests.cw2_service_support import add_action
from tests.test_devil_qi_augment_service import AUGMENT, cold, commit_first_choice

BOUNDARY = "tianxia.talent.radiance.consecrated_boundary"


class _Ctx:
    def __init__(self, engine):
        self.engine = engine


def _grow_foe(bundles):
    add_action(bundles[1], "Test grow", [{"type": "size_change", "size": "Large", "duration": "until_removed"}],
               target="SELF")


def _cast_boundary_with_large_foe(tmp_path, foe_x, foe_y):
    combat, table, mid, send, commit = s.fixture(tmp_path, [AUGMENT, BOUNDARY], wide=True,
                                                bundle_transform=_grow_foe,
                                                positions={s.OWNER: {"x": 3, "y": 6}, s.FOE: {"x": foe_x, "y": foe_y},
                                                           s.SECOND: {"x": 5, "y": 6}})
    commit(table.state(mid)["menu"]["end_turn"])
    commit(s.candidate(table, mid, "Test grow", target=s.FOE))
    while table.state(mid)["menu"]["actor_id"] != s.OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit_first_choice(table, mid, s.candidate(table, mid, "Consecrated Boundary"))
    return combat, mid


def test_large_creature_partly_inside_boundary_is_consecrated(tmp_path):
    combat, mid = _cast_boundary_with_large_foe(tmp_path, 2, 2)
    engine = cold(combat, tmp_path, mid)
    foe = engine.state.actors[s.FOE]
    zone = next(z for z in engine.state.zones.values() if z.active)
    assert foe.transformed_size_category == "Large"
    assert (foe.position.x, foe.position.y) not in {(c.x, c.y) for c in zone.affected_cells}, \
        "the anchor is outside the zone's recorded cells"
    assert spatial_areas.zone_contains(engine, foe, zone), "its footprint overlaps the sphere"
    assert dhsf._consecrated_source_cl(_Ctx(engine), foe) > 0, \
        "the Consecrated check must see a zone the creature's footprint is inside"


def test_creature_outside_boundary_is_not_consecrated(tmp_path):
    combat, mid = _cast_boundary_with_large_foe(tmp_path, 20, 4)
    engine = cold(combat, tmp_path, mid)
    foe = engine.state.actors[s.FOE]
    assert dhsf._consecrated_source_cl(_Ctx(engine), foe) == 0
