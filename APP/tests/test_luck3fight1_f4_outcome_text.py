"""Heaven's Luck sheet outcome text is player-facing (LUCK3FIGHT1 F4).

The sheet outcome must not carry internal owner-ruling provenance; that belongs in
reviewed_final.d / owner_text_edits.why. Synthetic-free: reads the public feature block file.
"""
import json
from pathlib import Path

BLOCKS = Path(__file__).resolve().parents[1] / "combat" / "rules" / "feature_blocks.d" / "a2_insights_five.json"
FORBIDDEN = ("owner", "ruling", "2026", "reviewed", "playtest")


def _heavens_luck_outcome() -> str:
    data = json.loads(BLOCKS.read_text(encoding="utf-8"))
    return data["features"]["insight.legacy-heavens-luck"]["outcome"]


def test_heavens_luck_outcome_has_no_internal_provenance():
    outcome = _heavens_luck_outcome()
    lowered = outcome.lower()
    for word in FORBIDDEN:
        assert word not in lowered, f"internal provenance '{word}' in player text: {outcome!r}"


def test_heavens_luck_outcome_states_three_uses_plainly():
    outcome = _heavens_luck_outcome()
    assert outcome.startswith("Up to three times each fight")
    assert "All three uses return at the start of each fight" in outcome
