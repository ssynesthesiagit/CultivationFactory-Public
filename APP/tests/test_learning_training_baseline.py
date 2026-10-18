"""Retained historical private-base checks, separate from public native acceptance."""
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_learning_training_native import ROOT
from tests.test_save_reload_equivalence import STOCK_SEEDS

# Last commit before the learning-choice producer (a932ac6d) existed; it still has the
# helper modules the native fixture imports, so the fixture can run against it.
PRE_PRODUCER_BASE = "2964cb2685286d25be30a30294be717c30c3d51b"
NATIVE_FIXTURE = Path(__file__).resolve().parent / "test_learning_training_native.py"


@pytest.mark.parametrize("seed", STOCK_SEEDS)
def test_exact_base_stock_replays(tmp_path, monkeypatch, seed):
    """Invoke the unmodified six stock guards with an exact reviewed base pin."""
    from tests import test_a2_glass_stock as guards
    monkeypatch.setenv("CF_REPLAY_BASE", "8bd818c78df011c2b67145d8e33975468c3e6a75")
    monkeypatch.setenv("CF_STOCK_EVIDENCE", str(tmp_path / "stock"))
    guards.test_six_stock_captures_equal_main(tmp_path, seed)


def test_exact_base_has_no_native_learning_choice_producer(tmp_path):
    """Fail-before evidence via exact Git modules and the same native fixture.

    The fixture file is the current one (it is not in the pinned tree); only the
    combat/catalog modules it imports come from PRE_PRODUCER_BASE.
    No alternate checkout, changes to source, or runtime engine patching.
    """
    script = '''
import runpy, sys
from pathlib import Path
from tests.wall_height_stock_capture import revision_sources
revision_sources(sys.argv[3], Path(sys.argv[2]) / "baseline")
fixture = runpy.run_path(sys.argv[1])
combat, table = fixture["native"](Path(sys.argv[2]) / "fixture")
try:
    fixture["offered"](table, "alchemy")
except KeyError as exc:
    assert exc.args == ("learning_choices",), exc
    print("BASELINE_MISSING_LEARNING_CHOICES")
else:
    raise AssertionError("The pinned base unexpectedly has a learning-choice producer")
'''
    result = subprocess.run([sys.executable, "-c", script, str(NATIVE_FIXTURE), str(tmp_path), PRE_PRODUCER_BASE],
                            cwd=ROOT, text=True, capture_output=True, timeout=180)
    assert result.returncode == 0, result.stdout[-1000:] + result.stderr[-2000:]
    assert "BASELINE_MISSING_LEARNING_CHOICES" in result.stdout
