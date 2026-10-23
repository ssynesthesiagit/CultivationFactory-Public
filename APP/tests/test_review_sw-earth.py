"""Printed-text regressions for Earth, Equipment, and Fate."""
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
E,Q,F='TAL_EARTH_','tianxia.talent.equipment.','TAL_FATE_'

@lru_cache(maxsize=None)
def compiled(key,cl=20,dc=50,extras=()):
    sphere=AUTH[key]['sphere_id']
    bases=[k for k,v in AUTH.items() if v.get('sphere_id')==sphere and v.get('kind')=='base_ability']
    return compile_character({**SHEET,
        'equipment':[{'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.jian','quantity':1}]}}],
        'identity':{**SHEET['identity'],'cultivation_level':cl},
        'ability_scores_and_statistics':{**SHEET['ability_scores_and_statistics'],'technique_save_dc':dc,
            'technique_attack_bonus':40,'primary_resource':{'name':'Qi','maximum':100}},
        'spheres_and_talents':{'sphere_record_ids':[sphere],
            'learned_talent_record_ids':list(dict.fromkeys([*bases,key,*extras]))}},actor_id=ME)

def fight(key,cl=20,dc=50,extras=()):
    b=copy.deepcopy(compiled(key,cl,dc,extras));e=_engine(b)
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
def marked(a):return te.bears_mark(a,ME,'Burden Mark')
def has(a,slug):return any(c.condition_id=='condition:typed.'+slug for c in a.conditions.values())


def test_foundation_waits_for_exactly_ten_feet_of_willing_movement():
    _,e,_,foe=fight('EARTH_BASE_SET_FOUNDATION');cast(e,'Set Foundation')
    assert not marked(foe)
    start=foe.position.model_copy();end=start.model_copy(update={'x':start.x+2})
    foe.position=end;zones.on_moved(e,foe,start,end,forced=True);assert not marked(foe)
    foe.position=start;foe.position=end;zones.on_moved(e,foe,start,end)
    assert marked(foe)
    e.end_turn();e.end_turn();assert marked(foe)


def test_deep_root_never_knocks_a_target_prone_or_spends_movement():
    _,e,me,foe=fight(E+'DEEP_ROOT_STANCE');before=me.movement_remaining_ft
    cast(e,'Deep Root Stance')
    assert not has(foe,'prone') and not has(me,'prone')
    assert me.movement_remaining_ft==before


@pytest.mark.parametrize('slug,name',[
    ('DOORSTONE_SEAL','Doorstone Seal'),('SEAL_THE_FAULT_BELOW','Seal the Fault Below'),
    ('RAISE_THE_LOAD_BEARING_WALL','Raise the Load-Bearing Wall')])
def test_object_properties_do_not_debuff_creatures_or_protect_the_caster(slug,name):
    _,e,me,foe=fight(E+slug);cast(e,name)
    assert not rolls(e,'SAVE')
    assert not has(foe,'check_mode')
    assert not any(m.target_field=='damage_immunity' for m in me.modifiers.values())


@pytest.mark.parametrize('already_marked',[False,True])
def test_earthbind_line_checks_existing_marks_only_when_crossed(already_marked):
    _,e,me,foe=fight(E+'EARTHBIND_LINE')
    if already_marked:e._apply_condition(foe,te.mark_condition_id('Burden Mark',ME),'test',ME,expires_on='UNTIL_REMOVED')
    cast(e,'Earthbind Line',at=(5,6));assert not rolls(e,'SAVE') and not has(foe,'prone')
    start=foe.position.model_copy(update={'x':5,'y':5});end=start.model_copy(update={'y':7})
    foe.position=end;zones.on_moved(e,foe,start,end)
    assert marked(foe) and has(foe,'prone')==already_marked
    assert bool(rolls(e,'SAVE'))==already_marked


def test_earth_carries_holds_one_hp_and_obeys_cost_and_rest_limit():
    _,e,me,foe=fight(E+'EARTH_CARRIES_THE_FALLEN');a=ally(e,me);a.current_hp=10
    remaining=tr.on_damage(e,a,25,0,source_actor_id=AN)
    assert remaining==9 and a.current_hp==10 and me.resources['resource:core.qi']==95
    me.reaction_available=True
    assert tr.on_damage(e,a,25,0,source_actor_id=AN)==25


def test_earth_carries_cannot_fire_without_five_cp():
    _,e,me,_=fight(E+'EARTH_CARRIES_THE_FALLEN');a=ally(e,me);a.current_hp=10
    me.resources['resource:core.qi']=4
    assert tr.on_damage(e,a,25,0,source_actor_id=AN)==25
    assert me.reaction_available and me.resources['resource:core.qi']==4


def test_ox_bearing_does_not_grant_following_movement_when_the_stance_starts():
    _,e,me,_=fight(E+'OX_BEARING_FOUNDATION',extras=(E+'DEEP_ROOT_STANCE',));ally(e,me)
    cast(e,'Deep Root Stance')
    assert not [v for v in e.events if v.event_type=='MOVEMENT_GRANTED' and v.payload.get('distance_ft',0)>0]


@pytest.mark.parametrize('dc',[-50,50])
def test_wheel_rut_waits_for_entry_or_start_then_applies_the_failed_save_mark(dc):
    _,e,_,foe=fight(E+'SINK_THE_WHEEL_RUT',dc=dc);cast(e,'Sink the Wheel-Rut',at=(4,6))
    assert not rolls(e,'SAVE') and e._effective_speed(foe)==30
    e.end_turn()
    assert len(rolls(e,'SAVE'))==1 and e._effective_speed(foe)==(20 if dc>0 else 30)
    assert marked(foe)==(dc>0)


@pytest.mark.parametrize('dc,speed',[(-50,15),(50,0)])
def test_ten_thousand_steps_has_both_speed_branches(dc,speed):
    _,e,me,foe=fight(E+'THE_BURDEN_OF_TEN_THOUSAND_STEPS',dc=dc)
    tr.on_creature_event(e,foe,'moved',moved_ft=30)
    assert e._effective_speed(foe)==speed and me.resources['resource:core.qi']==95
    e.end_turn();assert e._effective_speed(foe)==speed
    e.end_turn();assert e._effective_speed(foe)==30


@pytest.mark.parametrize('choice,dc',[('Nothing Unmoored May Rule',-50),('The Burden Returns to the Violent',50)])
def test_world_principles_do_not_fire_their_future_punishments_on_cast(choice,dc):
    _,e,_,foe=fight(E+'THE_WORLD_RESTS_ON_MY_PALM',dc=dc)
    cast(e,'The World Rests on My Palm',contains=choice)
    assert not rolls(e,'SAVE') and foe.current_hp==2000 and not marked(foe)


@pytest.mark.parametrize('slug,name,slot',[
    ('TREMOR_COURT_HEARING','Tremor Court Hearing','action_available'),
    ('TREMOR_LISTENING_PALM','Tremor-Listening Palm','bonus_action_available')])
def test_tremor_sensing_spends_the_printed_encounter_action(slug,name,slot):
    _,e,me,foe=fight(E+slug);cast(e,name)
    assert not getattr(me,slot) and not has(foe,'prone')


def test_brigandine_reaction_is_limited_to_one_use_per_rest():
    _,e,me,foe=fight(Q+'brigandine_robe_scripture')
    assert tr.on_attack_hit(e,foe,me,{},14,10,14)==(18,False)
    e.end_turn();e.end_turn();me.reaction_available=True
    assert tr.on_attack_hit(e,foe,me,{},14,10,14)==(14,True)


@pytest.mark.parametrize('slug',['iron_rain_readiness','lamellar_flow'])
def test_equipment_reductions_need_their_printed_cp(slug):
    _,e,me,foe=fight(Q+slug);me.resources['resource:core.qi']=0
    e._typed_pending_damage_type='SLASHING'
    if slug=='iron_rain_readiness':tr.on_attack_hit(e,foe,me,{'attack_kind':'weapon','range_ft':30},14,10,14)
    assert tr.on_damage(e,me,100,0,source_actor_id=AN)==100
    assert me.reaction_available and me.resources['resource:core.qi']==0


def test_iron_rain_pays_exactly_two_cp_for_the_ranged_hit_reduction():
    _,e,me,foe=fight(Q+'iron_rain_readiness')
    tr.on_attack_hit(e,foe,me,{'attack_kind':'weapon','range_ft':30},14,10,14)
    remaining=tr.on_damage(e,me,100,0,source_actor_id=AN)
    [r]=rolls(e,'GENERIC_AMOUNT')
    assert remaining==100-r.total and me.resources['resource:core.qi']==98


@pytest.mark.parametrize('cl,count',[(5,1),(10,2),(15,3)])
def test_lamellar_reduction_scales_at_printed_realms(cl,count):
    _,e,me,_=fight(Q+'lamellar_flow',cl=cl)
    e._typed_pending_damage_type='SLASHING'
    remaining=tr.on_damage(e,me,100,0,source_actor_id=AN)
    rs=rolls(e,'GENERIC_AMOUNT')
    assert len(rs)==1 and rs[0].expression==f'{count}d8+4' and remaining==100-rs[0].total
    assert me.resources['resource:core.qi']==99


@pytest.mark.parametrize('slug,name,cost_cp',[
    ('mirror_bright_armor','Mirror-Bright Armor',1),('walking_fortress_scripture','Walking Fortress Scripture',4),
    ('circuit_armor','Circuit Armor',2)])
def test_active_equipment_pays_upfront_and_cannot_cast_when_short(slug,name,cost_cp):
    _,e,me,_=fight(Q+slug);cast(e,name)
    assert me.resources['resource:core.qi']==100-cost_cp
    _,e,me,_=fight(Q+slug);me.resources['resource:core.qi']=cost_cp-1
    assert not [c for c in e.legal_candidates() if name in c.display_name]


def test_mirror_bright_reaches_thirty_feet():
    _,e,me,foe=fight(Q+'mirror_bright_armor');foe.position=foe.position.model_copy(update={'x':9})
    cast(e,'Mirror-Bright Armor',target=AN);assert rolls(e,'SAVE')


def test_armor_answers_the_soul_has_an_action_without_teleporting_the_user():
    _,e,me,_=fight(Q+'armor_answers_the_soul');pos=me.position.model_copy();cast(e,'Armor Answers the Soul')
    assert not me.action_available and me.position==pos


@pytest.mark.parametrize('slug,name',[
    # rider lane 9: the four choices are the curser's at each misstep (combat/ext/fate_riders.py), no longer options chosen at the cast
    ('CHAIN_OF_MISFORTUNE','Chain of Misfortune'),
    ('EXORCISING_NAME','Exorcising Name'),('MARKED_BY_THE_LEDGER','Marked by the Ledger')])
def test_conditional_fate_damage_does_not_hit_at_cast(slug,name):
    _,e,_,foe=fight(F+slug);cast(e,name)
    assert foe.current_hp==2000 and not rolls(e,'DAMAGE')


def test_consequence_edict_does_not_damage_or_grant_blanket_psychic_immunity():
    _,e,_,foe=fight(F+'CONSEQUENCE_EDICT');cast(e,'Consequence Edict')
    assert foe.current_hp==2000
    assert not any(m.target_field=='damage_immunity' for m in foe.modifiers.values())


@pytest.mark.parametrize('dc,speed',[(50,20),(-50,25)])
def test_heavenly_ledger_waits_for_enemy_start(dc,speed):
    _,e,me,foe=fight(F+'COURT_OF_THE_HEAVENLY_LEDGER',dc=dc);ally(e,me)
    cast(e,'Court of the Heavenly Ledger');assert not rolls(e,'SAVE') and e._effective_speed(foe)==30
    e.end_turn();assert len(rolls(e,'SAVE'))==1 and e._effective_speed(foe)==speed
    assert not any(m.target_field=='armor_class' for m in foe.modifiers.values())


@pytest.mark.parametrize('dc',[-50,50])
@pytest.mark.parametrize('choice',['No Reactions','Reduce Speed'])
def test_fate_incarnation_has_flight_rider_and_later_save_gated_enemy_payloads(dc,choice):
    _,e,me,foe=fight(F+'FATE_SOVEREIGN_INCARNATION',dc=dc);a=ally(e,me)
    cast(e,'Fate-Sovereign Incarnation',contains=choice)
    assert e._effective_speed(me)==30 and not rolls(e,'SAVE')
    assert not a.modifiers and e._effective_speed(foe)==30 and not has(foe,'reaction_denied')
    e.end_turn();assert len(rolls(e,'SAVE'))==1
    assert has(foe,'reaction_denied')==(dc>0 and choice=='No Reactions')
    assert e._effective_speed(foe)==(25 if dc<0 else 20 if choice=='Reduce Speed' else 30)


def test_fate_incarnation_aura_follows_the_user():
    _,e,me,_=fight(F+'FATE_SOVEREIGN_INCARNATION');cast(e,'Fate-Sovereign Incarnation')
    old=me.position;me.position=old.model_copy(update={'x':15,'y':10});zones.on_moved(e,me,old,me.position)
    [z]=zones.typed_zones(e);assert z.center==me.position


def test_hallow_does_not_protect_enemies_and_save_benefit_waits_for_cl10():
    _,e,me,foe=fight(F+'HALLOW_MANDATE_EDICT',cl=5);a=ally(e,me);cast(e,'Hallow Mandate Edict')
    assert not any(m.target_field=='incoming_attack_mode' for m in foe.modifiers.values())
    assert not has(a,'save_against')


@pytest.mark.parametrize('cl,radius',[(5,15),(11,20),(17,25)])
@pytest.mark.parametrize('slug,name',[('MISFORTUNE_EDICT','Misfortune Edict'),('SERENDIPITY_EDICT','Serendipity Edict')])
def test_fate_edict_radius_progression(cl,radius,slug,name):
    _,e,_,_=fight(F+slug,cl=cl);cast(e,name)
    [z]=zones.typed_zones(e);assert z.trigger_profile['size_ft']==radius


def test_misfortune_save_waits_for_enemy_start():
    _,e,_,_=fight(F+'MISFORTUNE_EDICT');cast(e,'Misfortune Edict');assert not rolls(e,'SAVE')
    e.end_turn();assert len(rolls(e,'SAVE'))==1


@pytest.mark.parametrize('slug,name',[
    ('RED_THREAD_AUSPICE','Red Thread Auspice'),('UNDO_HARM_EDICT','Undo Harm Edict')])
def test_fate_temporary_hp_waits_for_release_or_damage(slug,name):
    _,e,me,foe=fight(F+slug);a=ally(e,me);cast(e,name)
    assert all(x.temporary_hp==0 for x in [me,foe,a])


def test_terraced_ascent_does_not_turn_terrain_height_into_free_movement():
    _,e,me,_=fight(E+'TERRACED_ASCENT');before=me.movement_remaining_ft
    cast(e,'Terraced Ascent');assert me.movement_remaining_ft==before
