from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from ai_provider.secrets import InMemorySecretStore
from app.api import create_app
from app.core import Settings

ROOT = Path(__file__).resolve().parents[1]
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9WlXkAAAAASUVORK5CYII="
)


def _client(tmp_path: Path, *, transport=None, secret_store=None):
    settings = Settings.from_env(ROOT, tmp_path / "UserData")
    return TestClient(create_app(settings, ai_transport=transport, ai_secret_store=secret_store)), settings


def _headers(client: TestClient) -> dict[str, str]:
    return {"x-foundry-token": client.get("/api/session").json()["token"]}


def _upload_payload(name: str = "owner.png") -> dict[str, str]:
    return {
        "original_filename": name,
        "media_type": "image/png",
        "data_base64": base64.b64encode(PNG_1X1).decode("ascii"),
    }


def _primary(catalog: dict) -> list[dict]:
    return [row for row in catalog["projections"] if row.get("primary_combatant")]


def test_visual_profile_links_tokens_by_stable_actor_and_snapshots_new_match(tmp_path: Path) -> None:
    client, settings = _client(tmp_path)
    with client:
        headers = _headers(client)
        catalog = client.get("/api/combat/catalog").json()
        assert len(catalog["teams"]) == 2
        fighters = _primary(catalog)
        actor = next(row for row in fighters if row["display_name"] == "An Eui")
        assert actor["character_sheet_identity"] == f"character_mapping:{actor['runtime_entity_id']}"

        before = client.get("/api/combat/visual-assets").json()
        assert before["profile"]["custom_background"] is False
        assert before["profile"]["custom_token_actor_ids"] == []

        background = client.post("/api/combat/setup-visuals/background", headers=headers, json=_upload_payload("court.png"))
        assert background.status_code == 200, background.text
        token = client.post(
            f"/api/combat/setup-visuals/tokens/{actor['runtime_entity_id']}",
            headers=headers,
            json=_upload_payload("an-eui-custom.png"),
        )
        assert token.status_code == 200, token.text
        visuals = token.json()
        assert visuals["profile"]["custom_background"] is True
        assert visuals["profile"]["custom_token_actor_ids"] == [actor["runtime_entity_id"]]
        effective_token = next(row for row in visuals["tokens"] if actor["runtime_entity_id"] in row.get("stable_actor_ids", []))
        assert effective_token["source"] == "owner_upload"
        assert client.get(effective_token["public_url"]).content == PNG_1X1

        modes = {row["runtime_entity_id"]: "LOCAL_AUTO" for row in fighters}
        created = client.post(
            "/api/combat/matches",
            headers=headers,
            json={
                "encounter_id": catalog["encounters"][0]["stable_id"],
                "display_name": "Visual snapshot test",
                "match_seed": "R6-6-6-VISUAL-SNAPSHOT",
                "control_modes": modes,
                "maximum_rounds": 20,
            },
        )
        assert created.status_code == 200, created.text
        match = created.json()
        match_id = match["match_id"]
        snapshot = match["metadata"]["visual_assets"]
        assert snapshot["mechanical_authority"] is False
        assert snapshot["map"]["source"] == "match_snapshot"
        assert snapshot["tokens"][actor["runtime_entity_id"]]["source"] == "match_snapshot"
        map_url = snapshot["map"]["public_url"]
        token_url = snapshot["tokens"][actor["runtime_entity_id"]]["public_url"]
        assert client.get(map_url).content == PNG_1X1
        assert client.get(token_url).content == PNG_1X1

        # Global resets do not rewrite an existing match's visual snapshot.
        assert client.delete("/api/combat/setup-visuals/background", headers=headers).status_code == 200
        assert client.delete(f"/api/combat/setup-visuals/tokens/{actor['runtime_entity_id']}", headers=headers).status_code == 200
        reopened = client.get(f"/api/combat/matches/{match_id}").json()
        assert reopened["metadata"]["visual_assets"] == snapshot
        assert client.get(map_url).content == PNG_1X1
        assert client.get(token_url).content == PNG_1X1

        step = client.post(f"/api/combat/matches/{match_id}/auto-step", headers=headers, json={})
        assert step.status_code == 200, step.text
        assert step.json()["status"] == "COMMITTED"
        assert client.post(f"/api/combat/matches/{match_id}/verify", headers=headers, json={}).json()["status"] == "PASS"

        export = client.get(f"/api/combat/matches/{match_id}/export")
        assert export.status_code == 200
        path = tmp_path / "export.zip"
        path.write_bytes(export.content)
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            assert any(name.startswith("VisualAssets/background_") for name in names)
            assert any(name.startswith(f"VisualAssets/token_{actor['runtime_entity_id']}_") for name in names)

        profile = settings.data_dir / "Combat" / "VisualProfile" / "Profile.json"
        assert profile.is_file()
        profile_doc = json.loads(profile.read_text(encoding="utf-8"))
        assert profile_doc["background"] is None
        assert actor["runtime_entity_id"] not in profile_doc["tokens"]


def test_visual_upload_is_bounded_and_rejects_wrong_actor_or_content(tmp_path: Path) -> None:
    client, _settings = _client(tmp_path)
    with client:
        headers = _headers(client)
        unauthenticated = client.post("/api/combat/setup-visuals/background", json=_upload_payload())
        assert unauthenticated.status_code == 403
        unknown = client.post("/api/combat/setup-visuals/tokens/not-a-fighter", headers=headers, json=_upload_payload())
        assert unknown.status_code == 400
        bad = client.post(
            "/api/combat/setup-visuals/background",
            headers=headers,
            json={"original_filename": "bad.png", "media_type": "image/png", "data_base64": base64.b64encode(b"not image").decode("ascii")},
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["code"] == "COMBAT_UI_DATA_INVALID"


def test_api_auto_uses_provider_only_for_listed_intent_then_runtime_validates(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        prompt = payload["messages"][1]["content"]
        frame = json.loads(prompt.split("\n\n", 1)[1])
        candidate = frame["legal_candidates"][0]
        completion = {
            "schema": "TianxiaFactoryCombatAIIntent.v1",
            "action_intent": {
                "decision_id": frame["decision_id"],
                "state_version": frame["state_version"],
                "candidate_id": candidate["candidate_id"],
                "actor_id": candidate["actor_id"],
                "target_ids": candidate["target_ids"],
                "destination": candidate["destination"],
                "option_ids": candidate["option_ids"],
            },
            "rationale": "Select one offered candidate.",
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(completion)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    transport = httpx.MockTransport(handler)
    client, settings = _client(tmp_path, transport=transport, secret_store=InMemorySecretStore("test-api-key-123"))
    with client:
        headers = _headers(client)
        configured = client.post(
            "/api/ai-provider/configure",
            headers=headers,
            json={
                "enabled": True,
                "model": "deepseek-v4-flash",
                "thinking_mode": "disabled",
                "max_output_tokens": 2048,
                "timeout_seconds": 30,
                "data_sharing_acknowledged": True,
                "acknowledged_by": "test-user",
            },
        )
        assert configured.status_code == 200, configured.text
        assert configured.json()["ready"] is True
        catalog = client.get("/api/combat/catalog").json()
        modes = {row["runtime_entity_id"]: "API_AUTO" for row in _primary(catalog)}
        created = client.post(
            "/api/combat/matches",
            headers=headers,
            json={
                "encounter_id": catalog["encounters"][0]["stable_id"],
                "display_name": "API auto test",
                "match_seed": "R6-6-6-API-AUTO",
                "control_modes": modes,
                "maximum_rounds": 20,
            },
        )
        assert created.status_code == 200, created.text
        match_id = created.json()["match_id"]
        step = client.post(f"/api/combat/matches/{match_id}/auto-step", headers=headers, json={})
        assert step.status_code == 200, step.text
        body = step.json()
        assert body["status"] == "COMMITTED"
        assert body["provider"]["model"] == "deepseek-v4-flash"
        assert body["match"]["state"]["state_version"] == 1
        assert client.post(f"/api/combat/matches/{match_id}/verify", headers=headers, json={}).json()["status"] == "PASS"
        audit = next((settings.data_dir / "Combat" / "Matches").glob("*/ProviderController.ndjson"))
        audit_doc = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
        assert audit_doc["status"] == "COMMITTED"
        assert audit_doc["response_sha256"]
        assert "api-key" not in audit.read_text(encoding="utf-8")


def test_owner_combat_ui_has_team_visual_and_auto_controls() -> None:
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    required = {
        "combatBackgroundUpload",
        "combatBackgroundPreview",
        "combatTeamSetup",
        "combatFriendlySetupTab",
        "combatAdvancedSetupTab",
        "combatAutoPanel",
        "combatOwnerView",
        "combatTechnicalView",
        "combatConfigureAPI",
    }
    for identifier in required:
        assert f'id="{identifier}"' in html
    assert "/api/combat/setup-visuals/tokens/" in js
    assert "/auto-step" in js
    assert "Linked to ${actor.display_name}\'s character sheet" in js
    assert "visual ${mapAsset?.asset_id" not in js
    assert "Local AI" in js and "API AI" in js
