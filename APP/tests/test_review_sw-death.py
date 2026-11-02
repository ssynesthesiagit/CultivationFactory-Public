"""Printed-text regressions for Death, Destruction, and Disease."""
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
D, X, I = 'TAL_DEATH_', 'tianxia.talent.destruction.', 'tianxia.talent.disease.'


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
        'learned_talent_record_ids': list(dict.fromkeys([*bases, key]))}}, actor_id=ME,
        summon_plan={'lesser_corpse_servant': 0} if key == D+'DEATHLY_PASSAGE' else None)


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


def _target_damage_rolls(e, target_id=AN):
    ids={event.payload['roll_id'] for event in e.events if event.event_type=='DAMAGE_ROLLED' and target_id in event.target_ids}
    return [r for r in e.rolls if r.roll_id in ids]


def _ally(e, me):
    ally = me.model_copy(deep=True); ally.entity_id = 'review:ally'
    ally.position = ally.position.model_copy(update={'y': 7}); e.state.actors[ally.entity_id] = ally
    return ally


def _mark(e, target):
    e._apply_condition(target,te.mark_condition_id('Contagion Token',ME),'test',ME,expires_on='UNTIL_REMOVED')


def test_bone_bastion_does_not_give_an_ally_the_objects_defenses():
    _,e,me,_=_fight(D+'BONE_BASTION');ally=_ally(e,me)
    _cast(e,'Bone Bastion',target=ally.entity_id)
    assert ally.temporary_hp==0
    assert not any(m.target_field=='damage_immunity' for m in ally.modifiers.values())


def test_bone_ward_does_not_add_the_grave_object_bonus_without_an_object():
    _,e,me,foe=_fight(D+'BONE_WARD');ally=_ally(e,me)
    remaining=tr.on_damage(e,ally,100,0,source_actor_id=AN)
    rolls=[r for r in e.rolls if r.expression.startswith('3d8')]
    assert len(rolls)==1 and 100-remaining==rolls[0].total
    assert me.resources['resource:core.qi']==99


@pytest.mark.parametrize('key,name,cl,count,sides',[
    (D+'CORPSE_EXPLOSION','Corpse Explosion',11,6,6),
    (D+'CORPSE_EXPLOSION','Corpse Explosion',17,8,6),
    (D+'SOUL_FUNERAL','Soul Funeral',17,8,8),
    ('DISEASE_BASE_SOW_THE_FEVER_SEED','Sow the Fever Seed',5,2,8),
    ('DISEASE_BASE_SOW_THE_FEVER_SEED','Sow the Fever Seed',10,3,8),
    ('DISEASE_BASE_SOW_THE_FEVER_SEED','Sow the Fever Seed',15,4,8)])
def test_printed_damage_progression(key,name,cl,count,sides):
    _,e,_,foe=_fight(key,cl)
    if key == D+'SOUL_FUNERAL':
        foe.creature_types = ('ghost',)  # Printed target: ghost/undead/possessing/soul-bound only.
    if key == D+'CORPSE_EXPLOSION':
        from combat.gate2_runtime_models import RuntimeObjectState
        e._update_object(RuntimeObjectState(object_id='object:test.corpse', object_kind='corpse',
                         position=foe.position, unattended=True, flammable=False, ac=10, current_hp=1, maximum_hp=1), 'test:corpse')
    _cast(e,name)
    # Sow's printed damage adds the Path key modifier: this fixture has CON 14.
    bonus = 2 if key == 'DISEASE_BASE_SOW_THE_FEVER_SEED' else 0
    assert any(r.expression==f'{count}d{sides}+{bonus}' and r.total == sum(r.dice) + bonus
               for r in _rolls(e))


def test_grave_court_waits_for_enemy_start():
    _,e,_,foe=_fight(D+'COURT_OF_THE_NINTH_GRAVE');_cast(e,'Court of the Ninth Grave: Necrotic Damage')
    assert not _rolls(e,'SAVE:') and foe.current_hp==2000
    e.end_turn();assert foe.current_hp<2000


def test_deathly_passage_is_not_an_unrestricted_teleport():
    _,e,me,_=_fight(D+'DEATHLY_PASSAGE');before=me.position.model_copy()
    assert not any('Deathly Passage' in c.display_name for c in e.legal_candidates())
    assert me.position==before


@pytest.mark.parametrize('dc',[-50,50])
def test_death_incarnation_does_not_damage_on_cast_or_increase_walking_speed(dc):
    _,e,me,foe=_fight(D+'DEATH_SOVEREIGN_INCARNATION',dc=dc)
    _cast(e,'Death-Sovereign Incarnation');assert foe.current_hp==2000 and e._effective_speed(me)==me.speed_ft
    e.end_turn();assert len(_rolls(e))==1
    assert te._reduced_healing(e,foe,20)==(0 if dc>0 else 20)
    foe.position=foe.position.model_copy(update={'x':19,'y':1})
    e.end_turn();assert te._reduced_healing(e,foe,20)==(0 if dc>0 else 20)
    e.end_turn();assert te._reduced_healing(e,foe,20)==20


def test_grave_chill_success_still_reduces_healing():
    _,e,_,foe=_fight(D+'GRAVE_CHILL',dc=-50);_cast(e,'Grave Chill')
    assert te._reduced_healing(e,foe,20)==16
    e.end_turn();e.end_turn();assert te._reduced_healing(e,foe,20)==20


def test_death_incarnation_aura_moves_with_its_user():
    _,e,me,foe=_fight(D+'DEATH_SOVEREIGN_INCARNATION');_cast(e,'Death-Sovereign Incarnation')
    start=me.position.model_copy();me.position=me.position.model_copy(update={'x':15,'y':10})
    zones.on_moved(e,me,start,me.position)
    e.end_turn();assert foe.current_hp==2000


def test_grave_tax_cannot_grant_zero_reduction_rewards_unconditionally():
    _,e,me,foe=_fight(D+'GRAVE_TAX');tr.on_creature_event(e,foe,'healed')
    assert me.resources['resource:core.qi']==96
    assert not any('grave_mark' in c.condition_id for c in foe.conditions.values())


@pytest.mark.parametrize('end',['repeat','concentration'])
def test_mortality_seal_restrictions_end_together(end):
    _,e,me,foe=_fight(D+'MORTALITY_SEAL');_cast(e,'Mortality Seal')
    assert te._reduced_healing(e,foe,20)==0
    e._grant_temp_hp(foe,20,'test',ME);assert foe.temporary_hp==0
    if end=='repeat':
        e.end_turn();foe.saving_throws['CON']=1000;e.end_turn()
    else:e._end_concentration(me,'TEST')
    assert te._reduced_healing(e,foe,20)==20
    e._grant_temp_hp(foe,20,'test',ME);assert foe.temporary_hp==20


def test_mortality_seal_success_halves_healing_only_until_caster_start():
    _,e,_,foe=_fight(D+'MORTALITY_SEAL',dc=-50);_cast(e,'Mortality Seal')
    assert te._reduced_healing(e,foe,20)==10
    e._grant_temp_hp(foe,20,'test',ME);assert foe.temporary_hp==20
    e.end_turn();e.end_turn();assert te._reduced_healing(e,foe,20)==20


@pytest.mark.parametrize('dc',[-50,50])
def test_no_return_healing_and_temp_hp_follow_the_save_and_deadline(dc):
    _,e,_,foe=_fight(D+'NO_RETURN_EDICT',dc=dc);_cast(e,'No Return Edict')
    assert te._reduced_healing(e,foe,20)==(0 if dc>0 else 10)
    e._grant_temp_hp(foe,20,'test',ME);assert foe.temporary_hp==(0 if dc>0 else 20)
    e.end_turn();e.end_turn();assert te._reduced_healing(e,foe,20)==(0 if dc>0 else 20)
    e.end_turn();assert te._reduced_healing(e,foe,20)==20


@pytest.mark.parametrize('end',['repeat','concentration'])
def test_soul_hook_speed_zero_ends_on_save_or_concentration(end):
    _,e,me,foe=_fight(D+'SOUL_HOOK')
    foe.creature_types = ('ghost',)  # Keep the expiry test on an eligible printed target.
    _cast(e,'Soul Hook');assert e._effective_speed(foe)==0
    if end=='repeat':
        e.end_turn();foe.saving_throws['CHA']=1000;e.end_turn()
    else:e._end_concentration(me,'TEST')
    assert e._effective_speed(foe)==foe.speed_ft


def test_throne_does_not_hurt_its_caster_when_activated():
    _,e,me,_=_fight(D+'THRONE_OF_BORROWED_BONES');_cast(e,'Throne of Borrowed Bones')
    assert me.current_hp==2000


@pytest.mark.parametrize('cl,count',[(5,3),(11,5),(17,7)])
@pytest.mark.parametrize('dc',[-50,50])
def test_withering_field_waits_for_start_scales_and_uses_target_start_expiry(cl,count,dc):
    _,e,_,foe=_fight(D+'WITHERING_FIELD',cl,dc);_cast(e,'Withering Field',at=(4,6))
    assert foe.current_hp==2000
    e.end_turn();assert [r.expression for r in _target_damage_rolls(e)]==[f'{count}d6+0']
    assert te._reduced_healing(e,foe,20)==(10 if dc>0 else 20)
    foe.position=foe.position.model_copy(update={'x':19,'y':1})
    e.end_turn();assert te._reduced_healing(e,foe,20)==(10 if dc>0 else 20)
    e.end_turn();assert te._reduced_healing(e,foe,20)==20


def test_withering_hand_reduces_healing_on_hit():
    _,e,_,foe=_fight(D+'WITHERING_HAND');_cast(e,'Withering Hand')
    assert te._reduced_healing(e,foe,20)==16


@pytest.mark.parametrize('key,name,moment',[(X+'calamity_curtain','Calamity Curtain','enter'),(X+'wandering_calamity','Wandering Calamity','enter')])
def test_destructive_hazards_do_not_hit_on_appearance(key,name,moment):
    _,e,_,foe=_fight(key,foe_at=(8,6));_cast(e,name,at=(8,6));assert foe.current_hp==2000
    made=zones.typed_zones(e);assert len(made)==1
    assert [(c.x,c.y) for c in made[0].affected_cells]==[(8,6)]
    assert made[0].trigger_profile['triggers'][0]['on']==[moment]
    foe.position=foe.position.model_copy(update={'x':9,'y':6})
    start=foe.position.model_copy();foe.position=foe.position.model_copy(update={'x':8,'y':6})
    zones.on_moved(e,foe,start,foe.position);assert foe.current_hp<2000
    hp=foe.current_hp;zones.on_moved(e,foe,start,foe.position);assert foe.current_hp==hp


def test_calamity_incarnation_has_a_long_rest_limit():
    _,e,_,_=_fight(X+'calamity_sovereign_incarnation');_cast(e,'Calamity-Sovereign Incarnation')
    e.end_turn();e.end_turn();assert not any('Calamity-Sovereign Incarnation' in c.display_name for c in e.legal_candidates())


def test_world_ending_line_pays_three_cp_and_has_printed_dimensions():
    _,e,me,_=_fight(X+'world_ending_line');_cast(e,'World-Ending Line')
    assert me.resources['resource:core.qi']==97
    a=next(a for a in e.action_catalog.values() if 'World-Ending Line' in a.display_name)
    # Keep the printed geometry and the general SOL140 harmful-area policy.
    assert a.range_ft==300 and a.parameters['typed']['area']=={
        'shape':'line','size_ft':300,'width_ft':10,'recipients':'hostile','exclude_self':True}


@pytest.mark.parametrize('cl,count',[(1,1),(5,2),(10,3),(15,4)])
@pytest.mark.parametrize('dc',[-50,50])
def test_outbreak_veil_waits_for_start_and_scales_by_realm(cl,count,dc):
    _,e,_,foe=_fight('DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL',cl,dc)
    _cast(e,'Outbreak Mode',at=(4,6));assert foe.current_hp==2000
    e.end_turn();assert [r.expression for r in _rolls(e)]==[f'{count}d6+0']
    assert bool(_cond(foe,'sickened'))==(dc>0)


@pytest.mark.parametrize('cl,count',[(5,1),(10,2),(15,3)])
@pytest.mark.parametrize('dc',[-50,50])
def test_contaminated_wound_scales_and_reduces_healing_on_both_saves(cl,count,dc):
    _,e,_,foe=_fight(I+'contaminated_wound',cl,dc)
    _cast(e,'Sow the Fever Seed + Contaminated Wound')
    assert any(r.expression==f'{count}d6+0' for r in _rolls(e))
    pb=next(a for a in e.action_catalog.values() if 'Contaminated Wound' in a.display_name).parameters['typed']['numbers']['pb']
    assert te._reduced_healing(e,foe,20)==20-pb


@pytest.mark.parametrize('cl',[5,10,15])
def test_fever_symptom_failed_save_sickens_and_only_core_adds_key_damage(cl):
    _,e,_,foe=_fight(I+'fever_symptom',cl);_cast(e,'Sow the Fever Seed + Fever Symptom')
    assert _cond(foe,'sickened')
    _,control,_,other=_fight('DISEASE_BASE_SOW_THE_FEVER_SEED',cl);_cast(control,'Sow the Fever Seed')
    assert other.current_hp-foe.current_hp==(2 if cl>=10 else 0)


def test_fever_symptom_success_reduces_only_next_healing_and_expires():
    _,e,_,foe=_fight(I+'fever_symptom',dc=-50);_cast(e,'Sow the Fever Seed + Fever Symptom')
    assert te._reduced_healing(e,foe,20)==16 and te._reduced_healing(e,foe,20)==20
    _,e,_,foe=_fight(I+'fever_symptom',dc=-50);_cast(e,'Sow the Fever Seed + Fever Symptom')
    e.end_turn();e.end_turn();assert te._reduced_healing(e,foe,20)==20


@pytest.mark.parametrize('dc',[-50,50])
def test_malaise_symptom_obeys_both_save_branches(dc):
    _,e,_,foe=_fight(I+'malaise_symptom',dc=dc);_cast(e,'Sow the Fever Seed + Malaise Symptom')
    assert e._effective_speed(foe)==foe.speed_ft-(10 if dc>0 else 5)
    assert bool(_cond(foe,'reaction_denied'))==(dc>0)
    assert te.check_mode(foe,'STR','Athletics')==('DISADVANTAGE' if dc>0 else 'NORMAL')
    e.end_turn();e.end_turn();assert e._effective_speed(foe)==foe.speed_ft


def test_living_plague_creation_is_not_a_free_infected_strike():
    _,e,_,foe=_fight(I+'living_plague');_cast(e,'Living Plague')
    assert foe.current_hp==2000 and not _rolls(e,'ATTACK:')


@pytest.mark.parametrize('cl,count',[(5,2),(10,3),(15,4)])
def test_parasite_failed_save_waits_for_start_and_ends_on_repeat_save(cl,count):
    _,e,_,foe=_fight(I+'parasite_seed',cl);_cast(e,'Parasite Seed')
    assert foe.current_hp==2000
    e.end_turn();assert [r.expression for r in _rolls(e)]==[f'{count}d6+0']
    assert any(c.condition_id==te.mark_condition_id('Contagion Token',ME) for c in foe.conditions.values())
    foe.saving_throws['CON']=1000;e.end_turn();assert not _cond(foe,'disease_parasite')
    hp=foe.current_hp;e.end_turn();assert foe.current_hp==hp


def test_parasite_success_deals_scaled_damage_once_without_parasite():
    _,e,_,foe=_fight(I+'parasite_seed',15,-50);_cast(e,'Parasite Seed')
    assert [r.expression for r in _rolls(e)]==['4d6+0'] and not _cond(foe,'disease_parasite')
    hp=foe.current_hp;e.end_turn();assert foe.current_hp==hp


@pytest.mark.parametrize('key,name',[(I+'plague_bearing_body','Plague-Bearing Body'),(I+'plague_sovereign_incarnation','Plague-Sovereign Incarnation')])
def test_plague_transformations_grant_temporary_sickened_immunity(key,name):
    _,e,me,foe=_fight(key);_cast(e,name)
    assert te.condition_immune(e,me,'sickened')
    action=next(a for a in e.action_catalog.values() if name==a.display_name)
    te.run_effects(te.Context(e,foe,action,None,{'numbers':{},'duration':{'kind':'instant'}},[me],me,{}),[{'type':'condition','condition':'sickened','applies_to':'target'}])
    assert not _cond(me,'sickened') and foe.current_hp==2000 and e._effective_speed(me)==me.speed_ft
    for _ in range(20):e.end_turn()
    assert not te.condition_immune(e,me,'sickened')


@pytest.mark.parametrize('cl,count',[(10,5),(15,7)])
@pytest.mark.parametrize('dc',[-50,50])
def test_plague_eruption_waits_for_start_and_has_no_free_token_damage(cl,count,dc):
    _,e,_,foe=_fight(I+'plague_eruption',cl,dc);_cast(e,'Plague Eruption',at=(4,6))
    assert foe.current_hp==2000
    e.end_turn();assert [r.expression for r in _rolls(e)]==[f'{count}d6+0']
    assert bool(_cond(foe,'sickened'))==(dc>0)


def test_purging_breath_removes_the_casters_token():
    _,e,me,_=_fight(I+'purging_breath');ally=_ally(e,me);_mark(e,ally)
    _cast(e,'Purging Breath: Remove Contagion Token',target=ally.entity_id)
    assert not any(c.condition_id==te.mark_condition_id('Contagion Token',ME) for c in ally.conditions.values())


def test_quarantine_ward_is_paid_and_does_not_grant_unqualified_damage_resistance():
    _,e,me,foe=_fight(I+'quarantine_ward');ally=_ally(e,me)
    name='Containment Mode + Quarantine Ward'
    if not any(name in c.display_name for c in e.legal_candidates()):name='Containment Mode'
    _cast(e,name,at=(4,6))
    assert me.resources['resource:core.qi']==96
    assert not any(m.target_field=='damage_resistance' for a in (me,foe,ally) for m in a.modifiers.values())
    assert not _rolls(e,'SAVE:')
    assert not any('Outbreak Mode + Quarantine Ward' in a.display_name for a in e.action_catalog.values())


@pytest.mark.parametrize('cl,count',[(10,3),(15,4)])
def test_epidemic_surge_requires_and_consumes_token_and_scales(cl,count):
    _,e,_,foe=_fight(I+'epidemic_surge',cl)
    assert not any('Epidemic Surge' in c.display_name for c in e.legal_candidates())
    _mark(e,foe);_cast(e,'Epidemic Surge')
    assert [r.expression for r in _rolls(e)]==[f'{count}d8+0']
    assert not any(c.condition_id==te.mark_condition_id('Contagion Token',ME) for c in foe.conditions.values())


@pytest.mark.parametrize('cl,radius',[(5,15),(10,20),(15,30)])
def test_enlarged_veil_uses_printed_radius(cl,radius):
    _,e,_,_=_fight(I+'enlarged_quarantine_veil',cl);_cast(e,'Outbreak Mode',at=(4,6))
    z=zones.typed_zones(e)[0];assert max(abs(c.x-4) for c in z.affected_cells)==radius//5


def test_narrow_veil_is_containment_only_and_ends_after_casters_next_turn():
    _,e,me,_=_fight(I+'narrow_quarantine');_cast(e,'Containment Mode + Narrow Quarantine',at=(4,6))
    assert me.concentration is None
    assert len(zones.typed_zones(e))==1
    assert not any('Outbreak Mode + Narrow Quarantine' in a.display_name for a in e.action_catalog.values())
    e.end_turn();e.end_turn();assert zones.typed_zones(e)
    e.end_turn();assert not zones.typed_zones(e)


@pytest.mark.parametrize('dc',[-50,50])
def test_world_pestilence_healing_half_while_inside_and_damage_on_start(dc):
    _,e,me,foe=_fight(I+'world_of_pestilence',dc=dc);_cast(e,'World of Pestilence',at=(4,6))
    assert foe.current_hp==2000 and te._reduced_healing(e,foe,20)==10
    assert not any(c.condition_id==te.mark_condition_id('Contagion Token',ME) for c in foe.conditions.values())
    e.end_turn();assert [r.expression for r in _rolls(e)]==['8d8+0']
    assert not any(c.condition_id==te.mark_condition_id('Contagion Token',ME) for c in foe.conditions.values())
    e._end_concentration(me,'TEST')
    assert not any((c.data.get('rule') or {}).get('healing_halved') for c in foe.conditions.values() if c.condition_id==zones.ZONE_EFFECT)
