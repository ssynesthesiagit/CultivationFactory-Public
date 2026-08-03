from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARENT_MANIFEST = ROOT / "PACKAGE_MANIFEST.json"
ROOT_SUMS = ROOT / "SHA256SUMS.txt"
OUTER_NAME = "TIANXIA_W5_P1_CURRENT_INTEGRATED_WINDOWS_OWNER_TEST_READY"
EXCLUDED_PARTS = {".pytest_cache", "__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
SEAL_FILES = {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt", "W5_P1_SOURCE_DIFF.json"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def included(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    return (
        path.is_file()
        and not any(part in EXCLUDED_PARTS for part in rel.parts)
        and path.suffix.lower() not in EXCLUDED_SUFFIXES
    )


def inventory() -> list[Path]:
    return sorted((p for p in ROOT.rglob("*") if included(p)), key=lambda p: p.relative_to(ROOT).as_posix())


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: seal_cg1_p1r2d.py OUTPUT_ZIP")
    output = Path(sys.argv[1]).resolve()
    parent = json.loads(PARENT_MANIFEST.read_text(encoding="utf-8"))
    baseline = {entry["path"]: entry["sha256"] for entry in parent["files"]}

    nested = {
        rel: sha
        for rel, sha in baseline.items()
        if Path(rel).name == "SHA256SUMS.txt"
        and rel != "SHA256SUMS.txt"
        and not rel.endswith("C2B3_Build_SHA256SUMS.txt")
    }
    mismatched_nested = [
        rel for rel, sha in nested.items()
        if not (ROOT / rel).is_file() or digest(ROOT / rel) != sha
    ]
    if len(nested) != 19 or mismatched_nested:
        raise RuntimeError(f"nested checksum preservation failed: count={len(nested)} mismatches={mismatched_nested}")

    current_before_seal = {
        p.relative_to(ROOT).as_posix(): digest(p)
        for p in inventory()
        if p.relative_to(ROOT).as_posix() not in SEAL_FILES
    }
    comparison_paths = sorted((set(baseline) | set(current_before_seal)) - SEAL_FILES)
    diff = {
        "added": [p for p in comparison_paths if p not in baseline],
        "changed": [p for p in comparison_paths if p in baseline and p in current_before_seal and baseline[p] != current_before_seal[p]],
        "deleted": [p for p in comparison_paths if p not in current_before_seal],
        "nested_checksum_files_preserved": 19,
        "programming_parent_sha256": "9065c43a1fac54a5b19ad08cb58ddfc5eb88e4ef4433cc0cb730d079642151a1",
        "schema": "Tianxia.SourceDiff.v1",
        "status": "W5_CURRENT_INTEGRATED_WINDOWS_OWNER_TEST_READY",
    }
    (ROOT / "W5_P1_SOURCE_DIFF.json").write_text(
        json.dumps(diff, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    files_for_manifest = [
        p for p in inventory()
        if p.relative_to(ROOT).as_posix() not in {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}
    ]
    manifest = {
        "c3d_p2_started": False,
        "files": [
            {
                "bytes": p.stat().st_size,
                "path": p.relative_to(ROOT).as_posix(),
                "sha256": digest(p),
            }
            for p in files_for_manifest
        ],
        "fresh_current_project": True,
        "nested_checksum_files_preserved": 19,
        "programming_parent_sha256": "9065c43a1fac54a5b19ad08cb58ddfc5eb88e4ef4433cc0cb730d079642151a1",
        "schema": "Tianxia.PackageManifest.v1",
        "status": "W5_CURRENT_INTEGRATED_WINDOWS_OWNER_TEST_READY",
        "task": "W5-P1",
    }
    PARENT_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files_for_sums = [
        p for p in inventory()
        if p.relative_to(ROOT).as_posix() != "SHA256SUMS.txt"
    ]
    ROOT_SUMS.write_text(
        "".join(f"{digest(p)}  {p.relative_to(ROOT).as_posix()}\n" for p in files_for_sums),
        encoding="utf-8",
    )

    if output.exists():
        output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    fixed = (2026, 7, 29, 0, 0, 0)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for path in inventory():
            rel = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(f"{OUTER_NAME}/{rel}", fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    with zipfile.ZipFile(output, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
    print(json.dumps({
        "bytes": output.stat().st_size,
        "files": len(inventory()),
        "nested_checksum_files_preserved": len(nested),
        "output": str(output),
        "sha256": digest(output),
        "status": "W5_CURRENT_INTEGRATED_WINDOWS_OWNER_TEST_READY",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
