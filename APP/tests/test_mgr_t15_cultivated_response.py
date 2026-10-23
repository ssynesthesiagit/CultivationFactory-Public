"""Cultivated Response native acquisition and persistent table choices."""
import hashlib
import json
import tempfile
from copy import deepcopy
import pytest
from app.api import create_app
from combat.canonical import canonical_sha256
from combat.ext import defensive_disciplines as d
from combat.factory_compiler import compile_character
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, FOE, sheet
F = d.CULTIVATED
QI = 'tianxia.path.qi_cultivation'
_SOURCE_BUILDS = {}


def test_exact_printed_source():
    text = json.loads((ROOT/'authority/typed_mechanics/rules_text.json').read_text())[F]
    assert hashlib.sha256(text.encode()).hexdigest() == '604a341cd9a5299446748c6d227a583eba0e5fa04c9eada587ae4d2711191a68'


@pytest.fixture(scope='module')
def no_browser():
    with pytest.MonkeyPatch.context() as patch:
        runtime=ROOT.parent.parent/'scratch/MGR-T15-close-cultivated-response/runtime'
        runtime.mkdir(parents=True,exist_ok=True)
        patch.setenv('TMPDIR',str(runtime))
        patch.setattr(tempfile,'tempdir',str(runtime))
        patch.setenv('TIANXIA_BROWSER_EXECUTABLE', '/var/tmp/auto-audit/scratch/MGR-T15-close-cultivated-response/BROWSER_FORBIDDEN')
        yield


@pytest.fixture(scope='module')
def native_sheets(catalog_environment, no_browser):
    app = create_app(catalog_environment['settings']); builder = app.state.character_builder

    class Sheets(dict):
        """Build each requested level once, preserving independent level evidence."""
        failures = {}

        def __missing__(self, cl):
            if cl in self.failures:
                raise AssertionError(self.failures[cl])
            try:
                project = builder.create_project(working_name=f'Circulation CL{cl}', concept='Qi scholar',
                    source_reference=None,target_cl=cl,power_band='rival/boss',creation_mode='NORMAL',
                    generation_route='ai_bootstrap',ability_scores={},autogen_seed=f'circulation-{cl}',
                    selections={'path_choice':[QI]},method_planning_mode='AUTO')
                builder.commit_normal_first_cycle_catalog_choices(project['project_id'])
                run = app.state.character_creation.start(project['project_id'],execution_mode='STANDARD_API',
                    idempotency_key=f'circulation-{cl}',controller_route='DETERMINISTIC_CREATIVE_CONTROLLER')
                assert run['status'] in ('READY_FOR_REVIEW','NEEDS_REVIEW'), run.get('blockers')
                if run['status']=='NEEDS_REVIEW':
                    assert [b['code'] for b in run['blockers']]==['COMMAND6_CHARACTER_GM_CONSUMER_FAILED'], run['blockers']
                    consumer=run['blockers'][0]['details']['consumer_report']
                    guard=consumer['harness_run']
                    assert guard['skipped'] is True and guard['exit_code'] is None, guard
                    runtime=guard['browser_runtime']
                    assert runtime['kind']=='explicit_executable' and runtime['resolved_executable'] is None, guard
                    requested='/var/tmp/auto-audit/scratch/MGR-T15-close-cultivated-response/BROWSER_FORBIDDEN'
                    assert runtime['requested_executable']==requested, guard
                    assert guard['stderr']=='Explicit TIANXIA_BROWSER_EXECUTABLE is missing or not executable: '+requested, guard
                doc = app.state.character_creation.load_candidate_gm_context(run['run_id'])['owner_character_sheet']
                assert F in doc['path_and_subpath']['path_feature_record_ids']
                assert next(p['effective_cl'] for p in doc['path_and_subpath']['paths'] if p['path_id']==QI)==cl
            except Exception as error:
                self.failures[cl] = str(error)
                raise
            self[cl] = doc
            digest = canonical_sha256(doc)
            _SOURCE_BUILDS[digest] = {'run_id':run['run_id'],'status':run['status'],
                'project_id':project['project_id'],'owner_sheet_sha256':digest,
                'owning_qi_path_cl':cl,'source_feature_id':F,
                'blocker_codes':[b['code'] for b in run.get('blockers',[])],
                'consumer_guard':((run.get('blockers') or [{}])[0].get('details') or {}).get('consumer_report',{}).get('harness_run',{}),
                'request_sha256':(run.get('request') or {}).get('request_sha256')}
            (catalog_environment['settings'].data_dir/'native-source-builds.json').write_text(
                json.dumps(list(_SOURCE_BUILDS.values()),indent=2)+'\n')
            (catalog_environment['settings'].data_dir/f'native-source-sheet-{cl}.json').write_text(
                json.dumps(doc,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
            return doc

    return Sheets()


def fight(tmp_path,monkeypatch,doc,ability='DEX',dc=None,ask=True,face=10,hazard=False,qi=None,hp=None,all_saves=False):
    def die(roller,sides):
        n=roller.counter;roller.counter+=1;return min(face() if callable(face) else face,sides),n
    monkeypatch.setattr(DeterministicRollAuthority,'_die',die)
    digest=canonical_sha256(doc)
    (tmp_path/'input-source.json').write_text(json.dumps({'owner_sheet_sha256':digest,
        'native_build':_SOURCE_BUILDS.get(digest),'path_rows':(doc.get('path_and_subpath') or {}).get('paths'),
        'declared_save_proficiencies':(doc.get('ability_scores_and_statistics') or {}).get('saving_throw_proficiencies')},indent=2)+'\n')
    defender=compile_character(deepcopy(doc),actor_id=ME,reaction_plan={'ask':ask})
    save=defender['actor_template']['saving_throws'][ability]
    mid_by_ability={'DEX':'tianxia.talent.ink.scripture_prison',
                    'INT':'TAL_ILLUSION_POTENT_PHANTASM','CHA':'TAL_FATE_CURSE_WORD'}
    if dc is None:
        target_save=max(defender['actor_template']['saving_throws'][a] for a in mid_by_ability) if all_saves else save
        dc=target_save+face+1
    attacker=compile_character(sheet(list(mid_by_ability.values()) if all_saves else [mid_by_ability[ability]],dc=dc,cl=20),actor_id=FOE)
    for b,init in ((defender,-1000),(attacker,1000)):
        b['actor_template'].update(initiative_bonus=init)
        if hp is not None: b['actor_template']['maximum_hp']=hp
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    combat=CombatService(ROOT,tmp_path)
    battlefield=None
    if hazard:
        from combat.tabletop import to_battlefield
        document=combat.tabletop_maps.save({'map_id':'circulation-yard','width_squares':12,'height_squares':10,
            'terrain':[{'type':'QI_HAZARD','cells':[[2,6]]}],
            'starts':{'team1':[[3,6]],'team2':[[4,6]]}})
        battlefield=to_battlefield(combat.tabletop_maps.get(document['map_id']))
    genesis=({ME:{'placement':{'x':3,'y':6},'resources':{'resource:core.qi':qi}}}
             if qi is not None else None)
    session=combat.persistence.create_match(match_seed='Circulation',typed_bundles=(defender,attacker),battlefield=battlefield,
        genesis_setup=genesis,
        roster_setup={'primary_actor_ids':[ME,FOE],'rules':{'zero_hp':'dying_2024','finalized_turns':'skip_finalized_v1'},'team_by_actor':{ME:'team:a',FOE:'team:b'},
                      'starting_positions':{ME:{'x':3,'y':6},FOE:{'x':4,'y':6}}})
    mid=session.match_id;combat._read_metadata(mid,session)
    for a in (ME,FOE):combat.set_controller_mode(mid,actor_id=a,controller_mode='MANUAL')
    return combat,TabletopService(combat,tmp_path),mid


def attack(combat,table,mid,ability='DEX',picks=('DEX','INT'),use=True,auto=False):
    if ability=='INT':
        # Printed Potent Phantasm: choose its paid Deafened option, create the
        # actual figment, then let the owner's real turn start inside its area.
        assert not auto
        setup=next(c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']
                   if c['display_name']=='Figment: Potent Phantasm, Deafened (1 CP)')
        commit_candidate(table,mid,setup)
        create=next(o['candidate_id'] for g in table.state(mid)['menu']['actions']
                    if g['label']=='Create Figment' for o in g['options']
                    if o.get('destination')=={'x':3,'y':6})
        commit_candidate(table,mid,create)
        cid=table.state(mid)['menu']['end_turn']
    else:
        name={'DEX':'Scripture Prison','CHA':'Curse Word'}[ability]
        cid=next(c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']
                 if c['display_name']==name and ME in c['target_ids'])
    if auto:
        from combat.gate5_service import AI_RESPONSE_SCHEMA
        class OfflineProvider:
            def status(self): return {'ready':True}
            def complete_json(self, *, prompt_text, purpose, **kwargs):
                assert purpose=='combat_decision'
                frame=json.loads(prompt_text.split('\n\n',1)[1])
                row=next(c for c in frame['legal_candidates'] if c['candidate_id']==cid)
                payload={key:row[key] for key in ('candidate_id','actor_id','target_ids','destination','option_ids')}
                payload.update(decision_id=frame['decision_id'],state_version=frame['state_version'])
                value={'schema':AI_RESPONSE_SCHEMA,'action_intent':payload,'rationale':'Offline source-backed save.'}
                request_sha=hashlib.sha256(prompt_text.encode()).hexdigest()
                response_sha=canonical_sha256(value)
                (combat.userdata_root/'fake-transport.json').write_text(json.dumps({
                    'purpose':purpose,'request_sha256':request_sha,'response_sha256':response_sha,
                    'candidate_id':cid,'target_ids':payload['target_ids'],
                    'visible_candidate_count':len(frame['legal_candidates'])},indent=2)+'\n')
                return {'value':value,'provider_id':'test:offline','model':'fake',
                        'request_sha256':request_sha,'response_sha256':response_sha}
        combat.ai_provider=OfflineProvider()
        combat.set_controller_mode(mid,actor_id=FOE,controller_mode='API_AUTO')
    answers=[];prompts=[]
    for _ in range(30):
        menu=table.state(mid)['menu']
        out=(table.auto_step(mid,0,answers) if auto else
             table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers))
        if out['status']=='COMMITTED':return prompts
        assert out['status']=='REACTION_REQUIRED',out
        p=out['reaction'];prompts.append(p)
        a={**p['context'],'selection':'USE' if use and p['reaction']=='Cultivated Response' else 'DECLINE'}
        if p.get('choice'):
            ids=[o['id'] for o in p['choice']['options']]
            pick=next((v for v in picks if v in ids),ids[0])
            a.update(selection='USE',option_ids=[pick])
        answers.append(a)
    raise AssertionError('choice loop')


def cold(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    verification=session.verify();replay=session.mechanical.replay()
    assert verification['status']==replay['status']=='PASS'
    engine=session.engine;actor=engine.state.actors[ME]
    events=[{'type':event.event_type,'source':event.source_definition_id,'actor':event.actor_id,
             'targets':list(event.target_ids),'payload':event.payload} for event in engine.events
            if event.source_definition_id==F or (event.actor_id==ME and event.event_type in
                ('SAVE_ROLLED','CHECK_ROLLED','MOVEMENT_COMMITTED'))]
    (tmp_path/'native-play-proof.json').write_text(json.dumps({'match_id':mid,
        'verify_status':verification['status'],'replay_status':replay['status'],
        'round':engine.state.round_number,'qi':actor.resources.get('resource:core.qi'),
        'reaction_available':actor.reaction_available,'saving_throws':actor.saving_throws,
        'proficiency_bonus':actor.proficiency_bonus,'disciplines':d.chosen_abilities(engine,actor,F),
        'events':events},indent=2)+'\n')
    return engine


@pytest.mark.parametrize('cl,count',[(1,1),(14,1),(15,2),(19,2),(20,3)])
def test_native_build_choices_reload_replay(native_sheets,tmp_path,monkeypatch,cl,count):
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[cl])
    actor=combat._load_session(mid).engine.state.actors[ME]
    before=actor.saving_throws.copy();qi=actor.resources['resource:core.qi']
    attack(combat,table,mid)
    engine=cold(tmp_path,mid);actor=engine.state.actors[ME]
    assert d.chosen_abilities(engine,actor,F)==['DEX','INT','CHA'][:count]
    assert actor.saving_throws==before
    assert actor.resources['resource:core.qi']==qi-1


@pytest.mark.parametrize('ability',['DEX','INT','CHA'])
def test_all_three_real_saves(native_sheets,tmp_path,monkeypatch,ability):
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[20],ability)
    actor=combat._load_session(mid).engine.state.actors[ME]
    qi=actor.resources['resource:core.qi'];before=actor.saving_throws.copy()
    prompts=attack(combat,table,mid,ability)
    engine=cold(tmp_path,mid);actor=engine.state.actors[ME]
    assert actor.resources['resource:core.qi']==qi-1
    assert not actor.reaction_available and actor.saving_throws==before
    assert any(p['reaction']=='Cultivated Response' for p in prompts)
    windows=[event for event in engine.events if event.event_type=='REACTION_WINDOW_OPENED'
             and event.source_definition_id==F]
    responses=[event for event in engine.events if event.event_type=='REACTION_RESOLVED'
               and event.source_definition_id==F]
    assert len(windows)==len(responses)==1
    assert windows[0].payload['total']<windows[0].payload['dc']
    assert responses[0].payload['bonus']==actor.proficiency_bonus
    saves=[event for event in engine.events if event.event_type=='SAVE_ROLLED' and event.actor_id==ME
           and event.source_definition_id==responses[0].payload['source_save']]
    assert saves and saves[-1].payload['total']==windows[0].payload['total']+actor.proficiency_bonus


@pytest.mark.parametrize('cl,count',[(1,1),(14,1),(15,2),(19,2),(20,3)])
def test_effective_owning_path(tmp_path,monkeypatch,cl,count):
    doc=sheet([F],cl=20)
    doc['path_and_subpath']['paths']=[{'path_id':'tianxia.path.body_refining','effective_cl':20},
                                     {'path_id':QI,'effective_cl':cl}]
    combat,_,mid=fight(tmp_path,monkeypatch,doc)
    e=combat._load_session(mid).engine
    assert d.capacity(e,e.state.actors[ME],F)==count


@pytest.mark.parametrize('dc,use,paid',[(None,True,1),(None,False,0),(99,True,0),(1,True,0)])
def test_insufficient_bonus_decline_and_success(native_sheets,tmp_path,monkeypatch,dc,use,paid):
    """dc=None: the failed save is one Proficiency can flip, so it is offered (used or declined).
    dc=99: even Proficiency cannot reach the DC, so no rescue is offered and no Qi is spent.
    dc=1: the save succeeds on its own, so nothing is offered."""
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[20],dc=dc)
    qi=combat._load_session(mid).engine.state.actors[ME].resources['resource:core.qi']
    prompts=attack(combat,table,mid,use=use)
    e=cold(tmp_path,mid);actor=e.state.actors[ME]
    assert actor.resources['resource:core.qi']==qi-paid
    offers=[p for p in prompts if p['reaction']=='Cultivated Response' and not p.get('choice')]
    windows=[event for event in e.events if event.event_type=='REACTION_WINDOW_OPENED' and event.source_definition_id==F]
    responses=[event for event in e.events if event.event_type=='REACTION_RESOLVED' and event.source_definition_id==F]
    offered=int(dc is None)
    assert len(offers)==len(windows)==offered
    assert len(responses)==paid
    assert actor.reaction_available==(not paid)
    save=next(event for event in reversed(e.events) if event.event_type=='SAVE_ROLLED' and event.actor_id==ME)
    if offered:
        assert windows[0].payload['total']<windows[0].payload['dc']
        assert save.payload['total']==windows[0].payload['total']+paid*actor.proficiency_bonus
    if dc==99:
        assert save.payload['total']<dc and save.payload['success'] is False


TEMPERED='tianxia.path.body_refining.feature.tempered_response'


def test_cultivated_record_leaves_tempered_response_choice_alone(tmp_path,monkeypatch):
    """Cultivated Response records its own discipline instance only; another Path's saved choice (Tempered Response,
    same shared condition id) survives the table commit, the cold reload and a later Cultivated record."""
    doc=sheet([F,TEMPERED],cl=20)
    doc['path_and_subpath']['paths']=[{'path_id':'tianxia.path.body_refining','effective_cl':20},
                                     {'path_id':QI,'effective_cl':15}]
    combat,table,mid=fight(tmp_path,monkeypatch,doc)
    attack(combat,table,mid,picks=('DEX','INT'))
    engine=cold(tmp_path,mid);actor=engine.state.actors[ME]
    assert d.chosen_abilities(engine,actor,F)==['DEX','INT']
    assert d.chosen_abilities(engine,actor,TEMPERED)==['DEX']
    d._remember(engine,actor,F,['DEX','CHA'])
    assert d.chosen_abilities(engine,actor,TEMPERED)==['DEX']
    assert d.chosen_abilities(engine,actor,F)==['DEX','CHA']


def test_round_receipt_survives_reload_and_an_extra_reaction(tmp_path,monkeypatch):
    """A committed rescue records its round; a Reaction refreshed inside that same round cannot spend again.

    Both saves are real engine saves made by a committed table action, and the second (map-hazard) save is one the
    fresh Reaction could have rescued, so only the persisted round receipt refuses it.
    """
    combat,table,mid=fight(tmp_path,monkeypatch,sheet([F],cl=1,score=24),face=1,hazard=True)
    qi=combat._load_session(mid).engine.state.actors[ME].resources['resource:core.qi']
    attack(combat,table,mid)
    e=cold(tmp_path,mid);actor=e.state.actors[ME]
    assert actor.resources['resource:core.qi']==qi-1 and not actor.reaction_available
    receipts=[c for c in actor.conditions.values() if c.condition_id=='condition:typed.save_rescue_used:'+F]
    assert len(receipts)==1 and receipts[0].data['round']==e.state.round_number==1
    assert len([event for event in e.events if event.event_type=='REACTION_RESOLVED'
                and event.source_definition_id==F])==1
    # The real clock refreshes the Reaction inside round one.
    commit_candidate(table,mid,table.state(mid)['menu']['end_turn'])
    e=cold(tmp_path,mid);actor=e.state.actors[ME]
    assert e.state.round_number==1 and actor.reaction_available
    assert actor.resources['resource:core.qi']==qi-1
    move=next(c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']
              if c['kind']=='MOVE' and c['destination']['x']==2 and c['destination']['y']==6)
    commit_candidate(table,mid,move)
    e=cold(tmp_path,mid);actor=e.state.actors[ME]
    hazard=[event for event in e.events if event.event_type=='SAVE_ROLLED'
            and event.source_definition_id=='system:battlefield.qi_hazard']
    assert hazard
    # This failed hazard save was rescuable by the fresh Reaction; the receipt is what refuses it.
    assert 1+actor.saving_throws['DEX']<12
    assert 1+actor.saving_throws['DEX']+actor.proficiency_bonus>=12
    assert hazard[-1].payload['total']==1+actor.saving_throws['DEX']
    assert actor.resources['resource:core.qi']==qi-1 and actor.reaction_available
    assert len([event for event in e.events if event.event_type=='REACTION_RESOLVED'
                and event.source_definition_id==F])==1



def commit_candidate(table,mid,cid,accept_opportunity=False):
    answers=[]
    for _ in range(25):
        menu=table.state(mid)['menu']
        result=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
        if result['status']=='COMMITTED': return
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction']
        use=(prompt['reaction']=='Cultivated Response' or (accept_opportunity and
             prompt['context'].get('reaction_source_id')=='system:combat.opportunity_attack'))
        response={**prompt['context'],'selection':'USE' if use else 'DECLINE'}
        if prompt.get('choice'):
            response.update(selection='USE',option_ids=['DEX'])
        answers.append(response)
    raise AssertionError('choice loop')


def test_native_hazard_save_reaches_the_consumer_and_stays_unpaid_when_it_cannot_flip(
        native_sheets,tmp_path,monkeypatch):
    """A native CL1 Qi fighter's DEX save is too low for +PB to turn a hazard failure into a success."""
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[1],face=1,hazard=True)
    actor=combat._load_session(mid).engine.state.actors[ME]
    qi=actor.resources['resource:core.qi']
    assert 1+actor.saving_throws['DEX']<12
    assert 1+actor.saving_throws['DEX']+actor.proficiency_bonus<12
    commit_candidate(table,mid,table.state(mid)['menu']['end_turn'])
    engine=cold(tmp_path,mid)
    assert engine.state.current_actor_id==ME and engine.state.actors[ME].reaction_available
    assert engine.state.round_number==1
    move=next(c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']
              if c['kind']=='MOVE' and c['destination']['x']==2 and c['destination']['y']==6)
    commit_candidate(table,mid,move)
    engine=cold(tmp_path,mid);actor=engine.state.actors[ME]
    hazard=[e for e in engine.events if e.event_type=='SAVE_ROLLED'
            and e.source_definition_id=='system:battlefield.qi_hazard']
    assert hazard and hazard[-1].payload['total']==1+actor.saving_throws['DEX']
    # The printed response is only usable when +PB can turn the failure into success.
    assert actor.resources['resource:core.qi']==qi and actor.reaction_available
    assert not [event for event in engine.events if event.event_type=='REACTION_RESOLVED'
                and event.source_definition_id==F]


def test_committed_map_hazard_save_is_rescued_when_the_bonus_can_flip_it(tmp_path,monkeypatch):
    """The same map/turn flow with a DEX save high enough for +PB: the hazard save reaches the response."""
    combat,table,mid=fight(tmp_path,monkeypatch,sheet([F],cl=1,score=24),face=1,hazard=True)
    actor=combat._load_session(mid).engine.state.actors[ME]
    qi=actor.resources['resource:core.qi']
    assert 1+actor.saving_throws['DEX']<12
    assert 1+actor.saving_throws['DEX']+actor.proficiency_bonus>=12
    commit_candidate(table,mid,table.state(mid)['menu']['end_turn'])
    engine=cold(tmp_path,mid)
    assert engine.state.current_actor_id==ME and engine.state.actors[ME].reaction_available
    assert engine.state.round_number==1
    move=next(c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']
              if c['kind']=='MOVE' and c['destination']['x']==2 and c['destination']['y']==6)
    commit_candidate(table,mid,move)
    engine=cold(tmp_path,mid);actor=engine.state.actors[ME]
    hazard=[e for e in engine.events if e.event_type=='SAVE_ROLLED'
            and e.source_definition_id=='system:battlefield.qi_hazard']
    assert hazard
    assert hazard[-1].payload['total']==1+actor.saving_throws['DEX']+actor.proficiency_bonus
    responses=[event for event in engine.events if event.event_type=='REACTION_RESOLVED'
               and event.source_definition_id==F]
    assert len(responses)==1
    assert responses[0].payload['source_save']=='system:battlefield.qi_hazard'
    assert actor.resources['resource:core.qi']==qi-1 and not actor.reaction_available



@pytest.mark.parametrize('automatic_owner,cl',[(False,15),(True,15),(True,20)])
def test_native_other_turn_choice_ownership_with_fake_ai_transport(
        native_sheets,tmp_path,monkeypatch,automatic_owner,cl):
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[cl])
    qi=combat._load_session(mid).engine.state.actors[ME].resources['resource:core.qi']
    if automatic_owner:
        combat.set_controller_mode(mid,actor_id=ME,controller_mode='API_AUTO')
    prompts=attack(combat,table,mid,auto=True)
    e=cold(tmp_path,mid)
    picked=d.chosen_abilities(e,e.state.actors[ME],F)
    assert len(picked)==(3 if cl==20 else 2) and set(picked)<={'DEX','INT','CHA'}
    assert e.state.actors[ME].resources['resource:core.qi']==qi-int('DEX' in picked)
    if automatic_owner:
        assert not prompts
    else:
        assert picked==['DEX','INT']
        assert prompts and all(p['context']['reactor_id']==ME for p in prompts)



def test_native_failed_save_without_qi_uses_no_reaction(native_sheets,tmp_path,monkeypatch):
    # The public genesis input validates an ordinary depleted resource snapshot;
    # it grants no feature, success, source qualification or consent flag.
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[1],qi=0)
    prompts=attack(combat,table,mid)
    e=cold(tmp_path,mid);actor=e.state.actors[ME]
    assert actor.resources['resource:core.qi']==0 and actor.reaction_available
    assert not [p for p in prompts if not p.get('choice') and p['reaction']=='Cultivated Response']
    assert not [event for event in e.events if event.event_type=='REACTION_RESOLVED' and event.source_definition_id==F]


def test_native_opportunity_attack_spends_reaction_before_failed_save(native_sheets,tmp_path,monkeypatch):
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[1])
    qi=combat._load_session(mid).engine.state.actors[ME].resources['resource:core.qi']
    move=next(c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']
              if c['kind']=='MOVE' and c['destination']['x']==5 and c['destination']['y']==6)
    commit_candidate(table,mid,move,accept_opportunity=True)
    e=cold(tmp_path,mid)
    assert not e.state.actors[ME].reaction_available
    attack(combat,table,mid)
    e=cold(tmp_path,mid)
    assert e.state.actors[ME].resources['resource:core.qi']==qi
    assert not [event for event in e.events if event.event_type=='REACTION_RESOLVED' and event.source_definition_id==F]



def test_native_repeated_save_intent_cannot_pay_or_modify_twice(native_sheets,tmp_path,monkeypatch):
    from combat.gate5_service import CombatServiceError
    from combat.tabletop import TabletopError
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[20])
    menu=table.state(mid)['menu']
    cid=next(c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']
             if c['display_name']=='Scripture Prison' and ME in c['target_ids'])
    attack(combat,table,mid)
    before=cold(tmp_path,mid).state.model_dump(mode='json')
    try:
        table.act(mid,cid,menu['decision_id'],menu['state_version'],0,[])
    except (CombatServiceError,TabletopError):
        pass
    assert cold(tmp_path,mid).state.model_dump(mode='json')==before



@pytest.mark.parametrize('cl,ability,picks',[
    (1,'DEX',('DEX',)),(1,'INT',('INT',)),(1,'CHA',('CHA',)),
    (15,'DEX',('DEX','INT')),(15,'DEX',('DEX','CHA')),(15,'INT',('INT','CHA'))])
def test_every_initial_discipline_and_second_discipline_pair_is_native(
        native_sheets,tmp_path,monkeypatch,cl,ability,picks):
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[cl],ability=ability)
    qi=combat._load_session(mid).engine.state.actors[ME].resources['resource:core.qi']
    attack(combat,table,mid,ability=ability,picks=picks)
    e=cold(tmp_path,mid)
    assert d.chosen_abilities(e,e.state.actors[ME],F)==list(picks)
    assert e.state.actors[ME].resources['resource:core.qi']==qi-1


def test_native_failed_death_save_is_not_a_cultivated_response(native_sheets,tmp_path,monkeypatch):
    face=[20]
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[1],face=lambda:face[0],dc=99,hp=None)
    commit_candidate(table,mid,table.state(mid)['menu']['end_turn'])
    setup=next(c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']
               if 'Reflexive Circulation' in c['display_name'])
    commit_candidate(table,mid,setup)
    commit_candidate(table,mid,table.state(mid)['menu']['end_turn'])
    qi=cold(tmp_path,mid).state.actors[ME].resources['resource:core.qi']
    for _ in range(12):
        hit=next(c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']
                 if 'unarmed' in c['display_name'].lower() and ME in c['target_ids'])
        commit_candidate(table,mid,hit)
        e=cold(tmp_path,mid)
        dying=e.state.actors[ME].life_state=='DYING'
        if dying: face[0]=1
        commit_candidate(table,mid,table.state(mid)['menu']['end_turn'])
        e=cold(tmp_path,mid)
        if dying:
            rolls=[event for event in e.events if event.event_type=='CHECK_ROLLED'
                   and event.actor_id==ME and event.payload.get('skill')=='Death Saving Throw']
            assert rolls and rolls[-1].payload['actor']['total']==1
            assert rolls[-1].payload['success'] is False
            assert e.state.actors[ME].resources['resource:core.qi']==qi
            assert not [event for event in e.events if event.event_type=='REACTION_RESOLVED' and event.source_definition_id==F]
            return
        commit_candidate(table,mid,table.state(mid)['menu']['end_turn'])
    raise AssertionError('native unarmed attacks never produced a dying turn')



def test_native_first_choice_keeps_the_existing_checkpoint_namespace(native_sheets,tmp_path,monkeypatch):
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[1])
    cid=next(c['candidate_id'] for c in combat.decision(mid)['context']['legal_candidates']
             if c['display_name']=='Scripture Prison' and ME in c['target_ids'])
    menu=table.state(mid)['menu']
    result=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,[])
    assert result['status']=='REACTION_REQUIRED'
    prompt=result['reaction']
    checkpoint=prompt['context']['checkpoint']
    assert checkpoint.startswith('NEEDLE:defensive_discipline:')
    # This suffix is the already-shipped first-choice transport contract.
    assert checkpoint.endswith(f':{F}:{ME}')
    answer={**prompt['context'],'selection':'USE','option_ids':['DEX']}
    fresh=CombatService(ROOT,tmp_path);fresh_table=TabletopService(fresh,tmp_path)
    fresh_menu=fresh_table.state(mid)['menu']
    result=fresh_table.act(mid,cid,fresh_menu['decision_id'],fresh_menu['state_version'],0,[answer])
    if result['status']=='REACTION_REQUIRED':
        assert not result['reaction'].get('choice'), result
    assert result['status'] in ('COMMITTED','REACTION_REQUIRED')


@pytest.mark.parametrize('paths', [None, [],
    [{'path_id':'tianxia.path.body_refining','effective_cl':20}]])
def test_missing_owning_path_attainment_never_borrows_global_cl(tmp_path,monkeypatch,paths):
    doc=sheet([F],cl=20)
    doc['path_and_subpath']['paths']=paths
    combat,_,mid=fight(tmp_path,monkeypatch,doc)
    engine=combat._load_session(mid).engine
    assert d.capacity(engine,engine.state.actors[ME],F)==1


@pytest.mark.parametrize('cl,picks', [(1,('INT',)),(15,('INT','CHA'))])
def test_native_unselected_save_is_not_rescued(native_sheets,tmp_path,monkeypatch,cl,picks):
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[cl])
    before=combat._load_session(mid).engine.state.actors[ME].resources['resource:core.qi']
    attack(combat,table,mid,picks=picks)
    engine=cold(tmp_path,mid);actor=engine.state.actors[ME]
    assert d.chosen_abilities(engine,actor,F)==list(picks)
    assert actor.resources['resource:core.qi']==before and actor.reaction_available
    assert not [e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==F]


def test_recorded_first_choice_remains_compatible_at_full_capacity(tmp_path,monkeypatch):
    """Reader compatibility probe, not native level-advancement/rebuild proof."""
    doc=sheet([F],cl=20)
    doc['path_and_subpath']['paths']=[{'path_id':QI,'effective_cl':1}]
    combat,table,mid=fight(tmp_path,monkeypatch,doc)
    attack(combat,table,mid,picks=('INT',))
    engine=cold(tmp_path,mid);actor=engine.state.actors[ME]
    assert d.chosen(engine,actor,F)=='INT'
    # Probe the getter against a larger sealed-action capacity, keeping the
    # actual committed legacy choice. This does not execute a forged upgrade.
    for action in engine.action_catalog.values():
        if action.owner_id==ME and 'discipline_capacity' in action.parameters:
            action.parameters['discipline_capacity']=3
    assert d.chosen(engine,actor,F)=='INT'
    assert d.chosen_abilities(engine,actor,F)==['INT','DEX','CHA']


@pytest.mark.parametrize('cl',[15,19])
def test_native_persisted_second_discipline_rescues_after_cold_reload(native_sheets,tmp_path,monkeypatch,cl):
    combat,table,mid=fight(tmp_path,monkeypatch,native_sheets[cl],all_saves=True)
    qi=combat._load_session(mid).engine.state.actors[ME].resources['resource:core.qi']
    attack(combat,table,mid,picks=('DEX','CHA'))
    engine=cold(tmp_path,mid)
    assert d.chosen_abilities(engine,engine.state.actors[ME],F)==['DEX','CHA']
    assert engine.state.actors[ME].resources['resource:core.qi']==qi-1
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    commit_candidate(table,mid,table.state(mid)['menu']['end_turn'])
    commit_candidate(table,mid,table.state(mid)['menu']['end_turn'])
    engine=cold(tmp_path,mid)
    assert engine.state.round_number==2 and engine.state.actors[ME].reaction_available
    assert engine.state.actors[ME].resources['resource:core.qi']==qi-1
    prompts=attack(combat,table,mid,ability='CHA')
    assert not [p for p in prompts if p['reaction']=='Cultivated Response' and p.get('choice')]
    engine=cold(tmp_path,mid)
    assert d.chosen_abilities(engine,engine.state.actors[ME],F)==['DEX','CHA']
    assert engine.state.actors[ME].resources['resource:core.qi']==qi-2
    assert len([e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==F])==2
