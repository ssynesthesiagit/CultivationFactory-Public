from __future__ import annotations

from pathlib import Path

from tools.content_pack_validator import ValidationOptions, validate_content_pack
from conftest import load_json, rebuild_checksums, write_json


def test_registry_is_required_when_primitives_are_referenced(fixture_root: Path) -> None:
    result = validate_content_pack(fixture_root / "valid" / "minimal_pack", ValidationOptions())
    assert result.verdict == "BLOCKED"
    assert "PRIMITIVE_REGISTRY_REQUIRED" in {row.code for row in result.diagnostics}


def test_unknown_primitive_produces_typed_report(fixture_root: Path, options) -> None:
    result = validate_content_pack(fixture_root / "invalid" / "unknown_primitive", options)
    report = result.artifacts.unsupported_primitives
    assert report["unsupported_reference_count"] == 1
    assert report["references"][0]["primitive_id"] == "combat.unknown.fixture"


def test_creature_requires_policy_reference(copied_valid_pack: Path, options) -> None:
    path = copied_valid_pack / "creatures" / "creature_definitions.json"
    document = load_json(path)
    document["creatures"][0]["controller_policy_ref"] = "tianxia.policy.missing.fixture"
    write_json(path, document)
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    assert "CREATURE_POLICY_REFERENCE_MISSING" in {row.code for row in result.diagnostics}


def test_creature_requires_execution_reference(copied_valid_pack: Path, options) -> None:
    path = copied_valid_pack / "creatures" / "creature_definitions.json"
    document = load_json(path)
    document["creatures"][0]["typed_actions"] = ["tianxia.execution.missing.fixture"]
    write_json(path, document)
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    assert "CREATURE_EXECUTION_REFERENCE_MISSING" in {row.code for row in result.diagnostics}


def test_companion_owner_binding_and_typed_relationship_pass(fixture_root: Path, options) -> None:
    result = validate_content_pack(fixture_root / "valid" / "minimal_pack", options)
    codes = {row.code for row in result.diagnostics}
    assert "COMPANION_OWNER_BINDING_MISSING" not in codes
    assert result.verdict == "PASS"
