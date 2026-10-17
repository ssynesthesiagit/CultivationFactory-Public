"""Gravity second pass: accepted table/service intents and cold replay, including fixture probes sealed before genesis."""
import copy
import json
import zipfile
from pathlib import Path
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat import falling
from combat.ext import effective_size
from tests.h1_support import sheet
from tests import test_auto67_gravity as G
from tests.test_tabletop_hunt6 import on_hold

ROOT = Path(__file__).resolve().parents[1]
ME, FOE = (FACTORY_ACTOR_PREFIX + 'a2gravity-' + name for name in ('me', 'foe'))
ALLY = FACTORY_ACTOR_PREFIX + 'a2gravity-ally'
FOCUS = 'resource:core.martial_focus'
CRUSH = 'insight.crushing-focus'
STANCE = 'insight.mountain-stance'
HAMMER = 'TAL_GRAVITY_FALLING_HAMMER'
WS = 'TAL_GRAVITY_WEIGHT_SHIFT_BASE'
FLAG = 'once_per_turn:gravity_crushing_focus'


def fight(tmp_path, talents, *, rival=(), dc=50, focus=0, ally=False, legacy_protection=False, primary="Stamina"):
    bundles=[]
    for actor_id, mids in ((ME, talents),(FOE, rival), *([(ALLY, ())] if ally else [])):
        doc=sheet(list(mids), cl=17, dc=dc, primary=primary, score=30,
                  kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.fu','quantity':1}]}})
        doc.setdefault('spheres_and_talents', {})['cultivation_insight_record_ids']=[m for m in mids if m.startswith('insight.')]
        doc['spheres_and_talents']['learned_talent_record_ids']=[m for m in mids if not m.startswith('insight.')]
        doc['identity']['display_name']=actor_id.rsplit('-',1)[-1].title()
        doc['ability_scores_and_statistics']['hit_points']['maximum']=1000
        folder=tmp_path/'portable_characters'/actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
        b=compile_character(doc,actor_id=actor_id,reaction_plan={'ask':True})
        if legacy_protection:
            for row in b.get('typed_passives',[]):row.pop('first_thirty_feet',None)
        for r in b['actor_template']['resources']:
            if r.get('resource_id')==FOCUS:r['initial']=focus
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
        bundles.append(b)
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
    ids=[ME,FOE,*([ALLY] if ally else [])]
    teams={ME:'a',FOE:'b',**({ALLY:'a'} if ally else {})}
    starts={ME:{'x':3,'y':6},FOE:{'x':4,'y':6},**({ALLY:{'x':3,'y':7}} if ally else {})}
    mid=combat._finish_factory_match(bundles,ids,teams,starts,combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [ME],[FOE],control_modes={a:'MANUAL' for a in ids},match_seed='A2GRAVITY',display_name='Gravity test',maximum_rounds=15)['match_id']
    advance(combat,table,mid,ME)
    return combat,table,mid


def advance(combat,table,mid,actor):
    for _ in range(6):
        if combat._load_session(mid).engine.state.current_actor_id==actor:return
        G._table_press(table,mid,'End Turn')
    raise AssertionError('turn missing')


def reload(combat,mid,tmp_path):
    state=combat._load_session(mid).engine.state.model_dump(mode='json')
    fresh=CombatService(ROOT,tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode='json')==state
    assert fresh.verify()['status']==fresh.mechanical.replay()['status']=='PASS'
    return fresh.engine


def use(combat,table,mid,label,answer=None):
    candidates=list(combat._load_session(mid).engine.legal_candidates())
    if label=='End Turn':c=next(c for c in candidates if c.kind.value=='END_TURN')
    else:
        choices=[c for c in candidates if c.display_name==label] or [c for c in candidates if label.lower() in c.display_name.lower()]
        assert choices, [c.display_name for c in candidates]
        c=next((c for c in choices if FOE in c.target_ids and not c.source_definition_id.endswith('#thrown')),choices[0])
    answers=[];asked=[]
    for _ in range(20):
        result=G._table_send(table,mid,c.candidate_id,answers)
        if result['status']=='COMMITTED':return result,asked
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction'];asked.append(prompt);choice=prompt.get('choice') or {}
        picked=answer(prompt,choice) if answer else None
        reply={**prompt['context'],'selection':'DECLINE'}
        if choice and picked is not False:
            reply.update(selection='USE',option_ids=list(picked or (choice.get('preferred') or [choice['options'][0]['id']])[:1]))
        answers.append(reply)
    raise AssertionError('action never committed')


def submit(combat,mid,label,target=FOE):
    session=combat._load_session(mid)
    candidates=[c for c in session.engine.legal_candidates() if label.lower() in c.display_name.lower() and (target is None or target in c.target_ids)]
    assert candidates, [c.display_name for c in session.engine.legal_candidates()]
    c=candidates[0]
    session.submit_intent(ActionIntent(intent_id=f'a2gravity:{session.engine.state.state_version}',decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=c.actor_id,target_ids=c.target_ids,
        destination=c.destination,option_ids=c.option_ids),primary_decision_record=None,reaction_provider=None)


def focus_damage(engine):
    return [e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and (e.payload or {}).get('display_source_id')==CRUSH]


@pytest.mark.parametrize('dc,failed',[(50,True),(1,False)])
def test_crushing_focus_real_gravitic_pull_save(tmp_path,dc,failed):
    combat,table,mid=fight(tmp_path,[CRUSH,'tianxia.talent.gravity.gravitic_pull'],dc=dc)
    use(combat,table,mid,'Gravitic Pull')
    e=reload(combat,mid,tmp_path)
    assert bool(focus_damage(e)) is failed
    assert bool(e.state.actors[ME].turn_flags.get(FLAG)) is failed
    if failed:assert focus_damage(e)[0].payload['hp_damage']==e.state.actors[ME].proficiency_bonus


def test_crushing_focus_once_actual_turn_other_sphere_and_cold_reset(tmp_path,monkeypatch):
    combat,table,mid=fight(tmp_path,[CRUSH,'tianxia.talent.gravity.gravitic_pull'])
    from combat.typed_executor import Context, run_effects
    def saves(engine):
        actor,target=engine.state.actors[ME],engine.state.actors[FOE]
        action=next(a for a in engine.action_catalog.values() if a.owner_id==ME and a.parameters.get('typed',{}).get('source')=='tianxia.talent.gravity.gravitic_pull')
        typed=copy.deepcopy(action.parameters['typed']);typed['numbers']['save_dc']=50
        effect={'type':'save','ability':'str','on_fail':[],'on_success':[]}
        other={**typed,'sphere':'tianxia.sphere.fire'}
        run_effects(Context(engine,actor,action,engine._active_intent,other,[target],target,{}),[effect])
        assert FLAG not in actor.turn_flags
        run_effects(Context(engine,actor,action,engine._active_intent,typed,[target],target,{}),[effect,effect,effect])
    on_hold(monkeypatch,saves)
    submit(combat,mid,'Hold',target=None)
    e=reload(combat,mid,tmp_path);assert len(focus_damage(e))==1
    use(combat,table,mid,'End Turn');advance(combat,table,mid,FOE)
    e=reload(combat,mid,tmp_path);assert FLAG not in e.state.actors[ME].turn_flags
    submit(combat,mid,'Hold',target=None)
    assert len(focus_damage(reload(combat,mid,tmp_path)))==2


@pytest.mark.parametrize('benefit',['damage','focus'])
def test_crushing_focus_melee_weight_art_choice(tmp_path,benefit):
    combat,table,mid=fight(tmp_path,[CRUSH,WS],focus=0)
    use(combat,table,mid,'Weight Shift: Body Heavying')
    def answer(prompt,choice):
        source=prompt['context']['reaction_source_id']
        if source.endswith('gravity_weighted_strike'):return ['heavying:stamina']
        if source.endswith('gravity_crushing_focus'):return [benefit]
        if source.endswith('gravity_heavying'):return ['prone']
        return False
    _,asked=use(combat,table,mid,'Fu (Short Axe)',answer)
    e=reload(combat,mid,tmp_path)
    q=[q for q in asked if q['context']['reaction_source_id'].endswith('gravity_crushing_focus')]
    assert q and 'Crushing Focus' in str(q[0]), (asked, e.state.actors[ME].resources, [(r.reason,r.total) for r in e.rolls], [(ev.event_type,ev.source_definition_id) for ev in e.events[-15:]])
    assert bool(focus_damage(e)) is (benefit=='damage')
    assert e.state.actors[ME].resources[FOCUS]==int(benefit=='focus')


@pytest.mark.parametrize('height,expected',[(2,0),(6,0),(8,1),(12,3),(50,20)])
def test_falling_hammer_first_thirty_feet_in_service(tmp_path,monkeypatch,height,expected):
    combat,table,mid=fight(tmp_path,[HAMMER])
    on_hold(monkeypatch,lambda engine: falling.displace(engine,engine.state.actors[ME],height,'test:descent',intent=engine._active_intent))
    submit(combat,mid,'Hold',target=None)
    e=reload(combat,mid,tmp_path)
    rolls=[r for r in e.rolls if r.reason=='FALLING_DAMAGE']
    assert len(rolls)==int(expected>0)
    if rolls:assert len(rolls[-1].dice)==expected
    assert e.state.actors[ME].position.z==0
    assert any(ev.event_type=='MOVEMENT_COMMITTED' and ev.payload.get('fall_distance_ft')==height*5 for ev in e.events)


@pytest.mark.parametrize('anchor,reduction',[(False,5),(True,15)])
def test_mountain_stance_size_save_advantage_and_reduction(tmp_path,anchor,reduction):
    mids=[WS,STANCE]+(['TAL_GRAVITY_ANCHOR_STANCE'] if anchor else [])
    combat,table,mid=fight(tmp_path,mids)
    use(combat,table,mid,'Weight Shift: Body Heavying');e=reload(combat,mid,tmp_path)
    assert effective_size.cells(e,e.state.actors[ME],'act',{'grapple','shove'})==2
    use(combat,table,mid,'End Turn');advance(combat,table,mid,FOE)
    before=reload(combat,mid,tmp_path).state.actors[ME].position
    use(combat,table,mid,'Shove: Push 5 ft')
    e=reload(combat,mid,tmp_path)
    rolls=[r for r in e.rolls if r.actor_id==ME and r.reason.startswith('SAVE:')]
    assert rolls[-1].mode=='ADVANTAGE'
    assert e.state.actors[ME].position==before
    # Quote the pure reduction from the same persisted supported/mode state.
    from combat.typed_executor import Context
    from combat.ext.gravity import anchor_reduction
    action=next(a for a in e.action_catalog.values() if a.owner_id==FOE and 'Shove' in a.display_name)
    ctx=Context(e,e.state.actors[FOE],action,None,action.parameters['typed'],[e.state.actors[ME]],e.state.actors[ME],{})
    assert anchor_reduction(ctx,e.state.actors[ME])==reduction


@pytest.mark.parametrize('distance,take,expected',[(5,True,1),(5,False,0),(20,True,0)])
def test_anchor_stopped_movement_optional_reaction(tmp_path,monkeypatch,distance,take,expected):
    combat,table,mid=fight(tmp_path,[WS,'TAL_GRAVITY_ANCHOR_STANCE'])
    use(combat,table,mid,'Weight Shift: Body Heavying')
    use(combat,table,mid,'End Turn');advance(combat,table,mid,FOE)
    from combat.typed_executor import Context, run_effects
    def push(engine):
        actor,target=engine.state.actors[FOE],engine.state.actors[ME]
        action=next(a for a in engine.action_catalog.values() if a.owner_id==FOE and a.resolution_kind=='TYPED')
        ctx=Context(engine,actor,action,engine._active_intent,{'numbers':{'pb':6}},[target],target,{})
        run_effects(ctx,[{'type':'forced_movement','distance_ft':distance,'direction':'away','applies_to':'target'}])
    on_hold(monkeypatch,push)
    before=reload(combat,mid,tmp_path).state.actors[ME].position
    def answer(prompt,choice):
        if prompt['context']['reaction_source_id'].endswith('gravity_anchor_focus'):return ['focus'] if take else False
        return False
    _,asked=use(combat,table,mid,'Hold',answer)
    e=reload(combat,mid,tmp_path);actor=e.state.actors[ME]
    assert actor.resources[FOCUS]==expected
    assert actor.reaction_available is (not bool(expected))
    windows=[q for q in asked if q['context']['reaction_source_id'].endswith('gravity_anchor_focus')]
    assert bool(windows) is (distance<=10)
    assert (actor.position==before) is (distance<=10)
    if windows:
        assert 'Reaction' in str(windows[0]) and 'Anchor Stance' in str(windows[0])


def test_mountain_and_anchor_unsupported_are_inert(tmp_path,monkeypatch):
    combat,table,mid=fight(tmp_path,[WS,STANCE,'TAL_GRAVITY_ANCHOR_STANCE'])
    use(combat,table,mid,'Weight Shift: Body Heavying')
    def rise(engine):
        actor=engine.state.actors[ME]
        engine._apply_condition(actor,'condition:typed.test_hover','test:hover',ME,expires_on=None,
                                data={'fly_speed_ft':30,'flight_hover':1})
        falling.displace(engine,actor,2,'test:unsupported',intent=engine._active_intent)
    on_hold(monkeypatch,rise);submit(combat,mid,'Hold',target=None)
    e=reload(combat,mid,tmp_path);actor=e.state.actors[ME]
    assert actor.position.z==2 and not falling.supported(e,actor)
    assert effective_size.cells(e,actor,'act',{'shove'})==1
    from combat.typed_executor import Context
    from combat.ext.gravity import anchor_reduction, mountain_stance_save
    action=next(a for a in e.action_catalog.values() if a.owner_id==FOE and a.resolution_kind=='TYPED')
    ctx=Context(e,e.state.actors[FOE],action,None,action.parameters['typed'],[actor],actor,{})
    assert anchor_reduction(ctx,actor) is None
    assert mountain_stance_save(ctx,actor,'STR',{'prone','forced_movement'}) is None


def test_anchor_shared_ally_reaction_and_owner_turn_expiry(tmp_path,monkeypatch):
    combat,table,mid=fight(tmp_path,[WS,'TAL_GRAVITY_ANCHOR_STANCE'],ally=True)
    use(combat,table,mid,'Weight Shift: Body Heavying')
    use(combat,table,mid,'Anchor Stance: Steady',lambda p,c:[ALLY])
    e=reload(combat,mid,tmp_path)
    shared=[c for c in e.state.actors[ALLY].conditions.values() if c.condition_id=='condition:typed.gravity_anchor_share']
    assert len(shared)==1 and shared[0].data.get('stopped_focus')==1
    use(combat,table,mid,'End Turn');advance(combat,table,mid,FOE)
    from combat.typed_executor import Context,run_effects
    def push(engine):
        actor,target=engine.state.actors[FOE],engine.state.actors[ALLY]
        action=next(a for a in engine.action_catalog.values() if a.owner_id==FOE and a.resolution_kind=='TYPED')
        run_effects(Context(engine,actor,action,engine._active_intent,{'numbers':{}},[target],target,{}),
                    [{'type':'forced_movement','distance_ft':5,'direction':'away','applies_to':'target'}])
    on_hold(monkeypatch,push)
    use(combat,table,mid,'Hold',lambda p,c:['focus'] if p['context']['reaction_source_id'].endswith('gravity_anchor_focus') else False)
    e=reload(combat,mid,tmp_path);assert e.state.actors[ALLY].resources[FOCUS]==1
    assert not e.state.actors[ALLY].reaction_available and e.state.actors[ME].resources[FOCUS]==0
    use(combat,table,mid,'End Turn');advance(combat,table,mid,ME)
    e=reload(combat,mid,tmp_path)
    assert not any(c.condition_id=='condition:typed.gravity_anchor_share' for c in e.state.actors[ALLY].conditions.values())


def test_crushing_focus_native_gravity_reaction_context(tmp_path,monkeypatch):
    combat,table,mid=fight(tmp_path,[CRUSH])
    from combat.ext.gravity import _owner_ctx
    from combat.typed_executor import run_effects
    def trigger(engine):
        ctx=_owner_ctx(engine,engine.state.actors[ME],'tianxia.talent.gravity.orbit_breaking_guard',
                       engine.state.actors[FOE],engine._active_intent,'Orbit-Breaking Guard')
        assert not ctx.typed.get('sphere')
        run_effects(ctx,[{'type':'save','ability':'dex','dc':50,'on_fail':[],'on_success':[]}])
    on_hold(monkeypatch,trigger);submit(combat,mid,'Hold',target=None)
    e=reload(combat,mid,tmp_path);assert len(focus_damage(e))==1
    assert e.state.actors[ME].resources[FOCUS]==0


def test_anchor_completed_reductions_combine_before_focus_choice(tmp_path,monkeypatch):
    from combat import ext
    ext.effects()
    monkeypatch.setitem(ext._HOOKS,'forced_movement_reduction', [*ext._HOOKS.get('forced_movement_reduction',[]),lambda ctx,subject:5])
    combat,table,mid=fight(tmp_path,[WS,'TAL_GRAVITY_ANCHOR_STANCE'])
    use(combat,table,mid,'Weight Shift: Body Heavying')
    use(combat,table,mid,'End Turn');advance(combat,table,mid,FOE)
    from combat.typed_executor import Context,run_effects
    def push(engine):
        actor,target=engine.state.actors[FOE],engine.state.actors[ME]
        action=next(a for a in engine.action_catalog.values() if a.owner_id==FOE and a.resolution_kind=='TYPED')
        run_effects(Context(engine,actor,action,engine._active_intent,{'numbers':{}},[target],target,{}),
                    [{'type':'forced_movement','distance_ft':15,'direction':'away','applies_to':'target'}])
    on_hold(monkeypatch,push)
    use(combat,table,mid,'Hold',lambda p,c:['focus'] if p['context']['reaction_source_id'].endswith('gravity_anchor_focus') else False)
    e=reload(combat,mid,tmp_path)
    assert e.state.actors[ME].resources[FOCUS]==1 and not e.state.actors[ME].reaction_available


@pytest.mark.parametrize('rewritten_success',[False,True])
def test_crushing_focus_repeat_save_uses_final_outcome(tmp_path,monkeypatch,rewritten_success):
    combat,table,mid=fight(tmp_path,[CRUSH,'tianxia.talent.gravity.heaven_s_weight'])
    use(combat,table,mid,'Heaven')
    e=reload(combat,mid,tmp_path);assert len(focus_damage(e))==1
    use(combat,table,mid,'End Turn');advance(combat,table,mid,FOE)
    if rewritten_success:
        from tests.test_lock_choices import install
        install(monkeypatch,'repeat_save_failed',lambda engine,resolution:{'result':'SUCCESS','settled_by':'test:final-save'})
    use(combat,table,mid,'End Turn')
    e=reload(combat,mid,tmp_path)
    assert len(focus_damage(e))==(1 if rewritten_success else 2)


def test_anchor_chosen_forced_path_uses_same_completed_reductions(tmp_path,monkeypatch):
    combat,table,mid=fight(tmp_path,[WS,'TAL_GRAVITY_ANCHOR_STANCE'])
    use(combat,table,mid,'Weight Shift: Body Heavying')
    use(combat,table,mid,'End Turn');advance(combat,table,mid,FOE)
    from combat.typed_executor import Context
    from combat import movement_paths
    def push(engine):
        actor,target=engine.state.actors[FOE],engine.state.actors[ME]
        action=next(a for a in engine.action_catalog.values() if a.owner_id==FOE and a.resolution_kind=='TYPED')
        ctx=Context(engine,actor,action,engine._active_intent,{'numbers':{}},[target],target,{})
        route=[target.position,target.position.model_copy(update={'x':target.position.x-1})]
        assert movement_paths.resolve(engine,target,route,'test:chosen-forced',kind='forced',feet=5,
            intent=engine._active_intent,source_actor_id=FOE,ctx=ctx)==0
    on_hold(monkeypatch,push)
    use(combat,table,mid,'Hold',lambda p,c:['focus'] if p['context']['reaction_source_id'].endswith('gravity_anchor_focus') else False)
    e=reload(combat,mid,tmp_path)
    assert e.state.actors[ME].resources[FOCUS]==1 and not e.state.actors[ME].reaction_available


def test_mountain_stance_native_prone_save_and_ordinary_save(tmp_path,monkeypatch):
    combat,table,mid=fight(tmp_path,[WS,STANCE])
    use(combat,table,mid,'Weight Shift: Body Heavying')
    def native(engine):
        actor=engine.state.actors[ME]
        engine._roll_save(actor,'STR',50,'test:native-prone',roll_context={'named':['prone'],'source_actor_id':FOE})
        engine._roll_save(actor,'CON',50,'test:native-unrelated',roll_context={'named':[],'source_actor_id':FOE})
    on_hold(monkeypatch,native);submit(combat,mid,'Hold',target=None)
    e=reload(combat,mid,tmp_path)
    rolls=[r for r in e.rolls if r.reason.startswith('SAVE:')]
    assert [r.mode for r in rolls[-2:]]==['ADVANTAGE','NORMAL']


@pytest.mark.parametrize('height,expected',[(8,1),(12,3)])
def test_feather_body_first_thirty_feet_in_service(tmp_path,monkeypatch,height,expected):
    combat,table,mid=fight(tmp_path,[WS,'tianxia.talent.gravity.feather_body'])
    use(combat,table,mid,'Weight Shift: Body Lightening')
    on_hold(monkeypatch,lambda engine:falling.displace(engine,engine.state.actors[ME],height,'test:feather-descent',intent=engine._active_intent))
    submit(combat,mid,'Hold',target=None)
    e=reload(combat,mid,tmp_path)
    assert len([r for r in e.rolls if r.reason=='FALLING_DAMAGE'][-1].dice)==expected


@pytest.mark.parametrize('mechanic_id,review_file',[
    (HAMMER, 'auto67_gravity.json'),
    ('TAL_GRAVITY_ANCHOR_STANCE', 'riders_c2.json'),
    ('tianxia.talent.gravity.feather_body', 'riders_c2.json'),
])
def test_reviewed_gravity_has_one_source_after_service_replay(tmp_path,monkeypatch,mechanic_id,review_file):
    # Exercise the compiled rule through service/session execution and cold
    # replay before checking that future edits cannot be shadowed by an overlay.
    if mechanic_id == HAMMER:
        test_falling_hammer_first_thirty_feet_in_service(tmp_path,monkeypatch,12,3)
    elif mechanic_id == 'TAL_GRAVITY_ANCHOR_STANCE':
        test_anchor_stopped_movement_optional_reaction(tmp_path,monkeypatch,5,True,1)
    else:
        test_feather_body_first_thirty_feet_in_service(tmp_path,monkeypatch,12,3)
    directory = ROOT / 'authority/typed_mechanics'
    files = [directory / 'reviewed_final.json', *sorted((directory / 'reviewed_final.d').glob('*.json'))]
    sources = [p.name for p in files if mechanic_id in json.loads(p.read_text()).get('mechanics', {})]
    assert sources == [review_file], f'{mechanic_id} has shadowable reviewed sources: {sources}'


def test_legacy_falling_hammer_row_retains_previous_calculation(tmp_path,monkeypatch):
    combat,table,mid=fight(tmp_path,[HAMMER],legacy_protection=True)
    on_hold(monkeypatch,lambda engine:falling.displace(engine,engine.state.actors[ME],8,'test:legacy-descent',intent=engine._active_intent))
    submit(combat,mid,'Hold',target=None)
    e=reload(combat,mid,tmp_path)
    assert len([r for r in e.rolls if r.reason=='FALLING_DAMAGE'][-1].dice)==4


POTENCY = 'tianxia.path.qi_cultivation.feature.qi_technique_potency'


def test_crushing_focus_qi_initial_fixed_packet_keeps_activation_potency(tmp_path):
    """A real Qi-paid Falling Line must keep its damage-roll bonus after the failed save."""
    source = 'tianxia.talent.gravity.falling_line'
    combat, table, mid = fight(tmp_path, [CRUSH, POTENCY, source], primary='Qi')
    session = combat._load_session(mid)
    action = next(a for a in session.engine.action_catalog.values()
                  if a.owner_id == ME and a.parameters.get('typed', {}).get('source') == source)
    potency = action.parameters['typed']['numbers']['potency']
    assert potency == 10
    use(combat, table, mid, G._area(session.engine, 'Falling Line', at=(4, 6)))
    e = reload(combat, mid, tmp_path)
    packets = focus_damage(e)
    assert len(packets) == 1
    assert packets[0].payload['hp_damage'] == e.state.actors[ME].proficiency_bonus
    damage = [r for r in e.rolls if r.actor_id == ME and r.reason.startswith('DAMAGE') and r.dice]
    assert len(damage) == 1
    assert damage[0].modifier == potency
    assert damage[0].total == sum(damage[0].dice) + potency


def test_crushing_focus_qi_repeat_fixed_packet_after_cold_reload(tmp_path):
    """Repeats reconstruct an activation context but cannot reapply its potency to fixed PB."""
    source = 'tianxia.talent.gravity.heaven_s_weight'
    combat, table, mid = fight(tmp_path, [CRUSH, POTENCY, source], primary='Qi')
    session = combat._load_session(mid)
    action = next(a for a in session.engine.action_catalog.values()
                  if a.owner_id == ME and a.parameters.get('typed', {}).get('source') == source)
    assert action.parameters['typed']['numbers']['potency'] == 10
    use(combat, table, mid, 'Heaven')
    reload(combat, mid, tmp_path)
    # Replace both services to exercise the repeat using only durable fight data.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    use(combat, table, mid, 'End Turn')
    advance(combat, table, mid, FOE)
    use(combat, table, mid, 'End Turn')
    e = reload(combat, mid, tmp_path)
    packets = focus_damage(e)
    assert len(packets) == 2
    assert packets[-1].payload['hp_damage'] == e.state.actors[ME].proficiency_bonus
    # A second repeat on a later actual turn has the same independent fixed amount.
    advance(combat, table, mid, FOE)
    use(combat, table, mid, 'End Turn')
    e = reload(combat, mid, tmp_path)
    assert len(focus_damage(e)) == 3
    assert all(p.payload['hp_damage'] == e.state.actors[ME].proficiency_bonus for p in focus_damage(e))
