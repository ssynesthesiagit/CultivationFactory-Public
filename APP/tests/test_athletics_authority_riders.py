"""Implemented Athletics clauses must not remain published as GM riders."""
import json
from pathlib import Path


def test_implemented_scale_foe_and_strong_lungs_clauses_are_not_gm_riders():
    authority_path = Path(__file__).parents[1] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
    mechanics = json.loads(authority_path.read_text(encoding="utf-8"))["mechanics"]

    # Boarding and Strong Lungs run in combat. Scale Foe deliberately keeps
    # its two printed cross-sphere judgement clauses visible to the GM.
    scale = mechanics["TAL_ATHLETICS_SCALE_FOE"]
    assert scale["coverage"] == "CORE_WITH_RIDERS"
    assert len(scale["riders"]) == 2
    assert any("Beast Taming" in rider for rider in scale["riders"])
    assert any("Wrestling" in rider for rider in scale["riders"])

    lungs = mechanics["TAL_ATHLETICS_STRONG_LUNGS"]
    assert lungs["riders"] == []
    assert lungs["coverage"] == "FULL"
