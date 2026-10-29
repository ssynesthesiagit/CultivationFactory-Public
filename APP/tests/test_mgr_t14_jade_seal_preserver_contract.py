"""Source/build contract audit; these checks do not certify Lot transactions."""

import hashlib
import json
from pathlib import Path

import pytest

from character_creation.creative_controller.linear_menus import _relation_satisfied


APP = Path(__file__).resolve().parents[1]
OWNER = "insight.jade-seal-preserver"
SPHERE = "tianxia.sphere.harvesting_gathering"
WAX = "tianxia.talent.harvesting_gathering.spirit_sealing_wax"
SOURCE_SHA = "873ded7b0d7531687dc97a5be3de6f221e0894c2e450d4bb50d0d5b28d2bff33"


def _catalog_row():
    catalog = json.loads((APP / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text())
    return next(row for row in catalog["insights"] if row["canonical_insight_id"] == OWNER)


def test_complete_source_and_native_catalog_build_contract():
    text = json.loads((APP / "authority/typed_mechanics/rules_text.json").read_text())[OWNER]
    assert hashlib.sha256(text.encode()).hexdigest() == SOURCE_SHA
    mechanic = json.loads((APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"][OWNER]
    assert mechanic["source"]["text_sha256"] == SOURCE_SHA
    row = _catalog_row()
    raw = row["raw_source_record"]
    assert raw["full_rules_text"] == text
    assert raw["minimum_cl"] == raw["minimum_cl_level_selection"] == 8
    assert raw["ability_options"] == ["Wisdom", "Intelligence", "Constitution"]
    assert row["owning_canonical_sphere_id"] == SPHERE
    assert row["selectable"] is True
    assert {(r["kind"], r["operator"], r["target_id"]) for r in row["prerequisites"]} == {
        ("sphere", "requires", SPHERE), ("talent", "requires", WAX)
    }


@pytest.mark.parametrize("present, eligible", [
    (set(), False), ({SPHERE}, False), ({WAX}, False), ({SPHERE, WAX}, True),
])
def test_native_relation_consumer_requires_both_printed_prerequisites(present, eligible):
    # Level and Realm cap belong to the acquisition menu, not this relation API.
    assert all(_relation_satisfied(r, present) for r in _catalog_row()["prerequisites"]) is eligible
