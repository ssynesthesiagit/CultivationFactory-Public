"""Native recovery persists real sword custody without an optional item profile."""
from fractions import Fraction
import json

import pytest

from combat import acquisition_inventory as inventory
from combat import action_geometry
from combat.ext import ten_thousand_swords as swords
from combat.ext.water_defenses import SHIELD, shield_routes
from combat.tabletop_service import TabletopService
from combat.weapon_delivery import available_weapons, ready_weapons
from factory_authoring.owner_items import OwnerItemStore
from tests import test_mgr_t14_sword_round11_table as support
from tests.worker2_support import reload, settle, turn

A, B = support.A, support.B
DECLINE = {'choice:needle.sword_array.offturn': None}


def finish(table, mid, tmp_path):
    for _ in range(20):
        if reload(tmp_path, mid).state.terminal_result is not None:
            return
        settle(table, mid, table.state(mid)['menu']['end_turn'], picks=DECLINE)
    assert reload(tmp_path, mid).state.terminal_result is not None


def resume(cold, jid):
    return cold().journey_resume(jid, cold().journey_state(jid)['revision'],
        effect_resolutions={A: 'Other encounter effects ended.', B: 'Other encounter effects ended.'})


@pytest.mark.parametrize('borrowed', [False, True], ids=['owned', 'borrowed'])
@pytest.mark.parametrize('expiry', ['travel', 'combat'])
def test_native_pickup_restores_unprofiled_sword_after_expiry(tmp_path, monkeypatch, borrowed, expiry):
    owner = B if borrowed else A
    project = 'sword-lender' if borrowed else 'sword-owner'
    cold, jid, uid, acquire = support.native(tmp_path, monkeypatch, cl=14, seeds=0,
                                            talents=[support.SWORD_IN_HAND, SHIELD if owner == A else 'WATER_BASE_WATER_LASH'],
                                            lender_talents=[SHIELD if owner == B else 'WATER_BASE_WATER_LASH'],
                                            real_sword_owner=project)
    assert 'runtime_profile' not in OwnerItemStore(tmp_path / 'owner_items').items(project)[0]['record']
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
    support.use((cold(), table, mid), 'Manifest Twin Swords')
    sword = swords.state(reload(tmp_path, mid).state.actors[A])['swords'][0]
    position = swords.point(sword).model_dump(mode='json')
    assert sword['location'] == 'floating'
    finish(table, mid, tmp_path)
    resumed = resume(cold, jid)
    remaining = Fraction(resumed['actors'][A]['source_states'][swords.FAMILY]['manifest_seconds']['0'])
    assert remaining > 12 and remaining.denominator == 1
    waited = cold().journey_act(jid, resumed['revision'], A, 'wait',
        {'seconds': int(remaining) + 1 if expiry == 'travel' else int(remaining) - 12})
    assert waited == cold().journey_state(jid)

    positions = {owner: position, B if owner == A else A: {'x': 3, 'y': 2}}
    mid = cold().journey_start_combat(jid, waited['revision'], {A: 'team:a', B: 'team:b'},
                                      positions=positions, maximum_rounds=8)['match_id']
    table = TabletopService(cold(), tmp_path)
    if expiry == 'combat':
        for _ in range(6):
            settle(table, mid, table.state(mid)['menu']['end_turn'], picks=DECLINE)
    turn(table, mid, owner)
    engine = reload(tmp_path, mid)
    sword = swords.state(engine.state.actors[A])['swords'][0]
    action = sword['weapon_action']
    assert sword['item_uid'] == uid and sword['location'] == 'fallen'
    assert sword.get('holder', '') == ''
    assert not inventory.read(engine.state.actors[owner])
    assert action not in ready_weapons(engine, engine.state.actors[owner])
    support.use((cold(), table, mid), engine.action_catalog[action + '.pickup'].display_name)

    def assert_recovered(engine):
        actor = engine.state.actors[owner]
        assert action in ready_weapons(engine, actor), {
            'readiness': actor.equipment_readiness,
            'available': list(available_weapons(engine, actor)),
            'conditions': {c.condition_id: c.data for c in actor.conditions.values()},
        }
        assert not any(c.data.get('disables_action') == action for c in actor.conditions.values())
        bond = next(c for c in engine.state.actors[A].conditions.values() if c.condition_id == swords.STATE)
        assert swords.point(json.loads(bond.data['state'])['swords'][0]) == actor.position
        sword = swords.state(engine.state.actors[A])['swords'][0]
        assert sword['item_uid'] == uid and sword['location'] == 'wielded'
        assert sword['holder'] == owner
        assert swords.point(sword) == actor.position
        technique = next(row for row in engine.action_catalog.values()
                         if row.owner_id == A and row.source_definition_id.endswith(support.SWORD_IN_HAND))
        origin = next(row for row in action_geometry.origins(engine, engine.state.actors[A], technique)
                      if row['id'] == 'sword:technique:0')
        assert origin['position'] == actor.position.model_dump(mode='json')
        assert not inventory.read(actor), 'Native recovery must not invent an opted-in ledger'
        if borrowed:
            assert not any(row.parameters.get('requires_held_weapon') == action
                           for row in available_weapons(engine, engine.state.actors[A]).values())

    # Pickup and movement both survive cold replay, including a holder who does not own the bond.
    engine = reload(tmp_path, mid)
    assert_recovered(engine)
    pickup = engine.state.actors[owner].position
    move = next(row for row in engine.legal_candidates()
                if str(row.kind) in ('MOVE', 'CandidateKind.MOVE')
                and row.destination is not None and row.destination != pickup)
    settle(table, mid, move.candidate_id, picks=DECLINE)
    engine = reload(tmp_path, mid)
    moved = engine.state.actors[owner].position
    assert moved != pickup
    if borrowed:
        assert engine.state.actors[A].position != moved
    assert_recovered(engine)

    # Water Shield moves the holder inside DAMAGE_COMMITTED, not from a root MOVE.
    # Use the native reaction through the table, then check the committed bond and origin
    # before another turn or encounter initialization could refresh their coordinates.
    support.use((cold(), table, mid), 'Shape Current: Mist Basin', at=(moved.x, moved.y), picks=DECLINE)
    attacker = A if owner == B else B
    turn(table, mid, attacker)
    engine = reload(tmp_path, mid)
    destination, path = next(iter(shield_routes(engine, engine.state.actors[owner]).items()))
    before = len(engine.events)
    support.scripted_outcomes(monkeypatch)
    prompts = support.use((cold(), table, mid), 'Water Lash', target=owner,
        picks={**DECLINE, 'choice:needle.water_shield': 'use',
               'choice:needle.water_shield_step': destination})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.water_shield_step' for p in prompts)
    committed = table.combat._load_session(mid).engine
    assert committed.state.actors[owner].position == path[-1] != moved
    assert_recovered(committed)
    engine = reload(tmp_path, mid)
    moved = engine.state.actors[owner].position
    assert_recovered(engine)
    events = engine.events[before:]
    damage = next(e for e in events if e.event_type == 'DAMAGE_COMMITTED' and owner in e.target_ids)
    shift = next(e for e in events if e.event_type == 'MOVEMENT_COMMITTED'
                 and e.actor_id == owner and e.source_definition_id == SHIELD)
    assert damage.sequence < shift.sequence

    finish(table, mid, tmp_path)
    resumed = resume(cold, jid)
    source = resumed['actors'][A]['source_states'][swords.FAMILY]['swords'][0]
    assert source['holder'] == owner and source['location'] == 'wielded'
    assert swords.point(source) == moved
    positions[owner] = {'x': 7, 'y': 5}
    mid = cold().journey_start_combat(jid, resumed['revision'], {A: 'team:a', B: 'team:b'},
                                      positions=positions, maximum_rounds=2)['match_id']
    assert_recovered(reload(tmp_path, mid))
    assert len(OwnerItemStore(tmp_path / 'owner_items').items(project)) == 1
