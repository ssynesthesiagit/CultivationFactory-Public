"""Method/Foundation source projection shared by the release builder and selection authority.

This preserves the historical excerpt preference and evidence bytes. Authentication
belongs to release_descriptor, not to these pure projection helpers.
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import re
import unicodedata
import zipfile
from pathlib import PurePosixPath
from typing import Any, Iterable
from app.core import FoundryError
NOT_COMPILER_BACKED_CODE = "CG1_DELEGATED_CHOICE_NOT_COMPILER_BACKED"
def _error(code, message, *, details=None, status_code=503):
    return FoundryError(code, message, details=details, status_code=status_code)

def normalize_canonical_option_name(value: str) -> str:
    """Normalize a visible canonical name for exact source matching."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))



def _safe_member(zf: zipfile.ZipFile, member: str, *, source_path: str) -> bytes:
    path = PurePosixPath(member)
    if path.is_absolute() or ".." in path.parts or not member or member not in zf.namelist():
        raise _error(
            "CG1_COMPILER_AUTHORITY_SOURCE_INVALID",
            "The corpus authority manifest names an unsafe or missing source member.",
            details={"source_path": source_path, "member": member},
        )
    info = zf.getinfo(member)
    if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
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


def _method_excerpt(zf: zipfile.ZipFile, canonical_name: str, active: set[str], *, method_member: str, source_member: str, source_sha256: str) -> dict[str, Any] | None:
    target = normalize_canonical_option_name(canonical_name)
    # Keep exact legacy packet excerpts stable for existing Methods and builds.
    legacy_has_name = False
    if method_member in active:
        legacy_raw, _outer = _read_source(zf, method_member)
        legacy_has_name = any(line.lstrip().startswith("#") and _line_name(line) == target for line in legacy_raw.decode("utf-8").splitlines())
    if source_member in active and not legacy_has_name:
        raw, _outer = _read_source(zf, source_member)
        if sha256(raw).hexdigest() != source_sha256:
            raise _error("CG1_COMPILER_AUTHORITY_SOURCE_INVALID", "The released complete Method source has changed.")
        candidates = []
        for line in raw.decode("utf-8").splitlines(keepends=True):
            match = re.fullmatch(r"## METHOD-\d{3} — (.+)\n?", line)
            if match and normalize_canonical_option_name(match.group(1)) == target:
                candidates.append(line)
        if len(candidates) != 1:
            return None
        excerpt = candidates[0]
        return {"source_path": source_member,
                "source_file_sha256": sha256(raw).hexdigest(), "source_text": excerpt,
                "source_excerpt_sha256": sha256(excerpt.encode("utf-8")).hexdigest()}
    if method_member not in active:
        raise _error(
            "CG1_COMPILER_AUTHORITY_MANIFEST_INVALID",
            "The active corpus manifest does not activate the typed Method source.",
            details={"source_path": method_member},
        )
    raw, _outer = _read_source(zf, method_member)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _error(
            "CG1_COMPILER_AUTHORITY_SOURCE_INVALID",
            "The active typed Method source is not UTF-8.",
            details={"source_path": method_member},
        ) from exc
    target = normalize_canonical_option_name(canonical_name)
    lines = text.splitlines(keepends=True)
    candidates = [line for line in lines if _line_name(line) == target and line.lstrip().startswith("#")]
    if not candidates:
        return None
    excerpt = candidates[0]
    return {
        "source_path": method_member,
        "source_file_sha256": sha256(raw).hexdigest(),
        "source_text": excerpt,
        "source_excerpt_sha256": sha256(excerpt.encode("utf-8")).hexdigest(),
    }


def _foundation_excerpt(zf: zipfile.ZipFile, canonical_name: str, active: set[str], *, member_prefix: str) -> dict[str, Any] | None:
    target = normalize_canonical_option_name(canonical_name)
    released_sources = sorted(path for path in active if path.startswith(member_prefix))
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
