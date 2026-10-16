"""Bounded option transport and default-inert elapsed command seams."""
from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace
import pytest
from combat.ext import journey_native_choices as choices
from combat.journey_native import PENDING, KEY
from combat.journey import JourneySession


def test_large_multiselection_keeps_every_order_without_factorial_menu():
    ids = ['option:'+str(i) for i in range(40)]
    state = {KEY:{}, PENDING:{'request':{'reactor_id':'hero',
        'extension_choice':{'option_ids':ids,'minimum_selections':1,'maximum_selections':6,'allow_decline':True},
        'choice_trigger':{'prompt':'Choose the affected creatures','labels':{i:'Creature '+i.split(':')[1] for i in ids}}}}}
    session = SimpleNamespace(state=state, emit=lambda *a,**kw:None)
    for option in reversed(ids[-6:]):
        menu = choices.options(session, 'hero')
        assert len(menu) <= len(ids)+2
        offered = next(r for r in menu if r['kind']=='native_effect_pick' and r['payload']['option']==option)
        assert choices.answer(session,'hero',offered['kind'],offered['payload'])
    menu = choices.options(session,'hero')
    confirmed = next(r for r in menu if r['kind']=='native_effect_answer' and r['payload']['selection']=='USE')
    assert confirmed['payload']['option_ids']==list(reversed(ids[-6:]))
    removed = next(r for r in menu if r['kind']=='native_effect_pick')
    choices.answer(session,'hero',removed['kind'],removed['payload'])
    assert any(r['kind']=='native_effect_pick' and r['payload']['option']==ids[0] for r in choices.options(session,'hero'))
    assert choices.options(session,'other') is None
    with pytest.raises(ValueError): choices.answer(session,'other','native_effect_pick',{'option':ids[0]})


def test_tick_boundaries_preserve_fraction_and_zero_notification(monkeypatch):
    import combat.journey as journey
    seen=[]
    def hooks(point, *args):
        if point=='journey_tick_limit': return [Fraction(1,3)]
        if point=='journey_elapsed': seen.append((args[2],args[3]))
        return []
    monkeypatch.setattr(journey,'run_strict',hooks)
    session=object.__new__(JourneySession)
    session.state={'seconds':0,'actors':{'hero':{}}}
    session.tick(1)
    assert session.clock()==1 and seen==[(Fraction(0),Fraction(1,3)),(Fraction(1,3),Fraction(1,3)),(Fraction(2,3),Fraction(1,3))]
    session.tick(0)
    assert seen[-1]==(Fraction(1),0)


def test_no_native_capture_adds_no_scope_or_changes():
    session=SimpleNamespace(state={'phase':'travel','actors':{}})
    before=deepcopy(session.state)
    assert choices.scope(session,'hero','wait',{'seconds':10}) is None
    assert choices.options(session,'hero') is None
    assert session.state==before


def test_elapsed_incapacitation_stops_before_entering_travel_square(monkeypatch):
    import combat.journey as journey
    session=object.__new__(JourneySession)
    hero={'name':'Walker','position':{'x':0,'y':0},'incapacitated':0,
          'base_pace_ft_hour':1800,'loaded_pace_ft_hour':1800}
    session.state={'seconds':0,'actors':{'hero':hero},'events':[]}
    session.grid=SimpleNamespace(distance_ft=lambda *a:5)
    session.properties=lambda aid:{}
    session.step_profile=lambda *a:1
    monkeypatch.setattr(journey,'run_strict',lambda point,*a:[6] if point=='journey_tick_limit' else [])
    def tick(seconds, moving):
        session.state['seconds']+=seconds
        hero['incapacitated']=1
    session._tick=tick
    session.move('hero',{'path':[{'x':1,'y':0}]})
    assert session.clock()==6 and hero['position']=={'x':0,'y':0}
    assert session.state['events'][-1]['kind']=='TRAVEL_INTERRUPTED'


def test_native_work_interruption_keeps_elapsed_event_without_finishing(monkeypatch):
    from combat.ext import journey_activities as activities
    row={'source':'test:rite','required_seconds':60,'worked_seconds':0}
    actor={'incapacitated':0,'source_states':{activities.KEY:row}}
    calls=[]
    session=SimpleNamespace(state={'actors':{'hero':actor}},emit=lambda *a,**kw:calls.append(a))
    def tick(seconds):
        calls.append(('elapsed',seconds))
        del actor['source_states'][activities.KEY]
    session.tick=tick
    monkeypatch.setattr(activities,'run_strict',lambda point,*a:[6] if point=='journey_tick_limit' else [])
    assert activities.command(session,'hero','activity_work',{'seconds':60}) is True
    assert calls==[('elapsed',6)] and row['worked_seconds']==0
