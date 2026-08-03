from __future__ import annotations

import datetime as dt
import json
import secrets
import time
import uuid
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from app.core import Database, FoundryError, canonical_json, sha256_bytes, sha256_json
from security.clock_authority import (
    ProcessEpoch,
    ProcessEpochProvider,
    RuntimeProcessEpochProvider,
)
from security.integrity import IntegrityService
from security.local_identity import LocalPrincipal, PrincipalProvider, ProcessPrincipalProvider

ZERO_HASH = "0" * 64
APPROVAL_EVIDENCE_DOMAIN = "tianxia.foundry.approval_evidence.v2"
T = TypeVar("T")


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _format_time(value: dt.datetime) -> str:
    value = value.astimezone(dt.timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _monotonic_ns(value: float | int) -> int:
    if isinstance(value, bool):
        raise TypeError("A monotonic clock cannot return bool.")
    return int(round(float(value) * 1_000_000_000))


@dataclass(frozen=True)
class _ClockObservation:
    epoch: ProcessEpoch
    wall_now: dt.datetime
    monotonic_now_ns: int
    durable_wall_high_water: dt.datetime
    durable_monotonic_high_water_ns: int
    wall_rollback: bool
    monotonic_rollback: bool


class ApprovalChallengeService:
    """One-time exact-byte approval with external keyed and temporal authority.

    The process epoch is shared across service-object construction. During that
    epoch, monotonic time is the TTL authority. SQLite stores durable wall and
    per-epoch monotonic high-water state so clock reversal and process restart
    fail closed. Challenge consumption, terminal invalidation/expiry, evidence
    creation, and the protected callback remain one ``BEGIN IMMEDIATE``
    transaction.
    """

    def __init__(
        self,
        db: Database,
        principal_provider: PrincipalProvider | None = None,
        integrity: IntegrityService | None = None,
        *,
        clock: Callable[[], dt.datetime] | None = None,
        monotonic_clock: Callable[[], float | int] | None = None,
        process_epoch_provider: ProcessEpochProvider | None = None,
    ):
        self.db = db
        self.principal_provider = principal_provider or ProcessPrincipalProvider()
        self.integrity = integrity or IntegrityService.for_database(db)
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.process_epoch_provider = process_epoch_provider or RuntimeProcessEpochProvider()

        if monotonic_clock is not None:
            self._monotonic_clock = monotonic_clock
        elif clock is not None:
            # Backward-compatible deterministic seam for older R3/R4 tests and
            # the sealed rereview reproducer. Production never uses wall time as
            # monotonic authority: this path exists only when a wall clock is
            # explicitly injected. A rollback therefore produces a decreasing
            # derived value and fails closed.
            origin = self._normalized_wall(self._clock())
            self._monotonic_clock = lambda: (self._normalized_wall(self._clock()) - origin).total_seconds()
        else:
            self._monotonic_clock = time.monotonic

    @staticmethod
    def _normalized_wall(value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)

    def principal(self) -> LocalPrincipal:
        return self.principal_provider.current_principal()

    def _now(self) -> dt.datetime:
        deterministic = os.environ.get("TIANXIA_DETERMINISTIC_UTC")
        if deterministic and os.environ.get("TIANXIA_DETERMINISTIC_APPROVAL_SEED"):
            return _parse_time(deterministic)
        return self._normalized_wall(self._clock())

    def _monotonic_now_ns(self) -> int:
        seed = os.environ.get("TIANXIA_DETERMINISTIC_APPROVAL_SEED")
        if seed:
            return int(sha256_bytes(seed.encode("utf-8"))[:15], 16)
        return _monotonic_ns(self._monotonic_clock())

    def _epoch(self) -> ProcessEpoch:
        epoch = self.process_epoch_provider.current_epoch()
        if not epoch.epoch_id or not isinstance(epoch.process_id, int):
            raise FoundryError(
                "APPROVAL_PROCESS_EPOCH_INVALID",
                "The process epoch provider returned an invalid authority identity.",
                status_code=500,
            )
        return epoch

    @staticmethod
    def _binding(
        exact_bytes: bytes,
        binding: dict[str, Any] | None,
        project_lock_hash: str | None,
    ) -> tuple[str, str, str]:
        return (
            sha256_bytes(exact_bytes),
            sha256_json(binding or {}),
            project_lock_hash or ZERO_HASH,
        )

    def _observe_clock(self, conn: Any) -> _ClockObservation:
        wall_now = self._now()
        wall_text = _format_time(wall_now)
        monotonic_now_ns = self._monotonic_now_ns()
        epoch = self._epoch()

        authority = conn.execute(
            "SELECT * FROM approval_clock_authority_state WHERE singleton_id=1"
        ).fetchone()
        if authority is None:
            durable_wall = wall_now
            wall_rollback = False
            conn.execute(
                """INSERT INTO approval_clock_authority_state(
                   singleton_id,wall_high_water_at,last_process_epoch_id,updated_at)
                   VALUES(1,?,?,?)""",
                (wall_text, epoch.epoch_id, wall_text),
            )
        else:
            durable_wall = _parse_time(authority["wall_high_water_at"])
            wall_rollback = wall_now < durable_wall
            if wall_now > durable_wall:
                durable_wall = wall_now
                conn.execute(
                    """UPDATE approval_clock_authority_state
                       SET wall_high_water_at=?,last_process_epoch_id=?,updated_at=?
                       WHERE singleton_id=1""",
                    (wall_text, epoch.epoch_id, wall_text),
                )
            elif not wall_rollback:
                conn.execute(
                    """UPDATE approval_clock_authority_state
                       SET last_process_epoch_id=?,updated_at=? WHERE singleton_id=1""",
                    (epoch.epoch_id, wall_text),
                )

        epoch_row = conn.execute(
            "SELECT * FROM approval_process_epochs WHERE process_epoch_id=?",
            (epoch.epoch_id,),
        ).fetchone()
        if epoch_row is None:
            durable_monotonic = monotonic_now_ns
            monotonic_rollback = False
            conn.execute(
                """INSERT INTO approval_process_epochs(
                   process_epoch_id,process_id,first_seen_wall_at,first_seen_monotonic_ns,
                   monotonic_high_water_ns,last_seen_wall_at,last_seen_monotonic_ns,registered_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    epoch.epoch_id,
                    epoch.process_id,
                    wall_text,
                    monotonic_now_ns,
                    monotonic_now_ns,
                    wall_text,
                    monotonic_now_ns,
                    wall_text,
                ),
            )
        else:
            if int(epoch_row["process_id"]) != epoch.process_id:
                raise FoundryError(
                    "APPROVAL_PROCESS_EPOCH_COLLISION",
                    "The process epoch ID is already bound to a different process identity.",
                    details={"process_epoch_id": epoch.epoch_id},
                    status_code=500,
                )
            durable_monotonic = int(epoch_row["monotonic_high_water_ns"])
            monotonic_rollback = monotonic_now_ns < durable_monotonic
            new_high = max(durable_monotonic, monotonic_now_ns)
            conn.execute(
                """UPDATE approval_process_epochs
                   SET monotonic_high_water_ns=?,last_seen_wall_at=?,last_seen_monotonic_ns=?
                   WHERE process_epoch_id=?""",
                (new_high, wall_text, monotonic_now_ns, epoch.epoch_id),
            )
            durable_monotonic = new_high

        return _ClockObservation(
            epoch=epoch,
            wall_now=wall_now,
            monotonic_now_ns=monotonic_now_ns,
            durable_wall_high_water=durable_wall,
            durable_monotonic_high_water_ns=durable_monotonic,
            wall_rollback=wall_rollback,
            monotonic_rollback=monotonic_rollback,
        )

    @staticmethod
    def _challenge_core(row: Any) -> dict[str, Any]:
        try:
            core = json.loads(row["challenge_json"])
        except Exception as exc:
            raise FoundryError(
                "APPROVAL_CHALLENGE_CANONICAL_BYTES_INVALID",
                "The persisted approval challenge JSON is malformed.",
                details={"challenge_id": row["challenge_id"], "error": type(exc).__name__},
                status_code=409,
            ) from exc
        if not isinstance(core, dict) or canonical_json(core) != row["challenge_json"]:
            raise FoundryError(
                "APPROVAL_CHALLENGE_CANONICAL_BYTES_INVALID",
                "The persisted approval challenge is not its canonical byte representation.",
                details={"challenge_id": row["challenge_id"]},
                status_code=409,
            )
        schema = core.get("schema_version")
        if schema not in {
            "TianxiaFoundry.ExactApprovalChallenge.v1",
            "TianxiaFoundry.ExactApprovalChallenge.v2",
        }:
            raise FoundryError(
                "APPROVAL_CHALLENGE_SCHEMA_UNSUPPORTED",
                "The persisted approval challenge uses an unsupported schema.",
                details={"schema_version": schema},
                status_code=409,
            )
        expected = {
            "challenge_id": row["challenge_id"],
            "operation": row["operation"],
            "subject_type": row["subject_type"],
            "subject_id": row["subject_id"],
            "exact_bytes_hash": row["exact_bytes_hash"],
            "binding_hash": row["binding_hash"],
            "project_lock_hash": row["project_lock_hash"],
            "issued_at": row["issued_at"],
            "expires_at": row["expires_at"],
            "nonce_hash": row["nonce_hash"],
        }
        principal = core.get("principal", {})
        if principal.get("principal_id") != row["principal_id"] or sha256_json(principal) != row["principal_hash"]:
            raise FoundryError(
                "APPROVAL_CHALLENGE_PRINCIPAL_EVIDENCE_MISMATCH",
                "The challenge principal fields differ from the persisted authority columns.",
                status_code=409,
            )
        for key, value in expected.items():
            if core.get(key) != value:
                raise FoundryError(
                    "APPROVAL_CHALLENGE_EVIDENCE_MISMATCH",
                    "The canonical challenge bytes differ from persisted challenge columns.",
                    details={"field": key, "challenge_id": row["challenge_id"]},
                    status_code=409,
                )
        if schema.endswith(".v2"):
            clock_authority = core.get("clock_authority") or {}
            expected_clock = {
                "process_epoch_id": row["process_epoch_id"],
                "issued_monotonic_ns": row["issued_monotonic_ns"],
                "deadline_monotonic_ns": row["deadline_monotonic_ns"],
            }
            if clock_authority != expected_clock:
                raise FoundryError(
                    "APPROVAL_CHALLENGE_CLOCK_AUTHORITY_MISMATCH",
                    "The canonical challenge clock authority differs from persisted columns.",
                    status_code=409,
                )
            if not row["process_epoch_id"] or row["issued_monotonic_ns"] is None or row["deadline_monotonic_ns"] is None:
                raise FoundryError(
                    "APPROVAL_CHALLENGE_CLOCK_AUTHORITY_MISSING",
                    "The R5 challenge clock authority is incomplete.",
                    status_code=409,
                )
            if int(row["deadline_monotonic_ns"]) <= int(row["issued_monotonic_ns"]):
                raise FoundryError(
                    "APPROVAL_CHALLENGE_CLOCK_INTERVAL_INVALID",
                    "The challenge monotonic deadline is not after issuance.",
                    status_code=409,
                )
        elif any(
            row[name] is not None
            for name in ("process_epoch_id", "issued_monotonic_ns", "deadline_monotonic_ns")
        ):
            raise FoundryError(
                "APPROVAL_CHALLENGE_LEGACY_CLOCK_FIELDS_INVALID",
                "A legacy challenge unexpectedly contains partial R5 clock authority.",
                status_code=409,
            )
        if sha256_json(core) != row["challenge_hash"]:
            raise FoundryError(
                "APPROVAL_CHALLENGE_HASH_MISMATCH",
                "The challenge hash does not match its canonical bytes.",
                status_code=409,
            )
        return core

    def issue(
        self,
        *,
        operation: str,
        subject_type: str,
        subject_id: str,
        exact_bytes: bytes,
        binding: dict[str, Any] | None = None,
        project_lock_hash: str | None = None,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        if ttl_seconds < 1 or ttl_seconds > 900:
            raise FoundryError(
                "APPROVAL_CHALLENGE_TTL_INVALID",
                "Challenge TTL must be between 1 and 900 seconds.",
            )
        principal = self.principal()
        exact_hash, binding_hash, lock_hash = self._binding(exact_bytes, binding, project_lock_hash)
        deterministic_seed = os.environ.get("TIANXIA_DETERMINISTIC_APPROVAL_SEED")
        deterministic_material = canonical_json({
            "seed": deterministic_seed,
            "operation": operation,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "exact_hash": exact_hash,
            "binding_hash": binding_hash,
            "lock_hash": lock_hash,
        })
        nonce = sha256_bytes(deterministic_material.encode("utf-8")) if deterministic_seed else secrets.token_urlsafe(32)
        nonce_hash = sha256_bytes(nonce.encode("utf-8"))
        challenge_id = (
            str(uuid.uuid5(uuid.NAMESPACE_URL, "tianxia-scratch-approval:" + deterministic_material))
            if deterministic_seed else str(uuid.uuid4())
        )
        with self.db.transaction() as conn:
            observation = self._observe_clock(conn)
            if observation.wall_rollback or observation.monotonic_rollback:
                raise FoundryError(
                    "APPROVAL_CLOCK_AUTHORITY_ROLLBACK",
                    "Clock authority moved backward; a challenge cannot be issued.",
                    details={
                        "wall_rollback": observation.wall_rollback,
                        "monotonic_rollback": observation.monotonic_rollback,
                    },
                    status_code=409,
                )
            issued = observation.wall_now
            expires = issued + dt.timedelta(seconds=ttl_seconds)
            deadline_ns = observation.monotonic_now_ns + ttl_seconds * 1_000_000_000
            core = {
                "schema_version": "TianxiaFoundry.ExactApprovalChallenge.v2",
                "challenge_id": challenge_id,
                "principal": principal.as_dict(),
                "operation": operation,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "exact_bytes_hash": exact_hash,
                "binding_hash": binding_hash,
                "project_lock_hash": lock_hash,
                "issued_at": _format_time(issued),
                "expires_at": _format_time(expires),
                "nonce_hash": nonce_hash,
                "clock_authority": {
                    "process_epoch_id": observation.epoch.epoch_id,
                    "issued_monotonic_ns": observation.monotonic_now_ns,
                    "deadline_monotonic_ns": deadline_ns,
                },
            }
            challenge_hash = sha256_json(core)
            conn.execute(
                """INSERT INTO exact_approval_challenges(
                   challenge_id,challenge_hash,principal_id,principal_hash,operation,subject_type,subject_id,
                   exact_bytes_hash,binding_hash,project_lock_hash,nonce_hash,status,issued_at,expires_at,challenge_json,
                   process_epoch_id,issued_monotonic_ns,deadline_monotonic_ns)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    challenge_id,
                    challenge_hash,
                    principal.principal_id,
                    principal.principal_hash,
                    operation,
                    subject_type,
                    subject_id,
                    exact_hash,
                    binding_hash,
                    lock_hash,
                    nonce_hash,
                    "issued",
                    core["issued_at"],
                    core["expires_at"],
                    canonical_json(core),
                    observation.epoch.epoch_id,
                    observation.monotonic_now_ns,
                    deadline_ns,
                ),
            )
        return {"challenge": {**core, "challenge_hash": challenge_hash, "nonce": nonce}}

    def _validate_bindings(
        self,
        row: Any,
        *,
        nonce: str,
        operation: str,
        subject_type: str,
        subject_id: str,
        exact_bytes: bytes,
        binding: dict[str, Any] | None,
        project_lock_hash: str | None,
    ) -> tuple[dict[str, Any], LocalPrincipal, tuple[str, str, str]]:
        core = self._challenge_core(row)
        principal = self.principal()
        if row["principal_id"] != principal.principal_id or row["principal_hash"] != principal.principal_hash:
            raise FoundryError(
                "APPROVAL_CHALLENGE_PRINCIPAL_MISMATCH",
                "The challenge belongs to a different authoritative local principal.",
                status_code=403,
            )
        if row["operation"] != operation or row["subject_type"] != subject_type or row["subject_id"] != subject_id:
            raise FoundryError(
                "APPROVAL_CHALLENGE_SUBJECT_MISMATCH",
                "The challenge is bound to a different operation or subject.",
                status_code=409,
            )
        exact_hash, binding_hash, lock_hash = self._binding(exact_bytes, binding, project_lock_hash)
        if row["exact_bytes_hash"] != exact_hash:
            raise FoundryError(
                "APPROVAL_CHALLENGE_BYTES_CHANGED",
                "The exact bytes changed after challenge issuance.",
                status_code=409,
            )
        if row["binding_hash"] != binding_hash:
            raise FoundryError(
                "APPROVAL_CHALLENGE_BINDING_CHANGED",
                "The approval binding changed after challenge issuance.",
                status_code=409,
            )
        if row["project_lock_hash"] != lock_hash:
            raise FoundryError(
                "APPROVAL_CHALLENGE_PROJECT_LOCK_CHANGED",
                "The project or content lock changed after challenge issuance.",
                status_code=409,
            )
        if row["nonce_hash"] != sha256_bytes(str(nonce).encode("utf-8")):
            raise FoundryError(
                "APPROVAL_CHALLENGE_NONCE_INVALID",
                "The challenge nonce is invalid.",
                status_code=403,
            )
        return core, principal, (exact_hash, binding_hash, lock_hash)

    @staticmethod
    def _terminal_status_error(row: Any) -> FoundryError:
        status = row["status"]
        if status == "expired":
            return FoundryError(
                "APPROVAL_CHALLENGE_EXPIRED",
                "The exact-byte approval challenge expired and is permanently unusable.",
                details={"status": status, "expired_observed_at": row["expired_observed_at"]},
                status_code=409,
            )
        if status == "invalidated":
            return FoundryError(
                "APPROVAL_CHALLENGE_INVALIDATED",
                "The exact-byte approval challenge was durably invalidated.",
                details={
                    "status": status,
                    "invalidated_observed_at": row["invalidated_observed_at"],
                    "reason": row["invalidation_reason"],
                },
                status_code=409,
            )
        return FoundryError(
            "APPROVAL_CHALLENGE_ALREADY_CONSUMED",
            "The exact-byte approval challenge is no longer usable.",
            details={"status": status},
            status_code=409,
        )

    @staticmethod
    def _invalidate(
        conn: Any,
        row: Any,
        observation: _ClockObservation,
        *,
        reason: str,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> FoundryError:
        observed = _format_time(observation.wall_now)
        changed = conn.execute(
            """UPDATE exact_approval_challenges
               SET status='invalidated',invalidated_observed_at=?,invalidation_reason=?
               WHERE challenge_id=? AND status='issued'""",
            (observed, reason, row["challenge_id"]),
        ).rowcount
        if changed != 1:
            raise FoundryError(
                "APPROVAL_CHALLENGE_CONCURRENT_USE",
                "The challenge state changed concurrently.",
                status_code=409,
            )
        return FoundryError(
            code,
            message,
            details={"reason": reason, "observed_at": observed, **(details or {})},
            status_code=409,
        )

    def consume_with_action(
        self,
        *,
        challenge_id: str,
        nonce: str,
        operation: str,
        subject_type: str,
        subject_id: str,
        exact_bytes: bytes,
        binding: dict[str, Any] | None = None,
        project_lock_hash: str | None = None,
        evidence_context: dict[str, Any] | None = None,
        action: Callable[[Any, dict[str, Any]], T] | None = None,
    ) -> tuple[dict[str, Any], T | None]:
        """Consume once and commit the protected action atomically."""

        deferred_error: FoundryError | None = None
        evidence: dict[str, Any] | None = None
        action_result: T | None = None
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM exact_approval_challenges WHERE challenge_id=?",
                (challenge_id,),
            ).fetchone()
            if not row:
                raise FoundryError(
                    "APPROVAL_CHALLENGE_NOT_FOUND",
                    "No exact-byte approval challenge has that ID.",
                    status_code=404,
                )
            if row["status"] != "issued":
                raise self._terminal_status_error(row)

            challenge_core, principal, hashes = self._validate_bindings(
                row,
                nonce=nonce,
                operation=operation,
                subject_type=subject_type,
                subject_id=subject_id,
                exact_bytes=exact_bytes,
                binding=binding,
                project_lock_hash=project_lock_hash,
            )
            observation = self._observe_clock(conn)
            issued_at = _parse_time(row["issued_at"])
            expires_at = _parse_time(row["expires_at"])

            if not row["process_epoch_id"] or row["issued_monotonic_ns"] is None or row["deadline_monotonic_ns"] is None:
                deferred_error = self._invalidate(
                    conn,
                    row,
                    observation,
                    reason="legacy_clock_authority_unproven",
                    code="APPROVAL_CHALLENGE_CLOCK_AUTHORITY_UNPROVEN",
                    message="The outstanding legacy challenge has no R5 clock authority and is permanently unusable.",
                )
            elif row["process_epoch_id"] != observation.epoch.epoch_id:
                deferred_error = self._invalidate(
                    conn,
                    row,
                    observation,
                    reason="process_epoch_changed",
                    code="APPROVAL_CHALLENGE_PROCESS_EPOCH_CHANGED",
                    message="The issuing process epoch ended; the outstanding challenge is permanently unusable.",
                    details={
                        "issuing_process_epoch_id": row["process_epoch_id"],
                        "current_process_epoch_id": observation.epoch.epoch_id,
                    },
                )
            elif observation.monotonic_rollback or observation.monotonic_now_ns < int(row["issued_monotonic_ns"]):
                deferred_error = self._invalidate(
                    conn,
                    row,
                    observation,
                    reason="monotonic_clock_rollback",
                    code="APPROVAL_CHALLENGE_CLOCK_ROLLBACK",
                    message="Monotonic clock authority moved backward; the challenge was permanently invalidated.",
                    details={
                        "issued_monotonic_ns": row["issued_monotonic_ns"],
                        "durable_monotonic_high_water_ns": observation.durable_monotonic_high_water_ns,
                    },
                )
            elif observation.monotonic_now_ns >= int(row["deadline_monotonic_ns"]):
                observed = _format_time(observation.wall_now)
                changed = conn.execute(
                    """UPDATE exact_approval_challenges
                       SET status='expired',expired_observed_at=?
                       WHERE challenge_id=? AND status='issued'""",
                    (observed, challenge_id),
                ).rowcount
                if changed != 1:
                    raise FoundryError(
                        "APPROVAL_CHALLENGE_CONCURRENT_USE",
                        "The challenge state changed concurrently.",
                        status_code=409,
                    )
                deferred_error = FoundryError(
                    "APPROVAL_CHALLENGE_EXPIRED",
                    "The exact-byte approval challenge expired by its monotonic deadline and is permanently unusable.",
                    details={
                        "expired_observed_at": observed,
                        "deadline_monotonic_ns": row["deadline_monotonic_ns"],
                        "observed_monotonic_ns": observation.monotonic_now_ns,
                    },
                    status_code=409,
                )
            elif observation.wall_rollback or observation.wall_now < issued_at:
                deferred_error = self._invalidate(
                    conn,
                    row,
                    observation,
                    reason="wall_clock_rollback",
                    code="APPROVAL_CHALLENGE_CLOCK_ROLLBACK",
                    message="Wall-clock authority moved backward; the challenge was permanently invalidated.",
                    details={
                        "issued_at": row["issued_at"],
                        "durable_wall_high_water_at": _format_time(observation.durable_wall_high_water),
                    },
                )
            elif observation.wall_now >= expires_at:
                deferred_error = self._invalidate(
                    conn,
                    row,
                    observation,
                    reason="wall_clock_outside_authorized_interval",
                    code="APPROVAL_CHALLENGE_CLOCK_INTERVAL_INVALID",
                    message="Wall time is outside the challenge interval before the monotonic deadline; the challenge was invalidated.",
                    details={"expires_at": row["expires_at"]},
                )
            else:
                exact_hash, binding_hash, lock_hash = hashes
                consumed_at = _format_time(observation.wall_now)
                consumed_monotonic_ns = observation.monotonic_now_ns
                changed = conn.execute(
                    """UPDATE exact_approval_challenges
                       SET status='consumed',consumed_at=?,consumed_monotonic_ns=?
                       WHERE challenge_id=? AND status='issued'""",
                    (consumed_at, consumed_monotonic_ns, challenge_id),
                ).rowcount
                if changed != 1:
                    raise FoundryError(
                        "APPROVAL_CHALLENGE_CONCURRENT_USE",
                        "The challenge was consumed concurrently.",
                        status_code=409,
                    )
                projection = {
                    "schema_version": "TianxiaFoundry.ExactApprovalEvidence.v2",
                    "challenge": challenge_core,
                    "challenge_hash": row["challenge_hash"],
                    "principal": principal.as_dict(),
                    "operation": operation,
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "exact_bytes_hash": exact_hash,
                    "binding": binding or {},
                    "binding_hash": binding_hash,
                    "project_lock_hash": lock_hash,
                    "approval_context": evidence_context or {},
                    "clock_authority": {
                        "process_epoch_id": observation.epoch.epoch_id,
                        "consumed_monotonic_ns": consumed_monotonic_ns,
                    },
                    "consumed_at": consumed_at,
                }
                projection_json = canonical_json(projection)
                projection_hash = sha256_bytes(projection_json.encode("utf-8"))
                envelope = self.integrity.sign(APPROVAL_EVIDENCE_DOMAIN, projection)
                if envelope.projection_hash != projection_hash:
                    raise FoundryError(
                        "INTEGRITY_PROJECTION_HASH_MISMATCH",
                        "The approval projection hash differed during signing.",
                        status_code=500,
                    )
                evidence_hash = projection_hash
                evidence_id = "approval.evidence.v2." + evidence_hash
                conn.execute(
                    """INSERT INTO exact_approval_evidence(
                       evidence_id,challenge_id,challenge_hash,principal_id,principal_hash,operation,subject_type,subject_id,
                       exact_bytes_hash,binding_hash,project_lock_hash,evidence_hash,evidence_json,consumed_at,
                       approval_projection_json,approval_projection_hash,integrity_version,integrity_key_id,integrity_domain,integrity_mac,
                       process_epoch_id,consumed_monotonic_ns)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        evidence_id,
                        challenge_id,
                        row["challenge_hash"],
                        principal.principal_id,
                        principal.principal_hash,
                        operation,
                        subject_type,
                        subject_id,
                        exact_hash,
                        binding_hash,
                        lock_hash,
                        evidence_hash,
                        projection_json,
                        consumed_at,
                        projection_json,
                        projection_hash,
                        envelope.integrity_version,
                        envelope.key_id,
                        envelope.domain,
                        envelope.mac,
                        observation.epoch.epoch_id,
                        consumed_monotonic_ns,
                    ),
                )
                evidence = {
                    **projection,
                    "evidence_id": evidence_id,
                    "evidence_hash": evidence_hash,
                    "approval_projection_hash": projection_hash,
                    **envelope.as_dict(),
                }
                if action is not None:
                    action_result = action(conn, evidence)
        if deferred_error is not None:
            raise deferred_error
        assert evidence is not None
        return evidence, action_result

    def consume(
        self,
        *,
        challenge_id: str,
        nonce: str,
        operation: str,
        subject_type: str,
        subject_id: str,
        exact_bytes: bytes,
        binding: dict[str, Any] | None = None,
        project_lock_hash: str | None = None,
        evidence_context: dict[str, Any] | None = None,
        conn: Any | None = None,
    ) -> dict[str, Any]:
        if conn is not None:
            raise FoundryError(
                "APPROVAL_CHALLENGE_ATOMIC_ACTION_REQUIRED",
                "Challenge consumption must own the transaction so temporal invalidation and one-time use remain durable.",
                status_code=500,
            )
        evidence, _ = self.consume_with_action(
            challenge_id=challenge_id,
            nonce=nonce,
            operation=operation,
            subject_type=subject_type,
            subject_id=subject_id,
            exact_bytes=exact_bytes,
            binding=binding,
            project_lock_hash=project_lock_hash,
            evidence_context=evidence_context,
        )
        return evidence

    def verify_evidence(
        self,
        conn: Any,
        evidence_id: str,
        *,
        operation: str,
        subject_type: str,
        subject_id: str,
        exact_bytes: bytes,
        binding: dict[str, Any] | None = None,
        project_lock_hash: str | None = None,
        principal_id: str | None = None,
        evidence_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM exact_approval_evidence WHERE evidence_id=?",
            (evidence_id,),
        ).fetchone()
        if not row:
            raise FoundryError(
                "APPROVAL_EVIDENCE_NOT_FOUND",
                "The exact-byte approval evidence is missing.",
                details={"evidence_id": evidence_id},
                status_code=409,
            )
        challenge = conn.execute(
            "SELECT * FROM exact_approval_challenges WHERE challenge_id=?",
            (row["challenge_id"],),
        ).fetchone()
        if not challenge or challenge["status"] != "consumed":
            raise FoundryError(
                "APPROVAL_EVIDENCE_CHALLENGE_NOT_CONSUMED",
                "Approval evidence is not backed by a consumed one-time challenge.",
                status_code=409,
            )
        challenge_core = self._challenge_core(challenge)
        exact_hash, binding_hash, lock_hash = self._binding(exact_bytes, binding, project_lock_hash)
        expected_columns = {
            "challenge_hash": challenge["challenge_hash"],
            "principal_id": principal_id or row["principal_id"],
            "operation": operation,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "exact_bytes_hash": exact_hash,
            "binding_hash": binding_hash,
            "project_lock_hash": lock_hash,
            "consumed_at": challenge["consumed_at"],
        }
        for field, expected in expected_columns.items():
            if row[field] != expected:
                raise FoundryError(
                    "APPROVAL_EVIDENCE_BINDING_MISMATCH",
                    "Approval evidence differs from the exact authoritative binding.",
                    details={"field": field, "expected": expected, "actual": row[field]},
                    status_code=409,
                )
        if row["principal_hash"] != challenge["principal_hash"] or row["principal_id"] != challenge["principal_id"]:
            raise FoundryError(
                "APPROVAL_EVIDENCE_PRINCIPAL_MISMATCH",
                "Approval evidence principal fields differ from the consumed challenge.",
                status_code=409,
            )

        issued_at = _parse_time(challenge["issued_at"])
        expires_at = _parse_time(challenge["expires_at"])
        consumed_at = _parse_time(challenge["consumed_at"])
        if consumed_at < issued_at:
            raise FoundryError(
                "APPROVAL_EVIDENCE_TEMPORAL_ORDER_INVALID",
                "Approval evidence records consumption before challenge issuance.",
                details={"issued_at": challenge["issued_at"], "consumed_at": challenge["consumed_at"]},
                status_code=409,
            )
        if consumed_at >= expires_at:
            raise FoundryError(
                "APPROVAL_EVIDENCE_TEMPORAL_INTERVAL_INVALID",
                "Approval evidence records consumption outside the authorized wall-time interval.",
                details={"expires_at": challenge["expires_at"], "consumed_at": challenge["consumed_at"]},
                status_code=409,
            )

        projection = {
            "schema_version": "TianxiaFoundry.ExactApprovalEvidence.v2",
            "challenge": challenge_core,
            "challenge_hash": challenge["challenge_hash"],
            "principal": challenge_core["principal"],
            "operation": operation,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "exact_bytes_hash": exact_hash,
            "binding": binding or {},
            "binding_hash": binding_hash,
            "project_lock_hash": lock_hash,
            "approval_context": evidence_context or {},
        }
        if challenge_core["schema_version"] == "TianxiaFoundry.ExactApprovalChallenge.v2":
            process_epoch_id = challenge["process_epoch_id"]
            consumed_monotonic_ns = challenge["consumed_monotonic_ns"]
            if not process_epoch_id or consumed_monotonic_ns is None:
                raise FoundryError(
                    "APPROVAL_EVIDENCE_CLOCK_AUTHORITY_MISSING",
                    "R5 approval evidence is missing process-epoch or monotonic consumption authority.",
                    status_code=409,
                )
            if row["process_epoch_id"] != process_epoch_id or row["consumed_monotonic_ns"] != consumed_monotonic_ns:
                raise FoundryError(
                    "APPROVAL_EVIDENCE_CLOCK_AUTHORITY_MISMATCH",
                    "Approval evidence clock authority differs from the consumed challenge.",
                    status_code=409,
                )
            issued_mono = int(challenge["issued_monotonic_ns"])
            deadline_mono = int(challenge["deadline_monotonic_ns"])
            consumed_mono = int(consumed_monotonic_ns)
            if consumed_mono < issued_mono or consumed_mono >= deadline_mono:
                raise FoundryError(
                    "APPROVAL_EVIDENCE_MONOTONIC_INTERVAL_INVALID",
                    "Approval evidence records consumption outside the authorized monotonic interval.",
                    details={
                        "issued_monotonic_ns": issued_mono,
                        "deadline_monotonic_ns": deadline_mono,
                        "consumed_monotonic_ns": consumed_mono,
                    },
                    status_code=409,
                )
            projection["clock_authority"] = {
                "process_epoch_id": process_epoch_id,
                "consumed_monotonic_ns": consumed_mono,
            }
        elif row["process_epoch_id"] is not None or row["consumed_monotonic_ns"] is not None:
            raise FoundryError(
                "APPROVAL_EVIDENCE_LEGACY_CLOCK_FIELDS_INVALID",
                "Legacy approval evidence unexpectedly contains partial R5 clock authority.",
                status_code=409,
            )
        projection["consumed_at"] = challenge["consumed_at"]

        projection_json = canonical_json(projection)
        projection_hash = sha256_bytes(projection_json.encode("utf-8"))
        if row["approval_projection_json"] != projection_json or row["evidence_json"] != projection_json:
            raise FoundryError(
                "APPROVAL_EVIDENCE_CANONICAL_BYTES_MISMATCH",
                "Stored approval evidence is not the exact canonical projection.",
                status_code=409,
            )
        if row["approval_projection_hash"] != projection_hash or row["evidence_hash"] != projection_hash:
            raise FoundryError(
                "APPROVAL_EVIDENCE_HASH_MISMATCH",
                "Stored approval evidence hashes do not match the canonical projection.",
                status_code=409,
            )
        expected_id = "approval.evidence.v2." + projection_hash
        if row["evidence_id"] != expected_id:
            raise FoundryError(
                "APPROVAL_EVIDENCE_ID_MISMATCH",
                "The approval evidence ID does not match its canonical projection.",
                status_code=409,
            )
        envelope = {
            "integrity_version": row["integrity_version"],
            "algorithm": "HMAC-SHA-256",
            "key_id": row["integrity_key_id"],
            "domain": row["integrity_domain"],
            "projection_hash": row["approval_projection_hash"],
            "mac": row["integrity_mac"],
        }
        self.integrity.verify(APPROVAL_EVIDENCE_DOMAIN, projection, envelope)
        return {
            **projection,
            "evidence_id": row["evidence_id"],
            "evidence_hash": row["evidence_hash"],
            "approval_projection_hash": row["approval_projection_hash"],
            **envelope,
        }


__all__ = ["APPROVAL_EVIDENCE_DOMAIN", "ApprovalChallengeService"]
