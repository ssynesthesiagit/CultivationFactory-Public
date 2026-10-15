"""Dragged entry and unspent movement recovery through real Table journals."""
import pytest

from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.movement_budget import WITHHELD
from tests import lock8_support as S
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_lock8_movement_steps import portable, candidate, use
from tests.test_lock10_zone_paths import fight, zone, send


def hold(e, target, source, **data):
    e._apply_condition(target, 'condition:typed.grappled', 'test:hold', source.entity_id,
        expires_on='UNTIL_REMOVED', data={'reach_ft': 5, 'escape_dc': 1, **data})


@pytest.mark.parametrize('spent', [0, 10, 30])
def test_midturn_escape_never_refunds_spent_movement(spent):
    e=fight();a=e.state.actors[S.FOE]
    a.movement_remaining_ft=30-spent
    hold(e,a,e.state.actors[S.ME])
    e._remove_condition(a,'condition:typed.grappled','test:escape')
    assert a.movement_remaining_ft==30-spent
    assert WITHHELD not in a.turn_flags


def test_turn_start_withheld_allowance_waits_for_last_speed_zero_condition():
    e=fight();a=e.state.actors[S.FOE]
    hold(e,a,e.state.actors[S.ME])
    e._apply_condition(a,'condition:typed.restrained','test:net',S.ME,expires_on='UNTIL_REMOVED')
    e.end_turn();S.turn(e,S.FOE)
    assert a.movement_remaining_ft==0 and a.turn_flags[WITHHELD]==30
    e._remove_condition(a,'condition:typed.grappled','test:escape')
    assert a.movement_remaining_ft==0
    e._remove_condition(a,'condition:typed.restrained','test:free')
    assert a.movement_remaining_ft==30 and WITHHELD not in a.turn_flags
    e._remove_condition(a,'condition:typed.restrained','test:again')
    assert a.movement_remaining_ft==30


@pytest.mark.parametrize('hazard', ['typed', 'map'])
def test_drag_entry_hazard_stops_both_paths(hazard):
    e=fight();mover,held=e.state.actors[S.FOE],e.state.actors[S.ME]
    mover.position=Position(x=4,y=6);held.position=Position(x=3,y=6)
    hold(e,held,mover)
    if hazard=='typed':
        z=zone(e,cells=((4,5),));z.trigger_profile['triggers'][0]['who']='any'
    else:
        e.grid.qi_hazard={(4,5)};held.saving_throws['DEX']=-100
    before=held.current_hp
    use(e,candidate(e,7))
    assert held.current_hp<before
    assert held.position==Position(x=4,y=5) and mover.position==Position(x=5,y=6)
    dragged=[ev for ev in e.events if ev.event_type=='MOVEMENT_COMMITTED' and ev.payload.get('dragged_by')]
    assert len(dragged)==1 and dragged[0].payload['path']==[{'x':3,'y':6},{'x':4,'y':5}]


def test_escape_table_reloads_restored_unspent_movement(monkeypatch,tmp_path):
    combat,table,mid,left,right=portable(tmp_path,'SAND_BASE_SCOURING_HAND','SAND_BASE_SCOURING_HAND',
        left_at=(2,6),right_at=(3,6))
    H.on_hold(monkeypatch,lambda e:hold(e,e.state.actors[right],e.state.actors[left]))
    assert act(table,mid,'system:combat.hold_position')['status']=='COMMITTED'
    turn(table,mid,right)
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    a=loaded.engine.state.actors[right]
    assert a.movement_remaining_ft==0 and a.turn_flags[WITHHELD]>0
    c=next(c for c in loaded.engine.legal_candidates() if 'Escape' in c.display_name)
    assert send(table,mid,c)['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    a=loaded.engine.state.actors[right]
    assert a.movement_remaining_ft==loaded.engine._effective_speed(a)>0
    assert loaded.engine._movement_candidates(a)
    assert any(ev.event_type=='MOVEMENT_ALLOWANCE_RESTORED' for ev in loaded.engine.events)
    feed=[row for row in table.events(mid,0)['events'] if row['event_type']=='MOVEMENT_ALLOWANCE_RESTORED']
    assert len(feed)==1 and feed[0]['detailed_breakdown_recorded']
    assert a.display_name in feed[0]['summary']
    assert f'{a.movement_remaining_ft} feet of unspent movement restored' in feed[0]['summary']
    assert f'{a.movement_remaining_ft} feet remain this turn' in feed[0]['summary']
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_crown_dragged_entry_table_reload_and_replay(monkeypatch,tmp_path):
    combat,table,mid,left,right=portable(tmp_path,'FIRE_TAL_CROWN_OF_INFERNO','SAND_BASE_SCOURING_HAND',
        left_at=(4,6),right_at=(3,6),dc=50)
    H.on_hold(monkeypatch,lambda e:hold(e,e.state.actors[right],e.state.actors[left]))
    assert act(table,mid,'system:combat.hold_position')['status']=='COMMITTED'
    assert act(table,mid,'end')['status']=='COMMITTED'
    turn(table,mid,left)
    e=combat._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.display_name.startswith('Crown of the Inferno')
        and c.destination==Position(x=4,y=1))
    assert send(table,mid,c)['status']=='COMMITTED'
    e=combat._load_session(mid).engine;before=e.state.event_sequence
    c=candidate(e,5)
    snapshot=e.state.model_dump(mode='json');sequence=table.state(mid)['last_sequence']
    submit=lambda replies:table.act(mid,c.candidate_id,c.decision_id,c.state_version,sequence,replies)
    result=submit([]);replies=[]
    for _ in range(8):
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED'
        assert combat._load_session(mid).engine.state.model_dump(mode='json')==snapshot
        from tests.r10_fixup_support import answer
        prompt=result['reaction']
        replies.append(answer(prompt,use=True) if prompt.get('choice') else {**prompt['context'],'selection':'DECLINE'})
        result=submit(replies)
    assert result['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    events=[ev for ev in loaded.engine.events if ev.sequence>before]
    assert any(ev.event_type=='SAVE_ROLLED' and ev.actor_id==right for ev in events)
    assert any(ev.event_type=='DAMAGE_COMMITTED' and right in ev.target_ids for ev in events)
    assert loaded.engine.state.actors[left].position==Position(x=5,y=6)
    assert loaded.engine.state.actors[right].position==Position(x=4,y=5)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
