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


def test_real_compile_submission_persists_owner_gear_warning_and_review_quality(tmp_path, factory_environment):
    svc, _, db = make(tmp_path / "owner-gear-warning")
    from character_creation.constructed_arts.records import construct_starting_kit, build_starting_kit_record
    from catalog.service import CatalogService
    from project_store.service import ProjectStore
    from tests.r4v_harness import provision_external_test_key

    # Constructed kit validation needs genuine immutable pack membership in
    # each scratch database, unlike the ordinary modes-test plan.
    provision_external_test_key(db.settings.data_dir)
    CatalogService(db).rebuild_core(factory_environment["root"])
    store = ProjectStore(db)
    pack = pinned_content_lock()["packs"][0]
    with db.transaction() as conn:
        seal = store.verified_pack_seal(conn, pack["pack_id"], pack["version"], pack["content_hash"])
        store._snapshot_pack_seals(conn, "p", [seal], locked_at="now")

    concept = "A fighter with a staff, a sickle, and a crossbow"
    with db.transaction() as conn:
        project = json.loads(conn.execute("SELECT project_json FROM projects WHERE project_id='p'").fetchone()[0])
        project["user_locks"].append({"field": "concept", "value": concept})
        conn.execute("UPDATE projects SET project_json=? WHERE project_id='p'", (canonical_json(project),))
    run = svc.start("p", execution_mode="MANUAL_CHAT", idempotency_key="owner-gear-warning-123")
    assert len(run["request"]["owner_gear_requirements"]) == 3
    seed = "concept-production-warning"
    decision = {"path_option": "option_b", "picks": {"background:1": 2},
                "purchases": ["tianxia.mortal.weapon.nu_gong"]}
    kit = construct_starting_kit(background_id="tianxia.background.village_child",
                               path_id="tianxia.path.spirit_awakening", seed=seed, **decision)
    assert kit["resolved"]["coin_cc"] == 0
    assert "tianxia.mortal.weapon.lian" not in {row["item_id"] for row in kit["resolved"]["items"]}
    response = bound_plan(run)
    response["owner_descriptive_fields"]["concept"] = concept
    response["canonical_selection_intent"] = {
        "acquisition_intent": {"starting_kit": decision},
        "selected_by_slot": {"background_choice": ["tianxia.background.village_child"],
                             "path_choice": ["tianxia.path.spirit_awakening"]},
        "bounded_choices": {},
    }
    response["materialization_receipt"] = {"canonical_intent_hash": seed}
    response["stage2_proposal"]["choices"].append({"kind": "equipment_acquisition", "effective_cl": 1,
                                                 "record_id": build_starting_kit_record(kit)["record_id"]})
    warning = "Lian (Sickle) isn't covered by the guaranteed starting-kit coin, so it is optional and wasn't added. Either starting kit is allowed; rolled coin counts only at its minimum for required gear."
    submitted = svc.submit_manual(
        run["run_id"], response_text=canonical_json(response),
        request_sha256=run["request"]["request_sha256"],
    )
    assert submitted["status"] == "NEEDS_REVIEW"
    assert submitted["validation"].get("valid"), submitted["validation"]
    assert submitted["dry_run"]["independent_compilations"] == 2
    assert submitted["quality"]["status"] == "NEEDS_REVIEW"
    assert submitted["warnings"] == [{"code": "CG1_OWNER_NAMED_GEAR_UNAVAILABLE", "message": warning}]

    # get() reconstructs this public run from its persisted database row.
    reloaded = svc.get(run["run_id"])
    assert reloaded["status"] == "NEEDS_REVIEW"
    assert reloaded["quality"]["status"] == "NEEDS_REVIEW"
    assert reloaded["warnings"] == submitted["warnings"]

@pytest.mark.parametrize(("concept", "purchase", "expected"), [
    ("A fighter using a meteor hammer or wielding a maul", "tianxia.mortal.weapon.liu_xing_chui",
     {"tianxia.mortal.weapon.liu_xing_chui", "tianxia.mortal.weapon.da_chui"}),
    ("A fighter using a meteor hammer or wielding a maul", "tianxia.mortal.weapon.da_chui",
     {"tianxia.mortal.weapon.liu_xing_chui", "tianxia.mortal.weapon.da_chui"}),
    ("A fighter who carries a meteor hammer or a maul", "tianxia.mortal.weapon.liu_xing_chui",
     {"tianxia.mortal.weapon.liu_xing_chui", "tianxia.mortal.weapon.da_chui"}),
    ("A fighter who carries a meteor hammer or a maul", "tianxia.mortal.weapon.da_chui",
     {"tianxia.mortal.weapon.liu_xing_chui", "tianxia.mortal.weapon.da_chui"}),
    ("A fighter who carries a meteor hammer/maul", "tianxia.mortal.weapon.da_chui",
     {"tianxia.mortal.weapon.liu_xing_chui", "tianxia.mortal.weapon.da_chui"}),
    ("A fighter without armor and with a meteor hammer", "tianxia.mortal.weapon.liu_xing_chui",
     {"tianxia.mortal.weapon.liu_xing_chui"}),
    ("A fighter with no shield but carries a spear", "tianxia.mortal.weapon.qiang",
     {"tianxia.mortal.weapon.duan_qiang", "tianxia.mortal.weapon.qiang"}),
])
def test_owner_gear_clauses_submit_and_reload(tmp_path, factory_environment, concept, purchase, expected):
    from character_creation.constructed_arts.records import construct_starting_kit, build_starting_kit_record
    from catalog.service import CatalogService
    from project_store.service import ProjectStore
    from tests.r4v_harness import provision_external_test_key

    svc, _, db = make(tmp_path / "gear-clauses")
    # Use real immutable catalog membership and production kit construction;
    # Stage 1/2 and artifact collaborators remain the modes-test doubles.
    provision_external_test_key(db.settings.data_dir)
    CatalogService(db).rebuild_core(factory_environment["root"])
    store = ProjectStore(db)
    pack = pinned_content_lock()["packs"][0]
    with db.transaction() as conn:
        seal = store.verified_pack_seal(conn, pack["pack_id"], pack["version"], pack["content_hash"])
        store._snapshot_pack_seals(conn, "p", [seal], locked_at="now")
        project = json.loads(conn.execute("SELECT project_json FROM projects WHERE project_id='p'").fetchone()[0])
        project["user_locks"].append({"field": "concept", "value": concept})
        conn.execute("UPDATE projects SET project_json=? WHERE project_id='p'", (canonical_json(project),))
    run = svc.start("p", execution_mode="MANUAL_CHAT", idempotency_key="owner-gear-clauses-123")
    assert svc.request_payload_sha256(run["request"]) == run["request"]["request_sha256"]

    seed = "concept-production-clauses"
    background = "tianxia.background.abandoned_orphan"
    path = "tianxia.path.body_refining"

    def response_for(purchases):
        decision = {"path_option": "option_b", "picks": {}, "purchases": purchases}
        kit = construct_starting_kit(background_id=background, path_id=path, seed=seed, **decision)
        response = bound_plan(run)
        response["owner_descriptive_fields"]["concept"] = concept
        response["canonical_selection_intent"] = {
            "acquisition_intent": {"starting_kit": decision},
            "selected_by_slot": {"background_choice": [background], "path_choice": [path]},
            "bounded_choices": {},
        }
        response["materialization_receipt"] = {"canonical_intent_hash": seed}
        response["stage2_proposal"]["choices"].append({
            "kind": "equipment_acquisition", "effective_cl": 1,
            "record_id": build_starting_kit_record(kit)["record_id"],
        })
        return response, kit

    mandatory = len(expected) == 1
    for whole_kit in ((False, True) if mandatory else (False,)):
        omitted, _ = response_for([])
        if whole_kit:
            omitted["canonical_selection_intent"]["acquisition_intent"] = {}
            omitted["stage2_proposal"]["choices"].pop()
        result = svc.submit_manual(run["run_id"], response_text=canonical_json(omitted),
                                   request_sha256=run["request"]["request_sha256"])
        if mandatory:
            assert result["validation"]["response_state"]["compiled"] is False
            assert result["validation"]["last_submission_error"]["code"] == "CG1_OWNER_NAMED_GEAR_MISSING"
        else:
            assert result["validation"]["valid"], result["validation"]
            assert result["dry_run"]["independent_compilations"] == 2
            assert len(result["warnings"]) == 1
            assert "Optional gear suggestion" in result["warnings"][0]["message"]
        assert svc.get(run["run_id"])["validation"] == result["validation"]
        assert svc.get(run["run_id"])["warnings"] == result["warnings"]

    if not mandatory:
        # Accepted final plans are immutable; the optional purchase needs a
        # separate run. Rejected mandatory omissions stay in one repair run.
        run = svc.start("p", execution_mode="MANUAL_CHAT", idempotency_key="owner-gear-purchase-123")
    response, kit = response_for([purchase])
    assert {row["item_id"] for row in kit["resolved"]["items"]} & expected == {purchase}
    assert kit["resolved"]["purchases"] == [purchase]
    submitted = svc.submit_manual(run["run_id"], response_text=canonical_json(response),
                                  request_sha256=run["request"]["request_sha256"])
    assert submitted["status"] == ("READY_FOR_REVIEW" if mandatory else "NEEDS_REVIEW"), submitted["validation"]
    assert submitted["validation"]["valid"]
    assert submitted["dry_run"]["independent_compilations"] == 2
    assert bool(submitted["warnings"]) == (not mandatory)
    reloaded = svc.get(run["run_id"])
    assert reloaded["status"] == submitted["status"]
    assert reloaded["validation"] == submitted["validation"]
    assert reloaded["warnings"] == submitted["warnings"]
    assert {row["item_id"] for row in reloaded["request"].get("owner_gear_requirements", [])} == (expected if mandatory else set())
    assert reloaded["request"].get("owner_gear_requirements", []) == run["request"].get("owner_gear_requirements", [])
    assert svc.request_payload_sha256(reloaded["request"]) == run["request"]["request_sha256"]
    persisted_response = json.loads(reloaded["response"]["exact_response_text"])
    assert persisted_response["canonical_selection_intent"]["acquisition_intent"]["starting_kit"]["purchases"] == [purchase]


@pytest.mark.parametrize(("concept", "purchases"), [
    ("A fighter who fights without using a staff or wielding a maul", []),
    ("A fighter with no armor and no shield", []),
    ("A fighter without armor or shields", []),
    ("A fighter who doesn't wear armor or carry a shield", []),
    ("A fighter carrying a staff and sickle", ["tianxia.mortal.weapon.gun", "tianxia.mortal.weapon.lian"]),
    ("A fighter carrying a meteor hammer and chain whip", ["tianxia.mortal.weapon.liu_xing_chui", "tianxia.mortal.weapon.jie_bian"]),
])
def test_coordinated_gear_submission_and_reload(tmp_path, factory_environment, concept, purchases):
    _coordinated_gear_submission_and_reload(tmp_path, factory_environment, concept, purchases)


def _coordinated_gear_submission_and_reload(tmp_path, factory_environment, concept, purchases, *, quantity_advisories=(), dagger_count=None, background="tianxia.background.abandoned_orphan", check_omission=False):
    """Exercise real sealed gear submission/reload, also with fake embeddings."""
    from character_creation.constructed_arts.records import construct_starting_kit, build_starting_kit_record
    from catalog.service import CatalogService
    from project_store.service import ProjectStore
    from tests.r4v_harness import provision_external_test_key

    svc, _, db = make(tmp_path / "coordinated-gear")
    provision_external_test_key(db.settings.data_dir)
    CatalogService(db).rebuild_core(factory_environment["root"])
    store = ProjectStore(db)
    pack = pinned_content_lock()["packs"][0]
    with db.transaction() as conn:
        seal = store.verified_pack_seal(conn, pack["pack_id"], pack["version"], pack["content_hash"])
        store._snapshot_pack_seals(conn, "p", [seal], locked_at="now")
        project = json.loads(conn.execute("SELECT project_json FROM projects WHERE project_id='p'").fetchone()[0])
        project["user_locks"].append({"field": "concept", "value": concept})
        conn.execute("UPDATE projects SET project_json=? WHERE project_id='p'", (canonical_json(project),))
    run = svc.start("p", execution_mode="MANUAL_CHAT", idempotency_key="coordinated-gear-123")
    expected = [{item_id} for item_id in dict.fromkeys(purchases)]
    if dagger_count is not None:
        expected = [{"tianxia.mortal.weapon.bi_shou"}]
    assert [{row["item_id"]} for row in run["request"].get("owner_gear_requirements", [])] == expected
    assert not run["request"].get("owner_gear_warnings")
    assert run["request"].get("owner_gear_advisories", []) == list(quantity_advisories)
    assert svc.request_payload_sha256(run["request"]) == run["request"]["request_sha256"]
    seed = "concept-production-coordination"

    def response_for(selected):
        decision = {"path_option": "option_b", "picks": {}, "purchases": selected}
        path = "tianxia.path.body_refining"
        kit = construct_starting_kit(background_id=background, path_id=path, seed=seed, **decision)
        response = bound_plan(run)
        response["owner_descriptive_fields"]["concept"] = concept
        response["canonical_selection_intent"] = {
            "acquisition_intent": {"starting_kit": decision},
            "selected_by_slot": {"background_choice": [background], "path_choice": [path]},
            "bounded_choices": {},
        }
        response["materialization_receipt"] = {"canonical_intent_hash": seed}
        response["stage2_proposal"]["choices"].append({
            "kind": "equipment_acquisition", "effective_cl": 1,
            "record_id": build_starting_kit_record(kit)["record_id"],
        })
        return response, kit

    # Each affordable conjunct must be enforced independently, including after
    # persistence. Exclusions instead permit a kit containing neither item.
    for missing in (purchases if dagger_count is None or check_omission else []):
        response, omitted_kit = response_for([item for item in purchases if item != missing])
        assert missing not in {row["item_id"] for row in omitted_kit["resolved"]["items"]}
        rejected = svc.submit_manual(run["run_id"], response_text=canonical_json(response),
                                     request_sha256=run["request"]["request_sha256"])
        assert rejected["status"] == "NEEDS_REVIEW"
        assert rejected["validation"]["response_state"]["compiled"] is False
        assert rejected["validation"]["last_submission_error"]["code"] == "CG1_OWNER_NAMED_GEAR_MISSING"
        assert svc.get(run["run_id"])["validation"] == rejected["validation"]

    response, kit = response_for(purchases)
    owned = {row["item_id"] for row in kit["resolved"]["items"]}
    assert set(purchases) <= owned
    if dagger_count is not None:
        assert sum(row["quantity"] for row in kit["resolved"]["items"] if row["item_id"] == "tianxia.mortal.weapon.bi_shou") == dagger_count
    if not purchases:
        from factory_authoring.starting_kits import gear_catalog
        excluded = {"tianxia.mortal.weapon.gun", "tianxia.mortal.weapon.da_chui"}
        excluded.update(row["item_id"] for row in gear_catalog() if row["category"] in {"armor", "shield"})
        assert owned.isdisjoint(excluded)
    submitted = svc.submit_manual(run["run_id"], response_text=canonical_json(response),
                                  request_sha256=run["request"]["request_sha256"])
    assert submitted["status"] == "READY_FOR_REVIEW", submitted["validation"]
    assert submitted["validation"]["valid"]
    assert submitted["dry_run"]["independent_compilations"] == 2
    assert not any(row.get("code", "").startswith("CG1_OWNER_NAMED_GEAR") for row in submitted["warnings"])
    assert submitted["quality"]["status"] == "CLEAN"
    assert [row["message"] for row in submitted["warnings"] if row.get("code") == "CG1_OWNER_GEAR_QUANTITY_ADVISORY"] == list(quantity_advisories)
    reloaded = svc.get(run["run_id"])
    assert reloaded["status"] == submitted["status"]
    assert reloaded["validation"] == submitted["validation"]
    assert reloaded["warnings"] == submitted["warnings"]
    assert reloaded["quality"] == submitted["quality"]
    assert reloaded["request"].get("owner_gear_advisories", []) == list(quantity_advisories)
    assert reloaded["request"].get("owner_gear_requirements", []) == run["request"].get("owner_gear_requirements", [])
    assert svc.request_payload_sha256(reloaded["request"]) == run["request"]["request_sha256"]
    persisted_response = json.loads(reloaded["response"]["exact_response_text"])
    assert persisted_response["canonical_selection_intent"]["acquisition_intent"]["starting_kit"]["purchases"] == purchases
    return submitted, reloaded


@pytest.mark.parametrize("dagger_count", [1, 2])
@pytest.mark.parametrize("phrase", ["a dagger", "two daggers"])
def test_quantity_advice_submission_and_reload(tmp_path, factory_environment, dagger_count, phrase):
    advisories = [] if phrase == "a dagger" else [
        "Your concept asks for two daggers; one is required. The quantity isn't enforced automatically; add more by hand if you want them."
    ]
    # The background already grants one dagger; Option B can buy another.
    submitted, reloaded = _coordinated_gear_submission_and_reload(
        tmp_path, factory_environment, f"A fighter who wields {phrase}",
        ["tianxia.mortal.weapon.bi_shou"] * (dagger_count - 1),
        quantity_advisories=advisories, dagger_count=dagger_count,
    )
    assert reloaded["request"]["owner_gear_requirements"] == [
        {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)"},
    ]


@pytest.mark.parametrize("phrase", ["a small knife", "a hunting knife", "two hunting knives", "a pair of small knives"])
def test_printed_knife_submission_and_reload(tmp_path, factory_environment, phrase):
    advisories = [] if phrase in {"a small knife", "a hunting knife"} else [
        f"Your concept asks for {phrase}; one is required. The quantity isn't enforced automatically; add more by hand if you want them."
    ]
    _coordinated_gear_submission_and_reload(
        tmp_path, factory_environment, f"A fighter carrying {phrase}", ["tianxia.mortal.weapon.bi_shou"],
        quantity_advisories=advisories, dagger_count=1,
        background="tianxia.background.merchant_clan_scion", check_omission=True,
    )


@pytest.mark.parametrize(("concept", "remaining"), [
    ("A fighter using a stormglass glaive or wielding a maul", None),
    ("A fighter using either a meteor hammer or expertly wielding a maul", None),
    ("A fighter using a meteor hammer or maul", 100),
    ("A fighter using a meteor hammer or maul", 99),
])
def test_advisory_and_shared_purchase_submission_reload(tmp_path, factory_environment, concept, remaining):
    from character_creation.constructed_arts.records import construct_starting_kit, build_starting_kit_record
    from catalog.service import CatalogService
    from project_store.service import ProjectStore
    from tests.r4v_harness import provision_external_test_key

    svc, _, db = make(tmp_path / "gear-confidence-budget")
    provision_external_test_key(db.settings.data_dir)
    CatalogService(db).rebuild_core(factory_environment["root"])
    store = ProjectStore(db)
    pack = pinned_content_lock()["packs"][0]
    title = "Maul master" if remaining is not None else ""
    with db.transaction() as conn:
        seal = store.verified_pack_seal(conn, pack["pack_id"], pack["version"], pack["content_hash"])
        store._snapshot_pack_seals(conn, "p", [seal], locked_at="now")
        project = json.loads(conn.execute("SELECT project_json FROM projects WHERE project_id='p'").fetchone()[0])
        project["user_locks"].append({"field": "concept", "value": concept})
        if title:
            project["user_locks"].append({"field": "owner_descriptive_fields.identity.title", "value": title})
        conn.execute("UPDATE projects SET project_json=? WHERE project_id='p'", (canonical_json(project),))
    run = svc.start("p", execution_mode="MANUAL_CHAT", idempotency_key="gear-confidence-budget-123")
    maul = "tianxia.mortal.weapon.da_chui"
    hammer = "tianxia.mortal.weapon.liu_xing_chui"
    expected = [{maul}] if title else []
    assert [{row["item_id"]} for row in run["request"].get("owner_gear_requirements", [])] == expected
    if not title:
        assert not run["request"].get("owner_gear_preferences")
        assert len(run["request"]["owner_gear_warnings"]) == 1
        assert "Optional gear suggestion" in run["request"]["owner_gear_warnings"][0]
    assert svc.request_payload_sha256(run["request"]) == run["request"]["request_sha256"]
    seed = "concept-production-shared-budget"
    retained = [] if remaining is None else [
        "tianxia.mortal.gear.magnifying_glass", "tianxia.mortal.gear.scholar_s_pack", "tianxia.mortal.gear.chain",
    ]
    if remaining == 99:
        retained.append("tianxia.mortal.gear.candle")

    def response_for(purchases):
        decision = {"path_option": "option_b", "picks": {}, "purchases": purchases}
        kit = construct_starting_kit(background_id="tianxia.background.abandoned_orphan",
                                   path_id="tianxia.path.body_refining", seed=seed, **decision)
        response = bound_plan(run)
        response["owner_descriptive_fields"]["concept"] = concept
        if title:
            response["owner_descriptive_fields"]["identity"]["title"] = title
        response["canonical_selection_intent"] = {
            "acquisition_intent": {"starting_kit": decision},
            "selected_by_slot": {"background_choice": ["tianxia.background.abandoned_orphan"],
                                 "path_choice": ["tianxia.path.body_refining"]},
            "bounded_choices": {},
        }
        response["materialization_receipt"] = {"canonical_intent_hash": seed}
        response["stage2_proposal"]["choices"].append({
            "kind": "equipment_acquisition", "effective_cl": 1,
            "record_id": build_starting_kit_record(kit)["record_id"],
        })
        return response, kit

    response, kit = response_for(retained)
    if remaining is not None:
        assert kit["resolved"]["coin_cc"] == remaining
    assert not {maul, hammer} & {row["item_id"] for row in kit["resolved"]["items"]}
    submitted = svc.submit_manual(run["run_id"], response_text=canonical_json(response),
                                  request_sha256=run["request"]["request_sha256"])
    if remaining == 100:
        assert submitted["validation"]["response_state"]["compiled"] is False
        assert submitted["validation"]["last_submission_error"]["code"] == "CG1_OWNER_NAMED_GEAR_MISSING"
        assert svc.get(run["run_id"])["validation"] == submitted["validation"]
        response, kit = response_for([*retained, maul])
        assert kit["resolved"]["coin_cc"] == 0
        assert kit["resolved"]["purchases"].count(maul) == 1
        submitted = svc.submit_manual(run["run_id"], response_text=canonical_json(response),
                                      request_sha256=run["request"]["request_sha256"])
        assert submitted["status"] == "NEEDS_REVIEW", submitted["validation"]
        assert len(submitted["warnings"]) == 1
        assert "Optional gear suggestion" in submitted["warnings"][0]["message"]
    else:
        assert submitted["status"] == "NEEDS_REVIEW", submitted["validation"]
        assert submitted["warnings"]
        assert any(row["code"] == "CG1_OWNER_NAMED_GEAR_UNAVAILABLE" for row in submitted["warnings"])
    assert submitted["validation"]["valid"]
    assert submitted["dry_run"]["independent_compilations"] == 2
    reloaded = svc.get(run["run_id"])
    assert reloaded["status"] == submitted["status"]
    assert reloaded["validation"] == submitted["validation"]
    assert reloaded["warnings"] == submitted["warnings"]
    assert reloaded["request"].get("owner_gear_requirements", []) == run["request"].get("owner_gear_requirements", [])
    assert svc.request_payload_sha256(reloaded["request"]) == run["request"]["request_sha256"]
    persisted = json.loads(reloaded["response"]["exact_response_text"])
    assert persisted["canonical_selection_intent"]["acquisition_intent"]["starting_kit"]["purchases"] == kit["resolved"].get("purchases", [])


@pytest.mark.parametrize(("concept", "path", "option", "weapon_cue", "purchases"), [
    ("A fighter carrying a staff or sickle", "spirit_awakening", "option_a", "Gun (Staff)", []),
    ("A fighter carrying a staff or sickle", "spirit_awakening", "option_a", "Lian (Sickle)", []),
    ("A fighter carrying a staff or sickle", "spirit_awakening", "option_b", None, []),
    ("A fighter wearing Mountain-Pattern Grand Shell or Ring-Lamellar Harness", "body_refining", "option_a", None, []),
    ("A fighter wearing Mountain-Pattern Grand Shell or Ring-Lamellar Harness", "body_refining", "option_b", None, []),
    ("A fighter wearing Mountain-Pattern Grand Shell or Ring-Lamellar Harness", "body_refining", "option_b", None,
     ["tianxia.mortal.armor.ring_lamellar_harness"]),
    ("A fighter who wields a meteor hammer", "body_refining", "option_b", None,
     ["tianxia.mortal.weapon.liu_xing_chui"]),
])
def test_named_gear_controller_commit_submission_and_reload(
    tmp_path, factory_environment, concept, path, option, weapon_cue, purchases,
):
    from catalog.service import CatalogService
    from character_creation.constructed_arts.records import construct_starting_kit, build_starting_kit_record
    from character_creation.creative_controller.linear_menus import CommittedState, build_step_menu
    from character_creation.creative_controller.linear_walk import commit_option
    from factory_authoring.starting_kits import choice_menus
    from project_store.service import ProjectStore
    from tests.r4v_harness import provision_external_test_key

    svc, _, db = make(tmp_path / "controller-gear")
    provision_external_test_key(db.settings.data_dir)
    CatalogService(db).rebuild_core(factory_environment["root"])
    store = ProjectStore(db)
    pack = pinned_content_lock()["packs"][0]
    with db.transaction() as conn:
        seal = store.verified_pack_seal(conn, pack["pack_id"], pack["version"], pack["content_hash"])
        store._snapshot_pack_seals(conn, "p", [seal], locked_at="now")
        project = json.loads(conn.execute("SELECT project_json FROM projects WHERE project_id='p'").fetchone()[0])
        project["user_locks"].append({"field": "concept", "value": concept})
        conn.execute("UPDATE projects SET project_json=? WHERE project_id='p'", (canonical_json(project),))
    run = svc.start("p", execution_mode="MANUAL_CHAT", idempotency_key="controller-gear-123")
    request = run["request"]
    mandatory = "or" not in concept.split()
    if mandatory:
        assert request["owner_gear_preferences"] == purchases
        assert {row["item_id"] for row in request["owner_gear_requirements"]} == set(purchases)
        assert not request.get("owner_gear_warnings")
    else:
        assert not request.get("owner_gear_preferences")
        assert not request.get("owner_gear_requirements")
        assert len(request["owner_gear_warnings"]) == 1
        advisory = request["owner_gear_warnings"][0]
        options = ("staff", "sickle") if path == "spirit_awakening" else ("Mountain-Pattern Grand Shell", "Ring-Lamellar Harness")
        assert all(name in advisory for name in options)
        assert "does not require a starting kit or limit its choices" in advisory
    assert svc.request_payload_sha256(request) == request["request_sha256"]

    background = "tianxia.background.abandoned_orphan"
    path_id = f"tianxia.path.{path}"
    state = CommittedState(by_slot={"background_choice": [background], "path_choice": [path_id]})
    menu = build_step_menu(request, {}, state, step_id="starting_kit_option")
    assert [row.choice_ids for row in menu.options] == ([("option_b",)] if mandatory else [("option_a",), ("option_b",)])
    selected = next(row for row in menu.options if row.choice_ids == (option,))
    state = commit_option(menu, selected.option_id, state)
    for choice in choice_menus(background, path_id, option):
        menu = build_step_menu(request, {}, state, step_id=f"starting_kit_choice:{choice['choice_id']}")
        # Advice leaves every printed choice open across all menu pages.
        page, page_menu = 1, menu
        offered = set()
        while True:
            offered.update(row.choice_ids for row in page_menu.options if not row.is_continuation)
            if not page_menu.next_page_id:
                break
            page += 1
            page_menu = build_step_menu(request, {}, state, step_id=f"starting_kit_choice:{choice['choice_id']}", page=page)
        assert offered == {(f"{choice['choice_id']}={index}",) for index in range(len(choice["options"]))}
        selected = next(row for row in menu.options if weapon_cue in row.cue) if weapon_cue and choice["choice_id"] == "path:0" else menu.options[0]
        state = commit_option(menu, selected.option_id, state)
    decision = {**state.bounded["starting_kit"], **({"purchases": purchases} if purchases else {})}
    seed = "controller-gear-round8"

    def response_for(kit_decision):
        response = bound_plan(run)
        response["owner_descriptive_fields"]["concept"] = concept
        response["canonical_selection_intent"] = {
            "acquisition_intent": {} if kit_decision is None else {"starting_kit": kit_decision},
            "selected_by_slot": state.by_slot, "bounded_choices": {},
        }
        response["materialization_receipt"] = {"canonical_intent_hash": seed}
        if kit_decision is not None:
            kit = construct_starting_kit(background_id=background, path_id=path_id, seed=seed, **kit_decision)
            response["stage2_proposal"]["choices"].append({
                "kind": "equipment_acquisition", "effective_cl": 1,
                "record_id": build_starting_kit_record(kit)["record_id"],
            })
            if kit_decision.get("purchases"):
                assert set(kit_decision["purchases"]) <= {row["item_id"] for row in kit["resolved"]["items"]}
            if weapon_cue:
                assert any(weapon_cue == row["name"] for row in kit["resolved"]["items"])
        return response

    decisions = (None, {**decision, "purchases": []}, decision) if mandatory else (None, decision)
    for index, kit_decision in enumerate(decisions):
        if index and not mandatory:
            run = svc.start("p", execution_mode="MANUAL_CHAT", idempotency_key=f"controller-gear-{index}-123")
            request = run["request"]
        response = response_for(kit_decision)
        submitted = svc.submit_manual(run["run_id"], response_text=canonical_json(response), request_sha256=request["request_sha256"])
        if mandatory and kit_decision != decision:
            assert submitted["validation"]["response_state"]["compiled"] is False
            assert submitted["validation"]["last_submission_error"]["code"] == "CG1_OWNER_NAMED_GEAR_MISSING"
        else:
            assert submitted["validation"]["valid"], submitted["validation"]
            assert submitted["dry_run"]["independent_compilations"] == 2
            assert submitted["warnings"] == ([] if mandatory else [{"code": "CG1_OWNER_NAMED_GEAR_UNAVAILABLE", "message": advisory}])
        reloaded = svc.get(run["run_id"])
        assert reloaded["validation"] == submitted["validation"]
        assert reloaded["warnings"] == submitted["warnings"]
        assert reloaded["request"] == request
        assert json.loads(reloaded["response"]["exact_response_text"])["canonical_selection_intent"]["acquisition_intent"] == response["canonical_selection_intent"]["acquisition_intent"]


@pytest.mark.parametrize(("coin_case", "option"), [
    ("fixed", "option_b"), ("pinned", "option_b"),
    ("lucky", "option_a"), ("lucky", "option_b"),
])
def test_guaranteed_gear_budget_assembly_submission_reload(
    tmp_path, factory_environment, monkeypatch, coin_case, option,
):
    from copy import deepcopy
    from catalog.service import CatalogService
    from character_creation.constructed_arts.records import construct_starting_kit, build_starting_kit_record
    from character_creation.creative_controller.linear_assembly import build_response
    from character_creation.creative_controller.linear_menus import CommittedState, build_step_menu
    from character_creation.creative_controller.linear_walk import commit_option
    from factory_authoring import starting_kits
    from project_store.service import ProjectStore
    from tests.r4v_harness import provision_external_test_key

    background = "tianxia.background.merchant_clan_scion"
    path = "tianxia.path.body_refining"
    shell = "tianxia.mortal.armor.mountain_pattern_grand_shell"
    concept = "A fighter wearing a Mountain-Pattern Grand Shell"
    # Current authority has rolled Background coin only. A fixture with five
    # one-sided dice represents fixed 500 CC without changing kit resolution;
    # the pinned case puts that same grant behind an already committed choice.
    original_background = starting_kits.background_kit
    if coin_case != "lucky":
        def fixture_background(background_id):
            kit = original_background(background_id)
            if background_id == background:
                coin = next(entry for entry in kit["entries"] if entry["kind"] == "coin")
                coin["roll"] = {"count": 5, "sides": 1}
                if coin_case == "pinned":
                    kit["entries"][kit["entries"].index(coin)] = {
                        "kind": "choice", "printed": coin["printed"], "options": [
                            {"kind": "trinket", "text": "An empty purse"}, coin,
                        ],
                    }
            return kit
        monkeypatch.setattr(starting_kits, "background_kit", fixture_background)
    coin_index = next(index for index, entry in enumerate(starting_kits.background_kit(background)["entries"])
                      if entry.get("printed") == "a purse of mixed coin")
    picks = {f"background:{coin_index}": 1} if coin_case == "pinned" else {}
    assert starting_kits.deterministic_kit_coin_cc(background, path, "option_b", picks=picks) == (1650 if coin_case == "lucky" else 2050)
    if coin_case == "pinned":
        assert starting_kits.deterministic_kit_coin_cc(background, path, "option_b") == 1550

    svc, _, db = make(tmp_path / "guaranteed-controller-gear")
    provision_external_test_key(db.settings.data_dir)
    CatalogService(db).rebuild_core(factory_environment["root"])
    store = ProjectStore(db)
    pack = pinned_content_lock()["packs"][0]
    with db.transaction() as conn:
        seal = store.verified_pack_seal(conn, pack["pack_id"], pack["version"], pack["content_hash"])
        store._snapshot_pack_seals(conn, "p", [seal], locked_at="now")
        project = json.loads(conn.execute("SELECT project_json FROM projects WHERE project_id='p'").fetchone()[0])
        project["user_locks"].append({"field": "concept", "value": concept})
        conn.execute("UPDATE projects SET project_json=? WHERE project_id='p'", (canonical_json(project),))
    run = svc.start("p", execution_mode="MANUAL_CHAT", idempotency_key="guaranteed-controller-gear-123")
    request = run["request"]
    assert request["owner_gear_preferences"] == [shell]
    state = CommittedState(by_slot={"background_choice": [background], "path_choice": [path]},
                           bounded={"starting_kit": {"picks": picks}})
    menu = build_step_menu(request, {}, state, step_id="starting_kit_option")
    expected = [("option_a",), ("option_b",)] if coin_case == "lucky" else [("option_b",)]
    assert [row.choice_ids for row in menu.options] == expected
    selected = next(row for row in menu.options if row.choice_ids == (option,))
    state = commit_option(menu, selected.option_id, state)
    for choice in starting_kits.choice_menus(background, path, option):
        menu = build_step_menu(request, {}, state, step_id=f"starting_kit_choice:{choice['choice_id']}")
        if menu is not None:
            state = commit_option(menu, menu.options[0].option_id, state)
    # Production assembly owns purchases; this regression never inserts them.
    assembled = json.loads(build_response(request, state.with_identity("Test", "Shell Bearer")))
    decision = assembled["acquisition_intent"]["starting_kit"]
    assert decision.get("purchases", []) == ([] if coin_case == "lucky" else [shell])
    if coin_case == "pinned":
        assert decision["picks"][f"background:{coin_index}"] == 1
    seed = next(f"guaranteed-gear-{index}" for index in range(200)
                if starting_kits.seeded_roll(f"guaranteed-gear-{index}", f"coin:{background}:a purse of mixed coin:0", 20) >= 5)
    assert starting_kits.resolve_starting_kit(background, path, path_option="option_b", picks=picks, seed=seed)["coin_cc"] >= 2000

    def response_for(kit_decision):
        # Keep the existing modes harness's Stage 1/2 adapters; equipment goes
        # through real construction, service validation and persisted response.
        response = bound_plan(run)
        response["owner_descriptive_fields"] = assembled["owner_descriptive_fields"]
        response["canonical_selection_intent"] = {
            "acquisition_intent": {"starting_kit": kit_decision},
            "selected_by_slot": assembled["selection_intent"]["by_slot"], "bounded_choices": {},
        }
        response["materialization_receipt"] = {"canonical_intent_hash": seed}
        kit = construct_starting_kit(background_id=background, path_id=path, seed=seed, **kit_decision)
        response["stage2_proposal"]["choices"].append({
            "kind": "equipment_acquisition", "effective_cl": 1,
            "record_id": build_starting_kit_record(kit)["record_id"],
        })
        return response, kit

    if coin_case != "lucky":
        omitted = deepcopy(decision)
        omitted.pop("purchases")
        response, _ = response_for(omitted)
        rejected = svc.submit_manual(run["run_id"], response_text=canonical_json(response), request_sha256=request["request_sha256"])
        assert rejected["validation"]["last_submission_error"]["code"] == "CG1_OWNER_NAMED_GEAR_MISSING"
        assert svc.get(run["run_id"])["validation"] == rejected["validation"]
    response, kit = response_for(decision)
    submitted = svc.submit_manual(run["run_id"], response_text=canonical_json(response), request_sha256=request["request_sha256"])
    assert submitted["validation"]["valid"], submitted["validation"]
    assert submitted["dry_run"]["independent_compilations"] == 2
    actual = {row["item_id"] for row in kit["resolved"]["items"]}
    assert (shell in actual) == (coin_case != "lucky")
    if coin_case == "lucky":
        assert len(submitted["warnings"]) == 1
        assert "Mountain-Pattern Grand Shell" in submitted["warnings"][0]["message"]
        assert "optional" in submitted["warnings"][0]["message"]
    else:
        assert submitted["warnings"] == []
    reloaded = svc.get(run["run_id"])
    assert reloaded["validation"] == submitted["validation"]
    assert reloaded["warnings"] == submitted["warnings"]
    assert reloaded["request"] == request
    persisted = json.loads(reloaded["response"]["exact_response_text"])
    assert persisted["canonical_selection_intent"]["acquisition_intent"]["starting_kit"] == decision


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
