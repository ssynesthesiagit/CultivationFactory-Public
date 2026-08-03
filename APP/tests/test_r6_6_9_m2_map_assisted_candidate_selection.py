from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings.from_env(ROOT, tmp_path / "UserData")
    with TestClient(create_app(settings)) as api:
        token = api.get("/api/session").json()["token"]
        yield api, {"x-foundry-token": token}


def _create_manual(api: TestClient, headers: dict[str, str], seed: str) -> dict:
    catalog = api.get("/api/combat/catalog").json()
    modes = {
        row["runtime_entity_id"]: "MANUAL"
        for row in catalog["projections"]
        if row.get("primary_combatant")
    }
    response = api.post(
        "/api/combat/matches",
        headers=headers,
        json={
            "encounter_id": catalog["encounters"][0]["stable_id"],
            "display_name": "M2 map-assisted candidate test",
            "match_seed": seed,
            "control_modes": modes,
            "maximum_rounds": 20,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _intent(candidate: dict) -> dict:
    return {
        "decision_id": candidate["decision_id"],
        "state_version": candidate["state_version"],
        "candidate_id": candidate["candidate_id"],
        "actor_id": candidate["actor_id"],
        "target_ids": candidate.get("target_ids") or [],
        "destination": candidate.get("destination"),
        "option_ids": list(candidate.get("option_ids") or []),
    }


def test_map_selection_draft_has_a_closed_documentary_schema() -> None:
    schema = json.loads((ROOT / "schemas/TianxiaCombatMapSelectionDraft.v1.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"] == "TianxiaCombatMapSelectionDraft.v1"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema"]["const"] == "TianxiaCombatMapSelectionDraft.v1"
    assert set(schema["properties"]["controller_mode"]["enum"]) == {"MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"}
    assert "inspect" not in schema["properties"]["interaction_mode"]["enum"]
    assert schema["properties"]["legal_candidate_ids"]["uniqueItems"] is True


def test_m2_ui_exposes_formal_map_interaction_contract() -> None:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    assert {
        "combatPanMode",
        "combatInteractionBar",
        "combatInteractionTitle",
        "combatInteractionGuidance",
        "combatInteractionChoice",
        "combatInteractionUse",
        "combatInteractionCancel",
    }.issubset(ids)
    assert 'const COMBAT_INTERACTION_MODES = new Set(["inspect", "pan", "select_target", "select_destination", "select_area", "measure", "review"]);' in js
    assert 'schema: "TianxiaCombatMapSelectionDraft.v1"' in js
    assert "beginCombatMapSelection" in js
    assert "chooseCombatMapTarget" in js
    assert "chooseCombatMapDestination" in js
    assert "completeCombatMapSelection" in js
    assert "Choose Target on Map" in js
    assert "Choose Destination on Map" in js


def test_map_selection_uses_only_exact_current_candidate_fields() -> None:
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    start = js.index("function beginCombatMapSelection")
    end = js.index("function renderCombatInteractionBar")
    body = js[start:end]
    assert "combatDecisionCandidates()" in body
    assert "candidate_id" in body
    assert "decision_id" in body
    assert "state_version" in body
    assert "target_ids?.includes(actorId)" in body
    assert "destination?.x === x && row.destination?.y === y" in body
    forbidden = [
        "lineOfSight",
        "line_of_sight",
        "movementCost",
        "movement_cost",
        "pathfind",
        "coverBonus",
        "range_ft >=",
        "Math.hypot",
    ]
    for token in forbidden:
        assert token not in body


def test_token_click_routes_target_mode_without_changing_inspection_authority() -> None:
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    token_start = js.index('token.addEventListener("click"')
    token_end = js.index("group.appendChild(token)", token_start)
    handler = js[token_start:token_end]
    assert 'combatInteractionMode === "select_target"' in handler
    assert "chooseCombatMapTarget(actor.entity_id)" in handler
    assert handler.index("chooseCombatMapTarget") < handler.index("selectCombatActor")
    assert 'if (combatInteractionMode === "pan") return;' in handler


def test_escape_cancels_map_draft_before_sheet_or_inspection() -> None:
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    start = js.index('document.addEventListener("keydown"')
    body = js[start:]
    assert body.index("combatInteractionDraft") < body.index("combatPinnedActorId")
    assert 'cancelCombatMapSelection("Map interaction canceled. No combat state changed.")' in body


def test_exact_destination_candidate_previews_without_mutating_state(client) -> None:
    api, headers = client
    match = _create_manual(api, headers, "R669-M2-DESTINATION")
    match_id = match["match_id"]
    decision = api.get(f"/api/combat/matches/{match_id}/decision").json()
    candidates = decision["context"]["legal_candidates"]
    candidate = next(row for row in candidates if row.get("destination"))
    exact_matches = [
        row["candidate_id"]
        for row in candidates
        if row.get("destination") == candidate["destination"]
    ]
    assert candidate["candidate_id"] in exact_matches
    before = api.get(f"/api/combat/matches/{match_id}").json()["state"]
    preview = api.post(
        f"/api/combat/matches/{match_id}/preview",
        headers=headers,
        json={"intent": _intent(candidate), "reaction_decisions": []},
    )
    assert preview.status_code == 200, preview.text
    after = api.get(f"/api/combat/matches/{match_id}").json()["state"]
    assert (before["state_version"], before["event_sequence"], before["roll_counter"]) == (
        after["state_version"], after["event_sequence"], after["roll_counter"]
    )


def test_exact_target_candidate_is_server_issued(client) -> None:
    api, headers = client
    match = _create_manual(api, headers, "R669-M2-TARGET")
    decision = api.get(f"/api/combat/matches/{match['match_id']}/decision").json()
    candidate = next(row for row in decision["context"]["legal_candidates"] if row.get("target_ids"))
    actor_ids = {row["entity_id"] for row in match["state"]["actors"]}
    assert candidate["actor_id"] == decision["context"]["active_actor_id"]
    assert set(candidate["target_ids"]).issubset(actor_ids)
    assert candidate["candidate_id"].startswith("candidate:")


def test_pan_mode_is_viewport_only_in_ui_contract() -> None:
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    start = js.index('const combatViewport = document.getElementById("combatBattlefieldViewport")')
    end = js.index('document.getElementById("combatToggleNameplates")', start)
    body = js[start:end]
    assert "scrollLeft" in body and "scrollTop" in body
    for forbidden in ["position.x", "position.y", "/intent", "/preview", "candidate_id ="]:
        assert forbidden not in body
