from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

from app.core import FoundryError


SECRET_ENVIRONMENT_VARIABLE = "API_PROVIDER_API_KEY"
LEGACY_SECRET_ENVIRONMENT_VARIABLE = "DEEPSEEK_API_KEY"
SECRET_FILENAME = "api_provider_key.dpapi"
LEGACY_SECRET_FILENAME = "deepseek_api_key.dpapi"
DPAPI_ENTROPY = b"TianxiaCharacterFoundry.DeepSeek.Stage1.v1"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecretStore(Protocol):
    def set(self, value: str, provider_id: str | None = None) -> None: ...
    def get(self, provider_id: str | None = None) -> str | None: ...
    def delete(self, provider_id: str | None = None) -> bool: ...
    def status(self, provider_id: str | None = None) -> dict[str, object]: ...


def validate_api_key(value: str) -> str:
    key = str(value or "").strip()
    if len(key) < 8 or len(key) > 512 or any(char.isspace() for char in key):
        raise FoundryError(
            "AI_PROVIDER_API_KEY_INVALID",
            "The API key must be 8-512 non-whitespace characters.",
        )
    return key


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _input_blob(value: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _windows_crypto():
    """Load DPAPI with explicit signatures instead of ctypes' unsafe defaults."""
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_pointer = ctypes.POINTER(_DataBlob)
    crypt32.CryptProtectData.argtypes = [
        blob_pointer,
        wintypes.LPCWSTR,
        blob_pointer,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        blob_pointer,
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        blob_pointer,
        ctypes.POINTER(wintypes.LPWSTR),
        blob_pointer,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        blob_pointer,
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _crypt_protect(value: bytes) -> bytes:
    if os.name != "nt":
        raise FoundryError(
            "AI_PROVIDER_SECRET_PERSISTENCE_UNAVAILABLE",
            "Saved API keys require Windows DPAPI. Use the selected provider environment variable for an ephemeral key on this platform.",
        )
    crypt32, kernel32 = _windows_crypto()
    source, source_buffer = _input_blob(value)
    entropy, entropy_buffer = _input_blob(DPAPI_ENTROPY)
    target = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(source),
        "Tianxia Character Foundry DeepSeek key",
        ctypes.byref(entropy),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(target),
    )
    _ = (source_buffer, entropy_buffer)
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def _crypt_unprotect(value: bytes) -> bytes:
    if os.name != "nt":
        raise FoundryError(
            "AI_PROVIDER_SECRET_PERSISTENCE_UNAVAILABLE",
            "Saved API keys require Windows DPAPI.",
        )
    crypt32, kernel32 = _windows_crypto()
    source, source_buffer = _input_blob(value)
    entropy, entropy_buffer = _input_blob(DPAPI_ENTROPY)
    target = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        ctypes.byref(entropy),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(target),
    )
    _ = (source_buffer, entropy_buffer)
    if not ok:
        raise FoundryError(
            "AI_PROVIDER_API_KEY_DECRYPT_FAILED",
            "The saved API key cannot be decrypted by this Windows user account.",
        )
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


class APIProviderSecretStore:
    def __init__(self, data_dir: Path):
        self.directory = data_dir.resolve() / "secrets"
        self.path = self.directory / SECRET_FILENAME
        self.legacy_path = self.directory / LEGACY_SECRET_FILENAME

    def set(self, value: str, provider_id: str | None = None) -> None:
        key = validate_api_key(value)
        protected = _crypt_protect(key.encode("utf-8"))
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".new")
        temporary.write_bytes(protected)
        os.replace(temporary, self.path)

    def get(self, provider_id: str | None = None) -> str | None:
        path = self.path if self.path.is_file() else self.legacy_path
        if path.is_file():
            try:
                return validate_api_key(_crypt_unprotect(path.read_bytes()).decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise FoundryError(
                    "AI_PROVIDER_API_KEY_DECRYPT_FAILED",
                    "The saved API key is not valid UTF-8 after decryption.",
                ) from exc
        environment = (
            os.getenv({"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}.get(provider_id or "", ""))
            or os.getenv(SECRET_ENVIRONMENT_VARIABLE)
            or (os.getenv(LEGACY_SECRET_ENVIRONMENT_VARIABLE) if provider_id in (None, "deepseek") else None)
        )
        return validate_api_key(environment) if environment else None

    def delete(self, provider_id: str | None = None) -> bool:
        removed = False
        for path in (self.path, self.legacy_path):
            if path.exists():
                path.unlink()
                removed = True
        return removed

    def status(self, provider_id: str | None = None) -> dict[str, object]:
        persisted = self.path.is_file() or self.legacy_path.is_file()
        environment_name = {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}.get(provider_id or "")
        environment_name = environment_name or SECRET_ENVIRONMENT_VARIABLE
        environment = bool(os.getenv(environment_name)) or (provider_id in (None, "deepseek") and bool(os.getenv(LEGACY_SECRET_ENVIRONMENT_VARIABLE)))
        return {
            "present": persisted or environment,
            "source": "windows_dpapi" if persisted else ("environment" if environment else None),
            "persistent": persisted,
            "environment_variable": environment_name,
        }


# Historical imports and the accepted DeepSeek DPAPI file remain supported.
DeepSeekSecretStore = APIProviderSecretStore


class InMemorySecretStore:
    """Tests only: never selected by the application runtime."""

    def __init__(self, value: str | None = None):
        self.value = validate_api_key(value) if value else None

    def set(self, value: str, provider_id: str | None = None) -> None:
        self.value = validate_api_key(value)

    def get(self, provider_id: str | None = None) -> str | None:
        return self.value

    def delete(self, provider_id: str | None = None) -> bool:
        present = self.value is not None
        self.value = None
        return present

    def status(self, provider_id: str | None = None) -> dict[str, object]:
        return {
            "present": self.value is not None,
            "source": "in_memory_test" if self.value is not None else None,
            "persistent": False,
            "environment_variable": None,
        }
