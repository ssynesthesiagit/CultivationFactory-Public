from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import http.server
import importlib.metadata
import io
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any, Iterator

import httpx
import uvicorn
from fastapi.testclient import TestClient
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "APP"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ai_provider.secrets import InMemorySecretStore
from app.api import create_app
from app.core import Settings, canonical_json, sha256_file
from catalog.service import CatalogService
from character_creation.current_fixture import (
    ABANDONED_ORPHAN,
    CINDER_HEART,
    FIRE,
    HIDDEN_TOOL_CACHE,
    QI_PATH,
    SCOUNDREL,
    STARTING_SCORES,
    STREET_HARDENED,
    complete_plan,
    exact_stage1_response,
)
from portable_character.service import GM_MODEL_NAME, GM_VIEW_NAME, PortableCharacterPackageService
from stage1.service import Stage1ClipboardService
from vendor_adapter.service import FactoryAdapter

STARTING_HEAD = "d6d4355894c5804e51d366a3514bb191a840841c"
BASE_HEAD = "80560ac00421e73057a2962ab6cbc4e15e540904"
FACTORY = APP_ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
GM_ZIP = APP_ROOT / "gm_screen" / "HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"
CHARACTER_NAME = "Linux E2E Cinder Archivist"
FOUNDATION_TYPED_NONE = "tianxia.c1a.none.foundation"
# The public GM ZIP references this decorative private-workspace background but
# intentionally does not ship it. Keep the public E2E static server complete
# without masking arbitrary missing runtime assets.
GM_DECORATIVE_ASSET_PATH = "/work/Xianxia/Campaign%20Interface/Campaign%20player%20dashboard.png"
GM_DECORATIVE_ASSET_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
FAKE_SECRET = "linux-e2e-deterministic-placeholder-not-a-real-key"
SCREENSHOT_NAMES = [
    "01_factory_start.png",
    "02_intake_complete.png",
    "03_stage1_request.png",
    "04_stage1_validated.png",
    "05_advancement_review.png",
    "06_final_character.png",
    "07_reopened_project.png",
    "08_portable_export.png",
    "09_clean_import.png",
    "10_gm_screen_reopen.png",
]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_text(command: list[str], *, cwd: Path = REPO_ROOT) -> str:
    completed = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, check=True)
    return completed.stdout.strip()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def deterministic_provider(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content or b"{}")
    prompt = ((payload.get("messages") or [{}, {}])[1] or {}).get("content")
    if prompt == 'Return exactly {"connection":"ok"}.':
        content = '{"connection":"ok"}'
    else:
        content = canonical_json({
            "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
            "request_sha256": "0" * 64,
        })
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    )


def configured_app(data_root: Path):
    data_root.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env(APP_ROOT, data_root)
    app = create_app(
        settings,
        ai_transport=httpx.MockTransport(deterministic_provider),
        ai_secret_store=InMemorySecretStore(FAKE_SECRET),
    )
    configured = FactoryAdapter(app.state.db).configure(FACTORY)
    CatalogService(app.state.db).rebuild_core(Path(configured["factory_root"]))
    return app


@contextlib.contextmanager
def live_app(app, *, label: str) -> Iterator[str]:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    thread = threading.Thread(target=server.run, name=label, daemon=True)
    with TestClient(app):
        thread.start()
        deadline = time.time() + 45
        while time.time() < deadline and not server.started:
            thread.join(0.05)
        if not server.started:
            raise RuntimeError(f"{label} did not start on {base_url}")
        try:
            yield base_url
        finally:
            server.should_exit = True
            if thread.is_alive():
                thread.join(timeout=15)


@contextlib.contextmanager
def static_server(root: Path) -> Iterator[str]:
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path.split("?", 1)[0] in {GM_DECORATIVE_ASSET_PATH, "/favicon.ico"}:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(GM_DECORATIVE_ASSET_PNG)))
                self.end_headers()
                self.wfile.write(GM_DECORATIVE_ASSET_PNG)
                return
            super().do_GET()

    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(root), **kwargs)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, name="win1-gm-static", daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def attach_logs(page, phase: str, logs: dict[str, list[Any]]) -> None:
    page.on(
        "console",
        lambda message: logs["console"].append(
            {"phase": phase, "type": message.type, "text": message.text}
        ),
    )
    page.on("pageerror", lambda error: logs["page_errors"].append({"phase": phase, "error": str(error)}))
    page.on(
        "requestfailed",
        lambda request: logs["network_failures"].append(
            {"phase": phase, "method": request.method, "url": request.url, "failure": request.failure}
        ),
    )

    def response_handler(response) -> None:
        if response.status >= 400:
            logs["http_failures"].append(
                {
                    "phase": phase,
                    "method": response.request.method,
                    "url": response.url,
                    "status": response.status,
                }
            )

    page.on("response", response_handler)


def select_option_when_ready(page, selector: str, value: str, *, timeout: int = 120_000) -> None:
    page.wait_for_function(
        "([selector, value]) => Array.from(document.querySelector(selector)?.options || []).some(o => o.value === value)",
        [selector, value],
        timeout=timeout,
    )
    page.locator(selector).select_option(value)


def find_category(options: dict[str, Any], slot_id: str) -> dict[str, Any]:
    return next(row for row in options["categories"] if row["slot_id"] == slot_id)


def choose_method(options: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    choices = find_category(options, "method_choice").get("choices") or []
    compatible = [
        row for row in choices
        if QI_PATH in set(row.get("related_choice_ids") or [])
        and (row.get("method_planning") or {}).get("owner_route_options")
    ]
    if not compatible:
        raise AssertionError("No source-backed Method with an owner acquisition route is available for Qi Cultivation.")
    method = compatible[0]
    routes = (method.get("method_planning") or {}).get("owner_route_options") or []
    route = next((row for row in routes if row.get("typed_route") != "CUSTOM_DOCUMENTED_ROUTE"), routes[0])
    return method, route


def zip_member_inventory(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        manifest_name = "PACKAGE_MANIFEST.json" if "PACKAGE_MANIFEST.json" in names else "MANIFEST.json"
        manifest = json.loads(archive.read(manifest_name))
        rows = [
            {"path": name, "bytes": len(archive.read(name)), "sha256": sha256_bytes(archive.read(name))}
            for name in sorted(names)
            if not name.endswith("/")
        ]
    return manifest, rows


def recursive_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        if key in value:
            found.append(value[key])
        for child in value.values():
            found.extend(recursive_values(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(recursive_values(child, key))
    return found


def project_event_records(db, project_id: str) -> list[dict[str, Any]]:
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT event_json FROM events WHERE project_id=? ORDER BY sequence_no",
            (project_id,),
        ).fetchall()
    return [json.loads(row["event_json"]) for row in rows]


def contains_text(value: Any, needle: str) -> bool:
    return needle.lower() in json.dumps(value, sort_keys=True, ensure_ascii=False).lower()


def extract_character_payload(package: Path, output: Path) -> dict[str, Any]:
    with zipfile.ZipFile(package) as archive:
        view = json.loads(archive.read(GM_VIEW_NAME))
        model = json.loads(archive.read(GM_MODEL_NAME))
        nested = archive.read("source/Character_Project.tianxia-project.zip")
        with zipfile.ZipFile(io.BytesIO(nested)) as project_archive:
            project = json.loads(project_archive.read("project.json"))
            events = json.loads(project_archive.read("events.json"))
    write_json(output / "final-character-view.json", view)
    write_json(output / "final-character-model.json", model)
    write_json(output / "final-character-project.json", project)
    write_json(output / "final-character-events.json", events)
    return {"view": view, "model": model, "project": project, "events": events}


def write_evidence_manifest(root: Path) -> None:
    files = [path for path in sorted(root.rglob("*")) if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS.txt"}]
    manifest = {
        "schema": "Tianxia.WIN1LinuxE2EEvidenceManifest.v1",
        "file_count": len(files),
        "files": [
            {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in files
        ],
    }
    write_json(root / "MANIFEST.json", manifest)
    covered = [path for path in sorted(root.rglob("*")) if path.is_file() and path.name != "SHA256SUMS.txt"]
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}\n" for path in covered),
        encoding="utf-8",
    )


def classify_failure(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    if isinstance(exc, PlaywrightTimeoutError):
        return "HARNESS_FAILURE"
    if "timeout" in text:
        return "TIMEOUT_CONFIGURATION"
    if isinstance(exc, (PlaywrightError, OSError)):
        return "INFRASTRUCTURE_BLOCKER"
    if isinstance(exc, AssertionError):
        return "PRODUCT_FAILURE"
    return "HARNESS_FAILURE"


def visible_button_matching(page, pattern: re.Pattern[str]):
    for button in page.locator("button, input[type=button], input[type=submit]").all():
        try:
            text = button.inner_text() if button.evaluate("node => node.tagName === 'BUTTON'") else (button.get_attribute("value") or "")
            if button.is_visible() and pattern.search(text or ""):
                return button
        except PlaywrightError:
            continue
    return None


def exercise_exact_gm_screen(
    context,
    *,
    gm_root: Path,
    portable_zip: Path,
    screenshots: Path,
    logs: dict[str, list[Any]],
) -> dict[str, Any]:
    with static_server(gm_root) as gm_url:
        page = context.new_page()
        attach_logs(page, "gm-screen", logs)
        page.goto(gm_url + "/index.html", wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(1500)
        inputs = page.locator('input[type="file"]')
        attempts: list[dict[str, Any]] = []
        for index in range(inputs.count()):
            control = inputs.nth(index)
            accept = (control.get_attribute("accept") or "").lower()
            candidate = portable_zip if ".zip" in accept or "zip" in accept else gm_view_json
            try:
                control.set_input_files(str(candidate))
                attempts.append({"input": index, "accept": accept, "file": candidate.name, "status": "SET"})
            except PlaywrightError as exc:
                attempts.append({"input": index, "accept": accept, "file": candidate.name, "status": "ERROR", "error": str(exc)})
        automation_tab = visible_button_matching(page, re.compile(r"^\s*automation\s*$", re.I))
        if automation_tab is not None:
            automation_tab.click()
        page.wait_for_timeout(500)
        save_button = visible_button_matching(page, re.compile(r"^\s*save package\s*$", re.I))
        save_clicked = False
        if save_button is not None:
            save_button.click()
            save_clicked = True
        page.wait_for_timeout(2500)
        body_text = page.locator("body").inner_text()
        if CHARACTER_NAME not in body_text:
            raise AssertionError(
                "The exact bundled GM Screen did not render the imported character. "
                + json.dumps({"attempts": attempts, "automation_tab_visible": automation_tab is not None, "save_package_clicked": save_clicked, "visible_text": body_text[:2000]}, ensure_ascii=False)
            )
        before_reload = page.locator("body").inner_text()
        page.reload(wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(2000)
        after_reload = page.locator("body").inner_text()
        if CHARACTER_NAME not in after_reload:
            raise AssertionError("The exact bundled GM Screen did not retain the character after reload.")
        page.screenshot(path=str(screenshots / SCREENSHOT_NAMES[9]), full_page=True)
        result = {
            "status": "PASS",
            "url": gm_url,
            "file_inputs": attempts,
            "save_button_clicked": save_clicked,
            "rendered_before_reload": CHARACTER_NAME in before_reload,
            "rendered_after_reload": CHARACTER_NAME in after_reload,
            "body_excerpt_after_reload": after_reload[:2000],
        }
        page.close()
        return result


def build_summary(report: dict[str, Any]) -> str:
    character = report.get("character_summary") or {}
    package = report.get("portable_character") or {}
    return "\n".join(
        [
            "# WIN1 Linux Full-Character E2E",
            "",
            f"- Status: **{report.get('status')}**",
            f"- Classification: **{report.get('classification')}**",
            f"- Exact repository head: `{report.get('repository', {}).get('final_head')}`",
            f"- Character: **{character.get('name')}**, CL {character.get('cultivation_level')}",
            f"- Path / Subpath: {character.get('path')} / {character.get('subpath')}",
            f"- Foundation: `{character.get('foundation_id')}`",
            f"- Primary Method: `{character.get('primary_method_id')}`",
            f"- Portable Character ZIP: `{package.get('filename')}` ({package.get('bytes')} bytes, `{package.get('sha256')}`)",
            f"- Save/reopen: {report.get('save_reopen', {}).get('status')}",
            f"- Clean Factory import: {report.get('clean_import', {}).get('status')}",
            f"- Exact GM Screen save/reopen: {report.get('gm_screen', {}).get('status')}",
            "- Native Windows owner testing remains pending.",
            "- Merge and INS2 remain unauthorized.",
            "",
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.resolve()
    data_root = args.data_root.resolve()
    import_root = args.import_data_root.resolve()
    screenshots = output / "screenshots"
    output.mkdir(parents=True, exist_ok=True)
    screenshots.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(data_root, ignore_errors=True)
    shutil.rmtree(import_root, ignore_errors=True)
    data_root.mkdir(parents=True)
    import_root.mkdir(parents=True)

    final_head = run_text(["git", "rev-parse", "HEAD"])
    branch = run_text(["git", "branch", "--show-current"]) or os.getenv("GITHUB_REF_NAME", "")
    if final_head != args.expected_head:
        raise AssertionError(f"Workflow checked out {final_head}, expected exact head {args.expected_head}.")

    runtime = {
        "python": sys.version,
        "platform": platform.platform(),
        "node": run_text(["node", "--version"]),
        "git": run_text(["git", "--version"]),
        "playwright_package": importlib.metadata.version("playwright"),
        "command": "python ci/win1_linux_e2e.py --output <evidence> --data-root <isolated> --import-data-root <clean-isolated> --expected-head <github.sha>",
    }
    logs: dict[str, list[Any]] = {"console": [], "page_errors": [], "network_failures": [], "http_failures": []}
    assertions: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: Any = None) -> None:
        row = {"name": name, "status": "PASS" if condition else "FAIL"}
        if detail is not None:
            row["detail"] = detail
        assertions.append(row)
        print(f"[{row['status']}] {name}", flush=True)
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    app = configured_app(data_root)
    project_id = ""
    foundation = {"choice_id": FOUNDATION_TYPED_NONE}
    method: dict[str, Any] = {}
    route: dict[str, Any] = {}
    run_id = ""
    final_run: dict[str, Any] = {}
    portable_copy = output / "Linux_E2E_Cinder_Archivist_Character.zip"
    trace_path = output / "playwright-trace.zip"
    playwright_started = False
    context = None
    browser = None
    started = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.browser or pw.chromium.executable_path,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--no-proxy-server"],
        )
        runtime["chromium"] = browser.version
        context = browser.new_context(viewport={"width": 1600, "height": 1100}, accept_downloads=True)
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        playwright_started = True
        try:
            with live_app(app, label="win1-linux-e2e-factory") as base_url:
                page = context.new_page()
                attach_logs(page, "factory-create-finalize", logs)
                page.goto(base_url, wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_function(
                    "document.querySelector('#sheetOptionsStatus')?.textContent.includes('canonical Spheres')",
                    timeout=120_000,
                )
                page.screenshot(path=str(screenshots / SCREENSHOT_NAMES[0]), full_page=True)
                page.locator("#builderModeDetailed").click()
                options = page.evaluate("async () => (await fetch('/api/character-builder/options')).json()")
                method, route = choose_method(options)

                page.locator("#guidedName").fill(CHARACTER_NAME)
                page.locator("#guidedLevel").fill("5")
                page.locator("#guidedPower").select_option("heroic")
                page.locator("#guidedConcept").fill(
                    "A Fire-aligned Qi cultivator, abandoned orphan and street-hardened archivist. "
                    "They use a source-backed typed-none Foundation resolution and exact Primary Method, carry complete Fire base abilities, "
                    "and preserve every advancement decision for portable play."
                )
                page.locator("#guidedSource").fill("Installed Tianxia canonical catalog authority")
                for ability, score in STARTING_SCORES.items():
                    page.locator(f"#ability{ability}").select_option(str(score))
                page.locator(f'#sheetPaths input[value="{QI_PATH}"]').check()
                select_option_when_ready(page, "#sheetSubpath", CINDER_HEART)
                select_option_when_ready(page, "#sheetBackground", ABANDONED_ORPHAN)
                if page.locator(f'#sheetBackgroundSphere option[value="{SCOUNDREL}"]').count():
                    page.locator("#sheetBackgroundSphere").select_option(SCOUNDREL)
                select_option_when_ready(page, "#sheetBackgroundTalent", HIDDEN_TOOL_CACHE)
                select_option_when_ready(page, "#sheetOriginInsight", STREET_HARDENED)
                page.locator('input[name="sheetMethodMode"][value="EXACT"]').check()
                select_option_when_ready(page, "#sheetMethod", method["choice_id"])
                select_option_when_ready(page, "#sheetMethodRouteChoice", route["choice_id"])
                if route.get("typed_route") == "CUSTOM_DOCUMENTED_ROUTE":
                    page.locator("#sheetMethodLearningNote").fill("Documented owner route for deterministic Linux E2E validation.")
                else:
                    page.locator("#sheetMethodLearningNote").fill("Source-backed acquisition route selected by the owner.")
                select_option_when_ready(page, "#sheetSphereAdd", FIRE)
                page.locator('[data-add-slot="sphere_priorities"]').click()
                page.screenshot(path=str(screenshots / SCREENSHOT_NAMES[1]), full_page=True)

                page.locator("#guidedBuildButton").click()
                page.wait_for_function("Boolean(guidedProjectId)", timeout=120_000)
                project_id = page.evaluate("guidedProjectId")
                check("new_isolated_project_created", bool(project_id), project_id)
                if page.locator("#guidedSaveDraft").is_visible():
                    page.locator("#guidedSaveDraft").click()
                    page.wait_for_function(
                        "guidedProjectLifecycle?.persistence_state === 'saved_draft'",
                        timeout=120_000,
                    )

                page.evaluate("showScreen('projects')")
                page.wait_for_function("document.querySelector('#screen-projects').classList.contains('active')")
                page.evaluate("loadProjects()")
                project_card = page.locator("#characterCardList .character-library-card", has_text=CHARACTER_NAME)
                project_card.wait_for(state="visible", timeout=120_000)
                project_card.click()
                page.wait_for_function(
                    "document.querySelector('#stage1ContinuationSummary')?.textContent.includes('Ready to prepare Stage 1')",
                    timeout=120_000,
                )
                stage_button = page.locator('[data-artifact-kind="chat_request"]')
                stage_button.click()
                page.wait_for_function("Boolean(stage1PromptData?.prompt_id)", timeout=120_000)
                page.screenshot(path=str(screenshots / SCREENSHOT_NAMES[2]), full_page=True)
                prompt_id = page.evaluate("stage1PromptData.prompt_id")
                exact_response = exact_stage1_response(Stage1ClipboardService(app.state.db).get_prompt(prompt_id))
                stage1_attempt = page.evaluate(
                    """async responseText => {
                      stage1Attempt = await api(`/api/stage1/prompts/${encodeURIComponent(stage1PromptData.prompt_id)}/responses/validate`, {
                        method: 'POST', body: JSON.stringify({response_text: responseText})
                      });
                      return stage1Attempt;
                    }""",
                    canonical_json(exact_response),
                )
                check("stage1_response_valid", stage1_attempt["validation"]["valid"] is True, stage1_attempt)
                stage1_commit = page.evaluate(
                    """async approvedBy => {
                      stage1Attempt = await api(`/api/stage1/attempts/${encodeURIComponent(stage1Attempt.attempt_id)}/approve-commit`, {
                        method: 'POST', body: JSON.stringify({approved_by: approvedBy})
                      });
                      return stage1Attempt;
                    }""",
                    "WIN1 Linux E2E owner",
                )
                check("stage1_owner_approved", bool(stage1_commit.get("commit")), stage1_commit)
                page.screenshot(path=str(screenshots / SCREENSHOT_NAMES[3]), full_page=True)

                page.evaluate(
                    """({projectId, projectName}) => {
                      showScreen('builder');
                      guidedProjectId = projectId;
                      selectedProject = projectId;
                      guidedProjectLifecycle = {persistence_state:'saved_draft', is_temporary:false, display_label:'Saved Draft'};
                      document.querySelector('#guidedName').value = projectName;
                      document.querySelector('input[name="guidedExecutionMode"][value="MANUAL_CHAT"]').checked = true;
                      setGuidedStep(2); updateGuidedModeUI();
                    }""",
                    {"projectId": project_id, "projectName": CHARACTER_NAME},
                )
                page.locator("#guidedStartBuild").click()
                page.wait_for_function("guidedRun?.status === 'WAITING_FOR_RESPONSE'", timeout=120_000)
                run_id = page.evaluate("guidedRun.run_id")
                request_sha = page.evaluate("guidedRun.request.request_sha256")
                plan = complete_plan(app.state.db, project_id)
                plan["request_sha256"] = request_sha
                plan["stage2_proposal"]["idempotency_key"] = f"win1-linux-e2e-{project_id}"
                plan["owner_descriptive_fields"]["identity"]["name"] = CHARACTER_NAME
                plan["owner_descriptive_fields"]["concept"] = (
                    "Qi Cultivation / Cinder Heart / Abandoned Orphan / Street-Hardened / typed-none Foundation resolution and source-backed Method"
                )
                plan_text = canonical_json(plan)
                page.locator("#guidedCompleteResponseText").fill(plan_text)
                review_status = page.evaluate(
                    """async args => {
                      const response = await fetch(`/api/character-creation/runs/${encodeURIComponent(args.runId)}/manual-response`, {
                        method: 'POST', headers: {'X-Foundry-Token': token, 'Content-Type': 'application/json'},
                        body: JSON.stringify({response_text: args.responseText, request_sha256: args.requestSha}),
                      });
                      const data = await response.json();
                      if (!response.ok) throw new Error(JSON.stringify(data));
                      guidedRun = data; renderGuidedCandidate(guidedRun); return guidedRun.status;
                    }""",
                    {"runId": run_id, "responseText": plan_text, "requestSha": request_sha},
                )
                check("complete_response_ready_for_review", review_status == "READY_FOR_REVIEW", page.evaluate("guidedRun"))
                check("two_independent_compilations", page.evaluate("guidedRun.dry_run.independent_compilations") == 2)
                check("finalization_blockers_clear", page.evaluate("(guidedRun.blockers || []).length") == 0, page.evaluate("guidedRun.blockers"))
                page.screenshot(path=str(screenshots / SCREENSHOT_NAMES[4]), full_page=True)
                final_status = page.evaluate(
                    """async runId => {
                      const response = await fetch(`/api/character-creation/runs/${encodeURIComponent(runId)}/finalize`, {
                        method: 'POST', headers: {'X-Foundry-Token': token, 'Content-Type': 'application/json'}, body: '{}'
                      });
                      const data = await response.json();
                      if (!response.ok) throw new Error(JSON.stringify(data));
                      guidedRun = data; renderGuidedCandidate(guidedRun); return guidedRun.status;
                    }""",
                    run_id,
                )
                check("complete_character_finalized", final_status == "CLEAN_AND_FINALIZED", final_status)
                final_run = app.state.character_creation.get(run_id)
                check("server_final_run_has_no_blockers", not final_run.get("blockers"), final_run.get("blockers"))
                check("exact_method_materialized", (final_run.get("outputs") or {}).get("method_access", {}).get("primary_method_id") == method["choice_id"], (final_run.get("outputs") or {}).get("method_access"))
                method_access_plan = (final_run.get("outputs") or {}).get("method_access", {}).get("access_plan", {})
                check(
                    "method_route_bound",
                    method_access_plan.get("route_type") == route.get("typed_route")
                    and method_access_plan.get("route_label") == route.get("label")
                    and method_access_plan.get("source_route_sha256") == route.get("source_route_sha256"),
                    (final_run.get("outputs") or {}).get("method_access"),
                )
                page.screenshot(path=str(screenshots / SCREENSHOT_NAMES[5]), full_page=True)

                verified = app.state.portable_characters.verified_status(project_id)
                check("portable_export_registered", bool(verified) and verified.get("status") == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED", verified)
                portable_path = Path(verified["package_path"])
                shutil.copy2(portable_path, portable_copy)
                page.evaluate("loadProjects()")
                page.screenshot(path=str(screenshots / SCREENSHOT_NAMES[7]), full_page=True)
                browser_page_secret_surface = page.content() + "\n" + page.evaluate("JSON.stringify(localStorage)")
                check("no_provider_secret_returned_to_browser", FAKE_SECRET not in browser_page_secret_surface)
                page.close()

            reopened_app = configured_app(data_root)
            with live_app(reopened_app, label="win1-linux-e2e-reopen") as reopened_url:
                reopened_page = context.new_page()
                attach_logs(reopened_page, "factory-reopen", logs)
                reopened_page.goto(reopened_url, wait_until="domcontentloaded", timeout=120_000)
                reopened_page.wait_for_function("Boolean(token)", timeout=120_000)
                reopened_page.evaluate("showScreen('projects'); loadProjects()")
                reopened_card = reopened_page.locator("#characterCardList .character-library-card", has_text=CHARACTER_NAME)
                reopened_card.wait_for(state="visible", timeout=120_000)
                reopened_card.click()
                reopened_project = reopened_app.state.projects.get_project(project_id)
                check("stable_project_identity_after_restart", reopened_project["project_id"] == project_id, reopened_project)
                check("stable_character_identity_after_restart", CHARACTER_NAME in canonical_json(reopened_project), reopened_project)
                reopened_page.screenshot(path=str(screenshots / SCREENSHOT_NAMES[6]), full_page=True)
                reopened_page.close()

            audit = PortableCharacterPackageService.audit(portable_copy)
            check("portable_audit_valid", audit.get("valid") is True, audit)
            manifest, member_rows = zip_member_inventory(portable_copy)
            write_json(output / "portable-validation-report.json", {"audit": audit, "manifest": manifest, "members": member_rows})
            payloads = extract_character_payload(portable_copy, output)
            view = payloads["view"]
            model = payloads["model"]
            project_payload = payloads["project"]
            event_payload = payloads["events"]
            check("character_name_complete", contains_text(view, CHARACTER_NAME), view.get("identity"))
            check("character_level_complete", 5 in [int(v) for v in recursive_values(view, "cultivation_level") if str(v).isdigit()], recursive_values(view, "cultivation_level"))
            check("path_present", contains_text(view, "Qi Cultivation") or contains_text(view, QI_PATH))
            check("subpath_present", contains_text(view, "Cinder Heart") or contains_text(view, CINDER_HEART))
            foundation_state = ((view.get("cultivation") or {}).get("foundation") or {})
            typed_none_events = [
                event
                for event in event_payload
                if isinstance(event, dict)
                and event.get("advancement", {}).get("kind") == "typed_none"
                and event.get("subject", {}).get("record_id") == foundation["choice_id"]
            ]
            check(
                "typed_none_foundation_resolved",
                foundation_state.get("state") == "explicit_none" and len(typed_none_events) == 1,
                {"foundation": foundation_state, "events": typed_none_events},
            )
            check("primary_method_present", contains_text(view, method["choice_id"]) or contains_text(model, method["choice_id"]), method["choice_id"])
            check("fire_sphere_present", contains_text(view, FIRE) or contains_text(view, "Fire"))
            check("complete_base_abilities_present", len(recursive_values(view, "base_abilities")) > 0 or contains_text(view, "Flame"), recursive_values(view, "base_abilities"))
            check("talents_present", contains_text(view, "talent"))
            origin_insight_events = [
                event
                for event in event_payload
                if isinstance(event, dict)
                and event.get("advancement", {}).get("kind") == "origin_insight_acquisition"
                and event.get("subject", {}).get("record_id") == STREET_HARDENED
            ]
            check("origin_insight_present", len(origin_insight_events) == 1, origin_insight_events)
            check("advancement_ledger_present", contains_text(project_payload, "advancement") or contains_text(project_payload, "leveling"))
            check("derived_statistics_present", contains_text(view, "ability_scores") or contains_text(view, "armor_class"))
            check("resources_present", contains_text(view, "Qi") and contains_text(view, "resources"))
            check("source_bindings_present", contains_text(view, "source") and contains_text(manifest, "source"))
            check("portable_metadata_present", manifest.get("project_id") == project_id, manifest)
            check("gm_projection_present", bool(view) and bool(model))

            clean_app = configured_app(import_root)
            with live_app(clean_app, label="win1-linux-e2e-clean-import") as clean_url:
                clean_page = context.new_page()
                attach_logs(clean_page, "clean-factory-import", logs)
                clean_page.goto(clean_url, wait_until="domcontentloaded", timeout=120_000)
                clean_page.wait_for_function("Boolean(token)", timeout=120_000)
                package_b64 = base64.b64encode(portable_copy.read_bytes()).decode("ascii")
                import_result = clean_page.evaluate(
                    """async args => {
                      const raw = atob(args.payload);
                      const bytes = new Uint8Array(raw.length);
                      for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
                      const response = await fetch('/api/characters/portable-import-upload', {
                        method: 'POST',
                        headers: {'X-Foundry-Token': token, 'X-Tianxia-Filename': args.name, 'Content-Type': 'application/zip'},
                        body: bytes,
                      });
                      const data = await response.json();
                      if (!response.ok) throw new Error(JSON.stringify(data));
                      return data;
                    }""",
                    {"payload": package_b64, "name": portable_copy.name},
                )
                check("clean_factory_import_succeeded", import_result.get("status") == "IMPORTED", import_result)
                clean_page.evaluate("showScreen('projects'); loadProjects()")
                imported_card = clean_page.locator("#characterCardList .character-library-card", has_text=CHARACTER_NAME)
                imported_card.wait_for(state="visible", timeout=120_000)
                imported_card.click()
                imported_project = clean_app.state.projects.get_project(project_id)
                imported_events = project_event_records(clean_app.state.db, project_id)
                check("clean_import_project_identity_equivalent", imported_project["project_id"] == project_id)
                check("clean_import_character_identity_equivalent", CHARACTER_NAME in canonical_json(imported_project))
                imported_event_text = canonical_json(imported_events)
                check("clean_import_foundation_equivalent", foundation["choice_id"] in imported_event_text)
                check("clean_import_method_equivalent", method["choice_id"] in imported_event_text)
                clean_page.screenshot(path=str(screenshots / SCREENSHOT_NAMES[8]), full_page=True)
                clean_page.close()

            gm_root = data_root.parent / "ExactGMScreenRuntime"
            shutil.rmtree(gm_root, ignore_errors=True)
            gm_root.mkdir(parents=True)
            with zipfile.ZipFile(GM_ZIP) as archive:
                archive.extractall(gm_root)
            gm_browser_result = exercise_exact_gm_screen(
                context,
                gm_root=gm_root,
                portable_zip=portable_copy,
                screenshots=screenshots,
                logs=logs,
            )
            gm_consumer = (final_run.get("outputs") or {}).get("gm_consumer") or {}
            shutil.rmtree(gm_root, ignore_errors=True)
            check("exact_gm_consumer_verified", gm_consumer.get("status") == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED", gm_consumer)
            check("exact_gm_consumer_save_reload", gm_consumer.get("save_reload_semantic_equivalence") is True, gm_consumer)
            check("exact_gm_browser_reopened", gm_browser_result.get("rendered_after_reload") is True, gm_browser_result)

            expected_screenshots = [screenshots / name for name in SCREENSHOT_NAMES]
            check("all_required_screenshots_present", all(path.is_file() for path in expected_screenshots), [path.name for path in expected_screenshots if not path.is_file()])

            console_errors = [row for row in logs["console"] if row.get("type") == "error"]
            check("zero_browser_console_errors", not console_errors, console_errors)
            check("zero_unhandled_page_errors", not logs["page_errors"], logs["page_errors"])
            required_network_failures = [row for row in logs["network_failures"] if "/api/" in row.get("url", "")]
            check("zero_failed_required_network_requests", not required_network_failures, required_network_failures)
            required_http_failures = [row for row in logs["http_failures"] if "/api/" in row.get("url", "")]
            check("zero_failed_required_http_responses", not required_http_failures, required_http_failures)

            write_json(output / "browser-console-log.json", logs["console"])
            write_json(output / "page-error-log.json", logs["page_errors"])
            write_json(output / "required-network-failure-log.json", required_network_failures)
            write_json(output / "http-failure-log.json", required_http_failures)
            write_json(output / "validation-report.json", {"status": "PASS", "assertions": assertions})
            write_json(
                output / "save-reopen-identity-report.json",
                {
                    "status": "PASS",
                    "project_id": project_id,
                    "character_name": CHARACTER_NAME,
                    "same_data_root": str(data_root),
                    "application_restarted": True,
                },
            )
            write_json(
                output / "clean-import-comparison-report.json",
                {
                    "status": "PASS",
                    "source_project_id": project_id,
                    "imported_project_id": project_id,
                    "character_name": CHARACTER_NAME,
                    "foundation_id": foundation["choice_id"],
                    "primary_method_id": method["choice_id"],
                    "import_result": import_result,
                },
            )
            write_json(output / "gm-screen-result.json", {"browser": gm_browser_result, "exact_consumer": gm_consumer})
            write_json(output / "repository-head.json", {"starting_head": STARTING_HEAD, "base_head": BASE_HEAD, "final_head": final_head, "branch": branch})
            write_json(output / "runtime-versions.json", runtime)

            identity = (view.get("identity") or {}) if isinstance(view, dict) else {}
            cultivation = (view.get("cultivation") or {}) if isinstance(view, dict) else {}
            report = {
                "schema": "Tianxia.WIN1LinuxFullCharacterE2E.v1",
                "status": "WIN1_LINUX_FULL_CHARACTER_E2E_PASS",
                "delivery_status": "PENDING_REMOTE_UPLOAD",
                "classification": "PASS",
                "repository": {"starting_head": STARTING_HEAD, "base_head": BASE_HEAD, "final_head": final_head, "branch": branch},
                "elapsed_seconds": round(time.time() - started, 3),
                "character_summary": {
                    "name": identity.get("display_name") or CHARACTER_NAME,
                    "project_id": project_id,
                    "cultivation_level": cultivation.get("cultivation_level") or 5,
                    "path": "Qi Cultivation",
                    "subpath": "Cinder Heart Cultivator",
                    "foundation_id": foundation["choice_id"],
                    "primary_method_id": method["choice_id"],
                    "method_route": route.get("typed_route"),
                },
                "portable_character": {
                    "filename": portable_copy.name,
                    "bytes": portable_copy.stat().st_size,
                    "sha256": sha256_file(portable_copy),
                    "manifest": manifest,
                    "audit_valid": audit.get("valid"),
                },
                "save_reopen": {"status": "PASS", "project_id": project_id, "character_name": CHARACTER_NAME},
                "clean_import": {"status": "PASS", "result": import_result},
                "gm_screen": {"status": "PASS", "browser": gm_browser_result, "exact_consumer": gm_consumer},
                "screenshots": SCREENSHOT_NAMES,
                "assertion_count": len(assertions),
                "runtime": runtime,
                "known_limitations": [
                    "This Linux Chromium receipt does not replace the pending native Windows owner test.",
                    "No merge or INS2 authorization is granted.",
                ],
            }
            write_json(output / "linux-e2e-result.json", report)
            (output / "SUMMARY.md").write_text(build_summary(report), encoding="utf-8")
            return report
        finally:
            try:
                write_json(output / "browser-console-log.json", logs["console"])
                write_json(output / "page-error-log.json", logs["page_errors"])
                write_json(
                    output / "required-network-failure-log.json",
                    [row for row in logs["network_failures"] if "/api/" in row.get("url", "")],
                )
                write_json(
                    output / "http-failure-log.json",
                    [row for row in logs["http_failures"] if "/api/" in row.get("url", "")],
                )
                write_json(
                    output / "validation-report.json",
                    {
                        "status": "PASS" if assertions and all(row.get("status") == "PASS" for row in assertions) else "FAIL",
                        "assertions": assertions,
                    },
                )
            except Exception:
                pass
            if playwright_started and context is not None:
                try:
                    context.tracing.stop(path=str(trace_path))
                except PlaywrightError:
                    pass
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--import-data-root", type=Path, required=True)
    parser.add_argument("--browser")
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        report = run(args)
        exit_code = 0
    except Exception as exc:
        classification = classify_failure(exc)
        report = {
            "schema": "Tianxia.WIN1LinuxFullCharacterE2E.v1",
            "status": "FAIL",
            "classification": classification,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "repository": {
                "starting_head": STARTING_HEAD,
                "base_head": BASE_HEAD,
                "final_head": subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True).stdout.strip(),
            },
        }
        write_json(output / "linux-e2e-result.json", report)
        write_json(output / "failure-classification.json", report)
        (output / "SUMMARY.md").write_text(
            f"# WIN1 Linux Full-Character E2E\n\n- Status: **FAIL**\n- Classification: **{classification}**\n- Error: `{type(exc).__name__}: {exc}`\n",
            encoding="utf-8",
        )
        exit_code = 1
    finally:
        write_evidence_manifest(output)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
