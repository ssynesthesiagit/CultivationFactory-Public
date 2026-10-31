from __future__ import annotations

import json
from pathlib import Path
import time

from jsonschema import Draft202012Validator

from tools.content_pack_validator import validate_content_pack
from conftest import load_json, rebuild_checksums, write_json


def test_candidate_schemas_are_valid_and_non_authoritative(overlay_root: Path) -> None:
    root = overlay_root / "schemas" / "content_pack_candidate"
    schemas = sorted(root.glob("*.json"))
    assert schemas
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        text = path.read_text(encoding="utf-8")
        assert "CANDIDATE_NON_AUTHORITATIVE" in text


def test_dynamic_runtime_reference_is_rejected(copied_valid_pack: Path, options) -> None:
    path = copied_valid_pack / "records" / "definitions.json"
    document = load_json(path)
    document["records"][0]["runtime_module"] = "python:malicious.module"
    write_json(path, document)
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    codes = {row.code for row in result.diagnostics}
    assert "ARBITRARY_RUNTIME_REFERENCE" in codes
    assert "ARBITRARY_RUNTIME_INSTRUCTION" in codes


def test_macro_enabled_file_is_rejected(copied_valid_pack: Path, options) -> None:
    (copied_valid_pack / "payload.docm").write_bytes(b"not executed")
    manifest_path = copied_valid_pack / "pack.json"
    manifest = load_json(manifest_path)
    manifest["optional_files"].append("payload.docm")
    write_json(manifest_path, manifest)
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    assert "MACRO_ENABLED_FILE" in {row.code for row in result.diagnostics}


def test_unknown_checksum_covered_file_warns_but_does_not_crash(copied_valid_pack: Path, options) -> None:
    (copied_valid_pack / "unknown.dat").write_bytes(b"declarative opaque data\n")
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    assert result.verdict == "PASS"
    assert "UNKNOWN_OPTIONAL_FILE" in {row.code for row in result.diagnostics}


def test_strict_unknown_file_mode_blocks(copied_valid_pack: Path, registry_path: Path) -> None:
    from tools.content_pack_validator import ValidationOptions

    (copied_valid_pack / "unknown.dat").write_bytes(b"declarative opaque data\n")
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(
        copied_valid_pack,
        ValidationOptions(primitive_registry=registry_path, strict_unknown_files=True),
    )
    assert result.verdict == "BLOCKED"
    assert "UNKNOWN_OPTIONAL_FILE" in {row.code for row in result.diagnostics}


def test_large_reasonable_inventory_validates(copied_valid_pack: Path, options) -> None:
    records_path = copied_valid_pack / "records" / "definitions.json"
    records_doc = load_json(records_path)
    template = records_doc["records"][0]
    for index in range(1000):
        row = json.loads(json.dumps(template))
        row["record_id"] = f"tianxia.rule.bulk_{index}.fixture"
        row["display_name"] = f"Bulk Fixture {index}"
        row["capabilities"] = {
            "advancement": "NOT_APPLICABLE",
            "character_sheet": "SUPPORTED",
            "gm_display": "SUPPORTED",
            "combat_execution": "NOT_APPLICABLE",
            "ai_policy": "NOT_APPLICABLE",
        }
        records_doc["records"].append(row)
    write_json(records_path, records_doc)
    manifest_path = copied_valid_pack / "pack.json"
    manifest = load_json(manifest_path)
    for row in manifest["record_inventory"]:
        if row["path"] == "records/definitions.json":
            row["count"] = len(records_doc["records"])
    write_json(manifest_path, manifest)
    rebuild_checksums(copied_valid_pack)
    started = time.perf_counter()
    result = validate_content_pack(copied_valid_pack, options)
    elapsed = time.perf_counter() - started
    assert result.verdict == "PASS"
    assert result.artifacts.capability_matrix["record_count"] == 1002
    assert elapsed < 10.0


def test_unknown_document_schema_version_blocks(copied_valid_pack: Path, options) -> None:
    path = copied_valid_pack / "records" / "definitions.json"
    document = load_json(path)
    document["schema_version"] = "TianxiaContentPackCandidate.Definitions.v999"
    write_json(path, document)
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    assert "SCHEMA_VERSION_UNKNOWN" in {row.code for row in result.diagnostics}


def test_pack_local_source_hash_mismatch_blocks(copied_valid_pack: Path, options) -> None:
    (copied_valid_pack / "sources" / "authenticated_source.json").write_bytes(b"changed source bytes\n")
    rebuild_checksums(copied_valid_pack)
    result = validate_content_pack(copied_valid_pack, options)
    assert "SOURCE_PATH_HASH_MISMATCH" in {row.code for row in result.diagnostics}


def test_declared_environment_incompatibility_blocks(fixture_root: Path, registry_path: Path) -> None:
    from tools.content_pack_validator import ValidationOptions

    result = validate_content_pack(
        fixture_root / "valid" / "minimal_pack",
        ValidationOptions(
            primitive_registry=registry_path,
            factory_version="9.0.0",
            compiler_version="1.5.0",
            engine_version="1.5.0",
        ),
    )
    assert "COMPATIBILITY_VERSION_MISMATCH" in {row.code for row in result.diagnostics}
