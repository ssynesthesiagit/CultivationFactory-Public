"""Real floating swords fall as one recoverable item across service continuation."""
import json
from fractions import Fraction

import pytest

from combat import acquisition_inventory as inventory
from combat.ext import ten_thousand_swords as swords
from combat.ext.acquisition_inventory import interaction_pool
from combat.tabletop_service import TabletopService
from combat.weapon_delivery import available_weapons, ready_weapons
from factory_authoring import owner_items
from factory_authoring.owner_items import OwnerItemStore
from tests import test_mgr_t14_sword_round11_table as support
from tests.worker2_support import reload, settle, turn

A, B = support.A, support.B


def assert_journey_item(state, owner, uid, location, holder, position):
    actor = state['actors'][owner]
    items = actor['recorded_inventory']
    assert set(items) == {uid}
    assert actor['bundle']['acquisition_inventory'] == items
    conditions = [json.loads(row) for row in actor['encounter_snapshot']['conditions'].values()]
    retained = [json.loads(row['data']['inventory']) for row in conditions
                if row['condition_id'] == inventory.CONDITION]
    assert retained == [items]
    item = items[uid]
    assert item['id'] == uid and item['owner'] == owner
    assert item['location'] == location and item['holder'] == holder
    assert item['position'] == position
    return item


@pytest.mark.parametrize('borrowed', [False, True], ids=['owned', 'borrowed'])
@pytest.mark.parametrize('expiry', ['travel', 'combat'])
@pytest.mark.parametrize('recovery', ['recorded', 'native'])
def test_floating_real_sword_expires_to_one_recoverable_item(tmp_path, monkeypatch, borrowed, expiry, recovery):
    owner = B if borrowed else A
    project = 'sword-lender' if borrowed else 'sword-owner'
    original = owner_items.make_item
    profile = {
        'source_rule': 'Synthetic real sword', 'authority': 'Synthetic item owner',
        'source_cl': 1, 'kind': 'weapon', 'weight_lb': 2, 'cube_ft': 1,
        'flags': {'prerequisites_met': 1}, 'properties': []}

    def profiled_sword(spec, library=None):
        # The profile belongs to the resolved stored record, not the creation spec:
        # make_item rebuilds weapon specs and does not retain arbitrary extra fields.
        item = original(spec, library)
        item['record']['runtime_profile'] = profile
        return item

    monkeypatch.setattr(owner_items, 'make_item', profiled_sword)
    cold, jid, uid, acquire = support.native(tmp_path, monkeypatch, cl=14, seeds=0,
                                            real_sword_owner=project)
    stored = OwnerItemStore(tmp_path / 'owner_items').items(project)
    assert len(stored) == 1 and stored[0]['item_uid'] == uid
    assert stored[0]['record']['runtime_profile'] == profile
    initial_items = cold().journey_state(jid)['actors'][owner]['bundle']['acquisition_inventory']
    assert set(initial_items) == {uid} and initial_items[uid]['profile']['source_rule'] == profile['source_rule']
    support._admission(cold, jid, uid)
    if borrowed:
        support._permission(cold, jid, uid)
    acquire(swords.SEED, {'slot': 0, 'form': 'real', 'damage_type': 'force',
                          'item_uid': uid, 'owner_id': owner, 'admission_scope': 'real-sword'})
    acquire(swords.TWIN, {'slot': 1, 'form': 'projected', 'damage_type': 'force'})
    before = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, before['revision'], {A: 'team:a', B: 'team:b'},
                                      maximum_rounds=2)['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    game = (cold(), table, mid)
    # The first legal destination is (0, 0), away from either holder.
    support.use(game, 'Manifest Twin Swords')
    initial = reload(tmp_path, mid)
    sword = swords.state(initial.state.actors[A])['swords'][0]
    position = swords.point(sword).model_dump(mode='json')
    assert sword['location'] == 'floating'
    item = inventory.read(initial.state.actors[owner])[uid]
    assert sword['weapon_action'] in item['weapon_actions']
    assert item['location'] == 'floating'
    decline = {'choice:needle.sword_array.offturn': None}
    for _ in range(12):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'], picks=decline)
    assert reload(tmp_path, mid).state.terminal_result is not None
    resumed = cold().journey_resume(jid, cold().journey_state(jid)['revision'],
        effect_resolutions={A: 'Other encounter effects ended.', B: 'Other encounter effects ended.'})
    remaining = Fraction(resumed['actors'][A]['source_states'][swords.FAMILY]['manifest_seconds']['0'])
    assert remaining > 12 and remaining.denominator == 1
    waited = cold().journey_act(jid, resumed['revision'], A, 'wait',
                                {'seconds': int(remaining) + 1 if expiry == 'travel' else int(remaining) - 12})
    assert waited == cold().journey_state(jid)
    if expiry == 'travel':
        assert_journey_item(waited, owner, uid, 'space', '', position)
        source = waited['actors'][A]['source_states'][swords.FAMILY]
        assert source['swords'][0]['location'] == 'fallen'
        assert not source['manifest_seconds']

    # Cold service, a new encounter, then actual table pickup by the item's owner.
    positions = {owner: position, B if owner == A else A: {'x': 3, 'y': 2}}
    mid = cold().journey_start_combat(jid, waited['revision'], {A: 'team:a', B: 'team:b'},
                                      positions=positions, maximum_rounds=30)['match_id']
    table = TabletopService(cold(), tmp_path)
    game = (cold(), table, mid)
    if expiry == 'combat':
        for _ in range(6):
            settle(table, mid, table.state(mid)['menu']['end_turn'], picks=decline)
    turn(table, mid, owner)
    engine = reload(tmp_path, mid)
    assert sum(c.condition_id == swords.STATE for c in engine.state.actors[A].conditions.values()) == 1
    sword = swords.state(engine.state.actors[A])['swords'][0]
    action = sword['weapon_action']
    assert sword['item_uid'] == uid and sword['location'] == 'fallen'
    assert 'manifest_condition' not in sword
    item = inventory.read(engine.state.actors[owner])[uid]
    assert item['location'] == 'space' and item['holder'] == '' and item['position'] == position
    assert sum(uid in inventory.read(actor) for actor in engine.state.actors.values()) == 1
    assert action not in ready_weapons(engine, engine.state.actors[owner])
    assert uid in interaction_pool(engine, engine.state.actors[owner], 'pickup')
    if borrowed:
        assert action not in available_weapons(engine, engine.state.actors[B])
        assert not any(row.parameters.get('requires_held_weapon') == action
                       for row in available_weapons(engine, engine.state.actors[A]).values())
        dropped = [c.data for c in engine.state.actors[B].conditions.values()
                   if c.data.get('disables_action') == action]
        assert dropped and all(not row.get('held_by') for row in dropped)
    pickup = ('Pick up a recorded item' if recovery == 'recorded'
              else engine.action_catalog[action + '.pickup'].display_name)
    support.use(game, pickup)
    engine = reload(tmp_path, mid)
    item = inventory.read(engine.state.actors[owner])[uid]
    assert item['id'] == uid and item['location'] == 'hand' and item['holder'] == owner
    assert 'position' not in item
    assert not interaction_pool(engine, engine.state.actors[owner], 'pickup')
    assert action in ready_weapons(engine, engine.state.actors[owner])
    bond = swords.state(engine.state.actors[A])['swords'][0]
    assert bond['item_uid'] == uid and bond['location'] == 'wielded' and bond['holder'] == owner
    assert swords.point(bond) == engine.state.actors[owner].position
    if borrowed:
        assert not any(row.parameters.get('requires_held_weapon') == action
                       for row in available_weapons(engine, engine.state.actors[A]).values())
    assert len(OwnerItemStore(tmp_path / 'owner_items').items(project)) == 1
    assert sum(uid in inventory.read(actor) for actor in engine.state.actors.values()) == 1
