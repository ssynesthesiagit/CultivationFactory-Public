"""S5: owner-facing progress and continue routes, default-on guided controller UI.

Provider-free.  The progress view exposes step position, state, and
catalogue names only; never option cues, choice IDs, menus, or hashes.
"""

from __future__ import annotations

import re

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import test_dcc_stage_b_route as stage_b
from app.api import create_app
from app.core import Database
from character_creation.creative_controller import DETERMINISTIC_CREATIVE_CONTROLLER, build_route_binding
from character_creation.creative_controller.linear_menus import MAX_WALK_STEPS, CommittedState
from character_creation.creative_controller.linear_persistence import WALK_STARTED, LinearWalkPersistence
from character_creation.creative_controller.route_persistence import ControllerRoutePersistence
from character_creation.service import CharacterCreationExecutionService

STATIC = Path(__file__).resolve().parents[1] / "static"


def _seed_walk_run(db: Database, run_id: str) -> dict:
    binding = build_route_binding(DETERMINISTIC_CREATIVE_CONTROLLER)
    request = {
        "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
        "project_id": "p",
        "project_revision": 0,
        "content_lock_hash": "a" * 64,
        "controller_route": DETERMINISTIC_CREATIVE_CONTROLLER,
        "controller_route_binding": binding,
        "delegated_choice_envelope": {
            "choices_by_slot": {
                "path_choice": {
                    "path.qi": {"choice_id": "path.qi", "name": "Qi Cultivation"},
                    "path.body": {"choice_id": "path.body", "name": "Body Refining"},
                },
                "sphere_priorities": [{"choice_id": "sphere.alchemy", "name": "Alchemy"}],
            },
        },
    }
    request["request_sha256"] = CharacterCreationExecutionService.request_payload_sha256(request)
    stage_b._run(db, run_id, request=request)
    with db.transaction() as conn:
        ControllerRoutePersistence(db).bind_run(
            conn,
            run_id=run_id,
            project_id="p",
            request_sha256=request["request_sha256"],
            binding=binding,
            created_at="2026-09-02T00:00:00Z",
        )
    persistence = LinearWalkPersistence(db)
    projection = persistence.projection(run_id)
    assert projection is not None
    state = CommittedState.empty().with_slot("path_choice", ["path.qi"]).with_slot("sphere_priorities", ["sphere.alchemy"])
    started = persistence.append_event(
        run_id,
        event_type=WALK_STARTED,
        subject_sha256=request["request_sha256"],
        state_sha256_before=projection["state_sha256"],
        state_sha256_after=CommittedState.empty().committed_sha256,
        payload={"steps_estimate": 22, "ceilings": {"max_steps": MAX_WALK_STEPS}},
    )
    persistence.save_snapshot(run_id, 2, state, started["event_sha256"])
    return request


def test_l5_progress_route_reports_position_and_catalogue_names_only(tmp_path: Path) -> None:
    db = stage_b._db(tmp_path)
    _seed_walk_run(db, "walk-progress")
    app = create_app(db.settings)
    with TestClient(app) as client:
        response = client.get("/api/character-creation/runs/walk-progress/controller/progress")
        listing = client.get("/api/projects/p/character-creation/runs")
        active = client.get("/api/projects/p/character-creation/controller/active")
        empty = client.get("/api/projects/nobody/character-creation/controller/active")

    assert response.status_code == 200, response.text
    progress = response.json()
    assert progress["schema"] == "TianxiaFoundry.DccLinearWalkProgress.v1"
    assert progress["run_id"] == "walk-progress"
    assert progress["walk"]["state"] == "RUNNING"
    assert progress["walk"]["step_ordinal"] == 2
    assert progress["walk"]["steps_estimate"] == 22
    by_title = {row["title"]: row for row in progress["committed_choices"]}
    assert by_title["Path"]["names"] == ["Qi Cultivation"]
    assert by_title["Sphere Priorities"]["names"] == ["Alchemy"]
    serialized = json.dumps(progress, sort_keys=True)
    assert "path.qi" not in serialized
    assert "sphere.alchemy" not in serialized
    assert "sha256" not in serialized
    assert "cue" not in serialized
    assert progress["can_continue"] is False
    assert active.status_code == 200 and active.json()["run_id"] == "walk-progress"
    assert empty.status_code == 200 and empty.json()["run_id"] is None

    # The run list carries the bounded walk position for polling clients and
    # still redacts binding, event bodies, and hashes.
    public = next(row for row in listing.json()["runs"] if row["run_id"] == "walk-progress")
    assert public["controller_route_status"]["walk"] == {"state": "RUNNING", "step_ordinal": 2, "steps_estimate": 22}
    assert "event_head_sha256" not in json.dumps(public["controller_route_status"]["walk"])


def test_l5_progress_and_continue_reject_legacy_runs(tmp_path: Path) -> None:
    db = stage_b._db(tmp_path)
    stage_b._run(db, "legacy-run", request={"schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3", "project_id": "p", "controller_route": "LEGACY_FULL_PLAN"})
    app = create_app(db.settings)
    with TestClient(app) as client:
        headers = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
        progress = client.get("/api/character-creation/runs/legacy-run/controller/progress")
        resumed = client.post("/api/character-creation/runs/legacy-run/controller/continue", json={}, headers=headers)
    assert progress.status_code == 409, progress.text
    assert progress.json()["error"]["code"] == "DCC_LINEAR_ROUTE_REQUIRED"
    assert resumed.status_code == 409, resumed.text
    assert resumed.json()["error"]["code"] == "DCC_LINEAR_ROUTE_REQUIRED"


def test_l5_step_titles_never_leak_ids() -> None:
    title = CharacterCreationExecutionService._dcc_step_title
    assert title("path_progression:12") == "Path Progression"
    assert title("insight_occurrence:tianxia.path.qi.feature.cl8:ability") == "Insight Occurrence"
    assert title("identity") == "Identity"
    assert title(None) is None


def test_l5_guided_ui_defaults_to_the_controller_with_an_advanced_opt_out() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="guidedLegacyFullPlanOptOut" type="checkbox"' in html
    assert "Advanced: use the legacy full-plan prompt" in html
    assert 'id="guidedControllerProgress"' in html
    assert 'id="guidedResumeControllerWalk"' in html
    assert "Resume Guided Build" in html
    assert 'const GUIDED_CONTROLLER_ROUTE = "DETERMINISTIC_CREATIVE_CONTROLLER";' in javascript
    assert "if (useController) startBody.controller_route = GUIDED_CONTROLLER_ROUTE;" in javascript
    # Manual Chat never uses the controller; a seeded project (no AI) always does,
    # whichever build button is pressed (2026-09-24); otherwise only Local AI does.
    assert 'if (mode === "MANUAL_CHAT") return false;\n  if (guidedAutogenSeed) return true;\n  if (route !== "LOCAL_AI") return false;' in javascript
    assert 'return !document.getElementById("guidedLegacyFullPlanOptOut")?.checked;' in javascript
    assert "/controller/progress" in javascript
    assert "/controller/continue" in javascript
    # Every 4 s, not 2 s: each progress poll used to cost seconds of CPU and
    # the polls starved the build thread (2026-09-05, 22-minute CL 10 build).
    assert "window.setInterval(tick, 4000)" in javascript
    assert re.search(r"app\.js\?v=(?:[0-9]{8}-[a-z0-9-]+|r[0-9]+)", html)
    assert '["NEEDS_REVIEW", "PREPARING_REQUEST"].includes(run?.status)' in javascript
    assert "/character-creation/controller/active" in javascript
    assert "if (inFlight) return;" in javascript
    assert "if (generation !== guidedControllerProgressGeneration) return;" in javascript
