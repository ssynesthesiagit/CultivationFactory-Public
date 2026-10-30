"""Regressions for preserving unrelated reviewed rows and documenting shared hooks."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_body_refining_reviewed_rows_survive_cremation_authority():
    expected = {
        "reviewed_final.d/paths.json": {
            "tianxia.subpath.body.kensei.feature.flowing_blade_stance",
            "tianxia.subpath.body.kensei.feature.sword_saint_incarnation",
            "tianxia.subpath.body.thousand_fold_steel_body.feature.folded_edge_hidden_spine",
            "tianxia.subpath.body.thousand_fold_steel_body.feature.quench_the_impact",
        },
        "reviewed_final.d/docket.json": {
            "tianxia.subpath.body.sumo.feature.rooted_stance",
        },
        "reviewed_final.d/lock4_unbroken_bolt.json": {
            "tianxia.subpath.body.adamant_thunderbolt_body.feature.body_of_the_unbroken_bolt",
        },
    }
    for shard, ids in expected.items():
        mechanics = json.loads(
            (ROOT / "authority/typed_mechanics" / shard).read_text(encoding="utf-8")
        )["mechanics"]
        assert ids <= mechanics.keys()


def test_journey_acquisition_hooks_have_contracts():
    extension_contract = (ROOT / "combat/ext/__init__.py").read_text(encoding="utf-8")
    for hook in ("journey_source_sheet", "journey_acquisition", "journey_acquired"):
        assert hook in extension_contract
    assert "absent providers leave it unchanged" in extension_contract
    assert "absent providers make no changes" in extension_contract
