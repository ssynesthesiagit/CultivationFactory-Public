"""Printed-text regressions for Thread, Trap, and Unmaking."""
import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import typed_executor as te, typed_reactions as tr, zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
T, U = 'tianxia.talent.thread.', 'TAL_UNMAKING_'


@lru_cache(maxsize=None)
def _compiled(key, cl=20, dc=50):
    sphere = AUTH[key]['sphere_id']
    bases = [k for k, v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    return compile_character({**SHEET,
        'equipment': [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'quantity': 1}]}}],
        'identity': {**SHEET['identity'], 'cultivation_level': cl},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'], 'technique_save_dc': dc,
            'technique_attack_bonus': 40, 'primary_resource': {'name': 'Qi', 'maximum': 100}},
        'spheres_and_talents': {'sphere_record_ids': [sphere],
            'learned_talent_record_ids': list(dict.fromkeys([*bases, key]))}}, actor_id=ME)


def _fight(key, cl=20, dc=50, foe_at=(4, 6)):
    b = copy.deepcopy(_compiled(key, cl, dc)); e = _engine(b, foe_at=foe_at)
    me, foe = e.state.actors[ME], e.state.actors[AN]
    me.maximum_hp = me.current_hp = foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    me.resources['resource:core.martial_focus'] = 1
    return b, e, me, foe


def _cast(e, name, at=None, target=None, contains=''):
    cs = [c for c in e.legal_candidates() if name in c.display_name and contains in c.display_name
        and (at is None or c.destination and (c.destination.x, c.destination.y) == at)
        and (target is None or target in c.target_ids)]
    assert cs, (name, contains, at, target)
    pos = e.state.actors[AN].position
    c = min(cs, key=lambda c: (len(c.display_name), 0 if c.destination is None else abs(c.destination.x-pos.x)+abs(c.destination.y-pos.y)))
    e.execute_intent(ActionIntent(intent_id='review', decision_id=c.decision_id, candidate_id=c.candidate_id,
        state_version=c.state_version, actor_id=ME, target_ids=c.target_ids, destination=c.destination))


def _cond(actor, slug):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.' + slug]


def _rolls(e, prefix='DAMAGE:'):
    return [r for r in e.rolls if r.reason.startswith(prefix)]


def _ally(e, me):
    ally = me.model_copy(deep=True); ally.entity_id = 'review:ally'
    ally.position = ally.position.model_copy(update={'y': 7}); e.state.actors[ally.entity_id] = ally
    return ally


@pytest.mark.parametrize('key,name', [
    ('TAL_THREAD_THREADED_WEAPON_ORBIT','Threaded Weapon Orbit'),
    (T+'weight_on_a_string','Weight on a String')])
def test_thread_preparation_cannot_make_an_attack(key,name):
    _,e,_,foe=_fight(key);_cast(e,name)
    assert not _rolls(e,'ATTACK:') and foe.current_hp==2000


@pytest.mark.parametrize('key,name', [
    ('TAL_THREAD_THREAD_THROUGH_THE_CROWD','Thread Through the Crowd'),
    (T+'silk_step','Silk Step'),
    ('TAL_TRAP_COURT_OF_THE_HIDDEN_NAIL','Court of the Hidden Nail')])
def test_no_extra_movement_without_the_printed_trigger(key,name):
    _,e,me,_=_fight(key);before=me.movement_remaining_ft;_cast(e,name)
    assert me.movement_remaining_ft==before
    if key==T+'silk_step':assert e._effective_speed(me)==me.speed_ft+10


def test_borrow_the_allys_arm_does_not_guarantee_a_missed_roll():
    # AUTO19 2026-10-04: the printed effect now runs (tests/test_auto19_thread.py drives it), so this guard moves to
    # the outcome it was really about: the printed +Proficiency Bonus is added to the ally's own d20 and never
    # replaces it with a success. before the lane the talent spent its 1 CP here and applied nothing at all.
    _,e,me,foe=_fight('TAL_THREAD_BORROW_THE_ALLY_S_ARM');ally=_ally(e,me)
    e._apply_condition(ally,te.mark_condition_id('Thread Line',ME),'test',ME,expires_on='UNTIL_REMOVED')
    tr.after_d20(e,ally,'attack',success=False,natural=2,other=foe,melee=True)
    assert me.resources['resource:core.qi']==100  # after_d20 alone answers no roll: the bonus rides the d20
    assert getattr(e,'_typed_roll_outcome',{}).get(ally.entity_id)!='success'
    spec={'range_ft':5,'resolved_target_id':ME,'declaration_done':True}  # the foe's AC is -50 here, so aim at a real one
    with e.d20_scope({'kind':'attack','actor_id':ally.entity_id,'target_id':ME,'spec':spec,
                      'source_id':'test:attack','source_actor_id':ally.entity_id,'attack_index':1}):
        roll=e.roller.d20(modifier=-20,actor_id=ally.entity_id,reason='ATTACK:test:attack:1')  # a miss
    rewritten=[x for x in e.events if x.event_type=='D20_REWRITTEN']
    assert rewritten and rewritten[-1].payload['original']['total']==roll.total-me.proficiency_bonus
    # AUTO19f1 2026-10-05: the printed bonus is added to the ally's own roll, so assert the outcome it is really
    # about -- the corrected roll is still a miss against the target's Armor Class -- instead of an unrelated
    # outcome flag left over from after_d20.
    assert roll.total+me.proficiency_bonus < e.state.actors[ME].armor_class
    assert getattr(e,'_typed_roll_outcome',{}).get(ally.entity_id)!='success'


def test_meridian_snare_reaches_qi_thread_range():
    _,e,_,foe=_fight('TAL_THREAD_MERIDIAN_SNARE',foe_at=(9,6))
    _cast(e,'Meridian Snare: Leg Line');assert e._effective_speed(foe)==foe.speed_ft-15


def test_meridian_snare_lasts_through_casters_next_turn():
    _,e,me,foe=_fight('TAL_THREAD_MERIDIAN_SNARE');_cast(e,'Meridian Snare: Leg Line')
    e.end_turn();e.end_turn();assert e.state.current_actor_id==ME
    assert e._effective_speed(foe)==foe.speed_ft-15
    e.end_turn();assert e._effective_speed(foe)==foe.speed_ft


@pytest.mark.parametrize('dc',[-50,50])
def test_meridian_stitch_hostile_save_controls_healing(dc):
    _,e,_,foe=_fight('TAL_THREAD_MERIDIAN_STITCH',dc=dc)
    e._apply_condition(foe,te.mark_condition_id('Thread Line',ME),'test',ME,expires_on='UNTIL_REMOVED')  # "an unwilling creature with an active Thread Line"
    _cast(e,'Meridian Stitch: Hostile Use')
    assert te._reduced_healing(e,foe,20)==(0 if dc>0 else 20)
    e.end_turn();e.end_turn();assert te._reduced_healing(e,foe,20)==20


@pytest.mark.parametrize('option',['Move Yourself','Move the Target'])
def test_reeling_silk_does_not_deny_all_reactions(option):
    _,e,_,foe=_fight('TAL_THREAD_REELING_SILK_BODY')
    _cast(e,'Draw the Line: Snare + Reeling Silk Body: '+option)
    assert not _cond(foe,'reaction_denied') and not _cond(foe,'no_opportunity_attacks')


@pytest.mark.parametrize('dc',[-50,50])
def test_web_field_waits_for_enter_or_start_and_expires_at_target_start(dc):
    _,e,_,foe=_fight('TAL_THREAD_SILK_WEB_FIELD',dc=dc);_cast(e,'Silk Web Field',at=(4,6))
    assert e._effective_speed(foe)==foe.speed_ft and not _rolls(e,'SAVE:')
    e.end_turn();assert e._effective_speed(foe)==(0 if dc>0 else foe.speed_ft)
    foe.position=foe.position.model_copy(update={'x':19,'y':1})
    e.end_turn();assert e._effective_speed(foe)==(0 if dc>0 else foe.speed_ft)
    e.end_turn();assert e._effective_speed(foe)==foe.speed_ft


def test_stitch_a_push_does_not_make_anyone_prone_or_grant_caster_movement():
    _,e,me,foe=_fight('TAL_THREAD_STITCH_THE_FALLING_BODY');before=me.movement_remaining_ft
    tr.on_forced_movement(e,me,foe,10)
    assert me.resources['resource:core.qi']==99
    assert me.movement_remaining_ft==before and not _cond(me,'prone') and not _cond(foe,'prone')


def test_single_thread_through_heaven_has_a_long_rest_limit():
    _,e,_,_=_fight('TAL_THREAD_THE_SINGLE_THREAD_THROUGH_HEAVEN')
    _cast(e,'The Single Thread Through Heaven');e.end_turn();e.end_turn()
    assert not any('Single Thread Through Heaven' in c.display_name for c in e.legal_candidates())


def test_listen_through_tension_survives_next_start_but_not_next_end():
    _,e,me,_=_fight('THREAD_BASE_LISTEN_THROUGH_TENSION');_cast(e,'Listen Through Tension')
    assert te.check_mode(me,'WIS','Perception')=='ADVANTAGE'
    e.end_turn();e.end_turn();assert te.check_mode(me,'WIS','Perception')=='ADVANTAGE'
    e.end_turn();assert te.check_mode(me,'WIS','Perception')=='NORMAL'


@pytest.mark.parametrize('cl,count',[(1,1),(5,2),(11,3),(17,4)])
def test_cutting_thread_scales(cl,count):
    _,e,_,_=_fight(T+'cutting_thread',cl=cl);_cast(e,'Draw the Line: Snare + Cutting Thread')
    assert any(r.expression==f'{count}d6+2' for r in _rolls(e))


def test_heaven_net_does_not_reduce_a_grounded_creatures_walk():
    _,e,_,foe=_fight(T+'heaven_net_casting',dc=-50);_cast(e,'Heaven-Net Casting',at=(4,6))
    assert e._effective_speed(foe)==foe.speed_ft


# Meridian Lock's cost/save regression now lives in test_a2_thread.py through
# CombatService, actual paid Qi Thread setup, session intent and cold reload.
# The old bare-engine case cast without the printed Qi Thread prerequisite.


def test_puppet_line_cannot_penalize_a_successful_unwilling_save():
    # AUTO19 2026-10-04 changed this test to assert that a successful Wisdom save "costs nothing". AUTO19f1
    # 2026-10-05 reverted that half: the printed activation is "Cost: 2 CP" and "On a success, the roll is
    # unaffected" says what the save does to the ROLL, not that the activation is refunded. There is no printed
    # refund, so a resisting creature costs the weaver 2 CP and the Reaction and leaves the roll untouched; the
    # guard below is the original one (2 CP is spent) plus the printed roll outcome.
    _,e,me,foe=_fight(T+'puppet_line_correction');foe.saving_throws['WIS']=1000
    e._apply_condition(foe,te.mark_condition_id('Thread Line',ME),'test',ME,expires_on='UNTIL_REMOVED')
    shaped=tr.on_d20_pending(e,foe,'save',ability='DEX')
    assert me.resources['resource:core.qi']==100 and shaped['bonus']==0
    with e.d20_scope({'kind':'save','actor_id':AN,'target_id':AN,'source_id':'test:save',
                      'source_actor_id':AN,'ability':'DEX'}):
        roll=e.roller.d20(modifier=0,actor_id=AN,reason='SAVE:test:save:DEX')
    assert roll.total==roll.natural_result+roll.modifier   # "On a success, the roll is unaffected."
    assert me.resources['resource:core.qi']==98 and not me.reaction_available   # "Cost: 2 CP", spent to try


@pytest.mark.parametrize('dc',[-50,50])
def test_severing_a_pair_is_not_blanket_reaction_or_immediate_movement_loss(dc):
    _,e,_,foe=_fight(T+'sever_the_battle_line',dc=dc);_cast(e,'Sever the Battle Line')
    assert not _cond(foe,'reaction_denied') and e._effective_speed(foe)==foe.speed_ft


@pytest.mark.parametrize('marked',[False,True])
def test_soul_silk_damage_requires_the_users_spirit_thread(marked):
    _,e,_,foe=_fight(T+'soul_silk_thread')
    if marked:e._apply_condition(foe,te.mark_condition_id('Spirit Thread',ME),'test',ME,expires_on='UNTIL_REMOVED')
    _cast(e,'Draw the Line: Snare + Soul-Silk Thread')
    assert 2000-foe.current_hp==(4 if marked else 0)


def test_surgeon_does_not_heal_without_spending_a_hit_die():
    _,e,me,_=_fight(T+'surgeon_s_stitch');ally=_ally(e,me);ally.current_hp=100
    _cast(e,'Surgeon’s Stitch',target=ally.entity_id);assert ally.current_hp==100


@pytest.mark.parametrize('option',['Pull 10 Feet','Snare Speed','Additional Force Damage'])
def test_thread_domain_does_not_deliver_hit_rewards_at_creation(option):
    _,e,_,foe=_fight(T+'ten_thousand_thread_domain');pos=foe.position
    _cast(e,'Ten Thousand Thread Domain: '+option)
    assert foe.position==pos and foe.current_hp==2000 and e._effective_speed(foe)==foe.speed_ft


@pytest.mark.parametrize('key',[T+'threaded_guard',T+'webbed_mirror_defense'])
@pytest.mark.parametrize('cl,count',[(1,1),(5,2),(11,3),(17,4)])
def test_thread_deflections_reduce_the_actual_hit_with_scaled_dice(key,cl,count):
    _,e,me,foe=_fight(key,cl=cl);before=me.current_hp
    tr.on_attack_hit(e,foe,me,{'range_ft':30},100,10,15)
    c=e.legal_candidates()[0]
    intent=ActionIntent(intent_id='projectile',decision_id=c.decision_id,candidate_id=c.candidate_id,
        state_version=c.state_version,actor_id=AN,target_ids=(ME,))
    e._commit_damage(me,200,'PIERCING','test:projectile',AN,intent,reaction_depth=0)
    rolls=_rolls(e,'GENERIC_AMOUNT:');assert len(rolls)==1
    assert rolls[0].expression==f'{count}d8+4'
    assert me.current_hp==before-(200-rolls[0].total)
    assert not _rolls(e,'ATTACK:')


@pytest.mark.parametrize('key,name,cost',[
    (U+'FIFTH_RUIN_FORM_DOMAIN_OF_COLLAPSE','Fifth Ruin Form',4),
    (U+'FOURTH_RUIN_FORM_BLACK_VEIN_BODY','Fourth Ruin Form',2)])
# Lattice Unraveling is no longer offered against an ordinary creature at all (its printed target is an effect or a summoned
# construct; rider lane C14 aims it at a square): tests/test_riders_c14.py test_lattice_unraveling_is_not_offered_against_an_ordinary_creature.
# Sever the Mountain's Memory is no longer offered against a creature at all (its printed target is a structure; rider lane C5
# makes it an object check): tests/test_riders_c5.py test_sever_the_mountains_memory_targets_an_object_only.
def test_unmaking_does_not_apply_wrong_trigger_or_object_damage_to_creatures(key,name,cost):
    _,e,me,foe=_fight(key);_cast(e,name)
    assert foe.current_hp==2000 and me.current_hp==2000
    assert me.resources['resource:named.black_vein_strain']==0
    assert me.resources['resource:core.qi']==100-cost


@pytest.mark.parametrize('dc',[-50,50])
def test_hollowing_field_damage_and_denial_begin_on_target_turn(dc):
    _,e,me,foe=_fight(U+'HOLLOWING_FIELD',dc=dc);_cast(e,'Hollowing Field',at=(4,6))
    assert me.current_hp==2000 and foe.current_hp==2000 and not _rolls(e,'SAVE:')
    e.end_turn();r=_rolls(e)[0];assert r.expression=='5d8+0'
    assert 2000-foe.current_hp==(r.total if dc>0 else r.total//2)
    assert te._reduced_healing(e,foe,20)==(0 if dc>0 else 20)
    foe.position=foe.position.model_copy(update={'x':19,'y':1});e.end_turn()
    assert te._reduced_healing(e,foe,20)==(0 if dc>0 else 20)
    e.end_turn();assert te._reduced_healing(e,foe,20)==20


@pytest.mark.parametrize('dc,penalty',[(-50,-1),(50,-2)])
@pytest.mark.parametrize('attack_bonus',[-1000,40])
def test_hollow_armor_uses_one_save_branch_and_one_incoming_attack(dc,penalty,attack_bonus):
    _,e,me,foe=_fight(U+'HOLLOW_THE_ARMOR',dc=dc)
    _cast(e,'Black Trace: Sting + Hollow the Armor')
    assert e._ac_modifier(foe)==penalty
    from combat.gate2_runtime_models import DiceSpec
    c=e.legal_candidates()[0]
    intent=ActionIntent(intent_id='followup',decision_id=c.decision_id,candidate_id=c.candidate_id,
        state_version=c.state_version,actor_id=ME,target_ids=(AN,))
    e._resolve_attack_spec(me,foe,{'attack_bonus':attack_bonus,'damage':DiceSpec(count=1,sides=4),'damage_type':'PIERCING'},
        intent,source_definition_id='test:followup',attack_index=0)
    assert e._ac_modifier(foe)==0


def test_hollow_armor_expires_at_next_source_start_without_an_attack():
    _,e,_,foe=_fight(U+'HOLLOW_THE_ARMOR');_cast(e,'Black Trace: Sting + Hollow the Armor')
    assert e._ac_modifier(foe)==-2
    e.end_turn();assert e._ac_modifier(foe)==-2
    e.end_turn();assert e._ac_modifier(foe)==0


@pytest.mark.parametrize('cl,count',[(5,6),(11,8),(17,10)])
@pytest.mark.parametrize('dc',[-50,50])
def test_ruin_wave_damage_scales_on_both_save_branches(cl,count,dc):
    _,e,_,foe=_fight(U+'RUIN_WAVE',cl=cl,dc=dc)
    _cast(e,'Ruin Wave',at=(4,6))  # one action: its price is chosen after it resolves (rider lane C5)
    r=_rolls(e)[0];assert r.expression==f'{count}d8+0'
    assert 2000-foe.current_hp==(r.total if dc>0 else r.total//2)
    assert bool(_cond(foe,'reaction_denied'))==(dc>0)


def test_shred_temporary_shape_does_not_damage_or_refund_for_a_normal_living_target():
    _,e,me,foe=_fight(U+'SHRED_THE_TEMPORARY_SHAPE')
    _cast(e,'Black Trace: Sting, Unbound Trace')  # Shred rides the damage now (rider lane C5), offered only against a summoned creature
    r=_rolls(e);assert len(r)==1 and 2000-foe.current_hp==r[0].total
    assert me.resources['resource:core.qi']==100


@pytest.mark.parametrize('key,name,dice',[
    (U+'SIXTH_RUIN_FORM_STAR_SUNDERING_CUT','Sixth Ruin Form','16d10+0'),
    (U+'THIRD_RUIN_FORM_SEVERING_WAVE','Third Ruin Form','10d8+0')])
@pytest.mark.parametrize('dc',[-50,50])
def test_ruin_lines_have_distinct_save_branch_healing_deadlines(key,name,dice,dc):
    _,e,me,foe=_fight(key,dc=dc)
    _cast(e,name,at=(4,6))
    r=_rolls(e)[0];assert r.expression==dice
    assert 2000-foe.current_hp==(r.total if dc>0 else r.total//2)
    assert te._reduced_healing(e,foe,20)==0
    if 'SIXTH' in key:
        own=_rolls(e)[1];assert own.expression=='8d6+20'
        # Owner ruling 2026-10-01: this line says every creature, so its caster
        # takes the area damage too, followed by the separate printed backlash.
        area_damage = r.total if dc > 0 else r.total // 2
        assert 2000-me.current_hp == area_damage + own.total
        assert te._reduced_healing(e,me,20)==0
    e.end_turn();assert te._reduced_healing(e,foe,20)==0
    e.end_turn();assert te._reduced_healing(e,foe,20)==20


def _summoned(foe):  # Unbody targets a summoned creature (rider lane C5); its summoner here is not on the map
    foe.summon={'owner':'actor:review.summoner','group':'g','source':'s','status':'present','concentration':False,
                'commanded':False,'command':'free','command_range_ft':60}


@pytest.mark.parametrize('dc',[-50,50])
def test_unbody_does_not_deal_the_summoners_damage_to_the_original_target(dc):
    _,e,_,foe=_fight(U+'UNBODY_THE_FALSE_VESSEL',dc=dc);_summoned(foe);_cast(e,'Unbody the False Vessel')
    r=_rolls(e);assert len(r)==1 and r[0].expression=='14d10+0'
    assert 2000-foe.current_hp==(r[0].total if dc>0 else r[0].total//2)


def test_unbody_uses_the_targets_better_save():
    _,e,_,foe=_fight(U+'UNBODY_THE_FALSE_VESSEL');_summoned(foe);foe.saving_throws.update(CON=-1000,WIS=1000)
    _cast(e,'Unbody the False Vessel');r=_rolls(e)[0]
    assert 2000-foe.current_hp==r.total//2


@pytest.mark.parametrize('key,name',[
    (U+'SIXTH_RUIN_FORM_STAR_SUNDERING_CUT','Sixth Ruin Form'),
    (U+'THIRD_RUIN_FORM_SEVERING_WAVE','Third Ruin Form')])
def test_ten_foot_ruin_lines_cover_the_adjacent_row(key,name):
    _,e,_,foe=_fight(key,foe_at=(5,7))
    _cast(e,name,at=(8,6))
    assert foe.current_hp<2000


@pytest.mark.parametrize('dc',[-50,50])
def test_moment_nothing_answers_does_not_invent_conditional_damage(dc):
    _,e,me,foe=_fight('tianxia.talent.unmaking.the_moment_nothing_answers',dc=dc)
    _cast(e,'The Moment Nothing Answers');r=_rolls(e)
    assert len(r)==1 and r[0].expression=='24d10+0'
    assert 2000-foe.current_hp==(r[0].total if dc>0 else r[0].total//2)
    assert te._reduced_healing(e,me,20)==0
