from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import character_creation.production_release as release_module
import character_creation.service as service_module
from app.core import sha256_file
from character_creation.production_release import CharacterProductionReleaseAdapter
from character_creation.service import CharacterCreationExecutionService


def test_clean_import_proof_timings_are_private_numeric_and_result_neutral(tmp_path, monkeypatch) -> None:
    project_id = "project-clean-import-timing"
    package = tmp_path / "character.zip"
    package.write_bytes(b"deterministic package bytes")
    package_sha256 = sha256_file(package)
    factory_root = tmp_path / "factory"
    factory_root.mkdir()
    source_data = tmp_path / "source-data"
    source_data.mkdir()

    adapter = object.__new__(CharacterProductionReleaseAdapter)
    adapter.db = SimpleNamespace(
        settings=SimpleNamespace(
            root_dir=tmp_path / "source-root",
            data_dir=source_data,
            db_path=source_data / "source.sqlite",
        )
    )

    audit = {"sha256": package_sha256}
    producer_command5 = {
        "model_sha256": "producer-model-bytes",
        "view_sha256": "producer-view-bytes",
        "view_semantic_hash": "source-view-semantic",
        "combat_evidence": {},
    }
    package_model = {
        "source_conversion": {
            "schema_version": "TianxiaFoundry.SourceModelConversion.v1",
            "command5_model_sha256": "producer-model-bytes",
            "command5_view_model_sha256": "producer-view-bytes",
            "package_source_model_sha256": "package-source-model-bytes",
            "package_source_view_sha256": "package-source-view-bytes",
        },
        "source_model_sha256": "package-source-model-bytes",
        "source_view_sha256": "package-source-view-bytes",
        "source_view_semantic_hash": "source-view-semantic",
        "model_semantic_hash": "model-semantic",
        "view_semantic_hash": "package-view-semantic",
        "source_model_semantic_hash": "source-model-semantic",
        "model_current_cl": 1,
        "model_paths": [],
    }

    class _Settings:
        @staticmethod
        def from_env(root_dir, data_dir):
            return SimpleNamespace(
                root_dir=Path(root_dir),
                data_dir=Path(data_dir),
                db_path=Path(data_dir) / "clean.sqlite",
            )

    class _Database:
        def __init__(self, settings):
            self.settings = settings

        def migrate(self):
            return {"status": "MIGRATED"}

    class _FactoryAdapter:
        def __init__(self, _db):
            pass

        def status(self):
            return {"factory_root": str(factory_root), "health": "READY"}

    class _CatalogService:
        def __init__(self, _db):
            pass

        def rebuild_core(self, _factory_root):
            return {"status": "REBUILT"}

    class _PortableService:
        import_calls = 0

        def __init__(self, _db):
            pass

        def _import_into_factory(self, _package, **_kwargs):
            type(self).import_calls += 1
            if type(self).import_calls % 2 == 1:
                return {"status": "IMPORTED", "package_path": str(package)}
            return {"status": "ALREADY_INSTALLED_IDENTICAL"}

        def audit(self, _path):
            return deepcopy(audit)

    class _ProjectStore:
        def __init__(self, _db):
            pass

        def get_project(self, requested_project_id):
            return {"project": {"project_id": requested_project_id, "revision": 1}}

    class _CharacterSheetService:
        def __init__(self, _db):
            pass

        def sheet(self, _project_id):
            return {
                "project_id": project_id,
                "build_status": "CHARACTER_SHEET_READY",
            }

    monkeypatch.setattr(release_module, "Settings", _Settings)
    monkeypatch.setattr(release_module, "Database", _Database)
    monkeypatch.setattr(release_module, "FactoryAdapter", _FactoryAdapter)
    monkeypatch.setattr(release_module, "CatalogService", _CatalogService)
    monkeypatch.setattr(release_module, "PortableCharacterPackageService", _PortableService)
    monkeypatch.setattr(release_module, "ProjectStore", _ProjectStore)
    monkeypatch.setattr(release_module, "CharacterSheetService", _CharacterSheetService)
    # The retained-pack carry-over reads the producer database; this stubbed
    # proof has none, and its own behaviour is covered by
    # test_clean_import_retained_packs.py.
    monkeypatch.setattr(release_module, "carry_over_retained_pack_locks", lambda _source, _clean, _project_id: [])
    adapter.portable = _PortableService(None)
    adapter._character_sheet_semantic_hash = lambda _sheet, *, expected_gm_screen=None: "sheet-semantic"
    adapter._package_model_proof = lambda _path: deepcopy(package_model)
    adapter._combat_raw = lambda _value: {}
    adapter._layer_combat_execution_status = lambda _raw, *, layer: {
        "valid": True,
        "report_combat_execution": "READY",
        "statuses": {"manifest": "READY", "readiness": "READY"},
    }
    adapter._combat_semantics = lambda _raw: {
        field: [True] for field in release_module._COMBAT_REQUIRED_FIELDS
    }
    adapter._combat_fields_equal = lambda _left, _right, *, fields=release_module._COMBAT_REQUIRED_FIELDS: True
    adapter._combat_no_false_ready_claim = lambda _layers, _profile: True

    expected_keys = {
        "production_release.clean_import.producer_sheet_semantic_hash",
        "production_release.clean_import.clean_root_prepare_copy",
        "production_release.clean_import.clean_db_migrate_vendor_status",
        "production_release.clean_import.catalog_rebuild",
        "production_release.clean_import.retained_pack_carry_over",
        "production_release.clean_import.first_package_import",
        "production_release.clean_import.reopen_migrate_project_sheet",
        "production_release.clean_import.identical_second_import",
        "production_release.clean_import.installed_package_hash_audit_model_proof",
        "production_release.clean_import.semantic_combat_equality_checks",
    }

    timings: dict[str, object] = {}
    _PortableService.import_calls = 0
    result = adapter._clean_import_proof(
        project_id,
        package,
        producer_sheet={},
        producer_command5=producer_command5,
        producer_output_profile=None,
        package_model=package_model,
        consumer={},
        audit=audit,
        clean_import_root=tmp_path / "clean-root",
        _timing_sink=timings,
    )

    assert set(timings) == expected_keys
    assert len(timings) == 10
    assert all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in timings.values())
    assert all(
        not any(token in key.casefold() for token in ("path", "payload", "credential", "header", "secret"))
        for key in timings
    )
    filtered = service_module._compile_timing_receipt(
        {**timings, "unallowlisted": 99, "production_release.clean_import.path": 1}
    )
    assert set(filtered["phases_ms"]) == expected_keys
    def _mapping_keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield str(key)
                yield from _mapping_keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from _mapping_keys(child)

    assert not any("timing" in key.casefold() for key in _mapping_keys(result))
    assert result["first"]["status"] == "IMPORTED"
    assert result["second"]["status"] == "ALREADY_INSTALLED_IDENTICAL"

    # Timing is outside the result and the operation may be repeated with a
    # fresh sink without changing any proof output.
    second_timings: dict[str, object] = {}
    _PortableService.import_calls = 0
    second_result = adapter._clean_import_proof(
        project_id,
        package,
        producer_sheet={},
        producer_command5=producer_command5,
        producer_output_profile=None,
        package_model=package_model,
        consumer={},
        audit=audit,
        clean_import_root=tmp_path / "clean-root",
        _timing_sink=second_timings,
    )
    assert result == second_result
    assert set(second_timings) == expected_keys
