"""Printed cylinder height also bounds Air's ordinary projectile defenses."""
import pytest

from tests.cw2_service_support import seal
from tests.test_a2_air import prepare, area_candidate, CYCLONE
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn, sealed_native_attack


@pytest.mark.parametrize('height,mode', [(3, 'DISADVANTAGE'), (10, 'NORMAL')])
def test_cyclone_projectile_defense_uses_the_recorded_volume(tmp_path, height, mode):
    def setup(bundles):
        prepare(bundles)
        for bundle in bundles[1:]:
            bundle['actor_template']['fly_speed_ft'] = 5
            bundle['actor_template']['speed_ft'] = 5
            seal(bundle)
        source = sealed_native_attack(bundles[1], 'Test arrow', damage_type='PIERCING', count=1, sides=4, modifier=0)
        action = next(a for a in bundles[1]['action_catalog'] if a['source_definition_id'] == source)
        action['parameters']['typed'] = {'weapon': {'properties': 'Ammunition'}}
        seal(bundles[1])
    combat, table, mid = fixture(tmp_path, [CYCLONE], owner_dc=-100,
        bundle_transform=setup, seed=f'A2-CYLINDER-ARROW-{height}', positions={
            OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 1, 'y': 6, 'z': height},
            FOE: {'x': 6, 'y': 6, 'z': height}})
    settle(table, mid, area_candidate(combat, mid, 'Cyclone Prison').candidate_id)
    engine = reload(tmp_path, mid)
    assert any(z.trigger_profile.get('height_ft') == 40 for z in engine.state.zones.values())
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Test arrow', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    shot = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY)
    assert shot.payload['mode'] == mode
