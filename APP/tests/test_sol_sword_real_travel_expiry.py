"""Real sword custody survives manifestation expiry during travel."""
from fractions import Fraction

from combat.ext import ten_thousand_swords as swords
from combat.tabletop_service import TabletopService
from factory_authoring.owner_items import OwnerItemStore
from tests.test_mgr_t14_ten_thousand_sword_array_cultivator_floor58 import (
    A, B, native, combat, real_admission, use,
)
from tests.worker2_support import candidate, reload, settle, turn


def test_real_wielded_sword_remains_switchable_after_travel_expiry(tmp_path, monkeypatch):
    cold, jid, acquire = native(tmp_path, monkeypatch, cl=14, seeds=0, real_swords=1)
    uid = OwnerItemStore(tmp_path / 'owner_items').items('sword-owner')[0]['item_uid']
    real_admission(cold, jid, uid)
    acquire(swords.SEED, {'slot': 0, 'form': 'real', 'damage_type': 'force',
                          'item_uid': uid, 'owner_id': A, 'admission_scope': 'real-sword'})
    acquire(swords.TWIN, {'slot': 1, 'form': 'projected', 'damage_type': 'force'})
    before = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, before['revision'], {A: 'team:a', B: 'team:b'},
                                      maximum_rounds=2)['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    game = (cold(), table, mid)
    use(game, 'Manifest Twin Swords')
    use(game, 'Switch Sword Armament floating and wielded')
    for engine in (game[0]._load_session(mid).engine, reload(tmp_path, mid)):
        sword = swords.state(engine.state.actors[A])['swords'][0]
        assert sword['form'] == 'real' and sword['location'] == 'wielded'
    for _ in range(12):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'],
               picks={'choice:needle.sword_array.offturn': None})
    assert reload(tmp_path, mid).state.terminal_result is not None
    resumed = cold().journey_resume(jid, cold().journey_state(jid)['revision'],
        effect_resolutions={A: 'Other encounter effects ended.', B: 'Other encounter effects ended.'})
    assert resumed == cold().journey_state(jid)
    data = resumed['actors'][A]['source_states'][swords.FAMILY]
    remaining = Fraction(data['manifest_seconds']['0'])
    waited = cold().journey_act(jid, resumed['revision'], A, 'wait', {'seconds': int(remaining) + 1})
    assert waited == cold().journey_state(jid)
    data = waited['actors'][A]['source_states'][swords.FAMILY]
    assert data['swords'][0]['location'] == 'wielded'
    assert 'manifest_condition' not in data['swords'][0]
    assert '0' not in data['manifest_seconds']
    game = combat(cold, jid, tmp_path)
    for engine in (game[0]._load_session(game[2]).engine, reload(tmp_path, game[2])):
        sword = swords.state(engine.state.actors[A])['swords'][0]
        assert sword['item_uid'] == uid and sword['location'] == 'wielded'
        assert 'manifest_condition' not in sword
    assert candidate(game[0], game[2], 'Switch Sword Armament floating and wielded') is not None
    use(game, 'Switch Sword Armament floating and wielded')
    assert swords.state(reload(tmp_path, game[2]).state.actors[A])['swords'][0]['location'] == 'floating'
