from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.core import FoundryError
from ai_provider.secrets import InMemorySecretStore
from ai_provider.service import AIProviderService
from character_builder import CharacterBuilderService
from character_builder.insight_authority import classify_insight_authority, resolve_insight_occurrences
from character_creation.service import CharacterCreationExecutionService
from non_sphere_authority import NonSphereAuthorityService
from project_store.service import ProjectStore


def test_method_planning_matrix_covers_all_102_with_simple_server_projected_routes(fresh_db):
    records = NonSphereAuthorityService(fresh_db).method_catalog(initial_creation=True)["records"]
    assert len(records) == 102
    assert {row["method_id"] for row in records} == {f"METHOD-{index:03d}" for index in range(1, 103)}
    assert all(row["method_planning"]["preference_allowed"] for row in records)
    assert all(row["method_planning"]["auto_allowed"] for row in records)
    assert all(row["method_planning"]["required_record"]["authority_type"] == "method_access" for row in records)
    assert all(row["method_planning"]["exact_selection_available"] for row in records)
    assert sum(row["method_planning"]["direct_initial_acquisition_available"] for row in records) == 2
    assert all(row["method_planning"]["source_reference"]["method_record_sha256"] for row in records)
    assert all(
        option["choice_id"].startswith("route-") and option["label"] and option["description"]
        for row in records for option in row["method_planning"]["owner_route_options"]
    )


def test_exact_method_choice_blocks_without_route_then_materializes_server_authority(catalog_environment):
    fresh_db = catalog_environment["db"]
    builder = CharacterBuilderService(fresh_db)
    methods = {
        row["choice_id"]: row
        for row in next(category for category in builder.options()["categories"] if category["slot_id"] == "method_choice")["choices"]
    }
    method = methods["METHOD-002"]
    base = {
        "working_name": "Exact Method access route",
        "concept": "Owner-bound route compilation",
        "target_cl": 1, "power_band": "rival/boss", "source_reference": None,
        "creation_mode": "detailed", "ability_scores": {},
        "selections": {"method_choice": ["METHOD-002"]},
        "method_planning_mode": "EXACT",
    }
    with pytest.raises(FoundryError) as exc:
        builder.create_project(**base)
    assert exc.value.code == "CHARACTER_METHOD_LEARNING_ROUTE_REQUIRED"

    access = method["method_planning"]
    created = builder.create_project(**base, method_route_choice=access["owner_route_options"][0]["choice_id"], method_learning_note="Met during the first journey.")
    assert created["character_sheet"]["non_sphere_state"]["primary_method_id"] is None
    assert created["character_sheet"]["planning_preferences"]["method_exact_choice_id"] == "METHOD-002"
    project = ProjectStore(fresh_db).get_project(created["project_id"])
    envelope = project.get("project") or project
    locks = {row["field"]: row["value"] for row in envelope["user_locks"]}
    internal = locks["character_sheet.method_access_plan"]
    assert internal["route_type"] == access["owner_route_options"][0]["description"]
    assert internal["owner_annotation"] == "Met during the first journey."
    assert internal["source_reference"]["method_record_sha256"]
    assert internal["route_commitment_sha256"]

    execution = object.__new__(CharacterCreationExecutionService)
    execution.db = fresh_db
    execution.projects = ProjectStore(fresh_db)
    run = {"run_id": "cg1.run.method-access", "project_id": created["project_id"]}
    receipt = execution._materialize_method_hard_lock(run, fresh_db, phase="scratch_compile")
    assert receipt["primary_method_id"] == "METHOD-002"
    assert execution._materialize_method_hard_lock(run, fresh_db, phase="finalization") == receipt
    state = NonSphereAuthorityService(fresh_db).get_state(created["project_id"])
    assert state["primary_method_id"] == "METHOD-002"
    evidence = next(row for row in state["access_source_records"] if row["authority_type"] == "method_access")
    assert evidence["route_type"] == internal["route_type"]
    assert evidence["source_reference"] == internal["source_reference"]
    assert evidence["method_registry_commitment_sha256"] == internal["method_registry_commitment_sha256"]


def test_insight_authority_uses_explicit_bindings_and_never_defaults_missing_to_general():
    sphere = classify_insight_authority(
        {"record_id": "insight.fire", "sphere": "Fire", "category": "General Insights", "prerequisites": "Fire Sphere"},
        record_id="insight.fire",
    )
    assert sphere["authority_type"] == "Sphere"
    assert sphere["binding_records"][0]["binding_id"] == "Fire"
    unresolved = classify_insight_authority({}, record_id="insight.unknown")
    assert unresolved["authority_type"] == "Unresolved"
    assert unresolved["classification_code"] == "UNRESOLVED_INSIGHT_CLASSIFICATION"
    explicit_general = classify_insight_authority({"category": "General Insights"}, record_id="insight.general")
    assert explicit_general["authority_type"] == "General"
    sphere_with_path_requirement = classify_insight_authority(
        {"record_id": "insight.tempered", "sphere": "Fire", "legal_path_requirements": ["Body Refining"]},
        record_id="insight.tempered",
    )
    assert sphere_with_path_requirement["authority_type"] == "Sphere"
    assert sphere_with_path_requirement["prerequisites"] == "Legal Paths: Body Refining"
    assert {row["binding_role"] for row in sphere_with_path_requirement["binding_records"]} == {"controlling", "prerequisite"}


def test_insight_duplicate_resolution_uses_exact_supersession_and_matrix_has_zero_duplicate_ids():
    resolution = resolve_insight_occurrences([
        {"raw_record": {"record_id": "insight.same", "category": "General Insights"}, "source_reference": {"source_anchor": "records[1]"}},
        {"raw_record": {"record_id": "insight.same", "execution_status": "superseded_source_record", "superseded_by": "insight.same"}, "source_reference": {"source_anchor": "records[2]"}},
    ], record_id="insight.same")
    assert resolution["resolved"] is True
    assert resolution["collision_disposition"] == "CONSOLIDATED_EXPLICIT_SUPERSESSION"
    assert resolution["source_occurrence_count"] == 2

    matrix = json.loads((Path(__file__).resolve().parents[2] / "win1_p1r2" / "INSIGHT_SOURCE_AUTHORITY_MATRIX.json").read_text(encoding="utf-8"))
    ids = [row["record_id"] for row in matrix["records"]]
    assert len(ids) == 456 == len(set(ids))
    assert matrix["summary"]["duplicate_canonical_record_id_count"] == 0
    assert matrix["summary"]["resolved_duplicate_record_id_count"] == 3
    assert matrix["summary"]["unresolved_duplicate_record_id_count"] == 0


def test_primary_wizard_contains_only_simple_method_controls():
    static = Path(__file__).resolve().parents[1] / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    javascript = (static / "app.js").read_text(encoding="utf-8")
    wizard = html[html.index('<fieldset class="method-planning-field"'):html.index("</fieldset>", html.index('<fieldset class="method-planning-field"'))]
    assert "Choose for me" in wizard
    assert "I prefer this Method" in wizard
    assert "Use this Method" in wizard
    assert "How did this character learn this Method?" in wizard
    for forbidden in ("Hard Lock", "access tier", "route_type", "source_name", "source_reference", "stable ID", "schema", "hash"):
        assert forbidden not in wizard
    character_sheet = html[html.index('<section id="characterSheetPanel"'):html.index("</section>", html.index('<section id="characterSheetPanel"'))]
    assert "hard owner locks" not in character_sheet.lower()
    assert '<div id="sheetPaths" class="path-choice-list"></div>' in html
    assert 'selectedSet("path_choice")' in javascript
    assert 'requiredPaths.every(pathId => (choice.related_choice_ids || []).includes(pathId))' in javascript
    assert 'The selected Method must support every selected Path.' in javascript


def test_complete_request_save_receipt_is_small_and_exactly_bound():
    service = object.__new__(CharacterCreationExecutionService)
    request = {
        "request_sha256": "a" * 64,
        "content_lock_hash": "b" * 64,
        "typed_choice_snapshot": {"snapshot_sha256": "c" * 64, "large_projection": "x" * (3 * 1024 * 1024)},
    }
    service.get = lambda _run_id: {
        "run_id": "cg1.run." + "d" * 32,
        "project_id": "project-receipt",
        "starting_revision": 9,
        "request": request,
    }
    receipt = service.complete_request_save_receipt("cg1.run." + "d" * 32)
    encoded = json.dumps(receipt).encode()
    assert len(encoded) < 4096
    assert receipt["request"]["typed_choice_snapshot"] == {"snapshot_sha256": "c" * 64}
    assert receipt["filename"] == f"CG1_COMPLETE_REQUEST_project-receipt_{'a' * 12}.zip"


def test_owner_connection_test_uses_deepseek_mock_and_never_returns_secret(fresh_db):
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers.get("authorization")
        observed["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"connection":"ok"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    secret = "test-deepseek-secret-123"
    service = AIProviderService(fresh_db, transport=httpx.MockTransport(handler), secret_store=InMemorySecretStore(secret))
    service.configure(
        enabled=True, model="deepseek-v4-flash", thinking_mode="disabled", max_output_tokens=1024,
        timeout_seconds=30, data_sharing_acknowledged=True, acknowledged_by="Owner Test",
    )
    result = service.test_connection()
    assert result["status"] == "PASS" and result["secret_returned"] is False
    assert secret not in json.dumps(result)
    assert observed["authorization"] == f"Bearer {secret}"
    assert observed["body"]["model"] == "deepseek-v4-flash"
