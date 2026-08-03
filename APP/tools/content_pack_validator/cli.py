from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .models import ValidationOptions
from .validator import validate_content_pack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tianxia-content-pack-validator",
        description=(
            "Validate a local Tianxia candidate declarative content pack without installing, "
            "activating, or mutating it."
        ),
    )
    parser.add_argument("input", type=Path, help="Pack directory or ZIP")
    parser.add_argument("--primitive-registry", type=Path, required=False)
    parser.add_argument("--output", type=Path, required=True, help="New or empty report directory outside the input pack")
    parser.add_argument("--factory-version")
    parser.add_argument("--compiler-version")
    parser.add_argument("--engine-version")
    parser.add_argument("--strict-unknown-files", action="store_true")
    parser.add_argument("--omit-info", action="store_true")
    return parser


def _ensure_safe_output(input_path: Path, output: Path) -> None:
    resolved_input = input_path.resolve()
    resolved_output = output.resolve()
    if resolved_input == resolved_output:
        raise ValueError("output directory must be separate from the input")
    if resolved_input.is_dir() and resolved_input in resolved_output.parents:
        raise ValueError("output directory must not be inside the input pack")
    if resolved_output.exists() and any(resolved_output.iterdir()):
        raise ValueError("output directory must be new or empty")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _ensure_safe_output(args.input, args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    options = ValidationOptions(
        primitive_registry=args.primitive_registry.resolve() if args.primitive_registry else None,
        factory_version=args.factory_version,
        compiler_version=args.compiler_version,
        engine_version=args.engine_version,
        strict_unknown_files=args.strict_unknown_files,
        include_info_diagnostics=not args.omit_info,
    )
    result = validate_content_pack(args.input, options)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, data in sorted(result.artifacts.machine_files().items()):
        (args.output / name).write_bytes(data)
    print(result.verdict)
    print(f"reports={args.output.resolve()}")
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
