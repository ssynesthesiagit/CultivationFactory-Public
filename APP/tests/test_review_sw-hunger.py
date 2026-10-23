"""Printed-text regressions for Hunger, Ice, and Illusion."""
import pytest
import copy
import json
from functools import lru_cache
from pathlib import Path

from combat import typed_executor as te, typed_reactions as tr, zones
from combat.ext.hunger_riders import mantle
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT=Path(__file__).resolve().parents[1]
AUTH=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
H,I,U,L='tianxia.talent.hunger.','TAL_ICE_','TAL_ILLUSION_','tianxia.talent.illusion.'

@lru_cache(maxsize=None)
def compiled(key,cl=20,dc=50,extras=(),pick=None):
    sphere=AUTH[key]['sphere_id']
    bases=[k for k,v in AUTH.items() if v.get('sphere_id')==sphere and v.get('kind')=='base_ability']
    return compile_character({**SHEET,
        'equipment':[{'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.jian','quantity':1}]}}],
        'identity':{**SHEET['identity'],'cultivation_level':cl},
        'ability_scores_and_statistics':{**SHEET['ability_scores_and_statistics'],'technique_save_dc':dc,
            'technique_attack_bonus':40,'primary_resource':{'name':'Qi','maximum':100}},
        'spheres_and_talents':{'sphere_record_ids':[sphere],
            'learned_talent_record_ids':list(dict.fromkeys([*bases,key,*extras]))}},actor_id=ME,reaction_plan={"options":{key:pick}} if pick is not None else None)

def fight(key,cl=20,dc=50,extras=(),pick=None):
    b=copy.deepcopy(compiled(key,cl,dc,extras,pick));e=_engine(b)
    me,foe=e.state.actors[ME],e.state.actors[AN]
    me.maximum_hp=me.current_hp=foe.maximum_hp=foe.current_hp=2000
    foe.armor_class=-50
    me.resources['resource:core.martial_focus']=1
    return b,e,me,foe

def cast(e,name,at=None,target=None,contains=''):
    cs=[c for c in e.legal_candidates() if name in c.display_name and contains in c.display_name
        and (at is None or c.destination and (c.destination.x,c.destination.y)==at)
        and (target is None or target in c.target_ids)]
    assert cs,(name,contains,at,target)
    pos=e.state.actors[AN].position
    c=min(cs,key=lambda c:(len(c.display_name),0 if c.destination is None else abs(c.destination.x-pos.x)+abs(c.destination.y-pos.y)))
    e.execute_intent(ActionIntent(intent_id='review',decision_id=c.decision_id,candidate_id=c.candidate_id,
        state_version=c.state_version,actor_id=ME,target_ids=c.target_ids,destination=c.destination))

def ally(e,me):
    a=me.model_copy(deep=True);a.entity_id='review:ally';a.position=a.position.model_copy(update={'y':7})
    e.state.actors[a.entity_id]=a
    return a

def rolls(e,kind):return [r for r in e.rolls[2:] if r.reason.startswith(kind+':')]
def marked(a,name='Fracture Mark'):return te.bears_mark(a,ME,name)
def has(a,name):return any(c.condition_id.endswith('.'+name) for c in a.conditions.values())

def test_nine_beasts_burrowing_does_not_add_walking_speed():
    _,e,me,_=fight(H+'nine_beast_sovereign_course');me.resources['resource:named.satiety']=3
    cast(e,'Nine-Beast',contains='Burrowing Hunger')
    assert e._effective_speed(me)==me.speed_ft

@pytest.mark.parametrize('satiety',[0,1])
def test_three_course_requires_and_pays_satiety(satiety):
    # The printed line opens "When Digestive Mantle is active", so the Satiety gate is checked with the Mantle up
    # (AUTO14f1 added the Mantle requirement to the same button).
    _,e,me,_=fight(H+'three_course_battle_body');me.resources['resource:named.satiety']=3
    cast(e,'Digestive Mantle: Thick Hide')
    me.resources['resource:named.satiety']=satiety
    me.action_available=me.bonus_action_available=True
    offered=any('Three-Course' in c.display_name for c in e.legal_candidates())
    assert offered==bool(satiety)
    if satiety:
        cast(e,'Three-Course');assert me.resources['resource:named.satiety']==0

@pytest.mark.parametrize('satiety',[0,1])
def test_three_course_is_withheld_with_no_mantle_to_replace(satiety):
    """Three-Course Battle Body: "When Digestive Mantle is active ... replace your current basic Mantle benefit", so a
    character who holds the Satiety to pay but has no Mantle up is never offered it, and the Satiety is never charged
    for a use that cannot happen (AUTO14f1).  No Mantle is cast here: that is the point of the test, and the Satiety is
    banked first so the only thing withholding the button is the missing Mantle."""
    _,e,me,_=fight(H+'three_course_battle_body');me.resources['resource:named.satiety']=satiety
    me.action_available=me.bonus_action_available=True
    assert not mantle(me),'this test is only about a character with no Mantle up'
    assert not any('Three-Course' in c.display_name for c in e.legal_candidates())
    assert me.resources['resource:named.satiety']==satiety,'no Satiety may be spent on a use that cannot happen'

@pytest.mark.parametrize('cp',[0,1])
def test_devour_venom_requires_qualifying_mantle_before_reaction(cp):
    _,e,me,_=fight(H+'devour_the_venom_keep_the_fang');me.resources['resource:core.qi']=cp
    e._typed_pending_damage_type='ACID'
    remaining=tr.on_damage(e,me,100,0,source_actor_id=AN)
    # The printed trigger first requires activating a Mantle with a qualifying meal.
    # Affordability and consent with that state are covered through services in test_a2_hunger.
    assert remaining == 100
    assert me.reaction_available and me.resources['resource:core.qi'] == cp

def test_shard_needle_marks_a_hit():
    _,e,_,foe=fight('ICE_BASE_SHARD_NEEDLE');cast(e,'Shard Needle')
    assert foe.current_hp<2000 and marked(foe)

@pytest.mark.parametrize('key,name',[
    (I+'BITTER_EDGE','Bitter Edge'),(I+'FROST_SHEATHED_GUARD','Frost-Sheathed'),
    (I+'LIVING_GLACIER_ADVANCE','Living Glacier'),(I+'RIME_MIRROR_SURFACE','Rime Mirror'),
    (U+'BORROWED_VOICE','Borrowed Voice'),(L+'sovereign_illusion_incarnation','Sovereign Illusion')])
def test_setups_wait_for_their_printed_triggers(key,name):
    _,e,me,foe=fight(key);before=me.movement_remaining_ft;cast(e,name)
    assert me.movement_remaining_ft==before and me.current_hp==foe.current_hp==2000
    assert not marked(me) and not marked(foe) and not has(me,'deafened') and not has(foe,'deafened')
    assert not rolls(e,'SAVE')

def test_crystal_step_charges_one_cp_once():
    _,e,me,_=fight(I+'CRYSTAL_STEP')
    assert not any('Crystal Step' in c.display_name for c in e.legal_candidates()), 'requires a lattice origin'
    cast(e,'Crystallize Path')
    before=me.resources['resource:core.qi']
    cast(e,'Crystal Step')
    assert me.resources['resource:core.qi']==before-1
    assert me.resources['resource:core.qi']==99

@pytest.mark.parametrize('cl,dice',[(1,1),(20,4)])
@pytest.mark.parametrize('dc',[1,50])
def test_weather_waits_until_hostile_start_and_deals_cold_shard_damage(cl,dice,dc):
    _,e,me,foe=fight(I+'CRYSTAL_WEATHER_SCRIPT',cl=cl,dc=dc);cast(e,'Crystal Weather')
    assert me.resources['resource:core.qi']==96 and foe.current_hp==2000 and not marked(foe)
    e.end_turn()
    assert rolls(e,'SAVE') and marked(foe)==(dc==50)
    if dc==50:
        assert rolls(e,'DAMAGE')[0].expression==f'{dice}d8+0'
        assert foe.current_hp==2000-rolls(e,'DAMAGE')[0].total
    else:assert foe.current_hp==2000

@pytest.mark.parametrize('distance,forced,expected',[(5,False,False),(10,False,True),(10,True,False)])
def test_ice_domain_marks_at_ten_voluntary_feet_and_moves_with_caster(distance,forced,expected):
    _,e,me,foe=fight(I+'ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER');cast(e,'Ice Domain')
    assert not marked(foe)
    start=foe.position;foe.position=start.model_copy(update={'x':start.x+distance//5})
    zones.on_moved(e,foe,start,foe.position,forced=forced)
    assert marked(foe)==expected
    old=me.position;me.position=old.model_copy(update={'y':old.y+1});zones.on_moved(e,me,old,me.position)
    assert zones.typed_zones(e)[0].center==me.position

@pytest.mark.parametrize('cl,dice',[(1,1),(20,4)])
@pytest.mark.parametrize('dc',[1,50])
def test_shatter_bloom_uses_shard_dice_plus_key_and_success_halves(cl,dice,dc):
    _,e,me,foe=fight(I+'SHATTER_BLOOM',cl=cl,dc=dc)
    from combat.ext import ice_fracture
    ice_fracture._lattice_at(e,me,foe,'test')  # rider lane 9: Shatter Bloom shatters your Lattice Spaces (combat/ext/ice_fracture.py)
    me.position=foe.position.model_copy(update={'y':foe.position.y+4})  # 20 feet off: "each creature" near a shattered space includes its user
    cast(e,'Shatter Bloom')
    damage=rolls(e,'DAMAGE')[0]
    assert damage.expression==f'{dice}d8+2'
    assert foe.current_hp==2000-(damage.total if dc==50 else damage.total//2)

def test_single_crystal_cost_use_limit_and_future_effects():
    _,e,me,foe=fight(I+'THE_WORLD_BECOMES_A_SINGLE_CRYSTAL');cast(e,'World Becomes')
    assert me.resources['resource:core.qi']==90 and not marked(foe) and not has(foe,'prone')
    e.end_turn();e.end_turn()
    assert not any('World Becomes' in c.display_name for c in e.legal_candidates())

def test_thousand_facet_prison_repeats_its_save_without_premature_mark():
    _,e,_,foe=fight(I+'THOUSAND_FACET_PRISON');cast(e,'Thousand-Facet')
    assert has(foe,'restrained') and not marked(foe)
    before=len(rolls(e,'SAVE'));e.end_turn();e.end_turn()
    assert len(rolls(e,'SAVE'))>before

@pytest.mark.parametrize('dc',[1,50])
def test_world_fang_damage_and_end_of_caster_next_turn(dc):
    _,e,me,foe=fight(I+'WORLD_FANG_ICEFALL',dc=dc);cast(e,'World-Fang')
    r=rolls(e,'DAMAGE')[0];assert r.expression=='8d8+0'
    assert foe.current_hp==2000-(r.total if dc==50 else r.total//2)
    assert zones.typed_zones(e)
    e.end_turn();e.end_turn();assert zones.typed_zones(e)
    e.end_turn();assert not zones.typed_zones(e)

def test_heaven_sealing_does_not_fire_after_the_technique_has_finished():
    _,e,me,foe=fight(I+'HEAVEN_SEALING_ICE_SCRIPT',pick=2);before=foe.position
    e._apply_condition(foe,te.mark_condition_id('Fracture Mark',ME),'test',ME,expires_on='UNTIL_REMOVED')
    tr.on_creature_event(e,foe,'technique_used')
    assert me.reaction_available and foe.position==before

@pytest.mark.parametrize('key,name,cost,conc',[
    (U+'COURT_FALSE_PREMISES','Court of False',5,True),
    (L+'greater_invisibility','Greater Invisibility',4,True),
    (L+'sovereign_illusion_incarnation','Sovereign Illusion',6,False),
    (L+'mirage','Mirage',6,False),
    (L+'world_of_false_premises','World of False',8,True)])
def test_illusion_activation_cost_and_concentration(key,name,cost,conc):
    _,e,me,_=fight(key);cast(e,name)
    assert me.resources['resource:core.qi']==100-cost
    assert bool(me.concentration)==conc

@pytest.mark.parametrize('cl,size',[(1,10),(5,15),(11,20),(17,25)])
def test_figment_scales_and_does_not_demand_an_instant_save(cl,size):
    _,e,_,_=fight(U+'CREATE_FIGMENT',cl=cl);cast(e,'Create Figment')
    # The figment kit (combat/ext/figment.py, sys placed-effects) places the cube square by square; its size is the printed one.
    assert not rolls(e,'SAVE') and len(zones.typed_zones(e)[0].affected_cells)==(size//5)**2

@pytest.mark.parametrize('blind',[False,True])
def test_false_obstruction_is_light_and_only_penalizes_incoming_sight_attacks(blind):
    from combat import senses
    _,e,me,foe=fight(U+'FALSE_OBSTRUCTION',extras=(U+'PHANTOM_STING',));cast(e,'False Obstruction',at=(4,6))
    start=me.position;me.position=start.model_copy(update={'x':1});zones.on_moved(e,me,start,me.position)
    assert zones.typed_zones(e)[0].trigger_profile['obscured']=='light'
    assert not has(foe,'deafened') and not any(m.target_field=='attack_mode' for m in foe.modifiers.values())
    if blind:e._apply_condition(me,senses.SENSE,'test',ME,expires_on='UNTIL_REMOVED',data={'sense':'blindsight','range_ft':60})
    action=next(a for a in e.action_catalog.values() if a.owner_id==ME and 'Phantom Sting'==a.display_name)
    typed=action.parameters['typed'];ctx=te.Context(e,me,action,None,typed,[foe],foe,{})
    te.run_effects(ctx,typed['effects'])
    attack=rolls(e,'ATTACK')[0]
    assert attack.mode==('NORMAL' if blind else 'DISADVANTAGE')
    start=foe.position;foe.position=start.model_copy(update={'x':20});zones.on_moved(e,foe,start,foe.position)
    assert not any(r.get('attacked_with_if_sight') for r in te.condition_rules(foe))

def test_obscuring_glamer_has_no_free_invisibility_or_hearing_augment():
    _,e,_,foe=fight(U+'OBSCURING_GLAMER');cast(e,'Obscuring Glamer')
    assert not has(foe,'invisible') and not has(foe,'deafened')
    assert not any(m.target_field in ('check_mode','stealth_mode') for m in foe.modifiers.values())

@pytest.mark.parametrize('dc',[1,50])
def test_phantom_sting_omits_flat_cl_and_marks_only_failed_save(dc):
    _,e,me,foe=fight(U+'PHANTOM_STING',dc=dc);cast(e,'Phantom Sting')
    r=rolls(e,'DAMAGE')[0];assert r.expression=='4d8+0' and foe.current_hp==2000-r.total
    assert marked(foe,'False Premise')==(dc==50)
    e.end_turn();e.end_turn();assert not marked(foe,'False Premise')

@pytest.mark.parametrize('dc',[1,50])
def test_illusory_army_waits_for_enemy_start_and_marks_failed_save(dc):
    _,e,me,foe=fight(L+'illusory_army',dc=dc);before=me.movement_remaining_ft;cast(e,'Illusory Army')
    assert me.movement_remaining_ft==before and not rolls(e,'SAVE') and not marked(foe,'False Premise')
    e.end_turn();assert marked(foe,'False Premise')==(dc==50)
    assert len(rolls(e,'SAVE'))==1

@pytest.mark.parametrize('dc',[1,50])
def test_impossible_premise_failure_mark_or_success_immunity(dc):
    _,e,me,foe=fight(L+'impossible_premise',dc=dc);cast(e,'Impossible Premise')
    assert marked(foe,'False Premise')==(dc==50)
    assert marked(foe,'Impossible Premise immunity')==(dc==1)
    if dc==1:
        me.action_available=True;foe.saving_throws['INT']=-100;cast(e,'Impossible Premise')
        assert not marked(foe,'False Premise') and marked(foe,'Impossible Premise immunity')
    e.end_turn();e.end_turn();assert not marked(foe,'False Premise')

@pytest.mark.parametrize('dc',[1,50])
def test_phantom_prison_has_one_initial_save_and_zero_speed_on_failure(dc):
    _,e,_,foe=fight(L+'phantom_prison',dc=dc);cast(e,'Phantom Prison')
    assert len(rolls(e,'SAVE'))==1 and e._effective_speed(foe)==(0 if dc==50 else foe.speed_ft)
    assert marked(foe,'False Premise')==(dc==50)
    e.end_turn();e.end_turn();assert e._effective_speed(foe)==foe.speed_ft
