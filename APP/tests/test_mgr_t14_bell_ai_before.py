from tests.h1_support import sheet
from tests.worker2_support import fixture,candidate,settle,reload,turn,OWNER,ALLY,FOE
from combat import observer_information as information
from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
P='tianxia.subpath.qi.bell_tower_cultivator.feature.'
ALL=[]

def play(tmp_path,cl=18,features=None,**kw):
    return fixture(tmp_path,[],owner_features=ALL if features is None else features,cl=cl,named=True,**kw)

def cast(combat,table,mid,name,choices):
    c=candidate(combat,mid,name)
    return settle(table,mid,c.candidate_id,picks=choices)

def test_alarm_keeps_human_choices_on_a_native_local_ai_turn(tmp_path):
    combat,table,mid=play(tmp_path,features=[bell.ALARM],ask=False,
        modes={OWNER:'MANUAL',ALLY:'MANUAL',FOE:'LOCAL_AUTO'})
    turn(table,mid,FOE)
    prompts=settle(table,mid,None,auto=True,picks={
        'choice:needle.bell_ring_alarm':'ring',
        'choice:needle.bell_alarm_recipient':[ALLY],
        'choice:needle.bell_alarm_benefit':'temp_hp'})
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[bell.QI]==98
    assert engine.state.actors[ALLY].temporary_hp==4
    assert any(p['context']['reaction_source_id']=='choice:needle.bell_alarm_benefit'
        and p['context']['reactor_id']==ALLY for p in prompts)
