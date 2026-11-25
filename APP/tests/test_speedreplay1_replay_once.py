"""Fresh imports for replay and harm classification modules."""
import subprocess
import sys


def test_fresh_module_imports():
    for name in ("combat.gate3_reducer", "combat.effect_harm"):
        result = subprocess.run([sys.executable, "-c", f"import {name}"], capture_output=True, text=True)
        assert result.returncode == 0, f"{name}: {result.stderr}"
