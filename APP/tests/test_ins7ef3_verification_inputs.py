"""Focused verification must not acquire unrelated private-fixture dependencies."""
import ast
from pathlib import Path

import pytest


TESTS = Path(__file__).resolve().parent


@pytest.mark.parametrize('filename', ['test_a2_ins7d_batch6.py', 'test_a2_qi_tempered.py'])
def test_choice_captures_do_not_request_unrelated_validator_fixture(filename):
    # The public dependency scanner conservatively treats helper arguments as
    # fixture requests too. "options" belongs to a nested validator conftest,
    # not these service tests; it drags in a withheld registry when aliased.
    tree = ast.parse((TESTS / filename).read_text())
    captures = [node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == 'capture']
    assert captures
    assert all('options' not in {arg.arg for arg in node.args.args} for node in captures)


@pytest.mark.parametrize('filename', [
    'test_mgr_t16_athletics_1_close.py', 'test_mgr_t16_athletics_1_review_fixes.py',
])
def test_cover_checks_use_independent_action_helper(filename):
    # Importing a whole unrelated test module for one builder also imports its
    # legacy-character scenario closure in public qualification.
    tree = ast.parse((TESTS / filename).read_text())
    providers = [node.module for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom)
                 and any(alias.name == 'add_action' for alias in node.names)]
    assert providers == ['tests.athletics_action_support']


@pytest.mark.parametrize('label,target,distance', [
    ('Climb check', 'HOSTILE_ENTITY', 5), ('Outside attack', 'SELF', None),
])
def test_independent_action_helper_preserves_native_descriptor(label, target, distance):
    from tests.athletics_action_support import add_action

    effect_rows = [{'type': 'damage', 'flat': 3, 'damage_types': ['bludgeoning']}]
    bundle = {'actor_id': 'actor:test.verification', 'action_catalog': [],
              'actor_template': {'action_ids': []}}
    add_action(bundle, label, effect_rows)
    assert len(bundle['action_catalog']) == 1
    row = bundle['action_catalog'][0]
    source = 'action:test.ath2.' + label.replace(' ', '_')
    assert bundle['actor_template']['action_ids'] == [source]
    assert row['source_definition_id'] == source
    assert row['display_name'] == label and row['owner_id'] == bundle['actor_id']
    assert row['economy'] == 'NONE' and row['resolution_kind'] == 'TYPED'
    assert row['target_kind'] == target and row['range_ft'] == distance
    assert row['parameters'] == {'free_primary': True, 'typed': {
        'effects': effect_rows, 'numbers': {'save_dc': 12}, 'riders': [],
        'duration': {'kind': 'instant'}}}
