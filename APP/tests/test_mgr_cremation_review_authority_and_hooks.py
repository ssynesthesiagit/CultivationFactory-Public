"""Regressions for preserving unrelated reviewed rows and documenting shared hooks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_body_refining_reviewed_rows_survive_cremation_authority():
    expected = {
        "tianxia.subpath.body.kensei.feature.flowing_blade_stance",
        "tianxia.subpath.body.kensei.feature.sword_saint_incarnation",
        "tianxia.subpath.body.thousand_fold_steel_body.feature.folded_edge_hidden_spine",
        "tianxia.subpath.body.thousand_fold_steel_body.feature.quench_the_impact",
        "tianxia.subpath.body.sumo.feature.rooted_stance",
        "tianxia.subpath.body.adamant_thunderbolt_body.feature.body_of_the_unbroken_bolt",
    }
    shards = ROOT / "authority/typed_mechanics/reviewed_final.d"
    for mechanic_id in expected:
        mechanics = json.loads(
            (shards / f"{mechanic_id}.json").read_text(encoding="utf-8")
        )["mechanics"]
        assert mechanic_id in mechanics
        assert mechanics[mechanic_id].get("effects")
    # The shard check alone cannot see a rebuild that drops a row from the generated authority.
    built = json.loads(
        (ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8")
    )["mechanics"]
    for mechanic_id in expected:
        assert built.get(mechanic_id, {}).get("effects"), mechanic_id


def test_journey_acquisition_hooks_have_contracts():
    extension_contract = (ROOT / "combat/ext/__init__.py").read_text(encoding="utf-8")
    for hook in ("journey_source_sheet", "journey_acquisition", "journey_acquired"):
        assert hook in extension_contract
    assert "absent providers leave it unchanged" in extension_contract
    assert "absent providers make no changes" in extension_contract
