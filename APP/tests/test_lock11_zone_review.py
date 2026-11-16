"""Painted terrain persists its counters; cancelled steps cannot open later reactions."""
import pytest
from combat import ext, zones
from combat.gate2_runtime_models import Position, ZoneState
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_lock8_movement_steps import portable, candidate, STEAL
from tests.test_lock10_zone_paths import send
from tests.test_lock2_persistence import act
from tests.test_hidden_targeting import turn
from tests.r10_fixup_support import answer

SAND='SAND_BASE_SCOURING_HAND'


@pytest.mark.parametrize('pause',[False,True])
def test_painted_ash_split_movement_reloads_and_pause_rolls_back_counters(monkeypatch,tmp_path,pause):
    combat,table,mid,left,right=portable(tmp_path,STEAL if pause else SAND,SAND,
        left_at=(2,6),right_at=(4,4),map_fields={
            'materials':[{'material':'terrain:ash terrain','cells':[[4,y] for y in range(4,9)]}],
            'terrain_numbers':{'save_dc':50,'pb':2}})
    if pause:
        H.on_hold(monkeypatch,lambda e:e._gain_resource(e.state.actors[left],'resource:core.martial_focus',1,'test:focus'))
        assert act(table,mid,H.HOLD)['status']=='COMMITTED'
    turn(table,mid,right)
    seq=combat._load_session(mid).engine.state.event_sequence
    for y in (5,6,7):
        combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
        e=combat._load_session(mid).engine; c=candidate(e,4,y)
        before=e.state.model_dump(mode='json'); sequence=table.state(mid)['last_sequence']
        submit=lambda replies=():table.act(mid,c.candidate_id,c.decision_id,c.state_version,sequence,list(replies))
        result=submit()
        if pause:
            assert result['status']=='REACTION_REQUIRED'
            assert CombatService(ROOT,tmp_path)._load_session(mid).engine.state.model_dump(mode='json')==before
            result=submit([answer(result['reaction'],use=False)])
        assert result['status']=='COMMITTED'
        e=CombatService(ROOT,tmp_path)._load_session(mid).engine
        marks=e.state.actors[right].turn_flags['map_zone_runtime:zone:map:1']
        assert marks['move_distance:'+right]==(y-4)*5
        assert all(type(v) is int for v in marks.values())
        assert zones.map_zones(e)[0].per_turn_triggered=={}
    fresh=CombatService(ROOT,tmp_path)._load_session(mid)
    triggers=[ev for ev in fresh.engine.events if ev.sequence>seq and ev.event_type=='PASSIVE_TRIGGERED'
              and ev.payload.get('moment')=='move_through']
    assert len(triggers)==1
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'


def test_zone_defeat_cancels_owned_steal_momentum_before_prompt_or_payment(monkeypatch,tmp_path):
    combat,table,mid,left,right=portable(tmp_path,STEAL,SAND,left_at=(2,6),right_at=(4,4))
    def setup(e):
        e._gain_resource(e.state.actors[left],'resource:core.martial_focus',1,'test:focus')
        source=next(a for a in e.state.actors[left].action_ids if e.action_catalog[a].resolution_kind=='TYPED')
        z=ZoneState(zone_id='zone:test.defeat',source_definition_id=source,owner_id=left,
            center=Position(x=4,y=5),radius_cells=0,affected_cells=(Position(x=4,y=5),),
            concentration_link=False,created_round=e.state.round_number,
            trigger_profile={'kind':'TYPED','numbers':{},'triggers':[{'id':'test:defeat','name':'Dangerous ground',
                'on':['enter'],'who':'hostile','effects':[{'type':'damage','flat':10000,'damage_types':['force'],'applies_to':'target'}]}]})
        e.state.zones[z.zone_id]=z
        e._append_event('ZONE_CREATED',source,actor_id=left,payload={'zone':z.model_dump(mode='json')})
    H.on_hold(monkeypatch,setup)
    assert act(table,mid,H.HOLD)['status']=='COMMITTED'
    turn(table,mid,right)
    e=combat._load_session(mid).engine; c=candidate(e,4,7)
    before=e.state.event_sequence; focus=e.state.actors[left].resources['resource:core.martial_focus']
    assert send(table,mid,c)['status']=='COMMITTED'
    fresh=CombatService(ROOT,tmp_path)._load_session(mid); e=fresh.engine
    assert not e.state.actors[right].active and e.state.actors[right].position==Position(x=4,y=5)
    assert e.state.actors[left].reaction_available
    assert e.state.actors[left].resources['resource:core.martial_focus']==focus
    assert not any(ev.source_definition_id==STEAL for ev in e.events if ev.sequence>before)
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'


def test_displacement_without_stop_reply_skips_later_interruptions(monkeypatch):
    from tests.test_lock10_zone_paths import fight
    from combat.movement_steps import checkpoint
    e=fight(); actor=e.state.actors[e.state.current_actor_id]; previous=actor.position
    seen=[]
    def displace(engine,mover,*args):
        mover.position=Position(x=2,y=2)
        engine._append_event('MOVEMENT_COMMITTED','test:displace',actor_id=mover.entity_id,
            payload={'destination':mover.position.model_dump(mode='json'),'path':[], 'cost_ft':0,'forced':True})
    ext._load()
    monkeypatch.setitem(ext._HOOKS,'movement_step',[displace,lambda *args:seen.append('late')])
    assert checkpoint(e,actor,previous,previous,None,travelled_ft=5,remaining_ft=10)==[]
    assert seen==[]
