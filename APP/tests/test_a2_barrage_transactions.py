"""Settled attacks, subject-owned steps, penalty expiry and AI table transport."""
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet
from tests.test_a2_barrage import finish, option, ready, reload, COVER, SUPPRESS, MOBILE, PROTECTED, PRESSURE
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, ROOT
from tests.test_auto58_barrage_projectiles import ARROW_KIT
from tests.test_sph_barrage_r1 import _send


def battle(tmp_path, talents, *, hit=True, typed_foe=True, foe_kit=None):
    from combat.gate2_runtime_content import AN
    enemy=RIGHT if typed_foe else AN
    ids=[LEFT,ALLY,enemy]
    documents=[sheet(talents,cl=5,kit=ARROW_KIT),sheet([],cl=5,kit=ARROW_KIT),sheet([],cl=5,kit=foe_kit)]
    bundles=[]
    for aid,doc in zip(ids,documents):
        doc['identity']['display_name']={LEFT:'Archer',ALLY:'Protected ally',enemy:'Opponent'}[aid]
        doc['ability_scores_and_statistics']['hit_points']['maximum']=800
        if aid==ALLY:
            doc['ability_scores_and_statistics']['armor_class']['base_value']=1000
        bundle=compile_character(doc,actor_id=aid,reaction_plan={'ask':True})
        for action in bundle['action_catalog']:
            typed=action['parameters'].get('typed') or {}
            if any(e.get('type')=='attack' for e in typed.get('effects') or []):
                typed.setdefault('numbers',{})['attack_bonus']=(1000 if hit else -1000) if aid==LEFT else -1000
        if aid==enemy:
            source='test:ordinary_perception'
            bundle['actor_template']['action_ids'].append(source)
            bundle['action_catalog'].append({'source_definition_id':source,'display_name':'Test ordinary Perception check',
                'owner_id':aid,'economy':'NONE','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':30,
                'parameters':{'typed':{'numbers':{'ability_mods':{'WIS':0},'pb':2},'effects':[{
                    'type':'contest_against','harmful':False,'actor_check':{'kind':'check','ability':'WIS','skill':'Perception'},
                    'target_check':{'kind':'dc','dc':10},'on_success':[],'on_fail':[]}], 'riders':[]}}})
        from combat.canonical import canonical_sha256
        bundle.pop('bundle_sha256',None)
        bundle['bundle_sha256']=canonical_sha256(bundle)
        bundles.append(bundle)
    if not typed_foe:
        bundles=bundles[:2]
    combat=CombatService(ROOT,tmp_path)
    combat.tabletop_maps.save({'display_name':'A2 Barrage yard','width_squares':12,'height_squares':8,'walls':[],
                              'starts':{'team1':[[3,4],[3,5]],'team2':[[4,5]]}})
    arena=combat.factory_arenas()['battlefield:map.a2-barrage-yard']
    mid=combat._finish_factory_match(bundles,ids,{LEFT:'team:a',ALLY:'team:a',enemy:'team:b'},
        {LEFT:{'x':3,'y':4},ALLY:{'x':3,'y':5},enemy:{'x':4,'y':5}},arena,[LEFT,ALLY],[enemy],
        control_modes={a:'MANUAL' for a in ids},match_seed='A2-BARRAGE',display_name='A2 Barrage',maximum_rounds=10)['match_id']
    table=TabletopService(combat,tmp_path)
    while table.state(mid)['menu']['actor_id']!=LEFT:
        finish(table,mid,table.state(mid)['menu']['end_turn'])
    return combat,table,mid,enemy


def reach_turn(table,mid,aid):
    for _ in range(6):
        if table.state(mid)['menu']['actor_id']==aid:
            return
        finish(table,mid,table.state(mid)['menu']['end_turn'])
    raise AssertionError('did not reach turn')


@pytest.mark.parametrize('typed_foe',[False,True])
@pytest.mark.parametrize('take_step',[False,True])
def test_covering_first_opportunity_miss_offers_ally_own_step(tmp_path,take_step,typed_foe):
    combat,table,mid,enemy=battle(tmp_path,[COVER],typed_foe=typed_foe)
    ready(table,mid)
    finish(table,mid,option(table,mid,'Barrage: Gong Jian (Bow and Arrow) + Covering Volley',enemy),lambda p: ALLY)
    reach_turn(table,mid,ALLY)
    engine=reload(tmp_path,mid)
    cid=next(c.candidate_id for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination.x==2 and c.destination.y==5)
    def pick(p):
        if p['context']['reaction_source_id']=='choice:needle.barrage_step':
            return 'step:3,6,0' if take_step else False
        return None  # accept the native Opportunity Attack window
    prompts=finish(table,mid,cid,pick)
    step=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.barrage_step')
    assert step['context']['reactor_id']==ALLY
    engine=reload(tmp_path,mid)
    assert not any(c.condition_id==PROTECTED for c in engine.state.actors[ALLY].conditions.values())
    rolls=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==enemy]
    assert len(rolls)==1 and rolls[0].payload['mode']=='DISADVANTAGE'
    grants=[e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.source_definition_id==COVER]
    assert len(grants)==int(take_step)
    ally=engine.state.actors[ALLY]
    assert (ally.position.x,ally.position.y)==((3,6) if take_step else (2,5))
    assert ally.movement_remaining_ft==(30 if take_step else 25)


@pytest.mark.parametrize('hit',[False,True])
def test_mobile_hit_exemption_only_and_ordinary_budget(tmp_path,hit):
    combat,table,mid,enemy=battle(tmp_path,[MOBILE],hit=hit)
    ready(table,mid)
    def pick(p):
        if p['context']['reaction_source_id']=='choice:needle.barrage_step':return 'step:2,4,0'
        return False
    prompts=finish(table,mid,option(table,mid,'Barrage: Gong Jian (Bow and Arrow) + Mobile Barrage',enemy),pick)
    oa=[p for p in prompts if p['context']['reactor_id']==enemy]
    assert bool(oa)==(not hit)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[LEFT].movement_remaining_ft==25
    assert (engine.state.actors[LEFT].position.x,engine.state.actors[LEFT].position.y)==(2,4)


@pytest.mark.parametrize('automatic_archer',[False,True])
def test_suppression_perception_penalty_and_target_turn_expiry(tmp_path,automatic_archer):
    combat,table,mid,enemy=battle(tmp_path,[SUPPRESS])
    ready(table,mid)
    finish(table,mid,option(table,mid,'Barrage: Gong Jian (Bow and Arrow) + Suppressing Fire',enemy))
    cid=option(table,mid,'Suppressing Fire: Gong Jian',enemy)
    if automatic_archer:
        from combat.gate4_adapters import ManualControllerAdapter
        real=combat.controller
        class Selected:
            def choose_primary_action(self,context):
                return ManualControllerAdapter(lambda _:(cid,())).choose_primary_action(context)
            def __getattr__(self,name):return getattr(real,name)
        combat.controller=Selected()
        combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='LOCAL_AUTO')
        first=table.auto_step(mid,table.state(mid)['last_sequence'],[])
        assert first['status']=='REACTION_REQUIRED',first
        assert first['reaction']['context']['reactor_id']==enemy
        answer={**first['reaction']['context'],'selection':'USE','option_ids':['evade']}
        assert table.auto_step(mid,table.state(mid)['last_sequence'],[answer])['status']=='COMMITTED'
        combat.controller=real
        combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='MANUAL')
    else:
        finish(table,mid,cid,lambda p:'evade')
    reach_turn(table,mid,enemy)
    finish(table,mid,option(table,mid,'Test ordinary Perception check',LEFT))
    engine=reload(tmp_path,mid)
    rolls=[e for e in engine.events if e.event_type=='CHECK_ROLLED' and e.source_definition_id=='test:ordinary_perception']
    assert len(rolls)==1 and rolls[0].payload['actor']['modifier']==-2
    assert any(c.condition_id==PRESSURE for c in engine.state.actors[enemy].conditions.values())
    finish(table,mid,table.state(mid)['menu']['end_turn'])
    engine=reload(tmp_path,mid)
    assert not any(c.condition_id==PRESSURE for c in engine.state.actors[enemy].conditions.values())
    assert engine._effective_speed(engine.state.actors[enemy])==engine.state.actors[enemy].speed_ft
    assert not any(c.condition_id==PRESSURE for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('typed_foe',[False,True])
def test_suppression_attacks_take_exactly_two_penalty(tmp_path,typed_foe):
    combat,table,mid,enemy=battle(tmp_path,[SUPPRESS],typed_foe=typed_foe,foe_kit=ARROW_KIT)
    ready(table,mid)
    finish(table,mid,option(table,mid,'Barrage: Gong Jian (Bow and Arrow) + Suppressing Fire',enemy),lambda p:False)
    finish(table,mid,option(table,mid,'Suppressing Fire: Gong Jian',enemy),
        lambda p:'evade' if p['context']['reaction_source_id']=='choice:needle.suppressing_fire' else False)
    reach_turn(table,mid,enemy)
    ready(table,mid)
    engine=reload(tmp_path,mid)
    def eligible(c):
        if c.target_ids!=(ALLY,):return False
        action=engine.action_catalog.get(c.source_definition_id)
        if action is None:return False
        if typed_foe:return action.display_name=='Gong Jian (Bow and Arrow) attack'
        return action.resolution_kind=='MULTI_ATTACK'
    candidate=next(c for c in engine.legal_candidates() if eligible(c))
    action=engine.action_catalog[candidate.source_definition_id]
    expected=(action.parameters['typed']['numbers']['attack_bonus'] if typed_foe else action.attack_bonus)-2
    before=len(engine.events)
    finish(table,mid,candidate.candidate_id,lambda p:False)
    engine=reload(tmp_path,mid)
    rolls=[e for e in engine.events[before:] if e.event_type=='ATTACK_ROLLED' and e.actor_id==enemy]
    assert rolls and all(e.payload['modifier']==expected for e in rolls)
