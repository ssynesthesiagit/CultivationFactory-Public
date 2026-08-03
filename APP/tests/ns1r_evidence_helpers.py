from __future__ import annotations
import uuid

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
