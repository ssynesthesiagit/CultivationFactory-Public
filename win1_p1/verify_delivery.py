from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from application_checksum import verify as verify_application_checksum

GM_SCREEN_SHA256 = "c281c80e96c718a2c629b65c762b1c053a82eff7201d018a6acca1110c1c0f8f"
REQUIRED_ROOT_FILES = {
    "LAUNCH_TIANXIA_OWNER_TEST.cmd",
    "LAUNCH_CLEAN_IMPORT_TEST.cmd",
    "OPEN_EXACT_GM_SCREEN.cmd",
    "README_START_HERE.md",
    "OWNER_TEST_CHECKLIST.md",
    "REMOVE_OWNER_TEST_BUILD.md",
    "SOURCE_BUILD_IDENTITY.json",
    "PACKAGE_MANIFEST.json",
    "SHA256SUMS.txt",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_archive_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return False
    return all(part not in {"", ".", ".."} for part in PurePosixPath(name.rstrip("/")).parts)


def file_records(root: Path) -> dict[str, dict[str, object]]:
    return {
        path.relative_to(root).as_posix(): {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in root.rglob("*")
        if path.is_file()
    }


def verify(delivery: Path, archive: Path | None) -> dict[str, object]:
    delivery = delivery.resolve()
    missing = sorted(name for name in REQUIRED_ROOT_FILES if not (delivery / name).is_file())
    if missing:
        raise RuntimeError(f"missing required delivery files: {missing}")
    exe = delivery / "Application" / "Tianxia Factory.exe"
    if not exe.is_file():
        raise RuntimeError("isolated internal application executable is missing")
    if (delivery / "Application" / "UserData").exists():
        raise RuntimeError("internal Application/UserData must not be shipped")

    primary = (delivery / "LAUNCH_TIANXIA_OWNER_TEST.cmd").read_text(encoding="utf-8")
    clean = (delivery / "LAUNCH_CLEAN_IMPORT_TEST.cmd").read_text(encoding="utf-8")
    if 'set "TIANXIA_FOUNDRY_DATA=%OWNER_TEST_ROOT%"' not in primary:
        raise RuntimeError("primary launcher does not force its owner-test root")
    if 'set "OWNER_TEST_ROOT=%~dp0OwnerTestData"' not in primary:
        raise RuntimeError("primary launcher root is not exact OwnerTestData")
    if 'set "OWNER_TEST_ROOT=%~dp0OwnerTestData\\CleanFactory"' not in clean:
        raise RuntimeError("clean-import launcher is not nested under OwnerTestData")
    if "%~dp0Application\\Tianxia Factory.exe" not in primary or "%~dp0Application\\Tianxia Factory.exe" not in clean:
        raise RuntimeError("supported launchers do not target the isolated internal payload")

    gm = delivery / "Exact Bundled GM Screen" / "HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"
    if not gm.is_file() or sha256(gm) != GM_SCREEN_SHA256:
        raise RuntimeError("exact bundled GM Screen identity mismatch")
    with zipfile.ZipFile(gm) as gm_zip:
        if gm_zip.testzip() is not None:
            raise RuntimeError("exact bundled GM Screen CRC failure")
        if "Open_Dao_Dashboard.bat" not in gm_zip.namelist():
            raise RuntimeError("exact bundled GM Screen launcher is missing")

    declared: dict[str, str] = {}
    for line in (delivery / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        if not line:
            continue
        digest, relative = line.split("  ", 1)
        if relative in declared or not safe_archive_name(relative):
            raise RuntimeError(f"unsafe or duplicate checksum path: {relative}")
        declared[relative] = digest
    actual = {
        path.relative_to(delivery).as_posix(): sha256(path)
        for path in delivery.rglob("*")
        if path.is_file() and path != delivery / "SHA256SUMS.txt"
    }
    if declared != actual:
        raise RuntimeError("delivery SHA256SUMS coverage or identity mismatch")

    application_checksum = verify_application_checksum(delivery / "Application")
    if application_checksum["status"] != "PASS":
        raise RuntimeError("nested Application SHA256SUMS coverage or identity mismatch")

    archive_report: dict[str, object] | None = None
    if archive is not None:
        archive = archive.resolve()
        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
            unsafe = [name for name in names if not safe_archive_name(name)]
            if unsafe:
                raise RuntimeError(f"unsafe delivery ZIP paths: {unsafe[:5]}")
            bad = package.testzip()
            if bad is not None:
                raise RuntimeError(f"delivery ZIP CRC failure: {bad}")
            with tempfile.TemporaryDirectory(prefix="tianxia-win1-p1r2r2-clean-extract-") as temporary:
                clean_root = Path(temporary) / "delivery"
                clean_root.mkdir()
                package.extractall(clean_root)
                extracted_delivery = clean_root / delivery.name
                if not extracted_delivery.is_dir():
                    if all((clean_root / name).is_file() for name in REQUIRED_ROOT_FILES):
                        extracted_delivery = clean_root
                    else:
                        raise RuntimeError("clean-extracted delivery root is missing or ambiguous")
                extracted_application = verify_application_checksum(extracted_delivery / "Application")
                if extracted_application["status"] != "PASS":
                    raise RuntimeError("clean-extracted Application SHA256SUMS coverage or identity mismatch")
                staged_records = file_records(delivery)
                extracted_records = file_records(extracted_delivery)
                missing_after_extract = sorted(set(staged_records) - set(extracted_records))
                unexpected_after_extract = sorted(set(extracted_records) - set(staged_records))
                size_mismatches = [
                    relative for relative in sorted(set(staged_records).intersection(extracted_records))
                    if staged_records[relative]["bytes"] != extracted_records[relative]["bytes"]
                ]
                hash_mismatches = [
                    relative for relative in sorted(set(staged_records).intersection(extracted_records))
                    if staged_records[relative]["sha256"] != extracted_records[relative]["sha256"]
                ]
                if missing_after_extract or unexpected_after_extract or size_mismatches or hash_mismatches:
                    raise RuntimeError("clean-extracted delivery differs from staged final delivery")
                clean_extract_report = {
                    "status": "PASS",
                    "delivery_root": extracted_delivery.name,
                    "checked_count": len(staged_records),
                    "application_checked_count": extracted_application["checked_count"],
                    "missing_count": len(missing_after_extract),
                    "unexpected_count": len(unexpected_after_extract),
                    "size_mismatch_count": len(size_mismatches),
                    "hash_mismatch_count": len(hash_mismatches),
                    "version_json": extracted_application["version_json"],
                }
        archive_report = {
            "path": str(archive),
            "bytes": archive.stat().st_size,
            "sha256": sha256(archive),
            "entry_count": len(names),
            "crc": "PASS",
            "path_safety": "PASS",
            "clean_extraction": clean_extract_report,
        }

    files = [path for path in delivery.rglob("*") if path.is_file()]
    return {
        "schema": "Tianxia.WIN1P1.DeliveryVerification.v1",
        "status": "PASS",
        "delivery_root": str(delivery),
        "file_count": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
        "application_exe_sha256": sha256(exe),
        "gm_screen_sha256": sha256(gm),
        "internal_userdata_absent": True,
        "launchers_force_owner_test_data": True,
        "sha256sums": "PASS",
        "application_sha256sums": application_checksum,
        "archive": archive_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(args.delivery, args.archive)
    except Exception as exc:
        report = {
            "schema": "Tianxia.WIN1P1.DeliveryVerification.v1",
            "status": "FAIL",
            "error": str(exc),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
