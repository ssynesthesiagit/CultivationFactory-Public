from pathlib import Path
import pytest
from app.core import Database, FoundryError, Settings
from non_sphere_authority import NonSphereAuthorityService
from tests.test_ns1r_non_sphere_authority import insert_project, QI
from tests.ns1r_evidence_helpers import access_evidence, ap_award, commit_authority_event
ROOT=Path(__file__).resolve().parents[1]

def make(tmp_path):
 s=Settings.from_env(ROOT,tmp_path/'data'); s.ensure_dirs(); db=Database(s); db.migrate(); return NonSphereAuthorityService(db),db

def test_unrelated_event_and_caller_assertions_cannot_mint_authority(tmp_path):
 svc,db=make(tmp_path); insert_project(db,'p',5)
 unrelated=commit_authority_event(db,svc,'p','background_choice',{'background_id':'bg'})
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
