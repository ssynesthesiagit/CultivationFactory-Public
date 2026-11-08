"""Riders lane 4 (2026-09-29): GM-only "rider" lines of Thread, Sniper, Metal, Sand, Void, Ink, Dark, Brute, Protection and Trap
abilities that now run.  Each test compiles a real character and runs the line through the engine; each fails on the typing
it replaced (the rider was a GM note, or a wrong option list)."""
import copy
import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import typed_executor as te, typed_reactions as tr
from combat.ext import thread_lines
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
T = 'tianxia.talent.thread.'


@lru_cache(maxsize=None)
def _compiled(keys, cl=20, dc=50, weapon='tianxia.mortal.weapon.jian'):
    sphere = AUTH[keys[0]]['sphere_id']
    bases = [k for k, v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    return compile_character({**SHEET,
        'equipment': [{'starting_kit': {'items': [{'item_id': weapon, 'quantity': 1}]}}],
        'identity': {**SHEET['identity'], 'cultivation_level': cl},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'], 'technique_save_dc': dc,
            'technique_attack_bonus': 40, 'primary_resource': {'name': 'Qi', 'maximum': 100}},
        'spheres_and_talents': {'sphere_record_ids': [sphere],
            'learned_talent_record_ids': list(dict.fromkeys([*bases, *keys]))}}, actor_id=ME)


def _fight(*keys, cl=20, dc=50, foe_at=(4, 6), weapon='tianxia.mortal.weapon.jian'):
    engine = _engine(copy.deepcopy(_compiled(tuple(keys), cl, dc, weapon)), foe_at=foe_at)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.maximum_hp = me.current_hp = foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    me.resources['resource:core.martial_focus'] = 1
    return engine, me, foe


def _cast(engine, name, target=None, exact=False):
    cs = [c for c in engine.legal_candidates() if (c.display_name == name if exact else name in c.display_name)
          and (target is None or target in c.target_ids)]
    assert cs, (name, [c.display_name for c in engine.legal_candidates() if c.target_ids])
    c = min(cs, key=lambda c: len(c.display_name))
    engine.execute_intent(ActionIntent(intent_id='lane4', decision_id=c.decision_id, candidate_id=c.candidate_id,
        state_version=c.state_version, actor_id=ME, target_ids=c.target_ids, destination=c.destination))


def _names(engine):
    return [c.display_name for c in engine.legal_candidates()]


def _mark(actor, name, owner=ME):
    cid = te.mark_condition_id(name, owner)
    return [c for c in actor.conditions.values() if c.condition_id == cid]


def _attacks(engine):
    return [r for r in engine.rolls if r.reason.startswith('ATTACK:')]


# ---------------------------------------------------------------------------------------------------------- Thread
def _walk(rows):
    for row in rows or []:
        if isinstance(row, dict):
            yield row
            for value in row.values():
                if isinstance(value, list):
                    yield from _walk(value)


def test_threaded_strike_weighted_knot_alone_is_once_per_round():
    """"You can use Weighted Knot only once per round" limits that option, not the other three."""
    strike = AUTH['THREAD_BASE_THREADED_STRIKE']['modifier']
    assert strike.get('limit') is None
    assert {o['label']: o.get('limit') for o in strike['options']} == {
        'Follow the Sleeve': None, 'Tighten the Wrist': None, 'Draw the Guard': None, 'Weighted Knot': 'once_per_round'}
    engine, me, foe = _fight('THREAD_BASE_THREADED_STRIKE')
    gated = {}
    for action in engine.action_catalog.values():
        if 'Draw the Line: Pull + Threaded Strike: ' in action.display_name:
            rows = list(_walk((action.parameters.get('typed') or {}).get('effects')))
            gated[action.display_name.rsplit(': ', 1)[1]] = any(r.get('modifier_once') for r in rows)
    assert gated == {'Follow the Sleeve': False, 'Tighten the Wrist': False, 'Draw the Guard': False, 'Weighted Knot': True}


def test_threaded_strike_draw_the_guard_gives_the_next_thread_attack_advantage():
    engine, me, foe = _fight('THREAD_BASE_THREADED_STRIKE', foe_at=(6, 6))
    _cast(engine, 'Draw the Line: Pull + Threaded Strike: Draw the Guard')
    assert _mark(foe, 'Draw the Guard') and [r.mode for r in _attacks(engine)] == ['NORMAL']
    engine.end_turn(); engine.end_turn()
    assert engine.state.current_actor_id == ME and _mark(foe, 'Draw the Guard')  # "before the end of your next turn"
    _cast(engine, 'Draw the Line: Snare')
    assert [r.mode for r in _attacks(engine)] == ['NORMAL', 'ADVANTAGE'] and not _mark(foe, 'Draw the Guard')  # the next one only


def test_threaded_strike_draw_the_guard_is_used_up_and_ends_with_the_next_turn():
    engine, me, foe = _fight('THREAD_BASE_THREADED_STRIKE', foe_at=(6, 6))
    _cast(engine, 'Draw the Line: Pull + Threaded Strike: Draw the Guard')
    engine.end_turn(); engine.end_turn(); engine.end_turn(); engine.end_turn()  # my next turn is over
    assert not _mark(foe, 'Draw the Guard')


def test_threaded_strike_tighten_the_wrist_gives_the_targets_next_opportunity_attack_disadvantage():
    engine, me, foe = _fight('THREAD_BASE_THREADED_STRIKE', foe_at=(6, 6))
    _cast(engine, 'Draw the Line: Pull + Threaded Strike: Tighten the Wrist')
    assert _mark(foe, 'Tightened Wrist')
    ctx = SimpleNamespace(engine=engine, actor=foe, action=next(iter(engine.action_catalog.values())), source='test')
    assert thread_lines.attack_mode(ctx, me) is None  # an ordinary attack is not the Opportunity Attack
    engine._typed_oa_attacker = foe.entity_id
    assert thread_lines.attack_mode(ctx, me) == 'DISADVANTAGE' and not _mark(foe, 'Tightened Wrist')
    assert thread_lines.attack_mode(ctx, me) is None  # only the next one


def test_threaded_strike_follow_the_sleeve_moves_5_feet_without_the_targets_opportunity_attack():
    engine, me, foe = _fight('THREAD_BASE_THREADED_STRIKE', foe_at=(6, 6))
    before = me.movement_remaining_ft
    _cast(engine, 'Draw the Line: Pull + Threaded Strike: Follow the Sleeve')
    assert me.movement_remaining_ft == before + 5 and me.turn_flags.get('spark_step_ignore_oa_from') == foe.entity_id


def test_needle_guide_line_gives_the_next_thread_attack_plus_2():
    engine, me, foe = _fight(T + 'needle_guide', foe_at=(6, 6))
    _cast(engine, 'Draw the Line: Snare')
    assert _mark(foe, 'Needle Guide') and _mark(foe, 'Thread Line')
    engine.end_turn(); engine.end_turn()
    _cast(engine, 'Draw the Line: Snare')
    first, second = _attacks(engine)
    assert second.modifier == first.modifier + 2 and _mark(foe, 'Needle Guide')  # a hit renews it; the +2 was spent on this roll


def _large(engine, actor, cells=2):
    engine.actor_footprints[actor.entity_id] = engine._footprint(actor).model_copy(update={'width_cells': cells, 'height_cells': cells})


def _ally(engine, me):
    ally = me.model_copy(deep=True); ally.entity_id = 'lane4:ally'
    ally.position = ally.position.model_copy(update={'y': 7}); engine.state.actors[ally.entity_id] = ally
    return ally


def test_draw_the_line_pull_moves_a_creature_your_size_and_asks_a_strength_save_of_a_larger_one():
    """"Move the target 5 feet toward you ... if it is your size or smaller. Larger creatures are not moved unless they fail a Strength saving throw."""
    for larger, dc, moved in ((False, -50, True), (True, -50, False), (True, 50, True)):
        engine, me, foe = _fight('THREAD_BASE_DRAW_THE_LINE', dc=dc, foe_at=(7, 6))
        if larger: _large(engine, foe)
        before = foe.position.x
        _cast(engine, 'Draw the Line: Pull')
        assert (foe.position.x < before) == moved, (larger, dc)


def test_draw_the_line_trip_does_nothing_to_a_creature_more_than_one_size_larger():
    for cells, prone in ((1, True), (2, True), (3, False)):
        engine, me, foe = _fight('THREAD_BASE_DRAW_THE_LINE', foe_at=(7, 6))
        _large(engine, foe, cells)
        _cast(engine, 'Draw the Line: Trip')
        assert bool(te_cond(foe, 'prone')) == prone, cells


def te_cond(actor, slug):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.' + slug]


def test_meridian_snare_repeat_use_gives_the_affected_creature_advantage_against_the_next_snare():
    """"A creature affected by Meridian Snare has advantage on saves against your Meridian Snare until the end of your next turn."""
    engine, me, foe = _fight('TAL_THREAD_MERIDIAN_SNARE', foe_at=(9, 6))
    _cast(engine, 'Meridian Snare: Leg Line')
    assert _mark(foe, 'Meridian Snare')
    engine.end_turn(); engine.end_turn()
    _cast(engine, 'Meridian Snare: Leg Line')
    saves = [r for r in engine.rolls if r.reason.startswith('SAVE:')]
    assert [r.mode for r in saves] == ['NORMAL', 'ADVANTAGE']


def test_meridian_snare_breath_line_takes_away_advantage_on_constitution_saves():
    engine, me, foe = _fight('TAL_THREAD_MERIDIAN_SNARE', foe_at=(9, 6))
    _cast(engine, 'Meridian Snare: Breath Line')
    assert te_cond(foe, 'cannot_advantage_con_saves')
    engine.end_turn(); engine.end_turn()
    _cast(engine, 'Meridian Snare: Leg Line')  # the Repeat Use Advantage is a benefit on a Constitution save: it does not count
    assert [r.mode for r in engine.rolls if r.reason.startswith('SAVE:')][-1] == 'NORMAL'


def test_meridian_stitch_restores_cp_to_a_creature_only_once():
    """"Restore CP equal to your Proficiency Bonus, but a creature can benefit from this CP restoration once per Long Rest."""
    engine, me, foe = _fight('TAL_THREAD_MERIDIAN_STITCH')
    ally = _ally(engine, me)
    engine._apply_condition(ally, te.mark_condition_id('Thread Line', ME), 'test', ME, expires_on='UNTIL_REMOVED')
    ally.resources['resource:core.qi'] = 10
    _cast(engine, 'Meridian Stitch: Restore CP', target=ally.entity_id)
    gained = ally.resources['resource:core.qi'] - 10
    assert gained > 0 and _mark(ally, 'Stitched CP')
    me.resources['resource:core.qi'] = 100
    assert not [c for c in engine.legal_candidates() if 'Restore CP' in c.display_name and ally.entity_id in c.target_ids]


def test_meridian_stitch_reaches_only_through_a_thread_line():
    """"Touch, or 30 feet through an active Qi Thread." / "Hostile Use: ... an unwilling creature with an active Thread Line"."""
    engine, me, foe = _fight('TAL_THREAD_MERIDIAN_STITCH', foe_at=(9, 6))
    assert not [c for c in engine.legal_candidates() if 'Meridian Stitch' in c.display_name and foe.entity_id in c.target_ids]
    engine._apply_condition(foe, te.mark_condition_id('Thread Line', ME), 'test', ME, expires_on='UNTIL_REMOVED')
    names = [c.display_name for c in engine.legal_candidates() if 'Meridian Stitch' in c.display_name and foe.entity_id in c.target_ids]
    assert any(n.endswith('Hostile Use') for n in names)


def test_life_line_stitch_saves_a_creature_once():
    """"A creature can benefit from Life-Line Stitch once per Long Rest."""
    engine, me, foe = _fight('tianxia.talent.thread.life_line_stitch')
    ally = _ally(engine, me)
    for attempt in (1, 2):
        me.reaction_available = True; me.resources['resource:core.qi'] = 100
        ally.current_hp = 0  # what te._deal leaves behind before it tells the table a creature dropped
        tr.on_creature_event(engine, ally, 'any_drop_to_zero')
        assert (ally.current_hp == 1) == (attempt == 1), attempt
    assert _mark(ally, 'Life-Line Stitch')


def test_surgeons_stitch_limit_is_per_creature_not_per_caster():
    """"A creature can benefit from your Surgeon's Stitch once per Short Rest" -- a second creature can still be stitched."""
    assert AUTH['tianxia.talent.thread.surgeon_s_stitch']['use_limit'] == 'text:once per creature per short rest'
    engine, me, foe = _fight(T + 'surgeon_s_stitch')
    ally = _ally(engine, me)
    _cast(engine, "Surgeon’s Stitch", target=me.entity_id)
    assert _mark(me, "Surgeon's Stitch")
    engine.end_turn(); engine.end_turn()
    offered = [c for c in engine.legal_candidates() if "Stitch" in c.display_name]
    assert not [c for c in offered if me.entity_id in c.target_ids]
    assert [c for c in offered if ally.entity_id in c.target_ids]


@pytest.mark.parametrize('mode,slug', [('Weapon Hand', 'bound_hand'), ('Footwork', 'bound_footwork'), ('Tail or Balance', 'bound_balance')])
def test_binding_sleeve_binds_a_limb_instead_of_grappling(mode, slug):
    engine, me, foe = _fight('tianxia.talent.thread.binding_knot', 'TAL_THREAD_BINDING_SLEEVE_METHOD')
    _cast(engine, 'Binding Knot + Binding Sleeve Method: ' + mode)
    assert bool(te_cond(foe, slug)) == (slug != 'bound_hand')
    assert te_cond(foe, 'bound_limb') and not te_cond(foe, 'grappled')
    rules = te.condition_rules(foe)
    assert engine._effective_speed(foe) == foe.speed_ft - (15 if slug == 'bound_footwork' else 0)
    assert not any(r.get('attacks_have') == 'DISADVANTAGE' for r in rules)
    assert any((r.get('save_mode') or {}).get('DEX') == 'DISADVANTAGE' for r in rules) == (slug == 'bound_balance')


def test_binding_sleeve_binding_ends_when_the_creature_escapes():
    """"Until the target escapes, one chosen mode is impaired ... The target may escape as normal for Binding Knot." """
    from combat.ext import thread_lines
    for bonus, freed in ((200, True), (-200, False)):
        engine, me, foe = _fight('tianxia.talent.thread.binding_knot', 'TAL_THREAD_BINDING_SLEEVE_METHOD')
        _cast(engine, 'Binding Knot + Binding Sleeve Method: Footwork')
        ctx = SimpleNamespace(engine=engine, actor=foe, source='test:escape', numbers={}, typed={})
        thread_lines.escape_binding(ctx, {'bonus': bonus})
        assert (not te_cond(foe, 'bound_footwork') and not te_cond(foe, 'bound_limb')) == freed


# ---------------------------------------------------------------------------------------------------------- Sniper
BOW = 'tianxia.mortal.weapon.gong_jian'
SN = 'TAL_SNIPER_'


def _snipe(*keys, **kw):
    return _fight(*keys, weapon=BOW, foe_at=kw.pop('foe_at', (6, 6)), **kw)


def _cond_rule(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.' + name]


def test_meridian_grazing_shot_offers_the_two_disadvantage_choices():
    """"the target has Disadvantage on the next Constitution saving throw it makes to maintain Concentration ... on the next Strength or
    Dexterity saving throw it makes before the start of your next turn" were GM lines."""
    engine, me, foe = _snipe(SN + 'MERIDIAN_GRAZING_SHOT')
    _cast(engine, 'Meridian-Grazing Shot: Concentration Disadvantage')
    assert [c for c in _cond_rule(foe, 'concentration_mode')]
    engine, me, foe = _snipe(SN + 'MERIDIAN_GRAZING_SHOT')
    _cast(engine, 'Meridian-Grazing Shot: Strength or Dexterity Disadvantage')
    rules = [c.data['rule']['save_against'] for c in _cond_rule(foe, 'save_against')]
    assert rules and set(rules[0]['abilities']) == {'STR', 'DEX'} and rules[0]['mode'] == 'DISADVANTAGE' and rules[0]['next']


@pytest.mark.parametrize('miss', [True, False])
def test_breath_held_shot_gives_the_payment_back_on_a_miss_and_holds_the_shooter_still(miss):
    """"If the attack misses, you may keep the CP or Martial Focus spent, but your Speed becomes 0 until the start of your next turn."""
    engine, me, foe = _snipe(SN + 'BREATH_HELD_SHOT')
    foe.armor_class = 1000 if miss else -50
    _cast(engine, 'Breath-Held Shot (Martial Focus)')
    focus = me.resources['resource:core.martial_focus']
    hit = any(e.event_type == 'ATTACK_HIT' for e in getattr(engine, 'events', ())) if False else None
    assert (focus == 1 and bool(_cond_rule(me, 'still_aim'))) == miss
    assert (engine._effective_speed(me) == 0) == miss
    if miss:
        engine.end_turn(); engine.end_turn()
        assert engine.state.current_actor_id == ME and not _cond_rule(me, 'still_aim')  # "until the start of your next turn"


def test_breath_held_shot_is_offered_only_before_the_shooter_has_moved():
    engine, me, foe = _snipe(SN + 'BREATH_HELD_SHOT')
    assert any('Breath-Held Shot' in n for n in _names(engine))
    move = next(c for c in engine.legal_candidates() if c.movement_cost_ft == 5 and c.destination is not None)
    engine.execute_intent(ActionIntent(intent_id='breath-move', decision_id=move.decision_id,
        candidate_id=move.candidate_id, state_version=move.state_version, actor_id=ME,
        destination=move.destination))
    assert not any('Breath-Held Shot' in n for n in _names(engine))


@pytest.mark.parametrize('dc,hindered', [(50, True), (-50, False)])
def test_hindering_projectile_holds_attack_disadvantage_until_removed(dc, hindered):
    """"On a failed save, the target has Disadvantage on attack rolls until it uses an Action to remove the projectile ... On a
    successful save, ... Disadvantage on the next attack roll it makes before the start of your next turn." """
    engine, me, foe = _snipe(SN + 'HINDERING_PROJECTILE')
    foe.saving_throws['DEX'] = -dc * 10  # a Snipe Shot's save DC is the character's own 8 + PB + key modifier
    _cast(engine, 'Hindering Projectile')
    assert bool(_cond_rule(foe, 'hindered')) == hindered
    if hindered:
        assert any(r.get('attacks_have') == 'DISADVANTAGE' for r in te.condition_rules(foe))
        from combat.ext import sniper_lines
        sniper_lines.remove_lodged(SimpleNamespace(engine=engine, actor=foe, source='test:remove'), {})
        assert not _cond_rule(foe, 'hindered')  # the Action to remove the projectile
    else:
        assert any(m.target_field == 'attack_mode' and m.value == 'DISADVANTAGE' for m in foe.modifiers.values())


def test_hindering_projectile_actual_healing_seals_the_wound():
    """"The effect ends early if ... the wound is sealed by sufficient healing." """
    engine, me, foe = _snipe(SN + 'HINDERING_PROJECTILE')
    foe.saving_throws['DEX'] = -500
    _cast(engine, 'Hindering Projectile')
    assert _cond_rule(foe, 'hindered')
    engine._append_event('HEALING_APPLIED', 'test:heal', actor_id=ME, target_ids=(foe.entity_id,), payload={'offered': 5, 'before': 10, 'after': 15})
    assert not _cond_rule(foe, 'hindered')
    assert not any(e.event_type == 'GM_RIDER' and 'sufficiently seals' in e.payload.get('rider', '') for e in engine.events)


# ---------------------------------------------------------------------------------------------------------- Metal
MT = 'TAL_METAL_'
CANON = MT + 'WHITE_TIGER_SEVEN_SLAUGHTER_CANON'


def _metal(*keys, **kw):
    return _fight(*keys, foe_at=kw.pop('foe_at', (6, 6)), **kw)


PALM = MT + 'CONDUCTOR_S_PALM'


def _palm_fight():
    from combat.gate4_engine import Gate4ControllerEngine
    other = compile_character({**copy.deepcopy(SHEET), 'spheres_and_talents': {
        'sphere_record_ids': ['tianxia.sphere.metal'],
        'learned_talent_record_ids': [PALM, MT + 'NEEDLE_FLICK']}}, actor_id=AN)
    engine = Gate4ControllerEngine(ROOT, match_seed='LANE4-PALM',
        typed_bundles=(copy.deepcopy(_compiled((PALM, MT + 'NEEDLE_FLICK'))), other),
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 8, 'y': 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.maximum_hp = me.current_hp = foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    return engine, me, foe


def _palm_states(actor):
    from combat.ext.next_damage_bonus import PREFIX
    return [c for c in actor.conditions.values() if c.condition_id.startswith(PREFIX)]


@pytest.mark.parametrize('kind,metal', [('LIGHTNING', False), ('THUNDER', True), ('PIERCING', True)])
def test_conductor_next_qualifying_packet_gets_caster_pb_once(kind, metal):
    engine, me, foe = _palm_fight()
    _cast(engine, "Conductor's Palm", target=AN, exact=True)
    assert len(_palm_states(foe)) == 1
    assert me.resources['resource:core.qi'] == 99
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == ME and a.display_name == 'Needle Flick') if metal else 'test:hazard'
    before = foe.current_hp
    engine._commit_damage(foe, 10, kind, source, ME, None, reaction_depth=0)
    assert before - foe.current_hp == 14
    assert not _palm_states(foe)
    before = foe.current_hp
    engine._commit_damage(foe, 10, kind, source, ME, None, reaction_depth=0)
    assert before - foe.current_hp == 10


def test_conductor_real_metal_hit_increases_only_first_packet():
    engine, me, foe = _palm_fight()
    _cast(engine, "Conductor's Palm", target=AN, exact=True)
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    packets = [e.payload for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and AN in e.target_ids]
    assert packets[0]['reduced_to'] == packets[0]['rolled_or_pending_damage'] + 4
    assert all(p['reduced_to'] == p['rolled_or_pending_damage'] for p in packets[1:])
    assert not _palm_states(foe)


@pytest.mark.parametrize('mode', ['unrelated', 'zero', 'immune', 'resistance', 'temporary_hp'])
def test_conductor_defenses_and_nonqualifying_packets(mode):
    engine, me, foe = _palm_fight()
    _cast(engine, "Conductor's Palm", target=AN, exact=True)
    if mode == 'unrelated':
        engine._commit_damage(foe, 10, 'THUNDER', 'test:other', ME, None, reaction_depth=0)
    elif mode == 'zero':
        engine._commit_damage(foe, 0, 'LIGHTNING', 'test:other', ME, None, reaction_depth=0)
    elif mode == 'immune':
        engine._add_modifier(foe, 'test:immune', 'damage_immunity', 'SET', 'LIGHTNING', 'ALWAYS', expires_on='UNTIL_REMOVED')
        engine._commit_damage(foe, 10, 'LIGHTNING', 'test:other', ME, None, reaction_depth=0)
    else:
        if mode == 'resistance':
            engine._add_modifier(foe, 'test:resist', 'damage_resistance', 'SET', 'LIGHTNING', 'ALWAYS', expires_on='UNTIL_REMOVED')
        else:
            foe.temporary_hp = 50
        engine._commit_damage(foe, 10, 'LIGHTNING', 'test:other', ME, None, reaction_depth=0)
    packet = [e.payload for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'][-1]
    expected = {'unrelated': 10, 'zero': 0, 'immune': 0, 'resistance': 7, 'temporary_hp': 14}[mode]
    assert packet['reduced_to'] == expected
    assert bool(_palm_states(foe)) == (mode in ('unrelated', 'zero', 'immune'))


def test_conductor_replaces_other_caster_and_uses_new_caster_pb():
    engine, me, foe = _palm_fight()
    _cast(engine, "Conductor's Palm", target=AN, exact=True)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == AN and a.display_name == "Conductor's Palm")
    typed = action.parameters['typed']
    te.run_effects(te.Context(engine, foe, action, None, typed, [foe], foe, {}), typed['effects'])
    assert len(_palm_states(foe)) == 1 and _palm_states(foe)[0].source_actor_id == AN
    before = foe.current_hp
    engine._commit_damage(foe, 10, 'LIGHTNING', 'test:other', ME, None, reaction_depth=0)
    assert before - foe.current_hp == 10 + typed['numbers']['pb']


def test_conductor_self_target_and_source_next_turn_expiry():
    engine, me, foe = _palm_fight()
    _cast(engine, "Conductor's Palm", target=ME, exact=True)
    assert len(_palm_states(me)) == 1
    engine.end_turn()
    assert _palm_states(me)
    engine.end_turn()
    assert not _palm_states(me)


def test_conductor_nested_event_damage_does_not_reuse_bonus():
    engine, me, foe = _palm_fight()
    _cast(engine, "Conductor's Palm", target=AN, exact=True)
    engine._ext_in_event = True
    # Same suppression flag as the real event dispatcher, including zone ticks.
    try:
        for _ in range(2):
            engine._commit_damage(foe, 10, 'LIGHTNING', 'test:hazard', ME, None, reaction_depth=0)
    finally:
        engine._ext_in_event = False
    packets = [e.payload['reduced_to'] for e in engine.events if e.event_type == 'DAMAGE_COMMITTED']
    assert packets == [14, 10]


def test_conductor_pure_queries_do_not_consume_or_write_events():
    from combat.ext.next_damage_bonus import bonus
    engine, me, foe = _palm_fight()
    _cast(engine, "Conductor's Palm", target=AN, exact=True)
    before = len(engine.events)
    assert [bonus(engine, foe, 10, 'LIGHTNING', 'test:hazard', ME) for _ in range(3)] == [4, 4, 4]
    assert len(engine.events) == before and len(_palm_states(foe)) == 1


def test_conductor_target_domains_range_and_native_boundary():
    engine, me, foe = _palm_fight()
    candidates = [c for c in engine.legal_candidates() if c.display_name == "Conductor's Palm"]
    assert {c.target_ids for c in candidates} == {(ME,), (AN,)}
    foe.position = foe.position.model_copy(update={'x': 10})  # 35 feet, beyond printed 30
    assert not any(c.display_name == "Conductor's Palm" and AN in c.target_ids for c in engine.legal_candidates())
    foe.position = foe.position.model_copy(update={'x': 8})
    engine.typed_actor_ids.remove(AN)
    assert not any(c.display_name == "Conductor's Palm" and AN in c.target_ids for c in engine.legal_candidates())


def test_conductor_hook_is_inert_without_owned_state():
    from combat.ext.next_damage_bonus import bonus
    engine, me, foe = _metal(MT + 'NEEDLE_FLICK')
    before = len(engine.events)
    assert bonus(engine, me, 10, 'LIGHTNING', 'test:hazard', AN) == 0
    assert len(engine.events) == before


@pytest.mark.parametrize('predefended', [False, True])
def test_conductor_shared_portion_adds_bonus_exactly_once(predefended):
    engine, me, foe = _palm_fight()
    _cast(engine, "Conductor's Palm", target=AN, exact=True)
    amount = tr.defend(engine, foe, 10, 'LIGHTNING', 'test:share', ME) if predefended else 10
    engine._damage_unreduced = AN
    engine._damage_bonus_already_applied = AN if predefended else None
    try:
        before = foe.current_hp
        engine._commit_damage(foe, amount, 'LIGHTNING', 'test:share', ME, None, reaction_depth=2)
    finally:
        engine._damage_unreduced = engine._damage_bonus_already_applied = None
    assert before - foe.current_hp == 14
    assert not _palm_states(foe)


def test_conductor_fully_reduced_packet_keeps_next_use():
    engine, me, foe = _palm_fight()
    _cast(engine, "Conductor's Palm", target=AN, exact=True)
    # An existing generic flat defense removes the whole augmented packet.
    rows = engine.typed_passive_rows.setdefault(AN, [])
    rows.append({'block': 'defense', 'kind': 'reduction', 'amount': 100,
                 'damage_types': ['LIGHTNING'], 'feature_id': 'test:full_reduction'})
    engine._commit_damage(foe, 10, 'LIGHTNING', 'test:hazard', ME, None, reaction_depth=0)
    assert len(_palm_states(foe)) == 1
    rows.pop()
    before = foe.current_hp
    engine._commit_damage(foe, 10, 'LIGHTNING', 'test:hazard', ME, None, reaction_depth=0)
    assert before - foe.current_hp == 14 and not _palm_states(foe)


def test_conductor_survives_table_commit_reload_and_consumption(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed='LANE4-PALM-PERSIST',
        typed_bundles=(copy.deepcopy(_compiled((PALM, MT + 'NEEDLE_FLICK'))),
                       compile_character(copy.deepcopy(SHEET), actor_id=AN)),
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}}})
    def submit(name, target=None):
        c = next(c for c in session.engine.legal_candidates() if c.display_name == name
                 and (target is None or target in c.target_ids))
        session.submit_intent(ActionIntent(intent_id='lane4-palm-persist', decision_id=c.decision_id,
            candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
            target_ids=c.target_ids, destination=c.destination), primary_decision_record=None, reaction_provider=None)
    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    submit("Conductor's Palm", AN)
    session = persistence.load_match(session.match_id)
    assert len(_palm_states(session.engine.state.actors[AN])) == 1
    submit('Needle Flick', AN)
    session = persistence.load_match(session.match_id)
    packets = [e.payload for e in session.engine.events if e.event_type == 'DAMAGE_COMMITTED' and AN in e.target_ids]
    assert packets[0]['reduced_to'] == packets[0]['rolled_or_pending_damage'] + 4
    assert not _palm_states(session.engine.state.actors[AN])
    assert session.verify()['status'] == 'PASS'


IRON_BONE = MT + 'IRON_BONE_INTERNAL_METHOD'


def _iron_choice(engine, label):
    # Exercise a second activation in the same turn without a full round trip:
    # its normal bonus action was already tested by the first engine submission.
    engine.state.actors[ME].bonus_action_available = True
    _cast(engine, 'Iron-Bone Internal Method: ' + label, exact=True)


def _hold_for_scoped_escape(engine, me, kind):
    from combat.ext.thread_lines import BOUND
    from combat.ext.trap import NETTED

    cid = {'grapple': te.CONDITION_PREFIX + 'grappled', 'binding': BOUND, 'net': NETTED}[kind]
    engine._apply_condition(me, cid, 'test:grip', AN, expires_on='UNTIL_REMOVED',
                            data={'escape_dc': 500, 'dc': 500})
    return {'grapple': 'Escape grapple', 'binding': 'Escape the binding', 'net': 'Escape the net'}[kind]


@pytest.mark.parametrize('ability', ['STR', 'CON'])
def test_metal_iron_bone_check_scope_does_not_leak_to_unrelated_checks_or_saves(ability):
    engine, me, _ = _metal(IRON_BONE)
    _iron_choice(engine, 'Advantage on Checks')
    assert te.check_mode(me, ability) == 'NORMAL'
    assert te.check_mode(me, ability, hazards=('frightened',)) == 'NORMAL'
    for hazard in ('forced_movement', 'grappled', 'restrained', 'prone'):
        assert te.check_mode(me, ability, hazards=(hazard,)) == 'ADVANTAGE'
    assert te.check_mode(me, 'DEX', 'Acrobatics', hazards=('grappled',)) == 'NORMAL'
    assert engine._roll_save(me, ability, 15, 'test:save').mode == 'NORMAL'


@pytest.mark.parametrize('kind', ['grapple', 'net'])
@pytest.mark.parametrize('ability,skill,mode', [('Strength', 'Athletics', 'ADVANTAGE'), ('Dexterity', 'Acrobatics', 'NORMAL')])
def test_metal_iron_bone_scoped_escape_rolls_use_selected_skill_only(kind, ability, skill, mode):
    engine, me, _ = _metal(IRON_BONE)
    _iron_choice(engine, 'Advantage on Checks')
    name = _hold_for_scoped_escape(engine, me, kind)
    action_name = f'{name}: {ability} ({skill})'
    candidate = next(c for c in engine.legal_candidates() if c.display_name == action_name)
    action = engine.action_catalog[candidate.source_definition_id]
    expected_bonus = action.parameters['typed']['effects'][0]['bonus']
    assert not action.parameters.get('player_only')  # same choices available on AI turns
    _cast(engine, action_name, exact=True)
    roll = next(r for r in reversed(engine.rolls) if r.reason.startswith('CHECK:'))
    assert roll.mode == mode and roll.modifier == expected_bonus
    assert len(roll.dice) == (2 if mode == 'ADVANTAGE' else 1)
    assert not me.action_available


def test_metal_iron_bone_scoped_strength_escape_cancels_disadvantage():
    engine, me, _ = _metal(IRON_BONE)
    _iron_choice(engine, 'Advantage on Checks')
    _hold_for_scoped_escape(engine, me, 'grapple')
    engine._apply_condition(me, te.CONDITION_PREFIX + 'check_mode', 'test:penalty', AN,
        expires_on='UNTIL_REMOVED', data={'rule': {'check_mode': {'STR': 'DISADVANTAGE'}}})
    _cast(engine, 'Escape grapple: Strength (Athletics)', exact=True)
    assert next(r for r in reversed(engine.rolls) if r.reason.startswith('CHECK:')).mode == 'NORMAL'


def test_metal_iron_bone_scoped_check_does_not_treat_bound_limb_as_grappled():
    engine, me, _ = _metal(IRON_BONE)
    _iron_choice(engine, 'Advantage on Checks')
    _hold_for_scoped_escape(engine, me, 'binding')
    assert 'Escape the binding: Strength (Athletics)' not in _names(engine)
    _cast(engine, 'Escape the binding', exact=True)
    assert next(r for r in reversed(engine.rolls) if r.reason.startswith('CHECK:')).mode == 'NORMAL'


def test_metal_iron_bone_scoped_escape_does_not_borrow_higher_acrobatics_bonus():
    sheet = copy.deepcopy(SHEET)
    sheet['spheres_and_talents'] = {'sphere_record_ids': [AUTH[IRON_BONE]['sphere_id']],
                                  'learned_talent_record_ids': [IRON_BONE]}
    sheet['ability_scores_and_statistics']['skills'] = [
        {'skill': 'Athletics', 'bonus': 1}, {'skill': 'Acrobatics', 'bonus': 11}]
    engine = _engine(compile_character(sheet, actor_id=ME))
    me = engine.state.actors[ME]
    _iron_choice(engine, 'Advantage on Checks')
    _hold_for_scoped_escape(engine, me, 'grapple')
    _cast(engine, 'Escape grapple: Strength (Athletics)', exact=True)
    roll = next(r for r in reversed(engine.rolls) if r.reason.startswith('CHECK:'))
    assert roll.mode == 'ADVANTAGE' and roll.modifier == 1
    me.action_available = True
    _cast(engine, 'Escape grapple: Dexterity (Acrobatics)', exact=True)
    roll = next(r for r in reversed(engine.rolls) if r.reason.startswith('CHECK:'))
    assert roll.mode == 'NORMAL' and roll.modifier == 11


def test_metal_iron_bone_unowned_candidate_hooks_are_inert(capsys):
    from combat.ext.scoped_checks import active_escape_choice

    engine, me, _ = _metal(MT + 'NEEDLE_FLICK')
    assert active_escape_choice(engine, me, None, None) is None
    _hold_for_scoped_escape(engine, me, 'grapple')
    assert not any(': Strength (Athletics)' in name for name in _names(engine))
    assert 'scoped_checks' not in capsys.readouterr().err


def test_metal_iron_bone_scoped_escape_choices_end_on_switch_and_expiry():
    engine, me, _ = _metal(IRON_BONE)
    _hold_for_scoped_escape(engine, me, 'grapple')
    choice = 'Escape grapple: Strength (Athletics)'
    assert choice not in _names(engine)
    _iron_choice(engine, 'Advantage on Checks')
    assert choice in _names(engine)
    _iron_choice(engine, 'Temporary HP')
    assert choice not in _names(engine)
    _iron_choice(engine, 'Advantage on Checks')
    for _ in range(22):
        engine.end_turn()
    assert choice not in _names(engine)
    assert te.check_mode(me, 'STR', hazards=('grappled',)) == 'NORMAL'


def test_metal_iron_bone_scoped_check_suppression_disables_and_restores_benefit():
    from combat.ext.end_effect import suppress
    from combat.ext.scoped_checks import CONDITION

    engine, me, _ = _metal(IRON_BONE)
    _iron_choice(engine, 'Advantage on Checks')
    _hold_for_scoped_escape(engine, me, 'grapple')
    state = next(c for c in me.conditions.values() if c.condition_id == CONDITION)
    assert te.check_mode(me, 'STR', hazards=('grappled',)) == 'ADVANTAGE'
    suppress(me, 'condition', state.instance_id, state, engine=engine)
    assert te.check_mode(me, 'STR', hazards=('grappled',)) == 'NORMAL'
    assert 'Escape grapple: Strength (Athletics)' not in _names(engine)
    for _ in range(4):
        engine.end_turn()
    assert te.check_mode(me, 'STR', hazards=('grappled',)) == 'ADVANTAGE'
    assert 'Escape grapple: Strength (Athletics)' in _names(engine)


def test_metal_iron_bone_scoped_escape_survives_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed='LANE4-IRON-CHECK',
        typed_bundles=(copy.deepcopy(_compiled((IRON_BONE,))), compile_character(copy.deepcopy(SHEET), actor_id=AN)),
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}}})

    def submit(name):
        choices = session.engine.legal_candidates()
        assert any(c.display_name == name for c in choices), (name, [c.display_name for c in choices])
        c = next(c for c in choices if c.display_name == name)
        session.submit_intent(ActionIntent(intent_id='lane4-check-persist', decision_id=c.decision_id,
            candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
            target_ids=c.target_ids, destination=c.destination), primary_decision_record=None, reaction_provider=None)

    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    submit('Iron-Bone Internal Method: Advantage on Checks')
    session = persistence.load_match(session.match_id)
    me = session.engine.state.actors[ME]
    assert te.check_mode(me, 'STR') == 'NORMAL'
    assert te.check_mode(me, 'STR', hazards=('grappled',)) == 'ADVANTAGE'
    submit('End turn')
    # Actual opposing grapple action, rather than injecting a persisted grip.
    assert session.engine.state.current_actor_id == AN
    submit('Grapple')
    session = persistence.load_match(session.match_id)
    submit('End turn')
    assert session.engine.state.current_actor_id == ME
    submit('Escape grapple: Strength (Athletics)')
    session = persistence.load_match(session.match_id)
    rolls = [r for r in session.engine.rolls if r.reason.startswith('CHECK:')]
    assert rolls[-1].mode == 'ADVANTAGE'
    assert te.check_mode(session.engine.state.actors[ME], 'CON') == 'NORMAL'


@pytest.mark.parametrize('first,second', [('BLUDGEONING', 'PIERCING'), ('PIERCING', 'SLASHING'), ('SLASHING', 'BLUDGEONING')])
def test_metal_iron_bone_resistance_next_consumes_all_types_on_first_instance(first, second):
    engine, me, foe = _metal(IRON_BONE)
    _iron_choice(engine, 'Resistance to Next Instance')
    events = len(engine.events)
    for _ in range(2):
        assert tr.damage_factor(engine, me, first, None, foe.entity_id) == 0.5
    assert len(engine.events) == events  # damage-choice/preview queries never spend it
    before = me.current_hp
    engine._commit_damage(me, 11, first, 'test:first', foe.entity_id, None, reaction_depth=0)
    assert before - me.current_hp == 5
    engine._commit_damage(me, 11, second, 'test:second', foe.entity_id, None, reaction_depth=0)
    assert before - me.current_hp == 16
    assert not any(m.target_field == 'damage_resistance_next' for m in me.modifiers.values())


def test_metal_iron_bone_resistance_next_preserves_nonmatching_zero_and_other_sources():
    engine, me, foe = _metal(IRON_BONE)
    _iron_choice(engine, 'Resistance to Next Instance')
    engine._add_modifier(me, 'test:other', 'damage_resistance', 'ADD', 'SLASHING', 'ALWAYS', expires_on='UNTIL_REMOVED')
    engine._commit_damage(me, 11, 'FIRE', 'test:fire', foe.entity_id, None, reaction_depth=0)
    engine._commit_damage(me, 0, 'PIERCING', 'test:zero', foe.entity_id, None, reaction_depth=0)
    before = me.current_hp
    engine._commit_damage(me, 11, 'SLASHING', 'test:first', foe.entity_id, None, reaction_depth=0)
    assert before - me.current_hp == 5
    assert not any(m.target_field == 'damage_resistance_next' for m in me.modifiers.values())
    engine._commit_damage(me, 11, 'SLASHING', 'test:second', foe.entity_id, None, reaction_depth=0)
    assert before - me.current_hp == 10  # permanent Resistance survives; never stacks
    engine._commit_damage(me, 11, 'PIERCING', 'test:third', foe.entity_id, None, reaction_depth=0)
    assert before - me.current_hp == 21


@pytest.mark.parametrize('field,expected', [('resistance_suppressed', 11), ('damage_immunity', 0)])
def test_metal_iron_bone_resistance_next_consumed_when_defense_is_overridden(field, expected):
    engine, me, foe = _metal(IRON_BONE)
    _iron_choice(engine, 'Resistance to Next Instance')
    engine._add_modifier(me, 'test:override', field, 'ADD', 'PIERCING', 'ALWAYS', expires_on='UNTIL_REMOVED')
    before = me.current_hp
    engine._commit_damage(me, 11, 'PIERCING', 'test:first', foe.entity_id, None, reaction_depth=0)
    assert before - me.current_hp == expected
    assert not any(m.target_field == 'damage_resistance_next' for m in me.modifiers.values())
    engine._commit_damage(me, 11, 'SLASHING', 'test:second', foe.entity_id, None, reaction_depth=0)
    assert before - me.current_hp == expected + 11


def test_metal_iron_bone_resistance_next_consumes_during_nested_no_intent_damage():
    engine, me, foe = _metal(IRON_BONE)
    _iron_choice(engine, 'Resistance to Next Instance')
    engine._ext_in_event = True
    try:
        before = me.current_hp
        engine._commit_damage(me, 11, 'PIERCING', 'test:hazard', foe.entity_id, None, reaction_depth=0)
        engine._commit_damage(me, 11, 'SLASHING', 'test:hazard', foe.entity_id, None, reaction_depth=0)
    finally:
        engine._ext_in_event = False
    assert before - me.current_hp == 16


def test_metal_iron_bone_resistance_next_expires_at_next_turn_start():
    engine, me, foe = _metal(IRON_BONE)
    _iron_choice(engine, 'Resistance to Next Instance')
    engine.end_turn()
    assert tr.damage_factor(engine, me, 'SLASHING', None, foe.entity_id) == 0.5
    engine.end_turn()
    assert engine.state.current_actor_id == ME
    assert tr.damage_factor(engine, me, 'SLASHING', None, foe.entity_id) == 1


def test_metal_iron_bone_resistance_next_survives_table_reload_and_consumption(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed='LANE4-IRON-NEXT',
        typed_bundles=(copy.deepcopy(_compiled((IRON_BONE,))),),
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}}})

    def submit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.submit_intent(ActionIntent(intent_id='lane4-iron-next', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination),
            primary_decision_record=None, reaction_provider=None)

    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    submit('Iron-Bone Internal Method: Resistance to Next Instance')
    session = persistence.load_match(session.match_id)
    me = session.engine.state.actors[ME]
    assert len([m for m in me.modifiers.values() if m.target_field == 'damage_resistance_next']) == 3
    submit('End turn')
    submit('Paired Bi Shou Assault')  # real opposing multiattack; consumption commits with it
    session = persistence.load_match(session.match_id)
    packets = [e.payload for e in session.engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and ME in e.target_ids and e.payload.get('damage_type') == 'PIERCING']
    assert packets
    assert packets[0]['reduced_to'] == packets[0]['rolled_or_pending_damage'] // 2
    for packet in packets[1:]:
        assert packet['reduced_to'] == packet['rolled_or_pending_damage']
    assert not any(m.target_field == 'damage_resistance_next'
                   for m in session.engine.state.actors[ME].modifiers.values())
    assert session.verify()['status'] == 'PASS'


@pytest.mark.parametrize('first,second', [
    ('Resistance to Next Instance', 'Advantage on Checks'),
    ('Advantage on Checks', 'Resistance to Next Instance'),
    ('Resistance to Next Instance', 'Temporary HP'),
    ('Advantage on Checks', 'Temporary HP'),
])
def test_metal_iron_bone_replaces_previous_choice_across_action_variants(first, second):
    engine, me, _ = _metal(IRON_BONE)
    _iron_choice(engine, first)
    old_sources = {c.source_definition_id for c in me.conditions.values()}
    old_sources |= {m.source_definition_id for m in me.modifiers.values()}
    unrelated = te.CONDITION_PREFIX + 'check_mode'
    engine._apply_condition(me, unrelated, 'test:unrelated', ME, expires_on='UNTIL_REMOVED')
    engine._add_modifier(me, 'test:unrelated', 'armor_class', 'ADD', 2, 'ALWAYS', expires_on='UNTIL_REMOVED')
    _iron_choice(engine, second)
    assert not any(c.source_definition_id in old_sources for c in me.conditions.values())
    assert not any(m.source_definition_id in old_sources for m in me.modifiers.values())
    assert any(c.condition_id == unrelated for c in me.conditions.values())
    assert any(m.source_definition_id == 'test:unrelated' for m in me.modifiers.values())
    assert len([c for c in me.conditions.values() if c.condition_id.endswith(IRON_BONE)]) == 1


@pytest.mark.parametrize('damage', [0, 3])
def test_metal_iron_bone_switch_ends_only_remaining_attributable_temp_hp(damage):
    engine, me, foe = _metal(IRON_BONE)
    _iron_choice(engine, 'Temporary HP')
    granted = me.temporary_hp
    assert granted > damage
    if damage:
        engine._commit_damage(me, damage, 'FIRE', 'test:damage', foe.entity_id, None, reaction_depth=0)
        assert me.temporary_hp == granted - damage
    _iron_choice(engine, 'Advantage on Checks')
    assert me.temporary_hp == 0
    assert not any(m.target_field.startswith('singleton_temp_hp:') for m in me.modifiers.values())


@pytest.mark.parametrize('other_grant,when', [(100, 'before'), (100, 'after'), (1, 'after')])
def test_metal_iron_bone_preserves_other_temp_hp_and_tracks_replacement(other_grant, when):
    engine, me, _ = _metal(IRON_BONE)
    if when == 'before':
        engine._grant_temp_hp(me, other_grant, 'test:other', ME)
    _iron_choice(engine, 'Temporary HP')
    if when == 'after':
        engine._grant_temp_hp(me, other_grant, 'test:other', ME)
    _iron_choice(engine, 'Advantage on Checks')
    assert me.temporary_hp == (100 if other_grant == 100 else 0)


def test_metal_iron_bone_temp_hp_ends_at_normal_duration_expiry():
    engine, me, _ = _metal(IRON_BONE)
    _iron_choice(engine, 'Temporary HP')
    assert me.temporary_hp > 0
    for _ in range(22):
        engine.end_turn()
    assert me.temporary_hp == 0
    assert not any(c.condition_id.endswith(IRON_BONE) for c in me.conditions.values())


def test_metal_iron_bone_same_choice_refreshes_instead_of_stacking():
    from combat.ext.end_effect import helpful

    engine, me, _ = _metal(IRON_BONE)
    _iron_choice(engine, 'Resistance to Next Instance')
    _iron_choice(engine, 'Resistance to Next Instance')
    assert len([m for m in me.modifiers.values() if m.target_field == 'damage_resistance_next']) == 3
    states = [c for c in me.conditions.values() if c.condition_id.endswith(IRON_BONE)]
    assert len(states) == 1
    assert not helpful(states[0], 'condition')  # bookkeeping is not an extra removable buff


def test_metal_iron_bone_recast_temp_hp_replaces_the_old_activation():
    engine, me, _ = _metal(IRON_BONE)
    _iron_choice(engine, 'Temporary HP')
    granted = me.temporary_hp
    _iron_choice(engine, 'Temporary HP')
    assert me.temporary_hp == granted
    assert len([c for c in me.conditions.values() if c.condition_id.endswith(IRON_BONE)]) == 1
    assert len([m for m in me.modifiers.values() if m.target_field.startswith('singleton_temp_hp:')]) == 1


@pytest.mark.parametrize('replacement', [False, True])
def test_metal_iron_bone_accounts_for_events_inside_another_event_hook(replacement):
    engine, me, foe = _metal(IRON_BONE)
    _iron_choice(engine, 'Temporary HP')
    # The standard TURN event guard is active while zone/duration hooks execute.
    engine._ext_in_event = True
    try:
        engine._commit_damage(me, 3, 'FIRE', 'test:hazard', foe.entity_id, None, reaction_depth=0)
        if replacement:
            engine._grant_temp_hp(me, 100, 'test:replacement', ME)
        _iron_choice(engine, 'Advantage on Checks')
    finally:
        engine._ext_in_event = False
    assert me.temporary_hp == (100 if replacement else 0)


def test_metal_iron_bone_single_benefit_survives_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed='LANE4-IRON-BONE',
        typed_bundles=(copy.deepcopy(_compiled((IRON_BONE,))),),
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 8, 'y': 6}}})

    def submit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.submit_intent(ActionIntent(intent_id='lane4-iron-bone-persist', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination),
            primary_decision_record=None, reaction_provider=None)

    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    submit('Iron-Bone Internal Method: Temporary HP')
    session = persistence.load_match(session.match_id)
    assert session.engine.state.actors[ME].temporary_hp > 0
    submit('End turn')
    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    submit('Iron-Bone Internal Method: Advantage on Checks')
    session = persistence.load_match(session.match_id)
    me = session.engine.state.actors[ME]
    assert me.temporary_hp == 0
    assert len([c for c in me.conditions.values() if c.condition_id.endswith(IRON_BONE)]) == 1
    assert not any(m.target_field.startswith('singleton_temp_hp:') for m in me.modifiers.values())


@pytest.mark.parametrize('direction,delta', [('Push', 1), ('Pull', -1)])
@pytest.mark.parametrize('cells,moves', [(1, True), (2, True), (3, False)])
def test_weight_chooses_push_or_pull_on_a_failed_save_and_respects_large_limit(direction, delta, cells, moves):
    engine, me, foe = _metal(MT + 'NEEDLE_FLICK')
    _large(engine, foe, cells)
    foe.saving_throws['STR'] = -500
    before = foe.position.x
    _cast(engine, 'Choose Metal expression: Weight: ' + direction + ' 5 feet', exact=True)
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert foe.position.x == before + (delta if moves else 0)
    saves = [r for r in engine.rolls if r.reason.startswith('SAVE:')]
    assert len(saves) == int(moves)
    # Weight is instead of Sharpen. It cannot leave Sharpen's damage or allowance on this hit.
    assert not any(r.reason.startswith('DAMAGE:') and 'SHARPEN' in r.reason for r in engine.rolls)
    assert not me.turn_flags.get('typed_modifier_once:METAL_BASE_SHARPEN')


def test_weight_does_not_apply_sharpen_and_consumes_a_shared_once_per_turn_gate():
    engine, me, foe = _metal(MT + 'NEEDLE_FLICK')
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Needle Flick')
    rows = list(_walk(action.parameters['typed']['effects']))
    sharpen = [r for r in rows if r.get('source_modifier') == 'METAL_BASE_SHARPEN']
    assert sharpen and all(r.get('menu') == 'metal_base_expression' and r.get('option') == 'Sharpen' for r in sharpen)
    foe.saving_throws['STR'] = -500
    _cast(engine, 'Choose Metal expression: Weight: Push 5 feet', exact=True)
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert me.turn_flags.get('typed_modifier_once:METAL_BASE_WEIGHT')


@pytest.mark.parametrize('direction,delta', [('Push', 1), ('Pull', -1)])
@pytest.mark.parametrize('bonus,distance', [(-500, 2), (500, 1)])
def test_loadstone_tug_has_both_directions_and_moves_five_feet_even_on_save_success(direction, delta, bonus, distance):
    engine, me, foe = _metal(MT + 'LOADSTONE_TUG', foe_at=(8, 6))
    foe.saving_throws['STR'] = bonus
    before = foe.position.x
    _cast(engine, 'Loadstone Tug: ' + direction)
    assert foe.position.x == before + delta * distance


@pytest.mark.parametrize('bonus,menu,label,slug', [
    (-500, 'Failed Save', 'Speed becomes 0', 'speed_becomes'),
    (-500, 'Failed Save', 'Cannot teleport', 'cannot_teleport'),
    (-500, 'Failed Save', 'Cannot take Reactions', 'reaction_denied'),
    (500, 'Successful Save', 'Cannot take Opportunity Attacks', 'no_opportunity_attacks'),
])
def test_heaven_piercing_nail_runs_only_the_selected_save_result(bonus, menu, label, slug):
    engine, me, foe = _metal(MT + 'HEAVEN_PIERCING_NAIL')
    foe.saving_throws['CON'] = bonus
    _cast(engine, 'Choose Heaven-Piercing Nail: ' + label, exact=True)
    _cast(engine, 'Heaven-Piercing Nail', target=foe.entity_id, exact=True)
    if slug == 'speed_becomes':
        assert engine._effective_speed(foe) == 0
    else:
        assert te_cond(foe, slug)
    assert bool(te_cond(foe, 'reaction_denied')) == (slug == 'reaction_denied')


def test_heaven_piercing_nail_success_offers_speed_reduction_instead_of_reaction_denial():
    engine, me, foe = _metal(MT + 'HEAVEN_PIERCING_NAIL')
    foe.saving_throws['CON'] = 500
    _cast(engine, 'Heaven-Piercing Nail', target=foe.entity_id, exact=True)
    assert engine._effective_speed(foe) == foe.speed_ft - 10
    assert not te_cond(foe, 'reaction_denied')


@pytest.mark.parametrize('label,slug', [('Cannot take Reactions', 'reaction_denied'),
    ('Speed reduced by 15 feet', None), ('Cannot regain CP', 'no_cp_regain'),
    ('Disadvantage on maintaining a technique', 'concentration_mode')])
def test_heavenly_needle_sutra_runs_selected_seal_without_other_seals(label, slug):
    engine, me, foe = _metal('tianxia.talent.metal.heavenly_needle_sutra')
    foe.saving_throws['DEX'] = -500
    # Printed recipients and seals are now chosen during this actual use.
    from combat.gate2_runtime_models import ReactionDecision
    def provider(request):
        source = request['reaction_source_id']
        chosen = (foe.entity_id,) if source == 'choice:needle.rider_targets' else (label,) if source == 'choice:needle.metal_needle_seal' else ()
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=source, selection='USE' if chosen else 'DECLINE', option_ids=chosen), None
    engine.set_reaction_provider(provider)
    _cast(engine, 'Heavenly Needle Sutra', target=foe.entity_id, exact=True)
    if slug:
        assert te_cond(foe, slug)
    else:
        assert engine._effective_speed(foe) == foe.speed_ft - 15
    assert bool(te_cond(foe, 'reaction_denied')) == (slug == 'reaction_denied')


@pytest.mark.parametrize('sign', ['No Mending Under the Star', 'Cut the Coward Road', 'Open the Guard', 'Tiger Eats the Fear'])
def test_seven_slaughter_signs_require_the_active_canon_and_do_not_pay_activation_again(sign):
    engine, me, foe = _metal(CANON, MT + 'NEEDLE_FLICK')
    if sign == 'Tiger Eats the Fear':
        foe.current_hp = 500
    foe.saving_throws.update({'WIS': -500, 'CHA': -500})
    assert not any(' + White Tiger Seven-Slaughter Canon:' in n for n in _names(engine))
    _cast(engine, 'White Tiger Seven-Slaughter Canon', exact=True)
    assert _mark(me, 'Seven-Slaughter Canon')
    _cast(engine, 'Choose White Tiger Seven-Slaughter Canon: ' + sign, exact=True)
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert me.resources['resource:core.qi'] == 97  # 3 CP to activate; the compiled physical-medium Needle Flick is free
    assert not any(' + White Tiger Seven-Slaughter Canon:' in a.display_name for a in engine.action_catalog.values())
    assert me.turn_flags.get('typed_modifier_once:' + CANON)
    if sign == 'No Mending Under the Star':
        assert any(m.target_field == 'healing_reduction' for m in foe.modifiers.values()) and te_cond(foe, 'no_temp_hp')
    elif sign == 'Cut the Coward Road':
        assert te_cond(foe, 'cannot_teleport') and te_cond(foe, 'no_invisible')
    elif sign == 'Open the Guard':
        assert te_cond(foe, 'exposed')
    else:
        assert te_cond(foe, 'frightened')


def _canon_critical_fight(*, activate=True, helmet=False):
    from combat.gate4_engine import Gate4ControllerEngine
    bundles = [copy.deepcopy(_compiled((CANON, MT + 'NEEDLE_FLICK')))]
    if helmet:
        bundles.append(compile_character({**copy.deepcopy(SHEET), 'spheres_and_talents': {
            'sphere_record_ids': ['tianxia.sphere.equipment'],
            'learned_talent_record_ids': ['tianxia.talent.equipment.helmet_discipline']}}, actor_id=AN))
    engine = Gate4ControllerEngine(ROOT, match_seed='CANON-0',
        typed_bundles=tuple(bundles),
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 6, 'y': 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    if activate:
        _cast(engine, 'White Tiger Seven-Slaughter Canon', exact=True)
    return engine, me, foe


def _canon_provider(engine, *, decline=False, pause=False, selected=None, helmet=False):
    from combat.gate2_runtime_models import ReactionDecision
    seen = []
    def provider(request):
        if helmet and request['reaction_source_id'] == 'choice:needle.helmet_discipline':
            # Reviewed pre-damage cancellation requires an explicit confirmation
            # of qualifying head protection instead of automatic conversion.
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=('protected',)), None
        recovery = request['reaction_source_id'].endswith('metal_canon_recovery')
        if request['reaction_source_id'].endswith('metal_canon_sign'):
            option = (request['choice_trigger'].get('preferred') or request['legal_option_ids'])[0]
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(option,)), None
        if recovery:
            seen.append(request)
            if pause:
                raise RuntimeError('Canon choice paused')
        use = recovery and not decline
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE' if use else 'DECLINE',
            option_ids=(selected or request['legal_option_ids'][0],) if use else ()), None
    engine.set_reaction_provider(provider)
    return seen


@pytest.mark.parametrize('immune', [False, True])
def test_canon_critical_recovery_runs_once_even_when_critical_damage_is_zero(immune):
    engine, me, foe = _canon_critical_fight()
    if immune:
        for kind in ('PIERCING', 'SLASHING'):
            engine._add_modifier(foe, 'test:immune', 'damage_immunity', 'ADD', kind, 'SELF', expires_on='UNTIL_REMOVED')
    seen = _canon_provider(engine)
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert _attacks(engine)[0].natural_result == 20
    assert me.resources['resource:core.qi'] == 100
    assert _mark(me, 'Seven-Slaughter Canon')[0].data['recovery_used'] == 1
    assert len(seen) == 1
    assert all(text in seen[0]['choice_trigger']['prompt'] for text in ('White Tiger Seven-Slaughter Canon', 'Needle Flick', foe.display_name))
    assert (foe.current_hp == 2000) == immune
    # Real later attacks with the same activation cannot recover again, even across turn boundaries.
    me.resources['resource:core.qi'] = 80
    for _ in range(3):
        engine.end_turn(); engine.end_turn()
        _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert me.resources['resource:core.qi'] == 80 and len(seen) == 1


def test_canon_critical_recovery_ends_only_the_selected_condition_instance():
    engine, me, foe = _canon_critical_fight()
    for source in ('test:first', 'test:second'):
        engine._apply_condition(me, 'condition:typed.charmed', source, ME,
                                expires_on='UNTIL_REMOVED', data={'label': 'Charmed'})
    instances = te_cond(me, 'charmed')
    assert len(instances) == 2
    selected = instances[1].instance_id
    _canon_provider(engine, selected=selected)
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert me.resources['resource:core.qi'] == 100
    assert [c.instance_id for c in te_cond(me, 'charmed')] == [instances[0].instance_id]


def test_canon_critical_recovery_decline_preserves_activation_allowance():
    engine, me, foe = _canon_critical_fight()
    seen = _canon_provider(engine, decline=True)
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert len(seen) == 1 and me.resources['resource:core.qi'] == 97
    assert not _mark(me, 'Seven-Slaughter Canon')[0].data.get('recovery_used')


def test_canon_critical_recovery_ai_uses_automatic_choice_without_a_reaction():
    from combat.gate4_context import build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary
    engine, me, foe = _canon_critical_fight()
    me.reaction_available = False
    def provider(request):
        context = build_reaction_context(engine, PolicyLibrary(ROOT).fallback(), request)
        return LocalDeterministicController().choose_reaction(context).decision, None
    engine.set_reaction_provider(provider)
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert _attacks(engine)[0].natural_result == 20
    assert me.resources['resource:core.qi'] == 100
    assert _mark(me, 'Seven-Slaughter Canon')[0].data['recovery_used'] == 1
    assert not me.reaction_available


def test_canon_critical_recovery_respects_no_cp_regain_and_still_ends_one_condition():
    engine, me, foe = _canon_critical_fight()
    engine._apply_condition(me, 'condition:typed.check_mode', 'test:seal', AN,
                            expires_on='UNTIL_REMOVED', data={'rule': {'no_cp_regain': True}})
    engine._apply_condition(me, 'condition:typed.charmed', 'test:charm', ME,
                            expires_on='UNTIL_REMOVED', data={})
    _canon_provider(engine)
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert me.resources['resource:core.qi'] == 97
    assert not te_cond(me, 'charmed')
    assert _mark(me, 'Seven-Slaughter Canon')[0].data['recovery_used'] == 1


def test_canon_critical_recovery_inert_when_helmet_turns_the_critical_normal():
    engine, me, foe = _canon_critical_fight(helmet=True)
    seen = _canon_provider(engine, helmet=True)
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert _attacks(engine)[0].natural_result == 20
    # Reviewed native cancellation (031d3e69) records the decision before
    # damage, replacing the older plug-in's post-hit conversion marker.
    assert any(e.event_type == 'ATTACK_CRITICAL_RESOLVED' and e.payload.get('cancelled')
               and not e.payload.get('critical') for e in engine.events)
    assert not seen and me.resources['resource:core.qi'] == 97
    assert not _mark(me, 'Seven-Slaughter Canon')[0].data.get('recovery_used')


@pytest.mark.parametrize('mode', ['expired', 'no_intent', 'foreign_source'])
def test_canon_critical_recovery_inert_outside_supported_owned_checkpoint(mode):
    engine, me, foe = _canon_critical_fight()
    seen = _canon_provider(engine)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == 'Needle Flick')
    typed = copy.deepcopy(action.parameters['typed'])
    if mode == 'expired':
        engine._remove_condition(me, te.mark_condition_id('Seven-Slaughter Canon', ME), 'test:expiry')
    elif mode == 'foreign_source':
        action = action.model_copy(deep=True)
        typed['source'] = 'test:non_metal'
        action.parameters['typed'] = typed
    intent = None if mode == 'no_intent' else ActionIntent(intent_id='canon-boundary', decision_id='test',
        candidate_id='test', state_version=engine.state.state_version, actor_id=ME, target_ids=(AN,))
    te.run_effects(te.Context(engine, me, action, intent, typed, [foe], foe, {}), typed['effects'])
    assert _attacks(engine)[0].natural_result == 20
    assert not seen and me.resources['resource:core.qi'] == 97


def test_canon_critical_recovery_choice_pause_rolls_back_action():
    engine, me, foe = _canon_critical_fight()
    _canon_provider(engine, pause=True)
    before = engine.state.model_dump(mode='json')
    with pytest.raises(RuntimeError, match='Canon choice paused'):
        _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert engine.state.model_dump(mode='json') == before


def test_canon_critical_recovery_inert_without_activation():
    engine, me, foe = _canon_critical_fight(activate=False)
    me.resources['resource:core.qi'] = 80
    seen = _canon_provider(engine)
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert _attacks(engine)[0].natural_result == 20
    assert not seen and me.resources['resource:core.qi'] == 80


def test_canon_critical_recovery_asks_the_owner_on_another_actors_turn():
    engine, me, foe = _canon_critical_fight()
    engine.state.current_actor_id = AN
    seen = _canon_provider(engine)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == 'Needle Flick')
    intent = ActionIntent(intent_id='canon-offturn', decision_id='test', candidate_id='test',
                          state_version=engine.state.state_version, actor_id=AN, target_ids=(ME,))
    te.run_effects(te.Context(engine, me, action, intent, action.parameters['typed'], [foe], foe, {}),
                   action.parameters['typed']['effects'])
    assert _attacks(engine)[0].natural_result == 20
    assert me.resources['resource:core.qi'] == 100
    assert len(seen) == 1 and seen[0]['reactor_id'] == ME
    assert seen[0]['attacking_actor_id'] == AN
    assert seen[0]['protected_target_id'] == AN


def test_canon_critical_recovery_consumption_survives_table_commit_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    from combat.gate2_runtime_models import ReactionDecision
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed='CANON-0',
        typed_bundles=(copy.deepcopy(_compiled((CANON, MT + 'NEEDLE_FLICK'))),),
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 6, 'y': 6}}})
    def provider(request):
        use = request['reaction_source_id'].endswith('metal_canon_recovery')
        if request['reaction_source_id'].endswith('metal_canon_sign'):
            option = (request['choice_trigger'].get('preferred') or request['legal_option_ids'])[0]
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(option,)), None
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE' if use else 'DECLINE',
            option_ids=(request['legal_option_ids'][0],) if use else ()), None
    def submit(name):
        c = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.submit_intent(ActionIntent(intent_id='canon-persist', decision_id=c.decision_id,
            candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
            target_ids=c.target_ids, destination=c.destination), primary_decision_record=None,
            reaction_provider=provider)
    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    submit('White Tiger Seven-Slaughter Canon')
    submit('Needle Flick')
    assert _attacks(session.engine)[0].natural_result == 20
    session = persistence.load_match(session.match_id)
    active = _mark(session.engine.state.actors[ME], 'Seven-Slaughter Canon')[0]
    assert active.data['recovery_used'] == 1
    assert session.engine.state.actors[ME].resources['resource:core.qi'] == 100
    expiry = active.expires_on
    submit('End turn')
    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    session = persistence.load_match(session.match_id)
    assert _mark(session.engine.state.actors[ME], 'Seven-Slaughter Canon')[0].expires_on == expiry
    assert _mark(session.engine.state.actors[ME], 'Seven-Slaughter Canon')[0].data['recovery_used'] == 1


def _canon_extra_fight(cl=20):
    engine, me, foe = _metal(CANON, MT + 'NEEDLE_FLICK', cl=cl)
    other = foe.model_copy(deep=True)
    other.entity_id = 'lane4:extra'
    other.display_name = 'Extra creature'
    other.position = other.position.model_copy(update={'x': 7, 'y': 7})
    other.conditions = {}; other.modifiers = {}
    engine.state.actors[other.entity_id] = other
    # Actual compiled attack before activation: the printed turn includes this damage.
    _cast(engine, 'Needle Flick', target=other.entity_id, exact=True)
    me.action_available = True
    _cast(engine, 'White Tiger Seven-Slaughter Canon', exact=True)
    _cast(engine, 'Choose White Tiger Seven-Slaughter Canon: No Mending Under the Star', exact=True)
    return engine, me, foe, other


def _canon_extra_provider(engine, *, decline=False, pause=False):
    from combat.gate2_runtime_models import ReactionDecision
    seen = []
    def provider(request):
        extra = request['reaction_source_id'].endswith('metal_canon_extra')
        if request['reaction_source_id'].endswith('metal_canon_sign'):
            option = (request['choice_trigger'].get('preferred') or request['legal_option_ids'])[0]
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(option,)), None
        if extra:
            seen.append(request)
            if pause:
                raise RuntimeError('Extra target paused')
        use = extra and not decline
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE' if use else 'DECLINE',
            option_ids=(request['legal_option_ids'][0],) if use else ()), None
    engine.set_reaction_provider(provider)
    return seen


@pytest.mark.parametrize('cl', [15, 20])
def test_canon_extra_target_uses_prior_same_turn_damage_and_one_bounded_choice(cl):
    engine, me, foe, other = _canon_extra_fight(cl)
    seen = _canon_extra_provider(engine)
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert te_cond(foe, 'no_temp_hp') and te_cond(other, 'no_temp_hp')
    assert len(seen) == 1 and seen[0]['legal_option_ids'] == [other.entity_id]
    assert all(word in seen[0]['choice_trigger']['prompt'] for word in ('Canon', 'Needle Flick', foe.display_name))
    assert seen[0]['choice_trigger']['labels'][other.entity_id] == other.display_name
    me.action_available = True
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert len(seen) == 1
    engine.end_turn(); engine.end_turn()
    assert not te_cond(other, 'no_temp_hp') and not _mark(me, 'Canon Metal damage this turn')


@pytest.mark.parametrize('boundary', ['lower_realm', 'far', 'old_turn', 'decline', 'not_first_round', 'inactive', 'old_activation'])
def test_canon_extra_target_keeps_eligibility_and_optional_limits(boundary):
    engine, me, foe, other = _canon_extra_fight(14 if boundary == 'lower_realm' else 20)
    if boundary == 'far':
        other.position = other.position.model_copy(update={'x': 12, 'y': 6})
    elif boundary == 'old_turn':
        engine.end_turn(); engine.end_turn()
    elif boundary == 'not_first_round':
        active = _mark(me, 'Seven-Slaughter Canon')[0]
        active.data['sign_round'] = engine.state.round_number
    elif boundary == 'inactive':
        engine._remove_condition(me, te.mark_condition_id('Seven-Slaughter Canon', ME), 'test')
    elif boundary == 'old_activation':
        _mark(me, 'Seven-Slaughter Canon')[0].data.pop('additional_target')
    seen = _canon_extra_provider(engine, decline=boundary == 'decline')
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert not te_cond(other, 'no_temp_hp')
    assert len(seen) == (1 if boundary == 'decline' else 0)
    if boundary in ('lower_realm', 'old_activation'):
        assert 'sign_round' not in _mark(me, 'Seven-Slaughter Canon')[0].data


def test_canon_extra_target_choice_pause_rolls_back_damage_history_and_sign():
    engine, me, foe, other = _canon_extra_fight()
    _canon_extra_provider(engine, pause=True)
    before = engine.state.model_dump(mode='json')
    events = len(engine.events)
    with pytest.raises(RuntimeError, match='Extra target paused'):
        _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert engine.state.model_dump(mode='json') == before and len(engine.events) == events


@pytest.mark.parametrize('immune', [False, True])
def test_canon_extra_target_requires_actual_damage_not_just_a_hit(immune):
    engine, me, foe = _metal(CANON, MT + 'NEEDLE_FLICK')
    other = foe.model_copy(deep=True); other.entity_id = 'lane4:extra'
    other.position = other.position.model_copy(update={'x': 7, 'y': 7})
    engine.state.actors[other.entity_id] = other
    if immune:
        for kind in ('PIERCING', 'SLASHING'):
            engine._add_modifier(other, 'test', 'damage_immunity', 'ADD', kind, 'SELF', expires_on='UNTIL_REMOVED')
    _cast(engine, 'Needle Flick', target=other.entity_id, exact=True)
    me.action_available = True
    _cast(engine, 'White Tiger Seven-Slaughter Canon', exact=True)
    seen = _canon_extra_provider(engine)
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert bool(te_cond(other, 'no_temp_hp')) == (not immune)
    assert bool(seen) == (not immune)


def test_canon_extra_target_rolls_its_own_save_and_allows_exactly_30_feet():
    engine, me, foe, other = _canon_extra_fight()
    other.position = other.position.model_copy(update={'x': 9, 'y': 6})
    assert engine._distance_actor_to_actor(me, other) == 30
    foe.saving_throws['WIS'] = 500; other.saving_throws['WIS'] = -500
    _cast(engine, 'Choose White Tiger Seven-Slaughter Canon: Cut the Coward Road', exact=True)
    seen = _canon_extra_provider(engine)
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert not te_cond(foe, 'cannot_teleport') and te_cond(other, 'cannot_teleport')
    assert len(seen) == 1


def test_canon_extra_target_automatic_ai_choice_spends_no_reaction():
    from combat.gate4_context import build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary
    engine, me, foe, other = _canon_extra_fight()
    controller = LocalDeterministicController()
    engine.set_reaction_provider(lambda request: (controller.choose_reaction(
        build_reaction_context(engine, PolicyLibrary(ROOT).fallback(), request)).decision, None))
    me.reaction_available = False
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert te_cond(other, 'no_temp_hp') and not me.reaction_available


def test_canon_extra_target_history_and_round_allowance_survive_table_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    from combat.gate2_runtime_models import ReactionDecision
    persistence = Gate4Persistence(ROOT, tmp_path)
    from combat.gate2_runtime_content import LEE
    extra_id = LEE
    session = persistence.create_match(match_seed='CANON-EXTRA-8',
        typed_bundles=(copy.deepcopy(_compiled((CANON, MT + 'NEEDLE_FLICK'))),),
        roster_setup={'primary_actor_ids': [ME, AN, extra_id],
                      'team_by_actor': {ME: 'team:a', AN: 'team:b', extra_id: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 6, 'y': 6}, extra_id: {'x': 7, 'y': 7}}})
    def provider(request):
        use = request['reaction_source_id'].endswith('metal_canon_extra')
        if request['reaction_source_id'].endswith('metal_canon_sign'):
            option = (request['choice_trigger'].get('preferred') or request['legal_option_ids'])[0]
            return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(option,)), None
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE' if use else 'DECLINE',
            option_ids=(extra_id,) if use else ()), None
    def submit(name, target=None):
        c = next(c for c in session.engine.legal_candidates() if c.display_name == name
                 and (target is None or target in c.target_ids))
        session.submit_intent(ActionIntent(intent_id='canon-extra-persist', decision_id=c.decision_id,
            candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
            target_ids=c.target_ids, destination=c.destination), primary_decision_record=None,
            reaction_provider=provider)
    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    submit('Needle Flick', extra_id)
    session.engine.state.actors[ME].action_available = True
    submit('White Tiger Seven-Slaughter Canon')
    session = persistence.load_match(session.match_id)
    me = session.engine.state.actors[ME]
    me.action_available = True  # Fixture grants another attack; history/allowance use ordinary commits.
    assert _mark(me, 'Canon Metal damage this turn')[0].data['targets'] == [extra_id]
    expiry = _mark(me, 'Seven-Slaughter Canon')[0].expires_on
    submit('Needle Flick', AN)
    session = persistence.load_match(session.match_id)
    assert te_cond(session.engine.state.actors[extra_id], 'no_temp_hp'), (
        [(r.natural_result, r.total) for r in _attacks(session.engine)],
        session.engine.state.actors[extra_id].current_hp,
        _mark(session.engine.state.actors[ME], 'Seven-Slaughter Canon')[0].data)
    active = _mark(session.engine.state.actors[ME], 'Seven-Slaughter Canon')[0]
    assert active.data['sign_round'] == session.engine.state.round_number and active.expires_on == expiry


def test_open_the_guard_adds_pb_to_the_next_attack_and_is_consumed():
    engine, me, foe = _metal(CANON, MT + 'NEEDLE_FLICK')
    _cast(engine, 'White Tiger Seven-Slaughter Canon', exact=True)
    _cast(engine, 'Choose White Tiger Seven-Slaughter Canon: Open the Guard', exact=True)
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    # Another attack before the caster's next turn: execute its compiled effects through the engine.
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Needle Flick')
    typed = action.parameters['typed']
    te.run_effects(te.Context(engine, me, action, None, typed, [foe], foe, {}), typed['effects'])
    first, second = _attacks(engine)
    assert second.modifier == first.modifier + 4
    assert not te_cond(foe, 'exposed')


@pytest.mark.parametrize('passed', [True, False])
def test_ring_the_flaw_rolls_its_printed_dc_and_gives_target_bound_advantage_only_on_success(passed):
    engine, me, foe = _metal(MT + 'RING_THE_FLAW', MT + 'NEEDLE_FLICK')
    # The Sphere check is d20 + PB + key modifier; bounded extremes preserve deterministic result.
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Ring the Flaw: Attack Advantage')
    action.parameters['typed']['numbers']['key_mod'] = 500 if passed else -500
    _cast(engine, 'Ring the Flaw: Attack Advantage', target=foe.entity_id, exact=True)
    assert bool(_mark(foe, 'Ring the Flaw')) == passed
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED']
    assert checks[-1].payload['dc'] == 15 and checks[-1].payload['success'] == passed
    engine.end_turn(); engine.end_turn()
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert _attacks(engine)[-1].mode == ('ADVANTAGE' if passed else 'NORMAL')
    assert not _mark(foe, 'Ring the Flaw')


def test_white_tiger_severance_blocks_healing_after_slashing_damage_and_scales_at_nascent_soul():
    engine, me, foe = _metal(MT + 'WHITE_TIGER_SEVERANCE')
    _cast(engine, 'White Tiger Severance', target=foe.entity_id, exact=True)
    assert any(m.target_field == 'healing_reduction' for m in foe.modifiers.values())
    assert any(r.expression.startswith('8d8') for r in engine.rolls if r.reason.startswith('DAMAGE:'))
    engine.end_turn(); engine.end_turn()
    assert not any(m.target_field == 'healing_reduction' for m in foe.modifiers.values())


def test_ore_root_snare_triggers_only_for_the_first_enemy_in_the_casting():
    from combat import zones
    engine, me, foe = _metal(MT + 'ORE_ROOT_SNARE')
    foe.saving_throws['STR'] = -500
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith('Ore-Root Snare at ')
                     and c.destination == foe.position)
    engine.execute_intent(ActionIntent(intent_id='ore', decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    assert not [r for r in engine.rolls if r.reason.startswith('SAVE:')]  # no immediate save on casting
    zones.on_turn_start(engine, foe)
    assert engine._effective_speed(foe) == 0
    other = foe.model_copy(deep=True); other.entity_id = 'lane4:other'; other.conditions = {}; other.modifiers = {}
    other.position = foe.position.model_copy(update={'y': 7}); engine.state.actors[other.entity_id] = other
    before = len(engine.rolls)
    zones.on_turn_start(engine, other)
    assert len(engine.rolls) == before and engine._effective_speed(other) == other.speed_ft


def test_mountain_ore_dictate_runs_cast_choice_then_the_changed_next_turn_choice():
    engine, me, foe = _metal(MT + 'MOUNTAIN_ORE_DICTATE', foe_at=(9, 6))
    foe.saving_throws.update({'DEX': -500, 'STR': -500})
    candidate = next(c for c in engine.legal_candidates() if c.display_name == 'Mountain-Ore Dictate at 6,6')
    engine.execute_intent(ActionIntent(intent_id='mountain', decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    assert any(r.expression.startswith('4d8') for r in engine.rolls if r.reason.startswith('DAMAGE:'))
    assert foe.position.x == 9
    _cast(engine, 'Choose Mountain-Ore Dictate: Pull toward the center', exact=True)
    before = len(engine.rolls)
    engine.end_turn(); engine.end_turn()
    # Printed eligibility is significant metal, not every enemy in the area.
    # Until equipment provenance exists the pull is a GM line, never a blanket pull.
    assert foe.position.x == 9 and len(engine.rolls) == before
    assert not te_cond(me, 'mountain_ore_repeat')


def test_canon_sign_stops_at_its_minute_and_shares_one_allowance_across_attacks():
    engine, me, foe = _metal(CANON, MT + 'NEEDLE_FLICK')
    _cast(engine, 'White Tiger Seven-Slaughter Canon', exact=True)
    _cast(engine, 'Choose White Tiger Seven-Slaughter Canon: Open the Guard', exact=True)
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Needle Flick')
    typed = action.parameters['typed']
    te.run_effects(te.Context(engine, me, action, None, typed, [foe], foe, {}), typed['effects'])
    assert not te_cond(foe, 'exposed')  # the second hit consumed the old sign and did not place another
    for _ in range(20):
        engine.end_turn()
    assert not _mark(me, 'Seven-Slaughter Canon')
    _cast(engine, 'Needle Flick', target=foe.entity_id, exact=True)
    assert not te_cond(foe, 'exposed')


@pytest.mark.parametrize('cl,survives_start', [(5, False), (10, True), (20, True)])
def test_iron_filings_cloud_core_formation_upgrade_lasts_through_next_turn_start(cl, survives_start):
    engine, me, foe = _metal(MT + 'IRON_FILINGS_CLOUD', cl=cl)
    foe.saving_throws['DEX'] = -500
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith('Iron Filings Cloud at ')
                     and c.destination == foe.position)
    engine.execute_intent(ActionIntent(intent_id='filings', decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    def clouds():
        return [z for z in engine.state.zones.values() if z.active and z.source_definition_id == candidate.source_definition_id]
    assert clouds()
    engine.end_turn(); engine.end_turn()
    assert bool(clouds()) == survives_start
    engine.end_turn()
    assert not clouds()


@pytest.mark.parametrize('cl,bonus,survives,thorns', [(10, 500, True, False), (15, 500, True, True), (15, -500, False, False)])
def test_iron_marrow_sutra_rolls_own_dc_before_zero_ends_on_success_and_bursts_at_nascent(cl, bonus, survives, thorns):
    from combat.ext import riders_metal
    engine, me, foe = _metal('tianxia.talent.metal.indestructible_iron_marrow_sutra', cl=cl, foe_at=(5, 6))
    _cast(engine, 'Indestructible Iron Marrow Sutra', exact=True)
    assert te_cond(me, 'iron_marrow_sutra')
    me.current_hp = 2; me.temporary_hp = 0; me.saving_throws['CON'] = bonus
    before = foe.current_hp
    intent = ActionIntent(intent_id='incoming', decision_id='test', candidate_id='test', state_version=0,
                          actor_id=AN, target_ids=(ME,))
    engine._commit_damage(me, 3, 'FORCE', 'test:lethal', AN, intent, reaction_depth=0)
    assert (me.current_hp == 1 and me.active) == survives
    assert bool(te_cond(me, 'iron_marrow_sutra')) == (not survives)
    assert (foe.current_hp < before) == thorns
    saves = [r for r in engine.rolls if r.reason.startswith('SAVE:')]
    assert len(saves) == 1
    if survives:
        assert not any(m.source_definition_id.endswith('tianxia.talent.metal.indestructible_iron_marrow_sutra')
                       for m in me.modifiers.values())
    if thorns:
        assert any(r.expression == '3d8+2' and 'IRON_MARROW_THORNS' in r.reason for r in engine.rolls)


def test_iron_marrow_failed_attempt_is_once_per_round_and_survives_state_roundtrip():
    from combat.ext import riders_metal
    engine, me, foe = _metal('tianxia.talent.metal.indestructible_iron_marrow_sutra', cl=10)
    _cast(engine, 'Indestructible Iron Marrow Sutra', exact=True)
    me.saving_throws['CON'] = -500
    assert riders_metal.marrow_save(engine, me, 10000, AN) is None
    count = len(engine.rolls)
    engine.state = type(engine.state).model_validate_json(engine.state.model_dump_json())
    me = engine.state.actors[ME]
    assert riders_metal.marrow_save(engine, me, 10000, AN) is None and len(engine.rolls) == count
    state = te_cond(me, 'iron_marrow_sutra')[0]
    assert state.data['attempt_round'] == engine.state.round_number
    events = [e for e in engine.events if e.event_type == 'CONDITION_APPLIED' and e.payload.get('condition_id') == riders_metal.MARROW]
    assert events  # engine methods record the condition changes; its data survive snapshot serialization


@pytest.mark.parametrize('cells,save,moved,no_reactions', [(1, None, True, False), (2, None, True, False), (3, -500, True, False), (3, 500, False, True)])
def test_push_shot_size_rule(cells, save, moved, no_reactions):
    """"A creature more than one size larger than you may make a Strength saving throw to resist the push. On a successful save, it is
    not pushed, but it cannot take Reactions until the start of your next turn." """
    engine, me, foe = _snipe(SN + 'PUSH_SHOT')
    _large(engine, foe, cells)
    if save is not None: foe.saving_throws['STR'] = save
    before = foe.position.x
    _cast(engine, 'Push Shot')
    assert (foe.position.x > before) == moved
    assert bool(_cond_rule(foe, 'reaction_denied')) == no_reactions


def test_push_shot_into_a_wall_knocks_the_target_prone_instead():
    """"If this movement forces the target into a solid object, it instead falls Prone and the movement ends." """
    engine, me, foe = _snipe(SN + 'PUSH_SHOT', foe_at=(19, 6))
    edge = foe.position.x
    _cast(engine, 'Push Shot')
    assert foe.position.x == edge and _cond_rule(foe, 'prone')


@pytest.mark.parametrize('reload_state', [False, True])
def test_metal_domain_recast_replaces_old_area_and_only_new_area_triggers(reload_state):
    key = 'TAL_METAL_DOMAIN_OF_TEN_THOUSAND_BLADES'
    engine, me, foe = _fight(key)
    _cast(engine, 'Domain of Ten Thousand Blades')
    old = next(z for z in engine.state.zones.values() if z.owner_id == ME and z.active)
    engine.end_turn(); engine.end_turn()
    if reload_state:
        engine.state = type(engine.state).model_validate_json(engine.state.model_dump_json())
    _cast(engine, 'Domain of Ten Thousand Blades')
    active = [z for z in engine.state.zones.values() if z.owner_id == ME and z.active]
    assert len(active) == 1 and active[0].zone_id != old.zone_id
    assert not engine.state.zones[old.zone_id].active
    assert any(e.event_type == 'ZONE_REMOVED' and e.payload.get('zone_id') == old.zone_id
               and e.payload.get('reason') == 'REPLACED' for e in engine.events)
    before = len([r for r in engine.rolls if r.reason.startswith('SAVE:')])
    engine.end_turn()
    assert len([r for r in engine.rolls if r.reason.startswith('SAVE:')]) == before + 1


def test_metal_domain_replacement_preserves_other_owners_and_unrelated_areas():
    key = 'TAL_METAL_DOMAIN_OF_TEN_THOUSAND_BLADES'
    engine, me, foe = _fight(key, 'TAL_METAL_ORE_ROOT_SNARE')
    _cast(engine, 'Domain of Ten Thousand Blades')
    old = next(z for z in engine.state.zones.values() if z.owner_id == ME and z.active)
    # A second owner's same domain and the caster's unrelated area must survive.
    foreign = old.model_copy(deep=True, update={'zone_id': 'lane4:foreign-domain', 'owner_id': AN})
    engine.state.zones[foreign.zone_id] = foreign
    other_action = next(a for a in engine.action_catalog.values() if 'Ore-Root Snare' in a.display_name)
    unrelated = old.model_copy(deep=True, update={'zone_id': 'lane4:other-area',
                                                 'source_definition_id': other_action.source_definition_id})
    engine.state.zones[unrelated.zone_id] = unrelated
    engine.end_turn(); engine.end_turn()
    _cast(engine, 'Domain of Ten Thousand Blades')
    assert foreign.active and unrelated.active and not old.active


def test_metal_domain_replacement_matches_mechanic_across_compiled_action_ids():
    key = 'TAL_METAL_DOMAIN_OF_TEN_THOUSAND_BLADES'
    engine, me, foe = _fight(key)
    _cast(engine, 'Domain of Ten Thousand Blades')
    old = next(z for z in engine.state.zones.values() if z.owner_id == ME and z.active)
    action = engine.action_catalog[old.source_definition_id]
    # Saved choice variants can have different action IDs for the same mechanic.
    variant = action.model_copy(update={'source_definition_id': action.source_definition_id + '.piercing'})
    engine.action_catalog[variant.source_definition_id] = variant
    old.source_definition_id = variant.source_definition_id
    engine.end_turn(); engine.end_turn()
    _cast(engine, 'Domain of Ten Thousand Blades')
    assert not old.active
    assert len([z for z in engine.state.zones.values() if z.owner_id == ME and z.active]) == 1


def test_metal_domain_replacement_survives_persistent_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    key = 'TAL_METAL_DOMAIN_OF_TEN_THOUSAND_BLADES'
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed='LANE4-DOMAIN',
        typed_bundles=(copy.deepcopy(_compiled((key,))),),
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 15, 'y': 6}}})

    def submit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.submit_intent(ActionIntent(intent_id='lane4-persist', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination),
            primary_decision_record=None, reaction_provider=None)

    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    submit('Domain of Ten Thousand Blades')
    old_id = next(z.zone_id for z in session.engine.state.zones.values() if z.owner_id == ME and z.active)
    submit('End turn')
    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    session = persistence.load_match(session.match_id)
    assert session.engine.state.zones[old_id].active
    submit('Domain of Ten Thousand Blades')
    session = persistence.load_match(session.match_id)
    assert not session.engine.state.zones[old_id].active
    assert len([z for z in session.engine.state.zones.values() if z.owner_id == ME and z.active]) == 1


def _domain_bonus(choice='Sharpen', *, foe_at=(6, 6), active=True, extra=()):
    from combat.gate2_runtime_models import ReactionDecision

    engine, me, foe = _metal(MT + 'DOMAIN_OF_TEN_THOUSAND_BLADES', MT + 'NEEDLE_FLICK', *extra, foe_at=foe_at)
    _cast(engine, 'Domain of Ten Thousand Blades')
    engine.end_turn(); engine.end_turn()
    if not active:
        from combat import zones
        zones.remove(engine, next(z for z in engine.state.zones.values() if z.active), 'TEST_END')
    seen = []
    def provider(request):
        seen.append(request)
        use = request['reaction_source_id'].endswith('metal_domain_expression') and choice is not None
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE' if use else 'DECLINE',
            option_ids=(choice,) if use else ()), None
    engine.set_reaction_provider(provider)
    return engine, me, foe, seen


@pytest.mark.parametrize('choice', ['Sharpen', 'Weight: Push 5 feet', 'Weight: Pull 5 feet'])
def test_metal_domain_bonus_preserves_normal_expression_and_does_not_double_the_hit(choice):
    engine, me, foe, seen = _domain_bonus(choice)
    foe.saving_throws['STR'] = -500
    before = foe.position.x
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert me.turn_flags.get('typed_modifier_once:' + MT + 'DOMAIN_OF_TEN_THOUSAND_BLADES') == 1
    assert not me.turn_flags.get('typed_modifier_once:METAL_BASE_SHARPEN')
    assert not me.turn_flags.get('typed_modifier_once:METAL_BASE_WEIGHT')
    assert foe.position.x == before + (1 if 'Push' in choice else -1 if 'Pull' in choice else 0)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == ME]
    # Aura damage precedes this action. Exactly one PB-sized Sharpen packet on this hit.
    flick = [e for e in packets if 'NEEDLE_FLICK' in e.source_definition_id]
    assert len(flick) == (2 if choice == 'Sharpen' else 1)
    if choice == 'Sharpen':
        action = engine.action_catalog[flick[-1].source_definition_id]
        assert flick[-1].payload['rolled_or_pending_damage'] == action.parameters['typed']['numbers']['pb']
    requests = [r for r in seen if r['reaction_source_id'].endswith('metal_domain_expression')]
    assert len(requests) == 1
    prompt = requests[0]['choice_trigger']['prompt']
    assert all(text in prompt for text in ['Domain of Ten Thousand Blades', 'Needle Flick', foe.display_name])
    # A second hit still gets the ordinary expression; the shared domain allowance is exhausted.
    me.action_available = True
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert me.turn_flags.get('typed_modifier_once:METAL_BASE_SHARPEN')
    assert len([r for r in seen if r['reaction_source_id'].endswith('metal_domain_expression')]) == 1


@pytest.mark.parametrize('choice', [None, 'Sharpen'])
def test_metal_domain_bonus_is_optional_and_shared_after_normal_use(choice):
    engine, me, foe, seen = _domain_bonus(choice)
    me.turn_flags['typed_modifier_once:METAL_BASE_SHARPEN'] = True
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert bool(me.turn_flags.get('typed_modifier_once:' + MT + 'DOMAIN_OF_TEN_THOUSAND_BLADES')) == (choice is not None)
    assert any(r['reaction_source_id'].endswith('metal_domain_expression') for r in seen)


@pytest.mark.parametrize('active,foe_at', [(False, (6, 6)), (True, (10, 6))])
def test_metal_domain_bonus_needs_active_owned_area_and_target_inside(active, foe_at):
    engine, me, foe, seen = _domain_bonus(active=active, foe_at=foe_at)
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert not any(r['reaction_source_id'].endswith('metal_domain_expression') for r in seen)


def test_metal_domain_bonus_choice_pause_propagates():
    engine, me, foe, seen = _domain_bonus()

    class Paused(Exception):
        pass

    def pause(request):
        if request['reaction_source_id'].endswith('metal_domain_expression'):
            raise Paused()
        from combat.gate2_runtime_models import ReactionDecision
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='DECLINE'), None

    engine.set_reaction_provider(pause)
    before = engine.state.model_dump(mode='json')
    with pytest.raises(Paused):
        _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert engine.state.model_dump(mode='json') == before


def test_metal_domain_bonus_persisted_use_survives_table_commit_reload_and_resets_next_turn(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    from combat.gate2_runtime_models import ReactionDecision

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed='LANE4-DOMAIN-BONUS',
        typed_bundles=(copy.deepcopy(_compiled((MT + 'DOMAIN_OF_TEN_THOUSAND_BLADES', MT + 'NEEDLE_FLICK'))),),
        roster_setup={'primary_actor_ids': [ME, AN], 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 6, 'y': 6}}})

    def provider(request):
        use = request['reaction_source_id'].endswith('metal_domain_expression')
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE' if use else 'DECLINE',
            option_ids=('Sharpen',) if use else ()), None

    def submit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.submit_intent(ActionIntent(intent_id='lane4-bonus-persist', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination),
            primary_decision_record=None, reaction_provider=provider)

    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    submit('Domain of Ten Thousand Blades')
    submit('End turn')
    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    submit('Needle Flick')
    session = persistence.load_match(session.match_id)
    actor = session.engine.state.actors[ME]
    assert actor.turn_flags.get('typed_modifier_once:' + MT + 'DOMAIN_OF_TEN_THOUSAND_BLADES') == 1
    assert not actor.turn_flags.get('typed_modifier_once:METAL_BASE_SHARPEN')
    submit('End turn')
    while session.engine.state.current_actor_id != ME:
        submit('End turn')
    assert not session.engine.state.actors[ME].turn_flags.get('typed_modifier_once:' + MT + 'DOMAIN_OF_TEN_THOUSAND_BLADES')


@pytest.mark.parametrize('mode', ['immune', 'foreign', 'enemy_turn'])
def test_metal_domain_bonus_requires_damage_ownership_and_the_owners_turn(mode):
    engine, me, foe, seen = _domain_bonus()
    if mode == 'immune':
        for kind in ('PIERCING', 'SLASHING'):
            engine._add_modifier(foe, 'test:immunity', 'damage_immunity', 'ADD', kind, 'SELF', expires_on='UNTIL_REMOVED')
    elif mode == 'foreign':
        next(z for z in engine.state.zones.values() if z.active).owner_id = AN
    else:
        # A typed out-of-turn damage checkpoint keeps the caster and intent identities.
        action = next(a for a in engine.action_catalog.values() if a.display_name == 'Needle Flick')
        candidate = next(c for c in engine.legal_candidates() if c.display_name == 'Needle Flick' and c.target_ids == (AN,))
        intent = ActionIntent(intent_id='lane4-offturn', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME, target_ids=(AN,))
        engine.state.current_actor_id = AN
        te.run_effects(te.Context(engine, me, action, intent, action.parameters['typed'], [foe], foe, {}),
                      [{'type': 'damage', 'flat': 1, 'damage_types': ['piercing']}])
        assert not any(r['reaction_source_id'].endswith('metal_domain_expression') for r in seen)
        return
    _cast(engine, 'Needle Flick', target=AN, exact=True)
    assert not any(r['reaction_source_id'].endswith('metal_domain_expression') for r in seen)


def test_metal_domain_bonus_runs_on_save_damage_and_ai_automatically_chooses():
    engine, me, foe, seen = _domain_bonus(extra=(MT + 'HUNDRED_NEEDLES_FAN',))
    engine.set_reaction_provider(None)
    _cast(engine, 'Hundred Needles Fan')
    assert me.turn_flags.get('typed_modifier_once:' + MT + 'DOMAIN_OF_TEN_THOUSAND_BLADES') == 1
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Hundred Needles Fan')
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == action.source_definition_id]
    # The printed fan hits each creature, including its caster. The once-only
    # domain bonus remains one packet; the fan has one packet per recipient.
    fan = [packet for packet in packets if packet.payload['damage_type'] == 'PIERCING']
    bonus = [packet for packet in packets if packet.payload['damage_type'] == 'SLASHING']
    assert len(fan) == 2 and len(packets) == 3
    assert {target for packet in fan for target in packet.target_ids} == {me.entity_id, foe.entity_id}
    assert len(bonus) == 1 and bonus[0].payload['rolled_or_pending_damage'] == action.parameters['typed']['numbers']['pb']
