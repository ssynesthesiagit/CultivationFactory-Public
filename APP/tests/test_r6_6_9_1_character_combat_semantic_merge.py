from __future__ import annotations

import json
import re
from pathlib import Path

from app.api import create_app
from app.core import APP_STATUS, APP_VERSION, Settings

ROOT = Path(__file__).resolve().parents[1]


def test_combined_api_exposes_character_and_polished_combat_authority(tmp_path):
    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "data"))
    paths = {route.path for route in app.routes}
    required = {
        "/api/characters",
        "/api/characters/{project_id}/sheet",
        "/api/characters/{project_id}/gm-export/status",
        "/api/characters/{project_id}/gm-export",
        "/api/character-builder/options",
        "/api/stage1/prompts/{prompt_id}/responses/load-zip",
        "/api/combat/catalog",
        "/api/combat/matches",
        "/api/combat/matches/{match_id}/presentation",
        "/api/combat/matches/{match_id}/preview",
        "/api/combat/matches/{match_id}/intent",
    }
    assert required <= paths
    assert app.state.combat.ai_provider is app.state.ai_provider


def test_character_library_uses_one_compact_workflow_map_and_keeps_sheet_audit(tmp_path, monkeypatch):
    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "character-library-recovery"))
    projects = app.state.projects
    character_sheets = app.state.character_sheets
    character_creation = app.state.character_creation
    portable_characters = app.state.portable_characters
    # The per-project chooser cache discovers IDs/change markers from SQLite;
    # sheet and workflow construction remain isolated by the stand-ins below.
    active_id = "00000000-0000-4000-8000-000000000001"
    no_run_id = "00000000-0000-4000-8000-000000000002"
    with projects.db.transaction() as conn:
        for project_id, name in [(active_id, "Project Active"), (no_run_id, "Project No Run")]:
            conn.execute(
                """INSERT INTO projects (
                    project_id, working_name, status, revision, created_at, updated_at,
                    target_factory_version, target_candidate_schema_version, target_gm_screen_version,
                    quality_target, project_json, compatibility_projection_status,
                    compile_status, consumer_verification_status
                ) VALUES (?, ?, 'draft', 0, 'fixture', 'fixture', 'fixture', 'fixture',
                          'fixture', 'rival/boss', '{}', 'DRAFT', 'NOT_COMPILED', 'NOT_RUN')""",
                (project_id, name),
            )
    rows = [
        {"project_id": active_id, "name": "AI-proposed character"},
        {"project_id": no_run_id, "name": "Existing character"},
    ]
    project_rows = [
        {
            "project_id": active_id,
            "working_name": "Project Active",
            "status": "draft",
            "compile_status": "NOT_COMPILED",
            "updated_at": "2",
            "builder_lifecycle": {"persistence_state": "temporary"},
        },
        {
            "project_id": no_run_id,
            "working_name": "Project No Run",
            "status": "draft",
            "compile_status": "NOT_COMPILED",
            "updated_at": "1",
            "builder_lifecycle": {"persistence_state": "temporary"},
        },
    ]
    compact_workflow = {
        "schema": "TianxiaFoundry.CharacterCreationRecovery.v1",
        "project_id": active_id,
        "project_name": "Compact Active",
        "active": True,
        "active_run": {"run_id": "run-active", "status": "NEEDS_REVIEW"},
        "latest_run": {"run_id": "run-active", "status": "NEEDS_REVIEW"},
    }
    recovery_calls = []
    monkeypatch.setattr(projects, "list_projects", lambda: project_rows)
    monkeypatch.setattr(character_creation, "recoverable", lambda: [compact_workflow])
    monkeypatch.setattr(character_sheets, "list_characters", lambda: (_ for _ in ()).throw(AssertionError("library must not build character sheets")))
    monkeypatch.setattr(portable_characters, "verified_status", lambda _project_id: (_ for _ in ()).throw(AssertionError("library must not verify portable readiness")))
    monkeypatch.setattr(character_creation, "recovery", lambda project_id: recovery_calls.append(project_id) or {"project_id": project_id})

    list_route = next(route for route in app.routes if route.path == "/api/character-library")
    listed = list_route.endpoint()

    assert recovery_calls == []
    assert listed[0]["workflow"] is compact_workflow
    assert listed[0]["workflow"]["active_run"] == {"run_id": "run-active", "status": "NEEDS_REVIEW"}
    assert listed[0]["name"] == "Project Active"
    assert listed[0]["build_status"] == "NEEDS_REVIEW"
    assert listed[1]["workflow"]["active"] is False

    monkeypatch.setattr(character_sheets, "list_row", lambda project_id: next(dict(row) for row in rows if row["project_id"] == project_id))
    monkeypatch.setattr(portable_characters, "verified_status", lambda _project_id: None)
    full_recovery = {"project_id": active_id, "audit": "full"}
    def recovery(project_id, *, audit_provider=True):
        recovery_calls.append((project_id, audit_provider))
        return full_recovery

    monkeypatch.setattr(character_creation, "recovery", recovery)
    characters_route = next(route for route in app.routes if route.path == "/api/characters")
    characters = characters_route.endpoint()
    assert recovery_calls == [(active_id, False), (no_run_id, False)]
    assert characters[0]["workflow"] is full_recovery
    recovery_calls.clear()
    assert characters_route.endpoint() == characters
    assert recovery_calls == []  # unchanged project rows reuse the compact cache

    monkeypatch.setattr(character_sheets, "sheet", lambda project_id: {"project_id": project_id, "sheet": "full"})
    sheet_route = next(route for route in app.routes if route.path == "/api/characters/{project_id}/sheet")
    recovery_calls.clear()
    sheet = sheet_route.endpoint(active_id)
    assert recovery_calls == [(active_id, True)]
    assert sheet["workflow"] is full_recovery


def test_character_library_prefers_latest_run_when_no_current_active_run(tmp_path, monkeypatch):
    app = create_app(settings=Settings.from_env(ROOT, tmp_path / "character-library-finalized-latest"))
    project_rows = [{
        "project_id": "p-finalized",
        "working_name": "Finalized Project",
        "status": "draft",
        "compile_status": "NOT_COMPILED",
        "updated_at": "1",
        "builder_lifecycle": {"persistence_state": "saved"},
    }]
    workflow = {
        "project_id": "p-finalized",
        "active": False,
        "active_run": None,
        "latest_run": {"run_id": "run-finalized", "status": "CLEAN_AND_FINALIZED"},
    }
    monkeypatch.setattr(app.state.projects, "list_projects", lambda: project_rows)
    monkeypatch.setattr(app.state.character_creation, "recoverable", lambda: [workflow])

    list_route = next(route for route in app.routes if route.path == "/api/character-library")
    listed = list_route.endpoint()

    assert listed[0]["build_status"] == "CLEAN_AND_FINALIZED"
    assert listed[0]["workflow"]["active_run"] is None
    assert listed[0]["workflow"]["latest_run"]["status"] == "CLEAN_AND_FINALIZED"


def test_combined_owner_ui_preserves_character_workflow_and_exact_combat_workspace():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    assert "Character Sheets" in html
    assert "TIANXIA COMBAT" in html
    # Updated 2026-08-25 (Ox Alpha): accumulated authorized product work
    # renamed the chat-request affordances; pin their current exact labels.
    assert "Stage Chat Request ZIP" in html
    assert "Save Complete Request ZIP" in html
    assert "Export Character ZIP for GM Screen" in html
    assert 'schema_version: "TianxiaFoundry.Stage2AdvancementProposal.v2"' in js
    assert 'api("/api/character-library")' in js
    ids = re.findall(r'id="([^"]+)"', html)
    assert len(ids) == len(set(ids))


def test_successor_identity_preserves_both_authoritative_parents():
    assert APP_VERSION == "0.6.6.9.2-CAT2-CANONICAL-CATALOG"
    assert APP_STATUS == "CANONICAL_CATALOG_PRODUCT_INTEGRATION_READY_COMBATANT_LIBRARY_PRE_ENCOUNTER"
    version = json.loads((ROOT / "packaging/windows_portable/VERSION.json").read_text(encoding="utf-8"))
    assert version["authoritative_polished_combat_parent_sha256"] == "1896ea1d5ec61f0f8cfc42282bd84f4369ce5605cfb777d5a553efc24dea79ce"
    assert version["character_factory_feature_parent_sha256"] == "e1a42986475354c78f858698a227bbd0959f386a6c4fa965969c0b6aa8b5e495"
