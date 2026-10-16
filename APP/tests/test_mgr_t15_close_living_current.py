"""Public-safe native regression; no historical fixture imports.

Dynamic authority dependencies: TAL_WATER_LIVING_CURRENT,
TAL_WATER_PULL_OF_THE_RIVER, WATER_BASE_WATER_LASH, WATER_BASE_SHAPE_CURRENT,
WATER_BASE_RETURN_THE_FLOW, tianxia.sphere.water.
Registry dependencies: combat.ext.water_basins, combat.ext.water_effects,
combat.ext.water_pull, combat.ext.water_second_pass, combat.ext.needle,
combat.ext.retained_updates, combat.ext.cp_pools, combat.ext.choice_costs.
"""
import json
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile
import pytest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'TAL_WATER_LIVING_CURRENT'
PIDS = ['10000000-0000-4000-8000-00000000000' + str(i) for i in (1, 2, 3)]
OWNER, ALLY, FOE = IDS = ['actor:factory.' + p for p in PIDS]
MOVE = 'choice:needle.water_living_area'
DEST = 'choice:needle.water_living_destination'
REPLACE = 'choice:needle.water_basin_replace'


def document(cl, name):
    return {'identity': {'name': name, 'cultivation_level': cl, 'proficiency_bonus': 3,
                         'path': 'Qi Cultivation', 'key_ability': 'WIS'},
            'ability_scores_and_statistics': {
                'abilities': [{'ability': a, 'score': 18 if a == 'WIS' else 10,
                               'modifier': 4 if a == 'WIS' else 0}
                              for a in ('STR','DEX','CON','INT','WIS','CHA')],
                'primary_resource': {'name': 'Qi', 'maximum': 30},
                'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 150, 'current': 150},
                'speed': {'walking_ft': 30}, 'technique_save_dc': 16, 'technique_attack_bonus': 8}}


def fixture(tmp_path, *, owned=True, cl=5, foe_at=(16,6), pull=False):
    for pid, name in zip(PIDS, ['Wren','Tobin','Mara']):
        folder=tmp_path/'portable_characters'/pid; folder.mkdir(parents=True)
        with ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(document(cl,name)))
    combat=CombatService(ROOT,tmp_path); table=TabletopService(combat,tmp_path)
    table.canonical_catalog=CanonicalCatalogAuthorityService(ROOT)
    table.add_advancement(PIDS[0],'sphere','tianxia.sphere.water',gm=True)
    if owned:
        table.add_advancement(PIDS[0],'talent',SOURCE,gm=True)
    if pull:
        table.add_advancement(PIDS[0],'talent','TAL_WATER_PULL_OF_THE_RIVER',gm=True)
    docs=[combat._factory_owner_sheet(pid) for pid in PIDS]
    assert (SOURCE in docs[0]['spheres_and_talents'].get('learned_talent_record_ids',[])) is owned
    bundles=[compile_character(d,actor_id=a,reaction_plan={'ask':True}) for d,a in zip(docs,IDS)]
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    mid=combat._finish_factory_match(bundles,IDS,{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},
        {OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':9},FOE:{'x':foe_at[0],'y':foe_at[1]}},
        arena,[OWNER,ALLY],[FOE],control_modes={a:'MANUAL' for a in IDS},
        match_seed='LIVING-CURRENT-NATIVE',display_name='Living Current',maximum_rounds=20)['match_id']
    turn(table,mid)
    return combat,table,mid


def act(table,mid,cid,picks=None):
    answers,prompts=[],[]
    for _ in range(20):
        v=table.state(mid);m=v['menu']
        r=table.act(mid,cid,m['decision_id'],m['state_version'],v['last_sequence'],answers)
        if r['status']!='REACTION_REQUIRED':
            assert r['status']=='COMMITTED',r
            return prompts
        p=r['reaction'];prompts.append(p)
        choice=(picks or {}).get(p['context']['reaction_source_id'],'first')
        ids=[p['choice']['options'][0]['id']] if choice=='first' else choice
        answers.append({**p['context'],'selection':'DECLINE' if ids is None else 'USE','option_ids':ids or []})
    raise AssertionError('Unsettled choice')


def turn(table,mid):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id']==OWNER:return
        act(table,mid,table.state(mid)['menu']['end_turn'])
    raise AssertionError('No owner turn')


def next_turn(table,mid):
    act(table,mid,table.state(mid)['menu']['end_turn']);turn(table,mid)


def candidate(combat,mid,name,at=None,target=None):
    e=combat._load_session(mid).engine
    cs=[c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id)
        and e.action_catalog[c.source_definition_id].display_name==name
        and (at is None or c.destination and (c.destination.x,c.destination.y)==at)
        and (target is None or target in c.target_ids)]
    assert cs,name
    return cs[0].candidate_id


def basin(c,t,mid,at=(8,6),picks=None):
    prompts=act(t,mid,candidate(c,mid,'Shape Current: Mist Basin',at=at),picks)
    z=next(z for z in c._load_session(mid).engine.state.zones.values()
           if z.active and z.owner_id==OWNER and (z.center.x,z.center.y)==at)
    return z.zone_id,prompts


def cold(tmp_path,mid):
    c=CombatService(ROOT,tmp_path);s=c._load_session(mid)
    assert s.mechanical.replay()['status']=='PASS'
    return c,TabletopService(c,tmp_path),s.engine


def lash(c,mid):
    e=c._load_session(mid).engine
    return [x for x in e.legal_candidates() if x.target_ids==(FOE,)
            and (e.action_catalog[x.source_definition_id].parameters.get('typed') or {}).get('source')=='WATER_BASE_WATER_LASH']


def test_source_and_native_foundation_gate(tmp_path):
    text=json.loads((ROOT/'authority/typed_mechanics/rules_text.json').read_bytes())[SOURCE]
    assert sha256(text.encode()).hexdigest()=='6864e5eacbd53c15355ba28147ffafea87018ecfd4bee986a1264290a1232a70'
    with pytest.raises(Exception):fixture(tmp_path/'early',cl=4)
    c,t,mid=fixture(tmp_path/'foundation')
    assert any(r.get('block')=='water_living_current' for r in c._load_session(mid).engine.typed_passive_rows[OWNER])


def test_native_origins_boundary_range_and_cold_commit(tmp_path):
    c,t,mid=fixture(tmp_path)
    assert not lash(c,mid),'dry body cannot get a blanket range bonus'
    zid,_=basin(c,t,mid,(14,6));next_turn(t,mid)
    c,t,e=cold(tmp_path,mid)
    choices=lash(c,mid);assert choices
    origins={tuple(sorted(x.metadata['effect_origin']['position'].items())) for x in choices}
    z=e.state.zones[zid]
    assert origins=={tuple(sorted(p.model_dump(mode='json').items())) for p in z.affected_cells
                     if e.grid.distance_ft(e.state.actors[OWNER].position,p)<=60}
    assert any(x.metadata['effect_origin']['position']['x']==15 for x in choices)
    assert not any(x.metadata['effect_origin']['position']['x']>15 for x in choices)
    chosen=choices[-1];before=e.state.actors[OWNER].position.model_dump(),dict(e.state.actors[OWNER].resources)
    act(t,mid,chosen.candidate_id)
    _,_,e=cold(tmp_path,mid)
    assert (e.state.actors[OWNER].position.model_dump(),dict(e.state.actors[OWNER].resources))==before
    assert any(v.payload.get('effect_origin')==chosen.metadata['effect_origin'] for v in e.events)
    assert any(v.event_type=='ATTACK_ROLLED' for v in e.events)


def test_native_two_basins_cap_selected_replacement_and_reload(tmp_path):
    c,t,mid=fixture(tmp_path)
    first,_=basin(c,t,mid,(8,6));next_turn(t,mid)
    second,_=basin(c,t,mid,(10,6));next_turn(t,mid)
    c,t,e=cold(tmp_path,mid)
    assert e.state.zones[first].active and e.state.zones[second].active
    third,ps=basin(c,t,mid,(12,6),{REPLACE:[second]})
    p=next(p for p in ps if p['context']['reaction_source_id']==REPLACE)
    assert {o['id'] for o in p['choice']['options']}=={first,second}
    _,_,e=cold(tmp_path,mid)
    assert e.state.zones[first].active and e.state.zones[third].active and not e.state.zones[second].active
    assert e.state.actors[OWNER].resources['resource:core.qi']==27


def test_no_living_has_one_basin_and_no_remote_origin(tmp_path):
    c,t,mid=fixture(tmp_path,owned=False)
    first,_=basin(c,t,mid,(8,6));next_turn(t,mid)
    second,_=basin(c,t,mid,(10,6))
    _,_,e=cold(tmp_path,mid)
    assert not e.state.zones[first].active and e.state.zones[second].active
    assert not any(x.metadata.get('effect_origin') for x in lash(c,mid))


@pytest.mark.parametrize('decline',[None,'area','destination'])
def test_return_moves_chosen_effect_twenty_feet_or_declines(tmp_path,decline):
    c,t,mid=fixture(tmp_path)
    first,_=basin(c,t,mid,(8,6));next_turn(t,mid)
    second,_=basin(c,t,mid,(10,6))
    c,t,e=cold(tmp_path,mid)
    snapshot=e.state.zones[first].model_dump(mode='json');z=e.state.zones[second]
    shape=z.affected_cells;lifetime=z.created_round,z.duration_rounds,z.concentration_link
    cp=dict(e.state.actors[OWNER].resources)
    ps=act(t,mid,candidate(c,mid,'Return the Flow: Move Water Effect'),
           {MOVE:None if decline=='area' else [second],DEST:None if decline=='destination' else ['14,6']})
    area=next(p for p in ps if p['context']['reaction_source_id']==MOVE)
    assert {o['id'] for o in area['choice']['options']}=={first,second}
    if decline!='area':
        options=next(p for p in ps if p['context']['reaction_source_id']==DEST)['choice']['options']
        assert '14,6' in {o['id'] for o in options} and '15,6' not in {o['id'] for o in options}
    _,_,e=cold(tmp_path,mid);z=e.state.zones[second]
    assert e.state.zones[first].model_dump(mode='json')==snapshot
    assert (z.created_round,z.duration_rounds,z.concentration_link)==lifetime
    assert dict(e.state.actors[OWNER].resources)==cp
    assert (z.center.x,z.center.y)==((10,6) if decline else (14,6))
    assert tuple((p.x,p.y) for p in z.affected_cells)==tuple((p.x+(0 if decline else 4),p.y) for p in shape)
