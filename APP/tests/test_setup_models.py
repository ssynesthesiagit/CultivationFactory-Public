"""Setup model ownership through the real create, preset and seat APIs, offline."""
import copy

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.api import create_app
from app.core import Settings
from combat.tabletop import SingleTeamPresetStore, TeamPresetStore
from tests.h1_support import ROOT
from tests.test_agent_seats import runner_for
from tests.test_hunt5_player_choices import fixture, FOE, PLAYER
from tests.test_team_presets import SETUP


def test_created_model_fight_cannot_advance_until_all_seats_installed(tmp_path, monkeypatch):
    _, table, _, _, _ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    configured, fake = runner_for(tmp_path, table)
    monkeypatch.setenv("FACTORY_SEAT_PROVIDERS", str(configured.registry.path))
    monkeypatch.setattr(Draft202012Validator, "check_schema", classmethod(lambda cls, schema, format_checker=None: None))
    app = create_app(Settings.from_env(ROOT, tmp_path))
    runner = app.state.agent_seats
    runner.provider = fake
    # Run each observation's scheduled work synchronously: no sleeps or races,
    # and a seat POST really exercises observe → drive → persisted transport.
    steps = []
    monkeypatch.setattr(runner, "kick", lambda mid: steps.append(runner.drive(mid, max_steps=1)))
    with TestClient(app) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        created = client.post("/api/combat/factory-matches", headers=headers, json={
            "project_ids": ["h5-player"], "opponent_actor_ids": [FOE],
            "control_modes": {PLAYER: "MANUAL", FOE: "MANUAL"}, "prefight": {PLAYER: [], FOE: []},
        })
        assert created.status_code == 200, created.text
        mid = created.json()["match_id"]
        url = f"/api/tabletop/matches/{mid}"
        before = runner.table.state(mid)
        current = before["menu"]["actor_id"]
        other = FOE if current == PLAYER else PLAYER
        assert runner.seats(mid) == {}
        assert runner.drive(mid, max_steps=1) == 0
        assert client.post(url + "/playback", headers=headers, json={"paused": True}).status_code == 200
        for actor in [other, current]:  # later-installed fighter has initiative
            response = client.post(url + "/seat", headers=headers, json={
                "actor_id": actor, "control": "MODEL", "provider_id": "fake"})
            assert response.status_code == 200, response.text
            assert runner.drive(mid, max_steps=1) == 0
            state = runner.table.state(mid)
            assert state["last_sequence"] == before["last_sequence"]
            assert state["pending_action"] is None  # no attack/reaction before ownership is ready
            assert fake.prompts == []
        assert runner.seats(mid).keys() == {PLAYER, FOE}
        assert client.post(url + "/playback", headers=headers, json={"paused": False}).status_code == 200
        assert steps[-1] == 1
        assert runner.table.state(mid)["last_sequence"] > before["last_sequence"]
        session = app.state.combat._load_session(mid)
        assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("single", [False, True])
def test_both_preset_apis_preserve_model_selection_on_disk_and_reload(tmp_path, single):
    setup = copy.deepcopy(SETUP)
    setup["teams"][0][0]["mode"] = "MODEL:fake"
    setup["teams"][1][0]["mode"] = "MODEL:removed-model"
    preset = {"name": "Models", "members": setup["teams"][0] + setup["teams"][1][:1]} if single else setup
    settings = Settings.from_env(ROOT, tmp_path)
    endpoint = "/api/tabletop/saved-teams" if single else "/api/tabletop/team-presets"
    key = "teams" if single else "presets"
    with TestClient(create_app(settings)) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        result = client.post(endpoint, headers=headers, json={"preset": preset})
        assert result.status_code == 200, result.text
        saved = result.json()
        assert client.get(endpoint).json()[key] == [saved]
    store_type = SingleTeamPresetStore if single else TeamPresetStore
    assert store_type(tmp_path / "team_presets").list() == [saved]
    members = saved["members"] if single else saved["teams"][0] + saved["teams"][1]
    assert [row["mode"] for row in members][:2] == ["MODEL:fake", "MODEL:removed-model"]


@pytest.mark.parametrize("mode", ["MODEL:", "MODEL:" + "x" * 201, "unrecognized"])
def test_malformed_preset_control_falls_back_to_ai(tmp_path, mode):
    saved = SingleTeamPresetStore(tmp_path).save({"name": "Control", "members": [{"pid": "hero", "mode": mode}]})
    assert saved["members"][0]["mode"] == "LOCAL_AUTO"
