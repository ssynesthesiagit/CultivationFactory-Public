from __future__ import annotations

"""Exact completed C3C-P3 predecessor compatibility.

This module intentionally supports one accepted, completed, read-only match.
It is not a migration framework and it never rewrites owner match data.
"""

import json
from pathlib import Path
from typing import Any

from .canonical import sha256_file

HISTORICAL_MATCH_ID = "match:6eb2656f93305e489ac87d37"
PREDECESSOR_SOURCE_SHA256 = "2e77c79b210413bc8e5f9ebd54ed642e089f9dcbb5f42db953f72c85d73719cd"
EXPECTED_FINAL_STATE_SHA256 = "9e837d6fce7a16e4e054a496fc7cb42826533878e6bf4049bf335213063f438f"
EXPECTED_FINAL_SUMMARY_SHA256 = "f0a33f9591fce1bdcca5882b353c55d9b62ac419f9eae33f93571d5c205451aa"
EXPECTED_CONTROLLER_LOCK_SHA256 = "d85bf8529a738250f02352898869769fa0454b553b8d085e57dbc923af43a1e3"
EXPECTED_MATCH_LOCK_SHA256 = "17ba4e3f6090e19f3f226dee8bceaa6d6042aab0c418f75e51c3debde9d77a2c"

EXPECTED_MATCH_FILES: dict[str, str] = {
    ".writer.lock": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "ControllerJournal.ndjson": "06cc15ef260e1035e061a1faff8d5543321b90cbc6d35c82f6c4c282c7c77e28",
    "ControllerLock.json": EXPECTED_CONTROLLER_LOCK_SHA256,
    "DaoIChingChoiceAudit.ndjson": "442b28ee7ec502495e1a09780100768dfd915384eb9538d62cd03bb67a9d029c",
    "Exports/Gate3_Current_State.json": "9c664e9fb67dfe0ed49e42bad217ee1e1c8ff77f4d74dfe3187526f843aed17b",
    "Exports/Gate3_Event_Log.json": "78b47588bcc9116b561ea4a0dd0bf1d8df15572c34b042282bec142ddfb8a8ce",
    "Exports/Gate3_Replay_Result.json": "e092b6d2ab29dc77fabcda511e4bf78cd05ed83d344e58dedbff8cae65c4221d",
    "Exports/Gate3_Roll_Log.json": "71830b72ab784818372b1ae248eb5285861dedce28ecaadb87008217380a06b0",
    "FactoryIntegration.json": "b4660d90dbf09f11b93f5aebc5a3b06058d984cdecef51b5382cecb28981907c",
    "FinalSummary.json": EXPECTED_FINAL_SUMMARY_SHA256,
    "GenesisState.json": "ded41e309f964ff2d0e8995c9a959a05f7301f46bbabe4e7ab311419dc5e5016",
    "Journal.ndjson": "4e0ebcca093098c6a765b640c883acbca0a5c17f415c37dc401503ca6455d03b",
    "Manifest.json": "176111b101a6da62c46a576d21e93d288f416c6f19e28113df1c969c8db3b758",
    "MatchLock.json": EXPECTED_MATCH_LOCK_SHA256,
    "Snapshots/Snapshot_00000020.json": "63b64daf95172f3d78f231692bc907513aeceb1a231fd408766f7d31b2f98bb2",
    "Snapshots/Snapshot_00000025.json": "85700e3e7bf79b75d8055a82678e1fd94889b00492c5004178f9dfe5d1c2f305",
}


def is_historical_match_id(match_id: str) -> bool:
    return match_id == HISTORICAL_MATCH_ID


def is_exact_completed_predecessor(match_dir: Path, match_id: str) -> bool:
    """Cheap discriminator used before the full exact validation."""
    if not is_historical_match_id(match_id):
        return False
    root = Path(match_dir)
    controller = root / "ControllerLock.json"
    match_lock = root / "MatchLock.json"
    return (
        controller.is_file()
        and match_lock.is_file()
        and sha256_file(controller) == EXPECTED_CONTROLLER_LOCK_SHA256
        and sha256_file(match_lock) == EXPECTED_MATCH_LOCK_SHA256
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - exact diagnostic surface
        raise ValueError(f"C3D_HISTORICAL_FILE_INVALID:{path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"C3D_HISTORICAL_FILE_INVALID:{path.name}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception as exc:  # pragma: no cover - exact diagnostic surface
        raise ValueError(f"C3D_HISTORICAL_FILE_INVALID:{path.name}") from exc
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"C3D_HISTORICAL_FILE_INVALID:{path.name}")
    return rows


def validate_exact_completed_predecessor(match_dir: Path, match_id: str) -> dict[str, Any]:
    """Validate the exact accepted predecessor fixture without writing anything."""

    if not is_historical_match_id(match_id):
        raise ValueError("C3D_HISTORICAL_MATCH_ID_UNRECOGNIZED")
    root = Path(match_dir)
    if not root.is_dir():
        raise ValueError("C3D_HISTORICAL_MATCH_DIRECTORY_MISSING")

    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    expected_files = set(EXPECTED_MATCH_FILES)
    if actual_files != expected_files:
        raise ValueError(
            "C3D_HISTORICAL_FILE_SET_MISMATCH:"
            f"missing={sorted(expected_files-actual_files)}:extra={sorted(actual_files-expected_files)}"
        )
    for relative_path, expected_sha256 in EXPECTED_MATCH_FILES.items():
        # The operating-system writer lock temporarily contains process metadata
        # while a normal read path holds the lock, then returns to empty bytes.
        # It is not match authority and is checked by before/after immutability tests.
        if relative_path == ".writer.lock":
            continue
        actual_sha256 = sha256_file(root / relative_path)
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"C3D_HISTORICAL_FILE_IDENTITY_MISMATCH:{relative_path}:"
                f"expected={expected_sha256}:actual={actual_sha256}"
            )

    lock = _read_json(root / "MatchLock.json")
    controller_lock = _read_json(root / "ControllerLock.json")
    manifest = _read_json(root / "Manifest.json")
    summary = _read_json(root / "FinalSummary.json")
    journal = _read_jsonl(root / "Journal.ndjson")
    controller_journal = _read_jsonl(root / "ControllerJournal.ndjson")

    if lock.get("match_id") != match_id or manifest.get("match_id") != match_id or summary.get("match_id") != match_id:
        raise ValueError("C3D_HISTORICAL_MATCH_IDENTITY_MISMATCH")
    if lock.get("schema") != "TianxiaCombatMatchLock.v1":
        raise ValueError("C3D_HISTORICAL_MATCH_LOCK_SCHEMA_INVALID")
    if controller_lock.get("schema") != "TianxiaGate4ControllerLock.v1":
        raise ValueError("C3D_HISTORICAL_CONTROLLER_LOCK_SCHEMA_INVALID")
    if manifest.get("status") != "COMPLETE" or not manifest.get("terminal_result"):
        raise ValueError("C3D_HISTORICAL_MATCH_NOT_COMPLETE")
    if summary.get("final_state_sha256") != EXPECTED_FINAL_STATE_SHA256:
        raise ValueError("C3D_HISTORICAL_FINAL_STATE_IDENTITY_MISMATCH")
    if summary.get("terminal_result") != manifest.get("terminal_result"):
        raise ValueError("C3D_HISTORICAL_TERMINAL_RESULT_MISMATCH")
    if "portable_character_authority" in summary:
        raise ValueError("C3D_HISTORICAL_PORTABLE_AUTHORITY_FORBIDDEN")
    if (root / "PortableRuntimeAuthority.json").exists() or (root / "SourceCharacterPackage.zip").exists():
        raise ValueError("C3D_HISTORICAL_PORTABLE_AUTHORITY_FORBIDDEN")

    finalized = [row for row in journal if row.get("record_type") == "MATCH_FINALIZED"]
    if len(finalized) != 1 or journal[-1] is not finalized[0]:
        raise ValueError("C3D_HISTORICAL_FINALIZATION_INVALID")
    final = finalized[0]
    if final.get("final_state_sha256") != EXPECTED_FINAL_STATE_SHA256:
        raise ValueError("C3D_HISTORICAL_FINAL_STATE_IDENTITY_MISMATCH")
    if final.get("terminal_result") != summary.get("terminal_result"):
        raise ValueError("C3D_HISTORICAL_TERMINAL_RESULT_MISMATCH")

    open_controller_transactions: set[str] = set()
    for row in controller_journal:
        transaction_id = row.get("transaction_id")
        if row.get("record_type") == "CONTROLLER_PREPARE":
            open_controller_transactions.add(str(transaction_id))
        elif row.get("record_type") in {"CONTROLLER_COMMIT", "CONTROLLER_ABORT"}:
            open_controller_transactions.discard(str(transaction_id))
    if open_controller_transactions:
        raise ValueError("C3D_HISTORICAL_CONTROLLER_TRANSACTION_OPEN")

    return {
        "schema": "Tianxia.C3DP1RHistoricalCompatibility.v1",
        "status": "EXACT_COMPLETED_PREDECESSOR_READ_ONLY",
        "match_id": match_id,
        "created_from_source_sha256": PREDECESSOR_SOURCE_SHA256,
        "match_lock_sha256": EXPECTED_MATCH_LOCK_SHA256,
        "controller_lock_sha256": EXPECTED_CONTROLLER_LOCK_SHA256,
        "final_summary_sha256": EXPECTED_FINAL_SUMMARY_SHA256,
        "final_state_sha256": EXPECTED_FINAL_STATE_SHA256,
        "terminal_result": summary["terminal_result"],
        "finalization_record_count": 1,
        "controller_open_transactions": [],
        "match_file_count": len(EXPECTED_MATCH_FILES),
    }


def stored_historical_summary(match_dir: Path, match_id: str) -> dict[str, Any]:
    validate_exact_completed_predecessor(match_dir, match_id)
    return _read_json(Path(match_dir) / "FinalSummary.json")
