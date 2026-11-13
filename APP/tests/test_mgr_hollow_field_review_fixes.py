"""Review-fix regressions for the Void-Touched Cultivator branch.

Each test fails on the pre-fix code: the long CombatService.__init__ signature,
and the duplicated acquisition builders in the two Void-Touched test files.
"""
import ast
import inspect
from pathlib import Path

from combat.gate5_service import CombatService

ROOT = Path(__file__).resolve().parents[1]


def test_combat_service_init_signature_fits_the_style_limit():
    lines, _ = inspect.getsourcelines(CombatService.__init__)
    too_long = [line for line in lines if len(line.rstrip("\n")) > 120]
    assert too_long == [], f"CombatService.__init__ exceeds 120 columns: {too_long}"


def test_both_void_touched_test_files_use_the_shared_acquisition_builder():
    for name in ("test_mgr_hollow_field.py", "test_mgr_void_step.py"):
        tree = ast.parse((ROOT / "tests" / name).read_text(), name)
        local_defs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        assert "_build_acquisition" in local_defs, name
        imported = [a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                    and n.module == "tests.void_touched_acquisition_support" for a in n.names]
        assert imported == ["build_native_acquisition"], name
        body = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_build_acquisition")
        calls = [c for c in ast.walk(body) if isinstance(c, ast.Call)
                 and getattr(c.func, "id", None) == "build_native_acquisition"]
        assert len(calls) == 1, f"{name}: _build_acquisition must delegate to the shared builder"
