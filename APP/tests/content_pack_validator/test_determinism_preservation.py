from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

from tools.content_pack_validator import validate_content_pack


def _tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    for entry in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(entry.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(entry.read_bytes())
    return digest.hexdigest()


def test_repeated_reports_are_byte_identical(fixture_root: Path, options) -> None:
    pack = fixture_root / "valid" / "minimal_pack.zip"
    first = validate_content_pack(pack, options).artifacts.machine_files()
    second = validate_content_pack(pack, options).artifacts.machine_files()
    assert first == second


def test_directory_input_tree_is_unchanged(fixture_root: Path, options) -> None:
    pack = fixture_root / "valid" / "minimal_pack"
    before = _tree_hash(pack)
    result = validate_content_pack(pack, options)
    after = _tree_hash(pack)
    assert before == after
    assert result.input_preserved is True


def test_cli_writes_only_to_separate_output(tmp_path: Path, fixture_root: Path, registry_path: Path, overlay_root: Path) -> None:
    output = tmp_path / "reports"
    command = [
        sys.executable,
        "-m",
        "tools.content_pack_validator",
        str(fixture_root / "valid" / "minimal_pack.zip"),
        "--primitive-registry",
        str(registry_path),
        "--output",
        str(output),
    ]
    completed = subprocess.run(command, cwd=overlay_root, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert (output / "validation_report.json").is_file()
    assert completed.stdout.splitlines()[0] == "PASS"


def test_cli_blocked_exit_code(tmp_path: Path, fixture_root: Path, registry_path: Path, overlay_root: Path) -> None:
    output = tmp_path / "reports"
    command = [
        sys.executable,
        "-m",
        "tools.content_pack_validator",
        str(fixture_root / "invalid" / "bad_checksum"),
        "--primitive-registry",
        str(registry_path),
        "--output",
        str(output),
    ]
    completed = subprocess.run(command, cwd=overlay_root, capture_output=True, text=True, check=False)
    assert completed.returncode == 2
    assert completed.stdout.splitlines()[0] == "BLOCKED"


def test_cli_rejects_output_inside_input(tmp_path: Path, copied_valid_pack: Path, registry_path: Path, overlay_root: Path) -> None:
    output = copied_valid_pack / "reports"
    command = [
        sys.executable,
        "-m",
        "tools.content_pack_validator",
        str(copied_valid_pack),
        "--primitive-registry",
        str(registry_path),
        "--output",
        str(output),
    ]
    completed = subprocess.run(command, cwd=overlay_root, capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    assert not output.exists()
