"""Printed-text regressions for Qiweaving, Radiance, and Retribution."""
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
from tests import test_sys_resources_states as sys_k

ROOT=Path(__file__).resolve().parents[1]
AUTH=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
Q,R,T='TAL_QIWEAVING_','tianxia.talent.radiance.','TAL_RETRIBUTION_'

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

@pytest.mark.parametrize('cl,feet',[(1,60),(11,90),(17,90)])
def test_distant_modulation_reaches_its_printed_cl_band(cl,feet):
    _,e,me,foe=fight(Q+'DISTANT_MODULATION',cl=cl)
    foe.position=foe.position.model_copy(update={'x':min(18,3+feet//5)})
    cast(e,'Qi Bond',contains='Distant Modulation')
    assert te.bears_mark(foe,ME,'qi_bond')
    assert action(e,'Qi Bond + Distant Modulation').range_ft==feet

def test_meridian_grammar_extends_qi_bond():
    _,e,me,foe=fight(Q+'MERIDIAN_GRAMMAR');foe.position=foe.position.model_copy(update={'x':14})
    cast(e,'Qi Bond');assert te.bears_mark(foe,ME,'qi_bond')
    assert action(e,'Qi Bond').range_ft==60

@pytest.mark.parametrize('cl',[5,11])
def test_stable_modulation_only_changes_the_first_concentration_save(cl):
    from combat.concentration import save_mode
    _,e,me,_=fight(Q+'STABLE_MODULATION',cl=cl)
    cast(e,'Turbulent Field',contains='Stable Modulation')
    assert save_mode(e,me)=='ADVANTAGE'
    assert save_mode(e,me) is None

def test_stable_modulation_at_cl11_remains_through_next_turn_end():
    from combat.concentration import save_mode
    _,e,me,_=fight(Q+'STABLE_MODULATION',cl=11)
    cast(e,'Turbulent Field',contains='Stable Modulation');e.end_turn();e.end_turn()
    assert save_mode(e,me)=='ADVANTAGE'

@pytest.mark.parametrize('cl,radius',[(1,5),(5,10),(11,15),(17,20)])
def test_turbulent_field_scales_and_waits_for_a_paid_activation(cl,radius):
    _,e,me,_=fight(Q+'TURBULENT_FIELD',cl=cl);cast(e,'Turbulent Field')
    assert not rolls(e,'SAVE')
    assert zones.typed_zones(e)[0].trigger_profile['size_ft']==radius

def test_turbulent_backlash_penalizes_only_the_next_concentration_save(monkeypatch):
    # The Backlash is the sys Qi-instability plug-in's (combat/ext/qi_instability.py): it fires when a hostile creature fails the
    # Field's own save, so the failed save is driven through the sys Turbulent Field squad rather than through a typed modifier.
    # The foe's paid technique is Binding Word (Target: One creature, 2 CP, no damage); Lattice Unraveling, which the sys squad used
    # before, prints a formation/ward target and no creature (the round15 reconcile makes the same change in the sys tests).
    from combat.concentration import save_mode
    k=sys_k
    monkeypatch.setattr(k,'LATTICE','TAL_FATE_BINDING_WORD',raising=False)
    e=k._storm('TURBULENT_FIELD','TURBULENT_BACKLASH',friends=0);foe=e.state.actors[k.TFOE]
    k._use(e,'Turbulent Field');k._fixed(e,1);k._act(e,k.TFOE,'Binding Word',k.ME)
    assert save_mode(e,foe)=='DISADVANTAGE';assert save_mode(e,foe) is None

def test_dawnlit_rebuke_spends_its_printed_cp():
    _,e,me,foe=fight('RADIANCE_TAL_DAWNLIT_REBUKE');a=ally(e,me);mark(e,foe,'Dawnmark')
    before=me.resources['resource:core.qi'];tr.on_damage(e,a,10,0,'review:hit',AN)
    assert not me.reaction_available and foe.current_hp<2000
    assert me.resources['resource:core.qi']==before-1

@pytest.mark.parametrize('marked,qi',[(False,100),(True,0)])
def test_dawnlit_rebuke_needs_its_mark_and_cp(marked,qi):
    _,e,me,foe=fight('RADIANCE_TAL_DAWNLIT_REBUKE');a=ally(e,me)
    if marked:mark(e,foe,'Dawnmark')
    me.resources['resource:core.qi']=qi;tr.on_damage(e,a,10,0,'review:hit',AN)
    assert me.reaction_available and foe.current_hp==2000

@pytest.mark.parametrize('dc',[1,50])
def test_heaven_opening_judgment_places_marks_and_failure_healing_denial(dc):
    _,e,me,foe=fight('RADIANCE_TAL_HEAVEN_OPENING_JUDGMENT',dc=dc)
    cast(e,'Heaven-Opening Judgment');assert te.bears_mark(foe,ME,'Dawnmark')
    hp=foe.current_hp;te.run_effects(context(e,'Heaven-Opening',foe),[{'type':'healing','applies_to':'target','flat':10}])
    assert foe.current_hp==hp+(10 if dc==1 else 0)
    e.end_turn();e.end_turn()
    assert te.bears_mark(foe,ME,'Dawnmark')==(dc==50)

def test_sun_white_spear_does_not_blind_an_ordinary_target():
    _,e,me,foe=fight('RADIANCE_TAL_SUN_WHITE_JUDGMENT_SPEAR');cast(e,'Sun-White')
    assert foe.current_hp<2000 and te.bears_mark(foe,ME,'Dawnmark')
    assert not has(foe,'blinded') and not has(foe,'reaction_denied')

def save_vs_charm(e,name,subject):
    from combat.ext.save_against import save_against
    return save_against(context(e,name,subject),subject,'WIS',{'charmed'})

def test_consecrated_boundary_does_not_slow_ordinary_creatures_and_benefit_ends_on_exit():
    _,e,me,foe=fight(R+'consecrated_boundary');a=ally(e,me);cast(e,'Consecrated Boundary',at=(3,7))
    assert not zones.difficult_cells(e,foe)
    assert save_vs_charm(e,'Consecrated Boundary',a)['modes']==['ADVANTAGE']
    a.position=a.position.model_copy(update={'x':20});zones.sync_inside(e)
    assert not save_vs_charm(e,'Consecrated Boundary',a)

def test_court_of_dawn_waits_for_the_save_and_keeps_resistance_inside():
    _,e,me,foe=fight(R+'court_of_unshadowed_dawn');a=ally(e,me);cast(e,'Court')
    assert foe.current_hp==2000 and not has(foe,'blinded') and not has(foe,'reaction_denied')
    assert a.temporary_hp==0
    assert any(m.target_field=='damage_resistance' for m in a.modifiers.values())
    e._commit_damage(a,20,'NECROTIC','review:hit',AN,None,reaction_depth=0)
    assert a.current_hp==1990
    a.position=a.position.model_copy(update={'x':20});zones.sync_inside(e)
    assert not any(m.target_field=='damage_resistance' for m in a.modifiers.values())
    e._commit_damage(a,20,'NECROTIC','review:hit',AN,None,reaction_depth=0)
    assert a.current_hp==1970

def test_crown_prevents_blinded_until_concentration_ends():
    _,e,me,_=fight(R+'crown_of_the_unblinking_sun');cast(e,'Crown')
    ctx=context(e,'Crown',me);blind={'type':'condition','applies_to':'target','condition':'blinded'}
    te.run_effects(ctx,[blind]);assert not has(me,'blinded')
    e._end_concentration(me,'review');te.run_effects(ctx,[blind]);assert has(me,'blinded')

def test_gentle_dawn_adds_pb_and_key_modifier_in_one_thp_grant():
    _,e,me,_=fight(R+'gentle_dawn');a=ally(e,me);cast(e,'Gentle Dawn',target=a.entity_id)
    assert a.temporary_hp==6

def test_mercy_end_fear_does_not_apply_a_full_frightened_condition():
    """fix/hunt28 (33295c75, FIX28r2.review.md) enforces the caster's mark."""
    _,e,me,foe=fight(R+'mercy_of_morning');mark(e,me,'dawnmark')
    cast(e,'Mercy',contains='End Fear')
    assert not has(me,'frightened') and not has(foe,'frightened')

def test_mercy_grants_only_one_save_through_caster_next_end():
    """fix/hunt28 (33295c75, FIX28r2.review.md) enforces the caster's mark."""
    _,e,me,_=fight(R+'mercy_of_morning');a=ally(e,me);mark(e,a,'dawnmark')
    cast(e,'Mercy',contains='Advantage vs Charm',target=a.entity_id)
    e.end_turn();e.end_turn()
    assert save_vs_charm(e,'Mercy',a)['modes']==['ADVANTAGE']
    assert not save_vs_charm(e,'Mercy',a)

@pytest.mark.parametrize('choice,condition',[('End Poisoned','poisoned'),('End Charm or Fear','frightened')])
def test_purifying_cleanses_without_damaging_the_willing_target(choice,condition):
    _,e,me,foe=fight(R+'purifying_radiance');a=ally(e,me)
    e._apply_condition(a,'condition:typed.'+condition,'review',AN,expires_on='UNTIL_REMOVED')
    cast(e,'Purifying',contains=choice,target=a.entity_id)
    assert a.current_hp==2000 and not has(a,condition) and not rolls(e,'ATTACK')

@pytest.mark.parametrize('suffix,name',[
    ('searing_halo','Searing Halo'),('solar_radiance_form','Solar Radiance Form'),
    ('sever_the_possessing_shadow','Sever the Possessing Shadow')])
def test_radiance_effects_wait_for_their_printed_trigger(suffix,name):
    _,e,me,foe=fight(R+suffix);cast(e,name)
    assert foe.current_hp==2000 and not has(foe,'blinded') and not has(foe,'reaction_denied')

@pytest.mark.parametrize('cl,count',[(1,2),(11,4),(17,6)])
@pytest.mark.parametrize('dc',[1,50])
def test_solar_flare_uses_the_same_save_and_scaled_half_damage(cl,count,dc):
    _,e,me,foe=fight(R+'solar_flare',cl=cl,dc=dc,extras=('RADIANCE_TAL_BLINDING_FLASH',))
    # Blinding Flash affects chosen creatures, including legal friendly
    # recipients. This damage-sharing test explicitly chooses the AI's enemy
    # subset instead of relying on an ability-wide hostile geometry default.
    e.typed_control_modes={ME:'LOCAL_AUTO'}
    cast(e,'Blinding Flash',contains='Solar Flare')
    [damage]=rolls(e,'DAMAGE');assert damage.expression==f'{count}d6+0'
    assert len(rolls(e,'SAVE'))==1
    assert foe.current_hp==2000-(damage.total if dc==50 else damage.total//2)
    assert has(foe,'blinded')==(dc==50)

def test_resurrection_holds_at_one_and_removes_charm_without_moving_the_ally():
    _,e,me,foe=fight(R+'resurrection_of_the_morning_breath',pick=0);a=ally(e,me)
    a.current_hp=7;before=a.position
    e._apply_condition(a,'condition:typed.charmed','review',AN,expires_on='UNTIL_REMOVED')
    # Reviewed native rescue (4557070a) runs after final reductions and applies
    # its follow-up after DAMAGE_COMMITTED, instead of generic on_damage.
    from combat.gate2_runtime_models import ReactionDecision
    c = e.legal_candidates()[0]
    intent = ActionIntent(intent_id='review:rescue', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=ME)
    def answer_rescue(request):
        use = request['reaction_source_id'] == 'choice:needle.morning_breath'
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE' if use else 'DECLINE',
            option_ids=('charmed',) if use else ()), None
    e.set_reaction_provider(answer_rescue)
    e._commit_damage(a,20,'NECROTIC','review:hit',AN,intent,reaction_depth=0)
    assert a.current_hp==1 and not has(a,'charmed') and a.position==before
    assert not me.reaction_available

def test_resurrection_does_not_answer_an_unqualified_fire_hit():
    _,e,me,foe=fight(R+'resurrection_of_the_morning_breath',pick=0);a=ally(e,me);a.current_hp=7
    e._typed_pending_damage_type='FIRE'
    assert tr.on_damage(e,a,20,0,'review:hit',AN)==20 and me.reaction_available

def test_revealing_light_stealth_penalty_ends_on_exit():
    _,e,me,foe=fight(R+'revealing_light');cast(e,'Revealing Light')
    assert te.check_mode(foe,'DEX','stealth')=='DISADVANTAGE'
    foe.position=foe.position.model_copy(update={'x':20});zones.sync_inside(e)
    assert te.check_mode(foe,'DEX','stealth')=='NORMAL'

@pytest.mark.parametrize('dc',[1,50])
def test_world_of_morning_triggers_on_turn_start_not_creation_and_removes_ward_on_exit(dc):
    _,e,me,foe=fight(R+'world_of_revealed_morning',dc=dc);a=ally(e,me)
    cast(e,'World of Revealed Morning',at=(3,6))
    assert foe.current_hp==2000 and not rolls(e,'SAVE')
    assert a.temporary_hp==0 and any(m.target_field=='damage_resistance' for m in a.modifiers.values())
    zones.on_turn_start(e,foe)
    assert len(rolls(e,'SAVE'))==1 and foe.current_hp<2000
    assert has(foe,'blinded')==(dc==50) and has(foe,'reaction_denied')==(dc==1)
    e._end_concentration(me,'review')
    assert not any(m.target_field=='damage_resistance' for m in a.modifiers.values())

def resolve_prepared_attack(e,name='Counterstrike'):
    # The generic runtime has no Ready queue. Run the compiled payload at a GM-confirmed trigger.
    ctx=context(e,name,e.state.actors[AN])
    row=next(r for r in ctx.typed['effects'] if r['type']=='attack')
    te.run_effects(ctx,[{**row,'deferred':False}])

def test_counterstrike_preparation_does_not_attack_and_payload_has_weapon_damage():
    _,e,me,foe=fight('RETRIBUTION_BASE_COUNTERSTRIKE');cast(e,'Counterstrike')
    assert foe.current_hp==2000 and not rolls(e,'ATTACK')
    resolve_prepared_attack(e)
    assert rolls(e,'DAMAGE') and foe.current_hp<1996

def test_retribution_court_does_not_move_or_deny_reactions_on_creation():
    _,e,me,foe=fight(T+'COURT_OF_THE_AWAITING_BLADE');before=me.movement_remaining_ft;cast(e,'Court')
    assert me.movement_remaining_ft==before and not has(foe,'reaction_denied')

def test_liver_shot_sets_speed_to_five_and_ends_at_target_next_end():
    _,e,me,foe=fight(T+'LIVER_SHOT');resolve_prepared_attack(e,'Counterstrike + Liver Shot')
    assert e._effective_speed(foe)==5
    e.end_turn();assert e._effective_speed(foe)==5
    e.end_turn();assert e._effective_speed(foe)==foe.speed_ft

@pytest.mark.parametrize('cl,bonus',[(5,1),(11,2),(17,2)])
def test_tight_guard_cl_scaling(cl,bonus):
    _,e,me,foe=fight(T+'TIGHT_GUARD',cl=cl);before=e._ac_modifier(me);cast(e,'Counterstrike')
    assert e._ac_modifier(me)==before+bonus

def test_violent_pressure_reaches_30_feet():
    _,e,me,foe=fight(T+'VIOLENT_PRESSURE');foe.position=foe.position.model_copy(update={'x':9})
    cast(e,'Violent Pressure');assert has(foe,'frightened')

def test_dug_in_blow_does_not_grant_blanket_physical_resistance():
    _,e,me,foe=fight(T+'DUG_IN_BLOW');resolve_prepared_attack(e,'Counterstrike + Dug-In Blow')
    assert not any(m.target_field=='damage_resistance' for m in me.modifiers.values())

def test_haymaker_does_not_roll_the_later_constitution_save_on_hit():
    _,e,me,foe=fight(T+'HAYMAKER');resolve_prepared_attack(e,'Counterstrike + Haymaker')
    assert len(rolls(e,'SAVE'))==1
