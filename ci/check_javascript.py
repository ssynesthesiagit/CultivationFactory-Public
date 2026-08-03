from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from common import APP_ROOT, utc_now, write_json


JAVASCRIPT_FILES = (
    "static/app.js",
    "static/sphere_talent_logic.js",
    "tests/w1_gm_core_stats_check.js",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for relative in JAVASCRIPT_FILES:
        completed = subprocess.run(
            [args.node, "--check", str(APP_ROOT / relative)],
            cwd=str(APP_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        results.append(
            {
                "path": relative,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
    report = {
        "schema": "Tianxia.CI1P1.JavaScriptSyntax.v1",
        "checked_at_utc": utc_now(),
        "status": "PASS" if all(row["exit_code"] == 0 for row in results) else "PRODUCT_FAILURE",
        "node": args.node,
        "files": results,
    }
    write_json(args.output.resolve(), report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
