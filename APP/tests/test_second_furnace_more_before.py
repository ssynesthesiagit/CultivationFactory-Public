import pytest
from tests.test_second_furnace_native import game,fight,turn,play,engine,choose_seed,verify,OWNER,FOE,f

def test_native_qi_subpath_acquisition_preserves_an_existing_other_path_grant(tmp_path,monkeypatch):
    body='tianxia.subpath.body.nine_star_meridian_body.feature.star_lit_acupoints'
    paths={'path_record_ids':['tianxia.path.qi_cultivation','tianxia.path.body_refining'],
        'paths':[{'path_id':'tianxia.path.qi_cultivation','attainment':18},{'path_id':'tianxia.path.body_refining','attainment':3}],
        'source_granted_subpath_feature_record_ids':[body]}
    cold,jid,_,state=game(tmp_path,monkeypatch,initial_paths=paths,seed='retained-other-path')
    import json
    native=state['actors'][OWNER]['source_states'][f.PARENT]
    granted=json.loads(native['acquired_sheet'])['path_and_subpath']['source_granted_subpath_feature_record_ids']
    assert granted==[body,*[f.PREFIX+n for n in f.FEATURES]]
    mid=fight(cold,jid)
    assert any(r.get('feature_id')==body for r in engine(cold,mid).typed_passive_rows.get(OWNER,[]))
    verify(cold,mid)

def test_ordinary_activation_consumes_actual_interruption_and_cannot_rearm_on_continuation(tmp_path,monkeypatch):
    cold,jid,declare,_=game(tmp_path,monkeypatch,cl=6,foe_cl=6,seed='ordinary-interruption')
    declare('furnace_environment',{'source_rule':'The hostile exorcist’s seal suppresses the second furnace on its next Qi activation.',
        'source_cl':6,'source_actor_id':FOE,'subject':OWNER,'anti_daemonic':1,'second_suppressed':1,'interrupt_next_activation':1},'seal',seconds=120)
    state=cold().journey_state(jid);cold().journey_act(jid,state['revision'],OWNER,'furnace_environment',{'scope':'seal'})
    mid=fight(cold,jid,maximum_rounds=1);turn(cold,tmp_path,mid,OWNER)
    play(cold,tmp_path,mid,'Force Mantle')  # actual ordinary payment, with no Overdraw
    e=engine(cold,mid);a=e.state.actors[OWNER]
    profile=next(c for c in a.conditions.values() if c.condition_id=='condition:typed.second_furnace_interference')
    assert profile.data['interrupt_next_activation']==0
    assert a.resources[f.CORRUPTION]==0 and a.resources[f.DEVIL]==0
    assert sum(x.payload.get('kind')=='second_furnace_interruption' for x in e.events)==1
    for _ in range(3):
        if engine(cold,mid).state.terminal_result:break
        play(cold,tmp_path,mid,end=True)
    verify(cold,mid)
    state=cold().journey_state(jid)
    state=cold().journey_resume(jid,state['revision'],effect_resolutions={OWNER:'The owner voluntarily releases Force Mantle Concentration at the end of this encounter.'})
    stored=state['actors'][OWNER]['source_states'][f.PARENT]['environment'][0]
    assert stored['interrupt_next_activation']==0 and stored['expires_at']==114
    mid2=fight(cold,jid);turn(cold,tmp_path,mid2,OWNER)
    profile=next(c for c in engine(cold,mid2).state.actors[OWNER].conditions.values() if c.condition_id=='condition:typed.second_furnace_interference')
    assert profile.data['interrupt_next_activation']==0
    prompts=play(cold,tmp_path,mid2,'Force Mantle')
    assert not any('Demon Seed Overdraw' in str(p) for p in prompts)
    assert not any(x.payload.get('kind')=='second_furnace_interruption' for x in engine(cold,mid2).events)
    verify(cold,mid2)
