from __future__ import annotations

import json
import hashlib
from copy import deepcopy

import pytest

from app.core import CORE_PACK_ID, CORE_PACK_VERSION, FoundryError, canonical_json, sha256_json
from character_creation.custom_training_source_authority import (
    CUSTOM_TRAINING_SOURCE_APPROVAL_OPERATION,
    CUSTOM_TRAINING_SOURCE_APPROVAL_SUBJECT_TYPE,
    CUSTOM_TRAINING_SOURCE_PACK_ID,
    CUSTOM_TRAINING_SOURCE_PACK_VERSION,
    CUSTOM_TRAINING_SOURCE_SCHEMA,
    USER_DIRECTIVE_SOURCE_PATH,
    build_custom_training_source_record,
    normalize_custom_training_source,
    validate_custom_training_source_record,
)
import project_store.service as project_store_module
from project_store.service import ProjectStore, project_lock_proof_cache_scope


def _project(catalog_environment, *, suffix: str = "one") -> tuple[ProjectStore, str]:
    store = ProjectStore(catalog_environment["db"])
    with store.db.connection() as conn:
        pack = conn.execute(
            "SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?",
            (CORE_PACK_ID, CORE_PACK_VERSION),
        ).fetchone()
    assert pack is not None
    created = store.create_project(
        working_name=f"Custom training source {suffix}",
        pack_locks=[
            {
                "pack_id": CORE_PACK_ID,
                "version": CORE_PACK_VERSION,
                "pack_hash": pack["pack_hash"],
            }
        ],
        user_locks=[],
    )
    return store, created["project"]["project_id"]


def _target(store: ProjectStore, project_id: str, *, content_type: str = "sphere") -> dict:
    with store.db.connection() as conn:
        rows = conn.execute(
            "SELECT record_json FROM project_locked_records WHERE project_id=? ORDER BY record_id",
            (project_id,),
        ).fetchall()
    for row in rows:
        record = json.loads(row["record_json"])
        if (
            record.get("content_type") == content_type
            and record.get("publication", {}).get("status") == "published"
        ):
            return record
    raise AssertionError(f"No published {content_type} target in the core pack")


def _envelope(target_id: str, *, route_id: str = "owner_supplied_custom_training_source") -> dict:
    return {
        "route_id": route_id,
        "owner_confirmation_id": "owner-confirmation.custom-source.001",
        "display_name": "Owner Confirmed Training Source",
        "summary": "A source description sealed only after explicit owner confirmation.",
        "source_text": "The owner supplied this bounded training-source description.",
        "source_anchor": "manual-lineage.custom-training-source",
        "access_mode": "owner-confirmed-study",
        "training_types": ["new_sphere"],
        "target_record_ids": [target_id],
    }


def _approve(store: ProjectStore, project_id: str, envelope: dict) -> dict:
    issued = store.issue_custom_training_source_challenge(project_id, envelope)
    challenge = issued["challenge"]
    return store.approve_and_seal_custom_training_source(
        project_id,
        envelope,
        challenge["challenge_id"],
        challenge["nonce"],
    )


def test_custom_training_source_routes_normalize_to_same_contract_shape(catalog_environment):
    store, project_id = _project(catalog_environment)
    target = _target(store, project_id)
    records = []
    for route_id in (
        "owner_supplied_custom_training_source",
        "selected_ai_custom_training_source",
    ):
        normalized = normalize_custom_training_source(_envelope(target["record_id"], route_id=route_id))
        record = build_custom_training_source_record(normalized)
        records.append(record)
        assert normalized["schema"] == CUSTOM_TRAINING_SOURCE_SCHEMA
        assert normalized["source_path"] == USER_DIRECTIVE_SOURCE_PATH
        assert normalized["source_text_sha256"] == record["source"]["source_hash"]
        assert record["content_type"] == "source_document"
        assert record["publication"]["status"] == "published"
        assert record["grants"] == []
        assert record["execution_templates"] == []
        assert record["compatibility"]["factory"]["custom_design"] is True
        assert record["compatibility"]["factory"]["authority_classification"] == "user_directive"
        assert record["compatibility"]["factory"]["display_only_not_execution_authority"] is True
        assert record["compatibility"]["factory"]["mechanical_authority"] is False
        assert validate_custom_training_source_record(record)["route_id"] == route_id
    assert records[0].keys() == records[1].keys()
    assert records[0]["record_id"] != records[1]["record_id"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner_confirmation_id", ""),
        ("source_text", " leading"),
        ("source_anchor", "bad\x00anchor"),
        ("source_anchor", "bad\nanchor"),
        ("source_anchor", "bad\tanchor"),
        ("access_mode", "study mode"),
        ("training_types", ["unsupported"]),
        ("training_types", ["new_sphere", "new_sphere"]),
        ("target_record_ids", ["target", "target"]),
        ("record_id", "caller-controlled"),
        ("authority", "tianxia_rules"),
    ],
)
def test_custom_training_source_normalizer_rejects_unreviewed_or_caller_identity(catalog_environment, field, value):
    store, project_id = _project(catalog_environment, suffix=field.replace("_", "-"))
    envelope = _envelope(_target(store, project_id)["record_id"])
    if field in {"record_id", "authority"}:
        envelope[field] = value
    else:
        envelope[field] = value
    with pytest.raises(FoundryError) as exc:
        normalize_custom_training_source(envelope)
    assert exc.value.code == "CUSTOM_TRAINING_SOURCE_INPUT_INVALID"


def test_custom_training_source_seal_is_idempotent_and_does_not_change_project_revision(catalog_environment):
    store, project_id = _project(catalog_environment)
    target = _target(store, project_id)
    envelope = _envelope(target["record_id"])
    before_envelope = deepcopy(envelope)
    before_project = deepcopy(store.get_project(project_id)["project"])
    with store.db.connection() as conn:
        before_target_json = conn.execute(
            "SELECT record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, target["record_id"]),
        ).fetchone()["record_json"]

    first = _approve(store, project_id, envelope)
    second = _approve(store, project_id, envelope)

    assert envelope == before_envelope
    assert first["status"] == "inserted"
    assert second["status"] == "idempotent"
    assert first["record_id"] == second["record_id"]
    assert first["record_hash"] == second["record_hash"]
    assert first["source_hash"] == second["source_hash"]
    assert first["record_snapshot_hash_before"] != first["record_snapshot_hash_after"]
    assert second["record_snapshot_hash_before"] == second["record_snapshot_hash_after"]
    assert store.get_project(project_id)["project"] == before_project
    with store.db.connection() as conn:
        after_target_json = conn.execute(
            "SELECT record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, target["record_id"]),
        ).fetchone()["record_json"]
    assert after_target_json == before_target_json


def test_custom_training_source_requires_exact_one_time_approval(catalog_environment):
    store, project_id = _project(catalog_environment, suffix="approval-required")
    envelope = _envelope(_target(store, project_id)["record_id"])
    with pytest.raises(FoundryError) as error:
        store.seal_custom_training_source(project_id, envelope)
    assert error.value.code == "APPROVAL_CHALLENGE_REQUIRED"
    assert not hasattr(store, "add_project_locked_custom_training_source")

    issued = store.issue_custom_training_source_challenge(project_id, envelope)
    challenge = issued["challenge"]
    assert challenge["operation"] == CUSTOM_TRAINING_SOURCE_APPROVAL_OPERATION
    assert challenge["subject_type"] == CUSTOM_TRAINING_SOURCE_APPROVAL_SUBJECT_TYPE
    assert issued["binding"]["project_id"] == project_id
    assert issued["binding"]["record_id"] == issued["record_id"]
    assert issued["binding"]["record_hash"] == issued["record_hash"]
    assert issued["binding"]["source_hash"] == issued["source_hash"]
    assert issued["binding"]["project_lock_proof_hash"] == issued["project_lock_proof_hash"]
    with store.db.connection() as conn:
        row = conn.execute(
            "SELECT exact_bytes_hash,binding_hash,project_lock_hash,status FROM exact_approval_challenges WHERE challenge_id=?",
            (challenge["challenge_id"],),
        ).fetchone()
    assert row["exact_bytes_hash"] == hashlib.sha256(
        canonical_json(build_custom_training_source_record(normalize_custom_training_source(envelope))).encode("utf-8")
    ).hexdigest()
    assert row["binding_hash"] == sha256_json(issued["binding"])
    assert row["project_lock_hash"] == issued["project_lock_proof_hash"]
    assert row["status"] == "issued"

    with pytest.raises(FoundryError) as error:
        store.approve_and_seal_custom_training_source(
            project_id,
            envelope,
            challenge["challenge_id"],
            "wrong-nonce",
        )
    assert error.value.code == "APPROVAL_CHALLENGE_NONCE_INVALID"
    with store.db.connection() as conn:
        assert conn.execute(
            "SELECT status FROM exact_approval_challenges WHERE challenge_id=?",
            (challenge["challenge_id"],),
        ).fetchone()["status"] == "issued"

    receipt = store.approve_and_seal_custom_training_source(
        project_id,
        envelope,
        challenge["challenge_id"],
        challenge["nonce"],
    )
    assert receipt["approval"]["challenge_id"] == challenge["challenge_id"]
    assert receipt["approval"]["evidence_id"].startswith("approval.evidence.v2.")
    assert receipt["approval"]["principal_id"]
    assert receipt["approval"]["principal_hash"]
    with pytest.raises(FoundryError) as error:
        store.approve_and_seal_custom_training_source(
            project_id,
            envelope,
            challenge["challenge_id"],
            challenge["nonce"],
        )
    assert error.value.code == "APPROVAL_CHALLENGE_ALREADY_CONSUMED"


def test_custom_training_source_approval_binds_project_and_exact_envelope(catalog_environment):
    store, project_id = _project(catalog_environment, suffix="approval-binding")
    target = _target(store, project_id)
    envelope = _envelope(target["record_id"])
    issued = store.issue_custom_training_source_challenge(project_id, envelope)
    challenge = issued["challenge"]

    changed = deepcopy(envelope)
    changed["source_text"] += " changed"
    with pytest.raises(FoundryError) as error:
        store.approve_and_seal_custom_training_source(
            project_id,
            changed,
            challenge["challenge_id"],
            challenge["nonce"],
        )
    assert error.value.code in {
        "APPROVAL_CHALLENGE_SUBJECT_MISMATCH",
        "APPROVAL_CHALLENGE_BYTES_CHANGED",
    }
    with store.db.connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM project_locked_records WHERE project_id=? AND pack_id=?",
            (project_id, CUSTOM_TRAINING_SOURCE_PACK_ID),
        ).fetchone() is None

    other_store, other_project_id = _project(catalog_environment, suffix="approval-other-project")
    with pytest.raises(FoundryError) as error:
        other_store.approve_and_seal_custom_training_source(
            other_project_id,
            envelope,
            challenge["challenge_id"],
            challenge["nonce"],
        )
    assert error.value.code in {
        "APPROVAL_CHALLENGE_BINDING_CHANGED",
        "APPROVAL_CHALLENGE_PROJECT_LOCK_CHANGED",
        "APPROVAL_CHALLENGE_SUBJECT_MISMATCH",
    }
    with store.db.connection() as conn:
        assert conn.execute(
            "SELECT status FROM exact_approval_challenges WHERE challenge_id=?",
            (challenge["challenge_id"],),
        ).fetchone()["status"] == "issued"


def test_custom_training_source_approval_action_failure_rolls_back_challenge_and_insert(catalog_environment, monkeypatch):
    store, project_id = _project(catalog_environment, suffix="approval-rollback")
    envelope = _envelope(_target(store, project_id)["record_id"])
    issued = store.issue_custom_training_source_challenge(project_id, envelope)
    challenge = issued["challenge"]

    def fail(*_args, **_kwargs):
        raise FoundryError("TEST_APPROVAL_ACTION_FAILED", "synthetic action failure")

    monkeypatch.setattr(store, "_insert_custom_training_source", fail)
    with pytest.raises(FoundryError) as error:
        store.approve_and_seal_custom_training_source(
            project_id,
            envelope,
            challenge["challenge_id"],
            challenge["nonce"],
        )
    assert error.value.code == "TEST_APPROVAL_ACTION_FAILED"
    with store.db.connection() as conn:
        assert conn.execute(
            "SELECT status FROM exact_approval_challenges WHERE challenge_id=?",
            (challenge["challenge_id"],),
        ).fetchone()["status"] == "issued"
        assert conn.execute(
            "SELECT 1 FROM project_locked_records WHERE project_id=? AND record_id=?",
            (project_id, issued["record_id"]),
        ).fetchone() is None

    monkeypatch.undo()
    receipt = store.approve_and_seal_custom_training_source(
        project_id,
        envelope,
        challenge["challenge_id"],
        challenge["nonce"],
    )
    assert receipt["status"] == "inserted"


def test_custom_training_source_seal_requires_locked_supported_target_and_isolates_projects(catalog_environment):
    store, project_id = _project(catalog_environment, suffix="target")
    other_store, other_project_id = _project(catalog_environment, suffix="isolated")
    target = _target(store, project_id)
    missing = _envelope("not-locked.record")
    with pytest.raises(FoundryError) as exc:
        _approve(store, project_id, missing)
    assert exc.value.code == "PROJECT_CUSTOM_TRAINING_SOURCE_TARGET_INVALID"
    first = _approve(store, project_id, _envelope(target["record_id"]))
    with other_store.db.connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM project_locked_records WHERE project_id=? AND record_id=?",
            (other_project_id, first["record_id"]),
        ).fetchone() is None
    second = _approve(other_store, other_project_id, _envelope(target["record_id"]))
    assert second["record_id"] == first["record_id"]

    talent = _target(store, project_id, content_type="talent")
    wrong_type = _envelope(talent["record_id"])
    with pytest.raises(FoundryError) as exc:
        _approve(store, project_id, wrong_type)
    assert exc.value.code == "PROJECT_CUSTOM_TRAINING_SOURCE_TARGET_INVALID"


def test_custom_training_source_project_lock_proof_rejects_forged_extra(catalog_environment):
    store, project_id = _project(catalog_environment, suffix="forged")
    target = _target(store, project_id)
    record = build_custom_training_source_record(
        normalize_custom_training_source(_envelope(target["record_id"]))
    )
    forged = deepcopy(record)
    forged["display_name"] = "Forged display name"
    with store.db.transaction() as conn:
        conn.execute(
            "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
            (
                project_id,
                forged["record_id"],
                CUSTOM_TRAINING_SOURCE_PACK_ID,
                CUSTOM_TRAINING_SOURCE_PACK_VERSION,
                forged["record_hash"],
                canonical_json(forged),
            ),
        )
    with store.db.connection() as conn:
        with pytest.raises(FoundryError) as exc:
            store.project_lock_proof(conn, project_id)
    assert exc.value.code in {
        "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_INVALID",
        "PROJECT_LOCK_SNAPSHOT_MISMATCH",
        "CANONICAL_SCHEMA_VALIDATION_FAILED",
    }


def test_project_lock_proof_cache_scope_tracks_custom_and_forged_extra_snapshots(catalog_environment, monkeypatch):
    store, project_id = _project(catalog_environment, suffix="cache-scope")
    target = _target(store, project_id)
    calls = 0
    original_verify = project_store_module.verify_pack_seal

    def counted_verify(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_verify(*args, **kwargs)

    monkeypatch.setattr(project_store_module, "verify_pack_seal", counted_verify)
    with project_lock_proof_cache_scope():
        with store.db.connection() as conn:
            before = store.project_lock_proof(conn, project_id)
            repeated = store.project_lock_proof(conn, project_id)
        assert repeated == before
        assert calls == 1

        receipt = _approve(store, project_id, _envelope(target["record_id"]))
        assert receipt["lock_proof_hash_before"] != receipt["lock_proof_hash_after"]
        with store.db.connection() as conn:
            after = store.project_lock_proof(conn, project_id)
            repeated_after = store.project_lock_proof(conn, project_id)
        assert after == repeated_after
        assert after["lock_proof_hash"] == receipt["lock_proof_hash_after"]
        assert calls == 1

        forged_id = "tianxia.forged.extra.cache"
        with store.db.transaction() as conn:
            conn.execute(
                "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
                (project_id, forged_id, "tianxia.non_sphere.authority", "1", "0" * 64, "{}"),
            )
        with store.db.connection() as conn:
            with pytest.raises(FoundryError) as error:
                store.project_lock_proof(conn, project_id)
        assert error.value.code in {
            "PROJECT_LOCK_NON_SPHERE_AUTHORITY_INVALID",
            "PROJECT_LOCK_CUSTOM_TRAINING_SOURCE_INVALID",
            "PROJECT_LOCK_SNAPSHOT_INCOMPLETE",
            "CANONICAL_SCHEMA_VALIDATION_FAILED",
        }


def test_selected_ai_custom_training_source_requires_server_owned_proposal_without_side_effects(catalog_environment):
    store, project_id = _project(catalog_environment, suffix="selected-ai-policy")
    envelope = _envelope(
        _target(store, project_id)["record_id"],
        route_id="selected_ai_custom_training_source",
    )
    before_project = deepcopy(store.get_project(project_id)["project"])
    with store.db.connection() as conn:
        before_locked_count = conn.execute(
            "SELECT COUNT(*) FROM project_locked_records WHERE project_id=?",
            (project_id,),
        ).fetchone()[0]
        before_challenge_count = conn.execute(
            "SELECT COUNT(*) FROM exact_approval_challenges",
        ).fetchone()[0]

    def assert_denied(call):
        with pytest.raises(FoundryError) as error:
            call()
        assert error.value.code == "CUSTOM_TRAINING_SOURCE_AI_PROPOSAL_REQUIRED"
        assert error.value.status_code == 409
        assert "server-owned generated-proposal identifier" in error.value.message
        assert error.value.details == {
            "route_id": "selected_ai_custom_training_source",
            "required_binding": "server_owned_generated_proposal_identifier_and_exact_proposal_to_bytes_project_review_binding",
        }

    assert_denied(lambda: store.issue_custom_training_source_challenge(project_id, envelope))
    assert_denied(
        lambda: store.approve_and_seal_custom_training_source(
            project_id,
            envelope,
            "not-issued.selected-ai",
            "not-issued-selected-ai-nonce",
        )
    )
    assert_denied(
        lambda: store.seal_custom_training_source(
            project_id,
            envelope,
            challenge_id="not-issued.selected-ai",
            nonce="not-issued-selected-ai-nonce",
        )
    )
    assert_denied(lambda: store.seal_custom_training_source(project_id, envelope))

    assert store.get_project(project_id)["project"] == before_project
    with store.db.connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM project_locked_records WHERE project_id=?",
            (project_id,),
        ).fetchone()[0] == before_locked_count
        assert conn.execute(
            "SELECT COUNT(*) FROM exact_approval_challenges",
        ).fetchone()[0] == before_challenge_count
