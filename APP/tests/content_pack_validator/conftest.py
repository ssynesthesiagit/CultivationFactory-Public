from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[2]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.insert(0, str(OVERLAY_ROOT))

from tools.content_pack_validator import ValidationOptions


@pytest.fixture(scope="session")
def overlay_root() -> Path:
    return OVERLAY_ROOT


@pytest.fixture(scope="session")
def fixture_root(overlay_root: Path) -> Path:
    return overlay_root / "fixtures" / "content_pack_validator"


@pytest.fixture(scope="session")
def registry_path(fixture_root: Path) -> Path:
    return fixture_root / "primitive_registry.valid.json"


@pytest.fixture
def options(registry_path: Path) -> ValidationOptions:
    return ValidationOptions(primitive_registry=registry_path)


@pytest.fixture
def copied_valid_pack(tmp_path: Path, fixture_root: Path) -> Path:
    destination = tmp_path / "pack"
    shutil.copytree(fixture_root / "valid" / "minimal_pack", destination)
    return destination


def rebuild_checksums(pack: Path) -> None:
    rows = []
    for path in sorted(item for item in pack.rglob("*") if item.is_file() and item.name != "SHA256SUMS.txt"):
        relative = path.relative_to(pack).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {relative}\n")
    (pack / "SHA256SUMS.txt").write_text("".join(rows), encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
