"""Regression receipts for the Sol seam review (RB3) on Iron Oath consumers.

Each test fails on the tree before its fix:
- F1: Stand-Fast Witness roll spend was rider text, not a typed effect.
- F3: typed_executor imported nullcontext inside functions.
- F4: api.py had a missing blank line before the learning-preview route.
"""
import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json'
STAND_FAST = 'foundation.iron_oath_skin_v0_2B.stand_fast_witness'


def test_stand_fast_spend_is_typed_not_rider():
    mech = json.loads(AUTHORITY.read_text(encoding='utf-8'))['mechanics'][STAND_FAST]
    types = [e.get('type') for e in mech['effects']]
    assert types == ['foundation_roll_spend']
    spend = mech['effects'][0]
    assert spend['cost'] == {'resource': 'guarding_iron', 'amount': 1}
    assert spend['bonus'] == 'proficiency_bonus'
    assert all('Guarding Iron' not in r for r in mech['riders'])
    assert mech['riders'] == [
        'Oath purpose and project limitations require a sourced scene declaration.']


def test_roll_spend_effect_is_registered_for_dispatch():
    from combat.ext import foundation_combat  # noqa: F401  (registers effects)
    from combat.ext import _EFFECTS
    assert 'foundation_roll_spend' in _EFFECTS


def test_typed_executor_imports_nullcontext_once_at_module_level():
    tree = ast.parse((ROOT / 'combat' / 'typed_executor.py').read_text(encoding='utf-8'))
    top = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
           and node.module == 'contextlib' for alias in node.names}
    assert 'nullcontext' in top
    local = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
             and node.module == 'contextlib' and node.lineno > 1
             and any(a.name == 'nullcontext' for a in node.names)
             and node not in tree.body]
    assert local == []


def test_api_learning_preview_route_has_blank_line_before_it():
    lines = (ROOT / 'app' / 'api.py').read_text(encoding='utf-8').splitlines()
    idx = next(i for i, line in enumerate(lines)
               if '/api/tabletop/characters/{project_id}/learning-preview' in line)
    assert lines[idx - 1].strip() == ''


