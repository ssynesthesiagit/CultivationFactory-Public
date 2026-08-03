from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.api import create_app
from app.core import Database, FoundryError, Settings, canonical_json, utcnow
from non_sphere_authority import NonSphereAuthorityService
from non_sphere_authority.service import COMPACT_TO_CANONICAL
from tests.ns1r_evidence_helpers import access_evidence, ap_award, commit_authority_event

ROOT = Path(__file__).resolve().parents[1]
BODY = "tianxia.path.body_refining"
QI = "tianxia.path.qi_cultivation"
SPIRIT = "tianxia.path.spirit_awakening"


def insert_project(db: Database, project_id: str, target_cl: int = 10) -> None:
    now = utcnow()
    doc = {"project_id": project_id, "working_name": project_id, "user_locks": [{"field": "target_cl", "value": target_cl}], "events": []}
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,
               target_factory_version,target_candidate_schema_version,target_gm_screen_version,catalog_build_hash,
               quality_target,project_json,compatibility_projection_status,compile_status,consumer_verification_status,
               legacy_project_json,canonical_project_hash,canonical_schema_version,contract_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (project_id, project_id, "DRAFT", 0, now, now, "HF05ZVK-R1H", "HF05ZVK-R1F", "HF05ZUI-R2K.3-HF3-W1", None,
             "rival/boss", canonical_json(doc), "NOT_BUILT", "NOT_COMPILED", "NOT_VERIFIED", None, "0" * 64,
             "Tianxia.CharacterProject.v3", "legacy-unverified"),
        )



@pytest.fixture()
def authority(tmp_path: Path) -> tuple[NonSphereAuthorityService, Database]:
    settings = Settings.from_env(ROOT, tmp_path / "data")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    return NonSphereAuthorityService(db), db


def test_all_102_method_acquisition_dispositions(authority):
    service, _ = authority
    freely_available = []
    for method_id, method in sorted(service.methods.items()):
        without = service.method_acquisition_satisfied(method, [])
        with_exact = service.method_acquisition_satisfied(method, [{
            "authority_type": "method_access", "method_id": method_id, "source_record_id": f"proof.{method_id}",
        }])
        assert with_exact is True
        if without:
            freely_available.append((method_id, method["acquisition"]["access_tier"]))
    assert freely_available == [("METHOD-001", "OPEN_SECT_BASIC")]


def test_restricted_method_rejected_in_initialization_and_raw_save(authority):
    service, db = authority
    insert_project(db, "init-restricted")
    with pytest.raises(FoundryError) as exc:
        service.initialize_for_project("init-restricted", target_cl=5, path_ids=[BODY], method_id="METHOD-002")
    assert exc.value.code == "NS1R_METHOD_ACCESS_REQUIRED"

    insert_project(db, "raw-restricted")
    state = service.blank_state("raw-restricted", 5)
    state["known_method_ids"] = ["METHOD-002"]
    state["primary_method_id"] = "METHOD-002"
    with pytest.raises(FoundryError) as exc:
        service.save_state("raw-restricted", state)
    assert exc.value.code == "NS1R_NATIVE_SEMANTIC_MUTATION_REJECTED"
    assert any(row["code"] == "METHOD_ACQUISITION_EVIDENCE_REQUIRED" for row in exc.value.details["blockers"])


def test_subpath_cl_and_access_invalidation(authority):
    service, db = authority
    insert_project(db, "cl-invalidation")
    open_choice = next(row for row in service.subpaths.values() if row["owning_path_id"] == QI and not row["access"].get("access_source_record_required"))
    state = service.initialize_for_project(
        "cl-invalidation", target_cl=5, path_ids=[QI], method_id="METHOD-001",
        path_attainment_by_id={QI: 3}, subpath_ids=[open_choice["canonical_id"]],
    )
    assert state["readiness"]["status"] == "READY"
    state = service.set_path_attainment(
        "cl-invalidation", QI, 2, operation_mode="ADMINISTRATIVE_PRESERVATION",
        source_record_id="admin.cl.correction",
    )
    row = next(item for item in state["paths"] if item["path_id"] == QI)
    assert row["subpath_or_tradition_id"] is None
    assert row["invalidations"][-1]["cause"]["code"] == "SUBPATH_MINIMUM_CL_NO_LONGER_MET"
    assert state["readiness"]["status"] == "BLOCKED"

    insert_project(db, "access-invalidation")
    restricted = next(row for row in service.subpaths.values() if row["owning_path_id"] == SPIRIT and row["access"].get("access_source_record_required"))
    records = access_evidence(db,service,"access-invalidation","METHOD-005") + [commit_authority_event(db,service,"access-invalidation","subpath_access",{"selection_id":restricted["canonical_id"]})]
    service.initialize_for_project(
        "access-invalidation", target_cl=5, path_ids=[SPIRIT], method_id="METHOD-005", access_source_records=records,
        path_attainment_by_id={SPIRIT: 3}, subpath_ids=[restricted["canonical_id"]],
    )
    state = service.set_access_sources("access-invalidation", access_evidence(db,service,"access-invalidation","METHOD-005"))
    row = next(item for item in state["paths"] if item["path_id"] == SPIRIT)
    assert row["subpath_or_tradition_id"] is None
    assert row["invalidations"][-1]["cause"]["code"] == "SUBPATH_EXACT_ACCESS_NO_LONGER_PRESENT"


def complete_background_routes(service: NonSphereAuthorityService, background_id: str) -> dict[str, str]:
    authority = service.background_route_authority[background_id]
    route = authority["route_options"][0]
    return {
        "background_route_record_id": route["background_route_record_id"],
        "background_sphere_choice_id": route["background_sphere_choice_id"],
        "background_talent_choice_id": route["background_talent_choice_id"],
        "origin_insight_choice_id": authority["origin_insight_options"][0]["origin_insight_choice_id"],
        "ability_grant_mode_id": authority["ability_grant_modes"][0]["ability_grant_mode_id"],
        "equipment_authority_id": authority["equipment_authority_id"],
        "skills_authority_id": authority["skills_authority_id"],
        "tools_languages_trades_authority_id": authority["tools_languages_trades_authority_id"],
    }


def test_background_routes_exact_and_unresolved_fail_closed(authority):
    service, db = authority
    open_background = next(row for row in service.backgrounds.values() if not row["blockers"])
    exact = complete_background_routes(service, open_background["background_id"])
    result = service.validate_background(open_background["background_id"], selected_route_ids=exact, require_complete=True)
    assert result["ready"] is True
    assert result["background_talent_separate_from_ordinary_talents"] is True
    fake = dict(exact, background_route_record_id="fake.route")
    assert service.validate_background(open_background["background_id"], selected_route_ids=fake, require_complete=True)["ready"] is False

    unresolved = [row for row in service.backgrounds.values() if row["blockers"]]
    assert len(unresolved) == 3
    for background in unresolved:
        insert_project(db, background["background_id"])
        state = service.initialize_for_project(
            background["background_id"], target_cl=1, path_ids=[QI], method_id="METHOD-001",
            background_id=background["background_id"], background_route_ids=complete_background_routes(service, background["background_id"]),
        )
        assert state["readiness"]["status"] == "BLOCKED"
        assert any(item["code"] == "BACKGROUND_SOURCE_FIELD_UNRESOLVED" for item in state["readiness"]["blockers"])


def compatibility_samples(service: NonSphereAuthorityService) -> dict[str, dict]:
    samples: dict[str, dict] = {}
    for method in service.methods.values():
        active = [COMPACT_TO_CANONICAL[row["path_id"]] for row in method["explicit_ap_grants"] if row["grants_attainment_points"]]
        for foundation_id in service.foundations:
            result = service.resolve_compatibility(method["method_id"], foundation_id, active)
            samples.setdefault(result["state"], result)
    return samples


def test_all_eight_compatibility_readiness_states(authority):
    service, _ = authority
    samples = compatibility_samples(service)
    assert set(samples) == {"INCOMPATIBLE", "GM_REVIEW_REQUIRED", "CORRECTIVE_OPPORTUNITY", "TRANSFORMATION_OPPORTUNITY", "STRAINED", "WORKABLE_WITH_FRICTION", "NATURAL_AFFINITY", "WORKABLE"}
    assert service.compatibility_readiness(samples["INCOMPATIBLE"], [])["blockers"]
    gm = samples["GM_REVIEW_REQUIRED"]
    assert service.compatibility_readiness(gm, [])["blockers"]
    gm_record = {"authority_type": "compatibility_adjudication", "method_id": gm["method_id"], "foundation_id": gm["foundation_id"], "adjudication_outcome": "WORKABLE", "source_record_id": "gm.adjudication.1"}
    assert service.compatibility_readiness(gm, [gm_record])["blockers"] == []

    corrective = samples["CORRECTIVE_OPPORTUNITY"]
    gate = service.compatibility_readiness(corrective, [])
    blocker = gate["blockers"][0]
    assert blocker["code"] == "SPECIFIC_REPAIR_COMPLETION_REQUIRED"
    repair_record = {"authority_type": "repair_completion", "method_id": corrective["method_id"], "foundation_id": corrective["foundation_id"], "repair_interface": blocker["repair_interface"], "repair_practice_name": blocker["accepted_repair_practices"][0], "source_record_id": "repair.complete.1"}
    assert service.compatibility_readiness(corrective, [repair_record])["blockers"] == []

    transform = samples["TRANSFORMATION_OPPORTUNITY"]
    gate = service.compatibility_readiness(transform, [])
    blocker = gate["blockers"][0]
    transform_record = {"authority_type": "transformation_completion", "method_id": transform["method_id"], "foundation_id": transform["foundation_id"], "transformation_route": blocker["transformation_route"], "completion_type": "FOUNDATION_CHALLENGE", "source_record_id": "challenge.complete.1"}
    assert service.compatibility_readiness(transform, [transform_record])["blockers"] == []
    for state in ("STRAINED", "WORKABLE_WITH_FRICTION"):
        gate = service.compatibility_readiness(samples[state], [])
        assert gate["blockers"] == [] and gate["warnings"]
    for state in ("NATURAL_AFFINITY", "WORKABLE"):
        gate = service.compatibility_readiness(samples[state], [])
        assert gate == {"blockers": [], "warnings": []}


@pytest.mark.parametrize("method_id,paths,multiplier", [
    ("METHOD-081", [BODY, QI], 3),
    ("METHOD-082", [BODY, QI], 3),
    ("METHOD-083", [BODY, SPIRIT], 3),
    ("METHOD-084", [QI, SPIRIT], 3),
    ("METHOD-085", [BODY, QI, SPIRIT], 5),
    ("METHOD-087", [BODY, SPIRIT], 3),
])
def test_all_six_multi_path_methods_and_burdens(authority, method_id, paths, multiplier):
    service, db = authority
    insert_project(db, method_id)
    state = service.initialize_for_project(method_id, target_cl=10, path_ids=paths, method_id=method_id, access_source_records=access_evidence(db,service,method_id,method_id))
    assert service.method_burden_multiplier(service.methods[method_id]) == multiplier
    assert state["ap_transaction_history"][0]["ap_spent"] == len(paths) * multiplier


def test_all_five_allocation_rule_classes(authority):
    service, db = authority
    # ALL_METHOD_AP_TO_GRANTED_PATH and 1x.
    insert_project(db, "single")
    service.initialize_for_project("single", target_cl=10, path_ids=[QI], method_id="METHOD-001")
    state = service.allocate_advancement("single", {QI: 1}, evidence_id=ap_award(db,service,"single","METHOD-001",10,1), idempotency_key="ap.single")
    assert next(row for row in state["paths"] if row["path_id"] == QI)["attainment"] == 2

    # EQUAL_SPLIT: METHOD-082 and METHOD-085 cannot persist inequality.
    for pid, method_id, paths, spend in [
        ("equal-two", "METHOD-082", [BODY, QI], 3),
        ("equal-three", "METHOD-085", [BODY, QI, SPIRIT], 5),
    ]:
        insert_project(db, pid)
        service.initialize_for_project(pid, target_cl=10, path_ids=paths, method_id=method_id, access_source_records=access_evidence(db,service,pid,method_id))
        with pytest.raises(FoundryError) as exc:
            service.allocate_advancement(pid, {paths[0]: 1}, evidence_id=ap_award(db,service,pid,method_id,10,spend), idempotency_key=f"ap.{pid}.bad")
        assert exc.value.code == "NS1R_METHOD_ALLOCATION_RULE_VIOLATION"
        balanced = {path: 1 for path in paths}
        state = service.allocate_advancement(pid, balanced, evidence_id=ap_award(db,service,pid,method_id,10,len(paths)*spend), idempotency_key=f"ap.{pid}.good")
        assert len({next(row for row in state["paths"] if row["path_id"] == path)["attainment"] for path in paths}) == 1

    # PRIMARY_WITH_SECONDARY_MINIMUM.
    insert_project(db, "ratio")
    service.initialize_for_project("ratio", target_cl=10, path_ids=[BODY, SPIRIT], method_id="METHOD-083", access_source_records=access_evidence(db,service,"ratio","METHOD-083"))
    service.allocate_advancement("ratio", {BODY: 1}, evidence_id=ap_award(db,service,"ratio","METHOD-083",10,3), idempotency_key="ap.ratio.good")
    with pytest.raises(FoundryError):
        service.allocate_advancement("ratio", {BODY: 1}, evidence_id=ap_award(db,service,"ratio","METHOD-083",10,3), idempotency_key="ap.ratio.bad")

    # MILESTONE_LOCKED.
    insert_project(db, "milestone")
    service.initialize_for_project("milestone", target_cl=10, path_ids=[QI, SPIRIT], method_id="METHOD-084", access_source_records=access_evidence(db,service,"milestone","METHOD-084"))
    service.allocate_advancement("milestone", {QI: 1}, evidence_id=ap_award(db,service,"milestone","METHOD-084",10,3), idempotency_key="ap.milestone.good")
    with pytest.raises(FoundryError):
        service.allocate_advancement("milestone", {QI: 1}, evidence_id=ap_award(db,service,"milestone","METHOD-084",10,3), idempotency_key="ap.milestone.bad")

    # OWNER_DISTRIBUTED printed Realm minimum.
    insert_project(db, "owner")
    service.initialize_for_project("owner", target_cl=10, path_ids=[BODY, QI], method_id="METHOD-081", access_source_records=access_evidence(db,service,"owner","METHOD-081"))
    with pytest.raises(FoundryError):
        service.allocate_advancement("owner", {BODY: 4}, evidence_id=ap_award(db,service,"owner","METHOD-081",10,12), idempotency_key="ap.owner.bad")


def test_raw_attainment_cannot_bypass_ap_ledger(authority):
    service, db = authority
    insert_project(db, "raw-equal")
    state = service.initialize_for_project("raw-equal", target_cl=10, path_ids=[BODY, QI], method_id="METHOD-082", access_source_records=access_evidence(db,service,"raw-equal","METHOD-082"))
    next(row for row in state["paths"] if row["path_id"] == BODY)["attainment"] = 2
    with pytest.raises(FoundryError) as exc:
        service.save_state("raw-equal", state)
    assert exc.value.code == "NS1R_NATIVE_SEMANTIC_MUTATION_REJECTED"
    assert any(row["code"] == "PATH_ATTAINMENT_HISTORY_MISMATCH" for row in exc.value.details["blockers"])
    with pytest.raises(FoundryError) as exc:
        service.set_path_attainment("raw-equal", BODY, 2)
    assert exc.value.code == "NS1R_RAW_ATTAINMENT_ADVANCEMENT_FORBIDDEN"


def test_api_documentation_fastapi_and_ui_registry_are_identical(tmp_path: Path):
    contract = json.loads((ROOT / "CHECKPOINTS/NS1R_COMPLETE/NS1R_API_Service_Contract.json").read_text())
    documented = {(row["method"], row["path"]) for row in contract["routes"]}
    settings = Settings.from_env(ROOT, tmp_path / "api-data")
    settings.ensure_dirs()
    app = create_app(settings)
    implemented = {
        (method, route.path)
        for route in app.routes if getattr(route, "path", "").startswith("/api/non-sphere/")
        for method in getattr(route, "methods", set()) if method not in {"HEAD", "OPTIONS"}
    }
    js = (ROOT / "static/app.js").read_text()
    block = re.search(r"const NS1R_API_CONTRACT_ROUTES = Object\.freeze\(\[(.*?)\]\);", js, re.S)
    assert block
    ui = set(re.findall(r'\{method: "([A-Z]+)", path: "([^"]+)"\}', block.group(1)))
    assert documented == implemented == ui
    assert ("POST", "/api/non-sphere/projects/{project_id}/access-sources") in documented
    assert all(path != "/api/non-sphere/projects/{project_id}/access" for _, path in documented)


def test_independent_eleven_check_regression(authority):
    service, db = authority
    checks: list[bool] = []
    insert_project(db, "audit-acq")
    try:
        service.initialize_for_project("audit-acq", target_cl=5, path_ids=[BODY], method_id="METHOD-002")
        checks.append(False)
    except FoundryError:
        checks.append(True)

    insert_project(db, "audit-lower")
    choice = next(row for row in service.subpaths.values() if row["owning_path_id"] == QI and not row["access"].get("access_source_record_required"))
    service.initialize_for_project("audit-lower", target_cl=5, path_ids=[QI], method_id="METHOD-001", path_attainment_by_id={QI: 3}, subpath_ids=[choice["canonical_id"]])
    lowered = service.set_path_attainment("audit-lower", QI, 2, source_record_id="audit.lower")
    path = next(row for row in lowered["paths"] if row["path_id"] == QI)
    checks.extend([path["subpath_or_tradition_id"] is None, lowered["readiness"]["status"] == "BLOCKED"])

    insert_project(db, "audit-raw")
    state = service.initialize_for_project("audit-raw", target_cl=5, path_ids=[QI], method_id="METHOD-001", path_attainment_by_id={QI: 3})
    restricted = next(row for row in service.subpaths.values() if row["owning_path_id"] == QI and row["access"].get("access_source_record_required"))
    next(row for row in state["paths"] if row["path_id"] == QI)["subpath_or_tradition_id"] = restricted["canonical_id"]
    saved = service.save_state("audit-raw", state)
    checks.append(saved["readiness"]["status"] == "BLOCKED")

    blocked_bg = next(row for row in service.backgrounds.values() if row["blockers"])
    insert_project(db, "audit-bg")
    bg_state = service.initialize_for_project("audit-bg", target_cl=1, path_ids=[QI], method_id="METHOD-001", background_id=blocked_bg["background_id"], background_route_ids=complete_background_routes(service, blocked_bg["background_id"]))
    checks.append(bg_state["readiness"]["status"] == "BLOCKED")
    open_bg = next(row for row in service.backgrounds.values() if not row["blockers"])
    checks.append(service.validate_background(open_bg["background_id"], selected_route_ids={"background_route_record_id": "fake"})["ready"] is False)

    insert_project(db, "audit-compat")
    compat = service.initialize_for_project("audit-compat", target_cl=1, path_ids=[QI], method_id="METHOD-001", foundation_id="ancient_desolate_sacred_body_v0_2C")
    checks.extend([compat["compatibility_result"]["state"] == "GM_REVIEW_REQUIRED", compat["readiness"]["status"] == "BLOCKED"])

    insert_project(db, "audit-equal")
    service.initialize_for_project("audit-equal", target_cl=5, path_ids=[BODY, QI], method_id="METHOD-082", access_source_records=access_evidence(db,service,"audit-equal","METHOD-082"))
    try:
        service.allocate_advancement("audit-equal", {BODY: 1}, evidence_id=ap_award(db,service,"audit-equal","METHOD-082",5,3), idempotency_key="audit.bad")
        checks.extend([False, False])
    except FoundryError:
        state = service.get_state("audit-equal")
        attainments = {row["path_id"]: row["attainment"] for row in state["paths"]}
        checks.extend([attainments[BODY] == attainments[QI], state["readiness"]["status"] == "READY"])

    contract = json.loads((ROOT / "CHECKPOINTS/NS1R_COMPLETE/NS1R_API_Service_Contract.json").read_text())
    checks.append(any(row["path"].endswith("/access-sources") for row in contract["routes"]))
    assert len(checks) == 11
    assert all(checks)
