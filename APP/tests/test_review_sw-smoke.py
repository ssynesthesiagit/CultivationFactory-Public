"""Printed-rule engine regressions for Smoke, Sniper, and Sound."""
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

ROOT=Path(__file__).resolve().parents[1]
AUTH=json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
M,N,S='TAL_SMOKE_','TAL_SNIPER_','TAL_SOUND_'

@lru_cache(maxsize=None)
def _compiled(key,cl=20,dc=50,extra=()):
    sphere=AUTH[key]['sphere_id'];bases=[k for k,v in AUTH.items() if v.get('sphere_id')==sphere and v.get('kind')=='base_ability']
    return compile_character({**SHEET,
        'equipment':[{'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.gong_jian','quantity':1}]}}],
        'identity':{**SHEET['identity'],'cultivation_level':cl},
        'ability_scores_and_statistics':{**SHEET['ability_scores_and_statistics'],'technique_save_dc':dc,'technique_attack_bonus':40,'primary_resource':{'name':'Qi','maximum':100}},
        'spheres_and_talents':{'sphere_record_ids':[sphere],'learned_talent_record_ids':list(dict.fromkeys([*bases,key,*extra]))}},actor_id=ME)

def _fight(key,cl=20,dc=50,extra=(),foe_at=(5,6)):
    b=copy.deepcopy(_compiled(key,cl,dc,extra));e=_engine(b,foe_at=foe_at)
    me,foe=e.state.actors[ME],e.state.actors[AN]
    me.resources['resource:core.martial_focus']=1
    foe.maximum_hp=foe.current_hp=2000;foe.armor_class=-50
    return b,e,me,foe

def _cast(e,name,contains='',at=None,target=None):
    cs=[c for c in e.legal_candidates() if name in c.display_name and contains in c.display_name
        and (at is None or c.destination and (c.destination.x,c.destination.y)==at)
        and (target is None or target in c.target_ids)]
    assert cs,(name,contains)
    pos=e.state.actors[AN].position
    c=min(cs,key=lambda c:(0 if c.destination is None else abs(c.destination.x-pos.x)+abs(c.destination.y-pos.y),len(c.display_name)))
    e.execute_intent(ActionIntent(intent_id='review',decision_id=c.decision_id,candidate_id=c.candidate_id,
        state_version=c.state_version,actor_id=ME,target_ids=c.target_ids,destination=c.destination))

def _cond(actor,name):return [c for c in actor.conditions.values() if c.condition_id=='condition:typed.'+name]
def _rolls(e,kind):return [r for r in e.rolls if r.reason.startswith(kind)]
def _mark(e,target,name='Smoke Trace'):
    e._apply_condition(target,te.mark_condition_id(name,ME),'test:mark',ME,expires_on='UNTIL_REMOVED',data={'mark':name,'label':name})
def _react(b,e,me,foe,key):
    r=next(r for r in b['typed_reactions'] if r.get('feature_id')==key)
    tr._run_generic_effects(e,me,foe,r,r['effects'])
    return r
def _next(e,actor):
    e.end_turn();assert e.state.current_actor_id==actor.entity_id

def test_veil_does_not_move_its_creator():
    _,e,me,_=_fight('SMOKE_BASE_SMOKE_VEIL');before=me.movement_remaining_ft
    _cast(e,'Smoke Veil');assert me.movement_remaining_ft==before

@pytest.mark.parametrize('cl,count',[(1,1),(5,2),(11,3),(17,4)])
def test_cinder_wisp_scaling_and_trace_expiry(cl,count):
    _,e,me,foe=_fight(M+'CINDER_WISP',cl=cl);_cast(e,'Cinder Wisp')
    # Owner 2026-09-30: Cinder Wisp's main hit adds the Path key modifier (+2 in this sheet).
    assert _rolls(e,'DAMAGE:')[0].expression==f'{count}d6+2'
    assert te.bears_mark(foe,ME,'Smoke Trace')
    _next(e,foe);_next(e,me);e.end_turn()
    assert not te.bears_mark(foe,ME,'Smoke Trace')

def test_black_lung_does_not_debuff_at_cast():
    _,e,_,foe=_fight(M+'BLACK_LUNG_CLOUD');_cast(e,'Smoke Veil','Black-Lung')
    assert not _rolls(e,'SAVE:') and not _cond(foe,'poisoned')
    assert e._effective_speed(foe)==foe.speed_ft

def test_smoke_domain_is_aimed_dense_and_does_not_mark_at_cast():
    _,e,_,foe=_fight(M+'SMOKE_DOMAIN_COURT_OF_HIDDEN_WITNESSES')
    _cast(e,'Smoke Domain',at=(5,6))
    assert not te.bears_mark(foe,ME,'Smoke Trace')
    assert zones.typed_zones(e)[0].trigger_profile['obscured']=='heavy'

@pytest.mark.parametrize('dc',[-50,50])
def test_smother_spends_the_trace_on_both_save_results(dc):
    # The printed Smother the Breath now resolves on both results (AUTO43 2026-10-05). It used to deny Reactions on a
    # successful save only, leaving a failure with nothing at all, which this test asserted -- but the printed failed
    # save is the worse one: "Failed Save: ... It has Disadvantage on the triggering d20 Test if the trigger includes
    # one. If the trigger does not include a d20 Test, the creature cannot take Reactions until the start of its next
    # turn." Smothering a creature that spoke or breathed is that second branch (no d20 Test of its own), so both
    # results take the creature's Reaction away and it ends at the start of its next turn.
    key=M+'SMOTHER_THE_BREATH';b,e,me,foe=_fight(key,dc=dc);_mark(e,foe)
    _react(b,e,me,foe,key)
    assert not te.bears_mark(foe,ME,'Smoke Trace')
    assert _cond(foe,'reaction_denied')
    _next(e,foe)
    assert not _cond(foe,'reaction_denied')


def test_incense_body_does_not_place_an_immediate_trace():
    _,e,_,foe=_fight(M+'INCENSE_BODY_OF_THE_VANISHING_WITNESS',foe_at=(4,6))
    _cast(e,'Incense Body');assert not te.bears_mark(foe,ME,'Smoke Trace')

@pytest.mark.parametrize('dc',[-50,50])
def test_ashen_lung_does_not_deny_unrelated_reactions_or_buff_the_caster(dc):
    key=M+'ASHEN_LUNG_SEALS_THE_DRAGON_CRY';b,e,me,foe=_fight(key,dc=dc);_mark(e,foe)
    _react(b,e,me,foe,key)
    assert not _cond(foe,'reaction_denied') and not _cond(foe,'save_against')


def test_perfect_shot_requires_and_spends_focus():
    _,e,me,_=_fight(N+'PERFECT_SHOT');me.resources['resource:core.martial_focus']=0
    assert not any(c.display_name.startswith('Perfect Shot') for c in e.legal_candidates())
    me.resources['resource:core.martial_focus']=1;_cast(e,'Perfect Shot')
    assert me.resources['resource:core.martial_focus']==0

def test_severing_flight_requires_focus_and_grants_no_movement_or_ground_shove():
    key=N+'SEVERING_THE_FLIGHT_LINE';b,e,me,foe=_fight(key)
    row=next(r for r in b['typed_reactions'] if r.get('feature_id')==key)
    me.resources['resource:core.martial_focus']=0;assert not tr._generic_affordable(e,me,row)
    me.resources['resource:core.martial_focus']=1;before=me.movement_remaining_ft;pos=foe.position
    _react(b,e,me,foe,key)
    assert _rolls(e,'ATTACK:') and me.movement_remaining_ft==before and foe.position==pos

@pytest.mark.parametrize('dc',[-50,50])
def test_silencing_bell_cost_and_save_branches(dc):
    key=N+'SHOT_THAT_SILENCES_THE_BELL';b,e,me,foe=_fight(key,dc=dc)
    row=next(r for r in b['typed_reactions'] if r.get('feature_id')==key)
    me.resources['resource:core.martial_focus']=0;assert not tr._generic_affordable(e,me,row)
    me.resources['resource:core.martial_focus']=1;_react(b,e,me,foe,key)
    assert not _cond(foe,'reaction_denied')
    assert any(m.target_field=='attack_mode' and m.value=='DISADVANTAGE' for m in foe.modifiers.values())==(dc<0)

def test_arrow_inheritance_range_cost_and_once_per_fight():
    key='tianxia.talent.sniper.the_arrow_that_arrived_before_the_bowstring';b,e,me,foe=_fight(key,foe_at=(6,6))
    action=next(a for a in b['action_catalog'] if 'The Arrow That' in a['display_name'])
    assert action['range_ft']==5280 and action['parameters']['typed']['range_ft']==5280
    me.resources['resource:core.martial_focus']=0
    assert not any(c.display_name.startswith('The Arrow That') for c in e.legal_candidates())
    me.resources['resource:core.martial_focus']=1;_cast(e,'The Arrow That','Line Through the Eye')
    assert foe.current_hp<2000 and me.resources['resource:core.qi']==97 and me.resources['resource:core.martial_focus']==0
    me.action_available=True;me.resources['resource:core.martial_focus']=1;me.resources['resource:core.qi']=100
    assert not any(c.display_name.startswith('The Arrow That') for c in e.legal_candidates())

@pytest.mark.parametrize('cl,count',[(5,1),(11,2),(17,2)])
def test_bell_shell_reduction_scales(cl,count):
    key=S+'BELL_SHELL_GUARD';b,e,me,_=_fight(key,cl=cl)
    row=next(r for r in b['typed_reactions'] if r.get('feature_id')==key and r['kind']=='ally_damaged')
    reduced,_=tr._generic_damage_reduction(e,me,row,100)
    assert e.rolls[-1].expression==f'{count}d8+2' and reduced==100-e.rolls[-1].total

@pytest.mark.parametrize('slug,name',[('BELL_THAT_BREAKS_THE_FORMATION','Bell That Breaks'),('SHATTER_VESSEL','Shatter Vessel')])
def test_object_attacks_do_not_damage_creatures(slug,name):
    # riders lane 5 2026-09-29: both now run against placed objects (combat/ext/objects.py), so they are no longer offered
    # against a creature at all (they used to be offered and do nothing)
    _,e,_,foe=_fight(S+slug)
    assert not [c for c in e.legal_candidates() if name in c.display_name and AN in c.target_ids]
    assert foe.current_hp==2000 and not _rolls(e,'ATTACK:') and not _rolls(e,'DAMAGE:')

@pytest.mark.parametrize('cl,count',[(5,2),(11,4),(17,6)])
def test_harmonic_healing_scales(cl,count):
    _,e,me,_=_fight(S+'HARMONIC_HEALING_TONE',cl=cl)
    ally=me.model_copy(deep=True);ally.entity_id='review:ally';ally.position=me.position.model_copy(update={'y':7})
    ally.maximum_hp=500;ally.current_hp=1;e.state.actors[ally.entity_id]=ally
    _cast(e,'Harmonic Healing',target=ally.entity_id)
    assert e.rolls[-1].expression==f'{count}d8+2' and ally.current_hp==1+e.rolls[-1].total

@pytest.mark.parametrize('cl,count',[(1,1),(5,2),(11,3),(17,4)])
def test_resonant_note_damage_and_mark(cl,count):
    _,e,me,foe=_fight(S+'RESONANT_NOTE',cl=cl);_cast(e,'Resonant Note','Deafen')
    assert _rolls(e,'DAMAGE:')[0].expression.removesuffix('+0')==f'{count}d8'
    assert te.bears_mark(foe,ME,'Resonance')
    _next(e,foe);_next(e,me);assert not te.bears_mark(foe,ME,'Resonance')

@pytest.mark.parametrize('slug,name,cl,count,sides',[
    ('RESONANT_SHATTER','Resonant Shatter',5,5,8),('RESONANT_SHATTER','Resonant Shatter',11,7,8),('RESONANT_SHATTER','Resonant Shatter',17,9,8),
    ('THUNDERING_VOICE','Thundering Voice',1,2,6),('THUNDERING_VOICE','Thundering Voice',5,3,6),('THUNDERING_VOICE','Thundering Voice',11,5,6),('THUNDERING_VOICE','Thundering Voice',17,7,6)])
@pytest.mark.parametrize('dc',[-50,50])
def test_sound_damage_scales_on_both_save_results(slug,name,cl,count,sides,dc):
    _,e,_,foe=_fight(S+slug,cl=cl,dc=dc);_cast(e,name)
    r=_rolls(e,'DAMAGE:')[0]
    assert r.expression.removesuffix('+0')==f'{count}d{sides}'
    assert 2000-foe.current_hp==(r.total if dc>0 else r.total//2)


def test_sonic_cage_needs_resonance_and_no_thunder_means_no_save_penalty():
    _,e,_,foe=_fight(S+'SONIC_CAGE')
    assert not any(c.display_name.startswith('Sonic Cage') for c in e.legal_candidates())
    _mark(e,foe,'Resonance');_cast(e,'Sonic Cage')
    assert _cond(foe,'restrained') and not _cond(foe,'save_against')

def test_sound_sovereign_does_not_deny_reactions_at_activation():
    _,e,me,foe=_fight(S+'SOUND_SOVEREIGN_INCARNATION',foe_at=(4,6));_cast(e,'Sound-Sovereign')
    assert me.reaction_available and foe.reaction_available
    assert not _cond(me,'reaction_denied') and not _cond(foe,'reaction_denied')

@pytest.mark.parametrize('dc',[-50,50])
def test_steal_voice_failed_save_silences_until_source_next_end(dc):
    _,e,me,foe=_fight(S+'STEAL_VOICE',dc=dc);_cast(e,'Steal Voice')
    assert bool(_cond(foe,'silenced'))==(dc>0)
    if dc>0:
        _next(e,foe);_next(e,me);assert _cond(foe,'silenced')
        e.end_turn();assert not _cond(foe,'silenced')

@pytest.mark.parametrize('cl,feet',[(5,30),(11,60),(17,90)])
def test_soundwalk_level_range_moves_on_the_board(cl,feet):
    _,e,me,_=_fight(S+'SOUNDWALK_STEP',cl=cl)
    me.position=me.position.model_copy(update={'x':1,'y':1});dest=(1+feet//5,1)
    _cast(e,'Soundwalk Step',at=dest)
    assert (me.position.x,me.position.y)==dest

@pytest.mark.parametrize('slug,name',[('WORLD_RINGING_NOTE','World-Ringing Note'),('WORLD_SPLITTING_SCREAM','World-Splitting Scream')])
def test_sound_line_hits_second_lane(slug,name):
    # A separate Range longer than the line places its origin at the aim point.
    # World-Splitting Scream still aims its self-origin line by its endpoint.
    aim = (4,6) if slug == 'WORLD_RINGING_NOTE' else (12,6)
    _,e,_,foe=_fight(S+slug,foe_at=(6,7));_cast(e,name,at=aim)
    assert foe.current_hp<2000


@pytest.mark.parametrize('slug,name,damage,condition_name',[
    ('RESONANCE_FIELD','Resonance Field',True,None),
    ('COURT_OF_THE_WORLD_RINGING_BELL','Court of the World-Ringing Bell: Ringing Court',True,None),  # lane 5: one action per court
    ('FORBIDDEN_SILENCE_FIELD','Forbidden Silence Field',False,'silenced'),
    ('SILENCE_THAT_SWALLOWS_THUNDER','Silence That Swallows Thunder',False,'silenced'),
    ('TEN_THOUSAND_ECHOES_FIELD','Ten-Thousand Echoes Field',False,'reaction_denied')])
def test_domains_wait_for_start_turn(slug,name,damage,condition_name):
    _,e,me,foe=_fight(S+slug);before=me.movement_remaining_ft
    _cast(e,name)
    assert not _rolls(e,'SAVE:') and foe.current_hp==2000 and me.movement_remaining_ft==before
    zones.on_turn_start(e,foe)
    assert len(_rolls(e,'SAVE:'))==1
    assert (foe.current_hp<2000)==damage
    if condition_name:assert _cond(foe,condition_name)
    if condition_name=='silenced':
        _next(e,foe);foe.position=foe.position.model_copy(update={'x':19,'y':1})
        _next(e,me);assert _cond(foe,'silenced')
        _next(e,foe);assert not _cond(foe,'silenced')
