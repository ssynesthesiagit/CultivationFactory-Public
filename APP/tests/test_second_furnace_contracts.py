"""Native second users of reaction settlement and Asset authority contracts."""
import pytest
from tests.test_second_furnace_native import game,fight,engine,play,turn,next_owner,choose_seed,verify,OWNER,FOE,f

ARMOR='tianxia.path.qi_cultivation.feature.qi_armor'


@pytest.mark.parametrize('cl,payment',[(3,'Demon Seed Overdraw'),(10,'Second Furnace Core: pay 2')])
def test_ask_reaction_can_use_actual_furnace_payment_on_another_creatures_turn(tmp_path,monkeypatch,cl,payment):
    cold,jid,_,state=game(tmp_path,monkeypatch,cl=cl,seed='reaction-payment-'+str(cl),extras=(ARMOR,),ask=True)
    assert state['actors'][OWNER]['bundle']['reaction_plan']['mode']=='ask'
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    if cl==10:play(cold,tmp_path,mid,'Force Mantle',select=choose_seed)
    prompts=[]
    for _ in range(12):
        turn(cold,tmp_path,mid,FOE)
        attacks=[c for c in engine(cold,mid).legal_candidates() if c.kind.value=='ACTION' and OWNER in c.target_ids and 'Unarmed' in c.display_name]
        assert attacks,'The real installed character must have its ordinary attack.'
        def choose(p):
            key=p['context']['checkpoint']
            if 'PAYMENT_SHORTFALL' in key:return payment
            if 'seed_reinforcement' in key or 'furnace_motion' in key:return 'Temporary Hit Points'
            if 'Qi Armor' in str(p) and not p.get('choice'):return 'USE'
            return None
        prompts+=play(cold,tmp_path,mid,candidate_id=attacks[0].candidate_id,select=choose)
        paid=[e for e in engine(cold,mid).events if e.event_type=='ALTERNATIVE_PAYMENT_COMMITTED'
              and e.payload.get('technique_source_id')==ARMOR]
        if paid:break
        play(cold,tmp_path,mid,end=True);turn(cold,tmp_path,mid,OWNER);play(cold,tmp_path,mid,end=True)
    assert paid,{'prompts':prompts}
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert any(x.event_type=='REACTION_RESOLVED' and x.source_definition_id==ARMOR for x in e.events)
    assert any('Qi Armor' in str(p) and p['context']['reactor_id']==OWNER for p in prompts)
    if cl==3:
        assert a.resources[f.QI]==30 and a.resources[f.CORRUPTION]==1 and a.resources[f.DEVIL]==2
        assert any(x.event_type=='ACTIVATION_PAYMENT_SETTLED' for x in e.events)
    else:
        assert a.resources[f.DEVIL]==0
        assert paid[-1].payload['costs'][f.DEVIL]==2
    verify(cold,mid)


def test_actual_map_asset_supplies_counterflow_authority_and_takes_legal_backlash(tmp_path,monkeypatch):
    from combat.ext.objects import object_id
    objects=[{'kind':'statue','x':5,'y':6,'name':'Accusing heart seal','material':'stone','size':'small',
        'ac':12,'hp':200,'blocks':False,'source_cl':14,'cultivation_asset':True,
        'asset_declaration':{'actor':'GM','authority':'GM','source_rule':'This cultivated seal challenges any Qi activation.',
                             'visibility':'public','expiry':'source_rule'}}]
    cold,jid,declare,state=game(tmp_path,monkeypatch,cl=14,seed='asset-backlash',objects=objects)
    row=state['battlefield']['map_objects'][0];oid=object_id(row)
    declare('furnace_environment',{'source_rule':'The accusing heart seal forces a Wisdom save when Qi is activated.',
        'source_cl':14,'subject':OWNER,'activation_save':1,'source_object_id':oid,'save_ability':'WIS','save_dc':14},'seal')
    state=cold().journey_state(jid);cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'seal'})
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    # Build the reservoir by real Overdraw. Only native failed saves may offer
    # Counterflow; repeated turns use deterministic native dice, never forced rolls.
    for _ in range(10):
        def choose(p):
            key=p['context']['checkpoint']
            if 'PAYMENT_SHORTFALL' in key:return 'Demon Seed Overdraw'
            if 'seed_reinforcement' in key or 'furnace_motion' in key or 'overflow' in key:return 'Temporary Hit Points'
            if 'counterflow_damage_type' in key:return 'Necrotic'
            if 'Heart-Devil Counterflow' in str(p):return 'USE'
            return None
        play(cold,tmp_path,mid,'Force Mantle',select=choose)
        e=engine(cold,mid)
        if e.state.objects[oid].current_hp<200:break
        next_owner(cold,tmp_path,mid)
    assert e.state.objects[oid].current_hp<200
    assert e.state.objects[oid].component['source_cl']==14 and e.state.objects[oid].component['cultivation_asset'] is True
    verify(cold,mid)


@pytest.mark.parametrize('duration,present_after',[(1,False),(120,True)])
def test_native_environment_clock_crosses_encounter_and_scene_without_restarting(tmp_path,monkeypatch,duration,present_after):
    cold,jid,declare,_=game(tmp_path,monkeypatch,cl=6,seed='profile-clock-'+str(duration))
    declare('furnace_environment',{'source_rule':'The scene owner’s timed consecrated protection','source_cl':6,
        'subject':FOE,'consecrated':1},'timed-protection',seconds=duration)
    state=cold().journey_state(jid)
    cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'timed-protection'})
    mid=fight(cold,jid,maximum_rounds=1)
    for _ in range(3):
        if engine(cold,mid).state.terminal_result:break
        play(cold,tmp_path,mid,end=True)
    assert engine(cold,mid).state.terminal_result
    verify(cold,mid)
    state=cold().journey_state(jid);state=cold().journey_resume(jid,state['revision'])
    assert state['actors'][OWNER]['source_states'][f.PARENT]['environment'][0]['expires_at']==duration-6
    before=state
    with pytest.raises(ValueError,match='already admitted'):
        cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'timed-protection'})
    assert cold().journey_state(jid)==before
    state=cold().journey_end_scene(jid,state['revision'],'The first meaningful confrontation has ended; the protection keeps its own printed duration.')
    mid2=fight(cold,jid,maximum_rounds=1)
    profiles=[c for c in engine(cold,mid2).state.actors[FOE].conditions.values()
              if c.condition_id=='condition:typed.second_furnace_interference' and c.data.get('consecrated')]
    assert bool(profiles)==present_after
    verify(cold,mid2)


@pytest.mark.parametrize('extra',[False,True])
def test_counterflow_higher_authority_uses_optional_actual_extra_payment_and_dc_margin(tmp_path,monkeypatch,extra):
    source=f.PREFIX+'heart_devil_counterflow'
    cold,jid,declare,_=game(tmp_path,monkeypatch,cl=14,foe_cl=17,seed='higher-counterflow-'+str(extra))
    declare('furnace_environment',{'source_rule':'The hostile cultivator’s higher-authority heart-lock tests a Qi activation.',
        'source_cl':17,'source_actor_id':FOE,'subject':OWNER,'activation_save':1,'save_ability':'WIS','save_dc':14},'heart-lock')
    state=cold().journey_state(jid);cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'heart-lock'})
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    used=False
    for _ in range(8):
        start=len(engine(cold,mid).events)
        fuel=engine(cold,mid).state.actors[OWNER].resources[f.DEVIL]
        def choose(p):
            key=p['context']['checkpoint']
            if 'PAYMENT_SHORTFALL' in key:return 'Demon Seed Overdraw'
            if 'seed_reinforcement' in key or 'overflow' in key:return 'Temporary Hit Points'
            if key=='D20_REROLL_SAVE' and (not extra or fuel>=3):return 'USE'
            if 'counterflow_authority' in key and extra:return 'Spend 1 additional'
            if 'counterflow_damage_type' in key:return 'Necrotic'
            return None
        play(cold,tmp_path,mid,'Force Mantle',select=choose)
        e=engine(cold,mid);events=e.events[start:]
        rewritten=[x for x in events if x.event_type=='D20_REWRITTEN' and x.source_definition_id==source]
        if rewritten:
            used=True;result=rewritten[-1].payload['result']
            assert result['modifier']==(6 if extra else 2)
            paid=sum(x.payload['amount'] for x in events if x.event_type=='RESOURCE_SPENT' and x.source_definition_id==source and x.payload.get('resource_id')==f.DEVIL)
            assert paid==(3 if extra else 2)
            backlash=[x for x in events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==source]
            assert bool(backlash)==(result['total']>=19)
            break
        next_owner(cold,tmp_path,mid)
    assert used
    verify(cold,mid)


@pytest.mark.parametrize('restriction',['irresistible','forbids_rerolls'])
def test_counterflow_respects_the_actual_source_owners_printed_restriction(tmp_path,monkeypatch,restriction):
    cold,jid,declare,_=game(tmp_path,monkeypatch,cl=14,foe_cl=14,seed='restricted-'+restriction)
    declare('furnace_environment',{'source_rule':'The scene owner’s explicit restriction on this heart-seal save.',
        'source_cl':14,'source_actor_id':FOE,'subject':OWNER,'activation_save':1,'save_ability':'WIS','save_dc':50,restriction:1},'restricted-seal')
    state=cold().journey_state(jid);cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'restricted-seal'})
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    for _ in range(2):
        prompts=play(cold,tmp_path,mid,'Force Mantle',select=choose_seed)
        assert not any(p['context']['checkpoint']=='D20_REROLL_SAVE' for p in prompts)
        next_owner(cold,tmp_path,mid)
    assert engine(cold,mid).state.actors[OWNER].resources[f.DEVIL]==4
    assert not any(x.event_type=='D20_REWRITTEN' and x.source_definition_id==f.PREFIX+'heart_devil_counterflow' for x in engine(cold,mid).events)
    verify(cold,mid)


@pytest.mark.parametrize('erase_flag',[False,True])
def test_real_compiled_immortal_art_retains_its_printed_minimum_qi(tmp_path,monkeypatch,erase_flag):
    art={'art_id':'tianxia.constructed.immortal_art.second_furnace_mantle','display_name':'Imperial Mantle Immortal Art',
         'source_record_id':'TAL_FORCE_FORCE_MANTLE','path_id':'tianxia.path.qi_cultivation','activation_cp':3,
         'action_surface':{'action_type':'action','dc_basis':'none'}}
    cold,jid,declare,state=game(tmp_path,monkeypatch,cl=10,arts=(art,),seed='immortal-floor-'+str(erase_flag))
    action=next(a for a in state['actors'][OWNER]['bundle']['action_catalog'] if a['display_name']==art['display_name'])
    assert action['parameters']['typed']['immortal_from']=='TAL_FORCE_FORCE_MANTLE'
    if erase_flag:
        declare('cost_profile',{'source_rule':action['source_definition_id'],'quotation':'This declaration does not alter the actual Immortal Art provenance.',
            'classification':{'immortal_art':0}},'attempt-to-erase')
        state=cold().journey_state(jid)
        cold().journey_act(jid,state['revision'],OWNER,'furnace_cost_profile',{'scope':'attempt-to-erase'})
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    prompts=play(cold,tmp_path,mid,art['display_name'],select=choose_seed)
    a=engine(cold,mid).state.actors[OWNER]
    assert a.resources[f.QI]==29 and a.resources[f.CORRUPTION]==1 and a.resources[f.DEVIL]==2
    assert not any('Second Furnace Core:' in str(p) for p in prompts)
    verify(cold,mid)
