"""Combat regressions for the Fire, Flowers and Flowing River typing review."""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import typed_executor as te, typed_reactions as tr
from combat.flight import profile
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT=Path(__file__).resolve().parents[1]
AUTH=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
KIT={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.fu','name':'Fu (Short Axe)','quantity':1}]}}
FIRE='tianxia.talent.fire.'
FINAL='tianxia.talent.flowers.blossom_of_the_final_breath'
RIVER='TAL_FLOWING_RIVER_'


@lru_cache(maxsize=None)
def _compiled(key,cl=20,dc=50):
    sid=AUTH[key]['sphere_id']
    bases=[k for k,v in AUTH.items() if v.get('sphere_id')==sid and v.get('kind')=='base_ability']
    sheet={**SHEET,'equipment':[KIT],'identity':{**SHEET['identity'],'cultivation_level':cl},
           'ability_scores_and_statistics':{**SHEET['ability_scores_and_statistics'],'technique_save_dc':dc,
             'technique_attack_bonus':40,'primary_resource':{'name':'Qi','maximum':100}},
           'spheres_and_talents':{'sphere_record_ids':[sid],'learned_talent_record_ids':list(dict.fromkeys([*bases,key]))}}
    return compile_character(sheet,actor_id=ME)


def _fight(key,cl=20,dc=50,foe_at=(4,6)):
    bundle=copy.deepcopy(_compiled(key,cl,dc))
    e=_engine(bundle,foe_at=foe_at)
    me,foe=e.state.actors[ME],e.state.actors[AN]
    foe.maximum_hp=foe.current_hp=2000;foe.armor_class=-50
    me.resources['resource:core.martial_focus']=1
    return bundle,e,me,foe


def _cast(e,prefix,contains=''):
    found=[c for c in e.legal_candidates() if c.display_name.startswith(prefix) and contains in c.display_name]
    assert found, (prefix,contains,sorted({c.display_name for c in e.legal_candidates()}))
    pos=e.state.actors[AN].position
    c=min(found,key=lambda c:0 if c.destination is None else abs(c.destination.x-pos.x)+abs(c.destination.y-pos.y))
    e.execute_intent(ActionIntent(intent_id='review',decision_id=c.decision_id,candidate_id=c.candidate_id,
                                 state_version=c.state_version,actor_id=ME,target_ids=c.target_ids,destination=c.destination))


def _payloads(e,kind):return [ev.payload for ev in e.events if ev.event_type==kind]
def _expressions(e):return [p['expression'].removesuffix('+0') for p in _payloads(e,'DAMAGE_ROLLED')]
def _condition(a,name):return [c for c in a.conditions.values() if c.condition_id=='condition:typed.'+name]


def test_conflagrations_success_applies_kindled_until_the_casters_turn():
    _,e,me,foe=_fight('FIRE_BASE_CONFLAGRATION',dc=-40)
    _cast(e,'Conflagration')
    assert _condition(foe,'kindled') and not _condition(foe,'burning')
    e.end_turn();e.end_turn()
    assert not _condition(foe,'kindled')


@pytest.mark.parametrize('option',['Push Target','Fire Terrain Square','Increase Burn Damage','Bonus vs Kindled'])
def test_ignite_applies_burn_in_each_existing_option(option):
    _,e,me,foe=_fight('FIRE_BASE_IGNITE')
    _cast(e,'Ignite',contains=option)
    assert _condition(foe,'burning')


def test_burning_weapon_does_not_burn_its_recipient_at_cast():
    _,e,me,foe=_fight('FIRE_TAL_BURNING_WEAPON')
    _cast(e,'Burning Weapon')
    assert not _condition(me,'burning') and not _condition(foe,'burning')


def test_crown_of_inferno_does_not_roll_its_entry_save_at_cast():
    _,e,me,foe=_fight('FIRE_TAL_CROWN_OF_INFERNO')
    _cast(e,'Crown of the Inferno')
    assert foe.current_hp==2000 and not _payloads(e,'SAVE_ROLLED')
    e.end_turn()
    assert '5d8' in _expressions(e) and _condition(foe,'burning')


@pytest.mark.parametrize('cl,count',[(5,3),(10,3),(11,4),(16,4),(17,5),(20,5)])
def test_scorching_ray_count_scales_with_level(cl,count):
    _,e,me,foe=_fight('FIRE_TAL_SCORCHING_RAY_ART',cl=cl)
    _cast(e,'Scorching Ray Art')
    assert len(_payloads(e,'ATTACK_ROLLED'))==count
    assert _condition(foe,'burning')


def test_one_scorching_ray_hit_does_not_burn(monkeypatch):
    _,e,me,foe=_fight('FIRE_TAL_SCORCHING_RAY_ART',cl=5)
    original=e._resolve_attack_spec
    calls=0
    def resolve(actor,target,spec,intent,**kw):
        nonlocal calls
        calls+=1
        return original(actor,target,{**spec,'attack_bonus':100 if calls==1 else -100},intent,**kw)
    monkeypatch.setattr(e,'_resolve_attack_spec',resolve)
    _cast(e,'Scorching Ray Art')
    assert calls==3 and not _condition(foe,'burning')


def test_fire_sovereign_grants_fly_speed_eighty_and_hover_not_walking_speed():
    _,e,me,foe=_fight(FIRE+'fire_sovereign_incarnation')
    walk=e._effective_speed(me)
    _cast(e,'Fire-Sovereign Incarnation')
    assert profile(e,me).speed_ft==80 and profile(e,me).hover is True
    assert e._effective_speed(me)==walk


@pytest.mark.parametrize('foe_at,retaliation',[((4,6),4),((8,6),0)])
def test_fire_ward_reduces_damage_and_limits_retaliation_to_nearby_attackers(foe_at,retaliation):
    key=FIRE+'fire_ward'
    bundle,e,me,foe=_fight(key,foe_at=foe_at)
    e.typed_reaction_rows[ME]=[r for r in bundle['typed_reactions'] if r.get('feature_id')==key]
    pending=tr.on_damage(e,me,50,0,source_definition_id='test:attack',source_actor_id=AN)
    assert pending<50 and foe.current_hp==2000-retaliation
    assert any(r.expression=='3d8+2' for r in e.rolls)


def test_firebird_does_not_attack_or_increase_the_casters_ac_at_cast():
    _,e,me,foe=_fight(FIRE+'firebird_avatar')
    _cast(e,'Firebird Avatar')
    assert foe.current_hp==2000
    assert not _payloads(e,'ATTACK_ROLLED')
    assert not any(m.target_field=='armor_class' for m in me.modifiers.values())


def test_fire_ward_measures_retaliation_from_the_protected_ally():
    key=FIRE+'fire_ward'
    bundle,e,me,foe=_fight(key,foe_at=(10,6))
    ally=copy.deepcopy(me)
    ally.entity_id='actor:review.ally'
    ally.position=type(foe.position)(x=9,y=6)
    e.state.actors[ally.entity_id]=ally
    e.typed_reaction_rows[ME]=[r for r in bundle['typed_reactions'] if r.get('feature_id')==key]
    pending=tr.on_damage(e,ally,50,0,source_definition_id='test:attack',source_actor_id=AN)
    assert pending<50 and foe.current_hp==1996


def test_blazing_armor_does_not_apply_retaliation_at_cast():
    _,e,me,foe=_fight(FIRE+'blazing_armor')
    _cast(e,'Blazing Armor')
    assert foe.current_hp==2000 and not _payloads(e,'DAMAGE_COMMITTED')


@pytest.mark.parametrize('attack',['Ignite','Fu (Short Axe) attack'])
def test_combustive_step_moves_and_reserves_its_bonus_for_a_later_hit(attack):
    _,e,me,foe=_fight(FIRE+'combustive_step')
    before=me.movement_remaining_ft
    _cast(e,'Combustive Step')
    assert me.movement_remaining_ft==before+15
    assert foe.current_hp==2000 and not _payloads(e,'DAMAGE_COMMITTED')
    _cast(e,attack)
    damage=[p for p in _payloads(e,'DAMAGE_COMMITTED') if p.get('damage_type')=='FIRE']
    assert any(p.get('hp_damage')==4 for p in damage)


def test_explosive_combustions_splash_scales_to_seven_dice():
    _,e,me,foe=_fight(FIRE+'explosive_combustion')
    _cast(e,'Ignite',contains='Explosive Combustion')
    assert '7d6' in _expressions(e)


def test_searing_brand_does_not_deal_extinguishing_damage_on_hit():
    _,e,me,foe=_fight(FIRE+'searing_brand')
    _cast(e,'Ignite',contains='Searing Brand')
    assert not any(p.get('hp_damage')==4 for p in _payloads(e,'DAMAGE_COMMITTED'))


def test_white_hot_focus_does_not_grant_fire_resistance():
    _,e,me,foe=_fight(FIRE+'white_hot_focus')
    _cast(e,'White-Hot Focus')
    assert not any(m.target_field=='damage_resistance' and m.value=='FIRE' for m in me.modifiers.values())


def test_flower_of_false_death_holds_at_one_hp():
    """"Cause one Blossom already attached to the creature to bloom. The creature drops to 1 HP instead of 0 HP": with one of the
    caster's Blossoms on it the drop is held at 1 HP; without one there is nothing to bloom and the reaction is not offered
    (sys/placed-effects: combat/ext/blossom.py, tests/test_sys_placed_effects.py)."""
    key='TAL_FLOWERS_FLOWER_OF_FALSE_DEATH'
    bundle,e,me,foe=_fight(key)
    e.typed_reaction_rows[ME]=[r for r in bundle['typed_reactions'] if r.get('feature_id')==key]
    me.current_hp=10
    assert tr._offer_drop_to_zero_or_bloodied(e,me,foe,20,0,AN)==20 and me.current_hp==10  # no Blossom attached
    _cast(e,'Cultivate Blossom at %d,%d'%(me.position.x,me.position.y))  # one on the caster itself
    me.reaction_available=True
    pending=tr._offer_drop_to_zero_or_bloodied(e,me,foe,20,0,AN)
    assert pending==9 and me.current_hp==10


def _heal(e,me,foe):
    action=next(iter(e.action_catalog.values()))
    foe.current_hp=1000
    before=foe.current_hp
    te.block_healing(te.Context(e,me,action,None,{'numbers':{}},[foe],foe,{}),{'type':'healing','applies_to':'target','flat':20})
    return foe.current_hp-before


def test_final_breath_delays_damage_and_healing_denial_until_turn_start():
    _,e,me,foe=_fight(FINAL)
    _cast(e,'Blossom of the Final Breath')
    assert foe.current_hp==2000 and len(_payloads(e,'SAVE_ROLLED'))==1
    e.end_turn()
    assert _expressions(e)==['4d10'] and _heal(e,me,foe)==0
    foe.saving_throws['CON']=100
    e.end_turn();e.end_turn()
    assert _expressions(e)==['4d10'] and _heal(e,me,foe)==20


def test_final_breath_success_halves_healing_until_targets_turn():
    _,e,me,foe=_fight(FINAL,dc=-40)
    _cast(e,'Blossom of the Final Breath')
    assert _expressions(e)==['4d10'] and _heal(e,me,foe)==10
    e.end_turn()
    assert _heal(e,me,foe)==20


def _response(key,dc=50):
    bundle,e,me,foe=_fight(key,dc=dc)
    from combat.ext import flowing_river
    row=next(r for r in bundle['typed_reactions'] if r.get('feature_id')==flowing_river.RESPONSE)
    effects=flowing_river._riding(e,me)[key]
    return e,me,foe,row,effects


def test_soft_capture_grapples_after_a_failed_save():
    e,me,foe,row,effects=_response(RIVER+'SOFT_CAPTURE')
    tr._run_generic_effects(e,me,foe,row,effects)
    assert _condition(foe,'grappled') and e._effective_speed(foe)==0


def test_soft_capture_allows_the_targets_strength_save_choice():
    e,me,foe,row,effects=_response(RIVER+'SOFT_CAPTURE')
    foe.saving_throws.update(STR=100,DEX=-100)
    tr._run_generic_effects(e,me,foe,row,effects)
    saves=_payloads(e,'SAVE_ROLLED')
    assert saves[-1]['success']
    assert not _condition(foe,'grappled')


def test_return_the_grip_releases_reactions_at_the_targets_turn_start():
    e,me,foe,row,effects=_response(RIVER+'RETURN_THE_GRIP',dc=-40)
    tr._run_generic_effects(e,me,foe,row,effects)
    assert _condition(foe,'reaction_denied')
    e.end_turn()
    assert not _condition(foe,'reaction_denied')
