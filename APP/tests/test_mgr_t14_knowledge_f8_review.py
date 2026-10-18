"""F8 review regressions: repeat entry clock, complete labels and hook contracts.

Services and native learning use isolated stores. No live servers or browsers.
"""
from pathlib import Path

import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.knowledge_inputs_support import OWNER, ALLY, QI, TRACE, VESSEL, VENOM, METAL, make, source, journey_settle
from tests.test_mgr_t14_knowledge_f6_lifecycle import scene
from tests.worker2_support import reload, settle


@pytest.mark.parametrize('elapsed',[0,18])
def test_qi_second_combat_entry_uses_destination_round_and_slot(tmp_path,elapsed):
    combat,table,_=make(tmp_path,QI)
    state=scene(combat);jid=state['journey_id']
    state=journey_settle(combat,jid,state,OWNER,'information_reading',
        {'source':QI,'subject_id':ALLY,'questions':['qi.bloodied']})
    first=combat.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:b'},maximum_rounds=3)['match_id']
    for _ in range(8):
        if reload(tmp_path,first).state.terminal_result is not None:break
        settle(table,first,table.state(first)['menu']['end_turn'])
    terminal=reload(tmp_path,first)
    assert terminal.state.terminal_result is not None and terminal.state.round_number>1
    state=combat.journey_resume(jid,combat.journeys.load(jid).state['revision'])
    cold=CombatService(ROOT,tmp_path)
    state=cold.journey_act(jid,state['revision'],OWNER,'scene_turn',{'edge':'start'})
    previous=set(cold.journeys.load(jid).state.get('knowledge_reading_deadlines',{}))
    state=journey_settle(cold,jid,state,OWNER,'information_reading',
        {'source':QI,'subject_id':ALLY,'questions':['qi.bloodied']})
    deadlines=cold.journeys.load(jid).state['knowledge_reading_deadlines']
    created=set(deadlines)-previous
    assert created and all(deadlines[i]['expires_at']-state['seconds']==60 for i in created)
    if elapsed:
        state=cold.journey_act(jid,state['revision'],OWNER,'wait',{'seconds':elapsed})
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'
    second=cold.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:b'},maximum_rounds=12)['match_id']
    expiry_round=1+(60-elapsed)//6
    engine=reload(tmp_path,second)  # cold load also verifies mechanical replay
    assert engine.state.round_number==1 and engine.state.current_slot_index==0
    assert created<=set(engine.state.actors[OWNER].conditions)
    assert {engine.state.actors[OWNER].conditions[i].expires_on for i in created}=={f'START_OF_SLOT_AT:{expiry_round}:0'}
    # Survive every earlier slot, then actually expire at the first slot of
    # the new combat's deadline round, independent of the previous fight.
    for _ in range(24):
        engine=reload(tmp_path,second)
        if engine.state.round_number>=expiry_round:break
        assert created<=set(engine.state.actors[OWNER].conditions)
        settle(table,second,table.state(second)['menu']['end_turn'])
    engine=reload(tmp_path,second)
    assert (engine.state.round_number,engine.state.current_slot_index)==(expiry_round,0)
    assert not created.intersection(engine.state.actors[OWNER].conditions)
    assert not created.intersection(engine.state.actors[ALLY].conditions)


@pytest.mark.parametrize('row,ability,timing,values',[
    (QI,'Taste the Qi','Bonus Action',{}),
    (TRACE,'Read the Trace','Action',{'subject.kind':'inscription'}),
    (VESSEL,'Read the Vessel','Study Action or 1 minute of examination',{}),
    (VENOM,'Appraise the Venom','Action',{}),
    (METAL,'Metal Appraisal','Study or Search Action',{'metal.bearing':True}),
])
def test_journey_examinations_name_ability_each_target_modes_and_cost(tmp_path,row,ability,timing,values):
    combat,_,_=make(tmp_path,row)
    state=combat.create_journey(project_ids=[a.removeprefix('actor:factory.') for a in (OWNER,ALLY)],
        arena_id='battlefield:map.builtin-sect-trial-platform',
        positions={OWNER:{'x':4,'y':5},ALLY:{'x':4,'y':6}},base_paces={OWNER:5,ALLY:5},
        source_inputs=[source(a,values) for a in (OWNER,ALLY)] if values else None)
    jid=state['journey_id']
    menu=CombatService(ROOT,tmp_path).journey_menu(jid,OWNER)
    options=[o for o in menu['options'] if o['kind']=='information_reading' and o['payload']['source']==row]
    assert {o['payload']['subject_id'] for o in options}=={OWNER,ALLY}
    assert len({o['label'] for o in options})==2
    for option in options:
        name='Wren' if option['payload']['subject_id']==OWNER else 'Tobin'
        assert all(text in option['label'] for text in (ability,name,timing,'no CP'))
        assert OWNER not in option['label'] and ALLY not in option['label']
        assert option['questions'] and option['modes']
        if row==VENOM:assert '1 CP for three facts' in option['label']
    if row==VESSEL:
        procedures=[o for o in menu['options'] if o['kind']=='native_scene_procedure'
            and '#inventory' not in o['payload']['action_id'] and '#internal' not in o['payload']['action_id']]
        assert {o['payload']['subject_id'] for o in procedures}=={OWNER,ALLY}
        assert len({o['label'] for o in procedures})==2
        for option in procedures:
            name='Wren' if option['payload']['subject_id']==OWNER else 'Tobin'
            assert all(text in option['label'] for text in (ability,name,'60 seconds of examination','no CP'))
    assert CombatService(ROOT,tmp_path).journey_replay(jid)['status']=='PASS'


def test_shared_journey_and_history_hooks_have_extension_contracts():
    # Guard the integration reference, not the current number of subscribers.
    # A new provider must find the arguments and composition/privacy rules here.
    text=(Path(__file__).resolve().parents[1]/'combat/ext/__init__.py').read_text()
    contracts=text.split('# Additional journey/privacy contracts',1)[-1]
    for signature in (
        'journey_step_surcharge(session,actor_id,old_position,next_position)',
        'journey_pace_ratio(session,actor_id)', 'journey_view(state,viewer_id)',
        'journey_shared_fields()', 'journey_persistent_fields()',
        'journey_actor_restored(session,actor_id)',
        'journey_admission(session,actor_id,kind,payload,reason)',
        'journey_scene_end(session,previous_scene_id,next_scene_id)',
        'presentation_hidden_history_conditions(events)',
    ):
        assert '# '+signature+' -> ' in contracts, signature
    assert 'default-inert without subscribers' in contracts
