"""Printed-text regressions for Force, Formations, and Glass."""
import pytest
import copy
import json
from functools import lru_cache
from pathlib import Path

from combat import typed_executor as te, typed_reactions as tr, zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT=Path(__file__).resolve().parents[1]
AUTH=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
F,G='TAL_FORCE_','TAL_GLASS_'

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

def rolls(e,kind):return [r for r in e.rolls if r.reason.startswith(kind+':')]
def marked(a):return te.bears_mark(a,ME,'Faultline Mark')
def mark(e,foe):e._apply_condition(foe,te.mark_condition_id('Faultline Mark',ME),'test',ME,expires_on='UNTIL_REMOVED')
def has(a,slug):return any(c.condition_id=='condition:typed.'+slug for c in a.conditions.values())
def mods(a,field):return [m for m in a.modifiers.values() if m.target_field==field]

@pytest.mark.parametrize('slug,name', [('CASCADING_COLLISION','Cascading Collision'),('HAMMERFALL','Hammerfall')])
def test_impact_does_not_gain_collision_damage_on_an_open_path(slug,name):
    _,e,me,foe=fight(F+slug);cast(e,name)
    assert foe.current_hp==2000-sum(r.total for r in rolls(e,'DAMAGE')[:1])
    assert len(rolls(e,'DAMAGE'))==1
    if slug=='CASCADING_COLLISION':assert not has(foe,'prone') and not rolls(e,'SAVE')

@pytest.mark.parametrize('slug,name', [('COMPRESSION_FIELD','Compression Field'),('INVISIBLE_MOUNTAIN','Invisible Mountain'),('COURT_OF_THE_ANSWERING_WORLD','Court of the Answering World')])
@pytest.mark.parametrize('dc',[1,50])
def test_force_fields_wait_until_the_hostiles_turn(slug,name,dc):
    _,e,me,foe=fight(F+slug,dc=dc);before=me.movement_remaining_ft
    cast(e,name)
    assert foe.current_hp==2000 and not rolls(e,'SAVE') and not foe.conditions
    assert me.movement_remaining_ft==before
    e.end_turn()
    assert rolls(e,'SAVE')
    if slug=='COMPRESSION_FIELD':
        assert not has(foe,'prone')
        assert e._effective_speed(foe)==foe.speed_ft-(10 if dc==50 else 0)
    if slug=='INVISIBLE_MOUNTAIN':
        damage=rolls(e,'DAMAGE')[0].total
        assert foe.current_hp==2000-(damage if dc==50 else damage//2)
        assert has(foe,'restrained')==(dc==50)
        if dc==1:assert e._effective_speed(foe)==foe.speed_ft-10
    if slug=='COURT_OF_THE_ANSWERING_WORLD':
        assert not has(foe,'check_mode')
        assert has(foe,'prone')==(dc==50)
        assert not mods(foe,'save_mode')

@pytest.mark.parametrize('cl,count',[(1,1),(11,2),(17,3),(20,3)])
def test_counterpressure_damage_reduction_scales(cl,count):
    _,e,me,foe=fight(F+'COUNTERPRESSURE',cl=cl)
    e._typed_pending_damage_type='SLASHING'
    remaining=tr.on_damage(e,me,100,0,source_actor_id=AN)
    r=rolls(e,'GENERIC_AMOUNT')[0]
    assert r.expression==f'{count}d8+2' and remaining==100-r.total
    assert me.resources['resource:core.qi']==99

@pytest.mark.parametrize('cl,feet',[(1,10),(5,15),(11,20),(17,30)])
def test_counterpressure_movement_refusal_scales(cl,feet):
    _,e,me,foe=fight(F+'COUNTERPRESSURE',cl=cl,pick=1)
    assert tr.on_forced_movement(e,me,foe,40)==40-feet

def test_force_mantle_also_protects_against_prone():
    _,e,me,_=fight(F+'FORCE_MANTLE');cast(e,'Force Mantle')
    assert any('prone' in r.get('save_against',{}).get('against',[]) for r in te.condition_rules(me))
    assert sum(m.value for m in mods(me,'armor_class'))==2

@pytest.mark.parametrize('slug,name,length,width',[
    ('GROUND_ANSWERING_PALM','Ground-Answering Palm',30,5),('MERIDIAN_OF_IMPACT','Meridian of Impact',60,10)])
@pytest.mark.parametrize('dc',[1,50])
def test_force_lines_reach_beyond_melee_and_respect_their_width(slug,name,length,width,dc):
    b,e,me,foe=fight(F+slug,dc=dc);foe.position=foe.position.model_copy(update={'x':8})
    off=foe.model_copy(deep=True);off.entity_id='review:outside';off.position=off.position.model_copy(update={'y':9})
    e.state.actors[off.entity_id]=off
    cast(e,name,at=(8,6))
    assert foe.current_hp<2000 and off.current_hp==2000
    assert has(foe,'prone')==(dc==50)
    action=next(a for a in e.action_catalog.values() if a.owner_id==ME and a.display_name==name)
    assert action.parameters['typed']['area']['width_ft']==width
    assert action.range_ft==length

def test_impact_reaches_a_target_thirty_feet_from_self():
    _,e,me,foe=fight(F+'IMPACT');foe.position=foe.position.model_copy(update={'x':9})
    cast(e,'Impact',target=AN)
    assert foe.current_hp<2000

@pytest.mark.parametrize('key', [F+'MOMENTARY_RAMPART',F+'UNANSWERABLE_RAMPART','tianxia.talent.force.one_finger_holds_back_heaven'])
def test_reaction_barriers_do_not_grant_creature_ac_temp_hp_or_immunity(key):
    _,e,me,foe=fight(key);a=ally(e,me)
    tr.on_attacked(e,foe,a,{'attack_kind':'weapon','range_ft':30})
    assert not me.reaction_available
    for actor in [me,a,foe]:
        assert actor.temporary_hp==0
        assert not mods(actor,'armor_class') and not mods(actor,'damage_immunity')

@pytest.mark.parametrize('key,name',[(F+'RAMPART_OF_STILL_AIR','Rampart of Still Air'),(G+'GLASS_COFFIN_WITHOUT_DEATH','Glass Coffin Without Death'),(G+'RAISED_PANE_SCRIPTURE','Raised Pane Scripture')])
def test_object_stat_blocks_do_not_become_creature_defenses(key,name):
    _,e,me,foe=fight(key);cast(e,name)
    for actor in [me,foe]:
        assert not mods(actor,'armor_class') and not mods(actor,'damage_immunity')

def test_pressure_step_grants_ten_feet_of_oa_free_movement():
    _,e,me,_=fight(F+'PRESSURE_STEP');before=me.movement_remaining_ft;cast(e,'Pressure Step')
    assert me.movement_remaining_ft==before+10 and me.turn_flags.get('oa_free_ft')==10

def test_world_bracing_incarnation_does_not_hit_or_shield_the_caster_with_barrier_hp():
    _,e,me,foe=fight(F+'WORLD_BRACING_INCARNATION');cast(e,'World-Bracing Incarnation')
    assert me.current_hp==2000 and me.temporary_hp==0 and foe.current_hp==2000
    assert sum(m.value for m in mods(me,'armor_class'))==3
    assert {m.value for m in mods(me,'damage_resistance')}=={'BLUDGEONING','PIERCING','SLASHING','FORCE'}

@pytest.mark.parametrize('slug,event',[('BREAK_THE_PROUD_WEAPON','hit'),('FLAW_WITHIN_THE_GOLDEN_TECHNIQUE','technique_used')])
def test_glass_reactions_consume_their_faultline_mark(slug,event):
    _,e,me,foe=fight(G+slug);a=ally(e,me);mark(e,foe)
    if event=='hit':tr.on_attack_hit(e,foe,a,{'attack_kind':'weapon','range_ft':5},100,10,100)
    else:tr.on_creature_event(e,foe,event)
    assert not me.reaction_available and not marked(foe)

@pytest.mark.parametrize('slug,name',[
    ('CONTACT_PANE','Contact Pane'),('GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS','Glass Domain: Court of Visible Faults'),
    ('GLASS_ROAD','Glass Road'),('INCARNATION_OF_THE_TRANSPARENT_FAULT','Incarnation of the Transparent Fault'),
    ('LENS_OF_THE_HONEST_CRACK','Lens of the Honest Crack'),('THOUSAND_PANE_PALACE','Thousand-Pane Palace')])
def test_glass_setups_do_not_fire_their_later_mark_or_movement_triggers_at_cast(slug,name):
    _,e,me,foe=fight(G+slug);before=me.movement_remaining_ft;cast(e,name)
    assert not marked(foe) and not marked(me)
    assert me.movement_remaining_ft==before
    assert me.temporary_hp==0 and foe.temporary_hp==0 and me.current_hp==foe.current_hp==2000

def test_glass_bone_guard_does_not_grant_unprinted_resistance():
    _,e,me,_=fight(G+'GLASS_BONE_GUARD');cast(e,'Glass-Bone Guard',contains='Reduce Damage')
    assert not mods(me,'damage_resistance')

def test_lens_of_stored_pressure_cannot_add_damage_without_stored_pressure():
    _,e,_,foe=fight(G+'LENS_OF_STORED_PRESSURE');cast(e,'Glass Shard')
    assert len(rolls(e,'DAMAGE'))==1 and foe.current_hp==2000-rolls(e,'DAMAGE')[0].total

def test_mirror_bright_witness_does_not_deny_reactions_when_attack_still_hits():
    _,e,me,foe=fight(G+'MIRROR_BRIGHT_WITNESS');a=ally(e,me);mark(e,foe)
    tr.on_attack_hit(e,foe,a,{'attack_kind':'weapon','range_ft':5},100,10,100)
    assert not me.reaction_available and foe.reaction_available and not has(foe,'reaction_denied')

def test_polished_warning_does_not_place_a_mark_before_attack_outcome():
    _,e,me,foe=fight(G+'POLISHED_WARNING')
    # rider lane 9: "If you do not have a legal Glass Surface, you cannot use this talent" (combat/ext/glass_refraction.py)
    e._apply_condition(me,'condition:typed.glass_tempered','test',me.entity_id,expires_on='UNTIL_REMOVED')
    tr.on_attacked(e,foe,me,{'attack_kind':'weapon','range_ft':30})
    assert not me.reaction_available and not marked(foe)
    assert sum(m.value for m in mods(me,'armor_class'))==2
