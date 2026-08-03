from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from app.authorities import GM_SCREEN_SHA256
from app.core import Database, FoundryError, Settings, sha256_file, sha256_json
from catalog.service import CatalogService
from character_sheet import CharacterSheetService
from factory_authoring import FactoryAuthoringWorkspaceService
from factory_authoring.command5_profile import CHARACTER_GM_PROFILE, CharacterGMCommand5Profile
from gm_export import GMCharacterExportService
from portable_character import PortableCharacterPackageService
from project_store.service import ProjectStore
from projector.verification import ProjectionVerifier
from vendor_adapter.service import FactoryAdapter


class CharacterProductionReleaseAdapter:
    """Bounded adapter over the established Command 5/6 release route."""

    def __init__(self, db: Database):
        self.db = db
        self.vendor = FactoryAdapter(db)
        self.portable = PortableCharacterPackageService(db)
        self.gm_export = GMCharacterExportService(db)

    @staticmethod
    def _stable(value: Any) -> Any:
        if isinstance(value, dict):
            consumer_runtime_identity = bool(
                value.get("sourcePackageKey")
                and str(value.get("id") or "").startswith("pkg-")
            )
            transient = {
                "path", "package_path", "workspace", "workspace_path",
                "candidate_zip", "portable_character_zip", "consumer_root",
                "copied_factory_zip", "original_factory_zip",
                "created_at", "updated_at", "verified_at",
                "harness_run", "seal_run", "stdout", "stderr",
                "build", "selected_id",
            }
            return {
                k: CharacterProductionReleaseAdapter._stable(v)
                for k, v in sorted(value.items())
                if k not in transient
                and not (consumer_runtime_identity and k == "id")
                and not k.endswith(("_path", "_root", "_dir"))
            }
        if isinstance(value, list):
            return [CharacterProductionReleaseAdapter._stable(v) for v in value]
        return value

    def _clean_import_proof(self, project_id: str, package: Path) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="cg1-clean-import-", ignore_cleanup_errors=True) as td:
            root = Path(td)
            data = root / "data"
            data.mkdir()
            # Preserve authenticated producer/catalog configuration, but remove the character.
            for child in self.db.settings.data_dir.iterdir():
                if child.name == self.db.settings.db_path.name or child.name.endswith(("-wal", "-shm")):
                    continue
                dest = data / child.name
                if child.is_dir(): shutil.copytree(child, dest, symlinks=True)
                else: shutil.copy2(child, dest)
            # A clean import proof is an actually new database, not a copied
            # database with immutable project rows surgically removed. The
            # authenticated Factory/configuration files remain available, while
            # the portable package supplies the complete project snapshot.
            shutil.rmtree(data / "portable_characters" / project_id, ignore_errors=True)
            settings = Settings.from_env(self.db.settings.root_dir, data)
            clean_db = Database(settings); clean_db.migrate()
            clean_vendor = FactoryAdapter(clean_db).status()
            factory_root = Path(clean_vendor.get("factory_root") or "")
            if not factory_root.is_dir():
                raise FoundryError("CG1_CLEAN_IMPORT_FACTORY_NOT_READY", "The clean import root does not retain authenticated Factory authority.", details=clean_vendor)
            CatalogService(clean_db).rebuild_core(factory_root)
            service = PortableCharacterPackageService(clean_db)
            first = service.import_into_factory(package)
            reopened_db = Database(settings)
            reopened_db.migrate()
            reopened_project = ProjectStore(reopened_db).get_project(project_id)
            reopened_sheet = CharacterSheetService(reopened_db).sheet(project_id, compact=True)
            second = PortableCharacterPackageService(reopened_db).import_into_factory(package)
            if first.get("status") != "IMPORTED" or second.get("status") != "ALREADY_INSTALLED_IDENTICAL":
                raise FoundryError("CG1_CLEAN_IMPORT_PROOF_FAILED", "The portable Character did not pass clean import and identical re-import.", details={"first": first, "second": second})
            return {
                "first": first,
                "reopen": {
                    "project_id": reopened_project["project"]["project_id"],
                    "project_revision": reopened_project["project"]["revision"],
                    "character_sheet_project_id": reopened_sheet["project_id"],
                    "character_sheet_build_status": reopened_sheet["build_status"],
                },
                "second": second,
            }

    def readiness(self) -> dict[str, Any]:
        vendor = self.vendor.status()
        gm_archive = self.gm_export.bundled_gm_zip
        gm_hash = sha256_file(gm_archive) if gm_archive.is_file() else None
        checks = {
            "authenticated_factory": bool(vendor.get("configured") and vendor.get("health") == "READY"),
            "physical_gm_screen": bool(gm_hash == GM_SCREEN_SHA256),
            "exact_consumer_runtime": bool((self.db.settings.root_dir / "gm_export" / "exact_consumer_harness.py").is_file()),
            "command5_command6_route": bool(
                callable(getattr(CharacterGMCommand5Profile, "command5", None))
                and callable(getattr(ProjectionVerifier, "command6", None))
            ),
            "portable_audit_import_registration": all(
                callable(getattr(self.portable, name, None))
                for name in ("audit", "import_into_factory", "register_verified")
            ),
        }
        return {
            "schema": "TianxiaFoundry.CharacterProductionAuthorityReadiness.v1",
            "ready": all(checks.values()),
            "checks": checks,
            "factory": vendor,
            "gm_screen": {"expected_sha256": GM_SCREEN_SHA256, "actual_sha256": gm_hash},
        }

    @staticmethod
    def _fail(phase: str, fail_after: str | None) -> None:
        aliases = {
            "factory_authoring": "factory_authoring",
            "command5": "command5",
            "command6": "command6",
            "gm_consumer": "exact_gm_consumer",
            "portable_audit": "package_audit",
            "clean_import": "first_clean_import",
            "identical_reimport": "identical_reimport",
            "portable_registration": "verified_registration",
            "gm_export": "downstream_gm_export",
        }
        if fail_after == phase or aliases.get(fail_after or "") == phase:
            raise RuntimeError(f"forced production failure after {phase}")

    def compile(self, project_id: str, *, output_root: Path, register: bool = False, fail_after: str | None = None) -> dict[str, Any]:
        readiness = self.readiness()
        if not readiness["ready"]:
            raise FoundryError("CG1_PRODUCTION_AUTHORITY_NOT_READY", "The production release authority is not ready.", details=readiness)
        vendor = readiness["factory"]
        factory_root = Path(vendor["factory_root"])
        gm_root = self.gm_export._gm_screen_root()
        authoring = FactoryAuthoringWorkspaceService(self.db).build(project_id)
        self._fail("factory_authoring", fail_after)
        command5 = CharacterGMCommand5Profile(self.db, factory_root=factory_root).command5(project_id, output_root=output_root / "command5")
        self._fail("command5", fail_after)
        verifier = ProjectionVerifier(self.db, factory_root=factory_root, gm_screen_root=gm_root)
        command6 = verifier.command6(project_id, command5_report=command5, workspace=Path(command5["workspace"]), output_dir=output_root / "portable", build_profile=CHARACTER_GM_PROFILE)
        self._fail("command6", fail_after)
        package = Path(command6["portable_character_zip"])
        consumer = command6.get("consumer_report") or {}
        if consumer.get("status") != "GM_SCREEN_SOURCE_CONSUMER_VERIFIED":
            raise FoundryError("CG1_EXACT_GM_CONSUMER_FAILED", "The exact bundled GM consumer did not verify the portable Character.", details=consumer)
        self._fail("exact_gm_consumer", fail_after)
        audit = self.portable.audit(package)
        self._fail("package_audit", fail_after)
        imports = self._clean_import_proof(project_id, package)
        self._fail("first_clean_import", fail_after)
        self._fail("identical_reimport", fail_after)
        registration = None; gm_export = None
        if register:
            registration = self.portable.register_verified(project_id, package=package, command6_report=command6, consumer_report=consumer, factory_import_report=imports["first"])
            self._fail("verified_registration", fail_after)
            gm_export = self.gm_export.export(project_id)
            self._fail("downstream_gm_export", fail_after)
        receipt = {
            "schema": "TianxiaFoundry.CharacterProductionReleaseReceipt.v1",
            "project_id": project_id,
            "authority_readiness": readiness,
            "factory_authoring": authoring,
            "command5": command5,
            "gm_model_sha256": command5.get("candidate_sha256"),
            "command6": command6,
            "portable_zip_sha256": sha256_file(package),
            "portable_audit": audit,
            "consumer": consumer,
            "clean_import": imports,
            "registration": registration,
            "gm_export": gm_export,
            "combat_readiness": "NOT_REQUESTED_OR_NOT_SUPPORTED_FOR_THIS_NEW_IDENTITY",
        }
        receipt["production_artifact_identity"] = sha256_json(self._stable({
            key: receipt[key]
            for key in (
                "project_id", "authority_readiness", "factory_authoring",
                "command5", "gm_model_sha256", "command6",
                "portable_zip_sha256", "portable_audit", "consumer",
                "clean_import", "combat_readiness",
            )
        }))
        receipt["stable_identity"] = sha256_json(self._stable(receipt))
        return receipt
