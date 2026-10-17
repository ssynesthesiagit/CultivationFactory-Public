"""Replacement must preserve riders triggered while the old Mantle is active, and everything the Mantle's own condition
carries must survive a table commit and a reload (AUTO14f1, AUTO14r1f1)."""
from tests.hunt31_support import FOE, OWNER, act, fixture, finish_choices, pick, prepare, reload, send, owner_turn

MANTLE = 'HUNGER_BASE_DIGESTIVE_MANTLE'
MARROW = 'tianxia.talent.hunger.marrow_furnace_pulse'
MAW = 'tianxia.talent.hunger.maw_of_ten_thousand_courses'
THREE_COURSE = 'tianxia.talent.hunger.three_course_battle_body'
CONDITION = 'condition:typed.digestive_mantle'
NINE_BEAST = 'tianxia.talent.hunger.nine_beast_sovereign_course'
KING = 'tianxia.talent.hunger.predator_king_digestion'


def _mantle(combat, table, mid, text, option=None):
    """Play a Mantle option and answer every choice the table asks, the printed meal question included."""
    candidate = pick(table, mid, text)
    result = send(combat, table, mid, candidate, False)
    return finish_choices(lambda answers: send(combat, table, mid, candidate, False, answers), result, option=option)


def _ordered_mantle(combat, table, mid, text, order):
    """Play a Mantle option and answer each choice it asks with the next of ``order`` the table offers, so a Mantle whose
    later questions follow the meal question (Elemental Gut's damage type, Maw's paid benefits) can be answered in turn."""
    candidate = pick(table, mid, text)
    result = send(combat, table, mid, candidate, False)
    answers = []
    for _ in range(20):
        if result['status'] != 'REACTION_REQUIRED':
            return result
        prompt = result['reaction']
        offered = [option['id'] for option in prompt['choice']['options']]
        chosen = next((option for option in order[len(answers):] if option in offered), offered[0])
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': [chosen]})
        result = send(combat, table, mid, candidate, False, answers)
    raise AssertionError('too many choices')


def _mantle_data(engine):
    actor = engine.state.actors[OWNER]
    held = next(row for row in actor.conditions.values() if row.condition_id == CONDITION)
    return held.data


def test_replacement_keeps_marrow_spend_trigger(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [MANTLE, MARROW], resources={'resource:named.satiety': 6})
    assert _mantle(combat, table, mid, 'Digestive Mantle: Predator Step')['status'] == 'COMMITTED'
    owner_turn(table, mid, next_turn=True)
    assert _mantle(combat, table, mid, 'Digestive Mantle: Thick Hide')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == MARROW]
    assert len(grants) == 1
    assert engine._effective_speed(engine.state.actors[OWNER]) == 30


def test_the_meal_the_mantle_burned_survives_a_commit_and_a_reload(monkeypatch, tmp_path):
    """The kind of Satiety is stored on the Mantle's own condition (a string), and every later Hunger line reads it."""
    combat, table, mid = fixture(monkeypatch, tmp_path, [MANTLE, MARROW], resources={'resource:named.satiety': 6})
    assert _mantle(combat, table, mid, 'Digestive Mantle: Predator Step', option='demon_beast')['status'] == 'COMMITTED'
    assert _mantle_data(reload(combat, mid))['satiety'] == 'demon_beast'


def test_the_chosen_benefits_survive_a_commit_and_a_reload(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [MANTLE, MARROW], resources={'resource:named.satiety': 6})
    assert _mantle(combat, table, mid, 'Digestive Mantle: Predator Step')['status'] == 'COMMITTED'
    fresh = reload(combat, mid)
    data = _mantle_data(fresh)
    assert data['benefits'] == ['Predator Step'], data
    assert data['used'] == [] and data['pb'] and isinstance(data['pb'], int) and isinstance(data['key'], int)


def test_winged_hungers_fly_speed_survives_a_commit_and_a_reload(monkeypatch, tmp_path):
    """Nine-Beast Sovereign Course's Winged Hunger keeps its Fly Speed on the Mantle's own condition (an integer)."""
    combat, table, mid = fixture(monkeypatch, tmp_path, [MANTLE, NINE_BEAST], resources={'resource:named.satiety': 6})
    assert _mantle(combat, table, mid, 'Digestive Mantle: Thick Hide + Nine-Beast Sovereign Course: Winged Hunger')['status'] == 'COMMITTED'
    fresh = reload(combat, mid)
    assert _mantle_data(fresh)['fly_speed_ft'] == fresh.state.actors[OWNER].speed_ft
    assert fresh._effective_speed(fresh.state.actors[OWNER]) > 0


def _resists(actor):
    """The damage types the actor resists, read off the modifiers a typed ``resistance`` effect applies."""
    return {str(modifier.value).upper() for modifier in actor.modifiers.values()
            if getattr(modifier, 'target_field', '') == 'damage_resistance'}


def test_elemental_guts_chosen_resistance_survives_a_commit_and_a_reload(monkeypatch, tmp_path):
    """Elemental Gut: "Choose Acid, Cold, Fire, ... You gain Resistance to that damage type while the Mantle lasts."  The
    chosen type is a string on the Mantle's own condition and the Resistance it applies is its own retained modifier, so
    both have to come back from disk, not only the ones a re-compile can rebuild."""
    combat, table, mid = fixture(monkeypatch, tmp_path, [MANTLE, MARROW], resources={'resource:named.satiety': 6})
    assert _ordered_mantle(combat, table, mid, 'Digestive Mantle: Elemental Gut', ['normal', 'fire'])['status'] == 'COMMITTED'
    fresh = reload(combat, mid)
    assert _mantle_data(fresh)['element'] == 'fire', _mantle_data(fresh)
    resists = _resists(fresh.state.actors[OWNER])
    assert 'FIRE' in resists, resists
    assert 'ACID' not in resists, 'the printed line is Resistance to that one damage type'


def test_the_paid_multi_benefit_mantle_survives_a_commit_and_a_reload(monkeypatch, tmp_path):
    """Maw of Ten Thousand Courses: "you may spend up to 3 Satiety. Choose one Mantle benefit for each Satiety spent."  The
    three chosen benefits and the two Satiety the second and third cost are both state the next table has to see: the list
    decides what every triggered Hunger line does, the balance decides what may still be handed over."""
    combat, table, mid = fixture(monkeypatch, tmp_path, [MANTLE, MAW], resources={'resource:named.satiety': 6})
    assert _ordered_mantle(combat, table, mid, 'Digestive Mantle: Thick Hide',
                           ['normal', 'Iron Stomach', 'Beast Strength'])['status'] == 'COMMITTED'
    fresh = reload(combat, mid)
    data = _mantle_data(fresh)
    assert data['benefits'] == ['Thick Hide', 'Iron Stomach', 'Beast Strength'], data
    assert fresh.state.actors[OWNER].resources['resource:named.satiety'] == 3, \
        'the Mantle costs one Satiety and each of the two paid benefits costs one of its own'


def test_a_benefit_replaced_a_later_round_survives_a_commit_and_a_reload(monkeypatch, tmp_path):
    """Three-Course Battle Body spends a Bonus Action on a later round to replace the Mantle's benefit, so this change is a
    transaction of its own: the reloaded table has to read the replaced benefit, not the one the Mantle was cast with."""
    combat, table, mid = fixture(monkeypatch, tmp_path, [MANTLE, MAW, THREE_COURSE], resources={'resource:named.satiety': 6})
    assert _ordered_mantle(combat, table, mid, 'Digestive Mantle: Thick Hide',
                           ['normal', 'Iron Stomach', 'Beast Strength'])['status'] == 'COMMITTED'
    assert _mantle_data(reload(combat, mid))['benefits'] == ['Thick Hide', 'Iron Stomach', 'Beast Strength']
    owner_turn(table, mid, next_turn=True)
    assert _ordered_mantle(combat, table, mid, 'Three-Course Battle Body', ['Predator Step'])['status'] == 'COMMITTED'
    fresh = reload(combat, mid)
    assert _mantle_data(fresh)['benefits'] == ['Predator Step'], _mantle_data(fresh)
    assert fresh.state.actors[OWNER].resources['resource:named.satiety'] == 2, \
        'the Mantle, the two paid benefits and the Three-Course Satiety'


# ------------------------------------------------------------------------------------- a table sealed against the older Predator-King row
# The Predator-King die rides a hit on a Bloodied creature, so the opponent has to reach Bloodied through a real table
# commit rather than by the test writing hit points into the state.
INJURY = {'type': 'damage', 'applies_to': 'self', 'damage_types': ['FORCE'], 'flat': 40}


def _king_damage(engine):
    """The damage Predator-King Digestion's printed die has added, read off the fight's own recorded events."""
    return [event for event in engine.events
            if event.event_type == 'DAMAGE_COMMITTED' and event.source_definition_id == KING]


def _turn_to(table, mid, actor_id):
    """End turns the way a table with one manual character in it waits for the others."""
    for _ in range(10):
        if table.state(mid)['menu']['actor_id'] == actor_id:
            return
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    raise AssertionError('turn not reached')


def _bloodied_foe(combat, table, mid):
    """Walk the table round until the opponent has hurt itself down to half its hit points, so the hit that follows lands
    on a creature the fight itself made Bloodied."""
    _turn_to(table, mid, FOE)
    prepare(table, mid, FOE)
    foe = reload(combat, mid).state.actors[FOE]
    assert foe.current_hp * 2 <= foe.maximum_hp, (foe.current_hp, foe.maximum_hp)
    _turn_to(table, mid, OWNER)


def test_a_predator_meal_sealed_before_the_provenance_question_keeps_its_die_across_a_reload(monkeypatch, tmp_path):
    """Predator-King Digestion reads "Satiety from a predator or apex beast".  A table that was playing while that line was
    recorded as a *kind of meal* sealed a row declaring ``reads: ["predator"]`` and an active Mantle recording
    ``satiety: "predator"``, and a resumed match loads that sealed bundle unchanged -- no rules edit can reach it.  The die
    that row was compiled to grant therefore has to stay available there."""
    combat, table, mid = fixture(monkeypatch, tmp_path, [MANTLE, KING], setup=[INJURY],
                                 resources={'resource:named.satiety': 6}, armed=True, legacy_predator=True)
    # The meal question still offers the kind this sealed row reads, so this activation records a predator meal.
    assert _mantle(combat, table, mid, 'Digestive Mantle: Predator Step', option='predator')['status'] == 'COMMITTED'
    fresh = reload(combat, mid)
    assert _mantle_data(fresh)['satiety'] == 'predator', 'the meal this sealed row reads survives the reload'
    assert not _mantle_data(fresh).get('provenance'), 'a row sealed against the older data asks nothing about the creature'
    row = next(entry for entry in fresh.typed_passive_rows[OWNER] if entry.get('kind') == 'predator_king')
    assert row['reads'] == ['predator'] and 'reads_provenance' not in row, row
    _bloodied_foe(combat, table, mid)
    assert _king_damage(reload(combat, mid)) == [], 'the die rides the hit, not the Mantle going on'
    # A Bloodied hit after that reload still adds one roll of the printed die.
    assert send(combat, table, mid, pick(table, mid, 'attack', FOE), False)['status'] == 'COMMITTED'
    assert _king_damage(reload(combat, mid)), 'a table sealed against the older row lost the die its row grants'


def test_a_later_activation_in_that_saved_fight_records_the_predator_meal_again(monkeypatch, tmp_path):
    """The compatibility path has to reach past the Mantle that was already active: the next activation in a saved fight is
    answered by the same sealed row, so it must offer the same meal kind and open the same printed die."""
    combat, table, mid = fixture(monkeypatch, tmp_path, [MANTLE, KING], setup=[INJURY],
                                 resources={'resource:named.satiety': 6}, armed=True, legacy_predator=True)
    assert _mantle(combat, table, mid, 'Digestive Mantle: Predator Step', option='predator')['status'] == 'COMMITTED'
    owner_turn(table, mid, next_turn=True)
    assert _mantle(combat, table, mid, 'Digestive Mantle: Predator Step', option='predator')['status'] == 'COMMITTED'
    assert _mantle_data(reload(combat, mid))['satiety'] == 'predator'
    _bloodied_foe(combat, table, mid)
    assert send(combat, table, mid, pick(table, mid, 'attack', FOE), False)['status'] == 'COMMITTED'
    assert _king_damage(reload(combat, mid)), 'the later Mantle opened the same printed die'