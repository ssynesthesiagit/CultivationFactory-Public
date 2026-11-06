"""Synthetic native Void-family acquisition for public table regressions.

Every store and authority receipt is built under pytest's own temporary path;
no private fixture, installed character, repository history or model is read.
"""
import pytest

from app.core import Database, Settings, canonical_json, utcnow
from combat.authority_projection import compile_project_character
from combat.ext import void_touched_cultivator as void
from combat.typed_executor import Context
from combat.gate2_runtime_models import ActionIntent
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import (
    ap_award, commit_authority_event, install_authority_test_pack, lock_authority_test_pack,
)

QI = "tianxia.path.qi_cultivation"
VOID_SPHERE = "tianxia.sphere.void"


def insert_project(db, project_id, target_cl):
    now = utcnow()
    document = {"project_id": project_id, "working_name": project_id,
                "user_locks": [{"field": "target_cl", "value": target_cl}], "events": []}
    with db.transaction() as connection:
        connection.execute(
            """INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,
               target_factory_version,target_candidate_schema_version,target_gm_screen_version,catalog_build_hash,
               quality_target,project_json,compatibility_projection_status,compile_status,consumer_verification_status,
               legacy_project_json,canonical_project_hash,canonical_schema_version,contract_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (project_id, project_id, "DRAFT", 0, now, now, "HF05ZVK-R1H", "HF05ZVK-R1F",
             "HF05ZUI-R2K.3-HF3-W1", None, "rival/boss", canonical_json(document),
             "NOT_BUILT", "NOT_COMPILED", "NOT_VERIFIED", None, "0" * 64,
             "Tianxia.CharacterProject.v3", "legacy-unverified"))
    lock_authority_test_pack(db, project_id, target_cl)


@pytest.fixture(scope="module")
def acquired(tmp_path_factory):
    settings = Settings.from_env(ROOT, tmp_path_factory.mktemp("void-family") / "data")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    project = "synthetic-void-family"
    insert_project(db, project, 3)
    service.initialize_for_project(project, target_cl=3, path_ids=[QI], method_id="METHOD-001")
    service.allocate_advancement(project, {QI: 2},
                                 evidence_id=ap_award(db, service, project, "METHOD-001", 3, 2),
                                 idempotency_key=project + "-advance")
    access = commit_authority_event(db, service, project, "subpath_access",
                                    {"selection_id": void.PARENT, "path_id": QI})
    service.select_subpath(project, QI, void.PARENT, [access],
                           acquisition_choices={"void_scar": "My reflection no longer appears."},
                           spheres=[VOID_SPHERE])
    service.set_resource(project, QI, current=30, maximum=30)
    return service, project


def owner_sheet(service, project, *, name="Void cultivator"):
    document = sheet([], cl=3, name=name, dc=50)
    document["spheres_and_talents"] = {"sphere_record_ids": [VOID_SPHERE]}
    document["path_and_subpath"] = {"paths": service.get_state(project)["paths"]}
    return document


def bundle(service, project, actor_id):
    return compile_project_character(service, project, owner_sheet(service, project),
                                     actor_id=actor_id, reaction_plan={"ask": True})


def step_action(engine, owner_id):
    return next(engine.action_catalog[aid] for aid in engine.state.actors[owner_id].action_ids
                if void.family_source(engine.action_catalog.get(aid)) == void.VOID_STEP)


def step_context(engine, actor, action):
    intent = ActionIntent(intent_id="void-step-test", decision_id="", candidate_id="",
                          state_version=engine.state.state_version, actor_id=actor.entity_id)
    return Context(engine, actor, action, intent, dict(action.parameters["typed"]), [])
