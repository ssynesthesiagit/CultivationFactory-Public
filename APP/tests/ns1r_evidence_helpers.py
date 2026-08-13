from __future__ import annotations
from copy import deepcopy
import uuid

from app.core import canonical_json, sha256_json, utcnow
from content_packs.membership import create_direct_install_receipt, verify_pack_seal
from contracts.canonical import (
    canonical_project_document,
    canonical_project_hash,
    canonical_record_hash,
    normalize_core_catalog_record,
)
from security.integrity import IntegrityService

TEST_PACK_ID = "test.ns1r.authority"
TEST_PACK_VERSION = "1"


def install_authority_test_pack(db, service, *, include_exact_records: bool = True) -> None:
    """Install sealed TEST-only records with exact identities for NS1R targets.

    Keep the aggregate bundle as an unrelated containment decoy.  The runtime
    authority resolver must bind the exact per-target rows, never that bundle
    merely because it contains a target ID somewhere in its payload.
    """
    # The bundle is intentionally only a containment decoy.  Exact rows below
    # are the actual test lock members; keeping the decoy bounded avoids making
    # every disposable test database carry a duplicate source authority copy.
    dreamweaver_id = "tianxia.tradition.spirit.dreamweaver"
    spirit_path_id = "tianxia.path.spirit_awakening"
    authority = {
        "paths": {
            path_id: service.path_profiles[path_id]
            for path_id in service.path_profiles
        },
        "subpaths": {
            selection_id: service.subpaths[selection_id]
            for selection_id in service.subpaths
        },
        "methods": service.methods,
        "foundations": service.foundations,
        "backgrounds": service.backgrounds,
        "background_routes": service.background_route_authority,
        "spheres": service.cat2_spheres,
    }
    pack_hash = sha256_json({"pack_id": TEST_PACK_ID, "version": TEST_PACK_VERSION, "authority": authority})
    bundle_record = {
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
    bundle_record["record_hash"] = canonical_record_hash(bundle_record)
    records = [("records/ns1r-authority.json", bundle_record)]
    if include_exact_records:
        def exact_record(
            record_id: str,
            content_type: str,
            display_name: str,
            *,
            minimum_cl: int | None = None,
            owning_path_id: str | None = None,
            stage2_kind: str,
            stage2_channel: str,
            raw_record: dict | None = None,
        ) -> dict:
            projection = {
                "record_id": record_id,
                "content_type": content_type,
                "display_name": display_name,
                "pack_id": TEST_PACK_ID,
                "pack_version": TEST_PACK_VERSION,
                "authority": "test-only",
                "publication_state": "published",
                "source": {
                    "path": "tests/ns1r_evidence_helpers.py",
                    "anchor": f"test-authority:{record_id}",
                    "source_hash": sha256_json({"record_id": record_id, "authority": authority}),
                },
                "summary": display_name,
                "minimum_cl": minimum_cl,
                "acquisition_channels": [stage2_channel],
                "compatibility": {
                    "factory": {
                        "stage2_authority": {
                            "authority_complete": True,
                            "allowed_kinds": [stage2_kind],
                            "allowed_channels": [stage2_channel],
                            "rule_id": f"test.{record_id}.acquisition.v1",
                            **({"parent_path_id": owning_path_id, "owning_path_id": owning_path_id} if owning_path_id else {}),
                        },
                    },
                },
                "dependencies": [owning_path_id] if owning_path_id else [],
            }
            if owning_path_id:
                projection["owning_path_id"] = owning_path_id
                projection["parent_path_id"] = owning_path_id
            record = normalize_core_catalog_record(projection, pack_hash=pack_hash)
            if raw_record is not None:
                record["compatibility"]["factory"]["raw_projection"]["raw_record"] = deepcopy(raw_record)
                record["record_hash"] = canonical_record_hash(record)
            return record

        exact_authority_records = [
            (
                method_id,
                "method",
                exact_record(
                    method_id,
                    "cultivation_method",
                    row.get("name") or method_id,
                    stage2_kind="method_acquisition",
                    stage2_channel="method-acquisition",
                ),
            )
            for method_id, row in service.methods.items()
        ] + [
            (
                path_id,
                "path",
                exact_record(
                    path_id,
                    "path",
                    row.get("display_name") or path_id,
                    stage2_kind="path_acquisition",
                    stage2_channel="path-selection",
                ),
            )
            for path_id, row in service.path_profiles.items()
        ] + [
            (
                selection_id,
                "subpath",
                exact_record(
                    selection_id,
                    "subpath" if row.get("option_type") != "spirit_tradition" else "tradition",
                    row.get("display_name") or selection_id,
                    minimum_cl=service.subpath_minimum_cl(row),
                    owning_path_id=row["owning_path_id"],
                    stage2_kind="subpath_acquisition",
                    stage2_channel="subpath-selection",
                    raw_record=row,
                ),
            )
            for selection_id, row in service.subpaths.items()
        ] + [
            (
                foundation_id,
                "foundation",
                exact_record(
                    foundation_id,
                    "foundation",
                    row.get("display_name") or foundation_id,
                    stage2_kind="foundation_acquisition",
                    stage2_channel="foundation-selection",
                ),
            )
            for foundation_id, row in service.foundations.items()
        ]
        for record_id, content_type, authority_record in exact_authority_records:
            records.append((
                f"records/{content_type}/{record_id}.json",
                authority_record,
            ))
        for background_id, background in service.backgrounds.items():
            background_record = exact_record(
                background_id,
                "background",
                background.get("display_name") or background_id,
                stage2_kind="background_acquisition",
                stage2_channel="background-selection",
            )
            records.append((
                f"records/background/{background_id}.json",
                background_record,
            ))
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
            records=records,
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
