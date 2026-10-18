"""Printed-text regressions for Jester, Karma, and Life."""
import pytest
import copy
import json
from functools import lru_cache
from pathlib import Path

from combat import typed_executor as te, typed_reactions as tr, zones
from combat.ext import karma_imprints
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET
from tests import test_sys_resources_states as sys_k

ROOT=Path(__file__).resolve().parents[1]
AUTH=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
J,K,L='tianxia.talent.jester.','tianxia.talent.karma.','tianxia.talent.life.'

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
def has(a,name):return any(c.condition_id.endswith('.'+name) for c in a.conditions.values())
def mark(e,a,name):e._apply_condition(a,te.mark_condition_id(name,ME),'test',ME,expires_on='UNTIL_REMOVED')
def stock_marks(e,*actors):
    for a in actors:
        for name in ['Debt Imprint','Grace Imprint','Karmic Imprint','Imprint','Foil']:mark(e,a,name)

def test_court_does_not_charm_its_audience():
    _,e,_,foe=fight(J+'court_of_words_without_offense');cast(e,'Court of Words')
    assert not has(foe,'charmed')

def test_painted_exit_does_not_bank_its_immediate_step_as_ordinary_movement():
    _,e,me,_=fight(J+'painted_exit');before=me.movement_remaining_ft;cast(e,'Painted Exit')
    # The optional immediate move defaults to staying put without a chosen square.
    assert me.movement_remaining_ft==before and not me.turn_flags.get('oa_free_ft')

def test_recluse_waits_for_punchline_movement_and_is_immune_to_charm_and_fear():
    _,e,me,_=fight(J+'recluse_at_court_incarnation');before=me.movement_remaining_ft;cast(e,'Recluse-at-Court')
    assert me.movement_remaining_ft==before
    a=next(a for a in e.action_catalog.values() if a.owner_id==ME and a.display_name=='Recluse-at-Court Incarnation')
    ctx=te.Context(e,me,a,None,a.parameters['typed'],[me],me,{})
    for name in ['charmed','frightened','poisoned']:te.block_condition(ctx,{'type':'condition','condition':name,'applies_to':'self'})
    assert not has(me,'charmed') and not has(me,'frightened') and has(me,'poisoned')

@pytest.mark.parametrize('dc',[1,50])
def test_masks_wait_for_enemy_start_and_do_not_grant_instant_movement(dc):
    _,e,me,foe=fight(J+'ten_thousand_masks_procession',dc=dc);before=me.movement_remaining_ft;cast(e,'Ten-Thousand Masks Procession: Become Flustered')
    assert me.movement_remaining_ft==before and not rolls(e,'SAVE')
    e.end_turn();assert len(rolls(e,'SAVE'))==1
    assert has(foe,'flustered')==(dc==50) and has(foe,'reaction_denied')==(dc==1)

def test_thousand_faces_does_not_hide_the_caster_before_a_punchline():
    _,e,me,_=fight(J+'thousand_faces_one_mistake');cast(e,'Set the Scene')
    assert not has(me,'invisible')

@pytest.mark.parametrize('dc',[1,50])
def test_whole_court_laughs_has_both_printed_save_results(tmp_path,dc):
    from tests.test_a2_jester import test_whole_court_next_check_and_duration
    # Real declared attack, reaction answer, final save, commit and cold reload.
    test_whole_court_next_check_and_duration(tmp_path,success=dc==1)

@pytest.mark.parametrize('key,name,choice,cost',[
    ('TAL_KARMA_INVOKE_THE_LEDGER','Invoke the Ledger','',1),
    ('TAL_KARMA_SETTLE_MINOR_ACCOUNT','Settle Minor Account','Debt',1),
    (K+'chain_of_consequence','Chain of Consequence','',5),
    (K+'debt_written_on_bone','Debt Written on Bone','Psychic Backlash',3),
    (K+'merit_becomes_armor','Merit Becomes Armor','',3),
    (K+'shared_merit','Shared Merit','',1)])
def test_karma_compound_cost_actions_charge_their_cp(key,name,choice,cost):
    _,e,me,foe=fight(key);a=ally(e,me);stock_marks(e,me,foe,a)
    for _ in range(2):mark(e,foe,'Debt Imprint')  # rider lane 9: Chain of Consequence needs (and spends) three Debt Imprints
    cast(e,name,contains=choice)
    assert me.resources['resource:core.qi']==100-cost

@pytest.mark.parametrize('cl,dice',[(1,1),(5,2),(11,3),(17,4)])
@pytest.mark.parametrize('choice,dc',[('Debt',50),('Debt',1),('Grace',50)])
def test_settle_minor_account_scales_damage_and_temporary_hp(cl,dice,choice,dc):
    _,e,me,foe=fight('TAL_KARMA_SETTLE_MINOR_ACCOUNT',cl=cl,dc=dc);a=ally(e,me);stock_marks(e,me,foe,a)
    cast(e,'Settle Minor Account',contains=choice,target=AN if choice=='Debt' else a.entity_id)
    r=rolls(e,'DAMAGE' if choice=='Debt' else 'TEMP_HP')[0]
    assert r.expression==f'{dice}d8+2'
    if choice=='Debt':
        assert foe.current_hp==2000-(r.total if dc==50 else r.total//2)
        assert has(foe,'reaction_denied')==(dc==50)
    else:assert a.temporary_hp==r.total

@pytest.mark.parametrize('key,cost',[(K+'grace_repaid',1),(K+'harm_returned',3),(K+'return_the_sting',1)])
def test_karma_damage_reactions_charge_their_cp(key,cost):
    _,e,me,foe=fight(key);a=ally(e,me);stock_marks(e,me,foe,a)
    # Harm Returned needs the striker to carry at least two of the Karma character's Debt Imprints (printed Trigger).
    assert karma_imprints.place(e,me,foe,'debt','TAL_KARMA_RECORD_THE_DEED','test')
    tr.on_damage(e,a,100,0,source_actor_id=AN)
    assert not me.reaction_available and me.resources['resource:core.qi']==100-cost

@pytest.mark.parametrize('cl,dice',[(1,1),(5,2),(11,3),(17,4)])
def test_grace_repaid_reduction_scales(cl,dice):
    _,e,me,foe=fight(K+'grace_repaid',cl=cl);a=ally(e,me);mark(e,a,'Grace Imprint')
    remaining=tr.on_damage(e,a,100,0,source_actor_id=AN);r=rolls(e,'GENERIC_AMOUNT')[0]
    assert r.expression==f'{dice}d8+2' and remaining==100-r.total

@pytest.mark.parametrize('cl,dice',[(1,0),(11,1),(17,2)])
def test_return_the_sting_includes_key_and_cl_dice(cl,dice):
    _,e,me,foe=fight(K+'return_the_sting',cl=cl);a=ally(e,me);mark(e,foe,'Debt Imprint')
    tr.on_damage(e,a,100,0,source_actor_id=AN)
    if dice:
        r=rolls(e,'DAMAGE')[0];assert r.expression==f'{dice}d8+6';expected=r.total
    else:expected=6
    assert foe.current_hp==2000-expected

@pytest.mark.parametrize('slug,cost,earned_thp',[
    ('grace_shelters_the_innocent',2,True),   # printed: THP = PB only because the 1d6 turned the failure into a success
    ('karmic_exchange',3,False),
    ('reversal_of_due_fortune',4,False)])
def test_roll_reactions_charge_cp_without_unearned_temporary_hp(slug,cost,earned_thp):
    # The printed triggers: a Grace Imprint carrier fails a save (Shelters), rolls a save (Exchange), rolls a natural 1 (Reversal).
    # They are driven through a real forced save on the sys Karma ledger squad, not through a stocked mark on the review's harness.
    k=sys_k
    e=k._ledger(K+slug);me,a=e.state.actors[k.ME],e.state.actors[k.ALLY]
    k._mark(e,k.ME,k.ALLY,'grace');qi=me.resources[k.QI]
    k._fixed(e,1 if slug=='reversal_of_due_fortune' else 5)
    dc=(1 if slug=='reversal_of_due_fortune' else 5)+a.saving_throws['DEX']+(10 if slug=='reversal_of_due_fortune' else 1)
    k._forced_save(e,k.TFOE,k.ALLY,'DEX',dc,damage=5)
    assert not me.reaction_available and me.resources[k.QI]==qi-cost
    assert a.current_hp==a.maximum_hp and not k._imprints(e,k.ALLY)  # the flipped save held: no damage, the Grace Imprint is spent
    assert me.temporary_hp==0 and a.temporary_hp==(me.proficiency_bonus if earned_thp else 0)

@pytest.mark.parametrize('dc',[1,50])
def test_karmic_mirror_cost_and_damage_branch(dc):
    _,e,me,foe=fight(K+'karmic_mirror',dc=dc);stock_marks(e,me,foe)
    tr.on_technique_start(e,foe,[me],{'numbers':{'_cost':1}})
    assert me.resources['resource:core.qi']==96 and not me.reaction_available
    assert foe.current_hp==2000-(6 if dc==1 else 0)

@pytest.mark.parametrize('dc',[1,50])
def test_chain_of_consequence_damage_waits_on_failure_and_has_full_success_amount(dc):
    _,e,me,foe=fight(K+'chain_of_consequence',dc=dc);stock_marks(e,me,foe)
    for _ in range(2):mark(e,foe,'Debt Imprint')  # rider lane 9: "Target: One creature carrying at least three of your Debt Imprints"
    cast(e,'Chain of Consequence')
    assert foe.current_hp==2000-(6 if dc==1 else 0)

@pytest.mark.parametrize('choice',['Psychic Backlash','Deny Reactions','Negate Advantage'])
def test_written_debt_does_not_fire_before_the_marked_creature_deals_damage(choice):
    bundle,e,me,foe=fight(K+'debt_written_on_bone');stock_marks(e,me,foe)
    if choice == 'Negate Advantage':
        # Unsupported choice is a visible GM rider, with no automatic variant.
        # Activating a real Debt action with that rider must not fire it early.
        rows=[a for a in bundle['action_catalog'] if 'Debt Written' in a['display_name']]
        assert rows and not any('Negate Advantage' in a['display_name'] for a in rows)
        assert all(any('no benefit from Advantage' in line for line in a['parameters']['typed']['riders']) for a in rows)
        qi=me.resources['resource:core.qi']
        cast(e,'Debt Written',contains='Psychic Backlash')
        assert me.resources['resource:core.qi']==qi-3
        assert has(foe,'karma_bone')  # the real delayed obligation is armed
        assert any('no benefit from Advantage' in line for a in e.action_catalog.values()
                   if 'Debt Written' in a.display_name for line in a.parameters['typed']['riders'])
    else:
        cast(e,'Debt Written',contains=choice)
    assert foe.current_hp==2000 and foe.reaction_available
    assert not foe.modifiers and not has(foe,'reaction_denied')

@pytest.mark.parametrize('key,name',[(K+'court_of_cause_and_effect','Court of Cause'),(K+'no_lie_before_the_ledger','No Lie'),(K+'trial_of_the_ledger','Trial of the Ledger')])
def test_karma_areas_and_trials_do_not_apply_untriggered_consequences(key,name):
    _,e,me,foe=fight(key);stock_marks(e,me,foe);cast(e,name)
    assert me.current_hp==foe.current_hp==2000 and me.temporary_hp==foe.temporary_hp==0

@pytest.mark.parametrize('dc',[1,50])
def test_ten_thousand_debts_wait_for_later_cause_on_failure(dc):
    _,e,me,foe=fight(K+'ten_thousand_debts_return_to_source',dc=dc);stock_marks(e,me,foe);cast(e,'Ten Thousand Debts')
    if dc==50:assert foe.current_hp==2000 and not rolls(e,'DAMAGE')
    else:assert rolls(e,'DAMAGE')[0].expression=='4d10+0' and foe.current_hp<2000

@pytest.mark.parametrize('slug,name', [('karma_sovereign_incarnation','Karma-Sovereign'),('karmic_sight','Karmic Sight')])
def test_karma_reading_and_incarnation_do_not_consume_marks(slug,name):
    _,e,me,foe=fight(K+slug);stock_marks(e,me,foe);before=[c.condition_id for c in me.conditions.values()]
    cast(e,name,target=ME)
    assert set(before)<={c.condition_id for c in me.conditions.values()}

@pytest.mark.parametrize('slug,name,thp',[('merit_becomes_armor','Merit Becomes Armor',0),('shared_merit','Shared Merit',6)])
def test_merit_uses_the_correct_grace_imprint_and_trigger(slug,name,thp):
    _,e,me,foe=fight(K+slug);a=ally(e,me);stock_marks(e,me,foe,a);cast(e,name,target=a.entity_id)
    assert not te.bears_mark(a,ME,'Grace Imprint') and te.bears_mark(a,ME,'Imprint')
    assert a.temporary_hp==thp

def test_borrowed_tomorrow_does_not_collect_the_future_burden_on_activation():
    _,e,me,foe=fight(K+'borrowed_tomorrow');a=ally(e,me)
    tr.on_damage(e,a,2001,0,source_actor_id=AN)
    assert not me.reaction_available and me.resources['resource:core.qi']==92
    assert me.current_hp==foe.current_hp==a.current_hp==2000 and not rolls(e,'DAMAGE')

def test_fate_deferred_does_not_grant_an_unprinted_one_hp_floor():
    _,e,me,foe=fight(K+'fate_deferred');a=ally(e,me)
    assert tr.on_damage(e,a,2001,0,source_actor_id=AN)==2001

@pytest.mark.parametrize('missing,expected',[(2,2),(10,4)])
def test_borrowed_breath_base_does_not_exceed_missing_hp(missing,expected):
    _,e,me,_=fight('LIFE_BASE_BORROWED_BREATH');a=ally(e,me);a.current_hp=a.maximum_hp-missing
    cast(e,'Borrowed Breath',target=a.entity_id);assert a.temporary_hp==expected

def test_borrowed_breath_is_not_offered_on_an_uninjured_target():
    """Rider lane 9: "Borrowed Breath can only be used on an injured target" (combat/ext/life_riders.py candidate_allowed)."""
    _,e,me,_=fight('LIFE_BASE_BORROWED_BREATH');a=ally(e,me);a.current_hp=a.maximum_hp
    assert not any(c.target_ids==(a.entity_id,) and getattr(e.action_catalog.get(c.source_definition_id),'display_name','')=='Borrowed Breath'
                   for c in e.legal_candidates())

@pytest.mark.parametrize('cl,expected',[(1,5),(5,10),(10,15),(15,20)])
def test_greater_invigorate_grants_realm_temporary_hp_at_full_hp(cl,expected):
    _,e,me,_=fight(L+'greater_invigorate',cl=cl);a=ally(e,me)
    cast(e,'Borrowed Breath',contains='Greater Invigorate',target=a.entity_id)
    assert a.temporary_hp==expected and me.resources['resource:core.qi']==99

@pytest.mark.parametrize('cl',[1,10,20])
def test_greater_mend_replaces_rolled_healing_with_five_cl_plus_key(cl):
    _,e,me,_=fight(L+'greater_mend',cl=cl);a=ally(e,me);a.current_hp=1000
    cast(e,'Mend the Pulse',contains='Greater Mend',target=a.entity_id)
    assert a.current_hp==1000+5*cl+2 and not rolls(e,'HEALING')
    assert me.resources['resource:core.qi']==98

def test_life_domain_does_not_heal_on_activation():
    _,e,me,foe=fight(L+'life_domain_hall_of_returning_breath');a=ally(e,me)
    for x in [me,foe,a]:x.current_hp=1000
    cast(e,'Life Domain');assert all(x.current_hp==1000 for x in [me,foe,a])

@pytest.mark.parametrize('cl,size',[(10,20),(15,30)])
def test_vital_court_radius_and_deferred_temporary_hp(cl,size):
    _,e,me,foe=fight(L+'vital_court_field',cl=cl);a=ally(e,me);cast(e,'Vital Court')
    assert all(x.temporary_hp==0 for x in [me,foe,a])
    assert zones.typed_zones(e)[0].trigger_profile['size_ft']==size

def test_soul_in_body_treatment_pays_two_additional_cp():
    _,e,me,_=fight(L+'soul_in_the_body_treatment');a=ally(e,me)
    cast(e,'Purify the Pulse',contains='Soul-in-the-Body',target=a.entity_id)
    assert me.resources['resource:core.qi']==97
