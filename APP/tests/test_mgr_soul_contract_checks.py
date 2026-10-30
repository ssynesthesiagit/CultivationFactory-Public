"""Observer information UI renderer check.

Historical exact-base stock captures and the authority-rebuild comparison
previously lived here but pinned to a private fork-point commit (base
8bd818c7), reading repository history unavailable on public CI. They moved to
lane tooling; only the public, node-rendered observer check remains.
"""
from pathlib import Path
import shutil
import pytest
from tests.soul_contract_evidence_support import source_checkpoint


@pytest.mark.skipif(not shutil.which('node'), reason='node not installed')
def test_observer_private_ui_renderer_without_browser():
    import subprocess
    app = Path(__file__).resolve().parents[1]
    result = subprocess.run(['node', '--test', 'static/tabletop/observer-information.test.mjs'],
        cwd=app, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
