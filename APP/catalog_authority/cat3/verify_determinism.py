from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): digest(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--run-a", required=True)
    parser.add_argument("--run-b", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    source_root = Path(args.source_root).resolve()
    run_a = Path(args.run_a).resolve()
    run_b = Path(args.run_b).resolve()
    report_path = Path(args.report).resolve()
    generated = source_root / "catalog_authority" / "cat3" / "generated"
    a_files = inventory(run_a)
    b_files = inventory(run_b)
    generated_files = inventory(generated)
    assert a_files == b_files
    assert a_files == generated_files
    compiler_run = json.loads((run_a / "compiler_run.json").read_text(encoding="utf-8"))
    report = {
        "schema": "Tianxia.CAT3.DeterminismEvidence.v1",
        "result": "PASS",
        "clean_output_roots": [str(run_a), str(run_b)],
        "file_count_each": len(a_files),
        "byte_identical_run_a_to_run_b": True,
        "byte_identical_to_checked_in_generated_authority": True,
        "registry_commitment_sha256": compiler_run["registry_commitment_sha256"],
        "files": a_files,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
