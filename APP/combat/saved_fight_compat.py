"""Explicit, copy-on-migrate saved fights. Ordinary Gate 3/4 locks stay strict.

Inspection never calls load_match: that method can recover journals and write
manifests. A continuation is published only after its untouched source has a
verified backup and the staged new save passes the ordinary current loader.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes, canonical_sha256, sha256_file
from .gate2_runtime_models import ActionIntent, CombatEvent, MatchState, ReactionDecision
from .gate3_models import Gate3Genesis, REDUCER_VERSION
from .gate3_reducer import canonical_state_sha256
from .gate3_storage import (
    ENGINE_VERSION, Gate3MatchStore, _match_lock_deterministic_hash,
    _utc_display, atomic_write_bytes,
)
from .gate4_persistence import Gate4Persistence, _read_jsonl, CONTROLLER_JOURNAL_SCHEMA
from .historical_match_compat import HISTORICAL_MATCH_ID
from .read_queries import candidate_pass
from .targeting import LEGACY_POLICY, POLICY_KEYS


VERSION_FILE = "EngineVersion.json"
RECEIPT_FILE = "SavedFightCompatibility.json"


class CompatibilityError(ValueError):
    pass


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise CompatibilityError(reason)


@lru_cache(maxsize=1)
def predecessor_targeting_fingerprints():
    """Release policies identified by executable engine bytes, never fight IDs."""
    return _json(Path(__file__).parent / 'rules' / 'saved_targeting_policies.json')


def saved_targeting_policy(events, *, lock=None):
    """Unstamped predecessor policy, or the last saved general policy binding.

    Genesis events are part of the existing hashed immutable authority. A
    continuation binds its inherited settings in SAVED_FIGHT_CONTINUED, which
    takes precedence over the original genesis without rewriting old history.
    """
    for event in reversed(events):
        row = event.model_dump(mode='json') if hasattr(event, 'model_dump') else event
        if row['event_type'] in {'MATCH_CREATED', 'SAVED_FIGHT_CONTINUED'}:
            policy = row.get('payload', {}).get('targeting_policy')
            if policy is not None:
                _require(isinstance(policy, dict) and set(policy) == set(POLICY_KEYS)
                         and all(type(policy[key]) is int and 0 <= policy[key] <= 100 for key in POLICY_KEYS),
                         'The saved targeting rules are invalid.')
                return dict(policy)
    fingerprint = next((row['sha256'] for row in (lock or {}).get('content_identities', ())
                        if row.get('authority_scope', 'SOURCE') == 'SOURCE'
                        and row.get('relative_path') == 'combat/gate2_engine.py'), None)
    releases = predecessor_targeting_fingerprints()
    if fingerprint in releases['pre_concealment']:
        return {key: 0 for key in POLICY_KEYS}
    _require(fingerprint in releases['percentile_concealment'],
             'The saved targeting rules are unknown. Keep the original fight; this app needs support for its saved version before reopening.')
    return dict(LEGACY_POLICY)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_bytes(value) + b"\n")


def inventory(directory: Path) -> dict[str, str]:
    """Hash all save bytes, including auxiliary authorities; reject escaping links."""
    rows = {}
    for path in sorted(directory.rglob("*")):
        _require(not path.is_symlink(), "A saved-fight file is a symbolic link.")
        if path.is_file():
            rows[path.relative_to(directory).as_posix()] = sha256_file(path)
        else:
            _require(path.is_dir(), "A saved-fight entry is not a regular file or directory.")
    return rows


@contextmanager
def _read_lock(store: Gate3MatchStore):
    """Use the same OS lock as writers without altering even its metadata bytes."""
    _require(not store.lock_path.is_symlink(), "The saved-fight writer lock is a symbolic link.")
    with store.lock_path.open("rb") as handle:
        try:
            if os.name == "nt":  # pragma: no cover - native Windows required
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBRLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CompatibilityError("The fight is being saved; try again after the writer finishes.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":  # pragma: no cover
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def engine_version(lock: dict, controller: dict) -> dict:
    binding = {
        "content_identities": [r for r in lock["content_identities"] if r.get("authority_scope", "SOURCE") == "SOURCE"],
        "controller_lock": controller,
    }
    return {"schema": "TianxiaSavedFightEngine.v1", "engine_version": lock["engine_version"],
            "binding_sha256": canonical_sha256(binding), "binding": binding}


def record_engine_version(store: Gate3MatchStore) -> None:
    """Only called during creation; never implicitly stamps an older save."""
    version = engine_version(_json(store.match_lock_path), _json(store.match_dir / "ControllerLock.json"))
    path = store.match_dir / VERSION_FILE
    if path.exists():
        _require(_json(path) == version, "The saved engine-version record does not match its locks.")
    else:
        _write(path, version)


class _InspectionPersistence(Gate4Persistence):
    """An event reader, never a relaxed executable session loader."""

    def load_match(self, *args, **kwargs):
        raise RuntimeError("Compatibility inspection cannot open executable sessions.")

    def _validate_content(self, lock):
        _require(lock.reducer_version == REDUCER_VERSION, "The saved reducer schema is unsupported.")
        store = Gate3MatchStore(self.userdata_root, lock.match_id)
        expected = {r.relative_path for r in self._content_identity_rows()}
        bound = {r.relative_path for r in lock.content_identities if r.authority_scope == "SOURCE"}
        _require(expected.issubset(bound), "The save is missing required content identities.")
        _require(len({(r.authority_scope, r.relative_path) for r in lock.content_identities}) == len(lock.content_identities),
                 "The save contains duplicate content identities.")
        for row in lock.content_identities:
            relative = Path(row.relative_path or "")
            _require(row.relative_path is not None and not relative.is_absolute() and ".." not in relative.parts,
                     "The save contains an unsafe content path.")
            _require(bool(re.fullmatch(r"[a-f0-9]{64}", row.sha256)), "A saved content hash is malformed.")
            root = store.match_dir if row.authority_scope == "MATCH" else self.source_root
            path = root / relative
            _require(path.is_file(), f"Required saved content is missing: {relative}")
            # Only executable source may change. Data and MATCH-scoped inputs must
            # retain their exact identities; this is not an unbound content import.
            if row.authority_scope == "MATCH" or not (relative.parts[0] == "combat" and relative.suffix == ".py"):
                _require(sha256_file(path) == row.sha256, f"Saved content differs: {relative}")


class SavedFightCompatibility:
    def __init__(self, persistence: Gate4Persistence):
        self.persistence = persistence
        self.reader = _InspectionPersistence(persistence.source_root, persistence.userdata_root)

    def _inspection_key(self, store):
        """Full byte identities, not mtimes or a state-version-only shortcut.

        Include unlocked helpers/plug-ins and rule data as well as the ordinary
        immutable engine binding. Inspection depends on these files although
        they are deliberately outside saved-fight locks. Never persist this
        memo or reuse it for continuation publication.
        """
        root = self.persistence.source_root.resolve()
        data_root = self.persistence.userdata_root.resolve()
        nested_data = data_root != root and data_root.is_relative_to(root)
        # Combat plug-ins also consult typed authority and import helpers from
        # other runtime packages. Bind all runtime Python/JSON inputs rather
        # than assuming the saved locks cover their transitive dependencies.
        # Portable/default installations keep data under the app directory;
        # another fight's saves are not executable source. This fight's entire
        # inventory is independently bound below, including MATCH authorities.
        inputs = {path.relative_to(root).as_posix(): sha256_file(path)
                  for path in sorted(root.rglob('*'))
                  if path.is_file() and path.suffix in {'.py', '.json'}
                  and path.relative_to(root).parts[0] != 'tests'
                  and not (nested_data and path.is_relative_to(data_root))}
        return (str(store.match_dir.resolve()),
                canonical_sha256(inventory(store.match_dir)),
                canonical_sha256(self._current_version()), canonical_sha256(inputs))

    def _current_version(self):
        lock = {"engine_version": ENGINE_VERSION,
                "content_identities": [r.model_dump(mode="json") for r in self.persistence._content_identity_rows()]}
        return engine_version(lock, self.persistence._controller_lock_document())

    def _controller(self, store):
        saved = _json(store.match_dir / "ControllerLock.json")
        current = self.persistence._controller_lock_document()
        for key in ("schema", "controller_id", "controller_version"):
            _require(saved.get(key) == current[key], f"Unsupported controller {key}.")
        for key in ("interface_files", "policy_sha256"):
            _require(isinstance(saved.get(key), dict) and set(current[key]).issubset(saved[key]),
                     "The saved controller authority is incomplete.")
            _require(all(isinstance(v, str) and re.fullmatch(r"[a-f0-9]{64}", v) for v in saved[key].values()),
                     "A saved controller hash is malformed.")
        return saved, current

    def _replay_current(self, genesis, records, store, expected_state):
        """Re-execute recorded choices, not just their old outcome events."""
        engine = self.persistence._engine_from_loaded(
            genesis.state, list(genesis.initial_events), list(genesis.initial_rolls),
            commanded_cui_this_turn=genesis.commanded_cui_this_turn)
        # Unstamped policies derive from the locked executable fingerprint:
        # pre-concealment engines use zero; percentile-era engines use 20/50.
        # Stamped saves carry their configured settings, not today's data.
        engine._saved_targeting_policy = saved_targeting_policy(
            genesis.initial_events, lock=_json(store.match_lock_path))
        engine._replaying_legacy_target_label = not any(
            (e.payload if hasattr(e, 'payload') else e.get('payload', {})).get('targeting_policy') is not None
            for e in genesis.initial_events)
        metadata = _json(store.match_dir / "FactoryIntegration.json") if (store.match_dir / "FactoryIntegration.json").is_file() else {}
        engine.typed_control_modes = dict(metadata.get("participant_control_modes") or {})
        controllers = {r["transaction_id"]: r for r in _read_jsonl(store.match_dir / "ControllerJournal.ndjson")
                       if r.get("record_type") == "CONTROLLER_COMMIT"}
        prepares = {r["transaction_id"]: r for r in records if r["record_type"] == "PREPARE"}
        count = 0
        for record in records:
            if record["record_type"] != "COMMIT":
                continue
            try:
                intent = ActionIntent.model_validate(record["intent"])
                with candidate_pass(engine):
                    self.persistence._validate_intent_binding(engine, intent, prepares[record["transaction_id"]]["candidate_binding"])
                reactions = iter(controllers.get(record["transaction_id"], {}).get("reaction_decision_records", []))

                def reaction(request):
                    row = next(reactions, None)
                    _require(row is not None and row.get("selected_reaction") is not None,
                             "A current reaction has no recorded choice.")
                    return ReactionDecision.model_validate(row["selected_reaction"]), row

                engine.set_reaction_provider(reaction)
                start = len(engine.rolls)
                self.persistence.execute_recorded_intent(
                    engine, intent, prepares[record["transaction_id"]]["candidate_binding"])
                _require(next(reactions, None) is None, "The current engine did not consume a recorded reaction.")
                _require(canonical_state_sha256(engine.state) == record["post_state_sha256"],
                         "The current engine produced a different committed state.")
                _require([r.model_dump(mode="json") for r in engine.rolls[start:]] == record["rolls"],
                         "The current engine produced different rolls.")
                count += 1
            except Exception as exc:
                return {"status": "DIVERGED", "matched_commits": count,
                        "record_sequence": record["record_sequence"], "reason": str(exc)[:500]}
        _require(canonical_state_sha256(engine.state) == canonical_state_sha256(expected_state),
                 "The replay does not equal the saved state.")
        return {"status": "MATCHED", "matched_commits": count}

    def _inspect(self, store):
        _require(store.match_id != HISTORICAL_MATCH_ID,
                 "The sealed historical completed fight must retain its exact read-only authority.")
        current_version = self._current_version()
        files = inventory(store.match_dir)
        controller, _ = self._controller(store)
        lock, genesis = self.reader._load_lock_genesis(store)
        old_version = engine_version(_json(store.match_lock_path), controller)
        if VERSION_FILE in files:
            _require(_json(store.match_dir / VERSION_FILE) == old_version, "The saved engine-version record is inconsistent.")
        records, _ = store.scan_journal(recover_trailing_partial=False)
        self.reader._validate_record_transactions(records)
        _require(not records or records[-1]["record_type"] != "PREPARE",
                 "The old engine has an unfinished action; recover that action before migration.")
        open_controller = set()
        for index, row in enumerate(_read_jsonl(store.match_dir / "ControllerJournal.ndjson"), 1):
            _require(row.get("schema") == CONTROLLER_JOURNAL_SCHEMA and row.get("record_sequence") == index,
                     "The controller journal has an invalid schema or sequence.")
            transaction = row.get("transaction_id")
            if row.get("record_type") == "CONTROLLER_PREPARE":
                _require(isinstance(transaction, str) and transaction not in open_controller,
                         "The controller journal has an invalid prepare.")
                open_controller.add(transaction)
            else:
                _require(row.get("record_type") in {"CONTROLLER_COMMIT", "CONTROLLER_ABORT"}
                         and transaction in open_controller, "The controller journal has an invalid commit or abort.")
                open_controller.remove(transaction)
        _require(not open_controller, "The old engine has an unfinished controller action; recover it before migration.")
        commits = [r for r in records if r["record_type"] == "COMMIT"]
        events, rolls = list(genesis.initial_events), list(genesis.initial_rolls)
        commanded = genesis.commanded_cui_this_turn
        boundary = 0
        try:
            history = self.reader.history_boundaries(store.match_id)
            state = MatchState.model_validate(history["boundaries"][-1]["state"])
            boundary = commits[-1]["record_sequence"] if commits else 0
            replay = self._replay_current(genesis, records, store, state)
            saved_state_source = "JOURNAL_HEAD"
        except CompatibilityError:
            raise
        except Exception as exc:
            # A reducer change can also diverge. Only a snapshot that independently
            # binds a committed state is eligible, with rollback disclosed to the UI.
            snapshots, _ = store.valid_snapshots(records)
            valid = [s for s in snapshots if s.journal_record_sequence == 0 and s.canonical_state_sha256 == genesis.canonical_state_sha256
                     or any(r["record_sequence"] == s.journal_record_sequence and r["post_state_sha256"] == s.canonical_state_sha256 for r in commits)]
            _require(bool(valid), "Saved events cannot be replayed and no intact committed snapshot is available.")
            snapshot = max(valid, key=lambda s: s.journal_record_sequence)
            state, boundary, commanded = snapshot.state, snapshot.journal_record_sequence, snapshot.commanded_cui_this_turn
            replay = {"status": "DIVERGED", "matched_commits": 0, "reason": str(exc)[:500]}
            saved_state_source = "SNAPSHOT"
        for record in commits:
            if record["record_sequence"] > boundary:
                break
            events.extend(record["events"])
            rolls.extend(record["rolls"])
            if record["events"]:
                control = record["events"][-1].get("payload", {}).get("gate3_runtime_control_after")
                if control is not None:
                    commanded = bool(control["commanded_cui_this_turn"])
        _require(state.pending_resolution is None, "A pending resolution cannot cross engine versions.")
        _require(state.match_id == store.match_id, "The saved state belongs to another fight.")
        # Constructing the current engine proves that the saved roster/map can be
        # loaded. It does not prove that future choices will behave identically.
        probe = self.persistence._engine_from_loaded(state, events, rolls, commanded_cui_this_turn=commanded)
        from .zones import sync_walls
        sync_walls(probe)
        _require(current_version == self._current_version(), "The engine changed during inspection; inspect the fight again.")
        _require(inventory(store.match_dir) == files, "The saved fight changed during inspection; inspect it again.")
        report = {
            "match_id": store.match_id, "replay": replay, "saved_state_source": saved_state_source,
            "state_version": state.state_version, "record_sequence": boundary,
            "later_commits": sum(r["record_sequence"] > boundary for r in commits),
            "saved_state_sha256": canonical_state_sha256(state),
            "source_engine": old_version["binding_sha256"], "current_engine": current_version["binding_sha256"],
            "source_files_sha256": canonical_sha256(files), "original_preserved": True,
            "mode": "REPLAY_MATCHED" if replay["status"] == "MATCHED" else "CONTINUE_SAVED_STATE",
            "targeting_policy": saved_targeting_policy(events, lock=lock.model_dump(mode='json')),
        }
        report["token"] = canonical_sha256(report)
        return report, (files, lock, state, events, rolls, commanded)

    def inspect(self, match_id):
        store = Gate3MatchStore(self.persistence.userdata_root, match_id)
        with _read_lock(store):
            key = self._inspection_key(store)
            # Services create a fresh inspector for each request; keep only
            # reports on their shared persistence, bounded to sixteen saves.
            guard, cache = self.persistence.__dict__.setdefault(
                '_saved_fight_inspections', (threading.Lock(), OrderedDict()))
            with guard:
                cached = cache.get(key)
                if cached is not None:
                    cache.move_to_end(key)
                    cached = deepcopy(cached)
            if cached is not None:
                _require(key == self._inspection_key(store),
                         'The save or engine changed during inspection; inspect the fight again.')
                return cached
            report = self._inspect(store)[0]
            _require(key == self._inspection_key(store),
                     'The save or engine changed during inspection; inspect the fight again.')
            with guard:
                cache[key] = deepcopy(report)
                while len(cache) > 16:
                    cache.popitem(last=False)
            return report

    def continue_fight(self, match_id: str, *, token: str, mode: str) -> str:
        store = Gate3MatchStore(self.persistence.userdata_root, match_id)
        with _read_lock(store):
            report, material = self._inspect(store)
            _require(token == report["token"], "The save or engine changed; inspect the fight again before continuing.")
            _require(mode == report["mode"], "Continuing a divergent fight requires the explicit saved-state choice.")
            files, lock, state, events, rolls, commanded = material
            new_id = "match:" + canonical_sha256({"source": match_id, "token": token, "mode": mode})[:24]
            destination = Gate3MatchStore(self.persistence.userdata_root, new_id)
            if destination.match_dir.exists():
                receipt = _json(destination.match_dir / RECEIPT_FILE)
                _require(receipt.get("token") == token, "The continuation identity already exists with different provenance.")
                self.persistence.load_match(new_id, recover=False)
                return new_id
            combat_root = store.matches_root.parent
            backup = combat_root / "CompatibilityBackups" / store.match_dir.name / report["source_files_sha256"]
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                stage = Path(tempfile.mkdtemp(prefix=".backup-", dir=backup.parent))
                try:
                    shutil.copytree(store.match_dir, stage / "save")
                    _require(inventory(stage / "save") == files, "The backup differs from the original save.")
                    self._sync_tree(stage)
                    os.rename(stage / "save", backup)
                    self._sync_dir(backup.parent)
                finally:
                    shutil.rmtree(stage)
            _require(inventory(backup) == files, "The existing backup differs from the original save.")
            staging_root = combat_root / "CompatibilityStaging"
            staging_root.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix="continuation-", dir=staging_root))
            try:
                staged_store = Gate3MatchStore(stage, new_id)
                staged_store.ensure_layout()
                # Only runtime inputs and presentation metadata cross over. Old
                # journals, snapshots and controller decisions remain in the backup.
                inputs = {"Typed_Character_Bundles.json", "Arena_Battlefield.json", "FactoryIntegration.json"}
                inputs.update(r.relative_path for r in lock.content_identities if r.authority_scope == "MATCH")
                for relative in inputs:
                    source = store.match_dir / relative
                    if source.is_file():
                        target = staged_store.match_dir / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
                self._write_continuation(staged_store, report, material, backup)
                _require(_json(staged_store.match_dir / VERSION_FILE)["binding_sha256"] == report["current_engine"],
                         "The engine changed during migration; inspect the fight again.")
                staged = Gate4Persistence(self.persistence.source_root, stage).load_match(new_id, recover=False)
                staged.verify()
                _require(inventory(store.match_dir) == files, "The source changed before publication; retry inspection.")
                self._sync_tree(staged_store.match_dir)
                _require(self._current_version()["binding_sha256"] == report["current_engine"],
                         "The engine changed before publication; inspect the fight again.")
                os.rename(staged_store.match_dir, destination.match_dir)
                self._sync_dir(destination.matches_root)
            finally:
                shutil.rmtree(stage)
            return new_id

    def _write_continuation(self, store, report, material, backup):
        files, lock, state, events, rolls, commanded = material
        state = state.model_copy(deep=True)
        state.match_id = store.match_id
        state.event_sequence += 1
        note = ("Reopened under the current engine after every recorded action reproduced its saved state and rolls."
                if report["mode"] == "REPLAY_MATCHED" else
                "Continued from the saved state by explicit choice. Replay under the current engine differed; future outcomes may change.")
        if report["later_commits"]:
            note += f" Restored the last intact snapshot; {report['later_commits']} later actions remain only in the original save."
        note += " The original fight and a verified backup are preserved."
        from .terrain_occlusion import saved_policy
        from .knowledge_policy import KEY as knowledge_key, saved_policy as saved_knowledge_policy
        from .ai_search import KEY as search_key, saved_policy as saved_search_policy
        events = events + [CombatEvent(sequence=state.event_sequence, state_version=state.state_version,
            event_type="SAVED_FIGHT_CONTINUED", source_definition_id="system:saved-fight-compat",
            trigger_or_intent_id="system:saved-fight-compat", transaction_id="system:saved-fight-compat",
            payload={"log": note, "source_match_id": report["match_id"], "mode": report["mode"],
                     "targeting_policy": report["targeting_policy"],
                     "terrain_occlusion_policy": saved_policy(events),
                     knowledge_key: saved_knowledge_policy(events),
                     **({search_key: saved_search_policy(events)} if any(search_key in e.get('payload', {}) for e in events) else {})}).model_dump(mode="json")]
        from .area_knowledge import STAMP, ORIGIN_AUTHORITY, saved_policy, saved_origin_permissions
        # Do not add payload bytes to unstamped predecessor continuations.
        # A stamped fight retains its own rule through repeated continuations.
        if any(STAMP in event.get('payload', {}) for event in events[:-1]):
            events[-1]['payload'][STAMP] = saved_policy(events[:-1])
            if events[-1]['payload'][STAMP] == 1:
                events[-1]['payload'][ORIGIN_AUTHORITY] = saved_origin_permissions(events[:-1])
        genesis = Gate3Genesis(match_id=store.match_id, state=state, initial_events=tuple(events), initial_rolls=tuple(rolls),
            commanded_cui_this_turn=commanded, canonical_state_sha256=canonical_state_sha256(state),
            initial_event_log_sha256=canonical_sha256(events), initial_roll_log_sha256=canonical_sha256(rolls))
        doc = genesis.model_dump(mode="json", by_alias=True)
        bound = lock.model_dump(mode="json", by_alias=True)
        identities = list(self.persistence._content_identity_rows()) + [r for r in lock.content_identities if r.authority_scope == "MATCH"]
        bound.update(match_id=store.match_id, engine_version=ENGINE_VERSION, created_at_display=_utc_display(),
                     initial_roll_counter=state.roll_counter, actor_ids=sorted(state.actors),
                     genesis_state_sha256=genesis.canonical_state_sha256, genesis_payload_sha256=canonical_sha256(doc),
                     content_identities=[r.model_dump(mode="json") for r in identities])
        bound["deterministic_payload_sha256"] = _match_lock_deterministic_hash(bound)
        _write(store.genesis_path, doc)
        _write(store.match_lock_path, bound)
        _write(store.match_dir / "ControllerLock.json", self.persistence._controller_lock_document())
        record_engine_version(store)
        metadata_path = store.match_dir / "FactoryIntegration.json"
        if metadata_path.is_file():
            metadata = _json(metadata_path)
            metadata.update(match_id=store.match_id, display_name=str(metadata.get("display_name", "Fight")) + " — continued",
                            paused=False, local_auto_running=False, created_at=_utc_display(), updated_at=_utc_display())
            for key in ("c3c_creation_key", "c3c_setup_binding", "c3c_setup_binding_sha256", "c3c_preflight_commitment"):
                metadata.pop(key, None)
            _write(metadata_path, metadata)
        _write(store.match_dir / RECEIPT_FILE, {"schema": "TianxiaSavedFightContinuation.v1", **report,
               "continuation_match_id": store.match_id, "backup": str(backup), "source_files": files, "log": note})

    @staticmethod
    def _sync_tree(root):
        for path in root.rglob("*"):
            if path.is_file():
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())
        for path in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
            SavedFightCompatibility._sync_dir(path)
        SavedFightCompatibility._sync_dir(root)

    @staticmethod
    def _sync_dir(path):
        if os.name != "nt":
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
