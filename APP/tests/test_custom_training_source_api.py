from __future__ import annotations

import hashlib
import shutil
import sqlite3
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core import CORE_PACK_ID, CORE_PACK_VERSION, Database, Settings, canonical_json
from character_creation.custom_training_source_authority import (
    build_custom_training_source_record,
    normalize_custom_training_source,
)
from contracts.canonical import canonical_record_hash
from security.local_identity import DeterministicTestPrincipalProvider


ROOT = Path(__file__).resolve().parents[1]


class _RejectProviderTransport(httpx.BaseTransport):
    """Fail the test if any endpoint unexpectedly reaches an AI transport."""

    def __init__(self) -> None:
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise AssertionError(f"provider transport was called: {request.method} {request.url}")


def _clone_catalog_db(catalog_environment: dict, data_dir: Path) -> tuple[Settings, Database]:
    settings = Settings.from_env(ROOT, data_dir)
    settings.ensure_dirs()
    source = sqlite3.connect(catalog_environment["settings"].db_path)
    target = sqlite3.connect(settings.db_path)
    source.backup(target)
    target.close()
    source.close()
    source_security = catalog_environment["settings"].data_dir / "security"
    target_security = settings.data_dir / "security"
    if source_security.is_dir():
        shutil.copytree(source_security, target_security, dirs_exist_ok=True, copy_function=shutil.copy2)
    db = Database(settings)
    db.migrate()
    return settings, db


def _create_project(app) -> str:
    with app.state.db.connection() as conn:
        pack = conn.execute(
            "SELECT pack_hash FROM content_packs WHERE pack_id=? AND version=?",
            (CORE_PACK_ID, CORE_PACK_VERSION),
        ).fetchone()
    assert pack is not None
    created = app.state.projects.create_project(
        working_name="Custom training-source API fixture",
        pack_locks=[
            {
                "pack_id": CORE_PACK_ID,
                "version": CORE_PACK_VERSION,
                "pack_hash": pack["pack_hash"],
            }
        ],
        user_locks=[],
    )
    return created["project"]["project_id"]


def _state(db: Database, project_id: str) -> dict:
    with db.connection() as conn:
        project = conn.execute(
            "SELECT revision,canonical_project_hash,project_json FROM projects WHERE project_id=?",
            (project_id,),
        ).fetchone()
        assert project is not None
        return {
            "revision": project["revision"],
            "canonical_project_hash": project["canonical_project_hash"],
            "project_json": project["project_json"],
            "locked_count": conn.execute(
                "SELECT COUNT(*) FROM project_locked_records WHERE project_id=?",
                (project_id,),
            ).fetchone()[0],
            "challenge_count": conn.execute(
                "SELECT COUNT(*) FROM exact_approval_challenges",
            ).fetchone()[0],
        }


@pytest.fixture()
def api_environment(catalog_environment, tmp_path):
    settings, db = _clone_catalog_db(catalog_environment, tmp_path / "custom-source-api")
    transport = _RejectProviderTransport()
    app = create_app(
        settings,
        ai_transport=transport,
        principal_provider=DeterministicTestPrincipalProvider(),
    )
    project_id = _create_project(app)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        yield {
            "app": app,
            "client": client,
            "db": db,
            "project_id": project_id,
            "headers": {"X-Foundry-Token": token},
            "transport": transport,
        }


def _target_response(env: dict, *, training_type: str = "new_sphere", limit: int = 5) -> dict:
    response = env["client"].get(
        f"/api/projects/{env['project_id']}/manual-lineage-training-source/targets",
        params={"training_type": training_type, "limit": limit},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _envelope(target_id: str) -> dict:
    return {
        "route_id": "owner_supplied_custom_training_source",
        "owner_confirmation_id": "owner-confirmation.api.001",
        "display_name": "API Owner Training Source",
        "summary": "A bounded source supplied for an explicitly reviewed target.",
        "source_text": "The owner supplied this exact source description for the selected target.",
        "source_anchor": "manual-lineage.api.custom-source",
        "access_mode": "owner-confirmed-study",
        "training_types": ["new_sphere"],
        "target_record_ids": [target_id],
    }


def _deep_valid_source_snapshot(authenticated: dict) -> tuple[dict, str, str]:
    """Derive a schema-valid canonical source/target pair for helper testing."""
    rows = authenticated["records"]
    source_row = next(
        row
        for row in rows
        if row["record"].get("content_type") == "sphere"
        and isinstance(
            ((row["record"].get("compatibility") or {}).get("factory") or {}).get("stage2_authority"),
            dict,
        )
    )
    target_row = next(
        row
        for row in rows
        if row["record"].get("content_type") == "sphere"
        and row["record_id"] != source_row["record_id"]
    )
    source = deepcopy(source_row["record"])
    stage2 = source["compatibility"]["factory"]["stage2_authority"]
    allowed_kinds = list(stage2.get("allowed_kinds") or [])
    if "training_source_access" not in allowed_kinds:
        allowed_kinds.append("training_source_access")
    stage2["allowed_kinds"] = allowed_kinds
    stage2["training_source_access"] = {
        "mode": "requires_access_event",
        "access_modes": ["canonical-study"],
        "training_types": ["new_sphere"],
        "target_record_ids": [target_row["record_id"]],
    }
    source["record_hash"] = canonical_record_hash(source)
    replacement = deepcopy(source_row)
    replacement["record"] = source
    replacement["record_hash"] = source["record_hash"]
    injected = deepcopy(authenticated)
    injected["records"] = [
        replacement if row["record_id"] == source_row["record_id"] else row
        for row in injected["records"]
    ]
    return injected, source["record_id"], target_row["record_id"]


def test_contract_and_target_search_are_locked_deterministic_and_read_only(api_environment, monkeypatch):
    env = api_environment
    client = env["client"]
    project_id = env["project_id"]
    before = _state(env["db"], project_id)

    contract = client.get(f"/api/projects/{project_id}/manual-lineage-training-source")
    assert contract.status_code == 200, contract.text
    payload = contract.json()
    assert payload["schema"] == "TianxiaFoundry.ManualLineageTrainingSourceContract.v1"
    assert payload["selected_route"] is None
    assert [route["route_id"] for route in payload["resolution_routes"]] == [
        "selected_ai_custom_training_source",
        "owner_supplied_custom_training_source",
        "locked_canonical_training_source",
    ]
    assert all(route["selection"] == "Not auto-selected." for route in payload["resolution_routes"])
    assert payload["resolution_routes"][0]["available"] is True
    assert payload["resolution_routes"][0]["actionable_now"] is False
    assert payload["resolution_routes"][0]["availability_status"] == "requires_explicit_ai_proposal"
    assert payload["resolution_routes"][1]["available"] is True
    assert payload["resolution_routes"][1]["actionable_now"] is True
    locked_route = payload["resolution_routes"][2]
    assert locked_route["available"] is bool(payload["locked_canonical_records"])

    targets = _target_response(env)
    assert targets["content_type"] == "sphere"
    assert targets["records"]
    assert len(targets["records"]) <= 5
    assert all(row["content_type"] == "sphere" for row in targets["records"])
    first = targets["records"][0]
    searched = client.get(
        f"/api/projects/{project_id}/manual-lineage-training-source/legal-targets",
        params={"training_type": "new_sphere", "q": first["record_id"], "limit": 1},
    )
    assert searched.status_code == 200, searched.text
    assert searched.json()["records"] == [first]
    for training_type, content_type in (
        ("new_sphere", "sphere"),
        ("known_sphere_talent", "talent"),
        ("recorded_art", "recorded_art"),
    ):
        typed_targets = client.get(
            f"/api/projects/{project_id}/manual-lineage-training-source/targets",
            params={"training_type": training_type, "limit": 50},
        )
        assert typed_targets.status_code == 200, typed_targets.text
        assert all(row["content_type"] == content_type for row in typed_targets.json()["records"])
    assert client.get(
        f"/api/projects/{project_id}/manual-lineage-training-source/targets",
        params={"training_type": "new_sphere", "limit": 51},
    ).status_code == 422
    whitespace = client.get(
        f"/api/projects/{project_id}/manual-lineage-training-source/targets",
        params={"training_type": "new_sphere", "q": "  "},
    )
    assert whitespace.status_code == 400
    assert whitespace.json()["error"]["code"] == "CUSTOM_TRAINING_SOURCE_TARGET_QUERY_INVALID"

    # An apparent source with a complete-looking Stage-2 field but a target
    # outside the same authenticated snapshot is not an actionable canonical
    # option.  This injects only an in-memory post-authentication diagnostic;
    # the project lock and database remain untouched.
    store = env["app"].state.projects
    authenticated = store._custom_training_source_snapshot(project_id)
    source_row = next(
        row
        for row in authenticated["records"]
        if isinstance(
            ((row["record"].get("compatibility") or {}).get("factory") or {}).get("stage2_authority"),
            dict,
        )
    )
    apparent = deepcopy(source_row)
    apparent["record"]["compatibility"]["factory"]["stage2_authority"]["training_source_access"] = {
        "mode": "requires_access_event",
        "access_modes": ["canonical-study"],
        "training_types": ["new_sphere"],
        "target_record_ids": ["not-in-the-authenticated-lock"],
    }
    apparent_authority = apparent["record"]["compatibility"]["factory"]["stage2_authority"]
    apparent_allowed_kinds = list(apparent_authority.get("allowed_kinds") or [])
    if "training_source_access" not in apparent_allowed_kinds:
        apparent_allowed_kinds.append("training_source_access")
    apparent_authority["allowed_kinds"] = apparent_allowed_kinds
    apparent["record"]["record_hash"] = canonical_record_hash(apparent["record"])
    apparent["record_hash"] = apparent["record"]["record_hash"]
    injected = deepcopy(authenticated)
    injected["records"] = [
        apparent if row["record_id"] == source_row["record_id"] else row
        for row in injected["records"]
    ]
    monkeypatch.setattr(store, "_custom_training_source_snapshot", lambda _project_id: injected)
    invalid_contract = client.get(f"/api/projects/{project_id}/manual-lineage-training-source")
    assert invalid_contract.status_code == 200, invalid_contract.text
    assert invalid_contract.json()["locked_canonical_records"] == []
    assert invalid_contract.json()["resolution_routes"][2]["available"] is False

    deep_valid, source_id, target_id = _deep_valid_source_snapshot(authenticated)
    monkeypatch.setattr(store, "_custom_training_source_snapshot", lambda _project_id: deep_valid)
    valid_contract = client.get(f"/api/projects/{project_id}/manual-lineage-training-source")
    assert valid_contract.status_code == 200, valid_contract.text
    valid_payload = valid_contract.json()
    valid_route = valid_payload["resolution_routes"][2]
    assert valid_route["available"] is True
    assert valid_route["actionable_now"] is True
    assert valid_route["total_count"] == 1
    assert valid_route["truncated"] is False
    assert len(valid_payload["locked_canonical_records"]) == 1
    assert valid_payload["locked_canonical_records"][0]["record_id"] == source_id
    assert valid_payload["locked_canonical_records"][0]["target_record_ids"] == [target_id]

    target_row = next(row for row in authenticated["records"] if row["record_id"] == target_id)
    top_level_directive = deepcopy(authenticated)
    directive_target = deepcopy(target_row)
    directive_target["record"]["authority"] = "user_directive"
    directive_target["record"]["record_hash"] = canonical_record_hash(directive_target["record"])
    directive_target["record_hash"] = directive_target["record"]["record_hash"]
    top_level_directive["records"] = [
        directive_target if row["record_id"] == target_id else row
        for row in top_level_directive["records"]
    ]
    monkeypatch.setattr(store, "_custom_training_source_snapshot", lambda _project_id: top_level_directive)
    suppressed = client.get(
        f"/api/projects/{project_id}/manual-lineage-training-source/targets",
        params={"training_type": "new_sphere", "q": target_id, "limit": 50},
    )
    assert suppressed.status_code == 200, suppressed.text
    assert target_id not in {row["record_id"] for row in suppressed.json()["records"]}
    assert _state(env["db"], project_id) == before
    assert env["transport"].calls == 0


def test_challenge_preview_is_exact_and_approval_is_the_only_seal(api_environment):
    env = api_environment
    client = env["client"]
    project_id = env["project_id"]
    target = _target_response(env, limit=1)["records"][0]
    envelope = _envelope(target["record_id"])
    before = _state(env["db"], project_id)

    selected_ai = deepcopy(envelope)
    selected_ai["route_id"] = "selected_ai_custom_training_source"
    selected_issue = client.post(
        f"/api/projects/{project_id}/manual-lineage-training-source/challenge",
        headers=env["headers"],
        json={**selected_ai, "ttl_seconds": 300},
    )
    assert selected_issue.status_code == 409, selected_issue.text
    selected_issue_error = selected_issue.json()["error"]
    assert selected_issue_error["code"] == "CUSTOM_TRAINING_SOURCE_AI_PROPOSAL_REQUIRED"
    assert "server-owned generated-proposal identifier" in selected_issue_error["message"]
    assert _state(env["db"], project_id) == before

    selected_approve = client.post(
        f"/api/projects/{project_id}/manual-lineage-training-source/approve",
        headers=env["headers"],
        json={
            **selected_ai,
            "challenge_id": "not-issued.selected-ai",
            "nonce": "not-issued-selected-ai-nonce",
        },
    )
    assert selected_approve.status_code == 409, selected_approve.text
    assert selected_approve.json()["error"]["code"] == "CUSTOM_TRAINING_SOURCE_AI_PROPOSAL_REQUIRED"
    assert _state(env["db"], project_id) == before

    unknown = dict(envelope)
    unknown["unexpected"] = True
    invalid = client.post(
        f"/api/projects/{project_id}/manual-lineage-training-source/challenge",
        headers=env["headers"],
        json={**unknown, "ttl_seconds": 300},
    )
    assert invalid.status_code == 422
    assert _state(env["db"], project_id) == before

    response = client.post(
        f"/api/projects/{project_id}/manual-lineage-training-source/challenge",
        headers=env["headers"],
        json={**envelope, "ttl_seconds": 300},
    )
    assert response.status_code == 200, response.text
    challenge = response.json()
    preview = challenge["preview"]
    normalized = normalize_custom_training_source(envelope)
    record = build_custom_training_source_record(normalized)
    assert challenge["status"] == "challenge_issued"
    assert challenge["sealed"] is False
    assert preview["seals_nothing"] is True
    assert preview["source_text"] == envelope["source_text"]
    assert preview["source_anchor"] == envelope["source_anchor"]
    assert preview["source_path"] == normalized["source_path"]
    assert preview["source_text_sha256"] == normalized["source_text_sha256"]
    assert preview["record_id"] == record["record_id"]
    assert preview["record_hash"] == record["record_hash"]
    assert preview["exact_record_bytes_sha256"] == hashlib.sha256(
        canonical_json(record).encode("utf-8")
    ).hexdigest()
    assert preview["exact_record_bytes_sha256"] == challenge["challenge"]["exact_bytes_hash"]
    assert preview["target_identities"] == [
        {
            "record_id": target["record_id"],
            "display_name": target["display_name"],
            "content_type": target["content_type"],
            "record_hash": target["record_hash"],
        }
    ]
    after_challenge = _state(env["db"], project_id)
    assert after_challenge["locked_count"] == before["locked_count"]
    assert after_challenge["project_json"] == before["project_json"]
    assert after_challenge["revision"] == before["revision"]
    assert after_challenge["challenge_count"] == before["challenge_count"] + 1

    challenge_data = challenge["challenge"]
    approval_payload = {
        **envelope,
        "challenge_id": challenge_data["challenge_id"],
        "nonce": challenge_data["nonce"],
    }
    approved = client.post(
        f"/api/projects/{project_id}/manual-lineage-training-source/approve",
        headers=env["headers"],
        json=approval_payload,
    )
    assert approved.status_code == 200, approved.text
    receipt = approved.json()
    assert receipt["status"] == "inserted"
    assert receipt["sealed"] is True
    assert receipt["candidate_revision_required"] is True
    assert receipt["record_id"] == record["record_id"]
    assert receipt["record_hash"] == record["record_hash"]
    after_approval = _state(env["db"], project_id)
    assert after_approval["locked_count"] == before["locked_count"] + 1
    assert after_approval["revision"] == before["revision"]
    assert after_approval["canonical_project_hash"] == before["canonical_project_hash"]
    assert after_approval["project_json"] == before["project_json"]
    assert after_approval["challenge_count"] == after_challenge["challenge_count"]

    replay = client.post(
        f"/api/projects/{project_id}/manual-lineage-training-source/approve",
        headers=env["headers"],
        json=approval_payload,
    )
    assert replay.status_code in {400, 409}
    changed = deepcopy(approval_payload)
    changed["summary"] += " changed"
    wrong_bytes = client.post(
        f"/api/projects/{project_id}/manual-lineage-training-source/approve",
        headers=env["headers"],
        json=changed,
    )
    assert wrong_bytes.status_code in {400, 409}
    assert env["transport"].calls == 0
