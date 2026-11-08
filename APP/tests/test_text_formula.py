"""Printed amounts kept as text by the typing ("twice your proficiency bonus") are computed (owner 2026-09-29 playtest:
Mei Jiang's fights posted "Formula not typed" 25 times)."""

from combat.typed_amounts import text_formula

N = {"pb": 4, "cl": 10, "key_mod": 3}


def test_sums_of_pb_cl_and_key_modifier():
    assert text_formula("twice your proficiency bonus", N) == (8, "")
    assert text_formula("your proficiency bonus + your path key ability modifier", N) == (7, "")
    assert text_formula("`5 × your proficiency bonus`", N) == (20, "")
    assert text_formula("your cultivation level + your path key ability modifier", N) == (13, "")
    assert text_formula("2×pb + your path key ability modifier", N) == (11, "")


def test_extra_clauses_are_returned_and_non_sums_refused():
    assert text_formula("twice proficiency bonus and +1 ac until the start of your next turn", N) == (8, "and +1 ac until the start of your next turn")
    assert text_formula("the same roll", N) == (None, "the same roll")
