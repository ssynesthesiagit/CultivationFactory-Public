"""RW003 packet A1-P1: Humble Wall's rider text no longer denies tracking.

The rider used to read "object HP/AC are not tracked by the table yet" and to tell the
player to "track ... by hand". That is false: combat/rules/terrain.json's "humble wall" entry
carries the wall object's AC, hit points and immunities, and the table resolves attacks on a
wall section with them.

This public test checks only the stale wording. The prose checks that compare the rider with
the owner's reviewed wording live in tests/test_rw003_humble_wall_text_wording.py, which stays
local because the public mirror scrambles owner prose.
"""

import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
MECHANIC = "TAL_EARTH_HUMBLE_WALL"
AUTHORITY = APP / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"


def wall_rider() -> str:
    """The one rider sentence this record carries (the wall-modelling note)."""
    riders = json.loads(AUTHORITY.read_text(encoding="utf-8"))["mechanics"][MECHANIC]["riders"]
    assert len(riders) == 1, riders
    return riders[0]


def test_the_generated_rider_no_longer_denies_tracking_or_sends_the_numbers_by_hand():
    rider = wall_rider()
    lowered = rider.lower()
    for stale in ("by hand", "not tracked", "track its ac"):
        assert stale not in lowered, rider
