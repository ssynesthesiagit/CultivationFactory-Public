from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.queue_guard import require_test_queue


# Pinned Factory state root (MAINREDVENDOR1).
# The Method/Foundation corpus releases and the compiler selection authority
# verify their dependencies inside factory_authoring.final_character_materializer's
# state root: $CULTIVATION_FACTORY_STATE_ROOT, else ~/.local/state/cultivation-factory.
# That tree only exists where a live Factory installed the pinned archive, so on
# CI and on every other machine the acceptance tests around it failed with
# "The pinned compiler authority dependency is missing" and a FileNotFoundError
# for vendor/factory_adapter.json.  A test must never read the developer's home
# or live state (nor publish release files into it), so every run gets its own
# state root and the factory_state_root fixture extracts the pinned,
# hash-verified Factory archive there.
FACTORY_STATE_ROOT_ENV = "CULTIVATION_FACTORY_STATE_ROOT"
FACTORY_STATE_ROOT: Path | None = None


def pytest_configure(config):
    # Also covers batch runners that call pytest.main() in-process.
    require_test_queue()
    global FACTORY_STATE_ROOT
    given_basetemp = getattr(config.option, "basetemp", None)
    if given_basetemp:
        # pytest deletes and recreates a --basetemp when it first uses it, so
        # the fixture builds this tree only after tmp_path_factory.getbasetemp().
        root = Path(given_basetemp).resolve() / "factory-state-root"
    else:
        root = Path(tempfile.mkdtemp(prefix="cultivation-factory-state-"))
        config.add_cleanup(lambda: shutil.rmtree(root, ignore_errors=True))
    FACTORY_STATE_ROOT = root
    os.environ[FACTORY_STATE_ROOT_ENV] = str(root)


# Safety (owner 2026-10-13, EMBEDMENU incident): a test run that called the
# live EmbeddingGemma service unmocked flooded it at ~40 requests/s and hung
# the host GPU, needing a root reset. No test may open a real socket to the
# service's port, from any caller (combat/embedding_rank.py,
# character_creation/concept_index.py, or anything else): every test must
# inject a fake client/transport instead. This blocks the connection
# immediately -- callers that already handle a refused connection (both of
# the above do) degrade gracefully; nothing should rely on reaching it.
_BLOCKED_LIVE_MODEL_PORTS = {11448, 11434}
_real_socket_connect = socket.socket.connect
_real_socket_connect_ex = socket.socket.connect_ex


def _blocked_connect(self, address, *args, **kwargs):
    if isinstance(address, tuple) and len(address) >= 2 and address[1] in _BLOCKED_LIVE_MODEL_PORTS:
        raise OSError(f"tests must never reach a live model server (blocked connect to {address!r})")
    return _real_socket_connect(self, address, *args, **kwargs)


def _blocked_connect_ex(self, address, *args, **kwargs):
    if isinstance(address, tuple) and len(address) >= 2 and address[1] in _BLOCKED_LIVE_MODEL_PORTS:
        raise OSError(f"tests must never reach a live model server (blocked connect to {address!r})")
    return _real_socket_connect_ex(self, address, *args, **kwargs)


# Install before collection as well as fixtures: importing a test cannot
# contact the service before the session fixture starts.
socket.socket.connect = _blocked_connect
socket.socket.connect_ex = _blocked_connect_ex


@pytest.fixture(autouse=True, scope="session")
def _block_live_model_server_sockets():
    socket.socket.connect = _blocked_connect
    socket.socket.connect_ex = _blocked_connect_ex
    try:
        yield
    finally:
        socket.socket.connect = _real_socket_connect
        socket.socket.connect_ex = _real_socket_connect_ex

# TestClient hangs in sandboxes that refuse socket send(); see tests/asyncio_wakeup.py.
from tests.asyncio_wakeup import install_if_needed as _install_asyncio_wakeup_if_needed

_install_asyncio_wakeup_if_needed()

# CAT1 overlay-only tests retain their accepted byte-for-byte files.  In the
# integrated product tree those tests must evaluate the pristine CAT1 overlay,
# not the merged application root.  Patch only their imported path constants
# at test setup; accepted CAT1 source and tests remain byte-identical.
# These CAT1 acceptance checks read the pristine overlay's evidence/ files or
# external source/baseline trees.  The sanitized public baseline (80560ac0)
# never shipped them, so without the named roots they cannot run at all.
_CAT1_EXTERNAL_INPUTS = {
    "test_external_source_paths_and_hashes_exist": ("CAT1_OVERLAY_ROOT", "CAT1_AUTHORITY_ROOT"),
    "test_overlay_contains_only_new_paths": ("CAT1_OVERLAY_ROOT", "CAT1_BASELINE_ROOT"),
    "test_overlay_checksum_inventory_exact": ("CAT1_OVERLAY_ROOT",),
    "test_source_no_mutation_evidence": ("CAT1_OVERLAY_ROOT",),
    "test_deterministic_build_evidence": ("CAT1_OVERLAY_ROOT",),
}


def pytest_runtest_setup(item):
    if item.nodeid.startswith("tests/test_cat1_schema_provenance.py::"):
        missing = [name for name in _CAT1_EXTERNAL_INPUTS.get(item.name, ()) if not os.environ.get(name)]
        if missing:
            pytest.skip(
                "Needs the pristine CAT1 overlay and its external inputs ("
                + ", ".join(missing)
                + "), which the sanitized repository does not ship."
            )
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


@pytest.fixture(scope="session")
def factory_state_root(tmp_path_factory, factory_zip) -> Path:
    """Build this run's own Factory state root from the pinned bundled archive.

    The compiler/corpus acceptance tests read the pinned Factory tree through
    factory_authoring.final_character_materializer's state root (see
    FACTORY_STATE_ROOT_ENV above).  Building it here -- once per session, from
    the bundled archive whose SHA-256 is checked against its pin -- means those
    tests see the exact pinned Factory on every machine instead of whatever the
    person running them happens to have installed at home.  The tree is
    disposable: tests may publish their own derived corpora under
    vendor/releases/, and the whole thing is discarded with the run.
    """
    root = FACTORY_STATE_ROOT
    assert root is not None, "pytest_configure did not choose a Factory state root"
    # A given --basetemp is deleted when pytest first uses it; claim it now so
    # the extraction below cannot be wiped out by a later tmp_path test.
    tmp_path_factory.getbasetemp()
    if not (root / "vendor" / "factory_adapter.json").is_file():
        settings = Settings.from_env(ROOT, root)
        FactoryAdapter(Database(settings)).configure(factory_zip)
    from factory_authoring.final_character_materializer import FINAL_CHARACTER_DEFAULT_STATE_ROOT
    assert FINAL_CHARACTER_DEFAULT_STATE_ROOT == root, (
        "factory_authoring.final_character_materializer was imported before the test state root was chosen"
    )
    return root


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
