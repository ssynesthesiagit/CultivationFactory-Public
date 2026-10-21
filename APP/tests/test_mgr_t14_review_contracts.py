"""Integration regressions for the journey/Active Defense hook contracts."""
import ast
from pathlib import Path
import re

import pytest

APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("signature", [
    "reaction_admission(engine, row, target, attacker, intent, attack_spec)",
])
def test_hook_contracts_are_in_discoverable_module_documentation(signature):
    # Comments below the module docstring are invisible to the architecture
    # guard and to help(combat.ext). Multiline signatures must also be findable.
    tree = ast.parse((APP / "combat/ext/__init__.py").read_text())
    doc = ast.get_docstring(tree) or ""
    assert signature in doc
    point = signature.split("(")[0]
    assert point in set(re.findall(r"\b([a-z][a-z0-9_]*)\([^\n)]*\)", doc))
    contract = doc.split(signature, 1)[1].split("\n# ", 1)[0]
    assert "None" in contract
