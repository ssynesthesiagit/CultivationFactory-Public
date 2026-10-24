"""CAICLANLOCK1: the catalog inventory hash covers exactly what the importer reads.

The importer's declared input list (CoreCatalogImporter.declared_inputs) is the single
source of truth for catalog_inventory_hash. These tests fail if the importer opens a
data file the list does not declare, and if a previously omitted file changing no longer
marks the catalog out of sync.
"""
import builtins
import os
from pathlib import Path

import pytest

from app.core import Database, Settings
from catalog.service import CatalogService, CoreCatalogImporter
from product_bootstrap import ProductBootstrapService
from vendor_adapter.service import FactoryAdapter

ROOT = Path(__file__).resolve().parents[1]
DATA_SUFFIXES = (".json", ".md", ".csv", ".txt")


@pytest.fixture
def startup_settings(tmp_path):
    return Settings.from_env(ROOT, tmp_path / "owner data with spaces")


def _factory_root(db):
    return Path(FactoryAdapter(db).status()["factory_root"])


def test_importer_opens_no_data_file_outside_declared_inputs(startup_settings, monkeypatch):
    ProductBootstrapService(startup_settings).run()
    db = Database(startup_settings)
    factory_root = _factory_root(db)
    importer = CoreCatalogImporter(factory_root, owner_root=startup_settings.root_dir)
    declared = {path.resolve() for path in importer.declared_inputs()}

    opened: set[Path] = set()
    real_open = builtins.open
    real_path_open = Path.open

    def note(target):
        try:
            opened.add(Path(os.fspath(target)).resolve())
        except TypeError:
            pass

    def traced_open(file, *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)):
            note(file)
        return real_open(file, *args, **kwargs)

    def traced_path_open(self, *args, **kwargs):
        note(self)
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", traced_open)
    monkeypatch.setattr(Path, "open", traced_path_open)
    list(importer.iter_records())
    list(importer.iter_background_records())
    importer.owner_subpath_supplements()
    importer.catalog_inventory_hash()
    monkeypatch.undo()

    data_roots = (factory_root.resolve(), (ROOT / "catalog").resolve(),
                  (ROOT / "catalog_authority").resolve(), (ROOT / "character_creation").resolve(),
                  (ROOT / "non_sphere_authority").resolve())
    data_reads = {
        path for path in opened
        if path.suffix in DATA_SUFFIXES and any(path.is_relative_to(base) for base in data_roots)
    }
    # Guard against a vacuous pass: the importer really does read data from both trees.
    assert any(path.is_relative_to(factory_root.resolve()) for path in data_reads)
    assert any(path.is_relative_to((ROOT / "catalog_authority").resolve()) for path in data_reads)
    undeclared = sorted(str(path) for path in data_reads - declared)
    assert not undeclared, f"importer reads files outside the declared inventory: {undeclared}"


def test_omitted_source_drift_marks_catalog_out_of_sync_then_rebuild_restores(startup_settings):
    ProductBootstrapService(startup_settings).run()
    db = Database(startup_settings)
    catalog = CatalogService(db)
    assert catalog.sync_status(_factory_root(db))["in_sync"] is True

    # TreasureSetCatalog_R2.json was read by the importer but previously outside the hash.
    treasure = _factory_root(db) / "09_RULES/Items/TreasureSetCatalog_R2.json"
    original = treasure.read_bytes()
    treasure.write_bytes(original + b"\n")
    try:
        drifted = catalog.sync_status(_factory_root(db))
        assert drifted["in_sync"] is False
        assert drifted["current_inventory_hash"] != drifted["stored_inventory_hash"]
        # Core records carry this file's bytes, so the pinned core pack reports a version
        # conflict instead of silently rebuilding; boot still continues.
        assert ProductBootstrapService(startup_settings).run()["catalog_action"] == "STALE_CATALOG_NEEDS_CORE_VERSION"
        assert catalog.sync_status(_factory_root(db))["in_sync"] is False
    finally:
        treasure.write_bytes(original)

    # Shipped bytes restored: the stored build matches the sources again.
    assert catalog.sync_status(_factory_root(db))["in_sync"] is True
    assert ProductBootstrapService(startup_settings).run()["catalog_action"] == "PRESERVED_EXISTING_VALID_CATALOG"
    assert catalog.sync_status(_factory_root(db))["in_sync"] is True
