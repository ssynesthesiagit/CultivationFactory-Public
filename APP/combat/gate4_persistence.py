from __future__ import annotations

import json
import os
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, canonical_sha256
from .gate2_runtime_models import ActionIntent, CombatEvent, RollRecord
from .gate3_models import Gate3PreparePayload
from .gate3_storage import (
    Gate3Persistence, Gate3MatchStore, PersistentMatchSession,
    LocalMatchWriterLock,
    _typed_record_payload,
)
from .gate4_context import build_reaction_context
from .gate4_controller import LocalDeterministicController
from .gate4_engine import Gate4ControllerEngine, ReactionProvider
from .gate4_models import ControllerChoice, DecisionRecord
from .gate4_policy import PolicyLibrary
from .portable_runtime_authority import RUNTIME_AUTHORITY_FILE
from .saved_fight_format import UnsupportedSavedFight


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
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise UnsupportedSavedFight(f"{path.name} line {line_number} is not an object.")
        rows.append(row)
    return rows


CONTROLLER_RECORD_TYPES = frozenset({"CONTROLLER_PREPARE", "CONTROLLER_COMMIT", "CONTROLLER_ABORT"})


def _read_controller_journal(path: Path) -> list[dict[str, Any]]:
    """Read the controller journal, rejecting any record this version cannot use.

    The mechanical journal and this controller journal are separate; a save
    cannot be repaired for one while a malformed record remains in the other.
    Every record must carry a known record type, its transaction identity, and a
    payload shape its consumers can read -- an optional primary decision record
    that validates and an optional settings policy object -- so that recovery and
    the settings audit never fail after a mechanical write.
    """
    rows = _read_jsonl(path)
    for index, row in enumerate(rows, start=1):
        if row.get("record_type") not in CONTROLLER_RECORD_TYPES:
            raise UnsupportedSavedFight(f"{path.name} record {index} has an unsupported record type.")
        if not isinstance(row.get("transaction_id"), str) or not row["transaction_id"]:
            raise UnsupportedSavedFight(f"{path.name} record {index} is missing its transaction identity.")
        decision = row.get("primary_decision_record")
        if decision is not None:
            try:
                DecisionRecord.model_validate(decision)
            except Exception as exc:
                raise UnsupportedSavedFight(
                    f"{path.name} record {index} has an unreadable primary decision record: {exc}"
                ) from exc
        policy = row.get("settings_policy")
        if policy and not isinstance(policy, dict):
            raise UnsupportedSavedFight(f"{path.name} record {index} has an unreadable settings policy.")
    return rows


class Gate4PersistentSession:
    def __init__(self, persistence: "Gate4Persistence", mechanical: PersistentMatchSession):
        self.persistence = persistence
        self.mechanical = mechanical
        self.engine: Gate4ControllerEngine = mechanical.engine  # type: ignore[assignment]
        self.store = mechanical.store
        self.match_lock = mechanical.match_lock
        self.diagnostics = mechanical.diagnostics
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
        settings_binding: dict[str, Any] | None = None,
    ) -> None:
        """A settings writer owns its audit through both durable COMMIT records.

        Recovery takes the same guard, so a reader cannot close a live writer's
        mechanical/controller gap. Ordinary intent locking stays unchanged.
        """
        guard = (LocalMatchWriterLock(self.store.match_dir / ".settings_audit.lock", self.match_id)
                 if settings_binding is not None else nullcontext())
        # Reserve before controller PREPARE too. Mechanical execution nests
        # the same generic boundary; stale retained sessions append nothing.
        with guard, self.mechanical.command_boundary():
            self._submit_intent(intent, primary_decision_record=primary_decision_record,
                                reaction_provider=reaction_provider, failure_injector=failure_injector,
                                settings_binding=settings_binding)

    def _submit_intent(
        self,
        intent: ActionIntent,
        *,
        primary_decision_record: DecisionRecord | None,
        reaction_provider: ReactionProvider | None,
        failure_injector=None,
        settings_binding: dict[str, Any] | None = None,
    ) -> None:
        if settings_binding is not None and (primary_decision_record is not None or reaction_provider is not None):
            raise ValueError("Settings batches cannot carry controller combat decisions.")
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
        if settings_binding is not None:
            prepare["settings_policy"] = settings_binding
        self._append_controller_record(prepare)
        self.engine.set_reaction_provider(reaction_provider)
        try:
            # Versioned settings provenance uses the same PREPARE/COMMIT audit,
            # rollback, hashes and crash recovery as ordinary single intents.
            self.mechanical.execute_intent(intent, failure_injector=failure_injector,
                                           settings_binding=settings_binding)
        except Exception as exc:
            # If no mechanical PREPARE survived, close the controller-only record.
            records, _ = self.store.scan_journal(recover_trailing_partial=False)
            if settings_binding is not None and records and records[-1].get("transaction_id") == transaction_id:
                if records[-1]["record_type"] in {"COMMIT", "ABORT"}:
                    self._append_controller_record({
                        "record_type": "CONTROLLER_" + records[-1]["record_type"],
                        "transaction_id": transaction_id,
                        "reaction_decision_records": [],
                    })
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
    def __init__(self, source_root: Path, userdata_root: Path, *,
                 policy_library=None, engine_inputs=None, recover_choice=None):
        """Optional application execution inputs for exact crash recovery.

        engine_inputs(engine) refreshes read-only controls on reconstruction.
        recover_choice(engine, verified_prior_records) reproduces the SAME
        automatic policy/context as live execution. Defaults preserve standalone
        Gate4; neither callback may load/recover the fight or write persistence.
        Intent AND complete decision-record equality remain mandatory.
        """
        super().__init__(source_root, userdata_root)
        self.policy_library = policy_library or PolicyLibrary(source_root)
        self.engine_inputs = engine_inputs
        self.recover_choice = recover_choice
        self.local_controller = LocalDeterministicController()
        self._recovery_provider_enabled = False
        self._recovery_reaction_records: list[dict[str, Any]] = []

    def _upgrade_engine(self, engine) -> Gate4ControllerEngine:
        upgraded = Gate4ControllerEngine(
            self.source_root,
            match_seed=engine.state.match_seed,
            maximum_rounds=engine.state.maximum_rounds,
            runtime_authority=(
                engine.runtime_authority.model_dump(mode="json", by_alias=True)
                if getattr(engine, "runtime_authority", None) is not None else None
            ),
            typed_bundles=tuple(getattr(engine, "typed_bundle_documents", ()) or ()),
            battlefield=getattr(engine, "battlefield_document", None),
        )
        upgraded.state = engine.state.model_copy(deep=True)
        upgraded.events = [CombatEvent.model_validate(e.model_dump(mode="json") if hasattr(e, "model_dump") else e) for e in engine.events]
        from .terrain_occlusion import saved_policy
        upgraded.grid.bind_occluder_policy(saved_policy(upgraded.events))
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
        from .gate3_storage import load_arena, load_typed_bundles

        engine = Gate4ControllerEngine(
            self.source_root,
            match_seed=state.match_seed,
            maximum_rounds=state.maximum_rounds,
            runtime_authority=runtime_authority,
            typed_bundles=load_typed_bundles(Gate3MatchStore(self.userdata_root, state.match_id).match_dir),
            battlefield=load_arena(Gate3MatchStore(self.userdata_root, state.match_id).match_dir),
        )
        engine.state = state.model_copy(deep=True)
        engine.events = [CombatEvent.model_validate(event) for event in events]
        from .terrain_occlusion import saved_policy
        engine.grid.bind_occluder_policy(saved_policy(engine.events))
        engine.rolls = [RollRecord.model_validate(roll) for roll in rolls]
        engine.roller.counter = state.roll_counter
        engine._transaction_id = None
        engine._transaction_result_version = state.state_version
        engine._active_intent_id = "system:resume"
        engine._active_intent = None
        engine._commanded_cui_this_turn = commanded_cui_this_turn
        if self.engine_inputs is not None:
            self.engine_inputs(engine)
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

    def _recover_incomplete_prepare(self, store, lock, genesis, records, *, controller_appends):
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
            if self.recover_choice is not None:
                choice = self.recover_choice(probe, prior_records)
            else:
                policy, _ = self.policy_library.for_actor(prepare.intent.actor_id)
                from .gate4_context import build_decision_context
                context = build_decision_context(probe, policy, for_ai=True)
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
            result, commit_record = super()._recover_incomplete_prepare(
                store, lock, genesis, records, controller_appends=controller_appends
            )
        finally:
            self._recovery_provider_enabled = False
        if controller_prepare:
            # Queued for the write phase; a load that fails after this point must
            # leave the controller journal untouched too.
            controller_appends.append({
                "schema": CONTROLLER_JOURNAL_SCHEMA,
                "record_type": "CONTROLLER_COMMIT",
                "record_sequence": len(_read_jsonl(store.match_dir / "ControllerJournal.ndjson")) + 1,
                "transaction_id": prepare.transaction_id,
                "reaction_decision_records": self._recovery_reaction_records,
                "recovered_from_incomplete_prepare": True,
            })
        return result, commit_record

    def _apply_load_plan(self, store, plan) -> None:
        """Write the mechanical repairs, then any queued controller records."""
        super()._apply_load_plan(store, plan)
        for document in plan.controller_appends:
            _append_jsonl(store.match_dir / "ControllerJournal.ndjson", document)

    def create_match(
        self, *, match_seed: str, maximum_rounds: int = 20,
        genesis_setup: dict[str, dict[str, object]] | None = None,
        roster_setup: dict[str, object] | None = None,
        runtime_authority: dict[str, Any] | None = None,
        source_package: Path | None = None,
        typed_bundles: tuple[dict[str, Any], ...] = (),
        battlefield: dict[str, Any] | None = None,
    ) -> Gate4PersistentSession:
        base = super().create_match(
            match_seed=match_seed, maximum_rounds=maximum_rounds,
            genesis_setup=genesis_setup, roster_setup=roster_setup,
            runtime_authority=runtime_authority, source_package=source_package,
            typed_bundles=typed_bundles, battlefield=battlefield,
        )
        base.engine = self._upgrade_engine(base.engine)
        return Gate4PersistentSession(self, base)

    def _reconcile_settings_audit(self, session):
        """Close only versioned no-reaction settings audit gaps after durable resolution."""
        # A process can stop after mechanical COMMIT but before controller COMMIT.
        # Only the explicitly recorded no-reaction policy permits reconstruction.
        from .ext.setting_choices import BATCH_KINDS
        from .combat_world_facts import KIND
        from .fact_consent_admission import WORLD_KIND
        policies = {*BATCH_KINDS, KIND, WORLD_KIND}
        rows = _read_jsonl(session.controller_journal_path)
        closed = {r["transaction_id"] for r in rows if r["record_type"] in {"CONTROLLER_COMMIT", "CONTROLLER_ABORT"}}
        if not any(r["record_type"] == "CONTROLLER_PREPARE" and r["transaction_id"] not in closed
                   and (r.get("settings_policy") or {}).get("kind") in policies for r in rows):
            return  # inert for old histories and already closed settings audits
        with LocalMatchWriterLock(session.store.match_dir / ".settings_audit.lock", session.match_id), session.store.writer_lock():
            # Re-read under both guards: another reader may have closed the gap,
            # or a writer may have completed between the initial scan and lock.
            rows = _read_jsonl(session.controller_journal_path)
            session._controller_record_sequence = len(rows)
            closed = {r["transaction_id"] for r in rows if r["record_type"] in {"CONTROLLER_COMMIT", "CONTROLLER_ABORT"}}
            pending = [r for r in rows if r["record_type"] == "CONTROLLER_PREPARE"
                       and r["transaction_id"] not in closed and (r.get("settings_policy") or {}).get("kind") in policies]
            records, _ = session.store.scan_journal(recover_trailing_partial=False)
            for row in pending:
                end = next((r for r in reversed(records) if r.get("transaction_id") == row["transaction_id"]
                            and r["record_type"] in {"COMMIT", "ABORT"}), None)
                start = next((r for r in records if r.get("transaction_id") == row["transaction_id"]
                              and r["record_type"] == "PREPARE"), None)
                if end and start and start["candidate_binding"] == row["settings_policy"]:
                    session._append_controller_record({"record_type": "CONTROLLER_" + end["record_type"],
                        "transaction_id": row["transaction_id"], "reaction_decision_records": [],
                        "recovered_from_mechanical_record": True})

    def load_match(self, match_id: str, *, recover: bool = True, rebuild_manifest: bool = True) -> Gate4PersistentSession:
        """Load saved data under the current typed controller interfaces.

        Gate 3 validates saved data and journal integrity. Source-file and policy
        edits require no approval; incomplete AI decisions still must reproduce
        their recorded intent and explanation before recovery can commit them.
        """
        # Reject malformed controller records before mechanical recovery writes.
        _read_controller_journal(
            Gate3MatchStore(self.userdata_root, match_id).match_dir / "ControllerJournal.ndjson"
        )
        # The inherited load uses this class's _engine_from_loaded override.
        base = super().load_match(
            match_id,
            recover=recover,
            rebuild_manifest=rebuild_manifest,
        )
        if not isinstance(base.engine, Gate4ControllerEngine):
            base.engine = self._upgrade_engine(base.engine)
        # The grid is rebuilt from the map on load; walls raised in the fight come back from its zones (owner
        # 2026-09-27, combat/zones.py sync_walls).
        from .zones import sync_walls

        sync_walls(base.engine)
        session = Gate4PersistentSession(self, base)
        if recover:
            self._reconcile_settings_audit(session)
        return session
