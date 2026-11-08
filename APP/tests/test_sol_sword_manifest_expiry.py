"""A wielded manifestation expires across a journey and a table reload."""
from fractions import Fraction
from types import SimpleNamespace

from combat import activation_settlement
from combat.ext import ten_thousand_swords as swords
from combat.ext.hand_occupancy import free_hands
from combat.tabletop_service import TabletopService
from tests.test_mgr_t14_ten_thousand_sword_array_cultivator_floor58 import A, B, native, combat, use
from tests.worker2_support import reload, settle, turn


def test_wielded_manifest_expires_after_encounter_and_reload(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch, cl=14, seeds=2)
    before = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, before['revision'], {A: 'team:a', B: 'team:b'},
                                      maximum_rounds=2)['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    game = (cold(), table, mid)
    use(game, 'Manifest Twin Swords')
    use(game, 'Switch Sword Armament floating and wielded')
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
    cold().journey_act(jid, resumed['revision'], A, 'wait', {'seconds': int(remaining - 12)})
    game = combat(cold, jid, tmp_path)
    table, mid = game[1], game[2]
    initial = reload(tmp_path, mid)
    sword = swords.state(initial.state.actors[A])['swords'][0]
    assert sword['location'] == 'wielded'
    grip = sword['grip']
    assert grip not in free_hands(initial, initial.state.actors[A])

    # Advance real table commits across the restored deadline.
    for _ in range(6):
        settle(table, mid, table.state(mid)['menu']['end_turn'], picks=decline)

    def check(engine):
        actor = engine.state.actors[A]
        sword = swords.state(actor)['swords'][0]
        assert sword['location'] == 'carried'
        assert 'grip' not in sword
        assert grip in free_hands(engine, actor)
        with monkeypatch.context() as patch:
            patch.setattr(activation_settlement, 'profile', lambda *args: {'qi_powered': True})
            patch.setattr(swords, 'sword_technique', lambda *args: True)
            origins = swords._technique_origins(engine, actor, SimpleNamespace(parameters={}))
        assert 'sword:technique:0' not in [origin['id'] for origin in origins]

    check(game[0]._load_session(mid).engine)
    check(reload(tmp_path, mid))
