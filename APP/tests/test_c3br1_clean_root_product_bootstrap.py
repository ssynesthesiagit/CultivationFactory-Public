from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import APP_STATUS, EXPECTED_FACTORY_HASH, Database, FoundryError, Settings, sha256_file
from portable_character.service import PortableCharacterPackageService
from product_bootstrap import ProductBootstrapService, ProductReadinessService

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
RUNTIME_PACKAGE = ROOT / "tests/fixtures/M1/C1A_Clean_Fire_Qi_Proof_Character_Combat_Runtime_Ready.zip"


def test_bundled_corpus_identity_and_idempotent_bootstrap(tmp_path):
    assert sha256_file(BUNDLED) == EXPECTED_FACTORY_HASH
    data = tmp_path / "owner data Ω with spaces"
    settings = Settings.from_env(ROOT, data)
    first = ProductBootstrapService(settings).run()
    marker = data / "owner-preserved.txt"
    marker.write_text("owner data", encoding="utf-8")
    second = ProductBootstrapService(settings).run()

    assert first["status"] == second["status"] == "CANONICAL_CATALOG_PRODUCT_INTEGRATION_READY"
    assert first["clean_root_bootstrap_lineage_status"] == second["clean_root_bootstrap_lineage_status"] == "CLEAN_ROOT_PRODUCT_BOOTSTRAP_READY"
    assert first["adapter_action"] == "CONFIGURED_FROM_VERIFIED_CORPUS"
    assert second["adapter_action"] == "PRESERVED_EXISTING_READY_CONFIGURATION"
    assert second["catalog_action"] == "PRESERVED_EXISTING_VALID_CATALOG"
    assert marker.read_text(encoding="utf-8") == "owner data"
    report = ProductReadinessService(Database(settings)).report()
    assert report["portable_import"]["ready"] is True
    assert report["producer_corpus"]["actual_sha256"] == EXPECTED_FACTORY_HASH
    assert report["catalog"]["record_count"] > 0
    assert report["catalog"]["installed_pack_count"] > 0


def test_missing_and_altered_corpus_fail_closed(tmp_path):
    product_root = tmp_path / "product without corpus"
    product_root.mkdir()
    missing = Settings.from_env(product_root, tmp_path / "missing data")
    with pytest.raises(FoundryError) as exc:
        ProductBootstrapService(missing).run()
    assert exc.value.code == "PRODUCT_BOOTSTRAP_CORPUS_INVALID"

    bad = tmp_path / "altered.zip"
    bad.write_bytes(b"not the authenticated corpus")
    altered = replace(Settings.from_env(ROOT, tmp_path / "altered data"), factory_zip=bad)
    with pytest.raises(FoundryError) as exc:
        ProductBootstrapService(altered).run()
    assert exc.value.code == "PRODUCT_BOOTSTRAP_CORPUS_INVALID"
    assert not (altered.data_dir / "portable_characters").exists()


def test_preview_combines_package_and_environment_readiness_without_import(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path / "blocked preview")
    db = Database(settings)
    db.migrate()
    service = PortableCharacterPackageService(db)
    with db.connection() as conn:
        before = {
            "projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "snapshots": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        }
    preview = service.preview_for_factory(RUNTIME_PACKAGE)
    with db.connection() as conn:
        after = {
            "projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "snapshots": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        }

    assert preview["package_valid"] is True
    assert preview["environment_ready"] is False
    assert preview["can_import"] is False
    assert preview["blocking_prerequisites"]
    assert "Import is blocked" in preview["owner_message"]
    assert before == after


def test_health_and_advanced_status_are_dependency_aware(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path / "healthy product")
    ProductBootstrapService(settings).run()
    client = TestClient(create_app(settings))
    try:
        health = client.get("/api/health").json()
        status = client.get("/api/system/status").json()
    finally:
        client.close()

    assert health["process_live"] is True
    assert health["status"] == "CANONICAL_CATALOG_PRODUCT_INTEGRATION_READY"
    assert health["clean_root_bootstrap_lineage_status"] == "CLEAN_ROOT_PRODUCT_BOOTSTRAP_READY"
    assert health["database_ready"] is True
    assert health["producer_corpus_ready"] is True
    assert health["factory_adapter_ready"] is True
    assert health["catalog_ready"] is True
    assert health["portable_import_ready"] is True
    assert health["native_windows_status"] == "NATIVE_WINDOWS_OWNER_ACCEPTANCE_DEFERRED"
    for key in ("build", "project_store", "producer_corpus", "factory_adapter", "catalog", "gm_consumer", "combat_runtime", "combatant_library", "native_windows", "recent_errors"):
        assert key in status


def test_blocked_health_is_live_but_does_not_claim_product_ready(tmp_path):
    missing_override = tmp_path / "missing producer corpus.zip"
    settings = replace(Settings.from_env(ROOT, tmp_path / "blocked health data"), factory_zip=missing_override)
    db = Database(settings)
    db.migrate()
    client = TestClient(create_app(settings))
    try:
        health = client.get("/api/health").json()
        status = client.get("/api/system/status").json()
    finally:
        client.close()

    assert health["ok"] is True
    assert health["process_live"] is True
    assert health["status"] == "CLEAN_ROOT_PRODUCT_BOOTSTRAP_BLOCKED"
    assert health["portable_import_ready"] is False
    assert health["producer_corpus_ready"] is False
    assert status["build"]["status"] == "CLEAN_ROOT_PRODUCT_BOOTSTRAP_BLOCKED"
    assert status["packaging"]["status"] == "CLEAN_ROOT_PRODUCT_BOOTSTRAP_BLOCKED"
    assert status["build"]["declared_checkpoint_status"] == APP_STATUS


def test_two_simultaneous_bootstrap_attempts_converge(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path / "simultaneous data")
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _: ProductBootstrapService(settings).run(), range(2)))
    assert all(report["status"] == "CANONICAL_CATALOG_PRODUCT_INTEGRATION_READY" for report in reports)
    assert all(report["clean_root_bootstrap_lineage_status"] == "CLEAN_ROOT_PRODUCT_BOOTSTRAP_READY" for report in reports)
    assert ProductReadinessService(Database(settings)).report()["portable_import"]["ready"] is True


def test_invalid_existing_adapter_is_preserved_and_blocks_rebootstrap(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path / "existing owner data")
    ProductBootstrapService(settings).run()
    config = settings.vendor_dir / "factory_adapter.json"
    document = json.loads(config.read_text(encoding="utf-8"))
    root = Path(document["factory_root"])
    entrypoint = root / "FACTORY_MANIFEST.json"
    backup = entrypoint.read_bytes()
    entrypoint.unlink()
    marker = settings.data_dir / "owner-marker.txt"
    marker.write_text("preserve", encoding="utf-8")
    try:
        with pytest.raises(FoundryError) as exc:
            ProductBootstrapService(settings).run()
        assert exc.value.code == "PRODUCT_BOOTSTRAP_EXISTING_FACTORY_INVALID"
        assert marker.read_text(encoding="utf-8") == "preserve"
        assert json.loads(config.read_text(encoding="utf-8")) == document
    finally:
        entrypoint.write_bytes(backup)


def test_interrupted_vendor_publish_fails_closed(tmp_path, monkeypatch):
    from vendor_adapter.service import FactoryAdapter

    settings = Settings.from_env(ROOT, tmp_path / "interrupted publish")
    marker = settings.data_dir / "owner-marker.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("preserve", encoding="utf-8")

    def interrupted(_staging: Path, _destination: Path, **_kwargs):
        raise OSError("simulated interrupted atomic publish")

    monkeypatch.setattr(FactoryAdapter, "_publish_extraction", staticmethod(interrupted))
    with pytest.raises(OSError, match="simulated interrupted"):
        ProductBootstrapService(settings).run()
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not (settings.vendor_dir / "factory_adapter.json").exists()
    report = ProductReadinessService(Database(settings)).report()
    assert report["portable_import"]["ready"] is False


def test_catalog_build_failure_preserves_data_and_blocks_import(tmp_path, monkeypatch):
    from catalog.service import CatalogService

    settings = Settings.from_env(ROOT, tmp_path / "catalog failure")
    marker = settings.data_dir / "owner-marker.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("preserve", encoding="utf-8")

    def fail_catalog(self, factory_root: Path):
        raise FoundryError("TEST_CATALOG_BUILD_FAILURE", "simulated catalog build failure")

    monkeypatch.setattr(CatalogService, "rebuild_core", fail_catalog)
    with pytest.raises(FoundryError) as exc:
        ProductBootstrapService(settings).run()
    assert exc.value.code == "TEST_CATALOG_BUILD_FAILURE"
    assert marker.read_text(encoding="utf-8") == "preserve"
    report = ProductReadinessService(Database(settings)).report()
    assert report["factory_adapter"]["health"] == "READY"
    assert report["portable_import"]["ready"] is False
    preview = PortableCharacterPackageService(Database(settings)).preview_for_factory(RUNTIME_PACKAGE)
    assert preview["package_valid"] is True
    assert preview["can_import"] is False
    assert any(item["code"] == "PRODUCT_CORE_CATALOG_NOT_READY" for item in preview["blocking_prerequisites"])
