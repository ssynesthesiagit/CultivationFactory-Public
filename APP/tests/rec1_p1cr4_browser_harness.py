from __future__ import annotations

import argparse
import io
import json
import shutil
import socket
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_provider.secrets import InMemorySecretStore
from app.api import create_app
from app.core import Settings
from catalog.service import CatalogService
from vendor_adapter.service import FactoryAdapter


FACTORY = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
BODY_PATH = "tianxia.path.body_refining"
SPIRIT_PATH = "tianxia.path.spirit_awakening"
SUBPATH_IDS = [
    "tianxia.subpath.body.flesh_crucible",
    "tianxia.tradition.spirit.dreamweaver",
]
METHOD_ID = "METHOD-087"
FOUNDATION_ID = "ancient_desolate_sacred_body_v0_2C"


def _provider_handler(request: httpx.Request) -> httpx.Response:
    """Keep any accidental provider probe deterministic; no build uses it."""

    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"connection":"ok"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def _owner_path(row: dict[str, Any]) -> str | None:
    return row.get("owning_path_id") if isinstance(row.get("owning_path_id"), str) else None


def run(*, data: Path, output: Path, screenshot_dir: Path, browser: str, cleanup_data: bool = False) -> dict[str, Any]:
    data.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env(ROOT, data)
    app = create_app(
        settings,
        ai_transport=httpx.MockTransport(_provider_handler),
        ai_secret_store=InMemorySecretStore("rec1-p1cr4-browser-key-123"),
    )
    configured = FactoryAdapter(app.state.db).configure(FACTORY)
    CatalogService(app.state.db).rebuild_core(Path(configured["factory_root"]))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    server_thread = threading.Thread(target=server.run, name="rec1-p1cr4-browser", daemon=True)
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    dialogs: list[str] = []
    screenshots: list[str] = []

    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    error: str | None = None

    def check(name: str, condition: bool, detail: Any = None) -> None:
        checks[name] = bool(condition)
        if detail is not None:
            details[name] = detail
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    try:
        with TestClient(app):
            server_thread.start()
            for _ in range(300):
                if server.started:
                    break
                server_thread.join(0.05)
            check("real_loopback_server_started", server.started, base_url)

            with sync_playwright() as playwright:
                instance = playwright.chromium.launch(
                    executable_path=browser,
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--no-proxy-server"],
                )
                page = instance.new_page(viewport={"width": 1720, "height": 1200})
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on(
                    "console",
                    lambda message: console_errors.append(message.text)
                    if message.type == "error"
                    else None,
                )
                page.on(
                    "requestfailed",
                    lambda request: failed_requests.append(
                        f"{request.method} {request.url}: {request.failure}"
                    ),
                )
                page.goto(base_url, wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_function(
                    "document.querySelector('#sheetOptionsStatus')?.textContent.includes('canonical Spheres')",
                    timeout=120_000,
                )
                page.get_by_role("button", name="Customize Manually", exact=True).click()
                page.fill("#guidedName", "REC1 P1CR4 Browser Bindings")
                page.fill("#guidedConcept", "Body Refining and Spirit Awakening with two exact Path-owned Subpath bindings.")
                page.fill("#guidedLevel", "3")
                page.locator("#guidedBriefContinue").click()
                page.locator("#builderPaths").wait_for(state="visible", timeout=60_000)

                options = page.evaluate("async () => await api('/api/character-builder/options')")
                path_category = next(
                    row for row in options["categories"] if row["slot_id"] == "path_choice"
                )
                subpath_category = next(
                    row for row in options["categories"] if row["slot_id"] == "subpath_choice"
                )
                path_ids = [BODY_PATH, SPIRIT_PATH]
                path_index = options["path_subpath_index"]
                required_subpaths = list(SUBPATH_IDS)
                subpath_by_id = {
                    row["choice_id"]: row for row in subpath_category["choices"]
                }

                rendered_paths = page.locator("#sheetPaths input").evaluate_all(
                    "nodes => nodes.map(node => node.value)"
                )
                check(
                    "all_canonical_paths_rendered",
                    rendered_paths == [row["choice_id"] for row in path_category["choices"]],
                    {"rendered": rendered_paths, "server": [row["choice_id"] for row in path_category["choices"]]},
                )
                check(
                    "server_path_catalog_contains_body_and_spirit_only_selection",
                    set(path_ids).issubset(set(rendered_paths)) and len(path_ids) == 2,
                    {"selected": path_ids, "rendered_count": len(rendered_paths)},
                )
                for path_id in path_ids:
                    page.locator(f'#sheetPaths input[value="{path_id}"]').check()
                page.wait_for_function("methodCompatibility.state === 'accepted'", timeout=120_000)
                compatibility = page.evaluate("methodCompatibility.result")
                compatible_method_ids = [
                    row["method_id"]
                    for row in (compatibility or {}).get("compatible_methods", [])
                    if isinstance(row, dict) and isinstance(row.get("method_id"), str)
                ]
                method_row = next(
                    row for row in (compatibility or {}).get("compatible_methods", [])
                    if row.get("method_id") == METHOD_ID
                )
                check(
                    "server_compatibility_returns_method_087_for_body_spirit",
                    METHOD_ID in compatible_method_ids,
                    {"compatible_method_ids": compatible_method_ids},
                )
                check(
                    "method_087_action_and_access_text_are_server_provided",
                    method_row.get("access_required") is True
                    and bool(method_row.get("access_text"))
                    and any(route.get("choice_id") == "route-personal-teacher" for route in method_row.get("owner_route_options") or []),
                    {
                        "access_required": method_row.get("access_required"),
                        "access_text": method_row.get("access_text"),
                        "route_count": len(method_row.get("owner_route_options") or []),
                    },
                )
                page.locator('input[name="sheetMethodMode"][value="EXACT"]').check()
                page.wait_for_function(
                    "methodId => Array.from(document.querySelectorAll('#sheetMethod option')).some(option => option.value === methodId)",
                    arg=METHOD_ID,
                    timeout=60_000,
                )
                rendered_method_ids = page.locator("#sheetMethod option").evaluate_all(
                    "nodes => nodes.map(node => node.value).filter(Boolean)"
                )
                check(
                    "rendered_method_ids_equal_server_compatibility_response",
                    set(rendered_method_ids) == set(compatible_method_ids)
                    and len(rendered_method_ids) == len(compatible_method_ids),
                    {"rendered": rendered_method_ids, "server": compatible_method_ids},
                )
                page.locator("#sheetMethod").select_option(METHOD_ID)
                page.wait_for_function(
                    "document.querySelector('#sheetMethodRouteChoice option[value=\\\"route-personal-teacher\\\"]') !== null",
                    timeout=60_000,
                )
                page.locator("#sheetMethodRouteChoice").select_option("route-personal-teacher")
                page.locator("#sheetSubpath").select_option(required_subpaths)
                page.wait_for_function(
                    "expected => JSON.stringify([...document.querySelectorAll('#sheetSubpath option:checked')].map(node => node.value)) === JSON.stringify(expected)",
                    arg=required_subpaths,
                    timeout=60_000,
                )
                rendered_subpaths = page.locator("#sheetSubpath option").evaluate_all(
                    "nodes => nodes.map(node => node.value).filter(Boolean)"
                )
                allowed_subpaths = {
                    subpath_id
                    for path_id in path_ids
                    for subpath_id in path_index[path_id]
                }
                check(
                    "exact_path_owned_subpath_projection_rendered",
                    set(rendered_subpaths) == allowed_subpaths,
                    {"rendered_count": len(rendered_subpaths), "server_count": len(allowed_subpaths)},
                )
                selected_subpaths = page.locator("#sheetSubpath option:checked").evaluate_all(
                    "nodes => nodes.map(node => node.value)"
                )
                check(
                    "one_subpath_selected_per_path",
                    selected_subpaths == required_subpaths
                    and all(_owner_path(subpath_by_id[subpath_id]) == path_id for path_id, subpath_id in zip(path_ids, selected_subpaths)),
                     {"paths": path_ids, "subpaths": selected_subpaths},
                 )
                sphere_category = next(
                    row for row in options["categories"] if row["slot_id"] == "sphere_priorities"
                )
                sphere_priority = next(
                    row["choice_id"]
                    for row in sorted(sphere_category.get("choices") or [], key=lambda value: value["choice_id"])
                    if row.get("planning_priority_available") is not False
                )
                page.locator("#sheetSphereAdd").select_option(sphere_priority)
                page.locator('[data-add-slot="sphere_priorities"]').click()
                page.wait_for_function(
                    "sphereId => document.querySelector(`#sheetSphereList [data-sphere-id=\\\"${sphereId}\\\"]`) !== null || document.querySelector(`#sheetSphereCatalog [data-sphere-id=\\\"${sphereId}\\\"]`)?.classList.contains('selected')",
                    arg=sphere_priority,
                    timeout=60_000,
                )
                selected_spheres = page.evaluate(
                    "Array.from(document.querySelectorAll('#sheetSphereCatalog [data-sphere-id].selected, #sheetSphereList [data-sphere-id]')).map(node => node.dataset.sphereId)"
                )
                check(
                    "sphere_priority_selected_before_project_creation",
                    sphere_priority in selected_spheres,
                    {"selected_spheres": selected_spheres, "required_sphere": sphere_priority},
                )
                path_shot = screenshot_dir / "01-body-spirit-method-subpath-sphere.png"
                page.locator("#builderPaths").screenshot(path=str(path_shot))
                screenshots.append(path_shot.name)

                page.wait_for_function(
                    "!document.querySelector('#guidedBuildButton')?.disabled", timeout=60_000
                )
                page.locator("#guidedBuildButton").click()
                page.wait_for_function(
                    "guidedProjectId && guidedWizardStep === 3", timeout=120_000
                )
                project_id = page.evaluate("guidedProjectId")
                project_detail = page.evaluate(
                    "async projectId => await api(`/api/projects/${encodeURIComponent(projectId)}`)",
                    project_id,
                )
                locks = {
                    row["field"]: row["value"]
                    for row in project_detail["project"].get("user_locks", [])
                }
                locked_choices = locks["character_sheet.locked_choices"]
                check(
                    "browser_project_persists_exact_path_locks",
                    locked_choices["path_choice"] == path_ids,
                    {"actual": locked_choices["path_choice"], "expected": path_ids},
                )
                check(
                    "browser_project_persists_exact_subpath_locks",
                    locked_choices["subpath_choice"] == required_subpaths,
                    {"actual": locked_choices["subpath_choice"], "expected": required_subpaths},
                )
                details["project_id"] = project_id
                details["path_ids"] = path_ids
                details["subpath_ids"] = required_subpaths

                page.locator("#guidedStartBuild").click()
                page.wait_for_function(
                    "guidedRun?.status === 'WAITING_FOR_RESPONSE'", timeout=120_000
                )
                run_id = page.evaluate("guidedRun.run_id")
                request_zip = page.request.get(
                    f"{base_url}/api/character-creation/runs/{run_id}/complete-request.zip",
                    headers={"X-Foundry-Token": page.evaluate("token")},
                    timeout=180_000,
                )
                check("complete_request_zip_downloaded_through_browser_boundary", request_zip.status == 200, request_zip.status)
                with zipfile.ZipFile(io.BytesIO(request_zip.body())) as request_archive:
                    preferred_schema = json.loads(request_archive.read("RESPONSE_SCHEMA.json"))["preferred_response"]
                subpath_schema = preferred_schema["properties"]["selection_intent"]["properties"]["by_slot"]["properties"]["subpath_choice"]
                check(
                    "sealed_response_schema_allows_two_subpaths",
                    isinstance(subpath_schema.get("maxItems"), int) and subpath_schema["maxItems"] >= 2,
                    {"maxItems": subpath_schema.get("maxItems"), "minItems": subpath_schema.get("minItems")},
                )
                page.reload(wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_function(
                    "runId => guidedRun?.run_id === runId && guidedRun?.status === 'WAITING_FOR_RESPONSE'",
                    arg=run_id,
                    timeout=180_000,
                )
                check(
                    "reload_restores_active_run",
                    page.evaluate("guidedProjectId") == project_id,
                    {"project_id": project_id, "run_id": run_id},
                )
                page.wait_for_function("guidedWizardStep === 3", timeout=60_000)
                page.wait_for_timeout(5_000)
                page.locator('[data-owner-step="2"]').click()
                page.wait_for_function(
                    "guidedWizardStep === 2 && document.querySelector('#builderPaths')?.hidden === false",
                    timeout=120_000,
                )
                page.wait_for_function(
                    "payload => JSON.stringify([...document.querySelectorAll('#sheetPaths input:checked')].map(node => node.value)) === JSON.stringify(payload.paths) && JSON.stringify([...document.querySelectorAll('#sheetSubpath option:checked')].map(node => node.value)) === JSON.stringify(payload.subpaths)",
                    arg={"paths": path_ids, "subpaths": required_subpaths},
                    timeout=120_000,
                )
                check(
                    "reload_restores_exact_path_subpath_controls",
                    page.locator("#sheetPaths input:checked").evaluate_all("nodes => nodes.map(node => node.value)") == path_ids
                    and page.locator("#sheetSubpath option:checked").evaluate_all("nodes => nodes.map(node => node.value)") == required_subpaths,
                )

                page.locator('[data-owner-step="3"]').dispatch_event("click")
                page.once("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.accept()))
                page.locator("#guidedBack").dispatch_event("click")
                page.wait_for_function(
                    "guidedProjectId === null && guidedWizardStep === 1", timeout=120_000
                )
                cancelled_run = page.evaluate(
                    "async runId => await api(`/api/character-creation/runs/${encodeURIComponent(runId)}`)",
                    run_id,
                )
                check(
                    "start_over_cancels_active_run",
                    cancelled_run["status"] == "CANCELLED",
                    {"status": cancelled_run["status"]},
                )
                check(
                    "start_over_preserves_attempt_history",
                    any(
                        row.get("action_type") == "CANCEL_BUILD"
                        for row in cancelled_run.get("attempt_history", [])
                    ),
                    cancelled_run.get("attempt_history", []),
                )
                check("start_over_returns_to_brief", page.locator("#builderDescribe").is_visible())
                check("start_over_confirmation_was_shown", bool(dialogs), dialogs)
                first_project_after_start_over = page.evaluate(
                    "async projectId => await api(`/api/projects/${encodeURIComponent(projectId)}`)",
                    project_id,
                )
                first_lifecycle = first_project_after_start_over.get("builder_lifecycle") or {}
                check(
                    "discarded_first_project_retains_history_without_temporary_lifecycle",
                    first_lifecycle.get("is_temporary") is False
                    and first_lifecycle.get("persistence_state") in {"saved_draft", "legacy_persistent"}
                    and first_lifecycle.get("persistence_state") != "temporary",
                    first_lifecycle,
                )
                details["cancelled_run_id"] = run_id
                details["cancelled_run_status"] = cancelled_run["status"]
                details["first_project_lifecycle_after_start_over"] = {
                    key: first_lifecycle.get(key)
                    for key in ("persistence_state", "is_temporary", "display_label")
                }

                # Start a second genuinely new browser project and exercise
                # the persisted response-error/recovery lifecycle through the
                # rendered UI.  The first project above remains the explicit
                # Start Over/temporary-discard proof.
                page.fill("#guidedName", "REC1 P1CR4 Browser Recovery")
                page.fill("#guidedConcept", "Malformed response recovery through the owner surface.")
                page.fill("#guidedLevel", "3")
                page.locator("#guidedBriefContinue").click()
                page.wait_for_function("guidedWizardStep === 2", timeout=60_000)
                page.locator("#builderPaths").wait_for(state="visible", timeout=60_000)
                for path_id in path_ids:
                    page.locator(f'#sheetPaths input[value="{path_id}"]').check()
                page.wait_for_function("methodCompatibility.state === 'accepted'", timeout=120_000)
                page.locator("#sheetSubpath").select_option(required_subpaths)
                page.wait_for_function(
                    "expected => JSON.stringify([...document.querySelectorAll('#sheetSubpath option:checked')].map(node => node.value)) === JSON.stringify(expected)",
                    arg=required_subpaths,
                    timeout=60_000,
                )
                page.wait_for_function(
                    "!document.querySelector('#guidedBuildButton')?.disabled", timeout=60_000
                )
                page.locator("#guidedBuildButton").click()
                page.wait_for_function("guidedProjectId && guidedWizardStep === 3", timeout=120_000)
                recovery_project_id = page.evaluate("guidedProjectId")
                check(
                    "new_browser_project_has_new_identity",
                    recovery_project_id != project_id,
                    {"first_project_id": project_id, "new_project_id": recovery_project_id},
                )
                page.locator("#guidedStartBuild").click()
                page.wait_for_function("guidedRun?.status === 'WAITING_FOR_RESPONSE'", timeout=120_000)
                recovery_run_id = page.evaluate("guidedRun.run_id")
                recovery_request_sha = page.evaluate("guidedRun.request.request_sha256")

                malformed = b'{"schema":'
                page.locator("#guidedCompleteReplyFile").set_input_files({
                    "name": "malformed-browser.json",
                    "mimeType": "application/json",
                    "buffer": malformed,
                })
                page.wait_for_function(
                    "document.querySelector('#guidedResponseSourceState')?.textContent.includes('malformed-browser.json')",
                    timeout=30_000,
                )
                page.locator("#guidedSubmitCompleteResponse").click()
                page.wait_for_function("guidedRun?.status === 'NEEDS_REVIEW'", timeout=120_000)
                malformed_run = page.evaluate("guidedRun")
                malformed_error = malformed_run.get("submission_error") or ((malformed_run.get("validation") or {}).get("last_submission_error") if isinstance(malformed_run.get("validation"), dict) else {})
                check(
                    "browser_malformed_upload_persists_json_schema_diagnostic",
                    malformed_run.get("run_id") == recovery_run_id
                    and malformed_error.get("category") == "JSON_SCHEMA"
                    and isinstance((malformed_error.get("details") or {}).get("line"), int)
                    and isinstance((malformed_error.get("details") or {}).get("column"), int),
                    {"status": malformed_run.get("status"), "error": malformed_error},
                )
                check(
                    "browser_malformed_upload_records_attempt_history",
                    any(row.get("action_type") == "IMPORT_RESPONSE" and row.get("status") == "BLOCKED" for row in malformed_run.get("attempt_history", [])),
                    malformed_run.get("attempt_history", []),
                )
                page.reload(wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_function(
                    "runId => guidedRun?.run_id === runId && guidedRun?.status === 'NEEDS_REVIEW'",
                    arg=recovery_run_id,
                    timeout=180_000,
                )
                page.locator("#guidedDeveloperDiagnostics").evaluate("node => { node.open = true; return node.open; }")
                check(
                    "reload_restores_malformed_diagnostic",
                    "JSON_SCHEMA" in (page.locator("#guidedDiagnosticsDetail").text_content() or "")
                    and "malformed-browser.json" in (page.locator("#guidedCompleteReplyStatus").text_content() or "")
                    or "JSON_SCHEMA" in (page.locator("#guidedDiagnosticsDetail").text_content() or ""),
                    page.locator("#guidedDiagnosticsDetail").text_content(),
                )
                recovery_shot = screenshot_dir / "02-recovery-diagnostic-and-attempt-history.png"
                page.locator("#builderReview").screenshot(path=str(recovery_shot))
                screenshots.append(recovery_shot.name)

                page.locator('button[data-screen="projects"]').click()
                page.locator("#activeBuildRecovery").wait_for(state="visible", timeout=120_000)
                page.locator("#activeBuildRecovery").get_by_role("button", name="Inspect Build / Errors", exact=True).click()
                page.wait_for_function(
                    "runId => guidedRun?.run_id === runId && guidedRun?.status === 'NEEDS_REVIEW'",
                    arg=recovery_run_id,
                    timeout=120_000,
                )
                check(
                    "inspect_build_errors_restores_same_run",
                    page.evaluate("guidedRun.run_id") == recovery_run_id
                    and "JSON_SCHEMA" in (page.locator("#guidedDiagnosticsDetail").text_content() or ""),
                    page.locator("#guidedDiagnosticsDetail").text_content(),
                )

                prior_attempt_count = len(page.evaluate("guidedRun.attempt_history || []"))
                page.locator("#guidedRetryLocalBuild").click()
                page.wait_for_function(
                    "payload => guidedRun?.run_id === payload.runId && (guidedRun.attempt_history || []).length > payload.count",
                    arg={"runId": recovery_run_id, "count": prior_attempt_count},
                    timeout=120_000,
                )
                retried_run = page.evaluate("guidedRun")
                check(
                    "retry_local_build_preserves_request_and_history",
                    retried_run.get("status") == "NEEDS_REVIEW"
                    and retried_run.get("request", {}).get("request_sha256") == recovery_request_sha
                    and any(row.get("action_type") == "RETRY_LOCAL_BUILD" for row in retried_run.get("attempt_history", [])),
                    retried_run.get("attempt_history", []),
                )

                page.locator("#guidedReplaceResponse").click()
                page.wait_for_function("runId => guidedWizardStep === 3 && guidedRun?.run_id === runId", arg=recovery_run_id, timeout=60_000)
                replacement = b"{}"
                page.locator("#guidedCompleteReplyFile").set_input_files({
                    "name": "replacement-browser.json",
                    "mimeType": "application/json",
                    "buffer": replacement,
                })
                page.wait_for_function(
                    "document.querySelector('#guidedResponseSourceState')?.textContent.includes('replacement-browser.json')",
                    timeout=30_000,
                )
                check(
                    "replace_response_source_selected_in_ui",
                    page.evaluate("guidedResponseSubmissionAction") == "replace"
                    and not page.locator("#guidedSubmitCompleteResponse").is_disabled()
                    and "replacement-browser.json" in (page.locator("#guidedResponseSourceState").text_content() or ""),
                    {
                        "action": page.evaluate("guidedResponseSubmissionAction"),
                        "submit_disabled": page.locator("#guidedSubmitCompleteResponse").is_disabled(),
                        "source_state": page.locator("#guidedResponseSourceState").text_content(),
                    },
                )
                replacement_attempt_count = len(page.evaluate("guidedRun.attempt_history || []"))
                page.locator("#guidedSubmitCompleteResponse").click()
                page.wait_for_function(
                    "count => (guidedRun?.attempt_history || []).length > count",
                    arg=replacement_attempt_count,
                    timeout=120_000,
                )
                replaced_run = page.evaluate("guidedRun")
                replaced_server = page.evaluate(
                    "async runId => await api(`/api/character-creation/runs/${encodeURIComponent(runId)}`)",
                    recovery_run_id,
                )
                check(
                    "replace_response_preserves_run_identity_and_history",
                    replaced_run.get("run_id") == recovery_run_id
                    and any(row.get("action_type") == "REPLACE_RESPONSE" for row in replaced_server.get("attempt_history", [])),
                    {"ui_run": replaced_run, "server_run": replaced_server},
                )

                page.fill("#guidedRevisionNotes", "Create a genuinely new request after the malformed response.")
                page.locator("#guidedEditBrief").click()
                page.wait_for_function(
                    "runId => guidedRun?.run_id !== runId && guidedRun?.status === 'WAITING_FOR_RESPONSE'",
                    arg=recovery_run_id,
                    timeout=180_000,
                )
                new_request_run_id = page.evaluate("guidedRun.run_id")
                new_request_sha = page.evaluate("guidedRun.request.request_sha256")
                check(
                    "edit_brief_creates_genuinely_new_run",
                    new_request_run_id != recovery_run_id and new_request_sha != recovery_request_sha,
                    {"prior_run_id": recovery_run_id, "new_run_id": new_request_run_id, "prior_request_sha": recovery_request_sha, "new_request_sha": new_request_sha},
                )
                prior_run_after_revision = page.evaluate(
                    "async runId => await api(`/api/character-creation/runs/${encodeURIComponent(runId)}`)",
                    recovery_run_id,
                )
                check(
                    "prior_run_remains_recoverable_after_new_request",
                    prior_run_after_revision.get("run_id") == recovery_run_id
                    and bool(prior_run_after_revision.get("attempt_history")),
                    {"status": prior_run_after_revision.get("status"), "attempt_history_count": len(prior_run_after_revision.get("attempt_history", []))},
                )

                third_malformed = b'{"schema":'
                page.locator("#guidedCompleteReplyFile").set_input_files({
                    "name": "third-malformed-browser.json",
                    "mimeType": "application/json",
                    "buffer": third_malformed,
                })
                page.locator("#guidedSubmitCompleteResponse").click()
                page.wait_for_function("guidedRun?.status === 'NEEDS_REVIEW'", timeout=120_000)
                page.locator("#guidedCancel").dispatch_event("click")
                page.wait_for_function(
                    "runId => guidedRun?.run_id === runId && guidedRun?.status === 'CANCELLED'",
                    arg=new_request_run_id,
                    timeout=120_000,
                )
                cancelled_new_run = page.evaluate("guidedRun")
                check(
                    "explicit_cancel_build_preserves_attempt_history",
                    any(row.get("action_type") == "CANCEL_BUILD" for row in cancelled_new_run.get("attempt_history", [])),
                    cancelled_new_run.get("attempt_history", []),
                )
                page.locator('[data-owner-step="3"]').dispatch_event("click")
                page.locator("#guidedBack").dispatch_event("click")
                page.wait_for_function("guidedProjectId === null && guidedWizardStep === 1", timeout=120_000)
                check("start_new_after_cancel_returns_to_brief", page.locator("#builderDescribe").is_visible())
                second_project_after_start_over = page.evaluate(
                    "async projectId => await api(`/api/projects/${encodeURIComponent(projectId)}`)",
                    recovery_project_id,
                )
                second_lifecycle = second_project_after_start_over.get("builder_lifecycle") or {}
                check(
                    "discarded_recovery_project_retains_history_without_temporary_lifecycle",
                    second_lifecycle.get("is_temporary") is False
                    and second_lifecycle.get("persistence_state") in {"saved_draft", "legacy_persistent"}
                    and second_lifecycle.get("persistence_state") != "temporary",
                    second_lifecycle,
                )

                # A third, genuinely new project/run must remain usable after
                # the earlier cancelled/discarded projects and their retained
                # attempt histories.
                page.fill("#guidedName", "REC1 P1CR4 Browser Third Project")
                page.fill("#guidedConcept", "A new project remains usable after retained recovery history.")
                page.fill("#guidedLevel", "3")
                page.locator("#guidedBriefContinue").click()
                page.wait_for_function("guidedWizardStep === 2", timeout=60_000)
                page.locator("#builderPaths").wait_for(state="visible", timeout=60_000)
                for path_id in path_ids:
                    page.locator(f'#sheetPaths input[value="{path_id}"]').check()
                page.wait_for_function("methodCompatibility.state === 'accepted'", timeout=120_000)
                page.locator("#sheetSubpath").select_option(required_subpaths)
                page.wait_for_function(
                    "expected => JSON.stringify([...document.querySelectorAll('#sheetSubpath option:checked')].map(node => node.value)) === JSON.stringify(expected)",
                    arg=required_subpaths,
                    timeout=60_000,
                )
                page.wait_for_function(
                    "!document.querySelector('#guidedBuildButton')?.disabled", timeout=60_000
                )
                page.locator("#guidedBuildButton").click()
                page.wait_for_function("guidedProjectId && guidedWizardStep === 3", timeout=120_000)
                third_project_id = page.evaluate("guidedProjectId")
                check(
                    "third_browser_project_is_genuinely_new",
                    third_project_id not in {project_id, recovery_project_id},
                    {"first_project_id": project_id, "recovery_project_id": recovery_project_id, "third_project_id": third_project_id},
                )
                page.locator("#guidedStartBuild").click()
                page.wait_for_function("guidedRun?.status === 'WAITING_FOR_RESPONSE'", timeout=120_000)
                third_run_id = page.evaluate("guidedRun.run_id")
                third_request_sha = page.evaluate("guidedRun.request.request_sha256")
                check(
                    "third_browser_run_is_new_and_usable",
                    third_run_id not in {run_id, recovery_run_id, new_request_run_id}
                    and isinstance(third_request_sha, str)
                    and third_request_sha not in {recovery_request_sha, new_request_sha},
                    {"third_run_id": third_run_id, "third_request_sha": third_request_sha},
                )
                page.locator("#guidedCancel").dispatch_event("click")
                page.wait_for_function(
                    "runId => guidedRun?.run_id === runId && guidedRun?.status === 'CANCELLED'",
                    arg=third_run_id,
                    timeout=120_000,
                )
                third_cancelled = page.evaluate("guidedRun")
                check(
                    "third_project_cancel_preserves_attempt_history",
                    any(row.get("action_type") == "CANCEL_BUILD" for row in third_cancelled.get("attempt_history", [])),
                    third_cancelled.get("attempt_history", []),
                )
                page.locator('[data-owner-step="3"]').dispatch_event("click")
                page.locator("#guidedBack").dispatch_event("click")
                page.wait_for_function("guidedProjectId === null && guidedWizardStep === 1", timeout=120_000)
                check("final_start_over_returns_to_brief", page.locator("#builderDescribe").is_visible())
                third_project_after_start_over = page.evaluate(
                    "async projectId => await api(`/api/projects/${encodeURIComponent(projectId)}`)",
                    third_project_id,
                )
                third_lifecycle = third_project_after_start_over.get("builder_lifecycle") or {}
                check(
                    "third_project_history_is_retained_after_final_start_over",
                    third_lifecycle.get("is_temporary") is False
                    and third_lifecycle.get("persistence_state") in {"saved_draft", "legacy_persistent"},
                    third_lifecycle,
                )
                details["recovery_project_id"] = recovery_project_id
                details["recovery_run_id"] = recovery_run_id
                details["new_request_run_id"] = new_request_run_id
                details["new_request_sha"] = new_request_sha
                details["third_project_id"] = third_project_id
                details["third_run_id"] = third_run_id
                details["third_request_sha"] = third_request_sha
                instance.close()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        server.should_exit = True
        if server_thread.is_alive():
            server_thread.join(timeout=10)

    report = {
        "schema": "TianxiaFactory.REC1P1CR4BrowserAcceptance.v1",
        "status": "PASS" if error is None and all(checks.values()) and not page_errors and not console_errors and not failed_requests else "FAIL",
        "application_endpoints_mocked": False,
        "transport": "real FastAPI loopback HTTP; deterministic provider transport was not used by the manual build",
        "base_url": base_url,
        "checks": checks,
        "details": details,
        "dialogs": dialogs,
        "screenshots": screenshots,
        "page_errors": page_errors,
        "console_errors": console_errors,
        "failed_requests": failed_requests,
        "error": error,
    }
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if cleanup_data:
        shutil.rmtree(data, ignore_errors=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshot-dir", type=Path, required=True)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--cleanup-data", action="store_true")
    args = parser.parse_args()
    report = run(
        data=args.data.resolve(),
        output=args.output.resolve(),
        screenshot_dir=args.screenshot_dir.resolve(),
        browser=args.browser,
        cleanup_data=args.cleanup_data,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
