"""Receipt keys were spelled in four modules outside their owner.

A module spelling its own copy misses a renamed or added key, as happened
with the MATCH_ENDED receipt bug.
"""
import ast
from pathlib import Path

from combat.target_knowledge import OBSERVATION_RECEIPT_KEYS


def test_observation_receipt_literals_belong_to_target_knowledge():
    combat = Path(__file__).resolve().parents[1] / "combat"
    violations = []
    for path in sorted(combat.rglob("*.py")):
        if path == combat / "target_knowledge.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in OBSERVATION_RECEIPT_KEYS:
                violations.append(f"{path.relative_to(combat)}:{node.lineno}: {node.value}")
    assert not violations, violations
