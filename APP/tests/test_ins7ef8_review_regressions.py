"""Regression coverage for INS7E review documentation findings."""

from pathlib import Path
import ast


APP = Path(__file__).resolve().parents[1]


def test_essence_state_is_documented_as_a_shared_helper():
    module = ast.parse((APP / "combat/ext/essence_state.py").read_text())
    doc = (ast.get_docstring(module) or "").lower()
    assert "shared" in doc
    assert "qi_devourer" in doc


def test_attack_target_interception_hook_contract_is_in_module_docstring():
    module = ast.parse((APP / "combat/ext/__init__.py").read_text())
    doc = ast.get_docstring(module) or ""
    assert "attack_target_interception(engine, attacker, target, source_id, intent, index)" in doc
    assert "or None" in doc
    assert "inert" in doc
    assert "ownership" in doc
