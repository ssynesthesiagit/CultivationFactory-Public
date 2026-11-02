"""Quote published source blocks from the installed pack, bound by hash.

A locked talent record carries only a source anchor (``line:N:column:M``)
into a pack source file and that file's SHA-256.  The constructors quote the
printed block at that anchor so a technique's effect text is the published
text, never a paraphrase.  The file must hash to the record's source hash or
nothing is quoted.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError

_ANCHOR_RE = re.compile(r"^line:(\d+)(?::column:(\d+))?$")
_HEADING_RE = re.compile(r"^(#{1,6})\s")
_MAX_BLOCK_LINES = 80
_MAX_BLOCK_CHARS = 4000


def installed_factory_root(vendor_dir: Path) -> Path | None:
    """Return the extracted pack root the adapter configured, if any."""
    config = Path(vendor_dir) / "factory_adapter.json"
    if not config.is_file():
        return None
    try:
        root = json.loads(config.read_text(encoding="utf-8")).get("factory_root")
    except (OSError, ValueError):
        return None
    return Path(root) if isinstance(root, str) and root else None


@functools.lru_cache(maxsize=32)
def _verified_source_lines(path: str, expected_hash: str, size: int, mtime_ns: int) -> tuple[str, ...] | None:
    """Read and hash-verify one source file once per (path, hash, size, mtime).

    A compile reads the same multi-megabyte compendium for every constructed
    art it materializes; the verified lines are immutable for the life of
    the extracted pack, so identical bytes are not re-read and re-hashed.
    """

    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        return None
    return tuple(data.decode("utf-8", errors="replace").splitlines())


def _source_lines(factory_root: Path, source_path: str, expected_hash: str) -> list[str] | None:
    root = Path(factory_root).resolve()
    path = (root / source_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    lines = _verified_source_lines(str(path), expected_hash, stat.st_size, stat.st_mtime_ns)
    return None if lines is None else list(lines)


def published_block(factory_root: Path | None, source: Mapping[str, Any]) -> str:
    """Return the printed block at a record's source anchor, or an empty string.

    The block runs from the anchored line to the next heading of the same or
    a higher level, bounded in size.  An unverifiable source yields nothing
    rather than a guess.
    """
    if factory_root is None or not isinstance(source, Mapping):
        return ""
    path = source.get("path")
    anchor = source.get("anchor")
    expected_hash = source.get("source_hash")
    if not isinstance(path, str) or not isinstance(anchor, str) or not isinstance(expected_hash, str):
        return ""
    match = _ANCHOR_RE.match(anchor)
    if not match:
        return ""
    lines = _source_lines(factory_root, path, expected_hash)
    if lines is None:
        return ""
    start = int(match.group(1)) - 1
    if start < 0 or start >= len(lines):
        return ""
    heading = _HEADING_RE.match(lines[start])
    level = len(heading.group(1)) if heading else 6
    block = [lines[start]]
    for index in range(start + 1, min(start + _MAX_BLOCK_LINES, len(lines))):
        next_heading = _HEADING_RE.match(lines[index])
        if next_heading and len(next_heading.group(1)) <= level:
            break
        block.append(lines[index])
    text = "\n".join(block).strip()
    return text[:_MAX_BLOCK_CHARS]


def published_section(factory_root: Path | None, source: Mapping[str, Any]) -> str:
    """Return an exact source section after file and section hash checks.

    Non-Sphere Path projections carry explicit line bounds in their proof.
    The ordinary ``published_block`` helper intentionally caps a generic
    anchor; this reader uses those bounds and the section commitment so a
    constructed art cannot silently consume a truncated or adjacent feature.
    """
    if not isinstance(source, Mapping):
        return ""
    if source.get("source_kind") == "owner_subpath_json_text":
        # Optional first-party progressions live outside the sealed Factory.
        # Their decoded JSON text has its own exact locator and commitments.
        from non_sphere_authority.owner_subpaths import published_owner_section
        return published_owner_section(Path(__file__).resolve().parents[2], source)
    if factory_root is None:
        return ""
    path_value = source.get("factory_source_path") or source.get("path")
    file_hash = source.get("source_file_sha256") or source.get("source_hash")
    start = source.get("line_start")
    end = source.get("line_end")
    section_hash = source.get("section_sha256")
    if (
        not isinstance(path_value, str)
        or not isinstance(file_hash, str)
        or type(start) is not int
        or type(end) is not int
        or start < 1
        or end < start
        or not isinstance(section_hash, str)
    ):
        return ""
    path = (Path(factory_root) / path_value).resolve()
    try:
        path.relative_to(Path(factory_root).resolve())
    except ValueError:
        return ""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if hashlib.sha256(data).hexdigest() != file_hash:
        return ""
    lines = data.decode("utf-8", errors="replace").splitlines()
    if end > len(lines):
        return ""
    # Some locators end one blank line past the hashed section (the last
    # feature before a Part heading).  Blank lines carry no rules text, so
    # drop trailing blanks one at a time; only an exact hash match counts.
    while end >= start:
        section = "\n".join(lines[start - 1 : end])
        if hashlib.sha256(section.encode("utf-8")).hexdigest() == section_hash:
            return section
        if lines[end - 1].strip():
            break
        end -= 1
    return ""


__all__ = ["installed_factory_root", "published_block", "published_section"]
