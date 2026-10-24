"""CAICLANLOCK1: the catalog matches the sources the code ships, at every startup.

Startup (ProductBootstrapService._ensure_catalog) keeps a valid catalog only when its
stored source inventory hash matches the current sources (core, background and owner
Subpath packs). Any drift runs the one full rebuild path. Existing projects keep their
pinned pack locks. All tests use a fresh database under tmp_path.
"""
import json
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings
from catalog.service import CatalogService, CoreCatalogImporter
from character_builder.service import CharacterBuilderService
from product_bootstrap import ProductBootstrapService
from stage1.service import Stage1ClipboardService
from vendor_adapter.service import FactoryAdapter

ROOT = Path(__file__).resolve().parents[1]
OWNER_DIR = ROOT / "non_sphere_authority/authority/owner_subpaths.d"
CAI_SUBPATH = "tianxia.subpath.qi.cai_clan_empyreal_administrator"
CAI_PACK = "tianxia.owner.subpaths.cai_clan"
QI_PATH = "tianxia.path.qi_cultivation"


def _owner_documents():
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(OWNER_DIR.glob("*.json"))]


@pytest.fixture
def startup_settings(tmp_path):
    return Settings.from_env(ROOT, tmp_path / "owner data with spaces")


def _factory_root(db):
    return Path(FactoryAdapter(db).status()["factory_root"])


def _owner_pack_records(db, document):
    with db.connection() as conn:
        return {
            row["record_id"]
            for row in conn.execute(
                "SELECT record_id FROM catalog_records WHERE pack_id=? AND pack_version=? AND content_type='subpath'",
                (document["pack_id"], document["pack_version"]),
            ).fetchall()
        }


def test_stale_catalog_built_before_owner_packs_gains_them_on_next_startup(startup_settings, monkeypatch):
    # Build the catalog the way it was built before owner packs shipped: its stored
    # inventory hash describes the sources without the owner Subpath packs.
    real_hash = CoreCatalogImporter.catalog_inventory_hash
    monkeypatch.setattr(CoreCatalogImporter, "catalog_inventory_hash", lambda self: "pre-owner-sources")
    monkeypatch.setattr(CatalogService, "_rebuild_owner_subpaths", lambda self, importer, root: [])
    ProductBootstrapService(startup_settings).run()
    monkeypatch.undo()

    # Next startup: stored hash differs from the shipped sources, so the full rebuild runs.
    second = ProductBootstrapService(startup_settings).run()
    assert second["catalog_action"] == "REBUILT_STALE_CATALOG"

    db = Database(startup_settings)
    documents = _owner_documents()
    assert documents, "owner_subpaths.d must ship at least one pack"
    for document in documents:
        expected = {row["canonical_id"] for row in document["entries"]}
        assert expected <= _owner_pack_records(db, document), document["pack_id"]
        with db.connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM content_packs WHERE pack_id=? AND version=?",
                (document["pack_id"], document["pack_version"]),
            ).fetchone()[0] == 1


def test_valid_catalog_with_unchanged_sources_is_not_rebuilt(startup_settings, monkeypatch):
    ProductBootstrapService(startup_settings).run()

    def no_rebuild(self, factory_root):
        raise AssertionError("a valid catalog with unchanged sources must not rebuild")

    monkeypatch.setattr(CatalogService, "rebuild_core", no_rebuild)
    second = ProductBootstrapService(startup_settings).run()
    assert second["catalog_action"] == "PRESERVED_EXISTING_VALID_CATALOG"


def test_stored_inventory_hash_and_sync_status_report_match(startup_settings, monkeypatch):
    ProductBootstrapService(startup_settings).run()
    db = Database(startup_settings)
    catalog = CatalogService(db)
    sync = catalog.sync_status(_factory_root(db))
    assert sync["in_sync"] is True
    assert sync["stored_inventory_hash"] == sync["current_inventory_hash"]
    assert sync["stored_inventory_hash"] == catalog.status()["latest_build"]["inventory_hash"]

    # A source change the running code ships makes the catalog out of sync.
    monkeypatch.setattr(CoreCatalogImporter, "catalog_inventory_hash", lambda self: "changed-sources")
    drifted = catalog.sync_status(_factory_root(db))
    assert drifted["in_sync"] is False
    assert drifted["current_inventory_hash"] == "changed-sources"


def test_core_version_conflict_on_stale_catalog_keeps_app_bootable(startup_settings, monkeypatch):
    ProductBootstrapService(startup_settings).run()

    def conflict(self, factory_root):
        raise FoundryError("CORE_PACK_VERSION_HASH_CONFLICT", "bound to different bytes", details={})

    monkeypatch.setattr(CoreCatalogImporter, "catalog_inventory_hash", lambda self: "changed-sources")
    monkeypatch.setattr(CatalogService, "rebuild_core", conflict)
    result = ProductBootstrapService(startup_settings).run()
    assert result["catalog_action"] == "STALE_CATALOG_NEEDS_CORE_VERSION"


def test_new_project_offers_and_locks_owner_authored_subpath(startup_settings):
    ProductBootstrapService(startup_settings).run()
    db = Database(startup_settings)

    project = CharacterBuilderService(db).create_project(
        working_name="CAICLANLOCK1 regression", concept="Colorless-light retainer commander",
        power_band="rival/boss", source_reference=None, target_cl=5, creation_mode="detailed",
        ability_scores={}, selections={"path_choice": [QI_PATH], "subpath_choice": [CAI_SUBPATH]},
        autogen_seed="CAICLANLOCK1",
    )
    # build_envelope enforces the owner lock: a locked choice absent from the
    # slot's offered choices raises CHARACTER_SHEET_LOCK_UNAVAILABLE.
    envelope = Stage1ClipboardService(db).build_envelope(project["project_id"])
    slot = next(row for row in envelope["decision_slots"] if row["slot_id"] == "subpath_choice")
    offered = {choice["choice_id"]: choice for choice in slot["choices"]}
    assert CAI_SUBPATH in offered
    assert offered[CAI_SUBPATH]["pack_id"] == CAI_PACK
    assert CAI_SUBPATH in slot["required_choice_ids"]


def test_project_created_before_rebuild_keeps_its_pinned_locks(startup_settings, monkeypatch):
    ProductBootstrapService(startup_settings).run()
    db = Database(startup_settings)
    project = CharacterBuilderService(db).create_project(
        working_name="CAICLANLOCK1 pinned", concept="Colorless-light retainer commander",
        power_band="rival/boss", source_reference=None, target_cl=5, creation_mode="detailed",
        ability_scores={}, selections={"path_choice": [QI_PATH], "subpath_choice": [CAI_SUBPATH]},
        autogen_seed="CAICLANLOCK1",
    )
    with db.connection() as conn:
        locks_before = [tuple(row) for row in conn.execute(
            "SELECT pack_id,version,pack_hash FROM project_content_locks WHERE project_id=? ORDER BY pack_id,version",
            (project["project_id"],),
        ).fetchall()]
    assert locks_before

    # Force a full rebuild on the next startup, then resolve the old project again.
    monkeypatch.setattr(CoreCatalogImporter, "catalog_inventory_hash", lambda self: "forced-rebuild")
    ProductBootstrapService(startup_settings).run()
    monkeypatch.undo()
    with db.connection() as conn:
        locks_after = [tuple(row) for row in conn.execute(
            "SELECT pack_id,version,pack_hash FROM project_content_locks WHERE project_id=? ORDER BY pack_id,version",
            (project["project_id"],),
        ).fetchall()]
    assert locks_after == locks_before
    envelope = Stage1ClipboardService(db).build_envelope(project["project_id"])
    slot = next(row for row in envelope["decision_slots"] if row["slot_id"] == "subpath_choice")
    assert CAI_SUBPATH in {choice["choice_id"] for choice in slot["choices"]}


def test_catalog_status_endpoint_reports_sync_state(startup_settings, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import create_app

    ProductBootstrapService(startup_settings).run()
    with TestClient(create_app(startup_settings)) as client:
        body = client.get("/api/catalog/status").json()
        assert body["sync"]["in_sync"] is True
        assert body["sync"]["stored_inventory_hash"] == body["sync"]["current_inventory_hash"]
        assert body["latest_build"]["inventory_hash"] == body["sync"]["stored_inventory_hash"]

        monkeypatch.setattr(CoreCatalogImporter, "catalog_inventory_hash", lambda self: "changed-sources")
        drifted = client.get("/api/catalog/status").json()
        assert drifted["sync"]["in_sync"] is False
