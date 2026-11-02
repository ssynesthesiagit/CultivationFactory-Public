"""selected_query in combat/ext/foundation_combat.py has no unreachable statements.

A duplicated `return` line after another `return` is dead code that hides which branch
actually decides the selection. Checked from the source tree with ast; no history reads.
"""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'combat' / 'ext' / 'foundation_combat.py'


def _function(name):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)


def _unreachable_after_return(body):
    for index, statement in enumerate(body):
        if isinstance(statement, ast.Return) and index + 1 < len(body):
            return body[index + 1]
        for field in ('body', 'orelse', 'finalbody'):
            nested = getattr(statement, field, None)
            if isinstance(nested, list) and nested:
                found = _unreachable_after_return(nested)
                if found is not None:
                    return found
    return None


def test_selected_query_has_no_statement_after_a_return():
    dead = _unreachable_after_return(_function('selected_query').body)
    assert dead is None, f'unreachable statement in selected_query at line {getattr(dead, "lineno", "?")}'
