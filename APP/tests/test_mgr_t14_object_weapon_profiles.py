"""Acquired Ice -> native kit profiles -> actual object attack -> cold replay."""
import pytest

from combat.tabletop import TabletopMapStore, to_battlefield
from combat.weapon_delivery import weapon_identity
from combat.item_uses import possessions
from tests.worker2_support import OWNER, fixture, settle, reload
from tests.mgr_t14_acquisition_support import acquire_declared
from tests.test_mgr_t14_fracture_service import BASE, QUIET


@pytest.mark.parametrize('owns', [False, True])
def test_native_physical_profiles_preserve_all_items_and_default_inert_catalog(tmp_path, owns):
    saved = TabletopMapStore(tmp_path).save({'display_name': 'Physical profile courtyard',
        'width_squares': 20, 'height_squares': 18, 'objects': [
            {'kind': 'custom', 'name': 'Practice timber', 'x': 3, 'y': 7,
             'material': 'wood', 'hp': 1000, 'blocks': False}]})
    kit = {'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.weapon.dao', 'quantity': 1},
        {'item_id': 'tianxia.mortal.weapon.fu', 'quantity': 1}]}}
    combat, table, mid = fixture(tmp_path, [BASE] if owns else [], cl=1,
        owner_kit=kit, battlefield=to_battlefield(saved),
        sheet_edit=acquire_declared('tianxia.sphere.ice') if owns else None)
    before = reload(tmp_path, mid)
    physical = [a for a in before.action_catalog.values() if a.owner_id == OWNER
        and '.weapon.' in a.source_definition_id and not a.parameters.get('object_attack')
        and str(getattr(a.economy, 'value', a.economy)) == 'ACTION'
        and any(e.get('type') == 'attack' for e in a.parameters.get('typed', {}).get('effects', []))]
    siblings = [a for a in before.action_catalog.values() if a.owner_id == OWNER
        and a.parameters.get('object_attack')]
    if not owns:
        assert all(a.parameters.get('player_only') for a in siblings)
        assert not any(a.parameters['typed'].get('weapon_source_id') for a in siblings)
        return
    assert len(physical) >= 3  # Dao, Fu and its printed thrown mode.
    for original in physical:
        identity = weapon_identity(before, original.source_definition_id,
            original.parameters['typed'], original.parameters)
        matches = [a for a in siblings if a.parameters['typed'].get('weapon_source_id') == identity
            and a.range_ft == original.range_ft
            and a.parameters['typed']['object_weapon'] == original.parameters['typed']['weapon']]
        assert matches, original.source_definition_id
        assert all(not a.parameters.get('player_only') for a in matches)
        assert any(a.costs == original.costs for a in matches)
    dao = next(item for item in possessions(before, before.state.actors[OWNER])
        if str(item.get('weapon_action', '')).endswith('.weapon.dao'))
    sibling = next(a for a in siblings
        if a.parameters['typed'].get('weapon_source_id') == dao['weapon_action'])
    use = next(c for c in before.legal_candidates() if c.source_definition_id == sibling.source_definition_id
        and c.target_ids == ('object:map.1',))
    settle(table, mid, use.candidate_id, QUIET)
    after = reload(tmp_path, mid)
    attack = next(e for e in after.events[len(before.events):] if e.event_type == 'ATTACK_ROLLED')
    assert attack.source_definition_id == sibling.source_definition_id
    assert after.state.actors[OWNER].action_available is False
    assert after.state.objects['object:map.1'].current_hp < 1000 or attack.payload['natural_result'] == 1
