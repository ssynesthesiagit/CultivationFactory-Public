from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import APP_ROOT, utc_now, write_json


INTENTIONALLY_INVALID_PARTS = {"fixtures", "content_pack_validator", "invalid"}


def is_intentionally_invalid(path: Path) -> bool:
    parts = set(path.relative_to(APP_ROOT).parts)
    return INTENTIONALLY_INVALID_PARTS.issubset(parts)


def load_json(path: Path) -> object:
    # json.loads(bytes) performs the RFC-compatible UTF-8/16/32 BOM and null-pattern
    # detection that the accepted Windows self-check evidence requires.
    return json.loads(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parse_errors: list[dict[str, str]] = []
    schema_errors: list[dict[str, str]] = []
    parsed = 0
    schemas = 0
    for path in sorted(APP_ROOT.rglob("*.json")):
        if is_intentionally_invalid(path):
            continue
        relative = path.relative_to(APP_ROOT).as_posix()
        try:
            value = load_json(path)
            parsed += 1
        except Exception as exc:
            parse_errors.append({"path": relative, "error": str(exc)})
            continue
        lower = path.name.lower()
        if ".schema." in lower or lower.endswith(".schema.json"):
            schemas += 1
            try:
                from jsonschema.validators import validator_for

                validator_for(value).check_schema(value)
            except Exception as exc:
                schema_errors.append({"path": relative, "error": str(exc)})
    report = {
        "schema": "Tianxia.CI1P1.JsonSchemaValidation.v1",
        "validated_at_utc": utc_now(),
        "status": "PASS" if not parse_errors and not schema_errors else "PRODUCT_FAILURE",
        "parsed_json_files": parsed,
        "checked_schema_files": schemas,
        "excluded_intentionally_invalid_fixture_root": "fixtures/content_pack_validator/invalid",
        "parse_errors": parse_errors,
        "schema_errors": schema_errors,
    }
    write_json(args.output.resolve(), report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
