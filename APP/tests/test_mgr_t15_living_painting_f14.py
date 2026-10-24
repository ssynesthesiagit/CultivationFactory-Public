"""Living Painting review round (F13R): the swimming hook contract lives in the ext/__init__.py module docstring.

Source-only text checks; no fight, no model, no network, no authority JSON.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
EXT_INIT = APP / "combat" / "ext" / "__init__.py"


def _docstring():
    return ast.get_docstring(ast.parse(EXT_INIT.read_text(encoding="utf-8"))) or ""


def test_swimming_hook_contract_is_in_module_docstring_once():
    doc = _docstring()
    assert "swimming(engine, actor) -> {swim_speed_ft: int} | None" in doc
    assert "None or a zero grant is default-inert" in doc
    # The contract must not survive as a second copy in code comments.
    assert "# Native surface swimming" not in EXT_INIT.read_text(encoding="utf-8")


def test_transformation_reminder_no_longer_lists_native_movement():
    doc = _docstring()
    assert "climbing, flying, swimming, burrowing and beast agility remain" not in doc
    assert "burrowing and beast agility remain explicit Game Master reminders" in doc
