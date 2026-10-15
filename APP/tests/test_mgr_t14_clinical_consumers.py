"""The five real toxin consumers, after native acquisition and failed save."""
import pytest
from tests.test_mgr_t14_clinical_native import (A,B,game,anatomy,exposure,start,engine,use,turn,act,next_round,
                                               final_native_mechanical_replay)


def prepare(tmp_path,monkeypatch,choice,*,spheres=('poison',),enemy=(),blind=False):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=spheres,enemy=enemy)
    anatomy(world)
    if blind:exposure(world,'physical_impairment','blinded',label='An admitted eye injury')
    mid=start(cold,jid)
    from combat.ext.stacking_marks import count
    for _ in range(10):
        e=engine(cold,mid)
        if count(e,e.state.actors[A],e.state.actors[B],'Dose Mark')>=2:break
        use(cold,table,mid,'Deliver the Dose');next_round(cold,table,mid)
    e=engine(cold,mid);assert count(e,e.state.actors[A],e.state.actors[B],'Dose Mark')>=2
    use(cold,table,mid,'Ingrain the Toxin: Bitter Breath',choose=lambda p,ids:[choice] if choice in ids else ids[:1])
    assert any(c.data.get('choice')==choice for c in engine(cold,mid).state.actors[B].conditions.values())
    return cold,table,jid,mid


def toxin(e,choice):
    return [c for c in e.state.actors[B].conditions.values()
            if c.condition_id=='condition:typed.minor_ingrained_toxin' and c.data.get('choice')==choice]


def test_bitter_breath_consumes_on_real_next_constitution_save(tmp_path,monkeypatch):
    cold,table,jid,mid=prepare(tmp_path,monkeypatch,'Bitter Breath')
    next_round(cold,table,mid);before=len(engine(cold,mid).events)
    for _ in range(10):
        use(cold,table,mid,'Deliver the Dose')
        e=engine(cold,mid)
        saves=[v for v in e.events[before:] if v.event_type=='SAVE_ROLLED' and v.actor_id==B]
        if saves:break
        next_round(cold,table,mid)
    assert saves and saves[0].payload['mode']=='DISADVANTAGE'
    assert not toxin(e,'Bitter Breath')


def test_numb_channels_changes_native_speed_and_does_not_fall_off_at_turn_end(tmp_path,monkeypatch):
    cold,table,jid,mid=prepare(tmp_path,monkeypatch,'Numb Channels')
    for _ in range(2):
        e=engine(cold,mid)
        assert e._effective_speed(e.state.actors[B])==25
        next_round(cold,table,mid)
    assert toxin(engine(cold,mid),'Numb Channels')


def test_sour_blood_reduces_only_the_next_actual_healing(tmp_path,monkeypatch):
    cold,table,jid,mid=prepare(tmp_path,monkeypatch,'Sour Blood',enemy=('life',))
    for index in range(2):
        before=len(engine(cold,mid).events)
        use(cold,table,mid,'Mend the Pulse',target=B,aid=B)
        e=engine(cold,mid)
        event=next(v for v in e.events[before:] if v.event_type=='HEALING_APPLIED' and B in v.target_ids)
        roll=next(r for r in reversed(e.rolls) if r.actor_id==B and str(r.reason).startswith('HEALING'))
        assert event.payload['offered']==max(0,roll.total-(e.state.actors[A].proficiency_bonus if index==0 else 0))
        assert not toxin(e,'Sour Blood')
        state=turn(cold,table,mid,B)
        act(cold,table,mid,state,state['menu']['end_turn'],lambda p,ids:[])


def test_clouded_senses_consumes_only_a_real_wisdom_perception_check(tmp_path,monkeypatch):
    cold,table,jid,mid=prepare(tmp_path,monkeypatch,'Clouded Senses',blind=True)
    from combat.stealth import hidden
    for _ in range(10):
        next_round(cold,table,mid)
        use(cold,table,mid,'Hide',target=A)
        e=engine(cold,mid)
        if hidden(e.state.actors[A]) is not None:break
    assert hidden(e.state.actors[A]) is not None
    assert toxin(e,'Clouded Senses')
    use(cold,table,mid,'Search',target=B,aid=B)
    e=engine(cold,mid)
    checks=[r for r in e.rolls if r.actor_id==B and str(r.reason).startswith('CHECK:') and 'perception' in str(r.reason).lower()]
    assert checks and checks[-1].mode=='DISADVANTAGE'
    assert not toxin(e,'Clouded Senses')


def test_heavy_pulse_denies_next_turn_dash_benefit_and_next_dexterity_save(tmp_path,monkeypatch):
    cold,table,jid,mid=prepare(tmp_path,monkeypatch,'Heavy Pulse',spheres=('poison','fire'))
    state=turn(cold,table,mid,B);before=engine(cold,mid).state.actors[B].movement_remaining_ft
    use(cold,table,mid,'Dash',target=B,aid=B)
    e=engine(cold,mid)
    assert e.state.actors[B].movement_remaining_ft==before
    assert not e.state.actors[B].turn_flags.get('dash_used')
    assert toxin(e,'Heavy Pulse')
    # Conflagration supplies a real independent Dexterity save after this turn.
    state=turn(cold,table,mid,A)
    group=next(g for g in state['menu']['actions'] if g['label']=='Conflagration')
    option=min((o for o in group['options'] if o.get('destination')),
        key=lambda o:abs(o['destination']['x']-4)+abs(o['destination']['y']-6))
    before=len(engine(cold,mid).events)
    act(cold,table,mid,state,option['candidate_id'])
    e=engine(cold,mid)
    save=next(v for v in e.events[before:] if v.event_type=='SAVE_ROLLED' and v.actor_id==B)
    assert save.payload['mode']=='DISADVANTAGE'
    assert not toxin(e,'Heavy Pulse')


def test_successful_ingrain_save_spends_marks_and_cp_without_new_toxin(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('poison',),owner_dc=14,hp=5000)
    anatomy(world);mid=start(cold,jid)
    from combat.ext.stacking_marks import count
    for _ in range(10):
        for _delivery in range(30):
            e=engine(cold,mid)
            if count(e,e.state.actors[A],e.state.actors[B],'Dose Mark')>=2:break
            use(cold,table,mid,'Deliver the Dose');next_round(cold,table,mid)
        e=engine(cold,mid);before=len(e.events);n=len([c for c in e.state.actors[B].conditions.values() if c.condition_id=='condition:typed.minor_ingrained_toxin'])
        marks=count(e,e.state.actors[A],e.state.actors[B],'Dose Mark');cp=e.state.actors[A].resources['resource:core.qi']
        use(cold,table,mid,'Ingrain the Toxin: Numb Channels',choose=lambda p,ids:['Numb Channels'] if 'Numb Channels' in ids else ids[:1])
        e=engine(cold,mid);save=next(v for v in e.events[before:] if v.event_type=='SAVE_ROLLED' and v.actor_id==B)
        assert count(e,e.state.actors[A],e.state.actors[B],'Dose Mark')==marks-2
        assert e.state.actors[A].resources['resource:core.qi']==cp-2
        if save.payload['success']:
            assert len([c for c in e.state.actors[B].conditions.values() if c.condition_id=='condition:typed.minor_ingrained_toxin'])==n
            return
        next_round(cold,table,mid)
    pytest.fail('The deterministic scenario did not reach a successful native save')


def test_body_refining_ingrain_uses_real_stamina_and_touch_boundary(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('poison',),body=True)
    anatomy(world);mid=start(cold,jid)
    from combat.ext.stacking_marks import count
    for _ in range(10):
        e=engine(cold,mid)
        if count(e,e.state.actors[A],e.state.actors[B],'Dose Mark')>=2:break
        use(cold,table,mid,'Deliver the Dose');next_round(cold,table,mid)
    state=turn(cold,table,mid,A)
    def step(x):
        state=turn(cold,table,mid,A)
        option=next(o for o in state['menu']['moves'] if o['destination']=={'x':x,'y':6})
        return act(cold,table,mid,state,option['candidate_id'],lambda p,ids:[])
    step(2)
    state=turn(cold,table,mid,A)
    assert not any(g['label'].startswith('Ingrain the Toxin') for g in state['menu']['actions'])
    step(3)
    e=engine(cold,mid);before=e.state.actors[A].resources['resource:core.stamina']
    use(cold,table,mid,'Ingrain the Toxin: Numb Channels',choose=lambda p,ids:['Numb Channels'] if 'Numb Channels' in ids else ids[:1])
    e=engine(cold,mid)
    assert toxin(e,'Numb Channels') and e.state.actors[A].resources['resource:core.stamina']==before-2
