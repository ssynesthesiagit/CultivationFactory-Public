"""RW003 packet A1-P1: Humble Wall rider wording matches the table and reviewed sources.

The source-map comparison uses owner prose, so this read-only check is local-only.
"""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
MECHANIC = "TAL_EARTH_HUMBLE_WALL"
AUTHORITY = APP / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
OWNER_EDITS = APP / "authority" / "typed_mechanics" / "owner_text_edits.json"
PLAYER_TEXT = APP / "authority" / "typed_mechanics" / "player_text.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_humble_wall_rider_matches_table_facts_and_both_reviewed_sources():
    riders = _json(AUTHORITY)["mechanics"][MECHANIC]["riders"]
    assert len(riders) == 1, riders
    rider = riders[0]
    lowered = rider.lower()
    for stale in ("by hand", "not tracked", "track its ac"):
        assert stale not in lowered, rider
    for fact in ("automatically", "AC 12", "10 + Cultivation Level", "Poison", "Psychic",
                 "wall section", "records those numbers", "resolves attacks"):
        assert fact in rider, rider

    owner_pairs = _json(OWNER_EDITS)["records"][MECHANIC]["player_evidence"]
    player_evidence = _json(PLAYER_TEXT)["evidence"]
    assert owner_pairs, "the owner's reviewed wording for this rider is missing"
    for raw, wording in owner_pairs.items():
        assert player_evidence.get(raw) == wording, raw
        assert wording == rider, wording
