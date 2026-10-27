"""Guard: Blacksmith plug-ins must not put game actions inside assert (python -O strips them)."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "combat" / "ext"


def test_blacksmith_plugins_have_no_calls_inside_assert():
    offenders = []
    for path in sorted(ROOT.glob("blacksmith*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert) and any(isinstance(n, ast.Call) for n in ast.walk(node.test)):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"calls inside assert are stripped by python -O: {offenders}"


def test_quench_pays_its_forge_mark_under_python_optimize(tmp_path):
    """Behavior check in optimized mode: a paid Quench still spends the mark and the Reaction after reload."""
    import json
    import subprocess
    import sys

    app = Path(__file__).resolve().parents[1]
    run = subprocess.run([sys.executable, "-O", str(app / "tests" / "blacksmith_optimized_probe.py"), str(tmp_path)],
                         cwd=app, capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stderr[-3000:]
    result = json.loads(run.stdout.strip().splitlines()[-1])
    assert result["optimize"] == 1
    assert result["quench_resolved"] == 1
    assert result["marks"] == 0
    assert result["reaction_available"] is False
    assert result["foe_damaged"] is True
