"""RW003: the built Humble Wall rider reflects the table's wall rules."""
import json
from pathlib import Path


APP = Path(__file__).resolve().parents[1]
AUTHORITY = APP / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"


def test_humble_wall_rider_describes_tracked_wall_sections():
    authority = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    riders = authority["mechanics"]["TAL_EARTH_HUMBLE_WALL"]["riders"]
    assert len(riders) == 1, riders
    rider = riders[0]
    lowered = rider.lower()
    assert "by hand" not in lowered and "not tracked" not in lowered
    for fact in (
        "automatically",
        "AC 12",
        "10 + Cultivation Level",
        "Poison",
        "Psychic",
        "wall section",
        "records those numbers",
        "resolves attacks",
    ):
        assert fact in rider, rider
