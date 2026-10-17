"""Earned restricted scripture -> native table commits -> cold mechanical replay."""
from copy import deepcopy
import pytest
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE
from tests.cw2_service_support import add_action, seal
from tests.test_p15_save_condition_duration import pin_dice  # noqa: F401
P = 'tianxia.subpath.body.hundred_venom_body.feature.'
FEATURES = [P + f for f in ('venom_furnace','swallow_the_poison','three_sovereign_venoms','poisoned_body_poisoned_world','myriad_venom_immortal')]
STAMINA = 'resource:core.stamina'


@pytest.fixture(scope='session')
def native_environment(tmp_path_factory):
    # Native source acquisition reads installed portable characters and the
    # committed compiler authority. It does not invoke Factory generation or
    # require an unrelated catalog/archive to admit scripture access.
    from app.core import Settings
    root=tmp_path_factory.mktemp('hundred_venom_native')
    return {'settings':Settings.from_env(ROOT,root)}

def _acquire_once(native_environment, monkeypatch, cl=18, project="worker2-owner"):
    """Acquire from an installed, previously attained Body character.

    The fixture character has no Hundred-Venom IDs. Actual native GM access,
    source acquisition, committed state and cold overlay produce every one.
    """
    import json, zipfile
    from pathlib import Path
    from combat.gate5_service import CombatService
    from combat.ext.hundred_venom_acquisition import BODY, overlay
    from tests.h1_support import sheet as base_sheet
    cache=native_environment.setdefault('_hundred_venom_acquired_sheets',{})
    key=(cl,project)
    if key in cache:return deepcopy(cache[key])
    root=native_environment['settings'].data_dir/f'native-hundred-venom-{project}-cl{cl}'
    aid='actor:factory.'+project
    core=[BODY+'.feature.'+f for f,minimum in [('iron_fist',1),('unarmored_defense',1),
        ('stamina_guard',2),('extra_attack',5),('refined_iron_fist',5),('extra_attack_improvement',11)] if cl>=minimum]
    doc=base_sheet(core,cl=cl,primary='Stamina',key='CON',dc=10+(2+(cl-1)//4))
    doc['identity'].update(name='Hundred-Venom practitioner '+project,path='Body Refining',proficiency_bonus=2+(cl-1)//4)
    doc['ability_scores_and_statistics']['primary_resource']['maximum']=2*cl
    doc['ability_scores_and_statistics']['technique_attack_bonus']=2+(cl-1)//4+2
    paths=doc.setdefault('path_and_subpath',{})
    paths.update(path_record_id=BODY,path_record_ids=[BODY],
                 paths=[{'path_id':BODY,'attainment':cl,'effective_cl':cl}])
    assert not any(str(f).startswith(P) for f in paths.get('path_feature_record_ids',()))
    folder=root/'portable_characters'/project;folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,root)
    cold().tabletop_maps.save({'display_name':'Scripture acquisition yard','width_squares':12,'height_squares':12,'terrain':[]})
    arena=next(k for k,v in cold().factory_arenas().items() if v['display_name']=='Scripture acquisition yard')
    state=cold().create_journey(project_ids=[project],arena_id=arena,
        positions={aid:{'x':3,'y':3}},base_paces={aid:30})
    jid=state['journey_id'];family=P.removesuffix('.feature.')
    access={'source':family,'subject':aid,'kind':'source_access','scope':'native-scripture-access',
        'value':{'scripture':family,'source_rule':'The world owner grants actual access to the restricted Hundred-Venom Body scripture under Body Core CL3 and Compendium R8.'},
        'expires_at':3600,'readers':[aid]}
    with pytest.raises(ValueError,match='table-owner'):
        cold().journey_act(jid,state['revision'],aid,'declare_fact',access)
    assert cold().journey_state(jid)==state
    state=cold().journey_world_fact(jid,state['revision'],access)
    before=dict(state['actors'][aid]['resources'])
    state=cold().journey_acquire_source(jid,state['revision'],aid,family,{'access_scope':access['scope']})
    assert state==cold().journey_state(jid)
    event=state['events'][-1]
    assert event['kind']=='HUNDRED_VENOM_SOURCE_ACQUIRED'
    expected={f for f,minimum in zip(FEATURES,(3,6,10,14,18)) if cl>=minimum}
    assert set(event['earned_features'])==expected
    assert state['actors'][aid]['resources']==before
    receipt=state['actors'][aid]['source_states'][family]['acquisition']
    assert event['access_receipt']==state['fact_consent_admission'][-1]['receipt_id']==receipt['access_receipt']
    acquired=overlay(doc,receipt)
    assert set(acquired['path_and_subpath']['source_granted_subpath_feature_record_ids'])==expected
    # Finish/reopen keeps the installed source-free sheet untouched. The
    # owner's native overlay reconstructs the acquired build from committed state.
    state=cold().journey_act(jid,state['revision'],aid,'finish',{})
    reopened=cold().create_journey(project_ids=[project],arena_id=arena,
        positions={aid:{'x':3,'y':3}},base_paces={aid:30})
    assert reopened['actors'][aid]['source_states'][family]['acquisition']==receipt
    assert {r.get('role') for r in reopened['actors'][aid]['bundle']['typed_passives']
            if r.get('kind')=='hundred_venom'}=={r for r,minimum in [('furnace',3),('sovereign',10),('poisoned_world',14),('myriad',18)] if cl>=minimum}
    evidence=Path('/var/tmp/auto-audit/fix/MGR-T14-sol-reserve-hundred-venom-body-venom-furnace-1-evidence')
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/f'native-acquisition-{project}-cl{cl}.json').write_text(json.dumps({
        'cl':cl,'journey_id':jid,'event':event,'acquisition':receipt,
        'installed_sheet_owns_hundred_venom':False,'cold_reopened':True},sort_keys=True,indent=2)+'\n')
    cache[key]=deepcopy(acquired)
    return acquired


def acquire(env, monkeypatch, cl=18, project="worker2-owner"):
    failures=env.setdefault('_hundred_venom_acquisition_failures',{})
    key=(cl,project)
    if key in failures:
        raise AssertionError('The same real native acquisition already failed: '+failures[key])
    try:
        return _acquire_once(env,monkeypatch,cl,project)
    except Exception as exc:
        failures[key]=f'{type(exc).__name__}: {exc}'
        raise


def setup(tmp_path, env, cl=18, *, mirror=False, foe_con=None, mirror_cl=None, foe_speeds=None):
    document = acquire(env, None, cl)
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask':True})
    mirror_document = acquire(env,None,mirror_cl or cl,'worker2-foe') if mirror else None
    def scenario(bs):
        if mirror:
            bs[2] = compile_character(mirror_document, actor_id=FOE, reaction_plan={'ask':True})
        for b, initiative in zip(bs,(100,0,-100)):
            b['actor_template']['initiative_bonus']=initiative
            b['actor_template']['maximum_hp']=1000
            seal(b)
        if foe_speeds is not None:
            bs[2]['actor_template'].update(dict(zip(('speed_ft','fly_speed_ft','climb_speed_ft'),foe_speeds)))
            seal(bs[2])
        if foe_con is not None:
            bs[2]['actor_template']['saving_throws']['CON']=foe_con
            seal(bs[2])
        for kind in ('acid','poison','force'):
            add_action(bs[2],kind.title()+' exposure',[{'type':'damage','flat':3,'damage_types':[kind],'applies_to':'target'}])
        for ability in ('str','dex'):
            add_action(bs[0],ability.upper()+' save probe',[{'type':'save','ability':ability,'on_fail':[],'on_success':[]}])
        for category in ('disease','ordinary_disease','curse'):
            add_action(bs[2],category+' save',[{'type':'save','ability':'con','save_categories':[category],
              'on_fail':[{'type':'condition','condition':category,'applies_to':'target','duration':'one_minute'}],'on_success':[]}])
    return fixture(tmp_path,[],cl=cl,primary='Stamina',owner_bundle=bundle,bundle_transform=scenario,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':6},FOE:{'x':3,'y':7}})


class ExplicitReactions(dict):
    def get(self,key,default=None):
        # Numeric Reaction choices (Stamina Guard) also have a preferred option.
        # Unspecified reactions are declined; ordinary mandatory choices keep
        # their real preferred option. No product reaction priority is changed.
        if key not in self and key.startswith('reaction:'):return None
        return super().get(key,default)


def commit(c,t,m,name,target,picks=None):
    return settle(t,m,candidate(c,m,name,target=target).candidate_id,choices=ExplicitReactions(picks or {}))


def venoms(e,who=FOE):
    return sorted(x.data['venom'] for x in e.state.actors[who].conditions.values()
                  if x.condition_id=='condition:typed.sovereign_venom')


def attack(c,t,m,tmp_path,pin_dice,choices,extra=None,draws=31):
    e=c._load_session(m).engine
    name=next(a.display_name for a in e.action_catalog.values() if a.owner_id==OWNER
              and any(x.get('type')=='attack' and x.get('attack_kind')=='unarmed'
                      for x in ((a.parameters or {}).get('typed') or {}).get('effects') or []))
    pin_dice(e,[19]+[1]*(draws-1))
    commit(c,t,m,name,FOE,{'choice:needle.path_hit.'+P+'venom_furnace':['Use Venom Furnace'],
        'choice:needle.sovereign_venom':choices,'choice:needle.marrow_venom':['Dexterity'],**(extra or {})})
    return reload(tmp_path,m)


@pytest.mark.parametrize('cl',[3,6,10,14,18])
def test_real_restricted_scripture_progression(native_environment,monkeypatch,tmp_path,cl):
    acquire(native_environment,monkeypatch,cl)
    c,t,m=setup(tmp_path,native_environment,cl)
    e=reload(tmp_path,m)
    roles={r.get('role') for r in e.typed_passive_rows[OWNER] if r.get('kind')=='hundred_venom'}
    assert roles=={r for r,level in [('furnace',3),('sovereign',10),('poisoned_world',14),('myriad',18)] if cl>=level}


@pytest.mark.parametrize('kind,adapt',[('acid',False),('poison',True)])
def test_swallow_adapts_only_zero_poison(native_environment,monkeypatch,tmp_path,kind,adapt):
    acquire(native_environment,monkeypatch,6)
    c,t,m=setup(tmp_path,native_environment,6)
    turn(t,m,FOE)
    before=reload(tmp_path,m).state.actors[OWNER].resources[STAMINA]
    prompts=commit(c,t,m,kind.title()+' exposure',OWNER,{'reaction:typed.'+P+'swallow_the_poison':['use']})
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].resources[STAMINA]==before-1,prompts
    assert any(x.condition_id=='condition:typed.venom_adaptation' for x in e.state.actors[OWNER].conditions.values()) is adapt


def test_venoms_capture_source_level(native_environment,monkeypatch,tmp_path,pin_dice):
    acquire(native_environment,monkeypatch)
    c,t,m=setup(tmp_path,native_environment)
    e=attack(c,t,m,tmp_path,pin_dice,['nerve','marrow'])
    assert venoms(e)==['marrow','nerve']
    assert all('source_cl' in x.data for x in e.state.actors[FOE].conditions.values()
               if x.condition_id=='condition:typed.sovereign_venom')


def test_retaliation_cannot_trigger_another_retaliation(native_environment,monkeypatch,tmp_path,pin_dice):
    acquire(native_environment,monkeypatch,14)
    c,t,m=setup(tmp_path,native_environment,14,mirror=True)
    turn(t,m,FOE)
    pin_dice(c._load_session(m).engine,[1]*30)
    commit(c,t,m,'Force exposure',OWNER,{'choice:needle.poisoned_body_poisoned_world':['use'],
                                        'choice:needle.sovereign_venom':['nerve']})
    e=reload(tmp_path,m)
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==P+'poisoned_body_poisoned_world']
    assert len(packets)==1
    assert packets[0].actor_id==OWNER


@pytest.mark.parametrize('category,immune',[('ordinary_disease',True),('curse',False)])
def test_myriad_ordinary_disease_boundary(native_environment,monkeypatch,tmp_path,pin_dice,category,immune):
    acquire(native_environment,monkeypatch)
    c,t,m=setup(tmp_path,native_environment)
    turn(t,m,FOE)
    pin_dice(c._load_session(m).engine,[1]*10)
    commit(c,t,m,category+' save',OWNER)
    e=reload(tmp_path,m)
    assert any(x.condition_id.endswith('.'+category) for x in e.state.actors[OWNER].conditions.values()) is (not immune)


def native_exposure(tmp_path, env, cl, *, category='poison', delivery='damage', authority='ordinary', amount=3, stage='combat', source_body_cl=None, duration_kind=None):
    """Real acquisition, native GM declaration and collection, then a journey encounter."""
    import json, zipfile
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.hundred_venom_sources import FAMILY, KIND, SCOPE, COLLECT
    from tests.h1_support import sheet as ordinary_sheet
    from pathlib import Path
    acquired_levels={'abcdef01':cl,**({'abcdef02':source_body_cl} if source_body_cl else {})}
    for pid in ('abcdef01','abcdef02'):
        if pid in acquired_levels:
            level=acquired_levels[pid]
            acquire(env,None,level,pid)
            # Use the actual unchanged, source-free installed Body sheet from
            # the acquisition fixture. Acquire again in this journey's own
            # durable registry; never transplant a source-state receipt.
            archive=env['settings'].data_dir/f'native-hundred-venom-{pid}-cl{level}'/'portable_characters'/pid/'current.zip'
            with zipfile.ZipFile(archive) as z:doc=json.loads(z.read('Tianxia_Owner_Character_Sheet_v1.json'))
        else:doc=ordinary_sheet([],cl=cl,name='Exposure source')
        assert not any(str(f).startswith(P) for f in doc.get('path_and_subpath',{}).get('path_feature_record_ids',()))
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    owner='actor:factory.abcdef01';source='actor:factory.abcdef02'
    from combat.tabletop import ButtonStore
    for pid in ('abcdef01','abcdef02'):
        ButtonStore(tmp_path/'tabletop_buttons').save_reactions(pid,{'mode':'ask'},{'opportunity_attack'})
    def cold():return CombatService(ROOT,tmp_path)
    cold().tabletop_maps.save({'display_name':'Venom source yard','width_squares':16,'height_squares':12,'terrain':[]})
    arena=next(k for k,v in cold().factory_arenas().items() if v['display_name']=='Venom source yard')
    s=cold().create_journey(project_ids=['abcdef01','abcdef02'],arena_id=arena,
        positions={owner:{'x':3,'y':6},source:{'x':3,'y':7}},base_paces={owner:30,source:30})
    jid=s['journey_id']
    for pid,level in acquired_levels.items():
        aid='actor:factory.'+pid
        access={'source':FAMILY,'subject':aid,'kind':'source_access','scope':'native-scripture-access',
            'value':{'scripture':FAMILY,'source_rule':'The world owner grants actual restricted-scripture access for this native Body acquisition.'},
            'expires_at':3600,'readers':[aid]}
        s=cold().journey_world_fact(jid,s['revision'],access)
        before=dict(s['actors'][aid]['resources'])
        s=cold().journey_acquire_source(jid,s['revision'],aid,FAMILY,{'access_scope':access['scope']})
        assert s==cold().journey_state(jid) and s['actors'][aid]['resources']==before
        assert s['actors'][aid]['source_states'][FAMILY]['acquisition']['journey_id']==jid
    payload={'source':FAMILY,'subject':owner,'kind':KIND,'scope':SCOPE,'expires_at':120,'readers':[source],
        'value':{'name':'Recorded external exposure','source_actor':source,'delivery':delivery,'category':category,
                 'authority':authority,'amount':amount,'dc':16,'duration_seconds':60,'source_cl':cl,
                 **({'duration_kind':duration_kind} if duration_kind else {})}}
    with pytest.raises(ValueError,match='table-owner'):
        cold().journey_act(jid,s['revision'],owner,'declare_fact',payload)
    assert cold().journey_state(jid)==s
    s=cold().journey_world_fact(jid,s['revision'],payload)
    assert 'value' not in s['events'][-1]
    s=cold().journey_act(jid,s['revision'],owner,COLLECT,{})
    assert s==cold().journey_state(jid)
    if stage=='collected':
        return cold(),None,None,owner,source,jid
    m=cold().journey_start_combat(jid,s['revision'],{owner:'team:body',source:'team:source'},maximum_rounds=15)['match_id']
    t=TabletopService(cold(),tmp_path);turn(t,m,source)
    return cold(),t,m,owner,source,jid


@pytest.mark.parametrize('category,adapt',[('acid',False),('poison',True)])
def test_world_owner_exposure_collection_to_native_swallow(native_environment,monkeypatch,tmp_path,category,adapt):
    acquire(native_environment,monkeypatch,6)
    c,t,m,owner,source,jid=native_exposure(tmp_path,native_environment,6,category=category)
    before=reload(tmp_path,m).state.actors[owner].resources[STAMINA]
    prompts=commit(c,t,m,'Recorded external exposure — resolve recorded exposure',owner,
                   {'reaction:typed.'+P+'swallow_the_poison':['use']})
    e=reload(tmp_path,m)
    assert e.state.actors[owner].resources[STAMINA]==before-1,prompts
    assert any(x.condition_id=='condition:typed.venom_adaptation' for x in e.state.actors[owner].conditions.values()) is adapt
    assert not [x for x in e.legal_candidates() if x.source_definition_id.startswith('source:hundred_venom.exposure.')]


@pytest.mark.parametrize('authority,immune',[('ordinary',True),('curse',False),('tribulation',False)])
def test_native_source_disease_immunity_respects_authority(native_environment,monkeypatch,tmp_path,pin_dice,authority,immune):
    acquire(native_environment,monkeypatch)
    c,t,m,owner,source,jid=native_exposure(tmp_path,native_environment,18,
        category='ordinary_disease',delivery='save',authority=authority)
    pin_dice(c._load_session(m).engine,[1]*10)
    commit(c,t,m,'Recorded external exposure — resolve recorded exposure',owner)
    e=reload(tmp_path,m)
    assert any(x.condition_id=='condition:typed.diseased' for x in e.state.actors[owner].conditions.values()) is (not immune)


def test_native_source_failed_disease_save_can_add_pb(native_environment,monkeypatch,tmp_path,pin_dice):
    acquire(native_environment,monkeypatch,6)
    c,t,m,owner,source,jid=native_exposure(tmp_path,native_environment,6,category='disease',delivery='save')
    e=c._load_session(m).engine
    # The real acquired save bonus is authoritative. Force a failed total
    # within PB; Furnace grants Advantage, so both natural dice match.
    bonus=e.state.actors[owner].saving_throws['CON']
    natural=max(1,16-bonus-1)
    pin_dice(e,[natural,natural])
    prompts=commit(c,t,m,'Recorded external exposure — resolve recorded exposure',owner,
        {'reaction:typed.'+P+'swallow_the_poison':['use']})
    e=reload(tmp_path,m)
    assert any(x.event_type=='D20_REWRITTEN' and x.source_definition_id==P+'swallow_the_poison' for x in e.events),prompts
    assert any(x.condition_id=='condition:typed.venom_adaptation' for x in e.state.actors[owner].conditions.values())
    assert not any(x.condition_id=='condition:typed.diseased' for x in e.state.actors[owner].conditions.values())


def test_blood_venom_resolves_once_and_ends_its_named_state(native_environment,monkeypatch,tmp_path,pin_dice):
    acquire(native_environment,monkeypatch,10)
    c,t,m=setup(tmp_path,native_environment,10)
    e=attack(c,t,m,tmp_path,pin_dice,['blood'])
    assert venoms(e)==['blood']
    before=e.state.actors[FOE].current_hp
    turn(t,m,FOE)
    e=reload(tmp_path,m)
    assert e.state.actors[FOE].current_hp<before
    assert venoms(e)==[]
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==P+'three_sovereign_venoms']
    assert len(packets)==1


def test_myriad_reapplication_can_keep_unspent_marrow(native_environment,monkeypatch,tmp_path,pin_dice):
    acquire(native_environment,monkeypatch)
    c,t,m=setup(tmp_path,native_environment)
    e=attack(c,t,m,tmp_path,pin_dice,['nerve','marrow'],draws=9)
    marrow=next(x.model_dump(mode='json') for x in e.state.actors[FOE].conditions.values()
                if x.condition_id=='condition:typed.sovereign_venom' and x.data['venom']=='marrow')
    turn(t,m,FOE);turn(t,m,OWNER)
    e=c._load_session(m).engine
    name=next(a.display_name for a in e.action_catalog.values() if a.owner_id==OWNER
              and any(x.get('type')=='attack' and x.get('attack_kind')=='unarmed'
                      for x in ((a.parameters or {}).get('typed') or {}).get('effects') or []))
    pin_dice(e,[19]+[1]*30)
    commit(c,t,m,name,FOE,{'choice:needle.path_hit.'+P+'venom_furnace':['Use Venom Furnace'],
        'choice:needle.sovereign_reapply':['keep:marrow'],'choice:needle.sovereign_venom':['blood']})
    e=reload(tmp_path,m)
    assert venoms(e)==['blood','marrow']
    assert next(x.model_dump(mode='json') for x in e.state.actors[FOE].conditions.values()
                if x.condition_id=='condition:typed.sovereign_venom' and x.data['venom']=='marrow')==marrow
    assert not any(x.condition_id=='condition:typed.reaction_denied' for x in e.state.actors[FOE].conditions.values())


def test_poison_strike_and_furnace_share_percentage_defenses(native_environment,monkeypatch,tmp_path,pin_dice):
    acquire(native_environment,monkeypatch,3)
    c,t,m=setup(tmp_path,native_environment,3,mirror=True)
    e=c._load_session(m).engine
    name=next(a.display_name for a in e.action_catalog.values() if a.owner_id==OWNER
              and any(x.get('type')=='attack' and x.get('attack_kind')=='unarmed'
                      for x in ((a.parameters or {}).get('typed') or {}).get('effects') or []))
    before_stamina=e.state.actors[OWNER].resources[STAMINA]
    pin_dice(e,[19]+[1]*20)
    commit(c,t,m,name,FOE,{'choice:needle.venom_furnace_type':['POISON'],'choice:needle.iron_fist_damage_type':['POISON'],
        'choice:needle.path_hit.'+P+'venom_furnace':['Use Venom Furnace']})
    e=reload(tmp_path,m)
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.actor_id==OWNER and FOE in x.target_ids]
    assert packets and all(x.payload['damage_type']=='POISON' for x in packets)
    # At CL3 there is one strike, one matching packet and one resistance step.
    assert len(packets)==1
    assert packets[0].payload['reduced_to']==packets[0].payload['rolled_or_pending_damage']//2
    save=next(x for x in e.events if x.event_type=='SAVE_ROLLED' and x.source_definition_id==P+'venom_furnace')
    assert save.sequence>packets[0].sequence
    assert e.state.actors[OWNER].resources[STAMINA] == before_stamina-1


def test_myriad_success_still_delivers_one_brief_blood_venom(native_environment,monkeypatch,tmp_path,pin_dice):
    acquire(native_environment,monkeypatch)
    c,t,m=setup(tmp_path,native_environment,foe_con=100)
    e=attack(c,t,m,tmp_path,pin_dice,['blood'])
    assert venoms(e)==['blood']
    assert not any(x.condition_id=='condition:typed.poisoned' for x in e.state.actors[FOE].conditions.values())
    save=next(x for x in e.events if x.event_type=='SAVE_ROLLED' and x.source_definition_id==P+'venom_furnace')
    assert save.payload['success'] is True
    hp=e.state.actors[FOE].current_hp
    turn(t,m,FOE)
    e=reload(tmp_path,m)
    assert e.state.actors[FOE].current_hp<hp
    assert venoms(e)==[]


def test_retaliation_success_half_no_venom_no_reaction(native_environment,monkeypatch,tmp_path,pin_dice):
    acquire(native_environment,monkeypatch,14)
    c,t,m=setup(tmp_path,native_environment,14,foe_con=100)
    turn(t,m,FOE)
    e=c._load_session(m).engine
    before=e.state.actors[OWNER].resources[STAMINA]
    pin_dice(e,[1]*20)
    commit(c,t,m,'Force exposure',OWNER,{'choice:needle.poisoned_body_poisoned_world':['use']})
    e=reload(tmp_path,m)
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==P+'poisoned_body_poisoned_world']
    assert len(packets)==1 and packets[0].payload['rolled_or_pending_damage']==1
    assert not venoms(e)
    assert e.state.actors[OWNER].reaction_available
    assert e.state.actors[OWNER].resources[STAMINA]==before-1


@pytest.mark.parametrize('guard',['actor_authority','wrong_collector','malformed_document','expired','new_scene'])
def test_native_exposure_collection_guards(native_environment,monkeypatch,tmp_path,guard):
    from combat.ext.hundred_venom_sources import COLLECT
    from combat.tabletop_service import TabletopService
    acquire(native_environment,monkeypatch,6)
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,6,stage='collected')
    before=c.journey_state(jid)
    if guard in ('actor_authority','wrong_collector','malformed_document'):
        record=before['fact_consent_admission'][-1]
        payload={k:deepcopy(record[k]) for k in ('source','subject','kind','scope','value','expires_at','readers')}
        with pytest.raises(ValueError):
            if guard=='actor_authority':
                c.journey_act(jid,before['revision'],owner,'declare_fact',payload)
            elif guard=='wrong_collector':
                c.journey_act(jid,before['revision'],source,COLLECT,{})
            else:
                payload['value']['invented_authority']='my imagination'
                c.journey_world_fact(jid,before['revision'],payload)
        assert c.journey_state(jid)==before
        return
    if guard=='expired':
        state=c.journey_act(jid,before['revision'],owner,'wait',{'seconds':120})
    else:
        state=c.journey_end_scene(jid,before['revision'],'The exposure scene has ended')
    mid=c.journey_start_combat(jid,state['revision'],{owner:'team:body',source:'team:source'})['match_id']
    e=reload(tmp_path,mid)
    assert not any(a.source_definition_id.startswith('source:hundred_venom.exposure.') for a in e.action_catalog.values())


def test_acquired_scripture_projects_into_ordinary_factory_match(native_environment, monkeypatch):
    from combat.gate5_service import CombatService
    from combat.ext.hundred_venom_acquisition import FAMILY
    from tests.h1_support import ROOT, AN
    project='worker2-ordinary-match'
    root=native_environment['settings'].data_dir/f'native-hundred-venom-{project}-cl10'
    acquired=acquire(native_environment,monkeypatch,10,project)
    service=CombatService(ROOT,root)
    try:
        bundle=service.compile_installed_character(project)
    except Exception:
        import traceback
        pytest.fail(traceback.format_exc())
    assert any(r.get('kind')=='hundred_venom' and r.get('role')=='furnace'
               for r in bundle['typed_passives'])
    assert any(r.get('kind')=='hundred_venom' and r.get('role')=='sovereign'
               for r in bundle['typed_passives'])
    try:
        match=service.create_factory_match(project_ids=[project],opponent_actor_ids=[AN])
    except Exception:
        import traceback
        pytest.fail(traceback.format_exc())
    engine=service._load_session(match).engine
    assert any(r.get('kind')=='hundred_venom' and r.get('role')=='furnace'
               for r in engine.typed_passive_rows['actor:factory.'+project])
    assert acquired['path_and_subpath']['subpath_record_id']==FAMILY


@pytest.mark.parametrize('guard',['unknown_source','missing_access','wrong_path','low_body_attainment','sibling_progression','caller_sheet','expired_access','only_first_tier'])
def test_native_scripture_acquisition_guards(tmp_path,guard):
    import json,zipfile
    from combat.gate5_service import CombatService
    from combat.ext.hundred_venom_acquisition import BODY
    from tests.h1_support import sheet as base_sheet
    family=P.removesuffix('.feature.');aid='actor:factory.learner'
    doc=base_sheet([BODY+'.feature.iron_fist'],cl=18,primary='Stamina')
    paths=doc.setdefault('path_and_subpath',{})
    path='tianxia.path.qi_cultivation' if guard=='wrong_path' else BODY
    paths.update(path_record_id=path,path_record_ids=[path],paths=[{'path_id':path,'attainment':2 if guard=='low_body_attainment' else 3 if guard=='only_first_tier' else 18}])
    doc['identity']['proficiency_bonus']=6
    doc['ability_scores_and_statistics']['technique_save_dc']=16
    doc['ability_scores_and_statistics']['primary_resource']['maximum']=2*paths['paths'][0]['attainment']
    if guard=='sibling_progression':paths['subpath_record_ids']=['tianxia.subpath.body.iron_shirt']
    folder=tmp_path/'portable_characters'/'learner';folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    c=CombatService(ROOT,tmp_path)
    c.tabletop_maps.save({'display_name':'Acquisition guard yard','width_squares':12,'height_squares':12,'terrain':[]})
    arena=next(k for k,v in c.factory_arenas().items() if v['display_name']=='Acquisition guard yard')
    state=c.create_journey(project_ids=['learner'],arena_id=arena,positions={aid:{'x':3,'y':3}},base_paces={aid:30})
    jid=state['journey_id']
    if guard!='missing_access':
        access={'source':family,'subject':aid,'kind':'source_access','scope':'scripture','value':{
            'scripture':family,'source_rule':'The world owner grants actual controlled scripture instruction.'},'expires_at':60,'readers':[aid]}
        state=c.journey_world_fact(jid,state['revision'],access)
    if guard=='expired_access':state=c.journey_act(jid,state['revision'],aid,'wait',{'seconds':60})
    payload={'access_scope':'scripture'}
    if guard=='caller_sheet':payload['sheet']=base_sheet(FEATURES,cl=18)
    if guard=='only_first_tier':
        after=c.journey_acquire_source(jid,state['revision'],aid,family,payload)
        rows=[r for r in after['actors'][aid]['bundle']['typed_passives'] if r.get('kind')=='hundred_venom']
        assert {r['role'] for r in rows}=={'furnace'}
        assert {r['cl'] for r in rows}=={3}
        assert {r['pb'] for r in rows}=={6}
        assert {r['save_dc'] for r in rows}=={16}
        assert after['events'][-1]['earned_features']==[P+'venom_furnace']
        assert CombatService(ROOT,tmp_path).journey_state(jid)==after
        return
    with pytest.raises(ValueError):
        c.journey_acquire_source(jid,state['revision'],aid,'unknown' if guard=='unknown_source' else family,payload)
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    assert not any(r.get('kind')=='hundred_venom' for r in state['actors'][aid]['bundle']['typed_passives'])


@pytest.mark.parametrize('trigger',['grapple','start_grappling'])
def test_retaliation_from_actual_unarmed_grapple(native_environment,tmp_path,pin_dice,trigger):
    c,t,m=setup(tmp_path,native_environment,14)
    turn(t,m,FOE)
    e=c._load_session(m).engine
    action=next(a for a in e.action_catalog.values() if a.owner_id==FOE
                and ((a.parameters or {}).get('typed') or {}).get('unarmed_option')=='grapple')
    pin_dice(e,[1]*80)
    before=e.state.actors[OWNER].resources[STAMINA]
    choices={'choice:needle.poisoned_body_poisoned_world':['use'], 'choice:needle.sovereign_venom':['marrow'],
             'choice:needle.marrow_venom':['Strength']}
    commit(c,t,m,action.display_name,OWNER,choices if trigger=='grapple' else {})
    e=reload(tmp_path,m)
    assert any(x.condition_id.endswith('.grappled') and x.source_actor_id==FOE for x in e.state.actors[OWNER].conditions.values())
    if trigger=='start_grappling':
        # Advance actual turns; offer the no-action choice at the grappler's
        # next start, without an intervening manufactured trigger receipt.
        for _ in range(8):
            if c._load_session(m).engine.state.current_actor_id==FOE and c._load_session(m).engine.state.round_number>1:break
            settle(t,m,t.state(m)['menu']['end_turn'],choices=choices)
        e=reload(tmp_path,m)
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED'
             and x.source_definition_id==P+'poisoned_body_poisoned_world']
    assert len(packets)==1
    assert e.state.actors[OWNER].resources[STAMINA]==before-1
    applied=next(x for x in e.events if x.event_type=='CONDITION_APPLIED' and x.payload.get('condition_id','').endswith('.grappled'))
    assert packets[0].sequence>applied.sequence


def test_myriad_body_poison_is_not_beneficial_swallow_intake(native_environment,tmp_path,pin_dice):
    c,t,m=setup(tmp_path,native_environment,18,mirror=True,mirror_cl=6)
    before=reload(tmp_path,m).state.actors[FOE].resources[STAMINA]
    e=attack(c,t,m,tmp_path,pin_dice,['nerve','marrow'],{
        'choice:needle.venom_furnace_type':['POISON'],'choice:needle.iron_fist_damage_type':['POISON'],
        'reaction:typed.'+P+'swallow_the_poison':['use']})
    assert e.state.actors[FOE].resources[STAMINA]==before-1
    assert not any(x.condition_id=='condition:typed.venom_adaptation' for x in e.state.actors[FOE].conditions.values())
    assert not [x for x in e.events if x.event_type in ('HEALING_COMMITTED','RESOURCE_GAINED') and x.actor_id==FOE]


@pytest.mark.parametrize('speeds,expected',[( (30,40,20),(15,25,5)),((10,40,20),(0,25,5)),((30,10,10),(15,0,0))])
def test_marrow_reduces_independent_native_speeds(native_environment,tmp_path,pin_dice,speeds,expected):
    from combat.flight import profile,speed_available
    from combat.roof_movement import profile as climb_profile
    c,t,m=setup(tmp_path,native_environment,10,foe_speeds=speeds)
    initial=reload(tmp_path,m)
    assert (initial._effective_speed(initial.state.actors[FOE]),profile(initial,initial.state.actors[FOE]).speed_ft,
            climb_profile(initial,initial.state.actors[FOE]).speed_ft)==speeds
    e=attack(c,t,m,tmp_path,pin_dice,['marrow'])
    target=e.state.actors[FOE]
    assert (e._effective_speed(target),profile(e,target).speed_ft,climb_profile(e,target).speed_ft)==expected
    assert speed_available(e,target,'walk') is (expected[0]>0)
    assert speed_available(e,target,'fly') is (expected[1]>0)
    turn(t,m,FOE)
    e=reload(tmp_path,m)
    moves=[r for r in e.legal_candidates() if r.destination and r.destination.z>0 and r.metadata.get('movement_mode')=='fly']
    from combat.flight import remaining,reachable
    raw=e._movement_candidates(e.state.actors[FOE]) if not moves and expected[1]>0 else []
    vetoes=[]
    if raw:
        from combat import ext
        for provider in ext.callbacks('candidate_allowed'):
            if ext.invoke('candidate_allowed',provider,e,e.state.actors[FOE],raw[0],e.action_catalog.get(raw[0].source_definition_id)) is False:
                vetoes.append(provider.__module__+'.'+provider.__name__)
    assert bool(moves) is (expected[1]>0),{'raw_moves':len(raw),'vetoes':vetoes,'remaining':{k:remaining(e,e.state.actors[FOE],k) for k in ('walk','fly','climb')},'profile':profile(e,e.state.actors[FOE]),'flags':e.state.actors[FOE].turn_flags,'native_routes':len(reachable(e,e.state.actors[FOE])),'candidate_modes':sorted({r.metadata.get('movement_mode','walk') for r in e.legal_candidates() if r.destination})}
    if moves:
        settle(t,m,moves[0].candidate_id,choices={})
        moved=reload(tmp_path,m)
        assert moved.state.actors[FOE].position.z>0


def test_native_multiattack_shares_one_furnace_use(native_environment,tmp_path,pin_dice):
    c,t,m=setup(tmp_path,native_environment,18)
    e=c._load_session(m).engine
    action=next(a for a in e.action_catalog.values() if a.owner_id==OWNER
                and any(x.get('type')=='attack' and x.get('attack_kind')=='unarmed'
                        for x in ((a.parameters or {}).get('typed') or {}).get('effects',[])))
    before=e.state.actors[OWNER].resources[STAMINA]
    count=next(x['count'] for x in action.parameters['typed']['effects'] if x.get('type')=='attack')
    assert count>=3
    pin_dice(e,[19,1,1,1,1,1,1,19,1,19,1])
    prompts=commit(c,t,m,action.display_name,FOE,{'choice:needle.path_hit.'+P+'venom_furnace':['Use Venom Furnace'],
        'choice:needle.sovereign_venom':['nerve','marrow'],'choice:needle.marrow_venom':['Strength']})
    e=reload(tmp_path,m)
    assert len([x for x in e.events if x.event_type=='ATTACK_ROLLED' and x.actor_id==OWNER])==count
    assert len([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.path_hit.'+P+'venom_furnace'])==1
    assert e.state.actors[OWNER].resources[STAMINA]==before-1
    assert len([x for x in e.events if x.event_type=='SAVE_ROLLED' and x.source_definition_id==P+'venom_furnace'])==1


@pytest.mark.parametrize('ability',['Strength','Dexterity'])
def test_marrow_consumes_only_its_chosen_next_native_save(native_environment,tmp_path,pin_dice,ability):
    c,t,m=setup(tmp_path,native_environment,10)
    e=attack(c,t,m,tmp_path,pin_dice,['marrow'],{'choice:needle.marrow_venom':[ability]})
    def held(e):
        return [x for x in e.state.actors[FOE].conditions.values()
                if x.condition_id=='condition:typed.save_against' and x.source_definition_id==P+'three_sovereign_venoms']
    assert len(held(e))==1
    other='DEX' if ability=='Strength' else 'STR'
    chosen=ability[:3].upper()
    commit(c,t,m,other+' save probe',FOE)
    e=reload(tmp_path,m);assert len(held(e))==1
    commit(c,t,m,chosen+' save probe',FOE)
    e=reload(tmp_path,m);assert not held(e)
    event=next(x for x in reversed(e.events) if x.event_type=='SAVE_ROLLED' and x.actor_id==FOE)
    assert event.payload['mode']=='DISADVANTAGE'
    assert any(x.condition_id=='condition:typed.sovereign_venom' and x.data['venom']=='marrow'
               for x in e.state.actors[FOE].conditions.values())
    assert e._effective_speed(e.state.actors[FOE])==15


def test_cold_source_overlay_rejects_a_new_incompatible_body_progression(native_environment,tmp_path):
    import json,zipfile
    from combat.gate5_service import CombatService
    c,_,_,owner,source,jid=native_exposure(tmp_path,native_environment,18,stage='collected')
    state=c.journey_state(jid)
    state=c.journey_act(jid,state['revision'],owner,'finish',{})
    project=owner.removeprefix('actor:factory.')
    archive=tmp_path/'portable_characters'/project/'current.zip'
    with zipfile.ZipFile(archive) as z:
        document=json.loads(z.read('Tianxia_Owner_Character_Sheet_v1.json'))
    document['path_and_subpath']['subpath_record_ids']=['tianxia.subpath.body.nine_star_meridian_body']
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(document))
    with pytest.raises(ValueError,match='another Subpath progression'):
        CombatService(ROOT,tmp_path).create_journey(project_ids=[project],arena_id=state['battlefield']['stable_id'],
            positions={owner:state['actors'][owner]['position']},base_paces={owner:30})
    assert c.journey_state(jid)==state


def test_native_effect_setup_binding_does_not_grant_another_creatures_source(native_environment,tmp_path,pin_dice):
    from combat.fight_setup import authorized
    from combat.gate2_runtime_models import FightSetupTask
    c,t,m=setup(tmp_path,native_environment,10)
    e=attack(c,t,m,tmp_path,pin_dice,['blood'])
    held=next(x for x in e.state.actors[FOE].conditions.values() if x.condition_id=='condition:typed.blood_venom')
    task=FightSetupTask(actor_id=FOE,source_id=P+'three_sovereign_venoms',effect_instance_id=held.instance_id)
    assert authorized(e,e.state.actors[FOE],task)
    assert not authorized(e,e.state.actors[ALLY],task)
    assert not authorized(e,e.state.actors[FOE],task.model_copy(update={'source_id':P+'venom_furnace'}))
    assert not authorized(e,e.state.actors[FOE],task.model_copy(update={'effect_instance_id':'missing-native-instance'}))
    assert not authorized(e,e.state.actors[FOE],task.model_copy(update={'effect_instance_id':None}))
    assert not any(r.get('kind')=='hundred_venom' for r in e.typed_passive_rows[FOE])


def test_native_myriad_rider_overcomes_immunity_but_unrelated_poison_does_not(native_environment,tmp_path,pin_dice):
    c,t,m=setup(tmp_path,native_environment,18,mirror=True)
    e=attack(c,t,m,tmp_path,pin_dice,['nerve','marrow'])
    roll=next(x for x in e.events if x.event_type=='DAMAGE_ROLLED' and x.source_definition_id==P+'venom_furnace')
    packet=next(x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==P+'venom_furnace')
    assert packet.payload['hp_damage']==roll.payload['total']>0
    turn(t,m,FOE)
    before=reload(tmp_path,m).state.actors[OWNER].current_hp
    commit(c,t,m,'Poison exposure',OWNER)
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].current_hp==before
    external=next(x for x in reversed(e.events) if x.event_type=='DAMAGE_COMMITTED' and x.actor_id==FOE)
    assert external.payload['hp_damage']==0
