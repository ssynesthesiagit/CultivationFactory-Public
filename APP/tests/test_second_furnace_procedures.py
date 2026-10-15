"""Actual acquired organ procedures, native time, consent and persistent prices."""
import pytest
from tests.test_second_furnace_native import game,fight,engine,play,turn,choose_seed,verify,OWNER,FOE,f


def procedure(cold,jid,*,outcome='removed',operator=OWNER,complications=(),scope='operation'):
    state=cold().journey_state(jid)
    p={'source_rule':'The physician’s surgical second-furnace procedure','quotation':'Remove or reconstruct the cultivated organ over 60 seconds; a failed removal loses 2 maximum Qi.',
       'method':'surgical','operator':operator,'source_cl':6,'range_ft':5,'duration_seconds':60,'outcome':outcome,
       'requires_consent':1,'consent_scope':'patient','complications':list(complications)}
    if operator!=OWNER:p['operator_consent_scope']='operator'
    state=cold().journey_world_fact(jid,state['revision'],{'source':f.PARENT,'subject':OWNER,'kind':'organ_procedure',
        'scope':scope,'value':p,'expires_at':state['seconds']+3600,'readers':[]})
    return state,state['fact_consent_admission'][-1]['receipt_id']


def consent(cold,jid,receipt,*,operator=OWNER,who=OWNER):
    state=cold().journey_state(jid)
    value={'procedure_receipt':receipt,'operator':operator,'accepted':1} if who==OWNER else {'procedure_receipt':receipt,'patient':OWNER,'accepted':1}
    return cold().journey_act(jid,state['revision'],who,'declare_fact',{'source':f.PARENT,'subject':who,
        'kind':'organ_consent' if who==OWNER else 'organ_operator_consent','scope':'patient' if who==OWNER else 'operator',
        'value':value,'expires_at':state['seconds']+3600,'readers':[] if who==OWNER else [OWNER]})


@pytest.mark.parametrize('operator',[OWNER,FOE])
def test_native_organ_removal_needs_exact_consent_and_reconstruction_restores_play(tmp_path,monkeypatch,operator):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=6,foe_cl=6,seed='organ-'+operator)
    state,receipt=procedure(cold,jid,operator=operator)
    assert any(o['kind']=='furnace_organ' for o in cold().journey_menu(jid,OWNER)['options'])
    with pytest.raises(ValueError,match='own controller'):cold().journey_act(jid,state['revision'],OWNER,'furnace_organ',{'scope':'operation'})
    assert cold().journey_state(jid)==state
    state=consent(cold,jid,receipt,operator=operator)
    if operator!=OWNER:
        with pytest.raises(ValueError,match='operator’s own controller'):cold().journey_act(jid,state['revision'],OWNER,'furnace_organ',{'scope':'operation'})
        state=consent(cold,jid,receipt,operator=operator,who=operator)
    before=state['seconds']
    state=cold().journey_act(jid,state['revision'],OWNER,'furnace_organ',{'scope':'operation'})
    assert state['seconds']==before+60
    with pytest.raises(ValueError,match='already been completed'):cold().journey_act(jid,state['revision'],OWNER,'furnace_organ',{'scope':'operation'})
    mid=fight(cold,jid,maximum_rounds=1);turn(cold,tmp_path,mid,OWNER)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert f.condition(a,f.ORGAN).data['removed']==1
    assert not f.condition(a,f.ORGAN).data['information_profile']['tags']
    from combat.senses import perception
    assert not any(r.get('source_id')==f.PREFIX+'demon_seed_overdraw' for r in perception(e,a).get('information',[]))
    prompts=play(cold,tmp_path,mid,'Force Mantle')
    assert not any('Demon Seed Overdraw' in str(p) for p in prompts)
    for _ in range(3):
        if engine(cold,mid).state.terminal_result:break
        play(cold,tmp_path,mid,end=True)
    verify(cold,mid)
    state=cold().journey_state(jid);state=cold().journey_resume(jid,state['revision'])
    state,receipt=procedure(cold,jid,outcome='reconstructed',scope='rebuild')
    state=consent(cold,jid,receipt)
    state=cold().journey_act(jid,state['revision'],OWNER,'furnace_organ',{'scope':'rebuild'})
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    prompts=play(cold,tmp_path,mid,'Force Mantle',select=choose_seed)
    assert any('Demon Seed Overdraw' in str(p) for p in prompts)
    assert engine(cold,mid).state.actors[OWNER].resources[f.CORRUPTION]==1
    verify(cold,mid)


def test_failed_removal_maximum_qi_loss_persists_through_rest_and_real_combat(tmp_path,monkeypatch):
    cold,jid,_,state=game(tmp_path,monkeypatch,cl=6,seed='failed-removal')
    before=next(r['maximum'] for r in state['actors'][OWNER]['bundle']['actor_template']['resources'] if r['resource_id']==f.QI)
    state,receipt=procedure(cold,jid,outcome='failed',complications=[{'kind':'maximum_qi_loss','amount':2,'details':'Surgical damage to the primary reservoir'}])
    state=consent(cold,jid,receipt)
    state=cold().journey_act(jid,state['revision'],OWNER,'furnace_organ',{'scope':'operation'})
    state=cold().journey_act(jid,state['revision'],OWNER,'long_rest',{})
    assert next(r['maximum'] for r in state['actors'][OWNER]['bundle']['actor_template']['resources'] if r['resource_id']==f.QI)==before-2
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    e=engine(cold,mid);a=e.state.actors[OWNER]
    assert a.resource_maximums[f.QI]==before-2 and not f.condition(a,f.ORGAN).data['removed']
    play(cold,tmp_path,mid,'Force Mantle',select=choose_seed)
    verify(cold,mid)
