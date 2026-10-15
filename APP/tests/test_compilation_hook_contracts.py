"""Keep public compilation hook contracts discoverable after registry merges."""
import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize('hook, required', [
    ('compile_maximum_hp', (
        'owned_ids', 'context', 'owner_sheet', 'mods', 'pb', 'ownership',
        'summed', 'None adds nothing', 'booleans', 'ValueError', 'default-inert',
    )),
    ('compile_block', (
        'numbers', 'con_mod', "fighter's raw Constitution modifier", 'defaults to 0',
        'record', 'typed_authority', 'Default-inert',
    )),
])
def test_compilation_hook_contract_is_in_public_registry(hook, required):
    registry = Path(__file__).resolve().parents[1] / 'combat' / 'ext' / '__init__.py'
    documentation = ast.get_docstring(ast.parse(registry.read_text()))
    # Match the contract itself, not passing mentions in ability-specific notes.
    marker = f'  {hook}('
    assert marker in documentation, f'{hook} public contract is missing'
    # Continuation lines are indented beyond the two-space registry entry prefix.
    lines = documentation.split(marker, 1)[1].splitlines()
    contract_lines = [lines[0]]
    for line in lines[1:]:
        if line.startswith('  ') and not line.startswith('    '):
            break
        contract_lines.append(line)
    contract = ' '.join(' '.join(contract_lines).split())
    for phrase in required:
        assert phrase in contract, f'{hook} contract omits {phrase!r}'
