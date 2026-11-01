"""Opt-in comparison from pre-fix synthetic AI captures; never reads live fights."""
import os
from pathlib import Path

import pytest

from tests.hunt36_replay_compare import compare


@pytest.mark.skipif(not os.environ.get("HUNT36_BASE_REPLAY"), reason="requires task-owned pre-fix AI capture")
@pytest.mark.parametrize("scenario", ["ordinary", "radiance"])
def test_pre_fix_ai_replay_only_has_intended_differences(scenario):
    root = Path(os.environ["HUNT36_BASE_REPLAY"]).resolve()
    match = next((root / scenario).rglob("GenesisState.json")).parent
    sequences = [1, 3, 5, 7, 9, 11] if scenario == "ordinary" else [7, 9, 11, 13, 15, 17]
    results = compare(match, sequences)
    for result in results:
        if scenario == "ordinary":
            assert not result["diffs"], result
            continue
        # Heavenly Radiance already removes Invisible's benefits. Fix 4 makes
        # target knowledge honor that mask: the Factory team now sees movement.
        assert result["diffs"], result
        for diff in result["diffs"]:
            path = diff["path"]
            if path.startswith("/state/observations/team:factory/actor:factory.36000002/"):
                assert path.rsplit("/", 1)[-1] in ("x", "y")
            elif path.startswith("/events/") and path.endswith("/payload/observations_after"):
                assert diff["old"] is None
                assert set(diff["new"]) == {"team:factory"}
                assert set(diff["new"]["team:factory"]) == {"actor:factory.36000002"}
            elif path.startswith("/events/") and path.endswith("/payload/observed_by"):
                assert diff["old"] == ["team:opponents"]
                assert diff["new"] == ["team:factory", "team:opponents"]
            else:
                pytest.fail(f"Unexpected baseline-to-final difference: {diff}")
