"""Riders must distinguish wired Foundation improvements from manual clauses."""
import json
from pathlib import Path

from combat.typed_reactions import rules

ROOT = Path(__file__).parents[1]
BLOOD = "foundation.true_blackblood_physique_v0_2C."
REED = "foundation.weak_reed_tendons_v0_2B."
BONE = "foundation.sword_bones_v0_2B."
CRANE = "foundation.white_crane_cloud_step_v0_2B."


def test_generated_authority_matches_wired_foundation_improvements():
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    mechanics = authority["mechanics"]
    rows = json.loads((ROOT / "combat/rules/feature_blocks.d/a2_foundations4.json").read_text())["features"]
    resources = json.loads((ROOT / "combat/rules/feature_blocks.d/sys_resources-states.json").read_text())["features"]
    providers = rules()["features"]

    # These removed Refined riders are backed by specific consumer rows.
    for base, expression in {
        BLOOD + "blackblood_return": BLOOD + "refined_hidden_vitality_return",
        BLOOD + "blackblood_guard": BLOOD + "refined_clotted_iron_blood",
        REED + "bend_without_breaking_guard": REED + "refined_verdant_sinews",
    }.items():
        assert rows[base]["refined_expression"] == expression
        assert all("Refined" not in r for r in mechanics[base]["riders"])

    wings = resources[CRANE + "refined_wings_remember_ground"]
    assert (wings["block"], wings["kind"]) == ("foundation_spend", "wings_remember_ground")
    assert any(e["type"] == "foundations4_recovery" for e in mechanics[CRANE + "light_body_recovery"]["effects"])
    assert not mechanics[CRANE + "light_body_recovery"]["riders"]

    # A generic provider is not an owned expression row: the synthetic peer
    # packet in test_bone_perfected_parent does not publish one in production.
    assert BONE + "refined_bone_sheath_guard" not in providers
    assert "refined_expression" not in rows[BONE + "sheath_bone_guard"]
    assert any("Refined Bone-Sheath Guard" in r for r in mechanics[BONE + "sheath_bone_guard"]["riders"])

    # The base speed row has no stage-dependent extra; these other evolutions
    # have no matching production provider in the Foundation conversion rows.
    assert rows[REED + "reed_sway_frame"]["rules"] == [{"kind": "speed_bonus", "ft": 5}]
    for base, label in (
        (BLOOD + "blackblood_return", "Perfected Self-Owned Impurity"),
        (BLOOD + "blackblood_guard", "Perfected Self-Owned Impurity"),
        (REED + "bend_without_breaking_guard", "Perfected Unbroken Reed"),
        (REED + "reed_sway_frame", "Integrated Reed-Sway Frame"),
    ):
        assert any(label in rider for rider in mechanics[base]["riders"])
