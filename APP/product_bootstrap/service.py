from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.core import (
    APP_STATUS,
    APP_VERSION,
    EXPECTED_FACTORY_HASH,
    EXPECTED_GM_SCREEN_HASH,
    GM_SCREEN_VERSION,
    Database,
    FoundryError,
    Settings,
    sha256_file,
    utcnow,
)
from catalog.service import CatalogService
from canonical_catalog import CanonicalCatalogAuthorityService
from vendor_adapter.service import FactoryAdapter

BUNDLED_FACTORY_NAME = "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
BUNDLED_FACTORY_RELATIVE_PATH = Path("BundledContent") / BUNDLED_FACTORY_NAME
GM_SCREEN_RELATIVE_PATH = Path("gm_screen") / "HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"
NATIVE_WINDOWS_STATUS = "NATIVE_WINDOWS_OWNER_ACCEPTANCE_DEFERRED"
BOOTSTRAP_READY = "CANONICAL_CATALOG_PRODUCT_INTEGRATION_READY"
CLEAN_ROOT_BOOTSTRAP_LINEAGE = "CLEAN_ROOT_PRODUCT_BOOTSTRAP_READY"
BOOTSTRAP_BLOCKED = "CLEAN_ROOT_PRODUCT_BOOTSTRAP_BLOCKED"


class ProductReadinessService:
    """Dependency-aware product readiness without mutating owner state."""

    def __init__(self, db: Database):
        self.db = db
        self.settings = db.settings

    @property
    def bundled_corpus_path(self) -> Path:
        return (self.settings.root_dir / BUNDLED_FACTORY_RELATIVE_PATH).resolve()

    def resolve_corpus(self) -> dict[str, Any]:
        candidate = self.settings.factory_zip
        if candidate is None:
            candidate = self.bundled_corpus_path
            source = "BUNDLED_RELATIVE_PRODUCT_INPUT"
        else:
            candidate = Path(candidate).expanduser().resolve()
            source = "BUNDLED_RELATIVE_PRODUCT_INPUT" if candidate == self.bundled_corpus_path else "EXPLICIT_TRUSTED_OVERRIDE"
        exists = candidate.is_file()
        actual = sha256_file(candidate) if exists else None
        ready = bool(exists and actual == EXPECTED_FACTORY_HASH)
        reason = None
        if not exists:
            reason = "The authenticated producer corpus is missing."
        elif actual != EXPECTED_FACTORY_HASH:
            reason = "The producer corpus failed exact SHA-256 verification."
        return {
            "schema": "TianxiaFactory.ProducerCorpusReadiness.v1",
            "ready": ready,
            "source": source,
            "path": str(candidate),
            "filename": candidate.name,
            "expected_sha256": EXPECTED_FACTORY_HASH,
            "actual_sha256": actual,
            "bytes": candidate.stat().st_size if exists else None,
            "reason": reason,
            "inherited_fixture_checksum_limitation": (
                "Seven authenticated fixture Build-directory SHA256SUMS manifests contain stale declarations; "
                "the exact top-level corpus bytes remain authoritative and are not repaired."
            ),
        }

    def database_status(self) -> dict[str, Any]:
        try:
            with self.db.connection() as conn:
                conn.execute("SELECT 1").fetchone()
                migrations = int(conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0])
            return {
                "ready": True,
                "path": str(self.settings.db_path),
                "migrations_applied": migrations,
                "reason": None,
            }
        except Exception as exc:
            return {
                "ready": False,
                "path": str(self.settings.db_path),
                "migrations_applied": None,
                "reason": str(exc),
            }

    def project_store_status(self) -> dict[str, Any]:
        try:
            with self.db.connection() as conn:
                projects = int(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
                events = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            return {"ready": True, "project_count": projects, "event_count": events, "reason": None}
        except Exception as exc:
            return {"ready": False, "project_count": None, "event_count": None, "reason": str(exc)}

    def gm_consumer_status(self) -> dict[str, Any]:
        path = (self.settings.root_dir / GM_SCREEN_RELATIVE_PATH).resolve()
        exists = path.is_file()
        actual = sha256_file(path) if exists else None
        return {
            "ready": bool(exists and actual == EXPECTED_GM_SCREEN_HASH),
            "name": "Tianxia GM Screen",
            "version": GM_SCREEN_VERSION,
            "path": str(path),
            "expected_sha256": EXPECTED_GM_SCREEN_HASH,
            "actual_sha256": actual,
            "reason": None if exists and actual == EXPECTED_GM_SCREEN_HASH else "The exact bundled GM consumer is missing or altered.",
        }

    def combat_runtime_status(self) -> dict[str, Any]:
        required = [
            self.settings.root_dir / "combat" / "pre_encounter.py",
            self.settings.root_dir / "combat" / "character_runtime_adapter.py",
            self.settings.root_dir / "R6_6_9_2_C3B_STATUS.json",
        ]
        missing = [str(path) for path in required if not path.is_file()]
        return {
            "ready": not missing,
            "status": "COMBATANT_LIBRARY_READY_PRE_ENCOUNTER_DRAFT" if not missing else "COMBAT_RUNTIME_SOURCE_INCOMPLETE",
            "runtime_semantics": "RUNTIME_READY_PRE_ENCOUNTER",
            "live_encounter": "NOT_ATTEMPTED",
            "missing": missing,
        }

    @staticmethod
    def _capability(ready: bool, blockers: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "ready": ready,
            "status": "READY" if ready else "BLOCKED",
            "blocking_reasons": blockers,
        }

    def report(self) -> dict[str, Any]:
        database = self.database_status()
        project_store = self.project_store_status()
        corpus = self.resolve_corpus()
        adapter = FactoryAdapter(self.db).status()
        catalog = CatalogService(self.db).status()
        gm = self.gm_consumer_status()
        combat = self.combat_runtime_status()
        canonical = CanonicalCatalogAuthorityService(self.settings.root_dir).status()

        blockers: list[dict[str, str]] = []
        if not database["ready"]:
            blockers.append({"code": "PRODUCT_DATABASE_NOT_READY", "message": "The writable project database is not ready."})
        if not project_store["ready"]:
            blockers.append({"code": "PRODUCT_PROJECT_STORE_NOT_READY", "message": project_store["reason"] or "The writable project store is not ready."})
        if not corpus["ready"]:
            blockers.append({"code": "PRODUCT_PRODUCER_CORPUS_NOT_READY", "message": corpus["reason"] or "The producer corpus is not ready."})
        if not adapter.get("configured") or adapter.get("health") != "READY":
            blockers.append({"code": "PRODUCT_FACTORY_ADAPTER_NOT_READY", "message": "The authenticated Factory producer has not been published into the writable data root."})
        if int(catalog.get("record_count") or 0) <= 0 or int(catalog.get("installed_pack_count") or 0) <= 0:
            blockers.append({"code": "PRODUCT_CORE_CATALOG_NOT_READY", "message": "The authenticated core catalog has not been built."})
        if not canonical.get("ready"):
            blockers.append({"code": "PRODUCT_CANONICAL_CATALOG_AUTHORITY_NOT_READY", "message": (canonical.get("error") or {}).get("message") or "CAT1 canonical catalog authority is unavailable or invalid."})

        import_blockers = [row for row in blockers if row["code"] != "PRODUCT_CANONICAL_CATALOG_AUTHORITY_NOT_READY"]
        import_ready = not import_blockers
        creator_ready = not blockers
        product_ready = import_ready and gm["ready"] and combat["ready"]
        status = BOOTSTRAP_READY if product_ready else BOOTSTRAP_BLOCKED
        return {
            "schema": "TianxiaFactory.ProductReadiness.v1",
            "generated_at": utcnow(),
            "status": status,
            "clean_root_bootstrap_lineage_status": CLEAN_ROOT_BOOTSTRAP_LINEAGE if product_ready else BOOTSTRAP_BLOCKED,
            "process": {"live": True, "status": "RUNNING", "bound_host": "127.0.0.1"},
            "build": {
                "version": APP_VERSION,
                "status": status,
                "declared_checkpoint_status": APP_STATUS,
            },
            "data_root": str(self.settings.data_dir),
            "database": database,
            "project_store": project_store,
            "producer_corpus": corpus,
            "factory_adapter": adapter,
            "catalog": catalog,
            "canonical_catalog_authority": canonical,
            "character_creation": self._capability(creator_ready, list(blockers)),
            "portable_import": self._capability(import_ready, list(import_blockers)),
            "gm_consumer": gm,
            "combat_runtime": combat,
            "native_windows": {"status": NATIVE_WINDOWS_STATUS, "accepted": False},
            "blocking_reasons": blockers,
            "product_ready": product_ready,
        }


class ProductBootstrapService:
    """Single idempotent producer/catalog bootstrap used by Linux and Windows launchers."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.ensure_dirs()
        self.db = Database(settings)
        self.readiness = ProductReadinessService(self.db)
        self.lock_path = self.settings.security_dir / "product_bootstrap.lock"

    @contextmanager
    def _exclusive_lock(self, *, timeout_seconds: float = 120.0) -> Iterator[None]:
        deadline = time.monotonic() + timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(descriptor, json.dumps({"pid": os.getpid(), "created_at": utcnow()}).encode("utf-8"))
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise FoundryError(
                        "PRODUCT_BOOTSTRAP_LOCK_TIMEOUT",
                        "Another bootstrap attempt did not finish within the bounded wait.",
                        details={"lock": str(self.lock_path)},
                        status_code=503,
                    )
                time.sleep(0.05)
        try:
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError:
                pass

    def run(self) -> dict[str, Any]:
        started = utcnow()
        with self._exclusive_lock():
            corpus = self.readiness.resolve_corpus()
            if not corpus["ready"]:
                raise FoundryError(
                    "PRODUCT_BOOTSTRAP_CORPUS_INVALID",
                    corpus["reason"] or "The authenticated producer corpus is unavailable.",
                    details=corpus,
                    status_code=503,
                )

            self.db.migrate()
            adapter = FactoryAdapter(self.db)
            adapter_before = adapter.status()
            if adapter_before.get("configured"):
                if adapter_before.get("health") != "READY":
                    raise FoundryError(
                        "PRODUCT_BOOTSTRAP_EXISTING_FACTORY_INVALID",
                        "An existing Factory configuration is invalid and was preserved without replacement.",
                        details=adapter_before,
                        status_code=503,
                    )
                if adapter_before.get("factory_zip_hash") != EXPECTED_FACTORY_HASH:
                    raise FoundryError(
                        "PRODUCT_BOOTSTRAP_EXISTING_FACTORY_CONFLICT",
                        "An existing Factory configuration identifies a different producer and was not overwritten.",
                        details=adapter_before,
                        status_code=409,
                    )
                adapter_action = "PRESERVED_EXISTING_READY_CONFIGURATION"
            else:
                adapter.configure(Path(corpus["path"]))
                adapter_action = "CONFIGURED_FROM_VERIFIED_CORPUS"

            adapter_after = adapter.status()
            if adapter_after.get("health") != "READY":
                raise FoundryError(
                    "PRODUCT_BOOTSTRAP_FACTORY_NOT_READY",
                    "The verified producer corpus could not be published into a ready Factory adapter.",
                    details=adapter_after,
                    status_code=503,
                )

            catalog_service = CatalogService(self.db)
            catalog_before = catalog_service.status()
            catalog_invalid = (
                int(catalog_before.get("record_count") or 0) <= 0
                or int(catalog_before.get("installed_pack_count") or 0) <= 0
                or not catalog_before.get("latest_build")
            )
            if catalog_invalid:
                catalog_build = catalog_service.rebuild_core(Path(adapter_after["factory_root"]))
                catalog_action = "BUILT_AUTHENTICATED_CORE_CATALOG"
            else:
                catalog_build = None
                catalog_action = "PRESERVED_EXISTING_VALID_CATALOG"

            final = self.readiness.report()
            if not final["product_ready"]:
                raise FoundryError(
                    "PRODUCT_BOOTSTRAP_READINESS_BLOCKED",
                    "Bootstrap completed partially but the complete bounded product readiness contract remains blocked.",
                    details=final,
                    status_code=503,
                )
            return {
                "schema": "TianxiaFactory.ProductBootstrapReport.v1",
                "status": BOOTSTRAP_READY,
                "clean_root_bootstrap_lineage_status": CLEAN_ROOT_BOOTSTRAP_LINEAGE,
                "started_at": started,
                "completed_at": utcnow(),
                "corpus": corpus,
                "adapter_action": adapter_action,
                "catalog_action": catalog_action,
                "catalog_build": catalog_build,
                "readiness": final,
                "native_windows": NATIVE_WINDOWS_STATUS,
            }
