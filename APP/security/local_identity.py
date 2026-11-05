from __future__ import annotations

import ctypes
import hashlib
import os
import unicodedata

try:
    import pwd
except ImportError:  # pragma: no cover - Windows has no pwd module.
    pwd = None
from dataclasses import dataclass
from typing import Protocol

from app.core import FoundryError, sha256_json

_RESERVED = {
    "system", "machine", "migration", "planner", "fixture", "stage",
    "service", "automation", "bot", "internal",
}


def _normalized_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Cf")
    return " ".join(normalized.split()).casefold()


def _identity_tokens(value: str) -> set[str]:
    normalized = _normalized_identity(value)
    tokens: list[str] = []
    current: list[str] = []
    for ch in normalized:
        if ch.isalnum():
            current.append(ch)
        elif current:
            tokens.append("".join(current)); current = []
    if current:
        tokens.append("".join(current))
    compact = "".join(ch for ch in normalized if ch.isalnum())
    return set(tokens + ([compact] if compact else []))


def reject_reserved_identity(value: str, *, field_name: str = "local principal identity") -> str:
    normalized = _normalized_identity(value)
    if not normalized:
        raise FoundryError("LOCAL_PRINCIPAL_INVALID", "The local principal identity is empty.")
    tokens = _identity_tokens(normalized)
    matched = sorted({
        reserved
        for reserved in _RESERVED
        if any(token == reserved or (token.startswith(reserved) and token[len(reserved):].isdigit()) for token in tokens)
    })
    if matched:
        raise FoundryError(
            "RESERVED_MACHINE_IDENTITY",
            "Reserved machine identities cannot hold exact human trust or approval authority.",
            details={"field": field_name, "identity": value, "normalized": normalized, "reserved_tokens": matched},
        )
    return str(value).strip()


@dataclass(frozen=True)
class LocalPrincipal:
    principal_id: str
    display_name: str
    provider: str
    security_identifier: str

    def as_dict(self) -> dict[str, str]:
        return {
            "principal_id": self.principal_id,
            "display_name": self.display_name,
            "provider": self.provider,
            "security_identifier": self.security_identifier,
        }

    @property
    def principal_hash(self) -> str:
        return sha256_json(self.as_dict())


class PrincipalProvider(Protocol):
    def current_principal(self) -> LocalPrincipal: ...


def _windows_sid() -> tuple[str, str]:
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_uint, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.GetUserNameW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetUserNameW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    TOKEN_QUERY = 0x0008
    TokenUser = 1
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise OSError(ctypes.get_last_error(), "OpenProcessToken failed")
    try:
        needed = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(needed))
        buf = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(token, TokenUser, buf, needed, ctypes.byref(needed)):
            raise OSError(ctypes.get_last_error(), "GetTokenInformation failed")
        sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        string_sid = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(string_sid)):
            raise OSError(ctypes.get_last_error(), "ConvertSidToStringSidW failed")
        try:
            sid = string_sid.value
        finally:
            kernel32.LocalFree(string_sid)
        size = wintypes.DWORD(0)
        advapi32.GetUserNameW(None, ctypes.byref(size))
        name_buf = ctypes.create_unicode_buffer(size.value + 1)
        if not advapi32.GetUserNameW(name_buf, ctypes.byref(size)):
            raise OSError(ctypes.get_last_error(), "GetUserNameW failed")
        return sid, name_buf.value
    finally:
        kernel32.CloseHandle(token)


class ProcessPrincipalProvider:
    """Server-controlled principal derived from the running process security context."""

    def current_principal(self) -> LocalPrincipal:
        if os.name == "nt":
            sid, display = _windows_sid()
            principal = LocalPrincipal(f"windows-sid:{sid}", display, "windows_process_token", sid)
        else:
            uid = os.geteuid()
            try:
                display = pwd.getpwuid(uid).pw_name if pwd is not None else f"uid-{uid}"
            except Exception:
                display = f"uid-{uid}"
            sid = f"uid:{uid}"
            principal = LocalPrincipal(f"posix-uid:{uid}", display, "posix_effective_uid", sid)
        reject_reserved_identity(principal.display_name)
        return principal




class BoundPrincipalProvider:
    """Freezes one server-derived principal for the lifetime of a service session."""

    def __init__(self, principal: LocalPrincipal):
        self._principal = principal

    def current_principal(self) -> LocalPrincipal:
        return self._principal


class DeterministicTestPrincipalProvider:
    """Explicit test-only provider. Production construction never selects this class."""

    def __init__(self, principal_id: str = "test-principal:local-human", display_name: str = "Local Test Human"):
        self._principal = LocalPrincipal(principal_id, display_name, "deterministic_test_provider", principal_id)
        reject_reserved_identity(display_name)

    def current_principal(self) -> LocalPrincipal:
        return self._principal


__all__ = [
    "LocalPrincipal", "PrincipalProvider", "ProcessPrincipalProvider", "BoundPrincipalProvider",
    "DeterministicTestPrincipalProvider", "reject_reserved_identity",
]
