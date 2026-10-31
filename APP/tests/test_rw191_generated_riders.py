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

    # Automated improvements must not remain as manual instructions; genuinely
    # unwired improvements retain their riders.
    assert rows[REED + "reed_sway_frame"]["rules"] == [{"kind": "speed_bonus", "ft": 5}]
    for base in (BLOOD + "blackblood_return", BLOOD + "blackblood_guard",
                 REED + "bend_without_breaking_guard"):
        assert not any("Perfected" in rider for rider in mechanics[base]["riders"])
    assert BLOOD + "perfected_self_owned_impurity" in providers
    assert REED + "perfected_unbroken_reed" in providers
    # The Integrated clause's second 5 feet is not applied by the fight, so its
    # rider must name the clause, the amount, and who adds it. A rider that
    # claimed the fight applies it would be a false instruction.
    sway_riders = mechanics[REED + "reed_sway_frame"]["riders"]
    assert any("Integrated" in rider and "another 5 feet" in rider
               and "person running the game" in rider for rider in sway_riders), sway_riders
    blood_riders = mechanics[BLOOD + "blackblood_refusal"]["riders"]
    assert any("selected Refined Venom-Dark Marrow is already added" in r for r in blood_riders)
    reed_riders = mechanics[REED + "reed_recovery"]["riders"]
    assert any("Refined: River-Reed Flexibility" in r and "person running the game adds another Proficiency Bonus by hand" in r for r in reed_riders)
    for riders in (blood_riders, reed_riders):
        assert all("Perfected" not in rider for rider in riders)
