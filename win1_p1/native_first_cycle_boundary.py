from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root: Path) -> list[dict[str, object]]:
    return [
        {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(root.rglob("*")) if path.is_file()
    ]


def safe_extract(archive_path: Path, destination: Path) -> None:
    if destination.exists():
        if any(destination.iterdir()):
            raise RuntimeError(f"Extraction root must be empty: {destination}")
    else:
        destination.mkdir(parents=True)
    seen: set[str] = set()
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            name = info.filename
            pure = PurePosixPath(name)
            if (not name or "\\" in name or pure.is_absolute() or ".." in pure.parts
                    or info.flag_bits & 0x1 or name in seen
                    or ((info.external_attr >> 16) & 0o170000) == 0o120000):
                raise RuntimeError(f"Unsafe delivery ZIP member: {name!r}")
            seen.add(name)
        archive.extractall(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove the Windows browser cycle uses byte-identical packaged inputs.")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--delivery-zip", type=Path, required=True)
    parser.add_argument("--extract-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repository = args.repository.resolve()
    delivery_zip = args.delivery_zip.resolve()
    extract_root = args.extract_root.resolve()
    safe_extract(delivery_zip, extract_root)

    pairs = {
        "static": (repository / "APP/static", extract_root / "Application/Runtime/static"),
        "catalog_authority": (
            repository / "APP/catalog_authority/cat3/generated",
            extract_root / "Application/Runtime/catalog_authority/cat3/generated",
        ),
        "non_sphere_authority": (
            repository / "APP/non_sphere_authority/authority",
            extract_root / "Application/Runtime/non_sphere_authority/authority",
        ),
    }
    comparisons: dict[str, object] = {}
    for name, (source, packaged) in pairs.items():
        source_inventory = inventory(source)
        packaged_inventory = inventory(packaged)
        comparisons[name] = {
            "source_root": str(source), "packaged_root": str(packaged),
            "source_inventory": source_inventory, "packaged_inventory": packaged_inventory,
            "byte_identical": source_inventory == packaged_inventory,
        }
        if source_inventory != packaged_inventory:
            raise RuntimeError(f"Packaged {name} inputs differ from the exact checked-out source")

    owner_data = extract_root / "OwnerTestData"
    if not owner_data.is_dir():
        raise RuntimeError("Clean-extracted delivery has no OwnerTestData directory")
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True, encoding="utf-8"
    ).strip()
    result = {
        "schema": "Tianxia.WIN1P1R3R1.NativeFirstCycleBoundary.v1",
        "status": "PASS",
        "git_head": head,
        "delivery_zip": {"path": str(delivery_zip), "bytes": delivery_zip.stat().st_size, "sha256": sha256(delivery_zip)},
        "clean_extracted_delivery_root": str(extract_root),
        "owner_test_data_root": str(owner_data),
        "execution_boundary": (
            "The production FastAPI/static application is launched from the exact checkout because the packaged "
            "WebView executable has no unattended browser-control surface. It uses the clean-extracted delivery's "
            "OwnerTestData. Static, catalog-authority, and non-sphere-authority inputs are proven byte-identical here."
        ),
        "comparisons": comparisons,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
