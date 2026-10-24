"""Regression: combat/ext/water_second_pass.py exports helpers used by another plug-in.

The architecture guard requires a module whose public functions are imported by
another combat/ext module to say "shared" in its docstring and name its consumers.
Without the docstring section this fails with 'water_second_pass' as a new debt.
"""
import ast
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "combat" / "ext"


def test_water_second_pass_documents_shared_api_and_consumers():
    tree = ast.parse((EXT / "water_second_pass.py").read_text(encoding="utf-8"))
    doc = ast.get_docstring(tree) or ""
    assert "shared" in doc.lower()
    assert "Consumers:" in doc
    assert "combat/ext/water_defenses.py" in doc
    assert "mist_basins" in doc and "SOAKED" in doc


def test_documented_consumer_really_imports_the_shared_api():
    tree = ast.parse((EXT / "water_defenses.py").read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "water_second_pass"
        for alias in node.names
    }
    assert imported == {"mist_basins", "SOAKED"}
