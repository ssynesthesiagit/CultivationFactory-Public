from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from factory_authoring.command4_provider import Command4ProviderAuthoring
from factory_authoring.service import FactoryAuthoringWorkspaceService


ROOT = Path(__file__).resolve().parents[1]


def test_service_command4_authoring_uses_server_owned_output_root(tmp_path, monkeypatch) -> None:
    service = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
    service.db = SimpleNamespace(settings=SimpleNamespace(logs_dir=tmp_path / "logs"))
    provider = object()
    seen: dict[str, object] = {}

    def fake_author(self, project_id, received_provider, output_root):
        seen.update({"project_id": project_id, "provider": received_provider, "output_root": output_root})
        return {"valid": False, "test_only": True}

    monkeypatch.setattr(Command4ProviderAuthoring, "author", fake_author)
    result = service.author_command4("project.command4", provider)

    assert result == {"valid": False, "test_only": True}
    assert seen == {
        "project_id": "project.command4",
        "provider": provider,
        "output_root": (tmp_path / "logs" / "factory_command4_authoring").resolve(),
    }


def test_command4_authoring_endpoint_is_explicit_and_has_no_client_output_path(tmp_path) -> None:
    app = create_app(Settings.from_env(ROOT, tmp_path / "data"))
    calls: list[tuple[str, object]] = []

    def fake_author(project_id, provider):
        calls.append((project_id, provider))
        return {"valid": False, "test_only": True}

    app.state.factory_authoring.author_command4 = fake_author
    headers = {"x-foundry-token": app.state.session_token}
    with TestClient(app) as client:
        assert client.get("/api/characters/project.command4/factory-workspace/status").status_code == 200
        assert calls == []
        response = client.post(
            "/api/characters/project.command4/factory-workspace/command4-author?output_root=/tmp/ignored",
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {"valid": False, "test_only": True}
    assert calls == [("project.command4", app.state.ai_provider)]
