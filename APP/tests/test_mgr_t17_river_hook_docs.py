"""Hook catalogue regression (MGR-T17 River Without Edges review): every run/run_strict hook
name used in combat/ is named in the ext/__init__ docstring. Public source-only check."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _init_doc():
    return ast.get_docstring(ast.parse((ROOT / 'combat/ext/__init__.py').read_text(encoding='utf-8'))) or ''


def test_every_run_hook_is_documented_in_ext_docstring():
    pattern = re.compile(r"\brun(?:_strict)?\(['\"]([a-z_]+)['\"]")
    names = set()
    for path in (ROOT / 'combat').rglob('*.py'):
        names.update(pattern.findall(path.read_text(encoding='utf-8')))
    assert 'movement_end_blocked' in names and 'movement_passage_cells' in names
    missing = sorted(name for name in names if name not in _init_doc())
    assert not missing, 'hooks used but not documented in combat/ext/__init__.py: ' + ', '.join(missing)


def test_river_edge_hooks_document_their_arguments_and_default_inert():
    doc = _init_doc()
    for signature in ('movement_end_blocked(engine, actor, grant_ft)', 'movement_passage_cells(engine, actor, grant_ft)'):
        assert signature in doc
        paragraph = re.split(r'\n(?=\S)', doc.split(signature, 1)[1])[0]  # up to the next hook entry
        assert 'default-inert' in paragraph
