"""Review 1F6: actual possession and enduring bonds at the travel/table boundary."""
import pytest

from combat.gate5_service import CombatService, CombatServiceError, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_mgr_t14_iron_cloth import SILKEN, CLOTH, QI, CHOICE, use
from tests.worker2_support import settle, turn

A = FACTORY_ACTOR_PREFIX + 'cloth'
B = FACTORY_ACTOR_PREFIX + 'foe'
KEY = 'tianxia.mortal.gear.robe'
ARMAMENT = 'tianxia.path.qi_cultivation.feature.domain_armament'


def road(tmp_path, monkeypatch, *, steal=False):
    kit = {'starting_kit': {'items': CLOTH['starting_kit']['items'] * 2}}
    monkeypatch.setattr(CombatService, '_factory_owner_sheet', lambda self, pid:
        sheet([SILKEN] + ([ARMAMENT] if pid == 'cloth' else [])
              + (['TAL_SCOUNDREL_STEAL'] if steal and pid == 'cloth' else []),
              cl=18 if pid == 'cloth' else 3, score=30 if pid == 'cloth' else 14,
              key='CHA', kit=CLOTH if steal and pid == 'foe' else kit, name=pid))
    scene = {'stable_id': 'journey:cloth_reactivation', 'display_name': 'Cloth road',
             'width_squares': 12, 'height_squares': 12, 'square_size_ft': 5,
             'starting_positions': {}, 'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kw: {'scene': scene})
    cold = lambda: CombatService(ROOT, tmp_path)
    state = cold().create_journey(project_ids=['cloth', 'foe'], arena_id='scene',
        positions={A: {'x': 2, 'y': 2}, B: {'x': 3, 'y': 2}},
        base_paces={A: 5, B: 5}, control_modes={A: 'MANUAL', B: 'MANUAL'})
    return cold, state['journey_id']


def command(cold, jid, actor, kind, payload):
    state = cold().journey_state(jid)
    result = cold().journey_act(jid, state['revision'], actor, kind, payload)
    assert cold().journey_state(jid) == result
    return result


def infuse(cold, jid, actor, identity):
    # Historical own-item payloads remain valid; received items need full identity.
    owner, key = identity.split('|', 1)
    payload = {'item_key': key, 'fabric_kind': 'flexible_fabric'}
    if owner != actor:
        payload['item_object'] = identity
    return command(cold, jid, actor, 'iron_cloth_infuse', payload)


def start(cold, jid, *, rounds=8):
    state = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'},
                                    maximum_rounds=rounds)['match_id']
    assert cold()._load_session(mid).mechanical.replay()['status'] == 'PASS'
    return mid, TabletopService(cold(), cold().userdata_root)


def resume(cold, jid, mid, table):
    for _ in range(20):
        loaded = cold()._load_session(mid)
        if loaded.engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert loaded.engine.state.terminal_result is not None
    assert loaded.mechanical.replay()['status'] == 'PASS'
    state = cold().journey_state(jid)
    return cold().journey_resume(jid, state['revision'])


def infusion_at_genesis(cold, jid, actor, identity, *, bound=0):
    mid, _ = start(cold, jid)
    loaded = cold()._load_session(mid)
    e = loaded.engine
    w = next(c for c in e.state.actors[actor].conditions.values()
             if c.condition_id == 'condition:typed.silken_whip')
    assert w.data['item_object'] == identity
    assert w.data['item_owner'] == identity.split('|', 1)[0]
    assert w.data.get('domain_bound', 0) == bound
    assert w.data['declaration_authority'] == ('item_owner' if identity.startswith(actor + '|') else 'item_possessor')
    assert len([o for o in e.state.objects.values() if o.component.get('inventory_identity') == identity]) == 1
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return e


@pytest.mark.parametrize('disposition', ['dropped', 'destroyed'])
def test_absent_cloth_rejected_after_committed_encounter_resume(tmp_path, monkeypatch, disposition):
    cold, jid = road(tmp_path, monkeypatch)
    identity = B + '|' + KEY
    if disposition == 'destroyed':
        infuse(cold, jid, B, identity)
        infuse(cold, jid, A, A + '|' + KEY)
    mid, table = start(cold, jid)
    if disposition == 'dropped':
        turn(table, mid, B)
        e = cold()._load_session(mid).engine
        c = next(c for c in e.legal_candidates()
                 if (action := e.action_catalog.get(c.source_definition_id)) is not None
                 and action.parameters.get('item_action') == 'drop'
                 and action.parameters.get('item_key') == KEY)
        settle(table, mid, c.candidate_id)
    else:
        oid = 'object:iron_cloth:' + identity
        for _ in range(6):
            turn(table, mid, A)
            use(cold(), table, mid, 'Silken Whip: attack an object', target=oid,
                choices={CHOICE + 'object_damage_type': ['FORCE']})
            if cold()._load_session(mid).engine.state.objects[oid].destroyed:
                break
            settle(table, mid, table.state(mid)['menu']['end_turn'])
        assert cold()._load_session(mid).engine.state.objects[oid].destroyed
    state = resume(cold, jid, mid, table)
    options = cold().journey_menu(jid, B)['options']
    assert not any(o['kind'] == 'iron_cloth_infuse' and o['payload']['item_key'] == KEY for o in options)
    before = cold().journey_state(jid)
    with pytest.raises((ValueError, CombatServiceError)):
        infuse(cold, jid, B, identity)
    assert cold().journey_state(jid) == before  # no Qi, fact or revision spent
    # The other physical robe remains a legal option and reaches cold genesis.
    infuse(cold, jid, B, B + '|' + KEY + '.2')
    e = infusion_at_genesis(cold, jid, B, B + '|' + KEY + '.2')
    assert not any(c.condition_id == 'condition:typed.silken_whip' and c.data['item_object'] == identity
                   for c in e.state.actors[B].conditions.values())


def test_received_cloth_can_be_newly_infused_and_rebound_without_changing_owner(tmp_path, monkeypatch):
    from combat.ext.silken_whip import cloth_items
    cold, jid = road(tmp_path, monkeypatch, steal=True)
    identity = B + '|' + KEY
    mid, table = start(cold, jid)
    for _ in range(6):
        turn(table, mid, A)
        e = cold()._load_session(mid).engine
        c = next(c for c in e.legal_candidates() if c.target_ids == (B,) and
                 (action := e.action_catalog.get(c.source_definition_id)) is not None and
                 (action.parameters.get('typed') or {}).get('source') == 'TAL_SCOUNDREL_STEAL')
        settle(table, mid, c.candidate_id)
        e = cold()._load_session(mid).engine
        if any(i['object'] == identity for i in cloth_items(e, e.state.actors[A])):
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert any(i['object'] == identity for i in cloth_items(e, e.state.actors[A]))
    resume(cold, jid, mid, table)
    options = [o for o in cold().journey_menu(jid, A)['options'] if o['kind'] == 'iron_cloth_infuse']
    assert len({o['id'] for o in options}) == len(options)
    assert any(o['payload'].get('item_object') == identity for o in options)
    before = cold().journey_state(jid)
    with pytest.raises((ValueError, CombatServiceError)):
        infuse(cold, jid, B, identity)
    assert cold().journey_state(jid) == before
    state = infuse(cold, jid, A, identity)
    assert state['actors'][A]['resources'][QI] == before['actors'][A]['resources'][QI] - 1
    assert state['actors'][A]['travel_effects'][SILKEN]['fabric_record']['scope'] == identity
    command(cold, jid, A, 'iron_cloth_bind', {'item_key': KEY})
    command(cold, jid, A, 'iron_cloth_end', {})
    # Same catalog key on the recipient is still a different physical item.
    state = infuse(cold, jid, A, A + '|' + KEY)
    assert state['actors'][A]['travel_effects'][SILKEN].get('domain_bound', 0) == 0
    command(cold, jid, A, 'iron_cloth_end', {})
    state = infuse(cold, jid, A, identity)
    assert state['actors'][A]['travel_effects'][SILKEN]['domain_bound'] == 1
    assert not any(o['kind'] == 'iron_cloth_bind' for o in cold().journey_menu(jid, A)['options'])
    infusion_at_genesis(cold, jid, A, identity, bound=1)


@pytest.mark.parametrize('key,bound', [(KEY, 1), (KEY + '.2', 0)])
def test_travel_reinfusion_preserves_only_exact_retained_bond_through_reopen(tmp_path, monkeypatch, key, bound):
    cold, jid = road(tmp_path, monkeypatch)
    infuse(cold, jid, A, A + '|' + KEY)
    command(cold, jid, A, 'iron_cloth_bind', {'item_key': KEY})
    command(cold, jid, A, 'iron_cloth_end', {})
    state = infuse(cold, jid, A, A + '|' + key)
    assert state['actors'][A]['bundle']['iron_cloth_bond']['item_object'] == A + '|' + KEY
    assert state['actors'][A]['travel_effects'][SILKEN].get('domain_bound', 0) == bound
    command(cold, jid, A, 'finish', {})
    # New native journey imports the sealed source continuation from disk.
    state = cold().create_journey(project_ids=['cloth', 'foe'], arena_id='scene',
        positions={A: {'x': 2, 'y': 2}, B: {'x': 3, 'y': 2}},
        base_paces={A: 5, B: 5}, control_modes={A: 'MANUAL', B: 'MANUAL'})
    e = infusion_at_genesis(cold, state['journey_id'], A, A + '|' + key, bound=bound)
    assert any(c.condition_id == 'condition:typed.iron_cloth_bond' and c.data['item_object'] == A + '|' + KEY
               for c in e.state.actors[A].conditions.values())
