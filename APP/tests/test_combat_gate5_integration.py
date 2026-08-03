from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings

ROOT = Path(__file__).resolve().parents[1]
SEED = "TIANXIA-GATE4-BENCH-0004"


@pytest.fixture(scope="module")
def gate5_api(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("gate5_api") / "UserData"
    settings = Settings.from_env(ROOT, data_dir)
    with TestClient(create_app(settings)) as client:
        token = client.get("/api/session").json()["token"]
        yield client, {"x-foundry-token": token}, data_dir


def _sanitize(intent: dict) -> dict:
    return {
        key: intent.get(key)
        for key in (
            "decision_id",
            "state_version",
            "candidate_id",
            "actor_id",
            "target_ids",
            "destination",
            "option_ids",
        )
    }


def _create(client: TestClient, headers: dict[str, str], *, seed: str, modes: dict[str, str] | None = None) -> dict:
    encounter = client.get("/api/combat/catalog").json()["encounters"][0]["stable_id"]
    response = client.post(
        "/api/combat/matches",
        headers=headers,
        json={
            "encounter_id": encounter,
            "display_name": "Gate 5 integration test",
            "match_seed": seed,
            "control_modes": modes or {},
            "maximum_rounds": 20,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _suggest_preview_commit(client: TestClient, headers: dict[str, str], match_id: str) -> tuple[dict, list[dict]]:
    suggestion = client.post(f"/api/combat/matches/{match_id}/suggest", headers=headers, json={})
    assert suggestion.status_code == 200, suggestion.text
    payload = _sanitize(suggestion.json()["intent"])
    reactions: list[dict] = []
    for _ in range(8):
        before = client.get(f"/api/combat/matches/{match_id}").json()["state"]
        preview = client.post(
            f"/api/combat/matches/{match_id}/preview",
            headers=headers,
            json={"intent": payload, "reaction_decisions": reactions},
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        after = client.get(f"/api/combat/matches/{match_id}").json()["state"]
        assert (before["state_version"], before["event_sequence"], before["roll_counter"]) == (
            after["state_version"], after["event_sequence"], after["roll_counter"]
        )
        assert body["authoritative_state_unchanged"] is True
        if body["status"] == "REACTION_REQUIRED":
            assert body["reaction_context"]["pending_damage"] is not None or body["reaction_context"]["checkpoint"] != "DAMAGE_APPLICATION"
            reactions.append(body["local_suggestion"]["decision"])
            continue
        assert body["status"] == "PREVIEW_COMPLETE"
        commit = client.post(
            f"/api/combat/matches/{match_id}/intent",
            headers=headers,
            json={"intent": payload, "reaction_decisions": reactions, "preview_id": body["preview_id"]},
        )
        assert commit.status_code == 200, commit.text
        return commit.json(), reactions
    raise AssertionError("preview exceeded bounded reaction checkpoints")


def _check_service_registration(client, headers) -> None:
    status = client.get("/api/combat/status")
    assert status.status_code == 200
    assert status.json()["available"] is True
    assert client.app.state.combat is not None
    catalog = client.get("/api/combat/catalog").json()
    assert catalog["readiness_statuses"] == [
        "COMBAT_READY",
        "COMBAT_PROJECTION_INCOMPLETE",
        "UNSUPPORTED_MECHANICS",
        "REQUIRES_RECOMPILATION",
    ]
    assert sum(row["primary_combatant"] for row in catalog["projections"]) == 4
    assert any(row["runtime_entity_id"] == "bai_cui" and not row["primary_combatant"] for row in catalog["projections"])
    rejected = client.post("/api/combat/matches", json={})
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "CSRF_TOKEN_REQUIRED"
    invalid = client.post("/api/combat/matches", headers=headers, json={"current_hp": 999})
    assert invalid.status_code == 422


def _check_round_trip(client, headers, data_dir: Path) -> None:
    created = _create(client, headers, seed="GATE5-SERVICE-ROUNDTRIP")
    match_id = created["match_id"]
    assert created["state"]["actors"]
    assert any(row["match_id"] == match_id for row in client.get("/api/combat/matches").json())
    decision = client.get(f"/api/combat/matches/{match_id}/decision")
    assert decision.status_code == 200
    assert decision.json()["context"]["legal_candidates"]

    committed, _ = _suggest_preview_commit(client, headers, match_id)
    assert committed["match"]["state"]["state_version"] == 1
    paused = client.post(f"/api/combat/matches/{match_id}/pause", headers=headers, json={})
    assert paused.json()["metadata"]["paused"] is True
    resumed = client.post(f"/api/combat/matches/{match_id}/resume", headers=headers, json={})
    assert resumed.json()["metadata"]["paused"] is False
    snapshot = client.post(f"/api/combat/matches/{match_id}/snapshot", headers=headers, json={})
    assert snapshot.status_code == 200

    frame = client.get(f"/api/combat/matches/{match_id}/ai-frame")
    assert frame.status_code == 200
    frame_doc = frame.json()["frame"]
    candidate = frame_doc["legal_candidates"][0]
    intent = {
        "decision_id": frame_doc["decision_id"],
        "state_version": frame_doc["state_version"],
        "candidate_id": candidate["candidate_id"],
        "actor_id": candidate["actor_id"],
        "target_ids": candidate["target_ids"],
        "destination": candidate["destination"],
        "option_ids": [],
    }
    checked = client.post(
        f"/api/combat/matches/{match_id}/ai-intent/validate",
        headers=headers,
        json={"schema": "TianxiaFactoryCombatAIResponse.v1", "action_intent": intent, "rationale": "legal test"},
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["status"] == "VALID"
    executed = client.post(
        f"/api/combat/matches/{match_id}/ai-intent/execute",
        headers=headers,
        json={"action_intent": intent, "validation_token": checked.json()["validation_token"]},
    )
    assert executed.status_code == 200, executed.text

    stale = client.post(
        f"/api/combat/matches/{match_id}/ai-intent/validate",
        headers=headers,
        json={"action_intent": intent},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "COMBAT_DECISION_STALE"

    verify = client.post(f"/api/combat/matches/{match_id}/verify", headers=headers, json={})
    assert verify.status_code == 200
    assert verify.json()["status"] == "PASS"
    replay = client.get(f"/api/combat/matches/{match_id}/replay")
    assert replay.status_code == 200
    export = client.get(f"/api/combat/matches/{match_id}/export")
    assert export.status_code == 200
    export_path = data_dir / "match-test-download.zip"
    export_path.write_bytes(export.content)
    with zipfile.ZipFile(export_path) as archive:
        assert archive.testzip() is None
        checksums = archive.read("SHA256SUMS.txt").decode("utf-8").splitlines()
        expected = {}
        for line in checksums:
            digest, name = line.split("  ", 1)
            expected[name] = digest
        members = {info.filename for info in archive.infolist() if not info.is_dir() and info.filename != "SHA256SUMS.txt"}
        assert members == set(expected)
        for name, digest in expected.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest


def _check_local_auto(client, headers) -> None:
    catalog = client.get("/api/combat/catalog").json()
    modes = {
        row["runtime_entity_id"]: "LOCAL_AUTO"
        for row in catalog["projections"]
        if row.get("primary_combatant")
    }
    created = _create(client, headers, seed="GATE5-LOCAL-AUTO", modes=modes)
    match_id = created["match_id"]
    step = client.post(f"/api/combat/matches/{match_id}/local-step", headers=headers, json={})
    assert step.status_code == 200
    assert step.json()["status"] == "COMMITTED"
    paused = client.post(f"/api/combat/matches/{match_id}/pause", headers=headers, json={})
    assert paused.status_code == 200
    blocked = client.post(f"/api/combat/matches/{match_id}/local-step", headers=headers, json={})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "COMBAT_MATCH_PAUSED"
    client.post(f"/api/combat/matches/{match_id}/resume", headers=headers, json={})
    run = client.post(f"/api/combat/matches/{match_id}/local-run", headers=headers, json={"maximum_steps": 3})
    assert run.status_code == 200, run.text
    assert 1 <= len(run.json()["steps"]) <= 3
    assert client.post(f"/api/combat/matches/{match_id}/verify", headers=headers, json={}).json()["status"] == "PASS"


def _check_reactions(client, headers) -> None:
    created = _create(client, headers, seed=SEED)
    match_id = created["match_id"]
    seen: list[dict] = []
    for _ in range(3):
        committed, reactions = _suggest_preview_commit(client, headers, match_id)
        seen.extend(reactions)
        assert client.post(f"/api/combat/matches/{match_id}/verify", headers=headers, json={}).json()["status"] == "PASS"
        if seen or committed["match"]["state"]["terminal_result"] is not None:
            break
    assert seen
    assert any(row["checkpoint"] == "DAMAGE_APPLICATION" for row in seen)
    assert all(row["selection"] in {"USE", "DECLINE"} for row in seen)



def test_gate5_vertical_slice_api(gate5_api) -> None:
    client, headers, data_dir = gate5_api
    _check_service_registration(client, headers)
    _check_round_trip(client, headers, data_dir)
    _check_local_auto(client, headers)
    _check_reactions(client, headers)

def test_static_combat_ui_has_unique_ids_and_required_controls() -> None:
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    required = {
    "screen-combat",
    "combatBoard",
    "combatActionGroups",
    "combatReactionPrompt",
    "combatSuggest",
    "combatLocalStep",
    "combatLocalRun",
    "combatAIFrame",
    "combatCheckAIIntent",
    "combatExecuteAIIntent",
    "combatVerify",
    "combatReplay",
    "combatExport",
    }
    assert required.issubset(ids)
    assert 'data-screen="combat"' in html
