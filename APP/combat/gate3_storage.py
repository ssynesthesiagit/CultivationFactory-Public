from __future__ import annotations

import base64
import copy
import json
import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .canonical import canonical_bytes, canonical_sha256, sha256_file
from .diagnostics import RecoveryDisposition, error
from .gate2_engine import Gate2Engine
from .gate2_runtime_models import ActionIntent, CombatEvent, MatchState, RollRecord
from .gate3_models import (
    EVENT_SCHEMA_VERSION,
    JOURNAL_SCHEMA,
    REDUCER_VERSION,
    STORAGE_SCHEMA_VERSION,
    Gate3CommitPayload,
    Gate3ContentIdentity,
    Gate3Genesis,
    Gate3LoadedMatch,
    Gate3Manifest,
    Gate3AbortRecord,
    Gate3CommitRecord,
    Gate3FinalizedRecord,
    Gate3FinalizePayload,
    Gate3PrepareRecord,
    Gate3MatchLock,
    Gate3PreparePayload,
    Gate3Snapshot,
)
from .portable_runtime_authority import PortableRuntimeAuthority, RUNTIME_AUTHORITY_FILE, SOURCE_PACKAGE_FILE
from .historical_match_compat import is_exact_completed_predecessor, validate_exact_completed_predecessor
from .gate3_reducer import (
    Gate3EventReducer,
    canonical_state_document,
    canonical_state_sha256,
    capture_runtime_control,
    enrich_committed_events,
)

MATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MATCH_DIRECTORY_PREFIX = "m1_"
MATCH_DIRECTORY_PAYLOAD_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
WINDOWS_RESERVED_COMPONENTS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
R66_PRE_WINDOWS_STORAGE_GATE3_STORAGE_SHA256 = (
    "e9492cef71ba1d3096acef65ffbce32b3f8ad0d809adf30a82823482080afe90"
)
ZERO_HASH = "0" * 64
ENGINE_VERSION = "TianxiaFactoryHybridCombatGate3.v1"
CHOICE_AUTHORITY_RELATIVE_PATH = "combat/choice_authority.py"
REQUIRED_EXECUTABLE_CONTENT_IDENTITIES = (CHOICE_AUTHORITY_RELATIVE_PATH,)
FailureInjector = Callable[[str, dict[str, Any]], None]


class Gate3InjectedCrash(RuntimeError):
    def __init__(self, stage: str):
        super().__init__(f"Injected Gate 3 crash at {stage}")
        self.stage = stage


def _utc_display() -> str:
    return datetime.now(timezone.utc).isoformat()


def _diagnostic_dict(exc: Exception) -> dict[str, Any]:
    diagnostic = getattr(exc, "diagnostic", None)
    if diagnostic is not None:
        return diagnostic.model_dump(mode="json")
    return {
        "code": type(exc).__name__,
        "severity": "ERROR",
        "explanation": str(exc),
        "phase": "PERSISTENCE",
        "subsystem": "GATE3",
        "recommended_action": "Inspect the exact diagnostic and retry only after the cause is corrected.",
        "recovery": "STOP",
        "details": {},
    }


def _gate3_error(
    code: str,
    explanation: str,
    *,
    phase: str,
    subsystem: str,
    match_id: str | None = None,
    recommended_action: str,
    recovery: RecoveryDisposition = RecoveryDisposition.STOP,
    details: dict[str, Any] | None = None,
):
    return error(
        code,
        explanation,
        phase=phase,
        subsystem=subsystem,
        entity_id=match_id,
        recommended_action=recommended_action,
        recovery=recovery,
        details=details or {},
    )


def validate_match_id(match_id: str) -> str:
    if not MATCH_ID_PATTERN.fullmatch(match_id) or "/" in match_id or "\\" in match_id:
        raise _gate3_error(
            "MATCH_STORAGE_PATH_REJECTED",
            "The match ID is not a safe logical match identifier.",
            phase="STORAGE_PATH",
            subsystem="GATE3_STORAGE",
            match_id=match_id,
            recommended_action="Use only letters, numbers, period, underscore, colon, or hyphen.",
        )
    return match_id


def encode_match_directory_name(match_id: str) -> str:
    """Map a logical match ID to a reversible Windows-safe directory component."""
    logical = validate_match_id(match_id)
    payload = base64.urlsafe_b64encode(logical.encode("utf-8")).decode("ascii").rstrip("=")
    component = MATCH_DIRECTORY_PREFIX + payload
    if (
        not payload
        or not MATCH_DIRECTORY_PAYLOAD_PATTERN.fullmatch(payload)
        or component.endswith((".", " "))
        or component.split(".", 1)[0].upper() in WINDOWS_RESERVED_COMPONENTS
    ):
        raise _gate3_error(
            "MATCH_STORAGE_PATH_REJECTED",
            "The logical match ID could not be encoded as a Windows-safe directory component.",
            phase="STORAGE_PATH",
            subsystem="GATE3_STORAGE",
            match_id=match_id,
            recommended_action="Use a valid logical match ID and do not construct match directories manually.",
        )
    return component


def decode_match_directory_name(component: str) -> str:
    if not component.startswith(MATCH_DIRECTORY_PREFIX):
        raise ValueError("not an encoded match directory")
    payload = component[len(MATCH_DIRECTORY_PREFIX):]
    if not payload or not MATCH_DIRECTORY_PAYLOAD_PATTERN.fullmatch(payload):
        raise ValueError("invalid encoded match directory payload")
    padded = payload + "=" * (-len(payload) % 4)
    try:
        logical = base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8")
    except Exception as exc:
        raise ValueError("invalid encoded match directory payload") from exc
    validate_match_id(logical)
    if encode_match_directory_name(logical) != component:
        raise ValueError("non-canonical encoded match directory")
    return logical


def _validate_existing_match_directory(path: Path, matches_root: Path, match_id: str, *, legacy: bool) -> None:
    try:
        if path.is_symlink() or not path.is_dir():
            raise ValueError("match path is not a regular directory")
        resolved = path.resolve(strict=True)
    except Exception as exc:
        raise _gate3_error(
            "MATCH_STORAGE_PATH_REJECTED",
            "The existing match storage path is not a safe regular directory.",
            phase="STORAGE_PATH",
            subsystem="GATE3_STORAGE",
            match_id=match_id,
            recommended_action="Remove only the unsafe link or non-directory entry after preserving owner data.",
            details={"path": str(path), "legacy": legacy},
        ) from exc
    if resolved.parent != matches_root.resolve():
        raise _gate3_error(
            "MATCH_STORAGE_PATH_REJECTED",
            "The existing match storage path escapes the configured UserData match root.",
            phase="STORAGE_PATH",
            subsystem="GATE3_STORAGE",
            match_id=match_id,
            recommended_action="Restore the match beneath UserData/Combat/Matches without links or traversal.",
            details={"path": str(path), "legacy": legacy},
        )
    if legacy:
        component = path.name
        stem = component.split(".", 1)[0].upper()
        if component.endswith((".", " ")) or stem in WINDOWS_RESERVED_COMPONENTS:
            raise _gate3_error(
                "MATCH_STORAGE_LEGACY_PATH_REJECTED",
                "A legacy match directory uses a reserved or trailing-dot/space component.",
                phase="STORAGE_PATH",
                subsystem="GATE3_STORAGE",
                match_id=match_id,
                recommended_action="Use an explicit audited migration into the encoded directory scheme; do not rename blindly.",
                details={"path": str(path)},
            )


def resolve_match_directory(matches_root: Path, match_id: str) -> tuple[Path, str]:
    """Resolve encoded storage first, with bounded read compatibility for exact POSIX legacy IDs."""
    logical = validate_match_id(match_id)
    root = Path(matches_root).resolve()
    encoded = root / encode_match_directory_name(logical)
    legacy = root / logical
    encoded_exists = encoded.exists() or encoded.is_symlink()
    legacy_exists = legacy.exists() or legacy.is_symlink()
    if encoded_exists and legacy_exists and encoded != legacy:
        raise _gate3_error(
            "MATCH_STORAGE_IDENTITY_COLLISION",
            "Both encoded and legacy directories exist for the same logical match ID.",
            phase="STORAGE_PATH",
            subsystem="GATE3_STORAGE",
            match_id=logical,
            recommended_action="Stop and reconcile the two directories without overwriting or erasing either copy.",
            details={"encoded_path": str(encoded), "legacy_path": str(legacy)},
        )
    # Reject case-fold or NFC-equivalent sibling aliases before selecting a path.
    if root.is_dir():
        targets = {encoded.name.casefold(), legacy.name.casefold()}
        aliases = [row.name for row in root.iterdir() if row.name.casefold() in targets and row.name not in {encoded.name, legacy.name}]
        if aliases:
            raise _gate3_error(
                "MATCH_STORAGE_IDENTITY_COLLISION",
                "A case-fold-equivalent match directory collides with the requested identity.",
                phase="STORAGE_PATH",
                subsystem="GATE3_STORAGE",
                match_id=logical,
                recommended_action="Stop and reconcile colliding owner data without overwriting either directory.",
                details={"aliases": sorted(aliases)},
            )
    if encoded_exists:
        _validate_existing_match_directory(encoded, root, logical, legacy=False)
        return encoded, "ENCODED"
    if legacy_exists:
        _validate_existing_match_directory(legacy, root, logical, legacy=True)
        return legacy, "LEGACY_POSIX"
    return encoded, "ENCODED_NEW"


def _record_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "record_sha256"}
    return canonical_sha256(payload)


def _snapshot_hash(document: dict[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "snapshot_sha256"}
    return canonical_sha256(payload)


def _match_lock_deterministic_hash(document: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in document.items()
        if key not in {"created_at_display", "deterministic_payload_sha256"}
    }
    return canonical_sha256(payload)


def _typed_record_payload(record: dict[str, Any], model_type: type) -> dict[str, Any]:
    """Select only the typed journal payload fields from a flat record."""
    return {name: record[name] for name in model_type.model_fields}


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(
    path: Path,
    payload: bytes,
    *,
    failure_injector: FailureInjector | None = None,
    failure_stage: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    with temp.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    if failure_injector is not None and failure_stage is not None:
        failure_injector(failure_stage, {"path": str(path), "temporary_path": str(temp)})
    os.replace(temp, path)
    _fsync_directory(path.parent)


def immutable_write(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise _gate3_error(
                "MATCH_LOCK_HASH_MISMATCH" if path.name == "MatchLock.json" else "MATCH_GENESIS_HASH_MISMATCH",
                f"Immutable file {path.name} already exists with different bytes.",
                phase="MATCH_CREATE",
                subsystem="GATE3_STORAGE",
                recommended_action="Use the existing exact match or choose a new match ID.",
            )
        return
    atomic_write_bytes(path, payload)


class LocalMatchWriterLock:
    def __init__(self, path: Path, match_id: str):
        self.path = path
        self.match_id = match_id
        self._handle = None
        self.stale_metadata: dict[str, Any] | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        try:
            if os.name == "nt":  # pragma: no cover - native Windows not available here
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self._handle.close()
            self._handle = None
            raise _gate3_error(
                "MATCH_STORAGE_LOCKED",
                "Another local process currently owns this match directory.",
                phase="MATCH_OPEN",
                subsystem="GATE3_STORAGE",
                match_id=self.match_id,
                recommended_action="Close the other match process and retry.",
                recovery=RecoveryDisposition.RETRY,
                details={"lock_path": str(self.path)},
            ) from exc
        self._handle.seek(0)
        prior = self._handle.read().strip()
        if prior:
            try:
                self.stale_metadata = json.loads(prior)
            except Exception:
                self.stale_metadata = {"unparsed_lock_metadata": prior.decode("utf-8", errors="replace")}
            diagnostic = {
                "code": "MATCH_STORAGE_STALE_LOCK_RECOVERED",
                "match_id": self.match_id,
                "affected_file": ".writer.lock",
                "automatic_recovery": True,
                "may_continue": True,
                "recommended_action": "No action is required; the operating-system lock was free and stale metadata was replaced.",
                "details": {"stale_metadata": self.stale_metadata},
            }
            diagnostic_path = self.path.parent / "Diagnostics" / "StaleWriterLockRecovered.json"
            atomic_write_bytes(diagnostic_path, canonical_bytes(diagnostic) + b"\n")
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(
            canonical_bytes({"match_id": self.match_id, "pid": os.getpid(), "opened_at": _utc_display()})
            + b"\n"
        )
        self._handle.flush()
        os.fsync(self._handle.fileno())
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._handle is None:
            return
        try:
            # A clean close leaves an empty lock file. Non-empty metadata on a later
            # successful acquisition therefore records an interrupted owner, while
            # the operating-system lock remains the actual exclusion authority.
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.flush()
            os.fsync(self._handle.fileno())
            if os.name == "nt":  # pragma: no cover
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


class Gate3MatchStore:
    def __init__(self, userdata_root: Path, match_id: str):
        self.userdata_root = Path(userdata_root).resolve()
        self.matches_root = (self.userdata_root / "Combat" / "Matches").resolve()
        self.match_id = validate_match_id(match_id)
        self.match_dir, self.storage_layout = resolve_match_directory(self.matches_root, self.match_id)
        if self.match_dir.parent.resolve() != self.matches_root:
            raise _gate3_error(
                "MATCH_STORAGE_PATH_REJECTED",
                "The resolved match path escaped the configured UserData match root.",
                phase="STORAGE_PATH",
                subsystem="GATE3_STORAGE",
                match_id=match_id,
                recommended_action="Use a valid confined logical match ID.",
            )
        self.lock_path = self.match_dir / ".writer.lock"
        self.match_lock_path = self.match_dir / "MatchLock.json"
        self.genesis_path = self.match_dir / "GenesisState.json"
        self.journal_path = self.match_dir / "Journal.ndjson"
        self.manifest_path = self.match_dir / "Manifest.json"
        self.snapshots_dir = self.match_dir / "Snapshots"
        self.diagnostics_dir = self.match_dir / "Diagnostics"
        self.exports_dir = self.match_dir / "Exports"

    def ensure_layout(self) -> None:
        self.matches_root.mkdir(parents=True, exist_ok=True)
        self.match_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(exist_ok=True)
        self.diagnostics_dir.mkdir(exist_ok=True)
        self.exports_dir.mkdir(exist_ok=True)
        self.journal_path.touch(exist_ok=True)

    def writer_lock(self) -> LocalMatchWriterLock:
        return LocalMatchWriterLock(self.lock_path, self.match_id)

    def write_diagnostic(self, document: dict[str, Any], name: str | None = None) -> Path:
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        if name is None:
            existing = list(self.diagnostics_dir.glob("Diagnostic_*.json"))
            name = f"Diagnostic_{len(existing)+1:04d}.json"
        path = self.diagnostics_dir / name
        atomic_write_bytes(path, canonical_bytes(document) + b"\n")
        return path

    def append_record(self, document: dict[str, Any]) -> dict[str, Any]:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        completed = dict(document)
        completed["record_sha256"] = _record_hash(completed)
        with self.journal_path.open("ab") as handle:
            handle.write(canonical_bytes(completed) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return completed

    def scan_journal(self, *, recover_trailing_partial: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        diagnostics: list[dict[str, Any]] = []
        if not self.journal_path.exists():
            return [], diagnostics
        data = self.journal_path.read_bytes()
        if data and not data.endswith(b"\n"):
            last_newline = data.rfind(b"\n")
            complete = data[: last_newline + 1] if last_newline >= 0 else b""
            trailing = data[last_newline + 1 :]
            if not recover_trailing_partial:
                raise _gate3_error(
                    "MATCH_JOURNAL_TRAILING_PARTIAL_RECORD",
                    "The journal ends with an incomplete record.",
                    phase="JOURNAL_SCAN",
                    subsystem="GATE3_JOURNAL",
                    match_id=self.match_id,
                    recommended_action="Run recovery to preserve and truncate only the trailing partial bytes.",
                )
            self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
            (self.diagnostics_dir / "TrailingPartialRecord.bin").write_bytes(trailing)
            with self.journal_path.open("wb") as handle:
                handle.write(complete)
                handle.flush()
                os.fsync(handle.fileno())
            diagnostics.append({
                "code": "MATCH_JOURNAL_TRAILING_PARTIAL_RECORD",
                "match_id": self.match_id,
                "affected_file": "Journal.ndjson",
                "automatic_recovery": True,
                "may_continue": True,
                "recommended_action": "Review Diagnostics/TrailingPartialRecord.bin if needed.",
                "trailing_byte_count": len(trailing),
            })
            data = complete
        records: list[dict[str, Any]] = []
        previous = ZERO_HASH
        expected_sequence = 1
        for line_number, line in enumerate(data.splitlines(), start=1):
            try:
                record = json.loads(line)
            except Exception as exc:
                raise _gate3_error(
                    "MATCH_JOURNAL_RECORD_HASH_MISMATCH",
                    "A complete journal record is malformed and cannot be skipped.",
                    phase="JOURNAL_SCAN",
                    subsystem="GATE3_JOURNAL",
                    match_id=self.match_id,
                    recommended_action="Restore the journal from a known-good copy or stop using this match.",
                    details={"line_number": line_number, "last_valid_record": expected_sequence - 1},
                ) from exc
            if record.get("schema") != JOURNAL_SCHEMA:
                raise _gate3_error(
                    "MATCH_JOURNAL_RECORD_HASH_MISMATCH",
                    "A journal record uses an unsupported schema.",
                    phase="JOURNAL_SCAN",
                    subsystem="GATE3_JOURNAL",
                    match_id=self.match_id,
                    recommended_action="Use a compatible Gate 3 reducer and journal schema.",
                    details={"record_sequence": record.get("record_sequence")},
                )
            if record.get("record_sequence") != expected_sequence:
                raise _gate3_error(
                    "MATCH_JOURNAL_SEQUENCE_GAP",
                    "The journal record sequence is not contiguous.",
                    phase="JOURNAL_SCAN",
                    subsystem="GATE3_JOURNAL",
                    match_id=self.match_id,
                    recommended_action="Restore the missing or correct journal record; do not skip it.",
                    details={"expected": expected_sequence, "actual": record.get("record_sequence")},
                )
            if record.get("previous_record_sha256") != previous:
                raise _gate3_error(
                    "MATCH_JOURNAL_CHAIN_MISMATCH",
                    "The journal hash chain does not match the preceding record.",
                    phase="JOURNAL_SCAN",
                    subsystem="GATE3_JOURNAL",
                    match_id=self.match_id,
                    recommended_action="Restore the journal from a known-good copy; do not guess past the mismatch.",
                    details={
                        "record_sequence": expected_sequence,
                        "expected": previous,
                        "actual": record.get("previous_record_sha256"),
                    },
                )
            calculated = _record_hash(record)
            if record.get("record_sha256") != calculated:
                raise _gate3_error(
                    "MATCH_JOURNAL_RECORD_HASH_MISMATCH",
                    "A complete journal record hash does not match its canonical payload.",
                    phase="JOURNAL_SCAN",
                    subsystem="GATE3_JOURNAL",
                    match_id=self.match_id,
                    recommended_action="Restore the exact record; do not skip corrupted middle records.",
                    details={
                        "record_sequence": expected_sequence,
                        "expected": calculated,
                        "actual": record.get("record_sha256"),
                    },
                )
            record_type = record.get("record_type")
            try:
                if record_type == "PREPARE":
                    Gate3PrepareRecord.model_validate(record)
                elif record_type == "COMMIT":
                    Gate3CommitRecord.model_validate(record)
                elif record_type == "ABORT":
                    Gate3AbortRecord.model_validate(record)
                elif record_type == "MATCH_FINALIZED":
                    Gate3FinalizedRecord.model_validate(record)
                else:
                    raise ValueError(f"unsupported journal record type: {record_type}")
            except Exception as exc:
                raise _gate3_error(
                    "MATCH_JOURNAL_RECORD_HASH_MISMATCH",
                    "A complete journal record does not match its typed schema.",
                    phase="JOURNAL_SCAN",
                    subsystem="GATE3_JOURNAL",
                    match_id=self.match_id,
                    recommended_action="Restore the exact typed record; do not skip it.",
                    details={"record_sequence": expected_sequence, "record_type": record_type, "reason": str(exc)},
                ) from exc
            records.append(record)
            previous = calculated
            expected_sequence += 1
        return records, diagnostics

    def write_snapshot(
        self,
        state: MatchState,
        *,
        commanded_cui_this_turn: bool,
        journal_record_sequence: int,
        last_record_sha256: str,
        failure_injector: FailureInjector | None = None,
    ) -> Path:
        base = Gate3Snapshot(
            match_id=self.match_id,
            journal_record_sequence=journal_record_sequence,
            last_journal_record_sha256=last_record_sha256,
            event_sequence=state.event_sequence,
            state_version=state.state_version,
            roll_counter=state.roll_counter,
            state=state,
            commanded_cui_this_turn=commanded_cui_this_turn,
            canonical_state_sha256=canonical_state_sha256(state),
            snapshot_sha256=ZERO_HASH,
        ).model_dump(mode="json", by_alias=True)
        base["snapshot_sha256"] = _snapshot_hash(base)
        snapshot = Gate3Snapshot.model_validate(base)
        path = self.snapshots_dir / f"Snapshot_{journal_record_sequence:08d}.json"
        atomic_write_bytes(
            path,
            canonical_bytes(snapshot.model_dump(mode="json", by_alias=True)) + b"\n",
            failure_injector=failure_injector,
            failure_stage="during_snapshot_temporary_write",
        )
        valid = sorted(self.snapshots_dir.glob("Snapshot_*.json"), reverse=True)
        for old in valid[3:]:
            old.unlink(missing_ok=True)
        return path

    def valid_snapshots(
        self, records: list[dict[str, Any]]
    ) -> tuple[list[Gate3Snapshot], list[dict[str, Any]]]:
        by_sequence = {record["record_sequence"]: record for record in records}
        valid: list[Gate3Snapshot] = []
        diagnostics: list[dict[str, Any]] = []
        for path in sorted(self.snapshots_dir.glob("Snapshot_*.json"), reverse=True):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                snapshot = Gate3Snapshot.model_validate(doc)
                anchor = by_sequence.get(snapshot.journal_record_sequence)
                if _snapshot_hash(doc) != snapshot.snapshot_sha256:
                    raise ValueError("snapshot canonical hash mismatch")
                if canonical_state_sha256(snapshot.state) != snapshot.canonical_state_sha256:
                    raise ValueError("snapshot state hash mismatch")
                if (
                    snapshot.state.event_sequence != snapshot.event_sequence
                    or snapshot.state.state_version != snapshot.state_version
                    or snapshot.state.roll_counter != snapshot.roll_counter
                ):
                    raise ValueError("snapshot redundant state fields mismatch")
                if snapshot.reducer_version != REDUCER_VERSION:
                    raise ValueError("unsupported reducer version")
                if snapshot.journal_record_sequence and (
                    anchor is None
                    or anchor["record_sha256"] != snapshot.last_journal_record_sha256
                ):
                    raise ValueError("snapshot journal anchor mismatch")
                valid.append(snapshot)
            except Exception as exc:
                diagnostics.append({
                    "code": "MATCH_SNAPSHOT_HASH_MISMATCH_FALLBACK",
                    "match_id": self.match_id,
                    "affected_file": str(path.relative_to(self.match_dir)),
                    "automatic_recovery": True,
                    "may_continue": True,
                    "recommended_action": "The loader will try an older snapshot or replay from genesis.",
                    "details": {"reason": str(exc)},
                })
        return valid, diagnostics


class Gate3Persistence:
    def __init__(self, source_root: Path, userdata_root: Path):
        self.source_root = Path(source_root).resolve()
        self.userdata_root = Path(userdata_root).resolve()
        self.reducer = Gate3EventReducer()

    # ------------------------------------------------------------------
    # Content and immutable authority
    # ------------------------------------------------------------------
    def _content_identity_rows(self) -> tuple[Gate3ContentIdentity, ...]:
        paths = [
            "combat_gate2/generated/Gate2_Executable_Mechanics_Lock.json",
            "combat_gate2/generated/Gate2_Universal_Combat_Defaults_Lock.json",
            "combat_gate2/generated/Gate2_Runtime_Profile_Coverage.json",
            "combat_gate1/generated/Registry_Snapshot.json",
            "combat_gate1/generated/Battlefield.json",
            "combat_gate1/generated/Encounter.json",
            "combat_gate1/generated/projections/an_eui_early_book1_cl5.json",
            "combat_gate1/generated/projections/lee_jia_early_book1_cl5.json",
            "combat_gate1/generated/projections/ling_qi_early_outer_sect_cl5.json",
            "combat_gate1/generated/projections/bai_meizhen_early_outer_sect_cl5.json",
            "combat/gate2_engine.py",
            CHOICE_AUTHORITY_RELATIVE_PATH,
            "combat/gate2_grid.py",
            "combat/footprints.py",
            "combat/footprint_registry.py",
            "combat/gate2_runtime_content.py",
            "combat/gate2_runtime_models.py",
            "combat/gate2_rolls.py",
            "combat/gate3_models.py",
            "combat/gate3_reducer.py",
            "combat/gate3_storage.py",
        ]
        rows = []
        for rel in paths:
            path = self.source_root / rel
            if not path.is_file():
                raise _gate3_error(
                    "MATCH_CONTENT_MISSING",
                    f"Required exact content file is missing: {rel}",
                    phase="MATCH_CREATE",
                    subsystem="GATE3_CONTENT",
                    recommended_action="Restore the exact Gate 3 source checkpoint and retry.",
                    details={"relative_path": rel},
                )
            rows.append(
                Gate3ContentIdentity(
                    identity_id=f"file:{rel}", relative_path=rel, sha256=sha256_file(path)
                )
            )
        return tuple(rows)

    def _validate_content(self, lock: Gate3MatchLock) -> None:
        store = Gate3MatchStore(self.userdata_root, lock.match_id)
        if is_exact_completed_predecessor(store.match_dir, lock.match_id):
            validate_exact_completed_predecessor(store.match_dir, lock.match_id)
            return
        if lock.reducer_version != REDUCER_VERSION:
            raise _gate3_error(
                "MATCH_CONTENT_VERSION_MISMATCH",
                "The match requires an unsupported replay reducer version.",
                phase="MATCH_LOAD",
                subsystem="GATE3_CONTENT",
                match_id=lock.match_id,
                recommended_action="Open the match with the exact compatible Gate 3 source version.",
                details={"expected": lock.reducer_version, "available": REDUCER_VERSION},
            )
        bound_paths = {
            row.relative_path for row in lock.content_identities if row.relative_path
        }
        missing_required = sorted(set(REQUIRED_EXECUTABLE_CONTENT_IDENTITIES) - bound_paths)
        if missing_required:
            raise _gate3_error(
                "MATCH_CONTENT_AUTHORITY_INCOMPLETE",
                "The match lock predates required executable choice authority and cannot be continued safely.",
                phase="MATCH_LOAD",
                subsystem="GATE3_CONTENT",
                match_id=lock.match_id,
                recommended_action=(
                    "Open the match with its exact pre-R6.6.9-M3 source, or perform a separately "
                    "authorized lock migration after verifying all existing lock identities. Automatic "
                    "migration is intentionally disabled."
                ),
                details={
                    "missing_relative_paths": missing_required,
                    "compatibility_policy": "FAIL_CLOSED_NO_AUTOMATIC_MIGRATION",
                },
            )
        for row in lock.content_identities:
            if not row.relative_path:
                continue
            if row.authority_scope == "MATCH":
                path = Gate3MatchStore(self.userdata_root, lock.match_id).match_dir / row.relative_path
            else:
                path = self.source_root / row.relative_path
            if not path.is_file():
                raise _gate3_error(
                    "MATCH_CONTENT_MISSING",
                    f"Required match content is missing: {row.relative_path}",
                    phase="MATCH_LOAD",
                    subsystem="GATE3_CONTENT",
                    match_id=lock.match_id,
                    recommended_action="Restore the exact content version bound by MatchLock.json.",
                    details={"identity_id": row.identity_id, "expected_sha256": row.sha256},
                )
            actual = sha256_file(path)
            storage_compatibility = (
                row.relative_path == "combat/gate3_storage.py"
                and row.sha256 == R66_PRE_WINDOWS_STORAGE_GATE3_STORAGE_SHA256
            )
            if actual != row.sha256 and not storage_compatibility:
                raise _gate3_error(
                    "MATCH_CONTENT_VERSION_MISMATCH",
                    f"Required match content has a different exact identity: {row.relative_path}",
                    phase="MATCH_LOAD",
                    subsystem="GATE3_CONTENT",
                    match_id=lock.match_id,
                    recommended_action="Use the exact source/content bytes recorded by MatchLock.json.",
                    details={"identity_id": row.identity_id, "expected": row.sha256, "actual": actual},
                )

    def create_match(
        self, *, match_seed: str, maximum_rounds: int = 20,
        genesis_setup: dict[str, dict[str, object]] | None = None,
        roster_setup: dict[str, object] | None = None,
        runtime_authority: dict[str, Any] | None = None,
        source_package: Path | None = None,
    ) -> "PersistentMatchSession":
        authority = PortableRuntimeAuthority.model_validate(runtime_authority) if runtime_authority else None
        if authority is not None:
            if source_package is None or not Path(source_package).is_file():
                raise ValueError("C3D_SOURCE_PACKAGE_REQUIRED")
            if sha256_file(Path(source_package)) != authority.package_sha256:
                raise ValueError("C3D_SOURCE_PACKAGE_IDENTITY_CHANGED")
        engine = Gate2Engine(
            self.source_root, match_seed=match_seed, maximum_rounds=maximum_rounds,
            genesis_setup=genesis_setup, roster_setup=roster_setup,
            runtime_authority=authority.model_dump(mode="json", by_alias=True) if authority else None,
        )
        store = Gate3MatchStore(self.userdata_root, engine.state.match_id)
        store.ensure_layout()
        with store.writer_lock():
            runtime_rows: tuple[Gate3ContentIdentity, ...] = ()
            if authority is not None:
                authority_path = store.match_dir / RUNTIME_AUTHORITY_FILE
                package_path = store.match_dir / SOURCE_PACKAGE_FILE
                immutable_write(
                    authority_path,
                    canonical_bytes(authority.model_dump(mode="json", by_alias=True)) + b"\n",
                )
                immutable_write(package_path, Path(source_package).read_bytes())
                runtime_rows = (
                    Gate3ContentIdentity(
                        identity_id="match:portable-runtime-authority",
                        relative_path=RUNTIME_AUTHORITY_FILE,
                        sha256=sha256_file(authority_path),
                        authority_scope="MATCH",
                    ),
                    Gate3ContentIdentity(
                        identity_id="match:source-character-package",
                        relative_path=SOURCE_PACKAGE_FILE,
                        sha256=sha256_file(package_path),
                        authority_scope="MATCH",
                    ),
                )
            genesis_state_hash = canonical_state_sha256(engine.state)
            genesis = Gate3Genesis(
                match_id=engine.state.match_id,
                state=engine.state,
                initial_events=tuple(event.model_dump(mode="json") for event in engine.events),
                initial_rolls=tuple(roll.model_dump(mode="json") for roll in engine.rolls),
                commanded_cui_this_turn=bool(engine._commanded_cui_this_turn),
                canonical_state_sha256=genesis_state_hash,
                initial_event_log_sha256=canonical_sha256(
                    [event.model_dump(mode="json") for event in engine.events]
                ),
                initial_roll_log_sha256=canonical_sha256(
                    [roll.model_dump(mode="json") for roll in engine.rolls]
                ),
            )
            identities = self._content_identity_rows() + runtime_rows
            identity_map = {row.relative_path: row.sha256 for row in identities if row.relative_path}
            projection_sha = {
                Path(rel).stem: digest
                for rel, digest in identity_map.items()
                if "/projections/" in rel
            }
            lock_doc = Gate3MatchLock(
                match_id=engine.state.match_id,
                engine_version=ENGINE_VERSION,
                mechanics_lock_sha256=engine.state.mechanics_lock_sha256,
                universal_defaults_lock_sha256=engine.state.universal_defaults_lock_sha256,
                gate1_registry_snapshot_sha256=engine.state.gate1_registry_snapshot_sha256,
                projection_sha256=projection_sha,
                battlefield_sha256=identity_map["combat_gate1/generated/Battlefield.json"],
                encounter_sha256=identity_map["combat_gate1/generated/Encounter.json"],
                match_seed=match_seed,
                initial_roll_counter=engine.state.roll_counter,
                actor_ids=tuple(sorted(engine.state.actors)),
                genesis_state_sha256=genesis_state_hash,
                genesis_payload_sha256=canonical_sha256(
                    genesis.model_dump(mode="json", by_alias=True)
                ),
                content_identities=identities,
                created_at_display=_utc_display(),
                deterministic_payload_sha256=ZERO_HASH,
            ).model_dump(mode="json", by_alias=True)
            lock_doc["deterministic_payload_sha256"] = _match_lock_deterministic_hash(lock_doc)
            match_lock = Gate3MatchLock.model_validate(lock_doc)
            immutable_write(
                store.match_lock_path,
                canonical_bytes(match_lock.model_dump(mode="json", by_alias=True)) + b"\n",
            )
            immutable_write(
                store.genesis_path,
                canonical_bytes(genesis.model_dump(mode="json", by_alias=True)) + b"\n",
            )
            if store.journal_path.stat().st_size != 0:
                raise _gate3_error(
                    "MATCH_LOCK_HASH_MISMATCH",
                    "A newly created match directory already contains journal records.",
                    phase="MATCH_CREATE",
                    subsystem="GATE3_STORAGE",
                    match_id=engine.state.match_id,
                    recommended_action="Choose a new match seed or remove only the unintended duplicate directory.",
                )
            manifest = self._build_manifest(
                store,
                match_lock,
                engine.state,
                records=[],
                latest_snapshot=None,
                diagnostics=[],
            )
            self._write_manifest(store, manifest)
        return PersistentMatchSession(self, store, match_lock, engine)

    def _load_lock_genesis(self, store: Gate3MatchStore) -> tuple[Gate3MatchLock, Gate3Genesis]:
        if not store.match_lock_path.is_file():
            raise _gate3_error(
                "MATCH_LOCK_MISSING",
                "MatchLock.json is missing.",
                phase="MATCH_LOAD",
                subsystem="GATE3_STORAGE",
                match_id=store.match_id,
                recommended_action="Restore the immutable match lock from the exact match package.",
            )
        if not store.genesis_path.is_file():
            raise _gate3_error(
                "MATCH_GENESIS_HASH_MISMATCH",
                "GenesisState.json is missing.",
                phase="MATCH_LOAD",
                subsystem="GATE3_STORAGE",
                match_id=store.match_id,
                recommended_action="Restore the immutable genesis state from the exact match package.",
            )
        lock_doc = json.loads(store.match_lock_path.read_text(encoding="utf-8"))
        lock = Gate3MatchLock.model_validate(lock_doc)
        if lock.match_id != store.match_id or _match_lock_deterministic_hash(lock_doc) != lock.deterministic_payload_sha256:
            raise _gate3_error(
                "MATCH_LOCK_HASH_MISMATCH",
                "MatchLock.json does not match its canonical immutable identity.",
                phase="MATCH_LOAD",
                subsystem="GATE3_STORAGE",
                match_id=store.match_id,
                recommended_action="Restore the exact immutable match lock.",
            )
        genesis = Gate3Genesis.model_validate_json(store.genesis_path.read_text(encoding="utf-8"))
        genesis_doc = genesis.model_dump(mode="json", by_alias=True)
        genesis_valid = (
            genesis.match_id == lock.match_id
            and canonical_state_sha256(genesis.state) == genesis.canonical_state_sha256
            and genesis.canonical_state_sha256 == lock.genesis_state_sha256
            and canonical_sha256(list(genesis.initial_events)) == genesis.initial_event_log_sha256
            and canonical_sha256(list(genesis.initial_rolls)) == genesis.initial_roll_log_sha256
            and canonical_sha256(genesis_doc) == lock.genesis_payload_sha256
        )
        if not genesis_valid:
            raise _gate3_error(
                "MATCH_GENESIS_HASH_MISMATCH",
                "GenesisState.json does not match the immutable match lock.",
                phase="MATCH_LOAD",
                subsystem="GATE3_STORAGE",
                match_id=store.match_id,
                recommended_action="Restore the exact immutable genesis state.",
            )
        self._validate_content(lock)
        return lock, genesis

    # ------------------------------------------------------------------
    # Replay and load
    # ------------------------------------------------------------------
    def _commit_records(self, records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [record for record in records if record["record_type"] == "COMMIT"]

    def _replay_from(
        self,
        start_state: MatchState,
        commits: Iterable[dict[str, Any]],
    ) -> MatchState:
        state = start_state.model_copy(deep=True)
        for record in commits:
            payload = Gate3CommitPayload.model_validate(_typed_record_payload(record, Gate3CommitPayload))
            state = self.reducer.apply_events(state, payload.events)
            state.state_version = payload.post_state_version
            state.roll_counter = payload.roll_counter_end
            if payload.terminal_result is not None:
                state.terminal_result = payload.terminal_result
            actual = canonical_state_sha256(state)
            if actual != payload.post_state_sha256:
                raise _gate3_error(
                    "MATCH_REPLAY_FINAL_STATE_MISMATCH",
                    "Typed event replay did not reproduce the committed post-state hash.",
                    phase="MATCH_REPLAY",
                    subsystem="GATE3_REDUCER",
                    recommended_action="Stop and inspect the exact reducer/event-schema mismatch.",
                    details={
                        "transaction_id": payload.transaction_id,
                        "expected": payload.post_state_sha256,
                        "actual": actual,
                    },
                )
        return state

    def history_boundaries(self, match_id: str) -> dict[str, Any]:
        """Reconstruct genesis and every committed state without writing UserData.

        This is the read-only history authority used by the owner-facing battle
        timeline. It deliberately rejects incomplete trailing journal bytes rather
        than invoking recovery, never takes the writer lock, never rebuilds the
        manifest, and applies only the existing typed Gate 3 reducer.
        """
        store = Gate3MatchStore(self.userdata_root, match_id)
        lock, genesis = self._load_lock_genesis(store)
        records, diagnostics = store.scan_journal(recover_trailing_partial=False)
        self._validate_record_transactions(records)

        state = genesis.state.model_copy(deep=True)
        boundaries: list[dict[str, Any]] = [{
            "boundary_index": 0,
            "boundary_kind": "GENESIS",
            "record_sequence": 0,
            "transaction_id": "txn:match-creation",
            "intent": None,
            "events": list(genesis.initial_events),
            "rolls": list(genesis.initial_rolls),
            "state": canonical_state_document(state),
            "canonical_state_sha256": canonical_state_sha256(state),
        }]

        commit_count = 0
        all_events = list(genesis.initial_events)
        all_rolls = list(genesis.initial_rolls)
        for record in records:
            if record["record_type"] != "COMMIT":
                continue
            payload = Gate3CommitPayload.model_validate(
                _typed_record_payload(record, Gate3CommitPayload)
            )
            actual_pre = canonical_state_sha256(state)
            if actual_pre != payload.pre_state_sha256:
                raise _gate3_error(
                    "MATCH_REPLAY_PRE_STATE_MISMATCH",
                    "The committed history boundary does not bind the reconstructed pre-state.",
                    phase="MATCH_HISTORY",
                    subsystem="GATE3_REDUCER",
                    match_id=match_id,
                    recommended_action="Stop and inspect the exact journal/reducer mismatch.",
                    details={
                        "transaction_id": payload.transaction_id,
                        "expected": payload.pre_state_sha256,
                        "actual": actual_pre,
                    },
                )
            state = self.reducer.apply_events(state, payload.events)
            state.state_version = payload.post_state_version
            state.roll_counter = payload.roll_counter_end
            if payload.terminal_result is not None:
                state.terminal_result = payload.terminal_result
            actual_post = canonical_state_sha256(state)
            if actual_post != payload.post_state_sha256:
                raise _gate3_error(
                    "MATCH_REPLAY_FINAL_STATE_MISMATCH",
                    "Typed event replay did not reproduce a committed history boundary.",
                    phase="MATCH_HISTORY",
                    subsystem="GATE3_REDUCER",
                    match_id=match_id,
                    recommended_action="Stop and inspect the exact reducer/event-schema mismatch.",
                    details={
                        "transaction_id": payload.transaction_id,
                        "expected": payload.post_state_sha256,
                        "actual": actual_post,
                    },
                )
            commit_count += 1
            all_events.extend(payload.events)
            all_rolls.extend(payload.rolls)
            boundaries.append({
                "boundary_index": commit_count,
                "boundary_kind": "COMMIT",
                "record_sequence": record["record_sequence"],
                "transaction_id": payload.transaction_id,
                "intent": payload.intent.model_dump(mode="json"),
                "events": list(payload.events),
                "rolls": list(payload.rolls),
                "state": canonical_state_document(state),
                "canonical_state_sha256": actual_post,
            })

        return {
            "schema": "TianxiaGate3HistoryBoundaries.v1",
            "status": "PASS",
            "match_id": lock.match_id,
            "reducer_version": lock.reducer_version,
            "journal_record_count": len(records),
            "commit_count": commit_count,
            "boundaries": boundaries,
            "canonical_final_state_sha256": canonical_state_sha256(state),
            "canonical_event_log_sha256": canonical_sha256(all_events),
            "canonical_roll_log_sha256": canonical_sha256(all_rolls),
            "diagnostics": diagnostics,
            "read_only": True,
        }

    def _state_before_incomplete_prepare(
        self,
        genesis: Gate3Genesis,
        records: list[dict[str, Any]],
    ) -> MatchState:
        commits = self._commit_records(records)
        return self._replay_from(genesis.state, commits)

    def _engine_from_loaded(
        self,
        state: MatchState,
        events: list[dict[str, Any]],
        rolls: list[dict[str, Any]],
        *,
        commanded_cui_this_turn: bool,
    ) -> Gate2Engine:
        runtime_path = Gate3MatchStore(self.userdata_root, state.match_id).match_dir / RUNTIME_AUTHORITY_FILE
        runtime_authority = json.loads(runtime_path.read_text(encoding="utf-8")) if runtime_path.is_file() else None
        engine = Gate2Engine(
            self.source_root,
            match_seed=state.match_seed,
            maximum_rounds=state.maximum_rounds,
            runtime_authority=runtime_authority,
        )
        engine.state = state.model_copy(deep=True)
        engine.events = [CombatEvent.model_validate(event) for event in events]
        engine.rolls = [RollRecord.model_validate(roll) for roll in rolls]
        engine.roller.counter = state.roll_counter
        engine._transaction_id = None
        engine._transaction_result_version = state.state_version
        engine._active_intent_id = "system:resume"
        engine._active_intent = None
        engine._commanded_cui_this_turn = commanded_cui_this_turn
        return engine

    def load_match(
        self,
        match_id: str,
        *,
        recover: bool = True,
        rebuild_manifest: bool = True,
    ) -> "PersistentMatchSession":
        store = Gate3MatchStore(self.userdata_root, match_id)
        store.ensure_layout()
        with store.writer_lock():
            lock, genesis = self._load_lock_genesis(store)
            records, diagnostics = store.scan_journal(recover_trailing_partial=recover)
            self._validate_record_transactions(records)
            if recover and records and records[-1]["record_type"] == "PREPARE":
                recovery_diag = self._recover_incomplete_prepare(store, lock, genesis, records)
                diagnostics.append(recovery_diag)
                records, more = store.scan_journal(recover_trailing_partial=True)
                diagnostics.extend(more)
                self._validate_record_transactions(records)
            if recover and self._terminal_commit_needs_finalization(records):
                finalization = self._append_terminal_finalization(store, records)
                diagnostics.append({
                    "code": "MATCH_RECOVERY_TERMINAL_FINALIZED",
                    "match_id": match_id,
                    "affected_file": "Journal.ndjson",
                    "automatic_recovery": True,
                    "may_continue": False,
                    "recommended_action": "No action is required; the terminal COMMIT was already authoritative and its finalization marker was restored.",
                    "details": {"record_sequence": finalization["record_sequence"]},
                })
                records, more = store.scan_journal(recover_trailing_partial=True)
                diagnostics.extend(more)
                self._validate_record_transactions(records)
            valid_snapshots, snapshot_diags = store.valid_snapshots(records)
            diagnostics.extend(snapshot_diags)
            commits = self._commit_records(records)
            if valid_snapshots:
                snapshot = valid_snapshots[0]
                later_commits = [
                    record for record in commits
                    if record["record_sequence"] > snapshot.journal_record_sequence
                ]
                state = self._replay_from(snapshot.state, later_commits)
                commanded = snapshot.commanded_cui_this_turn
                for record in later_commits:
                    events = record["events"]
                    if events:
                        control = events[-1].get("payload", {}).get("gate3_runtime_control_after")
                        if control is not None:
                            commanded = bool(control["commanded_cui_this_turn"])
                latest_snapshot = f"Snapshots/Snapshot_{snapshot.journal_record_sequence:08d}.json"
            else:
                if list(store.snapshots_dir.glob("Snapshot_*.json")):
                    diagnostics.append({
                        "code": "MATCH_SNAPSHOT_NONE_VALID_REPLAY_FROM_GENESIS",
                        "match_id": match_id,
                        "automatic_recovery": True,
                        "may_continue": True,
                        "recommended_action": "Replace or regenerate damaged snapshots after successful genesis replay.",
                    })
                state = self._replay_from(genesis.state, commits)
                commanded = genesis.commanded_cui_this_turn
                for record in commits:
                    events = record["events"]
                    if events:
                        control = events[-1].get("payload", {}).get("gate3_runtime_control_after")
                        if control is not None:
                            commanded = bool(control["commanded_cui_this_turn"])
                latest_snapshot = None
            all_events = list(genesis.initial_events)
            all_rolls = list(genesis.initial_rolls)
            for record in commits:
                payload = Gate3CommitPayload.model_validate(_typed_record_payload(record, Gate3CommitPayload))
                all_events.extend(payload.events)
                all_rolls.extend(payload.rolls)
            engine = self._engine_from_loaded(
                state,
                all_events,
                all_rolls,
                commanded_cui_this_turn=commanded,
            )
            manifest = self._build_manifest(
                store,
                lock,
                state,
                records=records,
                latest_snapshot=latest_snapshot,
                diagnostics=diagnostics,
            )
            manifest_needs_rebuild = True
            if store.manifest_path.is_file():
                try:
                    current = Gate3Manifest.model_validate_json(
                        store.manifest_path.read_text(encoding="utf-8")
                    )
                    manifest_needs_rebuild = (
                        current.last_valid_journal_record != manifest.last_valid_journal_record
                        or current.last_journal_record_sha256 != manifest.last_journal_record_sha256
                        or current.state_version != manifest.state_version
                        or current.last_event_sequence != manifest.last_event_sequence
                        or current.status != manifest.status
                    )
                except Exception:
                    manifest_needs_rebuild = True
            if rebuild_manifest and manifest_needs_rebuild:
                diagnostics.append({
                    "code": "MATCH_MANIFEST_REBUILT",
                    "match_id": match_id,
                    "automatic_recovery": True,
                    "may_continue": True,
                    "recommended_action": "No action is required; the journal authority rebuilt the manifest.",
                })
                manifest = self._build_manifest(
                    store,
                    lock,
                    state,
                    records=records,
                    latest_snapshot=latest_snapshot,
                    diagnostics=diagnostics,
                )
                self._write_manifest(store, manifest)
            for diag in diagnostics:
                store.write_diagnostic(diag)
        return PersistentMatchSession(self, store, lock, engine, diagnostics=diagnostics, records=records)

    @staticmethod
    def _terminal_commit_needs_finalization(records: list[dict[str, Any]]) -> bool:
        if not records or records[-1]["record_type"] != "COMMIT":
            return False
        return records[-1].get("terminal_result") is not None

    @staticmethod
    def _terminal_finalization_payload(commit_record: dict[str, Any]) -> Gate3FinalizePayload:
        return Gate3FinalizePayload(
            final_commit_transaction_id=commit_record["transaction_id"],
            final_state_sha256=commit_record["post_state_sha256"],
            final_event_sequence=commit_record["event_sequence_end"],
            final_roll_counter=commit_record["roll_counter_end"],
            terminal_result=commit_record["terminal_result"],
        )

    def _append_terminal_finalization(
        self, store: Gate3MatchStore, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        commit_record = records[-1]
        payload = self._terminal_finalization_payload(commit_record)
        return store.append_record({
            "schema": JOURNAL_SCHEMA,
            "record_type": "MATCH_FINALIZED",
            "record_sequence": commit_record["record_sequence"] + 1,
            "previous_record_sha256": commit_record["record_sha256"],
            **payload.model_dump(mode="json"),
        })

    def _validate_record_transactions(self, records: list[dict[str, Any]]) -> None:
        prepared: dict[str, dict[str, Any]] = {}
        completed: set[str] = set()
        finalized: list[dict[str, Any]] = []
        for record in records:
            typ = record["record_type"]
            transaction_id = record.get("transaction_id")
            if typ == "MATCH_FINALIZED":
                finalized.append(record)
                continue
            if typ == "PREPARE":
                if transaction_id in prepared or transaction_id in completed:
                    raise _gate3_error(
                        "MATCH_JOURNAL_SEQUENCE_GAP",
                        "A transaction PREPARE is duplicated.",
                        phase="JOURNAL_SCAN",
                        subsystem="GATE3_JOURNAL",
                        recommended_action="Restore the exact journal; do not merge duplicate records.",
                        details={"transaction_id": transaction_id},
                    )
                prepared[transaction_id] = record
            elif typ in {"COMMIT", "ABORT"}:
                if transaction_id not in prepared or transaction_id in completed:
                    raise _gate3_error(
                        "MATCH_JOURNAL_SEQUENCE_GAP",
                        "A COMMIT or ABORT does not have exactly one preceding PREPARE.",
                        phase="JOURNAL_SCAN",
                        subsystem="GATE3_JOURNAL",
                        recommended_action="Restore the exact contiguous transaction records.",
                        details={"transaction_id": transaction_id, "record_type": typ},
                    )
                completed.add(transaction_id)
        if len(finalized) > 1 or (finalized and records[-1] is not finalized[0]):
            raise _gate3_error(
                "MATCH_JOURNAL_SEQUENCE_GAP",
                "MATCH_FINALIZED must occur at most once and only as the final record.",
                phase="JOURNAL_SCAN",
                subsystem="GATE3_JOURNAL",
                recommended_action="Restore the exact terminal journal sequence.",
            )
        if finalized:
            final = finalized[0]
            prior = records[-2] if len(records) >= 2 else None
            valid_final = (
                prior is not None
                and prior["record_type"] == "COMMIT"
                and prior.get("terminal_result") is not None
                and final["final_commit_transaction_id"] == prior["transaction_id"]
                and final["final_state_sha256"] == prior["post_state_sha256"]
                and final["final_event_sequence"] == prior["event_sequence_end"]
                and final["final_roll_counter"] == prior["roll_counter_end"]
                and final["terminal_result"] == prior["terminal_result"]
            )
            if not valid_final:
                raise _gate3_error(
                    "MATCH_JOURNAL_SEQUENCE_GAP",
                    "MATCH_FINALIZED does not bind the immediately preceding terminal COMMIT.",
                    phase="JOURNAL_SCAN",
                    subsystem="GATE3_JOURNAL",
                    recommended_action="Restore the exact terminal COMMIT and finalization record.",
                )
        incomplete = [tid for tid in prepared if tid not in completed]
        if len(incomplete) > 1 or (incomplete and records[-1].get("transaction_id") != incomplete[0]):
            raise _gate3_error(
                "MATCH_JOURNAL_SEQUENCE_GAP",
                "An incomplete PREPARE exists before the final journal record.",
                phase="JOURNAL_SCAN",
                subsystem="GATE3_JOURNAL",
                recommended_action="Restore the exact journal; only the trailing prepared transaction is recoverable.",
                details={"incomplete_transactions": incomplete},
            )

    def _recover_incomplete_prepare(
        self,
        store: Gate3MatchStore,
        lock: Gate3MatchLock,
        genesis: Gate3Genesis,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prepare_record = records[-1]
        prepare = Gate3PreparePayload.model_validate(_typed_record_payload(prepare_record, Gate3PreparePayload))
        prior_records = records[:-1]
        state = self._state_before_incomplete_prepare(genesis, prior_records)
        if canonical_state_sha256(state) != prepare.pre_state_sha256 or state.state_version != prepare.pre_state_version or state.roll_counter != prepare.roll_counter_start:
            raise _gate3_error(
                "MATCH_RECOVERY_DETERMINISM_MISMATCH",
                "The prepared transaction pre-state cannot be reconstructed exactly.",
                phase="MATCH_RECOVERY",
                subsystem="GATE3_RECOVERY",
                match_id=lock.match_id,
                recommended_action="Stop and restore the exact preceding journal/genesis content.",
                details={"transaction_id": prepare.transaction_id},
            )
        commits = self._commit_records(prior_records)
        events = list(genesis.initial_events)
        rolls = list(genesis.initial_rolls)
        commanded = genesis.commanded_cui_this_turn
        for record in commits:
            events.extend(record["events"])
            rolls.extend(record["rolls"])
            evs = record["events"]
            if evs:
                control = evs[-1].get("payload", {}).get("gate3_runtime_control_after")
                if control is not None:
                    commanded = bool(control["commanded_cui_this_turn"])
        engine = self._engine_from_loaded(state, events, rolls, commanded_cui_this_turn=commanded)
        self._validate_intent_binding(engine, prepare.intent, prepare.candidate_binding)
        event_start = len(engine.events)
        roll_start = len(engine.rolls)
        engine.execute_intent(prepare.intent)
        enriched = enrich_committed_events(engine.events[event_start:], post_engine=engine)
        new_rolls = tuple(roll.model_dump(mode="json") for roll in engine.rolls[roll_start:])
        commit_payload = Gate3CommitPayload(
            transaction_id=prepare.transaction_id,
            intent=prepare.intent,
            pre_state_sha256=prepare.pre_state_sha256,
            post_state_version=engine.state.state_version,
            post_state_sha256=canonical_state_sha256(engine.state),
            event_sequence_start=(enriched[0]["sequence"] if enriched else prepare.event_sequence_before + 1),
            event_sequence_end=(enriched[-1]["sequence"] if enriched else prepare.event_sequence_before),
            roll_counter_start=prepare.roll_counter_start,
            roll_counter_end=engine.state.roll_counter,
            events=enriched,
            rolls=new_rolls,
            terminal_result=engine.state.terminal_result,
        )
        previous_hash = prepare_record["record_sha256"]
        commit_record = {
            "schema": JOURNAL_SCHEMA,
            "record_type": "COMMIT",
            "record_sequence": prepare_record["record_sequence"] + 1,
            "previous_record_sha256": previous_hash,
            **commit_payload.model_dump(mode="json"),
        }
        store.append_record(commit_record)
        return {
            "code": "MATCH_RECOVERY_PREPARED_TRANSACTION_COMPLETED",
            "match_id": lock.match_id,
            "affected_file": "Journal.ndjson",
            "last_valid_transaction": prepare.transaction_id,
            "last_valid_event": engine.state.event_sequence,
            "automatic_recovery": True,
            "may_continue": engine.state.terminal_result is None,
            "recommended_action": "Continue normally; the accepted intent was completed with its original roll-counter start.",
        }

    # ------------------------------------------------------------------
    # Manifest and export
    # ------------------------------------------------------------------
    def _build_manifest(
        self,
        store: Gate3MatchStore,
        lock: Gate3MatchLock,
        state: MatchState,
        *,
        records: list[dict[str, Any]],
        latest_snapshot: str | None,
        diagnostics: list[dict[str, Any]],
    ) -> Gate3Manifest:
        last = records[-1] if records else None
        commits = self._commit_records(records)
        last_commit = commits[-1] if commits else None
        status = "COMPLETE" if state.terminal_result is not None else (
            "RECOVERY_REQUIRED" if last and last["record_type"] == "PREPARE" else "ACTIVE"
        )
        file_identities = {}
        for path in [store.match_lock_path, store.genesis_path, store.journal_path]:
            if path.is_file():
                file_identities[path.name] = sha256_file(path)
        return Gate3Manifest(
            match_id=lock.match_id,
            status=status,
            last_valid_journal_record=last["record_sequence"] if last else 0,
            last_journal_record_sha256=last["record_sha256"] if last else ZERO_HASH,
            last_committed_transaction=(last_commit["transaction_id"] if last_commit else None),
            last_event_sequence=state.event_sequence,
            state_version=state.state_version,
            roll_counter=state.roll_counter,
            latest_valid_snapshot=latest_snapshot,
            terminal_result=state.terminal_result,
            last_diagnostic_summary=(diagnostics[-1] if diagnostics else None),
            display_updated_at=_utc_display(),
            file_identities=file_identities,
        )

    def _write_manifest(
        self,
        store: Gate3MatchStore,
        manifest: Gate3Manifest,
        *,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        atomic_write_bytes(
            store.manifest_path,
            canonical_bytes(manifest.model_dump(mode="json", by_alias=True)) + b"\n",
            failure_injector=failure_injector,
            failure_stage="during_manifest_temporary_write",
        )

    def export_match(self, match_id: str) -> dict[str, str]:
        session = self.load_match(match_id)
        return session.export()

    def match_directory(self, match_id: str) -> Path:
        return Gate3MatchStore(self.userdata_root, match_id).match_dir

    def list_matches(self) -> list[dict[str, Any]]:
        matches_root = (self.userdata_root / "Combat" / "Matches").resolve()
        if not matches_root.is_dir():
            return []
        out: list[dict[str, Any]] = []
        seen_logical: dict[str, str] = {}
        for path in sorted(matches_root.iterdir(), key=lambda row: row.name):
            if path.is_symlink() or not path.is_dir():
                continue
            lock_path = path / "MatchLock.json"
            if not lock_path.is_file():
                continue
            try:
                lock = Gate3MatchLock.model_validate_json(lock_path.read_text(encoding="utf-8"))
                logical_id = validate_match_id(lock.match_id)
                expected_encoded = encode_match_directory_name(logical_id)
                if path.name == expected_encoded:
                    storage_layout = "ENCODED"
                    if decode_match_directory_name(path.name) != logical_id:
                        raise ValueError("encoded directory identity mismatch")
                elif path.name == logical_id:
                    _validate_existing_match_directory(path, matches_root, logical_id, legacy=True)
                    storage_layout = "LEGACY_POSIX"
                else:
                    raise ValueError("directory name does not bind the authoritative MatchLock identity")
                prior = seen_logical.get(logical_id)
                if prior is not None and prior != path.name:
                    raise _gate3_error(
                        "MATCH_STORAGE_IDENTITY_COLLISION",
                        "Multiple directories claim the same authoritative logical match ID.",
                        phase="MATCH_LIST",
                        subsystem="GATE3_STORAGE",
                        match_id=logical_id,
                        recommended_action="Stop and reconcile owner data without deleting or overwriting either directory.",
                        details={"first": prior, "second": path.name},
                    )
                seen_logical[logical_id] = path.name
                manifest_path = path / "Manifest.json"
                row: dict[str, Any] = {
                    "match_id": logical_id,
                    "storage_layout": storage_layout,
                    "manifest_available": manifest_path.is_file(),
                }
                if manifest_path.is_file():
                    manifest = Gate3Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
                    if manifest.match_id != logical_id:
                        raise ValueError("manifest logical identity mismatch")
                    row.update({
                        "status": manifest.status,
                        "state_version": manifest.state_version,
                        "last_event_sequence": manifest.last_event_sequence,
                    })
                out.append(row)
            except Exception as exc:
                diagnostic = getattr(exc, "diagnostic", None)
                if diagnostic is not None:
                    raise
                out.append({
                    "match_id": path.name,
                    "storage_layout": "INVALID",
                    "manifest_available": (path / "Manifest.json").is_file(),
                    "status": "IDENTITY_INVALID",
                })
        return out

    @staticmethod
    def _validate_intent_binding(
        engine: Gate2Engine, intent: ActionIntent, candidate_binding: dict[str, Any]
    ) -> None:
        candidates = {candidate.candidate_id: candidate for candidate in engine.legal_candidates()}
        candidate = candidates.get(intent.candidate_id)
        if candidate is None or candidate.model_dump(mode="json") != candidate_binding:
            raise _gate3_error(
                "MATCH_RECOVERY_DETERMINISM_MISMATCH",
                "The prepared candidate binding is no longer the exact legal candidate.",
                phase="MATCH_RECOVERY",
                subsystem="GATE3_RECOVERY",
                match_id=engine.state.match_id,
                recommended_action="Restore the exact content and pre-state; do not substitute another candidate.",
                details={"intent_id": intent.intent_id, "candidate_id": intent.candidate_id},
            )


class PersistentMatchSession:
    def __init__(
        self,
        persistence: Gate3Persistence,
        store: Gate3MatchStore,
        match_lock: Gate3MatchLock,
        engine: Gate2Engine,
        *,
        diagnostics: list[dict[str, Any]] | None = None,
        records: list[dict[str, Any]] | None = None,
    ):
        self.persistence = persistence
        self.store = store
        self.match_lock = match_lock
        self.engine = engine
        self.diagnostics = diagnostics or []
        self._records = list(records) if records is not None else []

    @property
    def match_id(self) -> str:
        return self.match_lock.match_id

    def execute_intent(
        self,
        intent: ActionIntent,
        *,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        if self.engine.state.terminal_result is not None:
            raise _gate3_error(
                "MATCH_ALREADY_COMPLETE",
                "A completed match cannot accept another intent.",
                phase="INTENT_ACCEPT",
                subsystem="GATE3_PERSISTENCE",
                match_id=self.match_id,
                recommended_action="Use replay, verify, status, or export for completed matches.",
            )
        with self.store.writer_lock():
            records = list(self._records)
            if records and records[-1]["record_type"] == "PREPARE":
                raise _gate3_error(
                    "MATCH_STORAGE_LOCKED",
                    "The journal already has an incomplete prepared transaction.",
                    phase="INTENT_ACCEPT",
                    subsystem="GATE3_PERSISTENCE",
                    match_id=self.match_id,
                    recommended_action="Resume the match to recover the prepared transaction first.",
                )
            candidates = {candidate.candidate_id: candidate for candidate in self.engine.legal_candidates()}
            candidate = candidates.get(intent.candidate_id)
            if candidate is None:
                raise _gate3_error(
                    "GATE2_STALE_OR_ILLEGAL_CANDIDATE",
                    "The selected candidate is not legal in the current state.",
                    phase="INTENT_ACCEPT",
                    subsystem="GATE3_PERSISTENCE",
                    match_id=self.match_id,
                    recommended_action="Regenerate candidates and select one exact current candidate.",
                    recovery=RecoveryDisposition.RETRY,
                )
            if failure_injector:
                failure_injector("before_prepare", {"match_id": self.match_id, "intent_id": intent.intent_id})
            transaction_id = f"persist:{self.engine.state.state_version + 1:08d}:{canonical_sha256(intent.model_dump(mode='json'))[:16]}"
            previous_hash = records[-1]["record_sha256"] if records else ZERO_HASH
            prepare_payload = Gate3PreparePayload(
                transaction_id=transaction_id,
                intent=intent,
                candidate_binding=candidate.model_dump(mode="json"),
                pre_state_version=self.engine.state.state_version,
                pre_state_sha256=canonical_state_sha256(self.engine.state),
                event_sequence_before=self.engine.state.event_sequence,
                roll_counter_start=self.engine.state.roll_counter,
            )
            prepare_record = self.store.append_record({
                "schema": JOURNAL_SCHEMA,
                "record_type": "PREPARE",
                "record_sequence": len(records) + 1,
                "previous_record_sha256": previous_hash,
                **prepare_payload.model_dump(mode="json"),
            })
            if failure_injector:
                failure_injector("after_prepare_flush", {"record": prepare_record})
            event_start = len(self.engine.events)
            roll_start = len(self.engine.rolls)
            pre_engine_state = self.engine.state.model_copy(deep=True)
            pre_commanded_cui = bool(self.engine._commanded_cui_this_turn)
            try:
                self.engine.execute_intent(intent)
                if failure_injector:
                    failure_injector(
                        "during_resolution",
                        {
                            "state_version": self.engine.state.state_version,
                            "event_count": len(self.engine.events) - event_start,
                        },
                    )
            except Gate3InjectedCrash:
                raise
            except Exception as exc:
                # Gate 2 already rolls back ordinary mechanical errors. Restore the
                # exact persistence checkpoint as an additional custody boundary.
                self.engine.state = pre_engine_state
                self.engine.events = self.engine.events[:event_start]
                self.engine.rolls = self.engine.rolls[:roll_start]
                self.engine.roller.counter = pre_engine_state.roll_counter
                self.engine._commanded_cui_this_turn = pre_commanded_cui
                abort_payload = {
                    "transaction_id": transaction_id,
                    "intent": intent.model_dump(mode="json"),
                    "unchanged_state_sha256": prepare_payload.pre_state_sha256,
                    "diagnostic": _diagnostic_dict(exc),
                }
                abort_record = self.store.append_record({
                    "schema": JOURNAL_SCHEMA,
                    "record_type": "ABORT",
                    "record_sequence": prepare_record["record_sequence"] + 1,
                    "previous_record_sha256": prepare_record["record_sha256"],
                    **abort_payload,
                })
                self._records = records + [prepare_record, abort_record]
                raise
            enriched_events = enrich_committed_events(
                self.engine.events[event_start:], post_engine=self.engine
            )
            new_rolls = tuple(
                roll.model_dump(mode="json") for roll in self.engine.rolls[roll_start:]
            )
            commit_payload = Gate3CommitPayload(
                transaction_id=transaction_id,
                intent=intent,
                pre_state_sha256=prepare_payload.pre_state_sha256,
                post_state_version=self.engine.state.state_version,
                post_state_sha256=canonical_state_sha256(self.engine.state),
                event_sequence_start=(
                    enriched_events[0]["sequence"]
                    if enriched_events
                    else prepare_payload.event_sequence_before + 1
                ),
                event_sequence_end=(
                    enriched_events[-1]["sequence"]
                    if enriched_events
                    else prepare_payload.event_sequence_before
                ),
                roll_counter_start=prepare_payload.roll_counter_start,
                roll_counter_end=self.engine.state.roll_counter,
                events=enriched_events,
                rolls=new_rolls,
                terminal_result=self.engine.state.terminal_result,
            )
            try:
                commit_record = self.store.append_record({
                    "schema": JOURNAL_SCHEMA,
                    "record_type": "COMMIT",
                    "record_sequence": prepare_record["record_sequence"] + 1,
                    "previous_record_sha256": prepare_record["record_sha256"],
                    **commit_payload.model_dump(mode="json"),
                })
            except Exception:
                # No COMMIT authority exists; keep the live session at the PREPARE
                # pre-state so it cannot outrun durable storage. Recovery may later
                # complete the exact prepared intent from the journal.
                self.engine.state = pre_engine_state
                self.engine.events = self.engine.events[:event_start]
                self.engine.rolls = self.engine.rolls[:roll_start]
                self.engine.roller.counter = pre_engine_state.roll_counter
                self.engine._commanded_cui_this_turn = pre_commanded_cui
                self._records = records + [prepare_record]
                raise
            if failure_injector:
                failure_injector("after_commit_flush_before_manifest", {"record": commit_record})
            records = records + [prepare_record, commit_record]
            if self.engine.state.terminal_result is not None:
                if failure_injector:
                    failure_injector("after_terminal_commit", {"record": commit_record})
                finalization_record = self.persistence._append_terminal_finalization(self.store, records)
                records.append(finalization_record)
            self._records = list(records)
            should_snapshot = (
                len([record for record in records if record["record_type"] == "COMMIT"]) % 10 == 0
                or any(event["event_type"] == "ROUND_STARTED" for event in enriched_events)
                or self.engine.state.terminal_result is not None
            )
            manifest = self.persistence._build_manifest(
                self.store,
                self.match_lock,
                self.engine.state,
                records=records,
                latest_snapshot=None,
                diagnostics=[],
            )
            self.persistence._write_manifest(
                self.store, manifest, failure_injector=failure_injector
            )
            if should_snapshot:
                snapshot_anchor = records[-1]
                snapshot_path = self.store.write_snapshot(
                    self.engine.state,
                    commanded_cui_this_turn=bool(self.engine._commanded_cui_this_turn),
                    journal_record_sequence=snapshot_anchor["record_sequence"],
                    last_record_sha256=snapshot_anchor["record_sha256"],
                    failure_injector=failure_injector,
                )
                manifest = manifest.model_copy(update={"latest_valid_snapshot": str(snapshot_path.relative_to(self.store.match_dir))})
                self.persistence._write_manifest(self.store, manifest)

    def explicit_snapshot(self) -> Path:
        with self.store.writer_lock():
            records = list(self._records)
            last_sequence = records[-1]["record_sequence"] if records else 0
            last_hash = records[-1]["record_sha256"] if records else ZERO_HASH
            return self.store.write_snapshot(
                self.engine.state,
                commanded_cui_this_turn=bool(self.engine._commanded_cui_this_turn),
                journal_record_sequence=last_sequence,
                last_record_sha256=last_hash,
            )

    def verify(self) -> dict[str, Any]:
        with self.store.writer_lock():
            lock, genesis = self.persistence._load_lock_genesis(self.store)
            records, diagnostics = self.store.scan_journal(recover_trailing_partial=False)
            self.persistence._validate_record_transactions(records)
            commits = self.persistence._commit_records(records)
            replayed = self.persistence._replay_from(genesis.state, commits)
            expected = canonical_state_sha256(self.engine.state)
            actual = canonical_state_sha256(replayed)
            if actual != expected:
                raise _gate3_error(
                    "MATCH_REPLAY_FINAL_STATE_MISMATCH",
                    "Genesis replay does not equal the currently loaded authoritative state.",
                    phase="MATCH_VERIFY",
                    subsystem="GATE3_REDUCER",
                    match_id=self.match_id,
                    recommended_action="Stop and inspect the exact replay mismatch.",
                    details={"expected": expected, "actual": actual},
                )
            return {
                "schema": "TianxiaGate3VerifyResult.v1",
                "status": "PASS",
                "match_id": self.match_id,
                "journal_record_count": len(records),
                "commit_count": len(commits),
                "event_count": len(self.engine.events),
                "roll_count": len(self.engine.rolls),
                "state_version": self.engine.state.state_version,
                "canonical_state_sha256": actual,
                "terminal_result": (
                    self.engine.state.terminal_result.model_dump(mode="json")
                    if self.engine.state.terminal_result
                    else None
                ),
                "diagnostics": diagnostics,
                "mechanics_preserved": True,
            }

    def replay(self) -> dict[str, Any]:
        with self.store.writer_lock():
            _, genesis = self.persistence._load_lock_genesis(self.store)
            records, _ = self.store.scan_journal(recover_trailing_partial=False)
            commits = self.persistence._commit_records(records)
            state = self.persistence._replay_from(genesis.state, commits)
            events = list(genesis.initial_events)
            rolls = list(genesis.initial_rolls)
            for record in commits:
                events.extend(record["events"])
                rolls.extend(record["rolls"])
            return {
                "schema": "TianxiaGate3ReplayResult.v1",
                "status": "PASS",
                "match_id": self.match_id,
                "state": canonical_state_document(state),
                "events": events,
                "rolls": rolls,
                "terminal_result": (
                    state.terminal_result.model_dump(mode="json")
                    if state.terminal_result
                    else None
                ),
                "canonical_state_sha256": canonical_state_sha256(state),
                "canonical_event_log_sha256": canonical_sha256(events),
                "canonical_roll_log_sha256": canonical_sha256(rolls),
            }

    def export(self) -> dict[str, str]:
        self.store.exports_dir.mkdir(parents=True, exist_ok=True)
        replay = self.replay()
        docs = {
            "Gate3_Current_State.json": replay["state"],
            "Gate3_Event_Log.json": {"schema": EVENT_SCHEMA_VERSION, "events": replay["events"]},
            "Gate3_Roll_Log.json": {"schema": "TianxiaGate3RollLog.v1", "rolls": replay["rolls"]},
            "Gate3_Replay_Result.json": replay,
        }
        hashes = {}
        for name, doc in docs.items():
            path = self.store.exports_dir / name
            atomic_write_bytes(path, canonical_bytes(doc) + b"\n")
            hashes[name] = sha256_file(path)
        return hashes
