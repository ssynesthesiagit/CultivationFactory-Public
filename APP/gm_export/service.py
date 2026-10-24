from __future__ import annotations

import json
import re
import shutil
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from app.core import Database, FoundryError, sha256_file
from character_sheet.service import CharacterSheetService
from projector.verification import ProjectionVerifier
from portable_character.service import PortableCharacterPackageService
from vendor_adapter.service import FactoryAdapter

from app.authorities import GM_SCREEN_FILENAME, GM_SCREEN_SHA256


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "character").strip()).strip("._-")
    return cleaned[:96] or "character"


def _audit_zip(path: Path) -> dict[str, Any]:
    seen: set[str] = set(); folded: set[str] = set(); nfc: set[str] = set()
    with zipfile.ZipFile(path) as zf:
        if zf.testzip() is not None:
            raise FoundryError("GM_EXPORT_CRC_FAILED", "The generated GM Screen ZIP failed its CRC check.")
        names = []
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or re.match(r"^[A-Za-z]:", name):
                raise FoundryError("GM_EXPORT_UNSAFE_PATH", "The generated GM Screen ZIP contains an unsafe path.", details={"entry": name})
            key = unicodedata.normalize("NFC", name)
            if name in seen or name.casefold() in folded or key in nfc:
                raise FoundryError("GM_EXPORT_PATH_COLLISION", "The generated GM Screen ZIP contains colliding paths.", details={"entry": name})
            seen.add(name); folded.add(name.casefold()); nfc.add(key)
            mode = (info.external_attr >> 16) & 0xFFFF
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or kind == stat.S_IFLNK:
                raise FoundryError("GM_EXPORT_SPECIAL_FILE", "The generated GM Screen ZIP contains a link or special file.", details={"entry": name})
            if info.flag_bits & 1:
                raise FoundryError("GM_EXPORT_ENCRYPTED", "The generated GM Screen ZIP is encrypted.")
            if not info.is_dir(): names.append(name)
        if "SHA256SUMS.txt" not in names:
            raise FoundryError("GM_EXPORT_CHECKSUMS_MISSING", "The generated GM Screen ZIP has no checksum inventory.")
        declared: dict[str, str] = {}
        for line in zf.read("SHA256SUMS.txt").decode("utf-8").splitlines():
            if not line.strip(): continue
            digest, rel = line.split("  ", 1)
            if rel in declared:
                raise FoundryError("GM_EXPORT_CHECKSUM_DUPLICATE", "The generated GM Screen ZIP checksum inventory contains a duplicate.", details={"entry": rel})
            declared[rel] = digest
        expected = set(names) - {"SHA256SUMS.txt"}
        if set(declared) != expected:
            raise FoundryError("GM_EXPORT_CHECKSUM_COVERAGE", "The generated GM Screen ZIP checksum inventory does not cover every other file exactly once.", details={"missing": sorted(expected-set(declared)), "extra": sorted(set(declared)-expected)})
        import hashlib
        mismatched = [name for name, digest in declared.items() if hashlib.sha256(zf.read(name)).hexdigest() != digest]
        if mismatched:
            raise FoundryError("GM_EXPORT_CHECKSUM_MISMATCH", "The generated GM Screen ZIP contains files that do not match its checksum inventory.", details={"files": mismatched})
        required = {
            "Tianxia_GM_Character_Model_v1.json", "Tianxia_GM_Character_View_Model_v2.json",
            "Character_Import_Surface.json", "Normalized_Sheet.json", "Character_Master_Ledger.json",
            "GM_Screen_Display_Rows.json", "GM_Screen_Projection_Rows.json", "PACKAGE_MANIFEST.json",
            "Semantic_Validation_Report.json", "Release_Gate_Manifest.json",
        }
        missing_required = sorted(required - set(names))
        if missing_required:
            raise FoundryError("GM_EXPORT_REQUIRED_ARTIFACT_MISSING", "The generated package is missing required GM Screen artifacts.", details={"missing": missing_required})
        ledger = json.loads(zf.read("Character_Master_Ledger.json"))
        gm_model = json.loads(zf.read("Tianxia_GM_Character_Model_v1.json"))
    return {"entry_count": len(names), "checksum_count": len(declared), "ledger": ledger, "gm_model": gm_model}


class GMCharacterExportService:
    def __init__(self, db: Database):
        self.db = db
        self.vendor = FactoryAdapter(db)
        self.sheets = CharacterSheetService(db)
        self.portable = PortableCharacterPackageService(db)

    @property
    def bundled_gm_zip(self) -> Path:
        return self.db.settings.root_dir / "gm_screen" / GM_SCREEN_FILENAME

    def _gm_screen_root(self) -> Path:
        archive = self.bundled_gm_zip
        if not archive.is_file() or sha256_file(archive) != GM_SCREEN_SHA256:
            raise FoundryError("GM_SCREEN_AUTHORITY_UNAVAILABLE", "The bundled GM Screen authority is missing or has changed.", details={"expected_sha256": GM_SCREEN_SHA256})
        destination = self.db.settings.vendor_dir / "gm_screen" / GM_SCREEN_SHA256
        marker = destination / ".verified-source-sha256"
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == GM_SCREEN_SHA256:
            return destination
        staging = destination.with_name(destination.name + ".staging")
        shutil.rmtree(staging, ignore_errors=True); staging.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                p = PurePosixPath(info.filename.replace("\\", "/"))
                if p.is_absolute() or ".." in p.parts:
                    raise FoundryError("GM_SCREEN_ARCHIVE_UNSAFE", "The bundled GM Screen contains an unsafe path.")
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or stat.S_IFMT(mode) == stat.S_IFLNK or info.flag_bits & 1:
                    raise FoundryError("GM_SCREEN_ARCHIVE_UNSAFE", "The bundled GM Screen contains unsupported archive entries.")
            if zf.testzip() is not None:
                raise FoundryError("GM_SCREEN_ARCHIVE_CRC_FAILED", "The bundled GM Screen failed its CRC check.")
            zf.extractall(staging)
        (staging / ".verified-source-sha256").write_text(GM_SCREEN_SHA256 + "\n", encoding="utf-8")
        if destination.exists(): shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(destination)
        return destination

    def status(self, project_id: str) -> dict[str, Any]:
        sheet = self.sheets.sheet(project_id, compact=True)
        vendor = self.vendor.status()
        verified = self.portable.verified_status(project_id)
        if verified and verified.get("status") == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED":
            return {
                "project_id": project_id, "available": True, "label": "Export Character ZIP", "blockers": [],
                "readiness": "GM_READY_SOURCE_VERIFIED", "source_consumer_verified": True,
                "native_or_interactive_acceptance": verified.get("native_or_interactive_acceptance", "NOT_RUN"),
                "combat": verified.get("combat", "NOT_ATTEMPTED"),
                "verified_package": {"path": verified.get("package_path"), "sha256": verified.get("package_sha256")},
                "factory": {"configured": vendor.get("configured", False), "health": vendor.get("health")},
                "gm_screen": {"filename": GM_SCREEN_FILENAME, "sha256": GM_SCREEN_SHA256, "bundled": self.bundled_gm_zip.is_file()},
                "sheet_build_status": sheet["build_status"],
            }
        blockers = list(sheet["gm_export"]["blockers"])
        if not vendor.get("configured") or vendor.get("health") != "READY":
            blockers.append("The pinned Factory producer is not configured and ready.")
        if not self.bundled_gm_zip.is_file() or sha256_file(self.bundled_gm_zip) != GM_SCREEN_SHA256:
            blockers.append("The bundled GM Screen authority is unavailable.")
        if verified and verified.get("status") == "STALE":
            blockers.append("The previously verified Character ZIP is stale and must be verified again.")
        return {
            "project_id": project_id, "available": not blockers, "label": "Export Character ZIP for GM Screen",
            "blockers": blockers, "source_consumer_verified": False,
            "factory": {"configured": vendor.get("configured", False), "health": vendor.get("health")},
            "gm_screen": {"filename": GM_SCREEN_FILENAME, "sha256": GM_SCREEN_SHA256, "bundled": self.bundled_gm_zip.is_file()},
            "sheet_build_status": sheet["build_status"],
        }

    def export(self, project_id: str, *, filename: str | None = None) -> dict[str, Any]:
        status = self.status(project_id)
        if not status["available"]:
            raise FoundryError("GM_CHARACTER_EXPORT_NOT_READY", "This character is not ready for GM Screen export.", details=status, status_code=409)
        vendor = self.vendor.status()
        sheet = self.sheets.sheet(project_id)
        output_name = filename or f"{_safe_stem(sheet['name'])}_{_safe_stem(project_id)}_GM_Screen.zip"
        if Path(output_name).name != output_name or not output_name.lower().endswith(".zip"):
            raise FoundryError("GM_CHARACTER_EXPORT_FILENAME_INVALID", "Use a plain .zip filename.")
        export_dir = self.db.settings.exports_dir / "CharacterBuilder" / "GM_Screen_Characters"
        export_dir.mkdir(parents=True, exist_ok=True)
        target = export_dir / output_name
        if target.exists():
            raise FoundryError("GM_CHARACTER_EXPORT_EXISTS", "That GM Screen export already exists. Rename or move it before exporting again.", details={"path": str(target)}, status_code=409)
        verified = self.portable.verified_status(project_id)
        if verified and verified.get("status") == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED":
            source = Path(verified["package_path"]).resolve()
            audit = self.portable.audit(source)
            shutil.copy2(source, target)
            return {
                "exported": True, "project_id": project_id, "path": str(target.resolve()), "filename": target.name,
                "sha256": sha256_file(target), "bytes": target.stat().st_size,
                "entry_count": audit["entry_count"], "checksum_count": audit["checksum_count"],
                "readiness": "GM_READY_SOURCE_VERIFIED", "source_consumer_verified": True,
                "native_or_interactive_acceptance": "NOT_RUN", "combat": "NOT_ATTEMPTED",
                "command5_rerun": False, "command6_rerun": False,
                "owner_message": "Character ZIP ready. Drag this same ZIP into either the Factory or the bundled GM Screen.",
            }
        # Historical completed packages retain their existing legacy route.
        run_root = self.db.settings.logs_dir / "gm_exports" / project_id / target.stem
        verifier = ProjectionVerifier(self.db, factory_root=Path(vendor["factory_root"]), gm_screen_root=self._gm_screen_root())
        command5 = verifier.command5(project_id, source_fixture=Path(vendor["fixture_path"]), output_root=run_root / "command5")
        if command5.get("status") != "COMMAND_5_GM_SCREEN_CANDIDATE_READY":
            raise FoundryError("GM_CHARACTER_COMMAND5_FAILED", "The Factory could not produce a GM Screen candidate.", details=command5, status_code=409)
        command6 = verifier.command6(project_id, command5_report=command5, workspace=Path(command5["workspace"]), output_dir=target)
        if command6.get("status") != "SIMULATED_CONSUMER_PASS_REAL_GMSCREEN_ACCEPTANCE_REQUIRED":
            target.unlink(missing_ok=True)
            raise FoundryError("GM_CHARACTER_IMPORT_VALIDATION_FAILED", "The generated character ZIP did not pass the bundled GM Screen importer proof.", details=command6, status_code=409)
        audit = _audit_zip(target)
        ledger_name = ((audit["ledger"].get("character") or {}).get("name") or "").strip()
        model_identity = audit["gm_model"].get("identity") or {}
        model_name = str(model_identity.get("display_name") or model_identity.get("name") or "").strip()
        sheet_name = str(sheet["name"] or "").strip()
        if not sheet_name or ledger_name != sheet_name or model_name != sheet_name:
            target.unlink(missing_ok=True)
            raise FoundryError("GM_CHARACTER_IDENTITY_MISMATCH", "The exported identity does not match the Factory character sheet.", details={"sheet": sheet_name, "ledger": ledger_name, "gm_model": model_name})
        return {
            "exported": True,
            "project_id": project_id,
            "path": str(target.resolve()),
            "filename": target.name,
            "sha256": sha256_file(target),
            "bytes": target.stat().st_size,
            "entry_count": audit["entry_count"],
            "checksum_count": audit["checksum_count"],
            "identity": {"name": sheet_name, "ledger_name": ledger_name, "gm_model_name": model_name},
            "command5": command5,
            "gm_screen_import_validation": command6,
            "real_installed_gm_screen_acceptance": False,
            "owner_message": "Character ZIP created and checked with the bundled GM Screen importer. Drag this ZIP into the GM Screen character import box.",
        }
