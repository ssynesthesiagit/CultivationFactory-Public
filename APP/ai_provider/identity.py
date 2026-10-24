"""Provider-independent identity binding for the deterministic creative director.

The identity contract intentionally has no transport or provider-service
dependencies.  Hosted identities bind only the saved service label.  A local
identity is stronger: it binds the GGUF and the executable of the one process
that owns the saved loopback listener.  All process inspection is read-only.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat as stat_module
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlsplit


IDENTITY_DOMAIN = "dcc.ai.identity.v1"
HOSTED_MODEL_COMMITMENT_DOMAIN = "dcc.ai.identity.hosted-model.v1"
HOSTED_ADAPTER_CONTRACT_DOMAIN = "dcc.ai.identity.hosted-adapter.v1"
LOCAL_IDENTITY_ASSURANCE = "LOCAL_ARTIFACTS"
SERVICE_LABELED = "SERVICE_LABELED"
LOCAL_PROVIDER_IDS = frozenset({"local", "lemonade"})

PAYLOAD_KEYS = frozenset(
    {
        "provider_kind",
        "provider_id",
        "model_id",
        "model_revision_or_artifact_sha256",
        "provider_adapter_sha256",
    }
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
_SOCKET_LINK = re.compile(r"^socket:\[(\d+)\]$")
_MAX_CMDLINE_BYTES = 1024 * 1024
_MAX_STATUS_BYTES = 128 * 1024
_MAX_PROC_ENTRIES = 131072
_HASH_CHUNK_BYTES = 1024 * 1024

# This is a versioned contract description, not a source-file or endpoint
# hash.  Bumping the contract requires a deliberate identity-domain change.
HOSTED_ADAPTER_CONTRACT = {
    "domain": HOSTED_ADAPTER_CONTRACT_DOMAIN,
    "factory_adapter": "tianxia-foundry.ai-provider-hosted",
    "version": 1,
    "binding": "saved-provider-model-service-label",
    "endpoint_bound": False,
    "credential_bound": False,
}


class IdentityResolutionError(ValueError):
    """Raised when an exact, safe identity cannot be proven."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_domain_value(domain: str, value: Any) -> str:
    return _sha256_bytes(_canonical_json_bytes({"domain": domain, "value": value}))


HOSTED_ADAPTER_CONTRACT_SHA256 = _sha256_bytes(_canonical_json_bytes(HOSTED_ADAPTER_CONTRACT))


def canonical_identity_document(payload: dict[str, str]) -> dict[str, Any]:
    """Return the exact document whose canonical bytes are hashed."""

    return {"domain": IDENTITY_DOMAIN, "payload": dict(payload)}


def hash_identity_payload(payload: dict[str, str]) -> str:
    """Hash ``canonical_json({domain: IDENTITY_DOMAIN, payload})``."""

    _validate_payload(payload)
    return _sha256_bytes(_canonical_json_bytes(canonical_identity_document(payload)))


def _require_text(value: Any, *, field: str, max_length: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length or "\x00" in value:
        raise IdentityResolutionError("AI identity contains an invalid value.")
    return value


def _validate_payload(payload: dict[str, str]) -> None:
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_KEYS:
        raise IdentityResolutionError("AI identity payload shape is invalid.")
    provider_kind = _require_text(payload.get("provider_kind"), field="provider_kind", max_length=32)
    if provider_kind not in {"local", "hosted"}:
        raise IdentityResolutionError("AI identity provider kind is invalid.")
    provider_id = _require_text(payload.get("provider_id"), field="provider_id")
    model_id = _require_text(payload.get("model_id"), field="model_id")
    if _MODEL_ID.fullmatch(provider_id) is None or _MODEL_ID.fullmatch(model_id) is None:
        raise IdentityResolutionError("AI identity identifier is invalid.")
    for field in ("model_revision_or_artifact_sha256", "provider_adapter_sha256"):
        value = payload.get(field)
        if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
            raise IdentityResolutionError("AI identity digest is invalid.")


def make_identity_payload(
    *,
    provider_kind: str,
    provider_id: str,
    model_id: str,
    model_revision_or_artifact_sha256: str,
    provider_adapter_sha256: str,
) -> dict[str, str]:
    """Build and validate the v1 payload with exactly its five required keys."""

    payload = {
        "provider_kind": provider_kind,
        "provider_id": provider_id,
        "model_id": model_id,
        "model_revision_or_artifact_sha256": model_revision_or_artifact_sha256,
        "provider_adapter_sha256": provider_adapter_sha256,
    }
    _validate_payload(payload)
    return payload


def identity_record(payload: dict[str, str], *, identity_assurance: str) -> dict[str, Any]:
    """Return safe identity metadata; no process or transport details escape."""

    _validate_payload(payload)
    digest = hash_identity_payload(payload)
    return {
        "identity_sha256": digest,
        "domain": IDENTITY_DOMAIN,
        "payload": dict(payload),
        "identity_assurance": identity_assurance,
    }


def hosted_model_revision_commitment(provider_id: str, model_id: str) -> str:
    """Commit to the saved hosted provider/model service label only."""

    provider_id = _require_text(provider_id, field="provider_id")
    model_id = _require_text(model_id, field="model_id")
    if _MODEL_ID.fullmatch(provider_id) is None or _MODEL_ID.fullmatch(model_id) is None:
        raise IdentityResolutionError("AI identity identifier is invalid.")
    return _digest_domain_value(
        HOSTED_MODEL_COMMITMENT_DOMAIN,
        {"service_label": {"provider_id": provider_id, "model_id": model_id}},
    )


def build_hosted_identity(provider_id: str, model_id: str) -> dict[str, Any]:
    """Build a deterministic service-labeled identity without endpoint/key data."""

    payload = make_identity_payload(
        provider_kind="hosted",
        provider_id=provider_id,
        model_id=model_id,
        model_revision_or_artifact_sha256=hosted_model_revision_commitment(provider_id, model_id),
        provider_adapter_sha256=HOSTED_ADAPTER_CONTRACT_SHA256,
    )
    return identity_record(payload, identity_assurance=SERVICE_LABELED)


@dataclass(frozen=True)
class _FileStatKey:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


_DIGEST_CACHE: dict[tuple[str, _FileStatKey], str] = {}
_DIGEST_CACHE_LOCK = RLock()


def _file_stat(path: Path) -> _FileStatKey:
    try:
        info = os.stat(path)
    except (OSError, ValueError) as exc:
        raise IdentityResolutionError("AI identity artifact could not be inspected.") from exc
    if not stat_module.S_ISREG(info.st_mode) or info.st_size <= 0:
        raise IdentityResolutionError("AI identity artifact is not a regular non-empty file.")
    return _FileStatKey(
        device=int(info.st_dev),
        inode=int(info.st_ino),
        size=int(info.st_size),
        mtime_ns=int(getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))),
        ctime_ns=int(getattr(info, "st_ctime_ns", int(info.st_ctime * 1_000_000_000))),
    )


def _hash_regular_file(path: Path) -> str:
    """Hash a regular file in bounded chunks and cache by its full stat tuple."""

    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise IdentityResolutionError("AI identity artifact path is invalid.") from exc
    resolved = str(path)
    for _ in range(2):
        before = _file_stat(path)
        cache_key = (resolved, before)
        with _DIGEST_CACHE_LOCK:
            cached = _DIGEST_CACHE.get(cache_key)
            if cached is not None:
                return cached
            digest = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
                        digest.update(chunk)
            except (OSError, ValueError) as exc:
                raise IdentityResolutionError("AI identity artifact could not be read.") from exc
            after = _file_stat(path)
            if before != after:
                continue
            result = digest.hexdigest()
            _DIGEST_CACHE[cache_key] = result
            return result
    raise IdentityResolutionError("AI identity artifact changed while it was being hashed.")


def _endpoint_port(endpoint: str, *, proc_root: Path) -> tuple[str, int]:
    del proc_root  # Kept in the signature for one consistent injectable seam.
    value = str(endpoint or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise IdentityResolutionError("Saved local endpoint is invalid.") from exc
    hostname = (parsed.hostname or "").rstrip(".").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise IdentityResolutionError("Saved local endpoint is invalid.") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65535
    ):
        raise IdentityResolutionError("Saved local endpoint is invalid.")
    return hostname, port


def _decode_ipv4(value: str) -> str:
    try:
        if len(value) != 8:
            raise ValueError
        return str(ipaddress.IPv4Address(bytes.fromhex(value)[::-1]))
    except (ValueError, TypeError) as exc:
        raise IdentityResolutionError("Local socket table shape is unsupported.") from exc


def _decode_ipv6(value: str) -> str:
    try:
        if len(value) != 32:
            raise ValueError
        raw = bytes.fromhex(value)
        # Linux prints each four-byte IPv6 word in host byte order.
        normalized = b"".join(raw[offset : offset + 4][::-1] for offset in range(0, 16, 4))
        return str(ipaddress.IPv6Address(normalized))
    except (ValueError, TypeError) as exc:
        raise IdentityResolutionError("Local socket table shape is unsupported.") from exc


def _socket_table_inodes(proc_root: Path, *, hostname: str, port: int) -> dict[str, int]:
    wanted_hosts: set[str]
    if hostname == "localhost":
        wanted_hosts = {"127.0.0.1", "::1"}
    else:
        wanted_hosts = {hostname}
    inodes: dict[str, int] = {}
    tables: tuple[tuple[str, Callable[[str], str]], ...] = (("tcp", _decode_ipv4), ("tcp6", _decode_ipv6))
    for table_name, decoder in tables:
        table_path = proc_root / "net" / table_name
        try:
            lines = table_path.read_text(encoding="ascii").splitlines()
        except (OSError, UnicodeError) as exc:
            raise IdentityResolutionError("Local socket table is unavailable.") from exc
        if len(lines) > _MAX_PROC_ENTRIES:
            raise IdentityResolutionError("Local socket table is too large.")
        for line in lines:
            fields = line.split()
            if not fields:
                continue
            if fields[0].lower() == "sl":
                continue
            if len(fields) < 10:
                raise IdentityResolutionError("Local socket table shape is unsupported.")
            local = fields[1]
            try:
                address_hex, port_hex = local.rsplit(":", 1)
                local_port = int(port_hex, 16)
            except (ValueError, AttributeError) as exc:
                raise IdentityResolutionError("Local socket table shape is unsupported.") from exc
            address = decoder(address_hex)
            state = fields[3].upper()
            inode = fields[9]
            address_matches = address in wanted_hosts
            if not address_matches and hostname in {"127.0.0.1", "localhost"}:
                try:
                    parsed_address = ipaddress.ip_address(address)
                    address_matches = parsed_address == ipaddress.IPv4Address("127.0.0.1")
                    if isinstance(parsed_address, ipaddress.IPv6Address):
                        address_matches = parsed_address.ipv4_mapped == ipaddress.IPv4Address("127.0.0.1")
                except ValueError:
                    address_matches = False
            if state != "0A" or local_port != port or not address_matches:
                continue
            if not inode.isdigit() or int(inode) <= 0:
                raise IdentityResolutionError("Local socket table shape is unsupported.")
            try:
                socket_uid = int(fields[7], 10)
            except (TypeError, ValueError) as exc:
                raise IdentityResolutionError("Local socket table shape is unsupported.") from exc
            if socket_uid < 0:
                raise IdentityResolutionError("Local socket table shape is unsupported.")
            previous_uid = inodes.get(inode)
            if previous_uid is not None and previous_uid != socket_uid:
                raise IdentityResolutionError("Local socket ownership is ambiguous.")
            inodes[inode] = socket_uid
    if not inodes:
        raise IdentityResolutionError("No exact local listener could be proven.")
    if len(inodes) != 1:
        raise IdentityResolutionError("Multiple local listeners matched the saved endpoint.")
    return inodes


def _numeric_children(path: Path) -> list[Path]:
    try:
        children = list(path.iterdir())
    except (OSError, ValueError) as exc:
        raise IdentityResolutionError("Local process ownership could not be inspected.") from exc
    if len(children) > _MAX_PROC_ENTRIES:
        raise IdentityResolutionError("Local process tree is too large.")
    return [child for child in children if child.name.isdigit()]


def _read_status_uids(pid_path: Path) -> set[int] | None:
    """Read Linux's four Uid values, returning None when they cannot prove ownership."""

    try:
        with (pid_path / "status").open("rb") as stream:
            raw = stream.read(_MAX_STATUS_BYTES + 1)
    except (OSError, ValueError):
        return None
    if not raw or len(raw) > _MAX_STATUS_BYTES:
        return None
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    matches = [line.split() for line in text.splitlines() if line.startswith("Uid:")]
    if len(matches) != 1 or len(matches[0]) != 5:
        return None
    try:
        values = [int(value, 10) for value in matches[0][1:]]
    except (TypeError, ValueError):
        return None
    if any(value < 0 for value in values):
        return None
    return set(values)


def _effective_uid() -> int:
    try:
        value = int(os.geteuid())
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise IdentityResolutionError("Local process ownership could not be proven.") from exc
    if value < 0:
        raise IdentityResolutionError("Local process ownership could not be proven.")
    return value


def _socket_owner(proc_root: Path, inode: str, *, owner_uid: int | None = None) -> tuple[Path, Path]:
    owner_uid = _effective_uid() if owner_uid is None else owner_uid
    owners: dict[Path, Path] = {}
    for pid_path in _numeric_children(proc_root):
        status_uids = _read_status_uids(pid_path)
        status_matches = status_uids is not None and owner_uid in status_uids
        if status_uids is not None and not status_matches:
            # A readable, different-UID process cannot own this owner-launched
            # socket.  Its fd tree may intentionally be inaccessible.
            continue
        fd_path = pid_path / "fd"
        try:
            fds = list(fd_path.iterdir())
        except FileNotFoundError:
            continue
        except (PermissionError, OSError, ValueError):
            # A process whose fd table cannot be read cannot be shown to own
            # this socket, and it cannot be shown not to.  It used to abort the
            # whole proof when it ran as the owner's UID; on an ordinary desktop
            # that is always the case -- Omarchy's session launcher wrappers,
            # (sd-pam) and a transient systemctl are all same-UID and all
            # non-dumpable -- so the proof could never succeed and the
            # controller route was refused for every local model.  Skip the
            # process instead.  The requirement that exactly one visible
            # process holds the socket is still enforced below.
            continue
        if len(fds) > _MAX_PROC_ENTRIES:
            raise IdentityResolutionError("Local process fd tree is too large.")
        for fd in fds:
            if not fd.name.isdigit():
                continue
            try:
                link = os.readlink(fd)
            except FileNotFoundError:
                continue
            except (PermissionError, OSError, ValueError):
                # Same reasoning as above for a single unreadable descriptor.
                continue
            match = _SOCKET_LINK.fullmatch(link)
            if match is not None and match.group(1) == inode:
                if not status_matches:
                    # A matching fd without a valid same-UID status record is
                    # a candidate whose ownership cannot be proven.
                    raise IdentityResolutionError("Local socket ownership could not be proven.")
                owners.setdefault(pid_path, fd)
                if len(owners) > 1:
                    raise IdentityResolutionError("Local socket ownership is ambiguous.")
    if len(owners) != 1:
        raise IdentityResolutionError("Local socket ownership could not be proven.")
    owner = next(iter(owners))
    # Return one matching fd while ownership itself is deduplicated by PID.
    return owner, owners[owner]


def _read_cmdline(pid_path: Path) -> list[str]:
    try:
        raw = (pid_path / "cmdline").read_bytes()
    except (OSError, ValueError) as exc:
        raise IdentityResolutionError("Local process arguments could not be read.") from exc
    if not raw or len(raw) > _MAX_CMDLINE_BYTES:
        raise IdentityResolutionError("Local process arguments are invalid.")
    values = raw.split(b"\x00")
    if values and values[-1] == b"":
        values.pop()
    if not values or any(not value for value in values):
        raise IdentityResolutionError("Local process arguments are invalid.")
    try:
        return [value.decode("utf-8") for value in values]
    except UnicodeDecodeError as exc:
        raise IdentityResolutionError("Local process arguments are invalid.") from exc


def _flag_value(argv: list[str], names: set[str], *, required: bool = True) -> str | None:
    matches: list[str] = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument in names:
            if index + 1 >= len(argv) or not argv[index + 1] or argv[index + 1].startswith("-"):
                raise IdentityResolutionError("Local process arguments are invalid.")
            matches.append(argv[index + 1])
            index += 2
            continue
        equal_name = next((name for name in names if argument.startswith(name + "=")), None)
        if equal_name is not None:
            value = argument[len(equal_name) + 1 :]
            if not value:
                raise IdentityResolutionError("Local process arguments are invalid.")
            matches.append(value)
        index += 1
    if required and len(matches) != 1:
        raise IdentityResolutionError("Local process arguments are missing an exact model or alias.")
    if len(matches) > 1:
        raise IdentityResolutionError("Local process arguments are ambiguous.")
    return matches[0] if matches else None


def _absolute_regular_path(value: str, *, suffix: str | None = None) -> Path:
    try:
        candidate = Path(value)
        if not candidate.is_absolute():
            raise IdentityResolutionError("Local process artifact path is not absolute.")
        resolved = candidate.resolve(strict=True)
    except IdentityResolutionError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise IdentityResolutionError("Local process artifact path is invalid.") from exc
    if suffix is not None and resolved.suffix.lower() != suffix.lower():
        raise IdentityResolutionError("Local model artifact is not GGUF.")
    _file_stat(resolved)
    return resolved


def _resolve_local_artifacts(endpoint: str, model_id: str, *, proc_root: str | os.PathLike[str] = "/proc") -> tuple[str, str]:
    if not isinstance(model_id, str) or _MODEL_ID.fullmatch(model_id) is None:
        raise IdentityResolutionError("Local model ID is invalid.")
    if sys.platform != "linux" or os.name != "posix":
        raise IdentityResolutionError("Exact local identity is unsupported on this operating system.")
    proc_path = Path(proc_root)
    hostname, port = _endpoint_port(endpoint, proc_root=proc_path)
    socket_inodes = _socket_table_inodes(proc_path, hostname=hostname, port=port)
    inode, socket_uid = next(iter(socket_inodes.items()))
    effective_uid = _effective_uid()
    if socket_uid != effective_uid:
        raise IdentityResolutionError("Local socket ownership could not be proven.")
    pid_path, _fd_path = _socket_owner(proc_path, inode, owner_uid=effective_uid)
    argv = _read_cmdline(pid_path)
    model_arg = _flag_value(argv, {"--model", "-m"})
    alias = _flag_value(argv, {"--alias"})
    if alias != model_id:
        raise IdentityResolutionError("Local process alias does not match the saved model ID.")
    model_path = _absolute_regular_path(model_arg or "", suffix=".gguf")
    try:
        executable_target = os.readlink(pid_path / "exe")
    except (OSError, ValueError) as exc:
        raise IdentityResolutionError("Local process executable could not be read.") from exc
    executable_path = _absolute_regular_path(executable_target)
    return _hash_regular_file(model_path), _hash_regular_file(executable_path)


def build_local_identity(
    provider_id: str,
    model_id: str,
    endpoint: str,
    *,
    proc_root: str | os.PathLike[str] = "/proc",
) -> dict[str, Any]:
    """Build a local artifact-bound identity using only read-only inspection."""

    if provider_id not in LOCAL_PROVIDER_IDS:
        raise IdentityResolutionError("Local identity provider is invalid.")
    model_digest, executable_digest = _resolve_local_artifacts(endpoint, model_id, proc_root=proc_root)
    payload = make_identity_payload(
        provider_kind="local",
        provider_id=provider_id,
        model_id=model_id,
        model_revision_or_artifact_sha256=model_digest,
        provider_adapter_sha256=executable_digest,
    )
    return identity_record(payload, identity_assurance=LOCAL_IDENTITY_ASSURANCE)


def derive_provider_identity(
    provider_id: str,
    model_id: str,
    *,
    endpoint: str | None = None,
    proc_root: str | os.PathLike[str] = "/proc",
) -> dict[str, Any]:
    """Derive either an artifact-bound local or service-labeled hosted record."""

    if provider_id in LOCAL_PROVIDER_IDS:
        return build_local_identity(provider_id, model_id, endpoint or "", proc_root=proc_root)
    return build_hosted_identity(provider_id, model_id)


# Explicit aliases make the narrow seam easy to discover without duplicating
# any implementation or exposing internal process metadata.
canonical_payload = make_identity_payload
identity_sha256 = hash_identity_payload
derive_local_identity = build_local_identity
derive_hosted_identity = build_hosted_identity


__all__ = [
    "HOSTED_ADAPTER_CONTRACT_SHA256",
    "HOSTED_MODEL_COMMITMENT_DOMAIN",
    "IDENTITY_DOMAIN",
    "IdentityResolutionError",
    "LOCAL_IDENTITY_ASSURANCE",
    "PAYLOAD_KEYS",
    "SERVICE_LABELED",
    "build_hosted_identity",
    "build_local_identity",
    "canonical_identity_document",
    "canonical_payload",
    "derive_hosted_identity",
    "derive_local_identity",
    "derive_provider_identity",
    "hash_identity_payload",
    "hosted_model_revision_commitment",
    "identity_record",
    "identity_sha256",
    "make_identity_payload",
]
