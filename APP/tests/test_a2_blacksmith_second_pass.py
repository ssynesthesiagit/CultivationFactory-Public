"""Service commits and cold mechanical replay; only attack d20s are controlled."""
import pytest
from combat import ext
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionIntent
from combat.ext.blacksmith_forge import held_condition, mark_count
from tests.worker2_support import fixture, candidate, turn, reload, OWNER, ALLY, FOE
from tests.test_a2_blacksmith import seal, press
K = 'tianxia.talent.blacksmith.'
QUENCH, STEADY, INCARNATION = [K+x for x in ['quench_against_the_grain','steady_hammer_breathing','incarnation_of_the_living_forge']]
LIVING='condition:typed.blacksmith_living_forge'
USED='condition:typed.blacksmith_steady_expertise_used'

def die(monkeypatch, natural=10):
    ext.effects()
    old=list(ext._HOOKS.get('d20_result', ()))
    def result(e,r,i):
        if r.reason.startswith('ATTACK:'):
            return {'source_id':'test:blacksmith.die','operation':'replace','natural_result':natural}
    monkeypatch.setitem(ext._HOOKS,'d20_result',old+[result])

def setup(bonus=4, rank=None, native=False):
    def build(bundles):
        for b in bundles:
            seal(b,'Sword',[{'type':'attack','attack_kind':'weapon','on_hit':[{'type':'damage','flat':10,'damage_types':['slashing'],'applies_to':'target'}]}],target='ANY_CREATURE')
            row=b['action_catalog'][-1]; row['parameters']['typed']['numbers']['attack_bonus']=bonus
            row['parameters']['typed']['weapon']={'damage_type':'slashing'}
            row['parameters']['expected_damage']=10
            if native:
                row.update(resolution_kind='ATTACK',attack_bonus=bonus,damage={'count':1,'sides':2,'modifier':9},damage_type='SLASHING')
                row['parameters']['attack_kind']='weapon'
            seal(b,'Extra mark',[{'type':'mark','mark':'Forge Mark','applies_to':'self'}])
            seal(b,'Fire packet',[{'type':'damage','flat':10,'damage_types':['fire'],'applies_to':'self'}])
            for name,skill in [('Smith check',"Smith's Tools"),('Other check','Athletics')]:
                seal(b,name,[{'type':'skill_check','ability':'INT','skill':skill}],target='ANY_CREATURE')
            if b['actor_id']==OWNER and rank is not None:
                b['skills']={"Smith's Tools":2+4*rank}; b['skill_proficiency']={"Smith's Tools":rank}
                b['actor_template']['skills']=b['skills']
            b.pop('bundle_sha256',None); b['bundle_sha256']=canonical_sha256(b)
    return build

def declare(combat,table,mid,kind):
    press(combat,table,mid,'Extra mark')
    press(combat,table,mid,'Quench Against the Grain: my marked workpiece is '+kind)

@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('margin,use',[(1,True),(2,True),(3,True),(2,False)])
def test_quench_close_miss_payment_and_decline(monkeypatch,tmp_path,native,margin,use):
    die(monkeypatch)
    combat,table,mid=fixture(tmp_path,[QUENCH],bundle_transform=setup(4-margin,native=native))
    declare(combat,table,mid,'weapon')
    before=combat._load_session(mid).engine.state.actors[FOE].current_hp
    prompts=press(combat,table,mid,'Sword',FOE,picks={'choice:needle.blacksmith_quench':['quench'] if use else None})
    e=reload(tmp_path,mid); expected=use and margin<=2
    assert bool(prompts)==(margin<=2)
    assert mark_count(e.state.actors[OWNER],OWNER)==(0 if expected else 1)
    assert e.state.actors[OWNER].reaction_available==(not expected)
    assert (e.state.actors[FOE].current_hp<before)==expected
    assert len([x for x in e.events if x.event_type=='ATTACK_ROLLED'])==1
    assert sum(x.source_definition_id==QUENCH and x.event_type=='REACTION_RESOLVED' for x in e.events)==int(expected)

@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('margin',[1,2])
@pytest.mark.parametrize('use',[False,True])
def test_quench_replaces_qualifying_natural_one_miss_through_service_and_reload(monkeypatch,tmp_path,native,margin,use):
    # The foe's AC is 14; natural 1 + (13 - margin) misses by exactly margin.
    die(monkeypatch,natural=1)
    combat,table,mid=fixture(tmp_path,[QUENCH],bundle_transform=setup(13-margin,native=native))
    declare(combat,table,mid,'weapon')
    before=combat._load_session(mid).engine.state.actors[FOE].current_hp
    prompts=press(combat,table,mid,'Sword',FOE,picks={'choice:needle.blacksmith_quench':['quench'] if use else None})
    e=reload(tmp_path,mid); expected=use
    assert bool(prompts)
    assert (e.state.actors[FOE].current_hp<before)==expected
    assert mark_count(e.state.actors[OWNER],OWNER)==(0 if expected else 1)
    assert e.state.actors[OWNER].reaction_available==(not expected)
    assert sum(x.event_type=='PASSIVE_TRIGGERED' and x.source_definition_id==QUENCH and x.payload.get('attack_outcome_replaced')=='miss_to_hit' for x in e.events)==int(expected)
    assert sum(x.event_type=='REACTION_RESOLVED' and x.source_definition_id==QUENCH for x in e.events)==int(expected)

@pytest.mark.parametrize('margin',[0,1,2,3])
def test_quench_close_hit_is_forced_miss(monkeypatch,tmp_path,margin):
    die(monkeypatch)
    combat,table,mid=fixture(tmp_path,[QUENCH],bundle_transform=setup(4+margin))
    declare(combat,table,mid,'armor or shield'); turn(table,mid,FOE)
    before=combat._load_session(mid).engine.state.actors[OWNER].current_hp
    start=len(combat._load_session(mid).engine.events)
    prompts=press(combat,table,mid,'Sword',OWNER,picks={'choice:needle.blacksmith_quench':['quench']})
    e=reload(tmp_path,mid)
    assert bool(prompts)==(margin<=2)
    damage=sum(x.payload['hp_damage'] for x in e.events[start:] if x.event_type=='DAMAGE_COMMITTED' and OWNER in x.target_ids)
    assert e.state.actors[OWNER].current_hp==before-damage
    assert (damage==0)==(margin<=2)
    assert mark_count(e.state.actors[OWNER],OWNER)==(0 if margin<=2 else 1)
    assert e.state.actors[OWNER].reaction_available==(margin>2)

@pytest.mark.parametrize('family',['armor or shield','tool',None])
def test_quench_weapon_miss_needs_qualified_marks(monkeypatch,tmp_path,family):
    die(monkeypatch)
    combat,table,mid=fixture(tmp_path,[QUENCH],bundle_transform=setup(2))
    if family: declare(combat,table,mid,family)
    else: press(combat,table,mid,'Extra mark')
    assert not press(combat,table,mid,'Sword',FOE)
    assert mark_count(reload(tmp_path,mid).state.actors[OWNER],OWNER)==1

def execute(combat,mid,name,target=None):
    session=combat._load_session(mid); row=candidate(combat,mid,name,target=target)
    session.mechanical.execute_intent(ActionIntent(intent_id='a2:'+name,actor_id=row.actor_id,decision_id=row.decision_id,candidate_id=row.candidate_id,state_version=row.state_version,target_ids=row.target_ids,destination=row.destination))

def test_incarnation_free_marks_and_repeated_temporary_hp(tmp_path):
    combat,table,mid=fixture(tmp_path,[INCARNATION],bundle_transform=setup())
    name='Living Forge: place a Forge Mark (once this turn)'
    assert not any(c.display_name==name for c in combat._load_session(mid).engine.legal_candidates())
    press(combat,table,mid,'Incarnation of the Living Forge')
    e=reload(tmp_path,mid); a=e.state.actors[OWNER]
    assert held_condition(a,LIVING); assert mark_count(a,OWNER)==0; assert a.temporary_hp==0
    execute(combat,mid,name)
    assert mark_count(reload(tmp_path,mid).state.actors[OWNER],OWNER)==1
    assert not any(c.display_name==name for c in combat._load_session(mid).engine.legal_candidates())
    turn(table,mid,ALLY); turn(table,mid,OWNER); press(combat,table,mid,'Set Edge')
    assert reload(tmp_path,mid).state.actors[OWNER].temporary_hp==4
    press(combat,table,mid,'Fire packet')
    assert reload(tmp_path,mid).state.actors[OWNER].temporary_hp==0
    press(combat,table,mid,name)
    turn(table,mid,ALLY); turn(table,mid,OWNER); press(combat,table,mid,'Set Edge')
    assert reload(tmp_path,mid).state.actors[OWNER].temporary_hp==4
    for _ in range(9): turn(table,mid,ALLY); turn(table,mid,OWNER)
    e=reload(tmp_path,mid)
    assert held_condition(e.state.actors[OWNER],LIVING) is None
    assert not any(c.display_name==name for c in e.legal_candidates())

@pytest.mark.parametrize('rank,extra',[(None,0),(0,0),(1,4),(2,0)])
def test_steady_explicit_proficiency_only(tmp_path,rank,extra):
    combat,table,mid=fixture(tmp_path,[STEADY],bundle_transform=setup(rank=rank))
    press(combat,table,mid,'Smith check',OWNER,picks={'choice:needle.blacksmith_steady':None})
    e=reload(tmp_path,mid)
    bonuses=[x for x in e.events if x.event_type=='D20_REWRITTEN' and x.source_definition_id==STEADY]
    assert len(bonuses)==int(extra>0)
    if extra:
        assert bonuses[0].payload['bonus']==extra
        assert bonuses[0].payload['result']['total']-bonuses[0].payload['original']['total']==extra
    start=len(e.events); press(combat,table,mid,'Other check',OWNER)
    assert not any(x.source_definition_id==STEADY for x in reload(tmp_path,mid).events[start:])

def test_existing_expertise_optional_once(tmp_path):
    combat,table,mid=fixture(tmp_path,[STEADY],bundle_transform=setup(rank=2))
    press(combat,table,mid,'Smith check',OWNER,picks={'choice:needle.blacksmith_steady':None})
    assert held_condition(reload(tmp_path,mid).state.actors[OWNER],USED) is None
    press(combat,table,mid,'Smith check',OWNER,picks={'choice:needle.blacksmith_steady':['advantage']})
    e=reload(tmp_path,mid); assert held_condition(e.state.actors[OWNER],USED)
    assert [x for x in e.events if x.event_type=='CHECK_ROLLED'][-1].payload['actor']['mode']=='ADVANTAGE'
    assert not press(combat,table,mid,'Smith check',OWNER)
    assert [x for x in reload(tmp_path,mid).events if x.event_type=='CHECK_ROLLED'][-1].payload['actor']['mode']=='NORMAL'

def test_ai_enemy_attack_with_ally_in_range(monkeypatch,tmp_path):
    die(monkeypatch)
    combat,table,mid=fixture(tmp_path,[QUENCH],bundle_transform=setup(2),ask=False)
    declare(combat,table,mid,'weapon')
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    e=reload(tmp_path,mid); ally_hp=e.state.actors[ALLY].current_hp; foe_hp=e.state.actors[FOE].current_hp
    execute(combat,mid,'Sword',FOE)
    e=reload(tmp_path,mid)
    assert e.state.actors[FOE].current_hp<foe_hp
    assert e.state.actors[ALLY].current_hp==ally_hp
    assert mark_count(e.state.actors[OWNER],OWNER)==0


def test_steady_mode_query_without_a_roll_does_not_spend(monkeypatch,tmp_path):
    ext.effects()
    def query(ctx,row):
        ext.run("skill_check_mode",ctx,ctx.actor,"INT","Smith's Tools")
    monkeypatch.setitem(ext._EFFECTS,"test_steady_query",query)
    monkeypatch.setitem(ext._EFFECT_HARM,"test_steady_query",False)
    def build(bundles):
        setup(rank=2)(bundles)
        seal(bundles[0],"Mode query",[{"type":"test_steady_query"}],target="ANY_CREATURE")
    combat,table,mid=fixture(tmp_path,[STEADY],bundle_transform=build)
    press(combat,table,mid,"Mode query",OWNER,picks={"choice:needle.blacksmith_steady":["advantage"]})
    assert held_condition(reload(tmp_path,mid).state.actors[OWNER],USED) is None
    prompts=press(combat,table,mid,"Smith check",OWNER,picks={"choice:needle.blacksmith_steady":["advantage"]})
    assert prompts
    assert held_condition(reload(tmp_path,mid).state.actors[OWNER],USED)


def test_steady_tools_apostrophe_alias_is_explicit_proficiency(tmp_path):
    def build(bundles):
        setup(rank=1)(bundles)
        b=bundles[0]; b['skill_proficiency']={"Smith’s Tools":1}
        b.pop('bundle_sha256',None); b['bundle_sha256']=canonical_sha256(b)
    combat,table,mid=fixture(tmp_path,[STEADY],bundle_transform=build)
    press(combat,table,mid,'Smith check',OWNER)
    e=reload(tmp_path,mid)
    bonuses=[x for x in e.events if x.event_type=='D20_REWRITTEN' and x.source_definition_id==STEADY]
    assert len(bonuses)==1 and bonuses[0].payload['bonus']==4


@pytest.mark.parametrize('target,declared',[(ALLY,True),(FOE,False)])
def test_ai_does_not_help_friendly_fire_or_invent_marked_weapon(monkeypatch,tmp_path,target,declared):
    die(monkeypatch)
    combat,table,mid=fixture(tmp_path,[QUENCH],bundle_transform=setup(2),ask=False)
    if declared: declare(combat,table,mid,'weapon')
    else: press(combat,table,mid,'Extra mark')
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    e=reload(tmp_path,mid); before=e.state.actors[target].current_hp
    execute(combat,mid,'Sword',target)
    e=reload(tmp_path,mid)
    assert e.state.actors[target].current_hp==before
    assert mark_count(e.state.actors[OWNER],OWNER)==1
    assert e.state.actors[OWNER].reaction_available


def test_real_table_ai_uses_quench_with_both_sides_visible(monkeypatch,tmp_path):
    from tests.worker2_support import settle
    die(monkeypatch)
    combat,table,mid=fixture(tmp_path,[QUENCH],bundle_transform=setup(2),ask=False)
    declare(combat,table,mid,'weapon')
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    e=reload(tmp_path,mid); ally_hp=e.state.actors[ALLY].current_hp; foe_hp=e.state.actors[FOE].current_hp
    settle(table,mid,None,auto=True)
    e=reload(tmp_path,mid)
    assert e.state.actors[FOE].current_hp<foe_hp
    assert e.state.actors[ALLY].current_hp==ally_hp
    assert mark_count(e.state.actors[OWNER],OWNER)==0
    assert any(x.event_type=='REACTION_RESOLVED' and x.source_definition_id==QUENCH for x in e.events)


@pytest.mark.parametrize('relation',['ALLY','NEUTRAL'])
def test_ai_quench_respects_current_relations_not_team_ids(monkeypatch,tmp_path,relation):
    die(monkeypatch)
    combat,table,mid=fixture(tmp_path,[QUENCH],bundle_transform=setup(2),ask=False)
    declare(combat,table,mid,'weapon')
    session=combat._load_session(mid)
    combat.change_relations(mid,change={'kind':'ACTOR_RELATION','subject':OWNER,'other':FOE,'relation':relation},
                            expected_state_version=session.engine.state.state_version)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    e=reload(tmp_path,mid); before=e.state.actors[FOE].current_hp
    execute(combat,mid,'Sword',FOE)
    e=reload(tmp_path,mid)
    assert e.state.actors[FOE].current_hp==before
    assert mark_count(e.state.actors[OWNER],OWNER)==1
    assert e.state.actors[OWNER].reaction_available
