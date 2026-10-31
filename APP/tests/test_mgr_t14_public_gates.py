"""Public-test gates for the MGR-T14 Drunken Fist tests (F13R2 blocking finding).

Pinned private revisions and evidence writes must be opt-in, skip with a reason
when disabled, and must not hard-code host paths outside the repository. The
CONDITION_REMOVED guard locks the audit result that only Falling Fist observes
the removal of Prone.
"""
import ast
import json
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
TESTS = APP / "tests"
FLAG = "MGR_T14_PRIVATE_BASE_CAPTURE"
EVIDENCE = "MGR_T14_EVIDENCE_DIR"
PRIVATE_BASE_FILES = (
    "test_mgr_t14_drunken_fist_stock.py",
    "test_mgr_t14_drunken_fist_baseline_attribution.py",
)
# Built from parts so this guard file never contains its own forbidden needles.
FORBIDDEN = ("/var/" + "tmp", "/home/", "auto-" + "audit", "ling-" + "resume")
FALLING_FIST = "tianxia.subpath.body.drunken_fist.feature.falling_fist"


def _drunken_files():
    return sorted(TESTS.glob("test_mgr_t14_drunken_fist_*.py"))


def test_drunken_fist_tests_have_no_host_or_lane_paths():
    hits = {}
    for path in _drunken_files():
        text = path.read_text()
        found = [needle for needle in FORBIDDEN if needle in text]
        if found:
            hits[path.name] = found
    assert hits == {}


def _pytestmark_source(path):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            return ast.unparse(node.value)
    return ""


def _string_constants(path):
    """Module-level string constants: a gate checks the value, not its spelling."""
    values = {}
    for node in ast.parse(path.read_text()).body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    return values


def _constant_holding(path, value):
    """The module constant that holds a given environment-variable name."""
    names = [name for name, held in _string_constants(path).items() if held == value]
    assert names, f"{path.name} must name {value} in a module constant"
    return names[0]


def _skipif_environment_constant(path):
    """The environment constant a module-level skipif reads, if any."""
    for node in ast.parse(path.read_text()).body:
        if not isinstance(node, ast.Assign) or not any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            continue
        for call in ast.walk(node.value):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "skipif" and call.args):
                continue
            test = call.args[0]
            if not (isinstance(test, ast.Compare) and isinstance(test.left, ast.Call)
                    and isinstance(test.left.func, ast.Attribute) and test.left.func.attr == "get"
                    and isinstance(test.left.func.value, ast.Attribute)
                    and test.left.func.value.attr == "environ"
                    and test.left.args and isinstance(test.left.args[0], ast.Name)):
                continue
            return test.left.args[0].id
    return None


@pytest.mark.parametrize("name", PRIVATE_BASE_FILES)
def test_private_base_files_skip_unless_opted_in(name):
    path = TESTS / name
    if not path.exists():
        pytest.skip(f"{name} is a private file; the published copy does not carry it")
    constant = _constant_holding(path, FLAG)
    read = _skipif_environment_constant(path)
    assert read == constant, f"{name} must skip on its {FLAG} constant"
    assert "skipif" in _pytestmark_source(path), f"{name} must skip unless {FLAG}=1"


def _environ_lookup(path, constant):
    """(bound name, line) of an os.environ.get(<constant>) lookup, if any."""
    for node in ast.walk(ast.parse(path.read_text())):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "get"
                and isinstance(node.value.func.value, ast.Attribute)
                and node.value.func.value.attr == "environ"
                and node.value.args and isinstance(node.value.args[0], ast.Name)
                and node.value.args[0].id == constant
                and isinstance(node.targets[0], ast.Name)):
            continue
        return node.targets[0].id, node.lineno
    return None, None


def _mentions(node, name):
    return any(isinstance(child, ast.Name) and child.id == name for child in ast.walk(node))


def _skip_guard(path, name, after_line):
    """The guard that stops the writer when the environment variable is unset."""
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.If) or node.lineno <= after_line or not _mentions(node.test, name):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Return):
                return node
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "skip"):
                return node
    return None


def _write_call(path, after_line):
    """The line of the evidence directory write, if any."""
    for node in ast.walk(ast.parse(path.read_text())):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "mkdir" and node.lineno > after_line):
            return node.lineno
    return None


def test_native_evidence_writer_only_writes_when_opted_in():
    path = TESTS / "test_mgr_t14_drunken_fist_native.py"
    if not path.exists():
        pytest.skip("the native evidence file is private; the published copy does not carry it")
    constant = _constant_holding(path, EVIDENCE)
    name, lookup_line = _environ_lookup(path, constant)
    assert name is not None, "evidence must be gated by " + EVIDENCE
    guard = _skip_guard(path, name, lookup_line)
    assert guard is not None, "the evidence writer must skip when " + EVIDENCE + " is unset"
    assert _write_call(path, guard.lineno) is not None, "evidence must be written after the guard"


def test_only_falling_fist_declares_removed_condition_transitions():
    doc = json.loads((APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    found = set()

    def walk(node):
        if isinstance(node, dict):
            if "removed" in (node.get("condition_transitions") or ()):
                found.add(node.get("mechanic_id"))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    assert found == {FALLING_FIST}, found
