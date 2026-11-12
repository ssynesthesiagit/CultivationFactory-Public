"""Viewer presence over HTTP, using a synthetic match and no model or browser."""
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from combat.gate2_runtime_models import ActionIntent, CandidateKind
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]


def test_activity_tracks_browser_polls_and_finished_matches_without_side_effects(tmp_path):
    settings = Settings.from_env(ROOT, tmp_path)
    app = create_app(settings)
    app.state.agent_seats.background = False
    combat = app.state.combat
    table = app.state.agent_seats.table
    session = combat.persistence.create_match(match_seed="TABLETOP-ACTIVITY", maximum_rounds=1)
    mid = session.match_id
    match_dir = combat._match_dir(mid)

    def saved_files():
        return {str(path.relative_to(match_dir)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in match_dir.rglob("*") if path.is_file()}

    with TestClient(app) as client:
        assert client.get("/api/tabletop/activity").json() == []
        # Server-owned presentation is not evidence of a browser watching.
        table.state(mid, include_menu=False)
        table.events(mid, 0)
        assert client.get("/api/tabletop/activity").json() == []

        for path in ("state?compact=true", "events?after=0", "seat-status"):
            if mid in table._last_requests:
                table._last_requests[mid] = time.monotonic() - 120
            response = client.get(f"/api/tabletop/matches/{mid}/{path}")
            assert response.status_code == 200, response.text
            response = client.get("/api/tabletop/activity")
            assert response.status_code == 200, response.text
            [row] = response.json()
            assert set(row) == {"match_id", "seconds_since_request", "seconds_since_command", "seconds_since_event", "seconds_since_change", "finished"}
            assert isinstance(row["match_id"], str)
            assert isinstance(row["seconds_since_request"], (int, float))
            assert isinstance(row["finished"], bool)
            assert row["match_id"] == mid and row["finished"] is False
            assert 0 <= row["seconds_since_request"] < 5
            assert row["seconds_since_command"] is None        # FIGHTACTIVE1: polling is never a player command
            assert row["seconds_since_change"] == row["seconds_since_event"]   # only committed changes count

        # A non-poll match endpoint also stamps activity.
        response = client.get(f"/api/tabletop/matches/{mid}/summary")
        assert response.status_code == 200, response.text
        [row] = client.get("/api/tabletop/activity").json()
        assert 0 <= row["seconds_since_request"] < 5

        # FIGHTACTIVE1 (Ino 2026-10-31: a frozen fight's tab, polling every 3 s, held exports and deploys for 40 min): only
        # a player's command (a non-GET request) is play. What breaks if this goes: polling counts as a live fight again.
        token = client.get("/api/session").json()["token"]
        client.post(f"/api/tabletop/matches/{mid}/settings", json={}, headers={"x-foundry-token": token})
        [row] = client.get("/api/tabletop/activity").json()
        assert 0 <= row["seconds_since_command"] < 5
        client.get(f"/api/tabletop/matches/{mid}/state?compact=true")         # a later poll doesn't move it
        [after] = client.get("/api/tabletop/activity").json()
        assert after["seconds_since_command"] >= row["seconds_since_command"]

        # A poll changes nothing: the fight's last change (its manifest, rewritten per committed transaction) stays put.
        import os
        manifest = match_dir / "Manifest.json"
        os.utime(manifest, (time.time() - 3000, time.time() - 3000))
        table._last_commands.pop(mid, None)
        client.get(f"/api/tabletop/matches/{mid}/state?compact=true")
        [row] = client.get("/api/tabletop/activity").json()
        assert row["seconds_since_change"] >= 2990                      # a frozen fight's tab: no change for 50 min

        # Finish by ending the first round through ordinary persisted intents.
        # No poll occurs after finishing: activity must read the current result.
        for index in range(10):
            if session.engine.state.terminal_result is not None:
                break
            end = next(c for c in session.engine.legal_candidates() if c.kind == CandidateKind.END_TURN)
            session.submit_intent(ActionIntent(
                intent_id=f"activity-end-{index}", decision_id=end.decision_id,
                candidate_id=end.candidate_id, state_version=end.state_version,
                actor_id=end.actor_id, target_ids=end.target_ids, option_ids=end.option_ids,
                destination=end.destination, reaction_decisions=(),
            ), primary_decision_record=None, reaction_provider=None)
        assert session.engine.state.terminal_result is not None
        [row] = client.get("/api/tabletop/activity").json()                # intents commit: the fight changed just now
        assert row["seconds_since_event"] < 60 and row["seconds_since_change"] < 60

        table._last_requests[mid] = time.monotonic() - 120
        requests_before = dict(table._last_requests)
        files_before = saved_files()
        for _ in range(2):
            response = client.get("/api/tabletop/activity")
            assert response.status_code == 200, response.text
            [row] = response.json()
            assert set(row) == {"match_id", "seconds_since_request", "seconds_since_command", "seconds_since_event", "seconds_since_change", "finished"}
            assert isinstance(row["match_id"], str)
            assert isinstance(row["seconds_since_request"], (int, float))
            assert isinstance(row["finished"], bool)
            assert row["match_id"] == mid and row["finished"] is True
            assert 120 <= row["seconds_since_request"] < 125
        assert table._last_requests == requests_before
        assert saved_files() == files_before, "activity must not load/recover or write a fight"
        assert TabletopService(combat, tmp_path).activity() == [], "presence is not persisted"

        token = client.get("/api/session").json()["token"]
        assert client.post("/api/tabletop/activity", headers={"x-foundry-token": token}).status_code == 405
        assert saved_files() == files_before

        table.delete_match(mid)
        assert client.get("/api/tabletop/activity").json() == []
