"""Printed-text regressions for Spirit Companions, Stars, and Sword."""
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
P, S, W = 'tianxia.talent.spirit_companions.', 'tianxia.talent.stars.', 'TAL_SWORD_'


@lru_cache(maxsize=None)
def _compiled(key, cl=20, dc=50, extra=()):
    sphere = AUTH[key]['sphere_id']
    bases = [k for k, v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    return compile_character({**SHEET,
        'equipment': [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'quantity': 1}]}}],
        'identity': {**SHEET['identity'], 'cultivation_level': cl},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'], 'technique_save_dc': dc,
            'technique_attack_bonus': 40, 'primary_resource': {'name': 'Qi', 'maximum': 100}},
        'spheres_and_talents': {'sphere_record_ids': [sphere],
            'learned_talent_record_ids': list(dict.fromkeys([*bases, key, *extra]))}}, actor_id=ME)


def _fight(key, cl=20, dc=50, foe_at=(4, 6), extra=()):
    b = copy.deepcopy(_compiled(key, cl, dc, tuple(extra))); e = _engine(b, foe_at=foe_at)
    me, foe = e.state.actors[ME], e.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000; foe.armor_class = -50
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


def _rolls(e, prefix):
    return [r for r in e.rolls if r.reason.startswith(prefix)]


def _mark(e, foe, name):
    e._apply_condition(foe, te.mark_condition_id(name, ME), 'test:mark', ME, expires_on='UNTIL_REMOVED')


def _ally(e, me):
    ally = me.model_copy(deep=True); ally.entity_id = 'review:ally'
    ally.position = ally.position.model_copy(update={'y': 7}); e.state.actors[ally.entity_id] = ally
    return ally


@pytest.mark.parametrize('cl', [1, 5, 10, 11, 17])
def test_shared_senses_conditions_stop_at_core_formation(cl):
    _, e, me, _ = _fight(P+'shared_senses', cl=cl); _cast(e, 'Shared Senses')
    assert bool(_cond(me, 'blinded')) == (cl < 11)
    assert bool(_cond(me, 'deafened')) == (cl < 11)
    e.end_turn(); e.end_turn()
    assert not _cond(me, 'blinded') and not _cond(me, 'deafened')


def test_hosted_aspect_needs_cp_before_activation():
    _, e, me, _ = _fight(P+'hosted_battle_aspect'); me.resources['resource:core.qi'] = 0
    assert not any(c.display_name == 'Hosted Battle Aspect' for c in e.legal_candidates())
    me.resources['resource:core.qi'] = 1; _cast(e, 'Hosted Battle Aspect')
    assert me.resources['resource:core.qi'] == 0


# Guardian Spirit Posture and Spirit Recall command the Bonded Spirit (rider lane C9, 2026-09-30: "When your bonded spirit is within
# 10 feet of you or a protected ally", "call a bonded spirit within 60 feet"): the character now needs one on the map.
BONDED = (P+'covenant_spirit', P+'battle_manifestation')


def _spirit(e):
    return next(a for a in e.state.actors.values() if a.summon and a.summon['owner'] == ME)


def test_guardian_posture_does_not_grant_unqualified_temporary_hp():
    _, e, me, _ = _fight(P+'guardian_spirit_posture', extra=BONDED); ally = _ally(e, me)
    _spirit(e).position = me.position.model_copy(update={'x': me.position.x - 1})
    _cast(e, 'Guardian Spirit Posture', target=ME)
    assert me.temporary_hp == 0 and ally.temporary_hp == 0


def test_spirit_recall_does_not_move_the_caster():
    _, e, me, _ = _fight(P+'spirit_recall', extra=BONDED); before = me.movement_remaining_ft; start = me.position
    _cast(e, 'Spirit Recall'); assert me.movement_remaining_ft == before and me.position == start


@pytest.mark.parametrize('cl,count', [(1, 1), (5, 2), (11, 3), (17, 4)])
def test_starbolt_damage_scales_and_mark_expires(cl, count):
    _, e, me, foe = _fight('STARS_BASE_STARBOLT', cl=cl); _cast(e, 'Starbolt')
    # The owner's edited Starbolt adds the Path key modifier (CON 14 here).
    roll = _rolls(e, 'DAMAGE:')[0]
    assert roll.expression == f'{count}d8+2'
    assert roll.total == sum(roll.dice) + 2
    assert te.bears_mark(foe, ME, 'Stellar Mark')
    e.end_turn(); e.end_turn(); te.expire_marks(e)
    assert not te.bears_mark(foe, ME, 'Stellar Mark')


@pytest.mark.parametrize('dc', [-50, 50])
@pytest.mark.parametrize('cl,count', [(5, 5), (11, 7), (17, 9)])
def test_comet_spear_save_and_damage(cl, count, dc):
    _, e, _, foe = _fight('STARS_TAL_COMET_SPEAR', cl=cl, dc=dc); before = foe.position.x
    _cast(e, 'Comet Spear')
    assert _rolls(e, 'DAMAGE:')[0].expression.removesuffix('+0') == f'{count}d8'
    assert foe.position.x == before + (3 if dc > 0 else 1)
    assert bool(_cond(foe, 'prone')) == (dc > 0)


@pytest.mark.parametrize('key,name,cl,count,sides', [
    ('STARS_TAL_FALLING_STAR', 'Falling Star', 10, 6, 8),
    ('STARS_TAL_FALLING_STAR', 'Falling Star', 17, 8, 8),
    ('STARS_TAL_METEOR_SHOWER', 'Meteor Shower', 5, 5, 6),
    ('STARS_TAL_METEOR_SHOWER', 'Meteor Shower', 11, 7, 6),
    ('STARS_TAL_METEOR_SHOWER', 'Meteor Shower', 17, 9, 6)])
@pytest.mark.parametrize('dc', [-50, 50])
def test_stellar_area_damage_scales(key, name, cl, count, sides, dc):
    _, e, _, foe = _fight(key, cl=cl, dc=dc); _cast(e, name, at=(4, 6))
    r = _rolls(e, 'DAMAGE:')[0]
    assert r.expression.removesuffix('+0') == f'{count}d{sides}'
    assert 2000-foe.current_hp == (r.total if dc > 0 else r.total//2)


@pytest.mark.parametrize('slug,name,cost', [('cold_star_mantle', 'Cold Star Mantle', 2),
    ('constellation_guard', 'Constellation Guard', 3), ('star_name_seal', 'Star Name Seal', 10)])
def test_stellar_wards_pay_and_require_concentration(slug, name, cost):
    _, e, me, foe = _fight(S+slug); _mark(e, foe, 'Stellar Mark')
    before = me.current_hp; _cast(e, name)
    assert me.resources['resource:core.qi'] == 100-cost and me.concentration is not None
    assert me.current_hp == before and foe.current_hp == 2000
    e._end_concentration(me, 'TEST')
    assert not any(m.expires_on == 'CONCENTRATION_END' for m in me.modifiers.values())


def test_cold_mantle_reaches_a_distant_ally_without_harming_it():
    _, e, me, _ = _fight(S+'cold_star_mantle'); ally = _ally(e, me)
    ally.position = ally.position.model_copy(update={'x': 8}); before = ally.current_hp
    _cast(e, 'Cold Star Mantle', target=ally.entity_id)
    assert ally.current_hp == before
    assert any(m.target_field == 'damage_resistance' and m.value == 'COLD' for m in ally.modifiers.values())


@pytest.mark.parametrize('dc', [-50, 50])
def test_constellation_prison_branches_and_shared_repeat_save(dc):
    _, e, me, foe = _fight(S+'constellation_prison', dc=dc); _cast(e, 'Constellation Prison')
    assert me.resources['resource:core.qi'] == 94 and me.concentration is not None
    assert e._effective_speed(foe) == (0 if dc > 0 else foe.speed_ft)
    assert any(r.get('no_teleport') for r in te.condition_rules(foe))
    if dc > 0:
        assert any(r.get('no_reactions') for r in te.condition_rules(foe))
        e.end_turn(); foe.saving_throws['CHA'] = 1000; e.end_turn()
        assert not any(r.get('no_reactions') or r.get('no_teleport') for r in te.condition_rules(foe))
        assert e._effective_speed(foe) == foe.speed_ft


def test_constellation_prison_respects_restraint_immunity():
    _, e, _, foe = _fight(S+'constellation_prison')
    e.typed_passive_rows.setdefault(AN, []).append({'block': 'condition_immunity', 'conditions': ['restrained']})
    _cast(e, 'Constellation Prison')
    assert e._effective_speed(foe) == foe.speed_ft
    assert any(r.get('no_reactions') and r.get('no_teleport') for r in te.condition_rules(foe))


@pytest.mark.parametrize('key,name', [(S+'constellation_prison', 'Constellation Prison'),
    (S+'constellation_that_names', 'Constellation That Names'), (W+'SWORD_PRISON', 'Sword Prison')])
def test_lost_concentration_ends_ongoing_restrictions_and_damage(key, name):
    _, e, me, foe = _fight(key); _cast(e, name)
    assert any(c.data.get('repeat_save') for c in foe.conditions.values())
    e._end_concentration(me, 'TEST'); e.end_turn()
    assert not any(c.data.get('repeat_save') for c in foe.conditions.values())
    assert foe.current_hp == 2000 and e._effective_speed(foe) == foe.speed_ft


@pytest.mark.parametrize('slug,name', [('constellation_that_names', 'Constellation That Names'), ('stable_stellar_mark', 'Stable Stellar Mark')])
@pytest.mark.parametrize('dc', [-50, 50])
def test_stellar_marks_follow_both_save_branches_and_repeat_save(slug, name, dc):
    _, e, me, foe = _fight(S+slug, dc=dc); _cast(e, name)
    assert foe.current_hp == 2000 and te.bears_mark(foe, ME, 'Stellar Mark')
    if slug == 'constellation_that_names':
        assert me.resources['resource:core.qi'] == 85 and me.concentration is not None
    e.end_turn()
    if dc > 0:
        if slug == 'constellation_that_names':
            assert [r.expression.removesuffix('+0') for r in _rolls(e, 'DAMAGE:')] == ['4d10', '4d10']
        foe.saving_throws['CHA'] = 1000
    e.end_turn(); te.expire_marks(e)
    assert not te.bears_mark(foe, ME, 'Stellar Mark')


@pytest.mark.parametrize('dc', [-50, 50])
def test_guiding_star_marks_only_failed_save(dc):
    _, e, _, foe = _fight(S+'guiding_star', dc=dc); _cast(e, 'Guiding Star')
    assert te.bears_mark(foe, ME, 'Stellar Mark') == (dc > 0)


def test_night_sight_does_not_grant_blanket_perception_advantage():
    _, e, me, _ = _fight(S+'night_sight_meridian'); _cast(e, 'Night-Sight Meridian')
    assert not any('Perception' in (c.data.get('rule', {}).get('check_mode') or {}) for c in me.conditions.values())


def test_seven_star_step_does_not_deny_unmarked_reactions():
    _, e, me, foe = _fight(S+'seven_star_step'); _cast(e, 'Seven-Star Step')
    assert not _cond(me, 'reaction_denied') and not _cond(foe, 'reaction_denied')


@pytest.mark.parametrize('key,name,cost', [(S+'star_shadow', 'Star Shadow', 5),
    (W+'FLYING_SWORD_TECHNIQUE', 'Flying Sword Technique', 2), (W+'SWORD_SOUL', 'Sword Soul', 6)])
def test_creating_a_manifestation_is_not_an_immediate_attack(key, name, cost):
    _, e, me, foe = _fight(key); _cast(e, name)
    assert foe.current_hp == 2000 and not _rolls(e, 'ATTACK:')
    assert me.resources['resource:core.qi'] == 100-cost and me.concentration is not None


def test_star_sovereign_does_not_grant_walking_speed_or_immediate_pulse():
    _, e, me, foe = _fight(S+'star_sovereign_incarnation'); before = me.movement_remaining_ft
    _cast(e, 'Star-Sovereign Incarnation')
    assert me.resources['resource:core.qi'] == 85 and me.movement_remaining_ft == before
    assert e._effective_speed(me) == me.speed_ft and foe.current_hp == 2000
    assert not _rolls(e, 'SAVE:')


@pytest.mark.parametrize('cl,count', [(5, 1), (11, 2), (17, 3)])
def test_starlight_ward_scales_without_unqualified_alignment_bonus(cl, count):
    b, e, me, _ = _fight(S+'starlight_ward', cl=cl)
    row = next(r for r in b['typed_reactions'] if r.get('feature_id') == S+'starlight_ward')
    remaining, _ = tr._generic_damage_reduction(e, me, row, 100)
    r = e.rolls[-1]; assert r.expression == f'{count}d8+2' and remaining == 100-r.total


@pytest.mark.parametrize('key,name,at', [(S+'stars_domain', 'Stars Domain', None),
    (S+'world_beneath_the_constellations', 'World Beneath', (4, 6)),
    (W+'MYRIAD_SWORD_PROCESSION', 'Myriad Sword Procession', (4, 6)),
    (W+'SWORD_PRESSURE', 'Sword Pressure', None)])
def test_domains_wait_for_enemy_turn_start(key, name, at):
    _, e, me, foe = _fight(key); before = me.movement_remaining_ft; _cast(e, name, at=at)
    assert foe.current_hp == 2000 and not _rolls(e, 'SAVE:')
    assert me.movement_remaining_ft == before
    zones.on_turn_start(e, foe)
    assert len(_rolls(e, 'SAVE:')) == 1
    if key != W+'SWORD_PRESSURE': assert foe.current_hp < 2000


def test_world_constellation_mark_lasts_until_target_next_start_after_leaving():
    _, e, _, foe = _fight(S+'world_beneath_the_constellations')
    _cast(e, 'World Beneath', at=(4, 6)); e.end_turn()
    assert te.bears_mark(foe, ME, 'Stellar Mark')
    foe.position = foe.position.model_copy(update={'x': 19, 'y': 1})
    e.end_turn(); assert te.bears_mark(foe, ME, 'Stellar Mark')
    e.end_turn(); assert not te.bears_mark(foe, ME, 'Stellar Mark')


@pytest.mark.parametrize('key,name', [('SWORD_BASE_SWORD_BEYOND_HAND', 'Sword Beyond Hand'),
    ('SWORD_BASE_SWORD_IN_HAND', 'Sword in Hand')])
def test_sword_base_hits_place_expiring_intent_and_hand_deals_weapon_damage(key, name):
    _, e, _, foe = _fight(key); _cast(e, name)
    assert te.bears_mark(foe, ME, 'Sword Intent')
    if 'IN_HAND' in key:
        assert len(_rolls(e, 'DAMAGE:')) == 2
    e.end_turn(); e.end_turn(); te.expire_marks(e)
    assert not te.bears_mark(foe, ME, 'Sword Intent')


@pytest.mark.parametrize('dc', [-50, 50])
def test_sword_prison_timing_speed_and_repeat_save(dc):
    _, e, me, foe = _fight(W+'SWORD_PRISON', dc=dc); _cast(e, 'Sword Prison')
    assert foe.current_hp == 2000 and e._effective_speed(foe) == (0 if dc > 0 else foe.speed_ft-10)
    e.end_turn()
    if dc > 0:
        assert _rolls(e, 'DAMAGE:')[-1].expression.removesuffix('+0') == '2d8'
        assert any(r.get('no_reactions') for r in te.condition_rules(foe))
        foe.saving_throws['DEX'] = 1000; e.end_turn()
        assert e._effective_speed(foe) == foe.speed_ft and not _cond(foe, 'sword_prison')
    else: assert e._effective_speed(foe) == foe.speed_ft


def test_sword_prison_damage_from_caster_does_not_grant_repeat_save():
    _, e, me, foe = _fight(W+'SWORD_PRISON'); _cast(e, 'Sword Prison')
    foe.saving_throws['DEX'] = 1000; rolls = len(_rolls(e, 'SAVE:'))
    e._commit_damage(foe, 1, 'FIRE', 'test:damage', ME, None, reaction_depth=0)
    assert len(_rolls(e, 'SAVE:')) == rolls and _cond(foe, 'sword_prison')
    e._commit_damage(foe, 1, 'FIRE', 'test:environment', None, None, reaction_depth=0)
    assert len(_rolls(e, 'SAVE:')) == rolls and _cond(foe, 'sword_prison')
    ally = _ally(e, me)
    ally.summon = {'owner': ME, 'source': W+'FLYING_SWORD_TECHNIQUE'}
    e._commit_damage(foe, 1, 'SLASHING', 'test:flying_sword', ally.entity_id, None, reaction_depth=0)
    assert len(_rolls(e, 'SAVE:')) == rolls and _cond(foe, 'sword_prison')
    ally.summon = None
    e._commit_damage(foe, 1, 'FIRE', 'test:damage', ally.entity_id, None, reaction_depth=0)
    assert len(_rolls(e, 'SAVE:')) == rolls+1 and not _cond(foe, 'sword_prison')


def test_qi_infusion_does_not_harm_its_user():
    _, e, me, _ = _fight(W+'SWORD_QI_INFUSION'); before = me.current_hp; _cast(e, 'Sword-Qi Infusion')
    assert me.current_hp == before and not _rolls(e, 'DAMAGE:')


def test_drawing_stance_does_not_buff_every_unrelated_attack():
    _, e, me, _ = _fight(W+'SWORD_DRAWING_STANCE'); _cast(e, 'Sword Drawing Stance')
    assert not any(m.target_field == 'attack_mode' for m in me.modifiers.values())


def test_sword_sovereign_does_not_grant_movement_without_mark_application():
    _, e, me, _ = _fight(W+'SWORD_SOVEREIGN_INCARNATION'); before = me.movement_remaining_ft
    _cast(e, 'Sword-Sovereign Incarnation'); assert me.movement_remaining_ft == before


def test_life_severing_blocks_temporary_hp_and_reduces_healing():
    _, e, me, foe = _fight(W+'LIFE_SEVERING_SWORD'); _cast(e, 'Sword Beyond Hand', contains='Life-Severing Sword')
    assert _cond(foe, 'no_temp_hp')
    # Sword Beyond Hand places this owner's Sword Intent on the same hit.
    # The additional printed choice defaults to halving for an automatic actor.
    assert te.bears_mark(foe, me.entity_id, 'Sword Intent')
    assert te._reduced_healing(e, foe, 20) == 10
    e._grant_temp_hp(foe, 20, 'test:temporary_hp', ME); assert foe.temporary_hp == 0
    e.end_turn(); e.end_turn()
    assert te._reduced_healing(e, foe, 20) == 20
    e._grant_temp_hp(foe, 20, 'test:temporary_hp', ME); assert foe.temporary_hp == 20


@pytest.mark.parametrize('dc', [-50, 50])
def test_fatal_strike_healing_and_reaction_save_branches(dc):
    _, e, _, foe = _fight(W+'FATAL_STRIKE', dc=dc); foe.current_hp = 900; _mark(e, foe, 'Sword Intent')
    # The printed trigger is a qualifying hit, not a pre-hit action modifier.
    # The bare engine chooses its on-hit payment automatically; table prompts
    # and persisted payment are covered by test_a2_sword_second_pass.py.
    assert not any('Fatal Strike' in c.display_name for c in e.legal_candidates())
    _cast(e, 'Sword Beyond Hand')
    assert _cond(e.state.actors[ME], 'sword_fatal_strike_used')
    assert _cond(foe, 'reaction_denied')
    assert te._reduced_healing(e, foe, 20) == (0 if dc > 0 else 10)
    e.end_turn(); e.end_turn()
    assert not _cond(foe, 'reaction_denied') and te._reduced_healing(e, foe, 20) == (0 if dc > 0 else 10)
    e.end_turn(); assert te._reduced_healing(e, foe, 20) == 20
