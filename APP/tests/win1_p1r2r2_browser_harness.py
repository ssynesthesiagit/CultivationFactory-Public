from __future__ import annotations

import argparse
import json
import platform
import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from ai_provider.secrets import InMemorySecretStore
from app.api import create_app
from app.core import Settings
from catalog.service import CatalogService
from vendor_adapter.service import FactoryAdapter


ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
FORBIDDEN_OWNER_TERMS = (
    "hard lock",
    "access tier",
    "route_type",
    "source_name",
    "source_reference",
    "stable id",
    "schema",
    "hash",
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def run(*, data: Path, output_root: Path, browser_path: str | None, cleanup_data: bool = False) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    screenshots = output_root / "screenshots"
    screenshots.mkdir(exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env(ROOT, data)
    app = create_app(
        settings,
        ai_transport=httpx.MockTransport(lambda _request: httpx.Response(500, json={"error": "provider not used"})),
        ai_secret_store=InMemorySecretStore("win1-p1r2r2-browser-only-secret"),
    )
    configured = FactoryAdapter(app.state.db).configure(FACTORY)
    CatalogService(app.state.db).rebuild_core(Path(configured["factory_root"]))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, name="win1-p1r2r2-browser", daemon=True)
    assertions: list[dict[str, Any]] = []
    console_log: list[dict[str, str]] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    network_log: list[dict[str, Any]] = []
    screenshot_names: list[str] = []
    browser_identity: dict[str, Any] = {}

    def check(name: str, condition: bool, detail: Any = None) -> None:
        row = {"name": name, "status": "PASS" if condition else "FAIL"}
        if detail is not None:
            row["detail"] = detail
        assertions.append(row)
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    status = "FAIL"
    error: str | None = None
    started = time.time()
    try:
        with TestClient(app):
            thread.start()
            for _ in range(300):
                if server.started:
                    break
                thread.join(0.05)
            check("real_loopback_server_started", server.started, base_url)
            with sync_playwright() as pw:
                executable = browser_path or pw.chromium.executable_path
                browser = pw.chromium.launch(
                    executable_path=executable,
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--no-proxy-server"],
                )
                page = browser.new_page(viewport={"width": 1600, "height": 1100})
                page.on("console", lambda message: console_log.append({"type": message.type, "text": message.text}))
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))
                page.on(
                    "response",
                    lambda response: network_log.append(
                        {"method": response.request.method, "url": response.url, "status": response.status}
                    ) if "/api/" in response.url else None,
                )
                page.goto(base_url, wait_until="domcontentloaded", timeout=120_000)
                page.wait_for_function(
                    "document.querySelector('#sheetOptionsStatus')?.textContent.includes('canonical Spheres')",
                    timeout=120_000,
                )
                page.locator("#builderModeDetailed").click()
                method_panel = page.locator(".method-planning-field")
                method_panel.scroll_into_view_if_needed()
                browser_identity = {
                    "engine": "Chromium",
                    "version": browser.version,
                    "executable": executable,
                    "user_agent": page.evaluate("navigator.userAgent"),
                    "platform": page.evaluate("navigator.platform"),
                    "runner": platform.platform(),
                }
                server_options = page.evaluate("async () => (await fetch('/api/character-builder/options')).json()")
                method_category = next(row for row in server_options["categories"] if row["slot_id"] == "method_choice")
                methods = method_category["choices"]
                path_category = next(row for row in server_options["categories"] if row["slot_id"] == "path_choice")
                selected_paths = ["tianxia.path.body_refining", "tianxia.path.spirit_awakening"]
                compatible_methods = [
                    row for row in methods
                    if set(selected_paths).issubset(row["related_choice_ids"])
                ]
                restricted = next(
                    row for row in compatible_methods
                    if not row["method_planning"]["direct_initial_acquisition_available"]
                    and row["method_planning"]["owner_route_options"]
                )
                unsupported_path = next(
                    row["choice_id"] for row in path_category["choices"]
                    if row["choice_id"] not in restricted["related_choice_ids"]
                )

                visible_labels = method_panel.locator("strong").all_text_contents()
                check("three_plain_method_choices_rendered", visible_labels == ["Choose for me", "I prefer this Method", "Use this Method"], visible_labels)
                check("choose_for_me_is_default", page.locator('input[name="sheetMethodMode"][value="AUTO"]').is_checked())
                check("method_choice_hidden_in_default", page.locator("#sheetMethodChoiceField").is_hidden())
                check("acquisition_question_absent_in_default", page.locator("#sheetMethodAccessPlan").is_hidden())
                visible_text = page.locator("#characterSheetPanel").inner_text().lower()
                exposed = [term for term in FORBIDDEN_OWNER_TERMS if term in visible_text]
                check("technical_authority_fields_not_visible", not exposed, exposed)
                default_shot = screenshots / "01-default-method-planning.png"
                page.screenshot(path=str(default_shot), full_page=True)
                screenshot_names.append(default_shot.name)

                rendered_path_choices = page.locator("#sheetPaths label").all_text_contents()
                source_path_choices = [row["name"] for row in path_category["choices"]]
                check("all_registry_paths_rendered", rendered_path_choices == source_path_choices, {"rendered": rendered_path_choices, "server": source_path_choices})
                for path_id in selected_paths:
                    page.locator(f'#sheetPaths input[value="{path_id}"]').check()
                page.locator('input[name="sheetMethodMode"][value="EXACT"]').check()
                rendered_methods = page.locator("#sheetMethod option").evaluate_all("nodes => nodes.map(node => node.value).filter(Boolean)")
                source_methods = [row["choice_id"] for row in compatible_methods]
                check(
                    "multi_path_method_filter_equals_server_projection",
                    rendered_methods == source_methods,
                    {"selected_paths": selected_paths, "rendered": rendered_methods, "server": source_methods},
                )
                page.locator("#sheetMethod").select_option(restricted["choice_id"])
                check("acquisition_question_appears_only_when_needed", page.locator("#sheetMethodAccessPlan").is_visible())
                check(
                    "acquisition_question_is_plain",
                    "How did this character learn this Method?" in page.locator("#sheetMethodAccessPlan").inner_text(),
                )
                rendered_routes = page.locator("#sheetMethodRouteChoice option").evaluate_all(
                    "nodes => nodes.slice(1).map(node => ({choice_id: node.value, label: node.textContent}))"
                )
                source_routes = [
                    {"choice_id": row["choice_id"], "label": row["label"]}
                    for row in restricted["method_planning"]["owner_route_options"]
                ]
                check("route_choices_equal_server_projection", rendered_routes == source_routes, {"rendered": rendered_routes, "server": source_routes})
                rendered_paths = page.locator("#sheetPaths input:checked").evaluate_all("nodes => nodes.map(node => node.value)")
                check("multi_path_selection_is_preserved", rendered_paths == selected_paths, {"rendered": rendered_paths, "selected": selected_paths})
                rendered_subpaths = page.locator("#sheetSubpath option").evaluate_all("nodes => nodes.map(node => node.value).filter(Boolean)")
                allowed_subpaths = set().union(*(set(server_options["path_subpath_index"].get(path_id, [])) for path_id in selected_paths))
                subpath_category = next(row for row in server_options["categories"] if row["slot_id"] == "subpath_choice")
                server_subpaths = [row["choice_id"] for row in subpath_category["choices"] if row["choice_id"] in allowed_subpaths]
                check(
                    "typed_path_subpath_projection_is_exact",
                    rendered_subpaths == server_subpaths,
                    {"rendered": rendered_subpaths, "server": server_subpaths},
                )
                if rendered_subpaths:
                    page.locator("#sheetSubpath").select_option(rendered_subpaths[0])
                page.locator("#sheetMethodRouteChoice").select_option(source_routes[0]["choice_id"])
                page.locator("#sheetMethodLearningNote").fill("Optional owner story only.")
                conditional_shot = screenshots / "02-restricted-method-question.png"
                page.screenshot(path=str(conditional_shot), full_page=True)
                screenshot_names.append(conditional_shot.name)

                page.locator(f'#sheetPaths input[value="{unsupported_path}"]').check()
                check("incompatible_path_change_clears_method", page.locator("#sheetMethod").input_value() == "")
                check("path_change_preserves_prior_paths", page.locator("#sheetPaths input:checked").count() == 3)
                check("path_change_clears_stale_route", page.locator("#sheetMethodRouteChoice").input_value() == "")
                check("path_change_clears_stale_note", page.locator("#sheetMethodLearningNote").input_value() == "")

                page.locator(f'#sheetPaths input[value="{unsupported_path}"]').uncheck()
                page.locator("#sheetMethod").select_option(restricted["choice_id"])
                page.locator("#sheetMethodLearningNote").fill("This prose must not grant access.")
                page.locator("#guidedName").fill("R2 Browser Proof")
                page.locator("#guidedConcept").fill("A deterministic owner-facing evidence character")
                project_posts_before = len([row for row in network_log if row["method"] == "POST" and row["url"].endswith("/api/character-builder/projects")])
                check("missing_route_disables_submission", page.locator("#guidedBuildButton").is_disabled())
                project_posts_after = len([row for row in network_log if row["method"] == "POST" and row["url"].endswith("/api/character-builder/projects")])
                check("annotation_cannot_authorize_missing_route", project_posts_after == project_posts_before)
                check(
                    "missing_route_fails_closed_in_plain_language",
                    "Choose the answer that fits this character" in page.locator("#sheetMethodAccessStatus").inner_text(),
                )

                page.locator("#sheetMethodRouteChoice").select_option(source_routes[0]["choice_id"])
                page.locator("#sheetMethodLearningNote").fill("Temporary story note")
                page.locator('input[name="sheetMethodMode"][value="PREFERENCE"]').check()
                check("mode_change_hides_acquisition_question", page.locator("#sheetMethodAccessPlan").is_hidden())
                check("mode_change_clears_route", page.locator("#sheetMethodRouteChoice").input_value() == "")
                check("mode_change_clears_note", page.locator("#sheetMethodLearningNote").input_value() == "")

                (output_root / "rendered-method-panel.html").write_text(method_panel.evaluate("node => node.outerHTML"), encoding="utf-8")
                (output_root / "accessibility-snapshot.txt").write_text(method_panel.aria_snapshot() + "\n", encoding="utf-8")
                browser.close()

            check("zero_page_errors", not page_errors, page_errors)
            console_errors = [row for row in console_log if row["type"] == "error"]
            check("zero_console_errors", not console_errors, console_errors)
            check("zero_failed_requests", not failed_requests, failed_requests)
            unexpected_http = [row for row in network_log if row["status"] >= 400]
            check("zero_unexpected_http_responses", not unexpected_http, unexpected_http)
            status = "PASS"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        server.should_exit = True
        if thread.is_alive():
            thread.join(timeout=10)
        write_json(output_root / "console-log.json", console_log)
        write_json(output_root / "page-errors.json", page_errors)
        write_json(output_root / "failed-requests.json", failed_requests)
        write_json(output_root / "network-log.json", network_log)
        if cleanup_data:
            shutil.rmtree(data, ignore_errors=True)

    report = {
        "schema": "Tianxia.WIN1P1R2R2.RenderedBrowserEvidence.v1",
        "status": status,
        "command": "python tests/win1_p1r2r2_browser_harness.py --data <isolated> --output-root <evidence>",
        "real_fastapi_loopback": True,
        "real_rendered_browser": True,
        "browser": browser_identity,
        "elapsed_seconds": round(time.time() - started, 3),
        "assertion_count": len(assertions),
        "passed_assertion_count": sum(row["status"] == "PASS" for row in assertions),
        "failed_assertion_count": sum(row["status"] == "FAIL" for row in assertions),
        "assertions": assertions,
        "screenshots": screenshot_names,
        "artifacts": {
            "rendered_dom": "rendered-method-panel.html",
            "accessibility_snapshot": "accessibility-snapshot.txt",
            "console_log": "console-log.json",
            "page_errors": "page-errors.json",
            "failed_requests": "failed-requests.json",
            "network_log": "network-log.json",
        },
        "error": error,
    }
    write_json(output_root / "browser-evidence.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--browser")
    parser.add_argument("--cleanup-data", action="store_true")
    args = parser.parse_args()
    report = run(data=args.data.resolve(), output_root=args.output_root.resolve(), browser_path=args.browser, cleanup_data=args.cleanup_data)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
