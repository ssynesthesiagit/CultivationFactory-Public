"""Synthetic HTTP acquisition: the real request contract and sheet overlay."""
from copy import deepcopy

from app.api import create_app
from app.core import Settings
from combat.tabletop_service import TabletopService
from fastapi.testclient import TestClient
from tests.grow5_support import PID, QI, ROOT, SPHERE, TALENTS, baseline, service, _reach
from tests.test_grow5_foundation import ANCHOR, pick


def test_http_foundation_gate_commit_sheet_and_undo(tmp_path, monkeypatch):
    s = service(tmp_path)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    monkeypatch.setattr(TabletopService, "_catalog_talents", lambda self: deepcopy(TALENTS))
    monkeypatch.setattr(TabletopService, "_sphere_names", lambda self: {SPHERE: "Water"})
    monkeypatch.setattr(app.state.character_sheets, "sheet", lambda _: {
        "owner_character_sheet": baseline(QI), "display_owner_character_sheet": baseline(QI),
        "sections": {"abilities_statistics": {"data": baseline(QI)["ability_scores_and_statistics"]}}})
    monkeypatch.setattr(app.state.character_creation, "recovery", lambda _: {})
    prefix = f"/api/tabletop/characters/{PID}/advancement"
    with TestClient(app) as client:
        token = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
        response = client.post(prefix + "/level", json=pick(client.get(prefix).json(), 0,
            foundation_id=ANCHOR, foundation_initial_stage="Awakened"), headers=token)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "TABLETOP_LEVEL_NOT_LEGAL"
        _reach(s, 5)
        view = client.get(prefix).json()
        payload = pick(view, foundation_id=ANCHOR, foundation_initial_stage="Awakened")
        response = client.post(prefix + "/level", json=payload, headers=token)
        assert response.status_code == 200, response.text
        sheet = client.get(f"/api/characters/{PID}/sheet").json()
        for key in ("owner_character_sheet", "display_owner_character_sheet"):
            foundation = sheet[key]["foundation"]
            assert foundation["record_id"] == ANCHOR and foundation["stage"] == "Awakened"
            assert foundation["display_name"] == "Empty Bowl Soul Anchor"
        response = client.post(prefix + "/level/undo", json={}, headers=token)
        assert response.status_code == 200, response.text
        assert not client.get(f"/api/characters/{PID}/sheet").json()["display_owner_character_sheet"].get("foundation")
