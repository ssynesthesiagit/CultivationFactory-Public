"""Durable, request-bound persistence for a DCC linear walk.

The route repository owns the append-only event chain and strict compare-and-
swap append.  This module adds only the replaceable walk snapshot and the
small set of typed helpers needed to resume a walk without trusting provider
prose or a stale in-memory state.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

from app.core import Database, FoundryError, canonical_json, sha256_json, utcnow

from .linear_menus import MAX_WALK_STEPS, CommittedState
from .route_persistence import ControllerRoutePersistence


WALK_STARTED = "WALK_STARTED"
MENU_PUBLISHED = "MENU_PUBLISHED"
OPTION_SELECTED = "OPTION_SELECTED"
STEP_COMMITTED = "STEP_COMMITTED"
STEP_AUTOCOMMITTED = "STEP_AUTOCOMMITTED"
STEP_RETRIED = "STEP_RETRIED"
WALK_COMPLETED = "WALK_COMPLETED"
WALK_FAILED = "WALK_FAILED"

WALK_EVENT_TYPES = frozenset(
    {
        WALK_STARTED,
        MENU_PUBLISHED,
        OPTION_SELECTED,
        STEP_COMMITTED,
        STEP_AUTOCOMMITTED,
        STEP_RETRIED,
        WALK_COMPLETED,
        WALK_FAILED,
    }
)

WALK_CEILINGS = {
    "max_steps": MAX_WALK_STEPS,
    "max_options_per_page": 12,
    "max_pages_per_step": 3,
    "per_call_seconds": 180,
    "max_walk_seconds": 45 * 60,
}
WALK_STATE_SCHEMA = "TianxiaFoundry.DccLinearWalkState.v1"
SNAPSHOT_TABLE = "dcc_walk_state"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UNSET = object()


def _error(code: str, message: str, *, details: Any = None, status_code: int = 409) -> None:
    raise FoundryError(code, message, details=details, status_code=status_code)


def _state(value: CommittedState | Mapping[str, Any] | None) -> CommittedState:
    if isinstance(value, CommittedState):
        return value
    if not isinstance(value, Mapping):
        return CommittedState.empty()
    return CommittedState(
        by_slot=value.get("by_slot") or {},
        pairs=value.get("pairs") or (),
        ordinary_by_cl=value.get("ordinary_by_cl") or {},
        insight_occurrences=value.get("insight_occurrences") or (),
        bounded=value.get("bounded") or {},
        route_id=value.get("route_id"),
        committed_sha256=value.get("committed_sha256") or "",
        trained_choices=value.get("trained_choices") or (),
        trained_choice_skips=value.get("trained_choice_skips") or (),
    )


def _digest(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        _error("DCC_LINEAR_PERSISTENCE_INVALID", f"{field} must be a lowercase SHA-256 digest.")
    return value


def state_sha256(value: CommittedState | Mapping[str, Any] | None) -> str:
    """Return the canonical digest of one typed committed state."""

    return _state(value).committed_sha256


def _walk_events(projection: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    events = projection.get("events") if isinstance(projection, Mapping) else None
    if not isinstance(events, (list, tuple)):
        return []
    return [
        event
        for event in events
        if isinstance(event, Mapping) and event.get("event_type") in WALK_EVENT_TYPES
    ]


def _step_events(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        event
        for event in events
        if event.get("event_type") in {STEP_COMMITTED, STEP_AUTOCOMMITTED}
    ]


class LinearWalkPersistence:
    """Snapshot and event helpers over :class:`ControllerRoutePersistence`."""

    snapshot_table = SNAPSHOT_TABLE

    def __init__(self, db: Database, routes: ControllerRoutePersistence | None = None):
        self.db = db
        self.routes = routes or ControllerRoutePersistence(db)

    def projection(self, run_id: str) -> dict[str, Any] | None:
        return self.routes.projection(run_id)

    load_projection = projection

    def events(self, run_id: str) -> list[dict[str, Any]]:
        projection = self.projection(run_id)
        return [deepcopy(dict(event)) for event in _walk_events(projection or {})]

    walk_events = events

    def status_light(self, run_id: str) -> dict[str, Any] | None:
        """Walk status for polling: snapshot row plus a handful of event rows.

        ``status`` loads and verifies the whole event chain (hundreds of
        multi-kilobyte rows) on every call; the guided page polls every few
        seconds and each such call held the interpreter for seconds, starving
        the build thread.  This reads the snapshot row, the WALK_STARTED
        estimate, and the newest events until one names a step.  Same shape
        as ``status``; hash-chain verification stays with ``status``/replay.
        """

        with self.db.connection() as conn:
            snapshot = conn.execute(
                f"SELECT step_ordinal, event_head_sha256 FROM {self.snapshot_table} WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if snapshot is None:
                return None
            count = conn.execute(
                "SELECT COUNT(*) FROM dcc_controller_events WHERE run_id=? AND event_type IN (%s)" % ",".join("?" * len(WALK_EVENT_TYPES)),
                (run_id, *sorted(WALK_EVENT_TYPES)),
            ).fetchone()[0]
            started = conn.execute(
                "SELECT event_json FROM dcc_controller_events WHERE run_id=? AND event_type=? ORDER BY ordinal LIMIT 1",
                (run_id, WALK_STARTED),
            ).fetchone()
            newest = conn.execute(
                "SELECT event_type, event_json FROM dcc_controller_events WHERE run_id=? ORDER BY ordinal DESC LIMIT 12",
                (run_id,),
            ).fetchall()
        estimate = None
        if started is not None:
            try:
                payload = (json.loads(started["event_json"]) or {}).get("payload") or {}
            except (TypeError, ValueError):
                payload = {}
            if type(payload.get("steps_estimate")) is int and payload["steps_estimate"] >= 0:
                estimate = payload["steps_estimate"]
        step_id: str | None = None
        state = "RUNNING"
        for row in newest:
            event_type = row["event_type"]
            if event_type not in WALK_EVENT_TYPES:
                continue
            try:
                payload = (json.loads(row["event_json"]) or {}).get("payload") or {}
            except (TypeError, ValueError):
                payload = {}
            if step_id is None and isinstance(payload.get("step_id"), str):
                step_id = payload["step_id"]
            if event_type == WALK_FAILED:
                state = "NEEDS_REVIEW"
                break
            if event_type == WALK_COMPLETED:
                state = "COMPLETED"
                break
            if step_id is not None:
                break
        return {
            "schema": "TianxiaFoundry.DccLinearWalkStatus.v1",
            "step_ordinal": snapshot["step_ordinal"] or 0,
            "step_id": step_id,
            "steps_estimate": estimate,
            "state": state,
            "event_count": count,
            "event_head_sha256": snapshot["event_head_sha256"],
        }

    def load_snapshot(self, run_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                f"SELECT run_id,step_ordinal,committed_json,committed_sha256,event_head_sha256,updated_at FROM {self.snapshot_table} WHERE run_id=?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        raw = row["committed_json"]
        if not isinstance(raw, str):
            _error("DCC_LINEAR_SNAPSHOT_INVALID", "The walk snapshot is not JSON text.", status_code=500)
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            _error("DCC_LINEAR_SNAPSHOT_INVALID", "The walk snapshot is not valid JSON.", status_code=500)
            raise AssertionError("unreachable") from exc
        if not isinstance(value, Mapping):
            _error("DCC_LINEAR_SNAPSHOT_INVALID", "The walk snapshot must be a typed state object.", status_code=500)
        state = _state(value)
        if (
            row["committed_json"] != canonical_json(state.to_dict())
            or row["committed_sha256"] != state.committed_sha256
            or row["committed_sha256"] != sha256_json(state._unsigned_dict())
            or row["event_head_sha256"] is None
            or not _HEX64.fullmatch(str(row["event_head_sha256"]))
            or type(row["step_ordinal"]) is not int
            or row["step_ordinal"] < 0
        ):
            _error(
                "DCC_LINEAR_SNAPSHOT_INVALID",
                "The walk snapshot digest or metadata does not match its typed state.",
                status_code=409,
            )
        return {
            "schema": WALK_STATE_SCHEMA,
            "run_id": row["run_id"],
            "step_ordinal": row["step_ordinal"],
            "committed": state,
            "committed_json": canonical_json(state.to_dict()),
            "committed_sha256": state.committed_sha256,
            "event_head_sha256": row["event_head_sha256"],
            "updated_at": row["updated_at"],
        }

    load_walk_snapshot = load_snapshot

    def save_snapshot(
        self,
        run_id: str,
        step_ordinal: int,
        committed: CommittedState | Mapping[str, Any] | None,
        event_head_sha256: str,
        *,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(run_id, str) or not run_id.strip():
            _error("DCC_LINEAR_SNAPSHOT_INVALID", "run_id must be a non-empty string.")
        if type(step_ordinal) is not int or step_ordinal < 0:
            _error("DCC_LINEAR_SNAPSHOT_INVALID", "step_ordinal must be a non-negative integer.")
        head = _digest(event_head_sha256, field="event_head_sha256")
        state = _state(committed)
        encoded = canonical_json(state.to_dict())
        timestamp = updated_at or utcnow()
        with self.db.transaction() as conn:
            # The snapshot is intentionally replaceable, while its run binding
            # stays protected by the migration foreign key.
            conn.execute(
                f"""INSERT INTO {self.snapshot_table}(
                    run_id,step_ordinal,committed_json,committed_sha256,event_head_sha256,updated_at
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                    step_ordinal=excluded.step_ordinal,
                    committed_json=excluded.committed_json,
                    committed_sha256=excluded.committed_sha256,
                    event_head_sha256=excluded.event_head_sha256,
                    updated_at=excluded.updated_at""",
                (run_id, step_ordinal, encoded, state.committed_sha256, head, timestamp),
            )
        return {
            "schema": WALK_STATE_SCHEMA,
            "run_id": run_id,
            "step_ordinal": step_ordinal,
            "committed": state,
            "committed_json": encoded,
            "committed_sha256": state.committed_sha256,
            "event_head_sha256": head,
            "updated_at": timestamp,
        }

    save_walk_snapshot = save_snapshot

    def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        subject_sha256: str,
        state_sha256_before: str,
        state_sha256_after: str,
        payload: Mapping[str, Any] | None = None,
        expected_event_head_sha256: str | None | object = _UNSET,
        expected_ordinal: int | object = _UNSET,
        expected_binding_sha256: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if event_type not in WALK_EVENT_TYPES:
            _error("DCC_LINEAR_EVENT_TYPE_INVALID", "Unsupported DCC walk event type.")
        _digest(subject_sha256, field="subject_sha256")
        _digest(state_sha256_before, field="state_sha256_before")
        _digest(state_sha256_after, field="state_sha256_after")
        if expected_event_head_sha256 is _UNSET or expected_ordinal is _UNSET:
            # Resolve exact CAS inputs once.  ControllerRoutePersistence still
            # performs the authoritative compare-and-swap under its write lock.
            projection = self.projection(run_id)
            if projection is None:
                _error("DCC_ROUTE_BINDING_NOT_FOUND", "No DCC controller route is bound to this run.", status_code=404)
            expected_event_head_sha256 = projection["event_head_sha256"]
            expected_ordinal = projection["event_count"] + 1
        return self.routes.append_event(
            run_id,
            event_type=event_type,
            subject_sha256=subject_sha256,
            state_sha256_before=state_sha256_before,
            state_sha256_after=state_sha256_after,
            payload=payload,
            expected_event_head_sha256=expected_event_head_sha256,
            expected_ordinal=expected_ordinal,
            expected_binding_sha256=expected_binding_sha256,
            created_at=created_at,
        )

    append_walk_event = append_event

    def verified_replay(
        self,
        request: Mapping[str, Any] | None,
        envelope: Mapping[str, Any] | None,
        run_id: str,
    ) -> dict[str, Any]:
        projection = self.projection(run_id)
        if projection is None:
            _error("DCC_ROUTE_BINDING_NOT_FOUND", "No DCC controller route is bound to this run.", status_code=404)
        snapshot = self.load_snapshot(run_id)
        if snapshot is None:
            _error("DCC_LINEAR_SNAPSHOT_MISSING", "The DCC walk has no resumable snapshot.", status_code=409)
        walk_events = _walk_events(projection)
        step_events = _step_events(walk_events)
        # Import lazily so the persistence module remains usable while the
        # pure walk module imports menu definitions.
        from .linear_walk import _apply_owner_locks, replay_committed_state

        replayed = replay_committed_state(step_events, request=request, envelope=envelope)
        # Identity is intentionally a bounded descriptive response (name, title,
        # optional one-sentence concept) rather
        # than a canonical option ID, so the pure replay helper leaves it to
        # this persistence boundary where its typed event payload is checked.
        for event in step_events:
            payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            identity = payload.get("identity")
            if isinstance(identity, Mapping):
                name = identity.get("name")
                title = identity.get("title")
                if isinstance(name, str) and isinstance(title, str) and name.strip() and title.strip():
                    concept = identity.get("concept")
                    replayed = replayed.with_identity(name, title, concept if isinstance(concept, str) else None)
        replayed = _apply_owner_locks(request or {}, envelope or {}, replayed)
        from character_creation.constructed_arts.explicit_forging import validate_required_design_selection
        validate_required_design_selection(envelope or {}, replayed.bounded.get("forged_design_ids") or [], complete=replayed.bounded.get("forged_design_done") is True, request=request or {})
        if (
            snapshot["event_head_sha256"] != projection["event_head_sha256"]
            or snapshot["committed_sha256"] != replayed.committed_sha256
            or snapshot["committed"].to_dict() != replayed.to_dict()
            or snapshot["step_ordinal"] < len(step_events)
        ):
            _error(
                "DCC_LINEAR_SNAPSHOT_MISMATCH",
                "The walk snapshot does not match the verified controller event replay.",
                details={
                    "snapshot_event_head_sha256": snapshot["event_head_sha256"],
                    "event_head_sha256": projection["event_head_sha256"],
                    "snapshot_committed_sha256": snapshot["committed_sha256"],
                    "replayed_committed_sha256": replayed.committed_sha256,
                },
                status_code=409,
            )
        return {
            "projection": projection,
            "snapshot": snapshot,
            "state": replayed,
            "events": [deepcopy(dict(event)) for event in projection["events"]],
            "walk_events": [deepcopy(dict(event)) for event in walk_events],
            "step_events": [deepcopy(dict(event)) for event in step_events],
        }

    verify_replay = verified_replay
    verify_walk_replay = verified_replay

    def status(self, run_id: str) -> dict[str, Any] | None:
        projection = self.projection(run_id)
        if projection is None:
            return None
        snapshot = self.load_snapshot(run_id)
        if snapshot is None:
            # The historical route seam may exist without an activated walk;
            # keep its status byte-compatible until WALK_STARTED is durable.
            return None
        walk_events = _walk_events(projection)
        step_id: str | None = None
        state = "RUNNING"
        for event in reversed(walk_events):
            payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            if isinstance(payload.get("step_id"), str):
                step_id = payload["step_id"]
            if event.get("event_type") == WALK_FAILED:
                state = "NEEDS_REVIEW"
                break
            if event.get("event_type") == WALK_COMPLETED:
                state = "COMPLETED"
                break
        return {
            "schema": "TianxiaFoundry.DccLinearWalkStatus.v1",
            "step_ordinal": snapshot["step_ordinal"] if snapshot else 0,
            "step_id": step_id,
            "steps_estimate": self._steps_estimate(walk_events),
            "state": state,
            "event_count": len(walk_events),
            "event_head_sha256": projection["event_head_sha256"],
        }

    walk_status = status

    @staticmethod
    def _steps_estimate(events: Sequence[Mapping[str, Any]]) -> int | None:
        for event in events:
            if event.get("event_type") == WALK_STARTED:
                payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
                estimate = payload.get("steps_estimate")
                if type(estimate) is int and estimate >= 0:
                    return estimate
        return None


DccLinearWalkPersistence = LinearWalkPersistence
DccWalkPersistence = LinearWalkPersistence


def load_walk_snapshot(db: Database, run_id: str) -> dict[str, Any] | None:
    return LinearWalkPersistence(db).load_snapshot(run_id)


def save_walk_snapshot(
    db: Database,
    run_id: str,
    step_ordinal: int,
    committed: CommittedState | Mapping[str, Any] | None,
    event_head_sha256: str,
) -> dict[str, Any]:
    return LinearWalkPersistence(db).save_snapshot(
        run_id,
        step_ordinal,
        committed,
        event_head_sha256,
    )


def verify_walk_replay(
    db: Database,
    request: Mapping[str, Any] | None,
    envelope: Mapping[str, Any] | None,
    run_id: str,
) -> dict[str, Any]:
    return LinearWalkPersistence(db).verified_replay(request, envelope, run_id)


__all__ = [
    "WALK_STARTED",
    "MENU_PUBLISHED",
    "OPTION_SELECTED",
    "STEP_COMMITTED",
    "STEP_AUTOCOMMITTED",
    "STEP_RETRIED",
    "WALK_COMPLETED",
    "WALK_FAILED",
    "WALK_EVENT_TYPES",
    "WALK_CEILINGS",
    "WALK_STATE_SCHEMA",
    "state_sha256",
    "LinearWalkPersistence",
    "DccLinearWalkPersistence",
    "DccWalkPersistence",
    "load_walk_snapshot",
    "save_walk_snapshot",
    "verify_walk_replay",
]
