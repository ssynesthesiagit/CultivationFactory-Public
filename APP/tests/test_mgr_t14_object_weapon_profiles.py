"""Acquired Ice -> native kit profiles -> actual object attack -> cold replay."""
import pytest

from combat.tabletop import TabletopMapStore, to_battlefield
from combat.weapon_delivery import weapon_identity
from combat.item_use_checkpoint import possessions
from tests.worker2_support import OWNER, FOE, fixture, settle, reload, turn
from tests.mgr_t14_acquisition_support import acquire_declared
from tests.test_mgr_t14_fracture_service import BASE, QUIET


@pytest.mark.parametrize('owns', [False, True])
def test_native_physical_profiles_preserve_all_items_and_default_inert_catalog(tmp_path, owns):
    saved = TabletopMapStore(tmp_path).save({'display_name': 'Physical profile courtyard',
        'width_squares': 20, 'height_squares': 18, 'objects': [
            {'kind': 'custom', 'name': 'Practice timber', 'x': 3, 'y': 7,
             'material': 'wood', 'hp': 999, 'blocks': False}]})
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
    base_profiles = [a for a in siblings if not a.source_definition_id.split('.object_attack.', 1)[-1].count('+')]
    # Profiles stay distinct by weapon identity, but same-group profiles share the
    # generic label; duplicate rows of one group/source collapse to the best row.
    assert len({a.parameters['typed']['weapon_source_id'] for a in base_profiles}) >= 2
    assert {a.display_name for a in base_profiles} == {'Attack an object'}
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
    assert attack.payload['natural_result'] != 1
    assert after.state.objects['object:map.1'].current_hp < 999
    stow = next(c for c in after.legal_candidates()
        if c.display_name.startswith('Stow ') and 'Dao' in c.display_name)
    settle(table, mid, stow.candidate_id)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    stowed = reload(tmp_path, mid)
    assert stowed.state.actors[OWNER].action_available
    offered = [stowed.action_catalog[c.source_definition_id] for c in stowed.legal_candidates()
        if c.target_ids == ('object:map.1',)]
    assert not any(a.parameters.get('typed', {}).get('weapon_source_id') == dao['weapon_action'] for a in offered)
    assert any(str(a.parameters.get('typed', {}).get('weapon_source_id', '')).endswith('.weapon.fu') for a in offered)


def test_profiled_object_attack_rows_dedupe_same_group_and_source(monkeypatch, tmp_path):
    from combat.ext import objects

    saved = TabletopMapStore(tmp_path).save({'display_name': 'Profile dedupe yard',
        'width_squares': 20, 'height_squares': 18, 'objects': [
            {'kind': 'custom', 'name': 'Practice timber', 'x': 3, 'y': 7, 'hp': 999}]})
    kit = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao', 'quantity': 1}]}}
    _combat, _table, mid = fixture(tmp_path, [BASE], cl=1, owner_kit=kit,
        battlefield=to_battlefield(saved), sheet_edit=acquire_declared('tianxia.sphere.ice'))
    engine = reload(tmp_path, mid)
    source_rows = [a for a in engine.action_catalog.values() if a.owner_id == OWNER
        and '.weapon.dao' in a.source_definition_id and not a.parameters.get('object_attack')
        and a.parameters.get('typed', {}).get('weapon')]
    assert source_rows
    original = source_rows[0]
    stronger = original.model_copy(update={
        'parameters': {**original.parameters,
            'typed': {**original.parameters['typed'],
                'weapon': {**original.parameters['typed']['weapon'], 'name': 'Synthetic stronger dao'}},
            'expected_damage': 999}})
    monkeypatch.setattr(objects, 'run', lambda name, *args: [True] if name == 'object_attack_profiles' else [])
    generated = objects.object_actions({'short': 'test', 'actor_id': OWNER,
        'actions': [original, stronger], 'passives': [], 'mods': {'STR': 0},
        'numbers': {}, 'pb': 2})
    assert generated is not None
    assert len(generated) == 1
    assert generated[0].parameters['typed']['object_weapon']['name'] == 'Synthetic stronger dao'
    assert generated[0].parameters['typed']['weapon_source_id'] == original.parameters['typed'].get('weapon_source_id', original.source_definition_id)
