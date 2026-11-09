"""The only pins of the HUNT24 unowned stream, in both scheduling modes.

Changes to choices, rolls or journal payloads re-pin here with the named commit.
"""
import pytest
from combat.canonical import canonical_sha256
from tests.hunt24_support import capture
from tests.legacy_fight_support import legacy_finalized_turns


# Since 14113ef5f3: 37e7e4966b added forced: false movement receipts;
# f8d6b97d56 (fix/ai-tiers-1) chose dodge at step 5; fc49e97763
# (fix/ai-tricky-tune-1) chose an unarmed grapple at step 5 instead.
@pytest.mark.usefixtures("legacy_finalized_turns")
def test_unstamped_capture_matches_requested_348e0f79_base(tmp_path):
    steps, events = capture(tmp_path)
    assert steps == 8
    assert canonical_sha256(events) == '4e6b98a50c9059c8cdcde15efcce28b08277e73c91ac80758a3933b84b19f288'
    assert next(e for e in events if e['event_type'] == 'MATCH_CREATED')['payload']['rules'] == {'zero_hp':'dying_2024'}


def test_stamped_new_fight_capture_is_pinned_separately(tmp_path):
    steps, events = capture(tmp_path)
    assert steps == 8
    assert canonical_sha256(events) == 'a6e2602871928899ccb9191e68bc018d48e8ce8ed908308a1c1319f9f7f20f38'
    assert next(e for e in events if e['event_type'] == 'MATCH_CREATED')['payload']['rules'] == {
        'zero_hp':'dying_2024', 'finalized_turns':'skip_finalized_v1'}
