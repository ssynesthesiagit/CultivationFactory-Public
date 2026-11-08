"""Granted choices preserve fear, hidden contact and unrelated OA protection."""
import pytest
from combat import ext
from combat.gate2_runtime_models import Position, ActionDefinition, EconomyKind
from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopService
from combat.typed_executor import Context
from tests.h1_support import ROOT
from tests.test_lock8_movement_steps import portable, STEAL, candidate
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import answer

BLOCKER='actor:factory.bbbbbbbb'


def hook(monkeypatch,point,fn):
    ext.effects();monkeypatch.setitem(ext._HOOKS,point,[*ext._HOOKS.get(point,[]),fn])


def checked(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']==session.mechanical.replay()['status']=='PASS'
    return session.engine


def sender(tmp_path,mid,c,after):
    # Every answer arrives through a new service, exercising persisted choices.
    def send(answers=()):
        table=TabletopService(CombatService(ROOT,tmp_path),tmp_path)
        return table.act(mid,c.candidate_id,c.decision_id,c.state_version,after,list(answers))
    return send


def followup(service,table,mid,tmp_path):
    c=candidate(service._load_session(mid).engine,6)
    send=sender(tmp_path,mid,c,table.state(mid)['last_sequence'])
    first=send();assert first['status']=='REACTION_REQUIRED'
    used=answer(first['reaction'],'use')
    second=send([used]);assert second['status']=='REACTION_REQUIRED'
    return send,used,second


def ids(result):
    return {o['id'] for o in result['reaction']['choice']['options']}


def test_real_steal_followup_refuses_frightened_destination_after_reload(monkeypatch,tmp_path):
    service,table,mid,left,right=portable(tmp_path,'SAND_BASE_SCOURING_HAND',STEAL)
    def setup(e,kind,kw):
        if kind=='HOLD_POSITION_COMMITTED' and kw.get('actor_id')==left:
            e._gain_resource(e.state.actors[right],'resource:core.martial_focus',1,'test:ready')
            e.state.actors[right].turn_flags['oa_free_ft']=5
            e._append_event('PASSIVE_TRIGGERED','test:protection',actor_id=right,payload={'log':'Movement protection granted.'})
            e._apply_condition(e.state.actors[right],'condition:typed.frightened','test:fear',left,expires_on='UNTIL_REMOVED')
    hook(monkeypatch,'event',setup)
    hook(monkeypatch,'d20_result',lambda *a:{'source_id':'test:roll','operation':'replace','natural_result':10})
    assert act(table,mid,'system:combat.hold_position')['status']=='COMMITTED'
    before=service._load_session(mid).engine.state.model_dump(mode='json')
    send,used,paused=followup(service,table,mid,tmp_path)
    assert 'cell:9,6' not in ids(paused) and 'cell:11,6' in ids(paused)
    with pytest.raises(CombatServiceError,match='completed intent was rejected'):
        send([used,answer(paused['reaction'],'cell:9,6')])
    assert service._load_session(mid).engine.state.model_dump(mode='json')==before
    assert send([used,answer(paused['reaction'],'cell:11,6')])['status']=='COMMITTED'
    e=checked(tmp_path,mid)
    assert e.state.actors[right].position==Position(x=11,y=6)
    assert e.state.actors[right].turn_flags['oa_free_ft']==5
    assert e.state.actors[right].movement_remaining_ft==before['actors'][right]['movement_remaining_ft']


def test_real_steal_menu_hides_blocker_motion_then_records_contact(monkeypatch,tmp_path):
    service,table,mid,left,right=portable(tmp_path,'SAND_BASE_SCOURING_HAND',STEAL,blocker=True)
    def setup(e,kind,kw):
        if kind!='HOLD_POSITION_COMMITTED' or kw.get('actor_id')!=left:return
        e._gain_resource(e.state.actors[right],'resource:core.martial_focus',1,'test:ready')
        b=e.state.actors[BLOCKER]
        if not any(c.condition_id=='condition:typed.invisible' for c in b.conditions.values()):
            e._apply_condition(b,'condition:typed.invisible','test:hide',BLOCKER,expires_on='UNTIL_REMOVED')
        else:
            previous=b.position;b.position=Position(x=10,y=7)
            e._append_event('MOVEMENT_COMMITTED','test:hidden-move',actor_id=BLOCKER,
                payload={'destination':b.position.model_dump(mode='json'),'path':[previous.model_dump(mode='json'),b.position.model_dump(mode='json')],'cost_ft':0})
        e.state.actors[right].turn_flags['oa_free_ft']=5
        e._append_event('PASSIVE_TRIGGERED','test:protection',actor_id=right,payload={'log':'Movement protection granted.'})
    hook(monkeypatch,'event',setup)
    hook(monkeypatch,'d20_result',lambda *a:{'source_id':'test:roll','operation':'replace','natural_result':10})
    assert act(table,mid,'system:combat.hold_position')['status']=='COMMITTED'
    from tests.r10_fixup_support import table_probe_copy
    with table_probe_copy(service, tmp_path) as (probe_service, probe_table, probe_root):
        _,_,empty=followup(probe_service,probe_table,mid,probe_root)
    assert act(table,mid,'system:combat.hold_position')['status']=='COMMITTED'
    send,used,blocked=followup(service,table,mid,tmp_path)
    assert ids(blocked)==ids(empty) and 'cell:10,7' in ids(blocked)
    assert send([used,answer(blocked['reaction'],'cell:10,7')])['status']=='COMMITTED'
    e=checked(tmp_path,mid);a=e.state.actors[right]
    assert a.position==Position(x=10,y=6) and a.turn_flags['oa_free_ft']==5
    assert a.turn_flags['unseen_contact_cells']==[{'x':10,'y':7}]
    assert any(ev.event_type=='TARGETS_OBSERVED' and ev.payload.get('contacted_cells') for ev in e.events)


def test_exempt_grant_preserves_protection_for_subsequent_ordinary_move(monkeypatch,tmp_path):
    service,table,mid,left,right=portable(tmp_path,'SAND_BASE_SCOURING_HAND','SAND_BASE_SCOURING_HAND',right_at=(4,6))
    def grant(e,kind,kw):
        if kind!='HOLD_POSITION_COMMITTED' or kw.get('actor_id')!=left:return
        a=e.state.actors[left];a.turn_flags['oa_free_ft']=5
        e._append_event('PASSIVE_TRIGGERED','test:protection',actor_id=left,payload={'log':'Movement protection granted.'})
        from combat.ext.rider_step import step
        action=ActionDefinition(source_definition_id='test:grant',display_name='Immediate step',owner_id=left,
            economy=EconomyKind.NONE,resolution_kind='TYPED',target_kind='SELF')
        step(Context(e,a,action,e._active_intent,{},[a],a,{}),{'distance_ft':5,'no_oa':True})
    hook(monkeypatch,'event',grant)
    e=service._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.source_definition_id=='system:combat.hold_position')
    send=sender(tmp_path,mid,c,table.state(mid)['last_sequence'])
    paused=send();assert paused['status']=='REACTION_REQUIRED'
    assert send([answer(paused['reaction'],'cell:3,7')])['status']=='COMMITTED'
    e=checked(tmp_path,mid);a=e.state.actors[left]
    assert a.position==Position(x=3,y=7) and a.turn_flags['oa_free_ft']==5
    sequence=e.state.event_sequence
    c=candidate(e,2,7)
    send=sender(tmp_path,mid,c,table.state(mid)['last_sequence'])
    assert send()['status']=='COMMITTED'
    e=checked(tmp_path,mid);a=e.state.actors[left]
    assert a.position==Position(x=2,y=7) and a.turn_flags['oa_free_ft']==0
    assert not any(ev.event_type=='REACTION_WINDOW_OPENED' and ev.sequence>sequence for ev in e.events)


def test_partial_exemption_still_uses_general_oa_protection():
    from tests import lock8_support as S
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(4,6))
    a=e.state.actors[S.ME];a.turn_flags['oa_free_ft']=5
    e._resolve_leave_reach(a,a.position,Position(x=2,y=6),None,ignore_oa_from=(S.ME,))
    assert a.turn_flags['oa_free_ft']==0
