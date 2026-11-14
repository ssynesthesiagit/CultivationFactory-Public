"""Server-owned staging context for later explicit GM authoring.

The character builder's scratch database is disposable.  This module copies
the authenticated inputs needed by a later authoring action into an immutable,
run-keyed capsule before the production release/GM gate runs.  It deliberately
does not create a GM artifact, ratify anything, or change the candidate state.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import errno
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import threading
from typing import Any, Mapping

from app.core import FoundryError, canonical_json, sha256_bytes, sha256_file, sha256_json
from contracts.canonical import ZERO_HASH, canonical_event_hash, canonical_record_hash
from security.integrity import IntegrityService


CAPSULE_SCHEMA = "TianxiaFoundry.GMCandidateContext.v1"
CAPSULE_STATUS = "CANDIDATE_CONTEXT_CAPTURED"
MANIFEST_DOMAIN = "tianxia.foundry.character_creation.gm_candidate.manifest.v1"
POINTER_DOMAIN = "tianxia.foundry.character_creation.gm_candidate.pointer.v1"
CAPSULE_ROOT_NAME = "character_creation_gm_candidates"
CAPSULE_ID_PREFIX = "cg1.gm.capsule."
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CAPSULE_ID_RE = re.compile(r"^cg1\.gm\.capsule\.[0-9a-f]{64}$")
_RUN_KEY_RE = re.compile(r"^[0-9a-f]{32}$")
_REQUIRED_PROJECTION_ARTIFACTS = (
    "Character_Master_Ledger.json",
    "Rules_Selection_Packets.json",
    "Projection_Provenance_Map.json",
    "Projection_Coverage_Report.json",
    "Projection_Diagnostics.json",
)
_FACTORY_WORKSPACE_PREFIX = "factory_workspace/"
_FACTORY_WORKSPACE_SCHEMA = "TianxiaFoundry.GMCandidateFactoryWorkspace.v1"
_LOCK = threading.RLock()


def _fail(code: str, message: str, *, details: Any = None, status_code: int = 409) -> None:
    raise FoundryError(code, message, details=details, status_code=status_code)


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _fail(
            "CG1_GM_CANDIDATE_BINDING_INVALID",
            f"The authenticated {label} hash is malformed.",
            details={"label": label},
        )
    return value


def _receipt_hash_detail(value: Any) -> str | None:
    """Keep receipt mismatch diagnostics limited to digest-shaped values."""
    return value if isinstance(value, str) and _SHA256_RE.fullmatch(value) else None


def _receipt_int_detail(value: Any) -> int | None:
    return value if type(value) is int else None


def _receipt_identifier_detail(value: Any) -> str | None:
    return value if isinstance(value, str) and len(value) <= 256 else None


def _json_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _parse_json_bytes(payload: bytes, *, label: str) -> Any:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(
            "CG1_GM_CANDIDATE_PAYLOAD_INVALID",
            f"The staged {label} is not valid JSON.",
            details={"label": label},
        )
    expected = canonical_json(value).encode("utf-8")
    if payload not in {expected, expected + b"\n"}:
        _fail(
            "CG1_GM_CANDIDATE_PAYLOAD_INVALID",
            f"The staged {label} is not in canonical JSON form.",
            details={"label": label},
        )
    return value


def _json_safe(value: Any) -> Any:
    """Convert SQLite values to a payload-safe value without exposing secrets."""
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return {"bytes_sha256": sha256_bytes(value), "bytes": len(value)}
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {str(key): _json_safe(value) for key, value in row.items()}
    if hasattr(row, "keys"):
        return {str(key): _json_safe(row[key]) for key in row.keys()}
    return {}


def _safe_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or "\x00" in value:
        _fail(
            "CG1_GM_CANDIDATE_BINDING_INVALID",
            f"The {label} identifier is invalid.",
            details={"label": label},
        )
    return value


def _canonical_db_json(raw: Any, label: str) -> tuple[str, Any]:
    if not isinstance(raw, str):
        _fail(
            "CG1_GM_CANDIDATE_SOURCE_INVALID",
            f"The authenticated {label} is not text JSON.",
            details={"label": label},
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(
            "CG1_GM_CANDIDATE_SOURCE_INVALID",
            f"The authenticated {label} is malformed JSON.",
            details={"label": label},
        )
    if canonical_json(value) != raw:
        _fail(
            "CG1_GM_CANDIDATE_SOURCE_INVALID",
            f"The authenticated {label} is not its canonical byte representation.",
            details={"label": label},
        )
    return raw, value



def _non_sphere_authority_for(db: Any) -> Any:
    """One authenticated non-Sphere authority per database handle.

    The service reads only the app's sealed authority files (verified at
    construction); a snapshot resolved it once per Method/Foundation record,
    620 constructions in one retry.  ``project_store`` caches it per store
    the same way.
    """
    from non_sphere_authority.service import NonSphereAuthorityService

    cached = getattr(db, "_cg1_non_sphere_authority", None)
    if cached is None:
        cached = NonSphereAuthorityService(db)
        try:
            setattr(db, "_cg1_non_sphere_authority", cached)
        except AttributeError:
            pass
    return cached

class CandidateGMCapsuleStore:
    """Persist and validate an immutable run-scoped GM authoring context."""

    def __init__(self, db: Any):
        self.db = db
        # Keep the namespace lexical.  Every component is opened below with
        # O_NOFOLLOW, so an attacker cannot replace ``runs`` or a run key with
        # a symlink between path construction and persistence.
        self.root = Path(os.path.abspath(os.fspath(Path(db.settings.data_dir) / CAPSULE_ROOT_NAME)))
        self.integrity = IntegrityService.for_database(db)

    @staticmethod
    def _run_key(run_id: str) -> str:
        return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:32]

    def _run_dir(self, run_id: str) -> Path:
        return self.root / "runs" / self._run_key(run_id)

    @staticmethod
    def _component(name: str, *, label: str) -> str:
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or "\x00" in name
        ):
            _fail("CG1_GM_CANDIDATE_PATH_INVALID", f"The {label} path component is invalid.")
        return name

    @staticmethod
    def _assert_no_symlink_path(root: Path, path: Path, *, label: str) -> Path:
        """Check lexical containment and every existing ancestor with lstat."""
        root = Path(os.path.abspath(os.fspath(root)))
        path = Path(os.path.abspath(os.fspath(path)))
        try:
            relative = path.relative_to(root)
        except ValueError:
            _fail(
                "CG1_GM_CANDIDATE_PATH_INVALID",
                f"The {label} path is outside its authenticated root.",
                details={"label": label},
            )
        current = root
        candidates = [root, *(root / part for part in relative.parts)]
        for candidate in candidates:
            try:
                mode = os.lstat(candidate).st_mode
            except FileNotFoundError:
                continue
            except OSError as exc:
                _fail(
                    "CG1_GM_CANDIDATE_PATH_INVALID",
                    f"The {label} path cannot be inspected safely.",
                    details={"label": label, "cause": type(exc).__name__},
                )
            if stat.S_ISLNK(mode):
                _fail(
                    "CG1_GM_CANDIDATE_PATH_INVALID",
                    f"The {label} path contains a symlinked ancestor.",
                    details={"label": label},
                )
            current = candidate
        return path

    @staticmethod
    def _dir_flags() -> int:
        return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)

    @staticmethod
    def _read_flags() -> int:
        return os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)

    def _open_root_dir(self, *, create: bool) -> int:
        root = self.root
        self._assert_no_symlink_path(root.parent, root.parent, label="capsule namespace parent")
        try:
            parent_fd = os.open(root.parent, self._dir_flags())
        except OSError as exc:
            _fail(
                "CG1_GM_CANDIDATE_PATH_INVALID" if exc.errno == errno.ELOOP else "CG1_GM_CANDIDATE_PAYLOAD_MISSING",
                "The capsule namespace parent is unavailable or is a symlink.",
            )
        try:
            try:
                root_mode = os.lstat(root.name, dir_fd=parent_fd).st_mode
            except FileNotFoundError:
                root_mode = None
            if root_mode is not None and stat.S_ISLNK(root_mode):
                _fail("CG1_GM_CANDIDATE_PATH_INVALID", "The capsule namespace root is a symlink.")
            if create:
                try:
                    os.mkdir(root.name, 0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
            try:
                return os.open(root.name, self._dir_flags(), dir_fd=parent_fd)
            except OSError as exc:
                _fail(
                    "CG1_GM_CANDIDATE_PATH_INVALID" if exc.errno == errno.ELOOP else "CG1_GM_CANDIDATE_PAYLOAD_MISSING",
                    "The capsule namespace root is unavailable or is a symlink.",
                )
        finally:
            os.close(parent_fd)

    def _open_child_dir(self, parent_fd: int, name: str, *, create: bool, label: str) -> int:
        name = self._component(name, label=label)
        try:
            existing_mode = os.lstat(name, dir_fd=parent_fd).st_mode
        except FileNotFoundError:
            existing_mode = None
        if existing_mode is not None and stat.S_ISLNK(existing_mode):
            _fail("CG1_GM_CANDIDATE_PATH_INVALID", f"The {label} directory is a symlink.")
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            except OSError as exc:
                _fail(
                    "CG1_GM_CANDIDATE_PATH_INVALID" if exc.errno == errno.ELOOP else "CG1_GM_CANDIDATE_WRITE_FAILED",
                    f"The {label} directory could not be created safely.",
                    details={"cause": type(exc).__name__},
                    status_code=500,
                )
        try:
            return os.open(name, self._dir_flags(), dir_fd=parent_fd)
        except OSError as exc:
            _fail(
                "CG1_GM_CANDIDATE_PATH_INVALID" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "CG1_GM_CANDIDATE_PAYLOAD_MISSING",
                f"The {label} directory is unavailable or is a symlink.",
                details={"label": label},
            )

    def _open_relative_dir(self, parent_fd: int, parts: tuple[str, ...], *, create: bool, label: str) -> int:
        current = os.dup(parent_fd)
        try:
            for part in parts:
                child = self._open_child_dir(current, part, create=create, label=label)
                os.close(current)
                current = child
            return current
        except Exception:
            os.close(current)
            raise

    @staticmethod
    def _read_regular_at(parent_fd: int, name: str, *, label: str) -> bytes:
        if not isinstance(name, str) or not name or "/" in name or "\\" in name or name in {".", ".."}:
            _fail("CG1_GM_CANDIDATE_PATH_INVALID", f"The {label} filename is invalid.")
        try:
            fd = os.open(name, CandidateGMCapsuleStore._read_flags(), dir_fd=parent_fd)
        except FileNotFoundError:
            _fail("CG1_GM_CANDIDATE_PAYLOAD_MISSING", f"The staged {label} is missing.")
        except OSError as exc:
            _fail(
                "CG1_GM_CANDIDATE_PATH_INVALID" if exc.errno == errno.ELOOP else "CG1_GM_CANDIDATE_PAYLOAD_INVALID",
                f"The staged {label} cannot be opened safely.",
                details={"cause": type(exc).__name__},
            )
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                _fail("CG1_GM_CANDIDATE_PATH_INVALID", f"The staged {label} is not a regular file.")
            return os.fdopen(fd, "rb").read()
        except FoundryError:
            os.close(fd)
            raise
        except OSError as exc:
            _fail("CG1_GM_CANDIDATE_PAYLOAD_INVALID", f"The staged {label} cannot be read.", details={"cause": type(exc).__name__})

    @staticmethod
    def _write_immutable_at(parent_fd: int, name: str, payload: bytes, *, label: str) -> None:
        if not isinstance(name, str) or not name or "/" in name or "\\" in name or name in {".", ".."}:
            _fail("CG1_GM_CANDIDATE_PATH_INVALID", f"The immutable {label} filename is invalid.")
        try:
            existing_fd = os.open(name, CandidateGMCapsuleStore._read_flags(), dir_fd=parent_fd)
        except FileNotFoundError:
            existing_fd = None
        except OSError as exc:
            _fail(
                "CG1_GM_CANDIDATE_PATH_INVALID" if exc.errno == errno.ELOOP else "CG1_GM_CANDIDATE_PAYLOAD_INVALID",
                f"The immutable {label} cannot be opened safely.",
                details={"cause": type(exc).__name__},
            )
        if existing_fd is not None:
            try:
                if not stat.S_ISREG(os.fstat(existing_fd).st_mode):
                    _fail("CG1_GM_CANDIDATE_PATH_INVALID", f"The immutable {label} is not a regular file.")
                existing = os.fdopen(existing_fd, "rb").read()
            except FoundryError:
                os.close(existing_fd)
                raise
            if existing != payload:
                _fail("CG1_GM_CANDIDATE_IMMUTABLE_COLLISION", f"The immutable {label} already contains different bytes.")
            return
        temporary = f".{name}.{os.getpid()}.{threading.get_ident()}.new"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=parent_fd)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
                os.unlink(temporary, dir_fd=parent_fd)
            except FileExistsError:
                os.unlink(temporary, dir_fd=parent_fd)
                CandidateGMCapsuleStore._write_immutable_at(parent_fd, name, payload, label=label)
            os.fsync(parent_fd)
        except FoundryError:
            raise
        except OSError as exc:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except OSError:
                pass
            _fail("CG1_GM_CANDIDATE_WRITE_FAILED", f"The immutable {label} could not be written safely.", details={"cause": type(exc).__name__}, status_code=500)

    @staticmethod
    def _write_pointer_at(parent_fd: int, name: str, payload: bytes) -> None:
        if name != "current.json":
            _fail("CG1_GM_CANDIDATE_PATH_INVALID", "The capsule pointer filename is invalid.")
        try:
            existing_fd = os.open(name, CandidateGMCapsuleStore._read_flags(), dir_fd=parent_fd)
        except FileNotFoundError:
            existing_fd = None
        except OSError as exc:
            _fail("CG1_GM_CANDIDATE_PATH_INVALID", "The capsule pointer is unavailable or is a symlink.", details={"cause": type(exc).__name__})
        if existing_fd is not None:
            os.close(existing_fd)
        temporary = f".{name}.{os.getpid()}.{threading.get_ident()}.new"
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=parent_fd)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            os.fsync(parent_fd)
        except OSError as exc:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except OSError:
                pass
            _fail("CG1_GM_CANDIDATE_WRITE_FAILED", "The capsule pointer could not be written safely.", details={"cause": type(exc).__name__}, status_code=500)

    @staticmethod
    def _row_query(db: Any, query: str, args: tuple[Any, ...]) -> list[Any]:
        try:
            with db.connection() as conn:
                return list(conn.execute(query, args).fetchall())
        except sqlite3.Error as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_UNAVAILABLE",
                "The authenticated source database does not expose the required evidence.",
                details={"cause": type(exc).__name__},
            )

    @staticmethod
    def _one_query(db: Any, query: str, args: tuple[Any, ...]) -> Any:
        try:
            with db.connection() as conn:
                return conn.execute(query, args).fetchone()
        except sqlite3.Error as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_UNAVAILABLE",
                "The authenticated source database does not expose the required evidence.",
                details={"cause": type(exc).__name__},
            )

    @staticmethod
    def _project_lock_proof(db: Any, project_id: str) -> Mapping[str, Any]:
        """Prove immutable project membership through the existing pack-seal path."""
        try:
            from project_store.service import ProjectStore, ensure_project_lock_proof_cache_scope

            project_store = ProjectStore(db)
            with db.connection() as conn, ensure_project_lock_proof_cache_scope():
                proof = project_store.project_lock_proof(conn, project_id)
                sealed_member_records: list[dict[str, Any]] = []
                for lock in proof.get("locks", ()):
                    # The proof above verified this seal inside the same
                    # scope; reuse it instead of re-reading the whole pack.
                    seal = project_store.verified_pack_seal(
                        conn, lock["pack_id"], lock["version"], lock["pack_hash"],
                    )
                    sealed_member_records.extend(
                        {
                            "record_id": member["record_id"],
                            "record_hash": member["record_hash"],
                            "pack_id": member["pack_id"],
                            "pack_version": member["pack_version"],
                            "record_json": member["record_json"],
                        }
                        for member in seal.records
                    )
                sealed_member_ids = {member["record_id"] for member in sealed_member_records}
                actual_rows = conn.execute(
                    "SELECT record_id,pack_id,pack_version,record_hash,record_json "
                    "FROM project_locked_records WHERE project_id=? ORDER BY record_id",
                    (project_id,),
                ).fetchall()
                authorized_extra_records = [
                    {
                        "record_id": row["record_id"],
                        "record_hash": row["record_hash"],
                        "pack_id": row["pack_id"],
                        "pack_version": row["pack_version"],
                        "record_json": row["record_json"],
                    }
                    for row in actual_rows
                    if row["record_id"] not in sealed_member_ids
                ]
        except FoundryError as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The project lock proof cannot authenticate the Foundation source snapshot.",
                details={"project_id": project_id, "cause": exc.code},
            )
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The project lock proof is unavailable for the Foundation source snapshot.",
                details={"project_id": project_id, "cause": type(exc).__name__},
            )
        if not isinstance(proof, Mapping) or not isinstance(proof.get("record_snapshot_hash"), str):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The project lock proof is malformed for the Foundation source snapshot.",
                details={"project_id": project_id},
            )
        return {
            **proof,
            "sealed_member_records": sorted(sealed_member_records, key=lambda row: row["record_id"]),
            "authorized_extra_records": sorted(authorized_extra_records, key=lambda row: row["record_id"]),
        }

    @staticmethod
    def _assert_project_lock_snapshot(
        proof: Mapping[str, Any],
        record_rows: list[Any],
        *,
        project_id: str,
    ) -> None:
        sealed_member_records = proof.get("sealed_member_records")
        authorized_extra_records = proof.get("authorized_extra_records")
        if not isinstance(sealed_member_records, (list, tuple)) or not isinstance(authorized_extra_records, (list, tuple)):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The project lock proof lacks its authenticated sealed-member identities.",
                details={"project_id": project_id},
            )
        sealed_by_id = {
            row.get("record_id"): row
            for row in sealed_member_records
            if isinstance(row, Mapping) and isinstance(row.get("record_id"), str)
        }
        extra_by_id = {
            row.get("record_id"): row
            for row in authorized_extra_records
            if isinstance(row, Mapping) and isinstance(row.get("record_id"), str)
        }
        if len(sealed_by_id) != len(sealed_member_records) or len(extra_by_id) != len(authorized_extra_records) or set(sealed_by_id) & set(extra_by_id):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The project lock proof has conflicting authenticated record identities.",
                details={"project_id": project_id},
            )
        rows_by_id: dict[str, Any] = {}
        for row in record_rows:
            record_id = row["record_id"]
            if not isinstance(record_id, str) or record_id in rows_by_id:
                _fail(
                    "CG1_GM_CANDIDATE_SOURCE_INVALID",
                    "The project lock snapshot contains a duplicate or invalid record identity.",
                    details={"project_id": project_id, "record_id": record_id},
                )
            rows_by_id[record_id] = row
        trusted_ids = set(sealed_by_id) | set(extra_by_id)
        if trusted_ids != set(rows_by_id):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The project lock proof does not cover the exact Foundation source snapshot.",
                details={"project_id": project_id},
            )
        ordered_ids = sorted(sealed_by_id) + sorted(extra_by_id)
        snapshot_rows = []
        for record_id in ordered_ids:
            row = rows_by_id[record_id]
            record_json = row["record_json"]
            if not isinstance(record_json, str):
                _fail(
                    "CG1_GM_CANDIDATE_SOURCE_INVALID",
                    "The project lock snapshot contains a non-text record document.",
                    details={"project_id": project_id, "record_id": row["record_id"]},
                )
            expected = sealed_by_id.get(record_id) or extra_by_id.get(record_id)
            if any(
                row[field] != expected.get(field)
                for field in ("record_hash", "pack_id", "pack_version", "record_json")
            ):
                _fail(
                    "CG1_GM_CANDIDATE_SOURCE_INVALID",
                    "The project lock proof does not cover the exact Foundation source bytes.",
                    details={"project_id": project_id, "record_id": record_id},
                )
            snapshot_rows.append(
                {
                    "record_id": row["record_id"],
                    "record_hash": row["record_hash"],
                    "pack_id": row["pack_id"],
                    "pack_version": row["pack_version"],
                }
            )
        if proof.get("record_snapshot_hash") != sha256_json(snapshot_rows):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The project lock proof does not cover the exact Foundation source snapshot.",
                details={"project_id": project_id},
            )

    @staticmethod
    def _resolve_versioned_method_snapshot(
        db: Any,
        *,
        record_id: str,
        raw_record: Mapping[str, Any],
        row_pack_id: Any,
        row_pack_version: Any,
        method_version: str,
        row_pack_hash: Any = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Resolve the exact authenticated Method version used by the producer.

        Method mechanics are a server-selected derivation over the immutable
        legacy row.  The Character Sheet projector consumes that derived
        record, while the candidate database intentionally retains the
        original source row.  Rebuild both versions through the installed
        authority and retain the raw row identity alongside the resolved map
        entry; never accept a card hash by label or by a live-catalog lookup.
        """
        if not isinstance(method_version, str) or not method_version:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The versioned Method source binding is missing its selected version.",
                details={"record_id": record_id},
            )
        from app.core import CORE_PACK_ID
        from character_creation.compiler_selection_authority import (
            ACCEPTED_CORE_PACK_HASHES_BY_VERSION,
        )

        non_sphere_pack_id = "tianxia.non_sphere.authority"
        if row_pack_id not in {non_sphere_pack_id, CORE_PACK_ID}:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The versioned Method source row is bound to an unexpected authority pack.",
                details={"record_id": record_id, "pack_id": row_pack_id},
            )
        is_core_snapshot = row_pack_id == CORE_PACK_ID
        if is_core_snapshot:
            expected_pack_hash = ACCEPTED_CORE_PACK_HASHES_BY_VERSION.get(row_pack_version)
            if expected_pack_hash is None or row_pack_hash != expected_pack_hash:
                _fail(
                    "CG1_GM_CANDIDATE_SOURCE_INVALID",
                    "The versioned core Method source row is not bound to an accepted pack release.",
                    details={
                        "record_id": record_id,
                        "pack_id": row_pack_id,
                        "pack_version": row_pack_version,
                    },
                )
            raw_binding = raw_record.get("content_binding")
            if (
                not isinstance(raw_binding, Mapping)
                or raw_binding.get("pack_id") != CORE_PACK_ID
                or raw_binding.get("pack_version") != row_pack_version
                or raw_binding.get("pack_hash") != expected_pack_hash
            ):
                _fail(
                    "CG1_GM_CANDIDATE_SOURCE_INVALID",
                    "The immutable core Method source row is not bound to its locked pack release.",
                    details={"record_id": record_id, "pack_version": row_pack_version},
                )
        try:
            authority = _non_sphere_authority_for(db)
            if is_core_snapshot:
                # Core rows are immutable legacy source snapshots.  The
                # installed non-sphere authority authenticates their source
                # fields before projecting the exact typed Method record.
                source_projection = authority.project_locked_method_catalog_record(
                    record_id,
                    snapshot_record=dict(raw_record),
                )
            else:
                source_projection = authority.reconstruct_locked_method_catalog_record({
                    "record_id": record_id,
                    "content_binding": {
                        "pack_id": row_pack_id,
                        "pack_version": row_pack_version,
                    },
                })
            resolved_projection = authority.reconstruct_locked_method_catalog_record({
                "record_id": record_id,
                "content_binding": {
                    "pack_id": non_sphere_pack_id,
                    "pack_version": method_version,
                },
            })
        except FoundryError as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Method version does not reproduce from authenticated authority.",
                details={"record_id": record_id, "cause": exc.code},
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Method version authority is unavailable or malformed.",
                details={"record_id": record_id, "cause": type(exc).__name__},
            )
        if not is_core_snapshot and canonical_json(source_projection) != canonical_json(dict(raw_record)):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The immutable Method source row does not reproduce from authenticated authority.",
                details={"record_id": record_id, "pack_version": row_pack_version},
            )
        if (
            resolved_projection.get("record_id") != record_id
            or resolved_projection.get("record_hash") != canonical_record_hash(resolved_projection)
            or (resolved_projection.get("content_binding") or {}).get("pack_id") != non_sphere_pack_id
            or (resolved_projection.get("content_binding") or {}).get("pack_version") != method_version
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Method version is not canonically bound to its authority identity.",
                details={"record_id": record_id, "pack_version": method_version},
            )
        raw_identity = {
            "project_locked_pack_id": row_pack_id,
            "project_locked_pack_version": row_pack_version,
            "project_locked_record_hash": raw_record.get("record_hash"),
            "project_locked_record_json_sha256": sha256_bytes(canonical_json(dict(raw_record)).encode("utf-8")),
        }
        if row_pack_hash is not None:
            raw_identity["project_locked_pack_hash"] = row_pack_hash
        return resolved_projection, raw_identity

    @staticmethod
    def _resolve_versioned_foundation_snapshot(
        db: Any,
        *,
        record_id: str,
        raw_record: Mapping[str, Any],
        row_pack_id: Any,
        row_pack_version: Any,
        foundation_version: str | None,
        row_pack_hash: Any = None,
        sealed_record_hash: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Resolve the exact Foundation projection selected by the request.

        Foundation cards are built from the typed P2A or initial-mechanics
        projection, while the project database retains the immutable Core
        source row.  Keep those identities separate and require the raw row's
        pack, canonical hash, and source-backed projection to authenticate
        before exposing the derived card record.
        """
        from app.core import CORE_PACK_ID
        from character_creation.compiler_selection_authority import (
            ACCEPTED_CORE_PACK_HASHES_BY_VERSION,
        )
        from non_sphere_authority.foundation_mechanics import (
            FOUNDATION_MECHANICS_PACK_VERSION,
        )

        non_sphere_pack_id = "tianxia.non_sphere.authority"
        if foundation_version not in {None, FOUNDATION_MECHANICS_PACK_VERSION}:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Foundation derivation is not supported by the sealed request.",
                details={"record_id": record_id, "pack_version": foundation_version},
            )
        if (
            not isinstance(raw_record, Mapping)
            or raw_record.get("record_id") not in {None, record_id}
            or raw_record.get("content_type") != "foundation"
            or raw_record.get("record_hash") != canonical_record_hash(dict(raw_record))
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The immutable Foundation source row is not canonically authenticated.",
                details={"record_id": record_id},
            )
        if not isinstance(sealed_record_hash, str) or raw_record.get("record_hash") != sealed_record_hash:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Foundation source row is not the exact sealed project member.",
                details={"record_id": record_id},
            )
        compatibility = raw_record.get("compatibility")
        factory = compatibility.get("factory") if isinstance(compatibility, Mapping) else None
        if not isinstance(factory, Mapping):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The immutable Foundation source row has an invalid factory compatibility shape.",
                details={"record_id": record_id},
            )
        raw_projection = factory.get("raw_projection")
        nested_source = raw_projection.get("raw_record") if isinstance(raw_projection, Mapping) else None
        if not isinstance(nested_source, Mapping) or nested_source.get("foundation_id") != record_id:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The immutable Foundation source row has no matching source-backed record identity.",
                details={"record_id": record_id},
            )
        raw_binding = raw_record.get("content_binding")
        if (
            not isinstance(raw_binding, Mapping)
            or raw_binding.get("pack_id") != row_pack_id
            or raw_binding.get("pack_version") != row_pack_version
            or (row_pack_hash is not None and raw_binding.get("pack_hash") != row_pack_hash)
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The immutable Foundation source row does not match its locked pack binding.",
                details={
                    "record_id": record_id,
                    "pack_id": row_pack_id,
                    "pack_version": row_pack_version,
                },
            )
        expected_pack_hash = ACCEPTED_CORE_PACK_HASHES_BY_VERSION.get(row_pack_version)
        if (
            row_pack_id != CORE_PACK_ID
            or expected_pack_hash is None
            or row_pack_hash != expected_pack_hash
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Foundation source row is not bound to an accepted Core pack release.",
                details={
                    "record_id": record_id,
                    "pack_id": row_pack_id,
                    "pack_version": row_pack_version,
                },
            )
        try:
            authority = _non_sphere_authority_for(db)
            # Rebuild the legacy projection first.  Besides retaining the
            # historical P2A route, this proves the source-backed raw
            # projection is complete before a mechanics derivation can use it.
            authority.project_locked_foundation_catalog_record(
                record_id,
                snapshot_record=dict(raw_record),
                mechanical=False,
            )
            resolved_projection = authority.project_locked_foundation_catalog_record(
                record_id,
                snapshot_record=dict(raw_record),
                mechanical=foundation_version == FOUNDATION_MECHANICS_PACK_VERSION,
            )
        except FoundryError as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Foundation version does not reproduce from authenticated authority.",
                details={"record_id": record_id, "cause": exc.code},
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Foundation authority is unavailable or malformed.",
                details={"record_id": record_id, "cause": type(exc).__name__},
            )
        expected_version = foundation_version or "P2A"
        binding = resolved_projection.get("content_binding")
        if (
            resolved_projection.get("record_id") != record_id
            or resolved_projection.get("content_type") != "foundation"
            or resolved_projection.get("record_hash") != canonical_record_hash(resolved_projection)
            or not isinstance(binding, Mapping)
            or binding.get("pack_id") != non_sphere_pack_id
            or binding.get("pack_version") != expected_version
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Foundation version is not canonically bound to its authority identity.",
                details={"record_id": record_id, "pack_version": expected_version},
            )
        raw_identity = {
            "project_locked_pack_id": row_pack_id,
            "project_locked_pack_version": row_pack_version,
            "project_locked_record_hash": raw_record.get("record_hash"),
            "project_locked_record_json_sha256": sha256_bytes(canonical_json(dict(raw_record)).encode("utf-8")),
        }
        if row_pack_hash is not None:
            raw_identity["project_locked_pack_hash"] = row_pack_hash
        return resolved_projection, raw_identity

    @staticmethod
    def _resolve_origin_insight_snapshot(
        db: Any,
        *,
        project_id: str,
        record_id: str,
        raw_record: Mapping[str, Any],
        row_pack_id: Any,
        row_pack_version: Any,
        row_pack_hash: Any = None,
        sealed_record_hash: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Resolve the authenticated Stage-2 projection for an Origin Insight.

        Origin Insight cards are projected from the immutable catalog row by
        ProjectStore: the source-backed record receives the Stage-2 authority
        needed by the executable acquisition route.  The candidate context
        must compare cards with that derived record while retaining the raw
        project-lock identity separately.
        """
        if (
            not isinstance(raw_record, Mapping)
            or raw_record.get("record_id") not in {None, record_id}
            or raw_record.get("content_type") != "origin_insight"
            or raw_record.get("record_hash") != canonical_record_hash(dict(raw_record))
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The immutable Origin Insight source row is not canonically authenticated.",
                details={"record_id": record_id},
            )
        if not isinstance(sealed_record_hash, str) or raw_record.get("record_hash") != sealed_record_hash:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Origin Insight source row is not the exact sealed project member.",
                details={"record_id": record_id},
            )
        if not isinstance(row_pack_hash, str) or not row_pack_hash:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Origin Insight source row has no unambiguous locked pack hash.",
                details={"record_id": record_id},
            )
        raw_binding = raw_record.get("content_binding")
        if (
            not isinstance(raw_binding, Mapping)
            or raw_binding.get("pack_id") != row_pack_id
            or raw_binding.get("pack_version") != row_pack_version
            or (row_pack_hash is not None and raw_binding.get("pack_hash") != row_pack_hash)
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Origin Insight source row does not match its locked pack binding.",
                details={
                    "record_id": record_id,
                    "pack_id": row_pack_id,
                    "pack_version": row_pack_version,
                },
            )
        try:
            from project_store.service import ProjectStore

            project_store = ProjectStore(db)
            with db.connection() as conn:
                row = conn.execute(
                    "SELECT record_hash,record_json FROM project_locked_records "
                    "WHERE project_id=? AND record_id=?",
                    (project_id, record_id),
                ).fetchone()
                if (
                    row is None
                    or row["record_hash"] != sealed_record_hash
                    or row["record_json"] != canonical_json(dict(raw_record))
                ):
                    _fail(
                        "CG1_GM_CANDIDATE_SOURCE_INVALID",
                        "The Origin Insight source row changed outside its authenticated lock proof.",
                        details={"record_id": record_id},
                    )
                resolved_projection = project_store._resolve_project_locked_origin_insight_after_proof(
                    conn,
                    project_id,
                    record_id,
                )
        except FoundryError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The authenticated Origin Insight authority is unavailable or malformed.",
                details={"record_id": record_id, "cause": type(exc).__name__},
            )
        if not isinstance(resolved_projection, Mapping):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Origin Insight has no authenticated Stage-2 projection.",
                details={"record_id": record_id},
            )
        resolved_projection = dict(resolved_projection)
        resolved_binding = resolved_projection.get("content_binding")
        resolved_compatibility = resolved_projection.get("compatibility")
        resolved_factory = (
            resolved_compatibility.get("factory")
            if isinstance(resolved_compatibility, Mapping)
            else None
        )
        stage2_authority = (
            resolved_factory.get("stage2_authority")
            if isinstance(resolved_factory, Mapping)
            else None
        )
        allowed_kinds = stage2_authority.get("allowed_kinds") if isinstance(stage2_authority, Mapping) else None
        allowed_channels = stage2_authority.get("allowed_channels") if isinstance(stage2_authority, Mapping) else None
        expected_channels = (raw_record.get("legality") or {}).get("acquisition_channels")
        raw_factory = (
            (raw_record.get("compatibility") or {}).get("factory")
            if isinstance(raw_record.get("compatibility"), Mapping)
            else None
        )
        raw_stage2_authority = raw_factory.get("stage2_authority") if isinstance(raw_factory, Mapping) else None
        expected_rule_id = (
            raw_stage2_authority.get("rule_id")
            if isinstance(raw_stage2_authority, Mapping)
            and raw_stage2_authority.get("authority_complete") is True
            else f"catalog.{record_id}.origin-insight-acquisition.v1"
        )
        if (
            resolved_projection.get("record_id") != record_id
            or resolved_projection.get("content_type") != "origin_insight"
            or resolved_projection.get("record_hash") != canonical_record_hash(resolved_projection)
            or not isinstance(resolved_binding, Mapping)
            or resolved_binding.get("pack_id") != row_pack_id
            or resolved_binding.get("pack_version") != row_pack_version
            or resolved_binding.get("pack_hash") != row_pack_hash
            or not isinstance(stage2_authority, Mapping)
            or stage2_authority.get("authority_complete") is not True
            or not isinstance(allowed_kinds, list)
            or "origin_insight_acquisition" not in allowed_kinds
            or not isinstance(allowed_channels, list)
            or not isinstance(expected_channels, list)
            or not set(expected_channels).issubset(set(allowed_channels))
            or stage2_authority.get("rule_id") != expected_rule_id
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Origin Insight projection is not canonically bound to its source authority.",
                details={"record_id": record_id},
            )
        raw_identity = {
            "project_locked_pack_id": row_pack_id,
            "project_locked_pack_version": row_pack_version,
            "project_locked_record_hash": raw_record.get("record_hash"),
            "project_locked_record_json_sha256": sha256_bytes(canonical_json(dict(raw_record)).encode("utf-8")),
        }
        if row_pack_hash is not None:
            raw_identity["project_locked_pack_hash"] = row_pack_hash
        return resolved_projection, raw_identity

    @staticmethod
    def _is_background_family_record(record_id: Any, record: Mapping[str, Any] | None = None) -> bool:
        """Return whether a selected card is an owner-facing Background record.

        ProjectStore projects Background, Background Sphere and Background
        Talent rows with the typed non-Sphere authority (see
        ``_resolve_project_locked_background_after_proof``) and the projector
        renders cards from that projection, so their card hash is never the
        raw locked hash.
        """
        if not isinstance(record_id, str):
            return False
        if not record_id.startswith(("tianxia.background.", "tianxia.background_")):
            return False
        if record is None:
            return True
        return record.get("content_type") in {"background", "background_sphere", "background_talent"}

    @staticmethod
    def _without_stage2_authority(record: Mapping[str, Any]) -> dict[str, Any]:
        """Strip the server-owned Stage-2 authority block and hash for comparison."""
        value = deepcopy(dict(record))
        value.pop("record_hash", None)
        compatibility = value.get("compatibility")
        if isinstance(compatibility, dict):
            factory = compatibility.get("factory")
            if isinstance(factory, dict):
                factory.pop("stage2_authority", None)
                if not factory:
                    compatibility.pop("factory", None)
        return value

    @staticmethod
    def _load_sealed_locked_record(conn: Any, project_id: str, record_id: str) -> tuple[dict[str, Any], str] | None:
        row = conn.execute(
            "SELECT record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, record_id),
        ).fetchone()
        if row is None:
            return None
        record = json.loads(row["record_json"])
        if (
            not isinstance(record, dict)
            or canonical_json(record) != row["record_json"]
            or record.get("record_hash") != row["record_hash"]
            or canonical_record_hash(record) != row["record_hash"]
        ):
            return None
        return record, str(row["record_hash"])

    def _resolve_background_projection_snapshot(
        self,
        db: Any,
        *,
        project_id: str,
        record_id: str,
        raw_record: Mapping[str, Any],
        row_pack_id: Any,
        row_pack_version: Any,
        row_pack_hash: Any = None,
        sealed_record_hash: str | None = None,
        project_store: Any = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Resolve the authenticated Stage-2 projection for a Background-family card.

        Mirrors ``_resolve_origin_insight_snapshot``: the immutable locked row
        is authenticated first, then the same ProjectStore projection the
        projector used is rebuilt and accepted only when it is exactly the
        sealed record (or, for Background Sphere/Talent aliases, exactly the
        sealed canonical Sphere/Talent member) plus a complete typed Stage-2
        authority block.  Canonical Sphere/Talent rows that a Background
        package promoted go through the same gate with the background-content
        projection.  The raw project-lock identity is retained separately.
        """
        content_type = raw_record.get("content_type") if isinstance(raw_record, Mapping) else None
        background_shaped = self._is_background_family_record(record_id, raw_record)
        background_content = content_type in {"sphere", "talent"} and not background_shaped
        if (
            not isinstance(raw_record, Mapping)
            or raw_record.get("record_id") not in {None, record_id}
            or not (background_shaped or background_content)
            or raw_record.get("record_hash") != canonical_record_hash(dict(raw_record))
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The immutable Background-family source row is not canonically authenticated.",
                details={"record_id": record_id},
            )
        if not isinstance(sealed_record_hash, str) or raw_record.get("record_hash") != sealed_record_hash:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Background-family source row is not the exact sealed project member.",
                details={"record_id": record_id},
            )
        if not isinstance(row_pack_hash, str) or not row_pack_hash:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Background-family source row has no unambiguous locked pack hash.",
                details={"record_id": record_id},
            )
        raw_binding = raw_record.get("content_binding")
        if (
            not isinstance(raw_binding, Mapping)
            or raw_binding.get("pack_id") != row_pack_id
            or raw_binding.get("pack_version") != row_pack_version
            or raw_binding.get("pack_hash") != row_pack_hash
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Background-family source row does not match its locked pack binding.",
                details={"record_id": record_id, "pack_id": row_pack_id, "pack_version": row_pack_version},
            )
        base_record: dict[str, Any] | None = None
        base_hash: str | None = None
        try:
            if project_store is None:
                from project_store.service import ProjectStore

                project_store = ProjectStore(db)
            with db.connection() as conn:
                sealed = self._load_sealed_locked_record(conn, project_id, record_id)
                if sealed is None or sealed[1] != sealed_record_hash or sealed[0] != dict(raw_record):
                    _fail(
                        "CG1_GM_CANDIDATE_SOURCE_INVALID",
                        "The Background-family source row changed outside its authenticated lock proof.",
                        details={"record_id": record_id},
                    )
                if background_shaped:
                    resolved_projection = project_store._resolve_project_locked_background_after_proof(
                        conn, project_id, record_id
                    )
                else:
                    resolved_projection = project_store._resolve_project_locked_background_content_after_proof(
                        conn, project_id, record_id
                    )
                if isinstance(resolved_projection, Mapping):
                    projected_id = resolved_projection.get("record_id")
                    if projected_id == record_id:
                        base_record, base_hash = dict(raw_record), sealed_record_hash
                    elif isinstance(projected_id, str) and projected_id.startswith(("tianxia.sphere.", "tianxia.talent.", "TAL_")):
                        base = self._load_sealed_locked_record(conn, project_id, projected_id)
                        if base is not None:
                            base_record, base_hash = base
        except FoundryError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError, KeyError) as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The authenticated Background authority is unavailable or malformed.",
                details={"record_id": record_id, "cause": type(exc).__name__},
            )
        if not isinstance(resolved_projection, Mapping) or base_record is None:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Background-family card has no authenticated Stage-2 projection.",
                details={"record_id": record_id},
            )
        resolved_projection = dict(resolved_projection)
        resolved_binding = resolved_projection.get("content_binding")
        base_binding = base_record.get("content_binding")
        resolved_compatibility = resolved_projection.get("compatibility")
        resolved_factory = resolved_compatibility.get("factory") if isinstance(resolved_compatibility, Mapping) else None
        stage2_authority = resolved_factory.get("stage2_authority") if isinstance(resolved_factory, Mapping) else None
        allowed_kinds = stage2_authority.get("allowed_kinds") if isinstance(stage2_authority, Mapping) else None
        allowed_channels = stage2_authority.get("allowed_channels") if isinstance(stage2_authority, Mapping) else None
        raw_factory = (
            (raw_record.get("compatibility") or {}).get("factory")
            if isinstance(raw_record.get("compatibility"), Mapping)
            else None
        )
        raw_stage2_authority = raw_factory.get("stage2_authority") if isinstance(raw_factory, Mapping) else None
        raw_authority_complete = (
            isinstance(raw_stage2_authority, Mapping)
            and raw_stage2_authority.get("authority_complete") is True
        )
        if record_id.startswith("tianxia.background."):
            required_kinds = {"background_acquisition"}
            required_channels = {"background-selection"}
            # A sealed row that already carried complete typed authority is
            # returned unchanged by ProjectStore; otherwise the projection is
            # the NS1R Background route rule bound to the authority snapshot.
            expected_rule_id: str | None = (
                raw_stage2_authority.get("rule_id")
                if raw_authority_complete
                else f"ns1r.{record_id}.background-acquisition.v1"
            )
            alias = False
        elif record_id.startswith("tianxia.background_sphere."):
            required_kinds = {"background_sphere_acquisition"}
            required_channels = {"background-grant"}
            expected_rule_id = None
            alias = True
        elif record_id.startswith("tianxia.background_talent."):
            required_kinds = {"background_talent_acquisition"}
            required_channels = {"background-grant"}
            expected_rule_id = None
            alias = True
        else:
            required_kinds = {"background_sphere_acquisition" if content_type == "sphere" else "background_talent_acquisition"}
            required_channels = {"background-grant"}
            expected_rule_id = None
            alias = False
        if (
            (alias and resolved_projection.get("record_id") == record_id)
            or (not alias and resolved_projection.get("record_id") != record_id)
            or resolved_projection.get("record_hash") != canonical_record_hash(resolved_projection)
            or not isinstance(resolved_binding, Mapping)
            or not isinstance(base_binding, Mapping)
            or resolved_binding != base_binding
            or self._without_stage2_authority(resolved_projection) != self._without_stage2_authority(base_record)
            or not isinstance(stage2_authority, Mapping)
            or stage2_authority.get("authority_complete") is not True
            or not isinstance(allowed_kinds, list)
            or not required_kinds.issubset(set(allowed_kinds))
            or not isinstance(allowed_channels, list)
            or not required_channels.issubset(set(allowed_channels))
            or (expected_rule_id is not None and stage2_authority.get("rule_id") != expected_rule_id)
            or (
                record_id.startswith("tianxia.background.")
                and not raw_authority_complete
                and not re.fullmatch(r"[0-9a-f]{64}", str(stage2_authority.get("source_authority_snapshot_hash") or ""))
            )
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Background-family projection is not canonically bound to its source authority.",
                details={"record_id": record_id, "projected_record_id": resolved_projection.get("record_id")},
            )
        raw_identity: dict[str, Any] = {
            "project_locked_pack_id": row_pack_id,
            "project_locked_pack_version": row_pack_version,
            "project_locked_pack_hash": row_pack_hash,
            "project_locked_record_hash": raw_record.get("record_hash"),
            "project_locked_record_json_sha256": sha256_bytes(canonical_json(dict(raw_record)).encode("utf-8")),
        }
        if alias:
            raw_identity["binding_kind"] = "project_locked_background_alias"
            raw_identity["parent_record_id"] = resolved_projection.get("record_id")
            raw_identity["parent_record_hash"] = base_hash
            raw_identity["parent_record_json_sha256"] = sha256_bytes(canonical_json(base_record).encode("utf-8"))
        return resolved_projection, raw_identity

    @staticmethod
    def _is_path_family_record(record_id: Any, record: Mapping[str, Any] | None = None) -> bool:
        """Return whether a selected card needs the proof-bound Path resolver."""
        if not isinstance(record_id, str):
            return False
        # Spirit Awakening Traditions are the Subpath rows of that Path: the
        # ProjectStore subpath projection already covers both prefixes, and
        # their Character Sheet cards are rendered from that projection.
        if not record_id.startswith(("tianxia.path.", "tianxia.subpath.", "tianxia.tradition.")):
            return False
        if record is None:
            return True
        return record.get("content_type") in {"path", "path_feature", "subpath", "tradition"}

    @staticmethod
    def _is_path_milestone_record_id(record_id: Any) -> bool:
        """Path ``.clN`` rows are progression intent, never emitted cards."""
        return (
            isinstance(record_id, str)
            and record_id.startswith("tianxia.path.")
            and bool(re.search(r"\.cl\d+$", record_id))
        )

    def _resolve_path_family_snapshot(
        self,
        db: Any,
        *,
        project_id: str,
        record_id: str,
        raw_record: Mapping[str, Any],
        row_pack_id: Any,
        row_pack_version: Any,
        row_pack_hash: Any = None,
        sealed_record_hash: str | None = None,
        proof: Mapping[str, Any] | None = None,
        proof_record_rows: list[Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Project one selected Path-family card after exact lock authentication.

        ProjectStore owns the Path, Path Feature, and Subpath projections.  The
        candidate context authenticates the complete lock before invoking that
        resolver, and carries the immutable row identity alongside the derived
        card so a projection hash can never silently replace its source hash.
        """
        if self._is_path_milestone_record_id(record_id):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "A Path milestone identifier is progression intent, not a Character Sheet card.",
                details={"record_id": record_id},
            )
        if not self._is_path_family_record(record_id, raw_record):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Path-family source row has an unsupported record identity or type.",
                details={"record_id": record_id, "content_type": raw_record.get("content_type")},
            )
        if (
            raw_record.get("record_id") not in {None, record_id}
            or raw_record.get("record_hash") != canonical_record_hash(dict(raw_record))
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The immutable Path-family source row is not canonically authenticated.",
                details={"record_id": record_id},
            )
        if not isinstance(sealed_record_hash, str) or raw_record.get("record_hash") != sealed_record_hash:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Path-family source row is not the exact sealed project member.",
                details={"record_id": record_id},
            )
        raw_binding = raw_record.get("content_binding")
        if (
            not isinstance(raw_binding, Mapping)
            or raw_binding.get("pack_id") != row_pack_id
            or raw_binding.get("pack_version") != row_pack_version
            or (row_pack_hash is not None and raw_binding.get("pack_hash") != row_pack_hash)
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Path-family source row does not match its locked pack binding.",
                details={
                    "record_id": record_id,
                    "pack_id": row_pack_id,
                    "pack_version": row_pack_version,
                },
            )
        if not isinstance(row_pack_hash, str) or _SHA256_RE.fullmatch(row_pack_hash) is None:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The Path-family source row has no unambiguous locked pack hash.",
                details={"record_id": record_id, "pack_id": row_pack_id, "pack_version": row_pack_version},
            )
        try:
            from project_store.service import ProjectStore

            project_store = ProjectStore(db)
            if proof is None:
                proof = self._project_lock_proof(db, project_id)
            if proof_record_rows is None:
                proof_record_rows = self._row_query(
                    db,
                    "SELECT record_id,pack_id,pack_version,record_hash,record_json "
                    "FROM project_locked_records WHERE project_id=? ORDER BY record_id",
                    (project_id,),
                )
            self._assert_project_lock_snapshot(proof, proof_record_rows, project_id=project_id)
            with db.connection() as conn:
                row = conn.execute(
                    "SELECT pack_id,pack_version,record_hash,record_json "
                    "FROM project_locked_records WHERE project_id=? AND record_id=?",
                    (project_id, record_id),
                ).fetchone()
                if (
                    row is None
                    or row["pack_id"] != row_pack_id
                    or row["pack_version"] != row_pack_version
                    or row["record_hash"] != sealed_record_hash
                    or row["record_json"] != canonical_json(dict(raw_record))
                ):
                    _fail(
                        "CG1_GM_CANDIDATE_SOURCE_INVALID",
                        "The Path-family source row changed outside its authenticated lock proof.",
                        details={"record_id": record_id},
                    )
                authority = project_store._cached_non_sphere_authority()
                # The row above is the exact sealed lock member, so a Path the
                # model chose (not an owner lock) is authorized here as the
                # candidate's own delegated Path (multi-Path CL18 build,
                # 2026-09-23).
                delegated_path = record_id.split(".feature.", 1)[0] if record_id.startswith("tianxia.path.") else None
                resolved_projection = project_store._resolve_locked_record_after_proof(
                    conn,
                    project_id,
                    record_id,
                    authority_service=authority,
                    authorized_delegated_path_ids=[delegated_path] if delegated_path else None,
                )
                expected_authority_hash = getattr(authority, "authority_snapshot_hash", None)
        except FoundryError as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Path-family card does not reproduce from authenticated authority.",
                details={"record_id": record_id, "cause": exc.code},
            )
        except (OSError, sqlite3.Error, TypeError, ValueError, AttributeError) as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Path-family authority is unavailable or malformed.",
                details={"record_id": record_id, "cause": type(exc).__name__},
            )
        if not isinstance(resolved_projection, Mapping):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Path-family card has no authenticated projection.",
                details={"record_id": record_id},
            )
        resolved_projection = dict(resolved_projection)
        resolved_binding = resolved_projection.get("content_binding")
        if (
            resolved_projection.get("record_id") != record_id
            or resolved_projection.get("content_type") not in {"path", "path_feature", "subpath"}
            or resolved_projection.get("record_hash") != canonical_record_hash(resolved_projection)
            or not isinstance(resolved_binding, Mapping)
            or resolved_binding.get("pack_id") != "tianxia.non_sphere.authority"
            or not isinstance(resolved_binding.get("pack_version"), str)
            or not isinstance(resolved_binding.get("pack_hash"), str)
            or _SHA256_RE.fullmatch(resolved_binding.get("pack_hash")) is None
            or (expected_authority_hash is not None and resolved_binding.get("pack_hash") != expected_authority_hash)
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The selected Path-family projection is not canonically bound to its authority identity.",
                details={
                    "record_id": record_id,
                    "resolved_pack_id": resolved_binding.get("pack_id") if isinstance(resolved_binding, Mapping) else None,
                    "resolved_pack_version": resolved_binding.get("pack_version") if isinstance(resolved_binding, Mapping) else None,
                },
            )
        raw_identity = {
            "project_locked_pack_id": row_pack_id,
            "project_locked_pack_version": row_pack_version,
            "project_locked_pack_hash": row_pack_hash,
            "project_locked_record_hash": raw_record.get("record_hash"),
            "project_locked_record_json_sha256": sha256_bytes(canonical_json(dict(raw_record)).encode("utf-8")),
        }
        return resolved_projection, raw_identity

    def _project_snapshot(
        self,
        db: Any,
        project_id: str,
        *,
        label: str,
        method_version: str | None = None,
        foundation_version: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
        row = self._one_query(
            db,
            "SELECT project_id,revision,project_json,canonical_project_hash FROM projects WHERE project_id=?",
            (project_id,),
        )
        if row is None:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                f"The {label} project is missing from the authenticated source database.",
                details={"project_id": project_id},
            )
        raw_project, project = _canonical_db_json(row["project_json"], f"{label} project")
        if not isinstance(project, dict) or project.get("project_id") not in {None, project_id}:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                f"The {label} project identity is inconsistent.",
                details={"project_id": project_id},
            )
        project_revision = row["revision"]
        if type(project_revision) is not int or project_revision < 0:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                f"The {label} project revision is invalid.",
            )
        stored_project_hash = row["canonical_project_hash"]
        if stored_project_hash != sha256_json(project):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                f"The {label} project hash does not authenticate its bytes.",
                details={"project_id": project_id},
            )
        content_lock = project.get("content_lock")
        if not isinstance(content_lock, dict) or not isinstance(content_lock.get("lock_hash"), str):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                f"The {label} project has no authenticated content lock.",
            )
        try:
            lock_rows = self._row_query(
                db,
                "SELECT * FROM project_content_locks WHERE project_id=? ORDER BY pack_id,version",
                (project_id,),
            )
            record_rows = self._row_query(
                db,
                "SELECT record_id,pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? ORDER BY record_id",
                (project_id,),
            )
        except FoundryError:
            raise
        has_authenticated_projection_record = False
        for row in record_rows:
            try:
                probe = json.loads(row["record_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(probe, dict) and probe.get("content_type") in {"foundation", "origin_insight"}:
                has_authenticated_projection_record = True
                break
        if has_authenticated_projection_record:
            proof = self._project_lock_proof(db, project_id)
            # Re-read after the proof so the proof hash covers the exact rows
            # consumed by this snapshot, including their canonical JSON bytes.
            record_rows = self._row_query(
                db,
                "SELECT record_id,pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? ORDER BY record_id",
                (project_id,),
            )
            self._assert_project_lock_snapshot(proof, record_rows, project_id=project_id)
        lock_pack_hashes: dict[tuple[Any, Any], set[Any]] = {}
        for lock_row in lock_rows:
            lock = _row_dict(lock_row)
            key = (lock.get("pack_id"), lock.get("version"))
            lock_pack_hashes.setdefault(key, set()).add(lock.get("pack_hash"))
        record_identities: list[dict[str, Any]] = []
        record_map: dict[str, dict[str, Any]] = {}
        for source_row in record_rows:
            item = _row_dict(source_row)
            record_id = item.get("record_id")
            if not isinstance(record_id, str) or not record_id or record_id in record_map:
                _fail(
                    "CG1_GM_CANDIDATE_SOURCE_INVALID",
                    f"The {label} locked-record set contains an invalid or duplicate record ID.",
                )
            raw_record, record = _canonical_db_json(item.get("record_json"), f"{label} record {record_id}")
            record_hash = item.get("record_hash")
            if not isinstance(record_hash, str) or canonical_record_hash(record) != record_hash:
                _fail(
                    "CG1_GM_CANDIDATE_SOURCE_INVALID",
                    f"The {label} locked record is not bound to its canonical hash.",
                    details={"record_id": record_id},
                )
            stored_record_id = record.get("record_id")
            if stored_record_id not in {None, record_id}:
                _fail(
                    "CG1_GM_CANDIDATE_SOURCE_INVALID",
                    f"The {label} locked record ID disagrees with its row.",
                    details={"record_id": record_id},
                )
            resolved_record = record
            resolved_raw_record = raw_record
            resolved_pack_id = item.get("pack_id")
            resolved_pack_version = item.get("pack_version")
            resolved_hash = record_hash
            raw_identity: dict[str, Any] = {}
            if method_version is not None and record_id.startswith("METHOD-"):
                resolved_record, raw_identity = self._resolve_versioned_method_snapshot(
                    db,
                    record_id=record_id,
                    raw_record=record,
                    row_pack_id=item.get("pack_id"),
                    row_pack_version=item.get("pack_version"),
                    row_pack_hash=(
                        next(iter(lock_pack_hashes[(item.get("pack_id"), item.get("pack_version"))]))
                        if len(lock_pack_hashes.get((item.get("pack_id"), item.get("pack_version")), set())) == 1
                        else None
                    ),
                    method_version=method_version,
                )
                resolved_raw_record = canonical_json(resolved_record)
                resolved_pack_id = (resolved_record.get("content_binding") or {}).get("pack_id")
                resolved_pack_version = (resolved_record.get("content_binding") or {}).get("pack_version")
                resolved_hash = resolved_record.get("record_hash")
            elif record.get("content_type") == "foundation":
                resolved_record, raw_identity = self._resolve_versioned_foundation_snapshot(
                    db,
                    record_id=record_id,
                    raw_record=record,
                    row_pack_id=item.get("pack_id"),
                    row_pack_version=item.get("pack_version"),
                    row_pack_hash=(
                        next(iter(lock_pack_hashes[(item.get("pack_id"), item.get("pack_version"))]))
                        if len(lock_pack_hashes.get((item.get("pack_id"), item.get("pack_version")), set())) == 1
                        else None
                    ),
                    foundation_version=foundation_version,
                    sealed_record_hash=record_hash,
                )
                resolved_raw_record = canonical_json(resolved_record)
                resolved_pack_id = (resolved_record.get("content_binding") or {}).get("pack_id")
                resolved_pack_version = (resolved_record.get("content_binding") or {}).get("pack_version")
                resolved_hash = resolved_record.get("record_hash")
            elif record.get("content_type") == "origin_insight":
                resolved_record, raw_identity = self._resolve_origin_insight_snapshot(
                    db,
                    project_id=project_id,
                    record_id=record_id,
                    raw_record=record,
                    row_pack_id=item.get("pack_id"),
                    row_pack_version=item.get("pack_version"),
                    row_pack_hash=(
                        next(iter(lock_pack_hashes[(item.get("pack_id"), item.get("pack_version"))]))
                        if len(lock_pack_hashes.get((item.get("pack_id"), item.get("pack_version")), set())) == 1
                        else None
                    ),
                    sealed_record_hash=record_hash,
                )
                resolved_raw_record = canonical_json(resolved_record)
                resolved_pack_id = (resolved_record.get("content_binding") or {}).get("pack_id")
                resolved_pack_version = (resolved_record.get("content_binding") or {}).get("pack_version")
                resolved_hash = resolved_record.get("record_hash")
            record_map[record_id] = {
                "record_id": record_id,
                "pack_id": resolved_pack_id,
                "pack_version": resolved_pack_version,
                "record_hash": resolved_hash,
                "record_json": resolved_raw_record,
                "record_json_sha256": sha256_bytes(resolved_raw_record.encode("utf-8")),
                **raw_identity,
            }
            record_identities.append({
                "record_id": record_id,
                "pack_id": item.get("pack_id"),
                "pack_version": item.get("pack_version"),
                "record_hash": record_hash,
                "record_json_sha256": sha256_bytes(raw_record.encode("utf-8")),
            })
        lock_snapshot = {
            "schema": "TianxiaFoundry.GMProjectLockSnapshot.v1",
            "project_id": project_id,
            "project_revision": project_revision,
            "content_lock_hash": content_lock["lock_hash"],
            "content_locks": [_row_dict(item) for item in lock_rows],
            "record_count": len(record_identities),
            "record_identities": record_identities,
        }
        lock_snapshot["lock_snapshot_sha256"] = sha256_json(lock_snapshot)
        metadata = {
            "project_id": project_id,
            "project_revision": project_revision,
            "project_json_sha256": sha256_bytes(raw_project.encode("utf-8")),
            "canonical_project_hash": stored_project_hash,
            "content_lock_hash": content_lock["lock_hash"],
            "lock_snapshot_sha256": lock_snapshot["lock_snapshot_sha256"],
            "record_count": len(record_identities),
        }
        return {
            "raw": raw_project,
            "project": project,
            "metadata": metadata,
            "lock_snapshot": lock_snapshot,
            "records": record_map,
        }, lock_snapshot, record_map

    def _event_snapshot(self, db: Any, project_id: str, project: dict[str, Any]) -> dict[str, Any]:
        rows = self._row_query(
            db,
            "SELECT sequence_no,event_id,event_hash,previous_event_hash,created_at,event_json,canonical_schema_version,contract_status FROM events WHERE project_id=? ORDER BY sequence_no",
            (project_id,),
        )
        events: list[dict[str, Any]] = []
        previous = ZERO_HASH
        for expected_sequence, row in enumerate(rows, 1):
            item = _row_dict(row)
            raw_event, event = _canonical_db_json(item.get("event_json"), f"event {expected_sequence}")
            if (
                item.get("sequence_no") != expected_sequence
                or event.get("sequence") != expected_sequence
                or item.get("previous_event_hash") != previous
                or event.get("previous_event_hash") != previous
                or canonical_event_hash(event) != item.get("event_hash")
                or event.get("event_hash") != item.get("event_hash")
                or item.get("canonical_schema_version") not in {None, event.get("schema_version")}
            ):
                _fail(
                    "CG1_GM_CANDIDATE_MECHANICS_INVALID",
                    "The candidate event stream is not an authenticated canonical chain.",
                    details={"sequence": expected_sequence},
                )
            events.append({
                "sequence_no": expected_sequence,
                "event_id": item.get("event_id"),
                "event_hash": item.get("event_hash"),
                "previous_event_hash": item.get("previous_event_hash"),
                "created_at": item.get("created_at"),
                "event_json": raw_event,
                "canonical_schema_version": item.get("canonical_schema_version"),
                "contract_status": item.get("contract_status"),
            })
            previous = item.get("event_hash")
        if not events:
            _fail(
                "CG1_GM_CANDIDATE_MECHANICS_MISSING",
                "A successful Character Sheet requires an authenticated Stage 2 event stream.",
            )
        stream = project.get("event_stream")
        if not isinstance(stream, dict) or stream.get("count") != len(events) or stream.get("head_hash") != previous:
            _fail(
                "CG1_GM_CANDIDATE_MECHANICS_INVALID",
                "The candidate project event-stream binding does not match its persisted events.",
            )
        return {
            "schema": "TianxiaFoundry.GMEventStream.v1",
            "event_count": len(events),
            "event_head_hash": previous,
            "events": events,
            "event_stream_sha256": sha256_json(events),
        }

    def _receipt_snapshot(
        self,
        db: Any,
        project_id: str,
        event_snapshot: dict[str, Any],
        stage2_commit: Any,
        stage2_service: Any | None,
        *,
        candidate_project_revision: int | None = None,
    ) -> dict[str, Any]:
        rows = self._row_query(
            db,
            "SELECT * FROM stage2_commit_receipts WHERE project_id=? AND status='committed' ORDER BY final_revision,completed_at",
            (project_id,),
        )
        if not rows:
            _fail(
                "CG1_GM_CANDIDATE_RECEIPT_MISSING",
                "The candidate event stream has no committed keyed Stage 2 receipt.",
            )
        terminal_row = rows[-1]
        ordering_keys = [
            (row_dict.get("final_revision"), row_dict.get("completed_at"))
            for row_dict in (_row_dict(row) for row in rows)
        ]
        if any(left == right for left, right in zip(ordering_keys, ordering_keys[1:])):
            _fail(
                "CG1_GM_CANDIDATE_RECEIPT_INVALID",
                "The committed terminal receipts are ambiguous at their selected ordering key.",
                details={"receipt_count": len(rows)},
            )
        verifier = getattr(stage2_service, "_verify_terminal_receipt", None)
        if callable(verifier):
            with db.connection() as conn:
                verifier(conn, terminal_row)
        terminal = _row_dict(terminal_row)
        if terminal.get("project_id") != project_id or terminal.get("status") != "committed":
            _fail("CG1_GM_CANDIDATE_RECEIPT_INVALID", "The selected terminal receipt is not committed for this project.")
        try:
            receipt_ids = json.loads(terminal.get("event_ids_json") or "[]")
            receipt_hashes = json.loads(terminal.get("event_hashes_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            _fail("CG1_GM_CANDIDATE_RECEIPT_INVALID", "The terminal receipt event set is malformed.")
        event_ids = [row["event_id"] for row in event_snapshot["events"]]
        event_hashes = [row["event_hash"] for row in event_snapshot["events"]]
        receipt_shape_valid = (
            isinstance(receipt_ids, list)
            and isinstance(receipt_hashes, list)
            and bool(receipt_ids)
            and len(receipt_ids) == len(receipt_hashes)
            and all(isinstance(value, str) for value in receipt_ids)
            and all(isinstance(value, str) for value in receipt_hashes)
            and len(set(receipt_ids)) == len(receipt_ids)
            and len(set(receipt_hashes)) == len(receipt_hashes)
            and len(receipt_ids) <= len(event_ids)
        )
        expected_suffix_ids = event_ids[-len(receipt_ids):] if receipt_shape_valid else None
        expected_suffix_hashes = event_hashes[-len(receipt_hashes):] if receipt_shape_valid else None
        if (
            not receipt_shape_valid
            or receipt_ids != expected_suffix_ids
            or receipt_hashes != expected_suffix_hashes
        ):
            _fail(
                "CG1_GM_CANDIDATE_RECEIPT_INVALID",
                "The terminal receipt does not cover the exact terminal suffix of the candidate event stream.",
                details={
                    "receipt_event_count": len(receipt_ids) if isinstance(receipt_ids, list) else None,
                    "candidate_event_count": len(event_ids),
                    "receipt_event_head": _receipt_hash_detail(receipt_hashes[-1]) if isinstance(receipt_hashes, list) and receipt_hashes else None,
                    "candidate_event_head": _receipt_hash_detail(event_hashes[-1]) if event_hashes else None,
                    "terminal_final_revision": _receipt_int_detail(terminal.get("final_revision")),
                    "candidate_project_revision": _receipt_int_detail(candidate_project_revision),
                },
            )
        try:
            terminal_projection = json.loads(terminal.get("terminal_projection_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            _fail("CG1_GM_CANDIDATE_RECEIPT_INVALID", "The terminal receipt projection is malformed.")
        if not isinstance(terminal_projection, Mapping):
            _fail("CG1_GM_CANDIDATE_RECEIPT_INVALID", "The terminal receipt projection is not an object.")
        projection_mismatch = (
            terminal_projection.get("event_count") != len(event_ids)
            or terminal_projection.get("event_chain_head") != (event_hashes[-1] if event_hashes else None)
            or terminal_projection.get("final_revision") != terminal.get("final_revision")
            or (
                candidate_project_revision is not None
                and terminal.get("final_revision") != candidate_project_revision
            )
        )
        if projection_mismatch:
            _fail(
                "CG1_GM_CANDIDATE_RECEIPT_INVALID",
                "The terminal receipt projection does not cover the authenticated candidate state.",
                details={
                    "terminal_projection_event_count": _receipt_int_detail(terminal_projection.get("event_count")),
                    "candidate_event_count": len(event_ids),
                    "terminal_projection_event_head": _receipt_hash_detail(terminal_projection.get("event_chain_head")),
                    "candidate_event_head": _receipt_hash_detail(event_hashes[-1]) if event_hashes else None,
                    "terminal_projection_final_revision": _receipt_int_detail(terminal_projection.get("final_revision")),
                    "terminal_final_revision": _receipt_int_detail(terminal.get("final_revision")),
                    "candidate_project_revision": _receipt_int_detail(candidate_project_revision),
                },
            )
        rebuild_rows: list[Any] = []
        try:
            rebuild_rows = self._row_query(
                db,
                "SELECT * FROM stage2_rebuild_receipts WHERE project_id=? ORDER BY created_at",
                (project_id,),
            )
        except FoundryError as exc:
            if exc.code != "CG1_GM_CANDIDATE_SOURCE_UNAVAILABLE":
                raise
        rebuild = None
        if rebuild_rows:
            rebuild_row = rebuild_rows[-1]
            rebuild_verifier = getattr(stage2_service, "_verify_rebuild_receipt", None)
            if callable(rebuild_verifier):
                with db.connection() as conn:
                    rebuild_verifier(conn, rebuild_row)
            rebuild = _row_dict(rebuild_row)
            if rebuild.get("project_id") != project_id:
                _fail("CG1_GM_CANDIDATE_RECEIPT_INVALID", "The rebuild receipt is bound to another project.")
            try:
                rebuild_projection = json.loads(rebuild.get("rebuild_projection_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                _fail("CG1_GM_CANDIDATE_RECEIPT_INVALID", "The rebuild receipt projection is malformed.")
            if not isinstance(rebuild_projection, Mapping):
                _fail("CG1_GM_CANDIDATE_RECEIPT_INVALID", "The rebuild receipt projection is not an object.")
            rebuild_mismatch = (
                rebuild.get("project_revision") != candidate_project_revision
                or rebuild.get("event_chain_head") != (event_hashes[-1] if event_hashes else None)
                or rebuild.get("terminal_commit_id") != terminal.get("commit_id")
                or rebuild.get("terminal_projection_hash") != terminal.get("terminal_projection_hash")
                or rebuild_projection.get("project_revision") != rebuild.get("project_revision")
                or rebuild_projection.get("event_chain_head") != rebuild.get("event_chain_head")
                or rebuild_projection.get("terminal_commit_id") != rebuild.get("terminal_commit_id")
                or rebuild_projection.get("terminal_projection_hash") != rebuild.get("terminal_projection_hash")
            )
            if rebuild_mismatch:
                _fail(
                    "CG1_GM_CANDIDATE_RECEIPT_INVALID",
                    "The rebuild receipt does not bind the authenticated candidate state and terminal receipt.",
                    details={
                        "rebuild_project_revision": _receipt_int_detail(rebuild.get("project_revision")),
                        "candidate_project_revision": _receipt_int_detail(candidate_project_revision),
                        "rebuild_event_head": _receipt_hash_detail(rebuild.get("event_chain_head")),
                        "candidate_event_head": _receipt_hash_detail(event_hashes[-1]) if event_hashes else None,
                        "rebuild_terminal_commit_id": _receipt_identifier_detail(rebuild.get("terminal_commit_id")),
                        "terminal_commit_id": _receipt_identifier_detail(terminal.get("commit_id")),
                    },
                )
        supplied = stage2_commit if isinstance(stage2_commit, Mapping) else {}
        supplied_receipt = supplied.get("receipt") if isinstance(supplied.get("receipt"), Mapping) else {}
        if supplied_receipt.get("commit_id") not in {None, terminal.get("commit_id")}:
            _fail("CG1_GM_CANDIDATE_RECEIPT_INVALID", "The Stage 2 result disagrees with its persisted terminal receipt.")
        return {
            "schema": "TianxiaFoundry.GMStage2ReceiptSet.v1",
            "terminal_receipt": terminal,
            "rebuild_receipt": rebuild,
            "terminal_receipt_sha256": sha256_json(terminal),
            "rebuild_receipt_sha256": sha256_json(rebuild) if rebuild is not None else None,
            "stage2_validation_sha256": sha256_json(supplied.get("validation") or {}),
            "stage2_commit_sha256": sha256_json(supplied),
        }

    @staticmethod
    def _safe_scratch_file(scratch_db: Any, path: Path, *, label: str) -> Path:
        scratch_root = Path(os.path.abspath(os.fspath(scratch_db.settings.data_dir)))
        candidate = CandidateGMCapsuleStore._assert_no_symlink_path(scratch_root, path, label=label)
        try:
            mode = os.lstat(candidate).st_mode
        except FileNotFoundError:
            _fail("CG1_GM_CANDIDATE_ARTIFACT_MISSING", f"The authenticated {label} is missing.")
        except OSError as exc:
            _fail("CG1_GM_CANDIDATE_ARTIFACT_INVALID", f"The {label} path cannot be inspected safely.", details={"cause": type(exc).__name__})
        if not stat.S_ISREG(mode):
            _fail("CG1_GM_CANDIDATE_ARTIFACT_PATH_INVALID", f"The authenticated {label} is not a regular file.")
        return candidate

    def _projection_snapshot(self, scratch_db: Any, project_id: str, projection: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, bytes]]:
        projection_id = projection.get("projection_id")
        if not isinstance(projection_id, str) or not projection_id:
            _fail("CG1_GM_CANDIDATE_PROJECTION_INVALID", "The Character Sheet has no authenticated projection ID.")
        row = self._one_query(
            scratch_db,
            "SELECT * FROM projection_runs WHERE project_id=? AND projection_id=?",
            (project_id, projection_id),
        )
        if row is None or row["status"] != "READY":
            _fail("CG1_GM_CANDIDATE_PROJECTION_INVALID", "The candidate projection is not READY.")
        if projection.get("project_revision") != row["project_revision"]:
            _fail("CG1_GM_CANDIDATE_PROJECTION_INVALID", "The supplied projection status disagrees with its sealed row.")
        artifact_rows = self._row_query(
            scratch_db,
            "SELECT artifact_name,path,sha256,bytes,media_type FROM projection_artifacts WHERE projection_id=? ORDER BY artifact_name",
            (projection_id,),
        )
        by_name = {item["artifact_name"]: item for item in artifact_rows}
        if set(by_name) != set(_REQUIRED_PROJECTION_ARTIFACTS):
            _fail(
                "CG1_GM_CANDIDATE_PROJECTION_INVALID",
                "The candidate projection does not expose the complete compiler artifact set.",
                details={"artifacts": sorted(by_name)},
            )
        supplied = {
            item.get("artifact_name"): item
            for item in projection.get("artifacts") or []
            if isinstance(item, Mapping)
        }
        artifact_bytes: dict[str, bytes] = {}
        artifact_hashes: dict[str, str] = {}
        for name in _REQUIRED_PROJECTION_ARTIFACTS:
            item = by_name[name]
            supplied_item = supplied.get(name)
            if supplied_item is not None and any(
                supplied_item.get(key) != item[key] for key in ("sha256", "bytes")
            ):
                _fail("CG1_GM_CANDIDATE_PROJECTION_INVALID", "The supplied projection artifact metadata is not sealed.", details={"artifact_name": name})
            expected_dir = (
                Path(scratch_db.settings.data_dir)
                / "projects" / project_id / "projections" / projection_id / "generated"
            )
            stored = Path(item["path"])
            path = stored if stored.is_file() else expected_dir / name
            path = self._safe_scratch_file(scratch_db, path, label=f"projection artifact {name}")
            payload = path.read_bytes()
            if len(payload) != item["bytes"] or sha256_bytes(payload) != item["sha256"]:
                _fail("CG1_GM_CANDIDATE_PROJECTION_TAMPERED", "A projection artifact differs from its sealed hash.", details={"artifact_name": name})
            _parse_json_bytes(payload, label=f"projection artifact {name}")
            artifact_bytes[name] = payload
            artifact_hashes[name] = item["sha256"]
        projection_identity = {
            "project_id": project_id,
            "projection_id": projection_id,
            "project_revision": row["project_revision"],
            "status": row["status"],
            "event_head_hash": row["event_head_hash"],
            "content_lock_hash": row["content_lock_hash"],
            "artifact_hashes": artifact_hashes,
            "artifact_set_sha256": sha256_json([
                {"artifact_name": name, "sha256": artifact_hashes[name], "bytes": len(artifact_bytes[name])}
                for name in _REQUIRED_PROJECTION_ARTIFACTS
            ]),
        }
        return projection_identity, artifact_bytes

    def _source_snapshot(
        self,
        candidate_project: dict[str, Any],
        owner_sheet: Mapping[str, Any],
        record_map: dict[str, dict[str, Any]],
        *,
        source_db: Any | None = None,
    ) -> dict[str, Any]:
        try:
            from factory_authoring.service import FactoryAuthoringWorkspaceService

            selected = FactoryAuthoringWorkspaceService._selected_record_snapshot(
                candidate_project["project"]["project_id"],
                candidate_project["metadata"]["project_revision"],
                owner_sheet,
            )
        except FoundryError:
            raise
        except Exception as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "The owner Character Sheet selected-record source cannot be materialized.",
                details={"cause": type(exc).__name__},
            )
        locked_records: list[dict[str, Any]] = []
        path_proof: Mapping[str, Any] | None = None
        path_proof_rows: list[Any] | None = None
        background_project_store: Any = None
        for row in selected["records"]:
            card = row["record"]
            record_id = card["record_id"]
            if self._is_path_milestone_record_id(record_id):
                _fail(
                    "CG1_GM_CANDIDATE_SOURCE_INVALID",
                    "A Path milestone identifier is progression intent, not a Character Sheet card.",
                    details={"record_id": record_id, "section": row.get("section")},
                )
            # Automatic Sphere components intentionally use stable IDs that
            # can also occur in the ordinary catalog namespace.  The sealed
            # Character Sheet shape is the authority discriminator here; do
            # not let a direct row win merely because its ID (or hash) also
            # exists in the project snapshot.
            automatic_component_card = (
                card.get("section") == "sphere_automatic_components"
                or isinstance(card.get("component_hash"), str)
                or (
                    isinstance(card.get("parent_sphere_id"), str)
                    and isinstance(card.get("automatic_component_authority"), Mapping)
                    and isinstance(card.get("automatic_component_authority", {}).get("component_ids"), list)
                )
            )
            if automatic_component_card:
                locked = self._locked_automatic_component(card, record_map)
                if locked is None:
                    _fail(
                        "CG1_GM_CANDIDATE_SOURCE_INVALID",
                        "A selected automatic Sphere component lacks an authenticated parent binding.",
                        details={
                            "record_id": record_id,
                            "section": card.get("section"),
                            "parent_record_id": card.get("parent_sphere_id"),
                        },
                    )
            else:
                locked = record_map.get(record_id)
                if locked is None:
                    _fail(
                        "CG1_GM_CANDIDATE_SOURCE_INVALID",
                        "A selected Character Sheet record is absent from the authenticated locked source set.",
                        details={"record_id": record_id},
                    )
                _raw_record_for_projection, raw_record_for_projection = _canonical_db_json(
                    locked["record_json"],
                    f"selected record {record_id}",
                )
                if self._is_path_family_record(record_id):
                    if source_db is None:
                        _fail(
                            "CG1_GM_CANDIDATE_SOURCE_INVALID",
                            "A selected Path-family card lacks its authenticated source database.",
                            details={"record_id": record_id},
                        )
                    project_id = candidate_project["project"]["project_id"]
                    if path_proof is None:
                        path_proof = self._project_lock_proof(source_db, project_id)
                        path_proof_rows = self._row_query(
                            source_db,
                            "SELECT record_id,pack_id,pack_version,record_hash,record_json "
                            "FROM project_locked_records WHERE project_id=? ORDER BY record_id",
                            (project_id,),
                        )
                    lock_hash_rows = self._row_query(
                        source_db,
                        "SELECT pack_hash FROM project_content_locks "
                        "WHERE project_id=? AND pack_id=? AND version=?",
                        (project_id, locked["pack_id"], locked["pack_version"]),
                    )
                    lock_hashes = {
                        item["pack_hash"]
                        for item in lock_hash_rows
                        if isinstance(item["pack_hash"], str)
                    }
                    row_pack_hash = next(iter(lock_hashes)) if len(lock_hashes) == 1 else None
                    resolved_record, raw_identity = self._resolve_path_family_snapshot(
                        source_db,
                        project_id=project_id,
                        record_id=record_id,
                        raw_record=raw_record_for_projection,
                        row_pack_id=locked["pack_id"],
                        row_pack_version=locked["pack_version"],
                        row_pack_hash=row_pack_hash,
                        sealed_record_hash=locked["record_hash"],
                        proof=path_proof,
                        proof_record_rows=path_proof_rows,
                    )
                    resolved_json = canonical_json(resolved_record)
                    resolved_binding = resolved_record["content_binding"]
                    locked = {
                        "record_id": record_id,
                        "pack_id": resolved_binding["pack_id"],
                        "pack_version": resolved_binding["pack_version"],
                        "record_hash": resolved_record["record_hash"],
                        "record_json": resolved_json,
                        "record_json_sha256": sha256_bytes(resolved_json.encode("utf-8")),
                        **raw_identity,
                    }
                elif card.get("record_hash") not in {None, locked["record_hash"]} and (
                    self._is_background_family_record(record_id, raw_record_for_projection)
                    or raw_record_for_projection.get("content_type") in {"sphere", "talent"}
                ):
                    # A Background-family row (or a canonical Sphere/Talent row
                    # promoted by a Background package) whose card disagrees
                    # with the raw lock was rendered from the ProjectStore
                    # authority projection; cards that already match the raw
                    # sealed hash keep the ordinary path.
                    if source_db is None:
                        _fail(
                            "CG1_GM_CANDIDATE_SOURCE_INVALID",
                            "A selected Background-family card lacks its authenticated source database.",
                            details={"record_id": record_id},
                        )
                    project_id = candidate_project["project"]["project_id"]
                    if background_project_store is None:
                        from project_store.service import ProjectStore

                        background_project_store = ProjectStore(source_db)
                    lock_hash_rows = self._row_query(
                        source_db,
                        "SELECT pack_hash FROM project_content_locks "
                        "WHERE project_id=? AND pack_id=? AND version=?",
                        (project_id, locked["pack_id"], locked["pack_version"]),
                    )
                    lock_hashes = {
                        item["pack_hash"]
                        for item in lock_hash_rows
                        if isinstance(item["pack_hash"], str)
                    }
                    resolved_record, raw_identity = self._resolve_background_projection_snapshot(
                        source_db,
                        project_id=project_id,
                        record_id=record_id,
                        raw_record=raw_record_for_projection,
                        row_pack_id=locked["pack_id"],
                        row_pack_version=locked["pack_version"],
                        row_pack_hash=next(iter(lock_hashes)) if len(lock_hashes) == 1 else None,
                        sealed_record_hash=locked["record_hash"],
                        project_store=background_project_store,
                    )
                    resolved_json = canonical_json(resolved_record)
                    resolved_binding = resolved_record["content_binding"]
                    locked = {
                        "record_id": record_id,
                        "pack_id": resolved_binding["pack_id"],
                        "pack_version": resolved_binding["pack_version"],
                        "record_hash": resolved_record["record_hash"],
                        "record_json": resolved_json,
                        "record_json_sha256": sha256_bytes(resolved_json.encode("utf-8")),
                        **raw_identity,
                    }
            if card.get("record_hash") not in {None, locked["record_hash"]}:
                _fail(
                    "CG1_GM_CANDIDATE_SOURCE_INVALID",
                    "A selected record card disagrees with its locked source hash.",
                    details={
                        "record_id": record_id,
                        "observed_card_hash": card.get("record_hash"),
                        "expected_source_hash": locked.get("record_hash"),
                        "card_source_identity": {
                            "section": card.get("section"),
                            "parent_sphere_id": card.get("parent_sphere_id"),
                            "component_hash": card.get("component_hash"),
                            "automatic_component_authority": deepcopy(card.get("automatic_component_authority")),
                        },
                        "locked_source_identity": {
                            "binding_kind": locked.get("binding_kind", "project_locked_record"),
                            "pack_id": locked.get("pack_id"),
                            "pack_version": locked.get("pack_version"),
                            "parent_record_id": locked.get("parent_record_id"),
                            "parent_record_hash": locked.get("parent_record_hash"),
                            "project_locked_pack_id": locked.get("project_locked_pack_id"),
                            "project_locked_pack_version": locked.get("project_locked_pack_version"),
                            "project_locked_pack_hash": locked.get("project_locked_pack_hash"),
                            "project_locked_record_hash": locked.get("project_locked_record_hash"),
                        },
                    },
                )
            raw_record, record = _canonical_db_json(locked["record_json"], f"selected record {record_id}")
            if locked.get("binding_kind") == "locked_sphere_automatic_component":
                expected_hash = sha256_json({key: value for key, value in record.items() if key != "component_hash"})
            else:
                expected_hash = canonical_record_hash(record)
            if expected_hash != locked["record_hash"]:
                _fail("CG1_GM_CANDIDATE_SOURCE_INVALID", "A selected source record failed canonical hash validation.", details={"record_id": record_id})
            source_row = {
                "section": row["section"],
                "record_id": record_id,
                "pack_id": locked["pack_id"],
                "pack_version": locked["pack_version"],
                "record_hash": locked["record_hash"],
                "record_json": raw_record,
                "record_json_sha256": locked["record_json_sha256"],
            }
            for key in (
                "binding_kind",
                "parent_record_id",
                "parent_record_hash",
                "parent_record_json_sha256",
                "automatic_component_package_hash",
                "project_locked_pack_id",
                "project_locked_pack_version",
                "project_locked_pack_hash",
                "project_locked_record_hash",
                "project_locked_record_json_sha256",
            ):
                if key in locked:
                    source_row[key] = locked[key]
            locked_records.append(source_row)
        return {
            "schema": "TianxiaFoundry.GMSelectedRecordSource.v1",
            "selected_record_content_sha256": selected["selected_record_content_sha256"],
            "snapshot": selected,
            "locked_records": locked_records,
        }

    @staticmethod
    def _locked_automatic_component(
        card: Mapping[str, Any],
        record_map: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Resolve a selected automatic Sphere component through its locked parent.

        Automatic component IDs are real Character Sheet records, but they are
        canonically nested in the locked parent Sphere record rather than stored
        as independent ``project_locked_records`` rows.  Rebuild the same packet
        used by the projector and require every card-side authority mirror to
        agree before treating that nested record as authenticated source.
        """
        parent_id = card.get("parent_sphere_id")
        authority = card.get("automatic_component_authority")
        if not isinstance(parent_id, str) or not parent_id or not isinstance(authority, Mapping):
            return None
        parent = record_map.get(parent_id)
        if parent is None:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "A selected automatic Sphere component has no authenticated locked parent Sphere.",
                details={"record_id": card.get("record_id"), "parent_record_id": parent_id},
            )
        _raw_parent, parent_record = _canonical_db_json(
            parent["record_json"],
            f"automatic component parent {parent_id}",
        )
        try:
            from sphere_component_authority import normalize_sphere_automatic_components

            packet = normalize_sphere_automatic_components(parent_record)
        except FoundryError as exc:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "A selected automatic Sphere component cannot be reproduced from its locked parent Sphere.",
                details={
                    "record_id": card.get("record_id"),
                    "parent_record_id": parent_id,
                    "cause": exc.code,
                },
            )
        if packet.get("parent_record_hash") != parent.get("record_hash"):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "A selected automatic Sphere component parent hash disagrees with its locked source.",
                details={"record_id": card.get("record_id"), "parent_record_id": parent_id},
            )
        if packet.get("parent_sphere_id") != parent_id:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "A selected automatic Sphere component packet parent disagrees with its locked parent identity.",
                details={"record_id": card.get("record_id"), "parent_record_id": parent_id},
            )
        record_id = card.get("record_id")
        components = [
            component
            for component in packet.get("components") or []
            if isinstance(component, Mapping) and component.get("component_id") == record_id
        ]
        if len(components) != 1:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "A selected automatic Sphere component is absent from its locked parent authority packet.",
                details={"record_id": record_id, "parent_record_id": parent_id},
            )
        component = deepcopy(dict(components[0]))
        if component.get("parent_sphere_id") != parent_id:
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "A selected automatic Sphere component parent disagrees with its locked parent identity.",
                details={"record_id": record_id, "parent_record_id": parent_id},
            )
        component_hash = component.get("component_hash")
        expected_authority = {
            "schema_version": packet.get("schema_version"),
            "parent_sphere_id": parent_id,
            "package_hash": packet.get("package_hash"),
            "component_ids": [record_id],
        }
        expected_flags = {
            key: component.get(key)
            for key in (
                "automatic_grant",
                "owner_removable",
                "counts_as_talent_choice",
                "counts_as_advancement_talent",
                "counts_as_training_talent",
            )
        }
        component_source = component.get("source") if isinstance(component.get("source"), Mapping) else {}
        parent_source = parent_record.get("source") if isinstance(parent_record.get("source"), Mapping) else {}
        expected_source = {
            "path": component_source.get("path") or component_source.get("source_path") or parent_source.get("path"),
            "anchor": component_source.get("anchor") or component_source.get("source_anchor") or f"{parent_source.get('anchor', parent_id)}:{record_id}",
            "sha256": component_source.get("source_hash") or component_source.get("source_file_sha256") or component_source.get("compendium_sha256") or parent_source.get("source_hash"),
        }
        if (
            not isinstance(component_hash, str)
            or card.get("record_hash") != component_hash
            or card.get("component_hash") != component_hash
            or any(authority.get(key) != value for key, value in expected_authority.items())
            or card.get("automatic_component_flags") != expected_flags
            or card.get("source") != expected_source
        ):
            _fail(
                "CG1_GM_CANDIDATE_SOURCE_INVALID",
                "A selected automatic Sphere component card disagrees with its locked parent authority.",
                details={
                    "record_id": record_id,
                    "observed_card_hash": card.get("record_hash"),
                    "expected_source_hash": component_hash if isinstance(component_hash, str) else None,
                    "card_source_identity": {
                        "section": card.get("section"),
                        "parent_sphere_id": card.get("parent_sphere_id"),
                        "component_hash": card.get("component_hash"),
                        "automatic_component_authority": deepcopy(card.get("automatic_component_authority")),
                    },
                    "locked_source_identity": {
                        "binding_kind": "locked_sphere_automatic_component",
                        "pack_id": parent.get("pack_id"),
                        "pack_version": parent.get("pack_version"),
                        "parent_record_id": parent_id,
                        "parent_record_hash": parent.get("record_hash"),
                        "automatic_component_package_hash": packet.get("package_hash"),
                    },
                },
            )
        raw_component = canonical_json(component)
        return {
            "record_id": record_id,
            "pack_id": parent["pack_id"],
            "pack_version": parent["pack_version"],
            "record_hash": component_hash,
            "record_json": raw_component,
            "record_json_sha256": sha256_bytes(raw_component.encode("utf-8")),
            "binding_kind": "locked_sphere_automatic_component",
            "parent_record_id": parent_id,
            "parent_record_hash": parent["record_hash"],
            "parent_record_json_sha256": parent["record_json_sha256"],
            "automatic_component_package_hash": packet["package_hash"],
        }

    def _sheet_snapshot(
        self,
        scratch_db: Any,
        project_id: str,
        sheet: Mapping[str, Any],
        projection_identity: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bytes]:
        if sheet.get("build_status") != "CHARACTER_SHEET_READY":
            _fail("CG1_GM_CANDIDATE_SHEET_INVALID", "The GM staging capsule requires a successful Character Sheet build.")
        owner_sheet = sheet.get("owner_character_sheet")
        artifact = sheet.get("sheet_artifact")
        if not isinstance(owner_sheet, Mapping) or not isinstance(artifact, Mapping):
            _fail("CG1_GM_CANDIDATE_SHEET_INVALID", "The Character Sheet did not return its authenticated snapshot and artifact.")
        owner_sheet = deepcopy(dict(owner_sheet))
        sheet_id = owner_sheet.get("sheet_id")
        if not isinstance(sheet_id, str) or not sheet_id or artifact.get("sheet_id") != sheet_id:
            _fail("CG1_GM_CANDIDATE_SHEET_INVALID", "The Character Sheet artifact identity is incomplete.")
        authority = owner_sheet.get("authority_and_artifact_identity")
        if (
            not isinstance(authority, Mapping)
            or authority.get("project_id") != project_id
            or authority.get("project_revision") != projection_identity.get("project_revision")
            or authority.get("projection_id") != projection_identity.get("projection_id")
            or authority.get("advancement_artifact_hashes") != projection_identity.get("artifact_hashes")
        ):
            _fail("CG1_GM_CANDIDATE_SHEET_INVALID", "The Character Sheet is not bound to the authenticated projection.")
        expected = (
            Path(scratch_db.settings.data_dir)
            / "character_sheets" / project_id / sheet_id / "Owner_Character_Sheet.json"
        )
        supplied = Path(str(artifact.get("path") or expected))
        path = self._safe_scratch_file(scratch_db, supplied if supplied.is_file() else expected, label="Character Sheet artifact")
        payload = path.read_bytes()
        expected_hash = artifact.get("sha256")
        if type(artifact.get("bytes")) is not int or len(payload) != artifact["bytes"] or sha256_bytes(payload) != expected_hash:
            _fail("CG1_GM_CANDIDATE_SHEET_TAMPERED", "The Character Sheet artifact differs from its sealed hash.")
        parsed = _parse_json_bytes(payload, label="Character Sheet artifact")
        if parsed != owner_sheet:
            _fail("CG1_GM_CANDIDATE_SHEET_INVALID", "The Character Sheet artifact bytes differ from its returned snapshot.")
        return {
            "schema": "TianxiaFoundry.GMCharacterSheetIdentity.v1",
            "sheet_id": sheet_id,
            "sheet_sha256": sha256_json(owner_sheet),
            "artifact_sha256": sha256_bytes(payload),
            "artifact_bytes": len(payload),
            "project_id": project_id,
            "project_revision": projection_identity["project_revision"],
        }, payload

    def _request_anchor(self, run: Mapping[str, Any], root_db: Any) -> dict[str, Any]:
        run_id = _safe_identifier(run.get("run_id"), "run")
        project_id = _safe_identifier(run.get("project_id"), "project")
        row = self._one_query(
            root_db,
            "SELECT run_id,project_id,starting_revision,request_json,response_json FROM character_creation_runs WHERE run_id=?",
            (run_id,),
        )
        if row is None or row["project_id"] != project_id or row["starting_revision"] != run.get("starting_revision"):
            _fail("CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID", "The persisted creation run does not match the compile run context.")
        raw_request, request = _canonical_db_json(row["request_json"], "creation request")
        expected_request = run.get("request")
        if not isinstance(request, dict) or (expected_request is not None and request != expected_request):
            _fail("CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID", "The compile request differs from the persisted exact request.")
        request_sha = _require_sha(request.get("request_sha256"), "request")
        try:
            from character_creation.service import CharacterCreationExecutionService

            recomputed = CharacterCreationExecutionService.request_payload_sha256(request)
        except FoundryError:
            raise
        except Exception as exc:
            _fail("CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID", "The persisted request hash cannot be recomputed.", details={"cause": type(exc).__name__})
        if recomputed != request_sha:
            _fail("CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID", "The persisted request hash is not bound to its canonical request.")
        asserted_response = run.get("response") if isinstance(run.get("response"), Mapping) else {}
        asserted_sha = asserted_response.get("response_sha256")
        asserted_text = asserted_response.get("exact_response_text")
        try:
            response = json.loads(row["response_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            _fail("CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID", "The persisted response binding is malformed JSON.")
        if not isinstance(response, dict):
            _fail("CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID", "The persisted response binding is not an object.")
        persisted_exact = response.get("exact_response_text")
        persisted_sha_value = response.get("response_sha256")
        if persisted_exact is not None:
            if not isinstance(persisted_exact, str):
                _fail("CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID", "The persisted response text is not text.")
            response_bytes = persisted_exact.encode("utf-8")
            persisted_response_sha = _require_sha(persisted_sha_value, "response")
            if sha256_bytes(response_bytes) != persisted_response_sha:
                _fail(
                    "CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID",
                    "The persisted response hash does not authenticate its exact response bytes.",
                )
            if asserted_sha is not None and _require_sha(asserted_sha, "response") != persisted_response_sha:
                _fail(
                    "CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID",
                    "The compile response assertion disagrees with the persisted exact response.",
                )
            if asserted_text is not None and asserted_text != persisted_exact:
                _fail(
                    "CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID",
                    "The compile response assertion disagrees with the persisted exact response bytes.",
                )
            response_text = persisted_exact
        else:
            persisted_response_sha = None
            if persisted_sha_value is not None:
                persisted_response_sha = _require_sha(persisted_sha_value, "response")
            if asserted_sha is None:
                asserted_sha = persisted_response_sha
            if asserted_sha is None:
                _fail("CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID", "The compile response assertion has no response digest.")
            asserted_sha = _require_sha(asserted_sha, "response")
            try:
                if isinstance(asserted_text, str) and asserted_text:
                    evidence = CharacterCreationExecutionService._compile_response_evidence(
                        run,
                        response_text=asserted_text,
                        response_sha256=asserted_sha,
                        persisted_response_sha256=persisted_response_sha,
                    )
                else:
                    if persisted_response_sha is not None and persisted_response_sha != asserted_sha:
                        raise FoundryError(
                            "CG1_RESPONSE_EVIDENCE_INVALID",
                            "The persisted response digest disagrees with the compile response.",
                        )
                    evidence = CharacterCreationExecutionService._retained_response_evidence(
                        run,
                        response_sha256=asserted_sha,
                    )
            except FoundryError as exc:
                _fail(
                    "CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID",
                    "The compact persisted response has no authenticated exact-response evidence.",
                    details={"cause": exc.code},
                )
            response_text = evidence["response_text"]
            response_bytes = evidence["response_bytes"]
            persisted_response_sha = evidence["response_sha256"]
        return {
            "run_id": run_id,
            "project_id": project_id,
            "starting_revision": run["starting_revision"],
            "request_sha256": request_sha,
            "request_json_sha256": sha256_bytes(raw_request.encode("utf-8")),
            "response_sha256": persisted_response_sha,
            "response_bytes": response_bytes,
            "response_bytes_sha256": persisted_response_sha,
            "response_text": response_text,
            "persisted_response_sha256": persisted_response_sha,
            "request": request,
        }

    def _summary(self, context: Mapping[str, Any], manifest_sha256: str) -> dict[str, Any]:
        root = context["root_project"]
        candidate = context["candidate_project"]
        projection = context["projection"]
        sheet = context["sheet"]
        mechanics = context["mechanics"]
        source = context["source"]
        return {
            "schema": CAPSULE_SCHEMA,
            "status": CAPSULE_STATUS,
            "run_id": context["run_id"],
            "project_id": context["project_id"],
            "capsule_id": context["capsule_id"],
            "context_sha256": context["context_sha256"],
            "manifest_sha256": manifest_sha256,
            "request_sha256": context["request_sha256"],
            "response_sha256": context["response_sha256"],
            "response_bytes": context["response_bytes"],
            "root_project_revision": root["project_revision"],
            "candidate_project_revision": candidate["project_revision"],
            "final_plan_sha256": context.get("final_plan_sha256"),
            "projection_id": projection["projection_id"],
            "sheet_id": sheet["sheet_id"],
            "event_count": mechanics["event_count"],
            "event_head_hash": mechanics["event_head_hash"],
            "selected_record_content_sha256": source["selected_record_content_sha256"],
            "gm_authoring_status": "NOT_AUTHORED",
            "owner_ratified": False,
            "ready_for_command5": False,
            **(
                {
                    "factory_workspace_sha256": context["factory_workspace"].get("workspace_sha256"),
                    "factory_workspace_manifest_sha256": context["factory_workspace"].get("manifest_sha256"),
                    "factory_workspace_file_count": context["factory_workspace"].get("file_count"),
                }
                if isinstance(context.get("factory_workspace"), Mapping)
                else {}
            ),
        }

    def _factory_workspace_snapshot(
        self,
        factory_authoring: Mapping[str, Any],
        *,
        project_id: str,
        candidate_project: Mapping[str, Any],
        scratch_root: Path,
    ) -> tuple[dict[str, Any], dict[str, bytes]]:
        """Capture the exact workspace produced by the already completed build."""
        if not isinstance(factory_authoring, Mapping):
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory authoring result is not an object.")
        raw_path = factory_authoring.get("workspace_path")
        workspace_sha256 = factory_authoring.get("workspace_sha256")
        manifest_sha256 = factory_authoring.get("manifest_sha256")
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or not _SHA256_RE.fullmatch(str(workspace_sha256 or ""))
            or not _SHA256_RE.fullmatch(str(manifest_sha256 or ""))
            or factory_authoring.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
        ):
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory authoring result has incomplete workspace bindings.")
        scratch_root = Path(os.path.abspath(os.fspath(scratch_root)))
        workspace = Path(os.path.abspath(os.fspath(raw_path)))
        self._assert_no_symlink_path(scratch_root, workspace, label="Factory workspace")
        try:
            workspace.relative_to(scratch_root)
        except ValueError:
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace is outside the disposable candidate root.")
        if workspace.is_symlink() or not workspace.is_dir():
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace is unavailable or symlinked.")
        files: dict[str, bytes] = {}
        for path in sorted(workspace.rglob("*")):
            if path.is_symlink():
                _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace contains a symlink.")
            if not path.is_file():
                continue
            relative = path.relative_to(workspace).as_posix()
            if not relative or ".." in PurePosixPath(relative).parts:
                _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace contains an invalid file path.")
            files[relative] = path.read_bytes()
        manifest_payload = files.get("Workspace_Manifest.json")
        if manifest_payload is None:
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace manifest is missing.")
        manifest = _parse_json_bytes(manifest_payload, label="Factory workspace manifest")
        candidate_revision = candidate_project.get("metadata", {}).get("project_revision")
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
            or manifest.get("project_id") not in {None, project_id}
            or manifest.get("project_revision") != candidate_revision
            or factory_authoring.get("project_id") not in {None, project_id}
            or factory_authoring.get("project_revision") not in {None, candidate_revision}
        ):
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace is not bound to this candidate project revision.")
        file_hashes = {name: sha256_bytes(payload) for name, payload in sorted(files.items())}
        if sha256_json(file_hashes) != workspace_sha256:
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace bytes do not match its returned tree hash.")
        returned_hashes = factory_authoring.get("artifact_hashes")
        if isinstance(returned_hashes, Mapping) and dict(returned_hashes) != file_hashes:
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace files differ from its artifact hash ledger.")
        if sha256_bytes(manifest_payload) != manifest_sha256:
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace manifest hash is stale.")
        identity = {
            "schema": _FACTORY_WORKSPACE_SCHEMA,
            "project_id": project_id,
            "project_revision": candidate_revision,
            "workspace_status": factory_authoring.get("workspace_status"),
            "workspace_sha256": workspace_sha256,
            "manifest_sha256": manifest_sha256,
            "manifest": {
                "project_id": manifest.get("project_id"),
                "project_revision": manifest.get("project_revision"),
                "projection_id": manifest.get("projection_id"),
                "event_head_hash": manifest.get("event_head_hash"),
            },
            "file_hashes": file_hashes,
            "file_count": len(files),
            "candidate_binding_sha256": sha256_json({
                "project_id": project_id,
                "project_revision": candidate_revision,
                "candidate_project_hash": (candidate_project.get("metadata") or {}).get("canonical_project_hash"),
                "workspace_sha256": workspace_sha256,
                "manifest_sha256": manifest_sha256,
            }),
        }
        return identity, files

    def capture(
        self,
        *,
        run: Mapping[str, Any],
        root_db: Any,
        scratch_db: Any,
        scratch_root: Path,
        sheet: Mapping[str, Any],
        projection: Mapping[str, Any],
        stage2_validation: Any,
        stage2_commit: Any,
        stage2_service: Any | None = None,
        final_plan: Mapping[str, Any] | None = None,
        factory_authoring: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Capture a verified scratch result before the production GM gate."""
        run_id = _safe_identifier(run.get("run_id"), "run")
        project_id = _safe_identifier(run.get("project_id"), "project")
        if root_db is not self.db:
            _fail("CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID", "The root source database is not the owning service database.")
        scratch_path = Path(scratch_root).resolve()
        if not Path(scratch_db.settings.data_dir).resolve().is_relative_to(scratch_path):
            _fail("CG1_GM_CANDIDATE_RUN_ANCHOR_INVALID", "The scratch database is outside the declared scratch root.")
        request_anchor = self._request_anchor(run, root_db)
        from non_sphere_authority.foundation_mechanics import initial_foundation_record_version
        from non_sphere_authority.method_mechanics import initial_method_record_version

        method_version = initial_method_record_version(request_anchor["request"])
        foundation_version = initial_foundation_record_version(request_anchor["request"])
        root_project, root_lock, _root_records = self._project_snapshot(root_db, project_id, label="root")
        candidate_project, candidate_lock, candidate_records = self._project_snapshot(
            scratch_db,
            project_id,
            label="candidate",
            method_version=method_version,
            foundation_version=foundation_version,
        )
        if candidate_project["metadata"]["project_revision"] <= root_project["metadata"]["project_revision"]:
            _fail("CG1_GM_CANDIDATE_PROJECT_INVALID", "The scratch candidate did not advance the root project revision.")
        event_snapshot = self._event_snapshot(scratch_db, project_id, candidate_project["project"])
        projection_identity, projection_artifacts = self._projection_snapshot(scratch_db, project_id, projection)
        # ProjectionService stores the digest of the complete canonical
        # content-lock document.  The document's embedded ``lock_hash`` is a
        # separate catalog-lock identity used by the request and Stage 2
        # contracts; comparing the projection row to that inner value rejects
        # every real v3 projection whose document contains the lock_hash field.
        expected_projection_lock_hash = sha256_json(
            candidate_project["project"]["content_lock"]
        )
        if (
            projection_identity["event_head_hash"] != event_snapshot["event_head_hash"]
            or projection_identity["content_lock_hash"] != expected_projection_lock_hash
        ):
            _fail("CG1_GM_CANDIDATE_PROJECTION_INVALID", "The projection is not bound to the candidate event and lock state.")
        owner_sheet = sheet.get("owner_character_sheet") if isinstance(sheet, Mapping) else None
        if not isinstance(owner_sheet, Mapping):
            _fail("CG1_GM_CANDIDATE_SHEET_INVALID", "The Character Sheet snapshot is missing.")
        sheet_identity, sheet_artifact = self._sheet_snapshot(scratch_db, project_id, sheet, projection_identity)
        source = self._source_snapshot(
            candidate_project,
            owner_sheet,
            candidate_records,
            source_db=scratch_db,
        )
        factory_workspace: dict[str, Any] | None = None
        factory_workspace_files: dict[str, bytes] = {}
        if factory_authoring is not None:
            factory_workspace, factory_workspace_files = self._factory_workspace_snapshot(
                factory_authoring,
                project_id=project_id,
                candidate_project=candidate_project,
                scratch_root=scratch_path,
            )
        mechanics = {
            **event_snapshot,
            **self._receipt_snapshot(
                scratch_db,
                project_id,
                event_snapshot,
                stage2_commit,
                stage2_service,
                candidate_project_revision=candidate_project["metadata"]["project_revision"],
            ),
        }
        if mechanics["terminal_receipt"]["final_revision"] is not None and mechanics["terminal_receipt"]["final_revision"] > candidate_project["metadata"]["project_revision"]:
            _fail("CG1_GM_CANDIDATE_RECEIPT_INVALID", "The terminal receipt claims a revision beyond the candidate project.")
        plan = deepcopy(dict(final_plan)) if isinstance(final_plan, Mapping) else None
        plan_sha = sha256_json(plan) if plan is not None else None
        context = {
            "schema": CAPSULE_SCHEMA,
            "status": CAPSULE_STATUS,
            "run_id": run_id,
            "project_id": project_id,
            "request_sha256": request_anchor["request_sha256"],
            "response_sha256": request_anchor["response_sha256"],
            "response_bytes": len(request_anchor["response_bytes"]),
            "response_bytes_sha256": request_anchor["response_bytes_sha256"],
            "request_json_sha256": request_anchor["request_json_sha256"],
            "final_plan_sha256": plan_sha,
            "root_project": root_project["metadata"],
            "candidate_project": candidate_project["metadata"],
            "projection": projection_identity,
            "sheet": sheet_identity,
            "source": {
                "selected_record_content_sha256": source["selected_record_content_sha256"],
                "source_snapshot_sha256": sha256_json(source),
                "record_ids": list(source["snapshot"]["record_ids"]),
            },
            "mechanics": {
                "event_count": mechanics["event_count"],
                "event_head_hash": mechanics["event_head_hash"],
                "event_stream_sha256": mechanics["event_stream_sha256"],
                "terminal_receipt_id": mechanics["terminal_receipt"].get("commit_id"),
                "terminal_receipt_sha256": mechanics["terminal_receipt_sha256"],
                "rebuild_receipt_id": mechanics["rebuild_receipt"].get("rebuild_receipt_id") if mechanics["rebuild_receipt"] else None,
                "rebuild_receipt_sha256": mechanics["rebuild_receipt_sha256"],
            },
            "root_lock_snapshot_sha256": root_lock["lock_snapshot_sha256"],
            "candidate_lock_snapshot_sha256": candidate_lock["lock_snapshot_sha256"],
            "factory_workspace": deepcopy(factory_workspace),
            "gm_authoring_status": "NOT_AUTHORED",
            "owner_ratified": False,
            "ready_for_command5": False,
        }
        context_sha256 = sha256_json(context)
        context_payload = {**context, "context_sha256": context_sha256}
        entries: dict[str, bytes] = {
            "context.json": _json_bytes(context_payload),
            "root/project.json": root_project["raw"].encode("utf-8"),
            "candidate/project.json": candidate_project["raw"].encode("utf-8"),
            "response/exact_response_bytes": request_anchor["response_bytes"],
            "source/selected_record_source.json": _json_bytes(source),
            "owner_character_sheet.json": _json_bytes(owner_sheet),
            "sheet/Owner_Character_Sheet.json": sheet_artifact,
            "mechanics/events.json": _json_bytes(mechanics["events"]),
            "mechanics/receipts.json": _json_bytes({
                "schema": mechanics["schema"],
                "terminal_receipt": mechanics["terminal_receipt"],
                "rebuild_receipt": mechanics["rebuild_receipt"],
            }),
            "mechanics.json": _json_bytes(mechanics),
        }
        if plan is not None:
            entries["final_plan.json"] = _json_bytes(plan)
        for name, payload in projection_artifacts.items():
            entries[f"projection/{name}"] = payload
        for name, payload in factory_workspace_files.items():
            entries[f"{_FACTORY_WORKSPACE_PREFIX}{name}"] = payload
        entry_hashes = {name: sha256_bytes(payload) for name, payload in sorted(entries.items())}
        capsule_id = CAPSULE_ID_PREFIX + sha256_json({
            "run_id": run_id,
            "context_sha256": context_sha256,
            "entry_hashes": entry_hashes,
        })
        manifest_entries = {
            name: {
                "path": name,
                "sha256": entry_hashes[name],
                "bytes": len(entries[name]),
                "media_type": "application/octet-stream" if name == "response/exact_response_bytes" else "application/json",
            }
            for name in sorted(entries)
        }
        manifest_unsigned = {
            "schema": "TianxiaFoundry.GMCandidateCapsuleManifest.v1",
            "status": CAPSULE_STATUS,
            "run_id": run_id,
            "project_id": project_id,
            "capsule_id": capsule_id,
            "context_sha256": context_sha256,
            "entries": manifest_entries,
        }
        manifest = {
            **manifest_unsigned,
            "integrity": self.integrity.sign(MANIFEST_DOMAIN, manifest_unsigned).as_dict(),
        }
        manifest_bytes = _json_bytes(manifest)
        with _LOCK:
            root_fd = self._open_root_dir(create=True)
            opened = [root_fd]
            try:
                runs_fd = self._open_relative_dir(root_fd, ("runs",), create=True, label="runs")
                opened.append(runs_fd)
                run_fd = self._open_relative_dir(runs_fd, (self._run_key(run_id),), create=True, label="run")
                opened.append(run_fd)
                capsules_fd = self._open_relative_dir(run_fd, ("capsules",), create=True, label="capsules")
                opened.append(capsules_fd)
                capsule_fd = self._open_relative_dir(capsules_fd, (capsule_id,), create=True, label="capsule")
                opened.append(capsule_fd)
                for name, payload in entries.items():
                    relative = PurePosixPath(name)
                    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                        _fail("CG1_GM_CANDIDATE_PATH_INVALID", "A capsule payload path is invalid.")
                    parent_fd = self._open_relative_dir(capsule_fd, tuple(relative.parts[:-1]), create=True, label=name)
                    try:
                        self._write_immutable_at(parent_fd, relative.parts[-1], payload, label=name)
                    finally:
                        os.close(parent_fd)
                self._write_immutable_at(capsule_fd, "manifest.json", manifest_bytes, label="manifest")
                pointer_unsigned = {
                    "schema": "TianxiaFoundry.GMCandidateCapsulePointer.v1",
                    "status": CAPSULE_STATUS,
                    "run_id": run_id,
                    "project_id": project_id,
                    "capsule_id": capsule_id,
                    "context_sha256": context_sha256,
                    "manifest_sha256": sha256_bytes(manifest_bytes),
                }
                pointer = {
                    **pointer_unsigned,
                    "integrity": self.integrity.sign(POINTER_DOMAIN, pointer_unsigned).as_dict(),
                }
                self._write_pointer_at(run_fd, "current.json", _json_bytes(pointer))
            finally:
                for fd in reversed(opened):
                    os.close(fd)
        summary = self._summary({**context, "capsule_id": capsule_id, "context_sha256": context_sha256}, sha256_bytes(manifest_bytes))
        return summary

    def _validate_pointer(self, run_id: str) -> tuple[dict[str, Any], bytes, int]:
        root_fd = self._open_root_dir(create=False)
        opened = [root_fd]
        try:
            runs_fd = self._open_relative_dir(root_fd, ("runs",), create=False, label="runs")
            opened.append(runs_fd)
            run_fd = self._open_relative_dir(runs_fd, (self._run_key(run_id),), create=False, label="run")
            opened.append(run_fd)
            pointer_bytes = self._read_regular_at(run_fd, "current.json", label="capsule pointer")
            pointer = _parse_json_bytes(pointer_bytes, label="capsule pointer")
            if not isinstance(pointer, dict) or pointer.get("run_id") != run_id or pointer.get("status") != CAPSULE_STATUS:
                _fail("CG1_GM_CANDIDATE_POINTER_INVALID", "The capsule pointer is not bound to the requested run.")
            unsigned = {key: value for key, value in pointer.items() if key != "integrity"}
            self.integrity.verify(POINTER_DOMAIN, unsigned, pointer.get("integrity") or {})
            capsule_id = pointer.get("capsule_id")
            if not isinstance(capsule_id, str) or _CAPSULE_ID_RE.fullmatch(capsule_id) is None:
                _fail("CG1_GM_CANDIDATE_POINTER_INVALID", "The capsule pointer names an invalid capsule.")
            capsules_fd = self._open_relative_dir(run_fd, ("capsules",), create=False, label="capsules")
            opened.append(capsules_fd)
            capsule_fd = self._open_relative_dir(capsules_fd, (capsule_id,), create=False, label="capsule")
            opened.append(capsule_fd)
            result = (pointer, pointer_bytes, capsule_fd)
            opened.pop()  # The caller owns the capsule handle until load finishes.
            return result
        finally:
            for fd in reversed(opened):
                os.close(fd)

    def _load_manifest(self, capsule_fd: int, pointer: Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
        payload = self._read_regular_at(capsule_fd, "manifest.json", label="capsule manifest")
        if sha256_bytes(payload) != pointer.get("manifest_sha256"):
            _fail("CG1_GM_CANDIDATE_MANIFEST_TAMPERED", "The capsule pointer does not match the manifest bytes.")
        manifest = _parse_json_bytes(payload, label="capsule manifest")
        if not isinstance(manifest, dict) or manifest.get("status") != CAPSULE_STATUS or manifest.get("capsule_id") != pointer.get("capsule_id"):
            _fail("CG1_GM_CANDIDATE_MANIFEST_INVALID", "The capsule manifest identity is invalid.")
        unsigned = {key: value for key, value in manifest.items() if key != "integrity"}
        self.integrity.verify(MANIFEST_DOMAIN, unsigned, manifest.get("integrity") or {})
        return manifest, payload

    def _validate_entries(self, capsule_fd: int, manifest: Mapping[str, Any]) -> dict[str, bytes]:
        entries = manifest.get("entries")
        if not isinstance(entries, Mapping) or "context.json" not in entries:
            _fail("CG1_GM_CANDIDATE_MANIFEST_INVALID", "The capsule manifest has no complete payload inventory.")
        output: dict[str, bytes] = {}
        for raw_name, descriptor in entries.items():
            name = str(raw_name)
            relative = PurePosixPath(name)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in relative.parts)
                or not isinstance(descriptor, Mapping)
                or descriptor.get("path") != name
            ):
                _fail("CG1_GM_CANDIDATE_PATH_INVALID", "The capsule manifest contains a path traversal or invalid entry.", details={"path": name})
            parent_fd = self._open_relative_dir(capsule_fd, tuple(relative.parts[:-1]), create=False, label=name)
            try:
                payload = self._read_regular_at(parent_fd, relative.parts[-1], label=name)
            finally:
                os.close(parent_fd)
            if descriptor.get("bytes") != len(payload) or descriptor.get("sha256") != sha256_bytes(payload):
                _fail("CG1_GM_CANDIDATE_PAYLOAD_TAMPERED", "A capsule payload differs from its immutable manifest hash.", details={"path": name})
            output[name] = payload
        return output

    def _read_capsule_payloads_for_id(
        self,
        run_id: str,
        capsule_id: str,
    ) -> tuple[dict[str, Any], dict[str, bytes]]:
        """Read one immutable historical capsule by its authenticated identity."""
        run_id = _safe_identifier(run_id, "run")
        if not isinstance(capsule_id, str) or _CAPSULE_ID_RE.fullmatch(capsule_id) is None:
            _fail("CG1_GM_CANDIDATE_POINTER_INVALID", "The historical capsule identity is invalid.")
        with _LOCK:
            root_fd = self._open_root_dir(create=False)
            opened = [root_fd]
            try:
                runs_fd = self._open_relative_dir(root_fd, ("runs",), create=False, label="runs")
                opened.append(runs_fd)
                run_fd = self._open_relative_dir(runs_fd, (self._run_key(run_id),), create=False, label="run")
                opened.append(run_fd)
                capsules_fd = self._open_relative_dir(run_fd, ("capsules",), create=False, label="capsules")
                opened.append(capsules_fd)
                capsule_fd = self._open_relative_dir(capsules_fd, (capsule_id,), create=False, label="historical capsule")
                opened.append(capsule_fd)
                manifest_bytes = self._read_regular_at(capsule_fd, "manifest.json", label="historical capsule manifest")
                pointer = {"capsule_id": capsule_id, "manifest_sha256": sha256_bytes(manifest_bytes)}
                manifest, _ = self._load_manifest(capsule_fd, pointer)
                if manifest.get("run_id") != run_id:
                    _fail("CG1_GM_CANDIDATE_POINTER_INVALID", "The historical capsule is bound to another run.")
                payloads = self._validate_entries(capsule_fd, manifest)
            finally:
                for fd in reversed(opened):
                    os.close(fd)
        return manifest, payloads

    def _read_capsule_payloads(
        self,
        run_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
        """Read and authenticate one capsule without exposing raw payloads publicly."""
        with _LOCK:
            pointer, _pointer_bytes, capsule_fd = self._validate_pointer(run_id)
            try:
                manifest, _manifest_bytes = self._load_manifest(capsule_fd, pointer)
                payloads = self._validate_entries(capsule_fd, manifest)
            finally:
                os.close(capsule_fd)
        return pointer, manifest, payloads

    def materialize_factory_workspace(self, run_id: str, destination: Path) -> dict[str, Any]:
        """Materialize the authenticated Factory workspace into a fresh directory."""
        run_id = _safe_identifier(run_id, "run")
        pointer, _manifest, payloads = self._read_capsule_payloads(run_id)
        context = _parse_json_bytes(payloads["context.json"], label="candidate context")
        if not isinstance(context, dict) or context.get("context_sha256") != pointer.get("context_sha256"):
            _fail("CG1_GM_CANDIDATE_CONTEXT_INVALID", "The candidate context does not match its pointer.")
        context_without_hash = {key: value for key, value in context.items() if key != "context_sha256"}
        if sha256_json(context_without_hash) != context.get("context_sha256"):
            _fail("CG1_GM_CANDIDATE_CONTEXT_TAMPERED", "The candidate context hash is invalid.")
        if context.get("run_id") != run_id or context.get("capsule_id") not in {None, pointer.get("capsule_id")}:
            _fail("CG1_GM_CANDIDATE_CONTEXT_INVALID", "The candidate context is bound to another run or capsule.")
        response_payload = payloads.get("response/exact_response_bytes")
        if response_payload is None:
            _fail("CG1_GM_CANDIDATE_PAYLOAD_MISSING", "The capsule has no exact persisted response bytes.")
        self._validate_current_root(context, response_payload)
        workspace = context.get("factory_workspace")
        if not isinstance(workspace, Mapping) or workspace.get("schema") != _FACTORY_WORKSPACE_SCHEMA:
            _fail("CG1_GM_CANDIDATE_WORKSPACE_MISSING", "The candidate capsule has no authenticated Factory workspace.")
        prefix = _FACTORY_WORKSPACE_PREFIX
        expected_files = workspace.get("file_hashes")
        if (
            not isinstance(expected_files, Mapping)
            or not expected_files
            or workspace.get("project_id") != context.get("project_id")
            or workspace.get("project_revision") != context.get("candidate_project", {}).get("project_revision")
            or not _SHA256_RE.fullmatch(str(workspace.get("workspace_sha256") or ""))
            or not _SHA256_RE.fullmatch(str(workspace.get("manifest_sha256") or ""))
        ):
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The authenticated Factory workspace binding is incomplete.")
        actual_names = {
            name[len(prefix):]
            for name in payloads
            if name.startswith(prefix)
        }
        expected_names = {str(name) for name in expected_files}
        if actual_names != expected_names or any(
            not relative or PurePosixPath(relative).is_absolute() or any(
                part in {"", ".", ".."} or "/" in part or "\\" in part
                for part in PurePosixPath(relative).parts
            )
            for relative in expected_names
        ):
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The capsule Factory workspace inventory is incomplete or unsafe.")
        files: dict[str, bytes] = {}
        for relative in sorted(expected_names):
            payload = payloads[prefix + relative]
            if expected_files.get(relative) != sha256_bytes(payload):
                _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "A Factory workspace entry differs from its authenticated hash.", details={"path": relative})
            files[relative] = payload
        if sha256_json({name: sha256_bytes(payload) for name, payload in sorted(files.items())}) != workspace.get("workspace_sha256"):
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The materialized Factory workspace tree hash is invalid.")
        manifest_payload = files.get("Workspace_Manifest.json")
        if manifest_payload is None:
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace manifest is missing.")
        manifest = _parse_json_bytes(manifest_payload, label="Factory workspace manifest")
        if (
            not isinstance(manifest, Mapping)
            or manifest.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
            or manifest.get("project_id") not in {None, context.get("project_id")}
            or manifest.get("project_revision") != workspace.get("project_revision")
            or sha256_bytes(manifest_payload) != workspace.get("manifest_sha256")
        ):
            _fail("CG1_GM_CANDIDATE_WORKSPACE_INVALID", "The Factory workspace manifest is not bound to the candidate.")
        destination = Path(os.path.abspath(os.fspath(destination)))
        if destination.exists():
            if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
                _fail("CG1_GM_CANDIDATE_WORKSPACE_PATH_INVALID", "The Factory workspace destination must be a fresh directory.")
        else:
            destination.mkdir(parents=True, exist_ok=False)
        for relative, payload in files.items():
            target = destination / Path(*PurePosixPath(relative).parts)
            self._assert_no_symlink_path(destination, target, label="materialized Factory workspace")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                _fail("CG1_GM_CANDIDATE_WORKSPACE_PATH_INVALID", "The Factory workspace destination has a file collision.")
            target.write_bytes(payload)
        return {
            "schema": _FACTORY_WORKSPACE_SCHEMA,
            "project_id": workspace["project_id"],
            "project_revision": workspace["project_revision"],
            "workspace_sha256": workspace["workspace_sha256"],
            "manifest_sha256": workspace["manifest_sha256"],
            "candidate_binding_sha256": workspace.get("candidate_binding_sha256"),
            "file_count": len(files),
            "root": destination,
        }

    def _validate_current_root(self, context: Mapping[str, Any], response_bytes: bytes) -> None:
        project_id = context["project_id"]
        if (
            type(context.get("response_bytes")) is not int
            or context["response_bytes"] != len(response_bytes)
            or _require_sha(context.get("response_bytes_sha256"), "response bytes") != sha256_bytes(response_bytes)
        ):
            _fail("CG1_GM_CANDIDATE_CONTEXT_INVALID", "The staged exact response bytes do not match their context hash.")
        request_anchor = self._request_anchor({
            "run_id": context["run_id"],
            "project_id": project_id,
            "starting_revision": context["root_project"]["project_revision"],
            "request": None,
            "response": {"response_sha256": context["response_sha256"]},
        }, self.db)
        if (
            request_anchor["request_sha256"] != context["request_sha256"]
            or request_anchor["request_json_sha256"] != context["request_json_sha256"]
            or (
                request_anchor.get("persisted_response_sha256") is not None
                and request_anchor["persisted_response_sha256"] != context["response_sha256"]
            )
            or request_anchor["response_sha256"] != context["response_sha256"]
            or request_anchor["response_bytes"] != response_bytes
        ):
            _fail("CG1_GM_CANDIDATE_ROOT_ANCHOR_STALE", "The persisted request no longer matches the capsule context.")
        current, lock_snapshot, _records = self._project_snapshot(self.db, project_id, label="root")
        expected = context["root_project"]
        if current["metadata"] != expected or lock_snapshot["lock_snapshot_sha256"] != context["root_lock_snapshot_sha256"]:
            _fail("CG1_GM_CANDIDATE_ROOT_ANCHOR_STALE", "The root project or lock snapshot changed after capsule capture.")

    def _decode_capsule_payloads(
        self,
        run_id: str,
        pointer: Mapping[str, Any],
        manifest: Mapping[str, Any],
        payloads: Mapping[str, bytes],
        *,
        validate_current_root: bool,
    ) -> dict[str, Any]:
        run_id = _safe_identifier(run_id, "run")
        context = _parse_json_bytes(payloads["context.json"], label="candidate context")
        if not isinstance(context, dict) or context.get("context_sha256") != pointer.get("context_sha256"):
            _fail("CG1_GM_CANDIDATE_CONTEXT_INVALID", "The candidate context does not match its pointer.")
        context_without_hash = {key: value for key, value in context.items() if key != "context_sha256"}
        if sha256_json(context_without_hash) != context.get("context_sha256"):
            _fail("CG1_GM_CANDIDATE_CONTEXT_TAMPERED", "The candidate context hash is invalid.")
        if context.get("run_id") != run_id or context.get("capsule_id") not in {None, pointer.get("capsule_id")}:
            _fail("CG1_GM_CANDIDATE_CONTEXT_INVALID", "The candidate context is bound to another run or capsule.")
        response_payload = payloads.get("response/exact_response_bytes")
        if response_payload is None:
            _fail("CG1_GM_CANDIDATE_PAYLOAD_MISSING", "The capsule has no exact persisted response bytes.")
        if validate_current_root:
            self._validate_current_root(context, response_payload)
        try:
            exact_response_text = response_payload.decode("utf-8")
        except UnicodeDecodeError:
            _fail("CG1_GM_CANDIDATE_PAYLOAD_INVALID", "The exact persisted response bytes are not UTF-8 text.")
        root_project = _parse_json_bytes(payloads["root/project.json"], label="root project")
        candidate_project = _parse_json_bytes(payloads["candidate/project.json"], label="candidate project")
        owner_sheet = _parse_json_bytes(payloads["owner_character_sheet.json"], label="owner Character Sheet")
        source = _parse_json_bytes(payloads["source/selected_record_source.json"], label="selected record source")
        mechanics = _parse_json_bytes(payloads["mechanics.json"], label="mechanics")
        events = _parse_json_bytes(payloads["mechanics/events.json"], label="event stream")
        if (
            not isinstance(root_project, dict)
            or sha256_json(root_project) != context["root_project"]["canonical_project_hash"]
            or not isinstance(candidate_project, dict)
            or sha256_json(candidate_project) != context["candidate_project"]["canonical_project_hash"]
            or not isinstance(source, dict)
            or sha256_json(source) != context["source"]["source_snapshot_sha256"]
        ):
            _fail("CG1_GM_CANDIDATE_CONTEXT_INVALID", "A staged source payload differs from its authenticated context anchors.")
        if mechanics.get("events") != events or context["mechanics"]["event_stream_sha256"] != mechanics.get("event_stream_sha256"):
            _fail("CG1_GM_CANDIDATE_MECHANICS_INVALID", "The staged mechanics files disagree with the capsule context.")
        if (
            mechanics.get("event_count") != context["mechanics"]["event_count"]
            or mechanics.get("event_head_hash") != context["mechanics"]["event_head_hash"]
        ):
            _fail("CG1_GM_CANDIDATE_MECHANICS_INVALID", "The staged event count or head differs from its authenticated context.")
        final_plan = None
        if "final_plan.json" in payloads:
            final_plan = _parse_json_bytes(payloads["final_plan.json"], label="final plan")
            if context.get("final_plan_sha256") != sha256_json(final_plan):
                _fail("CG1_GM_CANDIDATE_CONTEXT_INVALID", "The staged final plan differs from its bound hash.")
        projection_artifacts: dict[str, Any] = {}
        for name in _REQUIRED_PROJECTION_ARTIFACTS:
            key = f"projection/{name}"
            if key not in payloads:
                _fail("CG1_GM_CANDIDATE_PAYLOAD_MISSING", "A required projection artifact is absent.", details={"artifact_name": name})
            projection_artifacts[name] = _parse_json_bytes(payloads[key], label=f"projection artifact {name}")
            if context["projection"]["artifact_hashes"].get(name) != sha256_bytes(payloads[key]):
                _fail("CG1_GM_CANDIDATE_PROJECTION_TAMPERED", "A projection artifact differs from its context hash.", details={"artifact_name": name})
        sheet_artifact = _parse_json_bytes(payloads["sheet/Owner_Character_Sheet.json"], label="Character Sheet artifact")
        if sheet_artifact != owner_sheet or context["sheet"]["artifact_sha256"] != sha256_bytes(payloads["sheet/Owner_Character_Sheet.json"]):
            _fail("CG1_GM_CANDIDATE_SHEET_TAMPERED", "The staged Character Sheet artifact differs from its context hash.")
        if source.get("selected_record_content_sha256") != context["source"]["selected_record_content_sha256"]:
            _fail("CG1_GM_CANDIDATE_SOURCE_INVALID", "The selected-record source differs from its context hash.")
        summary = self._summary({**context, "capsule_id": pointer["capsule_id"], "context_sha256": context["context_sha256"]}, pointer["manifest_sha256"])
        return {
            "schema": CAPSULE_SCHEMA,
            "status": CAPSULE_STATUS,
            "summary": summary,
            "context": context,
            "exact_response_text": exact_response_text,
            "root_project": root_project,
            "candidate_project": candidate_project,
            "owner_character_sheet": owner_sheet,
            "selected_record_source": source,
            "events": events,
            "stage2_mechanics": mechanics,
            "final_plan": final_plan,
            "projection_artifacts": projection_artifacts,
            "sheet_artifact": sheet_artifact,
            "manifest": {
                "schema": manifest.get("schema"),
                "capsule_id": manifest.get("capsule_id"),
                "context_sha256": manifest.get("context_sha256"),
                "entries": deepcopy(manifest.get("entries") or {}),
            },
        }

    def _load_immutable_capsule_for_id(
        self,
        run_id: str,
        capsule_id: str,
    ) -> dict[str, Any]:
        """Decode one authenticated capsule without checking the live root.

        The capsule manifest and every payload remain authenticated by the
        existing immutable reader.  This private path is only for a caller
        that already binds the capsule identity to a frozen approval proof;
        ordinary ``load`` keeps its current-root validation.
        """
        run_id = _safe_identifier(run_id, "run")
        manifest, payloads = self._read_capsule_payloads_for_id(run_id, capsule_id)
        pointer = {
            "capsule_id": capsule_id,
            "context_sha256": manifest.get("context_sha256"),
            "manifest_sha256": sha256_bytes(_json_bytes(manifest)),
        }
        return self._decode_capsule_payloads(
            run_id,
            pointer,
            manifest,
            payloads,
            validate_current_root=False,
        )

    def load(self, run_id: str) -> dict[str, Any]:
        run_id = _safe_identifier(run_id, "run")
        pointer, manifest, payloads = self._read_capsule_payloads(run_id)
        return self._decode_capsule_payloads(
            run_id,
            pointer,
            manifest,
            payloads,
            validate_current_root=True,
        )

    def summary(self, run_id: str) -> dict[str, Any]:
        return self.load(run_id)["summary"]


__all__ = ["CAPSULE_SCHEMA", "CAPSULE_STATUS", "CandidateGMCapsuleStore"]
