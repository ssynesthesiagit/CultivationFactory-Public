from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from .canonical import canonical_bytes, canonical_sha256, sha256_file
from .gate2_runtime_models import ActionIntent, CombatEvent, RollRecord
from .gate3_models import JOURNAL_SCHEMA, Gate3CommitPayload, Gate3PreparePayload
from .gate3_reducer import canonical_state_sha256, enrich_committed_events
from .gate3_storage import (
    Gate3Persistence, Gate3MatchStore, PersistentMatchSession,
    _typed_record_payload, atomic_write_bytes,
)
from .gate4_context import build_reaction_context
from .gate4_controller import LocalDeterministicController
from .gate4_engine import Gate4ControllerEngine, ReactionProvider
from .gate4_models import ControllerChoice, DecisionRecord
from .gate4_policy import PolicyLibrary
from .portable_runtime_authority import RUNTIME_AUTHORITY_FILE
from .historical_match_compat import is_exact_completed_predecessor, validate_exact_completed_predecessor


CONTROLLER_LOCK_SCHEMA = "TianxiaGate4ControllerLock.v1"
CONTROLLER_JOURNAL_SCHEMA = "TianxiaGate4ControllerJournal.v1"


def _append_jsonl(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(document) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Gate4PersistentSession:
    def __init__(self, persistence: "Gate4Persistence", mechanical: PersistentMatchSession):
        self.persistence = persistence
        self.mechanical = mechanical
        self.engine: Gate4ControllerEngine = mechanical.engine  # type: ignore[assignment]
        self.store = mechanical.store
        self.match_lock = mechanical.match_lock
        self.diagnostics = mechanical.diagnostics
        self.historical_read_only = bool(getattr(mechanical, "historical_read_only", False))
        self._controller_record_sequence = len(_read_jsonl(self.store.match_dir / "ControllerJournal.ndjson"))

    @property
    def match_id(self) -> str:
        return self.mechanical.match_id

    @property
    def controller_journal_path(self) -> Path:
        return self.store.match_dir / "ControllerJournal.ndjson"

    def _append_controller_record(self, document: dict[str, Any]) -> None:
        self._controller_record_sequence += 1
        _append_jsonl(self.controller_journal_path, {
            **document,
            "schema": CONTROLLER_JOURNAL_SCHEMA,
            "record_sequence": self._controller_record_sequence,
        })

    def submit_intent(
        self,
        intent: ActionIntent,
        *,
        primary_decision_record: DecisionRecord | None,
        reaction_provider: ReactionProvider | None,
        failure_injector=None,
    ) -> None:
        transaction_id = (
            f"persist:{self.engine.state.state_version + 1:08d}:"
            f"{canonical_sha256(intent.model_dump(mode='json'))[:16]}"
        )
        prepare = {
            "record_type": "CONTROLLER_PREPARE",
            "transaction_id": transaction_id,
            "intent_id": intent.intent_id,
            "state_version": intent.state_version,
            "primary_decision_record": (
                primary_decision_record.model_dump(mode="json", by_alias=True)
                if primary_decision_record is not None else None
            ),
        }
        self._append_controller_record(prepare)
        self.engine.set_reaction_provider(reaction_provider)
        try:
            self.mechanical.execute_intent(intent, failure_injector=failure_injector)
        except Exception as exc:
            # If no mechanical PREPARE survived, close the controller-only record.
            records, _ = self.store.scan_journal(recover_trailing_partial=False)
            if not records or records[-1].get("transaction_id") != transaction_id:
                self._append_controller_record({
                    "record_type": "CONTROLLER_ABORT",
                    "transaction_id": transaction_id,
                    "diagnostic": {"type": type(exc).__name__, "message": str(exc)},
                })
            raise
        finally:
            self.engine.set_reaction_provider(None)
        self._append_controller_record({
            "record_type": "CONTROLLER_COMMIT",
            "transaction_id": transaction_id,
            "reaction_decision_records": self.engine.gate4_reaction_decision_records,
        })

    def execute_controller_choice(
        self,
        choice: ControllerChoice,
        *,
        controller: LocalDeterministicController,
        policy_library: PolicyLibrary,
        failure_injector=None,
    ) -> None:
        def provider(request: dict[str, Any]):
            policy, _ = policy_library.for_actor(str(request["reactor_id"]))
            context = build_reaction_context(self.engine, policy, request)
            reaction = controller.choose_reaction(context)
            return reaction.decision, reaction.record.model_dump(mode="json", by_alias=True)
        self.submit_intent(
            choice.intent,
            primary_decision_record=choice.record,
            reaction_provider=provider,
            failure_injector=failure_injector,
        )

    def verify(self) -> dict[str, Any]:
        base = self.mechanical.verify()
        rows = _read_jsonl(self.controller_journal_path)
        open_tx: set[str] = set()
        for index, row in enumerate(rows, start=1):
            if row.get("record_sequence") != index:
                raise ValueError("CONTROLLER_JOURNAL_SEQUENCE_GAP")
            tid = row.get("transaction_id")
            if row["record_type"] == "CONTROLLER_PREPARE":
                open_tx.add(tid)
            elif row["record_type"] in {"CONTROLLER_COMMIT", "CONTROLLER_ABORT"}:
                open_tx.discard(tid)
        return {**base, "controller_record_count": len(rows), "controller_open_transactions": sorted(open_tx)}


class Gate4Persistence(Gate3Persistence):
    def __init__(self, source_root: Path, userdata_root: Path):
        super().__init__(source_root, userdata_root)
        self.policy_library = PolicyLibrary(source_root)
        self.local_controller = LocalDeterministicController()
        self._recovery_provider_enabled = False
        self._recovery_reaction_records: list[dict[str, Any]] = []

    def _controller_lock_path(self, store: Gate3MatchStore) -> Path:
        return store.match_dir / "ControllerLock.json"

    @staticmethod
    def _controller_interface_paths() -> tuple[str, ...]:
        return (
            "combat/choice_authority.py",
            "combat/gate4_models.py",
            "combat/gate4_context.py",
            "combat/gate4_controller.py",
            "combat/gate4_engine.py",
            "combat/gate4_persistence.py",
        )

    def _controller_lock_document(self) -> dict[str, Any]:
        policy_rows = {
            path.name: sha256_file(path)
            for path in sorted((self.source_root / "combat_gate4/policies").glob("*.json"))
        }
        return {
            "schema": CONTROLLER_LOCK_SCHEMA,
            "controller_id": self.local_controller.controller_id,
            "controller_version": self.local_controller.controller_version,
            "policy_sha256": policy_rows,
            "interface_files": {
                rel: sha256_file(self.source_root / rel)
                for rel in self._controller_interface_paths()
            },
        }

    def _validate_controller_lock(self, store: Gate3MatchStore) -> None:
        """Validate controller authority without writing owner match data.

        This is deliberately called before the inherited Gate 3 load, writer-lock
        acquisition, replay, recovery, manifest rebuilding, diagnostics, or any
        other filesystem mutation. Normal load never creates or migrates a
        ControllerLock.
        """
        if is_exact_completed_predecessor(store.match_dir, store.match_id):
            validate_exact_completed_predecessor(store.match_dir, store.match_id)
            return
        path = self._controller_lock_path(store)
        if not path.is_file():
            raise ValueError("CONTROLLER_AUTHORITY_LOCK_INCOMPLETE")
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError("CONTROLLER_AUTHORITY_LOCK_INCOMPLETE") from exc
        expected = self._controller_lock_document()

        required_top_level = {
            "schema", "controller_id", "controller_version",
            "policy_sha256", "interface_files",
        }
        if not isinstance(existing, dict) or not required_top_level.issubset(existing):
            raise ValueError("CONTROLLER_AUTHORITY_LOCK_INCOMPLETE")

        existing_interfaces = existing.get("interface_files")
        existing_policies = existing.get("policy_sha256")
        expected_interfaces = expected["interface_files"]
        expected_policies = expected["policy_sha256"]
        if (
            not isinstance(existing_interfaces, dict)
            or not set(expected_interfaces).issubset(existing_interfaces)
            or not isinstance(existing_policies, dict)
            or not set(expected_policies).issubset(existing_policies)
        ):
            raise ValueError("CONTROLLER_AUTHORITY_LOCK_INCOMPLETE")
        if existing != expected:
            raise ValueError("CONTROLLER_POLICY_INVALID")

    def _create_controller_lock(self, store: Gate3MatchStore) -> None:
        """Create a lock only during explicit match creation.

        Existing locks are validated and never rewritten. Missing locks during
        normal load are a hard failure and require a separately authorized
        migration, not implicit adoption of the current source.
        """
        path = self._controller_lock_path(store)
        if path.exists():
            self._validate_controller_lock(store)
            return
        atomic_write_bytes(path, canonical_bytes(self._controller_lock_document()) + b"\n")

    def _upgrade_engine(self, engine) -> Gate4ControllerEngine:
        upgraded = Gate4ControllerEngine(
            self.source_root,
            match_seed=engine.state.match_seed,
            maximum_rounds=engine.state.maximum_rounds,
            runtime_authority=(
                engine.runtime_authority.model_dump(mode="json", by_alias=True)
                if getattr(engine, "runtime_authority", None) is not None else None
            ),
        )
        upgraded.state = engine.state.model_copy(deep=True)
        upgraded.events = [CombatEvent.model_validate(e.model_dump(mode="json") if hasattr(e, "model_dump") else e) for e in engine.events]
        upgraded.rolls = [RollRecord.model_validate(r.model_dump(mode="json") if hasattr(r, "model_dump") else r) for r in engine.rolls]
        upgraded.roller.counter = engine.state.roll_counter
        upgraded._transaction_id = None
        upgraded._transaction_result_version = engine.state.state_version
        upgraded._active_intent_id = "system:gate4"
        upgraded._active_intent = None
        upgraded._commanded_cui_this_turn = bool(engine._commanded_cui_this_turn)
        return upgraded

    def _engine_from_loaded(self, state, events, rolls, *, commanded_cui_this_turn):
        runtime_path = Gate3MatchStore(self.userdata_root, state.match_id).match_dir / RUNTIME_AUTHORITY_FILE
        runtime_authority = json.loads(runtime_path.read_text(encoding="utf-8")) if runtime_path.is_file() else None
        engine = Gate4ControllerEngine(
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
        if self._recovery_provider_enabled:
            def provider(request: dict[str, Any]):
                policy, _ = self.policy_library.for_actor(str(request["reactor_id"]))
                context = build_reaction_context(engine, policy, request)
                reaction = self.local_controller.choose_reaction(context)
                record = reaction.record.model_dump(mode="json", by_alias=True)
                self._recovery_reaction_records.append(record)
                return reaction.decision, record
            engine.set_reaction_provider(provider)
        return engine

    def _recover_incomplete_prepare(self, store, lock, genesis, records):
        prepare_record = records[-1]
        prepare = Gate3PreparePayload.model_validate(
            _typed_record_payload(prepare_record, Gate3PreparePayload)
        )
        controller_rows = _read_jsonl(store.match_dir / "ControllerJournal.ndjson")
        controller_prepare = next(
            (
                row for row in reversed(controller_rows)
                if row.get("record_type") == "CONTROLLER_PREPARE"
                and row.get("transaction_id") == prepare.transaction_id
            ),
            None,
        )
        if controller_prepare and controller_prepare.get("primary_decision_record"):
            prior_records = records[:-1]
            state = self._state_before_incomplete_prepare(genesis, prior_records)
            commits = self._commit_records(prior_records)
            events = list(genesis.initial_events)
            rolls = list(genesis.initial_rolls)
            commanded = genesis.commanded_cui_this_turn
            for record in commits:
                events.extend(record["events"])
                rolls.extend(record["rolls"])
                if record["events"]:
                    control = record["events"][-1].get("payload", {}).get("gate3_runtime_control_after")
                    if control is not None:
                        commanded = bool(control["commanded_cui_this_turn"])
            probe = self._engine_from_loaded(
                state, events, rolls, commanded_cui_this_turn=commanded
            )
            policy, _ = self.policy_library.for_actor(prepare.intent.actor_id)
            from .gate4_context import build_decision_context
            context = build_decision_context(probe, policy)
            choice = self.local_controller.choose_primary_action(context)
            stored = DecisionRecord.model_validate(controller_prepare["primary_decision_record"])
            if (
                choice.intent.model_dump(mode="json") != prepare.intent.model_dump(mode="json")
                or choice.record.model_dump(mode="json", by_alias=True)
                != stored.model_dump(mode="json", by_alias=True)
            ):
                raise ValueError("CONTROLLER_DECISION_NONDETERMINISTIC")
        self._recovery_reaction_records = []
        self._recovery_provider_enabled = True
        try:
            result = super()._recover_incomplete_prepare(store, lock, genesis, records)
        finally:
            self._recovery_provider_enabled = False
        if controller_prepare:
            _append_jsonl(store.match_dir / "ControllerJournal.ndjson", {
                "schema": CONTROLLER_JOURNAL_SCHEMA,
                "record_type": "CONTROLLER_COMMIT",
                "record_sequence": len(_read_jsonl(store.match_dir / "ControllerJournal.ndjson")) + 1,
                "transaction_id": prepare.transaction_id,
                "reaction_decision_records": self._recovery_reaction_records,
                "recovered_from_incomplete_prepare": True,
            })
        return result

    def create_match(
        self, *, match_seed: str, maximum_rounds: int = 20,
        genesis_setup: dict[str, dict[str, object]] | None = None,
        roster_setup: dict[str, object] | None = None,
        runtime_authority: dict[str, Any] | None = None,
        source_package: Path | None = None,
    ) -> Gate4PersistentSession:
        base = super().create_match(
            match_seed=match_seed, maximum_rounds=maximum_rounds,
            genesis_setup=genesis_setup, roster_setup=roster_setup,
            runtime_authority=runtime_authority, source_package=source_package,
        )
        base.engine = self._upgrade_engine(base.engine)
        with base.store.writer_lock():
            self._create_controller_lock(base.store)
        return Gate4PersistentSession(self, base)

    def load_match(self, match_id: str, *, recover: bool = True, rebuild_manifest: bool = True) -> Gate4PersistentSession:
        preflight_store = Gate3MatchStore(self.userdata_root, match_id)
        historical_read_only = is_exact_completed_predecessor(preflight_store.match_dir, match_id)
        # Controller authority must be validated before the inherited load can
        # replay, recover, rebuild a manifest, write diagnostics, or touch the
        # match writer-lock file. This preflight is read-only by construction.
        self._validate_controller_lock(preflight_store)

        # The inherited load uses this class's _engine_from_loaded override.
        base = super().load_match(
            match_id,
            recover=False if historical_read_only else recover,
            rebuild_manifest=False if historical_read_only else rebuild_manifest,
        )
        base.historical_read_only = historical_read_only
        if not isinstance(base.engine, Gate4ControllerEngine):
            base.engine = self._upgrade_engine(base.engine)
        return Gate4PersistentSession(self, base)
