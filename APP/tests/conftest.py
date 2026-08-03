from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# CAT1 overlay-only tests retain their accepted byte-for-byte files.  In the
# integrated product tree those tests must evaluate the pristine CAT1 overlay,
# not the merged application root.  Patch only their imported path constants
# at test setup; accepted CAT1 source and tests remain byte-identical.
def pytest_runtest_setup(item):
    overlay_value = os.environ.get("CAT1_OVERLAY_ROOT")
    if not overlay_value or not item.nodeid.startswith("tests/test_cat1_"):
        return
    overlay_root = Path(overlay_value).resolve()
    catalog_root = overlay_root / "catalog_authority" / "cat1"
    data_root = catalog_root / "data"

    import cat1_test_support as support

    support.ROOT = overlay_root
    support.CAT = catalog_root
    support.DATA = data_root
    # CAT1 test modules import these constants with ``import *``.  Update the
    # module copies as well as the helper module globals used by load()/sha().
    item.module.ROOT = overlay_root
    item.module.CAT = catalog_root
    item.module.DATA = data_root

from app.core import Database, Settings, sha256_file
from vendor_adapter.service import FactoryAdapter
from tests.r4v_harness import EXPECTED_FACTORY_SHA256, provision_external_test_key

_ORIGINAL_SETTINGS_FROM_ENV = Settings.from_env

def _r4v_settings_from_env(root: Path, data_dir: Path):
    settings = _ORIGINAL_SETTINGS_FROM_ENV(root, data_dir)
    provision_external_test_key(settings.data_dir)
    return settings

# This hook lives only in pytest support code. It materializes external,
# production-shaped key files in disposable TEST data directories.
Settings.from_env = staticmethod(_r4v_settings_from_env)


@pytest.fixture(scope="session")
def factory_zip() -> Path:
    value = os.environ.get("TIANXIA_TEST_FACTORY_ZIP") or os.environ.get("TIANXIA_FACTORY_ZIP")
    path = Path(value).resolve() if value else (ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip").resolve()
    assert path.is_file(), "The pinned Factory archive is missing from BundledContent and no trusted override was supplied."
    actual = sha256_file(path)
    assert actual == EXPECTED_FACTORY_SHA256, (
        f"R4V_FACTORY_HASH_MISMATCH expected={EXPECTED_FACTORY_SHA256} actual={actual}"
    )
    return path


@pytest.fixture(scope="session")
def factory_environment(tmp_path_factory, factory_zip):
    data = tmp_path_factory.mktemp("vendor_session")
    settings = Settings.from_env(ROOT, data)
    db = Database(settings); db.migrate()
    adapter = FactoryAdapter(db)
    config = adapter.configure(factory_zip)
    return {"settings": settings, "db": db, "adapter": adapter, "root": Path(config["factory_root"])}


@pytest.fixture
def fresh_db(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path / "data")
    db = Database(settings); db.migrate()
    return db


@pytest.fixture
def pack_v1() -> Path:
    return ROOT / "fixtures/packs/GOOD_TEST_PACK_v1_0_0.zip"


@pytest.fixture
def pack_v2() -> Path:
    return ROOT / "fixtures/packs/GOOD_TEST_PACK_v2_0_0.zip"

@pytest.fixture(scope="session")
def catalog_environment(factory_environment):
    from catalog.service import CatalogService
    service = CatalogService(factory_environment["db"])
    report = service.rebuild_core(factory_environment["root"])
    return {"service": service, "report": report, **factory_environment}

@pytest.fixture(scope="module")
def stage1_db(tmp_path_factory, catalog_environment):
    """Clone the session-built core catalog once for the Stage 1 regression module."""
    import sqlite3
    settings = Settings.from_env(ROOT, tmp_path_factory.mktemp("stage1 data with spaces"))
    settings.ensure_dirs()
    source = sqlite3.connect(catalog_environment["settings"].db_path)
    target = sqlite3.connect(settings.db_path)
    source.backup(target)
    target.close(); source.close()
    # The catalog seal is keyed by evidence outside SQLite. A database backup
    # without the matching external test key context is intentionally
    # unverifiable. Preserve that exact session key/key ID in this TEST-only
    # cloned workflow; production construction still has no fallback.
    source_security = catalog_environment["settings"].data_dir / "security"
    target_security = settings.data_dir / "security"
    if source_security.is_dir():
        shutil.copytree(source_security, target_security, dirs_exist_ok=True, copy_function=shutil.copy2)
    db = Database(settings); db.migrate()
    return db
