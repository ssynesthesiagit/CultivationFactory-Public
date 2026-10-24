"""Shared-helper contract for combat/ext/saber_learning.py (F15R lead review).

Other ext modules import saber_learning's public functions, so its module docstring must
say it is shared and name every consumer module. Checked on the source text, so the test
needs no prose fixtures and runs on public CI.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
MODULE = APP / "combat/ext/saber_learning.py"
CONSUMERS = ("sabers_riders", "weapon_required", "wenxue_sabers")


def test_saber_learning_docstring_declares_shared_helper_and_consumers():
    doc = ast.get_docstring(ast.parse(MODULE.read_text(encoding="utf-8"))) or ""
    assert "shared" in doc.lower()
    for name in CONSUMERS:
        assert f"combat/ext/{name}.py" in doc, f"docstring must name consumer {name}.py"


def test_every_saber_learning_importer_is_a_named_consumer():
    importers = set()
    for path in (APP / "combat/ext").glob("*.py"):
        if path.stem == "saber_learning":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "saber_learning" and node.level == 1:
                importers.add(path.stem)
    assert importers == set(CONSUMERS)
