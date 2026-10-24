from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import FoundryError
from character_creation.production_release import CharacterProductionReleaseAdapter


def test_command5_rebind_uses_current_server_overlay_and_rejects_missing_component(
    fresh_db, monkeypatch,
):
    app = create_app(fresh_db.settings)
    project_id = "project.command5-rebind"
    receipt = {"overlay_id": "a" * 64, "receipt_id": "component.command4." + "b" * 64}
    calls = []
    recorded = []
    candidate = {"workspace": str(fresh_db.settings.data_dir / "server-candidate"),
                 "candidate_sha256": "c" * 64, "projection_id": "projection.server"}
    present = True
    active = False

    @contextmanager
    def current_action(requested_project):
        nonlocal active
        assert requested_project == project_id
        if not present:
            raise FoundryError("FINAL_CHARACTER_REVIEW_NOT_READY", "Command 4 is missing.", status_code=409)
        active = True
        try:
            yield receipt, fresh_db.settings.data_dir / "verified-component-snapshot"
        finally:
            active = False

    def compile_release(self, requested_project, **kwargs):
        assert active
        calls.append((requested_project, kwargs))
        return {"status": "COMPILED", "command5": candidate}

    def record_action(requested_project, result):
        recorded.append((requested_project, result))
        return {"receipt_id": "component.command4.rebound"}

    monkeypatch.setattr(app.state.final_character_workflow, "_current_action", current_action)
    monkeypatch.setattr(CharacterProductionReleaseAdapter, "compile", compile_release)
    monkeypatch.setattr(app.state.final_character_workflow, "record_action_workspace", record_action)
    url = f"/api/characters/{project_id}/factory-workspace/command5-rebind"
    with TestClient(app) as client:
        headers = {"x-foundry-token": app.state.session_token}
        result = client.post(url, headers=headers, json={"reviewed_overlay_root": "/untrusted"})
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "COMPILED"
        assert result.json()["final_character_component"]["receipt_id"] == "component.command4.rebound"
        assert recorded == [(project_id, {"valid": True, "overlay_path": candidate["workspace"],
                                         "candidate_sha256": candidate["candidate_sha256"],
                                         "projection_id": candidate["projection_id"]})]
        assert calls == [(project_id, {
            "output_root": fresh_db.settings.logs_dir / "factory_command5_rebind" / project_id / receipt["receipt_id"],
            "reviewed_overlay_root": fresh_db.settings.logs_dir / "factory_command4_authoring" / "command4_authoring_overlays" / receipt["overlay_id"],
        })]
        assert active is False
        present = False
        missing = client.post(url, headers=headers, json={})
        assert missing.status_code == 409, missing.text
        assert missing.json()["error"]["code"] == "FINAL_CHARACTER_REVIEW_NOT_READY"
        assert len(calls) == 1
