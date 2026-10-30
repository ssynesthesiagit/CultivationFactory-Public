from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import create_app
from app.core import FoundryError, Settings
from app.models import (
    FinalCharacterApprovalChallengeRequest,
    FinalCharacterApproveRequest,
    FinalCharacterMaterializeRequest,
)
from security.local_identity import DeterministicTestPrincipalProvider


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "project.final-character.api"


@pytest.mark.parametrize(
    ("model", "required"),
    [
        (FinalCharacterApprovalChallengeRequest, {"ttl_seconds": 300}),
        (
            FinalCharacterApproveRequest,
            {"challenge_id": "challenge.api", "nonce": "nonce.api"},
        ),
        (
            FinalCharacterMaterializeRequest,
            {"review_record_id": "final-review." + "a" * 64},
        ),
    ],
)
def test_final_character_mutations_forbid_server_owned_fields(model, required) -> None:
    with pytest.raises(ValidationError):
        model(
            **required,
            path="/tmp/client-controlled",
            binding={"candidate_sha256": "b" * 64},
            provider="client-provider",
            evidence_id="client-evidence",
        )


def test_final_character_api_routes_are_typed_and_share_bound_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        Settings.from_env(ROOT, tmp_path / "data"),
        principal_provider=DeterministicTestPrincipalProvider(),
    )
    workflow = app.state.final_character_workflow
    factory_authoring = app.state.factory_authoring

    assert workflow.principal_provider is app.state.principal_provider
    assert factory_authoring.principal_provider is app.state.principal_provider
    assert factory_authoring.final_character_workflow is workflow
    assert factory_authoring.integrity is workflow.integrity

    dispatch: dict[str, tuple[object, ...]] = {}

    def fake_preview(project_id: str) -> dict[str, str]:
        dispatch["preview"] = (project_id,)
        return {"status": "NOT_READY", "project_id": project_id}

    def fake_challenge(project_id: str, ttl_seconds: int = 300) -> dict[str, object]:
        dispatch["challenge"] = (project_id, ttl_seconds)
        return {"status": "ISSUED", "project_id": project_id}

    def fake_approve(project_id: str, challenge_id: str, nonce: str) -> dict[str, str]:
        dispatch["approve"] = (project_id, challenge_id, nonce)
        return {"status": "APPROVED", "project_id": project_id}

    def fake_materialize(project_id: str, review_record_id: str) -> dict[str, str]:
        dispatch["materialize"] = (project_id, review_record_id)
        return {"status": "MATERIALIZED", "project_id": project_id}

    monkeypatch.setattr(
        workflow,
        "preview_current_triplet",
        fake_preview,
    )
    monkeypatch.setattr(
        workflow,
        "issue_review_challenge",
        fake_challenge,
    )
    monkeypatch.setattr(
        workflow,
        "approve_current_triplet",
        fake_approve,
    )
    monkeypatch.setattr(
        workflow,
        "materialize_current_triplet",
        fake_materialize,
    )

    expected_paths = {
        f"/api/characters/{{project_id}}/factory-workspace/final-character/{suffix}"
        for suffix in ("preview", "approval-challenge", "approve", "materialize")
    }
    assert expected_paths <= {route.path for route in app.routes}

    headers = {"x-foundry-token": app.state.session_token}
    with TestClient(app) as client:
        assert client.get(
            f"/api/characters/{PROJECT_ID}/factory-workspace/final-character/preview"
        ).status_code == 200

        assert client.post(
            f"/api/characters/{PROJECT_ID}/factory-workspace/final-character/approval-challenge",
            headers=headers,
            json={"ttl_seconds": 300, "path": "/tmp/ignored"},
        ).status_code == 422
        assert client.post(
            f"/api/characters/{PROJECT_ID}/factory-workspace/final-character/approval-challenge",
            headers=headers,
            json={"ttl_seconds": 321},
        ).status_code == 200

        assert client.post(
            f"/api/characters/{PROJECT_ID}/factory-workspace/final-character/approve",
            headers=headers,
            json={
                "challenge_id": "challenge.api",
                "nonce": "nonce.api",
                "binding": {"candidate_sha256": "b" * 64},
                "reviewer": "client-reviewer",
                "evidence_id": "client-evidence",
            },
        ).status_code == 422
        assert client.post(
            f"/api/characters/{PROJECT_ID}/factory-workspace/final-character/approve",
            headers=headers,
            json={"challenge_id": "challenge.api", "nonce": "nonce.api"},
        ).status_code == 200

        assert client.post(
            f"/api/characters/{PROJECT_ID}/factory-workspace/final-character/materialize",
            headers=headers,
            json={
                "review_record_id": "final-review." + "a" * 64,
                "output_root": "/tmp/ignored",
            },
        ).status_code == 422
        assert client.post(
            f"/api/characters/{PROJECT_ID}/factory-workspace/final-character/materialize",
            headers=headers,
            json={"review_record_id": "final-review." + "a" * 64},
        ).status_code == 200

    assert dispatch == {
        "preview": (PROJECT_ID,),
        "challenge": (PROJECT_ID, 321),
        "approve": (PROJECT_ID, "challenge.api", "nonce.api"),
        "materialize": (PROJECT_ID, "final-review." + "a" * 64),
    }


def test_final_character_api_redacts_foundry_error_paths_but_keeps_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        Settings.from_env(ROOT, tmp_path / "data"),
        principal_provider=DeterministicTestPrincipalProvider(),
    )
    workflow = app.state.final_character_workflow
    secret = tmp_path / "private" / "nested" / "server-file.json"
    secret.parent.mkdir(parents=True)
    secret.write_text("diagnostic fixture\n", encoding="utf-8")
    message = f"review store failed at {secret}"
    details = {
        "path": str(secret),
        "nested": {"cause": f"retrying {secret}", "paths": [str(secret), {"again": str(secret)}]},
    }

    def fail(_project_id: str, _ttl_seconds: int = 300) -> dict[str, object]:
        raise FoundryError("FINAL_CHARACTER_REVIEW_STORE_INVALID", message, details=details, status_code=409)

    monkeypatch.setattr(workflow, "issue_review_challenge", fail)
    route = f"/api/characters/{PROJECT_ID}/factory-workspace/final-character/approval-challenge"
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            route,
            headers={"x-foundry-token": app.state.session_token},
            json={"ttl_seconds": 300},
        )

    assert response.status_code == 409
    assert str(secret) not in response.text
    body = response.json()
    assert body["error"]["code"] == "FINAL_CHARACTER_REVIEW_STORE_INVALID"
    assert body["error"]["message"] == "review store failed at <server-path>"
    assert body["error"]["details"] == {
        "path": "<server-path>",
        "nested": {"cause": "retrying <server-path>", "paths": ["<server-path>", {"again": "<server-path>"}]},
    }
    with app.state.db.connection() as conn:
        row = conn.execute(
            "SELECT message, details_json FROM recent_errors WHERE code=? ORDER BY error_id DESC LIMIT 1",
            ("FINAL_CHARACTER_REVIEW_STORE_INVALID",),
        ).fetchone()
    assert row is not None
    assert str(secret) in row["message"]
    assert str(secret) in row["details_json"]


def test_final_character_api_redacts_unexpected_error_paths_but_keeps_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        Settings.from_env(ROOT, tmp_path / "data"),
        principal_provider=DeterministicTestPrincipalProvider(),
    )
    workflow = app.state.final_character_workflow
    secret = tmp_path / "private" / "unexpected" / "server-file.json"
    secret.parent.mkdir(parents=True)
    secret.write_text("diagnostic fixture\n", encoding="utf-8")

    def fail(_project_id: str, _review_record_id: str) -> dict[str, object]:
        raise RuntimeError(f"unexpected failure at {secret} and {secret / 'child.json'}")

    monkeypatch.setattr(workflow, "materialize_current_triplet", fail)
    route = f"/api/characters/{PROJECT_ID}/factory-workspace/final-character/materialize"
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            route,
            headers={"x-foundry-token": app.state.session_token},
            json={"review_record_id": "final-review." + "a" * 64},
        )

    assert response.status_code == 500
    assert str(secret) not in response.text
    body = response.json()
    assert body["error"]["code"] == "UNEXPECTED_ERROR"
    assert body["error"]["message"] == "An unexpected local application error occurred."
    assert body["error"]["details"] == "unexpected failure at <server-path> and <server-path>"
    with app.state.db.connection() as conn:
        row = conn.execute(
            "SELECT message FROM recent_errors WHERE code=? ORDER BY error_id DESC LIMIT 1",
            ("UNEXPECTED_ERROR",),
        ).fetchone()
    assert row is not None
    assert str(secret) in row["message"]
