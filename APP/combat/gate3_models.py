from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .models import StrictModel
from .gate2_runtime_models import ActionIntent, MatchState, Position, TerminalResult

STORAGE_SCHEMA_VERSION = "TianxiaCombatMatchStorage.v1"
EVENT_SCHEMA_VERSION = "TianxiaCombatEventReplay.v1"
REDUCER_VERSION = "TianxiaGate3Reducer.v1"
JOURNAL_SCHEMA = "TianxiaCombatJournalRecord.v1"
SNAPSHOT_SCHEMA = "TianxiaCombatSnapshot.v1"
MANIFEST_SCHEMA = "TianxiaCombatManifest.v1"
GENESIS_SCHEMA = "TianxiaCombatGenesis.v1"
MATCH_LOCK_SCHEMA = "TianxiaCombatMatchLock.v1"
RUNTIME_CONTROL_SCHEMA = "TianxiaGate3RuntimeControl.v1"


class Gate3ActorRuntimeControl(StrictModel):
    position: Position
    movement_remaining_ft: int = Field(ge=0)
    action_available: bool
    bonus_action_available: bool
    reaction_available: bool
    resources: dict[str, int]
    turn_flags: dict[str, Any]
    turns_started: int = Field(ge=0)


class Gate3ZoneRuntimeControl(StrictModel):
    active: bool
    per_turn_triggered: dict[str, int]


class Gate3RuntimeControl(StrictModel):
    schema_name: Literal["TianxiaGate3RuntimeControl.v1"] = Field(
        default=RUNTIME_CONTROL_SCHEMA, alias="schema"
    )
    round_number: int = Field(ge=1)
    current_slot_index: int = Field(ge=0)
    current_actor_id: str
    pending_resolution: dict[str, Any] | None
    actors: dict[str, Gate3ActorRuntimeControl]
    zones: dict[str, Gate3ZoneRuntimeControl]
    commanded_cui_this_turn: bool


class Gate3ContentIdentity(StrictModel):
    identity_id: str
    sha256: str
    relative_path: str | None = None
    authority_scope: Literal["SOURCE", "MATCH"] = "SOURCE"


class Gate3MatchLock(StrictModel):
    schema_name: Literal["TianxiaCombatMatchLock.v1"] = Field(
        default=MATCH_LOCK_SCHEMA, alias="schema"
    )
    match_id: str
    storage_schema_version: str = STORAGE_SCHEMA_VERSION
    engine_version: str
    event_schema_version: str = EVENT_SCHEMA_VERSION
    reducer_version: str = REDUCER_VERSION
    mechanics_lock_sha256: str
    universal_defaults_lock_sha256: str
    gate1_registry_snapshot_sha256: str
    projection_sha256: dict[str, str]
    battlefield_sha256: str
    encounter_sha256: str
    match_seed: str
    initial_roll_counter: int = Field(ge=0)
    actor_ids: tuple[str, ...]
    genesis_state_sha256: str
    genesis_payload_sha256: str
    content_identities: tuple[Gate3ContentIdentity, ...]
    created_at_display: str
    deterministic_payload_sha256: str


class Gate3Genesis(StrictModel):
    schema_name: Literal["TianxiaCombatGenesis.v1"] = Field(
        default=GENESIS_SCHEMA, alias="schema"
    )
    match_id: str
    state: MatchState
    initial_events: tuple[dict[str, Any], ...]
    initial_rolls: tuple[dict[str, Any], ...]
    commanded_cui_this_turn: bool
    canonical_state_sha256: str
    initial_event_log_sha256: str
    initial_roll_log_sha256: str


class Gate3Snapshot(StrictModel):
    schema_name: Literal["TianxiaCombatSnapshot.v1"] = Field(
        default=SNAPSHOT_SCHEMA, alias="schema"
    )
    match_id: str
    reducer_version: str = REDUCER_VERSION
    journal_record_sequence: int = Field(ge=0)
    last_journal_record_sha256: str
    event_sequence: int = Field(ge=0)
    state_version: int = Field(ge=0)
    roll_counter: int = Field(ge=0)
    state: MatchState
    commanded_cui_this_turn: bool
    canonical_state_sha256: str
    snapshot_sha256: str


class Gate3Manifest(StrictModel):
    schema_name: Literal["TianxiaCombatManifest.v1"] = Field(
        default=MANIFEST_SCHEMA, alias="schema"
    )
    match_id: str
    status: Literal["ACTIVE", "COMPLETE", "RECOVERY_REQUIRED", "BLOCKED"]
    last_valid_journal_record: int = Field(ge=0)
    last_journal_record_sha256: str
    last_committed_transaction: str | None = None
    last_event_sequence: int = Field(ge=0)
    state_version: int = Field(ge=0)
    roll_counter: int = Field(ge=0)
    latest_valid_snapshot: str | None = None
    terminal_result: TerminalResult | None = None
    last_diagnostic_summary: dict[str, Any] | None = None
    display_updated_at: str
    file_identities: dict[str, str]


class Gate3PreparePayload(StrictModel):
    transaction_id: str
    intent: ActionIntent
    candidate_binding: dict[str, Any]
    pre_state_version: int = Field(ge=0)
    pre_state_sha256: str
    event_sequence_before: int = Field(ge=0)
    roll_counter_start: int = Field(ge=0)


class Gate3CommitPayload(StrictModel):
    transaction_id: str
    intent: ActionIntent
    pre_state_sha256: str
    post_state_version: int = Field(ge=0)
    post_state_sha256: str
    event_sequence_start: int = Field(ge=0)
    event_sequence_end: int = Field(ge=0)
    roll_counter_start: int = Field(ge=0)
    roll_counter_end: int = Field(ge=0)
    events: tuple[dict[str, Any], ...]
    rolls: tuple[dict[str, Any], ...]
    terminal_result: TerminalResult | None = None


class Gate3AbortPayload(StrictModel):
    transaction_id: str
    intent: ActionIntent
    unchanged_state_sha256: str
    diagnostic: dict[str, Any]


class Gate3FinalizePayload(StrictModel):
    final_commit_transaction_id: str
    final_state_sha256: str
    final_event_sequence: int = Field(ge=0)
    final_roll_counter: int = Field(ge=0)
    terminal_result: TerminalResult


class Gate3JournalEnvelope(StrictModel):
    schema_name: Literal["TianxiaCombatJournalRecord.v1"] = Field(
        default=JOURNAL_SCHEMA, alias="schema"
    )
    record_type: Literal["PREPARE", "COMMIT", "ABORT", "MATCH_FINALIZED"]
    record_sequence: int = Field(ge=1)
    previous_record_sha256: str
    record_sha256: str


class Gate3PrepareRecord(Gate3PreparePayload, Gate3JournalEnvelope):
    record_type: Literal["PREPARE"] = "PREPARE"


class Gate3CommitRecord(Gate3CommitPayload, Gate3JournalEnvelope):
    record_type: Literal["COMMIT"] = "COMMIT"


class Gate3AbortRecord(Gate3AbortPayload, Gate3JournalEnvelope):
    record_type: Literal["ABORT"] = "ABORT"


class Gate3FinalizedRecord(Gate3FinalizePayload, Gate3JournalEnvelope):
    record_type: Literal["MATCH_FINALIZED"] = "MATCH_FINALIZED"


class Gate3LoadedMatch(StrictModel):
    match_lock: Gate3MatchLock
    state: MatchState
    events: tuple[dict[str, Any], ...]
    rolls: tuple[dict[str, Any], ...]
    last_record_sequence: int = Field(ge=0)
    last_record_sha256: str
    diagnostics: tuple[dict[str, Any], ...]
    resumed_prepared_transaction: bool
    terminal: bool
    commanded_cui_this_turn: bool
