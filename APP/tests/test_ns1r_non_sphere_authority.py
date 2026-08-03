from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from app.core import Database, FoundryError, Settings, canonical_json, utcnow
from non_sphere_authority.service import CANONICAL_TO_COMPACT, NonSphereAuthorityService
from tests.ns1r_evidence_helpers import access_evidence, ap_award, commit_authority_event

ROOT = Path(__file__).resolve().parents[1]
BODY = "tianxia.path.body_refining"
QI = "tianxia.path.qi_cultivation"
SPIRIT = "tianxia.path.spirit_awakening"



def insert_project(db: Database, project_id: str, target_cl: int = 10) -> None:
    now = utcnow()
    project_doc = {
        "project_id": project_id,
        "working_name": project_id,
        "user_locks": [{"field": "target_cl", "value": target_cl}],
        "events": [],
    }
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(project_id,working_name,status,revision,created_at,updated_at,
               target_factory_version,target_candidate_schema_version,target_gm_screen_version,catalog_build_hash,
               quality_target,project_json,compatibility_projection_status,compile_status,consumer_verification_status,
               legacy_project_json,canonical_project_hash,canonical_schema_version,contract_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                project_id, project_id, "DRAFT", 0, now, now,
                "HF05ZVK-R1H", "HF05ZVK-R1F", "HF05ZUI-R2K.3-HF3-W1", None,
                "rival/boss", canonical_json(project_doc), "NOT_BUILT", "NOT_COMPILED", "NOT_VERIFIED",
                None, "0" * 64, "Tianxia.CharacterProject.v3", "legacy-unverified",
            ),
        )


@pytest.fixture()
def authority(tmp_path: Path) -> tuple[NonSphereAuthorityService, Database]:
    settings = Settings.from_env(ROOT, tmp_path / "data")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    return NonSphereAuthorityService(db), db


def test_authority_identity_counts_and_no_pairwise(authority):
    service, _ = authority
    status = service.authority_status()
    assert status["status"] == "NS1R_R2_BOUND_EVIDENCE_AND_PROJECT_PACKAGE_COMPATIBILITY_READY"
    assert (status["method_count"], status["exact_override_count"]) == (102, 22)
    assert (status["path_count"], status["subpath_tradition_count"]) == (3, 156)
    assert (status["orthodox_foundation_count"], status["theoretical_chakra_foundation_count"]) == (30, 32)
    assert status["background_count"] == 31
    assert status["operative_pairwise_authority_rows"] == 0
    assert status["cross_catalog_audit_runtime_consumed"] is False
    assert {"METHOD-100", "METHOD-102"} <= set(service.methods)
    assert all(row["foundation_compatibility_authority"]["exact_named_override_registry"] == "AUTHORITY/Exact_Named_Method_Foundation_Overrides_v0_6.json" for row in service.methods.values())


def test_foundation_catalog_and_standardized_repairs(authority):
    service, _ = authority
    catalog = service.foundation_catalog()
    assert catalog["orthodox_count"] == 30
    assert catalog["theoretical_chakra_count"] == 32
    assert all(row["selectable"] is False and row["export_eligible"] is False and row["tournament_legal"] is False for row in catalog["theoretical_chakra"])
    assert service.foundations["mud_lotus_dantian_v0_2A"]["repair_practice_names"] == ["Clean-Water Lotus Bath", "Root-and-Silt Circulation", "Humble Bloom Service"]
    assert service.foundations["glass_heart_meridian_v0_2A"]["repair_practice_names"] == ["Warm Mirror-Meridian Treatment", "Trusted Witness Truth Rite", "Break the False Image"]


def test_full_102_by_30_resolver_audit_is_deterministic(authority):
    service, _ = authority
    def compute() -> tuple[int, str]:
        rows = []
        for method_id in sorted(service.methods):
            active = [row["path_id"] for row in service.methods[method_id]["explicit_ap_grants"] if row["grants_attainment_points"]]
            for foundation_id in sorted(service.foundations):
                result = service.resolve_compatibility(method_id, foundation_id, active)
                assert result["runtime_pairwise_authority_rows"] == 0
                assert result["authority_snapshot_hash"] == service.authority_snapshot_hash
                rows.append({"method_id": method_id, "foundation_id": foundation_id, "result": result})
        payload = canonical_json(rows).encode("utf-8")
        return len(rows), hashlib.sha256(payload).hexdigest()
    assert compute() == compute()
    assert compute()[0] == 3060


@pytest.mark.parametrize(
    "method_id,expected",
    [
        ("METHOD-001", {QI}),
        ("METHOD-002", {BODY}),
        ("METHOD-005", {SPIRIT}),
        ("METHOD-081", {BODY, QI}),
        ("METHOD-083", {BODY, SPIRIT}),
        ("METHOD-084", {QI, SPIRIT}),
        ("METHOD-085", {BODY, QI, SPIRIT}),
    ],
)
def test_method_gated_single_dual_and_triple_routes(authority, method_id, expected):
    service, db = authority
    insert_project(db, method_id)
    service.initialize_for_project(method_id, target_cl=10, method_id=method_id, access_source_records=access_evidence(db, service, method_id, method_id))
    result = service.ap_eligibility(method_id)
    actual = {row["path_id"] for row in result["paths"] if row["eligible"]}
    assert actual == expected
    assert result["thematic_compatibility_grants_ap"] is False


def test_dormant_paths_do_not_activate_resources_features_or_foundation_expressions(authority):
    service, db = authority
    insert_project(db, "dormant")
    state = service.initialize_for_project("dormant", target_cl=10, path_ids=[QI], method_id="METHOD-001", foundation_id="mud_lotus_dantian_v0_2A")
    assert [row["path_id"] for row in state["paths"] if row["status"] == "ACTIVE"] == [QI]
    for row in state["paths"]:
        assert row["resource"]["active"] is (row["path_id"] == QI)
    projection = state["foundation_projection"]
    assert projection["active_expression_path_ids"] == [QI]
    assert set(projection["dormant_expression_path_ids"]) == {BODY}
    assert SPIRIT not in projection["active_expression_path_ids"]
    assert projection["compatibility_grants_ap"] is False


def test_illegal_advancement_blocked_even_when_compatibility_exists(authority):
    service, db = authority
    insert_project(db, "blocked")
    service.initialize_for_project("blocked", target_cl=10, path_ids=[QI], method_id="METHOD-001", foundation_id="ancient_desolate_sacred_body_v0_2C")
    service.resolve_compatibility("METHOD-001", "ancient_desolate_sacred_body_v0_2C", [BODY, QI, SPIRIT])
    with pytest.raises(FoundryError) as exc:
        service.allocate_advancement("blocked", {BODY: 1}, evidence_id=ap_award(db,service,"blocked","METHOD-001",10,1), idempotency_key="test.ap.blocked")
    assert exc.value.code == "NS1R_METHOD_GATED_AP_ROUTE_BLOCKED"


def test_method_switch_preserves_attainment_and_resources_without_refill(authority):
    service, db = authority
    insert_project(db, "switch")
    service.initialize_for_project("switch", target_cl=10, path_ids=[BODY, QI, SPIRIT], method_id="METHOD-085", access_source_records=access_evidence(db, service, "switch", "METHOD-085"))
    service.set_resource("switch", BODY, current=2, maximum=9)
    before = service.get_state("switch")
    after = service.set_primary_method("switch", "METHOD-001")
    body_before = next(row for row in before["paths"] if row["path_id"] == BODY)
    body_after = next(row for row in after["paths"] if row["path_id"] == BODY)
    assert body_after["attainment"] == body_before["attainment"] == 1
    assert (body_after["resource"]["current"], body_after["resource"]["maximum"]) == (2, 9)
    assert after["method_switch_history"][-1]["event_stream_rewritten"] is False
    assert after["method_switch_history"][-1]["resources_restored"] is False
    assert service.ap_eligibility(after, BODY)["paths"][0]["eligible"] is False


def test_cl3_path_ownership_restricted_access_and_target_cl_preservation(authority):
    service, db = authority
    insert_project(db, "qi-subpath")
    service.initialize_for_project("qi-subpath", target_cl=10, path_ids=[QI], method_id="METHOD-001")
    qi_choice = next(row for row in service.subpaths.values() if row["owning_path_id"] == QI and not row["access"].get("access_source_record_required"))
    with pytest.raises(FoundryError) as exc:
        service.select_subpath("qi-subpath", QI, qi_choice["canonical_id"])
    assert exc.value.code == "NS1R_SUBPATH_CL3_REQUIRED"
    service.allocate_advancement("qi-subpath", {QI: 2}, evidence_id=ap_award(db,service,"qi-subpath","METHOD-001",10,2), idempotency_key="test.ap.qi.cl3")
    state = service.select_subpath("qi-subpath", QI, qi_choice["canonical_id"])
    assert next(row for row in state["paths"] if row["path_id"] == QI)["subpath_or_tradition_id"] == qi_choice["canonical_id"]
    with pytest.raises(FoundryError) as exc:
        service.select_subpath("qi-subpath", BODY, qi_choice["canonical_id"])
    assert exc.value.code == "NS1R_PATH_SUBPATH_MISMATCH"
    with pytest.raises(FoundryError) as exc:
        service.set_target_cl("qi-subpath", 2)
    assert exc.value.code == "NS1R_TARGET_CL_BELOW_HISTORICAL_ATTAINMENT"

    insert_project(db, "spirit-tradition")
    service.initialize_for_project("spirit-tradition", target_cl=10, path_ids=[SPIRIT], method_id="METHOD-005", access_source_records=access_evidence(db, service, "spirit-tradition", "METHOD-005"))
    service.allocate_advancement("spirit-tradition", {SPIRIT: 2}, evidence_id=ap_award(db,service,"spirit-tradition","METHOD-005",10,2), idempotency_key="test.ap.spirit.cl3")
    restricted = next(row for row in service.subpaths.values() if row["owning_path_id"] == SPIRIT and row["access"].get("access_source_record_required"))
    state = service.select_subpath("spirit-tradition", SPIRIT, restricted["canonical_id"])
    selected_path = next(row for row in state["paths"] if row["path_id"] == SPIRIT)
    assert selected_path["subpath_or_tradition_id"] == restricted["canonical_id"]
    assert selected_path["subpath_or_tradition_acquisition_provenance"]["content_type"] == "Spirit Tradition"
    assert selected_path["subpath_or_tradition_acquisition_provenance"]["access_category"] != "Open"


def test_duplicate_path_and_method_ids_fail_closed(authority):
    service, db = authority
    insert_project(db, "dupes")
    with pytest.raises(FoundryError) as exc:
        service.initialize_for_project("dupes", target_cl=5, path_ids=[QI, QI], method_id="METHOD-001")
    assert exc.value.code == "NS1R_DUPLICATE_PATH_ID"
    state = service.blank_state("dupes", 5)
    state["known_method_ids"] = ["METHOD-001", "METHOD-001"]
    with pytest.raises(FoundryError) as exc:
        service.save_state("dupes", state)
    assert exc.value.code == "NS1R_DUPLICATE_METHOD_ID"


def test_background_core_authority_keeps_talent_accounting_separate(authority):
    service, _ = authority
    catalog = service.background_catalog()
    assert catalog["count"] == 31
    assert all("ability_score_grants" in row and "skills" in row and "starting_equipment" in row and "origin_insight" in row and "background_sphere_talent_routes" in row for row in catalog["records"])
    row = next(x for x in catalog["records"] if not x["blockers"])
    result = service.validate_background(row["background_id"])
    assert result["background_talent_separate_from_ordinary_talents"] is True
    assert result["ready"] is True
    invalid = service.validate_background(row["background_id"], selected_route_ids={"ordinary_talent_id": "forbidden"})
    assert invalid["ready"] is False


def test_migration_is_fail_closed_and_never_rewrites_history(authority):
    service, _ = authority
    deterministic = service.migration_preview({"path_ids": [QI], "method_ids": ["METHOD-001"], "path_attainment": {QI: 7}})
    assert deterministic["status"] == "DETERMINISTIC"
    assert deterministic["inferred_primary_method_id"] == "METHOD-001"
    assert deterministic["event_stream_rewrite"] is False
    assert deterministic["retroactive_resource_grants"] is False
    blocked = service.migration_preview({"path_ids": [QI], "method_ids": []})
    assert blocked["status"] == "MIGRATION_REQUIRED"


def test_state_save_reopen_export_import_and_zero_events(authority):
    service, db = authority
    insert_project(db, "source")
    insert_project(db, "target")
    service.initialize_for_project("source", target_cl=10, path_ids=[QI], method_id="METHOD-001", foundation_id="mud_lotus_dantian_v0_2A")
    service.set_resource("source", QI, current=4, maximum=11)
    payload = service.export_state("source")
    assert payload and "credential" not in canonical_json(payload).casefold()
    imported = service.import_state("target", payload)
    assert imported["project_id"] == "target"
    assert imported["primary_method_id"] == "METHOD-001"
    assert next(row for row in imported["paths"] if row["path_id"] == QI)["resource"]["current"] == 4
    reopened = NonSphereAuthorityService(db).get_state("target")
    assert reopened["authority_snapshot_hash"] == service.authority_snapshot_hash
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_api_and_owner_ui_use_shared_non_sphere_service(tmp_path: Path):
    api_source = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
    for route in (
        "/api/non-sphere/authority/status", "/api/non-sphere/paths", "/api/non-sphere/methods",
        "/api/non-sphere/foundations", "/api/non-sphere/projects/{project_id}/state",
    ):
        assert route in api_source
    assert "non_sphere_authority = NonSphereAuthorityService(db)" in api_source
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "/api/non-sphere/" in js
    assert "nonSphereAuthorityPanel" in html
    assert "loadNonSphereAuthorityPanel" in js


def test_cat2_catalog_exact_preservation():
    data = ROOT / "catalog_authority" / "cat1" / "data"
    spheres = json.loads((data / "canonical_spheres.v1.json").read_text(encoding="utf-8"))
    talents = json.loads((data / "canonical_talents.v1.json").read_text(encoding="utf-8"))
    memberships = json.loads((data / "sphere_talent_memberships.v1.json").read_text(encoding="utf-8"))
    background_routes = json.loads((data / "background_origin_talent_routes.v1.json").read_text(encoding="utf-8"))
    status = json.loads((ROOT / "PACKAGE_VERSION.json").read_text(encoding="utf-8"))
    assert len(spheres["records"]) == status["canonical_sphere_count"] == 85
    assert len(talents["records"]) == status["canonical_talent_count"] == 1748
    assert len(memberships["records"]) == status["canonical_membership_count"] == 1748
    assert len(background_routes["records"]) == status["background_only_talent_route_count"] == 77
    assert status["automatic_base_ability_unique_count"] == 125
    assert status["quarantined_candidate_count"] == 25
    factory = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
    assert hashlib.sha256(factory.read_bytes()).hexdigest() == status["producer_corpus_sha256"]


def test_initial_multi_path_attainment_and_subpaths_persist_from_builder_authority(authority):
    service, db = authority
    insert_project(db, "multi-build", target_cl=5)
    body_choice = next(row for row in service.subpaths.values() if row["owning_path_id"] == BODY and not row["access"].get("access_source_record_required"))
    qi_choice = next(row for row in service.subpaths.values() if row["owning_path_id"] == QI and not row["access"].get("access_source_record_required"))
    state = service.initialize_for_project(
        "multi-build",
        target_cl=5,
        path_ids=[BODY, QI],
        method_id="METHOD-081",
        access_source_records=access_evidence(db, service, "multi-build", "METHOD-081"),
        path_attainment_by_id={BODY: 5, QI: 5},
        subpath_ids=[body_choice["canonical_id"], qi_choice["canonical_id"]],
    )
    by_path = {row["path_id"]: row for row in state["paths"]}
    assert by_path[BODY]["attainment"] == by_path[QI]["attainment"] == 5
    assert by_path[SPIRIT]["attainment"] == 0
    assert by_path[BODY]["subpath_or_tradition_id"] == body_choice["canonical_id"]
    assert by_path[QI]["subpath_or_tradition_id"] == qi_choice["canonical_id"]
    assert state["readiness"]["status"] == "READY"


def test_primary_method_switch_records_directional_future_ap_invalidation(authority):
    service, db = authority
    insert_project(db, "switch-invalidation")
    service.initialize_for_project("switch-invalidation", target_cl=10, path_ids=[BODY, QI, SPIRIT], method_id="METHOD-085", access_source_records=access_evidence(db, service, "switch-invalidation", "METHOD-085"))
    state = service.set_primary_method("switch-invalidation", "METHOD-001")
    body = next(row for row in state["paths"] if row["path_id"] == BODY)
    assert body["attainment"] == 1
    assert body["invalidations"][-1]["code"] == "PRIMARY_METHOD_NO_FUTURE_AP_ROUTE"
    assert body["invalidations"][-1]["historical_attainment_preserved"] is True
    assert state["method_switch_history"][-1]["future_ap_invalidated_path_ids"] == [BODY, SPIRIT]


def test_initial_open_method_context_does_not_weaken_post_creation_switch_gate(authority):
    service, db = authority
    insert_project(db, "post-creation-method-gate", target_cl=1)
    service.initialize_for_project(
        "post-creation-method-gate",
        target_cl=1,
        path_ids=[QI],
        method_id="METHOD-001",
    )
    with pytest.raises(FoundryError) as exc:
        service.set_primary_method("post-creation-method-gate", "METHOD-081")
    assert exc.value.code == "NS1R_METHOD_ACCESS_REQUIRED"
