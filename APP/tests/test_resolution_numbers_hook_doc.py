"""Hook-contract regression: resolution_numbers is documented in combat/ext/__init__.py.

Public source-only check (no fixtures, no saved fights). It fails if the typed
executor consumes the hook while the ext docstring omits its name, arguments,
return rule or default-inert behaviour.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _docstring(relative: str) -> str:
    return ast.get_docstring(ast.parse((ROOT / relative).read_text(encoding='utf-8'))) or ''


def test_resolution_numbers_hook_is_consumed_and_documented():
    executor = (ROOT / 'combat/typed_executor.py').read_text(encoding='utf-8')
    assert "run_strict('resolution_numbers', self, numbers)" in executor
    doc = _docstring('combat/ext/__init__.py')
    assert 'resolution_numbers(ctx, numbers) -> dict | None' in doc
    assert 'strict pure query' in doc
    assert 'None is the default' in doc
    assert 'ValueError' in doc
    assert 'last non-None replacement' in doc
    assert 'body_modes_scene_resources' in doc


def test_resolution_numbers_hook_provider_is_documented_inside_the_catalogue_not_only_in_code():
    provider = (ROOT / 'combat/ext/body_modes_scene_resources.py').read_text(encoding='utf-8')
    assert "@hook('resolution_numbers')" in provider
    doc = _docstring('combat/ext/__init__.py')
    # The catalogue entry must come before the next hook entry, so the contract is not orphaned.
    start = doc.index('resolution_numbers(ctx, numbers)')
    end = doc.index('escape_check_choice_required(ctx, effect, dc, grips, hazards)')
    assert start < end
