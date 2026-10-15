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
