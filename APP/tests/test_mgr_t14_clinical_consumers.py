"""The five real toxin consumers, after native acquisition and failed save."""
import pytest
from tests.test_mgr_t14_clinical_native import (A,B,game,anatomy,exposure,start,engine,use,turn,act,next_round,area,
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
    before=len(engine(cold,mid).events)
    area(cold,table,mid,'Conflagration',center=(4,6))
    e=engine(cold,mid)
    save=next(v for v in e.events[before:] if v.event_type=='SAVE_ROLLED' and v.actor_id==B)
    assert save.payload['mode']=='DISADVANTAGE'
    assert not toxin(e,'Heavy Pulse')


def test_successful_ingrain_save_spends_marks_and_cp_without_new_toxin(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('poison',),owner_dc=14,hp=5000)
    # The bounded scenario can make 300 deliveries and ten Ingrain attempts;
    # a 20-round encounter terminates before that trial budget is available.
    anatomy(world);mid=start(cold,jid,maximum_rounds=400)
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


@pytest.mark.parametrize('seconds',[6,12])
def test_native_admitted_medicine_collects_actions_costs_time_and_source_dc(tmp_path,monkeypatch,seconds):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=())
    group=exposure(world,'poison','poisoned',label='An externally admitted poison')
    world('clinical_protocol',{'method':'Medicine','ability':'WIS','skill':'medicine','seconds':seconds,
        'costs':{'resource:core.qi':1},'operation':'treat','source_instance':group},scope='appropriate_medicine')
    mid=start(cold,jid)
    assert next(c.data['clinical']['dc'] for c in engine(cold,mid).state.actors[B].conditions.values() if c.data.get('clinical'))==12
    use(cold,table,mid,'Begin Medicine treatment')
    e=engine(cold,mid)
    assert e.state.actors[A].resources['resource:core.qi']==29
    if seconds>6:
        assert any(c.condition_id=='condition:typed.clinical_procedure' for c in e.state.actors[A].conditions.values())
        assert any((c.data.get('clinical') or {}).get('source_instance')==group for c in e.state.actors[B].conditions.values())
        next_round(cold,table,mid)
        use(cold,table,mid,'Continue Medicine treatment')
        e=engine(cold,mid)
    assert e.state.actors[A].resources['resource:core.qi']==29
    assert not any((c.data.get('clinical') or {}).get('source_instance')==group for c in e.state.actors[B].conditions.values())
    check=next(v for v in e.events if v.event_type=='CHECK_ROLLED' and v.actor_id==A and v.payload.get('check')=='medicine')
    assert check.payload['success'] and 'dc' not in check.payload
    assert not any(c.condition_id=='condition:typed.clinical_procedure' for c in e.state.actors[A].conditions.values())


def test_native_medicine_losing_contact_interrupts_without_refunding(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=())
    group=exposure(world,'poison','poisoned',label='An externally admitted poison')
    world('clinical_protocol',{'method':'Medicine','ability':'WIS','skill':'medicine','seconds':60,
        'costs':{'resource:core.qi':1},'operation':'treat','source_instance':group},scope='appropriate_medicine')
    mid=start(cold,jid)
    assert next(c.data['clinical']['dc'] for c in engine(cold,mid).state.actors[B].conditions.values() if c.data.get('clinical'))==12
    use(cold,table,mid,'Begin Medicine treatment')
    state=turn(cold,table,mid,A)
    option=next(o for o in state['menu']['moves'] if o['destination']=={'x':2,'y':6})
    act(cold,table,mid,state,option['candidate_id'],lambda p,ids:[])
    e=engine(cold,mid)
    assert e.state.actors[A].resources['resource:core.qi']==29
    assert not any(c.condition_id=='condition:typed.clinical_procedure' for c in e.state.actors[A].conditions.values())
    assert any((c.data.get('clinical') or {}).get('source_instance')==group for c in e.state.actors[B].conditions.values())



def test_admitted_medicine_treats_actual_native_ingrain_by_source_rule(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('poison',))
    anatomy(world)
    world('clinical_protocol',{'method':'Medicine','ability':'WIS','skill':'medicine','seconds':6,
        'costs':{'resource:core.qi':1},'operation':'treat','source_instance':'rule:POISON_BASE_INGRAIN_THE_TOXIN'},scope='native_minor_toxin')
    mid=start(cold,jid)
    from combat.ext.stacking_marks import count
    for _ in range(10):
        e=engine(cold,mid)
        if count(e,e.state.actors[A],e.state.actors[B],'Dose Mark')>=2:break
        use(cold,table,mid,'Deliver the Dose');next_round(cold,table,mid)
    use(cold,table,mid,'Ingrain the Toxin: Numb Channels',choose=lambda p,ids:['Numb Channels'] if 'Numb Channels' in ids else ids[:1])
    e=engine(cold,mid);assert toxin(e,'Numb Channels')
    actual_dc=toxin(e,'Numb Channels')[0].data['clinical']['dc'];assert actual_dc==50
    next_round(cold,table,mid)
    before=engine(cold,mid).state.actors[A].resources['resource:core.qi']
    use(cold,table,mid,'Begin Medicine treatment')
    e=engine(cold,mid);assert not toxin(e,'Numb Channels')
    assert e.state.actors[A].resources['resource:core.qi']==before-1
    assert any(v.event_type=='CHECK_ROLLED' and v.payload.get('success') and v.payload.get('check')=='medicine' for v in e.events)


def test_restorative_mend_reads_the_same_native_disease_option(tmp_path,monkeypatch):
    from tests.test_mgr_t14_clinical_native import C
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('life',),ally=True,
        talents=('tianxia.talent.life.restorative_mend',))
    world('clinical_anatomy',{'living':1},target=C)
    world('clinical_source',{'label':'A real admitted disease on the additional ally','category':'disease',
        'conditions':['sickened'],'ongoing':0,'excluded':[],'dc':12},target=C)
    mid=start(cold,jid)
    e=engine(cold,mid)
    legal_sources={c.source_definition_id for c in e.legal_candidates() if C in c.target_ids}
    action=next(a for a in e.action_catalog.values() if a.owner_id==A and
        a.source_definition_id in legal_sources and
        any(r.get('type')=='purify_one' and r.get('choose_treatment') for r in (a.parameters.get('typed') or {}).get('effects',[])))
    use(cold,table,mid,action.display_name,target=C)
    assert not any((c.data.get('clinical') or {}).get('category')=='disease' for c in engine(cold,mid).state.actors[C].conditions.values())


@pytest.mark.parametrize('choice',['Numb Channels','Sour Blood'])
def test_same_minor_penalty_from_two_native_creators_does_not_add(tmp_path,monkeypatch,choice):
    from tests.test_mgr_t14_clinical_native import C
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('poison',),enemy=('life',),
        ally=True,third_spheres=('poison',),hp=5000)
    anatomy(world);world('clinical_anatomy',{'living':1,'meaningful_biology':1},target=C)
    mid=start(cold,jid)
    from combat.ext.stacking_marks import count
    for owner in (A,C):
        for _ in range(12):
            e=engine(cold,mid)
            if count(e,e.state.actors[owner],e.state.actors[B],'Dose Mark')>=2:break
            use(cold,table,mid,'Deliver the Dose',aid=owner)
            state=turn(cold,table,mid,owner)
            act(cold,table,mid,state,state['menu']['end_turn'],lambda p,ids:[])
        use(cold,table,mid,'Ingrain the Toxin: Bitter Breath',aid=owner,
            choose=lambda p,ids:[choice] if choice in ids else ids[:1])
    e=engine(cold,mid)
    assert {c.source_actor_id for c in toxin(e,choice)}=={A,C}
    if choice=='Numb Channels':assert e._effective_speed(e.state.actors[B])==25
    else:
        before=len(e.events)
        use(cold,table,mid,'Mend the Pulse',target=B,aid=B)
        e=engine(cold,mid)
        event=next(v for v in e.events[before:] if v.event_type=='HEALING_APPLIED' and B in v.target_ids)
        roll=next(r for r in reversed(e.rolls) if r.actor_id==B and str(r.reason).startswith('HEALING'))
        assert event.payload['offered']==max(0,roll.total-4)
        assert not toxin(e,choice)


def test_native_gm_annotation_collects_unknown_source_dc_without_replacing_condition(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=())
    declared=world('clinical_source',{'label':'A poison whose treatment DC is initially unknown','category':'poison',
        'conditions':['poisoned'],'ongoing':0,'excluded':[]},scope='unknown_dc')
    group=declared['fact_consent_admission'][-1]['receipt_id']
    world('clinical_protocol',{'method':'Medicine','ability':'WIS','skill':'medicine','seconds':6,
        'costs':{'resource:core.qi':1},'operation':'treat','source_instance':group},scope='appropriate_medicine')
    mid=start(cold,jid);state=turn(cold,table,mid)
    assert not any(g['label']=='Begin Medicine treatment' for g in state['menu']['actions'])
    e=engine(cold,mid);source=next(c for c in e.state.actors[B].conditions.values() if (c.data.get('clinical') or {}).get('source_instance')==group)
    original=source.model_dump(mode='json');payer=e.state.actors[A].model_dump(mode='json');version=e.state.state_version
    payload={'source':'clinical_source','subject':B,'kind':'clinical_annotation','scope':'real_source_dc',
        'value':{'condition_instances':[source.instance_id],'label':source.data['clinical']['label'],
            'category':'poison','ongoing':0,'excluded':[],'dc':12},'expires_at':600,'readers':[A]}
    committed=cold().world_fact(mid,version,payload)
    assert committed['status']=='COMMITTED'
    e=engine(cold,mid);current=e.state.actors[B].conditions[source.instance_id]
    assert current.data['clinical']['source_instance']==group and current.data['clinical']['dc']==12
    assert current.data['clinical']['annotation_receipt']==committed['receipt_id']
    assert {k:v for k,v in current.model_dump(mode='json').items() if k!='data'}=={k:v for k,v in original.items() if k!='data'}
    assert e.state.actors[A].model_dump(mode='json')==payer
    from combat.fact_consent_admission import combat_records
    assert combat_records(e,e.state.actors[A],source='clinical_source',kind='clinical_annotation')
    assert not combat_records(e,e.state.actors[B],source='clinical_source',kind='clinical_annotation')
    before=e.state.model_dump(mode='json')
    with pytest.raises(ValueError,match='Refresh'):cold().world_fact(mid,version,payload)
    assert engine(cold,mid).state.model_dump(mode='json')==before
    bad={**payload,'value':{**payload['value'],'dc':13}}
    with pytest.raises(ValueError,match='known native source DC'):cold().world_fact(mid,e.state.state_version,bad)
    assert engine(cold,mid).state.model_dump(mode='json')==before
    bad={**payload,'value':{'done':1}}
    with pytest.raises(ValueError):cold().world_fact(mid,e.state.state_version,bad)
    assert engine(cold,mid).state.model_dump(mode='json')==before
    use(cold,table,mid,'Begin Medicine treatment')
    e=engine(cold,mid)
    assert source.instance_id not in e.state.actors[B].conditions
    assert e.state.actors[A].resources['resource:core.qi']==payer['resources']['resource:core.qi']-1


def test_combat_gm_input_cannot_supply_consent_or_an_actor_intent(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=())
    mid=start(cold,jid);e=engine(cold,mid);before=e.state.model_dump(mode='json')
    payload={'source':'clinical_source','subject':B,'kind':'clinical_consent','scope':'procedure',
        'value':1,'expires_at':60,'readers':[A]}
    with pytest.raises(ValueError):cold().world_fact(mid,e.state.state_version,payload)
    assert engine(cold,mid).state.model_dump(mode='json')==before
    from combat.gate2_runtime_models import ActionIntent
    intent=ActionIntent(intent_id='actor:forged-world-input',candidate_id='world-fact:v1',
        decision_id=e.legal_candidates()[0].decision_id,state_version=e.state.state_version,actor_id=e.state.current_actor_id)
    from combat.diagnostics import CombatGate1Error
    with pytest.raises(CombatGate1Error,match='not legal|not a legal|not.*candidate|selected candidate'):
        cold()._load_session(mid).submit_intent(intent,primary_decision_record=None,reaction_provider=None)
    assert engine(cold,mid).state.model_dump(mode='json')==before
