"""Guard the sheet test's rule-text case selection without importing private builders."""
import ast
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def test_already_current_cases_only_select_rule_text_edits():
    """Display-only entries need their own idempotence test, not CURRENT indexing."""
    edits = json.loads((APP / "authority/typed_mechanics/owner_text_edits.json").read_text())["records"]
    current = json.loads((APP / "authority/typed_mechanics/rules_text.json").read_text())
    tree = ast.parse((APP / "tests/test_sheet_owner_current_rules.py").read_text())
    # Evaluate the actual selection declarations and decorator, not a copy of
    # their logic. Importing the test module would pull in the private builder.
    namespace = {"EDITS": edits}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in {"RULES_EDITS", "DISPLAY_ONLY"}
            for target in node.targets
        ):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<case-selection>", "exec"), namespace)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "test_already_current_rules_are_not_edited_twice")
    decorator = next(node for node in function.decorator_list
                     if isinstance(node, ast.Call) and node.args
                     and isinstance(node.args[0], ast.Constant) and node.args[0].value == "record_id")
    selected = eval(compile(ast.Expression(decorator.args[1]), "<case-selection>", "eval"), namespace)
    expected = {rid for rid, edit in edits.items() if edit.get("replace") or edit.get("remove")}
    assert set(selected) == expected
    assert set(selected) <= current.keys()
    # All other owner records retain explicit display-only idempotence coverage.
    assert set(namespace["DISPLAY_ONLY"]) == edits.keys() - expected
    assert any(isinstance(node, ast.FunctionDef)
               and node.name == "test_display_only_owner_edit_is_not_applied_twice"
               for node in tree.body)
