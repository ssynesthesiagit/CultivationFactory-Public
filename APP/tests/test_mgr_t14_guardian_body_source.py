"""Guardian-Body source/build contracts; these do not certify combat delivery.

Use the shipped catalogue importer rather than manufacturing an eligible row.
The conditional ally-Guard trigger still needs an enabling Guardian source rule.
"""
import hashlib
import json
from pathlib import Path

from character_creation.creative_controller.linear_menus import _relation_satisfied


OWNER = "insight.guardian-body-adept"
SOURCE_SHA = "772e17a70cc985005e1221430c6f54ad476ecc735e8db234dc79620036314bbb"


def test_printed_guardian_body_record_is_exact():
    root = Path(__file__).resolve().parents[1]
    text = json.loads((root / "authority/typed_mechanics/rules_text.json").read_text())[OWNER]
    assert hashlib.sha256(text.encode()).hexdigest() == SOURCE_SHA


def test_imported_guardian_body_build_contract(catalog_environment):
    with catalog_environment["db"].connection() as conn:
        records = [json.loads(row[0]) for row in conn.execute(
            "SELECT data_json FROM catalog_records WHERE selected_authority=1"
        )]
    record = next(row for row in records if row["record_id"] == OWNER)
    authority = record["compatibility"]["factory"]["stage2_authority"]
    assert authority["minimum_cl"] == 4
    assert 3 not in authority["allowed_cls"] and 4 in authority["allowed_cls"]
    assert authority["allowed_kinds"] == ["cultivation_insight_acquisition"]
    assert authority["ability_change"]["allowed_abilities"] == ["CON", "WIS"]
    assert authority["ability_change"]["amount"] == 1
    assert authority["ability_change"]["selection_mode"] == "level_selection"
    assert authority["repeatability"]["maximum"] == 1
    prerequisites = authority["typed_prerequisites"]
    guardian = next(row for row in prerequisites if row.get("target_id") == "tianxia.sphere.guardian")
    assert _relation_satisfied(guardian, {"tianxia.sphere.guardian"})
    assert not _relation_satisfied(guardian, set())
