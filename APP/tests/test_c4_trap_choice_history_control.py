"""Opt-in private history control for the C4 trap placement regression.

Supply ``C4_OLD_TRAP_FILE`` pointing at an archived trap.py source file to
replay the historical negative control. The public gameplay regression remains
in test_c4_trap_choice_review.py and has no dependency on private Git history.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest


def load_old_trap_helpers(source_path: Path, namespace: dict) -> set[str]:
    """Load only the historical placement helpers into a trap module namespace."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names = {"_scatter", "_relocate"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    found = {node.name for node in functions}
    if found != names:
        raise ValueError(f"historical trap source is missing helpers: {sorted(names - found)}")
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source_path), "exec"), namespace)
    return names


def test_history_control_loads_only_explicit_historical_helpers(tmp_path, monkeypatch) -> None:
    source = tmp_path / "archived_trap.py"
    source.write_text(
        "def _scatter(engine, owner, intent, count, within_ft, *, concealed): pass\n"
        "def _relocate(engine, mover, traps, cells): pass\n"
        "def unrelated(): raise AssertionError('must not be loaded')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("C4_OLD_TRAP_FILE", str(source))
    explicit = Path(os.environ["C4_OLD_TRAP_FILE"])
    namespace = {}
    selected = load_old_trap_helpers(explicit, namespace)
    assert selected == {"_scatter", "_relocate"}
    assert set(namespace) == selected
    assert all(callable(namespace[name]) for name in selected)


@pytest.mark.skipif(not os.environ.get("C4_OLD_TRAP_FILE"), reason="private archived trap.py not supplied")
def test_historical_control_source_is_available() -> None:
    """Keep the archived source input explicit; never fetch it from Git at runtime."""
    path = Path(os.environ["C4_OLD_TRAP_FILE"])
    assert path.is_file()
