"""Shadow second pass through accepted table intents and cold service replay."""
import pytest
from combat import zones
from combat.typed_executor import condition_rules
from tests.auto_worker1_support import (fight, triple_fight, OTHER, act, reload, turn,
    settle, action_sender, LEFT, RIGHT)
from combat.gate5_service import CombatService

AMBUSH = 'TAL_SHADOW_AMBUSH_FROM_BELOW'
MANTLE = 'TAL_SHADOW_SHADOW_MANTLE'
MARK = {'type':'mark','mark':'Shadow Mark','applies_to':'target','duration':{'kind':'hours','amount':8}}
ATTACK = [{'type':'attack','attack_kind':'cultivation_ranged','count':1,'on_hit':[],'on_miss':[]}]


def ambush_events(e):
    return [v for v in e.events if v.event_type=='REACTION_RESOLVED' and v.source_definition_id==AMBUSH]


def marked_fight(tmp_path, *, ai=False, **kw):
    c,t,m = fight(tmp_path,[AMBUSH],prepare=[MARK],cause=ATTACK, **kw)
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    turn(t,m,RIGHT)
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    return c,t,m


@pytest.mark.parametrize('ai',[False,True])
@pytest.mark.parametrize('success',[False,True])
@pytest.mark.parametrize('cl,dice',[(5,3),(11,4),(17,5)])
def test_ambush_end_turn_save_damage_payment_and_expiry(tmp_path,ai,success,cl,dice):
    c,t,m=marked_fight(tmp_path,ai=ai,cl=cl,right_score=214 if success else 14)
    _,p=settle(lambda a:act(t,m,'end',a))
    e=reload(c,m)
    assert len(ambush_events(e))==1
    assert ambush_events(e)[0].payload['trigger']=='ends its turn'
    assert bool(p)==(not ai)
    if p:
        assert 'Dexterity' in str(p) and 'Reaction + 2 Qi' in str(p)
    damage=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids][-1]
    rolled=[v for v in e.events if v.event_type=='DAMAGE_ROLLED'][-1]
    assert len(rolled.payload['dice'])==dice
    assert damage.payload['hp_damage']==(rolled.payload['total']//2 if success else rolled.payload['total'])
    assert e.state.actors[LEFT].resources['resource:core.qi']==98
    assert any(r.get('no_reactions') for r in condition_rules(e.state.actors[RIGHT]))==(not success)
    # Keeper's new turn refreshes its Reaction; the old recipient receipt must
    # not prohibit a new turn's end-trigger, but denial ends on Visitor's start.
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    turn(t,m,RIGHT)
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    e=reload(c,m)
    assert not any(r.get('no_reactions') for r in condition_rules(e.state.actors[RIGHT]))
    settle(lambda a:act(t,m,'end',a))
    assert len(ambush_events(reload(c,m)))==2


@pytest.mark.parametrize('trigger',['attack','move'])
@pytest.mark.parametrize('ai',[False,True])
def test_ambush_move_or_attack_then_end_is_one_trigger(tmp_path,trigger,ai):
    c,t,m=marked_fight(tmp_path,ai=ai)
    if trigger=='attack':settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    else:
        def send(answers):
            state=t.state(m); menu=state['menu']; choice=next(o for o in menu['moves'] if o['cost_ft']==5)
            return t.act(m,choice['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
        settle(send)
    e=reload(c,m)
    assert len(ambush_events(e))==1
    assert ambush_events(e)[0].payload['trigger']==('attacks' if trigger=='attack' else 'moves')
    settle(lambda a:act(t,m,'end',a))
    assert len(ambush_events(reload(c,m)))==1
    assert reload(c,m).state.actors[LEFT].resources['resource:core.qi']==98


def test_ambush_decline_commits_no_payment_or_outcome(tmp_path):
    c,t,m=marked_fight(tmp_path)
    _,p=settle(lambda a:act(t,m,'end',a),lambda p:[])
    assert p
    e=reload(c,m)
    assert not ambush_events(e) and e.state.actors[LEFT].resources['resource:core.qi']==100
    assert e.state.actors[RIGHT].current_hp==1000


@pytest.mark.parametrize('case',['unowned','unmarked','ally','out_of_range','unperceived','legacy'])
def test_ambush_admission_and_unstamped_inertia(tmp_path,case):
    def legacy(bundle):
        if case=='legacy':
            for row in bundle.get('typed_reactions',[]):
                if row.get('feature_id')==AMBUSH:
                    row['effects']=[e for e in row['effects'] if e.get('type')!='shadow_ambush_policy']
    c,t,m=fight(tmp_path,[] if case=='unowned' else [AMBUSH],
        prepare=[] if case=='unmarked' else [MARK], prepare_target='ALLY_OR_SELF' if case=='ally' else 'HOSTILE_ENTITY',
        right_team='team:factory' if case=='ally' else 'team:opponents', bundle_edit=legacy,
        cause=[{'type':'teleport','applies_to':'self','distance_ft':120}] if case=='out_of_range' else
              [{'type':'condition','applies_to':'self','condition':'hidden','duration':'one_minute'}] if case=='unperceived' else [])
    if case!='unmarked':settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    turn(t,m,RIGHT)
    if case=='out_of_range':
        # The grid's distance is Chebyshev (combat/gate2_grid.distance_cells), so rank the offered landing squares by
        # that metric: a Manhattan pick stops on the 60-foot ambush range boundary instead of leaving it.
        settle(lambda a:act(t,m,'Cause',a),lambda p:[max((o['id'] for o in p['choice']['options']), key=lambda i:max(abs(int(v)-b) for v,b in zip(i.removeprefix('cell:').split(','),(3,6))))])
        e=reload(c,m)
        assert e._distance_actor_to_actor(e.state.actors[LEFT],e.state.actors[RIGHT])>60
    if case=='unperceived':settle(lambda a:act(t,m,'Cause',a))
    if case=='ally':c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    settle(lambda a:act(t,m,'end',a))
    e=reload(c,m)
    assert not ambush_events(e)


@pytest.mark.parametrize('darkness,magical',[(True,False),(True,True),(False,False)])
@pytest.mark.parametrize('ai',[False,True])
def test_mantle_ordinary_darkness_only_and_concentration_cleanup(tmp_path,darkness,magical,ai):
    c,t,m=fight(tmp_path,[MANTLE],prepare=[{'type':'zone'}],prepare_target='SELF',
        prepare_zone_spec={'shape':'sphere','size_ft':10,'centered_on_self':True,'name':'Test darkness',
            'duration':{'kind':'minutes','amount':10},'obscured':'heavy',
            'visual':{'darkness':darkness,'magical':magical,'material':'darkness' if darkness else 'fog'}},
        extra_actions=[('Break concentration',{'effects':[{'type':'damage','flat':100,'damage_types':['fire'],'applies_to':'self'}]})])
    settle(lambda a:act(t,m,'Prepare',a))
    e=reload(c,m)
    assert zones.hidden_from(e,e.state.actors[LEFT],e.state.actors[RIGHT])
    settle(action_sender(c,t,m,'Shadow Mantle',ai=ai))
    e=reload(c,m)
    assert e.state.actors[LEFT].resources['resource:core.qi']==97
    assert zones.hidden_from(e,e.state.actors[LEFT],e.state.actors[RIGHT])!=(darkness and not magical)
    assert zones.hidden_from(e,e.state.actors[RIGHT],e.state.actors[LEFT])
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    settle(lambda a:act(t,m,'Break concentration',a))
    e=reload(c,m)
    assert zones.hidden_from(e,e.state.actors[LEFT],e.state.actors[RIGHT])
    assert not any(r.get('shadow_mantle_sight') for r in condition_rules(e.state.actors[LEFT]))


def test_ai_crossing_invites_only_ally_with_enemy_adjacent(tmp_path):
    c,t,m=triple_fight(tmp_path,['TAL_SHADOW_SHADOW_STEP','TAL_SHADOW_TWO_SHADOWS_CROSSING'],third_ally=True)
    records=[]
    real=c.controller
    class RecordingController:
        def choose_reaction(self, context):
            records.append(context.model_dump(mode='json'))
            return real.choose_reaction(context)
        def __getattr__(self, name):return getattr(real,name)
    c.controller=RecordingController()
    c.set_controller_mode(m,actor_id=OTHER,controller_mode='LOCAL_AUTO')
    label='Shadow Step + Two Shadows Crossing'
    # Use a real AI primary-action adapter; the owner and ally answer their
    # travel choices automatically, with an opponent in the same invitation range.
    settle(action_sender(c,t,m,label,ai=True))
    invitations=[r for r in records if 'shadow_crossing' in str(r) and 'Invite' in str(r)]
    assert invitations, records
    assert all(set(r['legal_option_ids'])=={OTHER} for r in invitations)
    e=reload(c,m)
    hops=[v for v in e.events if v.event_type=='MOVEMENT_COMMITTED' and v.payload.get('teleport')]
    assert any(v.actor_id==OTHER for v in hops)
    assert not any(v.actor_id==RIGHT for v in hops)
    assert e.state.actors[RIGHT].position.x==4 and e.state.actors[RIGHT].position.y==6


def test_ambush_shared_limit_survives_a_free_reaction_and_cold_reload(tmp_path):
    def grant(bundle):
        if bundle['actor_id']==LEFT:
            bundle['typed_passives'].append({'feature_id':'test:extra_reaction','block':'reaction_economy',
                'grant':'free','covers':{'features':[AMBUSH]}})
    c,t,m=marked_fight(tmp_path,bundle_edit=grant)
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=reload(c,m)
    assert e.state.actors[LEFT].reaction_available
    assert len(ambush_events(e))==1
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    settle(lambda a:act(t,m,'end',a))
    assert len(ambush_events(reload(c,m)))==1
    assert reload(c,m).state.actors[LEFT].resources['resource:core.qi']==98


@pytest.mark.parametrize('damage_type,loss',[('psychic',20),('necrotic',20),('fire',40)])
def test_mantle_resistances_and_stealth_remain_native_without_reminders(tmp_path,damage_type,loss):
    c,t,m=fight(tmp_path,[MANTLE],prepare_target='ALLY_OR_SELF',
        prepare=[{'type':'skill_check','ability':'dex','skill':'Stealth','dc':15,'applies_to':'self'}],
        cause=[{'type':'damage','flat':40,'damage_types':[damage_type],'applies_to':'target'}])
    settle(lambda a:act(t,m,'Shadow Mantle',a))
    settle(lambda a:act(t,m,'Prepare',a,target_id=LEFT))
    e=reload(c,m)
    assert [v for v in e.events if v.event_type=='CHECK_ROLLED'][-1].payload['actor']['mode']=='ADVANTAGE'
    assert not any(v.event_type=='GM_RIDER' and MANTLE in str(v.source_definition_id) for v in e.events)
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    assert reload(c,m).state.actors[LEFT].current_hp==1000-loss


def test_mantle_real_opportunity_has_disadvantage_ordinary_attack_does_not(tmp_path):
    c,t,m=fight(tmp_path,[MANTLE],cause=ATTACK)
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(lambda a:act(t,m,'Shadow Mantle',a))
    c.set_controller_mode(m,actor_id=RIGHT,controller_mode='LOCAL_AUTO')
    def walk(answers):
        state=t.state(m);menu=state['menu']
        cid=next(o['candidate_id'] for o in menu['moves'] if o['destination']=={'x':2,'y':6})
        return t.act(m,cid,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
    settle(walk)
    e=reload(c,m)
    rolls=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==RIGHT]
    assert rolls and rolls[-1].payload['mode']=='DISADVANTAGE'
    c.set_controller_mode(m,actor_id=RIGHT,controller_mode='MANUAL')
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    e=reload(c,m)
    assert [v for v in e.events if v.event_type=='ATTACK_ROLLED' and v.actor_id==RIGHT][-1].payload['mode']=='NORMAL'


def test_mantle_expires_at_one_minute_with_sight_and_opportunity_protection(tmp_path):
    c,t,m=fight(tmp_path,[MANTLE],maximum_rounds=12)
    settle(lambda a:act(t,m,'Shadow Mantle',a))
    assert any(r.get('shadow_mantle_sight') for r in condition_rules(reload(c,m).state.actors[LEFT]))
    for _ in range(10):turn(t,m,RIGHT);turn(t,m,LEFT)
    e=reload(c,m)
    assert not any(r.get('shadow_mantle_sight') or r.get('shadow_mantle_opportunity') for r in condition_rules(e.state.actors[LEFT]))


def test_manual_crossing_caster_chooses_companion_arrival(tmp_path):
    c,t,m=triple_fight(tmp_path,['TAL_SHADOW_SHADOW_STEP','TAL_SHADOW_TWO_SHADOWS_CROSSING'],third_ally=True)
    def choices(prompt):
        source=prompt['context']['reaction_source_id']
        if source.endswith('shadow_crossing_arrival'):return ['cell:6,5']
        if source.endswith('shadow_crossing'):return [OTHER]
        if source.endswith('shadow_crossing_consent'):return ['travel']
        options=prompt.get('choice',{}).get('options',[])
        if any(o['id']=='cell:6,6' for o in options):return ['cell:6,6']
        return [o['id'] for o in options[:1]]
    _,p=settle(action_sender(c,t,m,'Shadow Step + Two Shadows Crossing'),choices)
    assert any(r['context']['reaction_source_id'].endswith('shadow_crossing_arrival') for r in p)
    e=reload(c,m)
    assert (e.state.actors[LEFT].position.x,e.state.actors[LEFT].position.y)==(6,6)
    assert (e.state.actors[OTHER].position.x,e.state.actors[OTHER].position.y)==(6,5)
    assert (e.state.actors[RIGHT].position.x,e.state.actors[RIGHT].position.y)==(4,6)


def test_long_road_manual_companion_selection_and_arrival_cold_reload(tmp_path):
    from tests.auto_worker1_support import cell_send
    c,t,m=triple_fight(tmp_path,['TAL_SHADOW_SECOND_SILHOUETTE','TAL_SHADOW_LONG_ROAD_BETWEEN_LANTERNS'],third_ally=True)
    settle(cell_send(t,m,'Second Silhouette: Shadow Anchor',(3,6)))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(cell_send(t,m,'Second Silhouette: Shadow Anchor',(6,6)))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    def choices(prompt):
        source=prompt['context']['reaction_source_id']
        if source.endswith('shadow_long_road'):return [OTHER]
        if source.endswith('shadow_long_road_consent'):return ['travel']
        if source.endswith('shadow_road_arrival'):return ['cell:6,5']
        return [o['id'] for o in prompt.get('choice',{}).get('options',[])[:1]]
    _,p=settle(cell_send(t,m,'Long Road Between Lanterns',(6,6)),choices)
    invitation=next(r for r in p if r['context']['reaction_source_id'].endswith('shadow_long_road'))
    assert {o['id'] for o in invitation['choice']['options']} == {OTHER, RIGHT}
    assert any(r['context']['reaction_source_id'].endswith('shadow_road_arrival') for r in p)
    e=reload(c,m)
    assert e.state.actors[LEFT].resources['resource:core.qi']==95
    assert (e.state.actors[LEFT].position.x,e.state.actors[LEFT].position.y)==(6,6)
    assert (e.state.actors[OTHER].position.x,e.state.actors[OTHER].position.y)==(6,5)
    assert (e.state.actors[RIGHT].position.x,e.state.actors[RIGHT].position.y)==(4,6)


@pytest.mark.parametrize('ai',[False,True])
def test_ambush_marked_ally_requires_explicit_manual_use(tmp_path,ai):
    c,t,m=fight(tmp_path,[AMBUSH],prepare=[MARK],prepare_target='ALLY_OR_SELF',right_team='team:factory')
    settle(lambda a:act(t,m,'Prepare',a,target_id=RIGHT))
    turn(t,m,RIGHT)
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    _,p=settle(lambda a:act(t,m,'end',a))
    e=reload(c,m)
    assert bool(p)==(not ai)
    assert len(ambush_events(e))==(0 if ai else 1)
    assert e.state.actors[LEFT].resources['resource:core.qi']==(100 if ai else 98)
    assert (e.state.actors[RIGHT].current_hp<1000)==(not ai)


@pytest.mark.parametrize('team', ['team:neutral', 'team:opponents'])
@pytest.mark.parametrize('consent', [False, True])
def test_long_road_manual_non_ally_owns_consent_and_cold_reload(tmp_path, team, consent):
    from tests.auto_worker1_support import cell_send
    c,t,m=fight(tmp_path,['TAL_SHADOW_SECOND_SILHOUETTE','TAL_SHADOW_LONG_ROAD_BETWEEN_LANTERNS'],right_team=team)
    settle(cell_send(t,m,'Second Silhouette: Shadow Anchor',(3,6)))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(cell_send(t,m,'Second Silhouette: Shadow Anchor',(6,6)))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    # Reopen the services before the travel intent, as well as after commit.
    c=CombatService(c.source_root,c.userdata_root)
    from combat.tabletop_service import TabletopService
    t=TabletopService(c,c.userdata_root)
    def choices(prompt):
        source=prompt['context']['reaction_source_id']
        if source.endswith('shadow_long_road'):
            assert prompt['context']['reactor_id']==LEFT
            assert {o['id'] for o in prompt['choice']['options']}=={RIGHT}
            assert 'Invite Visitor' in str(prompt)
            return [RIGHT]
        if source.endswith('shadow_long_road_consent'):
            assert prompt['context']['reactor_id']==RIGHT
            assert 'Keeper invites Visitor' in str(prompt)
            return ['travel'] if consent else []
        if source.endswith('shadow_road_arrival'):
            assert prompt['context']['reactor_id']==LEFT
            return ['cell:6,5']
        return [o['id'] for o in prompt.get('choice',{}).get('options',[])[:1]]
    result,p=settle(cell_send(t,m,'Long Road Between Lanterns',(6,6)),choices)
    assert result['status']=='COMMITTED'
    assert any(r['context']['reaction_source_id'].endswith('shadow_long_road_consent') for r in p)
    assert any(r['context']['reaction_source_id'].endswith('shadow_road_arrival') for r in p)==consent
    e=reload(c,m)
    assert e.state.actors[LEFT].resources['resource:core.qi']==95
    assert (e.state.actors[LEFT].position.x,e.state.actors[LEFT].position.y)==(6,6)
    assert (e.state.actors[RIGHT].position.x,e.state.actors[RIGHT].position.y)==((6,5) if consent else (4,6))
    assert any(v.event_type=='INTENT_ACCEPTED' and 'long_road' in str(v) for v in e.events)


@pytest.mark.parametrize('mechanic,scenario', [
    (AMBUSH, 'ambush'), (MANTLE, 'mantle'),
    ('TAL_SHADOW_TWO_SHADOWS_CROSSING', 'crossing')])
def test_shadow_single_reviewed_definition_after_accepted_intent_and_reload(tmp_path, mechanic, scenario):
    # Runtime receipts exercise the reviewed result through accepted table
    # intents and cold replay; the source invariant catches filename overrides.
    if scenario=='ambush':
        test_ambush_decline_commits_no_payment_or_outcome(tmp_path)
    elif scenario=='mantle':
        test_mantle_resistances_and_stealth_remain_native_without_reminders(tmp_path,'psychic',20)
    else:
        test_manual_crossing_caster_chooses_companion_arrival(tmp_path)
    import json
    from tests.h1_support import ROOT
    directory=ROOT/'authority/typed_mechanics'
    files=[directory/'reviewed_final.json', *sorted((directory/'reviewed_final.d').glob('*.json'))]
    definitions=[p.name for p in files if p.exists() and mechanic in json.loads(p.read_text()).get('mechanics',{})]
    assert definitions==['riders_lane10.json'], definitions



def test_long_road_automatic_invites_only_perceived_allies(tmp_path):
    from tests.auto_worker1_support import cell_send
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate4_context import build_decision_context
    c,t,m=triple_fight(tmp_path,['TAL_SHADOW_SECOND_SILHOUETTE','TAL_SHADOW_LONG_ROAD_BETWEEN_LANTERNS'],third_ally=True)
    settle(cell_send(t,m,'Second Silhouette: Shadow Anchor',(3,6)))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(cell_send(t,m,'Second Silhouette: Shadow Anchor',(6,6)))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    real=c.controller
    records=[]
    class Controller:
        def choose_reaction(self, context):
            records.append(context.model_dump(mode='json'))
            return real.choose_reaction(context)
        def __getattr__(self, name):return getattr(real,name)
    c.controller=Controller()
    c.set_controller_mode(m,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    c.set_controller_mode(m,actor_id=OTHER,controller_mode='LOCAL_AUTO')
    # Long Road remains outside the built-in AI primary menu. Exercise an
    # explicit pilot choice through the persistent session's controller API.
    session=c._load_session(m)
    candidate=next(row for row in session.engine.legal_candidates()
                   if row.destination is not None and (row.destination.x,row.destination.y)==(6,6)
                   and row.source_definition_id.endswith('shadow.long_road'))
    policy,_=c.policies.for_actor(LEFT)
    context=build_decision_context(session.engine,policy,include_item_actions=True)
    choice=ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)
    session.execute_controller_choice(choice,controller=c.controller,policy_library=c.policies)
    invitations=[r for r in records if 'shadow_long_road' in str(r) and 'Invite' in str(r)]
    assert invitations
    assert all(set(r['legal_option_ids'])=={OTHER} for r in invitations)
    e=reload(c,m)
    assert any(v.event_type=='MOVEMENT_COMMITTED' and v.actor_id==OTHER and v.payload.get('teleport') for v in e.events)
    assert (e.state.actors[RIGHT].position.x,e.state.actors[RIGHT].position.y)==(4,6)


def test_long_road_manual_does_not_offer_unperceived_non_ally(tmp_path):
    from tests.auto_worker1_support import cell_send
    c,t,m=fight(tmp_path,['TAL_SHADOW_SECOND_SILHOUETTE','TAL_SHADOW_LONG_ROAD_BETWEEN_LANTERNS'],
                cause=[{'type':'condition','condition':'hidden','applies_to':'self','duration':'one_minute'}])
    settle(cell_send(t,m,'Second Silhouette: Shadow Anchor',(3,6)))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(cell_send(t,m,'Second Silhouette: Shadow Anchor',(6,6)))
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a))
    turn(t,m,LEFT)
    _,p=settle(cell_send(t,m,'Long Road Between Lanterns',(6,6)))
    assert not any(r['context']['reaction_source_id'].endswith('shadow_long_road') for r in p)
    e=reload(c,m)
    assert (e.state.actors[LEFT].position.x,e.state.actors[LEFT].position.y)==(6,6)
    assert (e.state.actors[RIGHT].position.x,e.state.actors[RIGHT].position.y)==(4,6)
