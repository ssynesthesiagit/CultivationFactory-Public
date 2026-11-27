from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Database, Settings, canonical_json
from catalog.service import CatalogService
from rec1_p1cr4_real_acceptance import PINNED_FACTORY, ROOT, _semantic_response, _start_run
from vendor_adapter.service import FactoryAdapter


def test_finalize_after_owner_edits_publishes_one_candidate_identity(tmp_path, monkeypatch):
    """Exercise the real Equal Path Stage 2 authority with an edited review candidate."""
    monkeypatch.setenv("TIANXIA_CONCEPT_EMBEDDINGS", "0")
    monkeypatch.setenv("TIANXIA_AUTO_TOKEN", "0")
    settings = Settings.from_env(ROOT, tmp_path / "data")
    db = Database(settings)
    db.migrate()
    configured = FactoryAdapter(db).configure(PINNED_FACTORY)
    CatalogService(db).rebuild_core(Path(configured["factory_root"]))
    app = create_app(settings)

    with TestClient(app) as client:
        headers = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
        created, started = _start_run(client, app.state.character_builder, headers, source="Owner edit candidate identity")
        locks = {row["field"]: row["value"] for row in created["project"]["user_locks"]}
        assert locks.get("character.identity.display_name") is None
        assert not locks.get("concept")
        run_id = started["run_id"]
        url = f"/api/character-creation/runs/{run_id}"
        run = app.state.character_creation.get(run_id)
        response = _semantic_response(run, planning=created["acceptance_planning"])
        upload = client.post(
            f"{url}/manual-response-file",
            params={"filename": "owner-edit-candidate.json"},
            headers={**headers, "Content-Type": "application/json"},
            content=canonical_json(response).encode("utf-8"),
        )
        assert upload.status_code == 200, upload.text
        reviewed = upload.json()
        assert reviewed["status"] == "READY_FOR_REVIEW", reviewed["blockers"]
        reviewed_identity = app.state.character_creation.get(run_id)["dry_run"]["candidate_identity"]

        name, concept = "Owner's Revised Character", "A wanderer writing a new story."
        edit = client.post(f"{url}/descriptive-fields", headers=headers, json={"name": name, "concept": concept})
        assert edit.status_code == 200, edit.text
        accepted = edit.json()["owner_descriptive_fields"]["accepted"]
        assert accepted["identity"]["name"] == name
        assert accepted["concept"] == concept

        finalized = client.post(f"{url}/finalize", headers=headers, json={})
        assert finalized.status_code == 200, finalized.text
        assert finalized.json()["status"] == "CLEAN_AND_FINALIZED"
        with db.connection() as conn:
            row = conn.execute(
                "SELECT dry_run_json, quality_json, commit_json FROM character_creation_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
        candidate, quality, commit = (json.loads(column) for column in row)
        assert candidate["candidate_identity"] != reviewed_identity
        assert candidate["candidate_identity"] == quality["candidate_identity"] == commit["approved_candidate_identity"]
