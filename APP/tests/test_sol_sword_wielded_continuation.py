"""Wielded sword geometry and manifestation continuation through the table."""
from fractions import Fraction
from types import SimpleNamespace

from combat import activation_settlement
from combat.tabletop_service import TabletopService
from combat.ext import ten_thousand_swords as swords
from tests.test_mgr_t14_ten_thousand_sword_array_cultivator_floor58 import A, B, native, combat, use
from tests.worker2_support import reload, settle, turn


def test_wielded_origin_follows_table_movement_and_release(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch, cl=14, seeds=2)
    game = combat(cold, jid, tmp_path)
    use(game, 'Manifest Twin Swords')
    use(game, 'Switch Sword Armament floating and wielded')
    engine = reload(tmp_path, game[2])
    move = next(c for c in engine.legal_candidates()
                if str(c.kind) in ('MOVE', 'CandidateKind.MOVE')
                and c.destination and (c.destination.x, c.destination.y) == (2, 3))
    settle(game[1], game[2], move.candidate_id)
    engine = reload(tmp_path, game[2])
    actor = engine.state.actors[A]
    assert (actor.position.x, actor.position.y) == (2, 3)
    with monkeypatch.context() as patch:
        patch.setattr(activation_settlement, 'profile', lambda *args: {'qi_powered': True})
        patch.setattr(swords, 'sword_technique', lambda *args: True)
        origins = swords._technique_origins(engine, actor, SimpleNamespace(parameters={}))
    origin = next(o for o in origins if o['id'] == 'sword:technique:0')
    assert (origin['position']['x'], origin['position']['y']) == (2, 3)
    turn(game[1], game[2], B)
    turn(game[1], game[2], A)
    use(game, 'Switch Sword Armament floating and wielded')
    sword = swords.state(reload(tmp_path, game[2]).state.actors[A])['swords'][0]
    assert sword['location'] == 'floating'
    assert (sword['x'], sword['y']) == (2, 3)


def test_wielded_clock_survives_settlement_travel_and_new_fight(tmp_path, monkeypatch):
    cold, jid, _ = native(tmp_path, monkeypatch, cl=14, seeds=2)
    before = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, before['revision'], {A: 'team:a', B: 'team:b'},
                                      maximum_rounds=2)['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, A)
    game = (cold(), table, mid)
    use(game, 'Manifest Twin Swords')
    use(game, 'Switch Sword Armament floating and wielded')
    for _ in range(12):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path, mid).state.terminal_result is not None
    resumed = cold().journey_resume(jid, cold().journey_state(jid)['revision'],
                                    effect_resolutions={A: 'Other encounter effects ended.', B: 'Other encounter effects ended.'})
    data = resumed['actors'][A]['source_states'][swords.FAMILY]
    assert data['swords'][0]['location'] == 'wielded'
    remaining = Fraction(data['manifest_seconds']['0'])
    assert 0 < remaining < 3600
    waited = cold().journey_act(jid, resumed['revision'], A, 'wait', {'seconds': 120})
    assert Fraction(waited['actors'][A]['source_states'][swords.FAMILY]['manifest_seconds']['0']) == remaining - 120
    game = combat(cold, jid, tmp_path)
    engine = reload(tmp_path, game[2])
    actor = engine.state.actors[A]
    sword = swords.state(actor)['swords'][0]
    assert sword['location'] == 'wielded'
    assert swords.condition(actor, sword['manifest_condition']) is not None
    use(game, 'Switch Sword Armament floating and wielded')
    turn(game[1], game[2], B)
    turn(game[1], game[2], A)
    engine = reload(tmp_path, game[2])
    assert swords.state(engine.state.actors[A])['swords'][0]['location'] == 'floating'
