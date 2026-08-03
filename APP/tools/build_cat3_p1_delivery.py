from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


ROOT_NAME = "TIANXIA_CAT3_P1_SOURCE_AND_EVIDENCE"
SOURCE_NAME = "TIANXIA_CAT3_P1_SOURCE_CHECKPOINT"
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache"}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_files(source_root: Path):
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_root)
        if "CAT3_P1_ACCEPTANCE" in relative.parts:
            continue
        if any(part in EXCLUDED_PARTS for part in relative.parts) or path.suffix == ".pyc":
            continue
        yield path, Path("SOURCE") / SOURCE_NAME / relative


def tree_files(root: Path, archive_prefix: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.relative_to(root).parts):
            yield path, archive_prefix / path.relative_to(root)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--task-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    task_root = Path(args.task_root).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    members: list[tuple[Path, Path]] = list(source_files(source_root))
    members.extend(tree_files(source_root / "CAT3_P1_ACCEPTANCE", Path("EVIDENCE") / "CAT3_P1_ACCEPTANCE"))
    members.extend(tree_files(task_root / "CONTROL", Path("INPUT_HANDOFF") / "CONTROL"))
    members.extend(tree_files(task_root / "EVIDENCE", Path("INPUT_HANDOFF") / "EVIDENCE"))
    for name in ("README_START_HERE.md", "PASTE_THIS_PROMPT.md", "MANIFEST.json", "SHA256SUMS.txt"):
        members.append((task_root / name, Path("INPUT_HANDOFF") / name))
    members.extend(
        [
            (source_root / "CAT3_P1_VERIFICATION_SUMMARY.md", Path("CAT3_P1_VERIFICATION_SUMMARY.md")),
            (source_root / "CAT3_P1_CONTINUATION_HANDOFF.md", Path("CAT3_P1_CONTINUATION_HANDOFF.md")),
        ]
    )

    payloads: list[tuple[str, bytes]] = []
    manifest_records: list[dict[str, object]] = []
    for disk_path, relative in members:
        payload = disk_path.read_bytes()
        archive_name = (Path(ROOT_NAME) / relative).as_posix()
        payloads.append((archive_name, payload))
        manifest_records.append(
            {"path": relative.as_posix(), "bytes": len(payload), "sha256": sha256_bytes(payload)}
        )

    manifest = {
        "schema": "Tianxia.CAT3.P1.SourceEvidenceManifest.v1",
        "status": "CAT3_P1_CANONICAL_CATALOG_SOURCE_READY_FOR_INDEPENDENT_REVIEW",
        "native_build_included": False,
        "registry_commitment_sha256": "704389709a00f5feee8408a4965859f570d7a2825dfc38afb0dc0a3f0980ef16",
        "record_count": len(manifest_records),
        "records": manifest_records,
    }
    manifest_payload = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    checksums_payload = "".join(
        f"{row['sha256']}  {row['path']}\n" for row in manifest_records
    ).encode("utf-8")
    payloads.extend(
        [
            (f"{ROOT_NAME}/PACKAGE_MANIFEST.json", manifest_payload),
            (f"{ROOT_NAME}/SHA256SUMS.txt", checksums_payload),
        ]
    )

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for name, payload in payloads:
            info = zipfile.ZipInfo(name, date_time=(2026, 7, 30, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    archive_sha = hashlib.sha256(output.read_bytes()).hexdigest()
    sidecar = output.with_suffix(output.suffix + ".sha256")
    sidecar.write_text(f"{archive_sha}  {output.name}\n", encoding="ascii", newline="\n")

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert all(not name.startswith("/") and ".." not in Path(name).parts for name in names)
        enclosed_manifest = json.loads(archive.read(f"{ROOT_NAME}/PACKAGE_MANIFEST.json"))
        for row in enclosed_manifest["records"]:
            payload = archive.read(f"{ROOT_NAME}/{row['path']}")
            assert len(payload) == row["bytes"]
            assert sha256_bytes(payload) == row["sha256"]

    size = output.stat().st_size
    if size >= 200 * 1024 * 1024:
        raise SystemExit(f"Delivery exceeds 200 MiB: {size}")
    print(
        json.dumps(
            {
                "result": "PASS",
                "output": str(output),
                "bytes": size,
                "sha256": archive_sha,
                "members": len(payloads),
                "sidecar": str(sidecar),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
