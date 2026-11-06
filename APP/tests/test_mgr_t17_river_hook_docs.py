"""Hook documentation regression (MGR-T17 River Without Edges review): the two movement hook points this
branch adds are documented with arguments and default-inert behaviour. The codebase-wide rule is
test_architecture_guards.test_hook_documentation_and_unique_effects. Public source-only check."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _init_doc():
    return ast.get_docstring(ast.parse((ROOT / 'combat/ext/__init__.py').read_text(encoding='utf-8'))) or ''


def test_river_edge_hooks_document_their_arguments_and_default_inert():
    doc = _init_doc()
    for signature in ('movement_end_blocked(engine, actor, grant_ft)', 'movement_passage_cells(engine, actor, grant_ft)'):
        assert signature in doc
        paragraph = re.split(r'\n(?=\S)', doc.split(signature, 1)[1])[0]  # up to the next hook entry
        assert 'default-inert' in paragraph
