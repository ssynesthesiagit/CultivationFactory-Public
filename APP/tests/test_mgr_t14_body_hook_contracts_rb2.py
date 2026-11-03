"""Regression (RB2): the Body-mode hooks registered in combat/ext/body_modes_scene_resources.py and
combat/ext/mgr_reserve_tribulation_vessel_gather_calamity.py must have a contract line in the
combat/ext/__init__.py module docstring. Without it the architecture guard
(tests/test_architecture_guards.py::test_hook_documentation_and_unique_effects) fails on head.
Synthetic: reads only repository source text."""
import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
HOOKS = {
    "body_mode_profiles": "combat/ext/mgr_reserve_tribulation_vessel_gather_calamity.py",
    # The retired branch-only mode/choice owner has no consumers. Main's
    # source owner has one admission/transfer/settlement/snapshot/timing path.
    "fact_admission_schema": "combat/ext/body_modes_scene_resources.py",
    "journey_combat_bundle": "combat/ext/body_modes_scene_resources.py",
    "journey_encounter_settled": "combat/ext/body_modes_scene_resources.py",
    "journey_snapshot_actor": "combat/ext/body_modes_scene_resources.py",
    "journey_time_boundaries": "combat/ext/body_modes_scene_resources.py",
}


def _doc():
    return ast.get_docstring(ast.parse((APP / "combat/ext/__init__.py").read_text(encoding="utf-8"))) or ""


def test_body_mode_hooks_have_documented_contracts():
    doc = _doc()
    for name, module in HOOKS.items():
        src = (APP / module).read_text(encoding="utf-8")
        assert f"@hook('{name}'" in src, f"{name} is no longer registered in {module}"
        assert re.search(r"\b" + name + r"\([^\n)]*\) -> ", doc), f"document {name}(args) -> return in ext/__init__.py"


def test_body_mode_hook_contracts_state_default_inert_behaviour():
    doc = _doc()
    for name in HOOKS:
        line = next(l for l in doc.splitlines() if l.lstrip().startswith(name + "("))
        assert "None" in line, f"{name} must name its None (default-inert) return"
