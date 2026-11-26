"""One plug-in owns each typed effect name (round 12 merge, 2026-09-29).

combat/ext/__init__.py imports every module in name order and ``effect(name)`` simply overwrites, so two plug-ins that register the
same effect name do not fail: the module that sorts last silently wins.  sw-blacksmith's combat/ext/blood_bloodied.py and
sw-lightning's combat/ext/bloodied_effects.py both registered ``if_bloodied``; ``bloodied_effects`` sorts after ``blood_bloodied``
("_" < "i"), so Blood Thread's ``before_damage`` test was dropped and a hit that took the foe from 251 to below half of 500 HP
earned the Proficiency Bonus the printed words ("If the target is Bloodied, add your Proficiency Bonus to one damage roll") give
only to a target that already was Bloodied.  The gate now lives in blood_bloodied.py alone.

The one-owner-per-effect-name scan that guards against the next collision is
tests/test_architecture_guards.py::test_hook_documentation_and_unique_effects, which parses combat/ext once per session.
"""


def test_the_bloodied_gate_is_the_one_that_tests_hp_before_the_hit():
    from combat.ext import effects

    assert effects()["if_bloodied"].__module__ == "combat.ext.blood_bloodied"
