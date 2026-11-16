"""Lotus-Root's activation_admission hook is documented in the ext contract docstring.

Regression for the isolated-batch failure of test_architecture_guards.py::test_hook_documentation_and_unique_effects:
the hook was described only in a '#' comment, which the guard does not read, so it counted as undocumented.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def _contract_docstring():
    tree = ast.parse((APP / "combat/ext/__init__.py").read_text())
    return ast.get_docstring(tree) or ""


def test_activation_admission_is_documented_in_contract_docstring():
    doc = _contract_docstring()
    entry = [line for line in doc.splitlines() if line.startswith("activation_admission(")]
    assert entry, "Document activation_admission(...) in combat/ext/__init__.py's module docstring"
    text = " ".join(doc.split("activation_admission(", 1)[1].split("\n\n", 1)[0].split())
    assert "-> None | dict" in text
    assert "before economy/resource payment" in text
    assert "None is exactly default-inert" in text


def test_activation_admission_is_not_only_a_comment():
    source = (APP / "combat/ext/__init__.py").read_text()
    assert "# activation_admission(" not in source
