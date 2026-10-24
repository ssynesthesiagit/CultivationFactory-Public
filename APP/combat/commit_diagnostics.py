"""Durable home for the diagnostics gate 5 raises beside a completed commit.

Used by combat/gate5_service.py (which records one) and by combat/tabletop_service.py
(which shows the latest one to the table). Nothing else writes or reads this file.

Why a sidecar file rather than the journal: the disagreement is only knowable after the
mechanical transaction that applied the action has already written its COMMIT record, so
it cannot ride along in that record, and opening a second record type in ControllerJournal
or the gate 3 journal would change the bytes of every saved fight. A separate file leaves
an agreeing fight's saved bytes exactly as they were -- the file is only ever created for a
fight that actually diverged.

Every value is a string or an integer, so a record survives a table commit and a reload
from disk unchanged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes

COMMIT_DIAGNOSTIC_FILE = "CommitDiagnostics.ndjson"
COMMIT_DIAGNOSTIC_SCHEMA = "TianxiaCommitDiagnostic.v1"

#: Shown to the table. No hashes, no ids, no internal names: a player who knows only
#: basic D&D still has to be able to read it. The hashes stay in the structured fields
#: below, for whoever looks at the file itself.
PLAIN_NOTICE = (
    "The fight played out differently from the guess the table made before you pressed the button. "
    "The real result is what the fight, its log and its saved copy all use now, so the fight is "
    "consistent and you can carry on playing it. Tell the table owner if this keeps happening."
)

PERSISTENCE_NOTICE = (
    "The action was saved, but the table could not save this warning. "
    "Tell the table owner; the warning may disappear when the service restarts."
)


def diagnostic_path(match_dir: Path) -> Path:
    """The one file these records live in, inside the saved fight's own directory."""
    return Path(match_dir) / COMMIT_DIAGNOSTIC_FILE


def record_commit_divergence(
    match_dir: Path,
    *,
    match_id: str,
    actor_id: str,
    decision_id: str,
    state_version: int,
    preview_id: str,
    preview_post_state_sha256: str,
    authoritative_post_state_sha256: str,
) -> dict[str, Any]:
    """Append one record of a commit whose result differed from the table's prediction.

    Called only when the two disagree, and only after the authoritative result is already
    committed: the authoritative result is the rules and stands, and this is the trace of the
    disagreement beside it. Returns the record, which is also the answer the service hands
    back to the caller. I/O failure adds a separate persistence notice to that record;
    it never changes the committed outcome or raises a storage error to the caller.
    """
    record = {
        "schema": COMMIT_DIAGNOSTIC_SCHEMA,
        "code": "COMBAT_PREVIEW_MISMATCH",
        "match_id": str(match_id),
        "actor_id": str(actor_id),
        "decision_id": str(decision_id),
        "state_version": int(state_version),
        "preview_id": str(preview_id),
        "preview_post_state_sha256": str(preview_post_state_sha256),
        "authoritative_post_state_sha256": str(authoritative_post_state_sha256),
        "outcome": "COMMITTED",
        "notice": PLAIN_NOTICE,
    }
    path = diagnostic_path(match_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            data = canonical_bytes(record) + b"\n"
            while data:
                written = os.write(fd, data)
                if written <= 0:
                    raise OSError("Diagnostic write made no progress")
                data = data[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        # The action is already committed. Keep its diagnostic in the response;
        # storage failure is separate from the mechanical outcome.
        record["persistence_error"] = "COMMIT_DIAGNOSTIC_WRITE_FAILED"
        record["persistence_notice"] = PERSISTENCE_NOTICE
    return record


def latest_commit_divergence(match_dir: Path) -> dict[str, Any] | None:
    """The most recent record for this fight, or None when the fight has never diverged.

    A damaged or unreadable file is treated as no record: a diagnostic that cannot be read
    must never be the reason a fight cannot be shown or played.
    """
    path = diagnostic_path(match_dir)
    try:
        rows = [line for line in path.read_bytes().splitlines() if line.strip()]
    except OSError:
        return None
    for line in reversed(rows):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(record, dict) and record.get("schema") == COMMIT_DIAGNOSTIC_SCHEMA:
            return record
    return None
