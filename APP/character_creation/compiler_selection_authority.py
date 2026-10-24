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
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata
from typing import Any, Iterable
import zipfile

from . import method_corpus_release, foundation_corpus_release

from app.core import (
    CORE_PACK_ID,
    CORE_PACK_VERSION,
    EXPECTED_FACTORY_HASH,
    FACTORY_VERSION,
    FoundryError,
    sha256_file,
    sha256_json,
)


COMPILER_SELECTION_AUTHORITY_SCHEMA = "TianxiaFoundry.CompilerSelectionAuthority.v1"
RELEASED_COMPILER_SELECTION_AUTHORITY_SCHEMA = "TianxiaFoundry.CompilerSelectionAuthority.v2"
FOUNDATION_COMPILER_SELECTION_AUTHORITY_SCHEMA = "TianxiaFoundry.CompilerSelectionAuthority.v3"
PINNED_COMPILER_SHA256 = "cc2fd0f6676ec2b5ba7486f6aeb480007d52c169614ba99c446780571d5bd689"
PINNED_CORPUS_SHA256 = "12ffcacf2dbf955c24c56eb711634c7c1ebe4f639e1c51681f5aaef1b1388c19"
PINNED_FACTORY_ROOT_TREE_SHA256 = "7b4f90512d9cecb312477e5b5bc1af039cbe78fa1468dd955c3be8fa88b23cc1"
PINNED_CORPUS_MANIFEST_SHA256 = "236a5bf8fb1a1017f2113680e5080d45decbd5481e20721964c9b124fad0266a"
PINNED_ACTIVE_SOURCE_INDEX_SHA256 = "25315fdffb85d54f4b8fa514dc82d366d931b36e8caeb4de5e752b536a8b2bfd"
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
PINNED_METHOD_RECORD_PROJECTION_SHA256 = "7be0aa9d095f403365d716b54286faa83ceb1b0bc7503bfe16f7071d9c86cec3"
PINNED_FOUNDATION_RECORD_PROJECTION_SHA256 = "054d293976837e6293f2b5914578aa8807efcfd3e57c02e7943fb6f89cb5130b"
PINNED_BACKED_METHOD_IDS_SHA256 = "841e4a0c4aa970744c76a1f9c80617e9c62bd40a098f0a026ea1ccbac87f29d3"
PINNED_BACKED_FOUNDATION_IDS_SHA256 = "c99b86fbb126b12b0733ab2d89ceca557cde08456773cdc0edfa24d53e514a45"
PINNED_COMPILER_RELATIVE_PATH = "05_COMPILER/compile_character.py"
PINNED_CORPUS_RELATIVE_PATH = "09_RULES/Tianxia_Canonical_Rules_Corpus_P2A.zip"
CORPUS_MANIFEST_MEMBER = "_CANON_AUTHORITY_MANIFEST.json"
METHOD_SOURCE_MEMBER = "Needed/Tianxia_Methods_Master_v0_1.md"
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


def normalize_canonical_option_name(value: str) -> str:
    """Normalize a visible canonical name for exact source matching."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


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


def _safe_member(zf: zipfile.ZipFile, member: str, *, source_path: str) -> bytes:
    path = PurePosixPath(member)
    if path.is_absolute() or ".." in path.parts or not member or member not in zf.namelist():
        raise _error(
            "CG1_COMPILER_AUTHORITY_SOURCE_INVALID",
            "The corpus authority manifest names an unsafe or missing source member.",
            details={"source_path": source_path, "member": member},
        )
    info = zf.getinfo(member)
    if info.is_dir():
        raise _error(
            "CG1_COMPILER_AUTHORITY_SOURCE_INVALID",
            "The corpus authority manifest names a directory, not a source file.",
            details={"source_path": source_path, "member": member},
        )
    return zf.read(member)


def _read_source(zf: zipfile.ZipFile, source_path: str) -> tuple[bytes, str]:
    pieces = source_path.split("::")
    outer = pieces[0]
    data = _safe_member(zf, outer, source_path=source_path)
    for nested in pieces[1:]:
        with zipfile.ZipFile(BytesIO(data)) as nested_zip:
            data = _safe_member(nested_zip, nested, source_path=source_path)
    return data, outer


def _line_name(line: str) -> str:
    value = line.strip()
    value = re.sub(r"^#+\s*", "", value)
    value = re.sub(r"^\d+[.)]?\s*", "", value)
    value = re.sub(r"^\*\*Name:\*\*\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\*\*Foundation:\*\*\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\*+\s*|\s*\*+$", "", value)
    value = value.rstrip(":")
    return normalize_canonical_option_name(value)


def _method_excerpt(zf: zipfile.ZipFile, canonical_name: str, active: set[str]) -> dict[str, Any] | None:
    target = normalize_canonical_option_name(canonical_name)
    # Keep exact legacy packet excerpts stable for existing Methods and builds.
    legacy_has_name = False
    if METHOD_SOURCE_MEMBER in active:
        legacy_raw, _outer = _read_source(zf, METHOD_SOURCE_MEMBER)
        legacy_has_name = any(line.lstrip().startswith("#") and _line_name(line) == target for line in legacy_raw.decode("utf-8").splitlines())
    if method_corpus_release.SOURCE_MEMBER in active and not legacy_has_name:
        raw, _outer = _read_source(zf, method_corpus_release.SOURCE_MEMBER)
        if sha256(raw).hexdigest() != method_corpus_release.SOURCE_SHA256:
            raise _error("CG1_COMPILER_AUTHORITY_SOURCE_INVALID", "The released complete Method source has changed.")
        candidates = []
        for line in raw.decode("utf-8").splitlines(keepends=True):
            match = re.fullmatch(r"## METHOD-\d{3} — (.+)\n?", line)
            if match and normalize_canonical_option_name(match.group(1)) == target:
                candidates.append(line)
        if len(candidates) != 1:
            return None
        excerpt = candidates[0]
        return {"source_path": method_corpus_release.SOURCE_MEMBER,
                "source_file_sha256": sha256(raw).hexdigest(), "source_text": excerpt,
                "source_excerpt_sha256": sha256(excerpt.encode("utf-8")).hexdigest()}
    if METHOD_SOURCE_MEMBER not in active:
        raise _error(
            "CG1_COMPILER_AUTHORITY_MANIFEST_INVALID",
            "The active corpus manifest does not activate the typed Method source.",
            details={"source_path": METHOD_SOURCE_MEMBER},
        )
    raw, _outer = _read_source(zf, METHOD_SOURCE_MEMBER)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _error(
            "CG1_COMPILER_AUTHORITY_SOURCE_INVALID",
            "The active typed Method source is not UTF-8.",
            details={"source_path": METHOD_SOURCE_MEMBER},
        ) from exc
    target = normalize_canonical_option_name(canonical_name)
    lines = text.splitlines(keepends=True)
    candidates = [line for line in lines if _line_name(line) == target and line.lstrip().startswith("#")]
    if not candidates:
        return None
    excerpt = candidates[0]
    return {
        "source_path": METHOD_SOURCE_MEMBER,
        "source_file_sha256": sha256(raw).hexdigest(),
        "source_text": excerpt,
        "source_excerpt_sha256": sha256(excerpt.encode("utf-8")).hexdigest(),
    }


def _foundation_excerpt(zf: zipfile.ZipFile, canonical_name: str, active: set[str]) -> dict[str, Any] | None:
    target = normalize_canonical_option_name(canonical_name)
    released_sources = sorted(path for path in active if path.startswith(foundation_corpus_release.MEMBER_PREFIX))
    if released_sources:
        matches = []
        for source_path in released_sources:
            raw, _outer = _read_source(zf, source_path)
            heading = raw.decode("utf-8").splitlines(keepends=True)[0]
            match = re.fullmatch(r"# \d+\. (.+)\n?", heading)
            if match and normalize_canonical_option_name(match.group(1)) == target:
                matches.append({"source_path": source_path,
                                "source_file_sha256": sha256(raw).hexdigest(),
                                "source_text": heading,
                                "source_excerpt_sha256": sha256(heading.encode()).hexdigest()})
        return matches[0] if len(matches) == 1 else None
    candidates: list[tuple[tuple[int, int, str], str, bytes, str]] = []
    for source_path in sorted(active):
        basename = source_path.split("::")[-1]
        if "SOURCE_EXCERPT_" not in basename and "Runtime_Rewrite" not in basename:
            continue
        try:
            raw, _outer = _read_source(zf, source_path)
            text = raw.decode("utf-8")
        except (UnicodeDecodeError, FoundryError, zipfile.BadZipFile):
            continue
        lines = text.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if _line_name(line) != target:
                continue
            if not (line.lstrip().startswith("#") or "**Name:**" in line or "**Foundation:**" in line):
                continue
            # Prefer a filename carrying the canonical name, then a source
            # excerpt over a runtime rewrite, then the earliest line.
            slug = normalize_canonical_option_name(canonical_name).replace(" ", "_")
            name_in_file = slug.casefold() in normalize_canonical_option_name(basename).replace(" ", "_").casefold()
            source_excerpt = "SOURCE_EXCERPT_" in basename
            rank = (0 if name_in_file else 1, 0 if source_excerpt else 1, index)
            candidates.append((rank, source_path, raw, line))
    if not candidates:
        return None
    _rank, source_path, raw, excerpt = sorted(candidates, key=lambda row: (row[0], row[1]))[0]
    return {
        "source_path": source_path,
        "source_file_sha256": sha256(raw).hexdigest(),
        "source_text": excerpt,
        "source_excerpt_sha256": sha256(excerpt.encode("utf-8")).hexdigest(),
    }


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


def _records_by_id(records: Iterable[dict[str, Any]], *, id_key: str, name_key: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        choice_id = row.get(id_key)
        name = row.get(name_key)
        if not isinstance(choice_id, str) or not choice_id or not isinstance(name, str) or not name.strip():
            raise _error(
                "CG1_COMPILER_AUTHORITY_OPTION_INVALID",
                "A Method/Foundation authority row lacks a stable ID or canonical name.",
                details={"id_key": id_key, "name_key": name_key, "row": row},
            )
        result.append((choice_id, name.strip()))
    return sorted(result)


def _evidence(
    *,
    choice_id: str,
    canonical_name: str,
    source: dict[str, Any] | None,
    corpus: dict[str, Any],
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "choice_id": choice_id,
        "canonical_name": canonical_name,
        "normalized_canonical_name": normalize_canonical_option_name(canonical_name),
        "classification": "tianxia_rules" if source else "unbacked",
        "selectable": bool(source),
        "reason_code": None if source else NOT_COMPILER_BACKED_CODE,
        "reason": None if source else "No exact active compiler-corpus excerpt proves this canonical option.",
        "corpus_sha256": corpus["corpus_sha256"],
        "factory_root_tree_sha256": corpus["factory_root_tree_sha256"],
    }
    if source:
        item.update(source)
    else:
        item.update({"source_path": None, "source_file_sha256": None, "source_text": None, "source_excerpt_sha256": None})
    return item


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
    release = foundation_corpus_release if include_complete_foundations else method_corpus_release
    corpus_path = release.ensure_release(Path(vendor_dir), root / PINNED_CORPUS_RELATIVE_PATH)
    effective_compiler = {**compiler, "corpus_sha256": release.CORPUS_SHA256}
    try:
        with zipfile.ZipFile(corpus_path) as zf:
            manifest_raw = _safe_member(zf, CORPUS_MANIFEST_MEMBER, source_path=CORPUS_MANIFEST_MEMBER)
            manifest = json.loads(manifest_raw.decode("utf-8"))
            active_rows = manifest.get("active_packet_sources") if isinstance(manifest, dict) else None
            if not isinstance(active_rows, list) or not all(isinstance(row, str) for row in active_rows):
                raise _error("CG1_COMPILER_AUTHORITY_MANIFEST_INVALID", "The active corpus authority manifest is malformed.")
            active = set(active_rows)
            active_source_index: list[dict[str, str]] = []
            for source_path in sorted(active):
                source_raw, _outer = _read_source(zf, source_path)
                active_source_index.append(
                    {
                        "source_path": source_path,
                        "source_file_sha256": sha256(source_raw).hexdigest(),
                    }
                )
            methods: dict[str, dict[str, Any]] = {}
            for choice_id, name in _records_by_id(method_records, id_key="method_id", name_key="name"):
                methods[choice_id] = _evidence(choice_id=choice_id, canonical_name=name, source=_method_excerpt(zf, name, active), corpus=effective_compiler)
            foundations: dict[str, dict[str, Any]] = {}
            for choice_id, name in _records_by_id(foundation_records, id_key="foundation_id", name_key="display_name"):
                foundations[choice_id] = _evidence(choice_id=choice_id, canonical_name=name, source=_foundation_excerpt(zf, name, active), corpus=effective_compiler)
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if isinstance(exc, FoundryError):
            raise
        raise _error(
            "CG1_COMPILER_AUTHORITY_CORPUS_UNREADABLE",
            "The pinned compiler rules corpus cannot be read.",
            details={"path": str(corpus_path)},
        ) from exc
    payload: dict[str, Any] = {
        "schema": FOUNDATION_COMPILER_SELECTION_AUTHORITY_SCHEMA if include_complete_foundations else RELEASED_COMPILER_SELECTION_AUTHORITY_SCHEMA,
        "factory": compiler,
        "method_corpus_release": method_corpus_release.binding(),
        **({"foundation_corpus_release": foundation_corpus_release.binding()} if include_complete_foundations else {}),
        "source_authority": {
            "manifest_sha256": sha256(manifest_raw).hexdigest(),
            "active_source_index": active_source_index,
            "active_source_index_sha256": sha256_json(active_source_index),
        },
        "content": content,
        "method_choice": {
            "records": methods,
            "compiler_backed_ids": sorted(choice_id for choice_id, row in methods.items() if row.get("selectable") is True),
        },
        "foundation_choice": {
            "records": foundations,
            "compiler_backed_ids": sorted(choice_id for choice_id, row in foundations.items() if row.get("selectable") is True),
        },
        "projection": {
            "method_records_sha256": sha256_json(methods),
            "foundation_records_sha256": sha256_json(foundations),
            "compiler_backed_method_ids_sha256": sha256_json(sorted(choice_id for choice_id, row in methods.items() if row.get("selectable") is True)),
            "compiler_backed_foundation_ids_sha256": sha256_json(sorted(choice_id for choice_id, row in foundations.items() if row.get("selectable") is True)),
        },
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
    foundations_released = payload["schema"] == FOUNDATION_COMPILER_SELECTION_AUTHORITY_SCHEMA
    released = payload["schema"] in {RELEASED_COMPILER_SELECTION_AUTHORITY_SCHEMA, FOUNDATION_COMPILER_SELECTION_AUTHORITY_SCHEMA}
    if (foundations_released and payload.get("foundation_corpus_release") != foundation_corpus_release.binding()) or (not foundations_released and "foundation_corpus_release" in payload):
        raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_PIN_MISMATCH", "The Foundation release identity does not match the exact snapshot version.", status_code=409)
    if (released and payload.get("method_corpus_release") != method_corpus_release.binding()) or (not released and "method_corpus_release" in payload):
        raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_PIN_MISMATCH", "The Method corpus release identity does not match the exact snapshot version.", status_code=409)
    release = foundation_corpus_release if foundations_released else method_corpus_release
    corpus_hash = release.CORPUS_SHA256 if released else PINNED_CORPUS_SHA256
    manifest_hash = release.MANIFEST_SHA256 if released else PINNED_CORPUS_MANIFEST_SHA256
    source_index_hash = release.ACTIVE_SOURCE_INDEX_SHA256 if released else PINNED_ACTIVE_SOURCE_INDEX_SHA256
    actual = sha256_json({key: value for key, value in payload.items() if key != "authority_sha256"})
    if actual != payload.get("authority_sha256"):
        raise _error("CG1_DELEGATED_COMPILER_AUTHORITY_TAMPERED", "The delegated compiler-selection authority hash does not match its evidence.", status_code=409, details={"expected": payload.get("authority_sha256"), "actual": actual})
    factory = payload.get("factory") or {}
    expected_factory = {
        "factory_archive_sha256": EXPECTED_FACTORY_HASH,
        "factory_root_tree_sha256": PINNED_FACTORY_ROOT_TREE_SHA256,
        "compiler_relative_path": PINNED_COMPILER_RELATIVE_PATH,
        "compiler_sha256": PINNED_COMPILER_SHA256,
        "corpus_relative_path": PINNED_CORPUS_RELATIVE_PATH,
        "corpus_sha256": PINNED_CORPUS_SHA256,
        "factory_version": FACTORY_VERSION,
    }
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
    expected_projection = {
        "method_records_sha256": release.METHOD_PROJECTION_SHA256 if released else PINNED_METHOD_RECORD_PROJECTION_SHA256,
        "foundation_records_sha256": release.FOUNDATION_PROJECTION_SHA256 if released else PINNED_FOUNDATION_RECORD_PROJECTION_SHA256,
        "compiler_backed_method_ids_sha256": method_corpus_release.BACKED_METHOD_IDS_SHA256 if released else PINNED_BACKED_METHOD_IDS_SHA256,
        "compiler_backed_foundation_ids_sha256": foundation_corpus_release.BACKED_FOUNDATION_IDS_SHA256 if foundations_released else PINNED_BACKED_FOUNDATION_IDS_SHA256,
    }
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
