"""Plug-in documentation regressions (MGR-T15 Soul Vessel F6): public source-only checks."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_hook_catalogue_documents_concentration_hooks_and_shared_helper_is_labelled():
    """Architecture-guard regression (F6): hooks used by plug-ins are named in the ext/__init__ docstring,
    and the ash_garden helper imported by foundations3 is labelled shared."""
    import ast
    init_doc = ast.get_docstring(ast.parse((ROOT / 'combat/ext/__init__.py').read_text(encoding='utf-8'))) or ''
    for name in ('concentration_save_sources(engine, subject)', 'concentration_save_resolved(engine, subject, roll, dc, maintained, sources)'):
        assert name in init_doc
    garden = ast.get_docstring(ast.parse((ROOT / 'combat/ext/ash_garden.py').read_text(encoding='utf-8'))) or ''
    assert 'shared' in garden.lower() and 'owns_zero_drop' in garden

