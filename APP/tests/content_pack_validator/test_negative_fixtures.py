from __future__ import annotations

from pathlib import Path

import pytest

from tools.content_pack_validator import validate_content_pack


@pytest.mark.parametrize(
    ("fixture", "expected_code"),
    [
        ("duplicate_record_ids", "RECORD_ID_DUPLICATE"),
        ("conflicting_versions", "RECORD_VERSION_CONFLICT"),
        ("missing_checksum_declaration", "CHECKSUM_PAYLOAD_UNDECLARED"),
        ("missing_checksum_manifest", "CHECKSUM_MANIFEST_MISSING"),
        ("bad_checksum", "CHECKSUM_MISMATCH"),
        ("undeclared_payload", "CHECKSUM_PAYLOAD_UNDECLARED"),
        ("dependency_cycle", "DEPENDENCY_CYCLE_SELF"),
        ("invalid_version_range", "DEPENDENCY_VERSION_RANGE_INVALID"),
        ("combat_claim_without_execution", "COMBAT_SUPPORT_WITHOUT_EXECUTION_DEFINITION"),
        ("ai_claim_combat_blocked", "AI_SUPPORT_WHILE_COMBAT_BLOCKED"),
        ("blocked_without_exact_blocker", "CAPABILITY_BLOCKER_IDENTITY_MISSING"),
        ("unknown_primitive", "PRIMITIVE_UNKNOWN"),
        ("creature_without_footprint", "CREATURE_FOOTPRINT_MISSING"),
        ("companion_without_owner", "COMPANION_OWNER_BINDING_MISSING"),
        ("executable_content", "EXECUTABLE_CONTENT_FILE"),
        ("malformed_json", "JSON_MALFORMED"),
    ],
)
def test_invalid_directory_fixtures_block(fixture_root: Path, options, fixture: str, expected_code: str) -> None:
    result = validate_content_pack(fixture_root / "invalid" / fixture, options)
    assert result.verdict == "BLOCKED"
    assert expected_code in {row.code for row in result.diagnostics}
    assert result.input_preserved is True


@pytest.mark.parametrize(
    ("fixture", "expected_code"),
    [
        ("path_traversal.zip", "ZIP_UNSAFE_PATH"),
        ("casefold_collision.zip", "ARCHIVE_CASEFOLD_COLLISION"),
        ("unicode_normalization_collision.zip", "ARCHIVE_UNICODE_NORMALIZATION_COLLISION"),
    ],
)
def test_invalid_zip_fixtures_block(fixture_root: Path, options, fixture: str, expected_code: str) -> None:
    path = fixture_root / "invalid_zips" / fixture
    before = path.read_bytes()
    result = validate_content_pack(path, options)
    assert result.verdict == "BLOCKED"
    assert expected_code in {row.code for row in result.diagnostics}
    assert path.read_bytes() == before


def test_malformed_checksum_row_blocks(copied_valid_pack: Path, options) -> None:
    sums = copied_valid_pack / "SHA256SUMS.txt"
    sums.write_text("not a checksum row\n" + sums.read_text(encoding="utf-8"), encoding="utf-8")
    result = validate_content_pack(copied_valid_pack, options)
    assert "CHECKSUM_ROW_MALFORMED" in {row.code for row in result.diagnostics}
