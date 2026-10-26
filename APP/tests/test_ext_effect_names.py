"""One plug-in owns each typed effect name (round 12 merge, 2026-09-29).

combat/ext/__init__.py imports every module in name order and ``effect(name)`` simply overwrites, so two plug-ins that register the
same effect name do not fail: the module that sorts last silently wins.  sw-blacksmith's combat/ext/blood_bloodied.py and
sw-lightning's combat/ext/bloodied_effects.py both registered ``if_bloodied``; ``bloodied_effects`` sorts after ``blood_bloodied``
("_" < "i"), so Blood Thread's ``before_damage`` test was dropped and a hit that took the foe from 251 to below half of 500 HP
earned the Proficiency Bonus the printed words ("If the target is Bloodied, add your Proficiency Bonus to one damage roll") give
only to a target that already was Bloodied.  The gate now lives in blood_bloodied.py alone; this guards against the next collision."""

import ast
from collections import defaultdict
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "combat" / "ext"


def _registered_effect_names():
    owners = defaultdict(list)
    for path in sorted(EXT.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and getattr(decorator.func, "id", getattr(decorator.func, "attr", "")) == "effect" \
                        and decorator.args and isinstance(decorator.args[0], ast.Constant):
                    owners[decorator.args[0].value].append(path.name)
    return owners


def test_no_effect_name_is_registered_by_two_plugins():
    clashes = {name: files for name, files in _registered_effect_names().items() if len(files) > 1}
    assert not clashes, f"the last module in name order silently wins these effect names: {clashes}"


def test_the_bloodied_gate_is_the_one_that_tests_hp_before_the_hit():
    from combat.ext import effects

    assert effects()["if_bloodied"].__module__ == "combat.ext.blood_bloodied"
