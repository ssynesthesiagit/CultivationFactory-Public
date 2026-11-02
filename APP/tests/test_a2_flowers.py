"""Flowers combat contracts via accepted service/table transactions and cold reload."""
import pytest
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import check_mode
from tests.h1_support import ROOT, sheet
from tests.hunt12_support import ME, FOE, candidate, send, reload, event_hook
from tests.test_auto86_flowers import flowers_fight, shape, at, _walk

ALLY='actor:factory.flowers-ally'
HUNDRED='TAL_FLOWERS_GARDEN_OF_THE_HUNDRED_BLOSSOMS'
BEGUILE='TAL_FLOWERS_BEGUILING_PERFUME'
CALM='TAL_FLOWERS_CALMING_PERFUME'
FRAGRANCE='FLOWERS_BASE_FRAGRANCE'
POISON='TAL_FLOWERS_POISON_BLOSSOM'
STORM='TAL_FLOWERS_THOUSAND_PETAL_STORM'
WARD='TAL_FLOWERS_PETAL_WARD'
THORN='TAL_FLOWERS_THORNED_BLOOM'
DART='TAL_FLOWERS_PETAL_DART'


def commit(combat,table,mid,chosen,*,picks=(),decline=False,auto=False):
    answers=[]
    result=send(combat,table,mid,chosen,auto=auto)
    for _ in range(8):
        if result['status']!='REACTION_REQUIRED': break
        prompt=result['reaction']
        if not prompt.get('choice'): answer={**prompt['context'],'selection':'DECLINE'}
        else:
            ids=[o['id'] for o in prompt['choice']['options']]
            picked=next((p for p in picks if p in ids),ids[0])
            answer={**prompt['context'],'selection':'DECLINE' if decline else 'USE','option_ids':[] if decline else [picked]}
        answers.append(answer)
        result=send(combat,table,mid,chosen,answers,auto=auto)
    assert result['status']=='COMMITTED',result


def end(combat,table,mid,**kw):
    commit(combat,table,mid,candidate(combat,mid,lambda c:c.kind.value=='END_TURN'),**kw)


def advance(combat,table,mid,who,**kw):
    for _ in range(4):
        if combat._load_session(mid).engine.state.current_actor_id==who: return
        end(combat,table,mid,auto=combat.decision(mid)['control_mode']=='LOCAL_AUTO',**kw)
    raise AssertionError('initiative failed to reach '+who)


def scene(tmp_path,mids,dc=100,cl=18,control_modes=None):
    docs=[sheet(mids,cl=cl,dc=dc,primary='Stamina',score=18),sheet([],cl=cl,primary='Stamina'),sheet([],cl=cl,primary='Stamina')]
    for doc,name in zip(docs,['Garden keeper','Garden foe','Garden ally']):
        doc['ability_scores_and_statistics']['hit_points']['maximum']=1000
        doc['identity']['display_name']=name
    docs[0]['ability_scores_and_statistics']['technique_attack_bonus']=30
    bundles=[compile_character(doc,actor_id=who) for doc,who in zip(docs,[ME,FOE,ALLY])]
    combat=CombatService(ROOT,tmp_path); table=TabletopService(combat,tmp_path)
    mid=combat._finish_factory_match(bundles,[ME,ALLY,FOE],{ME:'team:factory',ALLY:'team:factory',FOE:'team:opponents'},
        {ME:{'x':3,'y':6},FOE:{'x':4,'y':6},ALLY:{'x':4,'y':5}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],[ME,ALLY],[FOE],
        control_modes=control_modes or {ME:'MANUAL',FOE:'MANUAL',ALLY:'MANUAL'},match_seed='A2FLOWERS',
        display_name='Flowers service regression',maximum_rounds=20)['match_id']
    advance(combat,table,mid,ME)
    return combat,table,mid


def seed_condition(monkeypatch,who,name,save=None):
    def fixture(engine,event,kwargs):
        if event=='ZONE_CREATED' and not any(c.condition_id=='condition:typed.'+name for c in engine.state.actors[who].conditions.values()):
            engine._apply_condition(engine.state.actors[who],'condition:typed.'+name,'test:condition',FOE,
                expires_on='UNTIL_REMOVED',data={'origin_save':save} if save else {})
    event_hook(monkeypatch,fixture)


@pytest.mark.parametrize('penalty',['Poisoned','Reduce Speed','No Reactions','Poison Damage'])
def test_hundred_enemy_start_choices(tmp_path,penalty):
    combat,table,mid=scene(tmp_path,[HUNDRED])
    commit(combat,table,mid,candidate(combat,mid,lambda c:c.display_name.startswith('Garden of the Hundred Blossoms')))
    engine=reload(tmp_path,mid)
    assert not [e for e in engine.events if e.event_type=='SAVE_ROLLED' and HUNDRED in e.source_definition_id]
    assert engine.state.actors[ME].resources['resource:core.stamina']==23
    end(combat,table,mid,picks=[penalty]); advance(combat,table,mid,FOE,picks=[penalty])
    engine=reload(tmp_path,mid); foe=engine.state.actors[FOE]
    assert len([e for e in engine.events if e.event_type=='SAVE_ROLLED' and HUNDRED in e.source_definition_id and e.actor_id==FOE])==1
    assert foe.temporary_hp==0
    if penalty=='Poisoned': assert any(c.condition_id=='condition:typed.poisoned' for c in foe.conditions.values())
    elif penalty=='Reduce Speed': assert engine._effective_speed(foe)==10
    elif penalty=='No Reactions': assert any(c.condition_id=='condition:typed.reaction_denied' for c in foe.conditions.values())
    else:
        assert foe.current_hp<1000
        assert any(e.event_type=='DAMAGE_ROLLED' and '2d8' in e.payload.get('expression','') for e in engine.events)
    assert _walk(combat,table,mid,5,6)
    engine=reload(tmp_path,mid)
    assert len([e for e in engine.events if e.event_type=='SAVE_ROLLED' and HUNDRED in e.source_definition_id and e.actor_id==FOE])==1


@pytest.mark.parametrize('benefit',['Temporary HP','End Poisoned','Increase Speed'])
def test_hundred_ally_start_choices(tmp_path,monkeypatch,benefit):
    if benefit=='End Poisoned': seed_condition(monkeypatch,ALLY,'poisoned')
    combat,table,mid=scene(tmp_path,[HUNDRED])
    commit(combat,table,mid,candidate(combat,mid,lambda c:c.display_name.startswith('Garden of the Hundred Blossoms')))
    end(combat,table,mid,picks=[benefit]); advance(combat,table,mid,ALLY,picks=[benefit])
    engine=reload(tmp_path,mid); ally=engine.state.actors[ALLY]
    assert not [e for e in engine.events if e.event_type=='SAVE_ROLLED' and ALLY in e.target_ids and HUNDRED in e.source_definition_id]
    if benefit=='Temporary HP': assert ally.temporary_hp==4
    elif benefit=='End Poisoned': assert not any(c.condition_id=='condition:typed.poisoned' for c in ally.conditions.values())
    else:
        assert engine._effective_speed(ally)==40
        end(combat,table,mid); engine=reload(tmp_path,mid)
        assert engine._effective_speed(engine.state.actors[ALLY])==30


def test_hundred_success_only_slows(tmp_path):
    combat,table,mid=scene(tmp_path,[HUNDRED],dc=-100)
    commit(combat,table,mid,candidate(combat,mid,lambda c:c.display_name.startswith('Garden of the Hundred Blossoms')))
    end(combat,table,mid); advance(combat,table,mid,FOE)
    engine=reload(tmp_path,mid)
    assert engine._effective_speed(engine.state.actors[FOE])==20
    assert engine.state.actors[FOE].current_hp==1000


@pytest.mark.parametrize('decline',[False,True])
def test_calming_original_save_and_consent(tmp_path,monkeypatch,decline):
    seed_condition(monkeypatch,FOE,'frightened',{'ability':'WIS','dc':1})
    combat,table,mid=scene(tmp_path,[FRAGRANCE,CALM])
    shape(combat,table,mid,'Shape Fragrance: Calming Perfume')
    commit(combat,table,mid,at(combat,mid,'Fragrance',4,6))
    engine=reload(tmp_path,mid)
    assert check_mode(engine.state.actors[FOE],'CHA','Intimidation',engine=engine)=='DISADVANTAGE'
    assert check_mode(engine.state.actors[ME],'CHA','Intimidation',engine=engine)=='NORMAL'
    end(combat,table,mid,decline=decline); advance(combat,table,mid,FOE,decline=decline)
    engine=reload(tmp_path,mid)
    assert any(c.condition_id=='condition:typed.frightened' for c in engine.state.actors[FOE].conditions.values())==decline
    assert len([e for e in engine.events if e.event_type=='SAVE_ROLLED' and FRAGRANCE in e.source_definition_id])==(0 if decline else 1)
    assert engine.state.actors[ME].resources['resource:core.stamina']==29
    assert _walk(combat,table,mid,8,6)
    engine=reload(tmp_path,mid)
    assert not any((c.data or {}).get('name')=='Calming Perfume' for c in engine.state.actors[FOE].conditions.values())


def test_beguiling_protects_charmer_and_penalizes_attacks_on_ally(tmp_path):
    combat,table,mid=scene(tmp_path,[FRAGRANCE,BEGUILE])
    shape(combat,table,mid,'Shape Fragrance: Beguiling Perfume')
    commit(combat,table,mid,at(combat,mid,'Fragrance',4,6))
    end(combat,table,mid); advance(combat,table,mid,FOE)
    engine=reload(tmp_path,mid)
    charm=next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.charmed')
    assert charm.data['flowers_beguiling']==1
    assert not [c for c in engine.legal_candidates() if c.display_name.startswith('Unarmed Strike') and ME in c.target_ids]
    commit(combat,table,mid,candidate(combat,mid,lambda c:c.display_name.startswith('Unarmed Strike') and ALLY in c.target_ids))
    engine=reload(tmp_path,mid)
    assert [e.payload['mode'] for e in engine.events if e.event_type=='ATTACK_ROLLED']==['DISADVANTAGE']


@pytest.mark.parametrize('cl,dice',[(5,'3d6'),(11,'5d6'),(17,'7d6')])
def test_poison_damage_scale_and_once_per_turn(tmp_path,cl,dice):
    combat,table,mid=flowers_fight(tmp_path,[FRAGRANCE,POISON],dc=100,cl=cl,ask_reactions=False)
    shape(combat,table,mid,'Shape Fragrance: Poison Blossom')
    commit(combat,table,mid,at(combat,mid,'Fragrance',4,6)); end(combat,table,mid)
    engine=reload(tmp_path,mid)
    rolls=[e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and FRAGRANCE in e.source_definition_id]
    assert len(rolls)==1 and dice in rolls[0].payload['expression']
    assert _walk(combat,table,mid,8,6); assert _walk(combat,table,mid,7,6)
    engine=reload(tmp_path,mid)
    assert len([e for e in engine.events if e.event_type=='DAMAGE_ROLLED' and FRAGRANCE in e.source_definition_id])==1


@pytest.mark.parametrize('dc',[-100,100])
def test_storm_expires_on_caster_next_turn(tmp_path,dc):
    combat,table,mid=flowers_fight(tmp_path,[STORM],dc=dc,cl=17,ask_reactions=False)
    commit(combat,table,mid,at(combat,mid,'Thousand-Petal Storm',4,6))
    engine=reload(tmp_path,mid); condition='condition:typed.blinded' if dc==100 else 'condition:typed.reaction_denied'
    assert any(c.condition_id==condition for c in engine.state.actors[FOE].conditions.values())
    end(combat,table,mid); engine=reload(tmp_path,mid)
    assert any(c.condition_id==condition for c in engine.state.actors[FOE].conditions.values())
    end(combat,table,mid); engine=reload(tmp_path,mid)
    assert not any(c.condition_id==condition for c in engine.state.actors[FOE].conditions.values())


def test_changed_rows_full_and_no_manual_riders():
    from tests.h1_support import mechanics
    assert all(mechanics()[k]['coverage']=='FULL' and not mechanics()[k]['riders'] for k in [HUNDRED,BEGUILE,CALM,POISON,STORM,WARD,THORN,DART])
