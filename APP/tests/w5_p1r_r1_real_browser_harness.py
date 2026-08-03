from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import uvicorn
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_provider.secrets import InMemorySecretStore
from app.api import create_app
from app.core import Settings, canonical_json
from catalog.service import CatalogService
from character_creation.current_fixture import W5_PROJECT_ID, W5_PROJECT_NAME, create_fresh_project
from vendor_adapter.service import FactoryAdapter

FACTORY = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
BINDING_CODE = "CG1_COMPLETE_RESPONSE_REQUEST_HASH_MISMATCH"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def provider_handler(behavior_file: Path, provider_log: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        provider_request = json.loads(request.content)
        if provider_request["messages"][1]["content"] == 'Return exactly {"connection":"ok"}.':
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"connection":"ok"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })
        behavior = behavior_file.read_text(encoding="utf-8").strip()
        with provider_log.open("a", encoding="utf-8") as stream:
            stream.write(f"{behavior}\n")
        if behavior == "failure":
            return httpx.Response(503, json={"error": "deterministic browser-provider outage"})
        content = canonical_json(
            {
                "schema": "TianxiaFoundry.CharacterCreationPlan.v2",
                "request_sha256": "0" * 64,
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    return handler


def serve_real_application(data_root: str, port: int, behavior_file: str, provider_log: str, include_fixture: bool) -> None:
    data_path = Path(data_root)
    settings = Settings.from_env(ROOT, data_path)
    app = create_app(
        settings,
        ai_transport=httpx.MockTransport(provider_handler(Path(behavior_file), Path(provider_log))),
        ai_secret_store=InMemorySecretStore("browser-deepseek-key-123"),
    )
    configured = FactoryAdapter(app.state.db).configure(FACTORY)
    CatalogService(app.state.db).rebuild_core(Path(configured["factory_root"]))
    if include_fixture:
        create_fresh_project(app.state.db, project_id=W5_PROJECT_ID)
    app.state.ai_provider.configure(
        enabled=True,
        model="deepseek-v4-flash",
        thinking_mode="disabled",
        max_output_tokens=8192,
        timeout_seconds=30,
        data_sharing_acknowledged=True,
        acknowledged_by="W5-P1R-R1 real browser acceptance",
    )
    app.state.ai_provider.test_connection()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def wait_server(url: str) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if httpx.get(url + "/api/session", timeout=3).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("The real production server did not become ready.")


def project_revision(url: str, project_id: str) -> int:
    response = httpx.get(f"{url}/api/projects/{project_id}", timeout=30)
    response.raise_for_status()
    return int(response.json()["project"]["revision"])



async def wait_dom(page, expression: str, *, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        try:
            if await page.evaluate(expression):
                return
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise TimeoutError(f"DOM condition did not become true: {expression}") from last_error
    raise TimeoutError(f"DOM condition did not become true: {expression}")

def production_document(api_base_url: str) -> str:
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    sphere_js = (ROOT / "static" / "sphere_talent_logic.js").read_text(encoding="utf-8")
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    fetch_bridge = f"""
<script id="w5-browser-environment-bridge">
(() => {{
  if (typeof crypto.randomUUID !== "function") {{
    let uuidCounter = 0;
    crypto.randomUUID = () => {{
      uuidCounter += 1;
      return `00000000-0000-4000-8000-${{String(uuidCounter).padStart(12, "0")}}`;
    }};
  }}
  const apiBaseUrl = {json.dumps(api_base_url)};
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init = undefined) => {{
    if (typeof input === "string") {{
      const target = input.startsWith("/") ? apiBaseUrl + input : input;
      return nativeFetch(target, init);
    }}
    if (input instanceof URL) {{
      const raw = input.toString();
      const target = raw.startsWith("/") ? apiBaseUrl + raw : raw;
      return nativeFetch(target, init);
    }}
    if (input instanceof Request) {{
      const parsed = new URL(input.url, window.location.href);
      const target = parsed.pathname.startsWith("/api/") ? apiBaseUrl + parsed.pathname + parsed.search : input.url;
      return nativeFetch(new Request(target, input), init);
    }}
    return nativeFetch(input, init);
  }};
}})();
</script>
"""
    html = html.replace(
        '<link rel="stylesheet" href="/static/styles.css?v=w5-p1r-primary-character-creation">',
        "<style>\n" + css + "\n</style>",
    )
    html = html.replace(
        '<script src="/static/sphere_talent_logic.js?v=w5-p1r-primary-character-creation"></script>',
        fetch_bridge + "\n<script>\n" + sphere_js + "\n</script>",
    )
    html = html.replace(
        '<script src="/static/app.js?v=w5-p1r-primary-character-creation"></script>',
        "<script>\n" + app_js + "\n</script>",
    )
    return html


def project_count(app) -> int:
    with app.state.db.connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS count FROM projects").fetchone()["count"])


def run_count(app) -> int:
    with app.state.db.connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS count FROM character_creation_runs").fetchone()["count"])


async def wait_backend(predicate, *, timeout: float = 120.0, label: str) -> Any:
    deadline = time.monotonic() + timeout
    last_value: Any = None
    while time.monotonic() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Backend condition did not become true: {label}; last={last_value!r}")


def completed_request_count(requests: list[str], method: str, path_fragment: str) -> int:
    prefix = method.upper() + " "
    return sum(1 for row in requests if row.startswith(prefix) and path_fragment in row)


async def wait_request_increments(
    requests: list[str],
    requirements: list[tuple[str, str, int]],
    *,
    timeout: float = 180.0,
    label: str,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(completed_request_count(requests, method, path) >= target for method, path, target in requirements):
            await asyncio.sleep(0.5)
            return
        await asyncio.sleep(0.1)
    observed = {f"{method} {path}": completed_request_count(requests, method, path) for method, path, _ in requirements}
    raise TimeoutError(f"Required browser API sequence did not complete: {label}; observed={observed!r}")


async def wait_bridge_quiet(
    state: dict[str, Any],
    *,
    after_completed: int,
    label: str,
    timeout: float = 180.0,
    quiet_seconds: float = 1.5,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (
            int(state["completed"]) > after_completed
            and int(state["inflight"]) == 0
            and time.monotonic() - float(state["last_activity"]) >= quiet_seconds
        ):
            return
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Browser API transport did not become quiet: {label}; state={state!r}")


async def fill_and_continue(page, url: str, bridge_requests: list[str], *, name: str) -> tuple[str, int]:
    baselines = {
        "packs": completed_request_count(bridge_requests, "GET", "/api/content-packs"),
        "create": completed_request_count(bridge_requests, "POST", "/api/character-builder/projects"),
        "projects": completed_request_count(bridge_requests, "GET", "/api/projects"),
        "characters": completed_request_count(bridge_requests, "GET", "/api/characters"),
    }
    await page.evaluate(
        """name => {
            document.querySelector('#guidedName').value = name;
            document.querySelector('#guidedLevel').value = '5';
            document.querySelector('#guidedConcept').value = 'A Fire-aligned qi cultivator used to verify the real W5-P1R-R1 owner workflow.';
            setTimeout(() => document.querySelector('#guidedCreate').requestSubmit(document.querySelector('#guidedBuildButton')), 0);
        }""",
        name,
    )
    await wait_request_increments(
        bridge_requests,
        [
            ("GET", "/api/content-packs", baselines["packs"] + 1),
            ("POST", "/api/character-builder/projects", baselines["create"] + 1),
            ("GET", "/api/projects", baselines["projects"] + 1),
            ("GET", "/api/characters", baselines["characters"] + 1),
        ],
        label=f"guided project creation for {name}",
    )
    print(f"browser: guided project network sequence complete for {name}", flush=True)
    state = await page.evaluate(
        """() => ({
            modeCount: document.querySelectorAll('input[name="guidedExecutionMode"]').length,
            manualVisible: Boolean(document.querySelector('input[name="guidedExecutionMode"][value="MANUAL_CHAT"]')?.offsetParent),
            standardVisible: Boolean(document.querySelector('input[name="guidedExecutionMode"][value="STANDARD_API"]')?.offsetParent),
            autoVisible: Boolean(document.querySelector('input[name="guidedExecutionMode"][value="AUTO_FINALIZE_WHEN_CLEAN"]')?.offsetParent),
            autoChecked: document.querySelector('#guidedAutoFinalizeConsent').checked,
            projectId: guidedProjectId,
            status: document.querySelector('#guidedStatus').textContent
        })"""
    )
    assert state["modeCount"] == 3, state
    assert state["manualVisible"] is True, state
    assert state["standardVisible"] is True, state
    assert state["autoVisible"] is True, state
    assert state["autoChecked"] is False, state
    print(f"browser: guided mode DOM state {state}", flush=True)
    project_id = state["projectId"]
    assert project_id, state
    print(f"browser: reading project revision for {project_id}", flush=True)
    revision = project_revision(url, project_id)
    print(f"browser: project revision is {revision}", flush=True)
    return project_id, revision


async def select_standard_and_start(
    page, bridge_requests: list[str], *, expected_status: str
) -> dict[str, Any]:
    before = completed_request_count(bridge_requests, "POST", "/character-creation/runs")
    state = await page.evaluate(
        """() => {
            const input = document.querySelector('input[name="guidedExecutionMode"][value="STANDARD_API"]');
            input.checked = true;
            input.dispatchEvent(new Event('change', {bubbles: true}));
            const button = document.querySelector('#guidedStartBuild');
            const snapshot = {
                disabled: button.disabled,
                projectId: guidedProjectId,
                mode: guidedExecutionMode(),
                handlerType: typeof startGuidedCompleteBuild,
                status: document.querySelector('#guidedStatus').textContent
            };
            window.__w5BuildState = {status: "pending", error: null};
            startGuidedCompleteBuild().then(
                () => { window.__w5BuildState.status = "resolved"; },
                error => { window.__w5BuildState = {status: "rejected", error: String(error?.stack || error)}; }
            );
            return snapshot;
        }"""
    )
    print(f"browser: dispatch Standard API build {state}", flush=True)
    await page.wait_for_timeout(1500)
    debug_state = await page.evaluate("() => ({build: window.__w5BuildState, status: document.querySelector('#guidedStatus').textContent, buttonDisabled: document.querySelector('#guidedStartBuild').disabled})")
    print(f"browser: Standard API build state after 1.5s {debug_state}", flush=True)
    await wait_request_increments(
        bridge_requests,
        [("POST", "/character-creation/runs", before + 1)],
        label=f"standard build reaching {expected_status}",
    )
    await wait_dom(page, f"guidedRun && guidedRun.status === {json.dumps(expected_status)}", timeout=240.0)
    run = await page.evaluate("guidedRun")
    assert run["status"] == expected_status, run
    return run


async def run_async(output: Path, screenshots: Path, data_root: Path, browser_path: str) -> dict[str, Any]:
    screenshots.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    surface_requests: list[str] = []
    provider_requests: list[str] = []
    screenshots_written: list[str] = []
    wrong_hash_run: dict[str, Any] = {}
    fallback_run: dict[str, Any] = {}

    async def open_page(browser, url: str, request_log: list[str]):
        page = await browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        def on_console(message) -> None:
            if message.type == "error":
                console_errors.append(message.text)
                print(f"browser console error: {message.text}", flush=True)

        page.on("console", on_console)
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"),
        )

        def on_response(response) -> None:
            parsed = urlsplit(response.url)
            if parsed.scheme in {"http", "https"} and parsed.netloc == urlsplit(url).netloc:
                row = f"{response.request.method} {parsed.path} -> {response.status}"
                request_log.append(row)
                print(f"browser network: {row}", flush=True)

        page.on("response", on_response)
        await page.set_content(production_document(url), wait_until="load", timeout=180000)
        await wait_request_increments(
            request_log,
            [
                ("GET", "/api/session", 1),
                ("GET", "/api/character-builder/options", 1),
                ("GET", "/api/catalog/records", 1),
                ("GET", "/api/ai-provider", 1),
                ("GET", "/api/content-packs", 1),
                ("GET", "/api/system/status", 1),
            ],
            label="initial owner frontend load",
        )
        initial_ready = await page.evaluate("token !== null && characterBuilderOptions !== null")
        assert initial_ready is True
        return page

    def start_server(phase_root: Path, *, include_fixture: bool) -> tuple[subprocess.Popen, str, Path, Path]:
        phase_root.mkdir(parents=True, exist_ok=True)
        behavior_file = phase_root / "provider_behavior.txt"
        provider_log = phase_root / "provider_calls.log"
        server_log = phase_root / "server.log"
        behavior_file.write_text("wrong_hash\n", encoding="utf-8")
        provider_log.write_text("", encoding="utf-8")
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        command = [
            sys.executable,
            str(ROOT / "tests" / "w5_p1r_r1_browser_server.py"),
            "--data-root",
            str(phase_root),
            "--port",
            str(port),
            "--behavior-file",
            str(behavior_file),
            "--provider-log",
            str(provider_log),
        ]
        if include_fixture:
            command.append("--include-fixture")
        with server_log.open("w", encoding="utf-8") as stream:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
            )
        try:
            wait_server(url)
        except Exception:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
            raise RuntimeError(server_log.read_text(encoding="utf-8"))
        return process, url, behavior_file, provider_log

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=browser_path,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-web-security"],
        )
        try:
            # Phase A: exact normal wizard against a real clean production app.
            print("browser: start normal-wizard surface phase", flush=True)
            surface_process, surface_url, _surface_behavior, surface_provider_log = start_server(
                data_root / "surface_phase", include_fixture=False
            )
            try:
                surface_page = await open_page(browser, surface_url, surface_requests)
                print("browser: exact production owner frontend loaded for normal wizard", flush=True)
                temporary_project, _temporary_revision = await fill_and_continue(
                    surface_page, surface_url, surface_requests, name="Browser Mode Surface Proof"
                )
                mode_state = await surface_page.evaluate(
                    """() => ({
                        modeCount: document.querySelectorAll('input[name="guidedExecutionMode"]').length,
                        autoChecked: document.querySelector('#guidedAutoFinalizeConsent').checked,
                        detailedOptional: !document.querySelector('#builderModeDetailed').hidden
                    })"""
                )
                assert mode_state == {"modeCount": 3, "autoChecked": False, "detailedOptional": True}
                mode_path = screenshots / "00_real_normal_wizard_three_modes.png"
                await surface_page.screenshot(path=str(mode_path), full_page=True)
                screenshots_written.append(mode_path.name)
                delete_before = completed_request_count(surface_requests, "DELETE", "/temporary")
                await surface_page.evaluate("setTimeout(() => document.querySelector('#guidedBack').click(), 0)")
                await wait_request_increments(
                    surface_requests,
                    [("DELETE", "/temporary", delete_before + 1)],
                    label="discard normal-wizard temporary project",
                )
                assert httpx.get(f"{surface_url}/api/projects/{temporary_project}", timeout=30).status_code == 404
                await surface_page.close()
                print("browser: normal wizard exposed three modes with Auto-Finalize off", flush=True)
            finally:
                if surface_process.poll() is None:
                    surface_process.terminate()
                    try:
                        surface_process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        surface_process.kill()
                        surface_process.wait(timeout=20)

            # Phase B: same exact frontend, real app, real provider service, accepted fixture.
            print("browser: start provider-pipeline phase", flush=True)
            provider_process, provider_url, behavior_file, provider_log = start_server(
                data_root / "provider_phase", include_fixture=True
            )
            try:
                page = await open_page(browser, provider_url, provider_requests)
                print("browser: exact production owner frontend loaded for provider pipeline", flush=True)
                await page.evaluate(
                    """({projectId, projectName}) => {
                        resetGuidedBuilder();
                        selectedProject = projectId;
                        guidedProjectId = projectId;
                        guidedProjectLifecycle = {
                            persistence_state: "saved_draft",
                            is_temporary: false,
                            display_label: "Saved Draft",
                            plain_explanation: "Retained current W5 production acceptance fixture."
                        };
                        document.querySelector('#guidedName').value = projectName;
                        document.querySelector('#guidedLevel').value = '5';
                        document.querySelector('#guidedConcept').value = 'Cinder Heart Cultivator; Abandoned Orphan; Street-Hardened.';
                        renderGuidedPersistence();
                        setGuidedStatus(`${projectName} is ready. Choose a complete-character build mode.`);
                        setGuidedStep(2);
                        updateGuidedModeUI();
                    }""",
                    {"projectId": W5_PROJECT_ID, "projectName": W5_PROJECT_NAME},
                )
                initial_revision = project_revision(provider_url, W5_PROJECT_ID)
                wrong_hash_run = await select_standard_and_start(page, provider_requests, expected_status="NEEDS_REVIEW")
                owner_error_visible = await page.evaluate(
                    "document.querySelector('#guidedReviewDetail')?.textContent.includes('CG1_COMPLETE_RESPONSE_REQUEST_HASH_MISMATCH')"
                )
                assert owner_error_visible is True
                assert wrong_hash_run["blockers"][0]["code"] == BINDING_CODE
                assert wrong_hash_run["dry_run"] == {}
                assert project_revision(provider_url, W5_PROJECT_ID) == initial_revision
                wrong_path = screenshots / "01_real_standard_wrong_hash_owner_error.png"
                await page.screenshot(path=str(wrong_path), full_page=True)
                screenshots_written.append(wrong_path.name)
                print("browser: wrong-hash provider response rendered as typed owner review", flush=True)

                cancel_before = completed_request_count(provider_requests, "POST", "/cancel")
                await page.evaluate("setTimeout(() => document.querySelector('#guidedCancel').click(), 0)")
                await wait_request_increments(
                    provider_requests,
                    [("POST", "/cancel", cancel_before + 1)],
                    label="cancel wrong-hash review without mutation",
                )
                await wait_dom(page, "guidedRun && guidedRun.status === 'CANCELLED'", timeout=60.0)

                behavior_file.write_text("failure\n", encoding="utf-8")
                fallback_run = await select_standard_and_start(page, provider_requests, expected_status="WAITING_FOR_RESPONSE")
                manual_visible = await page.evaluate("!document.querySelector('#guidedManualTransfer').hidden")
                assert manual_visible is True
                assert fallback_run["execution_mode"] == "MANUAL_CHAT"
                assert fallback_run["warnings"][0]["code"] == "CG1_PROVIDER_EXECUTION_FAILED_FALLBACK_MANUAL"
                assert fallback_run["transport"]["provider_called"] is True
                assert project_revision(provider_url, W5_PROJECT_ID) == initial_revision
                fallback_path = screenshots / "02_real_standard_provider_fallback_manual.png"
                await page.screenshot(path=str(fallback_path), full_page=True)
                screenshots_written.append(fallback_path.name)
                print("browser: provider failure returned visibly to Manual Chat", flush=True)
                await page.close()
            finally:
                if provider_process.poll() is None:
                    provider_process.terminate()
                    try:
                        provider_process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        provider_process.kill()
                        provider_process.wait(timeout=20)
        finally:
            await browser.close()

    report = {
        "schema": "TianxiaFoundry.W5P1RR1RealBrowserAcceptance.v1",
        "status": "PASS",
        "application_endpoints_mocked": False,
        "frontend": {
            "html": "exact production static/index.html",
            "css": "exact production static/styles.css embedded unchanged",
            "javascript": [
                "exact production static/sphere_talent_logic.js embedded unchanged",
                "exact production static/app.js embedded unchanged",
            ],
        },
        "browser_environment_bridge": {
            "used": True,
            "reason": "Container Chromium blocks direct loopback navigation. A narrow URL-rebasing shim sends the production frontend's native browser fetches directly to live loopback FastAPI servers. Chromium is launched with web-security disabled because the required about:blank shell has an opaque origin; no application endpoint or response is mocked.",
            "crypto_random_uuid_shim": "Deterministic implementation of the standard secure-context primitive omitted by the required about:blank shell.",
            "surface_phase_requests": surface_requests,
            "provider_phase_requests": provider_requests,
        },
        "backend": "production app.api.create_app on live loopback Uvicorn servers",
        "provider_service": "production AIProviderService",
        "provider_pipeline_project": {"project_id": W5_PROJECT_ID, "name": W5_PROJECT_NAME},
        "external_provider_transport": "deterministic httpx.MockTransport only",
        "provider_calls": len(provider_log.read_text(encoding="utf-8").splitlines()),
        "surface_provider_calls": len(surface_provider_log.read_text(encoding="utf-8").splitlines()),
        "three_modes_visible": True,
        "auto_finalize_default_off": True,
        "standard_wrong_hash": {
            "status": wrong_hash_run["status"],
            "diagnostic": wrong_hash_run["blockers"][0],
            "scratch_compilations": wrong_hash_run["dry_run"].get("independent_compilations", 0),
            "canonical_mutation": False,
        },
        "provider_failure_fallback": {
            "execution_mode": fallback_run["execution_mode"],
            "status": fallback_run["status"],
            "warning": fallback_run["warnings"][0],
            "provider_called": fallback_run["transport"]["provider_called"],
            "canonical_mutation": False,
        },
        "screenshots": screenshots_written,
        "page_errors": page_errors,
        "console_errors": console_errors,
        "failed_requests": failed_requests,
    }
    if page_errors or console_errors or failed_requests:
        raise RuntimeError(canonical_json(report))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def run(output: Path, screenshots: Path, data_root: Path, browser_path: str) -> dict[str, Any]:
    return asyncio.run(run_async(output, screenshots, data_root, browser_path))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    args = parser.parse_args()
    report = run(args.output, args.screenshots, args.data_root, args.browser)
    print(
        canonical_json(
            {
                "status": report["status"],
                "screenshots": report["screenshots"],
                "provider_calls": report["provider_calls"],
            }
        )
    )


if __name__ == "__main__":
    main()
