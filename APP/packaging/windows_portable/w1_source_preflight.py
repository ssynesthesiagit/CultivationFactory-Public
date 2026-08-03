from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FACTORY_NAME = "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
FACTORY_SHA = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
FOUNDATION_NAME = "Tianxia_Foundation_FactoryApp_Handoff_v1_0.zip"
FOUNDATION_SHA = "df80217c64c0808190c85531095e5e78aa96ff6808be369915f36fbb4189771c"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_sums(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        if name in rows:
            raise RuntimeError(f"duplicate checksum path: {name}")
        rows[name] = digest
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--execution-root", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    source = Path(args.source_root).resolve()
    execution = Path(args.execution_root).resolve()
    report = Path(args.report).resolve()
    if source == report or source in report.parents:
        raise RuntimeError("Verification report path resolves inside the sealed package root")

    sums_path = source / "SHA256SUMS.txt"
    manifest_path = source / "PACKAGE_MANIFEST.json"
    if not sums_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("sealed source manifests are missing")
    sums = parse_sums(sums_path)
    actual_paths = {
        p.relative_to(source).as_posix()
        for p in source.rglob("*")
        if p.is_file() and p != sums_path
    }
    if set(sums) != actual_paths:
        missing = sorted(actual_paths - set(sums))
        extra = sorted(set(sums) - actual_paths)
        raise RuntimeError(f"source checksum coverage mismatch missing={missing[:10]} extra={extra[:10]}")
    for name, expected in sums.items():
        actual = sha256(source / name)
        if actual != expected:
            raise RuntimeError(f"source checksum mismatch: {name}")

    inputs = execution / "Inputs"
    factory = inputs / FACTORY_NAME
    foundation = inputs / FOUNDATION_NAME
    wheelhouse = inputs / "PrivateRuntimeWheels"
    for path, expected in ((factory, FACTORY_SHA), (foundation, FOUNDATION_SHA)):
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"missing or mismatched exact build input: {path.name}")
    if not wheelhouse.is_dir():
        raise RuntimeError("PrivateRuntimeWheels is missing")

    inventory_path = source / "packaging/windows_portable/R6_6_PRIVATE_RUNTIME_WHEEL_INVENTORY.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    required = {row["filename"]: row["sha256"] for row in inventory["wheels"]}
    actual_wheels = {p.name: sha256(p) for p in wheelhouse.iterdir() if p.is_file()}
    if actual_wheels != required:
        raise RuntimeError("private wheelhouse inventory mismatch")

    payload = {
        "status": "PASS",
        "source_root": str(source),
        "source_files_verified": len(sums),
        "factory_sha256": FACTORY_SHA,
        "foundation_sha256": FOUNDATION_SHA,
        "private_wheels_verified": len(required),
        "native_build_started": False,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
