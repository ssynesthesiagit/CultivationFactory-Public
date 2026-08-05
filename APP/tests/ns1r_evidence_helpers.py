from __future__ import annotations
import uuid

from app.core import canonical_json, sha256_json, utcnow
from content_packs.membership import create_direct_install_receipt, verify_pack_seal
from contracts.canonical import canonical_project_document, canonical_project_hash, canonical_record_hash
from security.integrity import IntegrityService

TEST_PACK_ID = "test.ns1r.authority"
TEST_PACK_VERSION = "1"


def install_authority_test_pack(db, service) -> None:
    """Install one sealed TEST-only record containing every NS1R target ID."""
    authority = {
        "methods": service.methods,
        "paths": service.path_profiles,
        "subpaths": service.subpaths,
        "foundations": service.foundations,
        "backgrounds": service.backgrounds,
        "background_routes": service.background_route_authority,
        "spheres": service.cat2_spheres,
    }
    pack_hash = sha256_json({"pack_id": TEST_PACK_ID, "version": TEST_PACK_VERSION, "authority": authority})
    record = {
        "schema_version": "TianxiaFoundry.TestAuthorityBundle.v1",
        "record_id": TEST_PACK_ID,
        "content_type": "test_authority_bundle",
        "display_name": "NS1R immutable authority test bundle",
        "content_binding": {
            "pack_id": TEST_PACK_ID,
            "pack_version": TEST_PACK_VERSION,
            "pack_hash": pack_hash,
            "catalog_build_id": "catalog.test.ns1r",
        },
        "authority": authority,
    }
    record["record_hash"] = canonical_record_hash(record)
    now = utcnow()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO content_packs(pack_id,version,pack_hash,lifecycle_state,authority,installed_path,manifest_json,installed_at) VALUES(?,?,?,?,?,?,?,?)",
            (TEST_PACK_ID, TEST_PACK_VERSION, pack_hash, "published", "test-only", None, canonical_json({"test_fixture": True}), now),
        )
        create_direct_install_receipt(
            conn,
            pack_id=TEST_PACK_ID,
            version=TEST_PACK_VERSION,
            pack_hash=pack_hash,
            authority="test-only",
            trust_state="test_only",
            records=[("records/ns1r-authority.json", record)],
            installed_at=now,
            integrity=IntegrityService.for_database(db),
        )


def lock_authority_test_pack(db, project_id: str, target_cl: int) -> None:
    """Give a synthetic project the same immutable membership proof as production locks."""
    with db.transaction() as conn:
        seal = verify_pack_seal(
            conn,
            pack_id=TEST_PACK_ID,
            version=TEST_PACK_VERSION,
            integrity=IntegrityService.for_database(db),
        )
        conn.execute(
            """INSERT INTO project_content_locks(
               project_id,pack_id,version,pack_hash,locked_at,record_set_hash,payload_files_hash,
               install_receipt_hash,membership_snapshot_hash) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                project_id, seal.pack_id, seal.version, seal.pack_hash, utcnow(), seal.record_set_hash,
                seal.payload_files_hash, seal.install_receipt_hash, seal.membership_snapshot_hash,
            ),
        )
        conn.executemany(
            """INSERT INTO project_locked_records(
               project_id,record_id,pack_id,pack_version,record_hash,record_json) VALUES(?,?,?,?,?,?)""",
            [
                (project_id, row["record_id"], row["pack_id"], row["pack_version"], row["record_hash"], row["record_json"])
                for row in seal.records
            ],
        )
        project = canonical_project_document(
            project_id=project_id,
            name=project_id,
            revision=0,
            status="draft",
            created_at=utcnow(),
            updated_at=utcnow(),
            catalog_build_id="catalog.test.ns1r",
            pack_locks=[seal.lock_row()],
            user_locks=[{"field": "target_cl", "value": target_cl}],
        )
        conn.execute(
            """UPDATE projects SET status=?,project_json=?,canonical_project_hash=?,
               canonical_schema_version=?,contract_status='valid' WHERE project_id=?""",
            (
                project["status"], canonical_json(project), canonical_project_hash(project),
                project["schema_version"], project_id,
            ),
        )

def commit_authority_event(db, service, project_id: str, authority_type: str, targets: dict, amount_awarded: int|None=None, creation_authority: str='TEST_COMMITTED_EVENT') -> str:
    targets = dict(targets)
    if authority_type == 'subpath_access' and 'path_id' not in targets and targets.get('selection_id') in service.subpaths:
        targets['path_id'] = service.subpaths[targets['selection_id']]['owning_path_id']
    return service.commit_authority_event(project_id, authority_type, targets, amount_awarded=amount_awarded, creation_authority=creation_authority, idempotency_key=f"test.{authority_type}.{uuid.uuid4().hex}")["evidence_id"]

def access_evidence(db, service, project_id: str, method_id: str):
    if method_id=='METHOD-001': return []
    return [commit_authority_event(db,service,project_id,'method_access',{'method_id':method_id})]

def ap_award(db, service, project_id: str, method_id: str, target_cl: int, amount: int) -> str:
    return commit_authority_event(db,service,project_id,'ap_award',{'method_id':method_id,'target_cl':target_cl},amount)
