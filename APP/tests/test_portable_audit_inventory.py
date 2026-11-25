"""Synthetic container checks; this fixture is not a playable character."""
import io
import struct
import zipfile

import pytest

from app.core import FoundryError, canonical_json, sha256_bytes, sha256_json
from portable_character.service import (
    GM_VIEW_NAME, LEGACY_GM_MODEL_NAME, PORTABLE_SCHEMA, PROJECT_MEMBER,
    PortableCharacterPackageService,
)


def package(path, *, payload=b"synthetic source bytes", bad_hash=None, directory=False):
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as inner:
        inner.writestr("manifest.json", canonical_json({"project_id": "synthetic"}))
        inner.writestr("project.json", canonical_json({"revision": 1}))
    manifest = {"schema_version": PORTABLE_SCHEMA, "project_id": "synthetic", "project_revision": 1,
                "canonical_project_export": PROJECT_MEMBER,
                "canonical_project_export_sha256": sha256_bytes(nested.getvalue())}
    files = {
        "PACKAGE_MANIFEST.json": canonical_json(manifest).encode(),
        "READINESS.json": b"{}",
        LEGACY_GM_MODEL_NAME: canonical_json({"schema_version": "Tianxia_GM_Character_Model_v1"}).encode(),
        GM_VIEW_NAME: b"{}",
        PROJECT_MEMBER: nested.getvalue(),
        "source/payload.bin": payload,
    }
    files["SHA256SUMS.txt"] = "".join(
        f"{('0' * 64 if name == bad_hash else sha256_bytes(body))}  {name}\n"
        for name, body in sorted(files.items())
    ).encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if directory:
            archive.writestr("source/", b"")
        for name, body in files.items():
            archive.writestr(name, body)
    return files


@pytest.mark.parametrize("directory", [False, True])
def test_inventory_hashes_the_exact_verified_bytes_including_ledger(tmp_path, directory):
    path = tmp_path / "synthetic.zip"
    files = package(path, directory=directory)
    audited = PortableCharacterPackageService._audit_uncached(path)
    inventory = audited["member_inventory"]
    assert audited["valid"] is True
    assert [row["name"] for row in inventory] == sorted(files)
    assert {row["name"]: row["sha256"] for row in inventory} == {
        name: sha256_bytes(body) for name, body in files.items()
    }
    assert {row["name"]: row["bytes"] for row in inventory} == {
        name: len(body) for name, body in files.items()
    }
    assert audited["member_inventory_sha256"] == sha256_json(inventory)
    assert audited["crc_validation"] == {"status": "VALID", "member_count": len(files), "failed_member": None}
    assert audited["checksum_count"] == len(files) - 1


@pytest.mark.parametrize("member", ["source/payload.bin", "READINESS.json", "PACKAGE_MANIFEST.json", PROJECT_MEMBER])
def test_each_payload_is_verified_before_acceptance(tmp_path, member):
    path = tmp_path / "bad-hash.zip"
    files = package(path, bad_hash=member)
    with pytest.raises(FoundryError) as raised:
        PortableCharacterPackageService._audit_uncached(path)
    assert raised.value.code == "PORTABLE_CHARACTER_MEMBER_HASH_MISMATCH"
    assert raised.value.details == {"member": member, "expected": "0" * 64,
                                    "actual": sha256_bytes(files[member])}


def test_crc_diagnostic_still_precedes_payload_interpretation(tmp_path):
    path = tmp_path / "bad-crc.zip"
    package(path)
    # Alter the uncompressed payload but keep a valid deflate stream by making
    # a new stored archive. Its recorded CRC then becomes inconsistent.
    with zipfile.ZipFile(path) as archive:
        files = {row.filename: archive.read(row) for row in archive.infolist()}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("source/payload.bin")
    data = bytearray(path.read_bytes())
    name_len, extra_len = struct.unpack_from("<HH", data, info.header_offset + 26)
    start = info.header_offset + 30 + name_len + extra_len
    data[start] ^= 1
    path.write_bytes(data)
    with pytest.raises(FoundryError) as raised:
        PortableCharacterPackageService._audit_uncached(path)
    assert raised.value.code == "PORTABLE_CHARACTER_CRC_FAILED"
    assert raised.value.details == {"member": "source/payload.bin"}
