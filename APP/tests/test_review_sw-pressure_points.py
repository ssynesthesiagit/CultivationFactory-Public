"""Printed-rule regressions for Pressure Points, Protection, and Puppetry."""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import carry, typed_executor as te, typed_reactions as tr
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
P, W, U = 'tianxia.talent.pressure_points.', 'tianxia.talent.protection.', 'tianxia.talent.puppetry.'


@lru_cache(maxsize=None)
def _compiled(key, cl=20, dc=50, armed=False, extra=(), actor_id=ME):
    sphere = AUTH[key]['sphere_id']
    bases = [k for k,v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    kit = [{'starting_kit': {'items': [{'item_id':'tianxia.mortal.weapon.fu','name':'Fu (Short Axe)','quantity':1}]}}] if armed else []
    sheet = {**SHEET, 'equipment':kit,
        'identity': {**SHEET['identity'], 'cultivation_level':cl},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'],
            'technique_save_dc':dc, 'technique_attack_bonus':40,
            'primary_resource':{'name':'Qi','maximum':100}},
        'spheres_and_talents': {'sphere_record_ids':[sphere],
            'learned_talent_record_ids':list(dict.fromkeys([*bases,key,*extra]))}}
    return compile_character(sheet, actor_id=actor_id)


def _fight(key, cl=20, dc=50, armed=False, foe_at=(4,6), extra=(), armed_foe=False):
    bundle = copy.deepcopy(_compiled(key,cl,dc,armed,extra))
    engine = _engine(bundle,foe_at=foe_at)
    if armed_foe:
        opponent = copy.deepcopy(_compiled('PUPPETRY_BASE_PUPPET_STRIKE',armed=True,actor_id=AN))
        engine = type(engine)(ROOT,match_seed='REVIEW_ARMED',typed_bundles=(bundle,opponent),
            roster_setup={'primary_actor_ids':[ME,AN],
                'team_by_actor':{ME:'team:a',AN:'team:b'},
                'starting_positions':{ME:{'x':3,'y':6},AN:{'x':foe_at[0],'y':foe_at[1]}}})
        engine.state.current_slot_index=engine.state.initiative_order.index(ME)
        engine.state.current_actor_id=ME
        engine._system_start_turn()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    me.resources['resource:core.martial_focus'] = 1
    return bundle,engine,me,foe


def _cast(engine,prefix,contains='',target_id=None,near=None):
    """Run one table candidate. ``near`` picks the placement closest to that square instead of the foe."""
    candidates = [c for c in engine.legal_candidates() if c.display_name.startswith(prefix) and contains in c.display_name
                  and (target_id is None or target_id in c.target_ids)]
    assert candidates,(prefix,contains)
    pos = near if near is not None else engine.state.actors[AN].position
    candidate = min(candidates,key=lambda c:(0 if c.destination is None else abs(c.destination.x-pos.x)+abs(c.destination.y-pos.y),len(c.display_name)))
    engine.execute_intent(ActionIntent(intent_id='review',decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,state_version=candidate.state_version,actor_id=ME,
        target_ids=candidate.target_ids,destination=candidate.destination))


def _mark(engine,foe,name='Opened'):
    engine._apply_condition(foe,te.mark_condition_id(name,ME),'test:mark',ME,expires_on='UNTIL_REMOVED',data={'mark':name,'label':name})


def _ally(engine,me):
    ally = me.model_copy(deep=True)
    ally.entity_id = 'actor:review.ally'
    ally.position = me.position.model_copy(update={'y':me.position.y+1})
    engine.state.actors[ally.entity_id] = ally
    return ally


def _rolls(engine,kind):
    return [r for r in engine.rolls if r.reason.startswith(kind)]


def _vessel(engine,me,near=None):
    """An active puppet vessel next to the puppeteer: the printed strike is made "from the puppet vessel's space", and the
    Substitute talents' printed trigger needs one within 30/60 feet (combat/ext/vessel.py). Raise the Vessel costs 1 CP and
    one Action, both refunded here so the tests' CP figures stay the ones they state and the following Action-costed
    ability (Puppet Strike) is still available."""
    qi = me.resources['resource:core.qi']
    spent = me.action_available
    _cast(engine,'Raise the Vessel',near=near)
    me.resources['resource:core.qi'] = qi
    me.action_available = spent


def _damage(engine):
    return [r.expression.removesuffix('+0') for r in _rolls(engine,'DAMAGE:')]


def _conditions(actor,name):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.'+name]


IRON=('TAL_IRON_FIST_IRON_FIST_TRAINING',)


@pytest.mark.parametrize('slug,prefix,seal',[
    ('grip_seal','Grip Seal',True),('grip_severing_point','Grip-Severing Point',False),
])
def test_failed_grip_save_drops_the_weapon(slug,prefix,seal):
    _,engine,me,foe=_fight(P+slug,extra=IRON,armed_foe=True)
    # fix/attack-ability (R22 merge 6592dcfa) gives the triggering Iron Fist
    # attack its own DC; the sheet technique DC no longer forces this save.
    ability = 'STR' if seal else 'CON'
    foe.saving_throws[ability] = -40
    weapon = next(item for item in carry.carrying_of(engine,AN)['items'] if item.get('weapon_action'))
    assert carry.holds(engine,foe,weapon['key'])
    if seal:_mark(engine,foe,'Pressure Point')
    _cast(engine,'Touch the Point: '+prefix)
    _cast(engine,'Unarmed Strike')
    saves = [event for event in engine.events if event.event_type == 'SAVE_ROLLED']
    assert len(saves) == 1
    assert saves[0].payload['dc'] == 14
    assert saves[0].payload['success'] is False
    assert _rolls(engine,'SAVE:')[0].reason.endswith(':'+ability)
    dropped = _conditions(foe,'disarmed')
    assert len(dropped) == 1
    assert dropped[0].data['disables_action'] == weapon['weapon_action']
    assert dropped[0].data['dropped_at'] == foe.position.model_dump(mode='json')
    assert not carry.holds(engine,foe,weapon['key'])


@pytest.mark.parametrize('slug,prefix,seal',[
    ('grip_seal','Grip Seal',True),('grip_severing_point','Grip-Severing Point',False),
])
def test_successful_grip_save_keeps_the_weapon(slug,prefix,seal):
    _,engine,me,foe=_fight(P+slug,extra=IRON,armed_foe=True)
    ability = 'STR' if seal else 'CON'
    foe.saving_throws[ability] = 40
    weapon = next(item for item in carry.carrying_of(engine,AN)['items'] if item.get('weapon_action'))
    if seal:_mark(engine,foe,'Pressure Point')
    _cast(engine,'Touch the Point: '+prefix)
    _cast(engine,'Unarmed Strike')
    saves = [event for event in engine.events if event.event_type == 'SAVE_ROLLED']
    assert len(saves) == 1
    assert saves[0].payload['dc'] == 14
    assert saves[0].payload['success'] is True
    assert _rolls(engine,'SAVE:')[0].reason.endswith(':'+ability)
    assert not _conditions(foe,'disarmed')
    assert carry.holds(engine,foe,weapon['key'])


def test_soft_paralysis_success_stops_speed_even_when_restraint_is_immune():
    _,engine,me,foe=_fight(P+'soft_paralysis_tap',dc=-50,extra=IRON)
    engine.typed_reaction_rows[AN]=[{'block':'condition_immunity','conditions':['restrained']}]
    _mark(engine,foe,'Pressure Point')
    _cast(engine,'Touch the Point: Soft Paralysis Tap')
    _cast(engine,'Unarmed Strike')
    assert not _conditions(foe,'restrained')
    assert engine._effective_speed(foe)==0


@pytest.mark.parametrize('cl,dice',[(1,'1d8+2'),(11,'2d8+2'),(17,'3d8+2')])
def test_needle_meets_blade_reduction_scales(cl,dice):
    key=P+'needle_meets_blade';bundle,engine,me,foe=_fight(key,cl=cl)
    _mark(engine,foe,'Pressure Point')
    row=next(r for r in bundle['typed_reactions'] if r.get('feature_id')==key)
    remaining,_=tr._generic_damage_reduction(engine,me,row,100,me)
    rolls=_rolls(engine,'GENERIC_AMOUNT:')
    assert len(rolls)==1 and rolls[0].expression==dice
    assert remaining==100-rolls[0].total


def test_stillness_field_does_not_harm_an_unmarked_creature_at_cast():
    _,engine,me,foe=_fight(P+'meridian_stillness_field')
    _cast(engine,'Meridian Stillness Field')
    assert foe.current_hp==2000 and not _rolls(engine,'SAVE:')
    assert engine._effective_speed(foe)==foe.speed_ft
    assert not _conditions(foe,'reaction_denied')
    engine._commit_damage(me,1,'FORCE','test:damage',AN,None,reaction_depth=0)
    concentration=[r for r in engine.rolls if 'concentration' in r.reason.lower()]
    assert concentration and not any(r.mode=='ADVANTAGE' for r in concentration)


def test_stillness_field_reaches_the_printed_sixty_feet():
    _,engine,me,foe=_fight(P+'meridian_stillness_field',foe_at=(12,6))
    candidates=[c for c in engine.legal_candidates() if c.display_name.startswith('Meridian Stillness Field')]
    assert any(c.destination and c.destination.x==12 and c.destination.y==6 for c in candidates)


@pytest.mark.parametrize('dc,sealed',[(50,True),(-50,False)])
def test_heartbeats_does_not_deal_the_later_attack_damage(dc,sealed):
    _,engine,me,foe=_fight(P+'the_point_between_heartbeats',dc=dc,extra=IRON)
    _cast(engine,'The Point Between Heartbeats')
    assert foe.current_hp==2000 and not _damage(engine)
    assert engine._effective_speed(foe)==(0 if sealed else 15)
    assert bool(_conditions(foe,'incapacitated'))==sealed
    assert not any(m.target_field=='incoming_attack_mode' for m in me.modifiers.values())
    assert any(m.target_field=='incoming_attack_mode' for m in foe.modifiers.values())
    # Resolve two ordinary attacks to verify the existing next-attack consumer.
    me.action_available=True;_cast(engine,'Unarmed Strike')
    first=_rolls(engine,'ATTACK:')[-1]
    me.action_available=True;_cast(engine,'Unarmed Strike')
    second=_rolls(engine,'ATTACK:')[-1]
    assert first.mode=='ADVANTAGE' and second.mode=='NORMAL'


def test_heartbeats_failed_seal_expires_at_the_targets_turn_end():
    _,engine,me,foe=_fight(P+'the_point_between_heartbeats')
    _cast(engine,'The Point Between Heartbeats')
    engine.end_turn()
    assert _conditions(foe,'incapacitated')
    engine.end_turn()
    assert not _conditions(foe,'incapacitated')


def test_bulwark_sacrifices_the_protected_allies_aegis():
    key=W+'bulwark';bundle,engine,me,foe=_fight(key)
    ally=_ally(engine,me);_mark(engine,ally,'Persistent Aegis')
    tr.on_attacked(engine,foe,ally,{'attack_kind':'weapon','attack_bonus':40,'range_ft':5})
    assert not te.bears_mark(ally,ME,'Persistent Aegis')
    assert tr.defend(engine,ally,20,'SLASHING','test:attack',AN)==10


def test_buttress_does_not_heal_a_creature():
    _,engine,me,foe=_fight(W+'buttress')
    ally=_ally(engine,me);ally.current_hp-=20;hp=ally.current_hp
    _cast(engine,'Buttress',target_id=ally.entity_id)
    assert ally.current_hp==hp


def test_heaven_sheltering_aegis_resists_all_damage():
    _,engine,me,foe=_fight(W+'heaven_sheltering_aegis')
    ally=_ally(engine,me)
    _cast(engine,'Heaven-Sheltering Aegis',target_id=ally.entity_id)
    for damage_type in ('FIRE','SLASHING','PSYCHIC'):
        assert tr.defend(engine,ally,20,damage_type,'test:attack',AN)==10


def test_wall_inheritance_requires_its_printed_cost_and_fight_limit():
    key=W+'the_wall_that_remains_after_heaven_breaks';bundle,engine,me,foe=_fight(key)
    row=next(r for r in bundle['typed_reactions'] if r.get('feature_id')==key)
    me.resources['resource:core.qi']=14
    assert not tr._generic_affordable(engine,me,row)
    me.resources['resource:core.qi']=20
    assert tr._generic_affordable(engine,me,row)
    tr._spend_generic(engine,me,row)
    assert me.resources['resource:core.qi']==5
    me.resources['resource:core.qi']=20
    assert not tr._generic_affordable(engine,me,row)


@pytest.mark.parametrize('cl,dice',[(1,'1d8+2'),(5,'2d8+2'),(11,'3d8+2'),(17,'4d8+2')])
def test_puppet_strike_damage_scales(cl,dice):
    _,engine,me,foe=_fight('PUPPETRY_BASE_PUPPET_STRIKE',cl=cl)
    # "Make a Puppetry attack roll from the puppet vessel's space": a native kit needs the vessel up.
    _vessel(engine,me)
    _cast(engine,'Puppet Strike')
    assert _damage(engine)==[dice]


def test_thread_the_object_does_not_move_its_user():
    _,engine,me,foe=_fight('PUPPETRY_BASE_THREAD_THE_OBJECT')
    movement=me.movement_remaining_ft
    _cast(engine,'Thread the Object')
    assert me.movement_remaining_ft==movement


def test_borrowed_body_senses_blind_and_deafen_the_user():
    _,engine,me,foe=_fight(U+'borrowed_body_performance')
    _cast(engine,'Borrowed Body Performance')
    assert _conditions(me,'blinded') and _conditions(me,'deafened')


def test_string_hook_waits_for_movement_to_roll_its_save():
    _,engine,me,foe=_fight(U+'enemy_string_hook')
    _vessel(engine,me)
    _cast(engine,'Puppet Strike','Enemy String Hook')
    assert not _rolls(engine,'SAVE:') and me.resources['resource:core.qi']==98


def test_corpse_runner_does_not_increase_the_users_speed():
    _,engine,me,foe=_fight(U+'forbidden_corpse_puppet_method')
    _vessel(engine,me)
    _cast(engine,'Puppet Strike','Runner’s Feet')
    assert engine._effective_speed(me)==me.speed_ft


@pytest.mark.parametrize('dc,grappled,marked',[(50,True,False),(-50,False,True)])
def test_grasping_marionette_marks_only_a_successful_save(dc,grappled,marked):
    _,engine,me,foe=_fight(U+'grasping_marionette',dc=dc)
    _cast(engine,'Grasping Marionette')
    assert bool(_conditions(foe,'grappled'))==grappled
    assert te.bears_mark(foe,ME,'Tension Mark')==marked


def test_grasping_marionette_allows_dexterity():
    _,engine,me,foe=_fight(U+'grasping_marionette')
    foe.saving_throws.update(STR=-100,DEX=100)
    _cast(engine,'Grasping Marionette')
    assert not _conditions(foe,'grappled') and te.bears_mark(foe,ME,'Tension Mark')


def test_operating_the_shell_does_not_trigger_destruction_consequences():
    _,engine,me,foe=_fight(U+'iron_coffin_puppet_shell')
    _cast(engine,'Iron-Coffin Puppet Shell')
    assert foe.current_hp==2000 and not _conditions(foe,'prone')


def test_joint_catching_needle_does_not_slow_before_movement():
    _,engine,me,foe=_fight(U+'joint_catching_needle')
    _vessel(engine,me)
    _cast(engine,'Puppet Strike')
    assert engine._effective_speed(foe)==foe.speed_ft
    assert te.bears_mark(foe,ME,'Tension Mark')


def test_knot_the_knee_spends_the_mark_without_an_extra_push():
    _,engine,me,foe=_fight(U+'knot_the_knee')
    _mark(engine,foe,'Tension Mark');position=foe.position.model_copy()
    tr.on_creature_event(engine,foe,'moved',moved_ft=10)
    assert _conditions(foe,'prone') and not te.bears_mark(foe,ME,'Tension Mark')
    assert foe.position==position


@pytest.mark.parametrize('foe_at,available',[((9,6),True),((10,6),False)])
def test_needle_rain_range_is_thirty_not_thirty_five(foe_at,available):
    _,engine,me,foe=_fight(U+'needle_rain_marionette',foe_at=foe_at)
    # The printed reach is measured from the puppet vessel, so the vessel is raised at the puppeteer's own square.
    _vessel(engine,me,near=me.position)
    choices=[c for c in engine.legal_candidates() if 'Needle Rain Marionette' in c.display_name]
    assert bool(choices)==available
    if available:_cast(engine,'Puppet Strike','Needle Rain Marionette');assert foe.current_hp<2000


def test_theater_domain_does_not_apply_vessel_destruction_at_cast():
    _,engine,me,foe=_fight(U+'puppet_theater_domain')
    ally=_ally(engine,me)
    _cast(engine,'Puppet Theater Domain')
    assert not _conditions(foe,'restrained') and not te.bears_mark(foe,ME,'Tension Mark')
    assert me.temporary_hp==0 and ally.temporary_hp==0


def test_self_marionette_requires_a_spent_mark_for_movement():
    _,engine,me,foe=_fight(U+'self_marionette_method')
    _vessel(engine,me)
    movement=me.movement_remaining_ft
    _cast(engine,'Puppet Strike')
    assert me.movement_remaining_ft==movement


@pytest.mark.parametrize('cl,dice',[(5,'2d8+2'),(11,'3d8+2'),(17,'4d8+2')])
def test_substitute_harm_reduces_without_rerolled_damage_to_an_ally(cl,dice):
    _,engine,me,foe=_fight(U+'substitute_harm_body',cl=cl)
    _vessel(engine,me)
    hp=me.current_hp
    remaining=tr.on_damage(engine,me,100,0,source_definition_id='test:attack',source_actor_id=AN)
    rolls=_rolls(engine,'GENERIC_AMOUNT:')
    assert len(rolls)==1 and rolls[0].expression==dice
    assert remaining==100-rolls[0].total and me.current_hp==hp
    assert me.resources['resource:core.qi']==99


def test_substitute_harm_cannot_reduce_damage_without_cp():
    _,engine,me,foe=_fight(U+'substitute_harm_body')
    _vessel(engine,me)
    me.resources['resource:core.qi']=0
    assert tr.on_damage(engine,me,100,0,source_definition_id='test:attack',source_actor_id=AN)==100
    assert me.reaction_available


def test_marionette_substitution_cannot_react_without_three_cp():
    _,engine,me,foe=_fight(U+'marionette_substitution_body')
    _vessel(engine,me)
    me.resources['resource:core.qi']=2
    tr.on_attacked(engine,foe,me,{'attack_kind':'weapon','attack_bonus':40,'range_ft':5})
    assert me.reaction_available and me.resources['resource:core.qi']==2


def test_incarnation_does_not_explode_a_vessel_at_activation():
    _,engine,me,foe=_fight(U+'thousand_puppet_incarnation')
    _cast(engine,'Thousand-Puppet Incarnation')
    assert foe.current_hp==2000 and not _rolls(engine,'SAVE:')
    assert not te.bears_mark(foe,ME,'Tension Mark')


def test_soul_thread_warning_does_not_mark_without_moving_a_vessel():
    _,engine,me,foe=_fight(U+'soul_thread_warning')
    tr.on_attacked(engine,foe,me,{'attack_kind':'weapon','attack_bonus':40,'range_ft':5})
    assert not te.bears_mark(foe,ME,'Tension Mark')


def test_thread_the_weapon_spends_tension_instead_of_cp():
    _,engine,me,foe=_fight(U+'thread_the_weapon')
    _mark(engine,foe,'Tension Mark')
    tr.on_attacked(engine,foe,me,{'attack_kind':'weapon','attack_bonus':40,'range_ft':5})
    assert not te.bears_mark(foe,ME,'Tension Mark')
    assert me.resources['resource:core.qi']==100
