"""Whole-family boundary paths, always acquired and played through native stores."""
import pytest
from tests.test_second_furnace_native import (game,fight,engine,play,turn,next_owner,choose_seed,verify,OWNER,FOE,f)


def collect(cold,root,mid,count):
    for i in range(count):
        if i:next_owner(cold,root,mid)
        play(cold,root,mid,'Force Mantle',select=lambda p:choose_seed(p) or ('Temporary Hit Points' if 'overflow' in p['context']['checkpoint'] else None))


def test_overdraw_and_core_can_mix_discount_and_actual_remaining_expenditure(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=18,seed='mixed-overdraw')
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    collect(cold,tmp_path,mid,2);next_owner(cold,tmp_path,mid)
    def select(p):
        key=p['context']['checkpoint']
        if 'PAYMENT_SHORTFALL' in key:return 'pay 4 remaining Qi with Devil Qi'
        if 'furnace_motion' in key:return 'Temporary Hit Points'
        if 'seed_reinforcement' in key:return 'Temporary Hit Points'
        return None
    play(cold,tmp_path,mid,'Demon Emperor',select=select)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert a.resources[f.QI]==30 and a.resources[f.DEVIL]==2 and a.resources[f.CORRUPTION]==3
    assert f.engine_form(a)
    assert any(x.event_type=='ALTERNATIVE_PAYMENT_COMMITTED' and x.payload['costs'].get(f.DEVIL)==4 for x in e.events)
    verify(cold,mid)


@pytest.mark.parametrize('specialist',[OWNER,FOE])
def test_breach_has_native_damage_order_and_cannot_be_accepted_twice_while_unstable(tmp_path,monkeypatch,specialist):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=18,seed='breach')
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    collect(cold,tmp_path,mid,10);next_owner(cold,tmp_path,mid)
    assert engine(cold,mid).state.actors[OWNER].resources[f.CORRUPTION]==10
    play(cold,tmp_path,mid,'Demon Emperor',select=lambda p:'ordinary cost' if 'PAYMENT_SHORTFALL' in p['context']['checkpoint'] else None)
    before=len(engine(cold,mid).events)
    def accept(p):
        key=p['context']['checkpoint']
        if 'PAYMENT_SHORTFALL' in key:return 'Demon Seed Overdraw'
        if ':breach:' in key:return 'Accept 4d10'
        if 'breach_damage' in key:return 'Psychic'
        if 'reinforcement' in key or 'overflow' in key:return 'Temporary Hit Points'
        return None
    prompts=play(cold,tmp_path,mid,'Force Mantle',select=accept)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert any('Furnace Breach' in str(p) for p in prompts)
    assert f.condition(a,'condition:typed.second_furnace_unstable')
    hits=[x for x in e.events[before:] if x.event_type=='DAMAGE_COMMITTED' and OWNER in x.target_ids]
    assert hits and all(x.payload.get('temporary_hp_absorbed',0)==0 for x in hits)
    assert f.condition(a,'condition:typed.second_furnace_no_healing')
    next_owner(cold,tmp_path,mid)
    later=play(cold,tmp_path,mid,'Force Mantle')
    assert not any('Demon Seed Overdraw' in str(p) or 'Emperor’s Overdraw' in str(p) for p in later)
    # The Engine ends before the same meaningful scene does; its breach makes
    # the actual organ Dormant. Finish the real encounter, then recover through
    # the persisted rest/session path rather than deleting a condition in tests.
    for _ in range(65):
        e=engine(cold,mid)
        if e.state.terminal_result:break
        play(cold,tmp_path,mid,end=True,select=lambda p:'Temporary Hit Points' if 'overflow' in p['context']['checkpoint'] else None)
    e=engine(cold,mid)
    assert e.state.terminal_result and f.condition(e.state.actors[OWNER],'condition:typed.second_furnace_dormant')
    verify(cold,mid)
    state=cold().journey_state(jid)
    state=cold().journey_resume(jid,state['revision'])
    assert state['actors'][OWNER]['source_states'][f.PARENT]['dormant']==1
    state=cold().journey_act(jid,state['revision'],OWNER,'long_rest',{})
    assert state['actors'][OWNER]['source_states'][f.PARENT]['dormant']==1
    state=cold().journey_end_scene(jid,state['revision'],'The battle and recovery watch have ended.')
    state=cold().journey_world_fact(jid,state['revision'],{'source':f.PARENT,'subject':OWNER,'kind':'stabilization',
        'scope':'stabilize','value':{'specialist':specialist,'specialty':'self' if specialist==OWNER else 'daemonic','source_cl':18,
            **({'consent_scope':'help-patient'} if specialist!=OWNER else {})},
        'expires_at':state['seconds']+7200,'readers':[]})
    if specialist!=OWNER:
        receipt=state['fact_consent_admission'][-1]['receipt_id']
        before=state
        with pytest.raises(ValueError,match='must consent'):
            cold().journey_act(jid,state['revision'],OWNER,'furnace_stabilize',{'scope':'stabilize'})
        assert cold().journey_state(jid)==before
        consent={'source':f.PARENT,'subject':specialist,'kind':'stabilization_consent','scope':'help-patient',
            'value':{'patient':OWNER,'procedure_scope':'stabilize','procedure_receipt':receipt},
            'expires_at':state['seconds']+7200,'readers':[OWNER]}
        with pytest.raises(ValueError,match='private consent'):
            cold().journey_world_fact(jid,state['revision'],consent)
        state=cold().journey_act(jid,state['revision'],specialist,'declare_fact',consent)
    before=state['seconds']
    state=cold().journey_act(jid,state['revision'],OWNER,'furnace_stabilize',{'scope':'stabilize'})
    assert state['seconds']==before+3600 and state['actors'][OWNER]['source_states'][f.PARENT]['dormant']==0
    assert state['actors'][OWNER]['resources'][f.DEVIL]==0
    mid2=fight(cold,jid,maximum_rounds=1)
    assert not f.condition(engine(cold,mid2).state.actors[OWNER],'condition:typed.second_furnace_dormant')
    turn(cold,tmp_path,mid2,OWNER)
    play(cold,tmp_path,mid2,'Demon Emperor')
    play(cold,tmp_path,mid2,'Force Mantle',select=accept)
    for _ in range(3):
        if engine(cold,mid2).state.terminal_result:break
        play(cold,tmp_path,mid2,end=True)
    verify(cold,mid2)
    state=cold().journey_state(jid);state=cold().journey_resume(jid,state['revision'])
    form=state['actors'][OWNER]['source_states'][f.PARENT]['engine']
    from fractions import Fraction
    remaining=Fraction(form['expires_num'],form['expires_den'])-state['seconds']
    assert remaining.denominator==1
    state=cold().journey_act(jid,state['revision'],OWNER,'wait',{'seconds':int(remaining)})
    assert state['actors'][OWNER]['source_states'][f.PARENT]['dormant']==1
    before=state
    with pytest.raises(ValueError,match='already been completed'):
        cold().journey_act(jid,state['revision'],OWNER,'furnace_stabilize',{'scope':'stabilize'})
    assert cold().journey_state(jid)==before



@pytest.mark.parametrize('cl,dice',[(6,2),(11,3),(17,4)])
def test_augment_scaling_uses_own_acquired_source_cl(tmp_path,monkeypatch,cl,dice):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=cl,seed='scale-'+str(cl))
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER);collect(cold,tmp_path,mid,1);next_owner(cold,tmp_path,mid)
    def augment(p):
        key=p['context']['checkpoint']
        if 'PAYMENT_SHORTFALL' in key:return 'ordinary cost'
        if key.endswith(':offer'):return 'add damage'
        if key.endswith(':damage_type'):return 'Necrotic'
        if key.endswith(':rider'):return 'Reactions'
        return None
    play(cold,tmp_path,mid,'Shockwave',target=FOE,select=augment)
    e=engine(cold,mid)
    added=[x for x in e.events if x.event_type=='DAMAGE_ROLLED' and str(x.payload.get('display_source_id','')).startswith(f.AUGMENT)]
    assert len(added)==1 and added[0].payload['expression'].startswith(str(dice)+'d8')
    verify(cold,mid)


def test_world_owner_cannot_invent_a_subjects_voluntary_permanent_price(tmp_path,monkeypatch):
    cold,jid,declare,_=game(tmp_path,monkeypatch,cl=14,seed='voluntary-guard')
    declare('furnace_environment',{'source_rule':'A permanent offered price','source_cl':14,'subject':OWNER,
        'voluntary_permanent_price':1,'voluntary_price_scope':'accepted-price'},'offered-price')
    state=cold().journey_state(jid)
    with pytest.raises(ValueError,match='own live source-scoped acceptance'):
        cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'offered-price'})
    assert cold().journey_state(jid)==state
    with pytest.raises(ValueError,match='private consent'):
        declare('voluntary_price',{'source_rule':'A permanent offered price','accepted':1},'accepted-price')
    state=cold().journey_state(jid)
    state=cold().journey_act(jid,state['revision'],OWNER,'declare_fact',{'source':f.PARENT,'subject':OWNER,
        'kind':'voluntary_price','scope':'accepted-price','value':{'source_rule':'A permanent offered price','accepted':1},
        'expires_at':state['seconds']+60,'readers':[]})
    state=cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'offered-price'})
    assert state['actors'][OWNER]['source_states'][f.PARENT]['environment'][-1]['consent_receipt']
    mid=fight(cold,jid);verify(cold,mid)


@pytest.mark.parametrize('level,outside,destroyed,allowed',[(9,0,0,True),(10,0,0,True),(13,0,0,False),(13,1,0,True),(9,1,1,False)])
def test_core_continuity_uses_actual_source_authority_and_required_structures(tmp_path,monkeypatch,level,outside,destroyed,allowed):
    cold,jid,declare,_=game(tmp_path,monkeypatch,cl=10,foe_cl=10,seed=f'continuity-{level}-{outside}-{destroyed}')
    profiles=[('hostility',{'source_rule':'A genuine hostile cultivator, with no farming or control relationship',
        'source_cl':10,'subject':FOE,'beneficiary':OWNER,'qualifying_hostility':1}),
        ('suppression',{'source_rule':'The scene owner’s actual Qi-suppression formation','source_cl':level,'subject':OWNER,
            'ordinary_suppressed':1,'save_dc':1,'outside_structure':outside,
            **({'destroyed_structure':'tianxia.sphere.force'} if destroyed else {})})]
    for scope,profile in profiles:
        declare('furnace_environment',profile,scope)
        state=cold().journey_state(jid)
        cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':scope})
    mid=fight(cold,jid)
    for _ in range(2):
        turn(cold,tmp_path,mid,FOE)
        play(cold,tmp_path,mid,'Force Mantle')
        play(cold,tmp_path,mid,end=True)
    turn(cold,tmp_path,mid,OWNER)
    assert engine(cold,mid).state.actors[OWNER].resources[f.DEVIL]==2
    if not allowed:
        from combat.tabletop_service import TabletopService
        assert not any('Shockwave' in group['label'] for group in TabletopService(cold(),tmp_path).state(mid)['menu']['actions'])
    else:
        def choose(p):
            key=p['context']['checkpoint']
            if 'PAYMENT_SHORTFALL' in key:return 'Second Furnace Core: pay 2'
            if 'continuity:' in key:return 'Make a Constitution save'
            if 'furnace_motion' in key:return 'Temporary Hit Points'
            return None
        prompts=play(cold,tmp_path,mid,'Shockwave',target=FOE,select=choose)
        assert engine(cold,mid).state.actors[OWNER].resources[f.DEVIL]==0
        assert any('continuity:' in p['context']['checkpoint'] for p in prompts)==(level==10 and not outside)
    verify(cold,mid)


def test_engine_armament_movement_range_and_expiry_do_not_bank_temporary_range(tmp_path,monkeypatch):
    from combat.ext import qi_path
    armament='tianxia.path.qi_cultivation.feature.domain_armament'
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=18,seed='armament-engine',extras=(armament,))
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    collect(cold,tmp_path,mid,1)
    play(cold,tmp_path,mid,'Domain Armament: Manifest',destination=(9,6),
        select=lambda p:'ordinary cost' if 'PAYMENT_SHORTFALL' in p['context']['checkpoint'] else None)
    next_owner(cold,tmp_path,mid)
    play(cold,tmp_path,mid,'Demon Emperor',select=lambda p:'ordinary cost' if 'PAYMENT_SHORTFALL' in p['context']['checkpoint'] else None)
    def motion(p):
        key=p['context']['checkpoint']
        if 'PAYMENT_SHORTFALL' in key:return 'Second Furnace Core: pay 2'
        if 'furnace_motion' in key:return 'Domain Armament'
        if 'FURNACE_ARMAMENT' in key and p['reaction']=='Furnace Motion':return '(15, 6)'
        return None
    play(cold,tmp_path,mid,'Shockwave',target=FOE,select=motion)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert qi_path.armament_point(a)==(15,6) and qi_path.armament_control_range(e,a)==60
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination is not None and (c.destination.x,c.destination.y)==(0,6))
    play(cold,tmp_path,mid,candidate_id=move.candidate_id)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert qi_path.armament_condition(a).data['reach_ft']==30
    assert e.grid.distance_ft(a.position,qi_path.armament_point(a))<=60
    for _ in range(23):
        if not f.engine_form(engine(cold,mid).state.actors[OWNER]):break
        play(cold,tmp_path,mid,end=True)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert not f.engine_form(a) and qi_path.armament_control_range(e,a)==30
    assert e.grid.distance_ft(a.position,qi_path.armament_point(a))<=30
    verify(cold,mid)
