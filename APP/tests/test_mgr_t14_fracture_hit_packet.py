"""Actual Ice mark and Starbolt hit retain attached bonus attack provenance."""
import pytest

from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload
from tests.mgr_t14_acquisition_support import acquire_sphere
from tests.test_mgr_t14_fracture_service import BASE, RESPONSE, QUIET, prepare
from combat.ext.ice_fracture import marked
from tests.test_auto116_ice import reach
from tests.test_a2_gravity import use


@pytest.mark.parametrize('critical,seed,cl,sides', [
    (False, 'ICE-BRITTLE-NORMAL-7', 1, 4), (True, 'ICE-BRITTLE-CRITICAL-21', 1, 4),
    (False, 'ICE-BRITTLE-CL11-NORMAL-58', 11, 6), (True, 'ICE-BRITTLE-CL11-CRITICAL-2', 11, 6)])
@pytest.mark.parametrize('target', [ALLY, FOE])
def test_native_brittle_opening_is_extra_damage_of_the_actual_hit(tmp_path, critical, seed, cl, sides, target):
    def acquire(doc, actor_id):
        if actor_id == OWNER:
            acquire_sphere(doc, actor_id, 'tianxia.sphere.ice')
            acquire_sphere(doc, actor_id, 'tianxia.sphere.stars')
    combat, table, mid = fixture(tmp_path, [BASE], cl=cl, seed=seed, named=True,
        sheet_edit=acquire, bundle_transform=prepare, primary='Body')
    settle(table, mid, candidate(combat, mid, 'Shard Needle', target=target).candidate_id, QUIET)
    assert marked(reload(tmp_path, mid).state.actors[target], OWNER)
    use(combat, table, mid, 'End Turn')
    reach(table, mid, OWNER, QUIET)
    before = reload(tmp_path, mid)
    prompts = settle(table, mid, candidate(combat, mid, 'Starbolt', target=target).candidate_id,
        {RESPONSE: 'brittle', 'choice:needle.brittle_type': 'PIERCING'})
    after = reload(tmp_path, mid)
    attack = next(e for e in after.events[len(before.events):] if e.event_type == 'ATTACK_ROLLED')
    assert (attack.payload['natural_result'] == 20) is critical
    bonus = next(e for e in after.events[len(before.events):] if e.event_type == 'DAMAGE_ROLLED'
        and e.payload.get('display_source_id') == BASE)
    assert bool(bonus.payload.get('critical')) is critical
    assert len(bonus.payload['dice']) == (2 if critical else 1)
    assert bonus.payload['expression'].startswith(f'{2 if critical else 1}d{sides}+')
    receipt = next(e for e in after.events[len(before.events):]
        if e.payload.get('checkpoint') == 'BRITTLE_OPENING_HIT')
    assert receipt.payload['attack_roll_id'] == attack.payload['roll_id']
    assert any(p['context']['reaction_source_id'] == RESPONSE for p in prompts)
