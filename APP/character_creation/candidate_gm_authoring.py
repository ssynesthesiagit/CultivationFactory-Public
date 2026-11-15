"""Run-scoped, source-bound GM authoring for captured character candidates."""

from __future__ import annotations

import hashlib
import fcntl
import inspect
import json
import os
import re
import stat
import tempfile
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError, canonical_json, sha256_bytes, sha256_file, sha256_json
from character_creation.candidate_gm import CandidateGMCapsuleStore
from factory_authoring.service import FactoryAuthoringWorkspaceService
from factory_authoring.composite_controller import (
    CompositeControllerAuthoring,
    COMPOSITE_CONTROLLER_MAX_OUTPUT_TOKENS,
    _canonical_wire_bytes,
)
from factory_authoring.theme_contract import validate_gm_themes
from security.integrity import IntegrityService
from security.approval_challenges import ApprovalChallengeService


# Keep authoring records beside, rather than inside, the immutable capture
# namespace.  The capsule store owns ``character_creation_gm_candidates`` and
# its ``current.json`` pointer; reusing that directory would make the two
# authenticated pointers ambiguous.
_ROOT_NAME = "character_creation_gm_authoring"
_ENVELOPE_SCHEMA = "TianxiaFoundry.CharacterCreationCandidateGMAuthoring.v1"
_ATTEMPT_SCHEMA = "TianxiaFoundry.CharacterCreationCandidateGMAuthoringAttempt.v1"
_INTENT_SCHEMA = "TianxiaFoundry.CharacterCreationCandidateGMAuthoringIntent.v1"
_INTEGRITY_DOMAIN = "tianxia.foundry.character_creation.gm_candidate_authoring"
_INTENT_INTEGRITY_DOMAIN = "tianxia.foundry.character_creation.gm_candidate_authoring.intent"
_PENDING_STATUS = "CANDIDATE_GM_AUTHORING_READY_FOR_REVIEW"
_APPROVED_STATUS = "CANDIDATE_GM_AUTHORING_OWNER_APPROVED"
_GM_LOCAL_PROVIDER_IDS = frozenset({"local", "lemonade"})
# The agent bridge speaks the same provider contract, so a harness-held agent
# may author this artifact exactly as a local model does.  The local-only set
# above still governs local runtime identity checks.
_GM_AUTHORING_PROVIDER_IDS = _GM_LOCAL_PROVIDER_IDS | {"agent"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMPOSITE_GM_CONTRACT = "TianxiaFoundry.CandidateGMCompositeController.v1"
_CANDIDATE_APPROVAL_SCHEMA = "TianxiaFoundry.CharacterCreationCandidateGMApproval.v1"
_CANDIDATE_APPROVAL_POINTER_SCHEMA = "TianxiaFoundry.CharacterCreationCandidateGMApprovalPointer.v1"
_CANDIDATE_APPROVAL_OPERATION = "character_creation_candidate_gm_promote"
_CANDIDATE_APPROVAL_SUBJECT_TYPE = "character_creation_gm_candidate"
_CANDIDATE_APPROVAL_INTEGRITY_DOMAIN = "tianxia.foundry.character_creation.gm_candidate_approval"
_FACTORY_OWNER_DECISION_SCHEMA = "TianxiaFoundry.GMOwnerRatificationDecision.v1"
_FACTORY_DECISION_INTEGRITY_DOMAIN = "tianxia.foundry.gm_authoring.owner_decision"


class _CandidateScopedGMIO:
    """Descriptor-relative file access for one authenticated namespace."""

    _STORE_CHILDREN = (
        "sources", "requests", "responses", "artifacts", "profiles",
        "receipts", "decisions", "attempts", "envelopes", "approvals",
    )

    def __init__(self, root: Path, *, state_root: Path | None = None, parent: "_CandidateScopedGMIO" | None = None):
        self.root = Path(os.path.abspath(os.fspath(root)))
        self.state_root = Path(os.path.abspath(os.fspath(state_root or self.root)))
        self.parent = parent
        self._root_fd: int | None = None
        self._store = CandidateGMCapsuleStore.__new__(CandidateGMCapsuleStore)
        self._store.root = self.state_root
        if parent is not None:
            try:
                self._relative_from_parent = tuple(self.root.relative_to(parent.root).parts)
            except ValueError as exc:
                raise FoundryError(
                    "CG1_GM_CANDIDATE_AUTHORING_PATH_INVALID",
                    "The candidate GM namespace is outside its authenticated parent.",
                ) from exc
            self._namespace_parts: tuple[str, ...] = ()
        else:
            try:
                self._namespace_parts = tuple(self.root.relative_to(self.state_root).parts)
            except ValueError as exc:
                raise FoundryError(
                    "CG1_GM_CANDIDATE_AUTHORING_PATH_INVALID",
                    "The candidate GM namespace is outside the trusted state root.",
                ) from exc
            self._relative_from_parent = ()

    def _ensure_open(self, *, create: bool) -> int:
        if self._root_fd is not None:
            return self._root_fd
        if self.parent is not None:
            parent_fd = self.parent._open_root(create=create)
            try:
                self._root_fd = self._store._open_relative_dir(
                    parent_fd,
                    self._relative_from_parent,
                    create=create,
                    label="candidate GM namespace",
                )
            finally:
                os.close(parent_fd)
        else:
            # The state root is the sole path opened by name.  Every
            # candidate component below it is then descended with openat and
            # O_NOFOLLOW while the resulting capability remains held.
            self._root_fd = self._store._open_root_dir(create=False)
            if self._namespace_parts:
                state_fd = self._root_fd
                try:
                    self._root_fd = self._store._open_relative_dir(
                        state_fd,
                        self._namespace_parts,
                        create=create,
                        label="candidate GM namespace",
                    )
                finally:
                    os.close(state_fd)
        return self._root_fd

    def _open_root(self, *, create: bool) -> int:
        return os.dup(self._ensure_open(create=create))

    def open(self, *, create: bool = False) -> "_CandidateScopedGMIO":
        self._ensure_open(create=create)
        return self

    def close(self) -> None:
        if self._root_fd is not None:
            os.close(self._root_fd)
            self._root_fd = None

    def descendant(self, root: Path, *, create: bool) -> "_CandidateScopedGMIO":
        child = _CandidateScopedGMIO(root, state_root=self.state_root, parent=self)
        child.open(create=create)
        return child

    def __enter__(self) -> "_CandidateScopedGMIO":
        return self.open(create=False)

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()

    @contextmanager
    def exclusive_lock(self):
        root_fd = self._open_root(create=True)
        try:
            try:
                lock_fd = os.open(
                    ".author.lock",
                    os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=root_fd,
                )
            except OSError as exc:
                raise FoundryError(
                    "CG1_GM_CANDIDATE_AUTHORING_LOCK_FAILED",
                    "The candidate GM authoring lock could not be opened safely.",
                    details={"cause": type(exc).__name__},
                    status_code=500,
                ) from exc
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                yield
            finally:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)
        finally:
            os.close(root_fd)

    def ensure_namespace(self) -> None:
        root_fd = self._open_root(create=True)
        try:
            for name in self._STORE_CHILDREN:
                child_fd = self._store._open_relative_dir(
                    root_fd, (name,), create=True, label=f"candidate GM {name}",
                )
                os.close(child_fd)
        finally:
            os.close(root_fd)

    @staticmethod
    def _name(name: str) -> str:
        if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise FoundryError("CG1_GM_CANDIDATE_AUTHORING_PATH_INVALID", "The candidate GM authoring filename is invalid.")
        return name

    def _relative(self, path: Path, *, allow_root: bool = False) -> tuple[str, ...]:
        path = Path(os.path.abspath(os.fspath(path)))
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise FoundryError(
                "CG1_GM_CANDIDATE_AUTHORING_PATH_INVALID",
                "The candidate GM authoring path is outside its authenticated namespace.",
            ) from exc
        parts = tuple(relative.parts)
        if (not parts and not allow_root) or any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in parts):
            raise FoundryError("CG1_GM_CANDIDATE_AUTHORING_PATH_INVALID", "The candidate GM authoring path is invalid.")
        return parts

    def read_bytes(self, path: Path) -> bytes:
        parts = self._relative(path)
        root_fd = self._open_root(create=False)
        parent_fd = self._store._open_relative_dir(
            root_fd, parts[:-1], create=False, label="candidate GM file parent",
        )
        try:
            return self._store._read_regular_at(parent_fd, parts[-1], label="candidate GM file")
        finally:
            os.close(parent_fd)
            os.close(root_fd)

    def read_json(self, path: Path, *, code: str) -> dict[str, Any]:
        try:
            raw = self.read_bytes(path)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("file too large")
            value = json.loads(raw.decode("utf-8"))
        except FoundryError:
            raise
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise FoundryError(
                code,
                "The server-owned GM authoring artifact is missing or invalid.",
                details={"path": Path(path).name},
            ) from exc
        if not isinstance(value, dict):
            raise FoundryError(code, "The server-owned GM authoring artifact must be one JSON object.")
        return value

    def write_immutable(self, root: Path, name: str, payload: bytes) -> tuple[Path, str]:
        name = self._name(name)
        root_fd = self._open_dir(root, create=True)
        try:
            self._store._write_immutable_at(root_fd, name, payload, label="candidate GM artifact")
        finally:
            os.close(root_fd)
        return Path(root) / name, sha256_bytes(payload)

    def write_pointer(self, path: Path, payload: bytes) -> None:
        name = self._name(Path(path).name)
        root_fd = self._open_dir(Path(path).parent, create=True)
        try:
            self._store._write_pointer_at(root_fd, name, payload)
        finally:
            os.close(root_fd)

    def _open_dir(self, path: Path, *, create: bool) -> int:
        parts = self._relative(path, allow_root=True)
        root_fd = self._open_root(create=create)
        try:
            return self._store._open_relative_dir(
                root_fd,
                parts,
                create=create,
                label="candidate GM file parent",
            )
        finally:
            os.close(root_fd)


class _CandidateFactoryAuthoringWorkspaceService(FactoryAuthoringWorkspaceService):
    """Factory authoring validator backed by descriptor-relative candidate IO."""

    def __init__(
        self,
        db: Any,
        integrity: IntegrityService,
        root: Path,
        *,
        parent_io: _CandidateScopedGMIO | None = None,
    ):
        self.db = db
        self.integrity = integrity
        self._candidate_gm_root = Path(os.path.abspath(os.fspath(root)))
        self._candidate_io = _CandidateScopedGMIO(
            self._candidate_gm_root,
            state_root=Path(db.settings.data_dir),
            parent=parent_io,
        )
        self._candidate_io.ensure_namespace()

    def close(self) -> None:
        self._candidate_io.close()

    def _gm_root(self, _project_id: str) -> Path:
        return self._candidate_gm_root

    def _gm_pointer_exists(self, path: Path) -> bool:
        try:
            self._candidate_io.read_bytes(path)
        except FoundryError as exc:
            if exc.code == "CG1_GM_CANDIDATE_PAYLOAD_MISSING":
                return False
            raise
        return True

    def _gm_read_json(self, path: Path, *, code: str = "GM_AUTHORING_ARTIFACT_INVALID") -> dict[str, Any]:
        return self._candidate_io.read_json(path, code=code)

    def _gm_write_immutable_json(self, root: Path, name: str, value: Mapping[str, Any]) -> tuple[Path, str]:
        payload = self._gm_json_bytes(value)
        return self._candidate_io.write_immutable(root, name, payload)

    def _gm_write_pointer(self, path: Path, value: Mapping[str, Any]) -> None:
        self._candidate_io.write_pointer(path, self._gm_json_bytes(value))

    def _gm_file_hash(self, path: Path, expected: str, *, label: str) -> str:
        if not isinstance(expected, str) or _SHA256_RE.fullmatch(expected) is None:
            raise FoundryError("GM_AUTHORING_ARTIFACT_BINDING_INVALID", f"The {label} hash is malformed.")
        try:
            actual = sha256_bytes(self._candidate_io.read_bytes(path))
        except FoundryError as exc:
            raise FoundryError("GM_AUTHORING_ARTIFACT_MISSING", f"The server-owned {label} is missing.", details={"path": Path(path).name}) from exc
        if actual != expected:
            raise FoundryError(
                "GM_AUTHORING_ARTIFACT_STALE",
                f"The server-owned {label} changed after authoring.",
                details={"expected": expected, "actual": actual},
            )
        return actual

    def _load_gm_authoring(self, project_id: str, *, project_revision: int | None = None, snapshot: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        """Let the base verifier keep its contract while making pointer absence safe."""
        pointer = self._candidate_gm_root / "current.json"
        try:
            self._candidate_io.read_bytes(pointer)
        except FoundryError as exc:
            if exc.code == "CG1_GM_CANDIDATE_PAYLOAD_MISSING":
                return None
            raise
        loaded = super()._load_gm_authoring(
            project_id,
            project_revision=project_revision,
            snapshot=snapshot,
        )
        if loaded is not None and (loaded.get("binding") or {}).get("authoring_contract") != _COMPOSITE_GM_CONTRACT:
            # Historical free-prose receipts remain immutable evidence, but
            # cannot satisfy the closed-choice candidate authoring contract.
            return {"legacy_contract": True}
        return loaded


class CandidateGMAuthoringService:
    """Author and review one captured candidate without touching live GM state."""

    def __init__(
        self,
        db: Any,
        *,
        provider: Any | None = None,
        capsule_store: CandidateGMCapsuleStore | None = None,
        integrity: IntegrityService | None = None,
    ):
        self.db = db
        self.provider = provider
        self.capsules = capsule_store or CandidateGMCapsuleStore(db)
        self.integrity = integrity or IntegrityService.for_database(db)
        self._io_local = threading.local()

    @staticmethod
    def _run_key(run_id: str) -> str:
        return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:32]

    def _root(self, run_id: str) -> Path:
        return (
            Path(os.path.abspath(os.fspath(self.db.settings.data_dir)))
            / _ROOT_NAME / "runs" / self._run_key(run_id)
        )

    @contextmanager
    def _run_scope(self, run_id: str):
        io = _CandidateScopedGMIO(
            self._root(run_id),
            state_root=Path(self.db.settings.data_dir),
        )
        io.open(create=True)
        previous = getattr(self._io_local, "run_io", None)
        self._io_local.run_io = io
        try:
            yield io
        finally:
            if previous is None:
                try:
                    del self._io_local.run_io
                except AttributeError:
                    pass
            else:
                self._io_local.run_io = previous
            io.close()

    def _io_for_path(self, path: Path, *, create: bool) -> _CandidateScopedGMIO:
        active = getattr(self._io_local, "run_io", None)
        if active is not None:
            active._relative(path, allow_root=True)
            return active
        run_base = Path(self.db.settings.data_dir) / _ROOT_NAME / "runs"
        try:
            relative = Path(os.path.abspath(os.fspath(path))).relative_to(run_base)
        except ValueError as exc:
            self._fail(
                "CG1_GM_CANDIDATE_AUTHORING_PATH_INVALID",
                "The candidate GM authoring path is outside its run namespace.",
            )
            raise AssertionError from exc
        if not relative.parts:
            self._fail("CG1_GM_CANDIDATE_AUTHORING_PATH_INVALID", "The candidate GM authoring run is missing.")
        io = _CandidateScopedGMIO(
            run_base / relative.parts[0],
            state_root=Path(self.db.settings.data_dir),
        )
        io.open(create=create)
        return io

    @staticmethod
    def _fail(code: str, message: str, *, details: Any = None, status_code: int = 409) -> None:
        raise FoundryError(code, message, details=details, status_code=status_code)

    @classmethod
    def _ensure_dir(cls, path: Path, *, create: bool) -> bool:
        """Create/check every ancestor without following a symlink."""
        path = Path(os.path.abspath(os.fspath(path)))
        parts = path.parts
        current = Path(parts[0])
        for part in parts[1:]:
            current /= part
            try:
                mode = os.lstat(current).st_mode
            except FileNotFoundError:
                if not create:
                    return False
                try:
                    os.mkdir(current, 0o700)
                except FileExistsError:
                    pass
                except OSError as exc:
                    cls._fail(
                        "CG1_GM_CANDIDATE_AUTHORING_PATH_INVALID",
                        "The candidate GM authoring directory could not be created safely.",
                        details={"cause": type(exc).__name__},
                        status_code=500,
                    )
                mode = os.lstat(current).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                cls._fail(
                    "CG1_GM_CANDIDATE_AUTHORING_PATH_INVALID",
                    "The candidate GM authoring namespace contains an unsafe ancestor.",
                )
        return True

    @classmethod
    def _assert_file_path(cls, path: Path, *, code: str) -> None:
        path = Path(os.path.abspath(os.fspath(path)))
        cls._ensure_dir(path.parent, create=False)
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            cls._fail(code, "The candidate GM authoring file is missing.")
        except OSError as exc:
            cls._fail(code, "The candidate GM authoring file cannot be inspected safely.", details={"cause": type(exc).__name__})
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            cls._fail("CG1_GM_CANDIDATE_AUTHORING_PATH_INVALID", "The candidate GM authoring file is not a regular file.")

    @staticmethod
    def _json_bytes(value: Mapping[str, Any]) -> bytes:
        return (canonical_json(dict(value)) + "\n").encode("utf-8")

    def _write_immutable(self, root: Path, name: str, value: Mapping[str, Any]) -> tuple[Path, str]:
        try:
            io = self._io_for_path(root, create=True)
            return io.write_immutable(root, name, self._json_bytes(value))
        except FoundryError:
            raise
        except OSError as exc:
            self._fail(
                "CG1_GM_CANDIDATE_AUTHORING_WRITE_FAILED",
                "The candidate GM authoring file could not be persisted safely.",
                details={"cause": type(exc).__name__},
                status_code=500,
            )

    def _write_pointer(self, path: Path, value: Mapping[str, Any]) -> None:
        try:
            io = self._io_for_path(Path(path).parent, create=True)
            io.write_pointer(path, self._json_bytes(value))
        except FoundryError:
            raise
        except OSError as exc:
            self._fail(
                "CG1_GM_CANDIDATE_AUTHORING_WRITE_FAILED",
                "The candidate GM authoring pointer could not be persisted safely.",
                details={"cause": type(exc).__name__},
                status_code=500,
            )

    def _read_bytes(self, path: Path, *, code: str) -> bytes:
        try:
            io = self._io_for_path(Path(path).parent, create=False)
            raw = io.read_bytes(path)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("file too large")
            return raw
        except FoundryError as exc:
            if exc.code == "CG1_GM_CANDIDATE_PAYLOAD_MISSING":
                self._fail(code, "The candidate GM authoring file is missing.")
            raise
        except (OSError, ValueError) as exc:
            self._fail(code, "The candidate GM authoring file is malformed.", details={"cause": type(exc).__name__})

    def _read_json(self, path: Path, *, code: str) -> dict[str, Any]:
        try:
            value = json.loads(self._read_bytes(path, code=code).decode("utf-8"))
        except FoundryError:
            raise
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            self._fail(code, "The candidate GM authoring file is malformed.", details={"cause": type(exc).__name__})
        if not isinstance(value, dict):
            self._fail(code, "The candidate GM authoring file must contain one object.")
        return value

    @classmethod
    def _context_parts(cls, capsule: Mapping[str, Any]) -> dict[str, Any]:
        context = capsule.get("context")
        summary = capsule.get("summary")
        source = capsule.get("selected_record_source")
        if not isinstance(context, Mapping) or not isinstance(summary, Mapping) or not isinstance(source, Mapping):
            cls._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured GM candidate context is incomplete.")
        if context.get("status") != "CANDIDATE_CONTEXT_CAPTURED":
            cls._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured GM candidate context is not in its authenticated captured state.")
        if context.get("context_sha256") != summary.get("context_sha256") or context.get("run_id") != summary.get("run_id"):
            cls._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured GM candidate context identity is inconsistent.")
        if sha256_json(source) != context.get("source", {}).get("source_snapshot_sha256"):
            cls._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured selected-record source does not match its context hash.")
        snapshot = source.get("snapshot")
        records = snapshot.get("records") if isinstance(snapshot, Mapping) else None
        if not isinstance(records, list) or not records:
            cls._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured selected-record source has no usable records.")
        selected_snapshot: dict[str, Any] = {"selected_record_sections": {}}
        for row in records:
            if not isinstance(row, Mapping) or not isinstance(row.get("record"), Mapping):
                cls._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured selected-record source contains a malformed record.")
            section = str(row.get("section") or "selected_records")
            selected_snapshot["selected_record_sections"].setdefault(section, []).append(deepcopy(dict(row["record"])))
        record_ids: list[str] = []
        for row in records:
            record_id = row["record"].get("record_id")
            if not isinstance(record_id, str) or not record_id:
                cls._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured selected-record source contains an invalid record ID.")
            record_ids.append(record_id)
        if record_ids != source.get("snapshot", {}).get("record_ids") or record_ids != context.get("source", {}).get("record_ids"):
            cls._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured selected-record index is inconsistent.")
        return {
            "context": deepcopy(dict(context)),
            "capsule_id": summary.get("capsule_id"),
            "project_id": context.get("project_id"),
            "project_revision": context.get("candidate_project", {}).get("project_revision"),
            "candidate": deepcopy(dict(capsule.get("candidate_project") or {})),
            "owner_sheet": deepcopy(dict(capsule.get("owner_character_sheet") or {})),
            "source": deepcopy(dict(source)),
            "factory_workspace": deepcopy(dict(context.get("factory_workspace"))) if isinstance(context.get("factory_workspace"), Mapping) else None,
            "snapshot": selected_snapshot,
            "records": deepcopy(records),
            "record_ids": record_ids,
        }

    def _capsule(self, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        capsule = self.capsules.load(run_id)
        parts = self._context_parts(capsule)
        if parts["context"].get("run_id") != run_id:
            self._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured GM candidate belongs to another run.")
        return capsule, parts

    def _factory_store(self, run_id: str, capsule_id: str | None = None) -> FactoryAuthoringWorkspaceService:
        root = self._root(run_id) / "gm"
        if capsule_id is not None:
            if not re.fullmatch(r"cg1\.gm\.capsule\.[0-9a-f]{64}", capsule_id):
                self._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured capsule identity is malformed.")
            root = self._root(run_id) / "contexts" / capsule_id / "gm"
        parent_io = getattr(self._io_local, "run_io", None)
        return _CandidateFactoryAuthoringWorkspaceService(
            self.db,
            self.integrity,
            root,
            parent_io=parent_io,
        )

    @staticmethod
    def _candidate_workspace_binding(parts: Mapping[str, Any]) -> str:
        context = parts["context"]
        workspace = context.get("factory_workspace")
        candidate = context.get("candidate_project")
        if not isinstance(workspace, Mapping) or not isinstance(candidate, Mapping):
            raise FoundryError(
                "CG1_GM_CANDIDATE_WORKSPACE_MISSING",
                "The captured candidate has no authenticated Factory workspace.",
            )
        metadata = candidate
        value = sha256_json({
            "project_id": context.get("project_id"),
            "project_revision": workspace.get("project_revision"),
            "candidate_project_hash": metadata.get("canonical_project_hash"),
            "workspace_sha256": workspace.get("workspace_sha256"),
            "manifest_sha256": workspace.get("manifest_sha256"),
        })
        if workspace.get("candidate_binding_sha256") not in {None, value}:
            raise FoundryError(
                "CG1_GM_CANDIDATE_WORKSPACE_BINDING_INVALID",
                "The Factory workspace candidate binding does not reproduce from the capsule.",
            )
        return value

    @contextmanager
    def _prepared_composite(self, parts: Mapping[str, Any]):
        workspace = parts["context"].get("factory_workspace")
        if not isinstance(workspace, Mapping):
            self._fail(
                "CG1_GM_CANDIDATE_WORKSPACE_MISSING",
                "The candidate capsule has no retained Factory workspace; explicit reauthoring is required.",
            )
        with tempfile.TemporaryDirectory(prefix="cg1-gm-workspace-", dir="/var/tmp") as temporary:
            materialized = self.capsules.materialize_factory_workspace(
                parts["context"]["run_id"], Path(temporary),
            )
            for key in ("project_id", "project_revision", "workspace_sha256", "manifest_sha256"):
                if materialized.get(key) != workspace.get(key):
                    self._fail(
                        "CG1_GM_CANDIDATE_WORKSPACE_BINDING_INVALID",
                        "The materialized Factory workspace does not reproduce the captured binding.",
                        details={"field": key},
                    )
            candidate_sha256 = self._candidate_workspace_binding(parts)
            controller = CompositeControllerAuthoring(
                workspace_root=Path(temporary),
                candidate_sha256=candidate_sha256,
                projection_id=parts["context"]["projection"]["projection_id"],
            )
            prepare = controller.prepare
            try:
                accepts_theme_records = "theme_records" in inspect.signature(prepare).parameters
            except (TypeError, ValueError):
                accepts_theme_records = True
            if accepts_theme_records:
                extra = {"allow_theme_only": True} if "allow_theme_only" in inspect.signature(prepare).parameters else {}
                prepared = prepare(
                    parts["project_id"],
                    theme_records=deepcopy(list(parts.get("records") or [])),
                    **extra,
                )
            else:
                # Keep compatibility with an older test or integration seam
                # that wraps the method without the optional source projection.
                prepared = prepare(parts["project_id"])
            if (
                prepared.get("workspace_sha256") != workspace.get("workspace_sha256")
                or prepared.get("candidate_sha256") != candidate_sha256
                or prepared.get("projection_id") != parts["context"]["projection"]["projection_id"]
            ):
                self._fail(
                    "CG1_GM_CANDIDATE_WORKSPACE_BINDING_INVALID",
                    "Composite controller preparation is not bound to the captured workspace.",
                )
            yield prepared

    @staticmethod
    def _server_action(action: Mapping[str, Any]) -> dict[str, Any]:
        allowed = (
            "action_id", "record_id", "name", "display_name", "action_type", "economy", "bucket",
            "timing", "cost", "range", "target", "area", "roll_save_check", "effect", "failure",
            "duration", "limit", "counterplay", "resource_costs", "resource_gains",
            "resource_requirements", "requires_states", "required_states", "state_requirements",
            "required_state_ids", "states", "state_arrays", "requirements", "full_description",
            "description", "readiness", "classification",
        )
        return {key: deepcopy(action[key]) for key in allowed if key in action}

    @classmethod
    def _server_controller_guidance(
        cls,
        prepared: Mapping[str, Any],
        validated: Mapping[str, Any],
        *,
        selected_record_ids: list[str],
    ) -> dict[str, Any]:
        controller = validated.get("composite_controller")
        actions = prepared.get("token_to_action")
        if not isinstance(controller, Mapping) or not isinstance(actions, Mapping):
            raise FoundryError("GM_AUTHORING_CONTROLLER_INVALID", "The validated controller authority is incomplete.")

        def action_for(token: Any) -> dict[str, Any]:
            if not isinstance(token, str) or not isinstance(actions.get(token), Mapping):
                raise FoundryError("GM_AUTHORING_CONTROLLER_INVALID", "The validated controller references an unknown action token.")
            return cls._server_action(actions[token])

        def condition_for(action: Mapping[str, Any]) -> dict[str, Any]:
            return {
                key: deepcopy(action[key])
                for key in (
                    "economy", "timing", "range", "target", "area", "roll_save_check", "resource_costs",
                    "resource_requirements", "required_states", "requirements", "duration", "limit",
                )
                if key in action
            }

        sequence: list[dict[str, Any]] = []
        for row in controller.get("sequence") or []:
            token = row.get("action_token") if isinstance(row, Mapping) else None
            action = action_for(token)
            sequence.append({
                "step": row.get("step"),
                "action_token": token,
                "action_id": action.get("action_id"),
                "record_id": action.get("record_id"),
                "economy": action.get("economy"),
                "round_offset": row.get("round_offset"),
                "conditions": {
                    **condition_for(action),
                    "requires_states": deepcopy(row.get("requires_states") or []),
                },
            })
        fallback = controller.get("fallback")
        fallback_token = fallback.get("action_token") if isinstance(fallback, Mapping) else None
        fallback_action = action_for(fallback_token)
        conditional: list[dict[str, Any]] = []
        for row in controller.get("conditional_options") or []:
            token = row.get("action_token") if isinstance(row, Mapping) else None
            action = action_for(token)
            conditional.append({
                "action_token": token,
                "action_id": action.get("action_id"),
                "record_id": action.get("record_id"),
                "priority": row.get("priority"),
                "conditions": condition_for(action),
            })
        linked_tokens = {
            row["action_token"] for row in sequence
        }
        linked_tokens.add(fallback_token)
        linked_tokens.update(row["action_token"] for row in conditional)
        linked_actions = [action_for(token) for token in sorted(linked_tokens)]
        resource = prepared.get("resource")
        return {
            "schema": "TianxiaFoundry.ServerDerivedCompositeGuidance.v1",
            "classification": "GM_GUIDANCE_ONLY",
            "execution_authority": False,
            "controller_policy_registered": False,
            "source_workspace_sha256": prepared.get("workspace_sha256"),
            "candidate_sha256": prepared.get("candidate_sha256"),
            "projection_id": prepared.get("projection_id"),
            "source_record_ids": list(selected_record_ids),
            "source_record_coverage": "All selected records remain descriptive source context; only the linked sealed action packets below are legal plan options.",
            "resource_authority": deepcopy(dict(resource)) if isinstance(resource, Mapping) else None,
            "resource_budget": deepcopy(dict(controller.get("resource_budget") or {})),
            "sequence": sequence,
            "fallback": {
                "action_token": fallback_token,
                "action_id": fallback_action.get("action_id"),
                "record_id": fallback_action.get("record_id"),
                "conditions": condition_for(fallback_action),
            },
            "conditional_options": conditional,
            "linked_actions": linked_actions,
            "model_text_admitted": False,
        }

    @classmethod
    def _server_theme_only_response(
        cls,
        validated: Mapping[str, Any],
        *,
        selected_record_ids: list[str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Dao and I Ching without a combat plan (too few executable actions)."""
        selected = list(selected_record_ids)
        themes = validate_gm_themes(validated.get("gm_themes"), selected)
        response = {
            "dao": deepcopy(themes["dao"]),
            "i_ching": deepcopy(themes["i_ching"]),
            "gm_themes": deepcopy(themes),
        }
        return response, {"gm_themes": deepcopy(themes), "gm_theme_source_record_ids": selected}

    @classmethod
    def _server_response(
        cls,
        prepared: Mapping[str, Any],
        validated: Mapping[str, Any],
        *,
        selected_record_ids: list[str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if prepared.get("theme_only") is True:
            return cls._server_theme_only_response(validated, selected_record_ids=selected_record_ids)
        guidance = cls._server_controller_guidance(
            prepared, validated, selected_record_ids=selected_record_ids,
        )
        selected = list(selected_record_ids)

        def fallback_theme(kind: str) -> dict[str, Any]:
            source_names = [
                str(row.get("display_name"))
                for row in (prepared.get("theme_sources") or [])
                if isinstance(row, Mapping) and row.get("display_name")
            ]
            source_label = ", ".join(source_names[:3]) or "the selected source records"
            return {
                "display_name": f"{kind} of {source_label}",
                "core_theme": f"A descriptive {kind} reading grounded in {source_label}.",
                "principles": ["Keep the selected source meanings intact.", "Separate descriptive guidance from executable rules."],
                "strengths": ["The source context is explicit.", "Server-owned conditions remain inspectable."],
                "risks": ["Narrative guidance can be overread.", "Unselected source claims remain outside this theme."],
                "roleplay_expression": f"Express the character through the selected {kind} source context.",
                "tactical_expression": "Use this as display guidance; resolve every action through the sealed controller.",
                "gm_usage_notes": "This descriptive layer grants no mechanic, cost, bonus, action, or effect.",
                "relevant_record_ids": selected,
                "mechanical_effects": [],
            }

        themes = validated.get("gm_themes")
        if isinstance(themes, Mapping):
            themes = validate_gm_themes(themes, selected)
        else:
            if prepared.get("theme_record_ids"):
                cls._fail(
                    "GM_AUTHORING_THEME_REQUIRED",
                    "A source-bound candidate GM response must include its descriptive themes.",
                )
            themes = {"dao": fallback_theme("Dao"), "i_ching": fallback_theme("I Ching")}
        response = {
            "dao": deepcopy(themes["dao"]),
            "i_ching": deepcopy(themes["i_ching"]),
            "gm_themes": deepcopy(themes),
        }
        return response, {
            "server_validated_controller": guidance,
            "gm_themes": deepcopy(themes),
            "gm_theme_source_record_ids": selected,
        }

    def _intent_root(self, parts: Mapping[str, Any]) -> Path:
        capsule_id = parts["capsule_id"]
        if not isinstance(capsule_id, str) or not re.fullmatch(r"cg1\.gm\.capsule\.[0-9a-f]{64}", capsule_id):
            self._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID", "The captured capsule identity is malformed.")
        return self._root(parts["context"]["run_id"]) / "contexts" / capsule_id / "binding"

    def _intent_unsigned(self, parts: Mapping[str, Any]) -> dict[str, Any]:
        context = parts["context"]
        return {
            "schema_version": _INTENT_SCHEMA,
            "run_id": context["run_id"],
            "capsule_id": parts["capsule_id"],
            "context_sha256": context["context_sha256"],
            "project_id": parts["project_id"],
            "project_revision": int(parts["project_revision"]),
            "source_snapshot_sha256": context["source"]["source_snapshot_sha256"],
            "selected_record_content_sha256": context["source"]["selected_record_content_sha256"],
        }

    def _write_intent(self, parts: Mapping[str, Any]) -> None:
        unsigned = self._intent_unsigned(parts)
        value = {
            **unsigned,
            "integrity": self.integrity.sign(_INTENT_INTEGRITY_DOMAIN, unsigned).as_dict(),
        }
        self._write_immutable(self._intent_root(parts), "intent.json", value)

    def _load_intent(self, parts: Mapping[str, Any]) -> dict[str, Any] | None:
        path = self._intent_root(parts) / "intent.json"
        try:
            value = self._io_for_path(path.parent, create=False).read_json(
                path, code="CG1_GM_CANDIDATE_AUTHORING_INTENT_INVALID",
            )
        except FoundryError as exc:
            if exc.code == "CG1_GM_CANDIDATE_PAYLOAD_MISSING":
                return None
            raise
        unsigned = {key: item for key, item in value.items() if key != "integrity"}
        self.integrity.verify(_INTENT_INTEGRITY_DOMAIN, unsigned, value.get("integrity") or {})
        if unsigned != self._intent_unsigned(parts):
            self._fail("CG1_GM_CANDIDATE_AUTHORING_CONTEXT_STALE", "The authenticated base authoring intent belongs to another candidate context.")
        return value

    @staticmethod
    def _base_identity(binding: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(binding.get(key))
            for key in (
                "project_id", "project_revision", "receipt_id", "receipt_sha256",
                "artifact_sha256", "profile_sha256", "request_sha256", "response_sha256",
                "source_snapshot_sha256", "selected_record_content_sha256", "provider_id",
                "model", "provider_request_sha256", "provider_response_sha256",
                "owner_ratified", "owner_decision_id",
            )
        }

    def _expected_envelope(self, parts: Mapping[str, Any], base_binding: Mapping[str, Any]) -> dict[str, Any]:
        context = parts["context"]
        return {
            "schema_version": _ENVELOPE_SCHEMA,
            "status": _PENDING_STATUS,
            "run_id": context["run_id"],
            "capsule_id": parts["capsule_id"],
            "context_sha256": context["context_sha256"],
            "root_project": deepcopy(context["root_project"]),
            "candidate_project": deepcopy(context["candidate_project"]),
            "projection": deepcopy(context["projection"]),
            "sheet": deepcopy(context["sheet"]),
            "source": deepcopy(context["source"]),
            "mechanics": deepcopy(context["mechanics"]),
            "final_plan_sha256": context.get("final_plan_sha256"),
            "base_gm": self._base_identity(base_binding),
            "owner_ratified": False,
            "eligible_for_later_command5_checkpoint": False,
        }

    def _public(self, loaded: Mapping[str, Any], *, provider_calls: int) -> dict[str, Any]:
        binding = loaded["envelope"]["base_gm"]
        result = {
            "status": _PENDING_STATUS,
            "run_id": loaded["envelope"]["run_id"],
            "capsule_id": loaded["envelope"]["capsule_id"],
            "context_sha256": loaded["envelope"]["context_sha256"],
            "provider_calls": provider_calls,
            "provider_id": binding.get("provider_id"),
            "model": binding.get("model"),
            "receipt_id": binding.get("receipt_id"),
            "receipt_sha256": binding.get("receipt_sha256"),
            "artifact_sha256": binding.get("artifact_sha256"),
            "profile_sha256": binding.get("profile_sha256"),
            "source_snapshot_sha256": binding.get("source_snapshot_sha256"),
            "selected_record_content_sha256": binding.get("selected_record_content_sha256"),
            "capsule_source_snapshot_sha256": loaded["envelope"]["source"]["source_snapshot_sha256"],
            "gm_authoring": "ACTUAL_GM_AUTHORING_PENDING_OWNER_RATIFICATION",
            "owner_ratified": False,
            "eligible_for_later_command5_checkpoint": False,
            "provider_free_review": True,
            "provider_free_build_available": True,
            "profile": deepcopy(loaded["base"]["profile"]),
            "workspace_profile": deepcopy(loaded["base"]["workspace_profile"]),
        }
        candidate_approval = loaded.get("candidate_approval")
        approval = candidate_approval.get("approval") if isinstance(candidate_approval, Mapping) else None
        if isinstance(approval, Mapping):
            result.update({
                "status": _APPROVED_STATUS,
                "gm_authoring": "ACTUAL_GM_AUTHORING_OWNER_APPROVED",
                "owner_ratified": True,
                "eligible_for_later_command5_checkpoint": True,
                "candidate_approval_id": approval.get("approval_id"),
                "candidate_approval_evidence_id": approval.get("approval_evidence_id"),
            })
        return result

    def _verify_stale_pointer_transition(
        self,
        parts: Mapping[str, Any],
        pointer: Mapping[str, Any],
    ) -> None:
        """Accept only a verified same-run pointer transition during authoring."""
        run_id = parts["context"]["run_id"]
        capsule_id = pointer.get("capsule_id")
        if (
            pointer.get("run_id") != run_id
            or capsule_id == parts["capsule_id"]
            or not isinstance(capsule_id, str)
            or not re.fullmatch(r"cg1\.gm\.capsule\.[0-9a-f]{64}", capsule_id)
            or not _SHA256_RE.fullmatch(str(pointer.get("context_sha256") or ""))
            or not _SHA256_RE.fullmatch(str(pointer.get("envelope_sha256") or ""))
            or not _SHA256_RE.fullmatch(str(pointer.get("envelope_file_sha256") or ""))
        ):
            self._fail(
                "CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE",
                "The candidate GM authoring pointer is not a valid same-run transition.",
            )
        try:
            _manifest, payloads = self.capsules._read_capsule_payloads_for_id(run_id, capsule_id)
            context_raw = payloads["context.json"]
            source_raw = payloads["source/selected_record_source.json"]
            context = json.loads(context_raw.decode("utf-8"))
            source = json.loads(source_raw.decode("utf-8"))
            if (
                not isinstance(context, dict)
                or not isinstance(source, dict)
                or context.get("run_id") != run_id
                or context.get("capsule_id") not in {None, capsule_id}
                or context.get("context_sha256") != pointer.get("context_sha256")
                or sha256_json({key: value for key, value in context.items() if key != "context_sha256"}) != context.get("context_sha256")
                or canonical_json(source).encode("utf-8") not in {source_raw, source_raw.rstrip(b"\n")}
            ):
                raise FoundryError(
                    "CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID",
                    "The historical capsule context is not bound to its pointer.",
                )
            old_parts = self._context_parts({
                "context": context,
                "summary": {"run_id": run_id, "capsule_id": capsule_id, "context_sha256": context["context_sha256"]},
                "selected_record_source": source,
            })
            if old_parts["capsule_id"] != capsule_id:
                raise FoundryError(
                    "CG1_GM_CANDIDATE_AUTHORING_CONTEXT_INVALID",
                    "The historical capsule summary is not bound to its pointer.",
                )

            root = self._root(run_id)
            envelope_path = root / "envelopes" / f"envelope.{pointer['envelope_sha256']}.json"
            envelope_raw = self._read_bytes(
                envelope_path, code="CG1_GM_CANDIDATE_AUTHORING_ENVELOPE_MISSING",
            )
            if sha256_bytes(envelope_raw) != pointer["envelope_file_sha256"]:
                raise FoundryError(
                    "CG1_GM_CANDIDATE_AUTHORING_ENVELOPE_TAMPERED",
                    "The historical authoring envelope bytes changed.",
                )
            envelope = json.loads(envelope_raw.decode("utf-8"))
            if (
                not isinstance(envelope, dict)
                or sha256_json(envelope) != pointer["envelope_sha256"]
                or envelope.get("schema_version") != _ENVELOPE_SCHEMA
                or envelope.get("status") != _PENDING_STATUS
            ):
                raise FoundryError(
                    "CG1_GM_CANDIDATE_AUTHORING_ENVELOPE_INVALID",
                    "The historical authoring envelope is invalid.",
                )
            envelope_unsigned = {key: value for key, value in envelope.items() if key != "integrity"}
            self.integrity.verify(_INTEGRITY_DOMAIN, envelope_unsigned, envelope.get("integrity") or {})
            if (
                envelope_unsigned != self._expected_envelope(old_parts, envelope.get("base_gm") or {})
                or envelope.get("owner_ratified") is not False
            ):
                raise FoundryError(
                    "CG1_GM_CANDIDATE_AUTHORING_BINDING_INVALID",
                    "The historical authoring envelope does not reproduce from its capsule.",
                )
            base_service = self._factory_store(run_id, capsule_id)
            try:
                base = FactoryAuthoringWorkspaceService._load_gm_authoring(
                    base_service,
                    old_parts["project_id"],
                    project_revision=int(old_parts["project_revision"]),
                    snapshot=old_parts["snapshot"],
                )
            finally:
                base_service.close()
            if (
                not isinstance(base, Mapping)
                or self._base_identity(base.get("binding") or {}) != envelope.get("base_gm")
            ):
                raise FoundryError(
                    "CG1_GM_CANDIDATE_AUTHORING_BINDING_INVALID",
                    "The historical authoring base no longer matches its envelope.",
                )
        except FoundryError as exc:
            self._fail(
                "CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE",
                "The candidate GM authoring pointer could not be authenticated for transition.",
                details={"cause": exc.code},
            )
        except (AttributeError, KeyError, UnicodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._fail(
                "CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE",
                "The candidate GM authoring pointer could not be authenticated for transition.",
                details={"cause": type(exc).__name__},
            )

    def _load_existing(
        self,
        parts: Mapping[str, Any],
        *,
        allow_stale_transition: bool = False,
    ) -> dict[str, Any] | None:
        root = self._root(parts["context"]["run_id"])
        pointer_path = root / "current.json"
        try:
            pointer_raw = self._io_for_path(root, create=False).read_bytes(pointer_path)
        except FoundryError as exc:
            if exc.code == "CG1_GM_CANDIDATE_PAYLOAD_MISSING":
                return None
            raise
        try:
            pointer = json.loads(pointer_raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            self._fail("CG1_GM_CANDIDATE_AUTHORING_POINTER_INVALID", "The candidate GM authoring pointer is malformed.", details={"cause": type(exc).__name__})
        if not isinstance(pointer, dict):
            self._fail("CG1_GM_CANDIDATE_AUTHORING_POINTER_INVALID", "The candidate GM authoring pointer must be one object.")
        unsigned_pointer = {key: value for key, value in pointer.items() if key != "pointer_sha256"}
        if pointer.get("pointer_sha256") != sha256_json(unsigned_pointer):
            self._fail("CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE", "The candidate GM authoring pointer hash is invalid.")
        pointer_matches = (
            pointer.get("run_id") == parts["context"].get("run_id")
            and pointer.get("capsule_id") == parts["capsule_id"]
            and pointer.get("context_sha256") == parts["context"].get("context_sha256")
            and _SHA256_RE.fullmatch(str(pointer.get("envelope_sha256") or "")) is not None
            and _SHA256_RE.fullmatch(str(pointer.get("envelope_file_sha256") or "")) is not None
        )
        if not pointer_matches:
            if (
                allow_stale_transition
                and pointer.get("run_id") == parts["context"].get("run_id")
                and pointer.get("capsule_id") != parts["capsule_id"]
            ):
                self._verify_stale_pointer_transition(parts, pointer)
                return None
            self._fail("CG1_GM_CANDIDATE_AUTHORING_POINTER_STALE", "The candidate GM authoring pointer is bound to another captured context.")
        envelope_path = root / "envelopes" / f"envelope.{pointer['envelope_sha256']}.json"
        try:
            envelope_raw = self._io_for_path(root, create=False).read_bytes(envelope_path)
        except FoundryError as exc:
            if exc.code == "CG1_GM_CANDIDATE_PAYLOAD_MISSING":
                self._fail("CG1_GM_CANDIDATE_AUTHORING_ENVELOPE_MISSING", "The candidate GM authoring envelope is missing.")
            raise
        if sha256_bytes(envelope_raw) != pointer["envelope_file_sha256"]:
            self._fail("CG1_GM_CANDIDATE_AUTHORING_ENVELOPE_TAMPERED", "The candidate GM authoring envelope bytes changed.")
        try:
            envelope = json.loads(envelope_raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            self._fail("CG1_GM_CANDIDATE_AUTHORING_ENVELOPE_INVALID", "The candidate GM authoring envelope is malformed.", details={"cause": type(exc).__name__})
        if not isinstance(envelope, dict):
            self._fail("CG1_GM_CANDIDATE_AUTHORING_ENVELOPE_INVALID", "The candidate GM authoring envelope must be one object.")
        if sha256_json(envelope) != pointer["envelope_sha256"]:
            self._fail("CG1_GM_CANDIDATE_AUTHORING_ENVELOPE_TAMPERED", "The candidate GM authoring envelope hash is invalid.")
        if envelope.get("schema_version") != _ENVELOPE_SCHEMA or envelope.get("status") != _PENDING_STATUS:
            self._fail("CG1_GM_CANDIDATE_AUTHORING_ENVELOPE_INVALID", "The candidate GM authoring envelope schema or status is invalid.")
        envelope_unsigned = {key: value for key, value in envelope.items() if key != "integrity"}
        try:
            self.integrity.verify(_INTEGRITY_DOMAIN, envelope_unsigned, envelope.get("integrity") or {})
        except FoundryError:
            raise
        expected = self._expected_envelope(parts, envelope.get("base_gm") or {})
        if envelope_unsigned != expected or envelope.get("owner_ratified") is not False:
            self._fail("CG1_GM_CANDIDATE_AUTHORING_BINDING_INVALID", "The candidate GM authoring envelope does not reproduce from the captured context.")
        base_service = self._factory_store(
            parts["context"]["run_id"], parts["capsule_id"],
        )
        try:
            base = base_service._load_gm_authoring(
                parts["project_id"],
                project_revision=int(parts["project_revision"]),
                snapshot=parts["snapshot"],
            )
        finally:
            base_service.close()
        if isinstance(base, Mapping) and base.get("legacy_contract") is True:
            return None
        if base is None or self._base_identity(base["binding"]) != envelope["base_gm"]:
            self._fail("CG1_GM_CANDIDATE_AUTHORING_BINDING_INVALID", "The candidate GM receipt/profile/artifact no longer matches its envelope.")
        return {"envelope": envelope, "base": base}

    def _publish(self, parts: Mapping[str, Any], loaded_base: Mapping[str, Any]) -> dict[str, Any]:
        """Publish the candidate envelope only after the base receipt is verified."""
        run_id = parts["context"]["run_id"]
        envelope_unsigned = self._expected_envelope(parts, loaded_base["binding"])
        envelope = {
            **envelope_unsigned,
            "integrity": self.integrity.sign(_INTEGRITY_DOMAIN, envelope_unsigned).as_dict(),
        }
        envelope_sha256 = sha256_json(envelope)
        _envelope_path, envelope_file_sha256 = self._write_immutable(
            self._root(run_id) / "envelopes",
            f"envelope.{envelope_sha256}.json",
            envelope,
        )
        pointer_unsigned = {
            "schema_version": "TianxiaFoundry.CharacterCreationCandidateGMAuthoringPointer.v1",
            "run_id": run_id,
            "capsule_id": parts["capsule_id"],
            "context_sha256": parts["context"]["context_sha256"],
            "envelope_sha256": envelope_sha256,
            "envelope_file_sha256": envelope_file_sha256,
        }
        self._write_pointer(
            self._root(run_id) / "current.json",
            {**pointer_unsigned, "pointer_sha256": sha256_json(pointer_unsigned)},
        )
        return {"envelope": envelope, "base": loaded_base}

    @staticmethod
    def _candidate_approval_evidence_context(parts: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": _CANDIDATE_APPROVAL_SCHEMA,
            "run_id": parts["context"]["run_id"],
            "capsule_id": parts["capsule_id"],
            "context_sha256": parts["context"]["context_sha256"],
        }

    def _candidate_approval_binding(
        self,
        parts: Mapping[str, Any],
        loaded: Mapping[str, Any],
    ) -> dict[str, Any]:
        context = parts["context"]
        envelope = loaded.get("envelope")
        if not isinstance(envelope, Mapping):
            self._fail("CG1_GM_CANDIDATE_APPROVAL_CONTEXT_INVALID", "The candidate approval has no authenticated pending envelope.")
        return {
            "schema_version": "TianxiaFoundry.CharacterCreationCandidateGMApprovalBinding.v1",
            "run_id": context["run_id"],
            "capsule_id": parts["capsule_id"],
            "context_sha256": context["context_sha256"],
            "root_project": deepcopy(context["root_project"]),
            "root_lock_snapshot_sha256": context["root_lock_snapshot_sha256"],
            "candidate_project": deepcopy(context["candidate_project"]),
            "projection": deepcopy(context["projection"]),
            "sheet": deepcopy(context["sheet"]),
            "source": deepcopy(context["source"]),
            "mechanics": deepcopy(context["mechanics"]),
            "final_plan_sha256": context.get("final_plan_sha256"),
            "base_gm": self._base_identity(envelope.get("base_gm") or {}),
            "envelope_sha256": sha256_json(dict(envelope)),
        }

    def _candidate_approval_root(self, parts: Mapping[str, Any]) -> Path:
        return self._root(parts["context"]["run_id"]) / "contexts" / parts["capsule_id"] / "approvals"

    @staticmethod
    def _candidate_approval_id(unsigned: Mapping[str, Any]) -> str:
        material = {
            key: deepcopy(value)
            for key, value in unsigned.items()
            if key not in {"approval_id", "integrity", "approval_sha256"}
        }
        return "cg1-candidate-approval." + sha256_json(material)

    def _load_candidate_approval(
        self,
        parts: Mapping[str, Any],
        loaded: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        root = self._candidate_approval_root(parts)
        pointer_path = root / "current.json"
        # Approval is optional until the explicit owner action.  Avoid walking
        # an absent approval namespace after a concurrent candidate transition;
        # authenticated reads below still reject any present symlink or file.
        if not pointer_path.is_file():
            return None
        try:
            pointer = self._read_json(pointer_path, code="CG1_GM_CANDIDATE_APPROVAL_POINTER_INVALID")
        except FoundryError as exc:
            if exc.code == "CG1_GM_CANDIDATE_APPROVAL_POINTER_INVALID" and not pointer_path.exists():
                return None
            raise
        pointer_unsigned = {key: value for key, value in pointer.items() if key != "pointer_sha256"}
        approval_id = pointer.get("approval_id")
        if (
            pointer.get("schema_version") != _CANDIDATE_APPROVAL_POINTER_SCHEMA
            or pointer.get("run_id") != parts["context"]["run_id"]
            or pointer.get("capsule_id") != parts["capsule_id"]
            or pointer.get("context_sha256") != parts["context"]["context_sha256"]
            or pointer.get("pointer_sha256") != sha256_json(pointer_unsigned)
            or not isinstance(approval_id, str)
            or not re.fullmatch(r"cg1-candidate-approval\.[0-9a-f]{64}", approval_id)
            or not _SHA256_RE.fullmatch(str(pointer.get("approval_file_sha256") or ""))
        ):
            self._fail("CG1_GM_CANDIDATE_APPROVAL_POINTER_INVALID", "The candidate approval pointer is stale or malformed.")
        path = root / f"{approval_id}.json"
        raw = self._read_bytes(path, code="CG1_GM_CANDIDATE_APPROVAL_INVALID")
        if sha256_bytes(raw) != pointer["approval_file_sha256"]:
            self._fail("CG1_GM_CANDIDATE_APPROVAL_TAMPERED", "The candidate approval bytes changed after publication.")
        try:
            approval = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            self._fail("CG1_GM_CANDIDATE_APPROVAL_INVALID", "The candidate approval is not valid JSON.", details={"cause": type(exc).__name__})
        if not isinstance(approval, dict):
            self._fail("CG1_GM_CANDIDATE_APPROVAL_INVALID", "The candidate approval must be one JSON object.")
        approval_core = {key: value for key, value in approval.items() if key != "approval_sha256"}
        if approval.get("approval_sha256") != sha256_json(approval_core):
            self._fail("CG1_GM_CANDIDATE_APPROVAL_TAMPERED", "The candidate approval content hash is invalid.")
        unsigned = {key: value for key, value in approval_core.items() if key != "integrity"}
        if (
            approval.get("schema_version") != _CANDIDATE_APPROVAL_SCHEMA
            or approval.get("approval_id") != approval_id
            or approval_id != self._candidate_approval_id(unsigned)
            or approval.get("run_id") != parts["context"]["run_id"]
            or approval.get("capsule_id") != parts["capsule_id"]
            or approval.get("context_sha256") != parts["context"]["context_sha256"]
            or approval.get("envelope_sha256") != sha256_json(loaded["envelope"])
            or approval.get("binding") != self._candidate_approval_binding(parts, loaded)
        ):
            self._fail("CG1_GM_CANDIDATE_APPROVAL_BINDING_INVALID", "The candidate approval does not reproduce from its pending envelope and capsule.")
        self.integrity.verify(_CANDIDATE_APPROVAL_INTEGRITY_DOMAIN, unsigned, approval.get("integrity") or {})
        evidence_id = approval.get("approval_evidence_id")
        principal = approval.get("principal")
        if not isinstance(evidence_id, str) or not evidence_id or not isinstance(principal, Mapping):
            self._fail("CG1_GM_CANDIDATE_APPROVAL_INVALID", "The candidate approval has no exact approval evidence identity.")
        approval_service = ApprovalChallengeService(self.db, integrity=self.integrity)
        with self.db.connection() as conn:
            evidence = approval_service.verify_evidence(
                conn,
                evidence_id,
                operation=_CANDIDATE_APPROVAL_OPERATION,
                subject_type=_CANDIDATE_APPROVAL_SUBJECT_TYPE,
                subject_id=parts["context"]["run_id"],
                exact_bytes=self._json_bytes(loaded["envelope"]),
                binding=self._candidate_approval_binding(parts, loaded),
                project_lock_hash=parts["context"]["root_lock_snapshot_sha256"],
                principal_id=principal.get("principal_id"),
                evidence_context=self._candidate_approval_evidence_context(parts),
            )
        if evidence.get("principal") != dict(principal):
            self._fail("CG1_GM_CANDIDATE_APPROVAL_PRINCIPAL_INVALID", "The candidate approval principal differs from its evidence.")
        return {"approval": approval, "evidence": evidence}

    def _recover_candidate_approval_evidence(
        self,
        parts: Mapping[str, Any],
        loaded: Mapping[str, Any],
        approval_service: ApprovalChallengeService,
        challenge_id: str,
        nonce: str,
    ) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT challenge_id,status,nonce_hash FROM exact_approval_challenges WHERE challenge_id=?",
                (challenge_id,),
            ).fetchone()
            if not row or row["status"] != "consumed":
                return None
            if row["nonce_hash"] != sha256_bytes(str(nonce).encode("utf-8")):
                self._fail("APPROVAL_CHALLENGE_NONCE_INVALID", "The consumed candidate approval challenge nonce is invalid.", status_code=403)
            evidence_rows = conn.execute(
                "SELECT evidence_id FROM exact_approval_evidence WHERE challenge_id=? ORDER BY evidence_id",
                (challenge_id,),
            ).fetchall()
            if len(evidence_rows) != 1:
                self._fail("CG1_GM_CANDIDATE_APPROVAL_RECOVERY_INVALID", "The consumed candidate approval challenge has no unique evidence row.")
            return approval_service.verify_evidence(
                conn,
                evidence_rows[0]["evidence_id"],
                operation=_CANDIDATE_APPROVAL_OPERATION,
                subject_type=_CANDIDATE_APPROVAL_SUBJECT_TYPE,
                subject_id=parts["context"]["run_id"],
                exact_bytes=self._json_bytes(loaded["envelope"]),
                binding=self._candidate_approval_binding(parts, loaded),
                project_lock_hash=parts["context"]["root_lock_snapshot_sha256"],
                principal_id=approval_service.principal().principal_id,
                evidence_context=self._candidate_approval_evidence_context(parts),
            )

    def _with_candidate_approval(self, parts: Mapping[str, Any], loaded: Mapping[str, Any]) -> dict[str, Any]:
        approved = self._load_candidate_approval(parts, loaded)
        return {**loaded, "candidate_approval": approved} if approved is not None else dict(loaded)

    def issue_candidate_approval_challenge(self, run_id: str, ttl_seconds: int = 300) -> dict[str, Any]:
        """Issue an exact-byte owner challenge for the current candidate GM draft."""
        self._capsule(run_id)
        with self._run_scope(run_id) as run_io:
            with run_io.exclusive_lock():
                _capsule, parts = self._capsule(run_id)
                loaded = self._load_existing(parts)
                if loaded is None:
                    self._fail("GM_AUTHORING_RECEIPT_NOT_FOUND", "No candidate GM authoring receipt is available for approval.", status_code=404)
                # ``base_gm`` is the historical identity projection and
                # intentionally omits the contract marker.  Check the
                # authenticated loaded binding instead so legacy envelopes
                # remain byte-compatible and composite receipts can enter
                # this explicit approval path.
                if (loaded.get("base", {}).get("binding", {}).get("authoring_contract")) != _COMPOSITE_GM_CONTRACT:
                    self._fail("GM_AUTHORING_RECEIPT_NOT_FOUND", "The candidate GM receipt is not eligible for owner approval.", status_code=409)
                approved = self._load_candidate_approval(parts, loaded)
                if approved is not None:
                    return {
                        "status": _APPROVED_STATUS,
                        "run_id": run_id,
                        "capsule_id": parts["capsule_id"],
                        "approval_id": approved["approval"]["approval_id"],
                        "approval_evidence_id": approved["approval"]["approval_evidence_id"],
                        "owner_ratified": True,
                    }
                binding = self._candidate_approval_binding(parts, loaded)
                lock_hash = parts["context"].get("root_lock_snapshot_sha256")
                if not isinstance(lock_hash, str) or _SHA256_RE.fullmatch(lock_hash) is None:
                    self._fail("CG1_GM_CANDIDATE_APPROVAL_CONTEXT_INVALID", "The root lock snapshot is not a valid approval authority.")
                challenge = ApprovalChallengeService(self.db, integrity=self.integrity).issue(
                    operation=_CANDIDATE_APPROVAL_OPERATION,
                    subject_type=_CANDIDATE_APPROVAL_SUBJECT_TYPE,
                    subject_id=run_id,
                    exact_bytes=self._json_bytes(loaded["envelope"]),
                    binding=binding,
                    project_lock_hash=lock_hash,
                    ttl_seconds=ttl_seconds,
                )
                return {
                    "status": "CANDIDATE_GM_APPROVAL_CHALLENGE_ISSUED",
                    "run_id": run_id,
                    "capsule_id": parts["capsule_id"],
                    "receipt_id": loaded["envelope"]["base_gm"].get("receipt_id"),
                    "challenge": challenge["challenge"],
                }

    def approve_candidate_gm(self, run_id: str, challenge_id: str, nonce: str) -> dict[str, Any]:
        """Consume one owner challenge and persist a separate immutable approval."""
        self._capsule(run_id)
        with self._run_scope(run_id) as run_io:
            with run_io.exclusive_lock():
                _capsule, parts = self._capsule(run_id)
                loaded = self._load_existing(parts)
                if loaded is None:
                    self._fail("GM_AUTHORING_RECEIPT_NOT_FOUND", "No candidate GM authoring receipt is available for approval.", status_code=404)
                existing = self._load_candidate_approval(parts, loaded)
                if existing is not None:
                    return self._public({**loaded, "candidate_approval": existing}, provider_calls=0)
                if not isinstance(challenge_id, str) or not challenge_id.strip() or not isinstance(nonce, str) or not nonce.strip():
                    self._fail("CG1_GM_CANDIDATE_APPROVAL_REQUEST_INVALID", "A challenge ID and nonce are required for candidate approval.", status_code=400)
                binding = self._candidate_approval_binding(parts, loaded)
                lock_hash = parts["context"]["root_lock_snapshot_sha256"]
                approval_service = ApprovalChallengeService(self.db, integrity=self.integrity)
                evidence = self._recover_candidate_approval_evidence(
                    parts, loaded, approval_service, challenge_id, nonce,
                )
                if evidence is None:
                    evidence = approval_service.consume(
                        challenge_id=challenge_id,
                        nonce=nonce,
                        operation=_CANDIDATE_APPROVAL_OPERATION,
                        subject_type=_CANDIDATE_APPROVAL_SUBJECT_TYPE,
                        subject_id=run_id,
                        exact_bytes=self._json_bytes(loaded["envelope"]),
                        binding=binding,
                        project_lock_hash=lock_hash,
                        evidence_context=self._candidate_approval_evidence_context(parts),
                    )
                unsigned = {
                    "schema_version": _CANDIDATE_APPROVAL_SCHEMA,
                    "approval_id": None,
                    "run_id": run_id,
                    "capsule_id": parts["capsule_id"],
                    "context_sha256": parts["context"]["context_sha256"],
                    "envelope_sha256": sha256_json(loaded["envelope"]),
                    "binding": binding,
                    "approval_evidence_id": evidence["evidence_id"],
                    "principal": deepcopy(evidence.get("principal") or {}),
                }
                unsigned["approval_id"] = self._candidate_approval_id(unsigned)
                signed = self.integrity.sign(_CANDIDATE_APPROVAL_INTEGRITY_DOMAIN, unsigned).as_dict()
                approval_core = {**unsigned, "integrity": signed}
                approval = {
                    **approval_core,
                    "approval_sha256": sha256_json(approval_core),
                }
                approval_id = approval["approval_id"]
                approval_root = self._candidate_approval_root(parts)
                _approval_path, approval_file_sha256 = self._write_immutable(
                    approval_root,
                    f"{approval_id}.json",
                    approval,
                )
                pointer_unsigned = {
                    "schema_version": _CANDIDATE_APPROVAL_POINTER_SCHEMA,
                    "run_id": run_id,
                    "capsule_id": parts["capsule_id"],
                    "context_sha256": parts["context"]["context_sha256"],
                    "approval_id": approval_id,
                    "approval_file_sha256": approval_file_sha256,
                }
                self._write_pointer(
                    approval_root / "current.json",
                    {**pointer_unsigned, "pointer_sha256": sha256_json(pointer_unsigned)},
                )
                loaded = {**loaded, "candidate_approval": {"approval": approval, "evidence": evidence}}
                return self._public(loaded, provider_calls=0)

    def _candidate_compilation_authority_locked(
        self,
        run: Mapping[str, Any],
        parts: Mapping[str, Any],
        *,
        final_plan: Mapping[str, Any] | None = None,
        loaded: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve the approved proof while the caller owns the run lock."""
        if loaded is None:
            loaded = self._load_existing(parts)
        if loaded is None:
            return None
        approved = self._load_candidate_approval(parts, loaded)
        if approved is None:
            return None
        expected_plan_sha = parts["context"].get("final_plan_sha256")
        selected_plan = final_plan if final_plan is not None else run.get("final_plan")
        actual_plan_sha = (
            sha256_json(dict(selected_plan))
            if isinstance(selected_plan, Mapping) and selected_plan
            else None
        )
        if expected_plan_sha != actual_plan_sha:
            self._fail(
                "CG1_GM_CANDIDATE_APPROVAL_PLAN_STALE",
                "The approved candidate is bound to a different final plan.",
                details={"expected": expected_plan_sha, "actual": actual_plan_sha},
            )
        binding = approved["approval"].get("binding")
        if not isinstance(binding, Mapping):
            self._fail(
                "CG1_GM_CANDIDATE_APPROVAL_BINDING_INVALID",
                "The approved candidate has no typed binding.",
            )
        return {
            "schema_version": "TianxiaFoundry.CharacterCreationCandidateGMCompilationAuthority.v1",
            "run_id": run["run_id"],
            "capsule_id": parts["capsule_id"],
            "context_sha256": parts["context"]["context_sha256"],
            "approval_id": approved["approval"]["approval_id"],
            "approval_evidence_id": approved["approval"]["approval_evidence_id"],
            "binding_sha256": sha256_json(dict(binding)),
            "candidate_project": deepcopy(parts["context"]["candidate_project"]),
            "final_plan_sha256": expected_plan_sha,
        }

    def candidate_compilation_authority(
        self,
        run: Mapping[str, Any],
        *,
        final_plan: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve the approved candidate into a narrow server-owned proof."""
        run_id = run.get("run_id") if isinstance(run, Mapping) else None
        if not isinstance(run_id, str) or not run_id:
            return None
        capsule_root = self.capsules._run_dir(run_id)
        if not (capsule_root / "current.json").is_file():
            return None
        self._capsule(run_id)
        with self._run_scope(run_id) as run_io:
            with run_io.exclusive_lock():
                _capsule, parts = self._capsule(run_id)
                return self._candidate_compilation_authority_locked(
                    run,
                    parts,
                    final_plan=final_plan,
                )

    def materialize_approved_factory_authoring(
        self,
        run: Mapping[str, Any],
        scratch_db: Any,
        *,
        final_plan: Mapping[str, Any] | None = None,
        factory_authoring: Any | None = None,
        authority: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Bridge an approved candidate receipt into one fresh scratch DB.

        The candidate receipt and profile remain immutable.  The scratch copy is
        a derived Factory pointer with an ordinary owner decision whose exact
        fields are bound to the consumed candidate approval evidence.
        """
        if authority is None:
            return None
        run_id = str(run["run_id"])
        frozen_capsule_id = authority.get("capsule_id") if isinstance(authority, Mapping) else None
        frozen_context_sha256 = authority.get("context_sha256") if isinstance(authority, Mapping) else None
        if (
            not isinstance(frozen_capsule_id, str)
            or not re.fullmatch(r"cg1\.gm\.capsule\.[0-9a-f]{64}", frozen_capsule_id)
            or not isinstance(frozen_context_sha256, str)
            or not _SHA256_RE.fullmatch(frozen_context_sha256)
        ):
            self._fail(
                "CG1_GM_CANDIDATE_APPROVAL_BINDING_INVALID",
                "The frozen candidate authority has no valid capsule identity.",
            )
        with self._run_scope(run_id) as run_io:
            with run_io.exclusive_lock():
                current_pointer, _current_manifest, _current_payloads = self.capsules._read_capsule_payloads(run_id)
                if (
                    current_pointer.get("capsule_id") != frozen_capsule_id
                    or current_pointer.get("context_sha256") != frozen_context_sha256
                ):
                    self._fail(
                        "CG1_GM_CANDIDATE_APPROVAL_BINDING_INVALID",
                        "The current candidate pointer no longer names the frozen approved capsule.",
                    )
                _capsule = self.capsules._load_immutable_capsule_for_id(run_id, frozen_capsule_id)
                parts = self._context_parts(_capsule)
                if (
                    parts["context"].get("run_id") != run_id
                    or parts["capsule_id"] != frozen_capsule_id
                    or parts["context"].get("context_sha256") != frozen_context_sha256
                ):
                    self._fail(
                        "CG1_GM_CANDIDATE_APPROVAL_BINDING_INVALID",
                        "The immutable candidate capsule differs from the frozen approval identity.",
                    )
                loaded = self._load_existing(parts)
                if loaded is None:
                    self._fail("GM_AUTHORING_RECEIPT_NOT_FOUND", "The approved candidate GM receipt is missing.")
                resolved_authority = self._candidate_compilation_authority_locked(
                    run,
                    parts,
                    final_plan=final_plan,
                    loaded=loaded,
                )
                if resolved_authority is None:
                    return None
                if authority is not None:
                    if not isinstance(authority, Mapping) or dict(authority) != dict(resolved_authority):
                        self._fail(
                            "CG1_GM_CANDIDATE_APPROVAL_BINDING_INVALID",
                            "The approved candidate authority changed after compilation began.",
                        )
                authority = resolved_authority
                approved = self._load_candidate_approval(parts, loaded)
                if approved is None:
                    self._fail("CG1_GM_CANDIDATE_APPROVAL_REQUIRED", "An owner-approved candidate is required before scratch admission.")
                context = parts["context"]
                candidate_meta = context.get("candidate_project")
                if not isinstance(candidate_meta, Mapping):
                    self._fail("CG1_GM_CANDIDATE_APPROVAL_CONTEXT_INVALID", "The approved candidate project metadata is missing.")
                with scratch_db.connection() as conn:
                    row = conn.execute(
                        "SELECT revision,canonical_project_hash FROM projects WHERE project_id=?",
                        (parts["project_id"],),
                    ).fetchone()
                if (
                    row is None
                    or int(row["revision"]) != int(candidate_meta.get("project_revision"))
                    or row["canonical_project_hash"] != candidate_meta.get("canonical_project_hash")
                ):
                    self._fail(
                        "CG1_GM_CANDIDATE_REPRODUCTION_INVALID",
                        "The scratch project does not reproduce the approved candidate project.",
                    )
                source_service = self._factory_store(run_id, parts["capsule_id"])
                try:
                    source_root = source_service._candidate_gm_root
                    source_io = source_service._candidate_io
                    files: dict[str, bytes] = {}
                    for path in sorted(source_root.rglob("*")):
                        try:
                            mode = os.lstat(path).st_mode
                        except OSError as exc:
                            self._fail("CG1_GM_CANDIDATE_APPROVAL_SOURCE_INVALID", "The approved GM source cannot be inspected safely.", details={"cause": type(exc).__name__})
                        if stat.S_ISLNK(mode):
                            self._fail("CG1_GM_CANDIDATE_APPROVAL_SOURCE_INVALID", "The approved GM source contains a symlink.")
                        if stat.S_ISREG(mode):
                            relative = path.relative_to(source_root)
                            files[relative.as_posix()] = source_io.read_bytes(path)
                finally:
                    source_service.close()
                if "current.json" not in files:
                    self._fail("CG1_GM_CANDIDATE_APPROVAL_SOURCE_INVALID", "The approved candidate has no Factory authoring pointer.")

                destination_root = Path(os.path.abspath(os.fspath(scratch_db.settings.data_dir))) / "factory_gm_authoring" / parts["project_id"]
                if destination_root.exists() and any(destination_root.rglob("*")):
                    self._fail("CG1_GM_CANDIDATE_PROMOTION_DESTINATION_COLLISION", "The scratch Factory authoring destination is already populated.")
                destination_root.mkdir(parents=True, exist_ok=True)
                for relative_name, payload in files.items():
                    target = destination_root / relative_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)

                binding = loaded["base"]["binding"]
                evidence = approved["evidence"]
                decision_unsigned = {
                    "schema_version": _FACTORY_OWNER_DECISION_SCHEMA,
                    "decision_id": None,
                    "project_id": parts["project_id"],
                    "project_revision": int(binding["project_revision"]),
                    "receipt_id": binding["receipt_id"],
                    "receipt_sha256": binding["receipt_sha256"],
                    "artifact_sha256": binding["artifact_sha256"],
                    "profile_sha256": binding["profile_sha256"],
                    "source_snapshot_sha256": binding["source_snapshot_sha256"],
                    "selected_record_content_sha256": binding["selected_record_content_sha256"],
                    "decision": True,
                    "approval_evidence_id": evidence["evidence_id"],
                    "principal": deepcopy(evidence.get("principal") or {}),
                }
                decision_unsigned["decision_id"] = "gm-decision." + sha256_json({
                    key: value for key, value in decision_unsigned.items() if key != "decision_id"
                })
                scratch_integrity = getattr(factory_authoring, "integrity", None) or self.integrity
                decision_integrity = scratch_integrity.sign(
                    _FACTORY_DECISION_INTEGRITY_DOMAIN,
                    decision_unsigned,
                ).as_dict()
                decision_core = {**decision_unsigned, "integrity": decision_integrity}
                decision = {
                    **decision_core,
                    "decision_sha256": sha256_json(decision_core),
                }
                decision_path = destination_root / "decisions" / f"{decision_unsigned['decision_id']}.json"
                decision_path.parent.mkdir(parents=True, exist_ok=True)
                decision_path.write_text(canonical_json(decision) + "\n", encoding="utf-8")
                try:
                    pointer = json.loads(files["current.json"].decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    self._fail("CG1_GM_CANDIDATE_APPROVAL_SOURCE_INVALID", "The copied Factory pointer is malformed.", details={"cause": type(exc).__name__})
                if not isinstance(pointer, dict):
                    self._fail("CG1_GM_CANDIDATE_APPROVAL_SOURCE_INVALID", "The copied Factory pointer is not an object.")
                pointer_unsigned = {key: value for key, value in pointer.items() if key != "pointer_sha256"}
                if pointer.get("pointer_sha256") != sha256_json(pointer_unsigned) or pointer_unsigned.get("owner_decision_id") is not None:
                    self._fail("CG1_GM_CANDIDATE_APPROVAL_SOURCE_INVALID", "The copied Factory pointer is stale or already promoted.")
                pointer_unsigned["owner_decision_id"] = decision_unsigned["decision_id"]
                pointer_unsigned["owner_decision_sha256"] = decision["decision_sha256"]
                destination_root.joinpath("current.json").write_text(
                    canonical_json({**pointer_unsigned, "pointer_sha256": sha256_json(pointer_unsigned)}) + "\n",
                    encoding="utf-8",
                )
                return {
                    **authority,
                    "decision_id": decision_unsigned["decision_id"],
                    "receipt_id": binding["receipt_id"],
                    "project_id": parts["project_id"],
                    "project_revision": int(binding["project_revision"]),
                }

    def _recover_existing_base(self, parts: Mapping[str, Any]) -> dict[str, Any] | None:
        """Complete a publication interrupted after the authenticated base write."""
        # A base receipt is recoverable only when this run/capsule had a
        # server-authenticated pre-publication intent.  The capsule-specific
        # staging root then prevents another same-project capsule from being
        # mistaken for this interrupted publication.
        if self._load_intent(parts) is None:
            return None
        base_service = self._factory_store(
            parts["context"]["run_id"], parts["capsule_id"],
        )
        try:
            base = base_service._load_gm_authoring(
                parts["project_id"],
                project_revision=int(parts["project_revision"]),
                snapshot=parts["snapshot"],
            )
        finally:
            base_service.close()
        if isinstance(base, Mapping) and base.get("legacy_contract") is True:
            return None
        if base is None:
            return None
        return self._publish(parts, base)

    def _record_failure(self, parts: Mapping[str, Any], exc: FoundryError) -> None:
        try:
            root = self._root(parts["context"]["run_id"])
            payload = {
                "schema_version": _ATTEMPT_SCHEMA,
                "run_id": parts["context"]["run_id"],
                "capsule_id": parts["capsule_id"],
                "context_sha256": parts["context"]["context_sha256"],
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": {
                        key: deepcopy(exc.details[key])
                        for key in ("phase", "cause_type")
                        if isinstance(exc.details, Mapping) and key in exc.details
                    },
                },
            }
            self._write_immutable(root / "attempts", f"attempt.{sha256_json(payload)}.json", payload)
        except (FoundryError, OSError):
            return

    def author(self, run_id: str) -> dict[str, Any]:
        # Validate before opening the staging namespace, then revalidate after
        # waiting for the cross-process run lock so a changed capsule cannot
        # be paired with an older provider request.
        self._capsule(run_id)
        with self._run_scope(run_id) as run_io:
            with run_io.exclusive_lock():
                _capsule, parts = self._capsule(run_id)
                return self._author_locked(run_id, parts)

    def _author_locked(self, run_id: str, parts: Mapping[str, Any]) -> dict[str, Any]:
        try:
            existing = self._load_existing(parts, allow_stale_transition=True)
            if existing is not None:
                return self._public(
                    self._with_candidate_approval(parts, existing),
                    provider_calls=0,
                )
            recovered = self._recover_existing_base(parts)
            if recovered is not None:
                return self._public(
                    self._with_candidate_approval(parts, recovered),
                    provider_calls=0,
                )

            # Record the exact run/capsule/context binding before any provider
            # result or base receipt is persisted.  A later retry can safely
            # finish publication without calling the provider again.
            self._write_intent(parts)

            provider = self.provider
            settings = getattr(provider, "_settings", lambda: None)() if provider is not None else None
            if not isinstance(settings, Mapping) or settings.get("provider_id") not in _GM_AUTHORING_PROVIDER_IDS:
                raise FoundryError("GM_AUTHORING_PROVIDER_INVALID", "Candidate GM authoring requires the selected local provider or the Agent bridge.")
            provider_result: Mapping[str, Any] | None = None
            prepared_for_persist: Mapping[str, Any] | None = None
            with self._prepared_composite(parts) as prepared:
                request_wire = _canonical_wire_bytes(
                    str(prepared["prompt_text"]),
                    str(prepared["system_message"]),
                    settings,
                    prepared["response_schema"],
                )
                expected_request_sha256 = sha256_bytes(request_wire)
                prepared_for_call = dict(prepared)
                prepared_for_call["wire_request_sha256"] = expected_request_sha256
                provider_result = provider.complete_json(
                    prompt_text=prepared["prompt_text"],
                    system_message=prepared["system_message"],
                    purpose=CompositeControllerAuthoring.purpose,
                    substantive=True,
                    response_schema=prepared["response_schema"],
                    response_schema_name=prepared["response_schema_name"],
                    response_schema_max_output_tokens=COMPOSITE_CONTROLLER_MAX_OUTPUT_TOKENS,
                    max_request_bytes=prepared["max_request_bytes"],
                    temperature=0,
                    expected_request_sha256=expected_request_sha256,
                )
                if not isinstance(provider_result, Mapping) or provider_result.get("request_sha256") != expected_request_sha256:
                    raise FoundryError(
                        "GM_AUTHORING_PROVIDER_REQUEST_EVIDENCE_INVALID",
                        "The local provider returned request evidence different from the server-authorized request.",
                    )
                raw_provider_text = provider_result.get("response_text")
                provider_value = provider_result.get("value")
                if not isinstance(raw_provider_text, str) or not raw_provider_text.strip():
                    if not isinstance(provider_value, Mapping):
                        raise FoundryError("GM_AUTHORING_PROVIDER_RESPONSE_INVALID", "The local provider returned no composite controller JSON.")
                    raw_provider_text = canonical_json(provider_value)
                try:
                    parsed_provider = json.loads(raw_provider_text)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise FoundryError("GM_AUTHORING_PROVIDER_RESPONSE_INVALID", "The local provider returned malformed composite controller JSON.") from exc
                if not isinstance(parsed_provider, Mapping) or (isinstance(provider_value, Mapping) and dict(parsed_provider) != dict(provider_value)):
                    raise FoundryError("GM_AUTHORING_PROVIDER_RESPONSE_INVALID", "The local provider response text differs from its parsed composite controller.")
                completion_sha256 = provider_result.get("completion_sha256")
                if not isinstance(completion_sha256, str) or sha256_bytes(raw_provider_text.encode("utf-8")) != completion_sha256:
                    raise FoundryError("GM_AUTHORING_PROVIDER_EVIDENCE_INVALID", "The provider completion hash does not match its composite response bytes.")
                validated = CompositeControllerAuthoring._validate_response(prepared_for_call, dict(parsed_provider))
                response, profile_extension = self._server_response(
                    prepared,
                    validated,
                    selected_record_ids=list(parts["record_ids"]),
                )
                adapted_provider_result = {
                    **dict(provider_result),
                    "purpose": FactoryAuthoringWorkspaceService.gm_tactical_contract()["purpose"],
                    "value": response,
                    "response_text": raw_provider_text,
                }
                prepared_for_persist = dict(prepared)
            if provider_result is None or prepared_for_persist is None:
                raise FoundryError(
                    "GM_AUTHORING_PROVIDER_RESPONSE_INVALID",
                    "The local provider did not return a composite controller result.",
                )
            _after_capsule, after_parts = self._capsule(run_id)
            if after_parts["context"]["context_sha256"] != parts["context"]["context_sha256"]:
                raise FoundryError(
                    "CG1_GM_CANDIDATE_AUTHORING_CONTEXT_STALE",
                    "The captured GM candidate changed while the provider was authoring.",
                    status_code=409,
                )
            base_service = self._factory_store(run_id, parts["capsule_id"])
            try:
                base_service._persist_gm_authoring(
                    parts["project_id"],
                    int(parts["project_revision"]),
                    parts["snapshot"],
                    prompt_text=str(prepared_for_persist["prompt_text"]),
                    system_message=str(prepared_for_persist["system_message"]),
                    provider_result=adapted_provider_result,
                    response=response,
                    provider_response=provider_result,
                    authoring_contract=_COMPOSITE_GM_CONTRACT,
                    response_schema_name=prepared_for_persist["response_schema_name"],
                    response_schema=prepared_for_persist["response_schema"],
                    profile_extension=profile_extension,
                )
                loaded_base = base_service._load_gm_authoring(
                    parts["project_id"],
                    project_revision=int(parts["project_revision"]),
                    snapshot=parts["snapshot"],
                )
            finally:
                base_service.close()
            if loaded_base is None:
                raise FoundryError("GM_AUTHORING_RECEIPT_INVALID", "The candidate GM receipt could not be reloaded after persistence.")
            loaded = self._publish(parts, loaded_base)
            return self._public(
                self._with_candidate_approval(parts, loaded),
                provider_calls=1,
            )
        except FoundryError as exc:
            self._record_failure(parts, exc)
            raise
        except Exception as exc:
            wrapped = FoundryError(
                "GM_AUTHORING_UNEXPECTED_FAILURE",
                "Candidate GM authoring failed unexpectedly; no candidate success was recorded.",
                details={"phase": "provider_or_publication", "cause_type": type(exc).__name__},
                status_code=502,
            )
            self._record_failure(parts, wrapped)
            raise wrapped from exc

    def load(self, run_id: str) -> dict[str, Any]:
        self._capsule(run_id)
        with self._run_scope(run_id) as run_io:
            with run_io.exclusive_lock():
                _capsule, parts = self._capsule(run_id)
                loaded = self._load_existing(parts)
                if loaded is None:
                    self._fail("GM_AUTHORING_RECEIPT_NOT_FOUND", "No candidate GM authoring receipt is available.", status_code=404)
                return self._public(self._with_candidate_approval(parts, loaded), provider_calls=0)

    def status(self, run_id: str) -> dict[str, Any]:
        self._capsule(run_id)
        with self._run_scope(run_id) as run_io:
            with run_io.exclusive_lock():
                _capsule, parts = self._capsule(run_id)
                loaded = self._load_existing(parts)
                if loaded is None:
                    return {
                        "status": "CANDIDATE_GM_AUTHORING_NOT_AUTHORED",
                        "run_id": run_id,
                        "capsule_id": parts["capsule_id"],
                        "context_sha256": parts["context"]["context_sha256"],
                        "provider_calls": 0,
                        "provider_free_review": True,
                        "owner_ratified": False,
                        "eligible_for_later_command5_checkpoint": False,
                    }
                return self._public(self._with_candidate_approval(parts, loaded), provider_calls=0)

    def build(self, run_id: str) -> dict[str, Any]:
        """Provider-free authenticated review/build of the candidate artifact."""
        loaded = self.load(run_id)
        approved = loaded.get("owner_ratified") is True
        status = _APPROVED_STATUS if approved else "CANDIDATE_GM_AUTHORING_REVIEW_READY"
        return {
            **loaded,
            "status": status,
            "workspace_status": status,
            "provider_calls": 0,
            "provider_free_build_available": True,
            "owner_ratified": approved,
            "eligible_for_later_command5_checkpoint": approved,
        }


__all__ = ["CandidateGMAuthoringService"]
