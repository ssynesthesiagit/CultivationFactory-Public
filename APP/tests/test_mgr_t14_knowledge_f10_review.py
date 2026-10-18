"""F10 service regressions for native dispatch, retained weather and test modes.

Real learning, isolated stores and cold mechanical replay; no live servers.
"""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.knowledge_inputs_support import (
    OWNER, ALLY, FOE, QI, VENOM, SKY, make, candidates, answers, journey_settle,
)
from tests.test_mgr_t14_knowledge_f6_lifecycle import scene, shroud
from tests.worker2_support import reload, settle, turn


@pytest.mark.parametrize('automatic',[False,True])
def test_qi_journey_selects_native_reading_and_reaches_consent_and_expiry(tmp_path,automatic):
    combat,_,_=make(tmp_path,QI)
    state=scene(combat,automatic=(ALLY,) if automatic else ());jid=state['journey_id']
    # Both legacy contests remain in the catalog; selection must identify the
    # actual effect implementation rather than arbitrarily taking a source ID.
    catalog=combat.journeys.load(jid).state['actors'][OWNER]['bundle']['action_catalog']
    assert sum(a.get('parameters',{}).get('typed',{}).get('source')==QI for a in catalog)>=3
    state=combat.journey_act(jid,state['revision'],OWNER,'information_reading',
        {'source':QI,'subject_id':ALLY,'questions':['qi.bloodied']})
    if not automatic:
        assert state['native_scene_pending']['awaiting_actor_id']==ALLY
        state=journey_settle(combat,jid,state,ALLY,'native_scene_answer',
            {'selection':'USE','option_ids':['open']})
    assert 'native_scene_pending' not in state
    cold=CombatService(ROOT,tmp_path)
    rows=cold.journey_menu(jid,OWNER)['properties']['information']
    assert any(r['details'].get('answers')=={'Is this creature Bloodied?':'No'} for r in rows)
    assert not cold.journey_menu(jid,ALLY)['properties'].get('information')
    assert cold.journey_replay(jid)['status']=='PASS'
    state=cold.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':59})
    assert cold.journey_menu(jid,OWNER)['properties']['information']
    state=cold.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':1})
    assert not CombatService(ROOT,tmp_path).journey_menu(jid,OWNER)['properties'].get('information')
    assert cold.journey_replay(jid)['status']=='PASS'


@pytest.mark.parametrize('ambient,air',[(False,True),(True,True),(False,False)])
def test_immediate_reading_retains_real_combat_gather_on_journey_resume(tmp_path,ambient,air):
    combat,table,_=make(tmp_path,SKY,starting_sign='cold')
    values={'weather.air':air}
    if ambient:
        values.update({'weather.categories':{'wind':1,'precipitation':0,'cold':0,'heat':0,'aridity':0,'storm':0},
            'weather.categories_radius_ft':5280,'weather.origin':['natural'],'weather.origin_radius_ft':300})
    state=scene(combat,values,'scene');jid=state['journey_id']
    state=shroud(combat,state)  # initialize a real native scene before combat
    state=journey_settle(combat,jid,state,OWNER,'scene_turn',{'edge':'end'})
    mid=combat.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:b'},maximum_rounds=2)['match_id']
    turn(table,mid,OWNER)
    gather=next(c for c in candidates(combat,mid,'WEATHER_BASE_GATHER_WEATHER')
        if c.destination and (c.destination.x,c.destination.y)==(4,5))
    settle(table,mid,gather.candidate_id,picks={
        'choice:needle.weather_field_gather_sign':'cold',
        'choice:needle.weather_field_severity_cold':'1','choice:needle.weather_battle_reading':[]})
    settle(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid,OWNER)
    settle(table,mid,candidates(combat,mid,SKY)[0].candidate_id)
    combat_answers=next(r['details']['answers'] for r in reversed(answers(tmp_path,mid))
        if r['details'].get('ability')=='Read the Sky')
    expected=[{'categories':{'cold':1},'origin':'cultivation-made','concentration':1}]
    if air:
        assert combat_answers['Gathered weather in this scene']==expected
    else:
        assert combat_answers=={'Weather':'Unknown: outdoor air access has not been established.'}
    for _ in range(6):
        if reload(tmp_path,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert reload(tmp_path,mid).state.terminal_result is not None
    state=combat.journey_resume(jid,combat.journeys.load(jid).state['revision'])
    cold=CombatService(ROOT,tmp_path)
    state=journey_settle(cold,jid,state,OWNER,'scene_turn',{'edge':'start'})
    state=cold.journey_act(jid,state['revision'],OWNER,'information_weather',{'mode':'immediate'})
    rows=CombatService(ROOT,tmp_path).journey_menu(jid,OWNER)['properties']['information']
    assert rows[-1]['details']['answers']==combat_answers
    if air:assert rows[-1]['details']['answers']['Gathered weather in this scene']==expected
    assert not cold.journey_menu(jid,ALLY)['properties'].get('information')
    assert cold.journey_replay(jid)['status']=='PASS'


@pytest.mark.parametrize('count',[1,3])
def test_venom_fixture_selects_explicit_free_or_paid_mode_without_losing_either(tmp_path,count):
    combat,table,mid=make(tmp_path,VENOM,{'poison.present':True,'poison.kind':'Mineral',
        'poison.timing':'Delayed','poison.antidote':False})
    rows=candidates(combat,mid,VENOM,FOE,count=count)
    assert rows
    engine=reload(tmp_path,mid)
    assert {int(engine.action_catalog[c.source_definition_id].parameters['typed'].get('reading_count',1)) for c in rows}=={count}
    questions=['poison.kind'] if count==1 else ['poison.kind','poison.timing','poison.antidote']
    settle(table,mid,rows[0].candidate_id,picks={'choice:needle.reading_questions':questions})
    result=answers(tmp_path,mid)[-1]['details']['answers']
    assert result['Is poison present?']=='Yes' and result['Poison family']=='Mineral'
    assert len(result)==count+1
    assert reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']==(100 if count==1 else 99)


def test_independent_qi_ingredient_menu_keeps_printed_impurity_question(tmp_path):
    combat,table,mid=make(tmp_path,QI,{'subject.kind':'ingredient','qi.impurity':True},
        subject='object:map.601',objects=[{'id':601,'kind':'custom','material':'wood','x':4,'y':7,'blocks':False}])
    prompts=settle(table,mid,candidates(combat,mid,QI,'object:map.601')[0].candidate_id,
        picks={'choice:needle.reading_questions':'qi.impurity'})
    question=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.reading_questions')
    assert {o['id'] for o in question['choice']['options']}=={
        'qi.nature','qi.expression','qi.impurity','qi.suitable','qi.ward'}
    assert answers(tmp_path,mid)[-1]['details']['answers']=={'Does this meal or ingredient contain Impurity?':'Yes'}
