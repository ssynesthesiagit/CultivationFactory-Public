"""Compiler rider policy: supported semantics, conservative bounds and isolation."""
from copy import deepcopy
from fractions import Fraction
from itertools import product

import pytest

from combat.rider_value import (MAX_EFFECT_DEPTH, MAX_EFFECT_ROWS, MAX_MOVEMENT_OUTCOMES,
                                    MAX_RIDER_UTILITY, estimate_rider_utility)


FOE = "HOSTILE_ENTITY"
NUMBERS = {"pb": 4, "key_mod": 3, "cl": 2}


def value(*effects, target_kind=FOE, economy="action", numbers=None, **typed):
    return estimate_rider_utility({"effects": list(effects), "numbers": NUMBERS if numbers is None else numbers, **typed},
                                  target_kind=target_kind, economy=economy)


@pytest.mark.parametrize("effect,target,expected", [
    ({"type": "condition", "condition": "incapacitated"}, FOE, 8),
    ({"type": "condition", "condition": "grappled"}, FOE, 4),
    ({"type": "condition", "condition": "prone"}, FOE, 3),
    ({"type": "condition", "condition": "reaction_denied"}, FOE, 3),
    ({"type": "condition", "condition": "invisible", "applies_to": "self"}, "SELF", 3),
    ({"type": "condition", "condition": "incapacitated", "applies_to": "self"}, FOE, 0),
    ({"type": "condition", "condition": "incapacitated", "applies_to": "ally"}, FOE, 0),
    ({"type": "condition", "condition": "invisible", "applies_to": "target"}, FOE, 0),
    ({"type": "condition", "condition": "invisible", "applies_to": "ally"}, FOE, 0),
    ({"type": "condition", "condition": "invisible", "applies_to": "ally"}, "ALLY_OR_SELF", 3),
    ({"type": "condition", "condition": "invisible", "applies_to": "target"}, "SELF", 0),
    ({"type": "condition", "condition": "petrified", "applies_to": "self"}, "SELF", 0),
    ({"type": "condition", "condition": "battered"}, FOE, 0),
    ({"type": "condition", "condition": "not_a_supported_condition"}, FOE, 0),
    ({"type": "condition", "condition": "active_ability", "evidence": "You have a powerful advantage"}, "SELF", 0),
    ({"type": "condition", "condition": "incapacitated", "applies_to": "creatures_in_area"}, FOE, 0),
    ({"type": "condition", "condition": "incapacitated"}, "ANY_ENTITY", 0),
])
def test_conditions_follow_executable_rules_and_recipient_polarity(effect, target, expected):
    assert value(effect, target_kind=target) == expected


def test_condition_data_override_is_respected_without_mutation():
    effect = {"type": "condition", "condition": "incapacitated",
              "condition_data": {"rule": {"no_actions": False, "no_reactions": False}}}
    before = deepcopy(effect)
    assert value(effect) == 0
    assert effect == before
    assert value({"type": "condition", "condition": "incapacitated", "condition_data": {"suppressed": True}}) == 0


@pytest.mark.parametrize("rule,expected", [
    ({"save_mode": {"UNEXECUTED": "DISADVANTAGE"}}, 0),
    ({"save_mode": {"STR": "AUTO_FAIL"}}, 3),
    ({"check_mode": {"UNEXECUTED": "DISADVANTAGE"}}, 0),
    ({"check_mode": {"STR": "AUTO_FAIL"}}, 0),
    ({"check_mode": {"Athletics": "DISADVANTAGE"}}, 1),
    ({"attacks_others_have": "DISADVANTAGE"}, 0),
    ({"no_cp_reactions": True}, 0),
])
def test_custom_condition_rules_only_score_actually_read_scopes(rule, expected):
    assert value({"type": "condition", "condition": "active_ability", "condition_data": {"rule": rule}}) == expected


@pytest.mark.parametrize("effect,target,expected", [
    ({"type": "advantage", "on": "your next attack roll", "applies_to": "self"}, FOE, 2),
    ({"type": "disadvantage", "on": "its next attack roll", "applies_to": "target"}, FOE, 2),
    ({"type": "advantage", "on": "attack rolls against it", "applies_to": "target"}, FOE, 2),
    ({"type": "disadvantage", "on": "attack rolls against you", "applies_to": "self"}, "SELF", 2),
    ({"type": "advantage", "on": "its next attack roll", "applies_to": "target"}, FOE, 0),
    ({"type": "disadvantage", "on": "attack rolls against it", "applies_to": "target"}, FOE, 0),
    ({"type": "disadvantage", "on": "its next attack roll", "applies_to": "ally"}, "ALLY_OR_SELF", 0),
    ({"type": "advantage", "on": "the next Dexterity saving throw", "applies_to": "self"}, "SELF", 2),
    ({"type": "advantage", "on": "saving throws", "applies_to": "self"}, "SELF", 0),
    ({"type": "disadvantage", "on": "Concentration saving throws", "applies_to": "target"}, FOE, 2),
    ({"type": "advantage", "on": "Strength checks", "applies_to": "self"}, "SELF", 1),
    ({"type": "advantage", "on": "winning the fight", "applies_to": "self"}, "SELF", 0),
])
def test_roll_modes_use_existing_typed_on_semantics(effect, target, expected):
    assert value(effect, target_kind=target) == expected


def test_opposing_modes_for_same_recipient_and_roll_cancel():
    advantage = {"type": "advantage", "on": "your next attack roll", "applies_to": "self"}
    disadvantage = {"type": "disadvantage", "on": "attack rolls", "applies_to": "self"}
    assert value(advantage, disadvantage) == value(disadvantage, advantage) == 0
    assert value(advantage, {**disadvantage, "deferred": True}) == 2
    assert value(advantage, {**disadvantage, "applies_to": "target"}) == 2


@pytest.mark.parametrize("effect,expected", [
    ({"type": "expose", "bonus": 2, "applies_to": "target"}, 2),
    ({"type": "expose", "bonus": "pb", "applies_to": "target"}, 3),
    ({"type": "next_damage_taken_bonus", "formula": "pb", "applies_to": "target"}, 2),
    ({"type": "next_damage_taken_bonus", "amount": 1, "formula": "key_ability_modifier", "applies_to": "target"}, 2),
    ({"type": "save_bonus", "flat": 2, "abilities": ["DEX"], "applies_to": "self"}, 2),
    ({"type": "save_bonus", "amount": 1, "against": ["frightened"], "applies_to": "self"}, 1),
    ({"type": "save_bonus", "formula": "pb", "applies_to": "self"}, 0),
    ({"type": "save_bonus", "flat": 2, "applies_to": "target"}, 0),
    ({"type": "attack_modifier", "flat": 100, "applies_to": "self"}, 0),
    ({"type": "next_hit", "flat": 100, "applies_to": "self"}, 0),
])
def test_supported_future_bonuses_do_not_invent_generic_bonus_handlers(effect, expected):
    assert value(effect) == expected


@pytest.mark.parametrize("effect,expected", [
    ({"type": "forced_movement", "distance_ft": 10}, 2),
    ({"type": "forced_movement", "distance_ft": 10000}, 4),
    ({"type": "forced_movement", "distance_ft": 10, "applies_to": "self"}, 0),
    ({"type": "movement", "distance_ft": 20, "applies_to": "self"}, 2),
    ({"type": "movement", "distance_ft": "half_speed", "applies_to": "self"}, 1),
    ({"type": "movement", "distance_ft": 0, "no_opportunity_attacks": True}, 1),
    ({"type": "movement", "distance_ft": 0}, 0),
    ({"type": "movement", "distance_ft": -5}, 0),
    ({"type": "speed", "flat": -10, "applies_to": "target"}, 2),
    ({"type": "speed", "flat": 10, "applies_to": "self"}, 2),
    ({"type": "speed", "flat": -10, "applies_to": "self"}, 0),
    ({"type": "speed", "flat": 10, "applies_to": "target"}, 0),
    ({"type": "speed", "halved": True, "applies_to": "target"}, 4),
    ({"type": "speed", "becomes": 0, "applies_to": "target"}, 4),
    ({"type": "speed", "becomes": 10, "applies_to": "target"}, 0),
    ({"type": "teleport", "distance_ft": 60, "applies_to": "self"}, 0),
    ({"type": "movement", "mode": "teleport", "distance_ft": 60}, 0),
])
def test_movement_is_a_bounded_opportunity_without_assuming_a_tactical_destination(effect, expected):
    assert value(effect) == expected


@pytest.mark.parametrize("amount", [
    {"flat": 1}, {"flat": 10000}, {"flat": -2},
    {"formula": "pb"}, {"formula": "half_pb"},
    {"formula": "key_ability_modifier"}, {"formula": "cl"},
    {"formula": "half_trigger_damage"}, {"formula": "text:some undefined amount"},
    {"dice": {"count": 1, "sides": 4}},
    {"dice": {"count_formula": "pb", "sides": 4}},
    {"dice_by_cl": [[1, 4, 1, 4], [5, 10, 2, 4]]},
])
def test_resource_recovery_earns_nothing_because_capacity_is_not_projected(amount):
    """Refilling a pool that is already full recovers nothing. This hint is compiled
    without the caster's remaining supply, and the controller adds it unchecked, so a
    published refill would outrank a useful alternative while wasting its action. The
    family returns with the state-aware projection in the next lock round."""
    gain = {"type": "gain_resource", "resource_id": "resource:core.qi", "applies_to": "self", **amount}
    assert value(gain) == 0
    assert value({"type": "save", "ability": "CON", "on_fail": [gain]}) == 0
    assert value({"type": "attack", "on_hit": [gain]}) == 0
    assert value(gain, {"type": "condition", "condition": "incapacitated", "applies_to": "target"}) == 8


def test_a_refill_alone_never_makes_an_activation_look_useful():
    """A printed "regain Martial Focus" bonus action, its real published shape."""
    focus = {"type": "gain_resource", "resource_id": "resource:core.martial_focus", "flat": 1, "applies_to": "self"}
    assert value(focus, economy="bonus_action") == 0
    assert value(focus, {"type": "spend_resource", "resource_id": "resource:core.martial_focus", "flat": 1}) == 0


def test_resource_gain_needs_a_resolved_resource_and_friendly_recipient():
    assert value({"type": "gain_resource", "flat": 9, "evidence": "regain Qi"}) == 0
    assert value({"type": "gain_resource", "resource_id": "unknown", "flat": 9}) == 0
    assert value({"type": "gain_resource", "resource_id": "resource:core.qi", "flat": 9, "applies_to": "target"}) == 0


def test_attack_ability_formula_uses_delivered_weapon_not_key_ability():
    bonus = {"type": "next_damage_taken_bonus", "amount": 1, "formula": "attack_ability_modifier",
             "applies_to": "target"}
    assert value(bonus, weapon={"ability_modifier": -1}) == 0
    assert value(bonus, weapon={"ability_modifier": 1}) == 1
    assert value(bonus, weapon={"ability_modifier": "invalid"}) == 0
    assert value(bonus) == 2  # the executor's documented key-ability fallback, halved


def test_reaction_setup_discount_is_only_option_value():
    effect = {"type": "ready_counterstrike", "applies_to": "self"}
    assert value(effect, economy="action") == 1
    assert value(effect, economy="bonus_action") == 2
    assert value(effect, {"type": "attack", "deferred": True,
                          "on_hit": [{"type": "damage", "dice": {"count": 100, "sides": 100}}]}, economy="action") == 1
    assert value({"type": "reaction_setup", "effects": [{"type": "condition", "condition": "incapacitated"}]}) == 0


def test_exclusive_save_branches_are_averaged_not_added():
    condition = {"type": "condition", "condition": "incapacitated"}
    push = {"type": "forced_movement", "distance_ft": 10, "applies_to": "target"}
    assert value({"type": "save", "ability": "CON", "on_fail": [condition]}) == 4
    assert value({"type": "save", "ability": "CON", "on_fail": [condition], "on_success": [condition]}) == 8
    assert value({"type": "save", "ability": "CON", "on_fail": [condition], "on_success": [push]}) == 5


def test_nested_attack_save_admission_and_parent_recipient_are_preserved():
    condition = {"type": "condition", "condition": "incapacitated"}
    save = {"type": "save", "ability": "CON", "on_fail": [condition]}
    assert value({"type": "attack", "on_hit": [save]}) == 2
    assert value({**save, "ability": "STR_OR_DEX"}) == 4
    assert value({**save, "applies_to": "self"}) == 0
    assert value({"type": "if_marked", "mark": "arbitrary typed mark", "effects": [condition]}) == 4
    assert value({"type": "if_marked", "mark": "arbitrary typed mark", "applies_to": "self", "effects": [condition]}) == 0
    assert value({"type": "if_marked", "effects": [condition]}) == 0


def test_known_empty_enemy_scopes_do_not_create_future_opportunities():
    condition = {"type": "condition", "condition": "incapacitated", "applies_to": "enemies_in_area"}
    assert value(condition, target_kind="ALLY_OR_SELF") == 0
    assert value(condition, target_kind="SELF") == 0
    assert value(condition, target_kind="SELF", area={"size_ft": 10, "shape": "sphere"}) == 8
    mark = {"type": "expose", "bonus": 2, "applies_to": "target"}
    assert value({"type": "attack", "on_hit": [mark]}, target_kind="SELF") == 0
    assert value({"type": "save", "ability": "CON", "on_fail": [mark]}, target_kind="SELF") == 0
    assert value({"type": "save", "ability": "CON", "applies_to": "self", "on_fail": [mark]}, target_kind="SELF") == 0
    # An explicitly self-targeted save is admitted, and its supported benefit is worth
    # 2 points of opportunity value, halved again by the branch it sits in.
    bonus = {"type": "save_bonus", "flat": 2, "applies_to": "self"}
    assert value({"type": "save", "ability": "CON", "applies_to": "self", "on_fail": [bonus]},
                 target_kind="SELF") == 1
    assert value({"type": "save", "ability": "CON", "on_fail": [bonus]}, target_kind="SELF") == 0


def test_same_activation_removals_and_mobility_overlap_do_not_manufacture_value():
    condition = {"type": "condition", "condition": "incapacitated", "applies_to": "target"}
    remove = {"type": "remove_condition", "condition": "condition:typed.incapacitated", "applies_to": "target"}
    assert value(condition, remove) == 0
    grapple = {"type": "condition", "condition": "grappled", "applies_to": "target"}
    speed = {"type": "speed", "becomes": 0, "applies_to": "target"}
    assert value(grapple, speed) == value(grapple) == 4
    # Prose under a manual wrapper cannot invalidate a real consequence.
    push = {"type": "forced_movement", "distance_ft": 10, "applies_to": "target"}
    assert value(push, {"type": "rider", "effects": [remove]}) == 2
    assert value({"type": "save_bonus", "flat": 2, "applies_to": "self"},
                 {"type": "rider", "effects": [remove]}) == 2


def test_a_nested_gate_keeps_the_surrounding_outcomes_removal_in_either_row_order():
    """Review finding 1: the deduplication scope is the complete outcome, not one gate.

    The target is Grappled outright, and a later gate may also take that same target's
    Speed away. Nothing inside a gate can free a creature that is already grappled, so
    the activation is worth the grapple alone. The two rows may be written in either
    order, because the removal is resolved once over the whole activation, and a gate
    that only one of two exclusive outcomes takes still counts on its own."""
    grapple = {"type": "condition", "condition": "grappled", "applies_to": "target"}
    shove = {"type": "forced_movement", "distance_ft": 20, "applies_to": "target"}
    step = {"type": "movement", "distance_ft": 20, "applies_to": "self"}

    def gate(inner):
        if inner["type"] == "forced_movement":
            return {"type": "if_marked", "mark": "Grave Mark", "effects": [inner]}
        return {"type": "save", "ability": "CON", "applies_to": "target", "on_fail": [inner]}

    for inner in (shove,
                  {"type": "speed", "becomes": 0, "applies_to": "target"},
                  {"type": "condition", "condition": "grappled", "applies_to": "target"}):
        assert value(grapple, gate(inner)) == value(gate(inner), grapple) == value(grapple) == 4
    # Another creature's movement inside the same gate is untouched by the foe's removal.
    assert value({"type": "save", "ability": "CON", "applies_to": "target",
                  "on_fail": [grapple, step]}) == 3


def test_exclusive_outcomes_credit_each_recipients_own_movement():
    """Review finding 1: the movement family is read per complete outcome, then averaged.

    A save that shoves the target on failure and steps the caster on success has two
    exclusive outcomes, each worth its own 2 movement points. Averaging each
    recipient's credit first and then taking the strongest would report 1, which is a
    half-credit for a consequence no single outcome produces. The same holds with the
    branches the other way round, and for an attack's hit and miss."""
    shove = {"type": "forced_movement", "distance_ft": 10, "applies_to": "target"}
    step = {"type": "movement", "distance_ft": 20, "applies_to": "self"}
    assert value({"type": "save", "ability": "CON", "applies_to": "target",
                  "on_fail": [shove], "on_success": [step]}) == 2
    assert value({"type": "save", "ability": "CON", "applies_to": "target",
                  "on_fail": [step], "on_success": [shove]}) == 2
    assert value({"type": "attack", "on_hit": [shove], "on_miss": [step]}) == 2
    assert value({"type": "attack", "on_hit": [step], "on_miss": [shove]}) == 2
    # Two gates in a row are two chances, so each consequence lands in a quarter of
    # the activation: shove only, shove and step, and step only each give 2 movement
    # points and the fourth gives none -- 6 over four outcomes, which the final int()
    # reports as 1. Each recipient still keeps its own full credit inside its outcome.
    assert value({"type": "if_marked", "mark": "Grave Mark", "effects": [shove]},
                 {"type": "attack", "on_miss": [step]}) == 1
    # Two creatures moved in the same outcome still keep only the strongest of the
    # two: the family is a maximum, never a sum.
    assert value({"type": "save", "ability": "CON", "on_fail": [shove, step]}) == 1
    assert value({"type": "save", "ability": "CON", "on_fail": [step],
                  "on_success": [{"type": "forced_movement", "distance_ft": 40,
                                  "applies_to": "target"}]}) == 3


# Eight gates whose movement is distinguishable, so every one of them either lands
# or does not and the activation describes more complete outcomes than the retained
# bound keeps. Each is a save on the target that fails into the next row, so one, two
# or three nested saves admit its leaf half, a quarter or an eighth of the time. The
# points are what the estimator awards: one per 5 ft of forced movement, one per 10 ft
# of the caster's own movement.
OVERFLOW_GATES = [
    ({"type": "forced_movement", "distance_ft": 5, "applies_to": "target"}, 3, "foe", 1),
    ({"type": "forced_movement", "distance_ft": 10, "applies_to": "target"}, 1, "foe", 2),
    ({"type": "forced_movement", "distance_ft": 15, "applies_to": "target"}, 2, "foe", 3),
    ({"type": "forced_movement", "distance_ft": 20, "applies_to": "target"}, 2, "foe", 4),
    ({"type": "movement", "distance_ft": 10, "applies_to": "self"}, 2, "friend", 1),
    ({"type": "movement", "distance_ft": 20, "applies_to": "self"}, 1, "friend", 2),
    ({"type": "movement", "distance_ft": 30, "applies_to": "self"}, 2, "friend", 3),
    ({"type": "movement", "distance_ft": 40, "applies_to": "self"}, 2, "friend", 4),
]


def nested_gate(leaf, saves):
    """`saves` saves on the target, each failing into the next one, the leaf innermost."""
    rows = [leaf]
    for _ in range(saves):
        rows = [{"type": "save", "ability": "CON", "applies_to": "target",
                 "on_fail": rows, "on_success": []}]
    return rows[0]


def exact_outcomes(gates):
    """Every complete outcome of `gates` and its exact chance, read without the bound.

    Each gate is a list of (movement it lands, the chance of landing it) alternatives
    and lands exactly one of them, listed chances included. Read from the gates
    themselves rather than from the estimator's bookkeeping: the movement family is a
    maximum per creature inside one outcome, and an outcome is worth its strongest
    creature."""
    outcomes = {}
    for landed_alternatives in product(*gates):
        held, chance = {}, Fraction(1)
        for landed, admitted in landed_alternatives:
            chance *= admitted
            for who, points in landed.items():
                held[who] = max(held.get(who, 0), points)
        key = tuple(sorted(held.items()))
        outcomes[key] = outcomes.get(key, Fraction()) + chance
    return outcomes


def exact_movement(gates):
    """What these gates are worth with no bound on the outcomes kept."""
    return sum((chance * max((points for _, points in held), default=Fraction())
                for held, chance in exact_outcomes(gates).items()), Fraction())


def overflow_model(gates):
    """`gates` as exact_outcomes() alternatives: `saves` nested saves admit the leaf."""
    return [[({who: points}, Fraction(1, 2 ** saves)),
             ({}, 1 - Fraction(1, 2 ** saves))]
            for _, saves, who, points in gates]


def test_overflow_publishes_never_more_than_the_exact_expectation():
    """Review finding 1: dropping outcomes must not raise the average kept.

    These eight gates land four different distances on the target and four on the
    caster, so they describe 25 complete outcomes -- more than the retained bound
    allows. Read outcome by outcome they are worth 97979/32768 = 2.99008 policy points,
    which the final int() publishes as 2. Keeping only the most likely outcomes and
    dividing their weights so they add back up to one discards the low-value
    remainder, raises the average of what is left and published 3: more than these
    outcomes are worth together, and enough to outrank a real alternative in the
    controller's ordering. (Individual outcomes here are worth up to 4, so this is a
    claim about the expected movement, not about every single outcome.)"""
    assert exact_movement(overflow_model(OVERFLOW_GATES)) == Fraction(97979, 32768)
    assert int(exact_movement(overflow_model(OVERFLOW_GATES))) == 2
    # This is the overflow payload: the activation really does describe more complete
    # outcomes than the bound retains, so the bound's path is the one under test here.
    # What this case cannot show is the retained LIST SIZE: keeping all 25 outcomes also
    # publishes 2, because the discarded mass is worth 0.181 of a point and int() drops
    # it either way. Enforcement of the bound is covered separately in
    # test_the_retained_outcome_bound_changes_what_a_wide_activation_publishes.
    assert len(exact_outcomes(overflow_model(OVERFLOW_GATES))) > MAX_MOVEMENT_OUTCOMES == 16
    gates = [nested_gate(leaf, saves) for leaf, saves, _, _ in OVERFLOW_GATES]
    assert value(*gates) == 2
    assert value(*gates) <= int(exact_movement(overflow_model(OVERFLOW_GATES)))


def test_the_retained_outcome_bound_changes_what_a_wide_activation_publishes(monkeypatch):
    """Separate coverage: the bound is ENFORCED, not merely reached.

    The test above cannot show that, because keeping all of its 25 outcomes publishes
    the same 2 -- the retained list size is invisible there. This activation is wider:
    three creatures, five distances each behind two saves, so many more than 16
    complete outcomes carry movement credit.

    Both numbers come from the shipped estimator on the same activation, once as
    published and once with the bound lifted, so the comparison needs no second
    implementation of the per-outcome reading. They differ, which means the bound is
    what held the figure down. It only ever lowers it, which is the one direction a
    hint that must never invent value is allowed to move.
    """
    from combat import rider_value

    def forced(distance_ft, applies_to):
        return {"type": "forced_movement", "distance_ft": distance_ft, "applies_to": applies_to}

    def own(distance_ft):
        return {"type": "movement", "distance_ft": distance_ft, "applies_to": "self"}

    wide = []
    for points in range(1, 6):  # shoving a creature 5 ft, or walking 10 ft, is one movement point
        wide += [nested_gate(forced(5 * points, "target"), 2),
                 nested_gate(forced(5 * points, "ally"), 2),
                 nested_gate(own(10 * points), 2)]
    assert len(wide) == 15 > 8

    bounded = value(*wide)
    assert bounded == 2
    monkeypatch.setattr(rider_value, "MAX_MOVEMENT_OUTCOMES", 10 ** 9)
    unbounded = value(*wide)
    monkeypatch.undo()
    assert unbounded == 3
    assert bounded < unbounded


def test_overflow_stays_conservative_under_row_order_wrappers_and_stops():
    """The bound drops probability mass, so later reading can only lower the figure.

    Row order decides which outcomes the bound sees first, and a wrapper's rows happen
    in the same outcome as their neighbours', so neither may report more than the
    unbounded figure."""
    exact = int(exact_movement(overflow_model(OVERFLOW_GATES)))
    gates = [nested_gate(leaf, saves) for leaf, saves, _, _ in OVERFLOW_GATES]
    for rows in (gates, list(reversed(gates)), gates[3:] + gates[:3]):
        assert 0 <= value(*rows) <= exact
    assert value({"type": "weapon_method", "effects": gates}) <= exact
    # A grapple that every outcome takes cancels the target's movement everywhere, so
    # only the caster's own four gates are left whatever order the stop is written in:
    # 281/128 = 2.1953 of movement on its own, plus the grapple's own 4 condition
    # points, which no movement bound touches.
    grapple = {"type": "condition", "condition": "grappled", "applies_to": "target"}
    assert exact_movement(overflow_model(OVERFLOW_GATES[4:])) == Fraction(281, 128)
    assert value(grapple, *gates) == value(*gates, grapple)
    assert 4 <= value(grapple, *gates) <= 4 + int(exact_movement(overflow_model(OVERFLOW_GATES[4:])))


def test_many_nested_gates_stay_inside_the_retained_outcome_bound():
    """The per-outcome bookkeeping is bounded: a wide activation cannot grow the hint.

    Copies of one gate describe the same three outcomes, so this activation never
    reaches the bound and its value is readable exactly: every copy pushes the target
    4 or steps the caster 2, the family is a maximum, and the figure approaches 4 from
    below without reaching it, so the final int() reports 3 however many copies there
    are. The depth limit still abstains rather than spending time on a deeply nested
    activation."""
    gate = {"type": "save", "ability": "CON", "applies_to": "target",
            "on_fail": [{"type": "forced_movement", "distance_ft": 20, "applies_to": "target"}],
            "on_success": [{"type": "movement", "distance_ft": 20, "applies_to": "self"}]}
    # One gate pushes the target 4 half the time and steps the caster 2 the other half.
    copies = [[({"foe": 4}, Fraction(1, 2)), ({"friend": 2}, Fraction(1, 2))]]
    for count in (1, 2, 3):
        exact = exact_movement(copies * count)
        assert exact < 4 and int(exact) == 3
        assert value(*[gate] * count) == 3
    assert len(exact_outcomes(copies * 3)) == 3 <= MAX_MOVEMENT_OUTCOMES
    wide = [dict(gate, source_modifier=f"row{index}") for index in range(4 * MAX_MOVEMENT_OUTCOMES)]
    assert value(*wide) == value(gate) == 3
    nested = gate
    for _ in range(MAX_EFFECT_DEPTH):
        nested = {"type": "weapon_method", "effects": [nested]}
    assert value(nested) == 0


def test_mobility_is_deduplicated_only_within_one_outcome_and_recipient():
    """Review finding 2: the two consequences are unrelated, so both are worth credit.

    A save that Grapples on failure and shoves 20 feet on success are exclusive outcomes:
    the creature that is grappled is the one that is not shoved. Each keeps its own
    weighted value, 2 condition points plus 2 movement points."""
    grapple = {"type": "condition", "condition": "grappled", "applies_to": "target"}
    shove = {"type": "forced_movement", "distance_ft": 20, "applies_to": "target"}
    assert value({"type": "save", "ability": "CON", "on_fail": [grapple], "on_success": [shove]}) == 4
    assert value({"type": "attack", "on_hit": [grapple], "on_miss": [shove]}) == 4
    # Two separate gates, read as the complete outcome they can happen in: when the
    # Mark is up *and* the attack hits, the target is already Grappled, so the shove
    # that Mark brings cannot also be credited as movement in that outcome. Only the
    # Mark-and-miss outcome, a quarter of the whole, carries the 4 movement points.
    assert value({"type": "if_marked", "mark": "Grave Mark", "effects": [shove]},
                 {"type": "attack", "on_hit": [grapple]}) == 3
    # Same creature, same outcome: the Speed the condition removed earns nothing extra.
    assert value({"type": "save", "ability": "CON", "on_fail": [grapple, shove]}) == 2
    # Same outcome, different creature: grappling a foe leaves your own movement alone.
    step = {"type": "movement", "distance_ft": 20, "applies_to": "self"}
    assert value(grapple, step) == 6
    assert value(grapple, step, {"type": "speed", "becomes": 0, "applies_to": "self"}) == 6
    # A wrapper's rows happen in the same outcome as its neighbours.
    assert value({"type": "weapon_method", "effects": [grapple, shove]}) == 4
    # Recipient scope is the executor's own polarity: the target, or the caster/their ally.
    assert value(grapple, shove, target_kind="HOSTILE_ENTITY") == 4


def test_known_level_limits_and_unresolved_menu_alternatives_do_not_leak():
    condition = {"type": "condition", "condition": "incapacitated"}
    assert value({**condition, "min_cl": 3}) == 0
    assert value({**condition, "max_cl": 1}) == 0
    assert value({**condition, "min_cl": 2, "max_cl": 2}) == 8
    push = {"type": "forced_movement", "distance_ft": 20, "applies_to": "target"}
    assert value({"type": "menu", "id": "choices", "count": 1, "options": ["A", "B"]},
                 {**condition, "menu": "choices", "option": "A"},
                 {**push, "menu": "choices", "option": "B"}) == 0


def test_repeat_counts_durations_and_duplicate_effects_never_multiply_value():
    condition = {"type": "condition", "condition": "incapacitated"}
    assert value(condition) == value(condition, deepcopy(condition), {**condition, "source_modifier": "different", "evidence": "different"}) == 8
    one = {"type": "attack", "count": 1, "on_hit": [condition]}
    many = {**one, "count": 10000, "count_by_cl": [[1, 20, 10000]]}
    assert value(one) == value(many) == 4
    assert value({**condition, "duration": "until_start_of_next_turn"}) == value({**condition, "duration": "permanent", "rounds": 10000})


@pytest.mark.parametrize("effect", [
    None, "condition", 5, [], {"type": []}, {"type": "condition", "condition": []},
    {"type": "condition", "condition": "incapacitated", "condition_data": []},
    {"type": "condition", "condition": "incapacitated", "condition_data": {"rule": []}},
    {"type": "gain_resource", "resource_id": "resource:core.qi", "flat": True},
    {"type": "gain_resource", "resource_id": "resource:core.qi", "dice_by_cl": [[1]]},
    {"type": "expose", "bonus": []}, {"type": "save_bonus", "flat": "a lot"},
    {"type": "save_bonus", "flat": 1, "abilities": ["invalid"]},
    {"type": "save_bonus", "flat": 1, "abilities": [None]},
    {"type": "save_bonus", "flat": 1, "against": "frightened"},
    {"type": "advantage", "on": {"attack": True}},
    {"type": "forced_movement", "distance_ft": "lots"},
    {"type": "speed", "becomes": False},
    {"type": "attack", "count": -1, "on_hit": [{"type": "condition", "condition": "incapacitated"}]},
    {"type": "attack", "count_by_cl": "ten", "on_hit": [{"type": "condition", "condition": "incapacitated"}]},
    {"type": "save", "ability": [], "on_fail": [{"type": "condition", "condition": "incapacitated"}]},
])
def test_malformed_rows_abstain(effect):
    assert value(effect) == 0


def test_outer_malformed_data_and_disabled_rows_abstain():
    for typed in (None, [], "manual", {"effects": "incapacitated"}, {"effects": {"type": "condition", "condition": "incapacitated"}}):
        assert estimate_rider_utility(typed, target_kind=FOE) == 0
    condition = {"type": "condition", "condition": "incapacitated"}
    for flag in ("inert", "gm_only", "manual", "setting_only", "player_only"):
        assert value(condition, **{flag: True}) == 0
        assert value({**condition, flag: True}) == 0
    assert estimate_rider_utility({"effects": [condition]}, target_kind=FOE, setting_only=True) == 0
    assert value(condition, numbers={"pb": True}) == 0


def test_unknown_manual_and_deferred_containers_do_not_leak_child_value():
    condition = {"type": "condition", "condition": "incapacitated"}
    for kind in ("unknown", "rider", "on_success", "zone", "attack_modifier_setting"):
        assert value({"type": kind, "effects": [condition], "on_hit": [condition], "on_fail": [condition]}) == 0
    assert value({"type": "save", "deferred": True, "on_fail": [condition]}) == 0
    assert value({"type": "gain_resource", "resource_id": "resource:core.qi", "flat": 99, "deferred": True}) == 0


def test_immediate_support_and_deferred_extra_damage_are_not_rider_credit():
    for kind in ("damage", "extra_damage", "destructive_blast_damage", "healing", "temp_hp"):
        for deferred in (True, False):
            assert value({"type": kind, "deferred": deferred, "flat": 100,
                          "formula": "pb", "dice": {"count": 50, "sides": 100},
                          "evidence": "Add this bonus when you hit with an attack"}) == 0


def test_total_cap_and_traversal_limits_are_effective():
    effects = [{"type": "condition", "condition": "incapacitated", "applies_to": "target"},
               {"type": "forced_movement", "distance_ft": 10000},
               {"type": "save_bonus", "flat": 100, "applies_to": "self"},
               {"type": "ready_counterstrike", "applies_to": "self"}]
    assert value(*effects) == MAX_RIDER_UTILITY
    assert type(value(*effects)) is int
    deep = effects[0]
    for _ in range(MAX_EFFECT_DEPTH + 1):
        deep = {"type": "weapon_method", "effects": [deep]}
    assert value(deep) == 0
    assert value(*([None] * MAX_EFFECT_ROWS), effects[0]) == 0
    assert value(effects[0], *([None] * MAX_EFFECT_ROWS)) == 0
    cyclic = {"type": "weapon_method"}
    cyclic["effects"] = [cyclic]
    assert value(cyclic) == 0


def test_names_prose_and_order_do_not_change_estimate_or_damage_fields():
    effects = [{"type": "condition", "condition": "incapacitated", "evidence": "old words"},
               {"type": "forced_movement", "distance_ft": 5}]
    typed = {"effects": effects, "numbers": NUMBERS.copy(), "source": "old id", "name": "old title",
             "riders": ["huge damage and bonus"], "expected_damage": 0, "expected_healing": 0}
    before = deepcopy(typed)
    estimate = estimate_rider_utility(typed, target_kind=FOE)
    assert estimate > 0 and typed == before
    renamed = deepcopy(typed)
    renamed.update(source="new id", name="new title", riders=["no benefit"])
    renamed["effects"][0]["evidence"] = "unrelated text"
    renamed["effects"].reverse()
    assert estimate_rider_utility(renamed, target_kind=FOE) == estimate
    assert typed["expected_damage"] == renamed["expected_damage"] == 0
    assert typed["expected_healing"] == renamed["expected_healing"] == 0
