from __future__ import annotations

from pathlib import Path

from tools.content_pack_validator import validate_content_pack
from tools.content_pack_validator.constants import REPORT_FILENAMES


def test_valid_directory_passes(fixture_root: Path, options) -> None:
    result = validate_content_pack(fixture_root / "valid" / "minimal_pack", options)
    assert result.verdict == "PASS"
    assert result.input_preserved is True
    assert result.artifacts.verdict["runtime_integration_claim"] == "NONE"
    assert result.artifacts.validation_report["scope_declaration"]["candidate_non_authoritative"] is True


def test_valid_zip_passes(fixture_root: Path, options) -> None:
    result = validate_content_pack(fixture_root / "valid" / "minimal_pack.zip", options)
    assert result.verdict == "PASS"
    assert result.input_kind == "zip"
    assert result.artifacts.checksum_inventory["exact_coverage"] is True


def test_optional_checksum_covered_file_passes(fixture_root: Path, options) -> None:
    result = validate_content_pack(fixture_root / "valid" / "optional_file_pack", options)
    assert result.verdict == "PASS"
    assert not [row for row in result.diagnostics if row.code == "UNKNOWN_OPTIONAL_FILE"]


def test_required_report_set_is_exact(fixture_root: Path, options) -> None:
    result = validate_content_pack(fixture_root / "valid" / "minimal_pack", options)
    assert tuple(sorted(result.artifacts.machine_files())) == tuple(sorted(REPORT_FILENAMES))


def test_valid_fixture_contains_requested_record_classes(fixture_root: Path, options) -> None:
    result = validate_content_pack(fixture_root / "valid" / "minimal_pack", options)
    matrix = result.artifacts.capability_matrix
    ids = {row["record_id"] for row in matrix["records"]}
    assert "tianxia.sphere.fire.fixture" in ids
    assert "tianxia.talent.fire.flame_lash.fixture" in ids
    graph_nodes = {row["node_id"] for row in result.artifacts.dependency_graph["nodes"]}
    assert "pack:tianxia.core.primitives" in graph_nodes
    source_kinds = {row["owner_kind"] for row in result.artifacts.source_binding_report["bindings"]}
    assert {"pack", "record", "execution_definition", "controller_policy", "creature_or_companion"} <= source_kinds
