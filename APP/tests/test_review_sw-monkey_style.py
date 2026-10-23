"""Printed-text regressions for Monkey Style, Music, and Poison."""
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
M,U,P='TAL_MONKEY_STYLE_','tianxia.talent.music.','tianxia.talent.poison.'

@lru_cache(maxsize=None)
def compiled(key,cl=20,dc=50,extras=(),pick=None):
    sphere=AUTH[key]['sphere_id']
    bases=[k for k,v in AUTH.items() if v.get('sphere_id')==sphere and v.get('kind')=='base_ability']
    return compile_character({**SHEET,
        'equipment':[{'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.'+name,'quantity':1} for name in ('jian','gun','gong_jian')]}}],
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
    me.resources['resource:core.stamina']=100
    me.resource_maximums['resource:core.stamina']=100
    return b,e,me,foe

def cast(e,name,at=None,target=None,contains=''):
    # Carrying all three test weapons no longer makes all three readied.
    # Prepare the intended attack legally before matching menu candidates,
    # rather than accidentally choosing a setup button for an unavailable hit.
    from tests.equipment_readiness import ready_weapon
    # These are now paid choices after a real hit/save, not separate attacks.
    if name == 'Deliver the Dose' and contains in ('Numbing Dose', 'Paralytic Dose', 'Venom in', 'Venomous Strike'):
        from combat.gate2_runtime_models import ReactionDecision
        def choose(request):
            options = tuple(request.get('legal_option_ids') or ())
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE' if options else 'DECLINE',
                option_ids=options[:1]), None
        e.set_reaction_provider(choose)
        contains = ''
    if name == 'Coated Weapon':
        ready_weapon(e, 'Jian')
        name = 'Coat a Weapon'
    attacks=[a for a in e.action_catalog.values() if a.owner_id==ME and name in a.display_name
             and contains in a.display_name and any(x.get('type')=='attack'
             for x in (a.parameters.get('typed') or {}).get('effects') or [])]
    if attacks:
        ready_weapon(e,min(attacks,key=lambda a:len(a.display_name)).display_name)
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
def has(a,name):return any(c.condition_id.endswith('.'+name) for c in a.conditions.values())
def mark(e,a,name):e._apply_condition(a,te.mark_condition_id(name,ME),'test',ME,expires_on='UNTIL_REMOVED')

def action(e,name):
    return min((a for a in e.action_catalog.values() if a.owner_id==ME and name in a.display_name),key=lambda a:len(a.display_name))

def context(e,name,target):
    a=action(e,name)
    return te.Context(e,e.state.actors[ME],a,None,a.parameters['typed'],[target],target,{})

@pytest.mark.parametrize('suffix,name',[
    ('COURT_OF_THE_LAUGHING_SAGE','Court of the Laughing Sage'),
    ('GREAT_SAGE_EQUAL_TO_HEAVEN','Great Sage'),
    ('STAFF_SWING_STEP','Capering Footwork + Staff-Swing')])
def test_monkey_movement_waits_for_the_printed_trigger(suffix,name):
    _,e,me,_=fight(M+suffix);before=me.movement_remaining_ft;cast(e,name)
    assert me.movement_remaining_ft==before and not rolls(e,'SAVE')

def test_golden_hoop_activation_does_not_move_an_enemy_or_force_its_save():
    _,e,me,foe=fight(M+'GOLDEN_HOOP_STAFF');before=foe.position;cast(e,'Golden Hoop')
    assert foe.position==before and not rolls(e,'SAVE')

def test_heaven_bridge_does_not_damage_the_user_on_activation():
    _,e,me,_=fight(M+'HEAVEN_BRIDGE_SWING');cast(e,'Capering Footwork',contains='Heaven-Bridge')
    assert me.current_hp==2000

@pytest.mark.parametrize('dc',[1,50])
def test_uprooting_staff_hits_the_printed_area(dc):
    _,e,me,foe=fight(M+'HEAVEN_UPROOTING_STAFF',dc=dc)
    other=foe.model_copy(deep=True);other.entity_id='review:other';other.position=other.position.model_copy(update={'x':6})
    e.state.actors[other.entity_id]=other;cast(e,'Heaven-Uprooting')
    assert foe.current_hp<2000 and other.current_hp<2000
    assert has(foe,'prone')==(dc==50) and has(other,'prone')==(dc==50)

def linked(e,me):
    """A Monkey Link in hand (rider lane 10: a special attack's save is its Finish, "If you have a Monkey Link, you may spend it")."""
    from combat.ext import monkey
    monkey.create(e,me,'test','test',counted=False)

def moved(e,me,feet=10):
    """Vaulting Strike's "Requirement: You moved at least 10 feet this turn before making the attack" (rider lane 10)."""
    start=me.position
    c=next(c for c in e.legal_candidates() if c.display_name.startswith('Move to ') and c.destination
           and max(abs(c.destination.x-start.x),abs(c.destination.y-start.y))*5==feet and abs(c.destination.x-4)+abs(c.destination.y-6)>=1
           and max(abs(c.destination.x-4),abs(c.destination.y-6))<=1)
    e.execute_intent(ActionIntent(intent_id='move',decision_id=c.decision_id,candidate_id=c.candidate_id,
        state_version=c.state_version,actor_id=ME,target_ids=c.target_ids,destination=c.destination))

@pytest.mark.parametrize('dc',[1,50])
def test_laughing_trip_has_normal_staff_damage_and_a_success_only_slow(dc):
    _,e,me,foe=fight(M+'LAUGHING_TRIP',dc=dc);linked(e,me);cast(e,'Laughing Trip')
    assert rolls(e,'DAMAGE') and foe.current_hp<2000
    assert e._effective_speed(foe)==foe.speed_ft-(10 if dc==1 else 0)
    assert has(foe,'prone')==(dc==50)

def test_laughing_trip_does_not_slow_a_missed_target():
    _,e,_,foe=fight(M+'LAUGHING_TRIP');foe.armor_class=100;cast(e,'Laughing Trip')
    assert foe.current_hp==2000 and e._effective_speed(foe)==foe.speed_ft

@pytest.mark.parametrize('cl,count',[(1,2),(5,3),(11,4),(17,5)])
def test_stone_skipping_damage_and_its_own_range(cl,count):
    _,e,me,foe=fight(M+'STONE_SKIPPING_STRIKE',cl=cl);me.position=me.position.model_copy(update={'x':1})
    cast(e,'Stone-Skipping')
    assert rolls(e,'DAMAGE')[0].expression==f'{count}d6+2'
    a=action(e,'Stone-Skipping');assert a.range_ft==90 and a.parameters['typed']['range_ft']==30

def test_monkey_uprising_waits_for_enemy_activity_and_denies_reactions_only_inside():
    _,e,me,foe=fight(M+'THOUSAND_MONKEY_UPRISING');cast(e,'Thousand-Monkey')
    assert foe.current_hp==2000 and not has(foe,'prone') and not rolls(e,'SAVE')
    assert any(row.get('no_reactions') for row in te.condition_rules(foe))
    foe.position=foe.position.model_copy(update={'x':20});zones.sync_inside(e)
    assert not any(row.get('no_reactions') for row in te.condition_rules(foe))

@pytest.mark.parametrize('dc',[1,50])
def test_vaulting_strike_has_normal_weapon_damage_and_success_movement(dc):
    _,e,me,foe=fight(M+'VAULTING_STRIKE',dc=dc);moved(e,me);linked(e,me);before=me.movement_remaining_ft;cast(e,'Vaulting Strike')
    assert len(rolls(e,'DAMAGE'))==2
    assert me.movement_remaining_ft==before+(5 if dc==1 else 0)

def test_battle_cadence_does_not_damage_its_performer():
    _,e,me,foe=fight(U+'battle_cadence');cast(e,'Keep the Measure',contains='Battle Cadence')
    assert me.current_hp==2000
    cast(e,'Jian')
    assert foe.current_hp==2000-rolls(e,'DAMAGE')[0].total-4 and me.current_hp==2000

def test_captivating_melody_repeats_the_save_and_ends_all_failed_save_restrictions():
    _,e,me,foe=fight(U+'captivating_melody');cast(e,'Captivating Melody')
    assert e._effective_speed(foe)==foe.speed_ft-10
    assert any(r.get('no_reactions') for r in te.condition_rules(foe))
    e.end_turn();foe.saving_throws['WIS']=100;e.end_turn()
    assert e._effective_speed(foe)==foe.speed_ft
    assert not any(r.get('no_reactions') for r in te.condition_rules(foe))

def test_captivating_melody_success_ends_at_target_next_start():
    _,e,_,foe=fight(U+'captivating_melody',dc=1);cast(e,'Captivating Melody')
    assert has(foe,'reaction_denied');e.end_turn();assert not has(foe,'reaction_denied')

@pytest.mark.parametrize('choice',['No Reactions','Speed 0'])
def test_concerto_riders_last_until_caster_next_start(choice):
    _,e,_,foe=fight(U+'concerto_of_broken_breath');cast(e,'Concerto',contains=choice)
    assert has(foe,'reaction_denied') if choice=='No Reactions' else e._effective_speed(foe)==0
    e.end_turn();assert has(foe,'reaction_denied') if choice=='No Reactions' else e._effective_speed(foe)==0
    # At the end of the holder turn, before the caster starts again, the rider still remains.
    e._expire_typed_for_checkpoint('END_OF_TURN',AN)
    assert has(foe,'reaction_denied') if choice=='No Reactions' else e._effective_speed(foe)==0

@pytest.mark.parametrize('choice',['No Reactions','Speed -10'])
def test_disruptive_harmony_ends_at_target_next_start(choice):
    key=U+'disruptive_harmony';_,e,me,foe=fight(key,pick=1 if choice=='No Reactions' else 2)
    tr.on_technique_start(e,foe,[],{'numbers':{'_cost':1}})
    assert not me.reaction_available
    assert has(foe,'reaction_denied') if choice=='No Reactions' else e._effective_speed(foe)==foe.speed_ft-10
    e.end_turn()
    assert not has(foe,'reaction_denied') and e._effective_speed(foe)==foe.speed_ft

def test_healing_hymn_does_not_heal_before_caster_turn_end():
    _,e,me,_=fight(U+'healing_hymn');a=ally(e,me);a.current_hp=1000;cast(e,'Healing Hymn')
    assert a.current_hp==1000 and not rolls(e,'HEALING')

@pytest.mark.parametrize('dc',[1,50])
def test_heartstring_does_not_turn_one_support_feature_into_blanket_reaction_denial(dc):
    _,e,_,foe=fight(U+'heartstring_severing_prelude',dc=dc);cast(e,'Heartstring')
    assert has(foe,'reaction_denied')==(dc==1)
    if dc==1:
        e.end_turn();assert has(foe,'reaction_denied')
        e.end_turn();assert not has(foe,'reaction_denied')

def test_funeral_bell_defers_death_trigger_save_but_imposes_concentration_disadvantage():
    from combat import concentration
    _,e,_,foe=fight(U+'immortal_funeral_bell');cast(e,'Immortal Funeral Bell')
    assert not rolls(e,'SAVE') and concentration.save_mode(e,foe)=='DISADVANTAGE'

def test_march_does_not_move_anyone_before_a_hit():
    _,e,me,_=fight(U+'march_of_the_immortal_host');a=ally(e,me);before=(me.movement_remaining_ft,a.movement_remaining_ft)
    cast(e,'March of the Immortal Host');assert (me.movement_remaining_ft,a.movement_remaining_ft)==before

@pytest.mark.parametrize('cl,count',[(1,1),(11,2),(17,3)])
def test_rhythmic_guard_uses_level_scaled_reduction(cl,count):
    _,e,me,_=fight(U+'rhythmic_guard',cl=cl);a=ally(e,me)
    # "You must be Keeping the Measure" (rider lane 10: combat/ext/music.py)
    e._apply_condition(me,'condition:typed.music_measure','test',ME,expires_on='UNTIL_REMOVED')
    amount=tr.on_damage(e,a,100,0,source_actor_id=AN)
    r=rolls(e,'GENERIC_AMOUNT')[0];assert r.expression==f'{count}d8+2' and amount==100-r.total

@pytest.mark.parametrize('cl,count',[(5,4),(11,6),(17,8)])
@pytest.mark.parametrize('dc',[1,50])
def test_shattering_chorus_scales_both_save_results(cl,count,dc):
    _,e,_,foe=fight(U+'shattering_chorus',cl=cl,dc=dc);cast(e,'Shattering Chorus')
    r=rolls(e,'DAMAGE')[0];assert r.expression==f'{count}d6+0'
    assert foe.current_hp==2000-(r.total if dc==50 else r.total//2)

def test_spirit_calling_prevents_invisibility_instead_of_granting_it():
    _,e,_,foe=fight(U+'spirit_calling_tune');cast(e,'Spirit-Calling Tune',contains='Prevent Invisibility')
    assert not has(foe,'invisible')
    ctx=context(e,'Spirit-Calling Tune',foe);te.block_condition(ctx,{'type':'condition','condition':'invisible','applies_to':'target'})
    assert not has(foe,'invisible')

@pytest.mark.parametrize('choice',['Movement of War','Movement of Courage','Movement of Silence'])
def test_symphony_mercy_does_not_heal_on_activation(choice):
    # Rider lane 10: the two movements are a choose-two menu (combat/ext/menus.py); Mercy heals at the end of your turns (combat/ext/music.py).
    from combat.ext import menus
    _,e,me,_=fight(U+'symphony_of_heaven_and_earth');a=ally(e,me);a.current_hp=1000
    menus.pick(e,me,'music_symphony','Movement of Mercy','test');menus.pick(e,me,'music_symphony',choice,'test')
    cast(e,'Symphony of Heaven');assert a.current_hp==1000 and not rolls(e,'HEALING')

def test_appraising_venom_does_not_poison_anyone():
    _,e,me,foe=fight('POISON_BASE_APPRAISE_THE_VENOM');a=ally(e,me);cast(e,'Appraise the Venom')
    assert not any(has(x,'poisoned') for x in [me,foe,a])

@pytest.mark.parametrize('dc',[1,50])
def test_deliver_the_dose_mark_and_check_penalty_require_failed_save(dc):
    _,e,_,foe=fight('POISON_BASE_DELIVER_THE_DOSE',dc=dc);cast(e,'Deliver the Dose')
    assert te.bears_mark(foe,ME,'Dose Mark')==(dc==50)
    assert any(r.get('check_mode') for r in te.condition_rules(foe))==(dc==50)

def test_antidote_art_removes_poisoned_and_charges_only_one_cp():
    _,e,me,_=fight(P+'antidote_art');a=ally(e,me)
    te.block_condition(context(e,'Appraise',a),{'type':'condition','condition':'poisoned','applies_to':'target'})
    cast(e,'Appraise',contains='End Poisoned',target=a.entity_id)
    assert not has(a,'poisoned') and me.resources['resource:core.qi']==99 and a.temporary_hp==0

def test_bitter_trace_keeps_the_printed_save_as_the_default_table_choice():
    _,e,_,foe=fight(P+'bitter_trace',dc=1);cast(e,'Deliver the Dose')
    assert rolls(e,'SAVE') and not te.bears_mark(foe,ME,'Dose Mark')
    assert not any(r.get('check_mode') for r in te.condition_rules(foe))

def test_bitter_trace_default_preserves_the_failed_save_disadvantage():
    _,e,_,foe=fight(P+'bitter_trace',dc=50);cast(e,'Deliver the Dose')
    assert rolls(e,'SAVE') and te.bears_mark(foe,ME,'Dose Mark')
    assert any(r.get('check_mode') for r in te.condition_rules(foe))

def test_bitter_trace_is_an_optional_table_choice_that_replaces_the_save():
    _,e,_,foe=fight(P+'bitter_trace')
    choices=[c for c in e.legal_candidates() if 'Deliver the Dose' in c.display_name]
    assert any(c.display_name == 'Deliver the Dose' for c in choices)
    variant=next(c for c in choices if 'Bitter Trace' in c.display_name)
    e.execute_intent(ActionIntent(intent_id='review-bitter-trace',decision_id=variant.decision_id,
        candidate_id=variant.candidate_id,state_version=variant.state_version,actor_id=ME,
        target_ids=variant.target_ids,destination=variant.destination))
    assert not rolls(e,'SAVE') and te.bears_mark(foe,ME,'Dose Mark')
    assert not any(r.get('check_mode') for r in te.condition_rules(foe))

def _dose_buttons(e):
    from combat.tabletop import engine_button_description
    return {a.display_name:engine_button_description(a.model_dump(mode='json')) for a in e.action_catalog.values()
            if a.owner_id==ME and 'Deliver the Dose' in a.display_name}

def test_the_bitter_trace_button_explains_the_trade_it_makes_not_the_save_it_removes():
    _,e,_,_=fight(P+'bitter_trace')
    buttons=_dose_buttons(e)
    # The base keeps its printed rules: the target still makes a Constitution saving throw.
    assert 'Constitution saving throw' in buttons['Deliver the Dose'] and 'Failed Save' in buttons['Deliver the Dose']
    text=buttons['Deliver the Dose + Bitter Trace']
    # What it replaces, what it keeps, what it costs -- the base's own text never says any of this.
    assert 'Constitution save' in text and 'removed' in text
    assert 'Poison or Acid damage' in text
    assert '1 Dose Mark' in text and 'no save to fail' in text
    assert 'Disadvantage' in text and 'Cost:' in text
    assert 'immune' in text  # the printed immunity restriction travels with the button
    assert 'Failed Save' not in text  # the removed save may not be promised by its own replacement

def test_the_ai_prefers_the_guaranteed_bitter_trace_over_the_save_gated_dose():
    from combat.gate4_context import build_decision_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary
    _,e,_,_=fight(P+'bitter_trace')
    context=build_decision_context(e,PolicyLibrary(ROOT).for_actor(ME)[0],for_ai=True)
    choice=LocalDeterministicController().choose_primary_action(context)
    rows={c.display_name:c for c in context.legal_candidates if 'Deliver the Dose' in c.display_name}
    base,variant=rows['Deliver the Dose'],rows['Deliver the Dose + Bitter Trace']
    scores={s.candidate_id:s.total for s in choice.record.scored_alternatives}
    # A mark the target can save against and a mark that always lands are not worth the same to the AI.
    # Equal scores are the bug: the choice would then be settled by candidate id hash (review MMX19).
    #
    # The mark's utility is no longer folded into expected_damage, because the controller also reads
    # that number as its enemy-HP finishing threshold and a Mark deals no damage (MMX38). The
    # preference itself needs a score component that is not the damage estimate, in the locked
    # controller. The reviewed lock21 reliable-mode seam now supplies that component.
    assert scores[variant.candidate_id]>scores[base.candidate_id]
    assert choice.intent.candidate_id==variant.candidate_id

def test_bitter_trace_still_deals_the_ordinary_attack_damage():
    _,e,_,foe=fight(P+'bitter_trace',dc=50);before=foe.current_hp
    cast(e,'Deliver the Dose',contains='Bitter Trace')
    assert foe.current_hp<before and te.bears_mark(foe,ME,'Dose Mark')

@pytest.mark.parametrize('hit',[True,False])
def test_black_antidote_does_not_grant_damage_without_a_stored_trace(hit):
    _,e,_,foe=fight(P+'black_antidote_method');foe.armor_class=-50 if hit else 100;cast(e,'Deliver the Dose')
    if hit:assert foe.current_hp==2000-rolls(e,'DAMAGE')[0].total
    else:assert foe.current_hp==2000

def test_coating_a_weapon_does_not_hurt_or_mark_its_recipient():
    _,e,me,foe=fight(P+'coated_weapon');a=ally(e,me);cast(e,'Coated Weapon')
    assert all(x.current_hp==2000 and not te.bears_mark(x,ME,'Dose Mark') for x in [me,foe,a])
    assert not rolls(e,'SAVE')

@pytest.mark.parametrize('dc',[1,50])
def test_corrosive_dose_never_grants_resistance_and_success_penalty_is_one_attack(dc):
    _,e,_,foe=fight(P+'corrosive_dose',dc=dc);cast(e,'Deliver the Dose',contains='Corrosive Dose')
    assert not any(m.target_field=='damage_resistance' for m in foe.modifiers.values())
    assert e._ac_modifier(foe)==-1
    if dc==1:
        e._append_event('ATTACK_ROLLED','test',actor_id=ME,target_ids=(AN,))
        assert e._ac_modifier(foe)==0

def test_numbing_dose_has_its_successful_save_slow():
    _,e,_,foe=fight(P+'numbing_dose',dc=1);cast(e,'Deliver the Dose',contains='Numbing Dose')
    assert e._effective_speed(foe)==foe.speed_ft-5 and not has(foe,'reaction_denied')

def test_paralytic_dose_sets_speed_to_zero_on_failure():
    _,e,_,foe=fight(P+'paralytic_dose');cast(e,'Deliver the Dose',contains='Paralytic Dose')
    assert e._effective_speed(foe)==0 and has(foe,'reaction_denied')

def test_miasma_flight_is_not_walking_speed_or_free_movement_or_automatic_poison():
    _,e,me,foe=fight(P+'miasma_form');before=me.movement_remaining_ft;cast(e,'Miasma Form')
    assert e._effective_speed(me)==me.speed_ft and me.movement_remaining_ft==before and not has(foe,'poisoned')

@pytest.mark.parametrize('slug,name,count,sides',[
    ('poison_domain','Poison Domain',2,8),('toxic_cloud','Toxic Cloud',7,6),
    ('ten_thousand_poison_wind','Ten Thousand Poison Wind',8,8)])
@pytest.mark.parametrize('dc',[1,50])
def test_poison_zones_wait_for_turn_start_and_trigger_only_once(slug,name,count,sides,dc):
    _,e,me,foe=fight(P+slug,dc=dc);before=me.movement_remaining_ft;cast(e,name)
    assert foe.current_hp==2000 and me.movement_remaining_ft==before and not rolls(e,'SAVE')
    e.end_turn();r=rolls(e,'DAMAGE')[0]
    assert r.expression==f'{count}d{sides}+0' and foe.current_hp==2000-(r.total if dc==50 else r.total//2)
    hp=foe.current_hp;zones.on_turn_start(e,foe);assert foe.current_hp==hp
    if slug=='poison_domain':assert te.bears_mark(foe,ME,'Dose Mark')==(dc==50)
    else:assert has(foe,'poisoned')==(dc==50)

@pytest.mark.parametrize('dc',[1,50])
def test_venom_in_a_bloodied_wound_has_both_mark_results(dc):
    _,e,_,foe=fight(P+'venom_in_the_wound',dc=dc);foe.current_hp=500;cast(e,'Deliver the Dose',contains='Venom in')
    assert te.bears_mark(foe,ME,'Toxin Burden')==(dc==50)
    assert len(rolls(e,'SAVE'))==2

def test_venom_in_the_wound_does_not_add_a_save_to_a_healthy_target():
    _,e,_,foe=fight(P+'venom_in_the_wound');cast(e,'Deliver the Dose',contains='Venom in')
    assert len(rolls(e,'SAVE'))==1 and not te.bears_mark(foe,ME,'Toxin Burden')

def test_venom_sovereign_does_not_nuke_at_cast_or_turn_flight_into_movement():
    _,e,me,foe=fight(P+'venom_sovereign_incarnation');before=me.movement_remaining_ft;cast(e,'Venom-Sovereign')
    assert foe.current_hp==2000 and me.movement_remaining_ft==before
    te.block_condition(context(e,'Venom-Sovereign',me),{'type':'condition','condition':'poisoned','applies_to':'self'})
    assert not has(me,'poisoned')

@pytest.mark.parametrize('cl,count',[(1,1),(11,2),(17,3)])
@pytest.mark.parametrize('dc',[1,50])
def test_venomous_strike_has_scaling_and_its_own_save(cl,count,dc):
    _,e,_,foe=fight(P+'venomous_strike',cl=cl,dc=dc);cast(e,'Deliver the Dose',contains='Venomous Strike')
    assert len(rolls(e,'SAVE'))==2 and rolls(e,'DAMAGE')[1].expression==f'{count}d6+0'
    assert has(foe,'poisoned')==(dc==50)
