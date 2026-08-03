from __future__ import annotations

import io
import json
import zipfile
import uuid
from copy import deepcopy
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from ai_provider.secrets import InMemorySecretStore
from app.api import create_app
from app.core import Settings, canonical_json
from catalog.service import CatalogService
from character_creation.current_fixture import W5_PROJECT_ID, create_fresh_project
from tests.cat3_p1r_browser_harness import (
    FREE_GRANTS,
    CAT3_LEVEL_TALENTS,
    PRIORITY_FIXTURES,
    SPHERES,
    complete_cat3_plan,
)
from tests.r4v_harness import provision_external_test_key
from vendor_adapter.service import FactoryAdapter

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
BINDING_CODE = "CG1_COMPLETE_RESPONSE_REQUEST_HASH_MISMATCH"
BINDING_MESSAGE = (
    "The complete response is not bound to this exact active request. "
    "Prepare a new response from this run's complete request and try again."
)


def _headers(client: TestClient) -> dict[str, str]:
    return {"x-foundry-token": client.get("/api/session").json()["token"]}


def _project_identity(app, project_id: str) -> tuple[int, str]:
    project = app.state.projects.get_project(project_id)["project"]
    return int(project["revision"]), canonical_json(project)


def _bound_plan(app, run: dict, *, warnings: bool = False) -> dict:
    # Keep the deterministic CAT3 character entirely inside external-provider
    # test output; production services continue to derive authority dynamically.
    plan = complete_cat3_plan(
        app.state.db,
        run["project_id"],
        stage1_prompt=run["request"]["stage1_prompt"],
    )
    plan["request_sha256"] = run["request"]["request_sha256"]
    if warnings:
        plan["uncertainties"] = [{"code": "OWNER_REVIEW_REQUIRED", "message": "Owner review is intentionally required."}]
    return plan


def _provider_handler(context: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        behavior = context.get("behavior", "clean")
        if behavior == "http_error":
            return httpx.Response(503, json={"error": "deterministic provider outage"})
        provider_request = json.loads(request.content)
        prompt = json.loads(provider_request["messages"][1]["content"])
        complete_request = prompt["complete_request"]
        app = context["app"]
        run_like = {
            "project_id": complete_request["project_id"],
            "request": complete_request,
        }
        plan = _bound_plan(app, run_like, warnings=behavior == "warning")
        if behavior == "wrong_hash":
            plan["request_sha256"] = "0" * 64
        content = canonical_json(plan)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 101, "completion_tokens": 53, "total_tokens": 154},
            },
        )

    return handler


def _new_project(app, label: str) -> str:
    project_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "tianxia:w5-p1r-r1:" + label))
    created = create_fresh_project(app.state.db, project_id=project_id)
    return created["project_id"]


def _start(client: TestClient, headers: dict[str, str], project_id: str, mode: str, key: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/character-creation/runs",
        headers=headers,
        json={"execution_mode": mode, "idempotency_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_binding_409(response) -> None:
    assert response.status_code == 409, response.text
    assert response.json() == {
        "error": {"code": BINDING_CODE, "message": BINDING_MESSAGE, "details": response.json()["error"]["details"]}
    }


def test_w5_p1r_r1_real_application_endpoints_and_provider(tmp_path: Path) -> None:
    data = tmp_path / "OwnerData"
    provision_external_test_key(data)
    settings = Settings.from_env(ROOT, data)
    context: dict = {"behavior": "clean"}
    app = create_app(
        settings,
        ai_transport=httpx.MockTransport(_provider_handler(context)),
        ai_secret_store=InMemorySecretStore("test-deepseek-key-123"),
    )
    context["app"] = app

    with TestClient(app) as client:
        configured = FactoryAdapter(app.state.db).configure(FACTORY)
        CatalogService(app.state.db).rebuild_core(Path(configured["factory_root"]))
        assert app.state.canonical_catalog.status()["canonical_sphere_count"] == 85
        headers = _headers(client)
        provider = client.post(
            "/api/ai-provider/configure",
            headers=headers,
            json={
                "enabled": True,
                "model": "deepseek-v4-flash",
                "thinking_mode": "disabled",
                "max_output_tokens": 8192,
                "timeout_seconds": 30,
                "data_sharing_acknowledged": True,
                "acknowledged_by": "W5-P1R-R1 deterministic acceptance",
            },
        )
        assert provider.status_code == 200, provider.text
        assert provider.json()["ready"] is True

        # Real Manual Chat paste endpoint: prior_attempt_id is accepted and reaches typed validation.
        manual_id = _new_project(app, "w5-r1-manual")
        manual_before = _project_identity(app, manual_id)
        manual = _start(client, headers, manual_id, "MANUAL_CHAT", "w5.r1.manual.paste")
        incomplete = {"schema": "TianxiaFoundry.CharacterCreationPlan.v2", "request_sha256": manual["request"]["request_sha256"]}
        pasted = client.post(
            f"/api/character-creation/runs/{manual['run_id']}/manual-response",
            headers=headers,
            json={
                "response_text": canonical_json(incomplete),
                "request_sha256": manual["request"]["request_sha256"],
                "prior_attempt_id": "stage1.attempt.owner-revision-chain",
            },
        )
        assert pasted.status_code == 200, pasted.text
        assert pasted.json()["status"] == "NEEDS_REVIEW"
        assert pasted.json()["blockers"][0]["code"] == "CG1_PLAN_BLOCKED"
        assert pasted.json()["transport"]["prior_attempt_id"] == "stage1.attempt.owner-revision-chain"
        assert _project_identity(app, manual_id) == manual_before

        # A response copied from another run, an all-zero hash, and a missing hash all fail with one exact 409.
        copied_id = _new_project(app, "w5-r1-manual-copied-target")
        copied = _start(client, headers, copied_id, "MANUAL_CHAT", "w5.r1.manual.copied")
        copied_plan = deepcopy(incomplete)
        copied_response = client.post(
            f"/api/character-creation/runs/{copied['run_id']}/manual-response",
            headers=headers,
            json={"response_text": canonical_json(copied_plan), "request_sha256": copied["request"]["request_sha256"]},
        )
        _assert_binding_409(copied_response)

        for label, value in (("zeros", "0" * 64), ("missing", None)):
            run = _start(client, headers, manual_id, "MANUAL_CHAT", f"w5.r1.manual.{label}")
            plan = {"schema": "TianxiaFoundry.CharacterCreationPlan.v2"}
            if value is not None:
                plan["request_sha256"] = value
            response = client.post(
                f"/api/character-creation/runs/{run['run_id']}/manual-response",
                headers=headers,
                json={"response_text": canonical_json(plan), "request_sha256": run["request"]["request_sha256"]},
            )
            _assert_binding_409(response)
            assert client.get(f"/api/character-creation/runs/{run['run_id']}").json()["status"] == "WAITING_FOR_RESPONSE"

        # Raw JSON and ZIP response-file surfaces share the same central binding gate.
        file_run = _start(client, headers, manual_id, "MANUAL_CHAT", "w5.r1.manual.file")
        file_plan = {"schema": "TianxiaFoundry.CharacterCreationPlan.v2", "request_sha256": file_run["request"]["request_sha256"]}
        file_response = client.post(
            f"/api/character-creation/runs/{file_run['run_id']}/manual-response-file?filename=response.json",
            headers=headers,
            content=canonical_json(file_plan).encode("utf-8"),
        )
        assert file_response.status_code == 200, file_response.text
        assert file_response.json()["blockers"][0]["code"] == "CG1_PLAN_BLOCKED"

        zip_run = _start(client, headers, manual_id, "MANUAL_CHAT", "w5.r1.manual.zip")
        bad_zip_plan = {"schema": "TianxiaFoundry.CharacterCreationPlan.v2", "request_sha256": "0" * 64}
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("response.json", canonical_json(bad_zip_plan))
        zip_response = client.post(
            f"/api/character-creation/runs/{zip_run['run_id']}/manual-response-file?filename=response.zip",
            headers=headers,
            content=payload.getvalue(),
        )
        _assert_binding_409(zip_response)
        assert _project_identity(app, manual_id) == manual_before

        # The accepted current production fixture has an immutable proof prefix bound to W5_PROJECT_ID.
        created = create_fresh_project(app.state.db, project_id=W5_PROJECT_ID)
        production_id = created["project_id"]
        production_before = _project_identity(app, production_id)

        # A production provider response with the wrong active hash fails before scratch compilation.
        context["behavior"] = "wrong_hash"
        wrong = _start(client, headers, production_id, "STANDARD_API", "w5.r1.standard.wronghash")
        assert wrong["status"] == "NEEDS_REVIEW"
        assert wrong["blockers"][0]["code"] == BINDING_CODE
        assert wrong["dry_run"] == {}
        assert _project_identity(app, production_id) == production_before

        # Provider failure returns truthfully to Manual Chat without canonical mutation.
        context["behavior"] = "http_error"
        failure = _start(client, headers, production_id, "AUTO_FINALIZE_WHEN_CLEAN", "w5.r1.auto.failure")
        assert failure["execution_mode"] == "MANUAL_CHAT"
        assert failure["status"] == "WAITING_FOR_RESPONSE"
        assert failure["transport"]["provider_called"] is True
        assert failure["warnings"][0]["code"] == "CG1_PROVIDER_EXECUTION_FAILED_FALLBACK_MANUAL"
        assert not failure["commit"] and not failure["dry_run"]
        assert _project_identity(app, production_id) == production_before

        # Real AIProviderService: use one server-generated normal-wizard project
        # through Standard review and Auto finalization. The legacy sealed W5
        # fixture above remains unchanged and retains its historical event shape.
        normal = app.state.character_builder.create_project(
            working_name="CAT3 external-provider production endpoint proof",
            concept="Typed current-authority production endpoint proof",
            target_cl=7,
            power_band="rival/boss",
            source_reference=None,
            creation_mode="detailed",
            ability_scores={},
            selections={},
            sphere_priority_ids=list(SPHERES),
            talent_priority_ids=[talent_id for _, talent_id in PRIORITY_FIXTURES],
            generation_route="ai_bootstrap",
        )
        normal_id = normal["project_id"]
        committed_choices = app.state.character_builder.commit_catalog_choices(
            normal_id,
            acquired_sphere_ids=list(SPHERES),
            free_talent_grants=dict(FREE_GRANTS),
            ordinary_talent_ids=list(CAT3_LEVEL_TALENTS),
        )
        assert committed_choices["evidence_issued"] is False
        assert committed_choices["grant_plan"]["ready"] is True
        normal_before = _project_identity(app, normal_id)

        # Standard API performs two isolated builds and stops for owner review.
        context["behavior"] = "clean"
        standard = _start(client, headers, normal_id, "STANDARD_API", "w5.r1.standard.clean")
        assert standard["status"] == "READY_FOR_REVIEW", canonical_json(
            {"status": standard["status"], "blockers": standard["blockers"]}
        )
        assert standard["dry_run"]["independent_compilations"] == 2
        assert standard["transport"]["provider_called"] is True
        assert standard["transport"]["provider_request_sha256"]
        assert standard["transport"]["provider_response_sha256"]
        assert standard["transport"]["provider_completion_sha256"]
        assert standard["transport"]["usage"]["total_tokens"] == 154
        assert not standard["commit"]
        standard_snapshot = standard["request"]["typed_choice_snapshot"]
        assert standard_snapshot["canonical_project_id"] == normal_id
        assert standard_snapshot["display_name_content"] == normal["working_name"]
        assert _project_identity(app, normal_id) == normal_before
        wrong_mode_opt_in = client.post(
            f"/api/character-creation/runs/{standard['run_id']}/auto-finalize-opt-in",
            headers=headers,
        )
        assert wrong_mode_opt_in.status_code == 409, wrong_mode_opt_in.text
        assert wrong_mode_opt_in.json()["error"]["code"] == "CG1_AUTO_FINALIZE_MODE_REQUIRED"
        assert _project_identity(app, normal_id) == normal_before

        # Finalize the reviewed candidate from that exact run and snapshot.
        finalized_response = client.post(
            f"/api/character-creation/runs/{standard['run_id']}/finalize",
            headers=headers,
        )
        assert finalized_response.status_code == 200, finalized_response.text
        finalized = finalized_response.json()
        assert finalized["status"] == "CLEAN_AND_FINALIZED"
        assert finalized["request"]["typed_choice_snapshot"] == standard_snapshot
        assert finalized["commit"]["typed_choice_snapshot_sha256"] == standard_snapshot["snapshot_sha256"]
        assert finalized["commit"]["auto_finalize_opt_in_receipt_sha256"] is None
        assert _project_identity(app, normal_id) != normal_before
