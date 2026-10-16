"""Review regressions for phone activation discovery and base-family identity."""
import subprocess


def test_phone_draft_enabled_and_aliased_activations():
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', 'tests/mobile_option_reachability.test.mjs'],
        text=True, capture_output=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
