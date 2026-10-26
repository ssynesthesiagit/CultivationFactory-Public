"""Generated authority must reflect rider removals in reviewed Foundation overrides."""
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_generated_authority_omits_removed_manual_refined_riders():
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    mechanics = authority["mechanics"]
    ids = (
        "foundation.white_crane_cloud_step_v0_2B.light_body_recovery",
        "foundation.true_blackblood_physique_v0_2C.blackblood_return",
        "foundation.weak_reed_tendons_v0_2B.bend_without_breaking_guard",
        "tianxia.path.qi_cultivation.feature.perfected_golden_core",
    )
    assert mechanics[ids[0]]["riders"] == []
    assert mechanics[ids[1]]["riders"]  # Perfected Return remains uncovered.
    assert mechanics[ids[2]]["riders"]  # Perfected Guard remains uncovered.
    assert mechanics[ids[3]]["riders"]  # Stable Core hostile Qi-loss protection remains uncovered.
