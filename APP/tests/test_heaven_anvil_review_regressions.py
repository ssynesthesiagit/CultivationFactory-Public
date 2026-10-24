"""Focused service regressions for the four pre-merge Heaven-Anvil findings."""
import pytest
from combat.gate2_runtime_models import Position
from tests.heaven_anvil_review_support import (
    BASE, OWNER, TARGET, ROOT, acquired, cold, commit, fractures, turn,
)


@pytest.mark.parametrize('blocked',[False,True])
def test_judgment_nearest_legal_crater_edge_from_outer_annulus_and_blocked_route(tmp_path,blocked):
    objects=[{'id':1,'kind':'wall_section','x':12,'y':10,'hp':10000,'blocks':True}] if blocked else []
    start=(11,10) if blocked else (14,10)
    svc,table,mid=acquired(tmp_path,['heaven_anvil_judgment'],target_at=start,objects=objects)
    commit(table,mid,'heaven_anvil_judgment',at={'x':10,'y':10})
    e=cold(svc,mid);target=e.state.actors[TARGET]
    assert fractures(target)==4
    if blocked:
        assert target.position in (Position(x=12,y=9),Position(x=12,y=11))
        assert e.state.objects['object:map.1'].current_hp>0
    else:
        assert target.position==Position(x=13,y=10)
    movement=[ev for ev in e.events if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==TARGET]
    assert movement, 'Crater placement must use native forced movement, not teleport or direct state mutation.'


def test_meteor_preserves_ground_other_floor_and_empty_elevation_choices(tmp_path):
    svc,table,mid=acquired(tmp_path,['hundred_hammer_meteor_foundry'],owner_z=4)
    prompts=[]
    commit(table,mid,'hundred_hammer_meteor_foundry',choices={'choice:needle.anvil_points':['4,4']},prompts=prompts)
    point_prompt=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.anvil_points')
    options={o['id']:o for o in point_prompt['choice']['options']}
    assert {'4,4','4,4,1','4,4,4','4,4,22'}<=options.keys()
    assert '4,4,23' not in options # 95 feet above the native activation volume
    assert 'height 0 feet' in str(options['4,4'])
    assert 'height 20 feet' in str(options['4,4,4'])
    e=cold(svc,mid)
    assert e.state.actors[TARGET].current_hp<1000 and fractures(e.state.actors[TARGET])==1
    zones=[z for z in e.state.zones.values() if 'hundred_hammer' in z.source_definition_id]
    assert len(zones)==1 and zones[0].center==Position(x=4,y=4)
    assert e.state.actors[OWNER].resources['resource:core.qi']==95


def test_free_qi_bond_has_native_maul_variant_and_independent_one_qi_surcharge(tmp_path):
    spheres={'sphere_record_ids':['tianxia.sphere.qiweaving','tianxia.sphere.weapons'],
             'automatic_sphere_component_record_ids':['TAL_QIWEAVING_QI_BOND'],
             'learned_talent_record_ids':[]}
    svc,table,mid=acquired(tmp_path,['heaven_anvil_impact'],owner_spheres=spheres,target_ac=1)
    e=cold(svc,mid)
    originals=[a for a in e.action_catalog.values() if a.owner_id==OWNER
               and a.parameters.get('typed',{}).get('source')=='TAL_QIWEAVING_QI_BOND'
               and '#anvil_' not in a.source_definition_id]
    assert originals and all(not a.costs for a in originals)
    original=originals[0]
    variant=next(a for a in e.action_catalog.values() if a.source_definition_id.startswith(original.source_definition_id+'#anvil_'))
    assert variant.costs==(('resource:core.qi',1),)
    legal={c.source_definition_id for c in e.legal_candidates()}
    assert original.source_definition_id in legal and variant.source_definition_id in legal
    for attempt in range(8):
        before=table.state(mid)['last_sequence']
        commit(table,mid,variant.source_definition_id,choices={'choice:needle.anvil_ring':None})
        e=cold(svc,mid)
        attacks=[ev for ev in e.events if ev.event_type=='ATTACK_ROLLED' and ev.actor_id==OWNER and ev.sequence>before]
        assert len(attacks)==1
        assert e.state.actors[OWNER].resources['resource:core.qi']==100-attempt-1
        if attacks[0].payload['provisional_hit']:break
        turn(table,mid,TARGET);turn(table,mid,OWNER)
    else:raise AssertionError('No native hit in eight maul deliveries.')
    assert e.state.actors[TARGET].current_hp<1000
    assert any('qi_bond' in c.condition_id and c.source_actor_id==OWNER for c in e.state.actors[TARGET].conditions.values())


@pytest.mark.parametrize('cl,dice',[(3,2),(11,3),(17,4)])
def test_object_ring_table_prompts_identify_object_attack_dice_and_fracture_benefit(tmp_path,cl,dice):
    obj={'id':1,'kind':'wall_section','name':'Copper training gate','x':3,'y':5,'hp':2000,'ac':1,'blocks':False}
    svc,table,mid=acquired(tmp_path,['heaven_anvil_impact'],cl=cl,objects=[obj])
    prompts=[]
    for _ in range(8):
        commit(table,mid,'.object_attack.weapon',prompts=prompts)
        rings=[p for p in prompts if p['context']['reaction_source_id'] in {
            'choice:needle.anvil_ring_object','choice:needle.anvil_ring_object_damage'}]
        if rings:break
        turn(table,mid,TARGET);turn(table,mid,OWNER)
    assert len(rings)==2
    e=cold(svc,mid)
    attack=next(ev for ev in e.events if ev.event_type=='ATTACK_ROLLED' and ev.actor_id==OWNER and ev.payload.get('provisional_hit'))
    action=e.action_catalog[attack.source_definition_id]
    for prompt in rings:
        text=str(prompt)
        assert 'Copper training gate' in text
        assert action.display_name in text
        assert f'{dice}d8' in text
        assert '1 Qi' in text and 'once per turn' in text
        assert 'damage threshold' in text and 'scene end or repair' in text
        assert prompt['affected']=='Copper training gate'
        assert prompt['action']==action.display_name
        displayed=str({key:value for key,value in prompt.items() if key!='context'})
        assert 'object:map.' not in displayed
    assert e.state.objects['object:map.1'].component['anvil_fractures'][OWNER]['count']==1
    assert e.state.actors[OWNER].resources['resource:core.qi']==99


@pytest.mark.parametrize('target_ac,hit',[(1,True),(40,False)])
def test_native_paid_maul_conduction_hit_and_miss_keep_complete_cost(tmp_path,target_ac,hit):
    # This regression isolates delivery with portable granted source records.
    # Native school-learning coverage remains in the original lane tests; its
    # full advancement menu requires a Path-access catalog excluded from CI.
    # It does not assert the stock Fate reaction's Ask prompt: the public export
    # replaces that talent's printed trigger prose, so the generic trigger
    # classifier cannot offer it there. Delivery below is source-owned.
    svc,table,mid=acquired(tmp_path,['heaven_anvil_impact'],learn_fate=True,target_ac=target_ac)
    prompts=[]
    for attempt in range(8 if hit else 1):
        before=table.state(mid)['last_sequence']
        commit(table,mid,'TAL_FATE_BINDING_WORD#anvil_',choices={'choice:needle.anvil_ring':None},prompts=prompts)
        e=cold(svc,mid)
        attacks=[ev for ev in e.events if ev.event_type=='ATTACK_ROLLED' and ev.actor_id==OWNER and ev.sequence>before]
        assert len(attacks)==1
        assert e.state.actors[OWNER].resources['resource:core.qi']==100-3*(attempt+1)
        saves=[ev for ev in e.events if ev.event_type=='SAVE_ROLLED' and ev.actor_id==TARGET and ev.sequence>before]
        landed=attacks[0].payload['provisional_hit']
        if not landed:
            assert e.state.actors[TARGET].current_hp==1000 and not saves
        if landed==hit:break
        turn(table,mid,TARGET);turn(table,mid,OWNER)
    else:raise AssertionError('No native paid hit occurred in eight declarations')
    if hit:
        technique_saves=[ev for ev in saves if str(ev.payload.get('reason') or '').endswith(':CHA')]
        assert e.state.actors[TARGET].current_hp<1000 and technique_saves
        delivered=e.action_catalog[attacks[0].source_definition_id]
        original=e.action_catalog[delivered.source_definition_id.split('#anvil_',1)[0]]
        weapon=e.action_catalog[delivered.parameters['anvil_weapon']]
        expected_dc=original.parameters['typed']['numbers']['save_dc']
        assert expected_dc!=weapon.parameters['typed']['numbers']['save_dc']
        assert all(ev.payload['dc']==expected_dc for ev in technique_saves)
        damage=next(ev for ev in e.events if ev.event_type=='DAMAGE_COMMITTED' and TARGET in ev.target_ids and ev.sequence>before)
        assert damage.sequence<technique_saves[0].sequence
    else:
        assert e.state.actors[TARGET].current_hp==1000 and not saves
    turn(table,mid,TARGET);turn(table,mid,OWNER)
    commit(table,mid,'.stow')
    assert not any('#anvil_' in c.source_definition_id for c in table.combat._load_session(mid).engine.legal_candidates())
