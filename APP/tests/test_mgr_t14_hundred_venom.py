"""Earned restricted scripture -> native table commits -> cold mechanical replay."""
from copy import deepcopy
import pytest
from app.api import create_app
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE
from tests.cw2_service_support import add_action, seal
from tests.test_p15_save_condition_duration import pin_dice  # noqa: F401
P = 'tianxia.subpath.body.hundred_venom_body.feature.'
FEATURES = [P + f for f in ('venom_furnace','swallow_the_poison','three_sovereign_venoms','poisoned_body_poisoned_world','myriad_venom_immortal')]
STAMINA = 'resource:core.stamina'

def acquire(catalog_environment, monkeypatch, cl=18):
    # Reuse only a successfully validated, genuinely acquired source sheet in
    # this one disposable catalog session. Every caller gets its own copy; no
    # ownership, feature record, cost or source receipt is manufactured.
    from copy import deepcopy
    cache = catalog_environment.setdefault('_hundred_venom_acquired_sheets', {})
    if cl in cache:
        return deepcopy(cache[cl])
    monkeypatch.setenv('TIANXIA_BROWSER_EXECUTABLE','/var/tmp/auto-audit/NO_BROWSER_ALLOWED')
    app=create_app(catalog_environment['settings'])
    builder=app.state.character_builder
    project=builder.create_project(working_name='Hundred Venom disciple',concept='Restricted Hundred-Venom scripture disciple',
        source_reference=None,target_cl=cl,power_band='rival/boss',creation_mode='detailed',
        generation_route='ai_bootstrap',ability_scores={},autogen_seed='HUNDRED-VENOM-NATIVE',
        selections={'path_choice':['tianxia.path.body_refining'],
                    'subpath_choice':['tianxia.subpath.body.hundred_venom_body']},method_planning_mode='AUTO')
    builder.commit_normal_first_cycle_catalog_choices(project['project_id'])
    run=app.state.character_creation.start(project['project_id'],execution_mode='STANDARD_API',
        idempotency_key='hundred-venom-acquisition',controller_route='DETERMINISTIC_CREATIVE_CONTROLLER')
    assert run['status'] in ('READY_FOR_REVIEW','NEEDS_REVIEW'),run
    if run['status']=='NEEDS_REVIEW':
        assert [b['code'] for b in run['blockers']]==['COMMAND6_CHARACTER_GM_CONSUMER_FAILED'], run['blockers']
    candidate=app.state.character_creation.load_candidate_gm_context(run['run_id'])
    sheet=candidate['owner_character_sheet']
    expected={feature for feature,minimum in zip(FEATURES,(3,6,10,14,18)) if cl>=minimum}
    # Native Subpath progression is earned from sealed causal level events;
    # path_feature_record_ids is the separate legacy direct Path-feature list.
    earned = [r for r in sheet['path_and_subpath']['earned_feature_occurrences']
              if r.get('parent_record_id') == P.removesuffix('.feature.')]
    assert {r['feature_id'] for r in earned} == expected
    assert all(r['owning_path_id'] == 'tianxia.path.body_refining'
               and r['parent_subpath_record_id'] == P.removesuffix('.feature.')
               and r['source_backed'] is True and r['source_packet_ids']
               and r['acquisition_event_hash'] and r['attainment_event_hash']
               for r in earned)
    cache[cl] = deepcopy(sheet)
    return deepcopy(sheet)


def setup(tmp_path, env, cl=18, *, mirror=False):
    document = acquire(env, None, cl)
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask':True})
    def scenario(bs):
        if mirror:
            bs[2] = compile_character(document, actor_id=FOE, reaction_plan={'ask':True})
        for b, initiative in zip(bs,(100,0,-100)):
            b['actor_template']['initiative_bonus']=initiative
            b['actor_template']['maximum_hp']=1000
            seal(b)
        for kind in ('acid','poison','force'):
            add_action(bs[2],kind.title()+' exposure',[{'type':'damage','flat':1,'damage_types':[kind],'applies_to':'target'}])
        for category in ('disease','ordinary_disease','curse'):
            add_action(bs[2],category+' save',[{'type':'save','ability':'con','save_categories':[category],
              'on_fail':[{'type':'condition','condition':category,'applies_to':'target','duration':'one_minute'}],'on_success':[]}])
    return fixture(tmp_path,[],cl=cl,primary='Stamina',owner_bundle=bundle,bundle_transform=scenario,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':5,'y':6},FOE:{'x':3,'y':7}})


def commit(c,t,m,name,target,picks=None):
    return settle(t,m,candidate(c,m,name,target=target).candidate_id,choices=picks or {})


def venoms(e,who=FOE):
    return sorted(x.data['venom'] for x in e.state.actors[who].conditions.values()
                  if x.condition_id=='condition:typed.sovereign_venom')


def attack(c,t,m,tmp_path,pin_dice,choices):
    e=c._load_session(m).engine
    name=next(a.display_name for a in e.action_catalog.values() if a.owner_id==OWNER
              and any(x.get('type')=='attack' and x.get('attack_kind')=='unarmed'
                      for x in ((a.parameters or {}).get('typed') or {}).get('effects') or []))
    pin_dice(e,[19]+[1]*30)
    commit(c,t,m,name,FOE,{'choice:needle.path_hit.'+P+'venom_furnace':['Use Venom Furnace'],
        'choice:needle.sovereign_venom':choices,'choice:needle.marrow_venom':['Dexterity']})
    return reload(tmp_path,m)


@pytest.mark.parametrize('cl',[3,6,10,14,18])
def test_real_restricted_scripture_progression(catalog_environment,monkeypatch,tmp_path,cl):
    acquire(catalog_environment,monkeypatch,cl)
    c,t,m=setup(tmp_path,catalog_environment,cl)
    e=reload(tmp_path,m)
    roles={r.get('role') for r in e.typed_passive_rows[OWNER] if r.get('kind')=='hundred_venom'}
    assert roles=={r for r,level in [('furnace',3),('sovereign',10),('poisoned_world',14),('myriad',18)] if cl>=level}


@pytest.mark.parametrize('kind,adapt',[('acid',False),('poison',True)])
def test_swallow_adapts_only_zero_poison(catalog_environment,monkeypatch,tmp_path,kind,adapt):
    acquire(catalog_environment,monkeypatch,6)
    c,t,m=setup(tmp_path,catalog_environment,6)
    turn(t,m,FOE)
    before=reload(tmp_path,m).state.actors[OWNER].resources[STAMINA]
    prompts=commit(c,t,m,kind.title()+' exposure',OWNER,{'reaction:typed.'+P+'swallow_the_poison':['use']})
    e=reload(tmp_path,m)
    assert e.state.actors[OWNER].resources[STAMINA]==before-1,prompts
    assert any(x.condition_id=='condition:typed.venom_adaptation' for x in e.state.actors[OWNER].conditions.values()) is adapt


def test_venoms_capture_source_level(catalog_environment,monkeypatch,tmp_path,pin_dice):
    acquire(catalog_environment,monkeypatch)
    c,t,m=setup(tmp_path,catalog_environment)
    e=attack(c,t,m,tmp_path,pin_dice,['nerve','marrow'])
    assert venoms(e)==['marrow','nerve']
    assert all('source_cl' in x.data for x in e.state.actors[FOE].conditions.values()
               if x.condition_id=='condition:typed.sovereign_venom')


def test_retaliation_cannot_trigger_another_retaliation(catalog_environment,monkeypatch,tmp_path,pin_dice):
    acquire(catalog_environment,monkeypatch,14)
    c,t,m=setup(tmp_path,catalog_environment,14,mirror=True)
    turn(t,m,FOE)
    pin_dice(c._load_session(m).engine,[1]*30)
    commit(c,t,m,'Force exposure',OWNER,{'choice:needle.poisoned_body_poisoned_world':['use'],
                                        'choice:needle.sovereign_venom':['nerve']})
    e=reload(tmp_path,m)
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.source_definition_id==P+'poisoned_body_poisoned_world']
    assert len(packets)==1
    assert packets[0].actor_id==OWNER


@pytest.mark.parametrize('category,immune',[('ordinary_disease',True),('curse',False)])
def test_myriad_ordinary_disease_boundary(catalog_environment,monkeypatch,tmp_path,pin_dice,category,immune):
    acquire(catalog_environment,monkeypatch)
    c,t,m=setup(tmp_path,catalog_environment)
    turn(t,m,FOE)
    pin_dice(c._load_session(m).engine,[1]*10)
    commit(c,t,m,category+' save',OWNER)
    e=reload(tmp_path,m)
    assert any(x.condition_id.endswith('.'+category) for x in e.state.actors[OWNER].conditions.values()) is (not immune)
