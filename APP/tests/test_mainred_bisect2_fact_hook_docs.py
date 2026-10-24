"""Regression for MAINREDBISECT2: source-fact admission hooks must be documented in the ext contract docstring.

Before the fix the four hooks were described only in a # comment block after the module docstring, so the
architecture guard (test_hook_documentation_and_unique_effects) flagged them as undocumented.
Synthetic static check of combat/ext/__init__.py; no fixtures, no private data.
"""
import ast
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]

FACT_HOOKS = {
    "fact_admission_schema": "fact_admission_schema(session, source, subject, kind)",
    "fact_admission_validate": "fact_admission_validate(session, source, subject, kind, value)",
    "fact_admitted": "fact_admitted(session, record)",
    "combat_fact_admission_allowed": "combat_fact_admission_allowed(session, source, subject, kind)",
}


def _ext_docstring():
    return ast.get_docstring(ast.parse((APP / "combat/ext/__init__.py").read_text(encoding="utf-8"))) or ""


@pytest.mark.parametrize("hook", sorted(FACT_HOOKS))
def test_source_fact_admission_hook_is_in_the_ext_docstring(hook):
    doc = _ext_docstring()
    assert FACT_HOOKS[hook] in doc, f"Document {hook} with its arguments in the combat/ext/__init__.py module docstring"
    assert re.search(re.escape(FACT_HOOKS[hook]) + r"\s*->", doc), f"Document the return value of {hook}"


def test_source_fact_admission_contract_is_not_only_a_comment():
    source = (APP / "combat/ext/__init__.py").read_text(encoding="utf-8")
    assert "# fact_admission_schema(" not in source, "Keep the hook contract in the docstring, not a # comment"
    assert "No schema/admission subscriber rejects input with no mechanical change" in _ext_docstring(), "State that the fact hooks are default-inert"
