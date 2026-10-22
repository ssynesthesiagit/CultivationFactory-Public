"""Pin both scheduling policies without changing the older HUNT24 assertions."""
import pytest
from combat.canonical import canonical_sha256
from tests.test_hunt24_replay import capture
from tests.legacy_fight_support import legacy_finalized_turns


@pytest.mark.usefixtures("legacy_finalized_turns")
def test_unstamped_capture_matches_requested_348e0f79_base(tmp_path):
    steps, events = capture(tmp_path)
    assert steps == 8
    # Base 348e0f79 pinned 1eb7b58f...; batch 3 (DEPLOY3) adds only the approved new-fight genesis stamps
    # (ai_knowledge_policy, ai_search_policy, subject_repositioning_policy, cover_anchor_expiry_policy) and
    # ai-search observations_after journal refreshes. Choices, rolls and every other event are unchanged.
    assert canonical_sha256(events) == '1725ce15d4843821efad20eceb8ba24a1171c69540822ae6d19164882cb7caea'
    assert next(e for e in events if e['event_type'] == 'MATCH_CREATED')['payload']['rules'] == {'zero_hp':'dying_2024'}


def test_stamped_new_fight_capture_is_pinned_separately(tmp_path):
    steps, events = capture(tmp_path)
    assert steps == 8
    # Was 503c3455... before batch 3; same approved stamp/observation-only difference as above.
    assert canonical_sha256(events) == 'd477f2aa377213c4ea414fb076cb9b75265b0726fb6d8bb07e8d2bf873e61d78'
    assert next(e for e in events if e['event_type'] == 'MATCH_CREATED')['payload']['rules'] == {
        'zero_hp':'dying_2024', 'finalized_turns':'skip_finalized_v1'}
