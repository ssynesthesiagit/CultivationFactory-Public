"""Sol findings F1–F6: native controllers, scene actions and cold continuation.

All transports are local deterministic fixtures. No browser/model connection.
F5/F6 additionally exercise the repaired original acceptance files in this lane.
"""
import importlib
import json
import pytest
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map,to_battlefield
from combat.ext.thread_base_line import DRAW,LISTEN,LISTENING,line_rows,grants
from combat.ext.ink_base_actions import PRESS,LIVING,mark_endpoints
from combat.ext.beauty_adorn_base import SOURCE as ADORN
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture,candidate,force_ai_candidate,OWNER,FOE
from tests.test_r1i_round3 import resolve,reload
from tests.test_mgr_t14_scoped_information import sheet,source_acquisition  # noqa: F401


def scene(tmp_path,monkeypatch,*,wall=False,cover=False,extra_sources=()):
    host='actor:factory.host';guest='actor:factory.guest'
    monkeypatch.setattr('combat.journey.secrets.token_hex',lambda n:'14'*n)
    def document(self,pid):
        doc=sheet([DRAW,LISTEN,PRESS,LIVING,*extra_sources] if pid=='host' else [],cl=10,dc=50,name=pid)
        doc['ability_scores_and_statistics']['technique_attack_bonus']=1000
        doc['equipment']=[{'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.jian','quantity':1}]}}]
        return doc
    monkeypatch.setattr(CombatService,'_factory_owner_sheet',document)
    arena=to_battlefield(normalize_map({'width_squares':8,'height_squares':8,
        'objects':[{'id':1,'kind':'crate','x':2,'y':3}],
        'walls':[{'shape':'rect','points':[[3,0],[3,7]],'filled':True}] if wall else [],
        'terrain':[{'type':'SIMPLE_COVER','cells':[[3,2],[3,3]]}] if cover else []}))
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self:{'room':arena})
    def cold():return CombatService(ROOT,tmp_path)
    state=cold().create_journey(project_ids=['host','guest'],arena_id='room',
        positions={host:{'x':2,'y':2},guest:{'x':4 if wall or cover else 3,'y':2}},
        base_paces={host:3600,guest:3600})
    jid=state['journey_id']
    def act(aid,kind,payload):
        result=cold().journey_act(jid,cold().journey_state(jid)['revision'],aid,kind,payload)
        # This helper resolves native scene prompts as the named controller,
        # just like the table resolve() helper. Dedicated transport regressions
        # inspect pauses without using this convenience function.
        for _ in range(40):
            state=cold().journeys.load(jid).state
            pending=state.get('scene_pending')
            if not pending:return result
            request=pending['request'];spec=request.get('extension_choice') or {}
            options=spec.get('preferred_option_ids') or spec.get('option_ids') or []
            picked=options[:max(1,spec.get('minimum_selections',1))]
            result=cold().journey_act(jid,state['revision'],request['reactor_id'],'scene_choice',
                {'selection':'USE' if picked or not spec else 'DECLINE','option_ids':picked,'spend':0})
        raise AssertionError('Too many native scene choices.')
    return cold,jid,act,host,guest


def draw(cold,jid,act,host,guest,effect='Guide',medium='mundane'):
    from combat.ext.material_ledger import holdings
    stock=next(iter(holdings(cold().journeys.load(jid),host))) if medium=='mundane' else ''
    payload={'subject':guest,'medium':medium,'stock':stock,'effect':effect,'anchor':host,'item':''}
    for attempt in range(4):
        act(host,'thread_draw_line',payload)
        state=cold().journeys.load(jid).state
        lines=state['actors'][host].get('scene_thread_lines',[])
        if lines:return lines[-1]
        act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    raise AssertionError('The deterministic native Thread attack never hit.')


def native_events(state):
    return [json.loads(e['native']) for e in state['events'] if e['kind']=='SOURCE_NATIVE_RESOLVED']


def test_f1_ai_uses_presentation_check_and_retains_all_choices(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[ADORN])
    resolve(combat,mid,send,candidate(table,mid,'Adorn the Moment: Advantage on Check',OWNER),{})
    cid=candidate(table,mid,'Adorn: make a presentation check')
    force_ai_candidate(combat,mid,OWNER,cid)
    resolve(combat,mid,send,cid,{'choice:needle.source_check':'Performance',
        'choice:needle.source_check_purpose':'grace','choice:needle.source_check_subject':OWNER},auto=True)
    e=reload(tmp_path,mid)
    checks=[r for r in e.events if r.event_type=='CHECK_ROLLED' and r.actor_id==OWNER]
    assert checks and checks[-1].payload['actor']['mode']=='ADVANTAGE'
    assert checks[-1].payload['subject']==OWNER
    action=next(a for a in e.action_catalog.values() if a.display_name=='Adorn: make a presentation check')
    assert not action.parameters.get('player_only')
    row=next(r for r in action.parameters['typed']['effects'] if r['type']=='source_check')
    assert set(row['checks'])=={'Performance','Persuasion','Acrobatics','Insight'}


def test_f1_ai_line_response_records_its_own_decision_cold(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[DRAW],foe_talents=[])
    resolve(combat,mid,send,candidate(table,mid,'Draw the Line: Guide (Qi Thread)',FOE),{})
    commit(table.state(mid)['menu']['end_turn'])
    for _ in range(5):
        if table.state(mid)['menu']['actor_id']==FOE:break
        commit(table.state(mid)['menu']['end_turn'])
    cid=candidate(table,mid,'Thread Line: ignoring')
    force_ai_candidate(combat,mid,FOE,cid)
    resolve(combat,mid,send,cid,{'choice:needle.thread_response':'$first'},auto=True)
    e=reload(tmp_path,mid)
    assert line_rows(e,e.state.actors[OWNER])[0][2].data['thread_handling']=='ignoring'


@pytest.mark.parametrize('medium',['mundane','qi'])
def test_f2_scene_wall_rejects_before_payment_or_roll(tmp_path,monkeypatch,medium):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch,wall=True)
    before=cold().journeys.load(jid).state
    from combat.gate2_rolls import DeterministicRollAuthority
    monkeypatch.setattr(DeterministicRollAuthority,'d20',lambda *a,**k:pytest.fail('An impossible scene target reached a roll.'))
    with pytest.raises(ValueError,match='known|physical|reachable'):
        draw(cold,jid,act,host,guest,'Trip',medium)
    assert cold().journeys.load(jid).state==before


def test_f2_native_scene_resolution_keeps_the_accepted_remembered_aim(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch)
    from combat.scene_resolution import engine_for,candidates,commit
    from combat.ext.ability_source import mechanic_of
    from combat.ext.material_ledger import holdings
    from combat.gate2_runtime_models import Position
    session=cold().journeys.load(jid);native=engine_for(session)
    action=next(a for a in native.action_catalog.values() if a.owner_id==host and mechanic_of(a)==DRAW
        and a.parameters['typed'].get('option_label')=='Guide' and not a.parameters.get('thread_twin')
        and not a.parameters.get('draw_attack_replacement') and not a.parameters.get('thread_weapon_source'))
    candidate=next(c for c in candidates(native,host,action) if c.target_ids==(guest,) and not c.metadata.get('effect_origin'))
    previous=native.state.actors[guest].position.model_copy(deep=True)
    candidate=candidate.model_copy(update={'destination':previous,'metadata':{**candidate.metadata,'target_knowledge':'LAST_OBSERVED'}})
    # Simulate the committed aim becoming empty before resolution, as a native
    # defensive relocation can do. This is adapter coverage in addition to the
    # real journey wall-admission regressions above.
    native.state.actors[guest].position=Position(x=4,y=2,z=0)
    material=next(iter(holdings(session,host)))
    commit(session,native,host,action,candidate,{
        (host,'choice:needle.thread_stock'):[material],(host,'choice:needle.thread_visibility'):['visible']})
    missed=next(e for e in native.events if e.event_type=='ATTACK_LOCATION_MISSED')
    assert missed.trigger_or_intent_id.startswith('scene:')
    assert not line_rows(native,native.state.actors[host])
    assert native._active_intent is None and native._active_candidate is None


@pytest.mark.parametrize('effect',['Snare','Trip','Guide'])
def test_f3_scene_thread_and_listen_cross_encounter_and_cold_reload(tmp_path,monkeypatch,effect):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch)
    line=draw(cold,jid,act,host,guest,effect)
    act(host,'thread_listen',{'line':line['id'],'benefit':'space'})
    session=cold().journeys.load(jid)
    # Source setup itself is tested before combat's first real turn may expire
    # a source-start effect. It defers no clocks in the actual created encounter.
    from combat.scene_resolution import engine_for
    native=engine_for(session)
    assert line_rows(native,native.state.actors[host])
    assert any(c.condition_id==LISTENING for c in native.state.actors[host].conditions.values())
    if effect=='Snare':assert any(m.target_field=='speed_ft' and m.value==-10 for m in native.state.actors[guest].modifiers.values())
    if effect=='Trip':assert any(c.condition_id=='condition:typed.prone' for c in native.state.actors[guest].conditions.values())
    if effect=='Guide':assert grants(native.state.actors[guest],host)
    result=cold().journey_start_combat(jid,session.state['revision'],{host:'a',guest:'b'})
    loaded=cold()._load_session(result['match_id'])
    assert line_rows(loaded.engine,loaded.engine.state.actors[host])
    assert loaded.mechanical.replay()['status']=='PASS'


@pytest.mark.parametrize('target',['creature','object','item','surface'])
def test_f3_scene_mark_retains_real_endpoint_in_encounter(tmp_path,monkeypatch,target):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch)
    payload={'subject':guest if target=='creature' else '',
        'surface':{} if target=='creature' else {'x':2,'y':2,'z':0},'conceal':0}
    if target=='item':
        from combat.journey_equipment import held
        item=held(cold().journeys.load(jid),host)[0]
        payload['surface']={'kind':'item','actor_id':host,'item_key':item['key']}
    if target=='object':payload.update(subject='object:map.1',surface={})
    act(host,'ink_press_mark',payload)
    before=cold().journeys.load(jid).state
    result=cold().journey_start_combat(jid,before['revision'],{host:'a',guest:'b'})
    loaded=cold()._load_session(result['match_id'])
    assert mark_endpoints(loaded.engine,loaded.engine.state.actors[host])
    assert loaded.mechanical.replay()['status']=='PASS'


def test_f3_object_line_rebinds_its_mark_and_listen_after_cold_encounter(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch)
    line=draw(cold,jid,act,host,'object:map.1','Guide')
    act(host,'thread_listen',{'line':line['id'],'benefit':'check'})
    state=cold().journeys.load(jid).state
    result=cold().journey_start_combat(jid,state['revision'],{host:'a',guest:'b'})
    loaded=cold()._load_session(result['match_id'])
    lines=line_rows(loaded.engine,loaded.engine.state.actors[host])
    assert any(subject=='object:map.1' for subject,_,_ in lines)
    ids={c.instance_id for _,_,c in lines}
    assert any(c.condition_id==LISTENING and c.data.get('line_id') in ids for c in loaded.engine.state.actors[host].conditions.values())
    assert loaded.mechanical.replay()['status']=='PASS'


def test_f4_object_guide_spends_only_on_the_next_real_object_roll(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch)
    draw(cold,jid,act,host,'object:map.1','Guide')
    from combat.ext.scoped_continuation import records
    from combat.ext.thread_base_line import OBJECT_GUIDE
    assert any(json.loads(r['native']).get('condition_id')==OBJECT_GUIDE for r in records(cold().journeys.load(jid),host))
    act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    draw(cold,jid,act,host,'object:map.1','Snare')
    assert all(json.loads(r['native']).get('condition_id')!=OBJECT_GUIDE for r in records(cold().journeys.load(jid),host))
    attacks=[e for e in native_events(cold().journeys.load(jid).state) if e['event_type']=='ATTACK_ROLLED' and 'object:map.1' in e.get('target_ids',[])]
    assert len(attacks)>=2 and attacks[-1]['payload']['cover_bonus']==0


def test_f3_continuation_keeps_existing_free_qi_option_reachable(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch,
        extra_sources=['tianxia.talent.thread.qi_thread_scripture'])
    draw(cold,jid,act,host,guest,medium='qi')
    before=cold().journeys.load(jid).state['actors'][host]['resources']['resource:core.qi']
    act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    draw(cold,jid,act,host,guest,medium='qi')
    assert cold().journeys.load(jid).state['actors'][host]['resources']['resource:core.qi']==before


@pytest.mark.parametrize('benefit',['motion','handling','space'])
def test_f4_scene_listen_has_private_cold_consumer(tmp_path,monkeypatch,benefit):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch)
    line=draw(cold,jid,act,host,guest)
    act(host,'thread_listen',{'line':line['id'],'benefit':benefit})
    if benefit=='motion':act(guest,'move',{'path':[{'x':4,'y':2,'z':0}]})
    if benefit=='handling':
        line=cold().journeys.load(jid).state['actors'][host]['scene_thread_lines'][0]
        act(guest,'thread_line_response',{'line':line['id'],'handling':'holding'})
    own=cold().journey_state(jid,viewer_id=host)
    other=cold().journey_state(jid,viewer_id=guest)
    assert own['information'][-1]['details']==({'motion':'farther'} if benefit=='motion' else {'handling':'holding'} if benefit=='handling' else {'position':{'x':3,'y':2,'z':0}})
    assert not other.get('information')
    assert all(e['kind']!='SOURCE_NATIVE_RESOLVED' for e in other['events'] if e['actor_id']==host)
    assert cold().journeys.replay(jid)['status']=='PASS'


def test_f4_scene_guide_consumes_on_next_native_roll(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch,cover=True)
    draw(cold,jid,act,host,guest,'Guide')
    act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    draw(cold,jid,act,host,guest,'Snare')
    attacks=[e for e in native_events(cold().journeys.load(jid).state) if e['event_type']=='ATTACK_ROLLED']
    assert attacks[0]['payload']['cover_bonus']==2
    assert attacks[-1]['payload']['cover_bonus']==0


def test_f5_portable_acceptance_module_collects_without_private_helper():
    module=importlib.import_module('tests.test_fact_consent_admission')
    assert callable(module.test_second_source_native_consent_privacy_expiry_and_refusal)


def test_f4_space_uses_line_lifetime_and_never_grants_sight(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch)
    line=draw(cold,jid,act,host,guest)
    act(host,'thread_listen',{'line':line['id'],'benefit':'space'})
    state=cold().journeys.load(jid).state
    grant=state['actors'][host]['scene_listen']
    assert 'expires_on' not in grant
    assert 'no sight' in cold().journey_state(jid,viewer_id=host)['information'][0]['label']
    act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    act(host,'scene_turn',{'edge':'end'})
    assert not cold().journey_state(jid,viewer_id=host).get('information')


def test_f4_raw_line_storage_never_bypasses_listen_information_choices(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch)
    draw(cold,jid,act,host,guest,medium='qi')
    for aid in (host,guest):
        view=cold().journey_state(jid,viewer_id=aid)
        assert not view.get('information')
        assert all(not {'motion','handling','position'}.intersection(row) for actor in view['actors'].values() for row in actor.get('scene_thread_lines',[]))
        encoded=json.dumps(view)
        assert all(key not in encoded for key in ('thread_path','thread_motion','thread_handling','SOURCE_NATIVE_RESOLVED'))
    assert cold().journeys.replay(jid)['status']=='PASS'


def test_native_scene_adapter_defers_turns_and_declarations_are_scoped(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch)
    from combat.scene_resolution import engine_for
    from combat.ext.needle import declared_choices,ask
    native=engine_for(cold().journeys.load(jid))
    assert all(a.turns_started==0 for a in native.state.actors.values())
    assert not native.rolls
    assert not any(e.event_type=='TURN_STARTED' for e in native.events)
    actor=native.state.actors[host]
    def choose(who=actor):return ask(native,None,'native-scene-test',who,'choice:test',['first','second'])
    with declared_choices(native,{(host,'choice:test'):['second']}):
        assert choose()==['second']
        assert choose(native.state.actors[guest])==['first']
    assert choose()==['first']
    with declared_choices(native,{(host,'choice:test'):['invented']}):
        with pytest.raises(ValueError,match='currently legal'):choose()


def test_f6_writing_setup_and_permanence_reach_actual_assertions(tmp_path,monkeypatch):
    from tests.test_mgr_t14_scoped_information import test_native_journey_actual_writing_expiry_permanence_wrong_owner
    test_native_journey_actual_writing_expiry_permanence_wrong_owner(tmp_path,monkeypatch)


def test_player_guidance_matches_automatic_harmful_effect_trigger():
    records=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    row=records['JESTER_BASE_SET_THE_SCENE']
    assert 'does not yet handle this trigger automatically' not in json.dumps(row)
    from combat.ext.thread_base_line import listen_label
    text=listen_label('check')
    assert all(term in text for term in ('one','Insight','Perception','Sleight of Hand','end of your next turn','no CP'))
