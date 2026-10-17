"""Attack provenance and shared scene limits through service commit/reload."""
from combat.canonical import canonical_sha256
from combat.ext import effect
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, turn, candidate, settle, reload, sealed_native_attack
from tests.test_a2_death_second_pass import preparation, direct, servant
from tests.test_a2_death_commander import COMMANDER


def reseal(bundles):
    for bundle in bundles:
        bundle.pop('bundle_sha256',None)
        bundle['bundle_sha256']=canonical_sha256(bundle)


def test_guard_does_not_reduce_non_attack_damage(tmp_path):
    def transform(bundles):
        preparation({})(bundles)
        sid='action:test.death_nonattack'
        bundles[2]['action_catalog'].append({'source_definition_id':sid,'display_name':'Nonattack damage',
            'owner_id':FOE,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,
            'parameters':{'typed':{'source':'test.death_nonattack','numbers':{},'riders':[],
                'effects':[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}],
                'duration':{'kind':'instant'}}}})
        bundles[2]['actor_template']['action_ids'].append(sid)
        reseal(bundles)
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_CORPSE_SERVANT','TAL_DEATH_DEATHLESS_GUARD'],cl=11,
        owner_plan={'counts':{'corpse_servant':1,'lesser_corpse_servant':0}},bundle_transform=transform,
        foe_position={'x':3,'y':5},ally_position={'x':2,'y':6})
    settle(table,mid,candidate(combat,mid,'Command Death servants').candidate_id)
    aid=servant(reload(tmp_path,mid),'corpse_servant').entity_id
    turn(table,mid,aid);direct(combat,mid,'Guard');turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[ALLY].current_hp
    prompts=settle(table,mid,candidate(combat,mid,'Nonattack damage',target=ALLY).candidate_id)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[ALLY].current_hp==before-1
    assert engine.state.actors[aid].reaction_available
    from combat.ext.eye_common import passive_perception
    assert passive_perception(engine,engine.state.actors[aid])==8+engine.state.actors[aid].proficiency_bonus
    assert not prompts
    assert not any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id=='TAL_DEATH_DEATHLESS_GUARD' for e in engine.events)


@effect("test_death_scene_successor", harmful=False)
def supplied_successor(ctx, row):
    # Scenario input: new remains after the first formation collapsed. The
    # public arrival procedure reuses its sealed slot as a fresh creature.
    from combat import summons
    summons.summon(ctx.engine, ctx.actor, 'grave_formation', ctx.source)


def test_commander_one_scene_allowance_shared_across_successive_formations(tmp_path):
    document=sheet(['TAL_DEATH_GRAVE_FORMATION'],cl=15)
    document['spheres_and_talents']['cultivation_insight_record_ids']=[COMMANDER]
    bundle=compile_character(document,actor_id=OWNER,reaction_plan={'ask':True},
        summon_plan={'counts':{'grave_formation':1,'lesser_corpse_servant':0}})
    def transform(bundles):
        for b,name,kind,effects in [
            (bundles[0],'Supply successor formation','SELF',[{'type':'test_death_scene_successor'}]),
            (bundles[2],'Destroy formation','HOSTILE_ENTITY',[{'type':'damage','flat':1000,'damage_types':['force'],'applies_to':'target'}])]:
            sid='action:test.'+name.lower().replace(' ','_')
            b['action_catalog'].append({'source_definition_id':sid,'display_name':name,
                'owner_id':b['actor_id'],'economy':'NONE' if kind=='SELF' else 'ACTION',
                'resolution_kind':'TYPED','target_kind':kind,'range_ft':60,
                'parameters':{'typed':{'source':sid,'effects':effects,'numbers':{},'riders':[],
                    'duration':{'kind':'instant'}}}})
            b['actor_template']['action_ids'].append(sid)
        for summon in bundles[0]['summons']:
            for row in summon['action_catalog']:
                row['parameters']['typed']['numbers']['attack_bonus']=100
        reseal(bundles)
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_GRAVE_FORMATION'],cl=15,owner_bundle=bundle,
        bundle_transform=transform,foe_position={'x':5,'y':5},ally_position={'x':3,'y':5})
    engine=reload(tmp_path,mid);formation=servant(engine,'grave_formation');aid=formation.entity_id
    from combat.ext.eye_common import passive_perception
    assert passive_perception(engine,formation)==8+formation.proficiency_bonus
    assert engine._distance_actor_to_actor(formation,engine.state.actors[FOE])<=10
    for index in range(2):
        if index:
            turn(table,mid,OWNER)
            direct(combat,mid,'Supply successor formation')
            engine=reload(tmp_path,mid)
            assert engine.state.actors[aid].active and engine.state.actors[aid].current_hp==165
            assert not any(c.condition_id=='condition:typed.black_lantern_last_assault_spent'
                           for c in engine.state.actors[aid].conditions.values())
            from combat import senses
            assert senses.of(engine,engine.state.actors[aid])['darkvision']['range_ft']==60
        turn(table,mid,FOE)
        before=len([e for e in reload(tmp_path,mid).events if e.event_type=='ATTACK_ROLLED' and e.actor_id==aid])
        prompts=settle(table,mid,candidate(combat,mid,'Destroy formation',target=aid).candidate_id,
            choices={'choice:needle.black_lantern_last_assault':[FOE]})
        engine=reload(tmp_path,mid)
        attacks=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==aid]
        assert len(attacks)-before==(1 if index==0 else 0)
        assert not engine.state.actors[aid].active
        assert any(c.condition_id=='condition:typed.black_lantern_last_assault_spent'
                   for c in engine.state.actors[OWNER].conditions.values())
        if index:
            assert not any(p['context']['reaction_source_id']=='choice:needle.black_lantern_last_assault' for p in prompts)
