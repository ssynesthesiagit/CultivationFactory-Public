from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import _character_creation_api_view, create_app
from app.core import FoundryError
from character_creation.service import CharacterCreationExecutionService
from character_builder.service import CharacterBuilderService
from non_sphere_authority import NonSphereAuthorityService
from path_method_authority import CANONICAL_PATH_IDS


ROOT = Path(__file__).resolve().parents[1]


def test_method_compatibility_is_bounded_and_shared_with_initial_creation_authority(catalog_environment, monkeypatch):
    service = CharacterBuilderService(catalog_environment["db"])

    empty = service.method_compatibility([])
    assert empty["schema"] == "TianxiaFoundry.CharacterBuilderMethodCompatibility.v1"
    assert empty["selected_path_ids"] == []
    assert empty["compatible_methods"]
    assert empty["authority"]["predicate"] == "every required Path has an explicit Method AP grant"

    required = [CANONICAL_PATH_IDS[0], CANONICAL_PATH_IDS[1]]
    result = service.method_compatibility(required)
    assert result["selected_path_ids"] == required
    assert result["selected_paths"] == ["Body Refining", "Qi Cultivation"]
    assert result["compatible_methods"]
    for method in result["compatible_methods"]:
        assert method["initial_creation_selectable"] is True
        assert set(required).issubset(method["supported_path_ids"])

    with pytest.raises(FoundryError) as duplicate:
        service.method_compatibility([CANONICAL_PATH_IDS[0], CANONICAL_PATH_IDS[0]])
    assert duplicate.value.code == "NS1R_DUPLICATE_PATH_ID"

    with pytest.raises(FoundryError) as unknown:
        service.method_compatibility(["not-a-canonical-path"])
    assert unknown.value.code == "NS1R_PATH_ID_UNKNOWN"

    def synthetic_catalog(_authority, state=None, *, initial_creation=None):
        assert state is None
        assert initial_creation is True
        return {
            "records": [
                {
                    "method_id": "synthetic.method",
                    "name": "Synthetic Method",
                    "initial_creation_selectable": True,
                    "explicit_ap_grants": [
                        {"path_id": "BODY_REFINING", "grants_attainment_points": True},
                    ],
                    "method_planning": {"access_tier": "OPEN_SECT_BASIC", "access_text": "Synthetic test method."},
                },
            ],
        }

    monkeypatch.setattr(NonSphereAuthorityService, "method_catalog", synthetic_catalog)
    synthetic = service.method_compatibility([CANONICAL_PATH_IDS[0]])
    assert [row["method_id"] for row in synthetic["compatible_methods"]] == ["synthetic.method"]
    assert synthetic["compatible_methods"][0]["supported_paths"] == ["Body Refining"]
    assert service.method_compatibility([CANONICAL_PATH_IDS[1]])["compatible_methods"] == []


def test_method_compatibility_endpoint_enforces_request_contract(catalog_environment):
    app = create_app(catalog_environment["settings"])
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        headers = {"X-Foundry-Token": token}
        response = client.post(
            "/api/character-builder/method-compatibility",
            headers=headers,
            json={"selected_path_ids": [CANONICAL_PATH_IDS[0]]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["selected_path_ids"] == [CANONICAL_PATH_IDS[0]]
        assert all(row["initial_creation_selectable"] is True for row in payload["compatible_methods"])
        assert payload["authority"]["authority_snapshot_sha256"]

        too_many = client.post(
            "/api/character-builder/method-compatibility",
            headers=headers,
            json={"selected_path_ids": list(CANONICAL_PATH_IDS) + [CANONICAL_PATH_IDS[0]]},
        )
        assert too_many.status_code == 422
        assert too_many.json()["error"]["code"] == "REQUEST_SCHEMA_INVALID"

        extra = client.post(
            "/api/character-builder/method-compatibility",
            headers=headers,
            json={"selected_path_ids": [], "inferred_method_ids": ["synthetic.method"]},
        )
        assert extra.status_code == 422
        assert extra.json()["error"]["code"] == "REQUEST_SCHEMA_INVALID"


def test_character_creation_api_view_uses_bounded_owner_projection_and_eight_screen_state():
    run = {
        "run_id": "run-owner-view",
        "project_id": "project-owner-view",
        "status": "READY_FOR_REVIEW",
        "request": {
            "request_sha256": "request-hash",
            "content_lock_hash": "content-hash",
            "delegated_choice_envelope": {
                "choices_by_slot": {
                    "method_choice": {"method-1": {"name": "Measured Method"}},
                    "foundation_choice": {"foundation-1": {"name": "Iron Foundation"}},
                    "subpath_choice": {"subpath-1": {"name": "Cinder Tradition"}},
                },
                "owner_locks": {"by_slot": {"path_choice": [CANONICAL_PATH_IDS[1]]}},
            },
        },
        "response": {"response_sha256": "response-hash"},
        "final_plan": {
            "target_cl": 20,
            "resolution": {
                "selected_path_ids": [CANONICAL_PATH_IDS[1]],
                "actual_advancing_path_ids": [CANONICAL_PATH_IDS[1]],
                "method_granted_path_ids": [CANONICAL_PATH_IDS[1]],
                "method_id": "method-1",
                "foundation_id": "foundation-1",
                "selected_choices_by_slot": {"subpath_choice": ["subpath-1"]},
                "provenance": [{"slot_id": "method_choice", "choice_id": "method-1", "provenance": "owner", "status": "accepted"}],
            },
        },
        "dry_run": {
            "schema": "TianxiaFoundry.CompiledCharacterCandidate.v3",
            "deterministic": True,
            "independent_compilations": 2,
            "preview": {
                "target_cl": 20,
                "compiled": {
                    "character_sheet": {
                        "owner_character_sheet": {
                            "identity": {"display_name": "Jiang Yun", "concept": "A test concept", "cultivation_level": 20, "realm": "Ascendant"},
                             "path_and_subpath": {"path": {"name": "Qi Cultivation"}, "subpath": {"name": "Cinder Tradition"}, "paths": [{"path_id": CANONICAL_PATH_IDS[1], "status": "ACTIVE", "attainment": 9}]},
                            "method": {"name": "Measured Method"},
                            "foundation": {"name": "Iron Foundation"},
                            "selected_record_sections": {
                                "sphere": [{"record_id": "sphere-1", "name": "Flame Sphere"}],
                                "talent": [
                                    {"record_id": "talent-free", "name": "Free Flame Talent", "acquisition_route": "new_sphere_bonus_talent_acquisition"},
                                    {"record_id": "talent-ordinary", "name": "Ordinary Flame Talent", "acquisition_route": "level_talent_acquisition"},
                                ],
                            },
                            "spheres_and_talents": {"automatic_sphere_components": [{"name": "Heat Sense"}]},
                        },
                    },
                },
            },
        },
        "outputs": {},
        "validation": {},
        "transport": {},
        "blockers": [],
        "warnings": [],
        "quality": {"status": "CLEAN"},
        "commit": {},
        "action_availability": {},
        "owner_descriptive_fields": {"resolved": {}, "proposed": {}},
    }

    view = _character_creation_api_view(run)
    assert view["owner_view"]["display_state"] == {"status": "READY_FOR_REVIEW", "step": 4, "label": "Ready For Review"}
    assert view["owner_view"]["next_legal_action"]["target_step"] == 4
    assert view["owner_view"]["identity"]["target_cl"] == 20
    assert view["owner_view"]["paths"][1]["state"] == "advancing"
    assert view["owner_view"]["paths"][1]["attainment"] == 9
    assert view["owner_view"]["method"]["name"] == "Measured Method"
    assert view["owner_view"]["scratch_candidate"]["sheet"]["spheres"] == [{"name": "Flame Sphere"}]
    assert view["owner_view"]["scratch_candidate"]["sheet"]["free_talents"] == [{"name": "Free Flame Talent", "acquisition": "free"}]
    assert view["owner_view"]["scratch_candidate"]["sheet"]["ordinary_talents"] == [{"name": "Ordinary Flame Talent", "acquisition": "ordinary"}]
    assert "compiled" not in view["dry_run"]["preview"]
    assert "final_plan" not in view
    assert view["diagnostics"]["final_plan"]["target_cl"] == 20
    assert "resolution" not in view["diagnostics"]["final_plan"]


def test_cancelled_owner_state_uses_terminal_step_eight_without_changing_legacy_stage():
    run = {"status": "CANCELLED", "request": {}, "final_plan": {}, "dry_run": {}, "outputs": {}}
    owner = _character_creation_api_view(run)["owner_view"]
    assert CharacterCreationExecutionService._owner_stage_for_status("CANCELLED") == 8
    assert CharacterCreationExecutionService._stage_for_status("CANCELLED") == 2
    assert owner["display_state"]["step"] == 8
    assert owner["next_legal_action"]["target_step"] == 1
    assert owner["next_legal_action"]["label"] == "Start a deliberate new build"


def test_owner_diagnostics_are_compact_even_when_stored_receipts_are_large():
    run = {
        "run_id": "bounded-large-run",
        "status": "READY_FOR_REVIEW",
        "request": {},
        "response": {},
        "dry_run": {},
        "final_plan": {"target_cl": 20, "resolution": {"selected_choices_by_slot": {"sphere_priorities": [str(index) for index in range(4000)]}}, "receipt": "x" * 250000},
        "validation": {"errors": ["x" * 1000 for _ in range(500)], "receipt": "y" * 250000},
        "transport": {"provider_called": False},
        "outputs": {},
    }
    view = _character_creation_api_view(deepcopy(run))
    assert view["diagnostics"]["final_plan"]["target_cl"] == 20
    assert view["diagnostics"]["final_plan"]["size_bytes"] > 250000
    assert "receipt" not in view["diagnostics"]["final_plan"]
    assert "errors" not in view["diagnostics"]["validation"]
    assert view["diagnostics"]["full_evidence_endpoint"].endswith("/evidence.json")


def test_production_owner_shell_has_one_eight_screen_contract_and_readable_responsive_surface():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "static/app.js").read_text(encoding="utf-8")
    styles = (ROOT / "static/styles.css").read_text(encoding="utf-8")

    assert '<a class="skip-link" href="#ownerWorkspace">' in html
    assert 'class="production-banner"' in html
    assert 'id="ownerStepNav"' in html
    assert len(re.findall(r'data-owner-step="[1-8]"', html)) == 8
    for panel_id in (
        "builderDescribe",
        "builderPaths",
        "builderAI",
        "builderReview",
        "builderInsights",
        "builderSpheres",
        "builderSheet",
        "builderExport",
    ):
        assert f'id="{panel_id}"' in html
    assert 'data-owner-step="1" aria-current="step"' in html
    assert 'id="diagnosticsDrawer"' in html
    assert 'role="dialog" aria-modal="true"' in html

    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))

    assert '"/api/character-builder/method-compatibility"' in javascript
    assert "methodCompatibilityRequestSerial" in javascript
    assert "ownerViewFor" in javascript
    assert "Path requirements changed. Check compatibility again." in javascript
    assert "AUTO_FINALIZE_WHEN_CLEAN" in javascript
    assert html.count('role="tab"') >= 4  # two route tabs plus the two response-import tabs and retained product tabs
    assert html.count('data-guided-route=') == 2
    assert 'id="sheetInsightCards"' in html
    assert 'id="sheetSphereCatalog"' in html
    assert 'id="ownerCustomizationSection"' in html
    assert "planningIsEditable" in javascript
    assert "Edit Brief / Create New Request is required" in javascript
    assert 'aria-selected="true"' in html
    assert "setDiagnostics(false)" in javascript
    assert 'event.key === "Escape"' in javascript
    assert "No priority cap" in html
    assert "choose any number of valid priorities" in javascript

    assert "@media (max-width: 860px)" in styles
    assert "@media (max-width: 560px)" in styles
    assert ".owner-step-nav { position: sticky" in styles
    assert ".owner-production-sheet { display: grid" in styles
    assert ".diagnostics-drawer.is-open" in styles
    assert "rec1-p1cr3-owner-view" in html
    assert not (ROOT / "package.json").exists()
