"""Earlier-window expiration and real counterattacks share current reach."""
import pytest
from combat import attack_reach, typed_reactions
from combat.gate2_runtime_models import Position
from combat.ext.effect_durations import round_token
from tests import test_tabletop_hunt6 as H
from tests.test_lock11_reach import STATE, COURT, reach_reply, apply_reach, move_fixture, natural, checked
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.test_hidden_targeting import turn
from tests.r10_fixup_support import cast_sender, commit

COUNTER = 'TAL_IRON_FIST_COUNTER_PALM'
CHA = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.cha_hu_cha',
                                 'name': 'Cha / Hu Cha (Fork / Tiger Fork)', 'quantity': 1}]}}


@pytest.mark.parametrize('window', ['on_d20_pending', 'on_attacked'])
def test_reach_removed_before_packet_has_no_roll_and_reloads(monkeypatch, tmp_path, window):
    install(monkeypatch, 'attack_reach_bonus', reach_reply)
    service, table, mid = H.table_fight(tmp_path, [COURT], ally_talents=[])
    def setup(engine):
        apply_reach(engine, engine.state.actors[H.LEFT], COURT, 5)
        move_fixture(engine, engine.state.actors[H.RIGHT], 5)
    H.on_hold(monkeypatch, setup)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    e = service._load_session(mid).engine
    action = natural(e); hp = e.state.actors[H.RIGHT].current_hp
    original = getattr(typed_reactions, window)
    def earlier(engine, actor, *args, **kwargs):
        result = original(engine, actor, *args, **kwargs)
        if actor.entity_id == H.LEFT:
            engine._remove_condition(actor, STATE, 'test:earlier_reach_end')
        return result
    monkeypatch.setattr(typed_reactions, window, earlier)
    commit(cast_sender(service, table, mid, action.display_name, target=H.RIGHT))
    e = checked(tmp_path, mid)
    assert e.state.actors[H.RIGHT].current_hp == hp
    assert not any(ev.event_type == 'ATTACK_ROLLED' and ev.source_definition_id == action.source_definition_id for ev in e.events)
    assert not any(c.condition_id == STATE for c in e.state.actors[H.LEFT].conditions.values())


def setup_counter(engine, *, own_turn=False):
    actor = engine.state.actors[H.LEFT]
    apply_reach(engine, actor, COURT, 5, expires=round_token(engine, 2))
    if own_turn:
        # Reapply through the native event so this scope flag survives replay.
        engine._remove_condition(actor, STATE, 'test:own_turn_scope')
        engine._apply_condition(actor, STATE, COURT, actor.entity_id,
            expires_on=round_token(engine, 2), data={'feet': 5, 'own_turn': 1})
    move_fixture(engine, engine.state.actors[H.RIGHT], 5)
    engine._add_modifier(actor, 'test:forced_miss', 'armor_class', 'ADD', 100,
                         'ALWAYS', expires_on='UNTIL_REMOVED')


def counters(engine):
    return [ev for ev in engine.events if ev.event_type == 'ATTACK_ROLLED' and ev.source_definition_id == COUNTER]


def test_table_counter_uses_unarmed_reach_then_expires_even_with_long_weapon(monkeypatch, tmp_path):
    install(monkeypatch, 'attack_reach_bonus', reach_reply)
    service, table, mid = H.table_fight(tmp_path, [COURT, COUNTER], ally_talents=[],
                                      kits={'left': CHA, 'right': CHA})
    H.on_hold(monkeypatch, setup_counter)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    turn(table, mid, H.RIGHT)
    e = service._load_session(mid).engine
    weapon = next(a for a in e.action_catalog.values() if a.owner_id == H.RIGHT and
                  (a.reach_ft or a.range_ft) == 10 and a.resolution_kind == 'TYPED'
                  and a.parameters.get('typed', {}).get('weapon') and '#' not in a.source_definition_id)
    commit(cast_sender(service, table, mid, weapon.display_name, target=H.LEFT))
    e = checked(tmp_path, mid)
    assert len(counters(e)) == 1 and not e.state.actors[H.LEFT].reaction_available
    for _ in range(10):
        if not any(c.condition_id == STATE for c in e.state.actors[H.LEFT].conditions.values()):
            break
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
        e = checked(tmp_path, mid)
    else:
        raise AssertionError('reach did not expire')
    turn(table, mid, H.RIGHT)
    e = checked(tmp_path, mid)
    assert e.state.actors[H.LEFT].reaction_available
    assert attack_reach.maximum(e, e.state.actors[H.LEFT], natural(e)) == 5
    commit(cast_sender(service, table, mid, weapon.display_name, target=H.LEFT))
    e = checked(tmp_path, mid)
    assert len(counters(e)) == 1 and e.state.actors[H.LEFT].reaction_available


def test_table_own_turn_counter_is_not_an_opportunity_attack(monkeypatch, tmp_path):
    install(monkeypatch, 'attack_reach_bonus', reach_reply)
    service, table, mid = H.table_fight(tmp_path, [COURT, COUNTER], ally_talents=[], kits={'right': CHA})
    def setup(engine):
        setup_counter(engine, own_turn=True)
        move_fixture(engine, engine.state.actors[H.ALLY], 4)
    H.on_hold(monkeypatch, setup)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    e = service._load_session(mid).engine
    actor = e.state.actors[H.LEFT]
    assert e._typed_opportunity_reach(actor) == 5
    candidate = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination == Position(x=2, y=4))
    result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version,
                       table.state(mid)['last_sequence'])
    assert result['status'] == 'COMMITTED'
    e = checked(tmp_path, mid)
    assert len(counters(e)) == 1
    assert not e.state.actors[H.LEFT].reaction_available
    # Geometry remains queryable even after that Reaction was spent.
    effect = {'type': 'attack', 'attack_kind': 'unarmed', 'strike_with': 'unarmed'}
    assert e._distance_actor_to_actor(e.state.actors[H.LEFT], e.state.actors[H.ALLY]) == 10
    assert typed_reactions.attack_reaches(e, e.state.actors[H.LEFT], e.state.actors[H.ALLY], effect)
