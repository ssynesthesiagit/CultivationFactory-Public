"""A tide Court alone is not a Basin: committed table actions and cold replay."""
import pytest

from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, turn, reload
from tests.test_auto134_water_pull import PULL, CHOICE, FOE_START, prepare, soak_then

COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
BASIN = 'WATER_BASE_SHAPE_CURRENT'


@pytest.mark.parametrize('with_basin', [False, True], ids=['court-only', 'court-and-basin'])
def test_pull_prone_requires_actual_basin_even_inside_court(tmp_path, with_basin):
    combat, table, mid = fixture(tmp_path, [PULL, COURT], foe_position=FOE_START,
                                 bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Court of the Endless Tide').candidate_id)
    if with_basin:
        settle(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', at=(4, 3)).candidate_id)
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    # Prove the committed geometry is present after a cold reload, before the hit.
    before = reload(tmp_path, mid)

    def owned_zones(engine, source):
        return [z for z in engine.state.zones.values()
                if z.active and z.owner_id == OWNER
                and engine.action_catalog[z.source_definition_id].parameters['typed']['source'] == source]

    courts = owned_zones(before, COURT)
    assert courts
    assert any((p.x, p.y) == (4, 3) for z in courts for p in z.affected_cells)
    assert bool(owned_zones(before, BASIN)) is with_basin
    soak_then(table, combat, mid)
    settle(table, mid, candidate(combat, mid, 'Water Lash + Pull of the River', target=FOE).candidate_id,
           {CHOICE: 'cell:4,3'})
    after = reload(tmp_path, mid)
    assert (after.state.actors[FOE].position.x, after.state.actors[FOE].position.y) == (4, 3)
    saves = [e for e in after.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE]
    assert len(saves) == int(with_basin)
    assert any(c.condition_id == 'condition:typed.prone'
               for c in after.state.actors[FOE].conditions.values()) is with_basin
