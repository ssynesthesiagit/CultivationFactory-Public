"""Journey lifecycle hooks must be documented in the public extension contract."""

from tests.hook_docs import catalogue
import ast
from pathlib import Path
import re


def test_journey_lifecycle_contract_is_in_module_docstring():
    doc = catalogue()
    for name in (
        "journey_initialize",
        "journey_encounter_settled",
        "journey_snapshot_actor",
        "journey_scene_end",
    ):
        assert re.search(rf"\b{name}\([^\n)]*\)\s*->", doc), name
