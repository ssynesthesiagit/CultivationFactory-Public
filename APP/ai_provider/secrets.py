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
PROVIDER_SECRET_FILENAME = "api_provider_key.{provider_id}.dpapi"
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
        # ``path`` is retained as a read-only migration source for the
        # pre-profile store. It is never used for OpenAI or Custom credentials.
        self.path = self.directory / SECRET_FILENAME
        self.legacy_path = self.directory / LEGACY_SECRET_FILENAME

    @staticmethod
    def _provider_id(provider_id: str | None) -> str | None:
        value = str(provider_id or "").strip().casefold()
        return value if value in {"openai", "deepseek", "custom"} else None

    def _provider_path(self, provider_id: str | None) -> Path | None:
        value = self._provider_id(provider_id)
        if value is None:
            return None
        return self.directory / PROVIDER_SECRET_FILENAME.format(provider_id=value)

    @staticmethod
    def _environment_name(provider_id: str | None) -> str | None:
        return {
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "custom": "CUSTOM_API_KEY",
        }.get(str(provider_id or "").strip().casefold())

    def set(self, value: str, provider_id: str | None = None) -> None:
        provider = self._provider_id(provider_id)
        if provider is None:
            raise FoundryError("AI_PROVIDER_PROFILE_INVALID", "A protected API key must be assigned to OpenAI, DeepSeek, or Custom.")
        key = validate_api_key(value)
        protected = _crypt_protect(key.encode("utf-8"))
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self._provider_path(provider)
        assert destination is not None
        temporary = destination.with_name(destination.name + ".new")
        temporary.write_bytes(protected)
        os.replace(temporary, destination)

    def get(self, provider_id: str | None = None) -> str | None:
        provider = self._provider_id(provider_id)
        if provider is None:
            return None
        path = self._provider_path(provider)
        # Historical DPAPI files were DeepSeek-only. The old generic file is
        # also treated as a DeepSeek migration source, never as a credential
        # for a newly selected OpenAI or Custom profile.
        legacy_path = path if path and path.is_file() else None
        if legacy_path is None and provider == "deepseek":
            legacy_path = self.legacy_path if self.legacy_path.is_file() else (self.path if self.path.is_file() else None)
        if legacy_path is not None and legacy_path.is_file():
            try:
                return validate_api_key(_crypt_unprotect(legacy_path.read_bytes()).decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise FoundryError(
                    "AI_PROVIDER_API_KEY_DECRYPT_FAILED",
                    "The saved API key is not valid UTF-8 after decryption.",
                ) from exc
        environment_name = self._environment_name(provider)
        environment = os.getenv(environment_name) if environment_name else None
        return validate_api_key(environment) if environment else None

    def delete(self, provider_id: str | None = None) -> bool:
        provider = self._provider_id(provider_id)
        if provider is None:
            return False
        removed = False
        paths = [self._provider_path(provider)]
        if provider == "deepseek":
            paths.extend((self.legacy_path, self.path))
        for path in paths:
            if path is None:
                continue
            if path.exists():
                path.unlink()
                removed = True
        return removed

    def status(self, provider_id: str | None = None) -> dict[str, object]:
        provider = self._provider_id(provider_id)
        provider_path = self._provider_path(provider)
        persisted = bool(provider_path and provider_path.is_file())
        source = "windows_dpapi" if persisted else None
        if provider == "deepseek" and not persisted:
            persisted = self.legacy_path.is_file() or self.path.is_file()
            source = "windows_dpapi_legacy_deepseek" if persisted else None
        environment_name = self._environment_name(provider)
        environment = bool(os.getenv(environment_name)) if environment_name else False
        return {
            "present": persisted or environment,
            "source": source or ("environment" if environment else None),
            "persistent": persisted,
            "environment_variable": environment_name,
            "provider_id": provider,
        }


# Historical imports and the accepted DeepSeek DPAPI file remain supported.
DeepSeekSecretStore = APIProviderSecretStore


class InMemorySecretStore:
    """Tests only: never selected by the application runtime."""

    def __init__(self, value: str | None = None):
        self.values: dict[str, str] = {}
        self._unbound_value = validate_api_key(value) if value else None

    def set(self, value: str, provider_id: str | None = None) -> None:
        provider = str(provider_id or "").strip().casefold()
        if provider not in {"openai", "deepseek", "custom"}:
            raise FoundryError("AI_PROVIDER_PROFILE_INVALID", "A protected API key must be assigned to a provider profile.")
        self.values[provider] = validate_api_key(value)

    def get(self, provider_id: str | None = None) -> str | None:
        provider = str(provider_id or "").strip().casefold()
        if provider in self.values:
            return self.values[provider]
        if self._unbound_value is not None and provider in {"openai", "deepseek", "custom"}:
            # Test-only compatibility for callers that provide one initial
            # secret before selecting a profile. It is bound once, then never
            # reused by another profile.
            self.values[provider] = self._unbound_value
            self._unbound_value = None
            return self.values[provider]
        return None

    def delete(self, provider_id: str | None = None) -> bool:
        provider = str(provider_id or "").strip().casefold()
        present = provider in self.values
        self.values.pop(provider, None)
        return present

    def status(self, provider_id: str | None = None) -> dict[str, object]:
        provider = str(provider_id or "").strip().casefold()
        if self._unbound_value is not None and provider in {"openai", "deepseek", "custom"}:
            # Bind the test-only constructor value when the application first
            # reports readiness for the selected provider.  This keeps status
            # truthful without making production secret stores infer or copy
            # credentials across provider profiles.
            self.values[provider] = self._unbound_value
            self._unbound_value = None
        return {
            "present": provider in self.values,
            "source": "in_memory_test" if provider in self.values else None,
            "persistent": False,
            "environment_variable": None,
            "provider_id": provider,
        }
