"""Implemented Athletics clauses must not remain published as GM riders."""
import json
from pathlib import Path


def test_implemented_scale_foe_and_strong_lungs_clauses_are_not_gm_riders():
    authority_path = Path(__file__).parents[1] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
    mechanics = json.loads(authority_path.read_text(encoding="utf-8"))["mechanics"]

    # Scale Foe's Bonus Action boarding and Strong Lungs' breath clock are
    # implemented in combat/ext/athletics_scale.py and athletics_grip_lungs.py.
    for mechanic_id in ("TAL_ATHLETICS_SCALE_FOE", "TAL_ATHLETICS_STRONG_LUNGS"):
        record = mechanics[mechanic_id]
        assert record["riders"] == []
        assert record["coverage"] == "FULL"
