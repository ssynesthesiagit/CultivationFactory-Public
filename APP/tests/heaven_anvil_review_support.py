"""Portable synthetic table fixtures for Heaven-Anvil review regressions.

No history, private fixtures, external services or owner evidence paths.
"""
import copy
import json
import zipfile
from pathlib import Path
from functools import lru_cache
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
ROOT=Path(__file__).resolve().parents[1]
BASE='tianxia.subpath.qi.heaven_anvil_maul_cultivator.feature.'
OWNER=FACTORY_ACTOR_PREFIX+'a1111111-1111-4111-8111-111111111111'
TARGET=FACTORY_ACTOR_PREFIX+'b2222222-2222-4222-8222-222222222222'
FRACTURE='condition:typed.mark.anvil_fracture.'

@lru_cache(maxsize=1)
def native_catalog():
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    return CanonicalCatalogAuthorityService(ROOT)

def sheet(ids=(), *, cl=18, dc=50, mods=None, items=(), spheres=None, stamina=60, name="C7 Cultivator"):
    scores = {a: 2 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    scores.update(mods or {})
    return {
        "identity": {"display_name": name, "proficiency_bonus": 6 if cl >= 17 else 5 if cl >= 13 else 4 if cl >= 9 else 3 if cl >= 5 else 2,
                     "cultivation_level": cl, "path": "Body Refining", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 10 + 2 * v, "modifier": v} for a, v in scores.items()],
            "primary_resource": {"name": "Stamina", "maximum": stamina}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 120}, "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8},
        "path_and_subpath": {"path_feature_record_ids": list(ids)},
        "spheres_and_talents": copy.deepcopy(spheres if spheres is not None else {}),
        "equipment": [{"starting_kit": {"items": [{"item_id": item} for item in items]}}],
    }


def acquired(tmp_path,features,*,cl=18,dc=50,target_at=(4,4),owner_items=('tianxia.mortal.weapon.da_chui',),target_items=(),objects=(),foe_features=(),learn_school=False,qi_profile=None,learn_fate=False,target_ac=14,owner_spheres=None,owner_z=0,walls=()):
    for name,ids,items in [('a1111111-1111-4111-8111-111111111111',[BASE+k for k in features],owner_items),('b2222222-2222-4222-8222-222222222222',[],target_items)]:
        if name=='b2222222-2222-4222-8222-222222222222' and foe_features:
            from tests.h1_support import mechanics
            records=mechanics()
            ids=[k for k in foe_features if records[k].get('kind') in {'path_feature','subpath_feature'}]
            spheres={records[k]['sphere_id'] for k in foe_features if records[k].get('sphere_id')}
            sphere_data={'sphere_record_ids':sorted(spheres),
                'learned_talent_record_ids':[k for k in foe_features if records[k].get('kind')=='talent'],
                'automatic_sphere_component_record_ids':[k for k,v in records.items() if v.get('kind')=='base_ability' and v.get('sphere_id') in spheres]}
        else:sphere_data={}
        if name=='a1111111-1111-4111-8111-111111111111' and learn_school:ids=[]
        if name.startswith('a111') and learn_fate:
            # Portable granted Sphere records, not a Sphere-learning test: the
            # full Path-access catalog is intentionally absent on public CI.
            # Native parent-school acquisition is still exercised below.
            records=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
            spheres={'tianxia.sphere.weapons','tianxia.sphere.fate'}
            sphere_data={'sphere_record_ids':sorted(spheres),
                'learned_talent_record_ids':['TAL_FATE_BINDING_WORD'],
                'automatic_sphere_component_record_ids':[k for k,v in records.items()
                    if v.get('kind')=='base_ability' and v.get('sphere_id') in spheres]}
        if name.startswith('a111') and owner_spheres is not None:sphere_data=owner_spheres
        doc=sheet(ids,cl=cl,dc=dc,items=items,spheres=sphere_data)
        if name=='a1111111-1111-4111-8111-111111111111' and learn_school:
            doc['path_and_subpath']['path_record_ids']=['tianxia.path.qi_cultivation']
            if qi_profile is not None:doc['path_and_subpath']['paths']=[{'path_id':'tianxia.path.qi_cultivation',**qi_profile}]
        doc['identity'].update(path='Qi Cultivation',display_name='Anvil owner' if name=='a1111111-1111-4111-8111-111111111111' else 'Anvil target')
        doc['ability_scores_and_statistics']['primary_resource']={'name':'Qi','maximum':100}
        doc['ability_scores_and_statistics']['hit_points']={'maximum':1000}
        if name=='b2222222-2222-4222-8222-222222222222':doc['ability_scores_and_statistics']['armor_class']={'base_value':target_ac}
        folder=tmp_path/'portable_characters'/name;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    svc=CombatService(ROOT,tmp_path)
    table=TabletopService(svc,tmp_path)
    table.canonical_catalog=native_catalog()
    if learn_fate:
        # Manual control does not itself make optional generic reactions Ask.
        # Persist the real Ask-me preference so Twist of Fate can be declined.
        table.buttons.save_reactions('a1111111-1111-4111-8111-111111111111',
            {'mode':'ask'},{'TAL_FATE_TWIST_OF_FATE'})
    if learn_school:
        from app.models import TabletopAdvanceRequest
        request=TabletopAdvanceRequest(kind='subpath',record_id=BASE.removesuffix('.feature.'))
        journal=table.add_advancement('a1111111-1111-4111-8111-111111111111',request.kind,request.record_id,gm=request.gm)
        row=next(r for r in journal['added']['subpaths'] if r['id']==BASE.removesuffix('.feature.'))
        assert not row['gm']

    svc.tabletop_maps.save({'display_name':'Anvil source yard','width_squares':30,'height_squares':24,
        'walls':list(walls),'objects':list(objects),'starts':{'team1':[[3,4]],'team2':[list(target_at)]}})
    mid=svc.create_factory_match(project_ids=['a1111111-1111-4111-8111-111111111111'],opponent_actor_ids=[TARGET],
        control_modes={OWNER:'MANUAL',TARGET:'MANUAL'},arena_id='battlefield:map.anvil-source-yard',
        match_seed='ANVIL-NATIVE-58')['match_id']
    if owner_z:
        # Recreate the synthetic roster through native match creation, never
        # mutate a running fight's positions or serialized state.
        from combat.factory_compiler import compile_character
        from combat.tabletop import to_battlefield
        from combat.canonical import canonical_sha256
        bundles=[compile_character(svc._factory_owner_sheet(a.removeprefix(FACTORY_ACTOR_PREFIX)),actor_id=a)
                 for a in (OWNER,TARGET)]
        bundles[0]['actor_template'].update(fly_speed_ft=30,hover=True)
        bundles[0].pop('bundle_sha256')
        bundles[0]['bundle_sha256']=canonical_sha256(bundles[0])
        mid=svc._finish_factory_match(bundles,[OWNER,TARGET],{OWNER:'team:a',TARGET:'team:b'},
            {OWNER:{'x':3,'y':4,'z':owner_z},TARGET:{'x':target_at[0],'y':target_at[1]}},
            to_battlefield(svc.tabletop_maps.get('anvil-source-yard')),[OWNER],[TARGET],
            control_modes={OWNER:'MANUAL',TARGET:'MANUAL'},match_seed='ANVIL-NATIVE-58',
            display_name='Elevated Anvil source yard',maximum_rounds=10)['match_id']
    turn(table,mid,OWNER)
    return svc,table,mid


def turn(table,mid,actor):
    for _ in range(5):
        if table.state(mid)['menu']['actor_id']==actor:return
        state=table.state(mid);menu=state['menu']
        assert table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],state['last_sequence'])['status']=='COMMITTED'
    raise AssertionError('No turn')


def cold(svc,mid):
    loaded=CombatService(ROOT,svc.userdata_root)._load_session(mid)
    assert loaded.verify()['status']=='PASS'
    assert loaded.mechanical.replay()['status']=='PASS'
    return loaded.engine

def commit(table,mid,source,*,choices=None,at=None,prompts=None):
    state=table.state(mid);menu=state['menu']
    group=next((g for g in menu['actions'] if source.lower() in g['source_definition_id'].lower()),None)
    if at is None and group is not None:
        option=group['options'][0]
    else:
        # Compact menus omit some utility groups and preview only some cells.
        # Submit an actual complete native candidate through the same table API.
        engine=table.combat._load_session(mid).engine
        candidates=[c for c in engine.legal_candidates() if source.lower() in c.source_definition_id.lower()
            and (at is None or c.destination is not None and c.destination.x==at['x'] and c.destination.y==at['y'])]
        if not candidates:
            from combat.action_legality import query_many
            matching=[k for k in engine.action_catalog if source.lower() in k.lower()]
            details=query_many(engine,menu['actor_id'],matching) if matching else {'missing_catalog_definition':source}
            raise AssertionError((source,details))
        option={'candidate_id':candidates[0].candidate_id}
    answers=[]
    for _ in range(40):
        result=table.act(mid,option['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
        if result['status']=='COMMITTED':return result
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction']
        if prompts is not None:prompts.append(p)
        answer={**p['context'],'selection':'USE'}
        if p.get('choice'):
            selection=(choices or {}).get(p['context']['reaction_source_id'],'first')
            if selection is None:answer['selection']='DECLINE'
            else:answer['option_ids']=[p['choice']['options'][0]['id']] if selection=='first' else ([selection] if isinstance(selection,str) else selection)
        else:answer['selection']='DECLINE'
        answers.append(answer)
    raise AssertionError('Too many prompts')


def fractures(actor):
    return sum(c.data['count'] for c in actor.conditions.values() if c.condition_id.startswith(FRACTURE) and c.source_actor_id==OWNER)
