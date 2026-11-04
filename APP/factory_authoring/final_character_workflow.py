"""Provider-free registry and review preview for final-character inputs.

The three authoring controllers produce detached trees.  This module records
only successful server-owned trees, then revalidates the exact current triplet
before exposing the immutable binding that an owner may later approve.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import secrets
import shutil
import stat
import tempfile
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping

from app.core import Database, FoundryError, canonical_json, sha256_file, sha256_json
from factory_authoring.composite_controller import CompositeControllerAuthoring
import factory_authoring.command4_provider as command4_provider
from factory_authoring.constructed_immortal_arts import constructed_immortal_art_binding
import factory_authoring.final_character_materializer as final_materializer
from security.approval_challenges import ApprovalChallengeService
from security.integrity import IntegrityService
from security.local_identity import PrincipalProvider, ProcessPrincipalProvider


FINAL_CHARACTER_COMPONENT_RECEIPT_SCHEMA = "TianxiaFoundry.FinalCharacterComponentReceipt.v1"
FINAL_CHARACTER_COMPONENT_POINTER_SCHEMA = "TianxiaFoundry.FinalCharacterComponentPointer.v1"
FINAL_CHARACTER_REVIEW_PREVIEW_SCHEMA = "TianxiaFoundry.FinalCharacterReviewPreview.v1"
FINAL_CHARACTER_REVIEW_CHALLENGE_SCHEMA = "TianxiaFoundry.FinalCharacterReviewApprovalChallenge.v1"
FINAL_CHARACTER_REVIEW_SUMMARY_SCHEMA = "TianxiaFoundry.FinalCharacterReviewSummary.v1"
FINAL_CHARACTER_MATERIALIZATION_SUMMARY_SCHEMA = "TianxiaFoundry.FinalCharacterMaterializationSummary.v1"
FINAL_CHARACTER_WORKFLOW_ROOT_NAME = "factory_final_character"
FINAL_CHARACTER_REVIEW_STORE_NAME = "reviews"
FINAL_CHARACTER_MATERIALIZATION_ROOT_NAME = "materializations"

# The Immortal Art is not a separate component: the creative controller
# builds it into the sealed Action workspace, and the review binding carries
# its rules-checked summary.
_COMPONENTS = ("command4", "composite_controller")
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_ID = re.compile(r"^component\.(?:command4|composite_controller)\.[0-9a-f]{64}$")
_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "receipt_sha256",
        "component",
        "project_id",
        "overlay_relative_path",
        "overlay_id",
        "artifact_sha256",
        "overlay_tree_sha256",
        "files_tree_sha256",
        "candidate_sha256",
        "projection_id",
        "source_workspace_sha256",
        "request_sha256",
        "response_sha256",
    }
)
_POINTER_KEYS = frozenset({"schema_version", "project_id", "components", "pointer_sha256"})
_CAPTURE_FILE_LIMIT = 4096
_CAPTURE_BYTE_LIMIT = 512 * 1024 * 1024
_CAPTURE_MEMBER_LIMIT = 64 * 1024 * 1024


def _error(code: str, message: str, *, details: Any = None, status_code: int = 409) -> FoundryError:
    return FoundryError(code, message, details=details, status_code=status_code)


def _digest(value: Any, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise _error("FINAL_CHARACTER_COMPONENT_HASH_INVALID", f"The {field} is not an exact SHA-256 digest.")
    return value


def _opaque(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None:
        raise _error("FINAL_CHARACTER_WORKFLOW_ID_INVALID", f"The {field} is not a bounded opaque identifier.")
    return value


def _challenge_nonce(value: Any) -> str:
    # token_urlsafe may start with '-' or '_'; identifiers may not.
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value) is None:
        raise _error("FINAL_CHARACTER_WORKFLOW_ID_INVALID", "The challenge nonce is not a bounded URL-safe token.")
    return value


def _project_id(value: Any) -> str:
    if not isinstance(value, str) or _PROJECT_ID.fullmatch(value) is None:
        raise _error("FINAL_CHARACTER_WORKFLOW_PROJECT_INVALID", "The project ID is not a bounded path-safe identifier.")
    return value


def _read_json(path: Path, *, code: str, maximum: int = 2 * 1024 * 1024) -> Any:
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise OSError("not a bounded regular file")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            raw = handle.read(maximum + 1)
        if len(raw) > maximum:
            raise OSError("file exceeds limit")
        return json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise _error(code, "A required server-owned JSON artifact is missing or malformed.", details={"name": path.name}) from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _stable_stat(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _copy_descriptor_tree(source_fd: int, target: Path, budget: dict[str, int]) -> None:
    """Copy one already-open directory without resolving another source path."""

    before = os.fstat(source_fd)
    if not stat.S_ISDIR(before.st_mode) or before.st_uid != os.getuid():
        raise _error("FINAL_CHARACTER_WORKFLOW_PATH_INVALID", "A captured tree directory is not owner-controlled.")
    try:
        names = sorted(os.listdir(source_fd))
    except OSError as exc:
        raise _error("FINAL_CHARACTER_COMPONENT_CHANGED", "A component tree changed while it was captured.") from exc
    if any(not name or name in {".", ".."} or "/" in name or "\x00" in name for name in names):
        raise _error("FINAL_CHARACTER_WORKFLOW_PATH_INVALID", "A component tree contains an invalid member name.")
    for name in names:
        member_fd = -1
        try:
            member_fd = os.open(
                name,
                os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=source_fd,
            )
            member_before = os.fstat(member_fd)
            destination = target / name
            if stat.S_ISDIR(member_before.st_mode):
                os.mkdir(destination, 0o700)
                _copy_descriptor_tree(member_fd, destination, budget)
                os.chmod(destination, 0o500)
            elif stat.S_ISREG(member_before.st_mode):
                if member_before.st_nlink != 1:
                    raise _error("FINAL_CHARACTER_WORKFLOW_PATH_INVALID", "A component tree contains a multiply linked file.", details={"name": name})
                budget["files"] += 1
                budget["bytes"] += member_before.st_size
                if (
                    budget["files"] > _CAPTURE_FILE_LIMIT
                    or budget["bytes"] > _CAPTURE_BYTE_LIMIT
                    or member_before.st_size > _CAPTURE_MEMBER_LIMIT
                ):
                    raise _error("FINAL_CHARACTER_COMPONENT_TOO_LARGE", "A component tree exceeds the bounded capture limits.")
                output_fd = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o400,
                )
                try:
                    while True:
                        chunk = os.read(member_fd, 1024 * 1024)
                        if not chunk:
                            break
                        view = memoryview(chunk)
                        while view:
                            written = os.write(output_fd, view)
                            view = view[written:]
                    os.fsync(output_fd)
                finally:
                    os.close(output_fd)
                if _stable_stat(os.fstat(member_fd)) != _stable_stat(member_before):
                    raise _error("FINAL_CHARACTER_COMPONENT_CHANGED", "A component file changed while it was captured.")
            else:
                raise _error("FINAL_CHARACTER_WORKFLOW_SYMLINK_REJECTED", "A component tree contains a link or special file.", details={"name": name})
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _error("FINAL_CHARACTER_WORKFLOW_SYMLINK_REJECTED", "A component tree contains a symlink.", details={"name": name}) from exc
            raise _error("FINAL_CHARACTER_COMPONENT_CHANGED", "A component tree changed while it was captured.", details={"name": name}) from exc
        finally:
            if member_fd >= 0:
                os.close(member_fd)
    try:
        after_names = sorted(os.listdir(source_fd))
        after = os.fstat(source_fd)
    except OSError as exc:
        raise _error("FINAL_CHARACTER_COMPONENT_CHANGED", "A component tree changed while it was captured.") from exc
    if names != after_names or _stable_stat(after) != _stable_stat(before):
        raise _error("FINAL_CHARACTER_COMPONENT_CHANGED", "A component directory changed while it was captured.")


class FinalCharacterWorkflowService:
    """Record and revalidate one server-owned final-character triplet."""

    def __init__(
        self,
        db: Database,
        *,
        principal_provider: PrincipalProvider | None = None,
        integrity: IntegrityService | None = None,
    ) -> None:
        if not isinstance(db, Database):
            raise _error("FINAL_CHARACTER_WORKFLOW_INVALID", "The workflow requires the server Database.", status_code=500)
        self.db = db
        self.principal_provider = principal_provider or ProcessPrincipalProvider()
        self.integrity = integrity or IntegrityService.for_database(db)
        self.challenges = ApprovalChallengeService(
            db,
            principal_provider=self.principal_provider,
            integrity=self.integrity,
        )
        try:
            self._data_root_authority = final_materializer._open_fixed_directory(
                Path(db.settings.data_dir),
                create=False,
            )
        except OSError as exc:
            raise _error(
                "FINAL_CHARACTER_WORKFLOW_ROOT_INVALID",
                "The configured data root is not a fixed regular directory.",
                status_code=500,
            ) from exc

    def close(self) -> None:
        authority = getattr(self, "_data_root_authority", None)
        if authority is not None:
            authority.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @property
    def review_root(self) -> Path:
        """The one fixed private review-record store for this application."""

        return self.data_root / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / FINAL_CHARACTER_REVIEW_STORE_NAME

    def _review_authority(
        self,
        review_root: Path | None = None,
        *,
        expected_identity: tuple[int, int] | None = None,
        expected_present: bool | None = None,
    ) -> final_materializer.FinalCharacterReviewAuthority:
        return final_materializer.FinalCharacterReviewAuthority(
            self.review_root if review_root is None else review_root,
            self.integrity,
            expected_identity=expected_identity,
            expected_present=expected_present,
        )

    @property
    def data_root(self) -> Path:
        try:
            self._data_root_authority.assert_current()
            info = os.fstat(self._data_root_authority.fd)
        except (FoundryError, OSError) as exc:
            raise _error("FINAL_CHARACTER_WORKFLOW_ROOT_INVALID", "The configured data root is unavailable.", status_code=500) from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise _error("FINAL_CHARACTER_WORKFLOW_ROOT_INVALID", "The configured data root is not a directory.", status_code=500)
        return self._data_root_authority.path

    @staticmethod
    def _check_private_directory(path: Path) -> None:
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", "The workflow directory cannot be inspected.", status_code=500) from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", "The workflow directory is not private and owner-controlled.", status_code=500)

    @classmethod
    def _private_child(
        cls,
        parent: Path,
        name: str,
        *,
        create: bool,
        include_identity: bool = False,
    ) -> Path | tuple[Path, tuple[int, int] | None]:
        if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise _error("FINAL_CHARACTER_WORKFLOW_PATH_INVALID", "A workflow directory name is invalid.", status_code=500)
        parent_fd = -1
        try:
            parent_descriptor = final_materializer._proc_fd_number(Path(parent))
            if parent_descriptor is not None:
                parent_fd = os.dup(parent_descriptor)
            else:
                parent_fd = os.open(
                    parent,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                )
            parent_info = os.fstat(parent_fd)
            if not stat.S_ISDIR(parent_info.st_mode):
                raise OSError("workflow parent is not a directory")
            try:
                info = os.lstat(name, dir_fd=parent_fd)
                exists = True
            except FileNotFoundError:
                exists = False
        except FileNotFoundError:
            exists = False
        except OSError as exc:
            if parent_fd >= 0:
                os.close(parent_fd)
            raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", "A workflow directory cannot be inspected.", status_code=500) from exc
        if not exists:
            if not create:
                if parent_fd >= 0:
                    os.close(parent_fd)
                result = parent / name
                return (result, None) if include_identity else result
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            except OSError as exc:
                if parent_fd >= 0:
                    os.close(parent_fd)
                raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", "A workflow directory could not be created.", status_code=500) from exc
        child_fd = -1
        try:
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_fd,
            )
            child_info = os.fstat(child_fd)
            if (
                not stat.S_ISDIR(child_info.st_mode)
                or child_info.st_uid != os.getuid()
                or stat.S_IMODE(child_info.st_mode) & 0o077
            ):
                raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", "The workflow directory is not private and owner-controlled.", status_code=500)
        except FoundryError:
            raise
        except OSError as exc:
            raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", "A workflow directory cannot be opened safely.", status_code=500) from exc
        finally:
            try:
                os.close(child_fd)
            except (NameError, OSError):
                pass
            if parent_fd >= 0:
                os.close(parent_fd)
        result = parent / name
        if include_identity:
            return result, (child_info.st_dev, child_info.st_ino)
        return result

    def _workflow_root(self, *, create: bool) -> Path:
        self._data_root_authority.assert_current()
        return self._private_child(self._data_root_authority.fd_path, FINAL_CHARACTER_WORKFLOW_ROOT_NAME, create=create)

    def _project_root(self, project_id: str, *, create: bool) -> Path:
        project_id = _project_id(project_id)
        workflow = self._workflow_root(create=create)
        if not workflow.exists() and not create:
            return workflow / project_id
        project = self._private_child(workflow, project_id, create=create)
        if create:
            self._private_child(project, "components", create=True)
        return project

    @staticmethod
    def _check_private_file(path: Path, *, field: str) -> None:
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", f"The {field} cannot be inspected.") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", f"The {field} is not a private owner-controlled file.")

    @staticmethod
    def _check_owned_file(path: Path, *, field: str, maximum: int) -> None:
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", f"The {field} cannot be inspected.") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > maximum:
            raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", f"The {field} is not a bounded owner-controlled file.")

    @staticmethod
    def _reject_tree_links(root: Path, *, field: str) -> None:
        if root.is_symlink() or not root.is_dir():
            raise _error("FINAL_CHARACTER_WORKFLOW_PATH_INVALID", f"The {field} is not a regular directory.")
        for child in root.rglob("*"):
            if child.is_symlink():
                raise _error("FINAL_CHARACTER_WORKFLOW_SYMLINK_REJECTED", f"The {field} contains a symlink.", details={"name": child.name})

    @staticmethod
    def _verify_snapshot_permissions(root: Path, *, field: str) -> None:
        entries = [root, *sorted(root.rglob("*"))]
        for entry in entries:
            try:
                info = os.lstat(entry)
            except OSError as exc:
                raise _error("FINAL_CHARACTER_COMPONENT_STALE", f"The {field} snapshot cannot be inspected.") from exc
            expected = 0o500 if stat.S_ISDIR(info.st_mode) else 0o400 if stat.S_ISREG(info.st_mode) else None
            if expected is None or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != expected:
                raise _error("FINAL_CHARACTER_COMPONENT_STALE", f"The {field} snapshot is not immutable and owner-controlled.", details={"name": entry.name})

    def _open_tree_fd(self, value: Any, *, field: str, relative: bool) -> tuple[int, str]:
        """Open every supplied path component with openat and retain the leaf."""

        if relative:
            if not isinstance(value, str) or not value:
                raise _error("FINAL_CHARACTER_COMPONENT_RECEIPT_INVALID", f"The {field} relative path is missing.")
            pure = PurePosixPath(value)
            if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
                raise _error("FINAL_CHARACTER_COMPONENT_RECEIPT_INVALID", f"The {field} relative path is invalid.")
            parts = pure.parts
            relative_value = pure.as_posix()
        else:
            if not isinstance(value, str) or not value or not Path(value).is_absolute():
                raise _error("FINAL_CHARACTER_WORKFLOW_PATH_INVALID", f"The server-owned {field} path is not absolute.")
            try:
                lexical = Path(value).relative_to(self.data_root)
            except ValueError as exc:
                raise _error("FINAL_CHARACTER_WORKFLOW_PATH_ESCAPE", f"The server-owned {field} escapes the configured data root.") from exc
            if any(part in {"", ".", ".."} for part in lexical.parts):
                raise _error("FINAL_CHARACTER_WORKFLOW_PATH_ESCAPE", f"The server-owned {field} escapes the configured data root.")
            parts = lexical.parts
            relative_value = lexical.as_posix()
        self._data_root_authority.assert_current()
        current = os.dup(self._data_root_authority.fd)
        try:
            for part in parts:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=current,
                )
                os.close(current)
                current = next_fd
            info = os.fstat(current)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise OSError("tree root is not owner-controlled")
            return current, relative_value
        except OSError as exc:
            os.close(current)
            raise _error("FINAL_CHARACTER_WORKFLOW_PATH_ESCAPE", f"The server-owned {field} is unavailable or contains a link.") from exc

    @contextmanager
    def _captured_server_tree(self, value: Any, *, field: str) -> Iterator[tuple[Path, str]]:
        source_fd, original_relative = self._open_tree_fd(value, field=field, relative=False)
        self._data_root_authority.assert_current()
        root_fd = os.dup(self._data_root_authority.fd)
        staging_fd = -1
        staging_name = ""
        for _ in range(128):
            staging_name = f".final-character-capture-{secrets.token_hex(12)}"
            try:
                os.mkdir(staging_name, 0o700, dir_fd=root_fd)
            except FileExistsError:
                continue
            try:
                staging_fd = os.open(
                    staging_name,
                    os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=root_fd,
                )
            except OSError:
                try:
                    os.rmdir(staging_name, dir_fd=root_fd)
                except OSError:
                    pass
                continue
            break
        if staging_fd < 0:
            os.close(root_fd)
            os.close(source_fd)
            raise _error("FINAL_CHARACTER_COMPONENT_CHANGED", "A component capture directory could not be reserved.")
        staging = final_materializer._BoundDirectoryPath(f"/proc/self/fd/{staging_fd}")
        try:
            _copy_descriptor_tree(source_fd, staging, {"files": 0, "bytes": 0})
            os.lseek(staging_fd, 0, os.SEEK_SET)
            anchors = [name for name in sorted(os.listdir(staging_fd))
                       if stat.S_ISDIR(os.stat(name, dir_fd=staging_fd, follow_symlinks=False).st_mode)]
            if not anchors:
                raise _error("FINAL_CHARACTER_COMPONENT_STALE", "A component capture has no regular directory anchor.")
            # Preserve descriptor binding when validators cast this subclass to Path.
            staging = final_materializer._BoundDirectoryPath(f"/proc/self/fd/{staging_fd}/{anchors[0]}/..")
            staging._capture_parent_fd = root_fd  # type: ignore[attr-defined]
            staging._capture_name = staging_name  # type: ignore[attr-defined]
            staging._capture_transferred = False  # type: ignore[attr-defined]
            self._reject_tree_links(staging, field=field)
            yield staging, original_relative
        finally:
            os.close(source_fd)
            try:
                if not getattr(staging, "_capture_transferred", False):
                    final_materializer._clear_directory_fd(staging_fd, remove_entries=True)
                    held = os.fstat(staging_fd)
                    current_stat = os.lstat(staging_name, dir_fd=root_fd)
                    if (current_stat.st_dev, current_stat.st_ino) == (held.st_dev, held.st_ino):
                        os.rmdir(staging_name, dir_fd=root_fd)
            except OSError:
                pass
            os.close(staging_fd)
            os.close(root_fd)

    @contextmanager
    def _pinned_tree_from_relative(self, value: Any, *, field: str) -> Iterator[Path]:
        fd, _relative = self._open_tree_fd(value, field=field, relative=True)
        try:
            anchors = [
                name
                for name in sorted(os.listdir(fd))
                if stat.S_ISDIR(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode)
            ]
            if not anchors:
                raise _error("FINAL_CHARACTER_COMPONENT_STALE", "A component snapshot has no regular directory anchor.")
            # The final path element is '..', so Path.is_symlink() observes the
            # pinned directory rather than the procfs descriptor link itself.
            yield Path(f"/proc/self/fd/{fd}/{anchors[0]}/..")
        finally:
            os.close(fd)

    def _install_snapshot(self, project_id: str, component: str, captured: Path, files_tree_sha256: str) -> tuple[Path, str]:
        project = self._project_root(project_id, create=True)
        snapshots = self._private_child(project, "snapshots", create=True)
        component_root = self._private_child(snapshots, component, create=True)
        target = component_root / files_tree_sha256
        if os.path.lexists(target):
            self._reject_tree_links(target, field=f"{component} snapshot")
            self._verify_snapshot_permissions(target, field=component)
            if final_materializer._tree_hash(target) != files_tree_sha256:
                raise _error("FINAL_CHARACTER_COMPONENT_COLLISION", "A content-addressed component snapshot contains different bytes.")
        else:
            try:
                source_parent_fd = getattr(captured, "_capture_parent_fd", None)
                source_name = getattr(captured, "_capture_name", None)
                if isinstance(source_parent_fd, int) and isinstance(source_name, str):
                    destination_parent_fd = os.open(
                        component_root,
                        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                    )
                    try:
                        os.rename(
                            source_name,
                            files_tree_sha256,
                            src_dir_fd=source_parent_fd,
                            dst_dir_fd=destination_parent_fd,
                        )
                    finally:
                        os.close(destination_parent_fd)
                    captured._capture_transferred = True  # type: ignore[attr-defined]
                else:
                    os.rename(captured, target)
            except FileExistsError:
                if final_materializer._tree_hash(target) != files_tree_sha256:
                    raise _error("FINAL_CHARACTER_COMPONENT_COLLISION", "A content-addressed component snapshot contains different bytes.")
            else:
                for child in sorted(target.rglob("*"), reverse=True):
                    if child.is_dir():
                        os.chmod(child, 0o500)
                    elif child.is_file():
                        os.chmod(child, 0o400)
                os.chmod(target, 0o500)
        relative = (
            PurePosixPath(FINAL_CHARACTER_WORKFLOW_ROOT_NAME)
            / project_id
            / "snapshots"
            / component
            / files_tree_sha256
        ).as_posix()
        return target, relative

    @contextmanager
    def _locked(self, project_root: Path) -> Iterator[None]:
        root_fd = os.open(project_root, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
        lock_fd = -1
        try:
            lock_fd = os.open(
                ".lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_fd,
            )
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield
        finally:
            if lock_fd >= 0:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            os.close(root_fd)

    @staticmethod
    def _exclusive_json(parent: Path, name: str, value: Mapping[str, Any]) -> None:
        payload = (canonical_json(value) + "\n").encode("utf-8")
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
        fd = -1
        try:
            try:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                path = parent / name
                FinalCharacterWorkflowService._check_private_file(path, field="component receipt")
                existing = path.read_bytes()
                if existing != payload:
                    raise _error("FINAL_CHARACTER_COMPONENT_COLLISION", "A content-addressed receipt path contains different bytes.")
                return
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(parent_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            os.close(parent_fd)

    @staticmethod
    def _atomic_pointer(project_root: Path, value: Mapping[str, Any]) -> None:
        payload = (canonical_json(value) + "\n").encode("utf-8")
        root_fd = os.open(project_root, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
        temporary = f".current.{secrets.token_hex(16)}.tmp"
        fd = -1
        try:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root_fd,
            )
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, "current.json", src_dir_fd=root_fd, dst_dir_fd=root_fd)
            os.fsync(root_fd)
        except Exception:
            try:
                os.unlink(temporary, dir_fd=root_fd)
            except OSError:
                pass
            raise
        finally:
            if fd >= 0:
                os.close(fd)
            os.close(root_fd)

    @staticmethod
    def _value(*sources_and_keys: Any) -> Any:
        *sources, keys = sources_and_keys
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    return value
        return None

    @staticmethod
    def _manifest(root: Path, name: str) -> dict[str, Any]:
        value = _read_json(root / name, code="FINAL_CHARACTER_COMPONENT_INVALID")
        if not isinstance(value, Mapping):
            raise _error("FINAL_CHARACTER_COMPONENT_INVALID", "A component manifest is not an object.")
        return dict(value)

    @staticmethod
    def _validate_command4_workspace(root: Path, project_id: str) -> None:
        """Freshly verify the full sealed executable Action workspace."""

        workspace = _read_json(root / "Workspace_Manifest.json", code="FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID")
        if isinstance(workspace, Mapping) and workspace.get("project_id") != project_id:
            raise _error("FINAL_CHARACTER_COMPONENT_PROJECT_MISMATCH", "The Command 4 workspace belongs to another project.")
        try:
            command4_provider._reject_recursive_nonregular(
                root,
                code="FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID",
                message="The Command 4 workspace contains a link or special member.",
            )
            command4_provider._verify_workspace_checksums(root)
            _index, packets = final_materializer._canonical_action_index(root)
        except FoundryError as exc:
            raise _error(
                "FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID",
                "The Command 4 workspace is not a fresh checksummed executable Action authority.",
                details={"cause": exc.code},
            ) from exc
        surface = _read_json(root / "Command_4/Complete_Action_Surface.json", code="FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID")
        build_surface_path = root / "Build/Complete_Action_Surface.json"
        build_surface = (
            _read_json(build_surface_path, code="FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID")
            if build_surface_path.is_file()
            else surface
        )
        validation = _read_json(root / "Validation/Command4_Provider.validation.json", code="FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID")
        provider_audit = _read_json(root / "Command_4/Provider_Action_Authoring_Audit.json", code="FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID")
        manifest = _read_json(root / "Command4_Provider_Overlay_Manifest.json", code="FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID")
        if (
            not isinstance(workspace, Mapping)
            or workspace.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
            or workspace.get("project_id") != project_id
            or not isinstance(surface, Mapping)
            or surface.get("schema_version") != "TianxiaFoundry.Command4ProviderCompleteActionSurface.v1"
            or surface.get("project_id") != project_id
            or surface.get("status") != "COMMAND4_ACTION_AUTHORITY_READY"
            or surface.get("execution_authority") is not True
            or surface.get("unresolved") not in (None, [])
            or surface.get("unresolved_actions") not in (None, [])
            or not packets
            or build_surface != surface
            or not isinstance(validation, Mapping)
            or validation.get("schema") != "TianxiaFoundry.Command4ProviderAuthoringEvidence.v1"
            or validation.get("valid") is not True
            or validation.get("execution_authority") is not True
            or not isinstance(provider_audit, Mapping)
            or provider_audit.get("schema") != "TianxiaFoundry.Command4ProviderAudit.v1"
            or provider_audit.get("execution_authority") is not True
            or not isinstance(manifest, Mapping)
            or manifest.get("schema") != "TianxiaFoundry.Command4ProviderOverlayManifest.v1"
        ):
            raise _error("FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID", "The Command 4 workspace lacks complete sealed Action evidence.")
        # The audit alone names provider_id and purpose; the manifest and the
        # validation receipt bind the same authoring result by its hashes
        # (the sealed provider-authoring manifest shape the Command 5 reviewed
        # overlay validator pins).
        shared = ("request_sha256", "response_sha256", "source_workspace_sha256")
        if (
            any(provider_audit.get(key) != manifest.get(key) for key in shared)
            or any(validation.get(key) != manifest.get(key) for key in ("request_sha256", "response_sha256"))
            or not isinstance(provider_audit.get("provider_id"), str)
            or not provider_audit.get("provider_id")
            or provider_audit.get("purpose") != command4_provider.COMMAND4_ACTION_AUTHORING_PURPOSE
        ):
            raise _error("FINAL_CHARACTER_COMMAND4_WORKSPACE_INVALID", "The Command 4 evidence records do not bind one authoring result.")

    def _load_pointer(self, project_id: str) -> dict[str, Any]:
        project = self._project_root(project_id, create=False)
        path = project / "current.json"
        if not os.path.lexists(path):
            raise _error("FINAL_CHARACTER_REVIEW_NOT_READY", "No current final-character components are recorded.")
        self._check_private_file(path, field="current component pointer")
        value = _read_json(path, code="FINAL_CHARACTER_CURRENT_POINTER_INVALID", maximum=256 * 1024)
        if not isinstance(value, Mapping) or set(value) != _POINTER_KEYS:
            raise _error("FINAL_CHARACTER_CURRENT_POINTER_INVALID", "The current component pointer has unsupported fields.")
        if value.get("schema_version") != FINAL_CHARACTER_COMPONENT_POINTER_SCHEMA or value.get("project_id") != project_id:
            raise _error("FINAL_CHARACTER_CURRENT_POINTER_INVALID", "The current component pointer has inconsistent identity.")
        components = value.get("components")
        if not isinstance(components, Mapping) or any(key not in _COMPONENTS for key in components):
            raise _error("FINAL_CHARACTER_CURRENT_POINTER_INVALID", "The current component pointer contains unsupported components.")
        unsigned = {key: deepcopy(value[key]) for key in sorted(_POINTER_KEYS - {"pointer_sha256"})}
        if value.get("pointer_sha256") != sha256_json(unsigned):
            raise _error("FINAL_CHARACTER_CURRENT_POINTER_INVALID", "The current component pointer hash is stale.")
        return dict(value)

    def _write_pointer(self, project_id: str, components: Mapping[str, Any]) -> None:
        if any(key not in _COMPONENTS for key in components):
            raise _error("FINAL_CHARACTER_CURRENT_POINTER_INVALID", "The component pointer contains an unsupported component.")
        normalized = {key: _opaque(value, field="component receipt ID") for key, value in sorted(components.items())}
        pointer: dict[str, Any] = {
            "schema_version": FINAL_CHARACTER_COMPONENT_POINTER_SCHEMA,
            "project_id": project_id,
            "components": normalized,
        }
        pointer["pointer_sha256"] = sha256_json(pointer)
        self._atomic_pointer(self._project_root(project_id, create=True), pointer)

    @contextmanager
    def _load_receipt(self, project_id: str, component: str, receipt_id: str) -> Iterator[tuple[dict[str, Any], Path]]:
        if _RECEIPT_ID.fullmatch(receipt_id) is None or not receipt_id.startswith(f"component.{component}."):
            raise _error("FINAL_CHARACTER_COMPONENT_RECEIPT_INVALID", "The component receipt ID is invalid.")
        path = self._project_root(project_id, create=False) / "components" / f"{receipt_id}.json"
        if not os.path.lexists(path):
            raise _error("FINAL_CHARACTER_COMPONENT_RECEIPT_NOT_FOUND", "A current component receipt is missing.")
        self._check_private_file(path, field="component receipt")
        value = _read_json(path, code="FINAL_CHARACTER_COMPONENT_RECEIPT_INVALID")
        if not isinstance(value, Mapping) or set(value) != _RECEIPT_KEYS:
            raise _error("FINAL_CHARACTER_COMPONENT_RECEIPT_INVALID", "A component receipt has unsupported fields.")
        receipt = dict(value)
        if (
            receipt.get("schema_version") != FINAL_CHARACTER_COMPONENT_RECEIPT_SCHEMA
            or receipt.get("receipt_id") != receipt_id
            or receipt.get("component") != component
            or receipt.get("project_id") != project_id
        ):
            raise _error("FINAL_CHARACTER_COMPONENT_RECEIPT_INVALID", "A component receipt has inconsistent identity.")
        expected_id = f"component.{component}." + sha256_json(
            {key: receipt[key] for key in sorted(_RECEIPT_KEYS - {"receipt_id", "receipt_sha256"})}
        )
        expected_sha = sha256_json({key: receipt[key] for key in sorted(_RECEIPT_KEYS - {"receipt_sha256"})})
        if receipt_id != expected_id or receipt.get("receipt_sha256") != expected_sha:
            raise _error("FINAL_CHARACTER_COMPONENT_RECEIPT_INVALID", "A component receipt is not content-addressed correctly.")
        for field in ("artifact_sha256", "overlay_tree_sha256", "files_tree_sha256"):
            _digest(receipt.get(field), field=field)
        for field in ("candidate_sha256", "source_workspace_sha256", "request_sha256", "response_sha256"):
            _digest(receipt.get(field), field=field, optional=True)
        if receipt.get("projection_id") is not None:
            _opaque(receipt["projection_id"], field="projection ID")
        expected_prefix = PurePosixPath(FINAL_CHARACTER_WORKFLOW_ROOT_NAME) / project_id / "snapshots" / component
        relative = PurePosixPath(str(receipt.get("overlay_relative_path") or ""))
        if relative.parent != expected_prefix or relative.name != receipt["files_tree_sha256"]:
            raise _error("FINAL_CHARACTER_COMPONENT_RECEIPT_INVALID", "A component receipt does not reference its private content-addressed snapshot.")
        with self._pinned_tree_from_relative(relative.as_posix(), field=f"{component} overlay") as overlay:
            self._verify_snapshot_permissions(overlay, field=component)
            if final_materializer._tree_hash(overlay) != receipt["files_tree_sha256"]:
                raise _error("FINAL_CHARACTER_COMPONENT_STALE", "A component overlay changed after it was recorded.")
            yield receipt, overlay

    @contextmanager
    def _current_action(self, project_id: str) -> Iterator[tuple[dict[str, Any], Path]]:
        pointer = self._load_pointer(project_id)
        receipt_id = (pointer.get("components") or {}).get("command4")
        if not isinstance(receipt_id, str):
            raise _error("FINAL_CHARACTER_REVIEW_NOT_READY", "The executable Command 4 Action workspace is not recorded.")
        with self._load_receipt(project_id, "command4", receipt_id) as (receipt, source):
            self._validate_command4_workspace(source, project_id)
            observed = final_materializer._workspace_sha256(source)
            if observed != receipt.get("source_workspace_sha256"):
                raise _error("FINAL_CHARACTER_SOURCE_WORKSPACE_MISMATCH", "The recorded Action workspace hash is stale.")
            yield receipt, source

    def _component_evidence(
        self,
        component: str,
        project_id: str,
        result: Mapping[str, Any],
        overlay: Path,
        relative: str,
    ) -> dict[str, Any]:
        request_sha = self._value(result, ("request_sha256",))
        response_sha = self._value(result, ("response_sha256",))
        if component == "command4":
            self._validate_command4_workspace(overlay, project_id)
            manifest = self._manifest(overlay, "Command4_Provider_Overlay_Manifest.json")
            surface = _read_json(overlay / "Command_4/Complete_Action_Surface.json", code="FINAL_CHARACTER_COMPONENT_INVALID")
            validation = _read_json(overlay / "Validation/Command4_Provider.validation.json", code="FINAL_CHARACTER_COMPONENT_INVALID")
            if (
                not isinstance(surface, Mapping)
                or not isinstance(validation, Mapping)
                or validation.get("valid") is not True
                or validation.get("execution_authority") is not True
                or surface.get("execution_authority") is not True
                or not isinstance(surface.get("actions"), list)
                or not surface["actions"]
                or surface.get("unresolved_actions") not in (None, [])
                or surface.get("unresolved") not in (None, [])
            ):
                raise _error("FINAL_CHARACTER_COMPONENT_INVALID", "The Command 4 workspace is not a complete executable Action surface.")
            overlay_id = self._value(result, manifest, ("overlay_id",)) or overlay.name
            project = self._value(result, surface, manifest, ("project_id",)) or project_id
            if project != project_id:
                raise _error("FINAL_CHARACTER_COMPONENT_PROJECT_MISMATCH", "The Command 4 workspace belongs to another project.")
            candidate = self._value(result, surface, manifest, ("candidate_sha256", "candidate_id", "base_candidate_sha256"))
            projection = self._value(result, surface, manifest, ("projection_id",))
            source_hash = final_materializer._workspace_sha256(overlay)
            artifact_sha = sha256_file(overlay / "Command_4/Complete_Action_Surface.json")
            semantic_tree = final_materializer._tree_hash(overlay, include_checksums=False)
            request_sha = request_sha or manifest.get("request_sha256")
            response_sha = response_sha or manifest.get("response_sha256")
        elif component == "composite_controller":
            manifest = self._manifest(overlay, "Composite_Controller_Overlay_Manifest.json")
            raw_artifact = _read_json(overlay / "Command_4/Composite_Controller_Artifact.json", code="FINAL_CHARACTER_COMPONENT_INVALID")
            if not isinstance(raw_artifact, Mapping):
                raise _error("FINAL_CHARACTER_COMPONENT_INVALID", "The Composite artifact is not an object.")
            candidate = raw_artifact.get("base_candidate_sha256")
            projection = raw_artifact.get("projection_id")
            with self._current_action(project_id) as (_, source):
                validated = CompositeControllerAuthoring.validate_overlay(
                    overlay,
                    project_id=project_id,
                    candidate_sha256=str(candidate),
                    projection_id=str(projection),
                    source_workspace=source,
                )
            artifact = validated.get("artifact") if isinstance(validated.get("artifact"), Mapping) else {}
            project = artifact.get("project_id")
            source_hash = artifact.get("source_workspace_sha256")
            overlay_id = validated.get("overlay_id")
            artifact_sha = validated.get("artifact_sha256")
            semantic_tree = final_materializer._validated_overlay_internal_tree_hash(overlay, validated, label="Composite")
            request_sha = request_sha or manifest.get("request_sha256")
            response_sha = response_sha or manifest.get("response_sha256")
        else:
            raise _error("FINAL_CHARACTER_COMPONENT_INVALID", "Unknown final-character component.", details={"component": component})
        if project != project_id:
            raise _error("FINAL_CHARACTER_COMPONENT_PROJECT_MISMATCH", "The authoring component belongs to another project.")
        overlay_id = _opaque(overlay_id, field="overlay ID")
        artifact_sha = _digest(artifact_sha, field="artifact_sha256")
        semantic_tree = _digest(semantic_tree, field="overlay_tree_sha256")
        candidate = _digest(candidate, field="candidate_sha256", optional=True)
        source_hash = _digest(source_hash, field="source_workspace_sha256")
        if projection is not None:
            projection = _opaque(projection, field="projection ID")
        request_sha = _digest(request_sha, field="request_sha256", optional=True)
        response_sha = _digest(response_sha, field="response_sha256", optional=True)
        return {
            "component": component,
            "project_id": project_id,
            "overlay_relative_path": relative,
            "overlay_id": overlay_id,
            "artifact_sha256": artifact_sha,
            "overlay_tree_sha256": semantic_tree,
            "files_tree_sha256": final_materializer._tree_hash(overlay),
            "candidate_sha256": candidate,
            "projection_id": projection,
            "source_workspace_sha256": source_hash,
            "request_sha256": request_sha,
            "response_sha256": response_sha,
        }

    @staticmethod
    def _public_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(receipt.get(key))
            for key in (
                "receipt_id",
                "receipt_sha256",
                "component",
                "project_id",
                "overlay_id",
                "artifact_sha256",
                "overlay_tree_sha256",
                "files_tree_sha256",
                "candidate_sha256",
                "projection_id",
                "source_workspace_sha256",
                "request_sha256",
                "response_sha256",
            )
        }

    def _record_component(self, component: str, project_id: str, result: Mapping[str, Any] | Any) -> dict[str, Any] | None:
        if not isinstance(result, Mapping) or result.get("valid") is not True:
            return None
        project_id = _project_id(project_id)
        if component not in _COMPONENTS:
            raise _error("FINAL_CHARACTER_COMPONENT_INVALID", "The workflow component is unsupported.")
        with self._captured_server_tree(result.get("overlay_path"), field=f"{component} overlay") as (captured, _original_relative):
            first = self._component_evidence(component, project_id, result, captured, "pending")
            project = self._project_root(project_id, create=True)
            with self._locked(project):
                _snapshot, relative = self._install_snapshot(project_id, component, captured, first["files_tree_sha256"])
                with self._pinned_tree_from_relative(relative, field=f"{component} snapshot") as overlay:
                    second = self._component_evidence(component, project_id, result, overlay, relative)
                comparable_first = {**first, "overlay_relative_path": relative}
                if comparable_first != second:
                    raise _error("FINAL_CHARACTER_COMPONENT_CHANGED", "The authoring component changed while it was being recorded.")
                unsigned = {
                "schema_version": FINAL_CHARACTER_COMPONENT_RECEIPT_SCHEMA,
                "component": component,
                **second,
                }
                receipt_id = f"component.{component}." + sha256_json(unsigned)
                with_id = {**unsigned, "receipt_id": receipt_id}
                receipt = {**with_id, "receipt_sha256": sha256_json(with_id)}
                components_root = self._private_child(project, "components", create=True)
                self._exclusive_json(components_root, f"{receipt_id}.json", receipt)
                try:
                    pointer = self._load_pointer(project_id)
                    components = dict(pointer["components"])
                except FoundryError as exc:
                    if exc.code != "FINAL_CHARACTER_REVIEW_NOT_READY":
                        raise
                    components = {}
                components[component] = receipt_id
                self._write_pointer(project_id, components)
        return self._public_receipt(receipt)

    def record_action_workspace(self, project_id: str, result: Mapping[str, Any] | Any) -> dict[str, Any] | None:
        return self._record_component("command4", project_id, result)

    def record_composite_controller(self, project_id: str, result: Mapping[str, Any] | Any) -> dict[str, Any] | None:
        return self._record_component("composite_controller", project_id, result)

    def _candidate_pointer(self, project_id: str) -> dict[str, Any] | None:
        path = self.data_root / "factory_candidates" / project_id / "current.json"
        if not os.path.lexists(path):
            return None
        self._check_owned_file(path, field="candidate pointer", maximum=512 * 1024)
        value = _read_json(path, code="FINAL_CHARACTER_CANDIDATE_POINTER_INVALID", maximum=512 * 1024)
        if not isinstance(value, Mapping) or value.get("project_id") not in (None, project_id):
            raise _error("FINAL_CHARACTER_CANDIDATE_POINTER_INVALID", "The current candidate pointer belongs to another project.")
        candidate = value.get("candidate_sha256")
        projection = value.get("projection_id")
        _digest(candidate, field="candidate_sha256", optional=True)
        if projection is not None:
            _opaque(projection, field="projection ID")
        return dict(value)

    def _derive_triplet(self, project_id: str) -> dict[str, Any]:
        project_id = _project_id(project_id)
        pointer = self._load_pointer(project_id)
        component_ids = pointer["components"]
        missing = [component for component in _COMPONENTS if component not in component_ids]
        if missing:
            raise _error("FINAL_CHARACTER_REVIEW_NOT_READY", "The Action and Composite components are required.", details={"missing": missing})
        with ExitStack() as stack:
            loaded = {
                component: stack.enter_context(self._load_receipt(project_id, component, str(component_ids[component])))
                for component in _COMPONENTS
            }
            receipts = {component: value[0] for component, value in loaded.items()}
            paths = {component: value[1] for component, value in loaded.items()}
            source = paths["command4"]
            self._validate_command4_workspace(source, project_id)
            source_hash = final_materializer._workspace_sha256(source)
            if source_hash != receipts["command4"].get("source_workspace_sha256"):
                raise _error("FINAL_CHARACTER_SOURCE_WORKSPACE_MISMATCH", "The current Action workspace no longer matches its receipt.")
            try:
                composite = CompositeControllerAuthoring.validate_overlay(
                    paths["composite_controller"],
                    project_id=project_id,
                    candidate_sha256=str(receipts["composite_controller"].get("candidate_sha256")),
                    projection_id=str(receipts["composite_controller"].get("projection_id")),
                    source_workspace=source,
                )
            except FoundryError as exc:
                raise _error("FINAL_CHARACTER_OVERLAY_REJECTED", "A current overlay failed fresh source-bound validation.", details={"cause": exc.code}) from exc
            # The controller-built Immortal Arts are re-checked against the
            # compiled rules; an invalid or missing CL15+ Art blocks review.
            immortal_arts = constructed_immortal_art_binding(source)
            composite_artifact = composite.get("artifact") if isinstance(composite.get("artifact"), Mapping) else {}
            candidate = composite_artifact.get("base_candidate_sha256")
            projection = composite_artifact.get("projection_id")
            if (
                composite_artifact.get("project_id") != project_id
                or composite_artifact.get("source_workspace_sha256") != source_hash
            ):
                raise _error("FINAL_CHARACTER_OVERLAY_BINDING_MISMATCH", "The current Composite overlay does not bind this project and source workspace.")
            _digest(candidate, field="candidate_sha256")
            _opaque(projection, field="projection ID")
            for component, validated in (("composite_controller", composite),):
                receipt = receipts[component]
                internal_tree = final_materializer._validated_overlay_internal_tree_hash(paths[component], validated, label=component)
                if (
                    validated.get("overlay_id") != receipt.get("overlay_id")
                    or validated.get("artifact_sha256") != receipt.get("artifact_sha256")
                    or internal_tree != receipt.get("overlay_tree_sha256")
                    or receipt.get("candidate_sha256") != candidate
                    or receipt.get("source_workspace_sha256") != source_hash
                ):
                    raise _error("FINAL_CHARACTER_COMPONENT_STALE", "A freshly validated overlay differs from its component receipt.")
            if receipts["composite_controller"].get("projection_id") != projection:
                raise _error("FINAL_CHARACTER_PROJECTION_BINDING_MISMATCH", "The Composite receipt differs from its current projection.")
            pointer_candidate = self._candidate_pointer(project_id)
            if pointer_candidate is not None and (
                pointer_candidate.get("candidate_sha256") not in (None, candidate)
                or pointer_candidate.get("projection_id") not in (None, projection)
            ):
                raise _error("FINAL_CHARACTER_CANDIDATE_BINDING_MISMATCH", "The current candidate pointer differs from the reviewed triplet.")
            binding = final_materializer._reviewed_binding_from_evidence(
                project_id=project_id,
                candidate_sha256=str(candidate),
                projection_id=str(projection),
                source_workspace_sha256=source_hash,
                composite_validated=composite,
                composite_overlay_files_tree_sha256=receipts["composite_controller"]["files_tree_sha256"],
                composite_overlay_root=paths["composite_controller"],
                constructed_immortal_arts=immortal_arts,
            )
            return {"receipts": receipts, "binding": binding}

    def preview_current_triplet(self, project_id: str) -> dict[str, Any]:
        project_id = _project_id(project_id)
        try:
            triplet = self._derive_triplet(project_id)
        except FoundryError as exc:
            if exc.code == "FINAL_CHARACTER_REVIEW_NOT_READY":
                return {
                    "schema_version": FINAL_CHARACTER_REVIEW_PREVIEW_SCHEMA,
                    "project_id": project_id,
                    "status": "NOT_READY",
                    "available": False,
                    "provider_calls": 0,
                    "details": deepcopy(exc.details),
                }
            raise
        return {
            "schema_version": FINAL_CHARACTER_REVIEW_PREVIEW_SCHEMA,
            "project_id": project_id,
            "status": "READY_FOR_OWNER_APPROVAL",
            "available": True,
            "provider_calls": 0,
            "binding": deepcopy(triplet["binding"]),
            "components": [self._public_receipt(triplet["receipts"][component]) for component in _COMPONENTS],
        }

    def _review_store_binding(self, *, create: bool) -> tuple[Path, tuple[int, int] | None]:
        workflow = self._workflow_root(create=create)
        binding = self._private_child(
            workflow,
            FINAL_CHARACTER_REVIEW_STORE_NAME,
            create=create,
            include_identity=True,
        )
        if not isinstance(binding, tuple):
            raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", "The review store binding did not return a directory identity.", status_code=500)
        _held_path, identity = binding
        logical_path = self._data_root_authority.path / FINAL_CHARACTER_WORKFLOW_ROOT_NAME / FINAL_CHARACTER_REVIEW_STORE_NAME
        return logical_path, identity

    def _ensure_review_store(self) -> Path:
        return self._review_store_binding(create=True)[0]

    @staticmethod
    def _public_challenge(project_id: str, issued: Mapping[str, Any]) -> dict[str, Any]:
        raw = issued.get("challenge")
        if not isinstance(raw, Mapping):
            raise _error("FINAL_CHARACTER_REVIEW_CHALLENGE_INVALID", "The approval challenge service returned no challenge envelope.", status_code=500)
        required = (
            "challenge_id",
            "challenge_hash",
            "operation",
            "subject_type",
            "subject_id",
            "exact_bytes_hash",
            "binding_hash",
            "project_lock_hash",
            "issued_at",
            "expires_at",
            "nonce",
        )
        if any(key not in raw for key in required):
            raise _error("FINAL_CHARACTER_REVIEW_CHALLENGE_INVALID", "The approval challenge service returned an incomplete challenge envelope.", status_code=500)
        challenge_id = _opaque(raw["challenge_id"], field="challenge ID")
        nonce = _challenge_nonce(raw["nonce"])
        hashes = {
            key: _digest(raw[key], field=key)
            for key in ("challenge_hash", "exact_bytes_hash", "binding_hash", "project_lock_hash")
        }
        return {
            "schema_version": FINAL_CHARACTER_REVIEW_CHALLENGE_SCHEMA,
            "project_id": project_id,
            "status": "ISSUED",
            "provider_calls": 0,
            "challenge": {
                "challenge_id": challenge_id,
                "challenge_hash": hashes["challenge_hash"],
                "operation": str(raw["operation"]),
                "subject_type": str(raw["subject_type"]),
                "subject_id": _opaque(raw["subject_id"], field="challenge subject ID"),
                "exact_bytes_hash": hashes["exact_bytes_hash"],
                "binding_hash": hashes["binding_hash"],
                "project_lock_hash": hashes["project_lock_hash"],
                "issued_at": str(raw["issued_at"]),
                "expires_at": str(raw["expires_at"]),
                "nonce": nonce,
            },
        }

    @staticmethod
    def _public_review_summary(
        project_id: str,
        record: Mapping[str, Any],
        *,
        challenge_id: str,
    ) -> dict[str, Any]:
        record_id = final_materializer._review_record_id(record.get("record_id"))
        record_sha256 = _digest(record.get("record_sha256"), field="record_sha256")
        binding_sha256 = _digest(record.get("binding_sha256"), field="binding_sha256")
        approval = record.get("approval")
        if not isinstance(approval, Mapping):
            raise _error("FINAL_CHARACTER_REVIEW_RECORD_INVALID", "The persisted review record has no approval summary.", status_code=500)
        evidence_id = _opaque(approval.get("evidence_id"), field="evidence ID")
        safe_challenge_id = _opaque(challenge_id, field="challenge ID")
        return {
            "schema_version": FINAL_CHARACTER_REVIEW_SUMMARY_SCHEMA,
            "project_id": project_id,
            "status": "APPROVED",
            "provider_calls": 0,
            "challenge_id": safe_challenge_id,
            "evidence_id": evidence_id,
            "review_record_id": record_id,
            "record_sha256": record_sha256,
            "binding_sha256": binding_sha256,
        }

    @staticmethod
    def _public_materialization_summary(
        project_id: str,
        review_record_id: str,
        binding: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        materialization_id = _opaque(result.get("materialization_id"), field="materialization ID")
        idempotent = result.get("idempotent") is True
        summary: dict[str, Any] = {
            "schema_version": FINAL_CHARACTER_MATERIALIZATION_SUMMARY_SCHEMA,
            "project_id": project_id,
            "status": "ALREADY_MATERIALIZED" if idempotent else "MATERIALIZED",
            "provider_calls": 0,
            "idempotent": idempotent,
            "review_record_id": final_materializer._review_record_id(review_record_id),
            "materialization_id": materialization_id,
            "binding_sha256": _digest(binding.get("binding_sha256"), field="binding_sha256"),
        }
        receipt = result.get("receipt")
        if isinstance(receipt, Mapping):
            output_tree = receipt.get("output_tree_sha256")
            if output_tree is not None:
                summary["output_tree_sha256"] = _digest(output_tree, field="output_tree_sha256")
        elif result.get("output_tree_sha256") is not None:
            summary["output_tree_sha256"] = _digest(result["output_tree_sha256"], field="output_tree_sha256")
        return summary

    def issue_review_challenge(self, project_id: str, ttl_seconds: int = 300) -> dict[str, Any]:
        """Issue one exact-byte owner challenge for the freshly derived triplet."""

        project_id = _project_id(project_id)
        if type(ttl_seconds) is not int:
            raise _error("APPROVAL_CHALLENGE_TTL_INVALID", "Challenge TTL must be an integer between 1 and 900 seconds.")
        if ttl_seconds < 1 or ttl_seconds > 900:
            raise _error("APPROVAL_CHALLENGE_TTL_INVALID", "Challenge TTL must be between 1 and 900 seconds.")
        triplet = self._derive_triplet(project_id)
        parameters = final_materializer._review_approval_parameters(triplet["binding"])
        # The context is evidence-only.  It must be checked on consumption,
        # but is intentionally not an input to challenge issuance.
        issue_parameters = {
            key: value
            for key, value in parameters.items()
            if key != "evidence_context"
        }
        self._ensure_review_store()
        issued = self.challenges.issue(ttl_seconds=ttl_seconds, **issue_parameters)
        return self._public_challenge(project_id, issued)

    def approve_current_triplet(self, project_id: str, challenge_id: str, nonce: str) -> dict[str, Any]:
        """Consume an exact current-triplet challenge and persist its review record."""

        project_id = _project_id(project_id)
        challenge_id = _opaque(challenge_id, field="challenge ID")
        nonce = _challenge_nonce(nonce)
        triplet = self._derive_triplet(project_id)
        parameters = final_materializer._review_approval_parameters(triplet["binding"])
        evidence = self.challenges.consume(
            challenge_id=challenge_id,
            nonce=nonce,
            operation=parameters["operation"],
            subject_type=parameters["subject_type"],
            subject_id=parameters["subject_id"],
            exact_bytes=parameters["exact_bytes"],
            binding=parameters["binding"],
            project_lock_hash=parameters["project_lock_hash"],
            evidence_context=parameters["evidence_context"],
        )
        if not isinstance(evidence, Mapping):
            raise _error("FINAL_CHARACTER_REVIEW_APPROVAL_INVALID", "Approval consumption returned no evidence envelope.", status_code=500)
        evidence_id = _opaque(evidence.get("evidence_id"), field="evidence ID")
        review_root, review_identity = self._review_store_binding(create=True)
        issuer = final_materializer.FinalCharacterReviewIssuer(
            review_root,
            self.db,
            self.integrity,
            triplet["binding"],
            expected_identity=review_identity,
            expected_present=True,
        )
        record = issuer.issue_from_evidence(evidence_id)
        return self._public_review_summary(project_id, record, challenge_id=challenge_id)

    def materialize_current_triplet(self, project_id: str, review_record_id: str) -> dict[str, Any]:
        """Materialize only a currently matching, persisted approved triplet."""

        project_id = _project_id(project_id)
        review_record_id = final_materializer._review_record_id(review_record_id)
        # The first derivation rejects stale or incomplete component state
        # before any output root is created.  A second derivation is made under
        # the project lock immediately before binding the held snapshots.
        self._derive_triplet(project_id)
        project_root = self._project_root(project_id, create=False)
        with self._locked(project_root):
            triplet = self._derive_triplet(project_id)
            review_root, review_identity = self._review_store_binding(create=False)
            authority = self._review_authority(
                review_root,
                expected_identity=review_identity,
                expected_present=review_identity is not None,
            )
            record = authority.load_record(review_record_id)
            if record.get("binding") != triplet["binding"] or record.get("binding", {}).get("project_id") != project_id:
                raise _error(
                    "FINAL_CHARACTER_REVIEW_BINDING_MISMATCH",
                    "The persisted review record does not authorize the current final-character triplet.",
                    details={"project_id": project_id, "review_record_id": review_record_id},
                    status_code=409,
                )
            with ExitStack() as stack:
                loaded: dict[str, tuple[dict[str, Any], Path]] = {}
                for component in _COMPONENTS:
                    receipt = triplet["receipts"][component]
                    receipt_id = str(receipt["receipt_id"])
                    loaded[component] = stack.enter_context(self._load_receipt(project_id, component, receipt_id))
                    if canonical_json(loaded[component][0]) != canonical_json(receipt):
                        raise _error(
                            "FINAL_CHARACTER_COMPONENT_CHANGED",
                            "A current component receipt changed while materialization was being prepared.",
                            details={"component": component},
                            status_code=409,
                        )
                current_pointer = self._load_pointer(project_id)
                if current_pointer.get("components") != {
                    component: triplet["receipts"][component]["receipt_id"]
                    for component in _COMPONENTS
                }:
                    raise _error(
                        "FINAL_CHARACTER_COMPONENT_CHANGED",
                        "The current component pointer changed while materialization was being prepared.",
                        status_code=409,
                    )
                source = loaded["command4"][1]
                composite = loaded["composite_controller"][1]
                materialization_binding = self._private_child(
                    project_root,
                    FINAL_CHARACTER_MATERIALIZATION_ROOT_NAME,
                    create=True,
                    include_identity=True,
                )
                if not isinstance(materialization_binding, tuple):
                    raise _error("FINAL_CHARACTER_WORKFLOW_STORE_INVALID", "The materialization root binding did not return a directory identity.", status_code=500)
                materialization_root, materialization_identity = materialization_binding
                # Keep the public materializer contract on the configured
                # logical path.  The root was created through the held data
                # descriptor above; the materializer binds that same path
                # with its own fixed-directory authority before writing.
                materialization_root = (
                    self.data_root
                    / FINAL_CHARACTER_WORKFLOW_ROOT_NAME
                    / project_id
                    / FINAL_CHARACTER_MATERIALIZATION_ROOT_NAME
                )
                result = final_materializer.FinalCharacterMaterializer(authority).materialize(
                    source,
                    composite,
                    materialization_root,
                    project_id=project_id,
                    candidate_sha256=triplet["binding"]["candidate_sha256"],
                    projection_id=triplet["binding"]["projection_id"],
                    review_record_id=review_record_id,
                    expected_output_root_identity=materialization_identity,
                    expected_output_root_present=True,
                )
                if not isinstance(result, Mapping):
                    raise _error("FINAL_CHARACTER_MATERIALIZATION_INVALID", "The final-character materializer returned no result.", status_code=500)
                return self._public_materialization_summary(project_id, review_record_id, triplet["binding"], result)

    status = preview_current_triplet


__all__ = [
    "FINAL_CHARACTER_COMPONENT_POINTER_SCHEMA",
    "FINAL_CHARACTER_COMPONENT_RECEIPT_SCHEMA",
    "FINAL_CHARACTER_REVIEW_PREVIEW_SCHEMA",
    "FINAL_CHARACTER_REVIEW_CHALLENGE_SCHEMA",
    "FINAL_CHARACTER_REVIEW_SUMMARY_SCHEMA",
    "FINAL_CHARACTER_MATERIALIZATION_SUMMARY_SCHEMA",
    "FINAL_CHARACTER_REVIEW_STORE_NAME",
    "FINAL_CHARACTER_MATERIALIZATION_ROOT_NAME",
    "FINAL_CHARACTER_WORKFLOW_ROOT_NAME",
    "FinalCharacterWorkflowService",
]
