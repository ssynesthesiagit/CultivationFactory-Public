from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import unicodedata
import zipfile
from typing import Callable, Iterable

from .canonical import canonical_json_bytes, sha256_bytes, sha256_file
from .models import Diagnostic, FileInventoryEntry, Severity, ValidationOptions

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:")


def _normalized_zip_name(name: str) -> str:
    return name.replace("\\", "/")


def _is_unsafe_logical_path(name: str) -> bool:
    normalized = _normalized_zip_name(name)
    if not normalized or normalized.startswith("/") or _WINDOWS_ABSOLUTE.match(normalized):
        return True
    parts = PurePosixPath(normalized).parts
    return any(part in ("", ".", "..") for part in parts)


def _single_pack_root(paths: Iterable[str]) -> str:
    paths = [path for path in paths if path]
    if "pack.json" in paths:
        return ""
    candidates = {path.split("/", 1)[0] for path in paths if "/" in path}
    if len(candidates) != 1:
        return ""
    root = next(iter(candidates))
    if f"{root}/pack.json" in paths:
        return root + "/"
    return ""


def _identity_for_directory(path: Path) -> str:
    rows: list[dict[str, object]] = []
    if not path.exists():
        return sha256_bytes(canonical_json_bytes([{"missing": str(path)}]))
    for current, dirs, files in os.walk(path, followlinks=False):
        dirs.sort()
        files.sort()
        current_path = Path(current)
        for name in dirs + files:
            entry = current_path / name
            relative = entry.relative_to(path).as_posix()
            try:
                info = entry.lstat()
            except OSError as exc:
                rows.append({"path": relative, "error": type(exc).__name__})
                continue
            mode = stat.S_IFMT(info.st_mode)
            row: dict[str, object] = {
                "path": relative,
                "mode": mode,
                "size": info.st_size,
            }
            if stat.S_ISREG(info.st_mode):
                row["sha256"] = sha256_file(entry)
            elif stat.S_ISLNK(info.st_mode):
                row["link_target"] = os.readlink(entry)
            rows.append(row)
    return sha256_bytes(canonical_json_bytes(rows))


def input_identity(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    return _identity_for_directory(path)


@dataclass
class PackSource:
    input_path: Path
    input_kind: str
    pack_root: str
    logical_paths: tuple[str, ...]
    inventory: tuple[FileInventoryEntry, ...]
    diagnostics: list[Diagnostic]
    _readers: dict[str, Callable[[], bytes]]
    _closer: Callable[[], None] | None = None

    def read_bytes(self, logical_path: str) -> bytes:
        try:
            reader = self._readers[logical_path]
        except KeyError as exc:
            raise FileNotFoundError(logical_path) from exc
        return reader()

    def exists(self, logical_path: str) -> bool:
        return logical_path in self._readers

    def close(self) -> None:
        if self._closer is not None:
            self._closer()
            self._closer = None

    def __enter__(self) -> "PackSource":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _collision_diagnostics(paths: list[str], subsystem: str = "archive") -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    exact: dict[str, int] = {}
    casefolded: dict[str, list[str]] = {}
    normalized: dict[str, list[str]] = {}
    for path in paths:
        exact[path] = exact.get(path, 0) + 1
        casefolded.setdefault(path.casefold(), []).append(path)
        normalized.setdefault(unicodedata.normalize("NFC", path), []).append(path)
    for path, count in sorted(exact.items()):
        if count > 1:
            diagnostics.append(
                Diagnostic(
                    code="ARCHIVE_DUPLICATE_PATH",
                    severity=Severity.ERROR,
                    subsystem=subsystem,
                    message="The input contains the same path more than once.",
                    path=path,
                    details={"occurrences": count},
                    recommended_action="Remove duplicate entries and rebuild the pack.",
                )
            )
    for key, values in sorted(casefolded.items()):
        unique = sorted(set(values))
        if len(unique) > 1:
            diagnostics.append(
                Diagnostic(
                    code="ARCHIVE_CASEFOLD_COLLISION",
                    severity=Severity.ERROR,
                    subsystem=subsystem,
                    message="Paths collide on case-insensitive filesystems.",
                    details={"paths": unique},
                    recommended_action="Rename the colliding paths to globally distinct spellings.",
                )
            )
    for key, values in sorted(normalized.items()):
        unique = sorted(set(values))
        if len(unique) > 1:
            diagnostics.append(
                Diagnostic(
                    code="ARCHIVE_UNICODE_NORMALIZATION_COLLISION",
                    severity=Severity.ERROR,
                    subsystem=subsystem,
                    message="Paths collide after NFC Unicode normalization.",
                    details={"paths": unique},
                    recommended_action="Rename paths to one normalized spelling.",
                )
            )
    return diagnostics


def open_pack_source(path: Path, options: ValidationOptions) -> PackSource:
    if not path.exists():
        return PackSource(
            input_path=path,
            input_kind="missing",
            pack_root="",
            logical_paths=(),
            inventory=(),
            diagnostics=[
                Diagnostic(
                    code="INPUT_NOT_FOUND",
                    severity=Severity.ERROR,
                    subsystem="input",
                    message="The requested content pack does not exist.",
                    path=path.name,
                    retry_safe=True,
                    recommended_action="Provide an existing directory or ZIP file.",
                )
            ],
            _readers={},
        )
    if path.is_dir():
        return _open_directory(path, options)
    if path.is_file() and path.suffix.casefold() == ".zip":
        return _open_zip(path, options)
    return PackSource(
        input_path=path,
        input_kind="unsupported",
        pack_root="",
        logical_paths=(),
        inventory=(),
        diagnostics=[
            Diagnostic(
                code="INPUT_TYPE_UNSUPPORTED",
                severity=Severity.ERROR,
                subsystem="input",
                message="Only content-pack directories and ZIP files are supported.",
                path=path.name,
                recommended_action="Provide a directory or .zip file.",
            )
        ],
        _readers={},
    )


def _open_directory(path: Path, options: ValidationOptions) -> PackSource:
    diagnostics: list[Diagnostic] = []
    raw_files: list[tuple[str, Path]] = []
    path_rows: list[str] = []
    total_size = 0
    for current, dirs, files in os.walk(path, followlinks=False):
        dirs.sort()
        files.sort()
        current_path = Path(current)
        retained_dirs: list[str] = []
        for name in dirs:
            entry = current_path / name
            relative = entry.relative_to(path).as_posix()
            info = entry.lstat()
            if stat.S_ISLNK(info.st_mode):
                diagnostics.append(
                    Diagnostic(
                        code="DIRECTORY_SYMBOLIC_LINK",
                        severity=Severity.ERROR,
                        subsystem="archive",
                        message="Symbolic links are not allowed in declarative content packs.",
                        path=relative,
                        recommended_action="Replace the link with a checksum-covered regular file or directory.",
                    )
                )
            elif stat.S_ISDIR(info.st_mode):
                path_rows.append(relative.rstrip("/"))
                retained_dirs.append(name)
            else:
                diagnostics.append(
                    Diagnostic(
                        code="DIRECTORY_SPECIAL_ENTRY",
                        severity=Severity.ERROR,
                        subsystem="archive",
                        message="Special filesystem entries are not allowed in content packs.",
                        path=relative,
                    )
                )
        dirs[:] = retained_dirs
        for name in files:
            entry = current_path / name
            relative = entry.relative_to(path).as_posix()
            path_rows.append(relative)
            info = entry.lstat()
            if stat.S_ISLNK(info.st_mode):
                diagnostics.append(
                    Diagnostic(
                        code="DIRECTORY_SYMBOLIC_LINK",
                        severity=Severity.ERROR,
                        subsystem="archive",
                        message="Symbolic links are not allowed in declarative content packs.",
                        path=relative,
                    )
                )
                continue
            if not stat.S_ISREG(info.st_mode):
                diagnostics.append(
                    Diagnostic(
                        code="DIRECTORY_SPECIAL_ENTRY",
                        severity=Severity.ERROR,
                        subsystem="archive",
                        message="Special filesystem entries are not allowed in content packs.",
                        path=relative,
                    )
                )
                continue
            if info.st_size > options.maximum_single_file_bytes:
                diagnostics.append(
                    Diagnostic(
                        code="INPUT_FILE_TOO_LARGE",
                        severity=Severity.ERROR,
                        subsystem="archive",
                        message="A pack file exceeds the configured single-file limit.",
                        path=relative,
                        details={"limit_bytes": options.maximum_single_file_bytes, "size_bytes": info.st_size},
                    )
                )
            total_size += info.st_size
            raw_files.append((relative, entry))
    diagnostics.extend(_collision_diagnostics(path_rows))
    if len(raw_files) > options.maximum_file_count:
        diagnostics.append(
            Diagnostic(
                code="INPUT_FILE_COUNT_LIMIT_EXCEEDED",
                severity=Severity.ERROR,
                subsystem="archive",
                message="The pack exceeds the configured file-count limit.",
                details={"file_count": len(raw_files), "limit": options.maximum_file_count},
            )
        )
    if total_size > options.maximum_uncompressed_bytes:
        resource_blocked = True
        diagnostics.append(
            Diagnostic(
                code="INPUT_TOTAL_SIZE_LIMIT_EXCEEDED",
                severity=Severity.ERROR,
                subsystem="archive",
                message="The pack exceeds the configured total-size limit.",
                details={"size_bytes": total_size, "limit_bytes": options.maximum_uncompressed_bytes},
            )
        )
    root = _single_pack_root([relative for relative, _ in raw_files])
    readers: dict[str, Callable[[], bytes]] = {}
    inventory: list[FileInventoryEntry] = []
    for relative, entry in raw_files:
        logical = relative[len(root) :] if root and relative.startswith(root) else relative
        if logical in readers:
            continue
        readers[logical] = lambda entry=entry: entry.read_bytes()
        inventory.append(
            FileInventoryEntry(
                logical_path=logical,
                size_bytes=entry.stat().st_size,
                sha256=sha256_file(entry),
                source_path=relative,
            )
        )
    inventory.sort(key=lambda row: row.logical_path)
    return PackSource(
        input_path=path,
        input_kind="directory",
        pack_root=root.rstrip("/"),
        logical_paths=tuple(row.logical_path for row in inventory),
        inventory=tuple(inventory),
        diagnostics=diagnostics,
        _readers=readers,
    )


def _open_zip(path: Path, options: ValidationOptions) -> PackSource:
    diagnostics: list[Diagnostic] = []
    try:
        archive = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        return PackSource(
            input_path=path,
            input_kind="zip",
            pack_root="",
            logical_paths=(),
            inventory=(),
            diagnostics=[
                Diagnostic(
                    code="ZIP_OPEN_FAILED",
                    severity=Severity.ERROR,
                    subsystem="archive",
                    message="The ZIP could not be opened.",
                    path=path.name,
                    details={"error_type": type(exc).__name__},
                    recommended_action="Rebuild the ZIP and verify its CRC before validation.",
                )
            ],
            _readers={},
        )
    infos = archive.infolist()
    normalized_names = [_normalized_zip_name(info.filename) for info in infos]
    collision_names = [name.rstrip("/") for name in normalized_names]
    diagnostics.extend(_collision_diagnostics(collision_names))
    total_size = 0
    resource_blocked = False
    safe_infos: list[tuple[str, zipfile.ZipInfo]] = []
    for info, raw_name in zip(infos, normalized_names):
        safety_name = raw_name.rstrip("/") if info.is_dir() else raw_name
        mode = (info.external_attr >> 16) & 0xFFFF
        if _is_unsafe_logical_path(safety_name):
            diagnostics.append(
                Diagnostic(
                    code="ZIP_UNSAFE_PATH",
                    severity=Severity.ERROR,
                    subsystem="archive",
                    message="The ZIP contains an absolute, traversal, or malformed path.",
                    path=raw_name,
                    recommended_action="Remove the unsafe member and rebuild the archive.",
                )
            )
            continue
        if info.is_dir():
            continue
        if stat.S_ISLNK(mode):
            diagnostics.append(
                Diagnostic(
                    code="ZIP_SYMBOLIC_LINK",
                    severity=Severity.ERROR,
                    subsystem="archive",
                    message="Symbolic links are not allowed in content-pack ZIPs.",
                    path=raw_name,
                )
            )
            continue
        file_kind = stat.S_IFMT(mode)
        if file_kind not in (0, stat.S_IFREG):
            diagnostics.append(
                Diagnostic(
                    code="ZIP_SPECIAL_FILE",
                    severity=Severity.ERROR,
                    subsystem="archive",
                    message="Special file entries are not allowed in content-pack ZIPs.",
                    path=raw_name,
                    details={"mode": oct(mode)},
                )
            )
            continue
        if info.flag_bits & 0x1:
            diagnostics.append(
                Diagnostic(
                    code="ZIP_ENCRYPTED_MEMBER",
                    severity=Severity.ERROR,
                    subsystem="archive",
                    message="Encrypted ZIP members are not supported.",
                    path=raw_name,
                )
            )
            continue
        if info.file_size > options.maximum_single_file_bytes:
            resource_blocked = True
            diagnostics.append(
                Diagnostic(
                    code="INPUT_FILE_TOO_LARGE",
                    severity=Severity.ERROR,
                    subsystem="archive",
                    message="A pack file exceeds the configured single-file limit.",
                    path=raw_name,
                    details={"limit_bytes": options.maximum_single_file_bytes, "size_bytes": info.file_size},
                )
            )
        total_size += info.file_size
        safe_infos.append((raw_name, info))
    if len(safe_infos) > options.maximum_file_count:
        resource_blocked = True
        diagnostics.append(
            Diagnostic(
                code="INPUT_FILE_COUNT_LIMIT_EXCEEDED",
                severity=Severity.ERROR,
                subsystem="archive",
                message="The ZIP exceeds the configured file-count limit.",
                details={"file_count": len(safe_infos), "limit": options.maximum_file_count},
            )
        )
    if total_size > options.maximum_uncompressed_bytes:
        resource_blocked = True
        diagnostics.append(
            Diagnostic(
                code="INPUT_TOTAL_SIZE_LIMIT_EXCEEDED",
                severity=Severity.ERROR,
                subsystem="archive",
                message="The ZIP exceeds the configured uncompressed-size limit.",
                details={"size_bytes": total_size, "limit_bytes": options.maximum_uncompressed_bytes},
            )
        )
    bad_member = None
    if not resource_blocked:
        try:
            bad_member = archive.testzip()
        except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
            bad_member = "<zip-read-error>"
            diagnostics.append(
                Diagnostic(
                    code="ZIP_CRC_CHECK_FAILED",
                    severity=Severity.ERROR,
                    subsystem="archive",
                    message="ZIP CRC verification could not complete.",
                    details={"error_type": type(exc).__name__},
                )
            )
        if bad_member:
            diagnostics.append(
                Diagnostic(
                    code="ZIP_CRC_FAILURE",
                    severity=Severity.ERROR,
                    subsystem="archive",
                    message="A ZIP member failed CRC verification.",
                    path=str(bad_member),
                    recommended_action="Rebuild the ZIP from known-good source files.",
                )
            )
    else:
        diagnostics.append(
            Diagnostic(
                code="ZIP_RESOURCE_LIMIT_BLOCKED",
                severity=Severity.ERROR,
                subsystem="archive",
                message="ZIP decompression and CRC traversal were stopped by configured resource limits.",
                recommended_action="Reduce the pack size or raise reviewed local limits deliberately.",
            )
        )
    root = _single_pack_root([raw_name for raw_name, _ in safe_infos])
    readers: dict[str, Callable[[], bytes]] = {}
    inventory: list[FileInventoryEntry] = []
    for raw_name, info in ([] if resource_blocked else safe_infos):
        logical = raw_name[len(root) :] if root and raw_name.startswith(root) else raw_name
        if logical in readers:
            continue
        readers[logical] = lambda info=info: archive.read(info)
        try:
            data = archive.read(info)
        except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
            diagnostics.append(
                Diagnostic(
                    code="ZIP_MEMBER_READ_FAILED",
                    severity=Severity.ERROR,
                    subsystem="archive",
                    message="A ZIP member could not be read.",
                    path=raw_name,
                    details={"error_type": type(exc).__name__},
                )
            )
            continue
        inventory.append(
            FileInventoryEntry(
                logical_path=logical,
                size_bytes=len(data),
                sha256=sha256_bytes(data),
                source_path=raw_name,
            )
        )
    inventory.sort(key=lambda row: row.logical_path)
    return PackSource(
        input_path=path,
        input_kind="zip",
        pack_root=root.rstrip("/"),
        logical_paths=tuple(row.logical_path for row in inventory),
        inventory=tuple(inventory),
        diagnostics=diagnostics,
        _readers=readers,
        _closer=archive.close,
    )
