from __future__ import annotations

import sqlite3
from copy import deepcopy

import pytest

from app.core import FoundryError, canonical_json
from character_creation.response_materialization import RESPONSE_SCHEMA
from character_creation.service import CharacterCreationExecutionService


def _preferred() -> dict:
    return {
        "schema": RESPONSE_SCHEMA,
        "request_sha256": "a" * 64,
        "selection_intent": {"by_slot": {"path_choice": ["PATH-QI"]}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [{"sphere_id": "SPHERE-FIRE", "talent_id": "TALENT-FLAME"}],
            "ordinary_talent_ids": ["TALENT-BURNING"],
            "insight_occurrences": [],
        },
        "bounded_choices": {},
        "owner_descriptive_fields": {"identity": {"name": "Semantic Test"}, "concept": "Bounded"},
    }


def test_preferred_response_is_semantic_and_top_level_closed() -> None:
    plan = _preferred()
    parsed, raw = CharacterCreationExecutionService._parse_plan(canonical_json(plan))
    assert parsed == plan
    assert raw == canonical_json(plan).encode("utf-8")

    backend_rows = deepcopy(plan)
    backend_rows["acquisition_intent"] = [{"kind": "level_talent_acquisition", "record_id": "TALENT-BURNING"}]
    with pytest.raises(FoundryError) as acquisition_error:
        CharacterCreationExecutionService._parse_plan(canonical_json(backend_rows))
    assert acquisition_error.value.code == "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID"

    asserted_events = deepcopy(plan)
    asserted_events["stage2_proposal"] = {"choices": []}
    with pytest.raises(FoundryError) as shape_error:
        CharacterCreationExecutionService._parse_plan(canonical_json(asserted_events))
    assert shape_error.value.code == "CG1_PREFERRED_RESPONSE_SHAPE_INVALID"

    bounded = deepcopy(plan)
    bounded["bounded_choices"] = {"background_ability_amount": 5}
    with pytest.raises(FoundryError) as bounded_error:
        CharacterCreationExecutionService._validate_preferred_bounded_fields(
            {"request": {"bounded_choice_contract": {"fields": {}}}},
            bounded,
        )
    assert bounded_error.value.code == "CG1_PREFERRED_RESPONSE_BOUNDED_FIELD_INVALID"


def test_attempt_history_update_and_delete_triggers_are_append_only(fresh_db) -> None:
    project_json = canonical_json(
        {
            "project_id": "REC1-P1CR3-MIGRATION-PROJECT",
            "working_name": "Migration Test",
            "revision": 0,
            "content_lock": {"lock_hash": "lock"},
        }
    )
    with fresh_db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(
                project_id,working_name,status,revision,created_at,updated_at,
                target_factory_version,target_candidate_schema_version,target_gm_screen_version,
                catalog_build_hash,quality_target,project_json,compatibility_projection_status,
                compile_status,consumer_verification_status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "REC1-P1CR3-MIGRATION-PROJECT",
                "Migration Test",
                "draft",
                0,
                "now",
                "now",
                "x",
                "x",
                "x",
                None,
                "x",
                project_json,
                "x",
                "x",
                "x",
            ),
        )
        conn.execute(
            """INSERT INTO character_creation_runs(
                run_id,project_id,starting_revision,execution_mode,idempotency_key,
                request_json,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                "cg1.run.rec1-p1cr3-migration",
                "REC1-P1CR3-MIGRATION-PROJECT",
                0,
                "MANUAL_CHAT",
                "migration-test-key",
                "{}",
                "WAITING_FOR_RESPONSE",
                "now",
                "now",
            ),
        )
        conn.execute(
            """INSERT INTO character_creation_attempt_history(
                attempt_id,run_id,project_id,ordinal,action_type,status,created_at
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "attempt.rec1-p1cr3-migration",
                "cg1.run.rec1-p1cr3-migration",
                "REC1-P1CR3-MIGRATION-PROJECT",
                1,
                "REQUEST_CREATED",
                "WAITING_FOR_RESPONSE",
                "now",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError):
        with fresh_db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_attempt_history SET status=? WHERE attempt_id=?",
                ("MUTATED", "attempt.rec1-p1cr3-migration"),
            )
    with pytest.raises(sqlite3.IntegrityError):
        with fresh_db.transaction() as conn:
            conn.execute(
                "DELETE FROM character_creation_attempt_history WHERE attempt_id=?",
                ("attempt.rec1-p1cr3-migration",),
            )
    with fresh_db.connection() as conn:
        row = conn.execute(
            "SELECT status FROM character_creation_attempt_history WHERE attempt_id=?",
            ("attempt.rec1-p1cr3-migration",),
        ).fetchone()
    assert row["status"] == "WAITING_FOR_RESPONSE"
