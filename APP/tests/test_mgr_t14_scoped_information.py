"""Assigned rows through native acquisition, table commits and cold replay."""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT,sheet as raw_sheet
from tests.r1i_service_support import fixture,candidate,OWNER,FOE
from tests.test_r1i_round3 import resolve,reload
from combat.ext.beauty_adorn_base import SOURCE as ADORN,PRESENT,MEMORY,USED
from combat.ext.ink_base_actions import LIVING,LASH,SUPPLY


def sheet(mids,**kwargs):
    """Acquire source-bound base packages; bases are never learned talents."""
    from canonical_catalog import CanonicalCatalogAuthorityService
    doc=raw_sheet(mids,**kwargs)
    block=doc.get('spheres_and_talents')
    if block:
        catalog=CanonicalCatalogAuthorityService(ROOT)
        packages=[row for sphere in block['sphere_record_ids'] for row in catalog.get_sphere(sphere)['automatic_base_abilities']]
        block['automatic_sphere_component_record_ids']=[r['runtime_component_id'] for r in packages]
        automatic=set(block['automatic_sphere_component_record_ids'])
        block['learned_talent_record_ids']=[r for r in block['learned_talent_record_ids'] if r not in automatic]
        assert all(r['automatic_grant'] and not r['counts_as_talent_choice'] for r in packages)
    return doc


@pytest.fixture(autouse=True)
def source_acquisition(monkeypatch):
    import tests.r1i_service_support as support
    monkeypatch.setattr(support,'sheet',sheet)


def test_lash_declares_type_and_shape_before_roll_cold(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[LASH])
    resolve(combat,mid,send,candidate(table,mid,'Ink Lash',FOE),{'choice:needle.ink_lash_type':'slashing','choice:needle.ink_lash_shape':'painted fang'})
    e=reload(tmp_path,mid)
    declaration=next(x for x in e.events if x.payload.get('brush_shape')=='painted fang')
    attack=next(x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.sequence>declaration.sequence)
    assert declaration.sequence<attack.sequence
    assert any(c.condition_id==SUPPLY for c in e.state.actors[OWNER].conditions.values())
    assert not any(c.condition_id==SUPPLY for c in e.state.actors[FOE].conditions.values())


def test_adorn_one_scoped_check_and_scene_cold(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[ADORN])
    resolve(combat,mid,send,candidate(table,mid,'Adorn the Moment: Advantage on Check',OWNER),{})
    assert any(c.condition_id==PRESENT for c in reload(tmp_path,mid).state.actors[OWNER].conditions.values())
    resolve(combat,mid,send,candidate(table,mid,'Adorn: make a presentation check'),{
        'choice:needle.source_check':'Performance','choice:needle.source_check_purpose':'grace','choice:needle.source_check_subject':OWNER})
    e=reload(tmp_path,mid)
    checks=[x for x in e.events if x.event_type=='CHECK_ROLLED' and x.actor_id==OWNER]
    assert checks[-1].payload['actor']['mode']=='ADVANTAGE'
    assert any(c.condition_id==USED for c in e.state.actors[OWNER].conditions.values())
    assert not any(c.condition_id==PRESENT for c in e.state.actors[OWNER].conditions.values())


def test_adorn_memory_witness_cold(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[ADORN])
    resolve(combat,mid,send,candidate(table,mid,'Adorn the Moment: Visually Memorable',OWNER),{})
    e=reload(tmp_path,mid)
    assert any(c.condition_id==MEMORY and c.data['subject']==OWNER for c in e.state.actors[FOE].conditions.values())
    assert not any('check_mode' in c.data.get('rule',{}) for c in e.state.actors[OWNER].conditions.values())


def test_native_journey_actual_writing_expiry_permanence_wrong_owner(tmp_path,monkeypatch):
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:sheet([LIVING] if pid=='host' else [],cl=10,name=pid))
    arena={'stable_id':'battlefield:ink','display_name':'Writing room','width_squares':8,'height_squares':8,'square_size_ft':5,'terrain_regions':[],'starting_positions':{}}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'room':arena})
    service=CombatService(ROOT,tmp_path);host='actor:factory.host';guest='actor:factory.guest'
    state=service.create_journey(project_ids=['host','guest'],arena_id='room',positions={host:{'x':2,'y':2},guest:{'x':3,'y':2}},base_paces={host:5,guest:5});jid=state['journey_id']
    def act(aid,kind,payload):
        s=CombatService(ROOT,tmp_path);before=s.journey_state(jid)
        return s.journey_act(jid,before['revision'],aid,kind,payload)
    payload={'origin':'brush','form':'map','content':'North gate -> river bridge','permanent':1,'surface':{'x':2,'y':2,'z':0}}
    act(host,'ink_write',payload)
    state=act(host,'ink_write',{**payload,'content':'Temporary route','permanent':0})
    assert len(state['actors'][host]['ink_writings'])==2
    with pytest.raises(ValueError):act(guest,'ink_write',payload)
    state=act(host,'wait',{'seconds':3600})
    assert CombatService(ROOT,tmp_path).journeys.replay(jid)['status']=='PASS'
    assert 'living_ink' not in state['actors'][host]
    assert [r['content'] for r in state['actors'][host]['ink_writings']]==[payload['content']]


@pytest.mark.parametrize('purpose',['other','grace'])
def test_adorn_qualifying_only_and_wrong_recipient(tmp_path,purpose):
    combat,table,mid,send,commit=fixture(tmp_path,[ADORN])
    resolve(combat,mid,send,candidate(table,mid,'Adorn the Moment: Advantage on Check',OWNER),{})
    assert not any('Adorn: make' in a['label'] for a in table.state(mid)['menu']['actions'] if a.get('actor_id')==FOE)
    resolve(combat,mid,send,candidate(table,mid,'Adorn: make a presentation check'),{
        'choice:needle.source_check':'Insight','choice:needle.source_check_purpose':purpose,'choice:needle.source_check_subject':OWNER})
    e=reload(tmp_path,mid);check=next(x for x in reversed(e.events) if x.event_type=='CHECK_ROLLED')
    assert check.payload['actor']['mode']==('ADVANTAGE' if purpose=='grace' else 'NORMAL')
    assert any(c.condition_id==PRESENT for c in e.state.actors[OWNER].conditions.values())==(purpose=='other')


@pytest.mark.parametrize('benefit',['motion','handling','check','space'])
def test_draw_native_paid_qi_then_listen_choose_whole_benefits(tmp_path,benefit):
    from combat.ext.thread_base_line import DRAW,LISTEN,LISTENING,line_rows
    from combat.observer_information import readings
    combat,table,mid,send,commit=fixture(tmp_path,[DRAW,LISTEN])
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    resolve(combat,mid,send,candidate(table,mid,'Draw the Line: Guide (Qi Thread)',FOE),{})
    e=reload(tmp_path,mid)
    assert e.state.actors[OWNER].resources['resource:core.qi']==before-1
    assert line_rows(e,e.state.actors[OWNER])
    resolve(combat,mid,send,candidate(table,mid,'Listen Through Tension'),{
        'choice:needle.thread_listen_line':FOE,'choice:needle.thread_listen_benefit':benefit})
    e=reload(tmp_path,mid)
    assert any(c.condition_id==LISTENING and c.data['benefit']==benefit for c in e.state.actors[OWNER].conditions.values())
    assert not readings(e,e.state.actors[FOE])
    if benefit=='check':
        # The check consumes only its own line-qualified single benefit.
        commit(table.state(mid)['menu']['end_turn']);owner_turn(table,mid,commit,OWNER)
        resolve(combat,mid,send,candidate(table,mid,'Listen: make a check involving the line'),{
            'choice:needle.source_check':'Perception','choice:needle.source_check_purpose':'line','choice:needle.source_check_subject':FOE})
        e=reload(tmp_path,mid)
        check=next(x for x in reversed(e.events) if x.event_type=='CHECK_ROLLED')
        assert check.payload['actor']['mode']=='ADVANTAGE'
        assert not any(c.condition_id==LISTENING for c in e.state.actors[OWNER].conditions.values())
    elif benefit in ('motion','handling'):
        private=readings(e,e.state.actors[OWNER]);assert private[-1]['details'][benefit]==('still' if benefit=='motion' else 'unknown')
    else:
        from combat.senses import pinpoints
        assert pinpoints(e,e.state.actors[OWNER],e.state.actors[FOE])


def test_jester_native_allied_foil_invitation_and_expiry(tmp_path):
    from combat.ext.jester import foil_mark
    from combat.typed_executor import bears_mark
    from combat.observer_information import readings
    combat,table,mid,send,commit=fixture(tmp_path,['JESTER_BASE_SET_THE_SCENE'],allies=[FOE])
    resolve(combat,mid,send,candidate(table,mid,'Set the Scene: Strike the Fool',FOE),{})
    e=reload(tmp_path,mid)
    assert bears_mark(e.state.actors[FOE],OWNER,foil_mark('Strike the Fool'))
    assert any('invitation' in r['details'] for r in readings(e,e.state.actors[FOE]))
    assert not readings(e,e.state.actors[OWNER])
    commit(table.state(mid)['menu']['end_turn']);owner_turn(table,mid,commit,OWNER)
    e=reload(tmp_path,mid)
    assert not bears_mark(e.state.actors[FOE],OWNER,foil_mark('Strike the Fool'))


def test_press_mark_actual_surface_persists_native(tmp_path):
    from combat.ext.ink_base_actions import PRESS,mark_endpoints
    combat,table,mid,send,commit=fixture(tmp_path,[PRESS])
    resolve(combat,mid,send,candidate(table,mid,'Press Mark: object or surface'),{'choice:needle.ink_surface':'$first'})
    e=reload(tmp_path,mid)
    endpoints=mark_endpoints(e,e.state.actors[OWNER])
    assert endpoints and endpoints[0]['position']==e.state.actors[OWNER].position
    assert not mark_endpoints(e,e.state.actors[FOE])


@pytest.mark.parametrize('aura',['soft','graceful','haunting','radiant','refined','tragic','elegant','terrible'])
def test_all_printed_adorn_auras_native_cold(tmp_path,aura):
    combat,table,mid,send,commit=fixture(tmp_path,[ADORN])
    resolve(combat,mid,send,candidate(table,mid,'Adorn the Moment: '+aura,OWNER),{})
    e=reload(tmp_path,mid)
    presentation=next(c for c in e.state.actors[OWNER].conditions.values() if c.condition_id==PRESENT)
    assert presentation.data['aura']==aura and presentation.data['kind']=='aura'
    assert 'rule' not in presentation.data
    assert e.state.actors[OWNER].action_available and not e.state.actors[OWNER].bonus_action_available


def scene_game(tmp_path,monkeypatch,sources,*,pace=5):
    host='actor:factory.host';guest='actor:factory.guest'
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',lambda self,pid:sheet(sources if pid=='host' else [],cl=10,name=pid))
    arena={'stable_id':'battlefield:source','display_name':'Writing room','width_squares':8,'height_squares':8,'square_size_ft':5,'terrain_regions':[],'starting_positions':{}}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'room':arena})
    service=CombatService(ROOT,tmp_path)
    state=service.create_journey(project_ids=['host','guest'],arena_id='room',positions={host:{'x':2,'y':2},guest:{'x':4,'y':2}},base_paces={host:pace,guest:pace})
    jid=state['journey_id']
    def cold():return CombatService(ROOT,tmp_path)
    def act(aid,kind,payload):
        before=cold().journey_state(jid)
        return cold().journey_act(jid,before['revision'],aid,kind,payload)
    return cold,jid,act,host,guest


def test_living_ink_fractional_clock_and_air_guard_native(tmp_path,monkeypatch):
    from fractions import Fraction
    cold,jid,act,host,guest=scene_game(tmp_path,monkeypatch,[LIVING],pace=3)
    act(host,'move',{'path':[{'x':2,'y':3,'z':0}]})
    payload={'origin':'brush','form':'writing','content':'The river rises','permanent':0,'surface':{'x':2,'y':3,'z':0}}
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='actual floor'):
        act(host,'ink_write',{**payload,'surface':{**payload['surface'],'z':1}})
    assert cold().journey_state(jid)==before
    state=act(host,'ink_write',payload)
    ink=state['actors'][host]['living_ink']
    started=cold().journeys.load(jid).clock()
    assert Fraction(ink['expires_num'],ink['expires_den'])==started+3600
    assert cold().journeys.replay(jid)['status']=='PASS'
    state=act(host,'wait',{'seconds':3599})
    assert state['actors'][host]['living_ink']
    state=act(host,'wait',{'seconds':1})
    assert 'living_ink' not in state['actors'][host]
    assert not state['actors'][host]['ink_writings']
    assert cold().journeys.replay(jid)['status']=='PASS'


def test_native_adorn_scene_allowance_requires_actual_owner_boundary(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene_game(tmp_path,monkeypatch,[ADORN])
    offer={'subject':host,'kind':'check','aura':''}
    act(host,'adorn_moment',offer)
    task={'id':'introduction','skill':'Persuasion','ability':'CHA','subject':host,'purpose':'first_impressions','dc':12}
    before=cold().journey_state(jid)
    cold().journey_admit(jid,before['revision'],host,'scene_check_task',task,gm=True,reason='Presenting the courier at the town reception.')
    state=act(host,'scene_check',{'task':'introduction'})
    receipt=next(e for e in reversed(state['events']) if e['kind']=='SCENE_CHECK_ROLLED')
    assert receipt['roll']['mode']=='ADVANTAGE'
    act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='already benefited'):act(host,'adorn_moment',offer)
    assert cold().journey_state(jid)==before
    cold().journey_end_scene(jid,before['revision'],'The reception ends and the next audience begins.')
    state=act(host,'adorn_moment',offer)
    assert state['actors'][host]['scoped_presentations']
    assert cold().journeys.replay(jid)['status']=='PASS'


def test_private_memories_remain_private_after_presentation_expiry(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[ADORN])
    resolve(combat,mid,send,candidate(table,mid,'Adorn the Moment: Visually Memorable',OWNER),{})
    engine=reload(tmp_path,mid)
    private={c.instance_id for a in engine.state.actors.values() for c in a.conditions.values() if c.condition_id==MEMORY}
    receipts={iid for event in engine.events if event.event_type=='SOURCE_PRIVACY_RECORDED' for iid in event.payload['private_condition_ids']}
    assert private and private<=receipts
    from combat.history_feed import concealed_condition_instances
    assert private<=concealed_condition_instances(engine.state.model_dump(mode='json'),engine.events)
    assert all('Remembers a visually memorable subject' not in str(row) for row in table.events(mid,0)['events'])


@pytest.mark.parametrize('source,label',[('INK_BASE_LIVING_INK','Living Ink: from'),('INK_BASE_INK_LASH','Ink Lash'),('INK_BASE_PRESS_MARK','Press Mark')])
def test_body_cannot_infer_restricted_ink_access_from_stamina(tmp_path,source,label):
    combat,table,mid,send,commit=fixture(tmp_path,[source],owner_path='Body Refining',owner_resource='Stamina')
    assert not any(label in row['label'] for row in table.state(mid)['menu']['actions'])
    e=reload(tmp_path,mid)
    assert not any(c.condition_id==SUPPLY for c in e.state.actors[OWNER].conditions.values())


def test_native_living_supply_carries_into_encounter_and_back_without_refresh(tmp_path,monkeypatch):
    from fractions import Fraction
    from combat.tabletop_service import TabletopService
    cold,jid,act,host,guest=scene_game(tmp_path,monkeypatch,[LIVING])
    state=act(host,'living_ink',{'origin':'sleeve'})
    state=act(host,'wait',{'seconds':37})
    result=cold().journey_start_combat(jid,state['revision'],{host:'a',guest:'b'},maximum_rounds=1)
    mid=result['match_id'];table=TabletopService(cold(),tmp_path)
    engine=cold()._load_session(mid).engine
    supplied=next(c for c in engine.state.actors[host].conditions.values() if c.condition_id==SUPPLY)
    assert supplied.data['origin']=='sleeve'
    for _ in range(4):
        menu=table.state(mid)['menu']
        if engine.state.terminal_result is not None:break
        assert table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],0,[])['status']=='COMMITTED'
        engine=cold()._load_session(mid).engine
    session=cold()._load_session(mid)
    assert session.engine.state.terminal_result is not None
    assert session.mechanical.replay()['status']=='PASS'
    before=cold().journey_state(jid)
    state=cold().journey_resume(jid,before['revision'])
    supplied=state['actors'][host]['living_ink']
    remaining=Fraction(supplied['expires_num'],supplied['expires_den'])-cold().journeys.load(jid).clock()
    assert 0<remaining<=3563
    assert cold().journey_state(jid)==state


@pytest.mark.parametrize('proposition',['Strike the Fool','Ignore the Fool','Show Your Hand'])
def test_foil_fulfillment_is_before_actual_committed_roll(tmp_path,proposition):
    from tests.r1i_service_support import SECOND
    source='JESTER_BASE_SET_THE_SCENE'
    combat,table,mid,send,commit=fixture(tmp_path,[source],foe_talents=[LASH])
    resolve(combat,mid,send,candidate(table,mid,'Set the Scene: '+proposition,FOE),{})
    commit(table.state(mid)['menu']['end_turn'])
    owner_turn(table,mid,commit,FOE)
    target=SECOND if proposition=='Ignore the Fool' else OWNER
    before=reload(tmp_path,mid).state.event_sequence
    resolve(combat,mid,send,candidate(table,mid,'Ink Lash',target),{
        'choice:needle.ink_lash_type':'slashing','choice:needle.ink_lash_shape':'cutting stroke'})
    e=reload(tmp_path,mid)
    triggered=[event for event in e.events if event.sequence>before and event.payload.get('proposition')==proposition]
    assert len(triggered)==1
    rolled=next(event for event in e.events if event.sequence>before and event.event_type=='ATTACK_ROLLED' and event.actor_id==FOE)
    assert triggered[0].sequence<rolled.sequence
    assert triggered[0].payload['trigger_source']
    assert not any(event.payload.get('proposition') in {'Strike the Fool','Ignore the Fool','Show Your Hand'}-{proposition} for event in e.events if event.sequence>before)


@pytest.mark.parametrize('accepted,concealed,dc',[(False,False,50),(True,False,50),(False,True,50),(False,False,1)])
def test_press_native_consent_dexterity_concealment_and_cold_history(tmp_path,accepted,concealed,dc):
    from combat.ext.ink_base_actions import PRESS
    from combat.typed_executor import mark_condition_id
    combat,table,mid,send,commit=fixture(tmp_path,[PRESS],owner_dc=dc)
    before=reload(tmp_path,mid).state.actors[OWNER].resources['resource:core.qi']
    resolve(combat,mid,send,candidate(table,mid,'Press Mark',FOE),{
        'choice:needle.ink_accept':'accept' if accepted else None,
        'choice:needle.ink_conceal':'conceal' if concealed else None})
    e=reload(tmp_path,mid)
    marks=[c for c in e.state.actors[FOE].conditions.values() if c.condition_id==mark_condition_id('ink_mark',OWNER)]
    assert bool(marks)==(accepted or dc==50)
    assert any(x.event_type=='SAVE_ROLLED' and x.actor_id==FOE for x in e.events)==(not accepted)
    assert e.state.actors[OWNER].resources['resource:core.qi']==before-int(concealed)
    if marks:
        assert bool(marks[0].data.get('concealed'))==concealed
        if concealed:
            from combat.history_feed import concealed_condition_instances
            assert marks[0].instance_id in concealed_condition_instances(e.state.model_dump(mode='json'),e.events)
    assert not e.state.actors[OWNER].action_available
