"""Opt-in Li Wei golden-output characterization and capture CLI.

This module intentionally contains no accepted data, hashes, private paths, or
path defaults.  Capture requires every input location and the output manifest
location explicitly.  Recalculation is read-only and provider-free.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import pytest

# Keep the explicit capture CLI runnable both as ``python -m`` with APP on
# PYTHONPATH and as ``python APP/tests/test_golden_li_wei.py`` from the repo.
if __package__ in {None, ""}:
    _APP_ROOT = Path(__file__).resolve().parents[1]
    if str(_APP_ROOT) not in sys.path:
        sys.path.insert(0, str(_APP_ROOT))

from combat.canonical import canonical_bytes, canonical_sha256
from combat.character_runtime_adapter import (
    CharacterCombatRuntimeAdapter,
    RuntimeResourceInitialization,
)


GOLDEN_DATA_ROOT_ENV = "TIANXIA_GOLDEN_LI_WEI_DATA_ROOT"
GOLDEN_MANIFEST_ENV = "TIANXIA_GOLDEN_LI_WEI_MANIFEST"
GOLDEN_SCHEMA = "TianxiaFoundry.LiWeiGoldenManifest.v1"
CANDIDATE_ACTION_SURFACE_SCHEMA = "TianxiaFoundry.Command4CompleteActionSurface.v1"
PORTABLE_READINESS_SCHEMA = "TianxiaFoundry.PortableCharacterReadiness.v1"
_COMBAT_SHEET_MEMBER = "combat/Combat_Sheet.json"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_MEMBER_RE = re.compile(r"^[^\x00-\x1f\x7f]+$")
_READINESS_STATE_TYPES = {
    "combat": str,
    "combat_execution": str,
    "combat_runtime": str,
    "combat_sheet": str,
    "combat_ready_semantics": str,
    "encounter": str,
    "controller_selection": str,
    "encounter_setup_required": bool,
    "token_placement": str,
    "initiative": str,
}
_READINESS_STATE_KEYS = tuple(sorted(_READINESS_STATE_TYPES))
_RUNTIME_INITIALIZATION = {
    "qi_current": 0,
    "martial_focus_current": 0,
    "provenance_kind": "TEST_FIXTURE",
    "provenance_id": "phase0-golden-runtime",
    "canonical_owner_choice": False,
}


class GoldenEvidenceError(RuntimeError):
    """The supplied golden evidence is incomplete, unsafe, or inconsistent."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _safe_absolute(path: Path, *, label: str) -> Path:
    """Return an absolute path while rejecting symlink components."""

    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        if current.is_symlink():
            raise GoldenEvidenceError(f"{label} contains a symlink: {current}")
    return absolute


def _data_root(path: str | Path) -> Path:
    root = _safe_absolute(Path(path), label="data root")
    if not root.exists() or not root.is_dir():
        raise GoldenEvidenceError(f"data root is not a directory: {root}")
    return root


def _relative_input(root: Path, value: str | Path, *, label: str, expect: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise GoldenEvidenceError(f"{label} must be a clean relative path below data root")
    absolute = _safe_absolute(root / candidate, label=label)
    try:
        absolute.relative_to(root)
    except ValueError as exc:
        raise GoldenEvidenceError(f"{label} escapes data root") from exc
    if expect == "file" and (not absolute.exists() or not absolute.is_file()):
        raise GoldenEvidenceError(f"{label} is not a regular file: {candidate}")
    if expect == "directory" and (not absolute.exists() or not absolute.is_dir()):
        raise GoldenEvidenceError(f"{label} is not a directory: {candidate}")
    return absolute


def _relative_manifest_path(root: Path, value: Any, *, label: str, expect: str) -> Path:
    if not isinstance(value, str):
        raise GoldenEvidenceError(f"manifest {label} is missing")
    return _relative_input(root, value, label=label, expect=expect)


def _immutable_connection(source_db: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(source_db), safe='/:')}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection
    except sqlite3.Error as exc:
        raise GoldenEvidenceError("could not open the golden database read-only/immutable") from exc


def _load_run(source_db: Path, *, project_id: str, run_id: str) -> sqlite3.Row:
    connection = _immutable_connection(source_db)
    try:
        try:
            row = connection.execute(
                """
                SELECT run_id, project_id, status, final_plan_json
                FROM character_creation_runs
                WHERE run_id=?
                """,
                (run_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise GoldenEvidenceError("golden database lacks the final-plan run contract") from exc
    finally:
        connection.close()
    if row is None:
        raise GoldenEvidenceError(f"golden run is missing: {run_id}")
    if row["run_id"] != run_id or row["project_id"] != project_id:
        raise GoldenEvidenceError("golden run/project identity does not match the requested identity")
    return row


def _json_value_and_kind(raw: Any, *, label: str) -> tuple[Any, str]:
    if raw is None:
        return None, "SQL_NULL"
    if not isinstance(raw, str):
        raise GoldenEvidenceError(f"{label} is not TEXT or SQL NULL")
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GoldenEvidenceError(f"{label} contains malformed JSON") from exc
    return value, "JSON_NULL" if value is None else "VALUE"


def _canonical_json_file(path: Path, *, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoldenEvidenceError(f"{label} is not valid UTF-8 JSON") from exc
    canonical = _canonical_json(value).encode("utf-8")
    return {
        "sha256": _sha256_bytes(canonical),
        "bytes": len(canonical),
    }


def _canonical_json_document(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    """Read a strict object and return its canonical bytes for evidence."""

    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_bytes().decode("utf-8"),
            object_pairs_hook=no_duplicate_keys,
        )
        if not isinstance(value, dict):
            raise ValueError("top-level JSON value is not an object")
        canonical = canonical_bytes(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise GoldenEvidenceError(f"{label} is not a canonical UTF-8 JSON object") from exc
    return value, canonical


def _require_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise GoldenEvidenceError(f"{label} must be a non-empty string")
    return value


def _require_boolean(value: Any, *, label: str) -> bool:
    if type(value) is not bool:
        raise GoldenEvidenceError(f"{label} must be a boolean")
    return value


def _require_integer(value: Any, *, label: str) -> int:
    if type(value) is not int:
        raise GoldenEvidenceError(f"{label} must be an integer")
    return value


def _candidate_action_surface_manifest(path: Path) -> dict[str, Any]:
    surface, canonical = _canonical_json_document(path, label="candidate action surface")
    for key in (
        "schema_version",
        "status",
        "candidate_status",
        "project_id",
        "workspace_authority",
    ):
        _require_string(surface.get(key), label=f"candidate action surface {key}")
    if surface["schema_version"] != CANDIDATE_ACTION_SURFACE_SCHEMA:
        raise GoldenEvidenceError("candidate action surface schema is unsupported")
    if surface["status"] != "ACTION_SURFACE_PARTIAL":
        raise GoldenEvidenceError("candidate action surface status is not the accepted partial state")
    if surface["candidate_status"] != "CANDIDATE_NON_AUTHORITATIVE":
        raise GoldenEvidenceError("candidate action surface is not marked non-authoritative")
    for key in ("global_combat_readiness", "execution_authority", "mechanical_authority"):
        _require_boolean(surface.get(key), label=f"candidate action surface {key}")
    if surface["global_combat_readiness"] or surface["execution_authority"]:
        raise GoldenEvidenceError("candidate action surface claims combat or execution authority")
    if not surface["mechanical_authority"]:
        raise GoldenEvidenceError("candidate action surface lost mechanical authority")

    project_revision = _require_integer(surface.get("project_revision"), label="candidate action surface project_revision")
    if project_revision < 0:
        raise GoldenEvidenceError("candidate action surface project_revision is negative")
    actions = surface.get("actions")
    unresolved = surface.get("unresolved")
    if not isinstance(actions, list) or not isinstance(unresolved, list):
        raise GoldenEvidenceError("candidate action surface actions/unresolved must be arrays")
    if len(actions) != 0:
        raise GoldenEvidenceError("accepted candidate action surface must contain zero executable actions")
    if len(unresolved) != 8:
        raise GoldenEvidenceError("accepted candidate action surface must contain exactly eight unresolved rows")
    for index, row in enumerate(unresolved):
        if not isinstance(row, dict):
            raise GoldenEvidenceError(f"candidate action surface unresolved[{index}] must be an object")
        for key in ("action_id", "record_id", "status"):
            _require_string(row.get(key), label=f"candidate action surface unresolved[{index}].{key}")
        diagnostics = row.get("diagnostics")
        missing_fields = row.get("missing_fields")
        if not isinstance(diagnostics, list) or not isinstance(missing_fields, list):
            raise GoldenEvidenceError(f"candidate action surface unresolved[{index}] diagnostics/missing_fields must be arrays")
        if not all(isinstance(field, str) and field for field in missing_fields):
            raise GoldenEvidenceError(f"candidate action surface unresolved[{index}].missing_fields must contain strings")
        for diagnostic_index, diagnostic in enumerate(diagnostics):
            if not isinstance(diagnostic, dict):
                raise GoldenEvidenceError(
                    f"candidate action surface unresolved[{index}].diagnostics[{diagnostic_index}] must be an object"
                )
            _require_string(
                diagnostic.get("code"),
                label=f"candidate action surface unresolved[{index}].diagnostics[{diagnostic_index}].code",
            )

    provenance = surface.get("provenance")
    if not isinstance(provenance, dict):
        raise GoldenEvidenceError("candidate action surface provenance must be an object")
    _require_string(provenance.get("algorithm"), label="candidate action surface provenance algorithm")
    _require_string(provenance.get("workspace_authority"), label="candidate action surface provenance workspace_authority")
    for key in ("eligible_record_count", "selected_record_count"):
        count = _require_integer(provenance.get(key), label=f"candidate action surface provenance {key}")
        if count < 0:
            raise GoldenEvidenceError(f"candidate action surface provenance {key} is negative")
    identity = provenance.get("project_identity")
    if not isinstance(identity, dict):
        raise GoldenEvidenceError("candidate action surface provenance project_identity must be an object")
    _require_string(identity.get("project_id"), label="candidate action surface provenance project_id")
    identity_revision = _require_integer(
        identity.get("project_revision"),
        label="candidate action surface provenance project_revision",
    )
    if identity_revision != project_revision or identity["project_id"] != surface["project_id"]:
        raise GoldenEvidenceError("candidate action surface provenance identity does not match the surface")
    return {
        "canonical_sha256": _sha256_bytes(canonical),
        "canonical_bytes": len(canonical),
        "schema_version": surface["schema_version"],
        "status": surface["status"],
        "candidate_status": surface["candidate_status"],
        "global_combat_readiness": surface["global_combat_readiness"],
        "execution_authority": surface["execution_authority"],
        "mechanical_authority": surface["mechanical_authority"],
        "actions_count": len(actions),
        "unresolved_count": len(unresolved),
    }


def _validate_member_name(name: str) -> None:
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or not _SAFE_MEMBER_RE.fullmatch(name)
    ):
        raise GoldenEvidenceError(f"GM export contains an unsafe member path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise GoldenEvidenceError(f"GM export contains an unsafe member path: {name!r}")


def _zip_manifest(path: Path) -> dict[str, Any]:
    members: list[dict[str, Any]] = []
    names: set[str] = set()
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise GoldenEvidenceError("GM export is not a readable ZIP archive") from exc
    with archive:
        for info in archive.infolist():
            _validate_member_name(info.filename)
            if info.filename in names:
                raise GoldenEvidenceError(f"GM export contains a duplicate member: {info.filename}")
            names.add(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if stat.S_ISLNK(mode):
                raise GoldenEvidenceError(f"GM export contains a symlink member: {info.filename}")
            directory = info.is_dir() or stat.S_ISDIR(mode)
            if not directory and mode not in {0, stat.S_IFREG}:
                raise GoldenEvidenceError(f"GM export contains a non-regular member: {info.filename}")
            try:
                raw = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise GoldenEvidenceError(f"GM export member cannot be read: {info.filename}") from exc
            members.append(
                {
                    "name": info.filename,
                    "directory": directory,
                    "bytes": len(raw),
                    "compressed_bytes": info.compress_size,
                    "sha256": _sha256_bytes(raw),
                }
            )
    members.sort(key=lambda row: row["name"])
    return {"members": members}


def _combat_zip_inventory(path: Path) -> dict[str, Any]:
    """Return only safe, deterministic members below the optional combat/ root."""

    manifest = _zip_manifest(path)
    members: list[dict[str, Any]] = []
    for row in manifest["members"]:
        name = row["name"]
        if name == "combat":
            raise GoldenEvidenceError("portable package contains an unsafe combat root member")
        if not name.startswith("combat/"):
            continue
        if row["directory"]:
            raise GoldenEvidenceError(f"portable package combat inventory contains a directory: {name}")
        members.append(row)
    members.sort(key=lambda row: row["name"])
    return {
        "members": members,
        "combat_sheet_present": any(row["name"] == _COMBAT_SHEET_MEMBER for row in members),
    }


def _portable_readiness_manifest(path: Path) -> dict[str, Any]:
    """Canonicalize portable readiness and retain only its readiness states."""

    inventory = _zip_manifest(path)
    readiness_rows = [row for row in inventory["members"] if row["name"] == "READINESS.json"]
    if not readiness_rows:
        raise GoldenEvidenceError("portable package is missing READINESS.json")
    if readiness_rows[0]["directory"]:
        raise GoldenEvidenceError("portable package READINESS.json is a directory")
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("READINESS.json")
    except (OSError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
        raise GoldenEvidenceError("portable package READINESS.json cannot be read") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("top-level JSON value is not an object")
        canonical = canonical_bytes(value)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise GoldenEvidenceError("portable package READINESS.json is not canonical UTF-8 JSON") from exc
    if value.get("schema_version") != PORTABLE_READINESS_SCHEMA:
        raise GoldenEvidenceError("portable package readiness schema is unsupported")
    for key, expected_type in _READINESS_STATE_TYPES.items():
        if key not in value:
            continue
        current = value[key]
        if expected_type is bool:
            if type(current) is not bool:
                raise GoldenEvidenceError(f"portable package readiness {key} must be a boolean")
        elif current is not None and not isinstance(current, expected_type):
            raise GoldenEvidenceError(f"portable package readiness {key} must be a string or null")
    return {
        "canonical_sha256": _sha256_bytes(canonical),
        "canonical_bytes": len(canonical),
        "schema_version": value["schema_version"],
        **{key: value.get(key) for key in _READINESS_STATE_KEYS},
    }


def _build_manifest(build_root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(build_root.rglob("*"), key=lambda item: item.relative_to(build_root).as_posix()):
        if path.is_symlink():
            raise GoldenEvidenceError(f"Build contains a symlink: {path.relative_to(build_root)}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise GoldenEvidenceError(f"Build contains a non-regular file: {path.relative_to(build_root)}")
        digest, size = _sha256_file(path)
        files.append({"path": path.relative_to(build_root).as_posix(), "bytes": size, "sha256": digest})
    return {"root": "Build", "files": files}


def _runtime_manifest(
    package: Path,
    *,
    combat_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    combat_inventory = combat_inventory or _combat_zip_inventory(package)
    if not combat_inventory["combat_sheet_present"]:
        return {
            "status": "NOT_READY",
            "compiled": False,
            "reason": "COMBAT_SHEET_NOT_PRESENT",
        }
    try:
        initialization = RuntimeResourceInitialization.model_validate(_RUNTIME_INITIALIZATION)
        adapter = CharacterCombatRuntimeAdapter(package)
        bundle = adapter.build_bundle(initialization)
        payload = bundle.model_dump(mode="json", by_alias=True)
    except Exception as exc:
        # Do not expose package internals or a provider error in public golden
        # evidence; the test still fails with a useful boundary label.
        raise GoldenEvidenceError("portable package could not build a combat runtime bundle") from exc
    return {
        "status": "COMBAT_RUNTIME_READY",
        "compiled": True,
        "initialization": initialization.model_dump(mode="json"),
        "bundle_sha256": bundle.bundle_sha256,
        "canonical_sha256": canonical_sha256(payload),
    }


def _manifest_inputs(
    root: Path,
    *,
    candidate_workspace: str | Path,
    owner_sheet: str | Path,
    gm_export: str | Path,
    portable_package: str | Path,
) -> dict[str, str]:
    candidate = _relative_input(root, candidate_workspace, label="candidate workspace", expect="directory")
    _relative_input(root, owner_sheet, label="owner sheet", expect="file")
    _relative_input(root, gm_export, label="GM export", expect="file")
    _relative_input(root, portable_package, label="portable package", expect="file")
    _relative_input(candidate, "Build", label="Build directory", expect="directory")
    return {
        "source_db": "foundry.sqlite3",
        "candidate_workspace": candidate.relative_to(root).as_posix(),
        "owner_sheet": Path(owner_sheet).as_posix(),
        "gm_export": Path(gm_export).as_posix(),
        "portable_package": Path(portable_package).as_posix(),
    }


def build_golden_manifest(
    data_root: str | Path,
    *,
    project_id: str,
    run_id: str,
    candidate_workspace: str | Path,
    owner_sheet: str | Path,
    gm_export: str | Path,
    portable_package: str | Path,
) -> dict[str, Any]:
    """Recompute all Phase 0 golden surfaces without writing or using a provider."""

    root = _data_root(data_root)
    if not isinstance(project_id, str) or not project_id:
        raise GoldenEvidenceError("project_id must be a non-empty string")
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise GoldenEvidenceError("run_id must be filesystem-safe and reversible")
    inputs = _manifest_inputs(
        root,
        candidate_workspace=candidate_workspace,
        owner_sheet=owner_sheet,
        gm_export=gm_export,
        portable_package=portable_package,
    )
    source_db = _relative_input(root, inputs["source_db"], label="source database", expect="file")
    candidate = _relative_input(root, inputs["candidate_workspace"], label="candidate workspace", expect="directory")
    owner = _relative_input(root, inputs["owner_sheet"], label="owner sheet", expect="file")
    gm = _relative_input(root, inputs["gm_export"], label="GM export", expect="file")
    portable = _relative_input(root, inputs["portable_package"], label="portable package", expect="file")
    row = _load_run(source_db, project_id=project_id, run_id=run_id)
    final_plan, final_plan_kind = _json_value_and_kind(row["final_plan_json"], label="final_plan_json")
    final_plan_bytes = _canonical_json(final_plan).encode("utf-8")
    source_db_sha256, source_db_bytes = _sha256_file(source_db)
    combat_inventory = _combat_zip_inventory(portable)
    return {
        "schema": GOLDEN_SCHEMA,
        "source_database": {
            "relative_path": inputs["source_db"],
            "sha256": source_db_sha256,
            "bytes": source_db_bytes,
        },
        "run": {
            "run_id": row["run_id"],
            "project_id": row["project_id"],
            "status": row["status"],
        },
        "inputs": inputs,
        "final_plan": {
            "sha256": _sha256_bytes(final_plan_bytes),
            "bytes": len(final_plan_bytes),
            "null_kind": final_plan_kind,
        },
        "owner_sheet": _canonical_json_file(owner, label="owner sheet"),
        "gm_export": _zip_manifest(gm),
        "build": _build_manifest(candidate / "Build"),
        "candidate_action_surface": _candidate_action_surface_manifest(
            candidate / "Build" / "Complete_Action_Surface.json"
        ),
        "portable_readiness": _portable_readiness_manifest(portable),
        "combat_runtime": {
            "members": combat_inventory["members"],
            **_runtime_manifest(portable, combat_inventory=combat_inventory),
        },
    }


def _tree_manifest(root: Path) -> dict[str, tuple[int, str]]:
    """Hash every regular file below root to detect any recomputation write."""

    result: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise GoldenEvidenceError(f"data root contains a symlink: {path.relative_to(root)}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise GoldenEvidenceError(f"data root contains a non-regular file: {path.relative_to(root)}")
        digest, size = _sha256_file(path)
        result[path.relative_to(root).as_posix()] = (size, digest)
    return result


def _manifest_output_path(path: str | Path, data_root: Path) -> Path:
    output = _safe_absolute(Path(path), label="manifest output")
    try:
        output.relative_to(data_root)
    except ValueError:
        pass
    else:
        raise GoldenEvidenceError("manifest output must remain outside data root")
    if output.exists() and output.is_dir():
        raise GoldenEvidenceError("manifest output is a directory")
    return output


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    payload = _canonical_json(manifest).encode("utf-8")
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise GoldenEvidenceError(f"conflicting existing manifest: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def capture_golden_manifest(
    data_root: str | Path,
    *,
    project_id: str,
    run_id: str,
    candidate_workspace: str | Path,
    owner_sheet: str | Path,
    gm_export: str | Path,
    portable_package: str | Path,
    manifest: str | Path,
) -> dict[str, Any]:
    root = _data_root(data_root)
    manifest_path = _manifest_output_path(manifest, root)
    result = build_golden_manifest(
        root,
        project_id=project_id,
        run_id=run_id,
        candidate_workspace=candidate_workspace,
        owner_sheet=owner_sheet,
        gm_export=gm_export,
        portable_package=portable_package,
    )
    _write_manifest(manifest_path, result)
    return result


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidate-workspace", required=True)
    parser.add_argument("--owner-sheet", required=True)
    parser.add_argument("--gm-export", required=True)
    parser.add_argument("--portable-package", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        result = capture_golden_manifest(
            args.data_root,
            project_id=args.project_id,
            run_id=args.run_id,
            candidate_workspace=args.candidate_workspace,
            owner_sheet=args.owner_sheet,
            gm_export=args.gm_export,
            portable_package=args.portable_package,
            manifest=args.manifest,
        )
    except GoldenEvidenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(_canonical_json(result))
    return 0


def _opt_in_paths() -> tuple[str, str] | None:
    data_root = os.environ.get(GOLDEN_DATA_ROOT_ENV, "").strip()
    manifest = os.environ.get(GOLDEN_MANIFEST_ENV, "").strip()
    if not data_root and not manifest:
        return None
    if not data_root or not manifest:
        pytest.fail(
            f"{GOLDEN_DATA_ROOT_ENV} and {GOLDEN_MANIFEST_ENV} must be supplied together"
        )
    return data_root, manifest


def _synthetic_candidate_surface() -> dict[str, Any]:
    unresolved = [
        {
            "action_id": f"action.synthetic.{index}",
            "diagnostics": [],
            "missing_fields": ["target"],
            "record_id": f"record.synthetic.{index}",
            "status": "NON_EXECUTABLE_INCOMPLETE_EXPLICIT_ACTION",
        }
        for index in range(8)
    ]
    return {
        "actions": [],
        "candidate_status": "CANDIDATE_NON_AUTHORITATIVE",
        "execution_authority": False,
        "global_combat_readiness": False,
        "mechanical_authority": True,
        "project_id": "project.synthetic",
        "project_revision": 1,
        "provenance": {
            "algorithm": "synthetic",
            "eligible_record_count": 8,
            "project_identity": {"project_id": "project.synthetic", "project_revision": 1},
            "selected_record_count": 8,
            "workspace_authority": "C2B2_INPUT_ONLY",
        },
        "schema_version": CANDIDATE_ACTION_SURFACE_SCHEMA,
        "status": "ACTION_SURFACE_PARTIAL",
        "unresolved": unresolved,
        "workspace_authority": "C2B2_INPUT_ONLY",
    }


def _write_test_zip(path: Path, entries: list[tuple[str, bytes, int]]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload, mode in entries:
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = mode << 16
            archive.writestr(info, payload)
    return path


def test_candidate_action_surface_evidence_is_canonical_and_fail_closed(tmp_path):
    surface_path = tmp_path / "Build" / "Complete_Action_Surface.json"
    surface_path.parent.mkdir()
    surface = _synthetic_candidate_surface()
    surface_path.write_text(json.dumps(surface, indent=2), encoding="utf-8")
    evidence = _candidate_action_surface_manifest(surface_path)
    expected_bytes = canonical_bytes(surface)
    assert evidence == {
        "canonical_sha256": _sha256_bytes(expected_bytes),
        "canonical_bytes": len(expected_bytes),
        "schema_version": CANDIDATE_ACTION_SURFACE_SCHEMA,
        "status": "ACTION_SURFACE_PARTIAL",
        "candidate_status": "CANDIDATE_NON_AUTHORITATIVE",
        "global_combat_readiness": False,
        "execution_authority": False,
        "mechanical_authority": True,
        "actions_count": 0,
        "unresolved_count": 8,
    }

    malformed = json.loads(json.dumps(surface))
    malformed["actions"] = {}
    surface_path.write_text(_canonical_json(malformed), encoding="utf-8")
    with pytest.raises(GoldenEvidenceError):
        _candidate_action_surface_manifest(surface_path)

    malformed = json.loads(json.dumps(surface))
    malformed["unresolved"][0]["diagnostics"] = "not-an-array"
    surface_path.write_text(_canonical_json(malformed), encoding="utf-8")
    with pytest.raises(GoldenEvidenceError):
        _candidate_action_surface_manifest(surface_path)


def test_pre_combat_package_records_readiness_and_does_not_compile_runtime(tmp_path, monkeypatch):
    readiness = {
        "schema_version": PORTABLE_READINESS_SCHEMA,
        "combat": "NOT_ATTEMPTED",
        "combat_execution": "NOT_ATTEMPTED",
        "combat_runtime": "NOT_CLAIMED",
        "combat_sheet": "NOT_CLAIMED",
        "combat_ready_semantics": "NOT_CLAIMED",
        "encounter": "NOT_ATTEMPTED",
        "controller_selection": "NOT_ATTEMPTED",
        "encounter_setup_required": True,
    }
    package = _write_test_zip(
        tmp_path / "pre-combat.zip",
        [("READINESS.json", _canonical_json(readiness).encode("utf-8"), stat.S_IFREG | 0o644)],
    )
    readiness_evidence = _portable_readiness_manifest(package)
    assert readiness_evidence["schema_version"] == PORTABLE_READINESS_SCHEMA
    assert readiness_evidence["combat"] == "NOT_ATTEMPTED"
    assert readiness_evidence["combat_runtime"] == "NOT_CLAIMED"
    assert readiness_evidence["canonical_bytes"] == len(canonical_bytes(readiness))
    inventory = _combat_zip_inventory(package)
    assert inventory == {"members": [], "combat_sheet_present": False}
    monkeypatch.setattr(
        sys.modules[__name__],
        "CharacterCombatRuntimeAdapter",
        lambda *_args: pytest.fail("adapter must not run without a regular combat sheet"),
    )
    assert _runtime_manifest(package, combat_inventory=inventory) == {
        "status": "NOT_READY",
        "compiled": False,
        "reason": "COMBAT_SHEET_NOT_PRESENT",
    }


@pytest.mark.parametrize(
    "entries",
    [
        [("combat/", b"", stat.S_IFDIR | 0o755)],
        [("combat/item.json", b"one", stat.S_IFREG | 0o644), ("combat/item.json", b"two", stat.S_IFREG | 0o644)],
        [("combat/Combat_Sheet.json", b"", stat.S_IFLNK | 0o777)],
        [("combat/../escape.json", b"", stat.S_IFREG | 0o644)],
    ],
    ids=["directory", "duplicate", "symlink", "traversal"],
)
def test_combat_inventory_rejects_unsafe_members(tmp_path, entries):
    package = _write_test_zip(
        tmp_path / "unsafe.zip",
        [("READINESS.json", b"{}", stat.S_IFREG | 0o644), *entries],
    )
    with pytest.raises(GoldenEvidenceError):
        _combat_zip_inventory(package)


def test_runtime_ready_branch_records_bundle_hashes_for_regular_combat_sheet():
    package = Path(__file__).resolve().parent / "fixtures/M1/C1A_Clean_Fire_Qi_Proof_Character_Combat_Runtime_Ready.zip"
    inventory = _combat_zip_inventory(package)
    assert inventory["combat_sheet_present"] is True
    runtime = _runtime_manifest(package, combat_inventory=inventory)
    assert runtime["status"] == "COMBAT_RUNTIME_READY"
    assert runtime["compiled"] is True
    assert re.fullmatch(r"[0-9a-f]{64}", runtime["bundle_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", runtime["canonical_sha256"])


def test_runtime_ready_branch_fails_closed_for_malformed_combat_package(tmp_path):
    package = _write_test_zip(
        tmp_path / "malformed-runtime.zip",
        [("combat/Combat_Sheet.json", b"{}", stat.S_IFREG | 0o644)],
    )
    inventory = _combat_zip_inventory(package)
    assert inventory["combat_sheet_present"] is True
    with pytest.raises(GoldenEvidenceError, match="could not build"):
        _runtime_manifest(package, combat_inventory=inventory)


def test_golden_li_wei_manifest_is_exact_and_recomputation_is_read_only():
    selected = _opt_in_paths()
    if selected is None:
        pytest.skip("set both golden opt-in environment variables to run the Li Wei characterization")
    data_root_text, manifest_text = selected
    root = _data_root(data_root_text)
    manifest_path = _safe_absolute(Path(manifest_text), label="golden manifest")
    if not manifest_path.exists() or not manifest_path.is_file():
        pytest.fail(f"golden manifest does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        pytest.fail(f"golden manifest is not valid UTF-8 JSON: {exc}")
    if not isinstance(manifest, dict) or manifest.get("schema") != GOLDEN_SCHEMA:
        pytest.fail("golden manifest schema is missing or unsupported")
    run = manifest.get("run")
    inputs = manifest.get("inputs")
    if not isinstance(run, dict) or not isinstance(inputs, dict):
        pytest.fail("golden manifest is incomplete: run/inputs")

    before_files = _tree_manifest(root)
    before_controller_modules = {
        name for name in sys.modules if name.startswith("character_creation.creative_controller")
    }
    try:
        recomputed = build_golden_manifest(
            root,
            project_id=run.get("project_id"),
            run_id=run.get("run_id"),
            candidate_workspace=inputs.get("candidate_workspace"),
            owner_sheet=inputs.get("owner_sheet"),
            gm_export=inputs.get("gm_export"),
            portable_package=inputs.get("portable_package"),
        )
    except GoldenEvidenceError as exc:
        pytest.fail(f"golden recomputation failed with incomplete evidence: {exc}")
    after_files = _tree_manifest(root)
    new_controller_modules = {
        name for name in sys.modules if name.startswith("character_creation.creative_controller")
    } - before_controller_modules
    assert after_files == before_files, "golden recomputation wrote below data root"
    assert not new_controller_modules, "golden recomputation imported the creative controller"
    assert recomputed == manifest


def test_golden_capture_parser_requires_all_explicit_inputs():
    parser = build_argument_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_golden_member_path_rejects_traversal_and_symlink_names():
    for name in ("../escape", "/absolute", "folder/../escape", "folder\\escape", ""):
        with pytest.raises(GoldenEvidenceError):
            _validate_member_name(name)


if __name__ == "__main__":  # pragma: no cover - exercised by the capture CLI
    raise SystemExit(main())
