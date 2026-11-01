"""Public, offline regression for desktop deferred-route confirmation."""
from pathlib import Path
import subprocess


def test_desktop_deferred_route_discloses_hazard_before_commit():
    app = Path(__file__).resolve().parents[1]
    result = subprocess.run(['node', 'tests/menuspeed7_route_confirmation.mjs'],
                            cwd=app, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'discloses native route/hazard' in result.stdout
