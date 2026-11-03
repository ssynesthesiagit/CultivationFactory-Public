from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


STRUCTURAL_FALSE_RECORDS = {
    ("Beauty", "Cultivation Insights"),
    ("Equipment", "Armor Traditions"),
    ("Source", "Source Traditions"),
    ("Weapons", "Weapon Catalogue"),
    ("Weapons", "Path Expression Notes"),
    ("Weapons", "Character Sheet Notes"),
}
INLINE_BOUNDARY_FIXTURES = {
    ("Athletics", "Flowing Pursuit"),
    ("Barrage", "Needle-Rain Burst"),
    ("Barrage", "Heaven-Splitting Line"),
    ("Beastmastery", "Beastback Relay"),
    ("Blood", "Heartblood Rebirth"),
    ("Dreams", "Symbolic Shelter"),
    ("Protection", "Community"),
}
REALM_FIXTURES = {
    ("Equipment", "Black Armor Legion Scripture"): (5, "Foundation"),
    ("Source", "Source-Heaven Scripture"): (5, "Foundation"),
    ("Source", "Source-Heaven Sealing Scripture"): (10, "Core Formation"),
    ("Equipment", "Ancestral Battle Dress Scripture"): (15, "Nascent Soul"),
    ("Ice", "The World Becomes a Single Crystal"): (15, "Nascent Soul"),
}
FALSE_FORBIDDEN_FIXTURES = {
    ("Harvesting Gathering", "Formation-Ward Harvest"),
    ("Hunger", "Hunger-Sense Meridian"),
    ("Sect Stewardship", "Inner Archive Index"),
    ("Talismans", "Heavenly Seal"),
    ("Unmaking", "Devouring Dregs"),
    ("Spear", "Spear Pressure"),
}


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def committed(row: dict[str, Any]) -> bool:
    payload = {key: value for key, value in row.items() if key != "record_commitment_sha256"}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest() == row.get("record_commitment_sha256")


def validate(source_root: Path) -> dict[str, Any]:
    path = source_root / "catalog_authority" / "cat3" / "generated" / "catalog_authority.v1.json"
    authority = json.loads(path.read_text(encoding="utf-8"))
    body = {key: value for key, value in authority.items() if key != "registry_commitment_sha256"}
    assert hashlib.sha256(canonical_bytes(body)).hexdigest() == authority["registry_commitment_sha256"]
    spheres = authority["spheres"]
    talents = authority["talents"]
    memberships = authority["memberships"]
    assert len(spheres) == len({row["canonical_sphere_id"] for row in spheres}) == 85
    assert len(talents) == len({row["canonical_talent_id"] for row in talents})
    assert len(memberships) == len(talents)
    assert {row["canonical_talent_id"] for row in memberships} == {row["canonical_talent_id"] for row in talents}
    committed_groups = (
        spheres, talents, authority["sphere_aliases_and_noncanonical_labels"],
        authority["automatic_base_abilities"], authority["automatic_base_ability_aliases"],
        authority["background_only_routes"], authority["quarantined_decision_packets"],
        authority["legacy_non_talent_findings"],
    )
    assert all(committed(row) for group in committed_groups for row in group)

    by_key = {(row["owning_canonical_sphere_name"], row["display_name"]): row for row in talents}
    assert not (STRUCTURAL_FALSE_RECORDS & set(by_key))
    assert INLINE_BOUNDARY_FIXTURES <= set(by_key)
    for key in INLINE_BOUNDARY_FIXTURES:
        assert not re.search(r"(?m)^#{1,6}\s|\s#{1,6}\s", by_key[key]["full_description"]), key
    assert not any(re.search(r"(?m)^#{1,6}\s|\s#{1,6}\s", row["full_description"]) for row in talents)

    for key, (minimum_cl, realm) in REALM_FIXTURES.items():
        row = by_key[key]
        assert row["minimum_cl"] == minimum_cl
        assert row["realm_band"] == realm
    flowing = by_key[("Athletics", "Flowing Pursuit")]
    assert flowing["minimum_cl"] == 7 and flowing["realm_band"] == "Foundation"

    for key in FALSE_FORBIDDEN_FIXTURES:
        assert by_key[key]["access_category"] == "Open", key
    for row in talents:
        assert row["source_provenance"]["source_path"]
        assert row["source_provenance"]["source_line"] >= 1
        assert row["source_provenance"]["source_column"] >= 1
        assert row["source_provenance"]["source_context_sha256"]
        assert row["full_exact_source_text"].startswith("#")
        assert row["realm_band"] in {"Mortal", "Foundation", "Core Formation", "Nascent Soul", "Immortal"}
        assert isinstance(row["minimum_cl"], int) and row["minimum_cl"] >= 1
        assert row["prerequisite_evaluation_status"] in {
            "TYPED", "TYPED_ACQUISITION_USE_CONDITION_UNRESOLVED", "UNRESOLVED_FAIL_CLOSED"
        }
        if row["raw_prerequisite_text"]:
            assert row["prerequisite_clauses"]
            assert all(clause["alternatives"] for clause in row["prerequisite_clauses"])
            referenced = {
                predicate_id
                for clause in row["prerequisite_clauses"]
                for alternative in clause["alternatives"]
                for predicate_id in alternative["predicate_ids"]
            }
            typed_ids = {predicate["predicate_id"] for predicate in row["typed_prerequisites"]}
            assert referenced <= typed_ids
        unresolved_acquisition = any(
            predicate["kind"] == "unresolved"
            and predicate["scope"] == "acquisition"
            and predicate["resolution_status"] == "unresolved"
            for predicate in row["typed_prerequisites"]
        )
        assert row["creator_selectability_can_be_evaluated_safely"] is (not unresolved_acquisition)
        if unresolved_acquisition:
            assert row["prerequisite_evaluation_status"] == "UNRESOLVED_FAIL_CLOSED"
            assert row["unresolved_reason"]
        explicit_values = [item["value"] for item in row["access_classification_evidence"]]
        if row["access_category"] != "Open":
            assert explicit_values

    base_rows = authority["automatic_base_abilities"]
    runtime_components = {row["runtime_component_id"] for row in base_rows}
    assert len(base_rows) == 132
    assert len(runtime_components) == 131
    aliases = authority["automatic_base_ability_aliases"]
    assert len(aliases) == 1
    assert aliases[0]["legacy_id"] == "TAL_DARK_DARKNESS"
    assert aliases[0]["canonical_component_id"] == "DARK_BASE_DARKNESS"

    for migration in authority["stable_id_migrations"]:
        evidence = migration["evidence"]
        assert evidence.get("source_pack")
        assert evidence.get("source_path")
        assert evidence.get("source_file_sha256")
        if migration.get("record_type") == "talent":
            assert evidence.get("source_anchor")
            assert evidence.get("source_context_sha256")
            assert evidence.get("owning_sphere")
            assert evidence.get("canonical_record_commitment_sha256")

    labels = {row["label"]: row for row in authority["sphere_aliases_and_noncanonical_labels"]}
    assert labels["Fencing"]["canonical_sphere_name"] == "The Piercing Needle"
    assert labels["Harvesting-Gathering"]["canonical_sphere_name"] == "Harvesting Gathering"
    harvesting = next(row for row in spheres if row["display_name"] == "Harvesting Gathering")
    assert "Harvesting and Gathering" in harvesting["aliases"]
    legacy_findings = authority["legacy_non_talent_findings"]
    assert len(legacy_findings) == authority["counts"]["legacy_non_talent_compatibility_records"]
    assert len(legacy_findings) == len({row["record_id"] for row in legacy_findings})
    assert "TAL_SPACE_BODY_REFINING" in {row["record_id"] for row in legacy_findings}

    by_sphere: dict[str, list[dict[str, Any]]] = {}
    for row in talents:
        if row["ordinary_talent"]:
            by_sphere.setdefault(row["owning_canonical_sphere_name"], []).append(row)
    old = json.loads((source_root / "catalog" / "sphere_talent_authority_v1.json").read_text(encoding="utf-8"))
    canonical_names = {row["display_name"] for row in spheres}
    formerly_empty = sorted(
        name for name in canonical_names
        if not (old["sphere_coverage"].get("Fencing" if name == "The Piercing Needle" else name, {}).get("selectable_talent_ids") or [])
    )
    assert len(formerly_empty) == 25
    assert all(by_sphere.get(name) for name in formerly_empty)

    return {
        "result": "PASS",
        "registry_commitment_sha256": authority["registry_commitment_sha256"],
        "counts": authority["counts"],
        "formerly_empty_spheres_restored": formerly_empty,
        "structural_false_records_removed": sorted([list(item) for item in STRUCTURAL_FALSE_RECORDS]),
        "inline_boundary_fixtures": sorted([list(item) for item in INLINE_BOUNDARY_FIXTURES]),
        "realm_fixtures": {" / ".join(key): {"minimum_cl": value[0], "realm": value[1]} for key, value in REALM_FIXTURES.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    args = parser.parse_args()
    print(json.dumps(validate(Path(args.source_root).resolve()), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
