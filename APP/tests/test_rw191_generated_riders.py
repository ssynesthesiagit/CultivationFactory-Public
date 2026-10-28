"""Generated authority must not call automated Foundation benefits manual."""
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_generated_authority_omits_automated_foundation_riders():
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    mechanics = authority["mechanics"]
    ids = (
        "foundation.white_crane_cloud_step_v0_2B.light_body_recovery",
        "foundation.true_blackblood_physique_v0_2C.blackblood_return",
        "foundation.sword_bones_v0_2B.sheath_bone_guard",
        "foundation.true_blackblood_physique_v0_2C.blackblood_guard",
        "foundation.weak_reed_tendons_v0_2B.bend_without_breaking_guard",
        "foundation.weak_reed_tendons_v0_2B.reed_sway_frame",
    )
    assert all(mechanics[feature_id]["riders"] == [] for feature_id in ids)
