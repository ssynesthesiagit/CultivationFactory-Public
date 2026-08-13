import json
import sqlite3
from pathlib import Path
import pytest
from app.core import Database, FoundryError, Settings
from non_sphere_authority import NonSphereAuthorityService
from tests.test_ns1r_non_sphere_authority import insert_project, QI, SPIRIT
from tests.ns1r_evidence_helpers import (
    access_evidence,
    ap_award,
    commit_authority_event,
    install_authority_test_pack,
)
ROOT=Path(__file__).resolve().parents[1]

def make(tmp_path, *, include_exact_records=True):
 s=Settings.from_env(ROOT,tmp_path/'data'); s.ensure_dirs(); db=Database(s); db.migrate(); svc=NonSphereAuthorityService(db); install_authority_test_pack(db, svc, include_exact_records=include_exact_records); return svc,db

def test_unrelated_event_and_caller_assertions_cannot_mint_authority(tmp_path):
    svc,db=make(tmp_path); insert_project(db,'p',5)
    background_id = "tianxia.background.abandoned_orphan"
    route_id = svc.background_route_authority[background_id]["route_options"][0]["background_route_record_id"]
    unrelated=commit_authority_event(db,svc,'p','background_choice',{'background_id':background_id,'route_ids':[route_id]})
    with pytest.raises(FoundryError) as exc: svc.resolve_evidence('p',unrelated,authority_type='method_access',targets={'method_id':'METHOD-002'})
    assert exc.value.code=='NS1R_EVIDENCE_TYPE_MISMATCH'
    with db.connection() as c: event_id=c.execute("SELECT source_identity FROM non_sphere_authority_evidence WHERE evidence_id=?",(unrelated,)).fetchone()[0]
    with pytest.raises(FoundryError) as exc: svc.commit_evidence('p',source_kind='PROJECT_EVENT',source_identity=event_id,authority_type='method_access',targets={'method_id':'METHOD-002'})
    assert exc.value.code=='NS1R_EVIDENCE_TYPE_MISMATCH'

def test_ap_atomic_idempotent_and_scoped(tmp_path):
 svc,db=make(tmp_path); insert_project(db,'p',5); svc.initialize_for_project('p',target_cl=5,path_ids=[QI],method_id='METHOD-001')
 eid=ap_award(db,svc,'p','METHOD-001',5,2)
 first=svc.allocate_advancement('p',{QI:1},evidence_id=eid,idempotency_key='retry-1')
 again=svc.allocate_advancement('p',{QI:1},evidence_id=eid,idempotency_key='retry-1')
 assert first==again
 assert svc.resolve_evidence('p',eid)['remaining_amount']==1
 with pytest.raises(FoundryError) as exc: svc.allocate_advancement('p',{QI:2},evidence_id=eid,idempotency_key='retry-2')
 assert exc.value.code=='NS1R_AP_AWARD_INSUFFICIENT'
 with pytest.raises(FoundryError) as exc: svc.allocate_advancement('p',{QI:1},evidence_id=eid,idempotency_key='retry-1') if False else svc.resolve_evidence('other',eid)
 assert exc.value.code in {'NS1R_EVIDENCE_NOT_FOUND','PROJECT_NOT_FOUND'}

def test_export_contains_immutable_evidence_ledger(tmp_path):
 svc,db=make(tmp_path); insert_project(db,'p',5); access=access_evidence(db,svc,'p','METHOD-002'); svc.initialize_for_project('p',target_cl=5,method_id='METHOD-002',access_source_records=access)
 payload=svc.export_state('p')
 assert payload['schema']=='Tianxia.NonSphereStateExport.v2'
 assert len(payload['evidence_ledger']['evidence'])==1
 state,state_hash,ledger=svc.validate_import_payload('p',payload)
 assert state_hash==payload['state_hash'] and ledger==payload['evidence_ledger']


def test_containment_decoy_cannot_satisfy_exact_path_target(tmp_path):
    svc, db = make(tmp_path, include_exact_records=False)
    insert_project(db, "exact-path")
    with pytest.raises(FoundryError) as exc:
        commit_authority_event(
            db,
            svc,
            "exact-path",
            "subpath_access",
            {"path_id": SPIRIT, "selection_id": "tianxia.tradition.spirit.dreamweaver"},
        )
    assert exc.value.code == "NS1R_LOCKED_TARGET_RESOLUTION_FAILED"
    assert exc.value.details["role"] == "path"
    assert exc.value.details["matches"] == []


def test_exact_spirit_path_and_dreamweaver_records_bind_uniquely(tmp_path):
    svc, db = make(tmp_path)
    insert_project(db, "exact-spirit")
    result = svc.commit_authority_event(
        "exact-spirit",
        "subpath_access",
        {"path_id": SPIRIT, "selection_id": "tianxia.tradition.spirit.dreamweaver"},
        creation_authority="TEST_COMMITTED_EVENT",
        idempotency_key="exact-spirit-subpath-access",
    )
    assert result["targets"] == {
        "path_id": SPIRIT,
        "selection_id": "tianxia.tradition.spirit.dreamweaver",
    }
    with db.connection() as conn:
        event = conn.execute(
            "SELECT event_json FROM events WHERE project_id=? AND event_id=?",
            ("exact-spirit", result["source_identity"]),
        ).fetchone()
    event_doc = json.loads(event["event_json"])
    bindings = {
        row["role"]: row
        for row in event_doc["advancement"]["authority_bindings"]
        if row["role"] != "project_lock_proof"
    }
    assert bindings["path"]["record_id"] == SPIRIT
    assert bindings["restricted_selection"]["record_id"] == "tianxia.tradition.spirit.dreamweaver"


def test_nested_foundation_and_background_roles_bind_parent_record(tmp_path):
    svc, db = make(tmp_path)
    insert_project(db, "nested-roles")
    method_id = "METHOD-073"
    foundation_id = "divine_king_body_v0_2B"
    interface = svc.foundations[foundation_id]["compatibility_traits"]["repair_interfaces"][0]
    practice = interface["repair_practices"][0].removeprefix("Repair: ")
    foundation_event = svc.commit_authority_event(
        "nested-roles",
        "repair_completion",
        {
            "method_id": method_id,
            "foundation_id": foundation_id,
            "repair_interface": interface["tag"],
            "repair_practice_name": practice,
        },
        creation_authority="TEST_COMMITTED_EVENT",
        idempotency_key="nested-foundation-repair",
    )
    with db.connection() as conn:
        foundation_doc = json.loads(conn.execute(
            "SELECT event_json FROM events WHERE project_id=? AND event_id=?",
            ("nested-roles", foundation_event["source_identity"]),
        ).fetchone()["event_json"])
    foundation_bindings = [
        row for row in foundation_doc["advancement"]["authority_bindings"]
        if row["role"] != "project_lock_proof"
    ]
    assert {row["role"]: row["record_id"] for row in foundation_bindings} == {
        "method": method_id,
        "foundation": foundation_id,
        "repair_interface": foundation_id,
        "repair_practice": foundation_id,
    }

    background_id = next(row for row in svc.backgrounds if row == "tianxia.background.abandoned_orphan")
    route_id = svc.background_route_authority[background_id]["route_options"][0]["background_route_record_id"]
    background_event = svc.commit_authority_event(
        "nested-roles",
        "background_choice",
        {"background_id": background_id, "route_ids": [route_id]},
        creation_authority="TEST_COMMITTED_EVENT",
        idempotency_key="nested-background-route",
    )
    with db.connection() as conn:
        background_doc = json.loads(conn.execute(
            "SELECT event_json FROM events WHERE project_id=? AND event_id=?",
            ("nested-roles", background_event["source_identity"]),
        ).fetchone()["event_json"])
    background_bindings = [
        row for row in background_doc["advancement"]["authority_bindings"]
        if row["role"] != "project_lock_proof"
    ]
    assert {row["role"]: row["record_id"] for row in background_bindings} == {
        "background": background_id,
        "background_route": background_id,
    }


def test_duplicate_exact_row_condition_is_rejected_fail_closed(tmp_path):
    svc, db = make(tmp_path)
    insert_project(db, "duplicate-exact")
    with db.connection() as conn:
        row = conn.execute(
            "SELECT record_id,pack_id,pack_version,record_hash,record_json FROM project_locked_records WHERE project_id=? AND record_id=?",
            ("duplicate-exact", SPIRIT),
        ).fetchone()
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO project_locked_records(project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)",
                (
                    "duplicate-exact",
                    row["record_id"],
                    row["pack_id"],
                    row["pack_version"],
                    row["record_hash"],
                    row["record_json"],
                ),
            )
    result = svc.commit_authority_event(
        "duplicate-exact",
        "subpath_access",
        {"path_id": SPIRIT, "selection_id": "tianxia.tradition.spirit.dreamweaver"},
        creation_authority="TEST_COMMITTED_EVENT",
        idempotency_key="duplicate-exact-still-unique",
    )
    assert result["targets"]["path_id"] == SPIRIT


@pytest.mark.parametrize(
    ("authority_type", "targets", "expected_code"),
    [
        ("method_access", {"method_id": "METHOD-404"}, "NS1R_AUTHORITY_TARGET_UNKNOWN"),
        ("subpath_access", {"path_id": "tianxia.path.unknown", "selection_id": "tianxia.tradition.spirit.dreamweaver"}, "NS1R_AUTHORITY_TARGET_UNKNOWN"),
        ("subpath_access", {"path_id": SPIRIT, "selection_id": "tianxia.tradition.unknown"}, "NS1R_AUTHORITY_TARGET_UNKNOWN"),
        ("repair_completion", {"method_id": "METHOD-073", "foundation_id": "divine_king_body_v0_2B", "repair_interface": "unknown-interface", "repair_practice_name": "unknown-practice"}, "NS1R_AUTHORITY_TARGET_UNKNOWN"),
        ("background_choice", {"background_id": "tianxia.background.unknown", "route_ids": []}, "NS1R_AUTHORITY_TARGET_UNKNOWN"),
        ("background_choice", {"background_id": "tianxia.background.abandoned_orphan", "route_ids": ["unknown-route"]}, "NS1R_AUTHORITY_TARGET_UNKNOWN"),
    ],
)
def test_unknown_authority_target_values_fail_through_structured_validation(tmp_path, authority_type, targets, expected_code):
    service, db = make(tmp_path)
    insert_project(db, f"unknown-{authority_type}")
    with pytest.raises(FoundryError) as exc:
        service.commit_authority_event(
            f"unknown-{authority_type}",
            authority_type,
            targets,
            creation_authority="TEST_COMMITTED_EVENT",
            idempotency_key=f"unknown-target-{authority_type}",
        )
    assert exc.value.code == expected_code


def test_unknown_transformation_route_fails_with_foundry_error(tmp_path):
    service, db = make(tmp_path)
    insert_project(db, "unknown-transformation")
    foundation_id = next(
        foundation_id
        for foundation_id, foundation in service.foundations.items()
        if (foundation.get("compatibility_traits") or {}).get("transformation_routes")
    )
    with pytest.raises(FoundryError) as exc:
        service.commit_authority_event(
            "unknown-transformation",
            "transformation_completion",
            {
                "method_id": "METHOD-073",
                "foundation_id": foundation_id,
                "transformation_route": "unknown-transformation-route",
                "completion_type": "FOUNDATION_CHALLENGE",
            },
            creation_authority="TEST_COMMITTED_EVENT",
            idempotency_key="unknown-transformation-route",
        )
    assert exc.value.code == "NS1R_AUTHORITY_TARGET_UNKNOWN"
