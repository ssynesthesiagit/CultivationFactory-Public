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
        arena_id=next(iter(combat.factory_arenas())),positions=positions or {OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':8,'y':6}},
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
    settle(table, mid, row.candidate_id, choices={'choice:needle.fact_admission.momentum_eligibility':'genuine'})

def strike(combat,mid,target):
    engine=combat._load_session(mid).engine
    rows=[c for c in engine.legal_candidates() if c.target_ids==(target,)
        and any(e.get('type')=='attack' and e.get('attack_kind')=='unarmed'
                for e in ((getattr(engine.action_catalog.get(c.source_definition_id),'parameters',{}) or {}).get('typed') or {}).get('effects',[]))]
    assert rows,[(a.display_name,a.source_definition_id) for a in engine.action_catalog.values() if a.owner_id==engine.state.current_actor_id]
    return rows[0]

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
    row=strike(combat,mid,FOE)
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


def test_wrong_owner_has_no_momentum_choices_or_resource(tmp_path):
    combat,table,mid=start(tmp_path,owned=False)
    move(combat,table,mid,7)
    engine=checked(tmp_path,mid)
    assert M not in engine.state.actors[OWNER].resources
    assert not any(e.source_definition_id.startswith(P) for e in engine.events)


def test_acquisition_rejects_wrong_path_and_duplicate_progression(tmp_path):
    # The source menu cannot grant features to a character on another Path.
    from combat.ext.momentum_body import _selection_legal
    from tests.h1_support import sheet
    doc=sheet([],cl=18)
    assert not _selection_legal(doc)
    doc.setdefault('path_and_subpath',{})['path_record_ids']=['tianxia.path.body_refining']
    doc['path_and_subpath']['subpath_record_ids']=['tianxia.subpath.body.iron_shirt']
    assert not _selection_legal(doc)
    combat,table,mid=start(tmp_path)
    engine=checked(tmp_path,mid)
    roles=[r for r in engine.typed_passive_rows[OWNER] if r.get('kind')=='momentum']
    assert len([r for r in roles if r.get('role')=='rebound'])==1
    assert {r['role'] for r in roles}>={'gather','store','rebound','avalanche'}


@pytest.mark.parametrize('option',['ac','next_push','push','move'])
def test_gather_native_options_are_reachable_after_acquisition(tmp_path,monkeypatch,option):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=11)
    move(combat,table,mid,7)
    row=strike(combat,mid,FOE)
    prompts=settle(table,mid,row.candidate_id,picks={'choice:needle.gather_and_return':option,
        'choice:needle.gather_damage_type':'force','choice:needle.gather_move':'cell:7,5'})
    engine=checked(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.gather_and_return' for p in prompts)
    assert engine.state.actors[OWNER].resources[M]==0
    assert len([e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER])==1
    if option=='next_push':
        assert any(c.condition_id.endswith('gather_next_push') for c in engine.state.actors[OWNER].conditions.values())
    if option=='move':
        assert engine.state.actors[OWNER].position==Position(x=7,y=5)
    if option=='push':
        assert engine.state.actors[FOE].position==Position(x=9,y=6)


def test_store_impact_off_turn_cost_and_direct_gain_survive_reload(tmp_path,monkeypatch):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=6,foe_features=[IRON])
    move(combat,table,mid,7)
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[OWNER]
    prompts=settle(table,mid,strike(combat,mid,OWNER).candidate_id,
        choices={'choice:needle.store_impact':'store','choice:needle.fact_admission.momentum_eligibility':'genuine'})
    engine=checked(tmp_path,mid);owner=engine.state.actors[OWNER]
    assert any(p['context']['reaction_source_id']=='choice:needle.store_impact' for p in prompts)
    assert owner.resources['resource:core.stamina']==before.resources['resource:core.stamina']-1
    assert not owner.reaction_available
    assert owner.current_hp==before.current_hp
    assert owner.resources[M]==2  # one real movement grant + Store's direct grant


def test_rebounding_assault_after_melee_damage_runs_granted_strike(tmp_path,monkeypatch):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=14,foe_features=[IRON])
    move(combat,table,mid,7)
    turn(table,mid,FOE)
    row=strike(combat,mid,OWNER)
    prompts=settle(table,mid,row.candidate_id,choices={
        'choice:needle.rebounding_assault':'use','choice:needle.fact_admission.momentum_eligibility':'genuine','choice:needle.rebound_move':'cell:7,5',
        'choice:needle.rebound_hit':'prone'})
    engine=checked(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.rebounding_assault' for p in prompts)
    assert any(e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER for e in engine.events)
    assert any(c.condition_id.endswith('.prone') for c in engine.state.actors[FOE].conditions.values())


def test_heaven_impact_native_spends_all_momentum_and_leaves_bounded_ground(tmp_path,monkeypatch):
    hit_dice(monkeypatch,save_roll=1)
    combat,table,mid=start(tmp_path,cl=18)
    move(combat,table,mid,7)
    turn(table,mid,OWNER)  # already own turn: explicitly end through a new round
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,OWNER)
    move(combat,table,mid,3)
    engine=reload(tmp_path,mid);assert engine.state.actors[OWNER].resources[M]==4
    row=candidate(combat,mid,'Heaven-Returning Impact',at=(10,6))
    settle(table,mid,row.candidate_id,choices={'choice:needle.impact_push':None})
    engine=checked(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[M]==0
    assert engine.state.actors[OWNER].position==Position(x=10,y=6)
    assert any(r.reason=='DAMAGE:'+P+'heaven_returning_impact' and r.expression.startswith('10d10') for r in engine.rolls)
    zones=[z for z in engine.state.zones.values() if z.source_definition_id==P+'heaven_returning_impact']
    assert zones and all(engine.grid.distance_ft(zones[-1].center,c)<=10 for c in zones[-1].affected_cells)
    assert any(c.condition_id.endswith('.prone') for c in engine.state.actors[FOE].conditions.values())
