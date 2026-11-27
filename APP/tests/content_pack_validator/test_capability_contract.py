from __future__ import annotations

import json
from pathlib import Path

from tools.content_pack_validator import validate_content_pack
from conftest import load_json, rebuild_checksums, write_json


def test_empty_execution_array_never_proves_combat(fixture_root: Path, options) -> None:
    result = validate_content_pack(fixture_root / "invalid" / "combat_claim_without_execution", options)
    assert "COMBAT_SUPPORT_WITHOUT_EXECUTION_DEFINITION" in {row.code for row in result.diagnostics}


def test_display_prose_does_not_prove_execution(copied_valid_pack: Path, options) -> None:
    path = copied_valid_pack / "records" / "definitions.json"
    document = load_json(path)
    talent = document["records"][1]
    talent["execution_definition_ids"] = []
    talent["display_representation"]["summary"] = "This prose describes a complete attack but remains display-only."
    write_json(path, document)
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    assert result.verdict == "BLOCKED"
    assert "COMBAT_SUPPORT_WITHOUT_EXECUTION_DEFINITION" in {row.code for row in result.diagnostics}


def test_incomplete_typed_action_blocks(copied_valid_pack: Path, options) -> None:
    path = copied_valid_pack / "execution" / "combat_definitions.json"
    document = load_json(path)
    document["definitions"][0]["typed_fields"].pop("target")
    write_json(path, document)
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    codes = {row.code for row in result.diagnostics}
    assert "EXECUTION_TYPED_FIELDS_MISSING" in codes
    assert "EXECUTION_DEFINITION_INCOMPLETE" in codes


def test_blocked_dependency_with_exact_primitive_is_accepted(copied_valid_pack: Path, options) -> None:
    path = copied_valid_pack / "records" / "definitions.json"
    document = load_json(path)
    talent = document["records"][1]
    talent["capabilities"]["combat_execution"] = "BLOCKED_BY_DEPENDENCY"
    talent["capability_blockers"] = [{"primitive_id": "combat.future.timeline", "capability": "combat_execution"}]
    talent.pop("execution_definition_ids", None)
    write_json(path, document)
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    assert "CAPABILITY_BLOCKER_IDENTITY_MISSING" not in {row.code for row in result.diagnostics}


def test_record_dependency_cycle_is_rejected(copied_valid_pack: Path, options) -> None:
    path = copied_valid_pack / "records" / "definitions.json"
    document = load_json(path)
    first, second = document["records"]
    first["record_dependencies"] = [{"record_id": second["record_id"], "capability": "advancement"}]
    second["record_dependencies"] = [{"record_id": first["record_id"], "capability": "advancement"}]
    write_json(path, document)
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    assert "CAPABILITY_DEPENDENCY_CYCLE" in {row.code for row in result.diagnostics}
