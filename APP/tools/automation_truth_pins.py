"""Regenerate existing automation proof pins from the reviewed bytes a caller supplies.

The rules live here so they can be tested without repository history: this module reads the working tree only, and the
reviewed bytes arrive through `regenerate`'s `reviewed_bytes` argument. tools/build_automation_truth_pins.py is the
command line that supplies them from the exact reviewed Git commit; new dependencies still require an explicit review.
Only existing digest literals are regenerated, preserving fail-closed checks.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import Callable

if __package__:
    from tools.automation_truth_digest import dependency_digest
else:  # Also support the documented direct-script invocation.
    from automation_truth_digest import dependency_digest

ROOT = Path(__file__).resolve().parents[2]
FILES = ("APP/tools/automation_truth_effects.py", "APP/tools/automation_truth_plugin_proofs.py")


def regenerate(relative: str, reviewed_ref: str, reviewed_bytes: Callable[[str], bytes]) -> str:
    """`relative`'s source with every existing pin refreshed to its reviewed bytes.

    `reviewed_bytes(dependency)` returns the reviewed source of one dependency path; the working copy must match it
    exactly, so an unreviewed edit raises before any pin changes.
    """
    path = ROOT / relative
    source = path.read_text()
    names = {}
    mapping = None
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name == "_REVIEWED_SHA256":
            mapping = node.value
        elif isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            names[name] = node.value.value
    if not isinstance(mapping, ast.Dict):
        raise ValueError(f"Missing proof dependency mapping in {relative}")
    edits = []
    lines = source.splitlines(keepends=True)
    for key, value in zip(mapping.keys, mapping.values):
        dependency = names[key.id] if isinstance(key, ast.Name) else ast.literal_eval(key)
        expected = reviewed_bytes(dependency)
        actual = (ROOT / dependency).read_bytes()
        if actual != expected:
            raise ValueError(f"Unreviewed working-copy drift: {dependency}")
        digest = dependency_digest(dependency, actual)
        if digest is None:
            raise ValueError(f"Cannot parse reviewed dependency: {dependency}")
        start = sum(len(line) for line in lines[:value.lineno - 1]) + value.col_offset
        end = sum(len(line) for line in lines[:value.end_lineno - 1]) + value.end_col_offset
        edits.append((start, end, '"' + digest + '"'))
    for start, end, replacement in reversed(edits):
        source = source[:start] + replacement + source[end:]
    source = re.sub(r'^_REVIEWED_REF = .*$', f'_REVIEWED_REF = "{reviewed_ref}"', source, flags=re.MULTILINE)
    return source
