"""Dawnmark Scripture's automated sight exception must not ship as a GM rider."""

import json
from pathlib import Path


def test_scripture_sight_exception_is_not_a_gm_rider():
    path = Path(__file__).parents[1] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
    authority = json.loads(path.read_text(encoding="utf-8"))
    scripture = authority["mechanics"]["tianxia.talent.radiance.dawnmark_scripture"]

    # The sight exception is Scripture's only 60-foot clause. The range
    # survives public CI's prose scrambling, unlike the rider's wording.
    assert not any("60 feet" in rider for rider in scripture["riders"])
