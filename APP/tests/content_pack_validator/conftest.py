from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import unicodedata
import zipfile

import pytest

OVERLAY_ROOT = Path(__file__).resolve().parents[2]
if str(OVERLAY_ROOT) not in sys.path:
    sys.path.insert(0, str(OVERLAY_ROOT))

from tools.content_pack_validator import ValidationOptions


@pytest.fixture(scope="session")
def overlay_root() -> Path:
    return OVERLAY_ROOT


ZIP_ROOT = "Tianxia_Content_Pack/"
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def _write_zip(path: Path, members: list[tuple[str, bytes]]) -> None:
    """Deterministic archive: fixed timestamps, sorted input, regular-file members only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)


def _pack_members(pack: Path) -> list[tuple[str, bytes]]:
    return [(ZIP_ROOT + item.relative_to(pack).as_posix(), item.read_bytes())
            for item in sorted(pack.rglob("*")) if item.is_file()]


def build_zip_fixtures(root: Path) -> None:
    """The archive fixtures FIXTURE_INVENTORY.json names, built from the committed directory fixtures.

    The repository ignores *.zip, so the archives were never committed; each one is the matching directory pack
    under a single pack root, and each invalid archive is the minimal pack plus the one unsafe member it is named for.
    """
    minimal = _pack_members(root / "valid" / "minimal_pack")
    _write_zip(root / "valid" / "minimal_pack.zip", minimal)
    _write_zip(root / "valid" / "optional_file_pack.zip", _pack_members(root / "valid" / "optional_file_pack"))
    invalid = root / "invalid_zips"
    _write_zip(invalid / "path_traversal.zip", minimal + [(ZIP_ROOT + "../outside.json", b"{}")])
    _write_zip(invalid / "casefold_collision.zip", minimal + [(ZIP_ROOT + "PACK.json", b"{}")])
    composed = unicodedata.normalize("NFC", "records/caf\u00e9.json")
    _write_zip(invalid / "unicode_normalization_collision.zip", minimal + [
        (ZIP_ROOT + composed, b"{}"), (ZIP_ROOT + unicodedata.normalize("NFD", composed), b"{}")])


@pytest.fixture(scope="session")
def fixture_root(overlay_root: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("cpk1") / "content_pack_validator"
    shutil.copytree(overlay_root / "fixtures" / "content_pack_validator", root)
    build_zip_fixtures(root)
    return root


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
