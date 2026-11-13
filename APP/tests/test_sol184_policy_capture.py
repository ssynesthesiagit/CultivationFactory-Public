"""The only pins of the HUNT24 unowned stream, in both scheduling modes.

Changes to choices, rolls or journal payloads re-pin here with the named commit.
The synthetic origin-rule input keeps the complete genesis payload identical on
private trees and public exports; no event field is removed from either pin.
"""
import pytest
from combat import area_knowledge
from combat.canonical import canonical_sha256
from tests.hunt24_support import capture
from tests.legacy_fight_support import legacy_finalized_turns


@pytest.fixture
def unowned_origin_rules(tmp_path, monkeypatch):
    """Supply the unowned fight's rule input, not export-dependent catalog prose."""
    # Genesis scans the entire rules catalog, even for these talent-free actors.
    # Public exports scramble the original Darkness permission sentence. Give
    # this synthetic replay the same explicit input in both environments, using
    # the real file reader, permission scanner and persisted genesis binding.
    rules = tmp_path / "origin-rules.json"
    rules.write_text('{"DARK_BASE_DARKNESS": "Darkness anywhere within range."}\n', encoding="utf-8")
    monkeypatch.setattr(area_knowledge, "RULES_TEXT", rules)


# Both unchanged pins were measured on the private db88590c1b host capture.
# The fixture retains that capture's {DARK_BASE_DARKNESS: 0} origin binding;
# public CI must now match the same complete stream rather than have its own pin.
# Since 14113ef5f3: 37e7e4966b added forced: false movement receipts;
# f8d6b97d56 (fix/ai-tiers-1) chose dodge at step 5; fc49e97763
# (fix/ai-tricky-tune-1) chose an unarmed grapple at step 5 instead.
@pytest.mark.usefixtures("legacy_finalized_turns")
def test_unstamped_capture_matches_requested_348e0f79_base(tmp_path, unowned_origin_rules):
    steps, events = capture(tmp_path)
    assert steps == 8
    assert canonical_sha256(events) == '4e6b98a50c9059c8cdcde15efcce28b08277e73c91ac80758a3933b84b19f288'
    assert next(e for e in events if e['event_type'] == 'MATCH_CREATED')['payload']['rules'] == {'zero_hp':'dying_2024'}


def test_stamped_new_fight_capture_is_pinned_separately(tmp_path, unowned_origin_rules):
    steps, events = capture(tmp_path)
    assert steps == 8
    assert canonical_sha256(events) == 'a6e2602871928899ccb9191e68bc018d48e8ce8ed908308a1c1319f9f7f20f38'
    assert next(e for e in events if e['event_type'] == 'MATCH_CREATED')['payload']['rules'] == {
        'zero_hp':'dying_2024', 'finalized_turns':'skip_finalized_v1'}
