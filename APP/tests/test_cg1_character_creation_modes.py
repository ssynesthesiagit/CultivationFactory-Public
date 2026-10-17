from __future__ import annotations
import json
import hashlib
import io
import zipfile
from pathlib import Path
import pytest
from app.core import Database, Settings, canonical_json, FoundryError, sha256_bytes, sha256_json
from character_creation import CharacterCreationExecutionService
import character_creation.service as cc_service

class Projects:
    def __init__(self,db): self.db=db; self.lock_proof_calls=[]
    def get_project(self,pid):
        with self.db.connection() as c: row=c.execute('select revision,project_json from projects where project_id=?',(pid,)).fetchone()
        p=json.loads(row['project_json']); p['revision']=row['revision']; return {'project':p}
    def project_lock_proof(self,conn,pid):
        self.lock_proof_calls.append(pid); return {'project_id':pid}

class Stage1:
    def __init__(self,db): self.db=db
    def generate_prompt(self,pid):
        p=Projects(self.db).get_project(pid)['project']; return {'prompt_id':'prompt.same','project_id':pid,'project_revision':p['revision'],'prompt_sha256':'a'*64,'created_at':'now','prompt_text':'same'}
    def validate_response(self,prompt_id,text,prior_attempt_id=None):
        d=json.loads(text); valid=d.get('path')=='PATH-QI'
        return {'attempt_id':'attempt.'+sha256_json(d)[:12],'response_sha256':sha256_json(d),'validation':{'valid':valid,'errors':[] if valid else [{'code':'BAD_PATH'}],'warnings':[]}}
    def approve_and_commit(self,attempt_id,approved_by):
        with self.db.transaction() as c:
            row=c.execute('select revision,project_json from projects where project_id="p"').fetchone(); p=json.loads(row['project_json']); p['revision']=row['revision']+1
            c.execute('update projects set revision=?,project_json=? where project_id="p"',(row['revision']+1,canonical_json(p)))
        return {'commit_id':'s1.'+attempt_id}

class Stage2:
    def __init__(self,db): self.db=db; self.payload={}
    def create_proposal(self,p): self.payload=p; return {'proposal_id':'proposal.'+sha256_json(p)[:12]}
    def validate_proposal(self,pid): return {'valid':self.payload.get('valid',True),'proposal_id':pid,'ledger':self.payload.get('choices',[])}
    def issue_approval_challenge(self,pid): return {'challenge_id':'c','nonce':'n'}
    def approve_proposal(self,*a,**k): return {'approved':True}
    def commit_proposal(self,pid):
        with self.db.transaction() as c:
            row=c.execute('select revision,project_json from projects where project_id="p"').fetchone(); p=json.loads(row['project_json']); p['revision']=row['revision']+1
            c.execute('update projects set revision=?,project_json=? where project_id="p"',(row['revision']+1,canonical_json(p)))
        return {'commit_id':'s2.'+pid}

class Artifact:
    def __init__(self,db,name): self.db=db; self.name=name
    def _out(self,pid,**kwargs):
        p=Projects(self.db).get_project(pid)['project']; out={'service':self.name,'project_id':pid,'revision':p['revision'],'stage1':p.get('stage1'),'stage2':p.get('stage2')}
        if self.name == 'projection':
            snapshot = kwargs.get('choice_snapshot')
            assert snapshot and snapshot['canonical_project_id'] == pid
            assert snapshot['snapshot_sha256']
            out['typed_choice_snapshot_sha256'] = snapshot['snapshot_sha256']
        path=self.db.settings.exports_dir/f'{self.name}.json'; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(canonical_json(out),encoding='utf-8')
        return {**out,'path':str(path),'sha256':sha256_json(out)}
    build=compile=current=sheet=export=build_for_project=build_verified=verified_status=_out

class Consumer:
    def verify(self,receipt): return {'verified':True,'source_sha256':receipt['sha256'],'service':'gm_consumer'}

class Provider:
    def __init__(self,plan,ready=True): self.plan=plan; self.calls=[]; self.ready=ready
    def status(self): return {'ready':self.ready,'provider_id':'deepseek'}
    def complete_json(self,*,prompt_text,system_message,purpose):
        prompt=json.loads(prompt_text); self.calls.append(prompt)
        value=json.loads(canonical_json(self.plan)); value['request_sha256']=prompt['binding']['request_sha256']
        response_text=canonical_json(value)
        return {
            'provider_id':'deepseek','purpose':purpose,'model':'deepseek-chat',
            'request_sha256':sha256_bytes(prompt_text.encode('utf-8')),
            'response_sha256':sha256_bytes(canonical_json({'content':response_text}).encode('utf-8')),
            'completion_sha256':sha256_bytes(response_text.encode('utf-8')),
            'response_text':response_text,'finish_reason':'stop',
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2},'value':value,
        }


class PreflightProvider:
    """A transport double that stops at the server-side request preflight."""

    def __init__(self):
        self.calls = []

    def status(self):
        return {'ready': True, 'provider_id': 'deepseek'}

    def complete_json(self, *, prompt_text, system_message, purpose, max_request_bytes):
        self.calls.append({
            'prompt_text': prompt_text,
            'system_message': system_message,
            'purpose': purpose,
            'max_request_bytes': max_request_bytes,
        })
        raise FoundryError(
            'AI_PROVIDER_REQUEST_TOO_LARGE',
            'The canonical provider request exceeded its exact byte limit; no network request was made.',
            details={
                'request_bytes': max_request_bytes + 1,
                'max_request_bytes': max_request_bytes,
                'provider_called': False,
            },
            status_code=413,
        )

# Request assembly freezes the compiler-backed Method/Foundation authority
# from the pinned vendor Factory (compiler_selection_authority, 23237ef), so
# even these stub-pipeline tests need a real configured vendor root and a
# content lock that names the pinned core pack.  The session-scoped
# ``factory_environment`` fixture configures the bundled Factory once.
_PINNED_VENDOR_DIR: Path | None = None


@pytest.fixture(autouse=True)
def _pinned_vendor(factory_environment):
    global _PINNED_VENDOR_DIR
    _PINNED_VENDOR_DIR = Path(factory_environment["settings"].vendor_dir)


def pinned_content_lock() -> dict:
    from app.core import CORE_PACK_ID, CORE_PACK_VERSION
    from character_creation.compiler_selection_authority import PINNED_CORE_PACK_HASH
    return {
        "catalog_build_id": "CG1-MODES-TEST",
        "lock_hash": "a" * 64,
        "packs": [{"pack_id": CORE_PACK_ID, "version": CORE_PACK_VERSION, "content_hash": PINNED_CORE_PACK_HASH}],
    }


def stub_project_document() -> dict:
    """A canonical project document; request assembly reads its typed fields."""
    from project_store.service import canonical_project_document
    lock = pinned_content_lock()
    return canonical_project_document(
        project_id='p', name='P', revision=0, status='draft', created_at='n', updated_at='n',
        catalog_build_id=lock['catalog_build_id'], pack_locks=[{**pack, 'pack_hash': pack['content_hash']} for pack in lock['packs']],
        # Builder projects always persist the owner's target CL as an
        # immutable user lock; delegated creation refuses a project without
        # one (885d87ea, REC1-P1AR2).
        user_locks=[{"field": "target_cl", "value": 1}], source_inputs=[], event_count=0, head_hash=None,
    )


def settings(root:Path):
    d=root/'data'; return Settings(root_dir=Path(__file__).parents[1],data_dir=d,db_path=d/'foundry.sqlite3',inbox_dir=d/'inbox',exports_dir=d/'exports',packs_dir=d/'content_packs',vendor_dir=_PINNED_VENDOR_DIR or d/'vendor',logs_dir=d/'logs',backups_dir=d/'backups',security_dir=d/'security')

def pipeline(db):
    return {'stage1':Stage1(db),'stage2':Stage2(db),'projections':Artifact(db,'projection'),'character_sheets':Artifact(db,'character_sheet'),'factory_authoring':Artifact(db,'factory_authoring'),'gm_exports':Artifact(db,'gm_model'),'gm_consumer':Consumer(),'portable_characters':Artifact(db,'portable_character'),'combat_readiness':Artifact(db,'combat')}

def plan(*,valid=True,combat=False):
    return {'schema':'TianxiaFoundry.CharacterCreationPlan.v2','stage1_response':{'path':'PATH-QI'},'target_cl':1,'stage2_proposal':{'project_id':'p','valid':valid,'choices':[{'target_cl':1,'kind':'qi'}]},'owner_descriptive_fields':{'identity':{'name':'Test'},'concept':'Qi'},'uncertainties':[],'fallbacks':[],'output_profile':{'combat_ready':combat}}

def bound_plan(run,value=None):
    result=json.loads(canonical_json(value or plan()))
    result['request_sha256']=run['request']['request_sha256']
    return result


def test_materialize_constructed_arts_skips_authority_lookup_without_relevant_rows():
    service = object.__new__(CharacterCreationExecutionService)

    class ProjectsProbe:
        def get_project(self, _project_id):
            raise AssertionError("ordinary Stage 2 choices must not load project authority")

    service.db = object()
    service.projects = ProjectsProbe()
    service._locked_records_for_project = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("ordinary Stage 2 choices must not load locked records")
    )
    ordinary_plan = {
        "stage2_proposal": {
            "choices": [{"kind": "qi", "record_id": "tianxia.sphere.fire"}],
        },
    }

    assert service._materialize_constructed_arts(
        {"project_id": "p"},
        service.db,
        phase="scratch_compile",
        plan=ordinary_plan,
    ) is None


def test_materialize_constructed_arts_keeps_authority_lookup_for_source_access():
    service = object.__new__(CharacterCreationExecutionService)
    calls = {"project": [], "records": []}

    class ProjectsProbe:
        def get_project(self, project_id):
            calls["project"].append(project_id)
            return {"project": {"project_id": project_id, "revision": 1}}

    def records_probe(project_id, **kwargs):
        calls["records"].append((project_id, kwargs.get("authority_db")))
        return {}

    service.db = object()
    service.projects = ProjectsProbe()
    service._locked_records_for_project = records_probe
    source_plan = {
        "stage2_proposal": {
            "choices": [{
                "kind": "training_source_access",
                "record_id": "manual.alt-id",
            }],
        },
    }

    assert service._materialize_constructed_arts(
        {"project_id": "p"},
        service.db,
        phase="scratch_compile",
        plan=source_plan,
    ) is None
    assert calls["project"] == ["p"]
    assert calls["records"] == [("p", service.db)]


def make(tmp:Path,p=None,ready=True):
    db=Database(settings(tmp)); db.migrate()
    with db.transaction() as c:
        c.execute("INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,target_factory_version,target_candidate_schema_version,target_gm_screen_version,catalog_build_hash,quality_target,project_json,compatibility_projection_status,compile_status,consumer_verification_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('p','P','draft',0,'n','n','x','x','x',None,'x',canonical_json(stub_project_document()),'x','x','x'))
    live=pipeline(db); provider=Provider(p or plan(),ready)
    svc=CharacterCreationExecutionService(db,stage1=live['stage1'],provider=provider,project_store=Projects(db),stage2=live['stage2'],character_sheets=live['character_sheets'],gm_exports=live['gm_exports'],portable_characters=live['portable_characters'],factory_authoring=live['factory_authoring'],projections=live['projections'],gm_consumer=live['gm_consumer'],combat_readiness=live['combat_readiness'],pipeline_factory=pipeline,owner_principal='owner')
    return svc,provider,db

def snapshot(db):
    with db.connection() as c: rows=[tuple(r) for r in c.execute('select project_id,revision,project_json from projects order by project_id')]
    # logs/, backups/ and diagnostics/ are process-generated (timing receipts,
    # pre-migration database copies, compile checkpoints), never canonical state.
    files={x.relative_to(db.settings.data_dir).as_posix():x.read_bytes() for x in db.settings.data_dir.rglob('*') if x.is_file() and x.name != db.settings.db_path.name and not x.name.endswith(('-wal','-shm')) and x.relative_to(db.settings.data_dir).parts[0] not in {'logs','backups','diagnostics'}}
    return rows,files

def test_three_modes_real_two_scratch_parity_and_no_preview_mutation(tmp_path):
    ids=[]
    for mode in ('MANUAL_CHAT','STANDARD_API','AUTO_FINALIZE_WHEN_CLEAN'):
        svc,provider,db=make(tmp_path/mode); before=snapshot(db)
        run=svc.start('p',execution_mode=mode,idempotency_key='same-key-123')
        if mode=='MANUAL_CHAT': run=svc.submit_manual(run['run_id'],response_text=canonical_json(bound_plan(run)),request_sha256=run['request']['request_sha256'])
        assert snapshot(db)==before
        assert run['dry_run']['independent_compilations']==2 and run['dry_run']['deterministic']
        frozen = run['request']['typed_choice_snapshot']
        assert frozen['canonical_project_id']=='p'
        assert frozen['display_name_content']=='P'
        assert run['dry_run']['typed_choice_snapshot']==frozen
        # candidate_identity also hashes the plan's own request_sha256, and each
        # run's request is unique (mode-bound idempotency binding, per-run
        # manual-collection nonce), so mode parity is checked on the compiled
        # artifact identities and the frozen choice snapshot.
        ids.append(canonical_json({'identities':run['dry_run']['identities'],'snapshot':frozen['snapshot_sha256']}))
        assert run['status']=='READY_FOR_REVIEW'
        with pytest.raises(FoundryError) as exc:
            svc.finalize(run['run_id'])
        assert exc.value.code == 'CG1_FINALIZATION_ROLLED_BACK'
        assert svc.get(run['run_id'])['status'] == 'READY_FOR_REVIEW'
    assert len(set(ids))==1


def test_finalize_without_production_release_rolls_back_and_never_persists_clean_status(tmp_path):
    svc, _, db = make(tmp_path / "no-production-release")
    run = svc.start("p", execution_mode="STANDARD_API", idempotency_key="no-release-finalize-123")
    before = snapshot(db)
    with pytest.raises(FoundryError) as exc:
        svc.finalize(run["run_id"])
    assert exc.value.code == "CG1_FINALIZATION_ROLLED_BACK"
    assert snapshot(db) == before
    assert svc.get(run["run_id"])["status"] == "READY_FOR_REVIEW"

def test_scratch_compile_binds_the_incoming_response_hash(tmp_path,monkeypatch):
    svc,_,_=make(tmp_path)
    observed={}
    original=svc._validate_and_compile

    def capture(run,response_text,**kwargs):
        observed['response_sha256']=run['response'].get('response_sha256')
        return original(run,response_text,**kwargs)

    monkeypatch.setattr(svc,'_validate_and_compile',capture)
    run=svc.start('p',execution_mode='MANUAL_CHAT',idempotency_key='response-binding-123')
    response_text=canonical_json(bound_plan(run))
    submitted=svc.submit_manual(run['run_id'],response_text=response_text,request_sha256=run['request']['request_sha256'])
    assert submitted['status']=='READY_FOR_REVIEW'
    assert observed['response_sha256']==sha256_bytes(response_text.encode('utf-8'))

def test_candidate_identity_excludes_process_local_approval_envelope_only():
    substantive = {
        'schema_version': 'TianxiaFoundry.Stage2TerminalCommitReceipt.v2',
        'approved_principal_hash': 'a' * 64,
        'approved_proposal_hash': 'b' * 64,
        'approved_validation_hash': 'c' * 64,
        'terminal_mechanical_state_hash': 'd' * 64,
    }
    first = {
        **substantive,
        'approval_evidence_id': 'approval.evidence.v2.process-one',
        'binding_set_hash': '1' * 64,
        'integrity_mac': '2' * 64,
        'terminal_attempt_id': 'attempt-process-one',
        'terminal_projection_hash': '3' * 64,
        'terminal_projection_json': '{"process_epoch_id":"one"}',
    }
    second = {
        **substantive,
        'approval_evidence_id': 'approval.evidence.v2.process-two',
        'binding_set_hash': '4' * 64,
        'integrity_mac': '5' * 64,
        'terminal_attempt_id': 'attempt-process-two',
        'terminal_projection_hash': '6' * 64,
        'terminal_projection_json': '{"process_epoch_id":"two"}',
    }
    assert CharacterCreationExecutionService._identity_payload(first) == substantive
    assert CharacterCreationExecutionService._identity_payload(second) == substantive
    changed = {**second, 'terminal_mechanical_state_hash': 'e' * 64}
    assert CharacterCreationExecutionService._identity_payload(changed) != substantive


def test_candidate_identity_excludes_actual_nested_stage2_receipt_process_values():
    first = {
        "committed": True,
        "receipt": {
            "approval_challenge_id": "challenge-one",
            "approval_evidence_id": "evidence-one",
            "binding_set_hash": "binding-one",
            "terminal_projection_hash": "projection-one",
            "terminal_projection_json": '{"process":"one"}',
            "integrity_mac": "mac-one",
            "integrity_key_id": "key-one",
            "integrity_domain": "domain-one",
            "terminal_attempt_id": "attempt-one",
            "created_at": "2026-08-10T00:00:01Z",
            "completed_at": "2026-08-10T00:00:02Z",
            "approval_evidence": {
                "evidence_id": "evidence-one",
                "projection_hash": "approval-projection-one",
                "mac": "approval-mac-one",
            },
            "approved_proposal_hash": "proposal-one",
            "event_hashes_json": '["event-hash-one"]',
            "state_after_hash": "state-one",
            "terminal_mechanical_state_hash": "mechanics-one",
            "source_binding": {"source_hash": "source-one", "source_path": "catalog/record.json"},
        },
        "project": {"canonical_project_hash": "project-one"},
        "replay": {"state_hash": "replay-one"},
    }
    second = json.loads(json.dumps(first))
    receipt = second["receipt"]
    receipt.update({
        "approval_challenge_id": "challenge-two",
        "approval_evidence_id": "evidence-two",
        "binding_set_hash": "binding-two",
        "terminal_projection_hash": "projection-two",
        "terminal_projection_json": '{"process":"two"}',
        "integrity_mac": "mac-two",
        "integrity_key_id": "key-two",
        "integrity_domain": "domain-two",
        "terminal_attempt_id": "attempt-two",
        "created_at": "2026-08-11T00:00:01Z",
        "completed_at": "2026-08-11T00:00:02Z",
    })
    receipt["approval_evidence"].update({
        "evidence_id": "evidence-two",
        "projection_hash": "approval-projection-two",
        "mac": "approval-mac-two",
    })
    assert CharacterCreationExecutionService._identity_payload(first) == CharacterCreationExecutionService._identity_payload(second)

    substantive = json.loads(json.dumps(first))
    substantive["receipt"]["event_hashes_json"] = '["event-hash-two"]'
    assert CharacterCreationExecutionService._identity_payload(first) != CharacterCreationExecutionService._identity_payload(substantive)

    state_change = json.loads(json.dumps(first))
    state_change["receipt"]["state_after_hash"] = "state-two"
    assert CharacterCreationExecutionService._identity_payload(first) != CharacterCreationExecutionService._identity_payload(state_change)

    source_change = json.loads(json.dumps(first))
    source_change["receipt"]["source_binding"]["source_hash"] = "source-two"
    assert CharacterCreationExecutionService._identity_payload(first) != CharacterCreationExecutionService._identity_payload(source_change)


def test_terminal_wrapper_identity_retains_receipt_replay_and_stage2_hashes():
    wrapper = {
        "commit_id": "commit-1",
        "event_count": 2,
        "event_ids": ["event-1", "event-2"],
        "project": {"project_hash": "project-1"},
        "receipt": {"terminal_state_hash": "terminal-1"},
        "replay": {"ledger_hash": "ledger-1"},
        "stage2": {"manifest_hash": "manifest-1"},
    }
    for branch, key in (("receipt", "terminal_state_hash"), ("replay", "ledger_hash"), ("stage2", "manifest_hash")):
        changed = json.loads(json.dumps(wrapper))
        changed[branch][key] = changed[branch][key] + "-changed"
        assert CharacterCreationExecutionService._identity_payload(changed) != CharacterCreationExecutionService._identity_payload(wrapper)


def test_nested_manifest_package_members_remain_identity_bearing():
    first = {"manifest": {"package_path": "member-a", "members": [{"path": "a.json", "sha256": "a"}]}}
    second = {"manifest": {"package_path": "member-b", "members": [{"path": "a.json", "sha256": "a"}]}}
    third = {"manifest": {"package_path": "member-a", "members": [{"path": "a.json", "sha256": "b"}]}}
    assert CharacterCreationExecutionService._identity_payload(first) != CharacterCreationExecutionService._identity_payload(second)
    assert CharacterCreationExecutionService._identity_payload(first) != CharacterCreationExecutionService._identity_payload(third)


def test_identity_drops_only_known_sheet_transport_paths_and_preserves_mechanics():
    first = {
        "advanced_details": {
            "projection_status": {
                "artifacts": [{"path": "scratch-a", "sha256": "ledger-a"}],
            },
        },
        "provenance": {
            "advancement_projection": {
                "projection": {"artifacts": [{"path": "scratch-b", "sha256": "projection-a"}]},
            },
            "character_sheet_projection": {
                "artifact": {"path": "scratch-c", "sha256": "sheet-a"},
            },
            "mechanical_projection": {
                "projection": {"artifacts": [{"path": "scratch-d", "sha256": "mechanics-a"}]},
            },
        },
        "sheet_artifact": {"path": "scratch-e", "sha256": "sheet-artifact-a"},
        "owner_character_sheet": {"spheres_and_talents": {"paths": [{"path": "qi-path"}]}},
    }
    second = json.loads(json.dumps(first))
    second["advanced_details"]["projection_status"]["artifacts"][0]["path"] = "scratch-other"
    second["provenance"]["advancement_projection"]["projection"]["artifacts"][0]["path"] = "scratch-other"
    second["provenance"]["character_sheet_projection"]["artifact"]["path"] = "scratch-other"
    second["provenance"]["mechanical_projection"]["projection"]["artifacts"][0]["path"] = "scratch-other"
    second["sheet_artifact"]["path"] = "scratch-other"
    assert CharacterCreationExecutionService._identity_payload(first) == CharacterCreationExecutionService._identity_payload(second)

    changed = json.loads(json.dumps(first))
    changed["provenance"]["mechanical_projection"]["projection"]["artifacts"][0]["sha256"] = "mechanics-b"
    assert CharacterCreationExecutionService._identity_payload(first) != CharacterCreationExecutionService._identity_payload(changed)


def test_identity_surface_transport_fields_are_scoped_to_their_surface():
    gm_model_one = {"build": "scratch-a", "workspace": "workspace-a", "identity": {"model_id": "model"}}
    gm_model_two = {"build": "scratch-b", "workspace": "workspace-b", "identity": {"model_id": "model"}}
    assert CharacterCreationExecutionService._identity_payload(gm_model_one, _surface="gm_model") == CharacterCreationExecutionService._identity_payload(gm_model_two, _surface="gm_model")

    consumer_one = {"selected_id": "package-a", "manifest": {"sha256": "manifest"}}
    consumer_two = {"selected_id": "package-b", "manifest": {"sha256": "manifest"}}
    assert CharacterCreationExecutionService._identity_payload(consumer_one, _surface="gm_consumer") == CharacterCreationExecutionService._identity_payload(consumer_two, _surface="gm_consumer")

    package_one = {"selected_id": "package-a", "manifest": {"sha256": "manifest"}}
    package_two = {"selected_id": "package-b", "manifest": {"sha256": "manifest"}}
    assert CharacterCreationExecutionService._identity_payload(package_one, _surface="portable_character") != CharacterCreationExecutionService._identity_payload(package_two, _surface="portable_character")


def test_server_descriptive_binding_response_identity_is_not_deleted():
    first = {"source": "cg1-owner-descriptive:run-a:server-derived", "value": {"value": "Name", "binding": {"response_sha256": "a"}}}
    second = {"source": "cg1-owner-descriptive:run-a:server-derived", "value": {"value": "Name", "binding": {"response_sha256": "b"}}}
    assert CharacterCreationExecutionService._identity_payload(first) != CharacterCreationExecutionService._identity_payload(second)

def test_candidate_identity_retains_project_and_manifest_mechanical_identity():
    first = {
        'audit': {
            'manifest': {
                'event_head_hash': 'event-head',
                'advancement_projection_references': {'Projection_Diagnostics.json': 'a' * 64},
                'source_command5_candidate_sha256': 'b' * 64,
            },
        },
        'clean_import': {
            'first': {
                'project_import': {
                    'event_head_hash': 'event-head',
                    'state_hash': 'state',
                    'project_hash': 'c' * 64,
                },
            },
        },
        'release_identity': 'release-one',
    }
    second = {
        'audit': {
            'manifest': {
                'event_head_hash': 'event-head',
                'advancement_projection_references': {'Projection_Diagnostics.json': 'd' * 64},
                'source_command5_candidate_sha256': 'e' * 64,
            },
        },
        'clean_import': {
            'first': {
                'project_import': {
                    'event_head_hash': 'event-head',
                    'state_hash': 'state',
                    'project_hash': 'f' * 64,
                },
            },
        },
        'release_identity': 'release-two',
    }
    assert CharacterCreationExecutionService._identity_payload(first) != CharacterCreationExecutionService._identity_payload(second)
    changed = {
        **second,
        'audit': {
            **second['audit'],
            'manifest': {**second['audit']['manifest'], 'event_head_hash': 'different-event-head'},
        },
    }
    assert CharacterCreationExecutionService._identity_payload(first) != CharacterCreationExecutionService._identity_payload(changed)

def test_adversarial_planner_authority_and_invalid_stage2_fail_closed(tmp_path):
    bad=plan(); bad['compiled_surfaces']={'ability_scores':{'int':20},'resources':{'qi':999}}; bad['readiness']={'gm_model':'READY'}
    svc,_,db=make(tmp_path/'bad',bad); before=snapshot(db); run=svc.start('p',execution_mode='STANDARD_API',idempotency_key='bad-plan-123')  #gitleaks:allow -- inert test idempotency label
    assert run['blockers'][0]['code']=='CG1_PLANNER_AUTHORITY_FIELDS_FORBIDDEN' and snapshot(db)==before
    svc,_,db=make(tmp_path/'invalid',plan(valid=False)); before=snapshot(db); run=svc.start('p',execution_mode='STANDARD_API',idempotency_key='invalid-123')  #gitleaks:allow -- inert test idempotency label
    assert run['blockers'][0]['code']=='CG1_STAGE2_INVALID' and snapshot(db)==before

def test_atomic_restore_all_forced_failure_points(tmp_path):
    points=('stage1','stage2','projection','character_sheet','gm_export','gm_consumer','portable','portable_registration','combat')
    for point in points:
        svc,_,db=make(tmp_path/point,plan(combat=True)); run=svc.start('p',execution_mode='STANDARD_API',idempotency_key='failure-'+point); before=snapshot(db)  #gitleaks:allow -- inert test idempotency label
        with pytest.raises(FoundryError) as exc: svc.finalize(run['run_id'],fail_after=point)
        assert exc.value.code=='CG1_FINALIZATION_ROLLED_BACK' and snapshot(db)==before

def test_revision_bound_before_transport_and_provider_fallback(tmp_path):
    svc,p,db=make(tmp_path/'revision'); run=svc.start('p',execution_mode='STANDARD_API',idempotency_key='revision-123'); child=svc.revise(run['run_id'],owner_notes='Change Method')  #gitleaks:allow -- inert test idempotency label
    assert p.calls[-1]['revision_context']['owner_notes']=='Change Method'
    assert p.calls[-1]['binding']['project_revision']==child['starting_revision']
    assert child['run_id']!=run['run_id']
    svc,p,db=make(tmp_path/'fallback',ready=False); run=svc.start('p',execution_mode='STANDARD_API',idempotency_key='fallback-123')  #gitleaks:allow -- inert test idempotency label
    assert run['execution_mode']=='MANUAL_CHAT' and not p.calls


def test_character_creation_preflight_forwards_request_cap_and_fallback_records_no_network(tmp_path):
    svc, _, db = make(tmp_path / 'request-preflight')
    provider = PreflightProvider()
    svc.provider = provider
    run_id = 'cg1.run.request-preflight'
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO character_creation_runs(run_id,project_id,starting_revision,execution_mode,idempotency_key,request_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                'p',
                0,
                'STANDARD_API',
                'request-preflight-123',
                canonical_json({'request_sha256': 'a' * 64}),
                'PREPARING_REQUEST',
                'now',
                'now',
            ),
        )
    svc._provider_prompt = lambda _run: '{}'

    run = svc._run_provider(run_id)

    assert len(provider.calls) == 1
    # The request hard cap is model-aware and owner-tunable (raised past the
    # historical 96 KiB floor on 2026-09-04); the preflight must forward it.
    assert provider.calls[0]['max_request_bytes'] == cc_service.PROVIDER_REQUEST_HARD_CAP_BYTES
    assert provider.calls[0]['max_request_bytes'] >= 96 * 1024
    assert run['execution_mode'] == 'MANUAL_CHAT'
    assert run['transport']['provider_called'] is False
    assert run['transport']['provider_error']['details']['provider_called'] is False


def test_provider_fallback_ignores_misleading_false_detail_after_transport(tmp_path):
    svc, _, db = make(tmp_path / 'transport-failure')
    run_id = 'cg1.run.transport-failure'
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO character_creation_runs(run_id,project_id,starting_revision,execution_mode,idempotency_key,request_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                'p',
                0,
                'STANDARD_API',
                'transport-failure-123',
                canonical_json({'request_sha256': 'b' * 64}),
                'PREPARING_REQUEST',
                'now',
                'now',
            ),
        )

    run = svc._provider_fallback(
        svc.get(run_id),
        FoundryError(
            'AI_PROVIDER_NETWORK_ERROR',
            'The provider transport failed after the request was sent.',
            details={'provider_called': False},
        ),
        provider_id='deepseek',
        attempt_evidence=[{'attempt': 1, 'status': 'TRANSPORT_ERROR'}],
    )

    assert run['transport']['provider_called'] is True

def test_complete_manual_request_zip_is_deterministic_and_exact(tmp_path, monkeypatch):
    svc,_,_=make(tmp_path)
    requested_record_ids=[]
    resolve_locked_records=svc._locked_records_for_project_ids
    def capture_requested_record_ids(project_id, record_ids):
        requested_record_ids.append(tuple(sorted(record_ids)))
        return resolve_locked_records(project_id, record_ids)
    monkeypatch.setattr(svc,'_locked_records_for_project_ids',capture_requested_record_ids)
    run=svc.start('p',execution_mode='MANUAL_CHAT',idempotency_key='manual-zip-123')
    name,first=svc.complete_request_zip(run['run_id'])
    assert (name,first)==svc.complete_request_zip(run['run_id'])
    assert requested_record_ids==[(),()]
    assert svc.projects.lock_proof_calls==['p','p']
    assert name.startswith('CG1_COMPLETE_REQUEST_p_')
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist()==[
            'AI_CHOICE_MODEL.json','AI_INSTRUCTIONS.md','BINDING.json','COMPLETE_REQUEST.json','PROMPT_INSTRUCTIONS.md','README_START_HERE.md',
            'RESPONSE_SCHEMA.json','SHA256SUMS.txt',
        ]
        declared={}
        for line in archive.read('SHA256SUMS.txt').decode('ascii').splitlines():
            digest,member=line.split('  ',1); declared[member]=digest
        assert set(declared)==set(archive.namelist())-{'SHA256SUMS.txt'}
        assert all(hashlib.sha256(archive.read(member)).hexdigest()==digest for member,digest in declared.items())
        complete_request = json.loads(archive.read('COMPLETE_REQUEST.json'))
        assert complete_request['request_sha256']==run['request']['request_sha256']
        private_manual_collection = (run['request'].get('server_owned_authority') or {}).get('manual_collection') or {}
        assert 'manual_collection' not in (complete_request.get('server_owned_authority') or {})
        if private_manual_collection:
            complete_request_bytes = archive.read('COMPLETE_REQUEST.json')
            assert private_manual_collection['nonce'].encode('utf-8') not in complete_request_bytes
            assert private_manual_collection['seed'].encode('utf-8') not in complete_request_bytes
        model = json.loads(archive.read('AI_CHOICE_MODEL.json'))
        assert model['request_sha256'] == run['request']['request_sha256']
        assert model['response_contract']['array_position_semantics'].startswith('zero-based array index')
        assert [row['cl'] for row in model['ordinary_talent_slots']] == list(range(1, 21))
        response_schema = json.loads(archive.read('RESPONSE_SCHEMA.json'))
        assert 'manual_collection' not in (response_schema.get('server_owned') or {})
        response_schema_bytes = archive.read('RESPONSE_SCHEMA.json')
        if private_manual_collection:
            assert private_manual_collection['nonce'].encode('utf-8') not in response_schema_bytes
            assert private_manual_collection['seed'].encode('utf-8') not in response_schema_bytes
        preferred_by_slot = response_schema['preferred_response']['properties']['selection_intent']['properties']['by_slot']
        for slot_id in ('sphere_priorities', 'insight_priorities', 'item_priorities'):
            if slot_id in preferred_by_slot['properties'] and preferred_by_slot['properties'][slot_id]['items']['enum']:
                assert slot_id in preferred_by_slot['required']
                assert preferred_by_slot['properties'][slot_id]['minItems'] >= 1
        assert CharacterCreationExecutionService._empty_schema_combinators(response_schema['preferred_response']) == []

def test_complete_request_download_builds_one_package_for_body_and_receipt(tmp_path, monkeypatch):
    svc,_,_=make(tmp_path)
    run=svc.start('p',execution_mode='MANUAL_CHAT',idempotency_key='manual-download-once-123')
    package={
        'filename':'CG1_COMPLETE_REQUEST_TEST.zip',
        'payload':b'one-package',
        'request_payload_sha256':'1'*64,
        'member_inventory':[],
        'content_set_sha256':'2'*64,
        'final_zip_sha256':'3'*64,
    }
    calls=[]
    monkeypatch.setattr(svc,'_complete_request_package',lambda run_id:(calls.append(run_id) or package))
    download=svc.complete_request_download(run['run_id'])
    assert calls==[run['run_id']]
    assert download['filename']==package['filename'] and download['payload']==package['payload']
    assert download['receipt']['final_zip_sha256']==package['final_zip_sha256']
    assert download['receipt']['final_zip_bytes']==len(package['payload'])

def test_preference_is_durable_per_server_principal_and_finalize_uses_server_principal(tmp_path):
    svc,_,db=make(tmp_path)
    assert svc.preference('p')['execution_mode']=='MANUAL_CHAT'
    assert svc.set_preference('p','STANDARD_API')['execution_mode']=='STANDARD_API'
    same_owner=CharacterCreationExecutionService(
        db,stage1=svc.stage1,provider=svc.provider,project_store=svc.projects,
        stage2=svc.stage2,character_sheets=svc.character_sheets,gm_exports=svc.gm_exports,
        portable_characters=svc.portable_characters,factory_authoring=svc.factory_authoring,
        projections=svc.projections,gm_consumer=svc.gm_consumer,
        combat_readiness=svc.combat_readiness,pipeline_factory=pipeline,owner_principal='owner')
    other_owner=CharacterCreationExecutionService(
        db,stage1=svc.stage1,provider=svc.provider,project_store=svc.projects,
        stage2=svc.stage2,character_sheets=svc.character_sheets,gm_exports=svc.gm_exports,
        portable_characters=svc.portable_characters,factory_authoring=svc.factory_authoring,
        projections=svc.projections,gm_consumer=svc.gm_consumer,
        combat_readiness=svc.combat_readiness,pipeline_factory=pipeline,owner_principal='other-owner')
    assert same_owner.preference('p')['execution_mode']=='STANDARD_API'
    assert other_owner.preference('p')['execution_mode']=='MANUAL_CHAT'
    run=same_owner.start('p',execution_mode='STANDARD_API',idempotency_key='principal-123')  #gitleaks:allow -- inert test idempotency label
    with pytest.raises(FoundryError) as exc:
        same_owner.finalize(run['run_id'])
    assert exc.value.code == 'CG1_FINALIZATION_ROLLED_BACK'
    assert same_owner.get(run['run_id'])['status'] == 'READY_FOR_REVIEW'

def test_auto_finalize_requires_explicit_durable_bound_opt_in(tmp_path):
    svc,_,db=make(tmp_path)
    run=svc.start('p',execution_mode='AUTO_FINALIZE_WHEN_CLEAN',idempotency_key='auto-optin-123')
    assert run['status']=='READY_FOR_REVIEW' and not run['commit']
    with pytest.raises(FoundryError) as exc:
        svc.create_auto_finalize_opt_in(run['run_id'])
    assert exc.value.code == 'CG1_FINALIZATION_ROLLED_BACK'
    with db.connection() as conn:
        row=conn.execute('select count(*) from character_creation_auto_finalize_opt_ins').fetchone()
    assert row[0] == 1
    assert svc.get(run['run_id'])['status'] == 'READY_FOR_REVIEW'
    manual,_,_=make(tmp_path/'manual')
    manual_run=manual.start('p',execution_mode='MANUAL_CHAT',idempotency_key='manual-no-auto-123')
    manual_run=manual.submit_manual(manual_run['run_id'],response_text=canonical_json(bound_plan(manual_run)),request_sha256=manual_run['request']['request_sha256'])
    with pytest.raises(FoundryError) as exc:
        manual.create_auto_finalize_opt_in(manual_run['run_id'])
    assert exc.value.code=='CG1_AUTO_FINALIZE_MODE_REQUIRED'

def test_accepted_final_plan_and_response_are_immutable(tmp_path):
    svc,_,_=make(tmp_path/'immutable')
    before=snapshot(svc.db)
    run=svc.start('p',execution_mode='STANDARD_API',idempotency_key='immutable-123')  #gitleaks:allow -- inert test idempotency label
    assert snapshot(svc.db)==before
    assert run['dry_run']['independent_compilations']==2 and run['dry_run']['deterministic']
    final_plan=run['final_plan']
    exact_response=run['response']['exact_response_text']
    changed=json.loads(exact_response)
    changed['owner_descriptive_fields']['concept']='Changed after acceptance'
    with pytest.raises(FoundryError) as exc:
        svc._apply_response(run['run_id'],canonical_json(changed),{'mode':'STANDARD_API','provider_called':True})
    assert exc.value.code=='CG1_FINAL_PLAN_IMMUTABLE'
    unchanged=svc.get(run['run_id'])
    assert unchanged['final_plan']==final_plan
    assert unchanged['response']['exact_response_text']==exact_response
    assert unchanged['status']=='READY_FOR_REVIEW'
