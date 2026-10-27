"""Saved team setups for the new-fight screen (owner 2026-09-29: "some kind of team saver")."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from combat.tabletop import TabletopError, TeamPresetStore, SingleTeamPresetStore

SETUP = {"name": "  Tabik  vs Corpse Sect ", "arena_id": "battlefield:map.bamboo-road", "fight_name": "Bamboo ambush",
         "teams": [[{"pid": "fec9fac0-efb5-4dbb-9819-fe5a1d185cbf", "mode": "MANUAL", "prefight": ["action:typed.x.a", "action:typed.x.b"]}],
                   [{"pid": "14d8bdcd-ddf8-49ec-9937-b015be8eef4b", "mode": "LOCAL_AUTO", "prefight": None},
                    {"pid": "29218ee0-ee23-44b2-8390-3653ec8aa7da", "mode": "SOMETHING", "prefight": []}]]}


def overlap_mutations(monkeypatch, store_type, first, second):
    """Hold the first snapshot while the second request attempts its transaction.

    Without serialization both requests read that snapshot before either writes.
    With serialization the second cannot read until the first has committed.
    """
    original = store_type._read
    read_started, second_read, release, attempted = Event(), Event(), Event(), Event()
    counter_lock = Lock()
    reads = 0

    def paused_read(self):
        nonlocal reads
        document = original(self)
        with counter_lock:
            reads += 1
            number = reads
        if number == 1:
            read_started.set()
            assert release.wait(5)
        else:
            second_read.set()
        return document

    def run_second():
        attempted.set()
        return second()

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(store_type, "_read", paused_read)
        one = pool.submit(first)
        try:
            assert read_started.wait(5)
            two = pool.submit(run_second)
            assert attempted.wait(5)
            second_read.wait(0.2)
        finally:
            release.set()
        return one.result(timeout=5), two.result(timeout=5)


@pytest.mark.parametrize("store_type", [SingleTeamPresetStore, TeamPresetStore])
def test_concurrent_store_save_and_delete(tmp_path, monkeypatch, store_type):
    def row(name):
        return {"name": name, "members": SETUP["teams"][0]} if store_type is SingleTeamPresetStore else {**SETUP, "name": name}

    def save(name):
        return store_type(tmp_path).save(row(name))

    overlap_mutations(monkeypatch, store_type, lambda: save("First"), lambda: save("Second"))
    assert {row["name"] for row in store_type(tmp_path).list()} == {"First", "Second"}
    overlap_mutations(monkeypatch, store_type, lambda: store_type(tmp_path).delete("First"), lambda: save("Third"))
    assert {row["name"] for row in store_type(tmp_path).list()} == {"Second", "Third"}


def test_a_setup_saves_lists_and_deletes(tmp_path):
    store = TeamPresetStore(tmp_path / "team_presets")
    assert store.list() == []
    saved = store.save(SETUP)
    assert saved["name"] == "Tabik vs Corpse Sect"  # whitespace tidied
    assert saved["teams"][0][0] == {"pid": "fec9fac0-efb5-4dbb-9819-fe5a1d185cbf", "mode": "MANUAL", "prefight": ["action:typed.x.a", "action:typed.x.b"]}
    assert saved["teams"][1][0]["prefight"] is None  # "the AI's picks" is kept apart from "none"
    assert saved["teams"][1][1]["mode"] == "LOCAL_AUTO"  # an unknown mode falls back to the AI
    assert store.list() == [saved]
    assert json.loads((tmp_path / "team_presets" / "presets.json").read_text(encoding="utf-8"))["Tabik vs Corpse Sect"] == saved
    store.delete("Tabik vs Corpse Sect")
    assert store.list() == []


def test_saving_under_the_same_name_replaces_it(tmp_path):
    store = TeamPresetStore(tmp_path)
    store.save(SETUP)
    store.save({**SETUP, "fight_name": "Rematch"})
    assert [row["fight_name"] for row in store.list()] == ["Rematch"]


@pytest.mark.parametrize("bad", [
    {**SETUP, "name": "   "},
    {**SETUP, "teams": [SETUP["teams"][0]]},
    {**SETUP, "teams": [[], SETUP["teams"][1]]},
    {**SETUP, "teams": [[{"pid": "../../etc/passwd", "mode": "MANUAL"}], SETUP["teams"][1]]},
    {**SETUP, "teams": [SETUP["teams"][0] * 7, SETUP["teams"][1]]},
])
def test_a_setup_that_is_not_a_fight_is_refused(tmp_path, bad):
    with pytest.raises(TabletopError):
        TeamPresetStore(tmp_path).save(bad)


def test_deleting_an_unknown_setup_says_so(tmp_path):
    with pytest.raises(TabletopError) as error:
        TeamPresetStore(tmp_path).delete("nope")
    assert error.value.status_code == 404


def test_single_team_roundtrip_collision_and_legacy_bytes(tmp_path):
    setups = TeamPresetStore(tmp_path)
    old = setups.save(SETUP)
    original = setups.path.read_bytes()
    store = SingleTeamPresetStore(tmp_path)
    team = {"name": "  Tabik   team ", "members": SETUP["teams"][0]}
    saved = store.save(team)
    assert saved == {**team, "name": "Tabik team"}
    assert SingleTeamPresetStore(tmp_path).list() == [saved]
    with pytest.raises(TabletopError) as error:
        store.save({**team, "members": SETUP["teams"][1]})
    assert error.value.status_code == 409
    assert store.list() == [saved]
    replacement = store.save({**team, "members": SETUP["teams"][1], "replace": True})
    assert replacement["members"][0]["prefight"] is None
    assert replacement["members"][1]["prefight"] == []
    assert replacement["members"][1]["mode"] == "LOCAL_AUTO"
    store.delete(saved["name"])
    assert store.list() == []
    assert setups.path.read_bytes() == original
    assert setups.list() == [old]
    with pytest.raises(TabletopError) as error:
        store.delete(saved["name"])
    assert error.value.status_code == 404


@pytest.mark.parametrize("members", [None, [], [None], ["fighter"], SETUP["teams"][0] * 7,
                                         [{"pid": "../bad"}], [{"pid": "valid", "prefight": 1}]])
def test_invalid_single_team(tmp_path, members):
    with pytest.raises(TabletopError):
        SingleTeamPresetStore(tmp_path).save({"name": "Bad team", "members": members})


def test_single_team_api_and_old_setup_roundtrip(tmp_path, monkeypatch):
    from pathlib import Path
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings

    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path / "UserData")
    # Sandboxes that refuse socket send() are handled for every TestClient by tests/conftest.py.
    with TestClient(create_app(settings)) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        old = client.post("/api/tabletop/team-presets", headers=headers, json={"preset": SETUP})
        assert old.status_code == 200, old.text
        legacy_path = settings.data_dir / "team_presets" / "presets.json"
        original = legacy_path.read_bytes()
        endpoint = "/api/tabletop/saved-teams"
        team = {"name": "Team / one", "members": SETUP["teams"][0]}
        response = client.post(endpoint, headers=headers, json={"preset": team})
        assert response.status_code == 200, response.text
        assert response.json() == team
        assert client.get(endpoint).json() == {"teams": [team]}
        changed = {**team, "members": SETUP["teams"][1][:1]}
        assert client.post(endpoint, headers=headers, json={"preset": changed}).status_code == 409
        assert client.get(endpoint).json() == {"teams": [team]}
        response = client.post(endpoint, headers=headers, json={"preset": {**changed, "replace": True}})
        assert response.status_code == 200
        assert response.json() == changed
        assert client.delete(endpoint + "/Team%20%2F%20one", headers=headers).status_code == 200
        assert client.get(endpoint).json() == {"teams": []}
        assert client.delete(endpoint + "/Team%20%2F%20one", headers=headers).status_code == 404
        assert client.get("/api/tabletop/team-presets").json() == {"presets": [old.json()]}
        assert legacy_path.read_bytes() == original
        def post(name):
            return client.post(endpoint, headers=headers, json={"preset": {**team, "name": name}})

        different = overlap_mutations(monkeypatch, SingleTeamPresetStore, lambda: post("First"), lambda: post("Second"))
        assert [response.status_code for response in different] == [200, 200]
        assert {row["name"] for row in client.get(endpoint).json()["teams"]} == {"First", "Second"}
        same = overlap_mutations(monkeypatch, SingleTeamPresetStore, lambda: post("Same name"), lambda: post("  Same   name "))
        assert sorted(response.status_code for response in same) == [200, 409]
        assert legacy_path.read_bytes() == original
