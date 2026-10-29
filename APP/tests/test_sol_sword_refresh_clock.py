"""Refresh, carry and expire a single manifestation clock through table commits."""
from fractions import Fraction
from types import SimpleNamespace

from combat import activation_settlement
from combat.ext import ten_thousand_swords as swords
from combat.ext.effect_durations import parse_round
from combat.ext.hand_occupancy import free_hands
from combat.tabletop_service import TabletopService
from tests.test_mgr_t14_ten_thousand_sword_array_cultivator_floor58 import A, B, native, combat, use
from tests.worker2_support import reload, settle, turn


def test_refreshed_clock_survives_wield_settlement_and_expires(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch, cl=14, seeds=2)
    before = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, before['revision'], {A: 'team:a', B: 'team:b'},
                                      maximum_rounds=3)['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    game = (cold(), table, mid)
    decline = {'choice:needle.sword_array.offturn': None}

    def clocks(engine):
        actor = engine.state.actors[A]
        return [[c for c in actor.conditions.values() if c.condition_id == swords.MANIFEST_PREFIX + str(i)]
                for i in range(2)]

    def check_clocks():
        live = clocks(game[0]._load_session(mid).engine)
        saved = clocks(reload(tmp_path, mid))
        assert [len(c) for c in live] == [1, 1]
        assert [len(c) for c in saved] == [1, 1]
        assert [c[0].expires_on for c in live] == [c[0].expires_on for c in saved]
        return [parse_round(c[0].expires_on)[0] for c in saved]

    use(game, 'Manifest Twin Swords')
    first = check_clocks()
    while True:
        settle(table, mid, table.state(mid)['menu']['end_turn'], picks=decline)
        engine = reload(tmp_path, mid)
        if table.state(mid)['menu']['actor_id'] == A and engine.state.round_number > 1:
            break
    use(game, 'Manifest Twin Swords')
    refreshed = check_clocks()
    assert all(new > old for new, old in zip(refreshed, first))
    use(game, 'Switch Sword Armament floating and wielded')
    check_clocks()
    for engine in (game[0]._load_session(mid).engine, reload(tmp_path, mid)):
        assert swords.state(engine.state.actors[A])['swords'][0]['location'] == 'wielded'

    for _ in range(12):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'], picks=decline)
    final = reload(tmp_path, mid)
    assert final.state.terminal_result is not None
    resumed = cold().journey_resume(jid, cold().journey_state(jid)['revision'],
        effect_resolutions={A: 'Other encounter effects ended.', B: 'Other encounter effects ended.'})
    assert resumed == cold().journey_state(jid)
    data = resumed['actors'][A]['source_states'][swords.FAMILY]
    remaining = Fraction(data['manifest_seconds']['0'])
    assert remaining == (refreshed[0] - final.state.round_number) * 6
    assert remaining > (first[0] - final.state.round_number) * 6
    waited = cold().journey_act(jid, resumed['revision'], A, 'wait', {'seconds': int(remaining - 12)})
    assert waited == cold().journey_state(jid)
    game = combat(cold, jid, tmp_path)
    table, mid = game[1], game[2]
    check_clocks()
    initial = reload(tmp_path, mid)
    sword = swords.state(initial.state.actors[A])['swords'][0]
    assert sword['location'] == 'wielded'
    grip = sword['grip']
    assert grip not in free_hands(initial, initial.state.actors[A])
    for _ in range(6):
        settle(table, mid, table.state(mid)['menu']['end_turn'], picks=decline)

    for engine in (game[0]._load_session(mid).engine, reload(tmp_path, mid)):
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
