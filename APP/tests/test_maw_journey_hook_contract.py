"""Journey lifecycle hooks must be documented in the public extension contract."""
import ast
from pathlib import Path
import re


def test_journey_lifecycle_contract_is_in_module_docstring():
    source = Path(__file__).resolve().parents[1] / "combat/ext/__init__.py"
    doc = ast.get_docstring(ast.parse(source.read_text(encoding="utf-8"))) or ""
    for name in (
        "journey_initialize",
        "journey_encounter_settled",
        "journey_snapshot_actor",
        "journey_scene_end",
    ):
        assert re.search(rf"\b{name}\([^\n)]*\)\s*->", doc), name
