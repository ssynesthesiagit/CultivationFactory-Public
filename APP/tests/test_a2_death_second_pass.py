"""Servant mechanics through CombatService transactions and cold replay."""
import pytest
from combat.canonical import canonical_sha256
from combat.ext import effect
from combat.gate2_runtime_models import ActionIntent, RuntimeObjectState, Position
from tests.worker2_support import OWNER, ALLY, FOE, fixture, turn, candidate, settle, reload, sealed_native_attack


@effect("test_death_second_setup", harmful=False)
def setup(ctx, row):
    if row.get('object_material'):
        ctx.engine._update_object(RuntimeObjectState(object_id="object:death-second-decay",
            object_kind="custom", position=Position(x=4,y=6), current_hp=500, maximum_hp=500,
            ac=1, unattended=not row.get('attended'), flammable=False,
            component={"blocks":False,"material":row['object_material'],"magical":bool(row.get('magical'))}),ctx.source)
    for actor in ctx.engine.state.actors.values():
        if (actor.summon or {}).get("owner") == OWNER:
            if row.get("hp") is not None:
                ctx.engine._commit_damage(actor, actor.current_hp - row['hp'], "UNTYPED", ctx.source, OWNER, None, reaction_depth=0)
            if row.get("corpse"):
                ctx.engine._update_object(RuntimeObjectState(object_id="object:death-second-corpse",
                    object_kind=row['corpse'], position=actor.position, current_hp=10, maximum_hp=10,
                    ac=10, unattended=True, flammable=False, component={"blocks":False}),ctx.source)
            if row.get("sickened"):
                ctx.engine._apply_condition(actor,"condition:typed.sickened",ctx.source,OWNER,expires_on="UNTIL_REMOVED")
            if row.get("healing_minus"):
                ctx.engine._add_modifier(actor, "test:flat_healing_reduction", "healing_reduction",
                    "ADD", f"minus:{row['healing_minus']}", "ALWAYS", expires_on="UNTIL_REMOVED")


def preparation(row, *, hit=0):
    def transform(bundles):
        b = bundles[0]
        sid="action:test.death_second_setup"
        b['action_catalog'].append({'source_definition_id':sid,'display_name':'Set servant scenario',
            'owner_id':OWNER,'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','costs':[],
            'parameters':{'typed':{'effects':[{'type':'test_death_second_setup',**row}],
                                  'numbers':{},'duration':{'kind':'instant'},'riders':[]}}})
        b['actor_template']['action_ids'].append(sid)
        if hit:
            sealed_native_attack(bundles[2], 'Guard test attack', count=1, sides=2, modifier=hit-1, attack_bonus=100)
        for bundle in bundles:
            bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    return transform


def direct(combat, mid, name, target=None):
    c=candidate(combat,mid,name,target=target)
    combat._load_session(mid).mechanical.execute_intent(ActionIntent(intent_id='death-second-'+c.candidate_id,
        decision_id=c.decision_id,candidate_id=c.candidate_id,state_version=c.state_version,
        actor_id=c.actor_id,target_ids=c.target_ids,destination=c.destination))


def servant(engine, kind):
    return next(a for a in engine.state.actors.values() if (a.summon or {}).get('owner')==OWNER
                and a.summon.get('death_servant_rules',{}).get('kind')==kind)


@pytest.mark.parametrize('size,cells',[('large',2),('huge',3)])
@pytest.mark.parametrize('corpse,hp,expected',[('corpse',73,75),('corpse',50,54),('crate',50,50)])
def test_formation_recovery_size_and_dismissal(tmp_path,size,cells,corpse,hp,expected):
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_GRAVE_FORMATION'],cl=15,
        owner_plan={'counts':{'grave_formation':1,'lesser_corpse_servant':0},'death_sizes':{'grave_formation':size}},
        bundle_transform=preparation({'hp':hp,'corpse':corpse}))
    direct(combat,mid,'Set servant scenario')
    settle(table,mid,candidate(combat,mid,'Command Death servants').candidate_id)
    engine=reload(tmp_path,mid); a=servant(engine,'grave_formation');aid=a.entity_id
    assert a.maximum_hp==150
    assert engine._footprint(a).width_cells==cells
    assert a.size_category==size.title()
    turn(table,mid,aid)
    engine=reload(tmp_path,mid);assert engine.state.actors[aid].current_hp==expected
    from combat import senses
    assert senses.of(engine,engine.state.actors[aid])['darkvision']['range_ft']==60
    turn(table,mid,OWNER)
    old=reload(tmp_path,mid).state.actors[OWNER]
    economy=(old.action_available,old.bonus_action_available,old.resources.copy())
    settle(table,mid,candidate(combat,mid,'Dismiss a Death servant').candidate_id,
           choices={'choice:needle.death_servant_dismiss':[aid]})
    engine=reload(tmp_path,mid);owner=engine.state.actors[OWNER]
    assert not engine.state.actors[aid].active and engine.state.actors[aid].summon['status']=='dismissed'
    assert (owner.action_available,owner.bonus_action_available,owner.resources)==economy


@pytest.mark.parametrize('cl,count',[(5,1),(11,2),(17,3)])
def test_guard_attack_scale_step_expiry_and_sides(tmp_path,cl,count):
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_CORPSE_SERVANT','TAL_DEATH_DEATHLESS_GUARD'],cl=cl,
        owner_plan={'counts':{'corpse_servant':1,'lesser_corpse_servant':0}},
        bundle_transform=preparation({},hit=1),foe_position={'x':3,'y':5},
        ally_position={'x':2,'y':6})
    direct(combat,mid,'Set servant scenario')
    settle(table,mid,candidate(combat,mid,'Command Death servants').candidate_id)
    engine=reload(tmp_path,mid);a=servant(engine,'corpse_servant');aid=a.entity_id
    turn(table,mid,aid)
    direct(combat,mid,'Guard')
    engine=reload(tmp_path,mid);a=engine.state.actors[aid]
    assert engine._distance_actor_to_actor(a,engine.state.actors[ALLY])<=5
    before=a.position
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Guard test attack',target=ALLY).candidate_id,
        choices={'reaction:typed.TAL_DEATH_DEATHLESS_GUARD':'first','choice:needle.death_guard_step':'first'})
    engine=reload(tmp_path,mid);a=engine.state.actors[aid]
    assert any(p['context']['reaction_source_id']=='choice:needle.death_guard_step' for p in prompts)
    assert a.position!=before and not a.reaction_available
    reductions=[e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id=='TAL_DEATH_DEATHLESS_GUARD']
    assert len(reductions)==1 and reductions[0].payload['protects']==ALLY
    assert engine.state.actors[ALLY].current_hp==engine.state.actors[ALLY].maximum_hp
    assert any(r.expression==f'{count}d8+{a.proficiency_bonus}' for r in engine.rolls)
    assert not any(e.source_definition_id.endswith('opportunity_attack') and e.event_type=='ATTACK_ROLLED' for e in engine.events)
    turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.guarding' for c in engine.state.actors[aid].conditions.values())


@pytest.mark.parametrize('material,maximum',[('wood',True),('cloth',True),('stone',False)])
@pytest.mark.parametrize('cl,count',[(1,1),(11,3),(17,4)])
def test_rotting_object_attack_choice_and_reload(tmp_path,material,maximum,cl,count):
    def transform(bundles):
        preparation({'object_material':material})(bundles)
        for a in bundles[0]['action_catalog']:
            typed=a.get('parameters',{}).get('typed',{})
            if typed.get('source')=='TAL_DEATH_ROTTING_GRASP':typed['numbers']['attack_bonus']=100
        bundles[0].pop('bundle_sha256',None);bundles[0]['bundle_sha256']=canonical_sha256(bundles[0])
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_ROTTING_GRASP'],cl=cl,bundle_transform=transform)
    direct(combat,mid,'Set servant scenario')
    engine=reload(tmp_path,mid)
    c=candidate(combat,mid,'Rotting Grasp',target='object:death-second-decay')
    assert c.metadata['object_target']
    prompts=settle(table,mid,c.candidate_id,choices={'choice:needle.rotting_object_damage':['maximum']})
    engine=reload(tmp_path,mid)
    roll=next(r for r in reversed(engine.rolls) if r.reason.startswith('ATTACK:') and r.actor_id==OWNER)
    critical=roll.natural_result==20
    damage=500-engine.state.objects['object:death-second-decay'].current_hp
    if maximum:
        assert any(p['context']['reaction_source_id']=='choice:needle.rotting_object_damage' for p in prompts)
        assert damage==count*8*(2 if critical else 1)
    else:
        assert not prompts
        rolled=next(r for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and r.actor_id==OWNER)
        assert damage==rolled.total
    assert engine.state.actors[OWNER].resources['resource:core.qi']==99
    assert not engine.state.actors[OWNER].action_available


@pytest.mark.parametrize('bad',[{'attended':True},{'magical':True}])
def test_rotting_rejects_illegal_object(tmp_path,bad):
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_ROTTING_GRASP'],bundle_transform=preparation({'object_material':'wood',**bad}))
    direct(combat,mid,'Set servant scenario')
    engine=reload(tmp_path,mid)
    assert not any(c.target_ids==('object:death-second-decay',) and 'Rotting Grasp' in c.display_name for c in engine.legal_candidates())


@pytest.mark.parametrize('protected,attacker',[(ALLY,FOE),(FOE,ALLY)])
def test_guard_ai_protects_allies_with_enemies_also_in_range(tmp_path,protected,attacker):
    def transform(bundles):
        preparation({})(bundles)
        sealed_native_attack(bundles[1 if attacker==ALLY else 2],'Mixed-side attack',count=1,sides=2,modifier=0,attack_bonus=100)
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_CORPSE_SERVANT','TAL_DEATH_DEATHLESS_GUARD'],cl=11,ask=False,
        owner_plan={'counts':{'corpse_servant':1,'lesser_corpse_servant':0}},bundle_transform=transform,
        foe_position={'x':3,'y':5},ally_position={'x':2,'y':6})
    settle(table,mid,candidate(combat,mid,'Command Death servants').candidate_id)
    engine=reload(tmp_path,mid);aid=servant(engine,'corpse_servant').entity_id
    turn(table,mid,aid);direct(combat,mid,'Guard')
    engine=reload(tmp_path,mid);a=engine.state.actors[aid]
    assert all(engine._distance_actor_to_actor(a,engine.state.actors[target])<=5 for target in (ALLY,FOE))
    turn(table,mid,attacker)
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    before=reload(tmp_path,mid).state.actors[protected].current_hp
    settle(table,mid,candidate(combat,mid,'Mixed-side attack',target=protected).candidate_id)
    engine=reload(tmp_path,mid)
    reductions=[e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id=='TAL_DEATH_DEATHLESS_GUARD']
    if protected==ALLY:
        assert len(reductions)==1 and reductions[0].payload['protects']==ALLY
        assert engine.state.actors[ALLY].current_hp==before
    else:
        assert not reductions and engine.state.actors[FOE].current_hp<before


@pytest.mark.parametrize('denied', [False, True])
def test_formation_sickened_recovery_uses_normal_healing(tmp_path,denied):
    def transform(bundles):
        preparation({'hp':50,'corpse':'corpse','sickened':denied})(bundles)
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_GRAVE_FORMATION'],cl=15,
        owner_plan={'counts':{'grave_formation':1,'lesser_corpse_servant':0}},bundle_transform=transform)
    direct(combat,mid,'Set servant scenario')
    settle(table,mid,candidate(combat,mid,'Command Death servants').candidate_id)
    aid=servant(reload(tmp_path,mid),'grave_formation').entity_id
    turn(table,mid,aid)
    assert reload(tmp_path,mid).state.actors[aid].current_hp==(52 if denied else 54)


@pytest.mark.parametrize('hp,sickened,healing_minus,expected',[
    (73,True,0,75), (74,True,0,75),
    (73,False,1,75), (74,False,1,75),
])
def test_formation_recovery_reductions_precede_half_hp_ceiling(
        tmp_path,hp,sickened,healing_minus,expected):
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_GRAVE_FORMATION'],cl=15,
        owner_plan={'counts':{'grave_formation':1,'lesser_corpse_servant':0}},
        bundle_transform=preparation({'hp':hp,'corpse':'corpse','sickened':sickened,
                                      'healing_minus':healing_minus}))
    direct(combat,mid,'Set servant scenario')
    settle(table,mid,candidate(combat,mid,'Command Death servants').candidate_id)
    aid=servant(reload(tmp_path,mid),'grave_formation').entity_id
    turn(table,mid,aid)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[aid].current_hp==expected
    healing=[e for e in engine.events if e.event_type=='HEALING_APPLIED'
             and e.target_ids==(aid,)]
    assert healing and healing[-1].payload.get('after')-healing[-1].payload.get('before') == expected-hp


@pytest.mark.parametrize('size',['small','medium'])
def test_corpse_servant_complete_statistics_attack_and_grave_body(tmp_path,size):
    def transform(bundles):
        preparation({})(bundles)
        sid='action:test.exhaust_servant'
        bundles[2]['action_catalog'].append({'source_definition_id':sid,'display_name':'Exhaust servant',
            'owner_id':FOE,'economy':'ACTION','resolution_kind':'TYPED','target_kind':'HOSTILE_ENTITY','range_ft':60,
            'parameters':{'typed':{'effects':[{'type':'save','ability':'con','on_fail':[{'type':'condition','condition':'exhaustion'}],
                'on_success':[]}],'numbers':{'save_dc':1},'duration':{'kind':'instant'},'riders':[]}}})
        bundles[2]['actor_template']['action_ids'].append(sid)
        for bundle in bundles:
            bundle.pop('bundle_sha256',None);bundle['bundle_sha256']=canonical_sha256(bundle)
    combat,table,mid=fixture(tmp_path,['TAL_DEATH_CORPSE_SERVANT'],cl=11,
        owner_plan={'counts':{'corpse_servant':1,'lesser_corpse_servant':0},'death_sizes':{'corpse_servant':size}},
        bundle_transform=transform,foe_position={'x':3,'y':5})
    settle(table,mid,candidate(combat,mid,'Command Death servants').candidate_id)
    engine=reload(tmp_path,mid);a=servant(engine,'corpse_servant');aid=a.entity_id
    assert a.size_category==size.title() and list(a.creature_types)==['Undead']
    assert a.maximum_hp==57 and a.armor_class==16 and a.speed_ft==30
    from combat import senses
    assert senses.of(engine,a)['darkvision']['range_ft']==60
    turn(table,mid,aid)
    c=candidate(combat,mid,'Grave Strike',target=FOE)
    action=combat._load_session(mid).engine.action_catalog[c.source_definition_id]
    assert action.parameters['typed']['weapon']['damage_types']==['NECROTIC','BLUDGEONING','SLASHING']
    settle(table,mid,c.candidate_id)
    reload(tmp_path,mid)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Exhaust servant',target=aid).candidate_id)
    engine=reload(tmp_path,mid)
    saved=next(r for r in reversed(engine.rolls) if r.actor_id==aid and r.reason.startswith('SAVE:'))
    assert saved.mode=='ADVANTAGE'
