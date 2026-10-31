"""Digest reviewed proof dependencies, ignoring Python documentation only."""
from __future__ import annotations

import ast
import hashlib
from pathlib import PurePath


class _StripDocstrings(ast.NodeTransformer):
    def _strip(self, node):
        self.generic_visit(node)
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            del node.body[0]
        return node

    visit_Module = _strip
    visit_ClassDef = _strip
    visit_FunctionDef = _strip
    visit_AsyncFunctionDef = _strip


def dependency_digest(path: str, content: bytes) -> str | None:
    """Hash Python syntax without docstrings, or raw bytes for other files.

    Unparseable Python cannot match a reviewed digest and therefore fails closed.
    """
    if PurePath(path).suffix == ".py":
        try:
            tree = _StripDocstrings().visit(ast.parse(content))
        except (SyntaxError, UnicodeError, ValueError):
            return None
        content = ast.dump(tree).encode("utf-8")
    return hashlib.sha256(content).hexdigest()
