from __future__ import annotations

import argparse
from pathlib import Path

from .canonical import canonical_bytes
from .gate1 import build_gate1
from .schema_export import export_schemas
from .validation import validate_gate1


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile Tianxia Factory hybrid-combat Gate 1 artifacts.")
    parser.add_argument("--gate1-root", type=Path, required=True, help="Directory containing installation_records.json and packs/")
    parser.add_argument("--output", type=Path, required=True, help="Destination for compiled Gate 1 artifacts")
    args = parser.parse_args()
    result = build_gate1(args.gate1_root.resolve(), args.output.resolve())
    export_schemas(args.output.resolve() / "schemas")
    report = validate_gate1(result)
    (args.output.resolve() / "Gate1_Validation_Report.json").write_bytes(canonical_bytes(report) + b"\n")
    print(report["validation"]["status"])
    print(result.registry.snapshot.snapshot_sha256)
    return 0 if report["validation"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
