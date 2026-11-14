from __future__ import annotations

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


def _create(api: TestClient, headers: dict[str, str], seed: str, mode: str) -> dict:
    catalog = api.get("/api/combat/catalog").json()
    encounter_id = catalog["encounters"][0]["stable_id"]
    modes = {
        row["runtime_entity_id"]: mode
        for row in catalog["projections"]
        if row.get("primary_combatant")
    }
    response = api.post(
        "/api/combat/matches",
        headers=headers,
        json={
            "encounter_id": encounter_id,
            "display_name": f"M1 {mode}",
            "match_seed": seed,
            "control_modes": modes,
            "maximum_rounds": 20,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _intent(decision: dict) -> dict:
    candidate = decision["context"]["legal_candidates"][0]
    return {
        "decision_id": candidate["decision_id"],
        "state_version": candidate["state_version"],
        "candidate_id": candidate["candidate_id"],
        "actor_id": candidate["actor_id"],
        "target_ids": candidate.get("target_ids") or [],
        "destination": candidate.get("destination"),
        "option_ids": list(candidate.get("option_ids") or []),
    }


def test_manual_decision_exposes_owner_submit_authority(client) -> None:
    api, headers = client
    match = _create(api, headers, "R669-M1-MANUAL-AUTHORITY", "MANUAL")
    decision = api.get(f"/api/combat/matches/{match['match_id']}/decision").json()
    assert decision["control_mode"] == "MANUAL"
    assert decision["manual_submit_allowed"] is True
    assert decision["manual_submit_reason"] == "ACTIVE_ACTOR_ACCEPTS_OWNER_INTENT"


def test_manual_preview_is_non_authoritative_and_commit_uses_checked_preview(client) -> None:
    api, headers = client
    match = _create(api, headers, "R669-M1-PREVIEW-COMMIT", "MANUAL")
    match_id = match["match_id"]
    decision = api.get(f"/api/combat/matches/{match_id}/decision").json()
    payload = _intent(decision)
    before = api.get(f"/api/combat/matches/{match_id}").json()["state"]
    preview = api.post(
        f"/api/combat/matches/{match_id}/preview",
        headers=headers,
        json={"intent": payload, "reaction_decisions": []},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    # The first candidate is chosen to avoid relying on a particular action label.
    if body["status"] == "REACTION_REQUIRED":
        pytest.skip("The deterministic first candidate reached a reaction window in this fixture.")
    assert body["status"] == "PREVIEW_COMPLETE"
    assert body["authoritative_state_unchanged"] is True
    after_preview = api.get(f"/api/combat/matches/{match_id}").json()["state"]
    assert (before["state_version"], before["event_sequence"], before["roll_counter"]) == (
        after_preview["state_version"], after_preview["event_sequence"], after_preview["roll_counter"]
    )
    commit = api.post(
        f"/api/combat/matches/{match_id}/intent",
        headers=headers,
        json={"intent": payload, "reaction_decisions": [], "preview_id": body["preview_id"]},
    )
    assert commit.status_code == 200, commit.text
    assert commit.json()["match"]["state"]["state_version"] > before["state_version"]
    assert api.post(f"/api/combat/matches/{match_id}/verify", headers=headers, json={}).json()["status"] == "PASS"


def test_owner_intent_is_rejected_for_automatic_controller(client) -> None:
    api, headers = client
    match = _create(api, headers, "R669-M1-MODE-GUARD", "LOCAL_AUTO")
    match_id = match["match_id"]
    decision = api.get(f"/api/combat/matches/{match_id}/decision").json()
    assert decision["manual_submit_allowed"] is False
    response = api.post(
        f"/api/combat/matches/{match_id}/preview",
        headers=headers,
        json={"intent": _intent(decision), "reaction_decisions": []},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COMBAT_CONTROLLER_MODE_MISMATCH"
    assert api.get(f"/api/combat/matches/{match_id}").json()["state"]["state_version"] == 0


def test_owner_ui_has_pending_draft_preview_and_reaction_dialogs() -> None:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    assert {
        "combatIntentReviewDialog",
        "combatIntentReviewBody",
        "combatIntentCommit",
        "combatIntentCancel",
        "combatReactionDialog",
        "combatReactionPrompt",
    }.issubset(ids)
    assert 'MANUAL: "Manual"' in js
    assert 'let combatPendingIntentDraft = null;' in js
    assert 'let combatInteractionMode = "inspect";' in js
    assert 'manual_submit_allowed' in js
    assert 'Review Action' in js
    assert 'authoritative_state_unchanged' not in html  # no fabricated browser authority
    preview_body = js[js.index("async function continueCombatPreview"):js.index("async function commitCombatPendingIntent") ]
    assert 'renderCombatIntentReview(preview);' in preview_body
    assert '/intent' not in preview_body  # preview no longer auto-commits
    assert 'async function commitCombatPendingIntent()' in js
    assert 'preview_id: draft.preview.preview_id' in js
