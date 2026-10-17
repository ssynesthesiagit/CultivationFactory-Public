"""F3 service regressions: health, private mirrors, complete attacks and Adorn.

Native acquisition and cold services only; no browser or live model clients.
"""
import json
import pytest
from combat.scene_resolution import engine_for
from combat.ext.ink_base_actions import LASH
from combat.ext.beauty_adorn_base import SOURCE as ADORN,PRESENT,USED
from combat.ext.special_attacks import FLAG,REST
from tests.test_mgr_t14_information_review import scene,draw,native_events
from tests.test_mgr_t14_scoped_information import source_acquisition  # noqa: F401


@pytest.fixture(autouse=True)
def source_fingerprint(capsys):
    import hashlib
    from tests.h1_support import ROOT
    paths=['combat/ext/__init__.py','combat/ext/beauty_adorn_base.py',
        'combat/ext/scene_native.py','combat/ext/scoped_continuation.py',
        'combat/ext/scoped_information_scene.py','combat/gate2_engine.py',
        'combat/journey_equipment.py','combat/scene_resolution.py',
        'tests/test_mgr_t14_information_fix3.py']
    digest=hashlib.sha256()
    for path in sorted(paths):digest.update(path.encode()+b'\0'+(ROOT/path).read_bytes()+b'\0')
    with capsys.disabled():print('SCOPED_INFORMATION_F3_SOURCE_SHA256='+digest.hexdigest(),flush=True)


def offered(cold,jid,aid,predicate,target=None):
    native=engine_for(cold().journeys.load(jid))
    from combat.scene_resolution import candidates
    for row in cold().journey_menu(jid,aid)['options']:
        if row['kind']!='scene_native_action':continue
        action=native.action_catalog[row['payload']['action']]
        if not predicate(action):continue
        candidate=next(c for c in candidates(native,aid,action) if c.candidate_id==row['payload']['candidate'])
        if target is None or candidate.target_ids==(target,):return row
    raise AssertionError('Missing legal scene continuation')


def play(cold,jid,act,aid,option,automatic=False):
    if automatic:
        state=cold().journeys.load(jid).state
        cold().journey_auto_step(jid,state['revision'],aid,option['id'])
        assert 'scene_pending' not in cold().journeys.load(jid).state
    else:act(aid,option['kind'],option['payload'])


@pytest.mark.parametrize('lethal',[False,True])
def test_f1_scene_lash_health_survives_next_command_reload_and_encounter(tmp_path,monkeypatch,lethal):
    if lethal:
        import tests.test_mgr_t14_information_review as support
        original=support.sheet
        def small(mids,**kwargs):
            doc=original(mids,**kwargs)
            if kwargs.get('name')=='guest':doc['ability_scores_and_statistics']['hit_points']['maximum']=1
            return doc
        monkeypatch.setattr(support,'sheet',small)
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch,extra_sources=[LASH])
    maximum=engine_for(cold().journeys.load(jid)).state.actors[guest].maximum_hp
    for _ in range(4):
        option=offered(cold,jid,host,lambda a:a.display_name=='Ink Lash',guest)
        play(cold,jid,act,host,option)
        receipts=native_events(cold().journeys.load(jid).state)
        if any(e['event_type']=='DAMAGE_COMMITTED' and guest in e['target_ids'] for e in receipts):break
        act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    else:pytest.fail('No hit in deterministic bounded sequence')
    state=cold().journeys.load(jid).state
    snapshot=state['actors'][guest]['encounter_snapshot']
    assert snapshot['current_hp']<maximum
    if lethal:assert snapshot['current_hp']==0 and state['actors'][guest]['incapacitated']==1
    native=engine_for(cold().journeys.load(jid));target=native.state.actors[guest]
    assert target.current_hp==snapshot['current_hp']
    assert int(target.active)==snapshot['active'] and (target.life_state or '')==snapshot['life_state']
    if not lethal:act(guest,'incapacitated',{'value':True})
    act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    act(host,'ink_press_mark',{'subject':host,'surface':{},'conceal':0})
    assert cold().journeys.load(jid).state['actors'][guest]['encounter_snapshot']==snapshot
    assert cold().journeys.load(jid).state['actors'][guest]['incapacitated']==1
    assert cold().journeys.replay(jid)['status']=='PASS'
    state=cold().journeys.load(jid).state
    result=cold().journey_start_combat(jid,state['revision'],{host:'a',guest:'b'})
    loaded=cold()._load_session(result['match_id'])
    target=loaded.engine.state.actors[guest]
    assert target.current_hp==snapshot['current_hp'] and int(target.active)==snapshot['active']
    assert (target.life_state or '')==snapshot['life_state']
    assert loaded.mechanical.replay()['status']=='PASS'


@pytest.mark.parametrize('object_target',[False,True])
def test_f2_concealed_connection_has_no_actor_mirror_or_history_disclosure(tmp_path,monkeypatch,object_target):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch)
    subject='object:map.1' if object_target else guest
    line=draw(cold,jid,act,host,subject,medium='qi',visibility='hidden')
    assert cold().journeys.load(jid).state['actors'][host]['scene_thread_lines']
    for viewer in (None,guest):
        view=cold().journey_state(jid,viewer_id=viewer)
        assert all(not actor.get('scene_thread_lines') for actor in view['actors'].values())
        assert 'replay_base' not in view and 'command_journal' not in view
        assert line['id'] not in json.dumps(view)
    own=cold().journey_state(jid,viewer_id=host)
    assert own['actors'][host]['scene_thread_lines'][0]['subject']==subject
    assert cold().journeys.replay(jid)['status']=='PASS'


def test_f1_unsupported_scene_consequence_rejects_without_payment_or_receipt(tmp_path,monkeypatch):
    from combat import ext
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch,extra_sources=[LASH],control_modes={
        'actor:factory.host':'LOCAL_AUTO','actor:factory.guest':'LOCAL_AUTO'})
    def unsupported(native,actor,economy,source):
        if native.action_catalog[source].display_name=='Ink Lash':
            native._apply_condition(actor,'condition:test.unsupported_scene_effect',source,actor.entity_id,
                expires_on='END_OF_HOLDER_NEXT_TURN',data={'label':'Unsupported test continuation'})
    monkeypatch.setitem(ext._HOOKS,'action_completed',list(ext._HOOKS['action_completed'])+[unsupported])
    option=offered(cold,jid,host,lambda a:a.display_name=='Ink Lash',guest)
    before=cold().journeys.load(jid).state
    with pytest.raises(ValueError,match='timed or unsupported condition'):
        play(cold,jid,act,host,option,automatic=True)
    assert cold().journeys.load(jid).state==before


@pytest.mark.parametrize('weapon_first',[False,True])
@pytest.mark.parametrize('automatic',[False,True])
def test_f3_complete_attack_orderings_across_cold_menu_and_service(tmp_path,monkeypatch,weapon_first,automatic):
    extra='tianxia.path.body_refining.feature.extra_attack'
    import tests.test_mgr_t14_information_review as support
    original=support.sheet
    def body(mids,**kwargs):
        doc=original(mids,primary='Stamina',**kwargs)
        if kwargs.get('name')=='host':doc['identity']['path']='Body Refining'
        return doc
    monkeypatch.setattr(support,'sheet',body)
    modes={'actor:factory.host':'LOCAL_AUTO','actor:factory.guest':'LOCAL_AUTO'} if automatic else None
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch,extra_sources=[extra],control_modes=modes)
    if weapon_first:predicate=lambda a:a.parameters.get('attack_sequence_start')==1
    else:predicate=lambda a:a.parameters.get('draw_attack_replacement') and not a.parameters.get(REST) and not a.parameters.get('thread_twin') and not a.parameters.get('thread_weapon_source') and ': Guide' in a.display_name
    first=offered(cold,jid,host,predicate,guest)
    play(cold,jid,act,host,first,automatic)
    state=cold().journeys.load(jid).state
    assert state['actors'][host]['source_turn']['action']==0
    assert state['actors'][host]['scene_turn_flags'][FLAG]==1
    assert engine_for(cold().journeys.load(jid)).state.actors[host].turn_flags[FLAG]==1
    for viewer in (None,host,guest):
        assert all('scene_turn_flags' not in a for a in cold().journey_state(jid,viewer_id=viewer)['actors'].values())
    if weapon_first:predicate=lambda a:a.parameters.get(REST) and a.parameters.get('draw_attack_replacement') and not a.parameters.get('thread_twin') and not a.parameters.get('thread_weapon_source') and ': Guide' in a.display_name
    else:predicate=lambda a:a.parameters.get(REST) and not a.parameters.get('draw_attack_replacement')
    second=offered(cold,jid,host,predicate,guest)
    play(cold,jid,act,host,second,automatic)
    state=cold().journeys.load(jid).state
    assert state['actors'][host]['scene_turn_flags'][FLAG]==0
    assert len([e for e in native_events(state) if e['event_type']=='ATTACK_ROLLED' and e.get('actor_id')==host])==2
    native=engine_for(cold().journeys.load(jid))
    assert not any(native.action_catalog[r['payload']['action']].parameters.get(REST) for r in cold().journey_menu(jid,host)['options'] if r['kind']=='scene_native_action')
    assert cold().journeys.replay(jid)['status']=='PASS'
    act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    assert not engine_for(cold().journeys.load(jid)).state.actors[host].turn_flags.get(FLAG)


def test_f4_scene_adorn_uses_native_grant_replacement_and_consumption(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch,extra_sources=[ADORN])
    act(host,'adorn_moment',{'subject':host,'kind':'memory','aura':''})
    native=engine_for(cold().journeys.load(jid))
    grants=[c for c in native.state.actors[host].conditions.values() if c.condition_id==PRESENT]
    # Before the fix scene grants are fabricated under the base record ID;
    # native grants must retain the actual acquired action and its receipt.
    assert len(grants)==1 and grants[0].source_definition_id in native.action_catalog
    assert any(e['event_type']=='CONDITION_APPLIED' and e['payload']['condition_id']==PRESENT for e in native_events(cold().journeys.load(jid).state))
    act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    act(host,'adorn_moment',{'subject':host,'kind':'check','aura':''})
    native=engine_for(cold().journeys.load(jid))
    assert [c.data['kind'] for c in native.state.actors[host].conditions.values() if c.condition_id==PRESENT]==['check']
    task={'id':'presentation','skill':'Persuasion','ability':'CHA','subject':host,'purpose':'grace','dc':12}
    state=cold().journeys.load(jid).state
    cold().journey_admit(jid,state['revision'],host,'scene_check_task',task,gm=True,reason='An actual greeting at the reception.')
    act(host,'scene_check',{'task':task['id']})
    native=engine_for(cold().journeys.load(jid))
    assert any(c.condition_id==USED for c in native.state.actors[host].conditions.values())
    assert not any(c.condition_id==PRESENT for c in native.state.actors[host].conditions.values())
    act(host,'scene_turn',{'edge':'end'});act(host,'scene_turn',{'edge':'start'})
    before=cold().journeys.load(jid).state
    with pytest.raises(ValueError,match='already benefited'):
        act(host,'adorn_moment',{'subject':host,'kind':'check','aura':''})
    assert cold().journeys.load(jid).state==before
    assert cold().journeys.replay(jid)['status']=='PASS'


def test_f4_unowned_adorn_check_consumer_does_not_grant_source_actions(tmp_path,monkeypatch):
    cold,jid,act,host,guest=scene(tmp_path,monkeypatch,extra_sources=[ADORN])
    assert not any(r['kind']=='adorn_moment' for r in cold().journey_menu(jid,guest)['options'])
    before=cold().journeys.load(jid).state
    with pytest.raises(ValueError,match='owner'):
        act(guest,'adorn_moment',{'subject':guest,'kind':'check','aura':''})
    assert cold().journeys.load(jid).state==before
