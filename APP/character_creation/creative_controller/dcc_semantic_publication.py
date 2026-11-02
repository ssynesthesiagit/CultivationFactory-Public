"""Crash-safe, local publication of the Factory DCC semantic library.

The public entry point is intentionally dry-run by default.  It reads one
immutable SQLite catalogue, builds all detached semantic authority objects in
memory, and only enters the filesystem/lock/activation path when ``publish``
is explicitly true.  The test-only authority-root seam is kept out of the
CLI; production callers always use the checked-in ``APP/authority`` root.

This module contains no provider or network integration.  Publication is a
local authority operation over deterministic, content-addressed JSON.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
import errno
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import quote

from app.core import FoundryError, Settings, canonical_json, sha256_bytes, sha256_file, sha256_json
from app.validation_cache import ValidationResultCache, file_content_key, file_fingerprint

from . import factory_catalog_adapter as _catalog_adapter
from . import semantic_admission as _semantic_admission
from .contracts import (
    CreativeControllerError,
    fail,
    require_digest,
    require_enum,
    require_exact_keys,
    require_identifier,
    require_list,
    require_type,
    validate_self_hash,
)
from .factory_catalog_adapter import (
    FACTORY_CATALOG_PUBLICATION_CANDIDATE_V1_SCHEMA,
    FACTORY_CATALOG_PUBLICATION_CANDIDATE_V1_VERSION,
    FACTORY_CATALOG_PUBLICATION_CANDIDATE_SCHEMA,
    FACTORY_CATALOG_PUBLICATION_CANDIDATE_VERSION,
    SOURCE_RIGHTS_AUTHORITY_TRUST_MANIFEST_SCHEMA,
    _compile_factory_catalog_publication,
    validate_reviewed_semantic_overlay,
)
from .factory_semantic_library import (
    FACTORY_SEMANTIC_ADAPTER_V1_SHA256,
    FACTORY_SEMANTIC_ADAPTER_SHA256,
    build_factory_semantic_library,
)
from .semantic_admission import (
    FACTORY_SEMANTIC_TRUST_MANIFEST_SCHEMA,
    _admit_typed_semantics,
    admit_typed_semantics,
    validate_semantic_authority_bundle,
    validate_semantic_profile_registry,
)
from .content_snapshots import validate_content_snapshot
from non_sphere_authority.service import project_locked_method_catalog_records_from_authority


DCC_SOURCE_RIGHTS_AUTHORITY_V1_SCHEMA = "TianxiaFoundry.DCCSourceRightsAuthority.v1"
DCC_SOURCE_RIGHTS_AUTHORITY_V1_VERSION = 1
DCC_SOURCE_RIGHTS_AUTHORITY_SCHEMA = "TianxiaFoundry.DCCSourceRightsAuthority.v2"
DCC_SOURCE_RIGHTS_AUTHORITY_VERSION = 2
DCC_SOURCE_RIGHTS_AUTHORITY_V3_SCHEMA = "TianxiaFoundry.DCCSourceRightsAuthority.v3"
DCC_SOURCE_RIGHTS_AUTHORITY_V3_VERSION = 3
DCC_SEMANTIC_PUBLICATION_RECEIPT_V1_SCHEMA = "TianxiaFoundry.DCCSemanticPublicationReceipt.v1"
DCC_SEMANTIC_PUBLICATION_RECEIPT_V1_VERSION = 1
DCC_SEMANTIC_PUBLICATION_RECEIPT_SCHEMA = "TianxiaFoundry.DCCSemanticPublicationReceipt.v2"
DCC_SEMANTIC_PUBLICATION_VERSION = 2
DCC_SEMANTIC_PUBLICATION_RECEIPT_V3_SCHEMA = "TianxiaFoundry.DCCSemanticPublicationReceipt.v3"
DCC_SEMANTIC_PUBLICATION_RECEIPT_V3_VERSION = 3

_APP_ROOT = Path(__file__).resolve().parents[2]
_AUTHORITY_ROOT = _APP_ROOT / "authority"
_NON_SPHERE_AUTHORITY_ROOT = _APP_ROOT / "non_sphere_authority" / "authority"
_SOURCE_RIGHTS_AUTHORITY_V1_NAME = "Tianxia_DCC_Source_Rights_Authority_v1.json"
_SOURCE_RIGHTS_AUTHORITY_NAME = "Tianxia_DCC_Source_Rights_Authority_v2.json"
_SOURCE_RIGHTS_AUTHORITY_V3_NAME = "Tianxia_DCC_Source_Rights_Authority_v3.json"
_SOURCE_RIGHTS_TRUST_NAME = "Tianxia_DCC_Source_Rights_Authority_Trust_v1.json"
_SEMANTIC_TRUST_NAME = "Tianxia_DCC_Semantic_Authority_Trust_v1.json"
_SEMANTIC_STORAGE_NAME = "dcc_semantics"
_OBJECTS_NAME = "objects"
_LOCK_NAME = ".publish.lock"
_V3_METHOD_AUTHORITY_INPUT_NAMES = (
    "NS1R_AUTHORITY_IDENTITIES.json",
    "Tianxia_Methods_Typed_Registry_v0_6.json",
)

_ACCEPTED_CONTENT_FAMILIES_V1 = frozenset(
    {
        "background",
        "cultivation_insight",
        "cultivation_method",
        "foundation",
        "origin_insight",
        "path",
        "path_feature",
        "sphere",
        "talent",
    }
)
_EXPECTED_FAMILY_COUNTS_V1 = {
    "background": 31,
    "cultivation_insight": 547,
    "cultivation_method": 80,
    "foundation": 30,
    "origin_insight": 50,
    "path": 3,
    "path_feature": 56,
    "sphere": 85,
    "talent": 2988,
}
_EXPECTED_RECORD_COUNT_V1 = sum(_EXPECTED_FAMILY_COUNTS_V1.values())

_ACCEPTED_CONTENT_FAMILIES = frozenset(
    {
        "background",
        "background_sphere",
        "background_talent",
        "cultivation_insight",
        "cultivation_method",
        "foundation",
        "origin_insight",
        "path",
        "path_feature",
        "sphere",
        "talent",
        "item",
        "subpath",
        "tradition",
    }
)
_EXPECTED_FAMILY_COUNTS = {
    **_EXPECTED_FAMILY_COUNTS_V1,
    "background_sphere": 30,
    "background_talent": 77,
    "item": 318,
    "subpath": 122,
    "tradition": 34,
}
_EXPECTED_RECORD_COUNT = sum(_EXPECTED_FAMILY_COUNTS.values())


@dataclass(frozen=True)
class _PublicationProfile:
    name: str
    descriptor_name: str
    descriptor_schema: str
    descriptor_version: int
    candidate_schema: str
    candidate_version: int
    receipt_schema: str
    receipt_version: int
    accepted_families: frozenset[str]
    family_counts: Mapping[str, int]
    record_count: int
    adapter_sha256: str
    descriptor_driven_counts: bool = False


_PROFILE_V1 = _PublicationProfile(
    name="v1",
    descriptor_name=_SOURCE_RIGHTS_AUTHORITY_V1_NAME,
    descriptor_schema=DCC_SOURCE_RIGHTS_AUTHORITY_V1_SCHEMA,
    descriptor_version=DCC_SOURCE_RIGHTS_AUTHORITY_V1_VERSION,
    candidate_schema=FACTORY_CATALOG_PUBLICATION_CANDIDATE_V1_SCHEMA,
    candidate_version=FACTORY_CATALOG_PUBLICATION_CANDIDATE_V1_VERSION,
    receipt_schema=DCC_SEMANTIC_PUBLICATION_RECEIPT_V1_SCHEMA,
    receipt_version=DCC_SEMANTIC_PUBLICATION_RECEIPT_V1_VERSION,
    accepted_families=_ACCEPTED_CONTENT_FAMILIES_V1,
    family_counts=_EXPECTED_FAMILY_COUNTS_V1,
    record_count=_EXPECTED_RECORD_COUNT_V1,
    adapter_sha256=FACTORY_SEMANTIC_ADAPTER_V1_SHA256,
)
_PROFILE_V2 = _PublicationProfile(
    name="v2",
    descriptor_name=_SOURCE_RIGHTS_AUTHORITY_NAME,
    descriptor_schema=DCC_SOURCE_RIGHTS_AUTHORITY_SCHEMA,
    descriptor_version=DCC_SOURCE_RIGHTS_AUTHORITY_VERSION,
    candidate_schema=FACTORY_CATALOG_PUBLICATION_CANDIDATE_SCHEMA,
    candidate_version=FACTORY_CATALOG_PUBLICATION_CANDIDATE_VERSION,
    receipt_schema=DCC_SEMANTIC_PUBLICATION_RECEIPT_SCHEMA,
    receipt_version=DCC_SEMANTIC_PUBLICATION_VERSION,
    accepted_families=_ACCEPTED_CONTENT_FAMILIES,
    family_counts=_EXPECTED_FAMILY_COUNTS,
    record_count=_EXPECTED_RECORD_COUNT,
    adapter_sha256=FACTORY_SEMANTIC_ADAPTER_SHA256,
)
_PROFILE_V3 = _PublicationProfile(
    name="v3",
    descriptor_name=_SOURCE_RIGHTS_AUTHORITY_V3_NAME,
    descriptor_schema=DCC_SOURCE_RIGHTS_AUTHORITY_V3_SCHEMA,
    descriptor_version=DCC_SOURCE_RIGHTS_AUTHORITY_V3_VERSION,
    candidate_schema=FACTORY_CATALOG_PUBLICATION_CANDIDATE_SCHEMA,
    candidate_version=FACTORY_CATALOG_PUBLICATION_CANDIDATE_VERSION,
    receipt_schema=DCC_SEMANTIC_PUBLICATION_RECEIPT_V3_SCHEMA,
    receipt_version=DCC_SEMANTIC_PUBLICATION_RECEIPT_V3_VERSION,
    accepted_families=_ACCEPTED_CONTENT_FAMILIES,
    family_counts={},
    record_count=0,
    adapter_sha256=FACTORY_SEMANTIC_ADAPTER_SHA256,
    descriptor_driven_counts=True,
)


def _is_v3_profile(profile: _PublicationProfile) -> bool:
    return profile.name == "v3"


def _authority_input_sha256s(root: Path, profile: _PublicationProfile) -> dict[str, str]:
    """Hash every authority file whose bytes determine one publication plan."""

    inputs = {f"descriptor:{profile.descriptor_name}": root / profile.descriptor_name}
    if _is_v3_profile(profile):
        inputs.update(
            {
                f"non_sphere:{name}": _NON_SPHERE_AUTHORITY_ROOT / name
                for name in _V3_METHOD_AUTHORITY_INPUT_NAMES
            }
        )
    return {
        label: sha256_bytes(_regular_file(path, code="DCC_PUBLICATION_AUTHORITY_UNAVAILABLE"))
        for label, path in sorted(inputs.items())
    }


def _validated_v3_family_counts(
    value: Any,
    *,
    path: str,
    invalid_code: str,
    noncanonical_code: str,
) -> dict[str, int]:
    """Validate the V3 count map without baking its values into Python."""

    require_exact_keys(value, _ACCEPTED_CONTENT_FAMILIES, path=path)
    if list(value) != sorted(_ACCEPTED_CONTENT_FAMILIES):
        fail(noncanonical_code, f"{path} must use canonical sorted keys.")
    counts: dict[str, int] = {}
    for family in sorted(_ACCEPTED_CONTENT_FAMILIES):
        count = require_type(value[family], int, path=f"{path}.{family}")
        if count < 0:
            fail(invalid_code, f"{path}.{family} must be non-negative.")
        counts[family] = count
    total = sum(counts.values())
    if total < 1 or total > 8192:
        fail(invalid_code, f"{path} total must be between 1 and 8192.")
    return counts


def _profile_with_descriptor_counts(profile: _PublicationProfile, descriptor: Mapping[str, Any]) -> _PublicationProfile:
    """Bind a descriptor-driven profile to the counts in its sealed descriptor."""

    if not profile.descriptor_driven_counts:
        return profile
    counts = _validated_v3_family_counts(
        descriptor.get("family_counts"),
        path="DCC source-rights authority.family_counts",
        invalid_code="DCC_SOURCE_RIGHTS_AUTHORITY_INVALID",
        noncanonical_code="DCC_SOURCE_RIGHTS_AUTHORITY_NONCANONICAL",
    )
    return replace(profile, family_counts=counts, record_count=sum(counts.values()))

_RECEIPT_KEYS = {
    "schema",
    "version",
    "mode",
    "status",
    "record_count",
    "family_counts",
    "database_sha256",
    "canonical_record_set_sha256",
    "source_rights_authority_sha256",
    "semantic_authority_bundle_sha256",
    "content_snapshot_sha256",
    "semantic_admission_receipt_sha256",
    "old_source_rights_manifest_sha256",
    "new_source_rights_manifest_sha256",
    "old_semantic_manifest_sha256",
    "new_semantic_manifest_sha256",
    "objects",
    "receipt_sha256",
    "predecessor_receipt_sha256",
}
_RECEIPT_KEYS_V1 = _RECEIPT_KEYS - {"predecessor_receipt_sha256"}
_ACTIVE_PUBLICATION_POINTER_NAME = "Tianxia_DCC_Semantic_Publication_Active_v1.json"
_ACTIVE_POINTER_KEYS = {
    "schema",
    "version",
    "status",
    "receipt_sha256",
    "receipt_object_sha256",
    "source_rights_authority_sha256",
    "semantic_authority_bundle_sha256",
    "source_rights_manifest_sha256",
    "semantic_manifest_sha256",
    "pointer_sha256",
}
_OBJECT_KINDS = (
    "source_rights_authority",
    "old_source_rights_trust",
    "new_source_rights_trust",
    "old_semantic_trust",
    "new_semantic_trust",
    "registry",
    "overlay",
    "candidate",
    "authority_bundle",
    "content_snapshot",
    "semantic_admission_receipt",
)


def _regular_file(path: Path, *, code: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        fail(code, "A required publication file is unavailable or non-regular.")
    try:
        return path.read_bytes()
    except (OSError, UnicodeError) as exc:
        fail(code, "A required publication file is unavailable.", details={"error_type": type(exc).__name__})


def _authority_dir(root: Path | None) -> Path:
    candidate = _AUTHORITY_ROOT if root is None else Path(root)
    if candidate.is_symlink():
        fail("DCC_PUBLICATION_STORAGE_INVALID", "The publication authority root cannot be a symlink.")
    resolved = candidate.resolve()
    if resolved.is_symlink():
        fail("DCC_PUBLICATION_STORAGE_INVALID", "The publication authority root cannot be a symlink.")
    if not resolved.exists() or not resolved.is_dir():
        fail("DCC_PUBLICATION_STORAGE_INVALID", "The publication authority root is unavailable.")
    return resolved


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _unique_identifiers(value: Any, *, path: str, maximum: int = 4096) -> list[str]:
    rows = require_list(value, path=path, max_length=maximum)
    result = [require_identifier(row, path=f"{path}[{index}]") for index, row in enumerate(rows)]
    if len(result) != len(set(result)):
        fail("DCC_SCHEMA_DUPLICATE", f"{path} must be duplicate-free.")
    return sorted(result)


def _validate_descriptor_value(value: Mapping[str, Any], profile: _PublicationProfile) -> dict[str, Any]:
    descriptor_keys = {"schema", "version", "authority_id", "allowed_uses", "source_bindings", "authority_sha256"}
    if _is_v3_profile(profile):
        descriptor_keys.add("family_counts")
    require_exact_keys(
        value,
        descriptor_keys,
        path="DCC source-rights authority",
    )
    if value["schema"] != profile.descriptor_schema:
        fail("DCC_SCHEMA_VALUE", "Unsupported DCC source-rights authority schema.")
    if require_type(value["version"], int, path="DCC source-rights authority.version") != profile.descriptor_version:
        fail("DCC_SCHEMA_VALUE", "Unsupported DCC source-rights authority version.")
    authority_id = require_identifier(value["authority_id"], path="DCC source-rights authority.authority_id")
    allowed_uses = _unique_identifiers(value["allowed_uses"], path="DCC source-rights authority.allowed_uses", maximum=16)
    if allowed_uses != ["DCC_SEMANTIC_PUBLICATION"]:
        fail("DCC_SOURCE_RIGHTS_AUTHORITY_USE_INVALID", "The fixed source-rights authority allows only DCC semantic publication.")
    bindings: list[dict[str, str]] = []
    for index, row in enumerate(require_list(value["source_bindings"], path="DCC source-rights authority.source_bindings", max_length=4096)):
        path_prefix = f"DCC source-rights authority.source_bindings[{index}]"
        require_exact_keys(row, {"source_id", "source_hash"}, path=path_prefix)
        bindings.append(
            {
                "source_id": require_identifier(row["source_id"], path=f"{path_prefix}.source_id"),
                "source_hash": require_digest(row["source_hash"], path=f"{path_prefix}.source_hash"),  # type: ignore[dict-item]
            }
        )
    bindings.sort(key=lambda row: (row["source_id"], row["source_hash"]))
    if not bindings:
        fail("DCC_SOURCE_RIGHTS_AUTHORITY_EMPTY", "The fixed source-rights authority must bind at least one source.")
    if len({(row["source_id"], row["source_hash"]) for row in bindings}) != len(bindings):
        fail("DCC_SOURCE_RIGHTS_AUTHORITY_DUPLICATE", "The fixed source-rights authority contains duplicate source bindings.")
    unsigned = {
        "schema": profile.descriptor_schema,
        "version": profile.descriptor_version,
        "authority_id": authority_id,
        "allowed_uses": allowed_uses,
        "source_bindings": bindings,
    }
    if _is_v3_profile(profile):
        unsigned["family_counts"] = _validated_v3_family_counts(
            value["family_counts"],
            path="DCC source-rights authority.family_counts",
            invalid_code="DCC_SOURCE_RIGHTS_AUTHORITY_INVALID",
            noncanonical_code="DCC_SOURCE_RIGHTS_AUTHORITY_NONCANONICAL",
        )
    validate_self_hash(value, "authority_sha256", code="DCC_SOURCE_RIGHTS_AUTHORITY_HASH_INVALID")
    rebuilt = {**unsigned, "authority_sha256": sha256_json(unsigned)}
    if dict(value) != rebuilt:
        fail("DCC_SOURCE_RIGHTS_AUTHORITY_NONCANONICAL", "The fixed source-rights authority is not canonical.")
    # The descriptor itself is an exact detached public object.  Requiring
    # valid UTF-8 JSON above is sufficient; source paths/prose cannot enter
    # because the exact key contract rejects every additional field.
    return rebuilt


def _load_dcc_source_rights_authority_for_profile(root: Path, profile: _PublicationProfile) -> dict[str, Any]:
    """Load the fixed sealed source-rights descriptor for one immutable profile."""

    path = root / profile.descriptor_name
    raw_bytes = _regular_file(path, code="DCC_SOURCE_RIGHTS_AUTHORITY_UNAVAILABLE")
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(
            "DCC_SOURCE_RIGHTS_AUTHORITY_UNAVAILABLE",
            "The fixed source-rights authority is unavailable or malformed.",
            details={"error_type": type(exc).__name__},
        )
    return _validate_descriptor_value(value, profile)


def _load_dcc_source_rights_authority_at(root: Path) -> dict[str, Any]:
    """Load the current fixed (V2) sealed source-rights descriptor."""

    return _load_dcc_source_rights_authority_for_profile(root, _PROFILE_V2)


def _load_dcc_source_rights_authority_v1_at(root: Path) -> dict[str, Any]:
    """Load the immutable V1 descriptor for explicit historical reopening."""

    return _load_dcc_source_rights_authority_for_profile(root, _PROFILE_V1)


def _load_dcc_source_rights_authority_v3_at(root: Path) -> dict[str, Any]:
    """Load the immutable V3 descriptor for dry-run publication preparation."""

    return _load_dcc_source_rights_authority_for_profile(root, _PROFILE_V3)


def load_dcc_source_rights_authority() -> dict[str, Any]:
    """Load the current fixed, checked-in V2 source-rights descriptor."""

    return _load_dcc_source_rights_authority_at(_authority_dir(None))


def load_dcc_source_rights_authority_v3() -> dict[str, Any]:
    """Load the immutable V3 descriptor used by the default dry run."""

    return _load_dcc_source_rights_authority_v3_at(_authority_dir(None))


def _validate_trust_manifest(value: Mapping[str, Any], *, semantic: bool, allow_inactive: bool = True) -> dict[str, Any]:
    if semantic:
        schema = FACTORY_SEMANTIC_TRUST_MANIFEST_SCHEMA
        keys = {"schema", "version", "status", "active_authority_bundle_sha256", "revoked_authority_bundle_sha256s", "manifest_sha256"}
        active_key = "active_authority_bundle_sha256"
        revoked_key = "revoked_authority_bundle_sha256s"
    else:
        schema = SOURCE_RIGHTS_AUTHORITY_TRUST_MANIFEST_SCHEMA
        keys = {"schema", "version", "status", "active_rights_authority_sha256", "revoked_rights_authority_sha256s", "manifest_sha256"}
        active_key = "active_rights_authority_sha256"
        revoked_key = "revoked_rights_authority_sha256s"
    require_exact_keys(value, keys, path="DCC trust manifest")
    validate_self_hash(value, "manifest_sha256", code="DCC_PUBLICATION_TRUST_HASH_INVALID")
    if value["schema"] != schema or require_type(value["version"], int, path="DCC trust manifest.version") != 1:
        fail("DCC_SCHEMA_VALUE", "Unsupported DCC trust manifest schema/version.")
    status = require_enum(value["status"], {"ACTIVE", "INACTIVE"}, path="DCC trust manifest.status")
    revoked = _unique_identifiers(value[revoked_key], path=f"DCC trust manifest.{revoked_key}", maximum=8192)
    for index, digest in enumerate(revoked):
        require_digest(digest, path=f"DCC trust manifest.{revoked_key}[{index}]")
    active = value[active_key]
    if status == "INACTIVE":
        if active is not None:
            fail("DCC_PUBLICATION_TRUST_INVALID", "An inactive DCC trust manifest cannot name an active digest.")
    else:
        active = require_digest(active, path=f"DCC trust manifest.{active_key}")
        if active in revoked:
            fail("DCC_PUBLICATION_TRUST_REVOKED", "An active DCC trust digest cannot be revoked.")
    canonical = {
        "schema": schema,
        "version": 1,
        "status": status,
        active_key: active,
        revoked_key: revoked,
    }
    rebuilt = {**canonical, "manifest_sha256": sha256_json(canonical)}
    if dict(value) != rebuilt:
        fail("DCC_PUBLICATION_TRUST_NONCANONICAL", "A DCC trust manifest is not canonical.")
    if status == "INACTIVE" and not allow_inactive:
        fail("DCC_PUBLICATION_TRUST_INACTIVE", "A DCC trust manifest is inactive.")
    return rebuilt


def _load_trust_manifest(path: Path, *, semantic: bool) -> tuple[dict[str, Any], bytes]:
    raw = _regular_file(path, code="DCC_PUBLICATION_TRUST_UNAVAILABLE")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail("DCC_PUBLICATION_TRUST_UNAVAILABLE", "A DCC trust manifest is unavailable or malformed.", details={"error_type": type(exc).__name__})
    return _validate_trust_manifest(value, semantic=semantic), raw


def _trust_paths(root: Path) -> tuple[Path, Path]:
    return root / _SOURCE_RIGHTS_TRUST_NAME, root / _SEMANTIC_TRUST_NAME


@contextmanager
def _fixed_trust_paths(root: Path) -> Iterator[None]:
    """Temporarily redirect fixed loaders for an isolated copied authority root."""

    source_path, semantic_path = _trust_paths(root)
    old_source = _catalog_adapter._SOURCE_RIGHTS_TRUST_PATH
    old_semantic = _semantic_admission._FACTORY_SEMANTIC_TRUST_MANIFEST_PATH
    _catalog_adapter._SOURCE_RIGHTS_TRUST_PATH = source_path
    _semantic_admission._FACTORY_SEMANTIC_TRUST_MANIFEST_PATH = semantic_path
    try:
        yield
    finally:
        _catalog_adapter._SOURCE_RIGHTS_TRUST_PATH = old_source
        _semantic_admission._FACTORY_SEMANTIC_TRUST_MANIFEST_PATH = old_semantic


def _build_rights_trust(authority_sha256: str, previous: Mapping[str, Any]) -> dict[str, Any]:
    revoked = list(previous["revoked_rights_authority_sha256s"])
    if authority_sha256 in revoked:
        fail("DCC_SOURCE_RIGHTS_AUTHORITY_REVOKED", "The fixed source-rights authority is already revoked.")
    unsigned = {
        "schema": SOURCE_RIGHTS_AUTHORITY_TRUST_MANIFEST_SCHEMA,
        "version": 1,
        "status": "ACTIVE",
        "active_rights_authority_sha256": authority_sha256,
        "revoked_rights_authority_sha256s": revoked,
    }
    return {**unsigned, "manifest_sha256": sha256_json(unsigned)}


def _build_semantic_trust(authority_bundle_sha256: str, previous: Mapping[str, Any]) -> dict[str, Any]:
    revoked = list(previous["revoked_authority_bundle_sha256s"])
    if authority_bundle_sha256 in revoked:
        fail("DCC_SEMANTIC_AUTHORITY_REVOKED", "The candidate semantic authority bundle is already revoked.")
    unsigned = {
        "schema": FACTORY_SEMANTIC_TRUST_MANIFEST_SCHEMA,
        "version": 1,
        "status": "ACTIVE",
        "active_authority_bundle_sha256": authority_bundle_sha256,
        "revoked_authority_bundle_sha256s": revoked,
    }
    return {**unsigned, "manifest_sha256": sha256_json(unsigned)}


def _known_v1_rights_authority(root: Path, rights: Mapping[str, Any]) -> bool:
    """Recognize only the sealed V1 authority as a valid historical predecessor."""

    if rights.get("status") != "ACTIVE":
        return False
    try:
        descriptor = _load_dcc_source_rights_authority_v1_at(root)
    except CreativeControllerError:
        return False
    return rights.get("active_rights_authority_sha256") == descriptor["authority_sha256"]


def _known_v2_rights_authority(root: Path, rights: Mapping[str, Any]) -> bool:
    """Recognize the sealed V2 authority as the V3 dry-run predecessor."""

    if rights.get("status") != "ACTIVE":
        return False
    try:
        descriptor = _load_dcc_source_rights_authority_at(root)
    except CreativeControllerError:
        return False
    return rights.get("active_rights_authority_sha256") == descriptor["authority_sha256"]


def _known_v1_semantic_authority(root: Path, semantic: Mapping[str, Any], semantic_bytes: bytes) -> bool:
    """Recognize a V1 semantic authority only through a stored V1 receipt."""

    if semantic.get("status") != "ACTIVE":
        return False
    objects = root / _SEMANTIC_STORAGE_NAME / _OBJECTS_NAME
    if objects.is_symlink() or not objects.is_dir():
        return False
    current_manifest_sha256 = _object_hash(semantic_bytes)
    for path in sorted(objects.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            if _object_hash(raw) != path.stem:
                continue
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, Mapping) or value.get("schema") != DCC_SEMANTIC_PUBLICATION_RECEIPT_V1_SCHEMA:
                continue
            receipt = _validate_publication_receipt(value)
        except (CreativeControllerError, OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            receipt["semantic_authority_bundle_sha256"] == semantic.get("active_authority_bundle_sha256")
            and receipt["new_semantic_manifest_sha256"] == current_manifest_sha256
        ):
            return True
    return False


def _known_v2_semantic_authority(root: Path, semantic: Mapping[str, Any], semantic_bytes: bytes) -> bool:
    """Recognize the stored V2 semantic authority as a V3 dry-run predecessor."""

    if semantic.get("status") != "ACTIVE":
        return False
    objects = root / _SEMANTIC_STORAGE_NAME / _OBJECTS_NAME
    if objects.is_symlink() or not objects.is_dir():
        return False
    current_manifest_sha256 = _object_hash(semantic_bytes)
    for path in sorted(objects.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            if _object_hash(raw) != path.stem:
                continue
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, Mapping) or value.get("schema") != _PROFILE_V2.receipt_schema:
                continue
            receipt = _validate_publication_receipt(value)
        except (CreativeControllerError, OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            receipt["semantic_authority_bundle_sha256"] != semantic.get("active_authority_bundle_sha256")
            or receipt["new_semantic_manifest_sha256"] != current_manifest_sha256
        ):
            continue
        descriptor_entry = next(
            (row for row in receipt["objects"] if row["kind"] == "source_rights_authority"),
            None,
        )
        if descriptor_entry is None:
            continue
        try:
            descriptor_raw = _receipt_object_payload(objects, descriptor_entry["sha256"], code="DCC_PUBLICATION_OBJECT_UNAVAILABLE")
            descriptor_value = json.loads(descriptor_raw.decode("utf-8"))
            descriptor = _validate_descriptor_value(descriptor_value, _PROFILE_V2)
        except (CreativeControllerError, OSError, UnicodeError, json.JSONDecodeError):
            continue
        if receipt["source_rights_authority_sha256"] == descriptor["authority_sha256"]:
            return True
    return False


def _open_immutable_database(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        fail("DCC_PUBLICATION_DATABASE_UNAVAILABLE", "The configured catalogue database is unavailable.")
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=1")
        connection.execute("PRAGMA temp_store=MEMORY")
        return connection
    except sqlite3.Error as exc:
        fail("DCC_PUBLICATION_DATABASE_UNAVAILABLE", "The catalogue database could not be opened read-only.", details={"error_type": type(exc).__name__})


def _read_catalogue(path: Path, profile: _PublicationProfile = _PROFILE_V2) -> tuple[list[dict[str, Any]], dict[str, int], str]:
    if _is_v3_profile(profile) and not profile.family_counts:
        profile = _profile_with_descriptor_counts(
            profile,
            _load_dcc_source_rights_authority_v3_at(_authority_dir(None)),
        )
    try:
        before_hash = sha256_file(path)
    except OSError as exc:
        fail(
            "DCC_PUBLICATION_DATABASE_UNAVAILABLE",
            "The configured catalogue database is unavailable.",
            details={"error_type": type(exc).__name__},
        )
    connection = _open_immutable_database(path)
    try:
        placeholders = ",".join("?" for _ in sorted(profile.accepted_families))
        rows = connection.execute(
            f"SELECT data_json FROM catalog_records WHERE contract_status='valid' AND content_type IN ({placeholders}) ORDER BY record_id",
            tuple(sorted(profile.accepted_families)),
        ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row["data_json"])
            except (TypeError, UnicodeError, json.JSONDecodeError) as exc:
                fail("DCC_PUBLICATION_DATABASE_RECORD_INVALID", "A valid catalogue row is not canonical JSON.", details={"error_type": type(exc).__name__})
            if not isinstance(value, Mapping):
                fail("DCC_PUBLICATION_DATABASE_RECORD_INVALID", "A valid catalogue row is not an object.")
            records.append(dict(value))
    except sqlite3.Error as exc:
        fail("DCC_PUBLICATION_DATABASE_UNAVAILABLE", "The catalogue database could not be read immutably.", details={"error_type": type(exc).__name__})
    finally:
        connection.close()
    try:
        after_hash = sha256_file(path)
    except OSError as exc:
        fail(
            "DCC_PUBLICATION_DATABASE_UNAVAILABLE",
            "The catalogue database could not be re-hashed after immutable preflight.",
            details={"error_type": type(exc).__name__},
        )
    if before_hash != after_hash:
        fail("DCC_PUBLICATION_DATABASE_CHANGED", "The catalogue database changed during immutable preflight.")
    if _is_v3_profile(profile):
        legacy_records = [record for record in records if record.get("content_type") != "cultivation_method"]
        try:
            method_records = project_locked_method_catalog_records_from_authority(
                _NON_SPHERE_AUTHORITY_ROOT,
                project_root=_APP_ROOT,
            )
        except FoundryError as exc:
            fail(exc.code, exc.message, details=exc.details, status_code=exc.status_code)
        records = legacy_records + [dict(record) for record in method_records]
        _validate_v3_catalogue_record_ids(records)
        records.sort(key=lambda record: (str(record.get("record_id")), str(record.get("content_type"))))
    counts = dict(sorted(Counter(row.get("content_type") for row in records).items()))
    if set(counts) != profile.accepted_families or counts != dict(profile.family_counts) or len(records) != profile.record_count:
        fail(
            "DCC_PUBLICATION_CATALOGUE_SCOPE_INVALID",
            "The immutable catalogue does not match the expected current DCC family set.",
            details={"record_count": len(records), "family_count_keys": sorted(counts)},
        )
    return records, counts, before_hash


def _validate_v3_catalogue_record_ids(records: Sequence[Mapping[str, Any]]) -> None:
    """Reject duplicate records and cross-family ID collisions in the V3 overlay."""

    by_record_id: dict[str, str] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for index, record in enumerate(records):
        record_id = require_identifier(record.get("record_id"), path=f"V3 catalogue record[{index}].record_id")
        content_type = require_identifier(record.get("content_type"), path=f"V3 catalogue record[{index}].content_type")
        pair = (record_id, content_type)
        if pair in seen_pairs:
            fail(
                "DCC_PUBLICATION_CATALOGUE_DUPLICATE_RECORD_ID",
                "The V3 catalogue overlay contains a duplicate record identity.",
                details={"record_id": record_id, "content_type": content_type},
            )
        prior_family = by_record_id.get(record_id)
        if prior_family is not None and prior_family != content_type:
            fail(
                "DCC_PUBLICATION_CATALOGUE_RECORD_ID_COLLISION",
                "The V3 catalogue overlay contains a cross-family record ID collision.",
                details={"record_id": record_id, "families": sorted({prior_family, content_type})},
            )
        seen_pairs.add(pair)
        by_record_id[record_id] = content_type


def _source_pairs(records: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for index, record in enumerate(records):
        source = record.get("source")
        if not isinstance(source, Mapping):
            fail("DCC_SOURCE_RIGHTS_AUTHORITY_SCOPE_INVALID", "A catalogue record has no typed source commitment.", details={"index": index})
        source_id = record.get("source", {}).get("source_id")
        source_hash = record.get("source", {}).get("source_hash")
        pairs.add((require_identifier(source_id, path="catalogue record.source.source_id"), require_digest(source_hash, path="catalogue record.source.source_hash")))  # type: ignore[arg-type]
    return pairs


def _prove_source_scope(records: Sequence[Mapping[str, Any]], authority: Mapping[str, Any]) -> None:
    allowed = {(row["source_id"], row["source_hash"]) for row in authority["source_bindings"]}
    observed = _source_pairs(records)
    if observed != allowed:
        fail(
            "DCC_SOURCE_RIGHTS_AUTHORITY_SCOPE_INVALID",
            "Every catalogue source pair must exactly match the fixed source-rights authority scope.",
            details={"observed_source_count": len(observed), "authorized_source_count": len(allowed)},
        )


def _object_bytes(value: Mapping[str, Any] | bytes) -> bytes:
    return value if isinstance(value, bytes) else _canonical_json_bytes(value)


def _object_hash(payload: bytes) -> str:
    return sha256_bytes(payload)


def _receipt_profile(value: Mapping[str, Any]) -> _PublicationProfile:
    schema_version = (value.get("schema"), value.get("version"))
    if schema_version == (_PROFILE_V1.receipt_schema, _PROFILE_V1.receipt_version):
        return _PROFILE_V1
    if schema_version == (_PROFILE_V2.receipt_schema, _PROFILE_V2.receipt_version):
        return _PROFILE_V2
    if schema_version == (_PROFILE_V3.receipt_schema, _PROFILE_V3.receipt_version):
        return _PROFILE_V3
    fail("DCC_SCHEMA_VALUE", "Unsupported DCC semantic publication receipt schema/version.")


def _validate_publication_receipt(
    value: Mapping[str, Any],
    *,
    descriptor: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    profile = _receipt_profile(value)
    required_keys = _RECEIPT_KEYS if profile.name in {"v2", "v3"} else _RECEIPT_KEYS_V1
    require_exact_keys(value, required_keys, path="DCC semantic publication receipt")
    validate_self_hash(value, "receipt_sha256", code="DCC_PUBLICATION_RECEIPT_HASH_INVALID")
    require_enum(value["mode"], {"DRY_RUN", "PUBLISH"}, path="DCC semantic publication receipt.mode")
    require_enum(value["status"], {"READY", "PUBLISHED"}, path="DCC semantic publication receipt.status")
    if value["mode"] == "DRY_RUN" and value["status"] != "READY":
        fail("DCC_PUBLICATION_RECEIPT_INVALID", "A dry-run publication receipt must remain ready.")
    if value["mode"] == "PUBLISH" and value["status"] != "PUBLISHED":
        fail("DCC_PUBLICATION_RECEIPT_INVALID", "A publish receipt must be published.")
    count = require_type(value["record_count"], int, path="DCC semantic publication receipt.record_count")
    family_counts = value["family_counts"]
    if _is_v3_profile(profile):
        normalized_family_counts = _validated_v3_family_counts(
            family_counts,
            path="DCC semantic publication receipt.family_counts",
            invalid_code="DCC_PUBLICATION_RECEIPT_INVALID",
            noncanonical_code="DCC_PUBLICATION_RECEIPT_NONCANONICAL",
        )
        if count != sum(normalized_family_counts.values()):
            fail("DCC_PUBLICATION_RECEIPT_INVALID", "Publication receipt record count must equal the family count total.")
        if descriptor is not None:
            descriptor_counts = _profile_with_descriptor_counts(profile, descriptor).family_counts
            if normalized_family_counts != dict(descriptor_counts) or count != sum(descriptor_counts.values()):
                fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "Publication receipt family counts do not match its stored V3 descriptor.")
    else:
        if count != profile.record_count:
            fail("DCC_PUBLICATION_RECEIPT_INVALID", "Publication receipt record count is outside the fixed current scope.")
        require_exact_keys(family_counts, profile.accepted_families, path="DCC semantic publication receipt.family_counts")
        if dict(family_counts) != dict(profile.family_counts):
            fail("DCC_PUBLICATION_RECEIPT_INVALID", "Publication receipt family counts are not the expected current scope.")
    for key in (
        "database_sha256",
        "canonical_record_set_sha256",
        "source_rights_authority_sha256",
        "semantic_authority_bundle_sha256",
        "content_snapshot_sha256",
        "semantic_admission_receipt_sha256",
        "old_source_rights_manifest_sha256",
        "new_source_rights_manifest_sha256",
        "old_semantic_manifest_sha256",
        "new_semantic_manifest_sha256",
    ):
        require_digest(value[key], path=f"DCC semantic publication receipt.{key}")
    objects = require_list(value["objects"], path="DCC semantic publication receipt.objects", max_length=64)
    normalized_objects: list[dict[str, str]] = []
    for index, row in enumerate(objects):
        path = f"DCC semantic publication receipt.objects[{index}]"
        require_exact_keys(row, {"kind", "sha256"}, path=path)
        normalized_objects.append(
            {
                "kind": require_identifier(row["kind"], path=f"{path}.kind"),
                "sha256": require_digest(row["sha256"], path=f"{path}.sha256"),  # type: ignore[dict-item]
            }
        )
    if [row["kind"] for row in normalized_objects] != list(_OBJECT_KINDS):
        fail("DCC_PUBLICATION_RECEIPT_INVALID", "Publication receipt objects must bind every detached artifact in stable order.")
    if normalized_objects != objects:
        fail("DCC_PUBLICATION_RECEIPT_NONCANONICAL", "Publication receipt objects must be canonical.")
    if profile.name in {"v2", "v3"}:
        require_digest(
            value["predecessor_receipt_sha256"],
            path="DCC semantic publication receipt.predecessor_receipt_sha256",
            allow_none=True,
        )
    unsigned = {key: value[key] for key in required_keys - {"receipt_sha256"}}
    rebuilt = {**unsigned, "receipt_sha256": sha256_json(unsigned)}
    if dict(value) != rebuilt:
        fail("DCC_PUBLICATION_RECEIPT_NONCANONICAL", "Publication receipt must use canonical ordering and hashes.")
    return rebuilt


def _make_publication_receipt(
    *,
    profile: _PublicationProfile = _PROFILE_V2,
    mode: str,
    record_count: int,
    family_counts: Mapping[str, int],
    database_sha256: str,
    candidate: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    admission_receipt: Mapping[str, Any],
    old_rights_manifest_bytes: bytes,
    new_rights_manifest_bytes: bytes,
    old_semantic_manifest_bytes: bytes,
    new_semantic_manifest_bytes: bytes,
    objects: Sequence[Mapping[str, str]],
    predecessor_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    unsigned = {
        "schema": profile.receipt_schema,
        "version": profile.receipt_version,
        "mode": mode,
        "status": "READY" if mode == "DRY_RUN" else "PUBLISHED",
        "record_count": record_count,
        "family_counts": dict(sorted(family_counts.items())),
        "database_sha256": database_sha256,
        "canonical_record_set_sha256": candidate["canonical_record_set_sha256"],
        "source_rights_authority_sha256": descriptor["authority_sha256"],
        "semantic_authority_bundle_sha256": candidate["authority_bundle"]["authority_bundle_sha256"],
        "content_snapshot_sha256": snapshot["content_snapshot_sha256"],
        "semantic_admission_receipt_sha256": admission_receipt["receipt_sha256"],
        "old_source_rights_manifest_sha256": _object_hash(old_rights_manifest_bytes),
        "new_source_rights_manifest_sha256": _object_hash(new_rights_manifest_bytes),
        "old_semantic_manifest_sha256": _object_hash(old_semantic_manifest_bytes),
        "new_semantic_manifest_sha256": _object_hash(new_semantic_manifest_bytes),
        "objects": [dict(row) for row in objects],
    }
    if profile.name in {"v2", "v3"}:
        unsigned["predecessor_receipt_sha256"] = require_digest(
            predecessor_receipt_sha256,
            path="DCC semantic publication receipt.predecessor_receipt_sha256",
            allow_none=True,
        )
    return _validate_publication_receipt({**unsigned, "receipt_sha256": sha256_json(unsigned)})


def _prepare_objects(
    *,
    descriptor_bytes: bytes,
    old_rights_manifest_bytes: bytes,
    new_rights_manifest_bytes: bytes,
    old_semantic_manifest_bytes: bytes,
    new_semantic_manifest_bytes: bytes,
    registry: Mapping[str, Any],
    overlay: Mapping[str, Any],
    candidate: Mapping[str, Any],
    authority_bundle: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    admission_receipt: Mapping[str, Any],
) -> tuple[dict[str, bytes], list[dict[str, str]]]:
    values: dict[str, Mapping[str, Any] | bytes] = {
        "source_rights_authority": descriptor_bytes,
        "old_source_rights_trust": old_rights_manifest_bytes,
        "new_source_rights_trust": new_rights_manifest_bytes,
        "old_semantic_trust": old_semantic_manifest_bytes,
        "new_semantic_trust": new_semantic_manifest_bytes,
        "registry": registry,
        "overlay": overlay,
        "candidate": candidate,
        "authority_bundle": authority_bundle,
        "content_snapshot": snapshot,
        "semantic_admission_receipt": admission_receipt,
    }
    payloads = {kind: _object_bytes(values[kind]) for kind in _OBJECT_KINDS}
    entries = [{"kind": kind, "sha256": _object_hash(payloads[kind])} for kind in _OBJECT_KINDS]
    return payloads, entries


def _check_storage_target(path: Path, *, directory: bool = False) -> None:
    if path.is_symlink():
        fail("DCC_PUBLICATION_STORAGE_INVALID", "A publication storage path cannot be a symlink.")
    if path.exists() and ((directory and not path.is_dir()) or (not directory and not path.is_file())):
        fail("DCC_PUBLICATION_STORAGE_INVALID", "A publication storage path has the wrong type.")


def _prepare_storage(root: Path) -> tuple[Path, Path, Path]:
    storage = root / _SEMANTIC_STORAGE_NAME
    objects = storage / _OBJECTS_NAME
    lock = storage / _LOCK_NAME
    _check_storage_target(storage, directory=True)
    _check_storage_target(objects, directory=True)
    _check_storage_target(lock, directory=False)
    return storage, objects, lock


def _check_object_collisions(objects: Path, payloads: Mapping[str, bytes], entries: Sequence[Mapping[str, str]]) -> None:
    for row in entries:
        target = objects / f"{row['sha256']}.json"
        if target.is_symlink():
            fail("DCC_PUBLICATION_OBJECT_COLLISION", "A content-addressed object target is a symlink.")
        if target.exists():
            if not target.is_file():
                fail("DCC_PUBLICATION_OBJECT_COLLISION", "A content-addressed object target is not a regular file.")
            if target.read_bytes() != payloads[row["kind"]]:
                fail("DCC_PUBLICATION_OBJECT_COLLISION", "A content-addressed object target contains different bytes.")


def _mkdir_storage(storage: Path, objects: Path) -> None:
    if not storage.exists():
        storage.mkdir()
        _fsync_directory(storage.parent)
    _check_storage_target(storage, directory=True)
    if not objects.exists():
        objects.mkdir()
        _fsync_directory(storage)
    _check_storage_target(objects, directory=True)


def _validate_existing_object_target(target: Path, payload: bytes) -> None:
    if target.is_symlink():
        fail("DCC_PUBLICATION_OBJECT_COLLISION", "A content-addressed object target is a symlink.")
    if not target.is_file():
        fail("DCC_PUBLICATION_OBJECT_COLLISION", "A content-addressed object target is not a regular file.")
    try:
        existing = target.read_bytes()
    except OSError as exc:
        fail(
            "DCC_PUBLICATION_OBJECT_COLLISION",
            "A content-addressed object target could not be read.",
            details={"error_type": type(exc).__name__},
        )
    if existing != payload:
        fail("DCC_PUBLICATION_OBJECT_COLLISION", "A content-addressed object target contains different bytes.")


def _write_object(objects: Path, payload: bytes, digest: str) -> None:
    target = objects / f"{digest}.json"
    if target.is_symlink() or target.exists():
        _validate_existing_object_target(target, payload)
        return
    temporary_name: str | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=".dcc-object-", suffix=".tmp", dir=str(objects))
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard-link install is atomic and cannot replace an existing
        # directory entry. If another publisher wins the race, reopen its
        # target and accept only byte-identical content.
        try:
            os.link(temporary_name, target, follow_symlinks=False)
        except FileExistsError:
            _validate_existing_object_target(target, payload)
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                _validate_existing_object_target(target, payload)
            else:
                raise
        else:
            os.unlink(temporary_name)
            temporary_name = None
            _fsync_directory(objects)
            return
        os.unlink(temporary_name)
        temporary_name = None
        _fsync_directory(objects)
    except OSError as exc:
        fail("DCC_PUBLICATION_STORAGE_WRITE_FAILED", "A detached publication object could not be stored.", details={"error_type": type(exc).__name__})
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass


def _validate_active_publication_pointer(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, _ACTIVE_POINTER_KEYS, path="DCC active publication pointer")
    validate_self_hash(value, "pointer_sha256", code="DCC_PUBLICATION_POINTER_HASH_INVALID")
    if value["schema"] != "TianxiaFoundry.DCCSemanticPublicationActive.v1" or value["version"] != 1:
        fail("DCC_SCHEMA_VALUE", "Unsupported DCC active publication pointer schema/version.")
    if value["status"] != "ACTIVE":
        fail("DCC_PUBLICATION_POINTER_INVALID", "The active publication pointer must be active.")
    for key in (
        "receipt_sha256",
        "receipt_object_sha256",
        "source_rights_authority_sha256",
        "semantic_authority_bundle_sha256",
        "source_rights_manifest_sha256",
        "semantic_manifest_sha256",
    ):
        require_digest(value[key], path=f"DCC active publication pointer.{key}")
    unsigned = {key: value[key] for key in _ACTIVE_POINTER_KEYS - {"pointer_sha256"}}
    rebuilt = {**unsigned, "pointer_sha256": sha256_json(unsigned)}
    if dict(value) != rebuilt:
        fail("DCC_PUBLICATION_POINTER_NONCANONICAL", "The active publication pointer is not canonical.")
    return rebuilt


def _make_active_publication_pointer(receipt: Mapping[str, Any], receipt_object_sha256: str) -> dict[str, Any]:
    unsigned = {
        "schema": "TianxiaFoundry.DCCSemanticPublicationActive.v1",
        "version": 1,
        "status": "ACTIVE",
        "receipt_sha256": receipt["receipt_sha256"],
        "receipt_object_sha256": require_digest(receipt_object_sha256, path="active publication pointer.receipt_object_sha256"),
        "source_rights_authority_sha256": receipt["source_rights_authority_sha256"],
        "semantic_authority_bundle_sha256": receipt["semantic_authority_bundle_sha256"],
        "source_rights_manifest_sha256": receipt["new_source_rights_manifest_sha256"],
        "semantic_manifest_sha256": receipt["new_semantic_manifest_sha256"],
    }
    return _validate_active_publication_pointer({**unsigned, "pointer_sha256": sha256_json(unsigned)})


def _receipt_object_payload(objects: Path, object_sha256: str, *, code: str = "DCC_PUBLICATION_RECEIPT_UNAVAILABLE") -> bytes:
    require_digest(object_sha256, path="publication receipt object sha256")
    target = objects / f"{object_sha256}.json"
    raw = _regular_file(target, code=code)
    if _object_hash(raw) != object_sha256:
        fail("DCC_PUBLICATION_OBJECT_HASH_INVALID", "A publication receipt object filename does not match its bytes.")
    return raw


def _load_active_publication_receipt_at(root: Path) -> tuple[dict[str, Any], dict[str, Any], bytes] | None:
    pointer_path = root / _ACTIVE_PUBLICATION_POINTER_NAME
    if pointer_path.is_symlink():
        fail("DCC_PUBLICATION_POINTER_UNAVAILABLE", "The active publication pointer is unavailable or non-regular.")
    if not pointer_path.exists():
        return None
    raw_pointer = _regular_file(pointer_path, code="DCC_PUBLICATION_POINTER_UNAVAILABLE")
    try:
        pointer_value = json.loads(raw_pointer.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail("DCC_PUBLICATION_POINTER_UNAVAILABLE", "The active publication pointer is unavailable or malformed.", details={"error_type": type(exc).__name__})
    pointer = _validate_active_publication_pointer(pointer_value)
    if raw_pointer != _canonical_json_bytes(pointer):
        fail("DCC_PUBLICATION_POINTER_NONCANONICAL", "The active publication pointer must use canonical UTF-8 JSON.")
    storage, objects, _ = _prepare_storage(root)
    del storage
    receipt_payload = _receipt_object_payload(objects, pointer["receipt_object_sha256"])
    try:
        receipt_value = json.loads(receipt_payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail("DCC_PUBLICATION_RECEIPT_UNAVAILABLE", "The active publication receipt is unavailable or malformed.", details={"error_type": type(exc).__name__})
    receipt_profile = _receipt_profile(receipt_value)
    receipt_descriptor = _load_dcc_source_rights_authority_for_profile(root, receipt_profile)
    receipt = _validate_publication_receipt(receipt_value, descriptor=receipt_descriptor)
    if receipt_payload != _canonical_json_bytes(receipt):
        fail("DCC_PUBLICATION_OBJECT_INVALID", "The active publication receipt must use canonical UTF-8 JSON.")
    if receipt["mode"] != "PUBLISH" or receipt["status"] != "PUBLISHED" or receipt["receipt_sha256"] != pointer["receipt_sha256"]:
        fail("DCC_PUBLICATION_POINTER_BINDING_INVALID", "The active publication pointer does not bind a published receipt.")
    for pointer_key, receipt_key in (
        ("source_rights_authority_sha256", "source_rights_authority_sha256"),
        ("semantic_authority_bundle_sha256", "semantic_authority_bundle_sha256"),
        ("source_rights_manifest_sha256", "new_source_rights_manifest_sha256"),
        ("semantic_manifest_sha256", "new_semantic_manifest_sha256"),
    ):
        if pointer[pointer_key] != receipt[receipt_key]:
            fail("DCC_PUBLICATION_POINTER_BINDING_INVALID", "The active publication pointer does not bind its receipt.")
    rights_path, semantic_path = _trust_paths(root)
    rights, rights_bytes = _load_trust_manifest(rights_path, semantic=False)
    semantic, semantic_bytes = _load_trust_manifest(semantic_path, semantic=True)
    if _object_hash(rights_bytes) != pointer["source_rights_manifest_sha256"] or _object_hash(semantic_bytes) != pointer["semantic_manifest_sha256"]:
        fail("DCC_PUBLICATION_POINTER_BINDING_INVALID", "The active publication pointer does not bind current trust manifests.")
    if rights["active_rights_authority_sha256"] != receipt["source_rights_authority_sha256"] or semantic["active_authority_bundle_sha256"] != receipt["semantic_authority_bundle_sha256"]:
        fail("DCC_PUBLICATION_POINTER_BINDING_INVALID", "The active publication pointer does not bind current authority identities.")
    return pointer, receipt, receipt_payload


_receipt_lookups = ValidationResultCache(limit=4)
_detached_validations = ValidationResultCache(limit=2)


def _receipt_directory_key(objects: Path) -> tuple[Any, ...]:
    # Lookup verifies every object's bytes on a miss. For the directory key,
    # ctime/inode-aware identities are sufficient to invalidate that result;
    # do not churn the bounded digest cache over unrelated historical objects
    # on every poll as the publication archive grows.
    return (file_fingerprint(objects), tuple(file_fingerprint(path) for path in sorted(objects.glob("*.json"))))


def dcc_publication_storage_key() -> tuple[Any, ...]:
    """Dependency key for route audits of historical detached publications.

    Include the directory inventory to notice deleted, replaced, or ambiguous
    receipt objects. Historical reopen uses stored objects, not active trust.
    """
    root = _authority_dir(None)
    _, objects, _ = _prepare_storage(root)
    return (str(root), _receipt_directory_key(objects))


def _find_receipt_object_by_internal_digest(objects: Path, receipt_sha256: str) -> tuple[dict[str, Any], bytes] | None:
    require_digest(receipt_sha256, path="predecessor publication receipt sha256")
    key = (receipt_sha256, _receipt_directory_key(objects))
    return _receipt_lookups.get_or_compute(
        key, lambda: _find_receipt_object_uncached(objects, receipt_sha256),
        still_current=lambda: _receipt_directory_key(objects) == key[1],
    )


def _find_receipt_object_uncached(objects: Path, receipt_sha256: str) -> tuple[dict[str, Any], bytes] | None:
    """Resolve an explicit receipt identity without ever picking an arbitrary match."""

    require_digest(receipt_sha256, path="predecessor publication receipt sha256")
    if not objects.exists() or objects.is_symlink() or not objects.is_dir():
        return None
    matches: list[tuple[dict[str, Any], bytes]] = []
    for path in sorted(objects.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        raw = path.read_bytes()
        if _object_hash(raw) != path.stem:
            continue
        try:
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, Mapping) or value.get("receipt_sha256") != receipt_sha256:
                continue
            receipt = _validate_publication_receipt(value)
        except (CreativeControllerError, UnicodeError, json.JSONDecodeError):
            continue
        matches.append((receipt, raw))
    if len(matches) > 1:
        fail("DCC_PUBLICATION_RECEIPT_AMBIGUOUS", "The explicit predecessor receipt identity is ambiguous.")
    return matches[0] if matches else None


def _find_existing_publication_receipt(
    objects: Path,
    *,
    database_sha256: str,
    candidate: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    snapshot: Mapping[str, Any] | Mapping[str, Any],
    admission_receipt: Mapping[str, Any],
    root: Path | None = None,
    predecessor_receipt_sha256: str | None = None,
) -> dict[str, Any] | None:
    """Resolve only the active pointer, or one exact crash-recovery match."""

    expected = {
        "database_sha256": database_sha256,
        "canonical_record_set_sha256": candidate["canonical_record_set_sha256"],
        "source_rights_authority_sha256": descriptor["authority_sha256"],
        "semantic_authority_bundle_sha256": candidate["authority_bundle"]["authority_bundle_sha256"],
        "content_snapshot_sha256": snapshot["content_snapshot_sha256"],
        "semantic_admission_receipt_sha256": admission_receipt["receipt_sha256"],
    }
    target_profile = _receipt_profile(
        {
            "schema": DCC_SEMANTIC_PUBLICATION_RECEIPT_V3_SCHEMA
            if descriptor.get("schema") == DCC_SOURCE_RIGHTS_AUTHORITY_V3_SCHEMA
            else DCC_SEMANTIC_PUBLICATION_RECEIPT_SCHEMA,
            "version": 3 if descriptor.get("schema") == DCC_SOURCE_RIGHTS_AUTHORITY_V3_SCHEMA else 2,
        }
    )
    if root is not None:
        active = _load_active_publication_receipt_at(root)
        if active is not None:
            _, receipt, _ = active
            if all(receipt.get(key) == expected[key] for key in expected) and (
                predecessor_receipt_sha256 is None or receipt.get("predecessor_receipt_sha256") == predecessor_receipt_sha256
            ):
                return receipt
            # A V3 successor is prepared while the current V2 pointer remains
            # active.  Let the exact predecessor gate validate that state;
            # any active V3 mismatch is still a pointer-binding failure.
            if _receipt_profile(receipt).name != "v2" or target_profile.name != "v3":
                fail("DCC_PUBLICATION_POINTER_BINDING_INVALID", "The active publication pointer does not match the prepared publication.")
    if not objects.exists() or objects.is_symlink() or not objects.is_dir():
        return None
    matches: list[dict[str, Any]] = []
    for path in sorted(objects.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            if _object_hash(raw) != path.stem:
                continue
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, Mapping):
                continue
            receipt_profile = _receipt_profile(value)
            if receipt_profile.name != target_profile.name:
                continue
            receipt = _validate_publication_receipt(value, descriptor=descriptor if receipt_profile.name == "v3" else None)
        except (CreativeControllerError, UnicodeError, json.JSONDecodeError):
            continue
        if all(receipt.get(key) == expected[key] for key in expected) and receipt.get("predecessor_receipt_sha256") == predecessor_receipt_sha256 and receipt["mode"] == "PUBLISH":
            matches.append(receipt)
    if len(matches) > 1:
        fail("DCC_PUBLICATION_RECEIPT_AMBIGUOUS", "More than one detached publication receipt matches the active publication.")
    return matches[0] if matches else None


def _validate_stored_receipt_objects(objects: Path, receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Reopen every object named by an explicit receipt and validate its hash."""

    values: dict[str, Any] = {}
    for row in receipt["objects"]:
        raw = _receipt_object_payload(objects, row["sha256"], code="DCC_PUBLICATION_OBJECT_UNAVAILABLE")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            fail("DCC_PUBLICATION_OBJECT_INVALID", "A stored publication object is not canonical JSON.", details={"error_type": type(exc).__name__})
        if not isinstance(value, Mapping) or (
            row["kind"] not in {"old_source_rights_trust", "old_semantic_trust"}
            and _canonical_json_bytes(value) != raw
        ):
            fail("DCC_PUBLICATION_OBJECT_INVALID", "A stored publication object is not canonical JSON.")
        values[row["kind"]] = value
    if set(values) != set(_OBJECT_KINDS):
        fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "A publication receipt does not bind every detached object.")
    return values


def _verify_predecessor_for_plan(
    plan: Mapping[str, Any],
    *,
    rights: Mapping[str, Any],
    rights_bytes: bytes,
    semantic: Mapping[str, Any],
    semantic_bytes: bytes,
    expected_receipt_sha256: str | None,
) -> None:
    """Verify an append-only predecessor before storage or activation writes."""

    if _is_v3_profile(plan["profile"]):
        _verify_v3_predecessor_for_plan(
            plan,
            rights=rights,
            rights_bytes=rights_bytes,
            semantic=semantic,
            semantic_bytes=semantic_bytes,
            expected_receipt_sha256=expected_receipt_sha256,
        )
        return

    target_rights = plan["descriptor"]["authority_sha256"]
    target_semantic = plan["authority_bundle"]["authority_bundle_sha256"]
    rights_changed = rights["status"] == "ACTIVE" and rights["active_rights_authority_sha256"] != target_rights
    semantic_changed = semantic["status"] == "ACTIVE" and semantic["active_authority_bundle_sha256"] != target_semantic
    requires_predecessor = rights_changed or semantic_changed
    if expected_receipt_sha256 is None:
        if rights_changed and not _known_v1_rights_authority(plan["root"], rights):
            fail("DCC_SOURCE_RIGHTS_AUTHORITY_CONFLICT", "An unrelated active source-rights authority cannot be replaced.")
        if semantic_changed and not _known_v1_semantic_authority(plan["root"], semantic, semantic_bytes):
            fail("DCC_SEMANTIC_AUTHORITY_CONFLICT", "An unrelated active semantic authority cannot be replaced.")
        if requires_predecessor:
            fail("DCC_PUBLICATION_PREDECESSOR_REQUIRED", "An active successor publication requires its exact predecessor receipt.")
        if (
            rights.get("active_rights_authority_sha256") == target_rights
            and semantic.get("active_authority_bundle_sha256") == target_semantic
            and _find_existing_publication_receipt(
                _prepare_storage(plan["root"])[1],
                database_sha256=plan["database_sha256"],
                candidate=plan["candidate"],
                descriptor=plan["descriptor"],
                snapshot=plan["content_snapshot"],
                admission_receipt=plan["semantic_admission_receipt"],
                root=plan["root"],
            )
            is None
        ):
            fail("DCC_PUBLICATION_POINTER_BINDING_INVALID", "The active publication has no uniquely bound stored receipt.")
        return
    require_digest(expected_receipt_sha256, path="expected predecessor receipt sha256")
    if not requires_predecessor and rights["status"] == "INACTIVE" and semantic["status"] == "INACTIVE":
        fail("DCC_PUBLICATION_PREDECESSOR_UNEXPECTED", "An initial publication cannot name a predecessor receipt.")
    already_active_successor: dict[str, Any] | None = None
    if (
        not requires_predecessor
        and rights.get("active_rights_authority_sha256") == target_rights
        and semantic.get("active_authority_bundle_sha256") == target_semantic
    ):
        # An already-active successor (or a crash after semantic activation)
        # may be resumed only when its detached receipt explicitly binds this
        # predecessor.  This keeps the exact predecessor CAS meaningful for
        # idempotent retries and for the pointer's guarded finalization.
        already_active_successor = _find_existing_publication_receipt(
            _prepare_storage(plan["root"])[1],
            database_sha256=plan["database_sha256"],
            candidate=plan["candidate"],
            descriptor=plan["descriptor"],
            snapshot=plan["content_snapshot"],
            admission_receipt=plan["semantic_admission_receipt"],
            root=plan["root"],
            predecessor_receipt_sha256=expected_receipt_sha256,
        )
        if already_active_successor is None:
            fail("DCC_PUBLICATION_PREDECESSOR_STALE", "The expected predecessor receipt does not bind current trust state.")
    storage, objects, _ = _prepare_storage(plan["root"])
    del storage
    found = _find_receipt_object_by_internal_digest(objects, expected_receipt_sha256)
    if found is None:
        fail("DCC_PUBLICATION_PREDECESSOR_UNAVAILABLE", "The expected predecessor receipt is not a valid stored publication receipt.")
    predecessor, _ = found
    if predecessor["mode"] != "PUBLISH" or predecessor["status"] != "PUBLISHED":
        fail("DCC_PUBLICATION_PREDECESSOR_INVALID", "The expected predecessor receipt is not published.")
    values = _validate_stored_receipt_objects(objects, predecessor)
    for key, kind in (
        ("old_source_rights_manifest_sha256", "old_source_rights_trust"),
        ("new_source_rights_manifest_sha256", "new_source_rights_trust"),
        ("old_semantic_manifest_sha256", "old_semantic_trust"),
        ("new_semantic_manifest_sha256", "new_semantic_trust"),
    ):
        entry = next(row for row in predecessor["objects"] if row["kind"] == kind)
        if predecessor[key] != entry["sha256"]:
            fail("DCC_PUBLICATION_PREDECESSOR_INVALID", "The predecessor receipt does not bind its trust objects.")
    current_rights_hash = _object_hash(rights_bytes)
    current_semantic_hash = _object_hash(semantic_bytes)
    fresh = (
        predecessor["new_source_rights_manifest_sha256"] == current_rights_hash
        and predecessor["new_semantic_manifest_sha256"] == current_semantic_hash
        and rights.get("active_rights_authority_sha256") == predecessor["source_rights_authority_sha256"]
        and semantic.get("active_authority_bundle_sha256") == predecessor["semantic_authority_bundle_sha256"]
    )
    resumed_rights = (
        current_rights_hash == _object_hash(plan["new_rights_bytes"])
        and current_semantic_hash == predecessor["new_semantic_manifest_sha256"]
        and rights.get("active_rights_authority_sha256") == target_rights
        and semantic.get("active_authority_bundle_sha256") == predecessor["semantic_authority_bundle_sha256"]
    )
    resumed_semantic = (
        current_rights_hash == _object_hash(plan["new_rights_bytes"])
        and current_semantic_hash == _object_hash(plan["new_semantic_bytes"])
        and rights.get("active_rights_authority_sha256") == target_rights
        and semantic.get("active_authority_bundle_sha256") == target_semantic
        and already_active_successor is not None
    )
    if not (fresh or resumed_rights or resumed_semantic):
        fail("DCC_PUBLICATION_PREDECESSOR_STALE", "The expected predecessor receipt does not bind current trust state.")
    # Validate the detached predecessor candidate and admission without making
    # it the current fixed trust root.  This is an explicit historical check.
    _validate_detached_publication(plan["root"], predecessor, receipt_payload=found[1])


def _verify_v3_predecessor_for_plan(
    plan: Mapping[str, Any],
    *,
    rights: Mapping[str, Any],
    rights_bytes: bytes,
    semantic: Mapping[str, Any],
    semantic_bytes: bytes,
    expected_receipt_sha256: str | None,
) -> None:
    """Enforce the exact active V2 receipt for the V2-to-V3 transition.

    The V3 successor is allowed to resume after either trust activation, but
    only when the original active V2 receipt remains the explicit predecessor
    (or the already-finalized V3 receipt carries that same predecessor).
    """

    if expected_receipt_sha256 is None:
        fail("DCC_PUBLICATION_PREDECESSOR_REQUIRED", "A V3 publication requires its exact active V2 predecessor receipt.")
    require_digest(expected_receipt_sha256, path="expected predecessor receipt sha256")

    storage, objects, _ = _prepare_storage(plan["root"])
    del storage
    found = _find_receipt_object_by_internal_digest(objects, expected_receipt_sha256)
    if found is None:
        fail("DCC_PUBLICATION_PREDECESSOR_UNAVAILABLE", "The expected V2 predecessor receipt is not a valid stored publication receipt.")
    predecessor, predecessor_payload = found
    if _receipt_profile(predecessor).name != "v2":
        fail("DCC_PUBLICATION_PREDECESSOR_INVALID", "The V3 transition predecessor must be a published V2 receipt.")
    if predecessor["mode"] != "PUBLISH" or predecessor["status"] != "PUBLISHED":
        fail("DCC_PUBLICATION_PREDECESSOR_INVALID", "The expected V2 predecessor receipt is not published.")
    _validate_stored_receipt_objects(objects, predecessor)
    _validate_detached_publication(plan["root"], predecessor, receipt_payload=predecessor_payload)

    active = _load_active_publication_receipt_at(plan["root"])
    active_receipt = active[1] if active is not None else None
    active_v2_predecessor = bool(
        active_receipt is not None
        and _receipt_profile(active_receipt).name == "v2"
        and active_receipt["receipt_sha256"] == expected_receipt_sha256
    )
    active_v3_successor = bool(
        active_receipt is not None
        and _receipt_profile(active_receipt).name == "v3"
        and active_receipt.get("predecessor_receipt_sha256") == expected_receipt_sha256
        and active_receipt["source_rights_authority_sha256"] == plan["descriptor"]["authority_sha256"]
        and active_receipt["semantic_authority_bundle_sha256"] == plan["authority_bundle"]["authority_bundle_sha256"]
    )
    current_rights_hash = _object_hash(rights_bytes)
    current_semantic_hash = _object_hash(semantic_bytes)
    predecessor_current = (
        active_v2_predecessor
        and predecessor["new_source_rights_manifest_sha256"] == current_rights_hash
        and predecessor["new_semantic_manifest_sha256"] == current_semantic_hash
        and rights.get("active_rights_authority_sha256") == predecessor["source_rights_authority_sha256"]
        and semantic.get("active_authority_bundle_sha256") == predecessor["semantic_authority_bundle_sha256"]
    )
    resumed_rights = (
        active_v2_predecessor
        and current_rights_hash == _object_hash(plan["new_rights_bytes"])
        and current_semantic_hash == predecessor["new_semantic_manifest_sha256"]
        and rights.get("active_rights_authority_sha256") == plan["descriptor"]["authority_sha256"]
        and semantic.get("active_authority_bundle_sha256") == predecessor["semantic_authority_bundle_sha256"]
    )
    resumed_semantic = (
        (active_v2_predecessor or active_v3_successor)
        and current_rights_hash == _object_hash(plan["new_rights_bytes"])
        and current_semantic_hash == _object_hash(plan["new_semantic_bytes"])
        and rights.get("active_rights_authority_sha256") == plan["descriptor"]["authority_sha256"]
        and semantic.get("active_authority_bundle_sha256") == plan["authority_bundle"]["authority_bundle_sha256"]
    )
    if not (predecessor_current or resumed_rights or resumed_semantic):
        fail("DCC_PUBLICATION_PREDECESSOR_STALE", "The expected V2 predecessor receipt is not the exact current publication state.")


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        fail("DCC_PUBLICATION_STORAGE_SYNC_FAILED", "Publication storage could not be durably synchronized.", details={"error_type": type(exc).__name__})


def _atomic_manifest_write(path: Path, payload: bytes) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        fail("DCC_PUBLICATION_TRUST_COLLISION", "A DCC trust manifest pointer is not a regular file.")
    fd, temporary_name = tempfile.mkstemp(prefix=".dcc-manifest-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        fail("DCC_PUBLICATION_STORAGE_WRITE_FAILED", "A DCC trust manifest could not be atomically stored.", details={"error_type": type(exc).__name__})


@contextmanager
def _publication_lock(storage: Path, lock_path: Path) -> Iterator[None]:
    _mkdir_storage(storage, storage / _OBJECTS_NAME)
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        fail("DCC_PUBLICATION_LOCK_FAILED", "The fixed publication lock could not be acquired.", details={"error_type": type(exc).__name__})
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    except OSError as exc:
        fail("DCC_PUBLICATION_LOCK_FAILED", "The fixed publication lock could not be acquired.", details={"error_type": type(exc).__name__})
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _reopen_publication_artifacts(
    objects: Path,
    *,
    receipt: Mapping[str, Any],
    expected_payloads: Mapping[str, bytes],
) -> dict[str, Any]:
    """Re-open and verify every detached artifact named by a publication receipt.

    On a crash after rights activation, the receipt's old-rights object is the
    pre-activation manifest while the current preflight plan naturally sees
    the now-active pointer. The two old-manifest objects are therefore
    validated structurally and by their receipt-bound hashes, while all
    newly-produced artifacts must still equal the current deterministic plan.
    """

    entries = receipt["objects"]
    values: dict[str, Any] = {}
    for row in entries:
        target = objects / f"{row['sha256']}.json"
        raw = _regular_file(target, code="DCC_PUBLICATION_OBJECT_UNAVAILABLE")
        if _object_hash(raw) != row["sha256"]:
            fail("DCC_PUBLICATION_OBJECT_HASH_INVALID", "A stored publication object filename does not match its bytes.")
        if row["kind"] not in {"old_source_rights_trust", "old_semantic_trust"} and raw != expected_payloads[row["kind"]]:
            fail("DCC_PUBLICATION_OBJECT_CHANGED", "A stored publication object changed after preflight.")
        try:
            values[row["kind"]] = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            fail("DCC_PUBLICATION_OBJECT_INVALID", "A stored publication object is not canonical JSON.", details={"error_type": type(exc).__name__})
    return values


def _revalidate_after_activation(
    *,
    root: Path,
    objects: Path,
    payloads: Mapping[str, bytes],
    receipt: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    database_sha256: str,
    profile: _PublicationProfile = _PROFILE_V2,
) -> None:
    # Validate the detached object list from the stored receipt itself. This
    # also permits a resume to retain the exact pre-activation old manifest.
    values = _reopen_publication_artifacts(objects, receipt=receipt, expected_payloads=payloads)
    descriptor = _load_dcc_source_rights_authority_for_profile(root, profile)
    if values["source_rights_authority"] != json.loads(payloads["source_rights_authority"].decode("utf-8")) or descriptor != values["source_rights_authority"]:
        fail("DCC_PUBLICATION_OBJECT_BINDING_INVALID", "The stored source-rights authority does not match the fixed descriptor.")
    _validate_trust_manifest(values["old_source_rights_trust"], semantic=False)
    _validate_trust_manifest(values["new_source_rights_trust"], semantic=False, allow_inactive=False)
    _validate_trust_manifest(values["old_semantic_trust"], semantic=True)
    _validate_trust_manifest(values["new_semantic_trust"], semantic=True, allow_inactive=False)
    registry = validate_semantic_profile_registry(values["registry"])
    overlay = validate_reviewed_semantic_overlay(values["overlay"])
    # The candidate validator is a fixed-trust public API.  For the isolated
    # test root, redirect only its fixed module constant for this bounded
    # validation window; production uses the checked-in root unchanged.
    with _fixed_trust_paths(root):
        candidate = _catalog_adapter.validate_factory_catalog_publication_candidate(values["candidate"])
    authority_bundle = validate_semantic_authority_bundle(values["authority_bundle"])
    snapshot = validate_content_snapshot(values["content_snapshot"])
    admission_receipt = _validate_admission_receipt(values["semantic_admission_receipt"])
    stored_receipt = _validate_publication_receipt(receipt, descriptor=descriptor)
    receipt_payload = _canonical_json_bytes(stored_receipt)
    receipt_target = objects / f"{_object_hash(receipt_payload)}.json"
    receipt_raw = _regular_file(receipt_target, code="DCC_PUBLICATION_OBJECT_UNAVAILABLE")
    if receipt_raw != receipt_payload:
        fail("DCC_PUBLICATION_OBJECT_CHANGED", "The stored publication receipt changed after activation.")
    try:
        reopened_receipt = _validate_publication_receipt(
            json.loads(receipt_raw.decode("utf-8")),
            descriptor=descriptor,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(
            "DCC_PUBLICATION_OBJECT_INVALID",
            "The stored publication receipt is not canonical JSON.",
            details={"error_type": type(exc).__name__},
        )
    if reopened_receipt != stored_receipt:
        fail("DCC_PUBLICATION_OBJECT_BINDING_INVALID", "The stored publication receipt does not match its detached evidence.")
    entry_by_kind = {row["kind"]: row["sha256"] for row in stored_receipt["objects"]}
    for receipt_key, object_kind in (
        ("old_source_rights_manifest_sha256", "old_source_rights_trust"),
        ("new_source_rights_manifest_sha256", "new_source_rights_trust"),
        ("old_semantic_manifest_sha256", "old_semantic_trust"),
        ("new_semantic_manifest_sha256", "new_semantic_trust"),
    ):
        if stored_receipt[receipt_key] != entry_by_kind[object_kind]:
            fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "Publication receipt does not bind a trust manifest object.")
    expected_receipt_bindings = {
        "database_sha256": database_sha256,
        "canonical_record_set_sha256": candidate["canonical_record_set_sha256"],
        "source_rights_authority_sha256": descriptor["authority_sha256"],
        "semantic_authority_bundle_sha256": authority_bundle["authority_bundle_sha256"],
        "content_snapshot_sha256": snapshot.content_snapshot_sha256,
        "semantic_admission_receipt_sha256": admission_receipt["receipt_sha256"],
    }
    if any(stored_receipt[key] != expected for key, expected in expected_receipt_bindings.items()):
        fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "Publication receipt does not bind the immutable publication inputs.")
    if candidate["authority_bundle"] != authority_bundle or snapshot.to_dict() != values["content_snapshot"]:
        fail("DCC_PUBLICATION_OBJECT_BINDING_INVALID", "Detached publication authority objects do not bind identically.")
    if stored_receipt["semantic_authority_bundle_sha256"] != authority_bundle["authority_bundle_sha256"]:
        fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "Publication receipt does not bind its stored authority bundle.")
    with _fixed_trust_paths(root):
        result = admit_typed_semantics(
            candidate["typed_records"],
            registry,
            authority_bundle,
            catalogue_schema_versions={candidate["catalogue_schema"]: candidate["catalogue_schema_version"]},
            rules_authority_sha256=candidate["canonical_record_set_sha256"],
            required_compiler_profile_sha256=profile.adapter_sha256,
        )
    if result.snapshot.to_dict() != snapshot.to_dict() or result.receipt != admission_receipt:
        fail("DCC_PUBLICATION_ADMISSION_BINDING_INVALID", "Re-opened semantic admission does not match stored detached evidence.")
    if records and len(records) != stored_receipt["record_count"]:
        fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "Publication receipt record count does not match the immutable catalogue.")
    if _is_v3_profile(profile):
        observed_family_counts = dict(sorted(Counter(row.get("content_type") for row in records).items()))
        if observed_family_counts != stored_receipt["family_counts"]:
            fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "Publication receipt family counts do not match the immutable catalogue.")


def _validate_admission_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema",
        "registry_sha256",
        "authority_bundle_sha256",
        "vocabulary_authority_sha256",
        "content_snapshot_sha256",
        "catalogue_set_sha256",
        "choice_semantics_set_sha256",
        "predicate_menu_sha256",
        "active_choice_ids",
        "record_count",
        "receipt_sha256",
    }
    require_exact_keys(value, required, path="semantic admission receipt")
    if value["schema"] != "TianxiaFoundry.SemanticAdmissionReceipt.v1":
        fail("DCC_SCHEMA_VALUE", "Unsupported semantic admission receipt schema.")
    validate_self_hash(value, "receipt_sha256", code="DCC_SEMANTIC_ADMISSION_RECEIPT_HASH_INVALID")
    for key in (
        "registry_sha256",
        "authority_bundle_sha256",
        "vocabulary_authority_sha256",
        "content_snapshot_sha256",
        "catalogue_set_sha256",
        "choice_semantics_set_sha256",
        "predicate_menu_sha256",
    ):
        require_digest(value[key], path=f"semantic admission receipt.{key}")
    active_ids = _unique_identifiers(value["active_choice_ids"], path="semantic admission receipt.active_choice_ids", maximum=8192)
    if active_ids != value["active_choice_ids"]:
        fail("DCC_SEMANTIC_ADMISSION_RECEIPT_NONCANONICAL", "Semantic admission active choice IDs must be sorted.")
    count = require_type(value["record_count"], int, path="semantic admission receipt.record_count")
    if count < 1 or count > 8192:
        fail("DCC_SCHEMA_LIMIT", "Semantic admission receipt record count is outside the supported bound.")
    unsigned = {key: value[key] for key in required - {"receipt_sha256"}}
    rebuilt = {**unsigned, "receipt_sha256": sha256_json(unsigned)}
    if rebuilt != dict(value):
        fail("DCC_SEMANTIC_ADMISSION_RECEIPT_NONCANONICAL", "Semantic admission receipt is not canonical.")
    return rebuilt


def _validate_detached_publication(
    root: Path,
    receipt: Mapping[str, Any],
    *,
    receipt_payload: bytes,
) -> dict[str, Any]:
    """Reuse admission only for the exact receipt and unchanged object bytes."""
    _receipt_profile(receipt)
    _, objects, _ = _prepare_storage(root)
    def content_key() -> tuple[Any, ...]:
        return (canonical_json(receipt), sha256_bytes(receipt_payload),
                tuple(file_content_key(objects / f"{row['sha256']}.json") for row in receipt["objects"]))
    key = content_key()
    return _detached_validations.get_or_compute(
        key, lambda: _validate_detached_publication_uncached(root, receipt, receipt_payload=receipt_payload),
        still_current=lambda: content_key() == key,
    )


def _validate_detached_publication_uncached(
    root: Path,
    receipt: Mapping[str, Any],
    *,
    receipt_payload: bytes,
) -> dict[str, Any]:
    """Validate a stored publication by its explicit receipt identity only."""

    profile = _receipt_profile(receipt)
    storage, objects, _ = _prepare_storage(root)
    del storage
    values = _validate_stored_receipt_objects(objects, receipt)
    descriptor = _validate_descriptor_value(values["source_rights_authority"], profile)
    _validate_trust_manifest(values["old_source_rights_trust"], semantic=False)
    new_rights = _validate_trust_manifest(values["new_source_rights_trust"], semantic=False, allow_inactive=False)
    _validate_trust_manifest(values["old_semantic_trust"], semantic=True)
    new_semantic = _validate_trust_manifest(values["new_semantic_trust"], semantic=True, allow_inactive=False)
    registry = validate_semantic_profile_registry(values["registry"])
    validate_reviewed_semantic_overlay(values["overlay"])
    candidate = _catalog_adapter._validate_factory_catalog_publication_candidate(
        values["candidate"],
        rights_trust=new_rights,
    )
    authority_bundle = validate_semantic_authority_bundle(values["authority_bundle"])
    snapshot = validate_content_snapshot(values["content_snapshot"])
    admission_receipt = _validate_admission_receipt(values["semantic_admission_receipt"])
    if candidate["authority_bundle"] != authority_bundle or candidate["source_rights_authority_sha256"] != new_rights["active_rights_authority_sha256"]:
        fail("DCC_PUBLICATION_OBJECT_BINDING_INVALID", "Detached publication candidate does not bind its authority objects.")
    if candidate["authority_bundle"]["authority_bundle_sha256"] != authority_bundle["authority_bundle_sha256"]:
        fail("DCC_PUBLICATION_OBJECT_BINDING_INVALID", "Detached publication candidate does not bind its authority bundle.")
    if receipt["source_rights_authority_sha256"] != descriptor["authority_sha256"] or receipt["semantic_authority_bundle_sha256"] != authority_bundle["authority_bundle_sha256"]:
        fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "Publication receipt does not bind its detached authority objects.")
    if receipt["canonical_record_set_sha256"] != candidate["canonical_record_set_sha256"]:
        fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "Publication receipt does not bind the detached candidate record set.")
    if receipt["content_snapshot_sha256"] != snapshot.content_snapshot_sha256 or receipt["semantic_admission_receipt_sha256"] != admission_receipt["receipt_sha256"]:
        fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "Publication receipt does not bind its detached semantic evidence.")
    receipt_object_hash = _object_hash(receipt_payload)
    entry_by_kind = {row["kind"]: row["sha256"] for row in receipt["objects"]}
    for receipt_key, object_kind in (
        ("old_source_rights_manifest_sha256", "old_source_rights_trust"),
        ("new_source_rights_manifest_sha256", "new_source_rights_trust"),
        ("old_semantic_manifest_sha256", "old_semantic_trust"),
        ("new_semantic_manifest_sha256", "new_semantic_trust"),
    ):
        if receipt[receipt_key] != entry_by_kind[object_kind]:
            fail("DCC_PUBLICATION_RECEIPT_BINDING_INVALID", "Publication receipt does not bind a trust manifest object.")
    admission = _admit_typed_semantics(
        candidate["typed_records"],
        registry,
        authority_bundle,
        catalogue_schema_versions={candidate["catalogue_schema"]: candidate["catalogue_schema_version"]},
        rules_authority_sha256=candidate["canonical_record_set_sha256"],
        required_compiler_profile_sha256=profile.adapter_sha256,
        expected_authority_bundle_sha256=authority_bundle["authority_bundle_sha256"],
    )
    if admission.snapshot.to_dict() != snapshot.to_dict() or admission.receipt != admission_receipt:
        fail("DCC_PUBLICATION_ADMISSION_BINDING_INVALID", "Detached semantic admission does not match its stored evidence.")
    return {
        "profile": profile,
        "source_rights_authority": descriptor,
        "source_rights_trust": new_rights,
        "semantic_trust": new_semantic,
        "registry": registry,
        "overlay": values["overlay"],
        "candidate": candidate,
        "authority_bundle": authority_bundle,
        "content_snapshot": snapshot.to_dict(),
        "semantic_admission_receipt": admission_receipt,
        "publication_receipt": _validate_publication_receipt(receipt, descriptor=descriptor),
        "receipt_object_sha256": receipt_object_hash,
    }


def load_active_dcc_semantic_publication() -> dict[str, Any]:
    """Resolve the active pointer using the descriptor bound to its receipt profile."""

    root = _authority_dir(None)
    active = _load_active_publication_receipt_at(root)
    if active is None:
        fail("DCC_PUBLICATION_POINTER_UNAVAILABLE", "The active DCC semantic publication pointer is unavailable.")
    pointer, receipt, receipt_payload = active
    profile = _receipt_profile(receipt)
    descriptor = _load_dcc_source_rights_authority_for_profile(root, profile)
    if descriptor["authority_sha256"] != receipt["source_rights_authority_sha256"]:
        fail("DCC_PUBLICATION_POINTER_BINDING_INVALID", "The active publication does not bind the current source-rights descriptor.")
    detached = _validate_detached_publication(root, receipt, receipt_payload=receipt_payload)
    return {"pointer": pointer, **detached}


def reopen_dcc_semantic_publication(
    receipt_sha256: str,
    *,
    test_authority_root: str | Path | None = None,
) -> dict[str, Any]:
    """Reopen a historical publication by its explicit receipt identity."""

    root = _authority_dir(Path(test_authority_root) if test_authority_root is not None else None)
    storage, objects, _ = _prepare_storage(root)
    del storage
    found = _find_receipt_object_by_internal_digest(objects, receipt_sha256)
    if found is None:
        fail("DCC_PUBLICATION_RECEIPT_UNAVAILABLE", "The requested publication receipt is not stored.")
    receipt, receipt_payload = found
    return _validate_detached_publication(root, receipt, receipt_payload=receipt_payload)


def _build_plan(
    database_path: Path,
    root: Path,
    *,
    profile: _PublicationProfile = _PROFILE_V2,
    predecessor_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    authority_input_sha256s = _authority_input_sha256s(root, profile)
    descriptor = _load_dcc_source_rights_authority_for_profile(root, profile)
    profile = _profile_with_descriptor_counts(profile, descriptor)
    _regular_file(root / profile.descriptor_name, code="DCC_SOURCE_RIGHTS_AUTHORITY_UNAVAILABLE")
    descriptor_bytes = _canonical_json_bytes(descriptor)
    source_trust_path, semantic_trust_path = _trust_paths(root)
    old_rights, old_rights_bytes = _load_trust_manifest(source_trust_path, semantic=False)
    old_semantic, old_semantic_bytes = _load_trust_manifest(semantic_trust_path, semantic=True)
    if (
        old_rights["status"] == "ACTIVE"
        and old_rights["active_rights_authority_sha256"] != descriptor["authority_sha256"]
        and not _known_v1_rights_authority(root, old_rights)
        and not (_is_v3_profile(profile) and _known_v2_rights_authority(root, old_rights))
    ):
        fail("DCC_SOURCE_RIGHTS_AUTHORITY_CONFLICT", "An unrelated active source-rights authority cannot be replaced.")
    records, family_counts, database_sha256 = _read_catalogue(database_path, profile)
    _prove_source_scope(records, descriptor)
    library = build_factory_semantic_library(
        records,
        rights_authority_id=descriptor["authority_id"],
        rights_authority_sha256=descriptor["authority_sha256"],
    )
    proposed_rights = _build_rights_trust(descriptor["authority_sha256"], old_rights)
    with _fixed_trust_paths(root):
        # This private helper uses the proposed trust only in memory.  It does
        # not activate or write either production trust manifest.
        candidate = _compile_factory_catalog_publication(
            records,
            library["registry"],
            library["overlay"],
            rights_trust=proposed_rights,
        )
    if candidate["status"] != "READY_FOR_OWNER_REVIEW" or not candidate["authority_bundle"] or candidate["diagnostics"]:
        fail(
            "DCC_PUBLICATION_PREFLIGHT_BLOCKED",
            "DCC semantic publication preflight is blocked.",
            details={"diagnostic_codes": sorted({row["code"] for row in candidate["diagnostics"]})},
        )
    authority_bundle = candidate["authority_bundle"]
    if (
        old_semantic["status"] == "ACTIVE"
        and old_semantic["active_authority_bundle_sha256"] != authority_bundle["authority_bundle_sha256"]
        and not _known_v1_semantic_authority(root, old_semantic, old_semantic_bytes)
        and not (_is_v3_profile(profile) and _known_v2_semantic_authority(root, old_semantic, old_semantic_bytes))
    ):
        fail("DCC_SEMANTIC_AUTHORITY_CONFLICT", "An unrelated active semantic authority cannot be replaced.")
    proposed_semantic = _build_semantic_trust(authority_bundle["authority_bundle_sha256"], old_semantic)
    # Full admission is deliberately performed before any storage, lock, or
    # manifest write.  The expected digest is the in-memory proposed trust.
    admission = _admit_typed_semantics(
        candidate["typed_records"],
        library["registry"],
        authority_bundle,
        catalogue_schema_versions={candidate["catalogue_schema"]: candidate["catalogue_schema_version"]},
        rules_authority_sha256=candidate["canonical_record_set_sha256"],
        required_compiler_profile_sha256=profile.adapter_sha256,
        expected_authority_bundle_sha256=proposed_semantic["active_authority_bundle_sha256"],
    )
    snapshot = admission.snapshot.to_dict()
    admission_receipt = admission.receipt
    payloads, object_entries = _prepare_objects(
        descriptor_bytes=descriptor_bytes,
        old_rights_manifest_bytes=old_rights_bytes,
        new_rights_manifest_bytes=_canonical_json_bytes(proposed_rights),
        old_semantic_manifest_bytes=old_semantic_bytes,
        new_semantic_manifest_bytes=_canonical_json_bytes(proposed_semantic),
        registry=library["registry"],
        overlay=library["overlay"],
        candidate=candidate,
        authority_bundle=authority_bundle,
        snapshot=snapshot,
        admission_receipt=admission_receipt,
    )
    receipt_dry_run = _make_publication_receipt(
        profile=profile,
        mode="DRY_RUN",
        record_count=len(records),
        family_counts=family_counts,
        database_sha256=database_sha256,
        candidate=candidate,
        descriptor=descriptor,
        snapshot=snapshot,
        admission_receipt=admission_receipt,
        old_rights_manifest_bytes=old_rights_bytes,
        new_rights_manifest_bytes=_canonical_json_bytes(proposed_rights),
        old_semantic_manifest_bytes=old_semantic_bytes,
        new_semantic_manifest_bytes=_canonical_json_bytes(proposed_semantic),
        objects=object_entries,
        predecessor_receipt_sha256=predecessor_receipt_sha256,
    )
    receipt_payload = _canonical_json_bytes(receipt_dry_run)
    if _authority_input_sha256s(root, profile) != authority_input_sha256s:
        fail("DCC_PUBLICATION_AUTHORITY_CHANGED", "A publication authority input changed during preflight.")
    # The receipt object is detached from the receipt's object list to avoid a
    # self-referential hash cycle, but it is still stored and hash-checked.
    payloads["publication_receipt"] = receipt_payload
    return {
        "profile": profile,
        "root": root,
        "database_path": database_path,
        "authority_input_sha256s": authority_input_sha256s,
        "records": records,
        "family_counts": family_counts,
        "database_sha256": database_sha256,
        "descriptor": descriptor,
        "descriptor_bytes": descriptor_bytes,
        "old_rights": old_rights,
        "old_rights_bytes": old_rights_bytes,
        "old_semantic": old_semantic,
        "old_semantic_bytes": old_semantic_bytes,
        "new_rights": proposed_rights,
        "new_rights_bytes": _canonical_json_bytes(proposed_rights),
        "new_semantic": proposed_semantic,
        "new_semantic_bytes": _canonical_json_bytes(proposed_semantic),
        "registry": library["registry"],
        "overlay": library["overlay"],
        "candidate": candidate,
        "authority_bundle": authority_bundle,
        "content_snapshot": snapshot,
        "semantic_admission_receipt": admission_receipt,
        "payloads": payloads,
        "object_entries": object_entries,
        "publication_receipt": receipt_dry_run,
    }


def _summary(plan: Mapping[str, Any], *, mode: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mode": mode,
        "status": receipt["status"],
        "candidate_status": plan["candidate"]["status"],
        "diagnostic_count": len(plan["candidate"]["diagnostics"]),
        "record_count": sum(plan["family_counts"].values()),
        "family_counts": dict(plan["family_counts"]),
        "database_sha256": plan["database_sha256"],
        "canonical_record_set_sha256": plan["candidate"]["canonical_record_set_sha256"],
        "source_rights_authority_sha256": plan["descriptor"]["authority_sha256"],
        "semantic_authority_bundle_sha256": plan["authority_bundle"]["authority_bundle_sha256"],
        "content_snapshot_sha256": plan["content_snapshot"]["content_snapshot_sha256"],
        "semantic_admission_receipt_sha256": plan["semantic_admission_receipt"]["receipt_sha256"],
        "receipt_sha256": receipt["receipt_sha256"],
        "objects": [dict(row) for row in plan["object_entries"]],
    }


def publish_dcc_semantic_library(
    database_path: str | Path | None = None,
    *,
    publish: bool = False,
    test_authority_root: str | Path | None = None,
    _failure_hook: Callable[[str], None] | None = None,
    expected_predecessor_receipt_sha256: str | None = None,
    _profile: _PublicationProfile | None = None,
) -> dict[str, Any]:
    """Preflight or explicitly publish the local DCC semantic library.

    ``test_authority_root`` and ``_failure_hook`` are test-only seams.  They
    are intentionally absent from the CLI so callers cannot choose a
    production trust root or publication destination.
    """

    profile = _PROFILE_V3 if _profile is None else _profile
    if publish and _is_v3_profile(profile):
        if expected_predecessor_receipt_sha256 is None:
            fail(
                "DCC_PUBLICATION_PREDECESSOR_REQUIRED",
                "A V3 publication requires the exact active V2 predecessor receipt.",
            )
        require_digest(expected_predecessor_receipt_sha256, path="expected predecessor receipt sha256")

    if database_path is None:
        database = Settings.from_env().db_path.resolve()
    else:
        database = Path(database_path).resolve()
    root = _authority_dir(Path(test_authority_root) if test_authority_root is not None else None)
    if expected_predecessor_receipt_sha256 is not None:
        require_digest(expected_predecessor_receipt_sha256, path="expected predecessor receipt sha256")
    plan = _build_plan(
        database,
        root,
        profile=profile,
        predecessor_receipt_sha256=expected_predecessor_receipt_sha256,
    )
    dry_receipt = plan["publication_receipt"]
    if not publish:
        return {
            "summary": _summary(plan, mode="DRY_RUN", receipt=dry_receipt),
            "source_rights_authority": plan["descriptor"],
            "source_rights_trust": plan["new_rights"],
            "semantic_trust": plan["new_semantic"],
            "registry": plan["registry"],
            "overlay": plan["overlay"],
            "candidate": plan["candidate"],
            "authority_bundle": plan["authority_bundle"],
            "content_snapshot": plan["content_snapshot"],
            "semantic_admission_receipt": plan["semantic_admission_receipt"],
            "publication_receipt": dry_receipt,
        }

    storage, objects, lock_path = _prepare_storage(root)
    # This read-only gate deliberately precedes storage creation and lock
    # acquisition.  A missing, wrong, or stale predecessor therefore leaves
    # the authority root byte-for-byte unchanged.
    _verify_predecessor_for_plan(
        plan,
        rights=plan["old_rights"],
        rights_bytes=plan["old_rights_bytes"],
        semantic=plan["old_semantic"],
        semantic_bytes=plan["old_semantic_bytes"],
        expected_receipt_sha256=expected_predecessor_receipt_sha256,
    )
    with _publication_lock(storage, lock_path):
        # Re-read the two pointers after taking the lock.  A concurrent
        # publisher must not silently replace a trust root seen at preflight.
        current_rights, current_rights_bytes = _load_trust_manifest(_trust_paths(root)[0], semantic=False)
        current_semantic, current_semantic_bytes = _load_trust_manifest(_trust_paths(root)[1], semantic=True)
        if current_rights_bytes != plan["old_rights_bytes"] or current_semantic_bytes != plan["old_semantic_bytes"]:
            fail("DCC_PUBLICATION_TRUST_CHANGED", "The DCC trust pointers changed during preflight.")
        if sha256_file(plan["database_path"]) != plan["database_sha256"]:
            fail("DCC_PUBLICATION_DATABASE_CHANGED", "The catalogue database changed before publication writes.")
        if _authority_input_sha256s(root, profile) != plan["authority_input_sha256s"]:
            fail("DCC_PUBLICATION_AUTHORITY_CHANGED", "A publication authority input changed before publication writes.")
        _verify_predecessor_for_plan(
            plan,
            rights=current_rights,
            rights_bytes=current_rights_bytes,
            semantic=current_semantic,
            semantic_bytes=current_semantic_bytes,
            expected_receipt_sha256=expected_predecessor_receipt_sha256,
        )
        _mkdir_storage(storage, objects)
        _check_object_collisions(objects, plan["payloads"], plan["object_entries"])
        receipt = _find_existing_publication_receipt(
            objects,
            database_sha256=plan["database_sha256"],
            candidate=plan["candidate"],
            descriptor=plan["descriptor"],
            snapshot=plan["content_snapshot"],
            admission_receipt=plan["semantic_admission_receipt"],
            root=root,
            predecessor_receipt_sha256=expected_predecessor_receipt_sha256,
        )
        if receipt is None:
            receipt = dict(dry_receipt)
            receipt["mode"] = "PUBLISH"
            receipt["status"] = "PUBLISHED"
            receipt["receipt_sha256"] = sha256_json({key: receipt[key] for key in _RECEIPT_KEYS - {"receipt_sha256"}})
            receipt = _validate_publication_receipt(receipt)
        receipt_payload = _canonical_json_bytes(receipt)
        receipt_digest = _object_hash(receipt_payload)
        receipt_target = objects / f"{receipt_digest}.json"
        if receipt_target.is_symlink() or (receipt_target.exists() and (not receipt_target.is_file() or receipt_target.read_bytes() != receipt_payload)):
            fail("DCC_PUBLICATION_OBJECT_COLLISION", "The publication receipt object collides with different bytes.")
        for kind in _OBJECT_KINDS:
            _write_object(objects, plan["payloads"][kind], next(row["sha256"] for row in plan["object_entries"] if row["kind"] == kind))
        _write_object(objects, receipt_payload, receipt_digest)
        source_trust_path, semantic_trust_path = _trust_paths(root)
        if source_trust_path.read_bytes() != plan["new_rights_bytes"]:
            _atomic_manifest_write(source_trust_path, plan["new_rights_bytes"])
        if _failure_hook is not None:
            _failure_hook("after_rights_activation")
        with _fixed_trust_paths(root):
            _catalog_adapter.validate_factory_catalog_publication_candidate(plan["candidate"])
        if semantic_trust_path.read_bytes() != plan["new_semantic_bytes"]:
            _atomic_manifest_write(semantic_trust_path, plan["new_semantic_bytes"])
        pointer = _make_active_publication_pointer(receipt, receipt_digest)
        pointer_path = root / _ACTIVE_PUBLICATION_POINTER_NAME
        pointer_payload = _canonical_json_bytes(pointer)
        if pointer_path.is_symlink() or not pointer_path.exists() or pointer_path.read_bytes() != pointer_payload:
            _atomic_manifest_write(pointer_path, pointer_payload)
        _revalidate_after_activation(
            root=root,
            objects=objects,
            payloads={**plan["payloads"], "publication_receipt": receipt_payload},
            receipt=receipt,
            records=plan["records"],
            database_sha256=plan["database_sha256"],
            profile=plan["profile"],
        )
        if sha256_file(plan["database_path"]) != plan["database_sha256"]:
            fail("DCC_PUBLICATION_DATABASE_CHANGED", "The catalogue database changed during publication.")
    result = {
        "summary": _summary(plan, mode="PUBLISH", receipt=receipt),
        "source_rights_authority": plan["descriptor"],
        "source_rights_trust": plan["new_rights"],
        "semantic_trust": plan["new_semantic"],
        "registry": plan["registry"],
        "overlay": plan["overlay"],
        "candidate": plan["candidate"],
        "authority_bundle": plan["authority_bundle"],
        "content_snapshot": plan["content_snapshot"],
        "semantic_admission_receipt": plan["semantic_admission_receipt"],
        "publication_receipt": receipt,
    }
    return result


__all__ = [
    "DCC_SEMANTIC_PUBLICATION_RECEIPT_SCHEMA",
    "DCC_SOURCE_RIGHTS_AUTHORITY_SCHEMA",
    "load_dcc_source_rights_authority",
    "publish_dcc_semantic_library",
]
