"""Compiler-backed Method/Foundation selection authority.

The Stage 1 catalog is intentionally broader than the compiler's active rules
corpus.  This module creates the small, server-owned intersection used by the
delegated-choice boundary.  It never accepts a path from a request and never
uses the application catalog as compiler evidence: every selectable row must
be proved by an active source in the pinned corpus.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable

from . import method_corpus_release, foundation_corpus_release
from . import release_descriptor as releases
from .release_projection import (
    normalize_canonical_option_name, _safe_member, _read_source, _line_name,
    _records_by_id, _evidence,
    _method_excerpt as _project_method_excerpt,
    _foundation_excerpt as _project_foundation_excerpt,
)

from app.core import (
    CORE_PACK_ID,
    CORE_PACK_VERSION,
    EXPECTED_FACTORY_HASH,
    FACTORY_VERSION,
    FoundryError,
    sha256_file,
    sha256_json,
)


COMPILER_SELECTION_AUTHORITY_SCHEMA = releases.DESCRIPTOR.release("base").data["schema"]
RELEASED_COMPILER_SELECTION_AUTHORITY_SCHEMA = releases.DESCRIPTOR.release("methods").data["schema"]
FOUNDATION_COMPILER_SELECTION_AUTHORITY_SCHEMA = releases.DESCRIPTOR.release("foundations").data["schema"]
_BASE_RELEASE = releases.select_release(key="base")
PINNED_COMPILER_SHA256 = releases.DESCRIPTOR.data["compiler"]["compiler_sha256"]
PINNED_CORPUS_SHA256 = _BASE_RELEASE.data["corpus_sha256"]
PINNED_FACTORY_ROOT_TREE_SHA256 = releases.DESCRIPTOR.data["compiler"]["factory_root_tree_sha256"]
PINNED_CORPUS_MANIFEST_SHA256 = _BASE_RELEASE.data["manifest_sha256"]
PINNED_ACTIVE_SOURCE_INDEX_SHA256 = _BASE_RELEASE.data["active_source_index_sha256"]
PINNED_CORE_PACK_HASH = "08c0e595cd32e084389cd41bafc019561e471c01cd86c65006e1dc01a36155fa"
# Historical core-pack releases whose project content locks remain valid. A
# project locks the catalog rows of the release current when it was created, so
# an older lock must keep resolving to its own exact hash; the current release
# is always the last entry and equals PINNED_CORE_PACK_HASH.
ACCEPTED_CORE_PACK_HASHES_BY_VERSION: dict[str, str] = {
    "2.9.3": "16f8af8d28cade3004a6e3f674043babc7322afebbb05f5ded65dbd1f3a33c5b",
    "2.9.4": "f9dde3cc9a069372e5985e207ee2c19b97b4aafd9988ac1b60c9a815c3ac0099",
    "2.9.5": "f8468c7e3531e0f28c9d473d563450ae573b6100610a58afe28f5eb301bb00f6",
    CORE_PACK_VERSION: PINNED_CORE_PACK_HASH,
}
PINNED_METHOD_RECORD_PROJECTION_SHA256 = _BASE_RELEASE.data["projection"]["method_records_sha256"]
PINNED_FOUNDATION_RECORD_PROJECTION_SHA256 = _BASE_RELEASE.data["projection"]["foundation_records_sha256"]
PINNED_BACKED_METHOD_IDS_SHA256 = _BASE_RELEASE.data["projection"]["compiler_backed_method_ids_sha256"]
PINNED_BACKED_FOUNDATION_IDS_SHA256 = _BASE_RELEASE.data["projection"]["compiler_backed_foundation_ids_sha256"]
PINNED_COMPILER_RELATIVE_PATH = releases.DESCRIPTOR.data["compiler"]["compiler_relative_path"]
PINNED_CORPUS_RELATIVE_PATH = releases.DESCRIPTOR.data["compiler"]["corpus_relative_path"]
CORPUS_MANIFEST_MEMBER = releases.DESCRIPTOR.data["manifest_member"]
METHOD_SOURCE_MEMBER = releases.DESCRIPTOR.data["legacy_method_member"]
NOT_COMPILER_BACKED_CODE = "CG1_DELEGATED_CHOICE_NOT_COMPILER_BACKED"
_SERVER_SNAPSHOT_TOKEN = object()


class CompilerSelectionAuthoritySnapshot(dict[str, Any]):
    """Non-forgeable-in-process marker for the server-built snapshot.

    The persisted request contains a plain JSON object and is rechecked by
    :func:`verify_compiler_selection_authority`.  During request assembly the
    marker prevents an arbitrary caller from supplying a self-consistent dict
    as if it had been read from the pinned Factory installation.
    """

    def __init__(self, payload: dict[str, Any], *, _token: object | None = None) -> None:
        if _token is not _SERVER_SNAPSHOT_TOKEN:
            raise TypeError("CompilerSelectionAuthoritySnapshot is server-constructed only")
        super().__init__(payload)
        self._server_snapshot_token = _SERVER_SNAPSHOT_TOKEN

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        # A copied snapshot intentionally loses the in-process admission marker;
        # persisted/request-provided dictionaries must never be mistaken for a
        # server-built authority during request assembly.
        return deepcopy(dict(self), memo)


def _error(code: str, message: str, *, details: Any = None, status_code: int = 503) -> FoundryError:
    return FoundryError(code, message, details=details, status_code=status_code)


def _regular_file(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise _error(
            "CG1_COMPILER_AUTHORITY_DEPENDENCY_INVALID",
            "The pinned compiler authority dependency is missing or is not a regular file.",
            details={"label": label, "path": str(path)},
        )
    return path


def _assert_no_symlink_path(path: Path, *, boundary: Path, label: str) -> None:
    """Reject symlink components before trusting a configured extracted root."""

    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise _error(
            "CG1_COMPILER_AUTHORITY_PATH_ESCAPE",
            "The configured Factory root escapes the server-owned vendor boundary.",
            details={"label": label, "path": str(path), "boundary": str(boundary)},
        ) from exc
    current = boundary
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise _error(
                "CG1_COMPILER_AUTHORITY_SYMLINK",
                "Symlinked compiler authority dependencies are not trusted.",
                details={"label": label, "path": str(current)},
            )


def _root_tree_rows(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        # Python bytecode is process-generated in the extracted trust root;
        # it is not a compiler dependency and must not turn a clean extraction
        # into a different authority tree after an import.
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_dir():
            continue
        if path.is_symlink():
            raise _error(
                "CG1_COMPILER_AUTHORITY_SYMLINK",
                "The pinned Factory trust root contains a symlink.",
                details={"path": str(path)},
            )
        if not path.is_file():
            raise _error(
                "CG1_COMPILER_AUTHORITY_DEPENDENCY_INVALID",
                "The pinned Factory trust root contains a non-regular entry.",
                details={"path": str(path)},
            )
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        })
    return rows


def _resolve_pinned_factory_root(vendor_dir: Path) -> tuple[Path, dict[str, Any]]:
    vendor = Path(vendor_dir).resolve()
    config_path = _regular_file(vendor / "factory_adapter.json", label="factory_adapter.json")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _error(
            "CG1_COMPILER_AUTHORITY_CONFIG_INVALID",
            "The configured Factory adapter record is not valid JSON.",
            details={"path": str(config_path)},
        ) from exc
    if not isinstance(config, dict) or config.get("factory_zip_hash") != EXPECTED_FACTORY_HASH:
        raise _error(
            "CG1_COMPILER_AUTHORITY_FACTORY_PIN_MISMATCH",
            "The configured Factory adapter is not bound to the pinned archive.",
            details={"expected_factory_hash": EXPECTED_FACTORY_HASH, "configured": config.get("factory_zip_hash") if isinstance(config, dict) else None},
        )
    raw_root = config.get("factory_root")
    if not isinstance(raw_root, str) or not raw_root:
        raise _error(
            "CG1_COMPILER_AUTHORITY_CONFIG_INVALID",
            "The configured Factory adapter has no extracted root.",
            details={"path": str(config_path)},
        )
    extracted = (vendor / "extracted" / EXPECTED_FACTORY_HASH).resolve()
    root = Path(raw_root).resolve()
    _assert_no_symlink_path(extracted, boundary=vendor, label="extracted Factory root")
    _assert_no_symlink_path(root, boundary=extracted, label="configured Factory root")
    if not root.is_dir():
        raise _error(
            "CG1_COMPILER_AUTHORITY_ROOT_MISSING",
            "The pinned extracted Factory root is unavailable.",
            details={"path": str(root)},
        )
    manifest_path = _regular_file(root / "FACTORY_MANIFEST.json", label="FACTORY_MANIFEST.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _error(
            "CG1_COMPILER_AUTHORITY_MANIFEST_INVALID",
            "The pinned Factory manifest cannot be read as JSON.",
            details={"path": str(manifest_path)},
        ) from exc
    if not isinstance(manifest, dict) or FACTORY_VERSION not in str(manifest.get("factory") or manifest.get("factory_version") or ""):
        raise _error(
            "CG1_COMPILER_AUTHORITY_FACTORY_VERSION_MISMATCH",
            "The extracted Factory manifest is not the pinned producer.",
            details={"expected": FACTORY_VERSION, "actual": manifest.get("factory") if isinstance(manifest, dict) else None},
        )
    rows = _root_tree_rows(root)
    tree_hash = sha256_json(rows)
    if tree_hash != PINNED_FACTORY_ROOT_TREE_SHA256:
        raise _error(
            "CG1_COMPILER_AUTHORITY_ROOT_HASH_MISMATCH",
            "The complete extracted Factory trust root differs from the pinned dependency tree.",
            details={"expected": PINNED_FACTORY_ROOT_TREE_SHA256, "actual": tree_hash},
        )
    compiler = _regular_file(root / PINNED_COMPILER_RELATIVE_PATH, label="pinned compiler")
    corpus = _regular_file(root / PINNED_CORPUS_RELATIVE_PATH, label="pinned corpus")
    compiler_hash = sha256_file(compiler)
    corpus_hash = sha256_file(corpus)
    if compiler_hash != PINNED_COMPILER_SHA256 or corpus_hash != PINNED_CORPUS_SHA256:
        raise _error(
            "CG1_COMPILER_AUTHORITY_CONTENT_HASH_MISMATCH",
            "The compiler or active rules corpus differs from the pinned content.",
            details={
                "compiler": {"expected": PINNED_COMPILER_SHA256, "actual": compiler_hash},
                "corpus": {"expected": PINNED_CORPUS_SHA256, "actual": corpus_hash},
            },
        )
    return root, {
        "factory_archive_sha256": EXPECTED_FACTORY_HASH,
        "factory_root_tree_sha256": tree_hash,
        "compiler_relative_path": PINNED_COMPILER_RELATIVE_PATH,
        "compiler_sha256": compiler_hash,
        "corpus_relative_path": PINNED_CORPUS_RELATIVE_PATH,
        "corpus_sha256": corpus_hash,
        "factory_version": FACTORY_VERSION,
    }


def _method_excerpt(zf, canonical_name, active):
    return _project_method_excerpt(zf, canonical_name, active, method_member=METHOD_SOURCE_MEMBER,
                                   source_member=method_corpus_release.SOURCE_MEMBER,
                                   source_sha256=method_corpus_release.SOURCE_SHA256)


def _foundation_excerpt(zf, canonical_name, active):
    return _project_foundation_excerpt(zf, canonical_name, active,
                                       member_prefix=foundation_corpus_release.MEMBER_PREFIX)


def _content_binding(content_lock: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(content_lock, dict):
        raise _error("CG1_COMPILER_AUTHORITY_CONTENT_LOCK_MISSING", "A frozen project content lock is required for compiler selection authority.")
    lock_hash = content_lock.get("lock_hash")
    packs = content_lock.get("packs")
    core_rows = [row for row in packs or [] if isinstance(row, dict) and row.get("pack_id") == CORE_PACK_ID and row.get("version") in ACCEPTED_CORE_PACK_HASHES_BY_VERSION]
    core = next((row for row in core_rows if row.get("version") == CORE_PACK_VERSION), core_rows[0] if core_rows else None)
    core_version = core.get("version") if isinstance(core, dict) else CORE_PACK_VERSION
    pack_hash = (
        (core.get("pack_hash") or core.get("content_hash"))
        if isinstance(core, dict)
        else None
    )
    if not (isinstance(lock_hash, str) and re.fullmatch(r"[0-9a-f]{64}", lock_hash)) or not (isinstance(pack_hash, str) and re.fullmatch(r"[0-9a-f]{64}", pack_hash)):
        raise _error(
            "CG1_COMPILER_AUTHORITY_CONTENT_LOCK_INVALID",
            "The frozen project content lock lacks an exact core-pack hash.",
            details={"content_lock_hash": lock_hash, "core_pack_hash": pack_hash},
        )
    if pack_hash != ACCEPTED_CORE_PACK_HASHES_BY_VERSION[core_version]:
        raise _error(
            "CG1_COMPILER_AUTHORITY_CORE_PACK_PIN_MISMATCH",
            "The frozen project content lock is not bound to the pinned HF05 core pack.",
            details={"expected_core_pack_hash": ACCEPTED_CORE_PACK_HASHES_BY_VERSION[core_version], "actual_core_pack_hash": pack_hash, "core_pack_version": core_version},
        )
    return {"content_lock_hash": lock_hash, "core_pack_id": CORE_PACK_ID, "core_pack_version": core_version, "core_pack_hash": pack_hash}


def build_compiler_selection_authority(
    vendor_dir: Path,
    *,
    content_lock: dict[str, Any],
    method_records: Iterable[dict[str, Any]],
    foundation_records: Iterable[dict[str, Any]],
    include_complete_foundations: bool = True,
) -> dict[str, Any]:
    """Build a deterministic compiler-backed authority snapshot.

    ``vendor_dir`` is supplied by server settings, never by a request.  The
    returned dictionary is safe to embed in a sealed request after this method
    has verified all dependency and source hashes.
    """

    root, compiler = _resolve_pinned_factory_root(Path(vendor_dir))
    content = _content_binding(content_lock)
    release = releases.select_release(key="foundations" if include_complete_foundations else "methods", consumer="selection")
    corpus_path, verified = releases.ensure_release(release, Path(vendor_dir), root / PINNED_CORPUS_RELATIVE_PATH)
    projected = verified.project_catalog(method_records, foundation_records)
    payload: dict[str, Any] = {
        "schema": release.data["schema"],
        "factory": compiler,
        **release.bindings(),
        **projected,
        "content": content,
        "provider_policy": {
            "selection_ids_are_closed_world": True,
            "response_prose_grants_no_authority": True,
            "classification_for_selectable_records": "tianxia_rules",
            "nonselectable_reason_code": NOT_COMPILER_BACKED_CODE,
        },
    }
    payload["authority_sha256"] = sha256_json(payload)
    snapshot = CompilerSelectionAuthoritySnapshot(payload, _token=_SERVER_SNAPSHOT_TOKEN)
    # Do not hand a caller-provided catalog projection to the request builder
    # merely because this function could hash it.  The complete projection and
    # its source bindings are pinned above and must pass the same gate used for
    # persisted/request-provided payloads before admission.
    verify_compiler_selection_authority(snapshot, expected_content_lock=content_lock)
    return snapshot


def verify_compiler_selection_authority(
    payload: dict[str, Any],
    *,
    expected_content_lock: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the self-consistency of a sealed authority payload."""

    if not isinstance(payload, dict) or payload.get("schema") not in {COMPILER_SELECTION_AUTHORITY_SCHEMA, RELEASED_COMPILER_SELECTION_AUTHORITY_SCHEMA, FOUNDATION_COMPILER_SELECTION_AUTHORITY_SCHEMA}:
        raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_INVALID", "The delegated compiler-selection authority has an unknown schema.", status_code=409)
    release = releases.select_release(schema=payload["schema"], consumer="selection")
    bindings = release.bindings()
    for field, message in (
        ("foundation_corpus_release", "The Foundation release identity does not match the exact snapshot version."),
        ("method_corpus_release", "The Method corpus release identity does not match the exact snapshot version."),
    ):
        if (field in bindings and payload.get(field) != bindings[field]) or (field not in bindings and field in payload):
            raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_PIN_MISMATCH", message, status_code=409)
    corpus_hash = release.data["corpus_sha256"]
    manifest_hash = release.data["manifest_sha256"]
    source_index_hash = release.data["active_source_index_sha256"]
    actual = sha256_json({key: value for key, value in payload.items() if key != "authority_sha256"})
    if actual != payload.get("authority_sha256"):
        raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_TAMPERED", "The delegated compiler-selection authority hash does not match its evidence.", status_code=409, details={"expected": payload.get("authority_sha256"), "actual": actual})
    factory = payload.get("factory") or {}
    expected_factory = releases.thaw(releases.DESCRIPTOR.data["compiler"])
    if any(factory.get(key) != value for key, value in expected_factory.items()):
        raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_PIN_MISMATCH", "The delegated compiler-selection authority is not bound to the pinned Factory dependency set.", status_code=409, details={"expected": expected_factory, "actual": factory})
    content = payload.get("content") or {}
    expected_content_shape = {
        "core_pack_id": CORE_PACK_ID,
        "core_pack_version": sorted(ACCEPTED_CORE_PACK_HASHES_BY_VERSION),
        "core_pack_hash": ACCEPTED_CORE_PACK_HASHES_BY_VERSION.get(str(content.get("core_pack_version"))),
    }
    if (
        content.get("core_pack_id") != CORE_PACK_ID
        or content.get("core_pack_version") not in ACCEPTED_CORE_PACK_HASHES_BY_VERSION
        or content.get("core_pack_hash") != expected_content_shape["core_pack_hash"]
    ):
        raise _error(
            "CG1_DELEGATED_COMPILER_AUTHORITY_CONTENT_MISMATCH",
            "The delegated compiler-selection authority is not bound to the pinned HF05 core pack identity.",
            status_code=409,
            details={"expected": expected_content_shape, "actual": content},
        )
    if expected_content_lock is not None:
        expected_content = _content_binding(expected_content_lock)
        if content != expected_content:
            raise _error(
                "CG1_DELEGATED_COMPILER_AUTHORITY_CONTENT_STALE",
                "The delegated compiler-selection authority is bound to a different project content lock.",
                status_code=409,
                details={"expected": expected_content, "actual": content},
            )
    source_authority = payload.get("source_authority") or {}
    active_source_index = source_authority.get("active_source_index")
    if (
        source_authority.get("manifest_sha256") != manifest_hash
        or source_authority.get("active_source_index_sha256") != source_index_hash
        or not isinstance(active_source_index, list)
        or sha256_json(active_source_index) != source_index_hash
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("source_path"), str)
            or not isinstance(row.get("source_file_sha256"), str)
            or set(row) != {"source_path", "source_file_sha256"}
            for row in active_source_index
        )
    ):
        raise _error(
            "CG1_DELEGATED_COMPILER_AUTHORITY_SOURCE_INDEX_MISMATCH",
            "The delegated compiler-selection authority is not bound to the pinned active corpus source index.",
            status_code=409,
            details={
                "expected_manifest_sha256": manifest_hash,
                "actual_manifest_sha256": source_authority.get("manifest_sha256"),
                "expected_source_index_sha256": source_index_hash,
                "actual_source_index_sha256": source_authority.get("active_source_index_sha256"),
            },
        )
    source_index = {row["source_path"]: row["source_file_sha256"] for row in active_source_index}
    if len(source_index) != len(active_source_index):
        raise _error(
            "CG1_DELEGATED_COMPILER_AUTHORITY_SOURCE_INDEX_MISMATCH",
            "The delegated compiler-selection authority repeats an active corpus source path.",
            status_code=409,
        )
    projection = payload.get("projection") or {}
    method_records = (payload.get("method_choice") or {}).get("records")
    foundation_records = (payload.get("foundation_choice") or {}).get("records")
    backed_method_ids = (payload.get("method_choice") or {}).get("compiler_backed_ids")
    backed_foundation_ids = (payload.get("foundation_choice") or {}).get("compiler_backed_ids")
    expected_projection = releases.thaw(release.data["projection"])
    actual_projection = {
        "method_records_sha256": sha256_json(method_records),
        "foundation_records_sha256": sha256_json(foundation_records),
        "compiler_backed_method_ids_sha256": sha256_json(backed_method_ids),
        "compiler_backed_foundation_ids_sha256": sha256_json(backed_foundation_ids),
    }
    if projection != expected_projection or actual_projection != expected_projection:
        raise _error(
            "CG1_DELEGATED_COMPILER_AUTHORITY_PROJECTION_MISMATCH",
            "The delegated compiler-selection authority does not match the pinned complete Method/Foundation projection.",
            status_code=409,
            details={"expected": expected_projection, "declared": projection, "actual": actual_projection},
        )
    for slot_id in ("method_choice", "foundation_choice"):
        section = payload.get(slot_id) or {}
        records = section.get("records") if isinstance(section, dict) else None
        backed = section.get("compiler_backed_ids") if isinstance(section, dict) else None
        if not isinstance(records, dict) or not isinstance(backed, list) or backed != sorted(backed) or set(backed) != {key for key, row in records.items() if isinstance(row, dict) and row.get("selectable") is True}:
            raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_INVALID", "The delegated compiler-selection authority has inconsistent option indexes.", status_code=409, details={"slot_id": slot_id})
        for choice_id, row in records.items():
            if (
                not isinstance(row, dict)
                or row.get("choice_id") != choice_id
                or row.get("classification") not in {"tianxia_rules", "unbacked"}
                or not isinstance(row.get("canonical_name"), str)
                or row.get("normalized_canonical_name") != normalize_canonical_option_name(row.get("canonical_name"))
                or row.get("corpus_sha256") != corpus_hash
                or row.get("factory_root_tree_sha256") != PINNED_FACTORY_ROOT_TREE_SHA256
            ):
                raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_INVALID", "The delegated compiler-selection authority contains an invalid option record.", status_code=409, details={"slot_id": slot_id, "choice_id": choice_id})
            if row.get("selectable") is True:
                source_path = row.get("source_path")
                if (
                    row.get("classification") != "tianxia_rules"
                    or not isinstance(source_path, str)
                    or source_path not in source_index
                    or row.get("source_file_sha256") != source_index[source_path]
                    or row.get("corpus_sha256") != corpus_hash
                    or row.get("factory_root_tree_sha256") != PINNED_FACTORY_ROOT_TREE_SHA256
                    or not isinstance(row.get("source_text"), str)
                    or row.get("source_excerpt_sha256") != sha256(row["source_text"].encode("utf-8")).hexdigest()
                    or normalize_canonical_option_name(row.get("canonical_name")) not in normalize_canonical_option_name(row.get("source_text"))
                ):
                    raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_INVALID", "A compiler-backed option lacks an exact active source excerpt.", status_code=409, details={"slot_id": slot_id, "choice_id": choice_id})
            elif row.get("reason_code") != NOT_COMPILER_BACKED_CODE:
                raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_INVALID", "A non-backed option lacks the stable nonselectable diagnostic.", status_code=409, details={"slot_id": slot_id, "choice_id": choice_id})
    return deepcopy(payload)
