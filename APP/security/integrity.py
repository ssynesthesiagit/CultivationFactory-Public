from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import secrets
import stat
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core import FoundryError, canonical_json, sha256_bytes

INTEGRITY_VERSION = "TianxiaFoundry.KeyedIntegrity.v1"
ALGORITHM = "HMAC-SHA-256"
KEY_BYTES = 32
KEY_FILENAME = "foundry_integrity_key_v1.bin"
KEY_METADATA_FILENAME = "foundry_integrity_key_v1.json"
DPAPI_ENTROPY = b"TianxiaCharacterFoundry.KeyedIntegrity.v1"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class IntegrityKeyProvider(Protocol):
    production_safe: bool
    platform_status: str

    def load_existing(self) -> tuple[str, bytes]: ...
    def load_or_create(self) -> tuple[str, bytes]: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _input_blob(value: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(value)
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _windows_crypto():
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_pointer = ctypes.POINTER(_DataBlob)
    crypt32.CryptProtectData.argtypes = [blob_pointer, wintypes.LPCWSTR, blob_pointer, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_pointer]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [blob_pointer, ctypes.POINTER(wintypes.LPWSTR), blob_pointer, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_pointer]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _protect_windows(value: bytes) -> bytes:
    crypt32, kernel32 = _windows_crypto()
    source, source_buffer = _input_blob(value)
    entropy, entropy_buffer = _input_blob(DPAPI_ENTROPY)
    target = _DataBlob()
    ok = crypt32.CryptProtectData(ctypes.byref(source), "Tianxia Character Foundry integrity key", ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(target))
    _ = (source_buffer, entropy_buffer)
    if not ok:
        raise FoundryError("INTEGRITY_KEY_PROTECTION_FAILED", "Windows DPAPI could not protect the Foundry integrity key.", details={"winerror": ctypes.get_last_error()}, status_code=500)
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def _unprotect_windows(value: bytes) -> bytes:
    crypt32, kernel32 = _windows_crypto()
    source, source_buffer = _input_blob(value)
    entropy, entropy_buffer = _input_blob(DPAPI_ENTROPY)
    target = _DataBlob()
    ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(target))
    _ = (source_buffer, entropy_buffer)
    if not ok:
        raise FoundryError("INTEGRITY_KEY_UNPROTECT_FAILED", "The Foundry integrity key cannot be decrypted by this Windows user.", details={"winerror": ctypes.get_last_error()}, status_code=409)
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


class FileIntegrityKeyProvider:
    """Production provider. The secret is outside SQLite and never exported."""

    production_safe = True

    def __init__(self, data_dir: Path):
        self.directory = data_dir.resolve() / "security"
        self.path = self.directory / KEY_FILENAME
        self.metadata_path = self.directory / KEY_METADATA_FILENAME
        self.platform_status = "windows_dpapi_current_user" if os.name == "nt" else "posix_development_file_0600"

    @staticmethod
    def _key_id(key: bytes) -> str:
        return "integrity-key-v1:" + hashlib.sha256(key).hexdigest()

    def _write(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise FoundryError("INTEGRITY_KEY_INVALID", "The Foundry integrity key has an invalid length.", status_code=500)
        self.directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.directory, 0o700)
        payload = _protect_windows(key) if os.name == "nt" else key
        temporary = self.path.with_name(self.path.name + ".new")
        temporary.write_bytes(payload)
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)
        if os.name != "nt":
            os.chmod(self.path, 0o600)
        metadata = {
            "schema_version": INTEGRITY_VERSION,
            "key_id": self._key_id(key),
            "algorithm": ALGORITHM,
            "platform_status": self.platform_status,
            "secret_in_metadata": False,
        }
        tmp_meta = self.metadata_path.with_name(self.metadata_path.name + ".new")
        tmp_meta.write_text(canonical_json(metadata), encoding="utf-8")
        if os.name != "nt":
            os.chmod(tmp_meta, 0o600)
        os.replace(tmp_meta, self.metadata_path)

    def _read(self) -> tuple[str, bytes]:
        if not self.path.is_file():
            raise FoundryError("INTEGRITY_KEY_MISSING", "The external Foundry integrity key is missing; keyed evidence cannot be trusted.", details={"expected_path": str(self.path)}, status_code=409)
        if os.name != "nt":
            mode = stat.S_IMODE(self.path.stat().st_mode)
            if mode & 0o077:
                raise FoundryError("INTEGRITY_KEY_PERMISSIONS_UNSAFE", "The POSIX development integrity key is not restricted to its owner.", details={"mode": oct(mode)}, status_code=409)
        payload = self.path.read_bytes()
        key = _unprotect_windows(payload) if os.name == "nt" else payload
        if len(key) != KEY_BYTES:
            raise FoundryError("INTEGRITY_KEY_INVALID", "The external Foundry integrity key has an invalid length.", status_code=409)
        key_id = self._key_id(key)
        if self.metadata_path.is_file():
            try:
                metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise FoundryError("INTEGRITY_KEY_METADATA_INVALID", "The external integrity-key metadata is malformed.", details={"error": type(exc).__name__}, status_code=409) from exc
            if metadata.get("key_id") != key_id or metadata.get("algorithm") != ALGORITHM:
                raise FoundryError("INTEGRITY_KEY_METADATA_MISMATCH", "The external key does not match its non-secret metadata.", status_code=409)
        return key_id, key

    def load_existing(self) -> tuple[str, bytes]:
        return self._read()

    def load_or_create(self) -> tuple[str, bytes]:
        if self.path.exists():
            return self._read()
        key = secrets.token_bytes(KEY_BYTES)
        self._write(key)
        return self._key_id(key), key


_TEST_CAPABILITY = object()


class DeterministicTestIntegrityKeyProvider:
    production_safe = False
    platform_status = "deterministic_test_only"

    def __init__(self, key: bytes = b"Tianxia-R4-deterministic-test-key"):
        self._key = hashlib.sha256(key).digest()
        self._key_id = "test-integrity-key:" + hashlib.sha256(self._key).hexdigest()

    def load_existing(self) -> tuple[str, bytes]:
        return self._key_id, self._key

    def load_or_create(self) -> tuple[str, bytes]:
        return self._key_id, self._key


@dataclass(frozen=True)
class IntegrityEnvelope:
    integrity_version: str
    algorithm: str
    key_id: str
    domain: str
    projection_hash: str
    mac: str

    def as_dict(self) -> dict[str, str]:
        return {
            "integrity_version": self.integrity_version,
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "domain": self.domain,
            "projection_hash": self.projection_hash,
            "mac": self.mac,
        }


class IntegrityService:
    def __init__(self, provider: IntegrityKeyProvider, *, _test_capability: object | None = None):
        if not getattr(provider, "production_safe", False) and _test_capability is not _TEST_CAPABILITY:
            raise FoundryError("TEST_INTEGRITY_PROVIDER_FORBIDDEN", "A deterministic integrity provider requires an explicit test-only capability.", status_code=500)
        self.provider = provider

    @classmethod
    def for_database(cls, db) -> "IntegrityService":
        return cls(FileIntegrityKeyProvider(db.settings.data_dir))

    @staticmethod
    def _message(domain: str, projection_json: str, *, key_id: str) -> bytes:
        if not domain or not domain.startswith("tianxia.foundry."):
            raise FoundryError("INTEGRITY_DOMAIN_INVALID", "Keyed integrity requires an explicit Tianxia domain separator.", status_code=500)
        return canonical_json({
            "integrity_version": INTEGRITY_VERSION,
            "algorithm": ALGORITHM,
            "key_id": key_id,
            "domain": domain,
            "projection": json.loads(projection_json),
        }).encode("utf-8")

    def sign(self, domain: str, projection: dict[str, Any]) -> IntegrityEnvelope:
        projection_json = canonical_json(projection)
        key_id, key = self.provider.load_or_create()
        mac = hmac.new(key, self._message(domain, projection_json, key_id=key_id), hashlib.sha256).hexdigest()
        return IntegrityEnvelope(INTEGRITY_VERSION, ALGORITHM, key_id, domain, sha256_bytes(projection_json.encode("utf-8")), mac)

    def verify(self, domain: str, projection: dict[str, Any], envelope: dict[str, Any] | IntegrityEnvelope) -> None:
        env = envelope.as_dict() if isinstance(envelope, IntegrityEnvelope) else dict(envelope)
        required = {"integrity_version", "algorithm", "key_id", "domain", "projection_hash", "mac"}
        missing = sorted(required - set(env))
        if missing:
            raise FoundryError("INTEGRITY_MAC_MISSING", "Keyed integrity evidence is incomplete.", details={"missing": missing}, status_code=409)
        if env["integrity_version"] != INTEGRITY_VERSION or env["algorithm"] != ALGORITHM:
            raise FoundryError("INTEGRITY_MAC_VERSION_UNKNOWN", "The keyed integrity version or algorithm is unsupported.", status_code=409)
        if env["domain"] != domain:
            raise FoundryError("INTEGRITY_MAC_DOMAIN_MISMATCH", "The keyed evidence belongs to another integrity domain.", status_code=409)
        projection_json = canonical_json(projection)
        if env["projection_hash"] != sha256_bytes(projection_json.encode("utf-8")):
            raise FoundryError("INTEGRITY_PROJECTION_HASH_MISMATCH", "The canonical integrity projection differs from its stored hash.", status_code=409)
        key_id, key = self.provider.load_existing()
        if env["key_id"] != key_id:
            raise FoundryError("INTEGRITY_KEY_ID_UNKNOWN", "The keyed evidence references an unavailable or rotated key.", details={"expected": key_id, "actual": env["key_id"]}, status_code=409)
        expected = hmac.new(key, self._message(domain, projection_json, key_id=key_id), hashlib.sha256).hexdigest()
        supplied = str(env["mac"])
        if len(supplied) != 64 or not hmac.compare_digest(expected, supplied):
            raise FoundryError("INTEGRITY_MAC_INVALID", "The keyed integrity MAC is invalid.", status_code=409)


def create_test_integrity_service(key: bytes = b"Tianxia-R4-deterministic-test-key") -> IntegrityService:
    return IntegrityService(DeterministicTestIntegrityKeyProvider(key), _test_capability=_TEST_CAPABILITY)


__all__ = [
    "ALGORITHM", "INTEGRITY_VERSION", "IntegrityEnvelope", "IntegrityKeyProvider", "IntegrityService",
    "FileIntegrityKeyProvider", "DeterministicTestIntegrityKeyProvider", "create_test_integrity_service",
]
