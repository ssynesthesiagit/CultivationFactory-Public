"""Printed-rule regressions for Sabers, Sand, and Scoundrel."""

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
AUTH = json.loads((ROOT/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
S, D, C = 'tianxia.talent.sabers.', 'TAL_SAND_', 'TAL_SCOUNDREL_'


@lru_cache(maxsize=None)
def _compiled(key, cl=20, dc=50, armed=True, extra=(), actor_id=ME):
    sphere = AUTH[key]['sphere_id']
    bases = [k for k,v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    kit = [{'starting_kit': {'items': [{'item_id':'tianxia.mortal.weapon.dao','name':'Dao','quantity':1}]}}] if armed else []
    sheet = {**SHEET, 'equipment':kit,
        'identity': {**SHEET['identity'], 'cultivation_level':cl},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'],
            'technique_save_dc':dc, 'technique_attack_bonus':40,
            'primary_resource':{'name':'Qi','maximum':100}},
        'spheres_and_talents': {'sphere_record_ids':[sphere],
            'learned_talent_record_ids':list(dict.fromkeys([*bases,key,*extra]))}}
    return compile_character(sheet, actor_id=actor_id)


def _fight(key, cl=20, dc=50, armed=True, foe_at=(4,6), extra=(), armed_foe=False):
    bundle = copy.deepcopy(_compiled(key,cl,dc,armed,extra))
    engine = _engine(bundle,foe_at=foe_at)
    if armed_foe:
        opponent = copy.deepcopy(_compiled('SABERS_BASE_SABER_LINE_METHOD',armed=True,actor_id=AN))
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


def _cast(engine,prefix,contains='',target_id=None):
    candidates = [c for c in engine.legal_candidates() if c.display_name.startswith(prefix) and contains in c.display_name
                  and (target_id is None or target_id in c.target_ids)]
    assert candidates,(prefix,contains)
    pos = engine.state.actors[AN].position
    candidate = min(candidates,key=lambda c:(0 if c.destination is None else abs(c.destination.x-pos.x)+abs(c.destination.y-pos.y),len(c.display_name)))
    engine.execute_intent(ActionIntent(intent_id='review',decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id,state_version=candidate.state_version,actor_id=ME,
        target_ids=candidate.target_ids,destination=candidate.destination))


def _on_my_sand(engine, foe, *, buried=False, terrain='shallow sand terrain'):
    """The printed Target lines (rider lane C4, 2026-09-30): Sand Drag "One creature standing on Sand Terrain you control", Sand
    Coffin "One Buried creature in Sand Terrain you control", Glass Prison "One Buried creature or one creature standing in Deep
    Sand Terrain you control" -- the foe stands in the caster's Sand Terrain (and is Buried) before the cast."""
    from combat import zones
    from combat.gate2_runtime_models import Position, ZoneState

    engine.state.zones['zone:test:sand'] = ZoneState(zone_id='zone:test:sand', source_definition_id='test:sand', owner_id=ME,
        center=foe.position.model_copy(), radius_cells=0, affected_cells=(foe.position.model_copy(),), concentration_link=False,
        duration_rounds=10, created_round=engine.state.round_number,
        trigger_profile={'kind': zones.KIND, 'name': 'Sand', 'terrain': [terrain], 'difficult': 'hostile', 'visual': {'material': 'sand'},
                         'triggers': [], 'numbers': {'pb': 4, 'save_dc': 50}})
    if buried:
        engine._apply_condition(foe, 'condition:typed.buried', 'test:buried', ME, expires_on='UNTIL_REMOVED', data={'escape_dc': 50})


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


def _damage(engine):
    return [r.expression.removesuffix('+0') for r in _rolls(engine,'DAMAGE:')]


def _conditions(actor,name):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.'+name]


FORWARD=(S+'forward_cut',)


@pytest.mark.parametrize('slug,prefix,dice',[('army_line_chopping_field','Army-Line Chopping Field','4d8'),('battlefield_beheading_line','Battlefield Beheading Line','10d8')])
@pytest.mark.parametrize('dc,failed',[(50,True),(-50,False)])
def test_saber_save_damage_and_halving(slug,prefix,dice,dc,failed):
    _,engine,me,foe=_fight(S+slug,dc=dc)
    _cast(engine,prefix)
    rolls=_rolls(engine,'DAMAGE:')
    assert rolls and rolls[0].expression.removesuffix('+0')==dice
    assert 2000-foe.current_hp==(rolls[0].total if failed else rolls[0].total//2)
    assert te.bears_mark(foe,ME,'Guard Pressured')==failed
    assert _rolls(engine,'SAVE:')[0].reason.endswith(':DEX')


def test_banner_does_not_gain_edge_before_the_later_saber_hit():
    _,engine,me,foe=_fight(S+'banner_cleaving_advance',extra=FORWARD)
    me.resources['resource:named.edge_momentum']=0
    _cast(engine,'Banner-Cleaving Advance')
    assert me.resources['resource:named.edge_momentum']==0


def test_beheading_feint_requires_two_cp_before_activation():
    _,engine,me,foe=_fight(S+'beheading_feint')
    me.resources['resource:core.qi']=1
    assert not any(c.display_name.startswith('Beheading Feint') for c in engine.legal_candidates())


def test_beheading_success_does_not_deny_unrelated_reactions():
    _,engine,me,foe=_fight(S+'beheading_feint',dc=-50)
    _cast(engine,'Beheading Feint')
    assert foe.reaction_available and not _conditions(foe,'reaction_denied')
    assert not tr.wants_opportunity_attack(engine,foe,me)


def test_counter_slope_cannot_step_with_zero_cp():
    _,engine,me,foe=_fight(S+'counter_slope_dao')
    me.resources['resource:core.qi']=0;movement=me.movement_remaining_ft
    tr.on_attack_missed(engine,foe,me,{'attack_kind':'weapon','range_ft':5})
    assert me.movement_remaining_ft==movement


def test_counter_slope_does_not_mark_before_moving_adjacent():
    _,engine,me,foe=_fight(S+'counter_slope_dao',foe_at=(6,6))
    tr.on_attack_missed(engine,foe,me,{'attack_kind':'weapon','range_ft':15})
    assert not te.bears_mark(foe,ME,'Guard Pressured')


def test_crescent_does_not_save_after_only_one_creature_is_hit():
    _,engine,me,foe=_fight(S+'crescent_through_the_shield_wall',extra=FORWARD)
    _cast(engine,'Forward Cut')
    assert not _rolls(engine,'SAVE:')


def test_unanswered_domain_does_not_save_an_unqualified_creature_at_cast():
    _,engine,me,foe=_fight(S+'domain_of_the_unanswered_cut')
    _cast(engine,'Domain of the Unanswered Cut')
    assert not _rolls(engine,'SAVE:') and not _conditions(foe,'reaction_denied')
    me.bonus_action_available=True;me.resources['resource:core.qi']=100
    assert not any(c.display_name.startswith('Domain of the Unanswered Cut') for c in engine.legal_candidates())


def test_hewing_entry_deals_weapon_damage_and_marks_successful_save():
    _,engine,me,foe=_fight(S+'hewing_entry',dc=-50)
    _cast(engine,'Hewing Entry')
    assert _damage(engine)==['1d10+2']
    assert te.bears_mark(foe,ME,'Guard Pressured') and not _conditions(foe,'prone')


def test_kingfisher_requires_cp_and_does_not_slow_a_miss():
    key=S+'kingfisher_beheads_the_retreat';bundle,engine,me,foe=_fight(key)
    row=next(r for r in bundle['typed_reactions'] if r.get('feature_id')==key)
    me.resources['resource:core.qi']=3
    assert not tr._generic_affordable(engine,me,row)
    foe.armor_class=500
    tr._run_generic_effects(engine,me,foe,row,row['effects'])
    assert foe.current_hp==2000 and engine._effective_speed(foe)==foe.speed_ft


def test_riders_followthrough_preserves_other_reactions():
    _,engine,me,foe=_fight(S+'rider_s_passing_cut',extra=FORWARD)
    _cast(engine,'Forward Cut','Rider')
    assert foe.reaction_available and not _conditions(foe,'reaction_denied')
    assert not tr.wants_opportunity_attack(engine,foe,me)


def test_infantry_road_reaches_the_second_lane_of_its_ten_foot_width():
    _,engine,me,foe=_fight(S+'thousand_saber_infantry_road',foe_at=(6,7))
    c=next(c for c in engine.legal_candidates() if c.display_name.startswith('Thousand-Saber Infantry Road')
           and c.destination and (c.destination.x,c.destination.y)==(12,6))
    engine.execute_intent(ActionIntent(intent_id='wide-line',decision_id=c.decision_id,
        candidate_id=c.candidate_id,state_version=c.state_version,actor_id=ME,
        target_ids=c.target_ids,destination=c.destination))
    assert foe.current_hp<2000 and _damage(engine)==['8d8']


@pytest.mark.parametrize('cl,dice',[(1,'1d8'),(5,'2d8'),(11,'3d8'),(17,'4d8')])
@pytest.mark.parametrize('dc',[-50,50])
def test_scouring_hand_scales_on_both_save_branches(cl,dice,dc):
    _,engine,me,foe=_fight('SAND_BASE_SCOURING_HAND',cl=cl,dc=dc)
    _cast(engine,'Scouring Hand','Reduce Speed')
    assert _damage(engine)==[dice]


@pytest.mark.parametrize('dc,restrained',[(50,True),(-50,False)])
def test_burial_cast_does_not_deal_future_turn_damage(dc,restrained):
    _,engine,me,foe=_fight(D+'BURIAL_OF_THE_NAMELESS_ARMY',dc=dc)
    _cast(engine,'Burial of the Nameless Army')
    assert foe.current_hp==2000 and not _conditions(foe,'reaction_denied')
    assert bool(_conditions(foe,'restrained'))==restrained
    assert _conditions(foe,'buried')


def test_dune_court_does_not_move_the_caster_and_is_limited():
    _,engine,me,foe=_fight(D+'COURT_OF_TEN_THOUSAND_DUNES')
    movement=me.movement_remaining_ft
    _cast(engine,'Court of Ten Thousand Dunes')
    assert me.movement_remaining_ft==movement
    me.action_available=True;me.resources['resource:core.qi']=100
    assert not any(c.display_name.startswith('Court of Ten Thousand Dunes') for c in engine.legal_candidates())


@pytest.mark.parametrize('dc,amount',[(50,0),(-50,10)])
def test_dry_the_body_restricts_healing_by_save_result(dc,amount):
    _,engine,me,foe=_fight(D+'DESERT_DRINKS_THE_RIVER',dc=dc)
    _cast(engine,'Desert Drinks the River','Dry the Body')
    assert te._reduced_healing(engine,foe,20)==amount


@pytest.mark.parametrize('key,prefix,option',[(D+'DESERT_DRINKS_THE_RIVER','Desert Drinks the River','Desiccate the Object'),(D+'EROSION_SCRIPTURE','Erosion Scripture','Object Wear')])
def test_object_erosion_does_not_damage_a_creature(key,prefix,option):
    _,engine,me,foe=_fight(key)
    _cast(engine,prefix,option)
    assert foe.current_hp==2000


def test_desert_skin_does_not_resist_an_unqualified_magical_fire_attack():
    _,engine,me,foe=_fight(D+'DESERT_SKIN_METHOD')
    _cast(engine,'Desert Skin Method')
    assert tr.defend(engine,me,20,'FIRE','test:magical.fire',AN)==20


@pytest.mark.parametrize('key,prefix',[(D+'DEVOURING_DUNE_MOUTH','Devouring Dune Mouth'),(D+'QUICKSAND_GATE','Quicksand Gate')])
def test_burial_zones_wait_for_entry_or_start_and_do_not_restrain_fresh_targets(key,prefix):
    _,engine,me,foe=_fight(key)
    _cast(engine,prefix)
    assert not _rolls(engine,'SAVE:') and not _conditions(foe,'restrained')
    zones.on_turn_start(engine,foe)
    assert _conditions(foe,'buried') and not _conditions(foe,'restrained')
    assert foe.current_hp==2000


def test_dune_heart_does_not_move_the_user_on_gathering_sand():
    _,engine,me,foe=_fight(D+'DUNE_HEART_SAND')
    movement=me.movement_remaining_ft
    _cast(engine,'Gather Sand')
    assert me.movement_remaining_ft==movement


def test_dune_sea_advance_does_not_save_a_creature_without_crossing_it():
    _,engine,me,foe=_fight(D+'DUNE_SEA_ADVANCE')
    pos=foe.position.model_copy()
    _cast(engine,'Dune Sea Advance')
    assert foe.position==pos and not _rolls(engine,'SAVE:')


@pytest.mark.parametrize('cl,feet',[(1,10),(5,15),(11,20),(17,30)])
def test_dune_slide_movement_scales(cl,feet):
    _,engine,me,foe=_fight(D+'DUNE_SLIDE',cl=cl)
    movement=me.movement_remaining_ft
    _cast(engine,'Dune Slide')
    assert me.movement_remaining_ft==movement+feet


def test_glass_judgment_does_not_deal_movement_damage_at_cast():
    _,engine,me,foe=_fight(D+'GLASS_DESERT_JUDGMENT')
    _cast(engine,'Glass Desert Judgment')
    assert _damage(engine)==['6d8']
    assert 2000-foe.current_hp==_rolls(engine,'DAMAGE:')[0].total
    engine.end_turn();engine.end_turn()
    assert _conditions(foe,'restrained')
    engine.end_turn()
    assert not _conditions(foe,'restrained')


def test_glass_prison_does_not_damage_at_cast():
    _,engine,me,foe=_fight(D+'GLASS_PRISON')
    _on_my_sand(engine,foe,buried=True)
    _cast(engine,'Glass Prison')
    assert foe.current_hp==2000 and _conditions(foe,'restrained')


def test_clone_does_not_grant_a_step_before_an_incoming_miss():
    _,engine,me,foe=_fight(D+'SAND_CLONE_DECOY')
    movement=me.movement_remaining_ft
    _cast(engine,'Sand Clone Decoy')
    assert me.movement_remaining_ft==movement


def test_sand_coffin_allows_constitution_instead_of_strength():
    _,engine,me,foe=_fight(D+'SAND_COFFIN')
    _on_my_sand(engine,foe,buried=True)
    foe.saving_throws.update(STR=-100,CON=100)
    _cast(engine,'Sand Coffin')
    assert not _conditions(foe,'restrained') and not _conditions(foe,'silenced')


def test_failed_sand_coffin_silences_the_target():
    _,engine,me,foe=_fight(D+'SAND_COFFIN')
    _on_my_sand(engine,foe,buried=True)
    _cast(engine,'Sand Coffin')
    assert _conditions(foe,'restrained') and _conditions(foe,'silenced')


def test_sand_drag_allows_dexterity_instead_of_strength():
    _,engine,me,foe=_fight(D+'SAND_DRAG')
    _on_my_sand(engine,foe)
    foe.saving_throws.update(STR=-100,DEX=100);pos=foe.position.model_copy()
    _cast(engine,'Sand Drag')
    assert foe.position==pos and engine._effective_speed(foe)==20


@pytest.mark.parametrize('cl,dice',[(5,'2d8'),(11,'3d8'),(17,'4d8')])
def test_sand_needles_scale(cl,dice):
    """The printed Target line is "each within 10 feet of Sand Terrain or a Sand Source", which the row
    now reads, so the foe stands in the caster's Sand Terrain; the case is about the CL damage scale."""
    _,engine,me,foe=_fight(D+'SAND_NEEDLE_VOLLEY',cl=cl)
    _on_my_sand(engine,foe)
    _cast(engine,'Sand Needle Volley')
    assert _damage(engine)==[dice]


def test_sand_sovereign_does_not_add_burrow_to_walking_speed():
    _,engine,me,foe=_fight(D+'SAND_SOVEREIGN_INCARNATION')
    speed=engine._effective_speed(me);movement=me.movement_remaining_ft
    _cast(engine,'Sand-Sovereign Incarnation')
    assert engine._effective_speed(me)==speed and me.movement_remaining_ft==movement
    assert me.resources['resource:core.qi']==95
    me.bonus_action_available=True;me.resources['resource:core.qi']=100
    assert not any(c.display_name.startswith('Sand-Sovereign Incarnation') for c in engine.legal_candidates())


def test_mountain_scripture_keeps_its_weekly_limit_as_once_per_fight():
    _,engine,me,foe=_fight(D+'THE_MOUNTAIN_REMEMBERS_IT_IS_DUST')
    _cast(engine,'The Mountain Remembers It Is Dust','Erode the Giant')
    me.action_available=True;me.resources['resource:core.qi']=100
    assert not any(c.display_name.startswith('The Mountain Remembers It Is Dust') for c in engine.legal_candidates())


def test_grain_grip_does_not_damage_without_a_failed_escape():
    _,engine,me,foe=_fight(D+'THOUSAND_GRAIN_GRIP')
    engine._apply_condition(foe,'condition:typed.buried','test:buried',ME,expires_on='UNTIL_REMOVED')
    tr.on_creature_event(engine,foe,'moved',moved_ft=5)
    assert foe.current_hp==2000


def test_sandstorm_waits_for_hostile_turn_start():
    _,engine,me,foe=_fight(D+'THOUSAND_MILE_SANDSTORM_BODY')
    _cast(engine,'Thousand-Mile Sandstorm Body')
    assert foe.current_hp==2000 and not _conditions(foe,'blinded')
    zones.on_turn_start(engine,foe)
    assert _damage(engine)==['4d8'] and _conditions(foe,'blinded')


def _force_scoundrel_success(engine):
    for bundle in engine.typed_bundle_documents:
        if bundle['actor_id']==ME:bundle.setdefault('skills',{})['Sleight of Hand']=100


def test_steal_voice_does_not_fire_when_the_scoundrel_check_fails():
    _,engine,me,foe=_fight(C+'STEAL_VOICE',dc=50)
    foe.skills.update({'Athletics':100,'Acrobatics':100})
    _cast(engine,'DIRTY TRICK','STEAL VOICE')
    checks=[v for v in engine.events if v.event_type=='CHECK_ROLLED']
    assert checks and not checks[-1].payload['success']
    assert not _conditions(foe,'silenced') and not _rolls(engine,'SAVE:')


def test_counter_theft_uses_a_scoundrel_check_not_a_damaging_attack():
    _,engine,me,foe=_fight(C+'COUNTER_THEFT',armed_foe=True)
    _force_scoundrel_success(engine)
    tr.on_attacked(engine,foe,me,{'attack_kind':'weapon','attack_bonus':40,'range_ft':5})
    assert foe.current_hp==2000 and not _rolls(engine,'ATTACK:')
    assert _rolls(engine,'CHECK:') and _conditions(foe,'disarmed')


@pytest.mark.parametrize('foe_at,available',[((9,6),True),((10,6),False)])
def test_empty_sleeve_reach_is_thirty_not_thirty_five(foe_at,available):
    _,engine,me,foe=_fight(C+'EMPTY_SLEEVE_HAND',foe_at=foe_at)
    candidates=[c for c in engine.legal_candidates() if c.display_name.startswith('DIRTY TRICK') and 'EMPTY-SLEEVE HAND' in c.display_name]
    assert bool(candidates)==available
    if available:_cast(engine,'DIRTY TRICK','EMPTY-SLEEVE HAND')


def test_scoundrel_sovereign_does_not_add_flight_to_walking_speed_or_movement():
    _,engine,me,foe=_fight(C+'SOVEREIGN_OF_TEN_THOUSAND_EMPTY_SLEEVES')
    speed=engine._effective_speed(me);movement=me.movement_remaining_ft
    _cast(engine,'SOVEREIGN OF TEN THOUSAND EMPTY SLEEVES')
    assert engine._effective_speed(me)==speed and me.movement_remaining_ft==movement


@pytest.mark.parametrize('cl',[5,10])
@pytest.mark.parametrize('dc,failed',[(50,True),(-50,False)])
def test_steal_voice_silences_only_on_a_failed_save(cl,dc,failed):
    _,engine,me,foe=_fight(C+'STEAL_VOICE',cl=cl,dc=dc)
    _force_scoundrel_success(engine)
    _cast(engine,'DIRTY TRICK','STEAL VOICE')
    assert bool(_conditions(foe,'silenced'))==failed
    assert bool([c for c in _conditions(foe,'silenced') if c.data.get('repeat_save')])==(failed and cl>=10)
    if failed:
        foe.saving_throws['CON']=-100
        engine.end_turn();engine.end_turn()
        assert bool(_conditions(foe,'silenced'))==(cl>=10)
