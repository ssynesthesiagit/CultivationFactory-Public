"""One numeric contract for execution, generic reactions and pre-roll estimates.

The regressions protect values a second reader previously replaced with zero,
and reject non-integer Python operations that could not be justified by the
existing query grammar. No live model, owner save or generated data is needed.
"""
from copy import deepcopy
import sys

import pytest

from combat import typed_amounts


@pytest.mark.parametrize("formula,expected", [
    ("double_pb", 6), ("triple_pb", 9), ("cl_x5", 40),
    ("key_ability_modifier", -2), ("key_mod", -2), ("con_mod", 4),
])
def test_named_amounts_agree_across_execution_reactions_and_bounds(formula, expected):
    numbers = {"pb": 3, "cl": 8, "key_mod": -2, "con_mod": 4}
    assert typed_amounts.formula_value(formula, numbers, unknown=None) == (expected, None)
    assert typed_amounts.static_bonus({"formula": formula, "flat": 1}, numbers) == expected + 1
    assert typed_amounts.amount_bounds({"formula": formula, "flat": 1}, numbers) == (expected + 1, expected + 1)


@pytest.mark.parametrize("formula", ["2**3", "2**-1", "1e3", "pb / 2"])
def test_execution_cannot_evaluate_an_operation_the_typed_grammar_rejects(formula):
    assert typed_amounts.formula_value(formula, {"pb": 4}, unknown=None)[0] is None
    assert typed_amounts.static_bonus({"formula": formula, "flat": 7}, {"pb": 4}) == 7
    assert typed_amounts.formula_bounds(formula, {"pb": 4}) == (None, None)


def test_expression_reuse_keeps_each_rows_inputs_and_ability_overrides():
    formula = "2 * pb + con - key_mod"
    numbers = {"pb": 3, "key_mod": -2, "con_mod": 1}
    before = deepcopy(numbers)
    for pb, con, expected in ((3, 4, 12), (5, -2, 10), (3, 4, 12)):
        values = {**numbers, "pb": pb}
        abilities = {"CON": con}
        assert typed_amounts.formula_value(formula, {**values, "con_mod": con})[0] == expected
        assert typed_amounts.static_bonus({"formula": formula}, values, ability_mods=abilities) == expected
        assert typed_amounts.formula_bounds(formula, values, ability_mods=abilities) == (expected, expected)
    assert numbers == before


def test_queries_keep_missing_inputs_unknown_and_generic_text_stays_unresolved():
    assert typed_amounts.formula_value("mod:STR", {"key_mod": -2}, unknown=17) == (17, "Formula not typed: mod:STR")
    assert typed_amounts.formula_bounds("mod:STR", {"key_mod": -2}) == (None, None)
    assert typed_amounts.formula_bounds("pb") == (0, None)
    assert typed_amounts.formula_bounds("key_mod") == (None, None)
    assert typed_amounts.formula_bounds("con") == (None, None)
    assert typed_amounts.static_bonus({"formula": "unrecognized", "flat": 3}) == 3
    assert typed_amounts.static_bonus({"formula": "text:twice your proficiency bonus", "flat": 3}, {"pb": 4}) == 3


def test_weapon_modifier_and_ordinary_formulas_retain_their_values():
    numbers = {"pb": 3, "cl": 8, "key_mod": 2}
    for formula, expected in (("none", 0), ("pb", 3), ("cl", 8),
                              ("half_pb", 1), ("key_ability_modifier", 2), ("pb+key", 5)):
        assert typed_amounts.static_bonus({"formula": formula}, numbers) == expected
    assert typed_amounts.static_bonus({"formula": "attack_ability_modifier"}, numbers,
                                     weapon={"ability_modifier": 0}) == 0


def test_invalid_execution_inputs_do_not_become_silent_zero_amounts():
    for invalid, error in ((None, TypeError), ("not-a-number", ValueError)):
        with pytest.raises(error):
            typed_amounts.formula_value("pb+key", {"pb": invalid})
        with pytest.raises(error):
            typed_amounts.static_bonus({"formula": "pb+key"}, {"pb": invalid})


def test_deep_arithmetic_remains_unresolved_without_crashing_readers():
    formula = "+".join(["pb"] * (sys.getrecursionlimit() + 50))
    assert typed_amounts.formula_bounds(formula, {"pb": 1}) == (None, None)
    assert typed_amounts.formula_value(formula, {"pb": 1}, unknown=None)[0] is None
    assert typed_amounts.static_bonus({"formula": formula, "flat": 7}, {"pb": 1}) == 7


def test_native_hit_reaction_uses_the_same_named_amount_as_its_menu_estimate():
    from combat import typed_reactions
    from tests.test_generic_reactions import _engine, REACTOR, AN

    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    effect = {"type": "ac_bonus", "formula": "double_pb"}
    row = {"feature_id": "amount_contract_guard", "block": "generic", "name": "Amount guard",
           "kind": "hit", "costs": [], "effects": [effect], "numbers": {"pb": 3}}
    engine.typed_reaction_rows[REACTOR] = [row]
    reactor.reaction_available = True

    assert typed_amounts.amount_bounds(effect, row["numbers"]) == (6, 6)
    new_ac, hit = typed_reactions.on_attack_hit(
        engine, attacker, reactor, {"range_ft": None}, total=17, natural=17, effective_ac=13,
    )
    assert (new_ac, hit) == (19, False)
    assert not reactor.reaction_available
    receipt = next(event for event in engine.events if event.event_type == "REACTION_RESOLVED"
                   and event.source_definition_id == "amount_contract_guard")
    assert receipt.payload["hit_after_recheck"] is False
