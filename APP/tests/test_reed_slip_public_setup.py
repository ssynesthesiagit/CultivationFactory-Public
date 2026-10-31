"""Reed Slip's synthetic setup must not import unrelated integration tests."""
import ast
from pathlib import Path


def test_reed_slip_setup_imports_helpers_not_other_test_modules():
    root = Path(__file__).parent
    pending = [root / "test_reed_slip_parent.py"]
    seen = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            for module in modules:
                if not module.startswith("tests."):
                    continue
                name = module.split(".")[1]
                assert not name.startswith("test_"), (
                    f"{path.name}:{node.lineno} imports {module}; use a synthetic support helper "
                    "rather than pulling another integration test into the public export"
                )
                pending.append(root / f"{name}.py")


def test_table_transport_preserves_decision_version_answers_and_end_turn():
    from tests.table_action_support import act, end_turn

    class Table:
        def __init__(self):
            self.calls = []

        def state(self, mid):
            assert mid == "synthetic-match"
            return {"menu": {"decision_id": "decision:current", "state_version": 7,
                             "end_turn": "candidate:end"}}

        def act(self, *args):
            self.calls.append(args)
            return {"status": "COMMITTED"}

    table = Table()
    answers = ({"selection": "DECLINE"},)
    assert act(table, "synthetic-match", "candidate:move", answers) == {"status": "COMMITTED"}
    assert table.calls == [("synthetic-match", "candidate:move", "decision:current", 7, 0, list(answers))]
    assert end_turn(table, "synthetic-match") == {"status": "COMMITTED"}
    assert table.calls[-1] == ("synthetic-match", "candidate:end", "decision:current", 7, 0, [])
