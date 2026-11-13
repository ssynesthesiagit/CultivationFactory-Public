"""Black-Lantern Commander service commits, owned choices and cold replay."""
import pytest
from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, turn, candidate, settle, reload, sealed_native_attack
from tests.test_a2_death_second_pass import preparation, direct, servant
from tests.h1_support import sheet
from combat.factory_compiler import compile_character

COMMANDER='insight.black-lantern-commander'


def commander_bundle(cl=15):
    document=sheet(['TAL_DEATH_GRAVE_FORMATION'],cl=cl)
    document['spheres_and_talents']['cultivation_insight_record_ids']=[COMMANDER]
    document['ability_scores_and_statistics']['primary_resource']['maximum']=100
    return compile_character(document,actor_id=OWNER,reaction_plan={'ask':True},
        summon_plan={'counts':{'grave_formation':1,'lesser_corpse_servant':0}})


@pytest.mark.parametrize('take',[True,False])
@pytest.mark.parametrize('auto',[False,True])
def test_commander_stats_final_assault_and_collapse(tmp_path,take,auto):
    def transform(bundles):
        preparation({})(bundles)
        sealed_native_attack(bundles[2],'Destroy formation',count=1,sides=2,modifier=500,attack_bonus=100)
        for summon in bundles[0]['summons']:
            for row in summon['action_catalog']:
                row['parameters']['typed']['numbers']['attack_bonus']=100
        for bundle in bundles:
            bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_GRAVE_FORMATION'],cl=15,
        owner_bundle=commander_bundle(),bundle_transform=transform,
        foe_position={'x':5,'y':5},ally_position={'x':3,'y':5})
    engine=reload(tmp_path,mid);a=servant(engine,'grave_formation');aid=a.entity_id
    assert a.maximum_hp==165 and a.speed_ft==30
    assert engine._distance_actor_to_actor(a,engine.state.actors[FOE])<=10
    assert engine._distance_actor_to_actor(a,engine.state.actors[ALLY])<=10
    turn(table,mid,FOE)
    if auto:
        combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    before=reload(tmp_path,mid).state.actors[FOE].current_hp
    prompts=settle(table,mid,candidate(combat,mid,'Destroy formation',target=aid).candidate_id,
        choices={'choice:needle.black_lantern_last_assault':[FOE] if take else None})
    engine=reload(tmp_path,mid)
    assert not engine.state.actors[aid].active and engine.state.actors[aid].summon['status']=='destroyed'
    spent=[c for c in engine.state.actors[OWNER].conditions.values()
           if c.condition_id=='condition:typed.black_lantern_last_assault_spent']
    if take or auto:
        assert spent and engine.state.actors[FOE].current_hp<before
        roll=next(r for r in reversed(engine.rolls) if r.actor_id==aid and r.reason.startswith('DAMAGE:'))
        assert roll.expression in {'2d8+2','4d8+2'}
        committed=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==aid]
        assert committed and all(e.target_ids==(FOE,) for e in committed)
    else:
        assert not spent and engine.state.actors[FOE].current_hp==before
    for prompt in prompts:
        if prompt['context']['reaction_source_id']=='choice:needle.black_lantern_last_assault':
            assert {option['id'] for option in prompt['choice']['options']}=={FOE}
