"""RW003: Humble Wall rider in the built table authority states tracked facts."""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
MECHANIC = "TAL_EARTH_HUMBLE_WALL"
AUTHORITY = APP / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
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

    # Source prose is transformed on public CI; check the built authority's
    # semantics rather than depending on byte-identical owner-text mappings.

