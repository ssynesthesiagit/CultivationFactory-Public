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


def test_source_fact_admission_hooks_are_documented_in_the_ext_contract():
    """Fact-admission hooks have explicit signatures, return contracts, and inert defaults."""
    import re

    init_doc = ast.get_docstring(ast.parse((ROOT / 'combat/ext/__init__.py').read_text(encoding='utf-8'))) or ''
    hooks = {
        'fact_admission_schema': 'fact_admission_schema(session, source, subject, kind)',
        'fact_admission_validate': 'fact_admission_validate(session, source, subject, kind, value)',
        'fact_admitted': 'fact_admitted(session, record)',
        'combat_fact_admission_allowed': 'combat_fact_admission_allowed(session, source, subject, kind)',
    }
    for name, signature in hooks.items():
        assert signature in init_doc, f'Document {name} with its arguments'
        assert re.search(re.escape(signature) + r'\s*->', init_doc), f'Document the return value of {name}'
    assert 'No schema/admission subscriber rejects input with no mechanical change' in init_doc
    source = (ROOT / 'combat/ext/__init__.py').read_text(encoding='utf-8')
    assert '# fact_admission_schema(' not in source, 'Keep the hook contract in the module docstring'

