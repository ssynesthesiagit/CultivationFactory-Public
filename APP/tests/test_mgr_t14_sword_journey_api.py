"""Journey owner inputs must be reachable through the application routes."""
from fastapi.testclient import TestClient
from pathlib import Path

from app.api import create_app
from app.core import Settings
from combat.gate5_service import CombatService


def test_journey_world_fact_and_scene_end_routes_forward_owner_authority(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(CombatService, "journey_world_fact",
                        lambda self, journey_id, revision, payload:
                        calls.append(("world", journey_id, revision, payload)) or {"revision": revision + 1})
    monkeypatch.setattr(CombatService, "journey_end_scene",
                        lambda self, journey_id, revision, reason:
                        calls.append(("scene", journey_id, revision, reason)) or {"revision": revision + 1})
    root = Path(__file__).resolve().parents[1]
    data = tmp_path / "app-data"
    app = create_app(Settings(root_dir=root, data_dir=data, db_path=data / "db.sqlite3",
                              inbox_dir=data / "inbox", exports_dir=data / "exports",
                              packs_dir=data / "packs", vendor_dir=data / "vendor",
                              logs_dir=data / "logs", backups_dir=data / "backups",
                              security_dir=data / "security"))
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        headers = {"x-foundry-token": token}
        payload = {"source": "source:test", "subject": "actor:test", "kind": "scripture_access",
               "scope": "instruction", "value": {"instruction": "owner supplied"}}
        world = client.post("/api/combat/journeys/journey:test/world-facts", headers=headers,
                            json={"revision": 4, "payload": payload})
        scene = client.post("/api/combat/journeys/journey:test/end-scene", headers=headers,
                            json={"revision": 5, "reason": "The encounter has settled."})
        assert world.status_code == 200, world.text
        assert scene.status_code == 200, scene.text
        assert calls == [("world", "journey:test", 4, payload),
                         ("scene", "journey:test", 5, "The encounter has settled.")]


def test_scene_end_notification_resets_only_scene_scoped_sword_use():
    from combat.ext.ten_thousand_swords import FAMILY, new_scene
    session = type("Session", (), {"state": {"actors": {
        "actor:owner": {"source_states": {FAMILY: {"origin_used": 1, "pursuit_round": 7}}},
        "actor:other": {"source_states": {"unrelated": {"origin_used": 1}}},
    }}})()
    new_scene(session, "scene:old", "scene:new")
    assert session.state["actors"]["actor:owner"]["source_states"][FAMILY] == {}
    assert session.state["actors"]["actor:other"]["source_states"]["unrelated"] == {"origin_used": 1}
