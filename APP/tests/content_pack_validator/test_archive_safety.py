from __future__ import annotations

import shutil
import stat
from pathlib import Path
import zipfile
import warnings

import pytest

from tools.content_pack_validator import validate_content_pack


def _copy_valid_zip_members(fixture_root: Path, target: zipfile.ZipFile) -> None:
    with zipfile.ZipFile(fixture_root / "valid" / "minimal_pack.zip") as source:
        for info in source.infolist():
            target.writestr(info, source.read(info))


def test_exact_duplicate_zip_path_is_rejected(tmp_path: Path, fixture_root: Path, options) -> None:
    path = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as archive:
            _copy_valid_zip_members(fixture_root, archive)
            archive.writestr("Tianxia_Content_Pack/pack.json", b"{}")
    result = validate_content_pack(path, options)
    assert "ARCHIVE_DUPLICATE_PATH" in {row.code for row in result.diagnostics}


def test_zip_symbolic_link_is_rejected(tmp_path: Path, fixture_root: Path, options) -> None:
    path = tmp_path / "link.zip"
    with zipfile.ZipFile(path, "w") as archive:
        _copy_valid_zip_members(fixture_root, archive)
        info = zipfile.ZipInfo("Tianxia_Content_Pack/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "pack.json")
    result = validate_content_pack(path, options)
    assert "ZIP_SYMBOLIC_LINK" in {row.code for row in result.diagnostics}


def test_zip_special_file_is_rejected(tmp_path: Path, fixture_root: Path, options) -> None:
    path = tmp_path / "special.zip"
    with zipfile.ZipFile(path, "w") as archive:
        _copy_valid_zip_members(fixture_root, archive)
        info = zipfile.ZipInfo("Tianxia_Content_Pack/fifo")
        info.create_system = 3
        info.external_attr = (stat.S_IFIFO | 0o644) << 16
        archive.writestr(info, b"")
    result = validate_content_pack(path, options)
    assert "ZIP_SPECIAL_FILE" in {row.code for row in result.diagnostics}


def test_directory_symlink_is_rejected(tmp_path: Path, fixture_root: Path, options) -> None:
    pack = tmp_path / "pack"
    shutil.copytree(fixture_root / "valid" / "minimal_pack", pack)
    try:
        (pack / "link").symlink_to(pack / "pack.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    result = validate_content_pack(pack, options)
    assert "DIRECTORY_SYMBOLIC_LINK" in {row.code for row in result.diagnostics}


def test_resource_limit_fails_before_zip_decompression(fixture_root: Path, registry_path: Path) -> None:
    from tools.content_pack_validator import ValidationOptions

    result = validate_content_pack(
        fixture_root / "valid" / "minimal_pack.zip",
        ValidationOptions(
            primitive_registry=registry_path,
            maximum_uncompressed_bytes=10,
            maximum_single_file_bytes=10,
        ),
    )
    codes = {row.code for row in result.diagnostics}
    assert "ZIP_RESOURCE_LIMIT_BLOCKED" in codes
    assert result.verdict == "BLOCKED"


def test_encrypted_member_flag_is_rejected(tmp_path: Path, options) -> None:
    import struct

    path = tmp_path / "encrypted.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("pack.json", b"{}")
    data = bytearray(path.read_bytes())
    local = data.find(b"PK\x03\x04")
    central = data.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    local_flags = struct.unpack_from("<H", data, local + 6)[0] | 0x1
    central_flags = struct.unpack_from("<H", data, central + 8)[0] | 0x1
    struct.pack_into("<H", data, local + 6, local_flags)
    struct.pack_into("<H", data, central + 8, central_flags)
    path.write_bytes(data)
    result = validate_content_pack(path, options)
    assert "ZIP_ENCRYPTED_MEMBER" in {row.code for row in result.diagnostics}


def test_crc_failure_is_rejected(tmp_path: Path, options) -> None:
    import struct

    path = tmp_path / "crc.zip"
    payload = b"0123456789"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("pack.json", payload)
    data = bytearray(path.read_bytes())
    local = data.find(b"PK\x03\x04")
    name_length, extra_length = struct.unpack_from("<HH", data, local + 26)
    offset = local + 30 + name_length + extra_length
    data[offset] ^= 0xFF
    path.write_bytes(data)
    result = validate_content_pack(path, options)
    assert {"ZIP_CRC_FAILURE", "ZIP_CRC_CHECK_FAILED"} & {row.code for row in result.diagnostics}


def test_zip_unsafe_directory_entry_is_rejected(tmp_path: Path, options) -> None:
    path = tmp_path / "unsafe-directory.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../escape/", b"")
        archive.writestr("pack.json", b"{}")
    result = validate_content_pack(path, options)
    assert "ZIP_UNSAFE_PATH" in {row.code for row in result.diagnostics}


def test_directory_casefold_collision_is_rejected(tmp_path: Path, options) -> None:
    pack = tmp_path / "pack"
    (pack / "Records").mkdir(parents=True)
    try:
        (pack / "records").mkdir()
    except FileExistsError:
        pytest.skip("filesystem is case-insensitive")
    (pack / "pack.json").write_text("{}", encoding="utf-8")
    result = validate_content_pack(pack, options)
    assert "ARCHIVE_CASEFOLD_COLLISION" in {row.code for row in result.diagnostics}
