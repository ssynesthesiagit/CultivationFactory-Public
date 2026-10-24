"""Printed-text review of Dreams, Drunken Style and Dual Wielding.

Each correction is exercised through a compiled character and combat engine.
The old authority is also run against this file to demonstrate the regressions.
"""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import typed_executor as te, typed_reactions as tr
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT=Path(__file__).resolve().parents[1]
AUTH=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
KIT={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.fu','name':'Fu (Short Axe)','quantity':1}]}}
NEEDLE='TAL_DREAM_DREAM_NEEDLE'
PRISON='TAL_DREAM_DREAM_PRISON'
CHAIN='TAL_DREAM_NIGHTMARE_CHAIN'
GLIMPSE='TAL_DREAM_NIGHTMARE_GLIMPSE'
BEAST='tianxia.talent.dreams.dream_beast'
SOVEREIGN='tianxia.talent.dreams.dream_sovereign_incarnation'
WORLD='tianxia.talent.dreams.dream_that_swallows_the_waking_world'
DRUNKEN='TAL_DRUNKEN_STYLE_'
FOCUS='resource:core.martial_focus'


@lru_cache(maxsize=None)
def _compiled(key, dc=50):
    sid=AUTH[key]['sphere_id']
    bases=[k for k,v in AUTH.items() if v.get('sphere_id')==sid and v.get('kind')=='base_ability']
    sheet={**SHEET,'equipment':[KIT],'identity':{**SHEET['identity'],'cultivation_level':20},
           'ability_scores_and_statistics':{**SHEET['ability_scores_and_statistics'],'technique_save_dc':dc,
             'technique_attack_bonus':40,'primary_resource':{'name':'Qi','maximum':100}},
           'spheres_and_talents':{'sphere_record_ids':[sid],'learned_talent_record_ids':list(dict.fromkeys([*bases,key]))}}
    return compile_character(sheet,actor_id=ME)


def _fight(key, dc=50):
    b=copy.deepcopy(_compiled(key,dc))
    e=_engine(b,foe_at=(4,6))
    me,foe=e.state.actors[ME],e.state.actors[AN]
    foe.maximum_hp=foe.current_hp=2000
    foe.armor_class=-50
    me.resources[FOCUS]=1
    if key in (PRISON,CHAIN,GLIMPSE):  # Nightmare Glimpse: "bearing your Dream Seed or currently Drowsy" (rider lane C5)
        e._apply_condition(foe,te.mark_condition_id('Dream Seed',ME),'test:seed',ME,expires_on='UNTIL_REMOVED')
    return b,e,me,foe


def _cast(e,prefix):
    found=[c for c in e.legal_candidates() if c.display_name.startswith(prefix)]
    assert found, prefix
    c=found[0]
    e.execute_intent(ActionIntent(intent_id='review',decision_id=c.decision_id,candidate_id=c.candidate_id,
                                 state_version=c.state_version,actor_id=ME,target_ids=c.target_ids,destination=c.destination))


def _payloads(e,kind):
    return [event.payload for event in e.events if event.event_type==kind]


def _expressions(e):
    return [p['expression'].removesuffix('+0') for p in _payloads(e,'DAMAGE_ROLLED')]


def _condition(actor,slug):
    return [c for c in actor.conditions.values() if c.condition_id=='condition:typed.'+slug]


def _damage(e,foe,source=ME):
    e._commit_damage(foe,1,'FIRE','test:external_damage',source,None,reaction_depth=0)


def test_dream_needles_seed_expires_at_the_casters_next_turn():
    _,e,me,foe=_fight(NEEDLE)
    from combat.gate2_runtime_models import ReactionDecision

    def seed(r):  # rider lane C5: "Once per turn on a hit, choose one" -- the player picks the Dream Seed
        pick=tuple(o for o in r["legal_option_ids"] if o.startswith("Plant")) if str(r["reaction_source_id"]).startswith("choice:needle.") else ()
        return ReactionDecision(checkpoint=r["checkpoint"],reactor_id=r["reactor_id"],reaction_source_id=r["reaction_source_id"],
                                selection="USE" if pick else "DECLINE",option_ids=pick),None
    e.set_reaction_provider(seed)
    _cast(e,'Dream Needle')
    assert te.bears_mark(foe,ME,'Dream Seed')
    e.end_turn()
    e.end_turn()
    te.expire_marks(e)
    assert not te.bears_mark(foe,ME,'Dream Seed')


@pytest.mark.parametrize('key,prefix',[(PRISON,'Dream Prison'),(CHAIN,'Nightmare Chain')])
def test_seed_talents_require_the_casters_seed(key,prefix):
    _,e,me,foe=_fight(key)
    e._remove_condition(foe,te.mark_condition_id('Dream Seed',ME),'test:remove_seed')
    assert not any(c.display_name.startswith(prefix) for c in e.legal_candidates())
    e._apply_condition(foe,te.mark_condition_id('Dream Seed',AN),'test:other_seed',AN,expires_on='UNTIL_REMOVED')
    assert not any(c.display_name.startswith(prefix) for c in e.legal_candidates())


def test_dream_prison_ends_all_restrictions_on_one_repeat_save():
    _,e,me,foe=_fight(PRISON)
    _cast(e,'Dream Prison')
    assert e._effective_speed(foe)==0 and not foe.reaction_available
    e.end_turn()
    assert e.state.current_actor_id==AN
    foe.saving_throws['WIS']=100
    before=len(_payloads(e,'SAVE_ROLLED'))
    e.end_turn()
    assert len(_payloads(e,'SAVE_ROLLED'))==before+1
    assert e._effective_speed(foe)==30
    assert not any(r.get('no_reactions') for r in te.condition_rules(foe))


def test_dream_prison_damage_grants_an_advantaged_repeat_save():
    _,e,me,foe=_fight(PRISON)
    _cast(e,'Dream Prison')
    foe.saving_throws['WIS']=100
    before=len(_payloads(e,'SAVE_ROLLED'))
    _damage(e,foe)
    assert len(_payloads(e,'SAVE_ROLLED'))==before+1
    assert _payloads(e,'SAVE_ROLLED')[-1]['mode']=='ADVANTAGE'
    assert e._effective_speed(foe)==30


def test_damage_repeat_save_removes_only_the_successful_condition_instance():
    _,e,me,foe=_fight(PRISON)
    _cast(e,'Dream Prison')
    first=_condition(foe,'dream_prison')[0]
    other_data=copy.deepcopy(first.data)
    other_data['repeat_save']['dc']=1000
    e._apply_condition(foe,first.condition_id,'test:other_prison',AN,
                       expires_on='CONCENTRATION_END',data=other_data)
    foe.saving_throws['WIS']=100
    _damage(e,foe)
    remaining=_condition(foe,'dream_prison')
    assert len(remaining)==1 and remaining[0].source_actor_id==AN


def test_dream_prison_success_only_slows_until_the_targets_turn():
    _,e,me,foe=_fight(PRISON,dc=-40)
    _cast(e,'Dream Prison')
    assert e._effective_speed(foe)==20 and not _condition(foe,'dream_prison')
    e.end_turn()
    assert e._effective_speed(foe)==30


def test_nightmare_chain_ticks_at_turn_start_and_stops_on_repeat_save():
    _,e,me,foe=_fight(CHAIN)
    _cast(e,'Nightmare Chain')
    assert foe.current_hp==2000 and not _expressions(e)
    e.end_turn()
    assert _expressions(e)==['4d8']
    assert _condition(foe,'concentration_mode')
    foe.saving_throws['WIS']=100
    e.end_turn()
    e.end_turn()
    assert _expressions(e)==['4d8']


def test_nightmare_chains_success_deals_only_the_printed_dice_once():
    _,e,me,foe=_fight(CHAIN,dc=-40)
    _cast(e,'Nightmare Chain')
    assert _expressions(e)==['4d8']
    assert not _condition(foe,'nightmare_chain')
    e.end_turn()
    assert _expressions(e)==['4d8']


def test_nightmare_glimpse_does_not_add_cultivation_level_to_damage():
    _,e,me,foe=_fight(GLIMPSE)
    _cast(e,'Nightmare Glimpse')
    assert _expressions(e)==['5d6']


def test_dream_beast_summoning_does_not_immediately_attack():
    _,e,me,foe=_fight(BEAST)
    _cast(e,'Dream Beast')
    assert foe.current_hp==2000 and not _payloads(e,'ATTACK_ROLLED')


def test_dream_sovereign_grants_speed_instead_of_an_immediate_move_or_seed():
    _,e,me,foe=_fight(SOVEREIGN)
    before=me.movement_remaining_ft
    _cast(e,'Dream-Sovereign Incarnation')
    assert me.movement_remaining_ft==before and e._effective_speed(me)==30
    from combat import flight
    assert flight.profile(e,me).speed_ft==40
    assert not te.bears_mark(foe,ME,'Dream Seed') and not te.bears_mark(me,ME,'Dream Seed')


def test_waking_world_caster_damage_repeats_its_save_with_advantage():
    _,e,me,foe=_fight(WORLD)
    _cast(e,'Dream That Swallows')
    assert foe.current_hp==2000 and e._effective_speed(foe)==0
    assert e._attack_mode(foe,me)=='DISADVANTAGE'
    saves=len(_payloads(e,'SAVE_ROLLED'))
    e.end_turn()
    assert _expressions(e)==['4d10']
    # The caster is another creature, including for its ongoing damage. Preserve
    # the repaired round-24 interpretation and the ordinary end-of-turn repeat.
    assert len(_payloads(e,'SAVE_ROLLED'))==saves+1
    assert _payloads(e,'SAVE_ROLLED')[-1]['mode']=='ADVANTAGE'
    foe.saving_throws['WIS']=100
    e.end_turn()
    assert e._effective_speed(foe)==30 and e._attack_mode(foe,me)=='NORMAL'


@pytest.mark.parametrize('source', [AN, None, 'test:not_a_creature'])
def test_waking_world_does_not_repeat_for_self_damage_or_environment(source):
    _,e,me,foe=_fight(WORLD)
    _cast(e,'Dream That Swallows')
    before=len(_payloads(e,'SAVE_ROLLED'))
    _damage(e,foe,source=source)
    assert len(_payloads(e,'SAVE_ROLLED'))==before
    assert e._effective_speed(foe)==0


def test_waking_world_repeats_with_advantage_on_external_damage():
    _,e,me,foe=_fight(WORLD)
    _cast(e,'Dream That Swallows')
    foe.saving_throws['WIS']=100
    before=len(_payloads(e,'SAVE_ROLLED'))
    _damage(e,foe)
    assert len(_payloads(e,'SAVE_ROLLED'))==before+1
    assert _payloads(e,'SAVE_ROLLED')[-1]['mode']=='ADVANTAGE'
    assert e._effective_speed(foe)==30


@pytest.mark.parametrize('key,prefix',[ (PRISON,'Dream Prison'),(CHAIN,'Nightmare Chain'),(WORLD,'Dream That Swallows')])
def test_ongoing_effect_ends_with_concentration(key,prefix):
    _,e,me,foe=_fight(key)
    _cast(e,prefix)
    e._end_concentration(me,'TEST')
    assert not any(c.data.get('repeat_save') for c in foe.conditions.values())
    e.end_turn()
    assert e._effective_speed(foe)==30 and not _expressions(e)


@pytest.mark.parametrize('tail',['COLLAPSE_INTO_VICTORY','FALSE_FALL_TRUE_ESCAPE','LAUGHING_QI_MISDIRECTION','STRIKE_FROM_THE_MISSING_STEP'])
def test_drunken_reaction_spends_focus(tail):
    key=DRUNKEN+tail
    b,e,me,foe=_fight(key)
    row=next(r for r in b['typed_reactions'] if r.get('feature_id')==key)
    e.typed_reaction_rows[ME]=[row]
    if tail=='FALSE_FALL_TRUE_ESCAPE':
        e._apply_condition(me,'condition:typed.prone','test:prone',ME,expires_on='UNTIL_REMOVED')
    if tail in ('COLLAPSE_INTO_VICTORY','FALSE_FALL_TRUE_ESCAPE'):
        tr.on_attack_hit(e,foe,me,{'range_ft':None},total=100,natural=15,effective_ac=14)
        tr.on_damage(e,me,50,0,source_definition_id='test:attack',source_actor_id=AN)
    elif tail=='LAUGHING_QI_MISDIRECTION':
        tr.on_attack_missed(e,foe,me,{'range_ft':None})
    else:
        tr.after_d20(e,foe,'attack',success=False,natural=2,other=me,melee=True)
    assert _payloads(e,'REACTION_RESOLVED')
    assert me.resources[FOCUS]==0
    assert not tr._generic_affordable(e,me,row)


def test_false_fall_reduction_includes_the_key_modifier():
    key=DRUNKEN+'FALSE_FALL_TRUE_ESCAPE'
    b,e,me,foe=_fight(key)
    row=next(r for r in b['typed_reactions'] if r.get('feature_id')==key)
    e.typed_reaction_rows[ME]=[row]
    e._apply_condition(me,'condition:typed.prone','test:prone',ME,expires_on='UNTIL_REMOVED')
    tr.on_attack_hit(e,foe,me,{'range_ft':None},total=100,natural=15,effective_ac=14)
    tr.on_damage(e,me,50,0,source_definition_id='test:attack',source_actor_id=AN)
    rolls=[roll.model_dump(mode='json') for roll in e.rolls]
    assert any('1d10+6' in str(p) for p in rolls), rolls


def test_domain_does_not_grant_conditional_movement_at_activation():
    _,e,me,foe=_fight(DRUNKEN+'COURT_OF_BROKEN_RHYTHM')
    before=me.movement_remaining_ft
    _cast(e,'Court of Broken Rhythm')
    assert me.movement_remaining_ft==before


def test_chaos_step_incarnation_does_not_deny_all_foe_reactions():
    _,e,me,foe=_fight(DRUNKEN+'SOVEREIGN_CHAOS_STEP_INCARNATION')
    _cast(e,'Sovereign Chaos-Step Incarnation')
    assert not _condition(foe,'reaction_denied') and not foe.modifiers


def test_unreliable_center_does_not_offer_an_attack_that_grants_advantage():
    _,e,me,foe=_fight(DRUNKEN+'UNRELIABLE_CENTER_STANCE')
    assert not any('Unreliable Center Stance' in c.display_name for c in e.legal_candidates())
    _cast(e,'Broken-Rhythm Strike')
    assert not any(m.target_field=='incoming_attack_mode' and m.value=='ADVANTAGE' for m in me.modifiers.values())
