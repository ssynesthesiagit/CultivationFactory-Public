"""Menu test documentation describes reproducible checks and prerequisites."""
import ast
import io
from pathlib import Path
import re
import tokenize

import pytest


TEST_FILES = (
    "test_menuspeed6_browser_optin.py",
    "test_menuspeed7_review.py",
    "test_ranked_menu_node.py",
    "test_menuspeed7_desktop_poll.py",
    "test_menuspeed7_lazy.py",
)
COORDINATION = re.compile(r"\b(?:lead|lane|worker|queue|ci)\b|\bthe sandbox\b", re.IGNORECASE)


# Inspect sources shipped in this installation without importing their
# application dependencies. Minimal distributions may omit integration tests.
TEST_PATHS = sorted(path for path in Path(__file__).parent.glob("test_*.py")
                    if path.name in TEST_FILES)


@pytest.mark.parametrize("path", TEST_PATHS, ids=lambda path: path.name)
def test_menu_test_documentation_is_environment_neutral(path):
    filename = path.name
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    prose = [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                prose.append((getattr(node, "lineno", 1), doc))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "pytest"
                and node.func.attr == "skip"):
            prose.extend((part.lineno, part.value) for part in ast.walk(node)
                         if isinstance(part, ast.Constant) and isinstance(part.value, str))
    violations = [f"{filename}:{line}: {text.strip()}" for line, text in prose
                  if COORDINATION.search(text)]
    assert not violations, "\n".join(violations)
