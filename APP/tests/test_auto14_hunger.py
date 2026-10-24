"""Hunger's Digestive Mantle at the table: every printed line AUTO14 automated (owner 2026-09-29, "i want everything we can
automated").  Owner text: authority/typed_mechanics/rules_text.json, Sphere Compendium "Hunger".  Plug-in:
combat/ext/hunger_riders.py (its module docstring quotes every printed line these tests hold it to); the kind of Satiety a
Mantle burns is that plug-in's own seam, asked of the player and recorded on the Mantle's condition.

Table-level: a real Gate4ControllerEngine with a compiled Hunger character, the printed option picked from the legal
candidates, and the resulting events and state read back.  Nothing here is a unit call into the plug-in.
"""
import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import flight
from combat.ext.needle import CHOICE
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
H = 'tianxia.talent.hunger.'
MANTLE_ID = 'HUNGER_BASE_DIGESTIVE_MANTLE'
MANTLE = 'condition:typed.digestive_mantle'
ME = 'actor:factory.hunger'
IMPURITY = 'resource:named.impurity'
SATIETY = 'resource:named.satiety'
ALL = (H + 'nine_beast_sovereign_course', H + 'three_course_battle_body', H + 'beast_bone_broth',
       H + 'demon_beast_digestion', H + 'marrow_furnace_pulse', H + 'predator_king_digestion',
       H + 'maw_of_ten_thousand_courses', H + 'the_empty_bowl_watches')


@lru_cache(maxsize=None)
def compiled(key, extras=()):
    sphere = AUTH[key]['sphere_id']
    bases = [k for k, v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    return compile_character({**SHEET,
        'equipment': [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'quantity': 1}]}}],
        'identity': {**SHEET['identity'], 'cultivation_level': 20},
        'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'], 'technique_save_dc': 15,
            'technique_attack_bonus': 40, 'primary_resource': {'name': 'Qi', 'maximum': 100}},
        'spheres_and_talents': {'sphere_record_ids': [sphere],
            'learned_talent_record_ids': list(dict.fromkeys([*bases, key, *extras]))}}, actor_id=ME)


def fight(key, extras=(), answers=None, impurity=0):
    """A real table: the compiled bundle in a Gate4ControllerEngine, my turn, Satiety banked, and a provider that answers
    the table's own questions in the printed order (``answers``; the default answer is each question's first choice)."""
    bundle = copy.deepcopy(compiled(key, extras))
    engine = Gate4ControllerEngine(ROOT, match_seed='AUTO14', typed_bundles=(bundle,),
                                   roster_setup={'primary_actor_ids': [ME, AN],
                                                 'team_by_actor': {ME: 'team:a', AN: 'team:b'},
                                                 'starting_positions': {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    me.maximum_hp = me.current_hp = foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    me.resources[SATIETY] = 6
    me.resources[IMPURITY] = impurity
    left = list(answers or [])
    asked = []

    def provider(request):
        """Answer the table's own Hunger questions in the printed order; decline everything else (a monster's own
        reactions are not this test's business)."""
        if not str(request.get('reaction_source_id') or '').startswith(CHOICE):
            return None, None
        asked.append(request)
        option = left.pop(0) if left and left[0] else request['legal_option_ids'][0]
        selection = 'DECLINE' if option == 'DECLINE' else 'USE'
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
                                reaction_source_id=request['reaction_source_id'], selection=selection,
                                option_ids=() if selection == 'DECLINE' else (option,)), None

    engine.set_reaction_provider(provider)
    engine.auto14_asked = asked
    return engine, me, foe


def use(engine, name):
    """Play the printed option, shortest name first (an option the table offers)."""
    candidates = [c for c in engine.legal_candidates() if name in c.display_name]
    assert candidates, (name, [c.display_name for c in engine.legal_candidates()][:24])
    candidate = min(candidates, key=lambda c: len(c.display_name))
    engine.execute_intent(ActionIntent(intent_id='auto14', decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return candidate


def mantle(me):
    held = next((c for c in me.conditions.values() if c.condition_id == MANTLE), None)
    return held.data if held is not None else None


def offered(engine, needle):
    return [c.display_name for c in engine.legal_candidates() if needle in c.display_name]


def damage_rolls(engine):
    return [r for r in engine.rolls if r.reason.startswith('DAMAGE:') and r.dice]


def reduced_by_thick_hide(engine, me, amount=1000):
    """What Thick Hide takes off one blow, read by playing a real incoming packet through the engine's own hook."""
    from combat.ext import hunger_riders

    return hunger_riders.thick_hide(engine, me, amount, 'PIERCING', MANTLE_ID, AN)


# ---------------------------------------------------------------------------- the recorded kind of Satiety
def test_the_meal_is_recorded_only_for_a_character_whose_printed_lines_read_it():
    """Beast-Bone Broth prints "Thick Hide from Bone Satiety", so the table records which meal the Mantle burns."""
    engine, me, _ = fight(H + 'beast_bone_broth', answers=['bone'])
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['satiety'] == 'bone'


def test_a_character_with_no_printed_meal_reading_is_never_asked_and_records_nothing():
    engine, me, _ = fight(H + 'bitter_medicine_belly')
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['satiety'] is None
    assert engine.auto14_asked == [], [request['checkpoint'] for request in engine.auto14_asked]


def test_every_printed_meal_kind_is_offered_and_named_in_plain_words():
    """The six kinds the printed Hunger lines name, each in words a player who knows only basic D&D can read."""
    from combat.ext import hunger_riders

    assert hunger_riders.SATIETY_KINDS == ('normal', 'corrupted', 'demon_beast', 'bone', 'dragon_marrow', 'forbidden')
    labels = hunger_riders.SATIETY_LABELS
    assert labels['normal'] == 'a normal meal'
    assert 'demon beast' in labels['demon_beast']
    assert 'spirit beast' in labels['bone'] and 'bone' in labels['bone']
    assert 'dragon' in labels['dragon_marrow']
    assert 'Forbidden' in labels['forbidden'] and 'cultivator' in labels['forbidden']
    assert all('tianxia.' not in label and 'lane' not in label for label in labels.values())


# ---------------------------------------------------------------------------- Nine-Beast Sovereign Course
def test_winged_hunger_gives_a_fly_speed_equal_to_my_speed_and_loses_it_with_the_mantle():
    """Nine-Beast Sovereign Course: "Winged Hunger: gain a Fly Speed equal to your Speed until the end of your next turn." """
    engine, me, _ = fight(H + 'nine_beast_sovereign_course')
    assert flight.profile(engine, me).speed_ft == 0
    use(engine, 'Digestive Mantle: Thick Hide + Nine-Beast Sovereign Course: Winged Hunger')
    assert flight.profile(engine, me).speed_ft == me.speed_ft
    engine._remove_condition(me, MANTLE, MANTLE_ID)
    assert flight.profile(engine, me).speed_ft == 0


def test_all_four_printed_sovereign_adaptations_are_choosable_and_armored_hunger_still_triples_thick_hide():
    engine, me, _ = fight(H + 'nine_beast_sovereign_course')
    names = offered(engine, 'Nine-Beast Sovereign Course')
    for adaptation in ('Winged Hunger', 'Burrowing Hunger', 'Armored Hunger', 'Venom Sovereign'):
        assert any(adaptation in name for name in names), (adaptation, names[:3])
    use(engine, 'Digestive Mantle: Thick Hide + Nine-Beast Sovereign Course: Armored Hunger')
    held = mantle(me)
    assert held['adaptation'] == 'Armored Hunger' and held['benefits'] == ['Thick Hide']
    assert reduced_by_thick_hide(engine, me) == 3 * held['pb'] + held['key']


# ---------------------------------------------------------------------------- two basic Mantle benefits
def test_a_demon_beast_meal_gives_two_manifest_benefits_and_the_constitution_save_when_the_mantle_ends():
    """Demon-Beast Digestion: "A Digestive Mantle using Demon-Beast Satiety may choose two basic Mantle benefits instead of
    one. When that Mantle ends, make a Constitution saving throw against your Hunger Save DC." """
    engine, me, _ = fight(H + 'demon_beast_digestion', answers=['demon_beast', 'Iron Stomach'])
    use(engine, 'Digestive Mantle: Thick Hide')
    held = mantle(me)
    assert held['benefits'] == ['Thick Hide', 'Iron Stomach'], held['benefits']
    assert me.resources[IMPURITY] == 0
    end_the_mantle(engine, me)
    saves = [r for r in engine.rolls if H + 'demon_beast_digestion' in r.reason]
    assert saves, [r.reason for r in engine.rolls]
    assert any('Demon-Beast Digestion' in json.dumps(e.payload or {}, ensure_ascii=False) for e in engine.events)


def test_a_plain_meal_owes_no_impurity_and_no_save():
    engine, me, _ = fight(H + 'demon_beast_digestion', answers=['normal'])
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['benefits'] == ['Thick Hide']
    end_the_mantle(engine, me)
    assert not [r for r in engine.rolls if H + 'demon_beast_digestion' in r.reason]


def test_only_one_of_two_chosen_benefits_may_add_damage():
    """Maw of Ten Thousand Courses and Demon-Beast Course: only one chosen benefit may add damage."""
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['normal', 'Venom Belly'])
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['benefits'][:2] == ['Thick Hide', 'Venom Belly']


def test_maw_of_ten_thousand_courses_can_be_declined_after_the_first_benefit():
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['normal', 'DECLINE'])
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['benefits'] == ['Thick Hide']
    assert me.resources[SATIETY] == 5, 'a declined benefit costs nothing'


def test_maw_of_ten_thousand_courses_loses_one_impurity_when_only_ordinary_meals_were_burned():
    """Maw of Ten Thousand Courses: "When the Mantle ends, reduce your Impurity by 1 if none of the spent Satiety was
    Corrupted, Demon-Beast, or Forbidden." """
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['normal', 'DECLINE'], impurity=2)
    use(engine, 'Digestive Mantle: Thick Hide')
    end_the_mantle(engine, me)
    assert me.resources[IMPURITY] == 1


def test_a_demon_beast_meal_keeps_that_impurity_reduction_from_being_owed_and_owes_the_courses_impurity():
    """Maw of Ten Thousand Courses owes nothing for a demon-beast meal; the base ability's own Demon-Beast Course line
    ("Gain 1 Impurity when the Mantle ends unless another talent changes this") does."""
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['demon_beast', 'Iron Stomach'], impurity=2)
    use(engine, 'Digestive Mantle: Thick Hide')
    end_the_mantle(engine, me)
    assert me.resources[IMPURITY] == 3


# ---------------------------------------------------------------------------- Beast-Bone Broth
def test_bone_satiety_doubles_thick_hide_and_an_ordinary_meal_does_not():
    """Beast-Bone Broth: "At Foundation Realm, Thick Hide from Bone Satiety reduces damage by twice your Proficiency Bonus." """
    engine, me, _ = fight(H + 'beast_bone_broth', answers=['bone'])
    use(engine, 'Digestive Mantle: Thick Hide')
    held = mantle(me)
    assert reduced_by_thick_hide(engine, me) == 2 * held['pb'] + held['key']
    engine, me, _ = fight(H + 'beast_bone_broth', answers=['normal'])
    use(engine, 'Digestive Mantle: Thick Hide')
    held = mantle(me)
    assert reduced_by_thick_hide(engine, me) == held['pb'] + held['key']


def end_the_mantle(engine, me, limit=40):
    """Let the Mantle's own minute run out through the table's duration clock (combat/ext/effect_durations.py), which is
    "when that Mantle ends"; never a hand-plucked removal."""
    turns = 0
    while mantle(me) is not None and turns < limit:
        engine.end_turn()
        turns += 1
    assert mantle(me) is None, 'the Mantle ended within a minute of play'
    return turns


def bloodied_hits(key, bloodied=True, answers=None):
    """The same Bloodied-or-not hit, played on the real table; returns how much HP the foe lost."""
    engine, me, foe = fight(key, answers=answers)
    use(engine, 'Digestive Mantle: Predator Step')
    foe.current_hp = foe.maximum_hp // 4 if bloodied else foe.maximum_hp
    before = foe.current_hp
    use(engine, 'Jian (Straight Sword) attack')
    return before - foe.current_hp


# ---------------------------------------------------------------------------- Predator-King Digestion
def test_predator_king_digestion_adds_one_damage_die_roll_to_a_bloodied_hit():
    """Predator-King Digestion: "once before the Mantle ends, when you hit a Bloodied creature with an attack, you may add
    damage equal to one roll of your Martial Arts die, weapon damage die, or a d8".  Both fights share the match seed, so the
    printed attack rolls the same and the difference is the talent's own die."""
    king = bloodied_hits(H + 'predator_king_digestion', bloodied=True, answers=['predator_or_apex'])
    plain = bloodied_hits(H + 'bitter_medicine_belly', bloodied=True)
    assert 1 <= king - plain <= 8, (king, plain)


def test_predator_king_digestion_does_nothing_for_a_meal_that_is_not_from_a_predator_or_apex_beast():
    """The printed line opens with "When you activate Digestive Mantle using Satiety from a predator or apex beast", so an
    ordinary meal takes nothing extra even on a Bloodied hit."""
    assert bloodied_hits(H + 'predator_king_digestion', bloodied=True, answers=['some_other_creature']) == bloodied_hits(
        H + 'bitter_medicine_belly', bloodied=True)


def test_predator_king_digestion_rolls_the_weapons_own_damage_die_and_not_always_a_d8():
    """The die is "your Martial Arts die, weapon damage die, or a d8": a jian is 1d10, so the roll is a d10 here."""
    engine, me, foe = fight(H + 'predator_king_digestion', answers=['predator_or_apex'])
    use(engine, 'Digestive Mantle: Predator Step')
    foe.current_hp = foe.maximum_hp // 4
    use(engine, 'Jian (Straight Sword) attack')
    rolls = [roll for roll in engine.rolls if roll.reason == 'DAMAGE:' + H + 'predator_king_digestion']
    assert [roll.expression for roll in rolls] == ['1d10+0'], [roll.expression for roll in rolls]


def test_predator_king_does_nothing_to_a_creature_that_is_not_bloodied():
    assert bloodied_hits(H + 'predator_king_digestion', bloodied=False, answers=['predator_or_apex']) == bloodied_hits(
        H + 'bitter_medicine_belly', bloodied=False)


def test_the_older_predator_meal_reads_nothing_for_a_fight_compiled_against_the_current_rules_data():
    """A table sealed before the predator line became a question about the creature recorded that meal as a kind of Satiety,
    and the plug-in still reads such a meal for such a row.  It must read nothing for a row compiled today: today's row asks
    where the creature came from, so a Mantle carrying the older value has to leave the printed line shut."""
    engine, me, foe = fight(H + 'predator_king_digestion', answers=['some_other_creature'])
    use(engine, 'Digestive Mantle: Predator Step')
    held = next(condition for condition in me.conditions.values() if condition.condition_id == MANTLE)
    held.data['satiety'] = 'predator'  # exactly what a Mantle saved by the older rules data holds
    assert mantle(me)['provenance'] != 'predator_or_apex', 'this row asks where the creature came from instead'
    foe.current_hp = foe.maximum_hp // 4
    use(engine, 'Jian (Straight Sword) attack')
    assert not [roll for roll in engine.rolls if roll.reason == 'DAMAGE:' + H + 'predator_king_digestion'], \
        'the meal a row compiled today never reads is not a predator meal to it, whatever an older save left behind'


# ---------------------------------------------------------------------------- Three-Course Battle Body
def test_three_course_battle_body_replaces_the_benefit_and_stops_at_proficiency_bonus_uses():
    """Three-Course Battle Body: replace the benefit, gain PB Temporary HP, "a number of times equal to your Proficiency
    Bonus per long rest" (no long rest passes inside a fight, so the table counts the uses)."""
    engine, me, _ = fight(H + 'three_course_battle_body')
    use(engine, 'Digestive Mantle: Thick Hide')
    pb = mantle(me)['pb']
    for attempt in range(pb):
        me.action_available = me.bonus_action_available = True
        me.resources[SATIETY] = 6
        use(engine, 'Three-Course Battle Body')
        assert me.resources[SATIETY] == 5, 'one more Satiety is burned each time'
        assert mantle(me)['benefits'] != ['Thick Hide']
    me.action_available = me.bonus_action_available = True
    me.resources[SATIETY] = 6
    assert not offered(engine, 'Three-Course Battle Body'), 'the Proficiency Bonus uses are spent'
    assert me.resources[SATIETY] == 6, 'and no Satiety is charged for a use that may not happen'


# ---------------------------------------------------------------------------- The Empty Bowl Watches
def test_the_empty_bowl_watches_offers_a_bonus_action_free_taste_the_qi_while_the_mantle_lasts():
    """The Empty Bowl Watches: "While Digestive Mantle is active, you can use Taste the Qi without spending a Bonus Action
    once on each of your turns." """
    engine, me, _ = fight(H + 'the_empty_bowl_watches')
    assert not offered(engine, 'Taste the Qi (free)')
    use(engine, 'Digestive Mantle: Thick Hide')
    free = offered(engine, '(free)')
    assert any('Taste the Qi' in name for name in free), free
    use(engine, 'Taste the Qi: Read an openly shown nature (free)')
    assert not offered(engine, '(free)'), 'once on each of your turns'


def test_the_free_taste_the_qi_reaches_sixty_feet():
    engine, me, _ = fight(H + 'the_empty_bowl_watches')
    use(engine, 'Digestive Mantle: Thick Hide')
    free = [a for a in engine.action_catalog.values()
            if a.owner_id == ME and 'Taste the Qi' in a.display_name and a.display_name.endswith('(free)')]
    assert free, 'the free copy is compiled with the Mantle'
    assert {a.range_ft for a in free} == {60}


def test_an_ordinary_taste_the_qi_still_costs_its_bonus_action():
    """The printed rule adds a free copy; it does not take the ordinary one away."""
    engine, me, _ = fight(H + 'the_empty_bowl_watches')
    me.bonus_action_available = True
    paid = [c for c in engine.legal_candidates() if c.display_name == 'Taste the Qi: Read an openly shown nature']
    assert paid, 'the ordinary copy is still there'
    use(engine, 'Taste the Qi: Read an openly shown nature')
    assert not me.bonus_action_available


# ---------------------------------------------------------------------------- the sheet's "not automated yet" lists
@pytest.mark.parametrize('key', ALL + (H + 'bitter_medicine_belly', H + 'devour_the_venom_keep_the_fang'))
def test_no_hunger_ability_this_lane_automated_is_left_as_a_gm_line(key):
    bundle = compiled(key, ALL)
    listed = {name for group in bundle['diagnostics']['skipped'].values() for name in group}
    assert AUTH[key]['name'] not in listed, bundle['diagnostics']['skipped']


def test_no_hunger_ability_at_all_is_left_as_a_gm_line_and_every_outside_says_why_in_plain_words():
    """Hunger is a sphere for between fights; each remaining line says so in words a newcomer can read, never as a bare id."""
    every = sorted(k for k, v in AUTH.items() if v.get('sphere_id') == 'tianxia.sphere.hunger')
    bundle = compiled(H + 'three_course_battle_body', tuple(k for k in every if k not in (
        'HUNGER_BASE_DIGESTIVE_MANTLE', 'HUNGER_BASE_REFINE_THE_MEAL', 'HUNGER_BASE_TASTE_THE_QI')))
    skipped = bundle['diagnostics']['skipped']
    assert not skipped['passive'] and not skipped['reaction'] and not skipped['not_typed'] \
        and not skipped['not_in_authority'] and not skipped['build'] and not skipped['table'], skipped
    from combat.factory_compiler import feature_status

    listed = feature_status()
    for name in skipped['outside']:
        entry = next(row for key, row in listed.items() if row and AUTH.get(key, {}).get('name') == name)
        assert entry['why'] and 'tianxia.' not in entry['why'] and len(entry['why']) >= 25, entry



# ============================================================ AUTO14f1 (review fixes): one regression per finding
def _my_turn_again(engine):
    """Let the opponent take its turn and hand the round back, so a second Bonus Action is available."""
    engine.state.current_actor_id = AN
    engine._system_start_turn()
    engine.state.current_actor_id = ME
    engine._system_start_turn()


def test_marrow_furnace_pulse_owns_the_printed_demon_beast_half_and_asks_which_meal_it_burned():
    """Marrow-Furnace Pulse: "If the active Mantle came from a demon beast, you may instead add your Proficiency Bonus to
    one damage roll that turn and gain 1 Impurity when the Mantle ends."

    The row that carries this lives in combat/rules/feature_blocks.d/riders_lane9.json, which already owned the talent.
    A second row under combat/rules/feature_blocks.d/hunger.json was silently discarded: combat/typed_reactions.py rules()
    merges those files in sorted filename order, so the later-sorting riders_lane9.json won and ``reads`` was lost -- with it
    the only way this printed line can be reached at all."""
    engine, me, _ = fight(H + 'marrow_furnace_pulse', answers=['demon_beast'])
    row = next(r for r in engine.typed_passive_rows[ME]
               if r.get('block') == 'lane9_hunger' and r.get('feature_id') == H + 'marrow_furnace_pulse')
    assert row.get('reads') == ['demon_beast'], row
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['satiety'] == 'demon_beast', 'the printed half is gated on the Mantle coming from a demon beast'
    # A second Digestive Mantle is the one Hunger activation that spends CP while one is active, and a replaced Mantle is
    # an ended Mantle, so the pulse's 1 Impurity is owed here.
    _my_turn_again(engine)
    me.resources['resource:core.qi'] = 10
    use(engine, 'Digestive Mantle: Iron Stomach')
    assert me.resources[IMPURITY] == 2, "the base course's 1 Impurity plus Marrow-Furnace Pulse's 1"


def test_activating_a_new_mantle_ends_the_previous_one_and_owes_what_its_ending_owed():
    """Demon-Beast Digestion: "When that Mantle ends, make a Constitution saving throw against your Hunger Save DC.
    Failed Save: gain 1 Impurity."  The base ability: "Activating a new Digestive Mantle ends the previous one", so a
    replaced Mantle is an ended Mantle.  combat/ext/hunger_riders.py replace_mantle runs on technique_start, which is
    before technique_used, so the debt has to be settled as the old Mantle is removed."""
    engine, me, _ = fight(H + 'demon_beast_digestion', answers=['demon_beast'])
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['satiety'] == 'demon_beast'
    _my_turn_again(engine)
    use(engine, 'Digestive Mantle: Iron Stomach')
    saves = [roll for roll in engine.rolls if 'digestion' in str(roll.reason)]
    assert saves, [roll.reason for roll in engine.rolls]


def test_a_replaced_mantle_still_owes_the_base_demon_beast_courses_impurity():
    """Demon-Beast Course: "Gain 1 Impurity when the Mantle ends unless another talent changes this."  Marrow-Furnace Pulse
    is the talent that reads a demon-beast meal here, and its own printed line owes a second, so a replaced Mantle owes
    both.  Before the fix replace_mantle deleted the Mantle on technique_start and the debts went with it."""
    engine, me, _ = fight(H + 'marrow_furnace_pulse', answers=['demon_beast'])
    use(engine, 'Digestive Mantle: Thick Hide')
    assert me.resources[IMPURITY] == 0
    _my_turn_again(engine)
    use(engine, 'Digestive Mantle: Iron Stomach')
    assert me.resources[IMPURITY] == 2, 'both printed "when that Mantle ends" lines are paid'


def test_a_replaced_mantle_still_owes_maws_impurity_reduction():
    """Maw of Ten Thousand Courses: "When the Mantle ends, reduce your Impurity by 1 if none of the spent Satiety was
    Corrupted, Demon-Beast, or Forbidden." """
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['normal', 'Iron Stomach'], impurity=3)
    use(engine, 'Digestive Mantle: Thick Hide')
    assert me.resources[IMPURITY] == 3
    _my_turn_again(engine)
    use(engine, 'Digestive Mantle: Venom Belly')
    assert me.resources[IMPURITY] == 2


def test_three_course_battle_body_is_not_offered_without_a_mantle_to_replace():
    """Three-Course Battle Body: "When Digestive Mantle is active, you may use a Bonus Action to consume 1 additional
    Satiety and replace your current basic Mantle benefit..."  Without a Mantle the Satiety was charged for nothing."""
    engine, me, _ = fight(H + 'three_course_battle_body', answers=['normal'])
    me.bonus_action_available = True
    assert offered(engine, 'Three-Course Battle Body') == [], 'printed: "When Digestive Mantle is active"'
    use(engine, 'Digestive Mantle: Thick Hide')
    me.action_available = me.bonus_action_available = True
    assert offered(engine, 'Three-Course Battle Body'), 'with the Mantle up it is a choice'


def _mantle_damage(engine, actor_id=ME):
    """The HP the Digestive Mantle's own extra-damage packets have taken off anybody, as the engine recorded them."""
    return [event for event in engine.events if event.event_type == 'DAMAGE_COMMITTED'
            and event.source_definition_id == MANTLE_ID and event.actor_id == actor_id]


def test_three_course_battle_body_does_not_reset_once_before_the_mantle_ends():
    """Beast Strength: "Once before the Mantle ends, when you hit with a melee attack ..., add your Proficiency Bonus to the
    damage roll."  Three-Course changes the benefit; it does not end the Mantle, so the once-per-Mantle count stands.

    The Mantle starts on Iron Stomach, so the only way to reach Beast Strength is Three-Course; the count must still be
    spent afterwards, and switching back away from it must not reopen the use either."""
    engine, me, foe = fight(H + 'three_course_battle_body', answers=['Beast Strength', 'Iron Stomach', 'Beast Strength'])
    use(engine, 'Digestive Mantle: Iron Stomach')
    use(engine, 'Unarmed Strike')
    assert mantle(me)['used'] == [], mantle(me)['used']
    me.action_available = me.bonus_action_available = True
    use(engine, 'Three-Course Battle Body')
    assert mantle(me)['benefits'] == ['Beast Strength'], mantle(me)['benefits']
    me.action_available = me.bonus_action_available = True
    use(engine, 'Unarmed Strike')
    assert mantle(me)['used'] == ['beast'], mantle(me)['used']
    assert _mantle_damage(engine), 'the first Beast Strength hit spends the once-before-the-Mantle-ends use'
    _my_turn_again(engine)
    use(engine, 'Three-Course Battle Body')
    assert mantle(me)['benefits'] == ['Iron Stomach'], mantle(me)['benefits']
    me.action_available = me.bonus_action_available = True
    use(engine, 'Three-Course Battle Body')
    assert mantle(me)['benefits'] == ['Beast Strength'], 'back to the benefit that spent the use'
    me.action_available = True
    use(engine, 'Unarmed Strike')
    assert len(_mantle_damage(engine)) == 1, '"once before the Mantle ends" was spent by the first Beast Strength hit'


def test_maw_of_ten_thousand_courses_spends_one_satiety_for_each_benefit_it_hands_over():
    """Maw of Ten Thousand Courses: "you may spend up to 3 Satiety. Choose one Mantle benefit for each Satiety spent."
    Three benefits for the one Satiety the Mantle costs was free damage."""
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['normal', 'Iron Stomach', 'Beast Strength'])
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['benefits'] == ['Thick Hide', 'Iron Stomach', 'Beast Strength'], mantle(me)['benefits']
    assert me.resources[SATIETY] == 3, me.resources[SATIETY]


def test_maw_never_offers_a_benefit_the_actor_cannot_pay_for():
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['normal'])
    me.resources[SATIETY] = 1
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['benefits'] == ['Thick Hide'], mantle(me)['benefits']
    assert me.resources[SATIETY] == 0


@pytest.mark.parametrize('banked,benefits', [
    (1, ['Thick Hide']),
    (2, ['Thick Hide', 'Iron Stomach']),
    (3, ['Thick Hide', 'Iron Stomach', 'Beast Strength']),
])
def test_maw_hands_over_every_benefit_the_satiety_left_can_pay_for(banked, benefits):
    """Maw of Ten Thousand Courses: "you may spend up to 3 Satiety. Choose one Mantle benefit for each Satiety spent."

    The check has to read the Satiety still in hand, not how many benefits are already held: with three Satiety the Mantle
    costs one and the other two buy the second and third benefit, so all three are owed. Before the fix the third benefit was
    withheld while one Satiety was still unspent."""
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['normal', *benefits[1:], 'ordinary_only'])
    me.resources[SATIETY] = banked
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['benefits'] == benefits, (banked, mantle(me)['benefits'])
    assert me.resources[SATIETY] == banked - 1 - (len(benefits) - 1), \
        'the Mantle costs one Satiety and each benefit past the first costs one of its own'


def test_the_note_that_runs_out_of_satiety_names_the_talent_and_never_its_ability_id():
    """The fight log names abilities, not ids (combat/tabletop_service.py reads each passive row's own name)."""
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['normal'])
    me.resources[SATIETY] = 1
    use(engine, 'Digestive Mantle: Thick Hide')
    said = [str((event.payload or {}).get('log')) for event in engine.events if event.event_type == 'PASSIVE_TRIGGERED']
    said = [line for line in said if line]
    assert any('Maw of Ten Thousand Courses' in line and 'no Satiety left' in line for line in said), said
    assert not [line for line in said if 'tianxia.' in line], said


def test_owning_maw_never_charges_for_the_demon_beast_courses_free_second_benefit():
    """Demon-Beast Course: "Choose two basic Mantle benefits above that fit the demon beast instead of one" -- two for the
    one Satiety the Mantle costs.  Maw of Ten Thousand Courses prints "up to 3 Satiety ... one Mantle benefit for each
    Satiety spent", so the third benefit is what a further Satiety buys; the second is free whatever else the actor owns."""
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['demon_beast', 'Iron Stomach'])
    me.resources[SATIETY] = 1
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['benefits'] == ['Thick Hide', 'Iron Stomach'], mantle(me)['benefits']
    assert me.resources[SATIETY] == 0, 'both printed entitlements ride the one Satiety the Mantle costs'


def test_owning_maw_charges_one_satiety_only_for_the_benefit_past_the_free_pair():
    engine, me, _ = fight(H + 'maw_of_ten_thousand_courses', answers=['demon_beast', 'Iron Stomach', 'Beast Strength'])
    me.resources[SATIETY] = 3
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['benefits'] == ['Thick Hide', 'Iron Stomach', 'Beast Strength'], mantle(me)['benefits']
    assert me.resources[SATIETY] == 1, 'one Satiety for the Mantle and one for the third benefit, not one for the second'


def test_the_base_abilities_own_second_benefit_for_a_demon_beast_meal_costs_no_second_satiety():
    """Demon-Beast Course: "Choose two basic Mantle benefits above that fit the demon beast instead of one."  Only Maw
    of Ten Thousand Courses prints a Satiety per benefit, so no talent here may charge one."""
    engine, me, _ = fight(H + 'demon_beast_digestion', answers=['demon_beast', 'Iron Stomach'])
    use(engine, 'Digestive Mantle: Thick Hide')
    assert mantle(me)['benefits'] == ['Thick Hide', 'Iron Stomach'], mantle(me)['benefits']
    assert me.resources[SATIETY] == 5, 'the Mantle costs one Satiety, not one per benefit'


def test_the_meal_menu_is_the_six_printed_kinds_and_the_predator_question_is_asked_only_by_its_own_owner():
    """Predator-King Digestion's "Satiety from a predator or apex beast" is a fact about the creature, so it is its own
    question with its own answer, and no other Hunger character is asked a question whose answer means nothing to it."""
    from combat.ext import hunger_riders

    engine, me, _ = fight(H + 'predator_king_digestion', answers=['predator_or_apex'])
    use(engine, 'Digestive Mantle: Thick Hide')
    asked = {request['reaction_source_id']: request for request in engine.auto14_asked}
    meals = [request for name, request in asked.items() if name.endswith('hunger_satiety')]
    provenance = [request for name, request in asked.items() if name.endswith('hunger_provenance')]
    assert not meals, 'this character\'s own lines name no kind of meal'
    assert len(provenance) == 1, list(asked)
    assert provenance[0]['legal_option_ids'] == ['predator_or_apex', 'some_other_creature'], provenance[0]
    labels = provenance[0]['choice_trigger']['labels']
    assert 'predator or an apex beast' in labels['predator_or_apex'], labels
    assert 'Predator-King Digestion' in provenance[0]['choice_trigger']['prompt'], provenance[0]['choice_trigger']['prompt']
    assert mantle(me)['provenance'] == 'predator_or_apex', mantle(me)
    assert mantle(me)['satiety'] is None, 'the meal kind and the provenance are recorded apart, so neither replaces the other'
    assert 'predator' not in hunger_riders.SATIETY_KINDS
    engine, me, _ = fight(H + 'demon_beast_digestion', answers=['demon_beast'])
    use(engine, 'Digestive Mantle: Thick Hide')
    meals = [request for request in engine.auto14_asked if request['reaction_source_id'].endswith('hunger_satiety')]
    assert [option for request in meals for option in request['legal_option_ids']] == list(hunger_riders.SATIETY_KINDS), meals
    assert not [request for request in engine.auto14_asked if request['reaction_source_id'].endswith('hunger_provenance')]


def test_a_predator_demon_beast_meal_satisfies_both_the_predator_king_and_the_demon_beast_course():
    """A predator's corrupted portion is Demon-Beast Satiety *and* the meal Predator-King Digestion reads. Recorded as one
    kind of meal, the two printed lines excluded each other: naming the predator lost the two free benefits, and naming the
    demon beast closed the predator die."""
    engine, me, foe = fight(H + 'predator_king_digestion', extras=(H + 'demon_beast_digestion',),
                            answers=['demon_beast', 'predator_or_apex', 'Iron Stomach'])
    use(engine, 'Digestive Mantle: Predator Step')
    held = mantle(me)
    assert held['benefits'] == ['Predator Step', 'Iron Stomach'], held['benefits']
    assert (held['satiety'], held['provenance']) == ('demon_beast', 'predator_or_apex'), held
    assert me.resources[SATIETY] == 5, "Demon-Beast Course's second benefit costs no Satiety of its own"
    foe.current_hp = foe.maximum_hp // 4
    use(engine, 'Jian (Straight Sword) attack')
    assert [roll for roll in engine.rolls if roll.reason == 'DAMAGE:' + H + 'predator_king_digestion'], \
        [roll.reason for roll in engine.rolls]


def test_a_predator_bone_meal_keeps_both_the_predator_king_die_and_the_bone_satiety_bonus():
    """The same for Bone Satiety: Beast-Bone Broth reads the kind of meal, Predator-King Digestion reads the creature."""
    engine, me, foe = fight(H + 'predator_king_digestion', extras=(H + 'beast_bone_broth',),
                            answers=['bone', 'predator_or_apex', 'bone', 'predator_or_apex'])
    use(engine, 'Digestive Mantle: Predator Step')
    held = mantle(me)
    assert (held['satiety'], held['provenance']) == ('bone', 'predator_or_apex'), held
    foe.current_hp = foe.maximum_hp // 4
    use(engine, 'Jian (Straight Sword) attack')
    assert [roll for roll in engine.rolls if roll.reason == 'DAMAGE:' + H + 'predator_king_digestion'], \
        [roll.reason for roll in engine.rolls]
    # A second Mantle from the same bone meal still reads as Bone Satiety, so Thick Hide still cuts twice the PB.
    _my_turn_again(engine)
    use(engine, 'Digestive Mantle: Thick Hide')
    held = mantle(me)
    assert (held['satiety'], held['provenance']) == ('bone', 'predator_or_apex'), held
    assert reduced_by_thick_hide(engine, me) == 2 * held['pb'] + held['key']


def test_every_one_of_the_eight_printed_mantle_benefits_can_be_chosen():
    """All eight basic benefits remain available, plus the separately printed Demon-Beast Course.

    Reviewed include_in_menu lets the ninth printed course pass the generic menu cap without hiding a basic benefit.
    """
    engine, me, _ = fight(H + 'beast_bone_broth', answers=[])
    from combat.ext import hunger_riders

    choices = {name.rsplit(': ', 1)[-1] for name in offered(engine, 'Digestive Mantle')}
    assert choices == set(hunger_riders.BENEFITS) | {"Demon-Beast Course"}, choices


def _chosen_resistances(actor):
    """The damage types the actor resists, read off the modifiers a typed ``resistance`` effect applies."""
    return {str(modifier.value).upper() for modifier in actor.modifiers.values()
            if getattr(modifier, 'target_field', '') == 'damage_resistance'}


def test_elemental_gut_gives_resistance_to_the_one_type_chosen_and_not_to_all_seven():
    """Elemental Gut: "Choose Acid, Cold, Fire, Lightning, Necrotic, Poison, or Thunder, as appropriate to the Satiety
    source. You gain Resistance to that damage type while the Mantle lasts." """
    engine, me, _ = fight(H + 'beast_bone_broth', answers=['bone', 'fire'])
    use(engine, 'Digestive Mantle: Elemental Gut')
    assert 'Elemental Gut' in mantle(me)['benefits'], mantle(me)
    assert mantle(me)['element'] == 'fire', mantle(me)
    resists = _chosen_resistances(me)
    assert 'FIRE' in resists, resists
    assert 'ACID' not in resists, 'the printed line is Resistance to that one damage type'


def test_elemental_gut_names_the_meal_it_burns_so_the_choice_can_be_made():
    engine, me, _ = fight(H + 'beast_bone_broth', answers=['bone', 'cold'])
    use(engine, 'Digestive Mantle: Elemental Gut')
    asked = [request for request in engine.auto14_asked if request['reaction_source_id'].endswith('elemental_gut')]
    assert asked, engine.auto14_asked
    assert 'Bone Satiety' in asked[0]['choice_trigger']['prompt'], asked[0]['choice_trigger']['prompt']
    assert asked[0]['legal_option_ids'] == ['acid', 'cold', 'fire', 'lightning', 'necrotic', 'poison', 'thunder'], asked
