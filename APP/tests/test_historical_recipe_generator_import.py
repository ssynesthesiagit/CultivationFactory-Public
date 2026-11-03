"""The historical generator must import with a base checkout's tests package."""
import os
from pathlib import Path
import subprocess
import sys


def test_generator_help_with_base_tests_package(tmp_path):
    base_tests = tmp_path / "base" / "tests"
    base_tests.mkdir(parents=True)
    (base_tests / "__init__.py").write_text("")
    generator = Path(__file__).parent / "fixtures" / "generate_historical_seeded_recipes.py"
    result = subprocess.run(
        [sys.executable, str(generator), "--help"], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(base_tests.parent)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--scratch" in result.stdout
