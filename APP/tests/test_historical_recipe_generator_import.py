"""The historical generator must import against a base checkout's tests package.

The generator lives beside the oracle it produces and is loaded here through its repository path, spelled as one
literal so the public export's dependency scan ships it with the test (a path built from Path operators is invisible
to that scan, which is how an earlier version of this file shipped without the script and failed on public CI).
"""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = "APP/tests/fixtures/generate_historical_seeded_recipes.py"


def test_generator_help_with_base_tests_package(tmp_path):
    base_tests = tmp_path / "base" / "tests"
    base_tests.mkdir(parents=True)
    (base_tests / "__init__.py").write_text("")
    generator = ROOT / GENERATOR
    assert generator.is_file()
    result = subprocess.run(
        [sys.executable, str(generator), "--help"], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(base_tests.parent)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--scratch" in result.stdout
