"""Keep the public reach regressions independent of owner saved-fight evidence."""
from pathlib import Path


def test_owner_snapshot_test_is_not_shipped():
    # Skipping an owner-only test does not make its embedded evidence public-safe.
    # The synthetic table tests in test_qiang_reach.py cover the same behavior.
    assert not Path(__file__).with_name("test_qiang_reach_private.py").exists()
