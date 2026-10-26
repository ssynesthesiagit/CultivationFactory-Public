"""Boundary and contract regressions for AIWALK1 walking forecasts (review findings 2, 4, 5).

Each test fails on the pre-fix branch: the reverse core->plug-in import, the plug-in
private import of gate4_controller, the unnamed default-on walk order and the
two-source attack damage.
"""
import ast
import inspect
from pathlib import Path

from combat import ground_decision

COMBAT = Path(__file__).resolve().parents[1] / 'combat'


def _imports(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = '.' * node.level + (node.module or '')
            yield module, [alias.name for alias in node.names], node.lineno


def test_core_walk_decision_does_not_import_plugins():
    """Finding 2: combat/ground_decision.py must not depend on combat/ext/ (a reverse dependency)."""
    offenders = [(mod, line) for mod, _, line in _imports(COMBAT / 'ground_decision.py')
                 if mod.lstrip('.').startswith('ext') or '.ext.' in mod or mod == '.ext']
    # Also the lazy imports inside functions: scan the whole module text.
    text = (COMBAT / 'ground_decision.py').read_text()
    assert 'from .ext' not in text and 'import ext' not in text, offenders


def test_core_walk_decision_uses_no_private_flight_helpers():
    """AIWALK1F3 checklist 5: core walk code must not import underscore helpers of flight_decision."""
    text = (COMBAT / 'ground_decision.py').read_text()
    private = [line.strip() for line in text.splitlines() if 'flight_decision._' in line]
    assert not private, private


def test_plugins_do_not_import_private_controller_helpers():
    """Finding 2: no combat/ext module may import an underscore name from gate4_controller."""
    offenders = []
    for path in sorted((COMBAT / 'ext').glob('*.py')):
        for mod, names, line in _imports(path):
            if mod.lstrip('.') == 'gate4_controller' or mod.endswith('.gate4_controller'):
                offenders += [(path.name, line, name) for name in names if name.startswith('_')]
    assert not offenders, offenders


def test_stress_weight_selection_is_public_and_shared():
    """Finding 2: the stress-weight choice has one public owner in the controller."""
    from combat import gate4_controller
    assert callable(gate4_controller.posture_weights)
    assert callable(gate4_controller.stress_reason)
    assert not hasattr(gate4_controller, '_stress_reason')


def test_movement_features_live_in_core_module():
    """Finding 2: the feature definitions are in a core module both sides can import."""
    from combat import walk_features
    assert callable(walk_features.movement_features) and callable(walk_features.occupied_harm)


def test_walk_attack_order_is_named_and_documented_default_on():
    """Finding 4: the walk branch is its own function whose docstring states it is not slice-gated."""
    from combat.ext import ai_movement
    doc = ai_movement.walk_attack_order.__doc__ or ''
    assert 'NOT gated by CF_COMBAT_AI_SLICES_1_2' in doc
    assert ai_movement.movement_order.__name__ == 'movement_order'


def test_attack_value_has_one_damage_source():
    """Finding 5: attack_value takes only the action, so 'here' and 'best' use the same source."""
    params = list(inspect.signature(ground_decision.attack_value).parameters)
    assert params == ['action'], params
    assert 'metadata' not in inspect.getsource(ground_decision.attack_value)


def test_attack_value_ignores_candidate_metadata_drift():
    """Finding 5: an action's own expected_damage is the only value, whatever a candidate says."""
    from types import SimpleNamespace
    action = SimpleNamespace(damage=None, parameters={'expected_damage': 7})
    assert ground_decision.attack_value(action) == 7


def test_walk_attack_order_is_default_on_and_documented_cost_cap():
    """Finding 1: the walk hook is default-on, unflagged, and its cost cap is stated in code."""
    from combat.ext import ai_movement
    doc = ai_movement.walk_attack_order.__doc__ or ''
    assert 'NOT gated by CF_COMBAT_AI_SLICES_1_2' in doc
    walk_doc = ai_movement.walking_attacks.__doc__ or ''
    assert 'POSITION_LIMIT' in walk_doc and '8' in walk_doc
    source = open(ai_movement.__file__, encoding='utf-8').read()
    assert 'def walk_attack_order' in source
    body = source[source.index('def movement_order'):]
    assert body.index('walk = walk_attack_order(context, rows)') < body.index('if not enabled()')
