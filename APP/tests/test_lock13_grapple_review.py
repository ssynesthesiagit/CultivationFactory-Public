"""Turn-edge Speed and multiple holds settle through accepted Table actions."""
import pytest
from combat.gate2_runtime_models import Position, ZoneState
from combat.gate5_service import CombatService
from combat.movement_budget import WITHHELD
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_lock12_grapple_movement import hold
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_lock8_movement_steps import portable
from tests.test_lock10_zone_paths import send


def checked(path, mid):
    session = CombatService(ROOT, path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


@pytest.mark.parametrize('field,value', [('speed_halved', 1), ('speed_ft', -60)])
@pytest.mark.parametrize('conscious', [False, True])
def test_escape_restores_allowance_after_starting_speed_penalty_expires(monkeypatch, tmp_path, field, value, conscious):
    combat, table, mid, left, right = portable(tmp_path, 'SAND_BASE_SCOURING_HAND', 'SAND_BASE_SCOURING_HAND',
                                              left_at=(2,6), right_at=(3,6))
    if conscious:
        from tests.test_lock_choices import install
        install(monkeypatch, 'zero_hp', lambda *args: 'CONSCIOUS')
    def setup(e):
        actor = e.state.actors[right]
        if conscious:
            e._commit_damage(actor, actor.current_hp, 'FORCE', 'test:zero', left, None, reaction_depth=0)
        hold(e, actor, e.state.actors[left])
        e._add_modifier(actor, 'test:expiring_speed', field, 'ADD', value, 'ALWAYS',
                         expires_on='START_OF_TARGET_NEXT_TURN')
    H.on_hold(monkeypatch, setup)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    turn(table, mid, right)
    e = checked(tmp_path, mid); actor = e.state.actors[right]
    if conscious:
        assert actor.current_hp == 0 and actor.life_state == 'CONSCIOUS' and actor.active
    assert actor.movement_remaining_ft == 0 and actor.turn_flags[WITHHELD] == 30
    assert not any(m.source_definition_id == 'test:expiring_speed' for m in actor.modifiers.values())
    escape = next(c for c in e.legal_candidates() if 'Escape' in c.display_name)
    assert send(table, mid, escape)['status'] == 'COMMITTED'
    e = checked(tmp_path, mid); actor = e.state.actors[right]
    assert actor.movement_remaining_ft == e._effective_speed(actor) == 30
    assert WITHHELD not in actor.turn_flags
    restored = [ev for ev in e.events if ev.event_type == 'MOVEMENT_ALLOWANCE_RESTORED']
    assert len(restored) == 1 and restored[0].payload['restored_ft'] == 30


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('displace', [False, True])
def test_table_two_holds_both_land_when_first_takes_damage(monkeypatch, tmp_path, reverse, displace):
    combat, table, mid = H.table_fight(tmp_path, ['SAND_BASE_SCOURING_HAND'], ally_talents=[])
    held_ids = [H.RIGHT, H.ALLY] if reverse else [H.ALLY, H.RIGHT]
    def position(e, who, x, y):
        actor = e.state.actors[who]; before = actor.position; actor.position = Position(x=x, y=y)
        e._append_event('MOVEMENT_COMMITTED', 'test:position', actor_id=who,
            payload={'destination': actor.position.model_dump(mode='json'),
                     'path': [before.model_dump(mode='json'), actor.position.model_dump(mode='json')], 'cost_ft': 0})
    def setup(e):
        position(e, H.LEFT, 4, 3)
        position(e, held_ids[0], 3, 3); position(e, held_ids[1], 3, 4)
        for who in held_ids:
            hold(e, e.state.actors[who], e.state.actors[H.LEFT])
        source = next(a for a in e.state.actors[H.LEFT].action_ids
                      if e.action_catalog[a].resolution_kind=='TYPED')
        effects = [{'type':'damage','flat':3,'damage_types':['force'],'applies_to':'target'}]
        if displace:
            effects.append({'type':'forced_movement','distance_ft':10,'direction':'away','applies_to':'target'})
        z = ZoneState(zone_id='zone:test.drag_landings', source_definition_id=source,
            owner_id=H.LEFT, center=Position(x=4,y=2), radius_cells=0,
            affected_cells=tuple(Position(x=4,y=y) for y in (2,3,4)),
            concentration_link=False, created_round=e.state.round_number,
            trigger_profile={'kind':'TYPED','shape':'painted','numbers':{},'triggers':[
                {'id':'test:drag_entry','name':'Scorching ground','on':['enter'],'who':'any',
                 'effects':effects}]})
        e.state.zones[z.zone_id] = z
        e._append_event('ZONE_CREATED', z.source_definition_id, actor_id=H.LEFT,
                        payload={'zone':z.model_dump(mode='json')})
    H.on_hold(monkeypatch, setup)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    e = checked(tmp_path, mid); before = e.state.event_sequence
    hp = {who:e.state.actors[who].current_hp for who in held_ids}
    c = next(c for c in e.legal_candidates() if c.kind=='MOVE' and c.destination==Position(x=7,y=3))
    assert send(table, mid, c)['status'] == 'COMMITTED'
    e = checked(tmp_path, mid)
    assert e.state.actors[H.LEFT].position == Position(x=5,y=3)
    assert e.state.actors[held_ids[0]].position == (Position(x=2,y=0) if displace else Position(x=4,y=2))
    # Before the upper hold moves, it blocks the lower hold's diagonal shortcut.
    second = Position(x=4,y=4 if reverse else 3)
    displaced_second = Position(x=2,y=6 if reverse else 3)
    assert e.state.actors[held_ids[1]].position == (displaced_second if displace else second)
    for who in held_ids:
        assert e.state.actors[who].current_hp == hp[who]-3
        assert any(c.condition_id=='condition:typed.grappled' and c.source_actor_id==H.LEFT
                   for c in e.state.actors[who].conditions.values()) is not displace
    events = [ev for ev in e.events if ev.sequence>before]
    for who in held_ids:
        assert sum(ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==who
                   and ev.payload.get('dragged_by')==H.LEFT for ev in events)==1
        assert sum(ev.event_type=='DAMAGE_COMMITTED' and who in ev.target_ids for ev in events)==1
        if displace:
            assert any(ev.event_type=='CONDITION_REMOVED' and who in ev.target_ids
                       # The nested range rider may release the displaced hold
                       # before the native drag fallback reaches it.
                       and ev.payload.get('reason') in {'DRAG_CANNOT_RETAIN_HOLD', 'OUT_OF_REACH'} for ev in events)
