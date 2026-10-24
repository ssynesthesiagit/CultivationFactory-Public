from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest

import project_store.service as project_store_module
import stage2.service as stage2_module
from app.core import FoundryError, canonical_json, sha256_json
from content_packs.membership import PackSeal
from project_store.service import ProjectStore, project_lock_proof_cache_scope
from stage2.service import (
    RulesCausalStage2Service,
    _TRUSTED_CHARACTER_CREATION_EXECUTION,
    _record_stage2_commit_timing,
    stage2_compiled_validation_cache_scope,
    stage2_commit_authority_proof_cache_scope,
)
from character_creation.service import CharacterCreationExecutionService


def _path_authority_fixture() -> tuple[sqlite3.Connection, dict[str, object]]:
    project_id = "project-compile-cache"
    run_id = "run-compile-cache"
    lock_hash = "content-lock-compile-cache"
    path_id = "tianxia.path.qi_cultivation"
    snapshot: dict[str, object] = {
        "schema": "TianxiaFoundry.TypedProjectChoiceSnapshot.v1",
        "canonical_project_id": project_id,
        "project_revision": 0,
        "content_lock_hash": lock_hash,
        "selections": {},
    }
    snapshot["snapshot_sha256"] = sha256_json(
        {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    )
    prompt = {"prompt_id": "prompt-compile-cache", "prompt_sha256": "prompt-sha"}
    binding = {
        "project_id": project_id,
        "project_revision": 0,
        "catalog_build_id": "catalog-compile-cache",
        "content_lock_hash": lock_hash,
        "stage1_prompt_id": prompt["prompt_id"],
        "stage1_prompt_sha256": prompt["prompt_sha256"],
    }
    envelope: dict[str, object] = {
        "schema": "TianxiaFoundry.DelegatedChoiceAuthorityEnvelope.v1",
        "binding": binding,
        "allowed_choice_ids_by_slot": {"path_choice": [path_id]},
        "choices_by_slot": {"path_choice": {path_id: {"display_name": "Qi"}}},
    }
    envelope["envelope_sha256"] = sha256_json(
        {key: value for key, value in envelope.items() if key != "envelope_sha256"}
    )
    request: dict[str, object] = {
        "project_id": project_id,
        "project_revision": 0,
        "content_lock_hash": lock_hash,
        "stage1_prompt": prompt,
        "typed_choice_snapshot": snapshot,
        "delegated_choice_envelope": envelope,
    }
    request["request_sha256"] = sha256_json(request)
    project = {
        "project_id": project_id,
        "revision": 0,
        "content_lock": {
            "lock_hash": lock_hash,
            "catalog_build_id": "catalog-compile-cache",
        },
    }

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE character_creation_runs(
            run_id TEXT, project_id TEXT, starting_revision INTEGER,
            request_json TEXT, status TEXT, quality_json TEXT, dry_run_json TEXT
        );
        CREATE TABLE projects(project_id TEXT, revision INTEGER, project_json TEXT);
        """
    )
    conn.execute(
        "INSERT INTO character_creation_runs VALUES(?,?,?,?,?,?,?)",
        (
            run_id,
            project_id,
            0,
            canonical_json(request),
            "WAITING_FOR_RESPONSE",
            "{}",
            "{}",
        ),
    )
    conn.execute(
        "INSERT INTO projects VALUES(?,?,?)",
        (project_id, 0, canonical_json(project)),
    )
    conn.commit()
    return conn, {
        "project_id": project_id,
        "run_id": run_id,
        "path_id": path_id,
        "lock_hash": lock_hash,
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "request": request,
    }


def test_compile_proposal_path_proof_cache_is_operation_local(monkeypatch) -> None:
    conn, fixture = _path_authority_fixture()
    service = object.__new__(RulesCausalStage2Service)
    calls: list[object] = []
    original_sha256_json = stage2_module.sha256_json

    def counting_sha256_json(value):
        calls.append(value)
        return original_sha256_json(value)

    def fake_uncached(self, _conn, _row):
        return (
            self._validated_initial_creation_delegated_path_ids(
                _conn, fixture["project_id"], fixture["path_id"]
            ),
            self._validated_initial_creation_delegated_path_ids(
                _conn, fixture["project_id"], fixture["path_id"]
            ),
        )

    monkeypatch.setattr(stage2_module, "sha256_json", counting_sha256_json)
    monkeypatch.setattr(RulesCausalStage2Service, "_compile_proposal_uncached", fake_uncached)
    with service._trusted_character_creation_scope(
        run_id=fixture["run_id"],
        project_id=fixture["project_id"],
        starting_revision=0,
        content_lock_hash=fixture["lock_hash"],
        typed_choice_snapshot_sha256=fixture["snapshot_sha256"],
        request_sha256=fixture["request"]["request_sha256"],
        authorized_delegated_path_ids=(fixture["path_id"],),
        phase="scratch_compile",
        candidate_identity=None,
        _server_authority=_TRUSTED_CHARACTER_CREATION_EXECUTION,
    ):
        first = service.compile_proposal(conn, {"project_id": fixture["project_id"]})
        first_calls = len(calls)
        assert first == (frozenset({fixture["path_id"]}), frozenset({fixture["path_id"]}))
        assert first_calls > 0

        changed_request = dict(fixture["request"])
        changed_request["unrelated_frozen_input"] = "changed"
        conn.execute(
            "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
            (canonical_json(changed_request), fixture["run_id"]),
        )
        conn.commit()
        second = service.compile_proposal(conn, {"project_id": fixture["project_id"]})

    assert second == (None, None)
    assert len(calls) > first_calls


def _bind_server_output_profile_target(fixture: dict[str, object], conn: sqlite3.Connection) -> None:
    """Add the request-bound combat target used by the real creation flow."""
    request = deepcopy(fixture["request"])
    assert isinstance(request, dict)
    request["server_owned_authority"] = {
        "output_profile_target_required": True,
        "output_profile": {
            "schema": "TianxiaFoundry.ServerOwnedOutputProfileTarget.v1",
            "profile": "CHARACTER_GM_MODEL",
            "combat_ready": True,
            "binding": {
                "project_id": fixture["project_id"],
                "project_revision": 0,
                "content_lock_hash": fixture["lock_hash"],
                "request_sha256": "",
            },
        },
    }
    request_sha256 = CharacterCreationExecutionService.request_payload_sha256(request)
    request["server_owned_authority"]["output_profile"]["binding"]["request_sha256"] = request_sha256
    assert CharacterCreationExecutionService.request_payload_sha256(request) == request_sha256
    request["request_sha256"] = request_sha256
    conn.execute(
        "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
        (canonical_json(request), fixture["run_id"]),
    )
    conn.commit()
    fixture["request"] = request


def test_initial_creation_path_proof_matches_cycle_free_output_profile_hash() -> None:
    conn, fixture = _path_authority_fixture()
    _bind_server_output_profile_target(fixture, conn)
    service = object.__new__(RulesCausalStage2Service)

    with service._trusted_character_creation_scope(
        run_id=fixture["run_id"],
        project_id=fixture["project_id"],
        starting_revision=0,
        content_lock_hash=fixture["lock_hash"],
        typed_choice_snapshot_sha256=fixture["snapshot_sha256"],
        request_sha256=fixture["request"]["request_sha256"],
        authorized_delegated_path_ids=(fixture["path_id"],),
        phase="scratch_compile",
        candidate_identity=None,
        _server_authority=_TRUSTED_CHARACTER_CREATION_EXECUTION,
    ):
        assert service._validated_initial_creation_delegated_path_ids(
            conn, fixture["project_id"], fixture["path_id"]
        ) == frozenset({fixture["path_id"]})


def test_initial_creation_path_proof_rejects_non_circular_target_tamper() -> None:
    conn, fixture = _path_authority_fixture()
    _bind_server_output_profile_target(fixture, conn)
    request = fixture["request"]
    request["server_owned_authority"]["output_profile"]["combat_ready"] = False
    conn.execute(
        "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
        (canonical_json(request), fixture["run_id"]),
    )
    conn.commit()
    service = object.__new__(RulesCausalStage2Service)

    with service._trusted_character_creation_scope(
        run_id=fixture["run_id"],
        project_id=fixture["project_id"],
        starting_revision=0,
        content_lock_hash=fixture["lock_hash"],
        typed_choice_snapshot_sha256=fixture["snapshot_sha256"],
        request_sha256=fixture["request"]["request_sha256"],
        authorized_delegated_path_ids=(fixture["path_id"],),
        phase="scratch_compile",
        candidate_identity=None,
        _server_authority=_TRUSTED_CHARACTER_CREATION_EXECUTION,
    ):
        assert service._validated_initial_creation_delegated_path_ids(
            conn, fixture["project_id"], fixture["path_id"]
        ) is None


def test_initial_creation_path_proof_rejects_unoffered_delegated_path() -> None:
    conn, fixture = _path_authority_fixture()
    _bind_server_output_profile_target(fixture, conn)
    service = object.__new__(RulesCausalStage2Service)
    unoffered_path = "tianxia.path.body_refining"

    with service._trusted_character_creation_scope(
        run_id=fixture["run_id"],
        project_id=fixture["project_id"],
        starting_revision=0,
        content_lock_hash=fixture["lock_hash"],
        typed_choice_snapshot_sha256=fixture["snapshot_sha256"],
        request_sha256=fixture["request"]["request_sha256"],
        authorized_delegated_path_ids=(unoffered_path,),
        phase="scratch_compile",
        candidate_identity=None,
        _server_authority=_TRUSTED_CHARACTER_CREATION_EXECUTION,
    ):
        assert service._validated_initial_creation_delegated_path_ids(
            conn, fixture["project_id"], unoffered_path
        ) is None


def test_commit_path_authority_proof_cache_is_connection_scoped_and_fail_closed() -> None:
    conn, fixture = _path_authority_fixture()
    conn2, _fixture2 = _path_authority_fixture()
    service = object.__new__(RulesCausalStage2Service)
    resolve_calls: list[dict[str, object]] = []

    class _ProjectStub:
        def _resolve_locked_record_after_proof(self, _conn, _project_id, record_id, **kwargs):
            resolve_calls.append(dict(kwargs))
            return {"record_id": record_id, "content_type": "path"}

    service.projects = _ProjectStub()
    first_trace: list[str] = []
    second_trace: list[str] = []
    conn.set_trace_callback(first_trace.append)
    conn2.set_trace_callback(second_trace.append)
    record = {"record_id": fixture["path_id"], "content_type": "path"}
    request_before = deepcopy(fixture["request"])

    with service._trusted_character_creation_scope(
        run_id=fixture["run_id"],
        project_id=fixture["project_id"],
        starting_revision=0,
        content_lock_hash=fixture["lock_hash"],
        typed_choice_snapshot_sha256=fixture["snapshot_sha256"],
        request_sha256=fixture["request"]["request_sha256"],
        authorized_delegated_path_ids=(fixture["path_id"],),
        phase="scratch_compile",
        candidate_identity=None,
        _server_authority=_TRUSTED_CHARACTER_CREATION_EXECUTION,
    ):
        with stage2_commit_authority_proof_cache_scope(conn):
            assert service._resolve_record_after_proof(
                conn, fixture["project_id"], fixture["path_id"]
            ) == record
            service._assert_record_after_proof(conn, fixture["project_id"], record)
            assert service._resolve_record_after_proof(
                conn, fixture["project_id"], fixture["path_id"]
            ) == record
            service._assert_record_after_proof(conn, fixture["project_id"], record)
            first_proof_sql = len(first_trace)
            assert first_proof_sql > 0

            # Repeated resolve/assert calls reuse only the validated Path-ID
            # proof; the project resolver still runs for every call.
            assert len(resolve_calls) == 4
            assert len(first_trace) == first_proof_sql

            with service._trusted_character_creation_scope(
                run_id=fixture["run_id"],
                project_id=fixture["project_id"],
                starting_revision=0,
                content_lock_hash=fixture["lock_hash"],
                typed_choice_snapshot_sha256=fixture["snapshot_sha256"],
                request_sha256="changed-request-binding",
                authorized_delegated_path_ids=(fixture["path_id"],),
                phase="scratch_compile",
                candidate_identity=None,
                _server_authority=_TRUSTED_CHARACTER_CREATION_EXECUTION,
            ):
                assert service._validated_initial_creation_delegated_path_ids(
                    conn, fixture["project_id"], fixture["path_id"]
                ) is None
            assert len(first_trace) > first_proof_sql

        # Scope reset forces a fresh proof on the same connection.
        after_scope = len(first_trace)
        with stage2_commit_authority_proof_cache_scope(conn):
            assert service._validated_initial_creation_delegated_path_ids(
                conn, fixture["project_id"], fixture["path_id"]
            ) == frozenset({fixture["path_id"]})
        assert len(first_trace) > after_scope

        # Exception exit also resets the operation cache.
        with pytest.raises(RuntimeError, match="scope failure"):
            with stage2_commit_authority_proof_cache_scope(conn):
                assert service._validated_initial_creation_delegated_path_ids(
                    conn, fixture["project_id"], fixture["path_id"]
                ) == frozenset({fixture["path_id"]})
                raise RuntimeError("scope failure")
        after_exception = len(first_trace)
        with stage2_commit_authority_proof_cache_scope(conn):
            assert service._validated_initial_creation_delegated_path_ids(
                conn, fixture["project_id"], fixture["path_id"]
            ) == frozenset({fixture["path_id"]})
        assert len(first_trace) > after_exception

        # A distinct connection cannot reuse the first transaction's proof;
        # without a commit scope it performs the ordinary full proof.
        before_conn2 = len(second_trace)
        assert service._validated_initial_creation_delegated_path_ids(
            conn2, fixture["project_id"], fixture["path_id"]
        ) == frozenset({fixture["path_id"]})
        assert len(second_trace) > before_conn2
        after_conn2 = len(second_trace)
        with stage2_commit_authority_proof_cache_scope(conn2):
            assert service._validated_initial_creation_delegated_path_ids(
                conn2, fixture["project_id"], fixture["path_id"]
            ) == frozenset({fixture["path_id"]})
        assert len(second_trace) > after_conn2

    assert fixture["request"] == request_before


def _compiled_validation_fixture() -> tuple[sqlite3.Connection, RulesCausalStage2Service, dict[str, object], dict[str, str]]:
    project_id = "project-stage2-validation-cache"
    proposal_id = "proposal-stage2-validation-cache"
    run_id = "run-stage2-validation-cache"
    lock = {
        "pack_id": "pack-stage2-validation-cache",
        "version": "1.0.0",
        "pack_hash": "pack-hash-stage2-validation-cache",
        "record_set_hash": "record-set-stage2-validation-cache",
        "payload_files_hash": "payload-stage2-validation-cache",
        "install_receipt_hash": "receipt-stage2-validation-cache",
        "membership_snapshot_hash": "membership-stage2-validation-cache",
        "locked_at": "2026-08-28T00:00:00Z",
    }
    proposal = {
        "schema": "TianxiaFoundry.Stage2AdvancementProposal.v2",
        "project_id": project_id,
        "idempotency_key": "stage2-validation-cache",
        "expected_project_revision": 0,
        "expected_content_lock_hash": "content-lock-stage2-validation-cache",
        "target_cl": 1,
        "choices": [],
    }
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE stage2_proposal_events(
            proposal_id TEXT, ordinal INTEGER, event_request_json TEXT,
            event_request_hash TEXT
        );
        CREATE TABLE projects(
            project_id TEXT, revision INTEGER, project_json TEXT,
            canonical_project_hash TEXT, status TEXT,
            canonical_schema_version TEXT, contract_status TEXT
        );
        CREATE TABLE events(
            project_id TEXT, sequence_no INTEGER, event_id TEXT,
            event_hash TEXT, previous_event_hash TEXT, created_at TEXT,
            event_json TEXT, legacy_event_json TEXT, legacy_event_hash TEXT,
            canonical_schema_version TEXT, contract_status TEXT
        );
        CREATE TABLE character_creation_runs(
            run_id TEXT, project_id TEXT, starting_revision INTEGER,
            request_json TEXT, transport_json TEXT, response_json TEXT,
            status TEXT, quality_json TEXT, dry_run_json TEXT
        );
        """
    )
    project = {
        "project_id": project_id,
        "revision": 0,
        "content_lock": {"lock_hash": proposal["expected_content_lock_hash"]},
    }
    request = {"request_sha256": "request-stage2-validation-cache"}
    conn.execute(
        "INSERT INTO projects VALUES(?,?,?,?,?,?,?)",
        (
            project_id,
            0,
            canonical_json(project),
            "project-hash-stage2-validation-cache",
            "stage_1",
            "TianxiaFoundry.Project.v1",
            "valid",
        ),
    )
    conn.execute(
        "INSERT INTO stage2_proposal_events VALUES(?,?,?,?)",
        (
            proposal_id,
            0,
            '{"event":"unchanged-child"}',
            "event-request-hash-stage2-validation-cache",
        ),
    )
    conn.execute(
        "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            project_id,
            1,
            "event-stage2-validation-cache",
            "event-hash-stage2-validation-cache",
            "0" * 64,
            "2026-08-28T00:00:00Z",
            "{\"event\":\"unchanged\"}",
            None,
            None,
            "TianxiaFoundry.AdvancementEvent.v3",
            "valid",
        ),
    )
    conn.execute(
        """INSERT INTO character_creation_runs(
            run_id,project_id,starting_revision,request_json,transport_json,
            response_json,status,quality_json,dry_run_json
        ) VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            run_id,
            project_id,
            0,
            canonical_json(request),
            '{"provider":"unused"}',
            '{"response":"unused"}',
            "WAITING_FOR_RESPONSE",
            "{}",
            "{}",
        ),
    )
    conn.commit()
    row = {
        "proposal_id": proposal_id,
        "project_id": project_id,
        "idempotency_key": proposal["idempotency_key"],
        "expected_project_revision": proposal["expected_project_revision"],
        "expected_content_lock_hash": proposal["expected_content_lock_hash"],
        "target_cl": proposal["target_cl"],
        "proposal_json": canonical_json(proposal),
        "proposal_hash": sha256_json(proposal),
    }

    class _ProjectProofs:
        def __init__(self) -> None:
            self.lock = deepcopy(lock)

        def _project_locks(self, _conn, _project_id):
            return [deepcopy(self.lock)]

        def project_lock_proof(self, _conn, _project_id):
            return {"lock_proof_hash": sha256_json(self.lock)}

    service = object.__new__(RulesCausalStage2Service)
    service.db = object()
    service.projects = _ProjectProofs()
    return conn, service, row, {"project_id": project_id, "proposal_id": proposal_id, "run_id": run_id}


def test_stage2_commit_reuses_exact_compilation_and_keeps_boundary_timings_private(monkeypatch) -> None:
    conn, stage2, row, ids = _compiled_validation_fixture()
    uncached_calls: list[int] = []

    def fake_uncached(self, _conn, _row):
        uncached_calls.append(1)
        proof = self.projects.project_lock_proof(_conn, _row["project_id"])
        return {
            "valid": True,
            "marker": len(uncached_calls),
            "nested": {"caller_mutation": []},
            "project_lock_proof_hash": proof["lock_proof_hash"],
        }

    monkeypatch.setattr(RulesCausalStage2Service, "_compile_proposal_uncached", fake_uncached)

    class _BoundaryService:
        db = object()

        def __init__(self):
            self.compile_calls = 0

        def create_proposal(self, _proposal):
            return {"proposal_id": ids["proposal_id"]}

        def _compile(self):
            self.compile_calls += 1
            return stage2.compile_proposal(conn, row)

        def validate_proposal(self, _proposal_id):
            return self._compile()

        def issue_approval_challenge(self, _proposal_id):
            self._compile()
            return {"challenge": {"challenge_id": "challenge", "nonce": "nonce"}}

        def approve_proposal(self, _proposal_id, **_kwargs):
            self._compile()
            self._compile()
            return {"approved": True}

        def commit_proposal(self, _proposal_id):
            self._compile()
            self._compile()
            return {"committed": True}

    boundary = _BoundaryService()
    creation = object.__new__(CharacterCreationExecutionService)
    timings: dict[str, object] = {}
    validation, result, projection = creation._stage2_commit(
        boundary,
        {"choices": []},
        "owner",
        after_commit=lambda: {"projection": "ready"},
        _timing_sink=timings,
    )

    assert boundary.compile_calls == 6
    assert len(uncached_calls) == 1
    assert validation["marker"] == 1
    assert result == {"committed": True}
    assert projection == {"projection": "ready"}
    assert set(timings) == {
        "stage2.create",
        "stage2.validate",
        "stage2.challenge",
        "stage2.approve",
        "stage2.commit",
        "stage2.after_commit_projection",
    }
    assert all(isinstance(value, int) and value >= 0 for value in timings.values())
    assert "timings" not in validation

    with stage2_compiled_validation_cache_scope():
        cached = stage2.compile_proposal(conn, row)
        cached["nested"]["caller_mutation"].append("must-not-leak")
        isolated = stage2.compile_proposal(conn, row)
        assert len(uncached_calls) == 2
        assert isolated["nested"]["caller_mutation"] == []

        row["proposal_json"] = row["proposal_json"] + " "
        stage2.compile_proposal(conn, row)
        assert len(uncached_calls) == 3
        row["proposal_json"] = row["proposal_json"].rstrip()

        conn.execute(
            "UPDATE stage2_proposal_events SET event_request_json=? WHERE proposal_id=?",
            ('{"changed":true}', ids["proposal_id"]),
        )
        conn.commit()
        stage2.compile_proposal(conn, row)
        assert len(uncached_calls) == 4
        conn.execute(
            "DELETE FROM stage2_proposal_events WHERE proposal_id=?",
            (ids["proposal_id"],),
        )
        conn.commit()

        conn.execute(
            "UPDATE projects SET project_json=? WHERE project_id=?",
            ("{\"project_id\":\"changed\"}", ids["project_id"]),
        )
        conn.commit()
        stage2.compile_proposal(conn, row)
        assert len(uncached_calls) == 5
        conn.execute(
            "UPDATE projects SET project_json=? WHERE project_id=?",
            (
                canonical_json({
                    "project_id": ids["project_id"],
                    "revision": 0,
                    "content_lock": {"lock_hash": "content-lock-stage2-validation-cache"},
                }),
                ids["project_id"],
            ),
        )
        conn.commit()

        conn.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                ids["project_id"],
                2,
                "event-stage2-validation-cache-2",
                "event-hash-stage2-validation-cache-2",
                "event-hash-stage2-validation-cache",
                "2026-08-28T00:00:01Z",
                "{\"event\":\"changed\"}",
                None,
                None,
                "TianxiaFoundry.AdvancementEvent.v3",
                "valid",
            ),
        )
        conn.commit()
        stage2.compile_proposal(conn, row)
        assert len(uncached_calls) == 6
        conn.execute(
            "DELETE FROM events WHERE project_id=? AND sequence_no=2",
            (ids["project_id"],),
        )
        conn.commit()

        conn.execute(
            "UPDATE character_creation_runs SET status=? WHERE run_id=?",
            ("READY_FOR_REVIEW", ids["run_id"]),
        )
        conn.commit()
        stage2.compile_proposal(conn, row)
        assert len(uncached_calls) == 7
        stage2.projects.lock["pack_hash"] = "changed-pack-hash"
        stage2.compile_proposal(conn, row)
        assert len(uncached_calls) == 8

    # ContextVar scope reset must force a new full compilation.
    stage2.compile_proposal(conn, row)
    assert len(uncached_calls) == 9


def test_stage2_cache_key_streams_large_run_fields_and_ignores_provider_payload(monkeypatch) -> None:
    conn, stage2, row, ids = _compiled_validation_fixture()
    uncached_calls: list[int] = []

    def fake_uncached(self, _conn, _row):
        uncached_calls.append(1)
        return {
            "valid": True,
            "marker": len(uncached_calls),
            "project_lock_proof_hash": self.projects.project_lock_proof(
                _conn, _row["project_id"]
            )["lock_proof_hash"],
        }

    monkeypatch.setattr(RulesCausalStage2Service, "_compile_proposal_uncached", fake_uncached)

    def run_context(*, phase: str, candidate_identity: str | None):
        return stage2._trusted_character_creation_scope(
            run_id=ids["run_id"],
            project_id=ids["project_id"],
            starting_revision=0,
            content_lock_hash="content-lock-stage2-validation-cache",
            typed_choice_snapshot_sha256="snapshot-stage2-validation-cache",
            request_sha256="request-stage2-validation-cache",
            authorized_delegated_path_ids=(),
            phase=phase,
            candidate_identity=candidate_identity,
            _server_authority=_TRUSTED_CHARACTER_CREATION_EXECUTION,
        )

    with run_context(phase="scratch_compile", candidate_identity=None):
        with stage2_compiled_validation_cache_scope():
            first = stage2.compile_proposal(conn, row)
            first_key = stage2._compile_proposal_binding_key(conn, row)
            large_provider_payload = "x" * (2 * 1024 * 1024)
            conn.execute(
                "UPDATE character_creation_runs SET transport_json=?,response_json=? WHERE run_id=?",
                (large_provider_payload, large_provider_payload, ids["run_id"]),
            )
            conn.commit()
            assert stage2._compile_proposal_binding_key(conn, row) == first_key
            assert stage2.compile_proposal(conn, row) == first
            assert len(uncached_calls) == 1

            conn.execute(
                "UPDATE character_creation_runs SET request_json=? WHERE run_id=?",
                ("request-bytes-changed", ids["run_id"]),
            )
            conn.commit()
            stage2.compile_proposal(conn, row)
            assert len(uncached_calls) == 2

            conn.execute(
                "UPDATE character_creation_runs SET status=? WHERE run_id=?",
                ("NEEDS_REVIEW", ids["run_id"]),
            )
            conn.commit()
            stage2.compile_proposal(conn, row)
            assert len(uncached_calls) == 3

    with run_context(phase="finalization", candidate_identity="candidate-stage2-cache"):
        with stage2_compiled_validation_cache_scope():
            stage2.compile_proposal(conn, row)
            assert len(uncached_calls) == 4
            final_key = stage2._compile_proposal_binding_key(conn, row)
            conn.execute(
                "UPDATE character_creation_runs SET transport_json=?,response_json=? WHERE run_id=?",
                ("provider-transport-changed", "provider-response-changed", ids["run_id"]),
            )
            conn.commit()
            assert stage2._compile_proposal_binding_key(conn, row) == final_key
            stage2.compile_proposal(conn, row)
            assert len(uncached_calls) == 4

            conn.execute(
                "UPDATE character_creation_runs SET quality_json=? WHERE run_id=?",
                ('{"status":"DIRTY"}', ids["run_id"]),
            )
            conn.commit()
            stage2.compile_proposal(conn, row)
            assert len(uncached_calls) == 5

            conn.execute(
                "UPDATE character_creation_runs SET dry_run_json=? WHERE run_id=?",
                ('{"candidate_identity":"changed"}', ids["run_id"]),
            )
            conn.commit()
            stage2.compile_proposal(conn, row)
            assert len(uncached_calls) == 6

    with run_context(phase="finalization", candidate_identity="other-candidate"):
        with stage2_compiled_validation_cache_scope():
            stage2.compile_proposal(conn, row)
            assert len(uncached_calls) == 7


def _pack_fixture(*, include_record: bool = False) -> tuple[ProjectStore, sqlite3.Connection, dict[str, str], PackSeal]:
    packed_record = {
        "record_id": "packed.cache.record",
        "record_hash": "a" * 64,
        "pack_id": "pack-compile-cache",
        "pack_version": "1.0.0",
        "pack_hash": "pack-hash-compile-cache",
    }
    packed_record["record_json"] = canonical_json(packed_record)
    pack_seal = PackSeal(
        pack_id="pack-compile-cache",
        version="1.0.0",
        pack_hash="pack-hash-compile-cache",
        record_set_hash="record-set-compile-cache",
        payload_files_hash="payload-compile-cache",
        install_receipt_hash="receipt-compile-cache",
        membership_snapshot_hash="membership-compile-cache",
        records=(packed_record,) if include_record else (),
    )
    lock = pack_seal.lock_row()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE project_locked_records(
            project_id TEXT, record_id TEXT, pack_id TEXT, pack_version TEXT,
            record_hash TEXT, record_json TEXT
        );
        CREATE TABLE project_locked_replacements(
            project_id TEXT, replacement_id TEXT, replacement_pack_id TEXT,
            replacement_pack_version TEXT, replacement_pack_hash TEXT,
            source_record_id TEXT, source_record_hash TEXT, source_pack_id TEXT,
            source_pack_version TEXT, source_pack_hash TEXT, target_record_id TEXT,
            target_record_hash TEXT, mode TEXT, reason TEXT, map_path TEXT, map_hash TEXT
        );
        """
    )
    if include_record:
        conn.execute(
            "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
            (
                "project-compile-cache",
                packed_record["record_id"],
                pack_seal.pack_id,
                pack_seal.version,
                packed_record["record_hash"],
                packed_record["record_json"],
            ),
        )
    store = object.__new__(ProjectStore)
    store.db = object()
    store.integrity = object()
    store._project_locks = lambda _conn, _project_id: [lock]
    return store, conn, lock, pack_seal


class _CountingConnection:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.record_identity_queries = 0
        self.record_snapshot_fingerprint_queries = 0
        self.full_actual_rows_queries = 0

    def execute(self, sql: str, *args):
        normalized = " ".join(sql.split()).casefold()
        if "from project_locked_records" in normalized:
            if "snapshot_record_identity" in normalized:
                self.record_identity_queries += 1
            elif "snapshot_record_json" in normalized:
                self.record_snapshot_fingerprint_queries += 1
            elif "record_json" in normalized:
                self.full_actual_rows_queries += 1
        return self._conn.execute(sql, *args)


def test_project_lock_proof_cache_reuses_complete_proof_and_is_copy_safe(monkeypatch) -> None:
    store, conn, _lock, pack_seal = _pack_fixture()
    counting_conn = _CountingConnection(conn)
    calls = 0

    def fake_verify(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return pack_seal

    monkeypatch.setattr(project_store_module, "verify_pack_seal", fake_verify)
    with project_lock_proof_cache_scope():
        first = store.project_lock_proof(counting_conn, "project-compile-cache")
        first["locks"].clear()
        second = store.project_lock_proof(counting_conn, "project-compile-cache")

    # The cheap identity query runs every call; the byte fingerprint and the
    # full proof rows are read once per operation scope.
    assert counting_conn.record_identity_queries == 2
    assert counting_conn.record_snapshot_fingerprint_queries == 1
    assert counting_conn.full_actual_rows_queries == 1
    assert calls == 1
    assert len(second["locks"]) == 1


def test_project_lock_proof_byte_fingerprint_is_computed_once_per_scope(monkeypatch) -> None:
    store, conn, _lock, pack_seal = _pack_fixture(include_record=True)
    counting_conn = _CountingConnection(conn)
    monkeypatch.setattr(project_store_module, "verify_pack_seal", lambda *_a, **_k: pack_seal)
    with project_lock_proof_cache_scope():
        proofs = [store.project_lock_proof(counting_conn, "project-compile-cache") for _ in range(5)]
    assert counting_conn.record_identity_queries == 5
    assert counting_conn.record_snapshot_fingerprint_queries == 1
    assert all(proof == proofs[0] for proof in proofs)

    # Outside a scope nothing is cached: every call fingerprints the bytes.
    store.project_lock_proof(counting_conn, "project-compile-cache")
    store.project_lock_proof(counting_conn, "project-compile-cache")
    assert counting_conn.record_snapshot_fingerprint_queries == 3


def test_locked_path_record_projection_built_once_per_cache_scope(catalog_environment, monkeypatch) -> None:
    from character_builder import CharacterBuilderService

    db = catalog_environment["db"]
    path_id = "tianxia.path.qi_cultivation"
    created = CharacterBuilderService(db).create_project(
        working_name="Path projection cache scope",
        concept="Repeated selected Path projection preserves independent results.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={"path_choice": [path_id]},
    )
    store = ProjectStore(db)
    authority = store._cached_non_sphere_authority()
    original = authority.project_locked_path_catalog_record
    calls = 0

    def counting_projection(record_id):
        nonlocal calls
        calls += 1
        return original(record_id)

    monkeypatch.setattr(authority, "project_locked_path_catalog_record", counting_projection)
    with db.connection() as conn:
        with project_lock_proof_cache_scope():
            results = [
                store._resolve_locked_record_after_proof(conn, created["project_id"], path_id)
                for _ in range(5)
            ]
        assert calls == 1
        assert results[0] is not None
        assert all(result == results[0] for result in results)
        assert all(left is not right for i, left in enumerate(results) for right in results[i + 1:])
        calls = 0
        store._resolve_locked_record_after_proof(conn, created["project_id"], path_id)
        store._resolve_locked_record_after_proof(conn, created["project_id"], path_id)
        assert calls == 2


def test_locked_record_resolution_is_memoized_per_scope_and_follows_row_bytes(monkeypatch) -> None:
    """One compile resolves the same locked row thousands of times.

    Inside an operation scope the resolved projection is reused only while
    the stored row bytes are identical; the row itself is read every time,
    so a replaced row is resolved afresh.  Outside a scope nothing is reused.
    """
    store, conn, _lock, _pack_seal = _pack_fixture(include_record=True)
    monkeypatch.setattr(ProjectStore, "_validate_or_raise", lambda *args, **kwargs: None)
    original = ProjectStore._resolve_locked_record_after_proof_uncached
    calls = 0

    def counting(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ProjectStore, "_resolve_locked_record_after_proof_uncached", counting)
    with project_lock_proof_cache_scope():
        results = [
            store._resolve_locked_record_after_proof(conn, "project-compile-cache", "packed.cache.record")
            for _ in range(5)
        ]
        assert calls == 1
        assert results[0] is not None and results[0]["record_id"] == "packed.cache.record"
        assert all(result == results[0] for result in results)
        assert all(left is not right for i, left in enumerate(results) for right in results[i + 1:])
        conn.execute(
            "UPDATE project_locked_records SET record_hash=?, record_json=? WHERE project_id=? AND record_id=?",
            (
                "c" * 64,
                canonical_json({
                    "record_id": "packed.cache.record",
                    "record_hash": "c" * 64,
                    "pack_id": "pack-compile-cache",
                    "pack_version": "1.0.0",
                    "pack_hash": "pack-hash-compile-cache",
                    "tampered": True,
                }),
                "project-compile-cache",
                "packed.cache.record",
            ),
        )
        replaced = store._resolve_locked_record_after_proof(conn, "project-compile-cache", "packed.cache.record")
        assert calls == 2
        assert replaced is not None and replaced.get("tampered") is True
    calls = 0
    store._resolve_locked_record_after_proof(conn, "project-compile-cache", "packed.cache.record")
    store._resolve_locked_record_after_proof(conn, "project-compile-cache", "packed.cache.record")
    assert calls == 2


def test_database_snapshot_is_byte_identical_and_independent(tmp_path) -> None:
    """The scratch snapshot reads back every committed row and stays detached."""
    import sqlite3 as _sqlite3
    from character_creation.service import CharacterCreationExecutionService as _Service, _reflink_file

    source = tmp_path / "live.sqlite3"
    with _sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE rows(id INTEGER PRIMARY KEY, body TEXT)")
        conn.executemany("INSERT INTO rows(body) VALUES(?)", [(f"row-{index}" * 50,) for index in range(2000)])
    target = tmp_path / "scratch" / "live.sqlite3"
    service = object.__new__(_Service)
    service._backup_database(source, target)
    with _sqlite3.connect(target) as copy:
        assert [row[0] for row in copy.execute("SELECT body FROM rows ORDER BY id")] == [f"row-{index}" * 50 for index in range(2000)]
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        copy.execute("INSERT INTO rows(body) VALUES('only-in-copy')")
    with _sqlite3.connect(source) as conn:
        assert conn.execute("SELECT count(*) FROM rows").fetchone()[0] == 2000
    # A second snapshot over an existing target still reflects the source,
    # including rows that only live in the WAL (no checkpoint has run).
    keep = _sqlite3.connect(source)
    keep.execute("PRAGMA wal_autocheckpoint=0")
    keep.execute("INSERT INTO rows(body) VALUES('newer')")
    keep.commit()
    assert (tmp_path / "live.sqlite3-wal").stat().st_size > 0
    service._backup_database(source, target)
    with _sqlite3.connect(target) as copy:
        assert copy.execute("SELECT count(*) FROM rows").fetchone()[0] == 2001
        assert copy.execute("SELECT body FROM rows WHERE id=2001").fetchone()[0] == "newer"
    keep.close()
    assert _reflink_file(source, tmp_path / "missing-dir" / "x") is False


def test_validate_and_compile_runs_inside_one_proof_cache_scope(monkeypatch) -> None:
    from character_creation.service import CharacterCreationExecutionService as _Service
    import project_store.service as _project_store

    seen: list[bool] = []

    def fake_unscoped(self, run, response_text, **kwargs):
        seen.append(_project_store._PROJECT_LOCK_SCOPE_MEMO.get() is not None)
        return {"ok": True}

    monkeypatch.setattr(_Service, "_validate_and_compile_unscoped", fake_unscoped)
    service = object.__new__(_Service)
    assert service._validate_and_compile({"project_id": "p"}, "{}") == {"ok": True}
    assert seen == [True]
    assert _project_store._PROJECT_LOCK_SCOPE_MEMO.get() is None


def test_locked_records_for_project_built_once_per_cache_scope(catalog_environment, monkeypatch) -> None:
    from character_builder import CharacterBuilderService
    from character_creation.service import CharacterCreationExecutionService as _Service

    db = catalog_environment["db"]
    created = CharacterBuilderService(db).create_project(
        working_name="Locked records cache scope",
        concept="Repeated locked-record loads reuse one reconstruction.",
        target_cl=3,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        selections={"path_choice": ["tianxia.path.qi_cultivation"]},
    )
    service = object.__new__(_Service)
    service.db = db
    service.projects = ProjectStore(db)
    original = _Service._locked_records_for_project_uncached
    calls = 0

    def counting(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(_Service, "_locked_records_for_project_uncached", counting)
    with project_lock_proof_cache_scope():
        results = [service._locked_records_for_project(created["project_id"]) for _ in range(4)]
    assert calls == 1
    assert results[0] and all(result == results[0] for result in results)
    assert all(left is not right for i, left in enumerate(results) for right in results[i + 1:])
    calls = 0
    service._locked_records_for_project(created["project_id"])
    service._locked_records_for_project(created["project_id"])
    assert calls == 2


def test_project_lock_proof_fingerprint_cache_rechecks_changed_membership(monkeypatch) -> None:
    store, conn, _lock, pack_seal = _pack_fixture(include_record=True)
    counting_conn = _CountingConnection(conn)
    monkeypatch.setattr(project_store_module, "verify_pack_seal", lambda *_a, **_k: pack_seal)
    with project_lock_proof_cache_scope():
        store.project_lock_proof(counting_conn, "project-compile-cache")
        conn.execute(
            "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
            ("project-compile-cache", "packed.cache.extra", pack_seal.pack_id, pack_seal.version, "b" * 64, "{}"),
        )
        with pytest.raises(FoundryError) as error:
            store.project_lock_proof(counting_conn, "project-compile-cache")
    # The changed membership forced a fresh byte fingerprint and a fresh proof,
    # which rejects the row that the sealed pack does not contain.
    assert counting_conn.record_snapshot_fingerprint_queries == 2
    assert error.value.code == "PROJECT_LOCK_SNAPSHOT_INCOMPLETE"


def test_project_lock_proof_pack_seal_cache_rechecks_changed_lock(monkeypatch) -> None:
    store, conn, lock, pack_seal = _pack_fixture()
    calls = 0

    def fake_verify(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if _kwargs.get("expected_pack_hash") != pack_seal.pack_hash:
            raise FoundryError("PACK_SEAL_HASH_MISMATCH", "changed test lock hash")
        return pack_seal

    monkeypatch.setattr(project_store_module, "verify_pack_seal", fake_verify)
    with project_lock_proof_cache_scope():
        store.project_lock_proof(conn, "project-compile-cache")
        store.project_lock_proof(conn, "project-compile-cache")
        assert calls == 1

        lock["pack_hash"] = "changed-pack-hash"
        with pytest.raises(FoundryError):
            store.project_lock_proof(conn, "project-compile-cache")
        assert calls == 2

    # The ContextVar scope is reset at the operation boundary; a later
    # request/transaction must verify the same immutable pack again.
    lock["pack_hash"] = pack_seal.pack_hash
    store.project_lock_proof(conn, "project-compile-cache")
    assert calls == 3


def test_project_lock_proof_cache_rejects_packed_payload_substitution(monkeypatch) -> None:
    """A byte substitution that changes a row's sealed hash is rejected.

    In-place JSON edits that keep the hash cannot happen through the schema
    (``trg_project_locked_record_no_update``, pinned by
    ``test_locked_records_by_reference``); the proof fingerprint therefore
    keys on the sealed membership identity inside one operation scope.
    """
    store, conn, _lock, pack_seal = _pack_fixture(include_record=True)

    def fake_verify(*_args, **_kwargs):
        return pack_seal

    monkeypatch.setattr(project_store_module, "verify_pack_seal", fake_verify)
    with project_lock_proof_cache_scope():
        store.project_lock_proof(conn, "project-compile-cache")
        conn.execute(
            "UPDATE project_locked_records SET record_hash=?, record_json=? WHERE project_id=? AND record_id=?",
            (
                "c" * 64,
                canonical_json({
                    "record_id": "packed.cache.record",
                    "record_hash": "c" * 64,
                    "pack_id": "pack-compile-cache",
                    "pack_version": "1.0.0",
                    "pack_hash": "pack-hash-compile-cache",
                    "tampered": True,
                }),
                "project-compile-cache",
                "packed.cache.record",
            ),
        )
        with pytest.raises(FoundryError) as error:
            store.project_lock_proof(conn, "project-compile-cache")
    assert error.value.code == "PROJECT_LOCK_SNAPSHOT_MISMATCH"


def test_stage2_commit_timing_aggregation_is_private_and_result_neutral() -> None:
    """Repeated commit internals aggregate without changing the boundary result."""
    creation = object.__new__(CharacterCreationExecutionService)
    timings: dict[str, object] = {}
    calls: list[str] = []

    class _BoundaryService:
        db = object()

        def create_proposal(self, _proposal):
            calls.append("create")
            return {"proposal_id": "proposal"}

        def validate_proposal(self, _proposal_id):
            calls.append("validate")
            return {"valid": True}

        def issue_approval_challenge(self, _proposal_id):
            calls.append("challenge")
            return {"challenge": {"challenge_id": "challenge", "nonce": "nonce"}}

        def approve_proposal(self, _proposal_id, **_kwargs):
            calls.append("approve")
            return {"approved": True}

        def commit_proposal(self, _proposal_id):
            calls.append("commit")
            # Fixed clock samples make aggregation and repeated phase counts
            # deterministic while exercising the real CharacterCreation sink.
            samples = (
                ("prepare_commit_attempt", 1.0, 1.125),
                ("approval_revalidation_binding", 2.0, 2.5),
                ("approval_revalidation_binding", 3.0, 3.125),
                ("base_replay", 4.0, 4.25),
                ("event_insert_authority", 5.0, 5.25),
                ("event_insert_authority", 6.0, 6.5),
                ("terminal_replay", 7.0, 7.25),
                ("project_update", 8.0, 8.125),
                ("terminal_receipt_sign_verify", 9.0, 9.5),
                ("terminal_receipt_sign_verify", 10.0, 10.25),
            )
            for phase, started, ended in samples:
                _record_stage2_commit_timing(phase, started, ended)
            return {"committed": True}

    validation, result, projection = creation._stage2_commit(
        _BoundaryService(),
        {"choices": []},
        "owner",
        after_commit=lambda: {"projection": "ready"},
        _timing_sink=timings,
    )

    assert calls == ["create", "validate", "challenge", "approve", "commit"]
    assert validation == {"valid": True}
    assert result == {"committed": True}
    assert projection == {"projection": "ready"}

    expected = {
        "stage2.commit.prepare_commit_attempt": (125.0, 1),
        "stage2.commit.approval_revalidation_binding": (625.0, 2),
        "stage2.commit.base_replay": (250.0, 1),
        "stage2.commit.event_insert_authority": (750.0, 2),
        "stage2.commit.terminal_replay": (250.0, 1),
        "stage2.commit.project_update": (125.0, 1),
        "stage2.commit.terminal_receipt_sign_verify": (750.0, 2),
    }
    for phase_key, (total, count) in expected.items():
        assert timings[phase_key] == total
        assert timings[f"{phase_key}.count"] == count
        assert isinstance(timings[phase_key], (int, float))
        assert not isinstance(timings[phase_key], bool)
        assert isinstance(timings[f"{phase_key}.count"], int)

    internal_keys = {
        key for key in timings if key.startswith("stage2.commit.") and key != "stage2.commit"
    }
    assert internal_keys == {
        key
        for phase_key in expected
        for key in (phase_key, f"{phase_key}.count")
    }
    assert all(
        not any(token in key.lower() for token in ("prompt", "response", "payload", "secret", "credential", "header", "token", "_id"))
        for key in internal_keys
    )

    before = deepcopy(timings)
    # The ContextVar is reset when _stage2_commit's operation scope exits.
    _record_stage2_commit_timing("event_insert_authority", 11.0, 12.0)
    assert timings == before
