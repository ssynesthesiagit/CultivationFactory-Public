from __future__ import annotations

import argparse
from pathlib import Path

from .canonical import canonical_bytes, canonical_sha256
from .gate3_models import (
    Gate3AbortRecord,
    Gate3CommitRecord,
    Gate3FinalizedRecord,
    Gate3Genesis,
    Gate3LoadedMatch,
    Gate3Manifest,
    Gate3MatchLock,
    Gate3PrepareRecord,
    Gate3RuntimeControl,
    Gate3Snapshot,
)
from .gate3_reducer import reducer_coverage_document

GATE3_RUNTIME_VERSION = "0.3.0-gate3"

_SCHEMA_MODELS = {
    "Gate3_Abort_Record.schema.json": Gate3AbortRecord,
    "Gate3_Commit_Record.schema.json": Gate3CommitRecord,
    "Gate3_Finalized_Record.schema.json": Gate3FinalizedRecord,
    "Gate3_Genesis_State.schema.json": Gate3Genesis,
    "Gate3_Loaded_Match.schema.json": Gate3LoadedMatch,
    "Gate3_Manifest.schema.json": Gate3Manifest,
    "Gate3_Match_Lock.schema.json": Gate3MatchLock,
    "Gate3_Prepare_Record.schema.json": Gate3PrepareRecord,
    "Gate3_Runtime_Control.schema.json": Gate3RuntimeControl,
    "Gate3_Snapshot.schema.json": Gate3Snapshot,
}

_DIAGNOSTICS = [
    ("MATCH_LOCK_MISSING", "BLOCK", "Restore MatchLock.json."),
    ("MATCH_LOCK_HASH_MISMATCH", "BLOCK", "Restore the exact immutable match lock."),
    ("MATCH_CONTENT_MISSING", "BLOCK", "Restore the exact required source/content file."),
    ("MATCH_CONTENT_VERSION_MISMATCH", "BLOCK", "Use the exact compatible Gate 3 source/content version."),
    ("MATCH_GENESIS_HASH_MISMATCH", "BLOCK", "Restore the exact immutable genesis state."),
    ("MATCH_JOURNAL_TRAILING_PARTIAL_RECORD", "RECOVER", "Preserve trailing bytes and truncate only to the last complete line."),
    ("MATCH_JOURNAL_RECORD_HASH_MISMATCH", "BLOCK", "Restore the exact malformed or altered complete record."),
    ("MATCH_JOURNAL_CHAIN_MISMATCH", "BLOCK", "Restore the exact hash-chained journal."),
    ("MATCH_JOURNAL_SEQUENCE_GAP", "BLOCK", "Restore the missing or exact contiguous journal record."),
    ("MATCH_SNAPSHOT_HASH_MISMATCH_FALLBACK", "RECOVER", "Try an older snapshot or genesis replay."),
    ("MATCH_SNAPSHOT_NONE_VALID_REPLAY_FROM_GENESIS", "RECOVER", "Replay from immutable genesis and journal."),
    ("MATCH_MANIFEST_REBUILT", "RECOVER", "Use the journal-authoritative rebuilt manifest."),
    ("MATCH_RECOVERY_PREPARED_TRANSACTION_COMPLETED", "RECOVER", "Continue from the deterministically completed accepted intent."),
    ("MATCH_RECOVERY_TERMINAL_FINALIZED", "RECOVER", "Use the restored terminal finalization marker."),
    ("MATCH_RECOVERY_DETERMINISM_MISMATCH", "BLOCK", "Restore exact pre-state/content; do not guess."),
    ("MATCH_REPLAY_FINAL_STATE_MISMATCH", "BLOCK", "Inspect reducer/event-schema mismatch."),
    ("MATCH_ALREADY_COMPLETE", "REJECT", "Use verify, replay, status, or export."),
    ("MATCH_STORAGE_LOCKED", "RETRY", "Close the active local writer and retry."),
    ("MATCH_STORAGE_STALE_LOCK_RECOVERED", "RECOVER", "No action required after stale metadata replacement."),
    ("MATCH_STORAGE_PATH_REJECTED", "REJECT", "Use a valid confined match ID and UserData root."),
]


def _write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(document) + b"\n")


def diagnostics_inventory_document() -> dict[str, object]:
    return {
        "schema": "TianxiaGate3DiagnosticsInventory.v1",
        "diagnostic_count": len(_DIAGNOSTICS),
        "diagnostics": [
            {"code": code, "disposition": disposition, "recommended_action": action}
            for code, disposition, action in _DIAGNOSTICS
        ],
        "security_claim": False,
        "scope": "ordinary local failure diagnosis and recovery",
    }


def build_gate3_artifacts(output_root: Path) -> dict[str, object]:
    output_root = Path(output_root)
    generated = output_root / "generated"
    schema_root = generated / "schemas"
    coverage = reducer_coverage_document()
    diagnostics = diagnostics_inventory_document()
    _write_json(generated / "Gate3_Replay_Completeness_Coverage.json", coverage)
    _write_json(generated / "Gate3_Diagnostics_Inventory.json", diagnostics)
    schema_hashes: dict[str, str] = {}
    for filename, model in sorted(_SCHEMA_MODELS.items()):
        schema = model.model_json_schema(by_alias=True)
        _write_json(schema_root / filename, schema)
        schema_hashes[filename] = canonical_sha256(schema)
    manifest = {
        "schema": "TianxiaGate3GeneratedArtifactManifest.v1",
        "gate3_runtime_version": GATE3_RUNTIME_VERSION,
        "reducer_version": coverage["reducer_version"],
        "replay_coverage_status": coverage["status"],
        "gate2_event_type_count": coverage["declared_gate2_event_type_count"],
        "diagnostic_count": diagnostics["diagnostic_count"],
        "runtime_schema_count": len(_SCHEMA_MODELS),
        "runtime_schema_sha256": dict(sorted(schema_hashes.items())),
        "generic_disk_state_patch_supported": False,
    }
    _write_json(generated / "Gate3_Generated_Artifact_Manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Gate 3 persistence schemas and coverage artifacts.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_gate3_artifacts(args.output)
    print(canonical_bytes(manifest).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
