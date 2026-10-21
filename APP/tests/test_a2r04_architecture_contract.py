"""Keep the F5 inherited documentation repairs in the discoverable contract."""
import ast
from pathlib import Path
import re

import pytest


EXT = Path(__file__).resolve().parents[1] / 'combat' / 'ext'


@pytest.mark.parametrize('module,consumer,helper', [
    ('fate_riders', 'fate_insights', 'fate_die'),
    ('water_map', 'water_return', 'extinguish'),
    ('prior_event_resources', 'foundations3', 'prior_generated_units'),
    ('athletics_grip_lungs', 'athletics', 'owns'),
    ('iron_oath_generation', 'foundation_combat', 'conscious_for_guarding_iron'),
])
def test_shared_contract_names_the_consumer_and_public_helper(module, consumer, helper):
    doc = ast.get_docstring(ast.parse((EXT / f'{module}.py').read_text())) or ''
    assert 'shared' in doc.lower()
    assert consumer in doc
    assert helper in doc


def test_interception_contract_is_in_the_discoverable_hook_documentation():
    doc = ast.get_docstring(ast.parse((EXT / '__init__.py').read_text())) or ''
    contract = doc.split('  attack_target_interception(', 1)[1].split('  stealth_search_mode(', 1)[0]
    for term in ('engine, attacker, target, source_id, intent, index', 'dict | None',
                 'source_id', 'recipient_object_id', 'condition_instance_id',
                 'default-inert', 'leaves the original attack intact', 'perception'):
        assert term in contract


@pytest.mark.parametrize('hook', ['shared_space', 'pass_through_stop', 'cover_miss_recipient'])
def test_athletics_hooks_document_their_default_inert_contract(hook):
    doc = ast.get_docstring(ast.parse((EXT / '__init__.py').read_text())) or ''
    entry = re.search(rf'(?ms)^  {hook}\(.*?(?=^  [a-z][a-z0-9_]*\(|\Z)', doc)
    assert entry is not None
    assert 'None' in entry.group()
    assert 'default-inert' in entry.group()
