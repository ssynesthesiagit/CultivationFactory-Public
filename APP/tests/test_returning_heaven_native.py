"""Returning-Heaven service regressions; resources come from committed movement."""
import pytest
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.worker2_support import fixture, candidate, reload, settle, turn, OWNER, ALLY, FOE
from tests.hunt12_support import hit_dice
from tests.h1_support import ROOT
P = 'tianxia.subpath.body.returning_heaven_momentum_body.feature.'
M = 'resource:named.momentum'
IRON = 'tianxia.path.body_refining.feature.iron_fist'
LEVELS = [(3, 'gather_and_return'), (6, 'store_the_collision'), (10, 'rebounding_assault'),
          (14, 'avalanche_meridian_circuit'), (18, 'heaven_returning_impact')]

def start(tmp_path,cl=14,owned=True,*,foe_features=(),positions=None,arena=None):
    import json,zipfile
    from tests.h1_support import sheet
    from combat.tabletop_service import TabletopService
    docs={OWNER:sheet([IRON],cl=cl,primary='Stamina',key='STR',score=20,dc=22),
          ALLY:sheet([],cl=cl),FOE:sheet(list(foe_features),cl=cl,score=10)}
    docs[OWNER]['identity'].update(path='Body Refining',proficiency_bonus=6)
    docs[OWNER]['path_and_subpath']['path_record_ids']=['tianxia.path.body_refining']
    for aid,doc in docs.items():
        doc['ability_scores_and_statistics']['hit_points']['maximum']=300
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    combat=cold()
    state=combat.create_journey(project_ids=[aid.removeprefix('actor:factory.') for aid in docs],
        arena_id='battlefield:factory_pillar_arena',positions=positions or {OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':8,'y':6}},
        base_paces={aid:3000 for aid in docs})
    jid=state['journey_id']
    if owned:
        menu=cold().journey_source_choices(jid,OWNER,P.removesuffix('.feature.'))
        assert len(menu['options'])==1
        state=cold().journey_acquire_source(jid,menu['revision'],OWNER,P.removesuffix('.feature.'),menu['options'][0]['payload'])
        assert cold().journey_source_choices(jid,OWNER,P.removesuffix('.feature.'))['options']==[]
    result=cold().journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},maximum_rounds=30)
    mid=result['match_id'];combat=cold();table=TabletopService(combat,tmp_path)
    turn(table,mid,OWNER)
    return combat,table,mid

def move(combat, table, mid, x, y=6):
    row = next(c for c in combat._load_session(mid).engine.legal_candidates()
               if c.kind == 'MOVE' and c.destination == Position(x=x,y=y))
    settle(table, mid, row.candidate_id, choices={})

def checked(tmp_path, mid):
    session = CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine

@pytest.mark.parametrize('cl,expected',[(3,6),(14,9)])
def test_momentum_native_movement_round_budget_and_maximum(tmp_path, cl, expected):
    combat,table,mid = start(tmp_path,cl)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[M] == 0
    move(combat,table,mid,7)
    engine = checked(tmp_path,mid); a=engine.state.actors[OWNER]
    assert a.resources[M] == (2 if cl>=14 else 1)
    from combat.ext.subpath_pools import maximum
    assert maximum(engine,a,M) == expected
    move(combat,table,mid,7,5)
    assert checked(tmp_path,mid).state.actors[OWNER].resources[M] == (2 if cl>=14 else 1)

@pytest.mark.parametrize('cl,option,dice',[(14,'die',2),(17,'die',3),(14,'push',0)])
def test_avalanche_replaces_base_damage_and_options_before_damage(tmp_path,monkeypatch,cl,option,dice):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl)
    move(combat,table,mid,7)
    engine=reload(tmp_path,mid); before=len(engine.events)
    row=candidate(combat,mid,'Iron Fist',target=FOE)
    settle(table,mid,row.candidate_id,picks={
        'choice:needle.gather_and_return':(option,None),
        'choice:needle.gather_damage_type':'force'})
    engine=checked(tmp_path,mid)
    events=engine.events[before:]
    bonus=[r for r in engine.rolls if 'Gather and Return' in r.reason]
    if dice:
        assert bonus and bonus[-1].expression.startswith(str(dice)+'d8')
    else:
        assert not bonus
    spent=[e for e in events if e.event_type=='RESOURCE_SPENT' and e.payload.get('resource_id')==M]
    damage=[e for e in events if e.event_type=='DAMAGE_COMMITTED']
    assert spent and damage and spent[0].sequence < damage[0].sequence
    assert engine.state.actors[OWNER].resources[M] == 1
